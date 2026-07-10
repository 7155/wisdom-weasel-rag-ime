from __future__ import annotations

import argparse
import json
import shlex
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class RuntimeProfile:
    name: str
    squirrel_latency_budget_ms: int
    squirrel_timeout_ms: int
    post_commit_completion_ttl_ms: int
    post_commit_model_hard_timeout_ms: int
    post_commit_model_budget_ms: int
    foreground_context_max_freshness_ms: int
    strict_foreground_context: bool
    assistant_pending_preview: bool
    hybrid_rag_core: bool
    rag_direct_display: bool
    composition_ai: bool
    pinyin_constrained_model: bool

    def shell_environment(self) -> dict[str, str]:
        return {
            "RAG_IME_PROFILE_NAME": self.name,
            "RAG_IME_PROFILE_SQUIRREL_LATENCY_BUDGET_MS": str(self.squirrel_latency_budget_ms),
            "RAG_IME_PROFILE_SQUIRREL_TIMEOUT_MS": str(self.squirrel_timeout_ms),
            "RAG_IME_PROFILE_POST_COMMIT_COMPLETION_TTL_MS": str(self.post_commit_completion_ttl_ms),
            "RAG_IME_PROFILE_POST_COMMIT_MODEL_HARD_TIMEOUT_MS": str(self.post_commit_model_hard_timeout_ms),
            "RAG_IME_PROFILE_POST_COMMIT_MODEL_BUDGET_MS": str(self.post_commit_model_budget_ms),
            "RAG_IME_PROFILE_FOREGROUND_CONTEXT_MAX_FRESHNESS_MS": str(
                self.foreground_context_max_freshness_ms
            ),
            "RAG_IME_PROFILE_REQUIRE_FOREGROUND_CONTEXT": _flag(self.strict_foreground_context),
            "RAG_IME_PROFILE_ASSISTANT_PENDING_PREVIEW": _flag(self.assistant_pending_preview),
            "RAG_IME_PROFILE_HYBRID_RAG_CORE": _flag(self.hybrid_rag_core),
            "RAG_IME_PROFILE_RAG_DIRECT_DISPLAY": _flag(self.rag_direct_display),
            "RAG_IME_PROFILE_COMPOSITION_AI": _flag(self.composition_ai),
            "RAG_IME_PROFILE_PINYIN_CONSTRAINED_MODEL": _flag(self.pinyin_constrained_model),
        }


PROFILES: dict[str, RuntimeProfile] = {
    "safe-dev": RuntimeProfile(
        name="safe-dev",
        squirrel_latency_budget_ms=300,
        squirrel_timeout_ms=250,
        post_commit_completion_ttl_ms=6000,
        post_commit_model_hard_timeout_ms=3000,
        post_commit_model_budget_ms=450,
        foreground_context_max_freshness_ms=700,
        strict_foreground_context=True,
        assistant_pending_preview=False,
        hybrid_rag_core=False,
        rag_direct_display=False,
        composition_ai=False,
        pinyin_constrained_model=False,
    ),
    "v1-proof": RuntimeProfile(
        name="v1-proof",
        squirrel_latency_budget_ms=900,
        squirrel_timeout_ms=1200,
        post_commit_completion_ttl_ms=12000,
        post_commit_model_hard_timeout_ms=12000,
        post_commit_model_budget_ms=900,
        foreground_context_max_freshness_ms=700,
        strict_foreground_context=True,
        assistant_pending_preview=False,
        hybrid_rag_core=True,
        rag_direct_display=False,
        composition_ai=False,
        pinyin_constrained_model=False,
    ),
    "production": RuntimeProfile(
        name="production",
        squirrel_latency_budget_ms=900,
        squirrel_timeout_ms=1200,
        post_commit_completion_ttl_ms=12000,
        post_commit_model_hard_timeout_ms=12000,
        post_commit_model_budget_ms=900,
        foreground_context_max_freshness_ms=700,
        strict_foreground_context=True,
        assistant_pending_preview=False,
        hybrid_rag_core=True,
        rag_direct_display=False,
        composition_ai=False,
        pinyin_constrained_model=False,
    ),
}


def get_runtime_profile(name: str) -> RuntimeProfile:
    normalized = str(name or "").strip().lower()
    try:
        return PROFILES[normalized]
    except KeyError as exc:
        raise ValueError(f"unknown runtime profile: {name}; expected one of {', '.join(PROFILES)}") from exc


def _flag(value: bool) -> str:
    return "1" if value else "0"


def main() -> int:
    parser = argparse.ArgumentParser(description="Print the canonical RAG-IME runtime profile.")
    parser.add_argument("--profile", default="v1-proof", choices=tuple(PROFILES))
    parser.add_argument("--format", default="json", choices=("json", "shell"))
    args = parser.parse_args()
    profile = get_runtime_profile(args.profile)
    if args.format == "shell":
        for key, value in profile.shell_environment().items():
            print(f"{key}={shlex.quote(value)}")
    else:
        print(json.dumps(asdict(profile), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
