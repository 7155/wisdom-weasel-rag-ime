#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag_ime.release_staging import prepare_release_candidate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare deterministic unsigned release-candidate staging archives")
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--output", default=str(ROOT / "output" / "release-candidate"))
    parser.add_argument("--squirrel-source", default="/tmp/rag-ime-squirrel")
    parser.add_argument("--squirrel-app", default="/tmp/rag-ime-squirrel-derived-data/Build/Products/Release/Squirrel.app")
    parser.add_argument("--control-app", default=str(ROOT / "build" / "RagImeControl.app"))
    parser.add_argument(
        "--desktop-bridge-app",
        default=str(ROOT / "build" / "RagImeDesktopBridge.app"),
    )
    parser.add_argument("--voice-app", default=str(ROOT / "build" / "RagImeVoice.app"))
    args = parser.parse_args(argv)
    try:
        report = prepare_release_candidate(
            ROOT,
            release_id=args.release_id,
            output_root=args.output,
            squirrel_source=args.squirrel_source,
            apps={
                "squirrel": args.squirrel_app,
                "control": args.control_app,
                "desktopBridge": args.desktop_bridge_app,
                "voice": args.voice_app,
            },
        )
    except (OSError, RuntimeError, ValueError) as exc:
        report = {"ok": False, "error": str(exc)}
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
