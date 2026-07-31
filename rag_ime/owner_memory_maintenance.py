from __future__ import annotations

import argparse
import json
import os

from .deepseek_memory_organizer import ManagedPiMemoryOrganizer
from .embeddings import embedding_provider_from_env
from .lexicon_organization import run_due_lexicon_organization
from .memory_maintenance_settings import MemoryMaintenanceSettings
from .memory_model_executor import build_managed_pi_memory_model_executor
from .owner_memory_curation import OwnerMemoryCurator


def _environment_bool(name: str, *, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


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
    parser.add_argument("--model", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    lexicon_organization = run_due_lexicon_organization(
        args.db_path,
        project=args.project,
        force=bool(args.manual),
    )
    managed = MemoryMaintenanceSettings.load(args.db_path)
    if not managed.automatic_organization_enabled:
        print(
            json.dumps(
                {
                    "schemaVersion": "rag-ime.owner-memory-curation-run.v1",
                    "ok": lexicon_organization.get("ok") is not False,
                    "skipped": True,
                    "reason": "automatic_organization_disabled",
                    "managedSettings": managed.as_dict(),
                    "lexiconOrganization": lexicon_organization,
                    "results": [],
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 0 if lexicon_organization.get("ok") is not False else 1
    env_auto_apply = (
        _environment_bool("RAG_IME_OWNER_MEMORY_AUTO_APPLY", default=True)
        if "RAG_IME_OWNER_MEMORY_AUTO_APPLY" in os.environ
        else True
    )
    auto_apply = (
        False
        if args.manual
        else bool(args.auto_apply)
        if args.auto_apply is not None
        else env_auto_apply
    )
    interval_seconds = managed.automatic_organization_interval_seconds
    selected_model = str(args.model).strip() or managed.automatic_organization_model
    try:
        executor = build_managed_pi_memory_model_executor(
            args.db_path,
            selected_model,
            managed.automatic_organization_thinking_level,
        )
        organizer = ManagedPiMemoryOrganizer(executor)
    except Exception as exc:
        report = {
            "schemaVersion": "rag-ime.owner-memory-curation-run.v1",
            "ok": False,
            "error": " ".join(str(exc).split())[:800] or exc.__class__.__name__,
            "managedSettings": managed.as_dict(),
            "effectiveModel": selected_model,
            "effectiveThinkingLevel": managed.automatic_organization_thinking_level,
            "lexiconOrganization": lexicon_organization,
            "results": [],
        }
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 1
    try:
        curator = OwnerMemoryCurator(
            args.db_path,
            organizer=organizer,
            project=args.project,
            max_sources=args.max_sources,
            auto_apply=auto_apply,
            include_agent_dialogue=managed.include_agent_dialogue,
            daily_interval_ms=max(60, interval_seconds) * 1_000,
            embedding_provider=embedding_provider_from_env(),
        )
        curator.initialize()
        report = curator.run_due(
            manual=bool(args.manual),
            owner_kind=args.owner_kind,
            owner_id=args.owner_id,
            instruction=args.instruction,
        )
        report["lexiconOrganization"] = lexicon_organization
        if lexicon_organization.get("ok") is False:
            report["ok"] = False
        report["managedSettings"] = managed.as_dict()
        report["effectiveModel"] = selected_model
        report["effectiveThinkingLevel"] = managed.automatic_organization_thinking_level
        report["effectiveIntervalSeconds"] = max(60, interval_seconds)
        report["autoApply"] = auto_apply
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if report.get("ok") else 1
    finally:
        organizer.close()


if __name__ == "__main__":
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    raise SystemExit(main())
