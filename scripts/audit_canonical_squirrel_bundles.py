#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import plistlib
import subprocess
from pathlib import Path
from typing import Any


def main() -> int:
    parser = argparse.ArgumentParser(description="Fail when more than one Squirrel bundle owns the canonical bundle id.")
    parser.add_argument("--canonical-app", default=str(Path.home() / "Library/Input Methods/Squirrel.app"))
    parser.add_argument("--system-dir", default="/Library/Input Methods")
    parser.add_argument("--user-dir", default=str(Path.home() / "Library/Input Methods"))
    parser.add_argument("--bundle-id", default="im.rime.inputmethod.Squirrel")
    parser.add_argument("--report-path", default="")
    args = parser.parse_args()

    canonical = Path(args.canonical_app).expanduser().resolve()
    candidates: list[dict[str, Any]] = []
    for directory in (Path(args.user_dir).expanduser(), Path(args.system_dir).expanduser()):
        if not directory.is_dir():
            continue
        for app in sorted(directory.glob("*.app")):
            info = inspect_app(app)
            if info.get("bundleId") == args.bundle_id:
                info["canonical"] = app.resolve() == canonical
                candidates.append(info)

    canonical_entries = [item for item in candidates if item.get("canonical")]
    errors: list[str] = []
    if len(canonical_entries) != 1:
        errors.append(f"canonical bundle count is {len(canonical_entries)}, expected 1")
    if len(candidates) != 1:
        errors.append(f"same-bundle Squirrel count is {len(candidates)}, expected 1")
    if canonical_entries and not canonical_entries[0].get("patchedMarkers"):
        errors.append("canonical bundle lacks current RAG-IME markers")

    report = {
        "schemaVersion": "rag-ime.canonical-squirrel-audit.v1",
        "ok": not errors,
        "bundleId": args.bundle_id,
        "canonicalApp": str(canonical),
        "bundleCount": len(candidates),
        "bundles": candidates,
        "errors": errors,
        "repairCommand": "scripts/quarantine_duplicate_squirrel_app.sh --preflight",
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.report_path:
        path = Path(args.report_path).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report["ok"] else 1


def inspect_app(app: Path) -> dict[str, Any]:
    plist_path = app / "Contents" / "Info.plist"
    executable_path = app / "Contents" / "MacOS" / "Squirrel"
    marker_path = app / "Contents" / "Resources" / "rag-ime-build-marker.json"
    bundle_id = ""
    input_source_id = ""
    if plist_path.is_file():
        try:
            payload = plistlib.loads(plist_path.read_bytes())
            bundle_id = str(payload.get("CFBundleIdentifier") or "")
            input_source_id = str(payload.get("TISInputSourceID") or "")
        except Exception:
            pass
    binary = executable_path.read_bytes() if executable_path.is_file() else b""
    marker_text = binary.decode("latin-1", errors="ignore")
    return {
        "path": str(app),
        "bundleId": bundle_id,
        "inputSourceId": input_source_id,
        "binarySha256": hashlib.sha256(binary).hexdigest() if binary else "",
        "binaryUUIDs": binary_uuids(executable_path),
        "patchedMarkers": all(
            marker in marker_text
            for marker in ("rag-ime.foreground-trace.v2", "composition_ai_suppressed", "foreground_context_capture_resolved")
        ),
        "buildMarkerPath": str(marker_path) if marker_path.is_file() else "",
    }


def binary_uuids(executable: Path) -> list[str]:
    if not executable.is_file():
        return []
    try:
        result = subprocess.run(
            ["dwarfdump", "--uuid", str(executable)],
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


if __name__ == "__main__":
    raise SystemExit(main())
