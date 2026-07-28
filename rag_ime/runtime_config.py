from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from typing import Mapping, Protocol

from .runtime_profile import get_runtime_profile
from .settings_schema import stable_settings_hash


RUNTIME_CONFIG_SCHEMA_VERSION = "rag-ime.runtime-config.v1"

_RAG_LANE_SETTING_NAMES = {
    "bm25_raw": "bm25Raw",
    "bm25_tags": "bm25Tags",
    "vector_raw": "vectorRaw",
    "vector_tag_boost": "vectorTagBoost",
    "tagmemo": "tagMemo",
    "time": "timeDailyBook",
    "feedback": "feedback",
}
_RAG_LANES = tuple(_RAG_LANE_SETTING_NAMES)
_DEFAULT_RAG_WEIGHTS = {
    "bm25_raw": 1.00,
    "bm25_tags": 1.15,
    "vector_raw": 1.05,
    "vector_tag_boost": 1.05,
    "tagmemo": 1.10,
    "time": 0.90,
    "feedback": 1.20,
}


class RuntimeConfigStateStore(Protocol):
    def get_settings(self, *, include_sensitive: bool = False) -> dict[str, object]: ...

    def resolve_runtime_config_revision(
        self,
        *,
        snapshot_hash: str,
        settings_revision: str,
        profile: str,
    ) -> int: ...


@dataclass(frozen=True)
class PostCommitRuntimeConfig:
    enabled: bool
    idle_trigger_ms: int
    min_delta_chars: int
    max_calls_per_10s: int
    cooldown_ms: int
    show_pending_status: bool
    pending_status_delay_ms: int
    panel_ttl_ms: int
    max_candidates: int
    completion_ttl_ms: int
    model_budget_ms: int
    model_hard_timeout_ms: int

    def payload(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "idleTriggerMs": self.idle_trigger_ms,
            "minDeltaChars": self.min_delta_chars,
            "maxCallsPer10s": self.max_calls_per_10s,
            "cooldownMs": self.cooldown_ms,
            "showPendingStatus": self.show_pending_status,
            "pendingStatusDelayMs": self.pending_status_delay_ms,
            "panelTtlMs": self.panel_ttl_ms,
            "maxCandidates": self.max_candidates,
            "completionTtlMs": self.completion_ttl_ms,
            "modelBudgetMs": self.model_budget_ms,
            "modelHardTimeoutMs": self.model_hard_timeout_ms,
        }


@dataclass(frozen=True)
class HybridRuntimeConfig:
    enabled: bool
    budget_ms: int
    direct_display: bool
    lanes: tuple[tuple[str, bool], ...]
    weights: tuple[tuple[str, float], ...]

    def lane_enabled(self, lane: str) -> bool:
        return dict(self.lanes).get(_canonical_rag_lane(lane), False)

    def lane_weight(self, lane: str) -> float:
        return dict(self.weights).get(_canonical_rag_lane(lane), 0.0)

    def payload(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "budgetMs": self.budget_ms,
            "directDisplay": self.direct_display,
            "lanes": {_settings_rag_lane(key): value for key, value in self.lanes},
            "weights": {_settings_rag_lane(key): value for key, value in self.weights},
        }

    def query_lanes(self) -> tuple[tuple[str, bool], ...]:
        return self.lanes

    def query_weights(self) -> tuple[tuple[str, float], ...]:
        return self.weights


@dataclass(frozen=True)
class MemoryRuntimeConfig:
    enabled: bool

    def payload(self) -> dict[str, object]:
        return {"enabled": self.enabled}


@dataclass(frozen=True)
class OverlayRuntimeConfig:
    candidate_font_size: int
    max_width: int
    fade_animation: bool
    panel_style: str

    def payload(self, *, expires_after_ms: int) -> dict[str, object]:
        return {
            "schemaVersion": "rag-ime.overlay-config.v1",
            "candidateFontSize": self.candidate_font_size,
            "maxWidth": self.max_width,
            "fadeAnimation": self.fade_animation,
            "panelStyle": self.panel_style,
            "expiresAfterMs": max(0, int(expires_after_ms)),
        }


