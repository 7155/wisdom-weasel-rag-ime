from __future__ import annotations

import argparse
import json
import os
from dataclasses import replace
from pathlib import Path

from .deepseek_config import load_deepseek_config
from .deepseek_memory_organizer import DeepSeekMemoryOrganizer
from .memory_maintenance_settings import MemoryMaintenanceSettings
from .owner_memory_curation import OwnerMemoryCurator


def _environment_bool(name: str, *, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _environment_int(name: str, *, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


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
    auto_apply = parser.add_mutually_exclusive_group()
    auto_apply.add_argument("--auto-apply", dest="auto_apply", action="store_true")
    auto_apply.add_argument("--no-auto-apply", dest="auto_apply", action="store_false")
    parser.set_defaults(auto_apply=None)
    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=None,
    )
    parser.add_argument("--model", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    managed = MemoryMaintenanceSettings.load(args.db_path)
    if not managed.automatic_organization_enabled:
        print(
            json.dumps(
                {
                    "schemaVersion": "rag-ime.owner-memory-curation-run.v1",
                    "ok": True,
                    "skipped": True,
                    "reason": "automatic_organization_disabled",
                    "managedSettings": managed.as_dict(),
                    "results": [],
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    env_auto_apply = (
        _environment_bool("RAG_IME_OWNER_MEMORY_AUTO_APPLY", default=True)
        if "RAG_IME_OWNER_MEMORY_AUTO_APPLY" in os.environ
        else True
    )
    auto_apply = (
        bool(args.auto_apply)
        if args.auto_apply is not None
        else env_auto_apply
    )
    interval_seconds = (
        int(args.interval_seconds)
        if args.interval_seconds is not None
        else (
            _environment_int(
                "RAG_IME_OWNER_MEMORY_INTERVAL_SECONDS",
                default=managed.automatic_organization_interval_seconds,
            )
            if "RAG_IME_OWNER_MEMORY_INTERVAL_SECONDS" in os.environ
            else managed.automatic_organization_interval_seconds
        )
    )
    env_path = (
        Path(args.model_env_path).expanduser()
        if args.model_env_path
        else None
    )
    config = load_deepseek_config(env_path)
    config = replace(
        config,
        model=(
            str(args.model).strip()
            or managed.automatic_organization_model
        ),
    )
    curator = OwnerMemoryCurator(
        args.db_path,
        organizer=DeepSeekMemoryOrganizer(config),
        project=args.project,
        max_sources=args.max_sources,
        auto_apply=auto_apply,
        include_agent_dialogue=managed.include_agent_dialogue,
        daily_interval_ms=max(60, interval_seconds) * 1_000,
    )
    curator.initialize()
    report = curator.run_due(
        manual=bool(args.manual),
        owner_kind=args.owner_kind,
        owner_id=args.owner_id,
        instruction=args.instruction,
    )
    report["managedSettings"] = managed.as_dict()
    report["effectiveModel"] = config.model
    report["effectiveIntervalSeconds"] = max(60, interval_seconds)
    report["autoApply"] = auto_apply
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    raise SystemExit(main())
