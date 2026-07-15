from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ModelProfile:
    id: str
    lane: str
    model_path: str
    adapter_path: str = ""
    max_tokens: int = 32
    target_candidates: int = 3
    latency_budget_ms: int = 500
    resident: bool = True
    prefix_cache: bool = True
    sequence_fork: bool = True
    idle_unload_ms: int = 0
    append_only: bool = False
    prompt_mode: str = "chat-json"
    decode_strategy: str = "chat-json"
    branch_count: int = 1
    stream_first: bool = True
    sampling_temperature: float = 0.15
    sampling_top_p: float = 0.85
    sampling_top_k: int = 0
    max_candidate_chars: int = 24
    expected_hidden_layers: int = 0
    expected_attention_heads: int = 0
    expected_vocab_size: int = 0

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        return {
            "id": payload["id"],
            "lane": payload["lane"],
            "modelPath": payload["model_path"],
            "adapterPath": payload["adapter_path"],
            "maxTokens": payload["max_tokens"],
            "targetCandidates": payload["target_candidates"],
            "latencyBudgetMs": payload["latency_budget_ms"],
            "resident": payload["resident"],
            "prefixCache": payload["prefix_cache"],
            "sequenceFork": payload["sequence_fork"],
            "idleUnloadMs": payload["idle_unload_ms"],
            "appendOnly": payload["append_only"],
            "promptMode": payload["prompt_mode"],
            "decodeStrategy": payload["decode_strategy"],
            "branchCount": payload["branch_count"],
            "streamFirst": payload["stream_first"],
            "sampling": {
                "temperature": payload["sampling_temperature"],
                "topP": payload["sampling_top_p"],
                "topK": payload["sampling_top_k"],
            },
            "maxCandidateChars": payload["max_candidate_chars"],
            "expectedArchitecture": {
                "numHiddenLayers": payload["expected_hidden_layers"],
                "numAttentionHeads": payload["expected_attention_heads"],
                "vocabSize": payload["expected_vocab_size"],
            },
        }


DEFAULT_MODEL_PROFILES: tuple[ModelProfile, ...] = (
    ModelProfile(
        id="minimind_ime_v2",
        lane="hot",
        model_path="~/Library/Application Support/RagIme/Models/minimind-ime-v2",
        max_tokens=8,
        target_candidates=3,
        latency_budget_ms=900,
        resident=True,
        prefix_cache=False,
        sequence_fork=False,
        append_only=True,
        prompt_mode="base-completion",
        decode_strategy="seeded-logit-branches-v2",
        branch_count=4,
        stream_first=False,
    ),
    ModelProfile(
        id="minimind_ime_100m_v1",
        lane="hot",
        model_path="~/Library/Application Support/RagIme/Models/minimind-ime-100m-user-daily-core-v1",
        max_tokens=16,
        target_candidates=3,
        latency_budget_ms=1200,
        resident=True,
        prefix_cache=False,
        sequence_fork=True,
        append_only=True,
        prompt_mode="base-completion",
        decode_strategy="bos-sampled-completion-v1",
        branch_count=8,
        stream_first=False,
        sampling_temperature=0.42,
        sampling_top_p=0.92,
        sampling_top_k=50,
        max_candidate_chars=24,
        expected_hidden_layers=14,
        expected_attention_heads=12,
        expected_vocab_size=16384,
    ),
    ModelProfile(
        id="minimind_ime_60m_v8",
        lane="hot",
        model_path="~/Library/Application Support/RagIme/Models/minimind-ime-60m-daily-short-final-v8",
        max_tokens=8,
        target_candidates=3,
        latency_budget_ms=700,
        resident=True,
        prefix_cache=False,
        sequence_fork=True,
        append_only=True,
        prompt_mode="base-completion",
        decode_strategy="bos-short-completion-v8",
        branch_count=8,
        stream_first=False,
        sampling_temperature=0.38,
        sampling_top_p=0.90,
        sampling_top_k=50,
        max_candidate_chars=8,
        expected_hidden_layers=8,
        expected_attention_heads=8,
        expected_vocab_size=6400,
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
        prompt_mode="chat-json",
        decode_strategy="chat-json",
        branch_count=1,
        stream_first=True,
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
        prompt_mode="chat-json",
        decode_strategy="chat-json",
        branch_count=1,
        stream_first=False,
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
        prompt_mode="chat-json",
        decode_strategy="chat-json",
        branch_count=1,
        stream_first=False,
    ),
)

