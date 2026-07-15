#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag_ime.authorized_blog_corpus import (
    audit_whitelist,
    build_authorized_blog_corpus,
    package_authorized_blog_corpus,
    sync_git_sources,
)


DEFAULT_WHITELIST = ROOT / "dataset" / "authorized_blog_whitelist.v1.json"
DEFAULT_CACHE = ROOT / ".rag-ime-data" / "authorized-blog-sources"
DEFAULT_OUTPUT = ROOT / ".rag-ime-data" / "authorized-blog-corpus-v1"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Collect a pinned, licensed Chinese blog corpus without chat/prompt formatting"
    )
    parser.add_argument("command", choices=("audit", "sync", "build", "package", "all"))
    parser.add_argument("--whitelist", default=str(DEFAULT_WHITELIST))
    parser.add_argument("--cache", default=str(DEFAULT_CACHE))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--seed", default="rag-ime-blog-v1")
    parser.add_argument("--min-chars", type=int, default=100)
    parser.add_argument("--max-chars", type=int, default=4000)
    parser.add_argument("--min-han-ratio", type=float, default=0.65)
    parser.add_argument("--max-source-share", type=float, default=0.45)
    parser.add_argument("--review-sample-size", type=int, default=50)
    parser.add_argument("--no-near-dedupe", action="store_true")
    parser.add_argument("--package-root", default="")
    parser.add_argument("--package-name", default="rag-ime-authorized-blog-corpus-v1")
    parser.add_argument("--downloaded-audit", default="")
    args = parser.parse_args(argv)

    try:
        if args.command == "audit":
            payload = audit_whitelist(args.whitelist)
        elif args.command == "sync":
            payload = sync_git_sources(args.whitelist, args.cache)
        elif args.command == "build":
            payload = _build(args)
        elif args.command == "package":
            if not args.package_root:
                raise ValueError("--package-root is required for package")
            payload = package_authorized_blog_corpus(
                args.whitelist,
                args.cache,
                args.output,
                args.package_root,
                package_name=args.package_name,
                downloaded_audit_path=args.downloaded_audit or None,
            )
        else:
            audit = audit_whitelist(args.whitelist)
            synced = sync_git_sources(args.whitelist, args.cache)
            built = _build(args)
            payload = {"ok": True, "audit": audit, "sync": synced, "build": built}
    except (FileExistsError, FileNotFoundError, json.JSONDecodeError, RuntimeError, ValueError) as exc:
        payload = {"ok": False, "command": args.command, "error": str(exc)}

    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if payload.get("ok") else 1


def _build(args: argparse.Namespace) -> dict[str, object]:
    return build_authorized_blog_corpus(
        args.whitelist,
        args.cache,
        args.output,
        seed=args.seed,
        min_chars=args.min_chars,
        max_chars=args.max_chars,
        min_han_ratio=args.min_han_ratio,
        max_source_share=args.max_source_share,
        review_sample_size=args.review_sample_size,
        near_dedupe=not args.no_near_dedupe,
    )


if __name__ == "__main__":
    raise SystemExit(main())
