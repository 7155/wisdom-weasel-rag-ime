#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag_ime.deployment_status import audit_installed_product


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit installed RAG-IME apps and runtime components for provenance drift."
    )
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--home", type=Path, default=Path.home())
    parser.add_argument("--app-support", type=Path)
    parser.add_argument("--expected-commit", default="")
    parser.add_argument("--require", action="append", dest="required")
    parser.add_argument("--fast", action="store_true", help="Skip hashing every Pi Runtime payload file.")
    parser.add_argument("--report-path", type=Path)
    parser.add_argument("--require-current", action="store_true")
    args = parser.parse_args()

    report = audit_installed_product(
        repo_root=args.repo_root,
        home=args.home,
        app_support=args.app_support,
        expected_commit=args.expected_commit,
        required_components=args.required or ("control", "sidecar", "squirrel"),
        verify_pi_files=not args.fast,
    )
    output = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.report_path:
        args.report_path.expanduser().write_text(output, encoding="utf-8")
    print(output, end="")
    return 1 if args.require_current and not report["ok"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
