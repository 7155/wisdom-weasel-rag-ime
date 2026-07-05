#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import plistlib
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    input_source_id = args.input_source_id or os.environ.get("RAG_IME_SQUIRREL_INPUT_SOURCE_ID") or "im.rime.inputmethod.Squirrel.Hans"
    bundle_id = args.bundle_id or os.environ.get("RAG_IME_SQUIRREL_BUNDLE_ID") or input_source_id.rsplit(".", 1)[0]
    check_script = Path(args.check_script or os.environ.get("RAG_IME_CHECK_INPUT_SOURCE_SCRIPT") or root / "scripts" / "check_macos_input_source.sh")

    check_report = run_check_script(check_script, input_source_id, bundle_id)
    parsed = check_report.get("parsed") if isinstance(check_report.get("parsed"), dict) else {}
    preferences = preference_report(Path.home(), input_source_id, bundle_id)
    launch_services = launch_services_report(bundle_id)
    readiness = readiness_report(parsed, check_report, preferences)
    report: dict[str, Any] = {
        "schemaVersion": "rag-ime.macos-input-source-audit.v1",
        "mutatesSystem": False,
        "inputSourceId": input_source_id,
        "bundleId": bundle_id,
        "checkScript": str(check_script),
        "check": check_report,
        "preferences": preferences,
        "launchServices": launch_services,
        "readiness": readiness,
        "commands": {
            "inspectRepairPlan": "scripts/enable_squirrel_hitoolbox_input_source.sh --dry-run",
            "manualAdd": "scripts/open_squirrel_input_source_settings.sh --wait",
            "waitForAdd": "scripts/wait_squirrel_input_source_added.sh",
            "waitForSelection": "scripts/wait_squirrel_typing_ready.sh",
        },
    }
    write_report(report, args.report_path)
    return 0 if readiness["state"] in {"ready", "switch"} else 1


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Write a read-only JSON audit for the macOS Squirrel input-source state.")
    parser.add_argument("--input-source-id", default=None)
    parser.add_argument("--bundle-id", default=None)
    parser.add_argument("--check-script", default=None)
    parser.add_argument("--report-path", default="-", help="Write JSON to this path, or '-' for stdout.")
    return parser.parse_args(argv)


def run_check_script(check_script: Path, input_source_id: str, bundle_id: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "available": check_script.exists(),
        "exitCode": None,
        "rawOutput": "",
        "parsed": {},
    }
    if not check_script.exists():
        return {**payload, "error": "check script is missing"}
    env = {**os.environ, "RAG_IME_INPUT_SOURCE_BUNDLE_ID": bundle_id}
    completed = subprocess.run(
        [str(check_script), "--require-hitoolbox-enabled", input_source_id],
        check=False,
        text=True,
        capture_output=True,
        timeout=10,
        env=env,
    )
    output = "\n".join(part for part in (completed.stdout.strip(), completed.stderr.strip()) if part)
    return {
        **payload,
        "exitCode": completed.returncode,
        "rawOutput": output,
        "parsed": parse_check_output(output),
    }


def parse_check_output(output: str) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    if not output:
        return parsed
    first_line = output.splitlines()[0]
    if first_line.startswith("missing "):
        parsed["missing"] = first_line.removeprefix("missing ").strip()
        return parsed
    for key in ("id", "name", "current"):
        match = re.search(rf"(?:^|\s){re.escape(key)}=(.*?)(?=\s(?:id|name|enabled|selectable|selected|tisSelected|current|hitoolboxEnabled|thirdPartyEnabled)=|$)", first_line)
        if match:
            parsed[key] = match.group(1)
    for key in ("enabled", "selectable", "selected", "tisSelected", "hitoolboxEnabled", "thirdPartyEnabled"):
        match = re.search(rf"(?:^|\s){re.escape(key)}=(true|false)", first_line)
        if match:
            parsed[key] = match.group(1) == "true"
    return parsed


def preference_report(home: Path, input_source_id: str, bundle_id: str) -> dict[str, Any]:
    hitoolbox_path = home / "Library" / "Preferences" / "com.apple.HIToolbox.plist"
    inputsources_path = home / "Library" / "Preferences" / "com.apple.inputsources.plist"
    hitoolbox = list_report(hitoolbox_path, "AppleEnabledInputSources", input_source_id, bundle_id)
    third_party = list_report(inputsources_path, "AppleEnabledThirdPartyInputSources", input_source_id, bundle_id)
    return {
        "hitoolbox": hitoolbox,
        "thirdParty": third_party,
        "wouldChangeHitoolbox": not (hitoolbox["hasInputMode"] and hitoolbox["hasBundle"]),
        "wouldChangeThirdParty": not (third_party["hasInputMode"] and third_party["hasBundle"]),
    }


