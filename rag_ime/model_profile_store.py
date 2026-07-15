from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .model_profiles import DEFAULT_MODEL_PROFILES, ModelProfile, profile_by_id, validate_profile


class ModelProfileStore:
    def __init__(self, profiles: tuple[ModelProfile, ...] = DEFAULT_MODEL_PROFILES) -> None:
        self._profiles = {profile.id: profile for profile in profiles}

    @classmethod
    def from_json_file(cls, path: Path) -> "ModelProfileStore":
        if not path.exists():
            return cls()
        payload = json.loads(path.read_text(encoding="utf-8"))
        raw_profiles = payload.get("profiles") if isinstance(payload, dict) else None
        if not isinstance(raw_profiles, list):
            return cls()
        profiles = tuple(_profile_from_payload(item) for item in raw_profiles if isinstance(item, dict))
        return cls(profiles or DEFAULT_MODEL_PROFILES)

    def resolve(self, profile_id: str) -> ModelProfile:
        normalized = str(profile_id or "").strip().lower().replace("-", "_")
        return self._profiles.get(normalized) or profile_by_id(normalized)

    def payload(self) -> dict[str, Any]:
        profiles = [profile.to_payload() for profile in self._profiles.values()]
        return {
            "schemaVersion": "rag-ime.model-profiles.v1",
            "profiles": profiles,
            "errors": {
                item["id"]: errors
                for item in profiles
                if (errors := validate_profile(self.resolve(str(item["id"]))))
            },
        }


def _profile_from_payload(payload: dict[str, Any]) -> ModelProfile:
    sampling = dict(payload.get("sampling") or {})
    return ModelProfile(
        id=str(payload.get("id") or ""),
        lane=str(payload.get("lane") or "hot"),
        model_path=str(payload.get("modelPath") or payload.get("model_path") or ""),
        adapter_path=str(payload.get("adapterPath") or payload.get("adapter_path") or ""),
        max_tokens=int(payload.get("maxTokens") or payload.get("max_tokens") or 32),
        target_candidates=int(payload.get("targetCandidates") or payload.get("target_candidates") or 3),
        latency_budget_ms=int(payload.get("latencyBudgetMs") or payload.get("latency_budget_ms") or 500),
        resident=bool(payload.get("resident", True)),
        prefix_cache=bool(payload.get("prefixCache", payload.get("prefix_cache", True))),
        sequence_fork=bool(payload.get("sequenceFork", payload.get("sequence_fork", True))),
        idle_unload_ms=int(payload.get("idleUnloadMs") or payload.get("idle_unload_ms") or 0),
        append_only=bool(payload.get("appendOnly", payload.get("append_only", False))),
        prompt_mode=str(payload.get("promptMode") or payload.get("prompt_mode") or "chat-json"),
        decode_strategy=str(payload.get("decodeStrategy") or payload.get("decode_strategy") or "chat-json"),
        branch_count=int(payload.get("branchCount") or payload.get("branch_count") or 1),
        stream_first=bool(payload.get("streamFirst", payload.get("stream_first", True))),
        sampling_temperature=float(
            sampling.get("temperature")
            if sampling.get("temperature") is not None
            else payload.get("sampling_temperature", 0.15)
        ),
        sampling_top_p=float(
            sampling.get("topP")
            if sampling.get("topP") is not None
            else payload.get("sampling_top_p", 0.85)
        ),
        sampling_top_k=int(
            sampling.get("topK")
            if sampling.get("topK") is not None
            else payload.get("sampling_top_k", 0)
        ),
        max_candidate_chars=int(
            payload.get("maxCandidateChars") or payload.get("max_candidate_chars") or 24
        ),
        expected_hidden_layers=int(
            dict(payload.get("expectedArchitecture") or {}).get("numHiddenLayers")
            or payload.get("expected_hidden_layers")
            or 0
        ),
        expected_attention_heads=int(
            dict(payload.get("expectedArchitecture") or {}).get("numAttentionHeads")
            or payload.get("expected_attention_heads")
            or 0
        ),
        expected_vocab_size=int(
            dict(payload.get("expectedArchitecture") or {}).get("vocabSize")
            or payload.get("expected_vocab_size")
            or 0
        ),
    )