@dataclass(frozen=True)
class ActiveRagRuntimeConfig:
    enabled: bool
    shortcut: str
    latency_budget_ms: int

    def payload(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "shortcut": self.shortcut,
            "latencyBudgetMs": self.latency_budget_ms,
        }


@dataclass(frozen=True)
class ModelRuntimeConfig:
    profile_id: str
    model_path: str

    def payload(self) -> dict[str, object]:
        return {"profileId": self.profile_id, "modelPath": self.model_path}


@dataclass(frozen=True)
class SourceBadgeRuntimeConfig:
    enabled: bool
    items: tuple[tuple[str, str], ...]

    def badge_for(self, source_type: str) -> str:
        if not self.enabled:
            return ""
        return dict(self.items).get(source_type, "")

    def payload(self) -> dict[str, object]:
        return {"enabled": self.enabled, "items": dict(self.items)}


@dataclass(frozen=True)
class KeyPolicyRuntimeConfig:
    composition_number_keys: str
    composition_tab: str
    composition_option_number: str
    composition_escape: str
    post_commit_number_keys: str
    tab_action: str
    option_number: str
    escape: str

    def payload(self) -> dict[str, object]:
        return {
            "composition": {
                "numberKeys": self.composition_number_keys,
                "tab": self.composition_tab,
                "optionNumber": self.composition_option_number,
                "escape": self.composition_escape,
            },
            "postCommit": {
                "numberKeys": self.post_commit_number_keys,
                "tabAction": self.tab_action,
                "optionNumber": self.option_number,
                "escape": self.escape,
            },
        }


@dataclass(frozen=True)
class RuntimeConfigSnapshot:
    runtime_revision: int
    settings_revision: str
    snapshot_hash: str
    profile: str
    composition_ai: bool
    show_only_rime: bool
    foreground_context_max_freshness_ms: int
    strict_foreground_context: bool
    post_commit: PostCommitRuntimeConfig
    hybrid_rag: HybridRuntimeConfig
    memory: MemoryRuntimeConfig
    model: ModelRuntimeConfig
    source_badges: SourceBadgeRuntimeConfig
    source_colors: tuple[tuple[str, str], ...]
    overlay: OverlayRuntimeConfig
    active_rag: ActiveRagRuntimeConfig
    key_policy: KeyPolicyRuntimeConfig
    experiment_overrides: tuple[str, ...] = ()
    safety_clamps: tuple[str, ...] = ()

    def payload(self) -> dict[str, object]:
        return {
            "schemaVersion": RUNTIME_CONFIG_SCHEMA_VERSION,
            "runtimeRevision": self.runtime_revision,
            "settingsRevision": self.settings_revision,
            "snapshotHash": self.snapshot_hash,
            "profile": self.profile,
            "composition": {
                "aiEnabled": self.composition_ai,
                "showOnlyRime": self.show_only_rime,
            },
            "foregroundContext": {
                "strict": self.strict_foreground_context,
                "maxFreshnessMs": self.foreground_context_max_freshness_ms,
            },
            "postCommit": self.post_commit.payload(),
            "hybridRag": self.hybrid_rag.payload(),
            "memory": self.memory.payload(),
            "model": self.model.payload(),
            "sourceBadges": self.source_badges.payload(),
            "sourceColors": dict(self.source_colors),
            "overlayConfig": self.overlay.payload(expires_after_ms=self.post_commit.panel_ttl_ms),
            "activeRag": self.active_rag.payload(),
            "keyPolicy": self.key_policy.payload(),
            "experimentOverrides": list(self.experiment_overrides),
            "safetyClamps": list(self.safety_clamps),
        }

    def effective_settings(self, persisted: Mapping[str, object]) -> dict[str, object]:
        settings = copy.deepcopy(dict(persisted))
        interaction = _mapping(settings.setdefault("interaction", {}))
        composition = _mapping(interaction.setdefault("composition", {}))
        composition["showPrediction"] = self.composition_ai
        composition["showOnlyRime"] = self.show_only_rime
        composition["numberKeys"] = self.key_policy.composition_number_keys
        post_commit = _mapping(interaction.setdefault("postCommit", {}))
        post_commit.update(self.post_commit.payload())
        post_commit["numberKeys"] = self.key_policy.post_commit_number_keys
        post_commit["tabAction"] = self.key_policy.tab_action
        post_commit["optionNumber"] = self.key_policy.option_number
        post_commit["escape"] = self.key_policy.escape

        display = _mapping(settings.setdefault("display", {}))
        display["showSourceBadge"] = self.source_badges.enabled
        display["maxPostCommitCandidates"] = self.post_commit.max_candidates
        display["badges"] = dict(self.source_badges.items)
        display["colors"] = dict(self.source_colors)
        display["candidateFontSize"] = self.overlay.candidate_font_size
        display["maxWidth"] = self.overlay.max_width
        display["fadeAnimation"] = self.overlay.fade_animation
        display["panelStyle"] = self.overlay.panel_style

        rag = _mapping(settings.setdefault("rag", {}))
        hybrid = _mapping(rag.setdefault("hybrid", {}))
        hybrid["enabled"] = self.hybrid_rag.enabled
        hybrid["budgetMs"] = self.hybrid_rag.budget_ms
        hybrid["directDisplay"] = self.hybrid_rag.direct_display
        rag["lanes"] = {_settings_rag_lane(key): value for key, value in self.hybrid_rag.lanes}
        rag["weights"] = {_settings_rag_lane(key): value for key, value in self.hybrid_rag.weights}

        memory = _mapping(settings.setdefault("memory", {}))
        memory["enabled"] = self.memory.enabled

        active_rag = _mapping(settings.setdefault("activeRag", {}))
        active_rag["enabled"] = self.active_rag.enabled
        active_rag["shortcut"] = self.active_rag.shortcut

        models = _mapping(settings.setdefault("models", {}))
        models["hot"] = self.model.profile_id
        models["path"] = self.model.model_path
        return settings


