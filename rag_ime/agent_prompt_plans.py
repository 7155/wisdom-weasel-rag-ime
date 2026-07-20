from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from .agent_room_context import ProviderProjectionJournalStore
from .contracts.json_schema import validate_contract
from .db import apply_database_migrations


PROMPT_LAYER_SPECS = (
    (1, "core_rails", "pi-core-safety", False),
    (2, "persona", "persona-compiler", False),
    (3, "collaboration_role", "collaboration-role-compiler", False),
    (4, "agent_template_policy", "template-capability-compiler", False),
    (5, "room_profile_overlay", "profile-room-kernel-compiler", True),
    (6, "provider_dynamic_facts", "room-context-compiler", False),
)


class PromptProducerConflict(RuntimeError):
    """An instruction domain has more than one producer."""


class PromptPlanConflict(RuntimeError):
    """An immutable PromptPlan receipt identity changed."""


@dataclass(frozen=True)
class PromptLayer:
    layer: str
    producer: str
    ref: str
    content: str
    instruction_domains: tuple[str, ...]
    omitted_reason: str = ""


class RoomPromptPlanStore:
    """Durable six-layer PromptPlan compiler for canonically bound Room Sessions."""

    legacy_producer_ref = "rag_ime.pi_runtime.PiRuntimeConfig.system_prompt_for_session"

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.projections = ProviderProjectionJournalStore(self.db_path)

    def initialize(self) -> int:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            return apply_database_migrations(conn).current_version

    def compile(
        self,
        *,
        receipt_id: str,
        room_binding: Mapping[str, object] | None,
        participant_binding: Mapping[str, object] | None,
        journal_id: str,
        session_epoch: int,
        context_epoch: int,
        skill_policy_revision: str,
        context_policy_revision: str,
        layers: Sequence[PromptLayer],
        created_at_ms: int,
    ) -> dict[str, object] | None:
        # Ordinary Agent is a strict no-op: no migration, journal read, or DB write.
        if room_binding is None and participant_binding is None:
            return None
        if room_binding is None or participant_binding is None:
            raise PromptPlanConflict("Room PromptPlan binding handshake is incomplete")
        identity = _binding_identity(room_binding, participant_binding)
        normalized_layers, omitted, audit, stable_layers = _compile_layers(layers)
        audit = [
            {
                "surface": "live_provider_system_prompt",
                "producer": self.legacy_producer_ref,
                "mode": "disabled_for_room_binding",
            },
            *audit,
        ]
        projection = self.projections.projection(
            _required(journal_id, "journal_id"),
            expected_generation=identity["generation"],
        )
        journal = self._journal_identity(journal_id)
        expected_journal = {
            "bindingId": identity["bindingId"],
            "roomId": identity["roomId"],
            "rootId": identity["rootId"],
            "sessionId": identity["sessionId"],
            "sessionEpoch": _positive(session_epoch, "session_epoch"),
            "contextEpoch": _positive(context_epoch, "context_epoch"),
            "generation": identity["generation"],
        }
        if journal != expected_journal:
            raise PromptPlanConflict("PromptPlan journal does not match Room/Participant binding")
        sealed_refs = [
            str(item["contextEntryId"])
            for item in projection["sealedPrefix"]
        ]
        dynamic_refs = [
            str(item["contextEntryId"])
            for item in projection["pendingTail"]
        ]
        stable_prefix = _frame(
            [
                stable_layers,
                *(
                    _model_visible_projection_content(item).encode("utf-8")
                    for item in projection["sealedPrefix"]
                ),
            ]
        )
        dynamic_tail = b"".join(
            _model_visible_projection_content(item).encode("utf-8")
            for item in projection["pendingTail"]
        )
        stable_hash = _sha256(stable_prefix)
        plan_material = {
            "bindingId": identity["bindingId"],
            "roomId": identity["roomId"],
            "rootId": identity["rootId"],
            "sessionId": identity["sessionId"],
            "journalId": journal_id,
            "generation": identity["generation"],
            "sessionEpoch": expected_journal["sessionEpoch"],
            "contextEpoch": expected_journal["contextEpoch"],
            "capabilityRevision": identity["capabilityRevision"],
            "capabilityEpoch": identity["capabilityEpoch"],
            "skillPolicyRevision": _required(skill_policy_revision, "skill_policy_revision"),
            "contextPolicyRevision": _required(context_policy_revision, "context_policy_revision"),
            "layers": normalized_layers,
            "stablePrefixHash": stable_hash,
            "projectionHash": str(projection["projectionHash"]),
            "throughSequence": int(projection["throughSequence"]),
            "sealedProjectionRefs": sealed_refs,
            "dynamicTailRefs": dynamic_refs,
        }
        plan = {
            "schemaVersion": "wisdom-weasel.prompt-plan.v1",
            **plan_material,
            "planHash": _hash_json(plan_material),
        }
        validate_contract(plan, "prompt-plan.v1.json")
        receipt = {
            "schemaVersion": "wisdom-weasel.prompt-compile-receipt.v1",
            "receiptId": _required(receipt_id, "receipt_id"),
            "plan": plan,
            "omittedLayers": omitted,
            "producerAudit": audit,
            "createdAtMs": _non_negative(created_at_ms, "created_at_ms"),
        }
        validate_contract(receipt, "prompt-compile-receipt.v1.json")
        created = self._persist(receipt)
        return {
            "receipt": receipt,
            "stablePrefixBytes": stable_prefix,
            "dynamicTailBytes": dynamic_tail,
            "created": created,
            "mode": "live_room_binding",
        }

    def provider_payload(self, receipt_id: str) -> dict[str, object]:
        """Rebuild the live cache-stable prefix and append-only Room tail."""

        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM room_v2_prompt_compile_receipts WHERE receipt_id = ?",
                (_required(receipt_id, "receipt_id"),),
            ).fetchone()
        if row is None:
            raise KeyError(receipt_id)
        receipt = _receipt_payload(row)
        plan = dict(receipt["plan"])
        projection = self.projections.projection(
            str(plan["journalId"]), expected_generation=int(plan["generation"])
        )
        stable_prompt = _provider_layer_prompt(plan["layers"])
        sealed = _provider_projection_text(projection["sealedPrefix"], state="sealed")
        dynamic = _provider_projection_text(projection["pendingTail"], state="pending")
        return {
            "schemaVersion": "wisdom-weasel.room-provider-context.v1",
            "promptCompileReceiptId": receipt["receiptId"],
            "promptPlanHash": plan["planHash"],
            "stableSystemPrompt": stable_prompt + sealed,
            "providerContext": dynamic,
            "journalId": plan["journalId"],
            "generation": plan["generation"],
            "throughSequence": projection["throughSequence"],
            "sealedThroughSequence": projection["sealedThroughSequence"],
            "projectionHash": projection["projectionHash"],
            "dynamicTailRefs": [
                str(item["contextEntryId"]) for item in projection["pendingTail"]
            ],
        }

    def record_compare_diff(
        self,
        *,
        diff_id: str,
        binding_id: str,
        legacy_prompt_hash: str,
        prompt_plan_hash: str,
        added_layer_refs: Sequence[str],
        removed_legacy_refs: Sequence[str],
        created_at_ms: int,
    ) -> tuple[dict[str, object], bool]:
        """Record hashes/refs only; callers cannot supply provider or tool callbacks."""

        values = {
            "diffId": _required(diff_id, "diff_id"),
            "bindingId": _required(binding_id, "binding_id"),
            "legacyPromptHash": _hash(legacy_prompt_hash, "legacy_prompt_hash"),
            "promptPlanHash": _hash(prompt_plan_hash, "prompt_plan_hash"),
            "addedLayerRefs": list(_refs(added_layer_refs)),
            "removedLegacyRefs": list(_refs(removed_legacy_refs)),
            "createdAtMs": _non_negative(created_at_ms, "created_at_ms"),
        }
        with self._connect(immediate=True) as conn:
            existing = conn.execute(
                "SELECT * FROM room_v2_prompt_compare_diffs WHERE diff_id = ?",
                (values["diffId"],),
            ).fetchone()
            if existing is not None:
                payload = _compare_payload(existing)
                if payload != values:
                    raise PromptPlanConflict("Prompt compare diff identity changed")
                return payload, False
            conn.execute(
                """
                INSERT INTO room_v2_prompt_compare_diffs(
                    diff_id, binding_id, legacy_prompt_hash, prompt_plan_hash,
                    added_layer_refs_json, removed_legacy_refs_json, created_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    values["diffId"], values["bindingId"], values["legacyPromptHash"],
                    values["promptPlanHash"], _json(values["addedLayerRefs"]),
                    _json(values["removedLegacyRefs"]), values["createdAtMs"],
                ),
            )
        return values, True

    def _persist(self, receipt: Mapping[str, object]) -> bool:
        plan = dict(receipt["plan"])
        with self._connect(immediate=True) as conn:
            existing = conn.execute(
                "SELECT * FROM room_v2_prompt_compile_receipts WHERE receipt_id = ?",
                (receipt["receiptId"],),
            ).fetchone()
            if existing is not None:
                if _receipt_payload(existing) != dict(receipt):
                    raise PromptPlanConflict("PromptCompileReceipt identity changed")
                return False
            epoch_row = conn.execute(
                """
                SELECT capability_revision, capability_epoch
                FROM room_v2_prompt_compile_receipts
                WHERE binding_id = ? AND session_epoch = ? AND context_epoch = ?
                  AND generation = ?
                ORDER BY created_at_ms DESC LIMIT 1
                """,
                (
                    plan["bindingId"], plan["sessionEpoch"], plan["contextEpoch"],
                    plan["generation"],
                ),
            ).fetchone()
            if epoch_row is not None and (
                str(epoch_row["capability_revision"]) != str(plan["capabilityRevision"])
                or int(epoch_row["capability_epoch"]) != int(plan["capabilityEpoch"])
            ):
                raise PromptPlanConflict(
                    "capability revocation requires a new Context epoch"
                )
            conn.execute(
                """
                INSERT INTO room_v2_prompt_compile_receipts(
                    receipt_id, binding_id, room_id, root_id, session_id, journal_id,
                    generation, session_epoch, context_epoch, capability_revision,
                    capability_epoch, skill_policy_revision, context_policy_revision,
                    plan_hash, stable_prefix_hash, projection_hash, through_sequence,
                    layers_json, sealed_projection_refs_json, dynamic_tail_refs_json, omitted_layers_json,
                    producer_audit_json, created_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    receipt["receiptId"], plan["bindingId"], plan["roomId"], plan["rootId"],
                    plan["sessionId"], plan["journalId"], plan["generation"],
                    plan["sessionEpoch"], plan["contextEpoch"], plan["capabilityRevision"],
                    plan["capabilityEpoch"], plan["skillPolicyRevision"],
                    plan["contextPolicyRevision"], plan["planHash"],
                    plan["stablePrefixHash"], plan["projectionHash"], plan["throughSequence"],
                    _json(plan["layers"]), _json(plan["sealedProjectionRefs"]),
                    _json(plan["dynamicTailRefs"]),
                    _json(receipt["omittedLayers"]), _json(receipt["producerAudit"]),
                    receipt["createdAtMs"],
                ),
            )
        return True

    def _journal_identity(self, journal_id: str) -> dict[str, object]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM room_v2_provider_projection_journals WHERE journal_id = ?",
                (journal_id,),
            ).fetchone()
        if row is None:
            raise KeyError(journal_id)
        return {
            "bindingId": str(row["binding_id"]), "roomId": str(row["room_id"]),
            "rootId": str(row["root_id"]), "sessionId": str(row["session_id"]),
            "sessionEpoch": int(row["session_epoch"]),
            "contextEpoch": int(row["context_epoch"]),
            "generation": int(row["generation"]),
        }

    @contextmanager
    def _connect(self, *, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            if immediate:
                conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()


def _compile_layers(
    layers: Sequence[PromptLayer],
) -> tuple[list[dict[str, object]], list[str], list[dict[str, object]], bytes]:
    by_name = {layer.layer: layer for layer in layers}
    if len(by_name) != len(layers):
        raise PromptProducerConflict("PromptPlan contains a duplicate layer")
    expected_names = {spec[1] for spec in PROMPT_LAYER_SPECS}
    if set(by_name) != expected_names:
        raise ValueError("PromptPlan must contain exactly the six fixed layers")
    domain_owner: dict[str, str] = {}
    payloads: list[dict[str, object]] = []
    omitted: list[str] = []
    audit: list[dict[str, object]] = []
    stable_parts: list[bytes] = []
    for order, name, expected_producer, optional in PROMPT_LAYER_SPECS:
        layer = by_name[name]
        allowed_producers = {expected_producer}
        if name == "room_profile_overlay":
            allowed_producers.add("guard-materialization")
        if layer.producer not in allowed_producers:
            raise PromptProducerConflict(f"{name} has an unregistered prompt producer")
        if name == "provider_dynamic_facts" and layer.content:
            raise ValueError("Room dynamic facts must come only from ProviderProjectionJournal")
        if not optional and name != "provider_dynamic_facts" and not layer.content:
            raise ValueError(f"{name} must not be empty")
        if optional and not layer.content:
            reason = _required(layer.omitted_reason, "omitted_reason")
            omitted.append(f"{name}:{reason}")
        content_bytes = layer.content.encode("utf-8")
        for domain in _refs(layer.instruction_domains):
            previous = domain_owner.get(domain)
            if previous is not None:
                raise PromptProducerConflict(
                    f"instruction domain {domain} is produced by both {previous} and {layer.producer}"
                )
            domain_owner[domain] = layer.producer
        content_hash = _sha256(content_bytes)
        payloads.append(
            {
                "order": order, "layer": name, "producer": layer.producer,
                "ref": _required(layer.ref, "layer_ref"), "contentHash": content_hash,
                "instructionDomains": list(_refs(layer.instruction_domains)),
                "omitted": not bool(layer.content),
                "content": layer.content,
            }
        )
        audit.append(
            {"layer": name, "producer": layer.producer, "domains": list(_refs(layer.instruction_domains))}
        )
        if order <= 5 and layer.content:
            stable_parts.append(content_bytes)
    return payloads, omitted, audit, _frame(stable_parts)


def _binding_identity(
    room_binding: Mapping[str, object],
    participant_binding: Mapping[str, object],
) -> dict[str, object]:
    validate_contract(dict(room_binding), "room-binding.v2.json")
    validate_contract(dict(participant_binding), "room-participant-binding.v2.json")
    if participant_binding.get("roomBindingRef") != {
        "bindingId": room_binding["bindingId"],
        "schemaVersion": room_binding["schemaVersion"],
    }:
        raise PromptPlanConflict("ParticipantBinding does not reference the RoomBinding")
    if participant_binding["capabilityRevision"] != room_binding["capabilityRevision"]:
        raise PromptPlanConflict("capability revision differs across bindings")
    return {
        "bindingId": str(participant_binding["bindingId"]),
        "sessionId": str(participant_binding["sessionId"]),
        "roomId": str(room_binding["roomId"]), "rootId": str(room_binding["rootId"]),
        "generation": int(room_binding["generation"]),
        "capabilityRevision": str(room_binding["capabilityRevision"]),
        "capabilityEpoch": int(participant_binding["capabilityEpoch"]),
    }


def _provider_layer_prompt(layers: object) -> str:
    if not isinstance(layers, list):
        raise PromptPlanConflict("PromptPlan layers are corrupt")
    stable = [item for item in layers if isinstance(item, Mapping) and int(item.get("order", 0)) <= 5]
    if [int(item.get("order", 0)) for item in stable] != [1, 2, 3, 4, 5]:
        raise PromptPlanConflict("PromptPlan stable layer order changed")
    parts = ["<room-prompt-plan schema=\"wisdom-weasel.prompt-plan.v1\">\n"]
    for item in stable:
        parts.extend(
            (
                f'<layer order="{item["order"]}" name="{item["layer"]}" ref="{item["ref"]}">\n',
                str(item.get("content") or ""),
                "\n</layer>\n",
            )
        )
    parts.append("</room-prompt-plan>\n")
    return "".join(parts)


def _provider_projection_text(items: object, *, state: str) -> str:
    if not isinstance(items, list) or not items:
        return ""
    lines = [f'<room-projection state="{state}">']
    for item in items:
        if not isinstance(item, Mapping):
            raise PromptPlanConflict("Room projection item is corrupt")
        lines.append(_model_visible_projection_content(item))
    lines.append("</room-projection>")
    return "\n".join(lines) + "\n"


_MODEL_CONTEXT_FORBIDDEN_KEY_PARTS = (
    "relevance",
    "score",
    "rank",
    "hash",
    "debug",
    "diagnostic",
    "trace",
    "receipt",
    "internal",
)
_MODEL_CONTEXT_SOURCE_FIELDS = frozenset({"label", "title", "path", "uri", "section"})
_MODEL_CONTEXT_KIND = {
    "control_receipt": "control",
    "evidence_receipt": "evidence",
    "skill_receipt": "skill",
    "knowledge_receipt": "knowledge",
    "recovery_packet": "recovery",
}


def _model_visible_projection_content(item: Mapping[str, object]) -> str:
    """Compile audit-rich Room entries into compact model-visible facts."""

    raw = str(item.get("content") or "")
    raw_kind = str(item.get("entryKind") or "room_fact").strip() or "room_fact"
    kind = _MODEL_CONTEXT_KIND.get(raw_kind, raw_kind)
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        value = raw
    visible = _model_visible_value(value)
    if isinstance(visible, str):
        content = visible.strip()
    else:
        content = json.dumps(visible, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f'<room-fact kind="{kind}">{content}</room-fact>'


def _model_visible_value(value: object, *, source_context: bool = False) -> object:
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for raw_key, raw_value in value.items():
            key = str(raw_key)
            normalized = "".join(character for character in key.casefold() if character.isalnum())
            is_source = normalized in {"source", "sources", "citation", "citations"}
            if source_context and normalized not in _MODEL_CONTEXT_SOURCE_FIELDS:
                continue
            if (
                any(part in normalized for part in _MODEL_CONTEXT_FORBIDDEN_KEY_PARTS)
                or _model_context_identifier_key(key)
            ):
                continue
            child = _model_visible_value(raw_value, source_context=is_source or source_context)
            if child not in (None, "", [], {}):
                result[key] = child
        return result
    if isinstance(value, list):
        return [
            child
            for item in value
            for child in [_model_visible_value(item, source_context=source_context)]
            if child not in (None, "", [], {})
        ]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _model_context_identifier_key(key: str) -> bool:
    stripped = key.strip()
    lowered = stripped.casefold()
    if lowered in {"id", "ids", "ref", "refs"}:
        return True
    if re.search(r"(?:^|[_.-])(?:id|ids|ref|refs)$", lowered):
        return True
    return bool(re.search(r"(?:Id|ID|Ids|IDs|Ref|Refs)$", stripped))


def _receipt_payload(row: sqlite3.Row) -> dict[str, object]:
    plan = {
        "schemaVersion": "wisdom-weasel.prompt-plan.v1",
        "bindingId": str(row["binding_id"]), "roomId": str(row["room_id"]),
        "rootId": str(row["root_id"]), "sessionId": str(row["session_id"]),
        "journalId": str(row["journal_id"]), "generation": int(row["generation"]),
        "sessionEpoch": int(row["session_epoch"]), "contextEpoch": int(row["context_epoch"]),
        "capabilityRevision": str(row["capability_revision"]),
        "capabilityEpoch": int(row["capability_epoch"]),
        "skillPolicyRevision": str(row["skill_policy_revision"]),
        "contextPolicyRevision": str(row["context_policy_revision"]),
        "layers": json.loads(str(row["layers_json"])),
        "stablePrefixHash": str(row["stable_prefix_hash"]),
        "projectionHash": str(row["projection_hash"]),
        "throughSequence": int(row["through_sequence"]),
        "sealedProjectionRefs": json.loads(str(row["sealed_projection_refs_json"])),
        "dynamicTailRefs": json.loads(str(row["dynamic_tail_refs_json"])),
        "planHash": str(row["plan_hash"]),
    }
    return {
        "schemaVersion": "wisdom-weasel.prompt-compile-receipt.v1",
        "receiptId": str(row["receipt_id"]), "plan": plan,
        "omittedLayers": json.loads(str(row["omitted_layers_json"])),
        "producerAudit": json.loads(str(row["producer_audit_json"])),
        "createdAtMs": int(row["created_at_ms"]),
    }


def _compare_payload(row: sqlite3.Row) -> dict[str, object]:
    return {
        "diffId": str(row["diff_id"]), "bindingId": str(row["binding_id"]),
        "legacyPromptHash": str(row["legacy_prompt_hash"]),
        "promptPlanHash": str(row["prompt_plan_hash"]),
        "addedLayerRefs": json.loads(str(row["added_layer_refs_json"])),
        "removedLegacyRefs": json.loads(str(row["removed_legacy_refs_json"])),
        "createdAtMs": int(row["created_at_ms"]),
    }


def _frame(parts: Sequence[bytes]) -> bytes:
    framed = bytearray()
    for part in parts:
        framed.extend(len(part).to_bytes(8, "big"))
        framed.extend(part)
    return bytes(framed)


def _refs(values: Sequence[str]) -> tuple[str, ...]:
    result = tuple(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))
    return result


def _required(value: object, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field} is required")
    return normalized


def _positive(value: object, field: str) -> int:
    normalized = int(value)
    if normalized < 1:
        raise ValueError(f"{field} must be positive")
    return normalized


def _non_negative(value: object, field: str) -> int:
    normalized = int(value)
    if normalized < 0:
        raise ValueError(f"{field} must be non-negative")
    return normalized


def _hash(value: object, field: str) -> str:
    normalized = _required(value, field)
    if len(normalized) != 64 or any(character not in "0123456789abcdef" for character in normalized):
        raise ValueError(f"{field} must be a lowercase sha256")
    return normalized


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _hash_json(value: object) -> str:
    return _sha256(_json(value).encode("utf-8"))


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