def list_report(path: Path, key: str, input_source_id: str, bundle_id: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "path": str(path),
        "key": key,
        "exists": path.exists(),
        "count": 0,
        "hasInputMode": False,
        "hasBundle": False,
        "matchingEntries": [],
        "error": "",
    }
    if not path.exists():
        return payload
    try:
        with path.open("rb") as handle:
            plist = plistlib.load(handle)
    except Exception as exc:
        return {**payload, "error": str(exc)}
    entries = plist.get(key, [])
    if not isinstance(entries, list):
        return {**payload, "error": f"{key} is not a list"}
    matches: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        input_mode = entry.get("Input Mode")
        entry_bundle = entry.get("Bundle ID")
        if input_mode == input_source_id or entry_bundle == bundle_id:
            clean = {str(k): v for k, v in entry.items() if isinstance(k, str)}
            matches.append(clean)
    return {
        **payload,
        "count": len(entries),
        "hasInputMode": any(isinstance(item, dict) and item.get("Input Mode") == input_source_id for item in entries),
        "hasBundle": any(isinstance(item, dict) and item.get("Bundle ID") == bundle_id and "Input Mode" not in item for item in entries),
        "matchingEntries": matches,
    }


def launch_services_report(bundle_id: str) -> dict[str, Any]:
    lsregister = Path(
        os.environ.get("RAG_IME_LSREGISTER")
        or "/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"
    )
    payload: dict[str, Any] = {
        "available": lsregister.exists(),
        "bundleId": bundle_id,
        "matchingRecords": [],
        "duplicatePathCount": 0,
        "error": "",
    }
    if not lsregister.exists():
        return payload
    completed = subprocess.run(
        [str(lsregister), "-dump"],
        check=False,
        text=True,
        capture_output=True,
        timeout=10,
    )
    if completed.returncode != 0:
        return {**payload, "error": completed.stderr.strip() or f"lsregister exited {completed.returncode}"}
    records = parse_lsregister_dump(completed.stdout)
    matches = [record for record in records if record.get("identifier") == bundle_id]
    paths = sorted({record.get("path", "") for record in matches if record.get("path")})
    return {
        **payload,
        "matchingRecords": matches,
        "duplicatePathCount": max(0, len(paths) - 1),
    }


def parse_lsregister_dump(text: str) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    current: dict[str, str] = {}

    def flush() -> None:
        if current:
            records.append(dict(current))
            current.clear()

    for raw in text.splitlines():
        line = raw.rstrip()
        if line.startswith("-" * 20):
            flush()
            continue
        stripped = line.strip()
        if stripped.startswith("path:"):
            current["path"] = stripped.split(":", 1)[1].strip().split(" (0x", 1)[0]
        elif stripped.startswith("identifier:"):
            current["identifier"] = stripped.split(":", 1)[1].strip().strip('"')
        elif stripped.startswith("name:"):
            current["name"] = stripped.split(":", 1)[1].strip().strip('"')
    flush()
    return records


def readiness_report(parsed: dict[str, Any], check_report: dict[str, Any], preferences: dict[str, Any]) -> dict[str, Any]:
    visible = parsed.get("enabled") is True and parsed.get("selectable") is True
    hitoolbox = parsed.get("hitoolboxEnabled") is True
    third_party = parsed.get("thirdPartyEnabled") is True
    selected = parsed.get("selected") is True
    if visible and hitoolbox and third_party and selected and check_report.get("exitCode") == 0:
        return {"state": "ready", "nextAction": "type in a foreground text field with Squirrel selected"}
    if visible and hitoolbox and third_party:
        return {"state": "switch", "nextAction": "select Squirrel from the macOS input menu, then run scripts/wait_squirrel_typing_ready.sh"}
    if visible and hitoolbox and not third_party:
        return {
            "state": "third-party-missing",
            "nextAction": "run scripts/enable_squirrel_hitoolbox_input_source.sh --dry-run or add Squirrel in System Settings",
            "wouldChangeThirdParty": preferences["wouldChangeThirdParty"],
        }
    if visible:
        return {"state": "preferences-incomplete", "nextAction": "inspect the preference report and System Settings input-source list"}
    return {"state": "missing", "nextAction": "install/register patched Squirrel, then rerun this audit"}


def write_report(report: dict[str, Any], report_path: str) -> None:
    text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if report_path == "-":
        sys.stdout.write(text)
        return
    Path(report_path).write_text(text, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