class RuntimeConfigResolver:
    def __init__(
        self,
        store: RuntimeConfigStateStore,
        *,
        environ: Mapping[str, str],
        profile_name: str = "",
    ) -> None:
        self.store = store
        self.environ = environ
        self.profile_name = profile_name

    def resolve(self, *, settings: Mapping[str, object] | None = None) -> RuntimeConfigSnapshot:
        persisted = dict(settings) if settings is not None else self.store.get_settings(include_sensitive=True)
        profile = get_runtime_profile(
            self.profile_name or str(self.environ.get("RAG_IME_RUNTIME_PROFILE") or "v1-proof")
        )
        settings_revision = stable_settings_hash(persisted)
        experiment_overrides: list[str] = []
        safety_clamps: list[str] = []

        interaction = _nested_mapping(persisted, "interaction")
        composition = _nested_mapping(interaction, "composition")
        post_commit_settings = _nested_mapping(interaction, "postCommit")
        display = _nested_mapping(persisted, "display")
        rag = _nested_mapping(persisted, "rag")
        hybrid = _nested_mapping(rag, "hybrid")
        rag_lanes_settings = _nested_mapping(rag, "lanes")
        rag_weights_settings = _nested_mapping(rag, "weights")
        memory_settings = _nested_mapping(persisted, "memory")
        active_rag_settings = _nested_mapping(persisted, "activeRag")
        models = _nested_mapping(persisted, "models")

        requested_composition_ai = _bool_value(composition.get("showPrediction"), True) and not _bool_value(
            composition.get("showOnlyRime"), False
        )
        requested_composition_ai = _bool_override(
            self.environ,
            "RAG_IME_RUNTIME_OVERRIDE_COMPOSITION_AI",
            requested_composition_ai,
            experiment_overrides,
        )
        composition_ai = bool(profile.composition_ai and requested_composition_ai)
        if requested_composition_ai and not composition_ai:
            safety_clamps.append("composition_ai_disabled_by_profile")
        if not _bool_value(composition.get("showOnlyRime"), False):
            safety_clamps.append("composition_rime_only")

        post_commit_enabled = _bool_override(
            self.environ,
            "RAG_IME_RUNTIME_OVERRIDE_POST_COMMIT_ENABLED",
            _bool_value(post_commit_settings.get("enabled"), True),
            experiment_overrides,
        )
        max_candidates = _int_override(
            self.environ,
            "RAG_IME_RUNTIME_OVERRIDE_MAX_POST_COMMIT_CANDIDATES",
            _bounded_int(display.get("maxPostCommitCandidates"), 5, 1, 10),
            1,
            10,
            experiment_overrides,
        )
        show_pending = bool(
            profile.assistant_pending_preview
            and _bool_value(post_commit_settings.get("showPendingStatus"), False)
        )
        post_commit = PostCommitRuntimeConfig(
            enabled=post_commit_enabled,
            idle_trigger_ms=_bounded_int(post_commit_settings.get("idleTriggerMs"), 180, 40, 3000),
            min_delta_chars=_bounded_int(post_commit_settings.get("minDeltaChars"), 1, 1, 32),
            max_calls_per_10s=_bounded_int(post_commit_settings.get("maxCallsPer10s"), 6, 0, 10),
            cooldown_ms=_bounded_int(post_commit_settings.get("cooldownMs"), 0, 0, 10000),
            show_pending_status=show_pending,
            pending_status_delay_ms=_bounded_int(
                post_commit_settings.get("pendingStatusDelayMs"), 150, 0, 3000
            ),
            panel_ttl_ms=_bounded_int(post_commit_settings.get("panelTtlMs"), 4000, 500, 30000),
            max_candidates=max_candidates,
            completion_ttl_ms=profile.post_commit_completion_ttl_ms,
            model_budget_ms=profile.post_commit_model_budget_ms,
            model_hard_timeout_ms=profile.post_commit_model_hard_timeout_ms,
        )

        hybrid_enabled = _bool_override(
            self.environ,
            "RAG_IME_RUNTIME_OVERRIDE_HYBRID_RAG_ENABLED",
            _bool_value(hybrid.get("enabled"), True),
            experiment_overrides,
        )
        requested_direct_display = _bool_override(
            self.environ,
            "RAG_IME_RUNTIME_OVERRIDE_RAG_DIRECT_DISPLAY",
            _bool_value(self.environ.get("RAG_IME_RAG_DIRECT_DISPLAY"), False),
            experiment_overrides,
        )
        direct_display = bool(profile.rag_direct_display and requested_direct_display)
        if requested_direct_display and not direct_display:
            safety_clamps.append("rag_direct_display_disabled_by_profile")
        embedding_provider = _string_value(self.environ.get("RAG_IME_EMBEDDING_PROVIDER")).lower()
        vector_available = embedding_provider not in {"", "none", "disabled", "off"}
        if embedding_provider in {"openai", "openai-compatible"}:
            vector_available = bool(
                _string_value(self.environ.get("RAG_IME_EMBEDDING_BASE_URL"))
                and _string_value(self.environ.get("RAG_IME_EMBEDDING_MODEL"))
            )
        rag_lane_items: list[tuple[str, bool]] = []
        for lane in _RAG_LANES:
            requested = _bool_value(rag_lanes_settings.get(_settings_rag_lane(lane)), True)
            enabled = requested
            if lane in {"vector_raw", "vector_tag_boost"} and not vector_available:
                enabled = False
                if requested:
                    safety_clamps.append(f"{lane}_unavailable")
            rag_lane_items.append((lane, enabled))
        rag_lanes = tuple(rag_lane_items)
        rag_weights = tuple(
            (
                lane,
                _bounded_float(
                    rag_weights_settings.get(_settings_rag_lane(lane)),
                    _DEFAULT_RAG_WEIGHTS[lane],
                    0.0,
                    5.0,
                ),
            )
            for lane in _RAG_LANES
        )
        hybrid_rag = HybridRuntimeConfig(
            enabled=bool(profile.hybrid_rag_core and hybrid_enabled),
            budget_ms=_bounded_int(hybrid.get("budgetMs"), 400, 1, 5000),
            direct_display=direct_display,
            lanes=rag_lanes,
            weights=rag_weights,
        )
        memory = MemoryRuntimeConfig(enabled=_bool_value(memory_settings.get("enabled"), True))

        profile_id = _string_value(
            self.environ.get("RAG_IME_RUNTIME_OVERRIDE_MODEL_PROFILE")
            or self.environ.get("RAG_IME_MLX_PROFILE")
            or self.environ.get("RAG_IME_PREDICTOR_PROFILE")
            or models.get("hot")
            or "custom"
        )
        if "RAG_IME_RUNTIME_OVERRIDE_MODEL_PROFILE" in self.environ:
            experiment_overrides.append("RAG_IME_RUNTIME_OVERRIDE_MODEL_PROFILE")
        model_path = _string_value(
            self.environ.get("RAG_IME_RUNTIME_OVERRIDE_MODEL_PATH")
            or self.environ.get("RAG_IME_MLX_MODEL")
            or models.get("path")
            or ""
        )
        if "RAG_IME_RUNTIME_OVERRIDE_MODEL_PATH" in self.environ:
            experiment_overrides.append("RAG_IME_RUNTIME_OVERRIDE_MODEL_PATH")
        model = ModelRuntimeConfig(profile_id=profile_id, model_path=model_path)

        source_badges = SourceBadgeRuntimeConfig(
            enabled=_bool_override(
                self.environ,
                "RAG_IME_RUNTIME_OVERRIDE_SHOW_SOURCE_BADGES",
                _bool_value(display.get("showSourceBadge"), True),
                experiment_overrides,
            ),
            items=_string_pairs(_nested_mapping(display, "badges")),
        )
        source_colors = _string_pairs(_nested_mapping(display, "colors"))
        overlay = OverlayRuntimeConfig(
            candidate_font_size=_bounded_int(display.get("candidateFontSize"), 14, 11, 24),
            max_width=_bounded_int(display.get("maxWidth"), 520, 320, 760),
            fade_animation=_bool_value(display.get("fadeAnimation"), True),
            panel_style=_enum_value(display.get("panelStyle"), {"compact", "expanded"}, "compact"),
        )
        active_rag = ActiveRagRuntimeConfig(
            enabled=_bool_value(active_rag_settings.get("enabled"), True),
            shortcut=_string_value(active_rag_settings.get("shortcut")) or "ctrl+.",
            latency_budget_ms=_bounded_int(
                active_rag_settings.get("latencyBudgetMs"),
                8000,
                2000,
                30000,
            ),
        )
        post_commit_number_keys = _enum_override(
            self.environ,
            "RAG_IME_RUNTIME_OVERRIDE_POST_COMMIT_NUMBER_KEYS",
            _string_value(post_commit_settings.get("numberKeys") or "pass_through"),
            {"pass_through", "select_prediction"},
            experiment_overrides,
        )
        key_policy = KeyPolicyRuntimeConfig(
            composition_number_keys="select_rime_candidate",
            composition_tab="rime_default",
            composition_option_number="disabled",
            composition_escape="rime_cancel",
            post_commit_number_keys=post_commit_number_keys,
            tab_action=_enum_value(
                post_commit_settings.get("tabAction"),
                {"accept_top_prediction", "rime_default", "disabled"},
                "accept_top_prediction",
            ),
            option_number=_string_value(
                post_commit_settings.get("optionNumber") or "select_prediction_by_ordinal"
            ),
            escape=_string_value(post_commit_settings.get("escape") or "dismiss_prediction"),
        )

        configuration = {
            "schemaVersion": RUNTIME_CONFIG_SCHEMA_VERSION,
            "settingsRevision": settings_revision,
            "profile": profile.name,
            "composition": {"aiEnabled": composition_ai, "showOnlyRime": not composition_ai},
            "foregroundContext": {
                "strict": profile.strict_foreground_context,
                "maxFreshnessMs": profile.foreground_context_max_freshness_ms,
            },
            "postCommit": post_commit.payload(),
            "hybridRag": hybrid_rag.payload(),
            "memory": memory.payload(),
            "model": model.payload(),
            "sourceBadges": source_badges.payload(),
            "sourceColors": dict(source_colors),
            "overlayConfig": overlay.payload(expires_after_ms=post_commit.panel_ttl_ms),
            "activeRag": active_rag.payload(),
            "keyPolicy": key_policy.payload(),
            "experimentOverrides": sorted(set(experiment_overrides)),
            "safetyClamps": sorted(set(safety_clamps)),
        }
        snapshot_hash = _snapshot_hash(configuration)
        runtime_revision = self.store.resolve_runtime_config_revision(
            snapshot_hash=snapshot_hash,
            settings_revision=settings_revision,
            profile=profile.name,
        )
        return RuntimeConfigSnapshot(
            runtime_revision=runtime_revision,
            settings_revision=settings_revision,
            snapshot_hash=snapshot_hash,
            profile=profile.name,
            composition_ai=composition_ai,
            show_only_rime=not composition_ai,
            foreground_context_max_freshness_ms=profile.foreground_context_max_freshness_ms,
            strict_foreground_context=profile.strict_foreground_context,
            post_commit=post_commit,
            hybrid_rag=hybrid_rag,
            memory=memory,
            model=model,
            source_badges=source_badges,
            source_colors=source_colors,
            overlay=overlay,
            active_rag=active_rag,
            key_policy=key_policy,
            experiment_overrides=tuple(sorted(set(experiment_overrides))),
            safety_clamps=tuple(sorted(set(safety_clamps))),
        )


