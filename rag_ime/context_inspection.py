from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence


_MODEL_NOISE = re.compile(
    r'(?i)(?:"(?:score|rank|debug|receipt|hash|dispatchId|taskId|rootId)"\s*:|'
    r'<(?:debug|receipt)\b)'
)


def _bytes(value: object) -> bytes:
    if isinstance(value, str):
        return value.encode("utf-8")
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _prefix_bytes(left: bytes, right: bytes) -> int:
    size = min(len(left), len(right))
    index = 0
    while index < size and left[index] == right[index]:
        index += 1
    return index


def _layer_value(value: object) -> object:
    if isinstance(value, Mapping) and "content" in value:
        return value["content"]
    return value


def context_delta(previous: object, current: object) -> dict[str, object]:
    before = _bytes(previous)
    after = _bytes(current)
    prefix = _prefix_bytes(before, after)
    return {
        "schemaVersion": "rag-ime.context-delta.v1",
        "prefixSha256": hashlib.sha256(after[:prefix]).hexdigest(),
        "prefixBytes": prefix,
        "previousBytes": len(before),
        "currentBytes": len(after),
        "deltaBytes": len(after) - prefix,
        "duplicateBytes": prefix,
        "appendOnly": prefix == len(before),
    }


def inspect_context_sequence(
    snapshots: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    violations: list[dict[str, object]] = []
    deltas: list[dict[str, object]] = []
    cache_evidence_rows: list[dict[str, object]] = []
    previous_by_scope: dict[tuple[str, int, str], Mapping[str, object]] = {}

    for index, snapshot in enumerate(snapshots):
        root_id = str(snapshot.get("rootId") or "")
        generation = int(snapshot.get("generation") or 0)
        session_id = str(snapshot.get("sessionId") or "")
        scope = (root_id, generation, session_id)
        layers = list(snapshot.get("layers") or [])
        if [str(item.get("name") or "") for item in layers if isinstance(item, Mapping)] != [
            "system",
            "persona",
            "tools-skills",
            "sealed-room",
            "dynamic-tail",
        ]:
            violations.append({"index": index, "code": "layer_order_changed"})

        provider_body = str(snapshot.get("providerBody") or "")
        if _MODEL_NOISE.search(provider_body):
            violations.append({"index": index, "code": "provider_body_internal_noise"})

        private_refs = {str(value) for value in snapshot.get("privateSessionRefs") or []}
        room_refs = {str(value) for value in snapshot.get("roomContributionRefs") or []}
        if private_refs & room_refs:
            violations.append({"index": index, "code": "private_session_entered_room"})

        sealed = [str(value) for value in snapshot.get("sealedContributionRefs") or []]
        if len(sealed) != len(set(sealed)):
            violations.append({"index": index, "code": "sealed_contribution_duplicated"})

        previous = previous_by_scope.get(scope)
        if previous is not None:
            old_layers = list(previous.get("layers") or [])
            for layer_index in range(min(4, len(old_layers), len(layers))):
                old = old_layers[layer_index]
                new = layers[layer_index]
                delta = context_delta(_layer_value(old), _layer_value(new))
                deltas.append({"index": index, "layer": layer_index + 1, **delta})
                if _bytes(_layer_value(old)) != _bytes(_layer_value(new)):
                    violations.append(
                        {"index": index, "code": "stable_layer_changed", "layer": layer_index + 1}
                    )
            if len(old_layers) >= 5 and len(layers) >= 5:
                delta = context_delta(_layer_value(old_layers[4]), _layer_value(layers[4]))
                deltas.append({"index": index, "layer": 5, **delta})
                if snapshot.get("transition") not in {"compaction", "recovery"} and not delta["appendOnly"]:
                    violations.append({"index": index, "code": "dynamic_tail_not_append_only"})

        usage = snapshot.get("usage")
        usage_map = usage if isinstance(usage, Mapping) else {}
        supports_cache = "cacheRead" in usage_map or "cacheWrite" in usage_map
        cache_evidence = {
            "index": index,
            "inputTokens": int(usage_map.get("input") or 0),
            "outputTokens": int(usage_map.get("output") or 0),
            "cacheReadTokens": int(usage_map.get("cacheRead") or 0),
            "cacheWriteTokens": int(usage_map.get("cacheWrite") or 0),
            "capability": "reported" if supports_cache else "unsupported",
        }
        if deltas:
            latest = deltas[-1]
            cache_evidence.update(
                {
                    "prefixSha256": latest["prefixSha256"],
                    "prefixBytes": latest["prefixBytes"],
                    "deltaBytes": latest["deltaBytes"],
                    "duplicateBytes": latest["duplicateBytes"],
                }
            )
        cache_evidence_rows.append(cache_evidence)
        previous_by_scope[scope] = snapshot

    active_roots = {str(item.get("rootId") or "") for item in snapshots if item.get("rootId")}
    for index, snapshot in enumerate(snapshots):
        body = str(snapshot.get("providerBody") or "")
        current_root = str(snapshot.get("rootId") or "")
        for other_root in active_roots - {current_root}:
            if other_root and other_root in body:
                violations.append({"index": index, "code": "old_root_leaked"})

    return {
        "schemaVersion": "rag-ime.context-inspection-report.v1",
        "safe": not violations,
        "snapshotCount": len(snapshots),
        "deltas": deltas,
        "cacheEvidence": cache_evidence_rows,
        "violations": violations,
    }


def replay_context_jsonl(lines: Iterable[str]) -> dict[str, object]:
    active_generation: dict[str, int] = {}
    applied: list[str] = []
    ignored: list[str] = []
    seen: set[str] = set()
    crashed = False
    for raw in lines:
        if not raw.strip():
            continue
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            crashed = True
            continue
        event_id = str(event.get("eventId") or "")
        root_id = str(event.get("rootId") or "")
        generation = int(event.get("generation") or 0)
        if event_id in seen:
            ignored.append(event_id)
            continue
        seen.add(event_id)
        if event.get("type") == "generation_started":
            active_generation[root_id] = generation
        if generation < active_generation.get(root_id, generation):
            ignored.append(event_id)
            continue
        active_generation[root_id] = generation
        applied.append(event_id)
    return {
        "schemaVersion": "rag-ime.context-jsonl-replay.v1",
        "activeGeneration": active_generation,
        "appliedEventIds": applied,
        "ignoredEventIds": ignored,
        "recoveredFromTruncatedTail": crashed,
    }
