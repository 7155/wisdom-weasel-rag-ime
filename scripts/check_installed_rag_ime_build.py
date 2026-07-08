#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_APP = Path.home() / "Library" / "Input Methods" / "Squirrel.app"
DEFAULT_INPUT_SOURCE_ID = "im.rime.inputmethod.Squirrel.Hans"
DEFAULT_BUNDLE_ID = "im.rime.inputmethod.Squirrel"


def sha256_file(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except FileNotFoundError:
        return None


def load_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except json.JSONDecodeError as exc:
        return {"_decodeError": str(exc)}


def run_text(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True)


def input_source_report(input_source_id: str, check_script: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="rag-ime-build-check-") as tmp:
        report_path = Path(tmp) / "input-source.json"
        result = run_text(
            [
                "bash",
                str(check_script),
                "--require-selected",
                "--require-hitoolbox-enabled",
                "--report-path",
                str(report_path),
                input_source_id,
            ]
        )
        report = load_json(report_path) or {}
        report["commandExitCode"] = result.returncode
        if result.stdout:
            report["stdoutTail"] = result.stdout[-2000:]
        if result.stderr:
            report["stderrTail"] = result.stderr[-2000:]
        return report


def running_processes(app_path: Path) -> list[dict[str, str]]:
    executable = app_path / "Contents" / "MacOS" / "Squirrel"
    pgrep = run_text(["pgrep", "-f", str(executable)])
    if pgrep.returncode != 0:
        return []
    pids = [pid.strip() for pid in pgrep.stdout.splitlines() if pid.strip()]
    processes: list[dict[str, str]] = []
    for pid in pids:
        ps = run_text(["ps", "-p", pid, "-o", "pid=", "-o", "lstart=", "-o", "command="])
        if ps.returncode != 0:
            continue
        processes.append({"pid": pid, "ps": ps.stdout.strip()})
    return processes


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    root = args.repo_root.resolve()
    app_path = args.app.expanduser().resolve()
    marker_path = app_path / "Contents" / "Resources" / "rag-ime-build-marker.json"
    patch_path = root / "squirrel-patches" / "0001-add-rag-ime-sidecar.patch"
    marker = load_json(marker_path)
    current_patch_sha = sha256_file(patch_path)
    marker_patch_sha = marker.get("patchSha256") if isinstance(marker, dict) else None
    marker_bundle_id = marker.get("bundleId") if isinstance(marker, dict) else None
    marker_input_source_id = marker.get("inputSourceId") if isinstance(marker, dict) else None
    installed_latest = (
        isinstance(marker, dict)
        and marker.get("schemaVersion") == "rag-ime.squirrel-build-marker.v1"
        and marker_patch_sha is not None
        and current_patch_sha is not None
        and marker_patch_sha == current_patch_sha
        and marker_bundle_id == args.bundle_id
        and marker_input_source_id == args.input_source_id
    )
    input_report = input_source_report(args.input_source_id, args.check_script) if args.check_input_source else None
    selected = None
    hitoolbox_enabled = None
    third_party_enabled = None
    if isinstance(input_report, dict):
        source = input_report.get("source")
        if isinstance(source, dict):
            selected = source.get("selected")
            hitoolbox_enabled = source.get("hitoolboxEnabled")
            third_party_enabled = source.get("thirdPartyEnabled")
    processes = running_processes(app_path) if args.check_process else []
    ok = installed_latest and selected is not False and hitoolbox_enabled is not False and third_party_enabled is not False
    return {
        "schemaVersion": "rag-ime.installed-build-check.v1",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "ok": bool(ok),
        "repoRoot": str(root),
        "appPath": str(app_path),
        "markerPath": str(marker_path),
        "markerPresent": marker is not None,
        "installedLatest": installed_latest,
        "currentPatchSha256": current_patch_sha,
        "markerPatchSha256": marker_patch_sha,
        "bundleIdExpected": args.bundle_id,
        "bundleIdInstalled": marker_bundle_id,
        "inputSourceIdExpected": args.input_source_id,
        "inputSourceIdInstalled": marker_input_source_id,
        "selected": selected,
        "hitoolboxEnabled": hitoolbox_enabled,
        "thirdPartyEnabled": third_party_enabled,
        "inputSource": input_report,
        "runningPids": processes,
        "runningProcessCount": len(processes),
        "marker": marker,
        "notes": [
            "installedLatest proves the installed app marker matches the current Squirrel patch file.",
            "A running process can still be old until macOS restarts or reselects the input method.",
            "If installedLatest=true but candidates look old, quit/reselect Squirrel and run this checker again.",
        ],
    }


def main() -> int:
    root_default = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Check whether the installed patched Squirrel app matches this checkout.")
    parser.add_argument("--repo-root", type=Path, default=root_default)
    parser.add_argument("--app", type=Path, default=Path(os.environ.get("RAG_IME_SQUIRREL_APP", DEFAULT_APP)))
    parser.add_argument("--input-source-id", default=os.environ.get("RAG_IME_SQUIRREL_INPUT_SOURCE_ID", DEFAULT_INPUT_SOURCE_ID))
    parser.add_argument("--bundle-id", default=os.environ.get("RAG_IME_SQUIRREL_BUNDLE_ID", DEFAULT_BUNDLE_ID))
    parser.add_argument("--check-script", type=Path, default=root_default / "scripts" / "check_macos_input_source.sh")
    parser.add_argument("--no-input-source", action="store_false", dest="check_input_source")
    parser.add_argument("--no-process", action="store_false", dest="check_process")
    parser.add_argument("--report-path", type=Path)
    parser.add_argument("--require-latest", action="store_true")
    args = parser.parse_args()

    report = build_report(args)
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.report_path:
        args.report_path.expanduser().write_text(text, encoding="utf-8")
    print(text, end="")
    if args.require_latest and not report["ok"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
