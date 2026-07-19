from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .settings_store import ManagementSettingsStore
from .text_utils import compact_whitespace


DEFAULT_MAINTENANCE_MODEL = "deepseek-v4-flash"
DEFAULT_CODEX_MEMORY_ROOT = "~/.codex/memories"
SECONDS_PER_DAY = 24 * 60 * 60


@dataclass(frozen=True)
class MemoryMaintenanceSettings:
    automatic_organization_enabled: bool = True
    automatic_organization_model: str = DEFAULT_MAINTENANCE_MODEL
    automatic_organization_runs_per_day: int = 2
    include_agent_dialogue: bool = True
    dreaming_enabled: bool = True
    dreaming_model: str = DEFAULT_MAINTENANCE_MODEL
    dreaming_runs_per_day: int = 2
    codex_memory_enabled: bool = False
    codex_memory_root: str = DEFAULT_CODEX_MEMORY_ROOT
    codex_memory_lookback_days: int = 90
    codex_memory_include_rollout_summaries: bool = True
    recall_detail_level: str = "compact"
    timeline_recall_enabled: bool = True
    timeline_max_items: int = 2

    @classmethod
    def load(cls, db_path: str | Path) -> "MemoryMaintenanceSettings":
        settings = ManagementSettingsStore(db_path).get_settings(
            include_sensitive=True
        )
        memory = _mapping(settings.get("memory"))
        automatic = _mapping(memory.get("automaticOrganization"))
        dreaming = _mapping(memory.get("dreaming"))
        external_sources = _mapping(memory.get("externalSources"))
        codex_memory = _mapping(external_sources.get("codexMemory"))
        recall = _mapping(memory.get("recall"))
        return cls(
            automatic_organization_enabled=bool(automatic.get("enabled", True)),
            automatic_organization_model=_maintenance_model(
                automatic.get("model")
            ),
            automatic_organization_runs_per_day=_runs_per_day(
                automatic.get("runsPerDay")
            ),
            include_agent_dialogue=bool(
                automatic.get("includeAgentDialogue", True)
            ),
            dreaming_enabled=bool(dreaming.get("enabled", True)),
            dreaming_model=_maintenance_model(dreaming.get("model")),
            dreaming_runs_per_day=_runs_per_day(dreaming.get("runsPerDay")),
            codex_memory_enabled=bool(codex_memory.get("enabled", False)),
            codex_memory_root=_memory_root(codex_memory.get("path")),
            codex_memory_lookback_days=_bounded_int(
                codex_memory.get("lookbackDays"),
                default=90,
                minimum=1,
                maximum=90,
            ),
            codex_memory_include_rollout_summaries=bool(
                codex_memory.get("includeRolloutSummaries", True)
            ),
            recall_detail_level=_detail_level(recall.get("detailLevel")),
            timeline_recall_enabled=bool(recall.get("timelineEnabled", True)),
            timeline_max_items=_bounded_int(
                recall.get("timelineMaxItems"),
                default=2,
                minimum=1,
                maximum=4,
            ),
        )

    @property
    def automatic_organization_interval_seconds(self) -> int:
        return max(
            60,
            SECONDS_PER_DAY // self.automatic_organization_runs_per_day,
        )

    @property
    def dreaming_interval_seconds(self) -> int:
        return max(60, SECONDS_PER_DAY // self.dreaming_runs_per_day)

    def as_dict(self) -> dict[str, object]:
        return {
            "schemaVersion": "rag-ime.memory-maintenance-settings.v1",
            "automaticOrganization": {
                "enabled": self.automatic_organization_enabled,
                "model": self.automatic_organization_model,
                "runsPerDay": self.automatic_organization_runs_per_day,
                "intervalSeconds": self.automatic_organization_interval_seconds,
                "autoApply": True,
                "includeAgentDialogue": self.include_agent_dialogue,
            },
            "dreaming": {
                "enabled": self.dreaming_enabled,
                "model": self.dreaming_model,
                "runsPerDay": self.dreaming_runs_per_day,
                "intervalSeconds": self.dreaming_interval_seconds,
            },
            "externalSources": {
                "codexMemory": {
                    "enabled": self.codex_memory_enabled,
                    "path": self.codex_memory_root,
                    "lookbackDays": self.codex_memory_lookback_days,
                    "includeRolloutSummaries": (
                        self.codex_memory_include_rollout_summaries
                    ),
                    "rawTranscriptImported": False,
                }
            },
            "recall": {
                "detailLevel": self.recall_detail_level,
                "timelineEnabled": self.timeline_recall_enabled,
                "timelineMaxItems": self.timeline_max_items,
            },
        }


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _maintenance_model(value: object) -> str:
    model = compact_whitespace(str(value or DEFAULT_MAINTENANCE_MODEL))
    if "/" in model:
        provider, _, model_id = model.partition("/")
        if provider.casefold() == "deepseek" and model_id:
            model = model_id
    if not model.casefold().replace("_", "-").startswith("deepseek-v4"):
        return DEFAULT_MAINTENANCE_MODEL
    return model


def _memory_root(value: object) -> str:
    root = str(value or DEFAULT_CODEX_MEMORY_ROOT).strip()
    return root[:1_024] or DEFAULT_CODEX_MEMORY_ROOT


def _runs_per_day(value: object) -> int:
    return _bounded_int(value, default=2, minimum=1, maximum=6)


def _bounded_int(
    value: object,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        normalized = default
    return max(minimum, min(normalized, maximum))


def _detail_level(value: object) -> str:
    normalized = compact_whitespace(str(value or "")).casefold()
    return (
        normalized
        if normalized in {"compact", "balanced", "detailed"}
        else "compact"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Resolve managed Dream and automatic-memory settings.",
    )
    parser.add_argument("--db-path", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = MemoryMaintenanceSettings.load(args.db_path).as_dict()
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
