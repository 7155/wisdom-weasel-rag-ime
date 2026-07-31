from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ModelProfile:
    id: str
    lane: str
    model_path: str
    adapter_path: str = ""
    max_tokens: int = 32
    prompt_mode: str = "chat-json"
    temperature: float = 0.15
    top_p: float = 0.85
    target_candidates: int = 3
    latency_budget_ms: int = 500
    resident: bool = True
    prefix_cache: bool = True
    sequence_fork: bool = True
    idle_unload_ms: int = 0
    append_only: bool = False

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        return {
            "id": payload["id"],
            "lane": payload["lane"],
            "modelPath": payload["model_path"],
            "adapterPath": payload["adapter_path"],
            "maxTokens": payload["max_tokens"],
            "promptMode": payload["prompt_mode"],
            "temperature": payload["temperature"],
            "topP": payload["top_p"],
            "targetCandidates": payload["target_candidates"],
            "latencyBudgetMs": payload["latency_budget_ms"],
            "resident": payload["resident"],
            "prefixCache": payload["prefix_cache"],
            "sequenceFork": payload["sequence_fork"],
            "idleUnloadMs": payload["idle_unload_ms"],
            "appendOnly": payload["append_only"],
        }


DEFAULT_MODEL_PROFILES: tuple[ModelProfile, ...] = (
    ModelProfile(
        id="minimind_ime_v2",
        lane="hot",
        model_path="~/Library/Application Support/RagIme/Models/minimind-ime-v2",
        max_tokens=8,
        prompt_mode="base-completion",
        temperature=0.15,
        top_p=0.85,
        target_candidates=3,
        latency_budget_ms=900,
        resident=True,
        prefix_cache=False,
        sequence_fork=False,
        append_only=True,
    ),
    ModelProfile(
        id="qwen3_06b_ime_hot",
        lane="hot",
        model_path="mlx-community/Qwen3-0.6B-4bit",
        adapter_path="adapters/ime-qwen3-0.6b-sft-v1",
        max_tokens=32,
        target_candidates=3,
        latency_budget_ms=500,
        resident=True,
        prefix_cache=True,
        sequence_fork=True,
    ),
    ModelProfile(
        id="qwen25_15b_ime_main",
        lane="main",
        model_path="mlx-community/Qwen2.5-1.5B-Instruct-4bit",
        adapter_path="adapters/ime-qwen25-1.5b-sft-v1",
        max_tokens=48,
        target_candidates=3,
        latency_budget_ms=900,
        resident=True,
        prefix_cache=True,
        sequence_fork=True,
    ),
    ModelProfile(
        id="qwen3_17b_ime_quality",
        lane="quality",
        model_path="mlx-community/Qwen3-1.7B-4bit",
        max_tokens=64,
        target_candidates=5,
        latency_budget_ms=1800,
        resident=False,
        idle_unload_ms=60000,
        prefix_cache=True,
        sequence_fork=False,
        append_only=True,
    ),
)


_MINIMIND_RUNTIME_PROFILE_ALIASES = {
    "base_completion",
    "minimind",
    "minimind_ime_60m_v8",
    "minimind_ime_100m_v1",
    "minimind_ime_v2",
    "minimind_v2",
}


def canonical_runtime_profile_id(profile_id: str) -> str:
    """Map known deployment labels onto their shared inference contract.

    The model registry keeps the exact training/deployment label for provenance
    and rollback. Runtime clients, however, need the stable profile that defines
    prompt mode, sampling defaults and latency budget. Only known compatible
    MiniMind artifacts are aliased; arbitrary custom profiles remain untouched.
    """

    raw = str(profile_id or "").strip().lower()
    normalized = raw.replace("-", "_")
    if normalized in _MINIMIND_RUNTIME_PROFILE_ALIASES:
        return "minimind_ime_v2"
    return raw


def profile_by_id(profile_id: str) -> ModelProfile:
    normalized = normalize_profile_id(canonical_runtime_profile_id(profile_id))
    for profile in DEFAULT_MODEL_PROFILES:
        if profile.id == normalized:
            return profile
    if normalized in {"ime_hot", "instant", "hot", "qwen_hot"}:
        return next(item for item in DEFAULT_MODEL_PROFILES if item.id == "qwen3_06b_ime_hot")
    if normalized in {"ime_post_commit", "main", "post_commit"}:
        return next(item for item in DEFAULT_MODEL_PROFILES if item.lane == "main")
    if normalized in {"ime_quality", "quality"}:
        return next(item for item in DEFAULT_MODEL_PROFILES if item.lane == "quality")
    return DEFAULT_MODEL_PROFILES[0]


def normalize_profile_id(profile_id: str) -> str:
    return str(profile_id or "").strip().lower().replace("-", "_") or "qwen3_06b_ime_hot"


def validate_profile(profile: ModelProfile) -> list[str]:
    errors: list[str] = []
    if profile.lane == "hot" and not profile.resident:
        errors.append("hot profile must be resident")
    if profile.lane == "quality" and not profile.append_only:
        errors.append("quality profile must be append-only")
    if profile.lane != "quality" and profile.idle_unload_ms:
        errors.append("idle unload only applies to quality lane")
    if profile.latency_budget_ms <= 0:
        errors.append("latency budget must be positive")
    if profile.target_candidates <= 0:
        errors.append("target candidates must be positive")
    if not 1 <= profile.max_tokens <= 64:
        errors.append("max tokens must be between 1 and 64")
    if profile.prompt_mode not in {"base-completion", "chat-json"}:
        errors.append("prompt mode must be base-completion or chat-json")
    if not 0.0 <= profile.temperature <= 2.0:
        errors.append("temperature must be between 0 and 2")
    if not 0.0 < profile.top_p <= 1.0:
        errors.append("top p must be greater than 0 and at most 1")
    return errors
