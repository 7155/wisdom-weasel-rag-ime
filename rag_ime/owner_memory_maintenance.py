from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .deepseek_config import load_deepseek_config
from .deepseek_memory_organizer import DeepSeekMemoryOrganizer
from .owner_memory_curation import OwnerMemoryCurator


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run owner-scoped daily memory curation once.",
    )
    parser.add_argument("--db-path", required=True)
    parser.add_argument("--project", default="")
    parser.add_argument("--model-env-path", default="")
    parser.add_argument("--owner-kind", default="")
    parser.add_argument("--owner-id", default="")
    parser.add_argument("--instruction", default="")
    parser.add_argument("--manual", action="store_true")
    parser.add_argument("--max-sources", type=int, default=64)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    env_path = (
        Path(args.model_env_path).expanduser()
        if args.model_env_path
        else None
    )
    config = load_deepseek_config(env_path)
    curator = OwnerMemoryCurator(
        args.db_path,
        organizer=DeepSeekMemoryOrganizer(config),
        project=args.project,
        max_sources=args.max_sources,
    )
    curator.initialize()
    report = curator.run_due(
        manual=bool(args.manual),
        owner_kind=args.owner_kind,
        owner_id=args.owner_id,
        instruction=args.instruction,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    raise SystemExit(main())
