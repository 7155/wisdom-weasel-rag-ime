#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import plistlib
import re
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


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
    parser.add_argument("--gateway-url", default="")
    parser.add_argument("--report-path", default="")
    args = parser.parse_args()

    app_root = Path(args.app_root).expanduser().resolve()
    plist_path = Path(args.plist_path).expanduser()
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
    for required in (wrapper, marker):
        if not required.is_file():
            errors.append(f"installed runtime artifact missing: {required}")
    for obsolete in (runner, package):
        if obsolete.exists():
            errors.append(
                f"obsolete database/runtime payload must be removed: {obsolete}"
            )
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
    elif marker_payload.get("component") != "memory-maintenance-trigger":
        errors.append("installed marker still describes the retired maintenance runtime")

    environment = plist.get("EnvironmentVariables")
    environment = environment if isinstance(environment, dict) else {}
    gateway_url = str(
        args.gateway_url
        or environment.get("RAG_IME_AGENT_GATEWAY_URL")
        or ""
    ).strip()
    if not _is_loopback_origin(gateway_url):
        errors.append("maintenance trigger has no valid loopback Agent Gateway origin")
    forbidden_environment = sorted(
        key
        for key in environment
        if key == "RAG_IME_DB_PATH"
        or "DEEPSEEK" in key
        or key in {"RAG_IME_MODEL_ENV", "RAG_IME_ROOT"}
    )
    if forbidden_environment:
        errors.append(
            "maintenance trigger still owns database/model runtime settings: "
            + ", ".join(forbidden_environment)
        )
    if args.require_run:
        warnings.append(
            "--require-run is retired; curation receipts are owned by the Gateway database"
        )

    launchd = _launchd_status(args.label)
    if not launchd["loaded"]:
        message = f"LaunchAgent is not loaded: {args.label}"
        (errors if args.require_loaded else warnings).append(message)
    elif launchd["lastExitCode"] not in (None, 0):
        errors.append(f"LaunchAgent last exit code is {launchd['lastExitCode']}")

    report: dict[str, Any] = {
        "schemaVersion": "rag-ime.memory-book-maintenance-doctor.v2",
        "ok": not errors,
        "appRoot": str(app_root),
        "plistPath": str(plist_path),
        "gatewayUrl": gateway_url,
        "schedulerReadsDatabase": False,
        "schedulerStartsRuntimeHost": False,
        "installMarker": marker_payload or {},
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


def _is_loopback_origin(value: str) -> bool:
    parsed = urlparse(str(value or "").strip().rstrip("/"))
    return bool(
        parsed.scheme == "http"
        and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
        and parsed.username is None
        and parsed.password is None
        and parsed.path in {"", "/"}
        and not parsed.query
        and not parsed.fragment
    )


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
