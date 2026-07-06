from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal, Mapping


DeepSeekScene = Literal["offline_compile", "post_commit", "active_rag", "passive_per_key"]


@dataclass(frozen=True)
class HybridRagRuntimeFlags:
    hybrid_rag_core: bool = False
    deepseek_offline_compile: bool = False
    deepseek_post_commit: bool = False
    deepseek_active_rag: bool = False
    deepseek_passive_per_key: bool = False
    deepseek_stream: bool = True
    rag_core_v3_budget_ms: int = 25


def load_hybrid_rag_runtime_flags(env: Mapping[str, str] | None = None) -> HybridRagRuntimeFlags:
    source = os.environ if env is None else env
    return HybridRagRuntimeFlags(
        hybrid_rag_core=_env_flag(source, "RAG_IME_HYBRID_RAG_CORE", default=False),
        deepseek_offline_compile=_env_flag(source, "RAG_IME_DEEPSEEK_OFFLINE_COMPILE", default=False),
        deepseek_post_commit=_env_flag(source, "RAG_IME_DEEPSEEK_POST_COMMIT", default=False),
        deepseek_active_rag=_env_flag(source, "RAG_IME_DEEPSEEK_ACTIVE_RAG", default=False),
        deepseek_passive_per_key=_env_flag(source, "RAG_IME_DEEPSEEK_PASSIVE_PER_KEY", default=False),
        deepseek_stream=_env_flag(source, "RAG_IME_DEEPSEEK_STREAM", default=True),
        rag_core_v3_budget_ms=_env_int(source, "RAG_IME_RAG_CORE_V3_BUDGET_MS", default=25, minimum=1),
    )


def deepseek_scene_enabled(scene: DeepSeekScene, flags: HybridRagRuntimeFlags | None = None) -> bool:
    resolved = flags or load_hybrid_rag_runtime_flags()
    if scene == "offline_compile":
        return resolved.deepseek_offline_compile
    if scene == "post_commit":
        return resolved.deepseek_post_commit
    if scene == "active_rag":
        return resolved.deepseek_active_rag
    if scene == "passive_per_key":
        return False
    raise ValueError(f"unknown DeepSeek scene: {scene}")


def assert_deepseek_scene_allowed(scene: DeepSeekScene, flags: HybridRagRuntimeFlags | None = None) -> None:
    resolved = flags or load_hybrid_rag_runtime_flags()
    if scene == "passive_per_key":
        if resolved.deepseek_passive_per_key:
            raise RuntimeError("DeepSeek passive per-key path is disabled in v1")
        raise RuntimeError("DeepSeek passive per-key path is disabled; no remote model may run on /rime-suggest")
    if deepseek_scene_enabled(scene, resolved):
        return
    env_name = {
        "offline_compile": "RAG_IME_DEEPSEEK_OFFLINE_COMPILE",
        "post_commit": "RAG_IME_DEEPSEEK_POST_COMMIT",
        "active_rag": "RAG_IME_DEEPSEEK_ACTIVE_RAG",
    }.get(scene)
    if env_name is None:
        raise ValueError(f"unknown DeepSeek scene: {scene}")
    raise RuntimeError(f"DeepSeek scene {scene!r} requires {env_name}=1")


def assert_deepseek_not_called(scene: str, *, provider_name: str = "", model: str = "") -> None:
    if scene != "passive_per_key":
        return
    provider = f"{provider_name} {model}".lower()
    if "deepseek" in provider:
        raise RuntimeError("DeepSeek must not be called from passive per-key /rime-suggest in v1")


def _env_flag(env: Mapping[str, str], key: str, *, default: bool) -> bool:
    raw = str(env.get(key, "")).strip().lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


def _env_int(env: Mapping[str, str], key: str, *, default: int, minimum: int | None = None) -> int:
    raw = str(env.get(key, "")).strip()
    if not raw:
        value = default
    else:
        try:
            value = int(raw)
        except ValueError:
            value = default
    if minimum is not None:
        value = max(minimum, value)
    return value
