#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import plistlib
import re
import subprocess
import time
from pathlib import Path
from typing import Any


def main() -> int:
    parser = argparse.ArgumentParser(description="Check the installed Memory Book maintenance runtime.")
    parser.add_argument(
        "--app-root",
        default=str(
            Path.home()
            / "Library/Application Support/RagIme/components/memory-book-maintenance"
        ),
    )
    parser.add_argument(
        "--plist-path",
        default=str(Path.home() / "Library/LaunchAgents/com.rag-ime.memory-book-maintenance.plist"),
    )
    parser.add_argument(
        "--runs-dir",
        default=str(Path.home() / "Library/Application Support/RagIme/memory-book-runs"),
    )
    parser.add_argument(
        "--db-path",
        default=str(Path.home() / "Library/Application Support/RagIme/rag-ime.sqlite"),
    )
    parser.add_argument("--label", default="com.rag-ime.memory-book-maintenance")
    parser.add_argument("--max-age-hours", type=float, default=48.0)
    parser.add_argument("--require-run", action="store_true")
    parser.add_argument("--require-loaded", action="store_true")
    parser.add_argument("--report-path", default="")
    args = parser.parse_args()

    app_root = Path(args.app_root).expanduser().resolve()
    plist_path = Path(args.plist_path).expanduser()
    runs_dir = Path(args.runs_dir).expanduser()
    db_path = Path(args.db_path).expanduser()
    errors: list[str] = []
    warnings: list[str] = []

    plist = _load_plist(plist_path)
    if plist is None:
        errors.append(f"LaunchAgent plist missing or invalid: {plist_path}")
        plist = {}
    program_args = [str(item) for item in plist.get("ProgramArguments", [])]
    wrapper = app_root / "memory_book_maintenance_launch.py"
    runner = app_root / "scripts/run_memory_book_maintenance_once.sh"
    package = app_root / "rag_ime/cli.py"
    marker = app_root / "rag-ime-install-marker.json"
    for required in (wrapper, runner, package, marker):
        if not required.is_file():
            errors.append(f"installed runtime artifact missing: {required}")
    resolved_program_paths = {
        str(Path(item).expanduser().resolve())
        for item in program_args
        if item.startswith("/")
    }
    if not program_args or str(wrapper) not in resolved_program_paths:
        errors.append("LaunchAgent does not execute the app-local maintenance wrapper")
    working_directory = str(plist.get("WorkingDirectory") or "")
    resolved_working_directory = str(Path(working_directory).expanduser().resolve()) if working_directory else ""
    if resolved_working_directory != str(app_root):
        errors.append(f"WorkingDirectory={working_directory!r}, expected {str(app_root)!r}")

    marker_payload = _load_json(marker)
    if marker_payload is None:
        errors.append("installed code marker is missing or invalid")
    elif not str(marker_payload.get("sourceCommit") or ""):
        errors.append("installed code marker has no sourceCommit")

    db_parent = db_path.parent
    db_writable = os.access(db_path, os.W_OK) if db_path.exists() else db_parent.is_dir() and os.access(db_parent, os.W_OK)
    if not db_writable:
        errors.append(f"Memory Book DB is not writable: {db_path}")

    latest = _latest_run(runs_dir)
    if latest is None:
        message = f"no Memory Book plan/validate output found in {runs_dir}"
        (errors if args.require_run else warnings).append(message)
    else:
        if not latest["validationOk"]:
            errors.append(f"latest Memory Book validation failed: {latest['validatePath']}")
        if latest["ageHours"] > max(0.0, args.max_age_hours):
            message = f"latest successful validation is stale: {latest['ageHours']:.1f}h"
            (errors if args.require_run else warnings).append(message)

    launchd = _launchd_status(args.label)
    if not launchd["loaded"]:
        message = f"LaunchAgent is not loaded: {args.label}"
        (errors if args.require_loaded else warnings).append(message)
    elif launchd["lastExitCode"] not in (None, 0):
        errors.append(f"LaunchAgent last exit code is {launchd['lastExitCode']}")

    report: dict[str, Any] = {
        "schemaVersion": "rag-ime.memory-book-maintenance-doctor.v1",
        "ok": not errors,
        "appRoot": str(app_root),
        "plistPath": str(plist_path),
        "dbPath": str(db_path),
        "dbWritable": db_writable,
        "installMarker": marker_payload or {},
        "latestRun": latest or {},
        "launchd": launchd,
        "errors": errors,
        "warnings": warnings,
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.report_path:
        report_path = Path(args.report_path).expanduser()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report["ok"] else 1


def _load_plist(path: Path) -> dict[str, Any] | None:
    try:
        payload = plistlib.loads(path.read_bytes())
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _latest_run(runs_dir: Path) -> dict[str, Any] | None:
    validations = sorted(runs_dir.glob("memory-book-*.validate.json"), key=lambda item: item.stat().st_mtime)
    if not validations:
        return None
    validate_path = validations[-1]
    stem = validate_path.name.removesuffix(".validate.json")
    plan_path = runs_dir / f"{stem}.json"
    preview_path = runs_dir / f"{stem}.preview.json"
    validate = _load_json(validate_path) or {}
    age_hours = max(0.0, (time.time() - validate_path.stat().st_mtime) / 3600.0)
    return {
        "planPath": str(plan_path),
        "previewPath": str(preview_path),
        "validatePath": str(validate_path),
        "planExists": plan_path.is_file(),
        "previewExists": preview_path.is_file(),
        "validationOk": bool(validate.get("ok")) and plan_path.is_file() and preview_path.is_file(),
        "ageHours": round(age_hours, 3),
    }


def _launchd_status(label: str) -> dict[str, Any]:
    try:
        result = subprocess.run(
            ["launchctl", "print", f"gui/{os.getuid()}/{label}"],
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError:
        return {"loaded": False, "lastExitCode": None, "state": "launchctl_unavailable"}
    if result.returncode != 0:
        return {"loaded": False, "lastExitCode": None, "state": "not_loaded"}
    exit_match = re.search(r"last exit code\s*=\s*(-?\d+)", result.stdout)
    state_match = re.search(r"\bstate\s*=\s*([^\n]+)", result.stdout)
    return {
        "loaded": True,
        "lastExitCode": int(exit_match.group(1)) if exit_match else None,
        "state": state_match.group(1).strip() if state_match else "unknown",
    }


if __name__ == "__main__":
    raise SystemExit(main())
