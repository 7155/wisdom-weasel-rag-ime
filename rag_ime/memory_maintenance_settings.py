from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .settings_store import ManagementSettingsStore
from .text_utils import compact_whitespace


DEFAULT_MAINTENANCE_MODEL = "openai-codex/gpt-5.6-luna"
DEFAULT_MAINTENANCE_THINKING_LEVEL = "max"
SECONDS_PER_DAY = 24 * 60 * 60


@dataclass(frozen=True)
class MemoryMaintenanceSettings:
    automatic_organization_enabled: bool = True
    automatic_organization_model: str = DEFAULT_MAINTENANCE_MODEL
    automatic_organization_thinking_level: str = DEFAULT_MAINTENANCE_THINKING_LEVEL
    automatic_organization_runs_per_day: int = 2
    include_agent_dialogue: bool = True
    dreaming_enabled: bool = True
    dreaming_model: str = DEFAULT_MAINTENANCE_MODEL
    dreaming_thinking_level: str = DEFAULT_MAINTENANCE_THINKING_LEVEL
    dreaming_runs_per_day: int = 2
    recall_detail_level: str = "compact"
    timeline_recall_enabled: bool = True
    timeline_max_items: int = 2

    @classmethod
    def load(
        cls,
        db_path: str | Path,
        *,
        preverified_schema: bool = False,
    ) -> "MemoryMaintenanceSettings":
        settings = ManagementSettingsStore(
            db_path,
            preverified_schema=preverified_schema,
        ).get_settings(
            include_sensitive=True
        )
        memory = _mapping(settings.get("memory"))
        automatic = _mapping(memory.get("automaticOrganization"))
        dreaming = _mapping(memory.get("dreaming"))
        recall = _mapping(memory.get("recall"))
        return cls(
            automatic_organization_enabled=bool(automatic.get("enabled", True)),
            automatic_organization_model=_maintenance_model(
                automatic.get("model")
            ),
            automatic_organization_thinking_level=_thinking_level(
                automatic.get("thinkingLevel")
            ),
            automatic_organization_runs_per_day=_runs_per_day(
                automatic.get("runsPerDay")
            ),
            include_agent_dialogue=bool(
                automatic.get("includeAgentDialogue", True)
            ),
            dreaming_enabled=bool(dreaming.get("enabled", True)),
            dreaming_model=_maintenance_model(dreaming.get("model")),
            dreaming_thinking_level=_thinking_level(dreaming.get("thinkingLevel")),
            dreaming_runs_per_day=_runs_per_day(dreaming.get("runsPerDay")),
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
                "thinkingLevel": self.automatic_organization_thinking_level,
                "runsPerDay": self.automatic_organization_runs_per_day,
                "intervalSeconds": self.automatic_organization_interval_seconds,
                "autoApply": True,
                "includeAgentDialogue": self.include_agent_dialogue,
            },
            "dreaming": {
                "enabled": self.dreaming_enabled,
                "model": self.dreaming_model,
                "thinkingLevel": self.dreaming_thinking_level,
                "runsPerDay": self.dreaming_runs_per_day,
                "intervalSeconds": self.dreaming_interval_seconds,
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
    if model == "gpt/gpt-5.6-luna":
        return DEFAULT_MAINTENANCE_MODEL
    if "/" not in model:
        if model.casefold().replace("_", "-").startswith("deepseek-v4"):
            return f"deepseek/{model}"
        return DEFAULT_MAINTENANCE_MODEL
    provider, _, model_id = model.partition("/")
    if not provider or not model_id or any(character.isspace() for character in model):
        return DEFAULT_MAINTENANCE_MODEL
    return f"{provider}/{model_id}"


def _thinking_level(value: object) -> str:
    normalized = compact_whitespace(str(value or DEFAULT_MAINTENANCE_THINKING_LEVEL)).casefold()
    return (
        normalized
        if normalized in {"off", "minimal", "low", "medium", "high", "xhigh", "max"}
        else DEFAULT_MAINTENANCE_THINKING_LEVEL
    )


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
