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
    parser = argparse.ArgumentParser(
        description="Audit source-repository and distribution readiness"
    )
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--report", default="")
    parser.add_argument(
        "--manifest",
        default=DEFAULT_RELEASE_MANIFEST_PATH,
        help="Repo-relative generated release manifest to verify",
    )
    parser.add_argument(
        "--repository-only",
        action="store_true",
        help=(
            "Require a clean, public-safe source repository without claiming "
            "that a signed/notarized macOS distribution is ready"
        ),
    )
    parser.add_argument("--allow-blocked", action="store_true", help="Print blockers but exit zero")
    args = parser.parse_args()
    report = audit_public_release(args.root, release_manifest_path=args.manifest)
    requested_scope = "repository" if args.repository_only else "distribution"
    requested_scope_ok = bool(
        report["repositoryReady"]
        if args.repository_only
        else report["distributionReady"]
    )
    report = {
        **report,
        "requestedScope": requested_scope,
        "requestedScopeOk": requested_scope_ok,
    }
    if args.report:
        write_public_release_report(report, args.report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if requested_scope_ok or args.allow_blocked else 1


if __name__ == "__main__":
    raise SystemExit(main())
