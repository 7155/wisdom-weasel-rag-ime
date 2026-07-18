"""Privacy-preserving diagnostics for context capture and model injection."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Iterable, Mapping


CONTEXT_INJECTION_TRACE_SCHEMA_VERSION = "rag-ime.context-injection-trace.v1"
ACTIVE_RAG_ROUTE_STATUS_SCHEMA_VERSION = "rag-ime.active-rag-route-status.v1"


def text_fingerprint(value: object, *, include_text: bool = False) -> dict[str, object]:
    text = "" if value is None else str(value)
    encoded = text.encode("utf-8")
    payload: dict[str, object] = {
        "present": bool(text),
        "chars": len(text),
        "utf8Bytes": len(encoded),
        "hash": f"sha256:{hashlib.sha256(encoded).hexdigest()[:16]}" if text else "",
    }
    if include_text:
        payload["text"] = text
    return payload


def json_fingerprint(value: object) -> dict[str, object]:
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return text_fingerprint(serialized)


def evidence_injection_diagnostics(
    evidence_pack: Iterable[Mapping[str, object]],
    *,
    include_text: bool = False,
) -> dict[str, object]:
    items: list[dict[str, object]] = []
    source_counts: Counter[str] = Counter()
    lane_counts: Counter[str] = Counter()
    for index, item in enumerate(evidence_pack):
        source_type = str(item.get("sourceType") or item.get("source_type") or "unknown")
        source_lane = str(item.get("sourceLane") or item.get("source_lane") or "unknown")
        source_counts[source_type] += 1
        lane_counts[source_lane] += 1
        semantic_text = _evidence_text(item)
        item_payload: dict[str, object] = {
            "ordinal": index + 1,
            "sourceType": source_type,
            "sourceLane": source_lane,
            "content": text_fingerprint(semantic_text, include_text=include_text),
        }
        evidence_id = str(item.get("id") or item.get("evidenceId") or item.get("evidence_id") or "")
        if evidence_id:
            item_payload["idHash"] = text_fingerprint(evidence_id)["hash"]
        items.append(item_payload)
    return {
        "count": len(items),
        "sourceCounts": dict(sorted(source_counts.items())),
        "sourceLaneCounts": dict(sorted(lane_counts.items())),
        "items": items,
    }


def build_context_injection_trace(
    *,
    current_context: str = "",
    selected_text: str = "",
    surrounding_before: str = "",
    surrounding_after: str = "",
    evidence_pack: Iterable[Mapping[str, object]] = (),
    context_packet: Mapping[str, object] | None = None,
    messages: Iterable[Mapping[str, object]] = (),
    include_text: bool = False,
) -> dict[str, object]:
    evidence_items = tuple(dict(item) for item in evidence_pack)
    packet = dict(context_packet or {})
    message_items = tuple(dict(item) for item in messages)
    parsed_user_payload = _parsed_user_payload(message_items)
    message_diagnostics = [
        {
            "ordinal": index + 1,
            "role": str(item.get("role") or ""),
            "content": text_fingerprint(item.get("content"), include_text=include_text),
        }
        for index, item in enumerate(message_items)
    ]
    injection = {
        "promptBuilt": bool(message_items),
        "currentContextIncluded": _payload_has_text(parsed_user_payload, "currentContext", current_context),
        "selectedTextIncluded": _payload_has_text(parsed_user_payload, "selectedText", selected_text),
        "contextPacketIncluded": bool(packet) and isinstance(parsed_user_payload.get("contextPacket"), dict),
        "evidenceIncluded": bool(evidence_items)
        and bool(
            parsed_user_payload.get("groundingEvidence")
            or parsed_user_payload.get("evidencePack")
            or parsed_user_payload.get("evidenceHints")
        ),
    }
    required = ["promptBuilt", "currentContextIncluded"]
    if selected_text:
        required.append("selectedTextIncluded")
    if packet:
        required.append("contextPacketIncluded")
    if evidence_items:
        required.append("evidenceIncluded")
    missing = [name for name in required if not injection[name]]
    injection["success"] = not missing
    injection["missing"] = missing
    return {
        "schemaVersion": CONTEXT_INJECTION_TRACE_SCHEMA_VERSION,
        "privacy": {
            "rawTextIncluded": bool(include_text),
            "hashAlgorithm": "sha256-16",
            "textNormalization": "none",
        },
        "capturedContext": {
            "currentContext": text_fingerprint(current_context, include_text=include_text),
            "selectedText": text_fingerprint(selected_text, include_text=include_text),
            "surroundingBefore": text_fingerprint(surrounding_before, include_text=include_text),
            "surroundingAfter": text_fingerprint(surrounding_after, include_text=include_text),
        },
        "evidence": evidence_injection_diagnostics(evidence_items, include_text=include_text),
        "contextPacket": {
            "present": bool(packet),
            "packetIdHash": text_fingerprint(packet.get("packetId"))["hash"] if packet else "",
            "fingerprint": json_fingerprint(packet),
            "sectionCounts": _packet_section_counts(packet),
        },
        "prompt": {
            "messageCount": len(message_diagnostics),
            "messages": message_diagnostics,
            "fingerprint": json_fingerprint(message_items),
        },
        "injection": injection,
    }


def _evidence_text(item: Mapping[str, object]) -> str:
    values: list[str] = []
    for key in ("text", "candidateText", "evidencePreview", "evidence_preview", "summary", "title"):
        value = item.get(key)
        if value:
            values.append(str(value))
    hints = item.get("surfaceHints") or item.get("surface_hints")
    if isinstance(hints, (list, tuple)):
        values.extend(str(value) for value in hints if value)
    return "\n".join(values)


def _parsed_user_payload(messages: tuple[dict[str, object], ...]) -> dict[str, object]:
    for item in reversed(messages):
        if item.get("role") != "user" or not isinstance(item.get("content"), str):
            continue
        try:
            payload = json.loads(str(item["content"]))
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}
    return {}


def _payload_has_text(payload: Mapping[str, object], key: str, expected: str) -> bool:
    if not expected:
        return False
    return str(payload.get(key) or "") == expected


def _packet_section_counts(packet: Mapping[str, object]) -> dict[str, int]:
    result: dict[str, int] = {}
    for key in ("oneRing", "notebook", "timeline"):
        section = packet.get(key)
        if not isinstance(section, Mapping):
            result[key] = 0
            continue
        sequence = section.get("events") if key == "oneRing" else section.get("items")
        if key == "timeline":
            sequence = section.get("recentDecisions")
        result[key] = len(sequence) if isinstance(sequence, (list, tuple)) else 0
    return result
