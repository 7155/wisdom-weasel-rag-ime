#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag_ime.public_release import DEFAULT_RELEASE_MANIFEST_PATH, audit_public_release, write_public_release_report


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit tracked files and metadata before a public RAG-IME release")
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--report", default="")
    parser.add_argument(
        "--manifest",
        default=DEFAULT_RELEASE_MANIFEST_PATH,
        help="Repo-relative generated release manifest to verify",
    )
    parser.add_argument("--allow-blocked", action="store_true", help="Print blockers but exit zero")
    args = parser.parse_args()
    report = audit_public_release(args.root, release_manifest_path=args.manifest)
    if args.report:
        write_public_release_report(report, args.report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] or args.allow_blocked else 1


if __name__ == "__main__":
    raise SystemExit(main())