def _snapshot_hash(payload: Mapping[str, object]) -> str:
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def _nested_mapping(value: Mapping[str, object], key: str) -> dict[str, object]:
    nested = value.get(key)
    return dict(nested) if isinstance(nested, Mapping) else {}


def _canonical_rag_lane(value: str) -> str:
    text = str(value or "").strip()
    if text in _RAG_LANE_SETTING_NAMES:
        return text
    reverse = {setting: lane for lane, setting in _RAG_LANE_SETTING_NAMES.items()}
    return reverse.get(text, text)


def _settings_rag_lane(value: str) -> str:
    lane = _canonical_rag_lane(value)
    return _RAG_LANE_SETTING_NAMES.get(lane, lane)


def _mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise TypeError("runtime settings section must be a dictionary")
    return value


def _string_pairs(value: Mapping[str, object]) -> tuple[tuple[str, str], ...]:
    return tuple(sorted((str(key), _string_value(item)) for key, item in value.items()))


def _string_value(value: object) -> str:
    return str(value or "").strip()


def _bool_value(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    normalized = str(value or "").strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _bounded_int(value: object, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def _bounded_float(value: object, default: float, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def _bool_override(
    environ: Mapping[str, str],
    key: str,
    default: bool,
    applied: list[str],
) -> bool:
    if key not in environ:
        return default
    applied.append(key)
    return _bool_value(environ.get(key), default)


def _int_override(
    environ: Mapping[str, str],
    key: str,
    default: int,
    minimum: int,
    maximum: int,
    applied: list[str],
) -> int:
    if key not in environ:
        return default
    applied.append(key)
    return _bounded_int(environ.get(key), default, minimum, maximum)


def _enum_override(
    environ: Mapping[str, str],
    key: str,
    default: str,
    allowed: set[str],
    applied: list[str],
) -> str:
    if key not in environ:
        return _enum_value(default, allowed, default)
    applied.append(key)
    return _enum_value(environ.get(key), allowed, default)


def _enum_value(value: object, allowed: set[str], default: str) -> str:
    normalized = _string_value(value)
    return normalized if normalized in allowed else default
