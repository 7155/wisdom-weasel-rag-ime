from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from .deepseek_memory_organizer import (
    OWNER_MEMORY_CURATION_SCHEMA_VERSION,
    _normalize_owner_memory_curation,
    _owner_memory_model_bundle,
    _owner_memory_system_prompt,
)
from .memory_generator import _extract_json_object
from .text_utils import compact_whitespace


class LocalMlxMemoryOrganizerError(RuntimeError):
    pass


class LocalMlxMemoryOrganizer:
    """Run owner-memory curation entirely on the local Apple Silicon device."""

    provider_name = "local-mlx"

    def __init__(
        self,
        model_path: str | Path,
        *,
        max_tokens: int = 8_192,
        completion: Callable[[Sequence[Mapping[str, str]]], str] | None = None,
    ) -> None:
        self.model_path = Path(model_path).expanduser().resolve()
        if completion is None and not self.model_path.is_dir():
            raise FileNotFoundError(self.model_path)
        self.max_tokens = max(1_024, min(int(max_tokens), 16_384))
        self._completion = completion
        self._model: Any = None
        self._tokenizer: Any = None

    def curate_owner_memory(
        self,
        *,
        bundle: dict[str, object],
        project: str,
        owner_kind: str,
        owner_id: str,
        instruction: str = "",
    ) -> dict[str, object]:
        model_bundle = _owner_memory_model_bundle(bundle)
        effective_instruction = compact_whitespace(instruction)[:600] or (
            "只保留跨会话仍有价值的事实、偏好、决定、约束和持续计划；噪声进入 not_for_memory。"
        )
        messages = [
            {"role": "system", "content": _owner_memory_system_prompt()},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "project": project,
                        "owner": {"kind": owner_kind, "id": owner_id},
                        "instruction": effective_instruction,
                        "bundle": model_bundle,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            },
        ]
        started = time.perf_counter()
        raw_text = self._generate(messages)
        try:
            raw_payload = _extract_json_object(raw_text)
        except Exception as exc:
            raise LocalMlxMemoryOrganizerError(
                "local MLX memory organizer did not return a JSON object"
            ) from exc
        payload = _normalize_owner_memory_curation(
            raw_payload,
            model_bundle=model_bundle,
        )
        repair_count = 0
        uncovered = _uncovered_remember_refs(payload, model_bundle=model_bundle)
        if uncovered:
            repair_count = 1
            payload = self._repair_uncovered_memory(
                payload,
                model_bundle=model_bundle,
                project=project,
                owner_kind=owner_kind,
                owner_id=owner_id,
                instruction=effective_instruction,
                uncovered=uncovered,
            )
            remaining = _uncovered_remember_refs(payload, model_bundle=model_bundle)
            if remaining:
                raise LocalMlxMemoryOrganizerError(
                    "local MLX organizer left remember evidence without an Atom: "
                    + ", ".join(remaining)
                )
        payload["schemaVersion"] = OWNER_MEMORY_CURATION_SCHEMA_VERSION
        payload["provider"] = self.provider_name
        payload["model"] = self.model_path.name
        payload["instruction"] = effective_instruction
        payload["modelDiagnostics"] = {
            "localOnly": True,
            "externalRequestCount": 0,
            "responseChars": len(raw_text),
            "repairCount": repair_count,
        }
        payload["modelBundleStats"] = {
            "chars": len(json.dumps(model_bundle, ensure_ascii=False, sort_keys=True)),
            "sourceCount": len(model_bundle.get("inputs") or []),
            "existingBookCount": len(model_bundle.get("existingMemoryBooks") or []),
            "existingAtomCount": len(model_bundle.get("existingMemoryAtoms") or []),
            "activitySegmentCount": len(
                dict(model_bundle.get("activityContext") or {}).get("segments") or []
            ),
            "conversationMessageCount": len(
                dict(model_bundle.get("agentConversationContext") or {}).get("messages") or []
            ),
        }
        payload["elapsedMs"] = int((time.perf_counter() - started) * 1_000)
        return payload

    def _repair_uncovered_memory(
        self,
        payload: dict[str, object],
        *,
        model_bundle: dict[str, object],
        project: str,
        owner_kind: str,
        owner_id: str,
        instruction: str,
        uncovered: Sequence[str],
    ) -> dict[str, object]:
        missing = set(uncovered)
        repair_bundle = {
            **model_bundle,
            "inputs": [
                dict(item)
                for item in model_bundle.get("inputs") or []
                if isinstance(item, Mapping)
                and str(item.get("sourceRef") or "") in missing
            ],
        }
        repair_messages = [
            {
                "role": "system",
                "content": _owner_memory_system_prompt()
                + " 这是契约修复轮：只要仍判定 remember，就必须生成至少一个引用该证据 "
                "sourceEventIds 的 memoryAtom；若它其实不值得长期保存，应改判 not_for_memory。",
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "project": project,
                        "owner": {"kind": owner_kind, "id": owner_id},
                        "instruction": instruction,
                        "missingRememberSourceRefs": list(uncovered),
                        "bundle": repair_bundle,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            },
        ]
        try:
            repaired_raw = _extract_json_object(self._generate(repair_messages))
        except Exception as exc:
            raise LocalMlxMemoryOrganizerError(
                "local MLX memory contract repair did not return JSON"
            ) from exc
        repaired = _normalize_owner_memory_curation(
            repaired_raw,
            model_bundle=repair_bundle,
        )
        decision_by_ref = {
            str(item.get("sourceRef") or ""): dict(item)
            for item in payload.get("sourceDecisions") or []
            if isinstance(item, Mapping)
        }
        for item in repaired.get("sourceDecisions") or []:
            if isinstance(item, Mapping):
                decision_by_ref[str(item.get("sourceRef") or "")] = dict(item)
        result = dict(payload)
        result["sourceDecisions"] = [
            decision_by_ref[str(item.get("sourceRef") or "")]
            for item in model_bundle.get("inputs") or []
            if isinstance(item, Mapping)
            and str(item.get("sourceRef") or "") in decision_by_ref
        ]
        for key in (
            "topicBooks",
            "memoryAtoms",
            "semanticGroups",
            "semanticTags",
            "tagMerges",
            "tagEdges",
            "supersedes",
            "warnings",
        ):
            result[key] = [
                *(
                    item
                    for item in result.get(key) or []
                    if isinstance(item, Mapping) or key == "warnings"
                ),
                *(
                    item
                    for item in repaired.get(key) or []
                    if isinstance(item, Mapping) or key == "warnings"
                ),
            ]
        return result

    def _generate(self, messages: Sequence[Mapping[str, str]]) -> str:
        if self._completion is not None:
            return str(self._completion(messages))
        self._ensure_loaded()
        try:
            from mlx_lm import generate  # type: ignore
            from mlx_lm.sample_utils import make_sampler  # type: ignore

            prompt = self._tokenizer.apply_chat_template(
                [dict(message) for message in messages],
                tokenize=False,
                add_generation_prompt=True,
                enable_thinking=False,
            )
            return str(
                generate(
                    self._model,
                    self._tokenizer,
                    prompt,
                    max_tokens=self.max_tokens,
                    sampler=make_sampler(temp=0.0),
                    verbose=False,
                )
            )
        except Exception as exc:
            raise LocalMlxMemoryOrganizerError(
                f"local MLX memory generation failed: {type(exc).__name__}: {exc}"
            ) from exc

    def _ensure_loaded(self) -> None:
        if self._model is not None and self._tokenizer is not None:
            return
        try:
            from mlx_lm import load  # type: ignore

            self._model, self._tokenizer = load(str(self.model_path))
        except Exception as exc:
            raise LocalMlxMemoryOrganizerError(
                f"local MLX memory model failed to load: {type(exc).__name__}: {exc}"
            ) from exc


def _uncovered_remember_refs(
    payload: Mapping[str, object],
    *,
    model_bundle: Mapping[str, object],
) -> list[str]:
    event_ids_by_ref = {
        str(item.get("sourceRef") or ""): {
            int(event_id)
            for event_id in item.get("sourceEventIds") or []
            if str(event_id).isdigit() and int(event_id) > 0
        }
        for item in model_bundle.get("inputs") or []
        if isinstance(item, Mapping)
    }
    covered_event_ids = {
        int(event_id)
        for atom in payload.get("memoryAtoms") or []
        if isinstance(atom, Mapping)
        for event_id in atom.get("sourceEventIds") or []
        if str(event_id).isdigit() and int(event_id) > 0
    }
    return [
        source_ref
        for decision in payload.get("sourceDecisions") or []
        if isinstance(decision, Mapping)
        and decision.get("disposition") == "remember"
        and (source_ref := str(decision.get("sourceRef") or ""))
        and not (event_ids_by_ref.get(source_ref, set()) & covered_event_ids)
    ]