SUPPORTED_DECODE_STRATEGIES = {
    "chat-json",
    "seeded-logit-branches-v2",
    "bos-sampled-completion-v1",
    "bos-short-completion-v8",
}


def profile_by_id(profile_id: str) -> ModelProfile:
    normalized = normalize_profile_id(profile_id)
    aliases = {
        "minimind": "minimind_ime_v2",
        "minimind_v2": "minimind_ime_v2",
        "base_completion": "minimind_ime_v2",
        "minimind_100m": "minimind_ime_100m_v1",
        "minimind_60m": "minimind_ime_60m_v8",
        "ime_hot": "qwen3_06b_ime_hot",
        "instant": "qwen3_06b_ime_hot",
        "hot": "qwen3_06b_ime_hot",
        "qwen_hot": "qwen3_06b_ime_hot",
        "ime_post_commit": "qwen25_15b_ime_main",
        "main": "qwen25_15b_ime_main",
        "post_commit": "qwen25_15b_ime_main",
        "ime_quality": "qwen3_17b_ime_quality",
        "quality": "qwen3_17b_ime_quality",
    }
    normalized = aliases.get(normalized, normalized)
    for profile in DEFAULT_MODEL_PROFILES:
        if profile.id == normalized:
            return profile
    raise ValueError(f"unknown model profile: {profile_id or '<empty>'}")


def normalize_profile_id(profile_id: str) -> str:
    return str(profile_id or "").strip().lower().replace("-", "_")


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
    if profile.max_tokens <= 0:
        errors.append("max tokens must be positive")
    if profile.branch_count <= 0:
        errors.append("branch count must be positive")
    if profile.sampling_temperature < 0:
        errors.append("sampling temperature must not be negative")
    if not 0 < profile.sampling_top_p <= 1:
        errors.append("sampling top-p must be in (0, 1]")
    if profile.sampling_top_k < 0:
        errors.append("sampling top-k must not be negative")
    if profile.max_candidate_chars <= 0:
        errors.append("max candidate chars must be positive")
    if profile.prompt_mode not in {"base-completion", "chat-json", "chat"}:
        errors.append("unsupported prompt mode")
    if profile.prompt_mode == "base-completion" and not profile.decode_strategy:
        errors.append("base-completion profile requires a decode strategy")
    if profile.decode_strategy not in SUPPORTED_DECODE_STRATEGIES:
        errors.append("unsupported decode strategy")
    architecture = (
        profile.expected_hidden_layers,
        profile.expected_attention_heads,
        profile.expected_vocab_size,
    )
    if any(value < 0 for value in architecture):
        errors.append("expected architecture values must not be negative")
    if any(architecture) and not all(architecture):
        errors.append("expected architecture must specify layers, heads, and vocab together")
    return errors


def validate_profile_artifact(profile: ModelProfile, model_path: str | Path) -> list[str]:
    """Validate strict MiniMind geometry without guessing from a directory name."""

    expected = {
        "num_hidden_layers": profile.expected_hidden_layers,
        "num_attention_heads": profile.expected_attention_heads,
        "vocab_size": profile.expected_vocab_size,
    }
    if not any(expected.values()):
        return []
    config_path = Path(model_path).expanduser() / "config.json"
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return [f"model profile {profile.id} requires a readable config.json"]
    errors: list[str] = []
    for field, wanted in expected.items():
        try:
            actual = int(payload.get(field) or 0)
        except (TypeError, ValueError):
            actual = 0
        if actual != wanted:
            errors.append(f"{profile.id} expects {field}={wanted}, got {actual}")
    return errors
