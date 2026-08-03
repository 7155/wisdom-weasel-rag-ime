from __future__ import annotations

import json
import re
import time
from collections.abc import Mapping
from typing import Any

from .sensitive_content import contains_sensitive_content
from .text_utils import compact_whitespace


PERSONAL_CURATION_PROTOCOL_VERSION = "personal-v2"
PERSONAL_CURATION_SCHEMA_VERSION = "rag-ime.personal-memory-curation.v2"
PERSONAL_CURATION_POLICY_REVISION = "personal-curator-v8"
MIN_DURABLE_CONFIDENCE = 0.92
MIN_CORRECTION_CONFIDENCE = 0.95
MAX_CONTEXT_ONLY_ROWS = 12
MAX_PERSONAL_ATOM_CATALOG_TOKENS = 72_000

_KIND_BY_CODE = {
    "f": "personal_fact",
    "h": "personal_habit",
    "d": "durable_preference",
    "p": "personal_principle",
}
_CODE_BY_KIND = {value: key for key, value in _KIND_BY_CODE.items()}
_EVIDENCE_CODES = frozenset({"p", "n", "r", "c", "f"})
_UPDATE_SIGNAL_RE = re.compile(
    r"(?:改为|改成|更新为|切换为|调整为|纠正|更正|不再|以后(?:都|不要)|"
    r"现在(?:是|改用)|from\s+.+\s+to\s+|changed?\s+to|no\s+longer)",
    re.IGNORECASE,
)
_FORGET_SIGNAL_RE = re.compile(
    r"(?:忘(?:掉|记)|不要再记|别再记|删除.{0,16}(?:记忆|偏好|事实)|"
    r"移除.{0,16}(?:记忆|偏好|事实)|forget|do\s+not\s+remember)",
    re.IGNORECASE,
)


class PersonalMemoryCurationError(RuntimeError):
    pass


def curate_personal_memory_v2(
    executor: Any,
    *,
    bundle: Mapping[str, object],
    instruction: str = "",
) -> dict[str, object]:
    """Run Evidence, Atom, and independent verification over one frozen batch."""

    started = time.perf_counter()
    packet, index = build_personal_memory_packet(bundle)
    evidence_payload, evidence_receipt = _complete_json(
        executor,
        phase="evidence-adjudication",
        system=_evidence_prompt(),
        packet={"p": packet, "i": compact_whitespace(instruction)[:800]},
        max_tokens=24_000,
    )
    evidence_decisions = _validate_evidence_decisions(
        evidence_payload,
        expected_refs=set(index["evidenceByRef"]),
    )
    eligible_refs = {
        ref
        for ref, decision in evidence_decisions.items()
        if decision["code"] in {"p", "c", "f"}
    }

    atom_payload: dict[str, object] = {"v": 2, "o": []}
    atom_receipt: dict[str, object] = {}
    if eligible_refs:
        atom_payload, atom_receipt = _complete_json(
            executor,
            phase="atom-adjudication",
            system=_atom_prompt(),
            packet={
                "v": 2,
                "e": [
                    row
                    for row in packet["e"]
                    if isinstance(row, list) and str(row[0]) in eligible_refs
                ],
                "a": packet["a"],
                "k": packet["k"],
                "c": packet["c"],
                "d": [
                    [ref, evidence_decisions[ref]["code"]]
                    for ref in sorted(eligible_refs, key=_ref_ordinal)
                ],
            },
            max_tokens=48_000,
        )
    operations = _validate_atom_operations(
        atom_payload,
        eligible_refs=eligible_refs,
        evidence_decisions=evidence_decisions,
        index=index,
    )

    verifier_payload, verifier_receipt = _complete_json(
        executor,
        phase="independent-verifier",
        system=_verifier_prompt(),
        packet={
            "p": packet,
            "d": evidence_payload,
            "o": atom_payload,
        },
        max_tokens=24_000,
        isolated=True,
    )
    _validate_verifier(
        verifier_payload,
        evidence_refs=set(index["evidenceByRef"]),
        operation_count=len(operations),
    )
    return _compile_output(
        evidence_decisions=evidence_decisions,
        operations=operations,
        index=index,
        executor=executor,
        receipts={
            "evidence": evidence_receipt,
            "atom": atom_receipt,
            "verifier": verifier_receipt,
        },
        packet=packet,
        elapsed_ms=max(0, int((time.perf_counter() - started) * 1_000)),
    )


def build_personal_memory_packet(
    bundle: Mapping[str, object],
) -> tuple[dict[str, object], dict[str, dict[str, dict[str, object]]]]:
    """Build a compact object protocol; context-only rows never receive refs."""

    inputs = [dict(item) for item in bundle.get("inputs") or [] if isinstance(item, Mapping)]
    atoms = [
        dict(item)
        for item in bundle.get("existingMemoryAtoms") or []
        if isinstance(item, Mapping)
    ]
    channels = _dictionary(
        compact_whitespace(str(item.get("sourceChannel") or item.get("source") or "input"))
        for item in inputs
    )
    apps = _dictionary(compact_whitespace(str(item.get("app") or "")) for item in inputs)
    channel_index = {value: index for index, value in enumerate(channels)}
    app_index = {value: index for index, value in enumerate(apps)}
    base_ms = min(
        (int(item.get("sourceOccurredAtMs") or item.get("createdAtMs") or 0) for item in inputs),
        default=0,
    )
    evidence_rows: list[list[object]] = []
    evidence_by_ref: dict[str, dict[str, object]] = {}
    for ordinal, item in enumerate(inputs, start=1):
        evidence_ids = _strings(item.get("evidenceIds") or [item.get("evidenceId")])
        if len(evidence_ids) != 1:
            raise PersonalMemoryCurationError(
                "each personal curation input must resolve to exactly one canonical Evidence"
            )
        source_ref = compact_whitespace(str(item.get("sourceRef") or ""))
        text = compact_whitespace(str(item.get("text") or ""))
        if not source_ref or not text:
            raise PersonalMemoryCurationError("personal curation input is incomplete")
        ref = f"E{ordinal}"
        evidence_rows.append(
            [
                ref,
                max(0, int(item.get("sourceOccurredAtMs") or item.get("createdAtMs") or 0) - base_ms),
                channel_index[compact_whitespace(str(item.get("sourceChannel") or item.get("source") or "input"))],
                app_index[compact_whitespace(str(item.get("app") or ""))],
                compact_whitespace(str(item.get("boundaryKind") or ""))[:40],
                text,
            ]
        )
        evidence_by_ref[ref] = {
            **item,
            "evidenceId": evidence_ids[0],
            "sourceRef": source_ref,
        }

    atom_rows: list[list[object]] = []
    atom_by_ref: dict[str, dict[str, object]] = {}
    atom_catalog_tokens = 0
    for ordinal, atom in enumerate(atoms, start=1):
        atom_id = compact_whitespace(str(atom.get("atomId") or atom.get("id") or ""))
        claim_key = compact_whitespace(str(atom.get("claimKey") or ""))
        canonical = compact_whitespace(
            str(atom.get("canonicalText") or atom.get("text") or "")
        )
        kind = compact_whitespace(str(atom.get("kind") or ""))
        if not atom_id or not claim_key or not canonical or kind not in _CODE_BY_KIND:
            raise PersonalMemoryCurationError(
                "current personal Atom catalog contains an invalid entry"
            )
        ref = f"A{ordinal}"
        evidence_ids = _strings(atom.get("evidenceIds"))
        tags = _safe_tags(atom.get("tags"))
        atom_rows.append(
            [ref, _CODE_BY_KIND[kind], claim_key, canonical, evidence_ids, tags]
        )
        atom_by_ref[ref] = {**atom, "atomId": atom_id, "kind": kind, "tags": tags}
        atom_catalog_tokens += _estimated_tokens(claim_key) + _estimated_tokens(canonical)
    if atom_catalog_tokens > MAX_PERSONAL_ATOM_CATALOG_TOKENS:
        raise PersonalMemoryCurationError(
            "complete current personal Atom catalog exceeds its audit budget"
        )

    context_rows: list[list[object]] = []
    for item in list(bundle.get("contextOnly") or [])[-MAX_CONTEXT_ONLY_ROWS:]:
        if not isinstance(item, Mapping):
            continue
        text = compact_whitespace(str(item.get("text") or ""))
        if text:
            context_rows.append(
                [
                    max(0, int(item.get("occurredAtMs") or 0) - base_ms),
                    compact_whitespace(str(item.get("channel") or ""))[:40],
                    compact_whitespace(str(item.get("app") or ""))[:160],
                    text[:1200],
                ]
            )
    packet: dict[str, object] = {
        "v": 2,
        "t": base_ms,
        "k": channels,
        "c": apps,
        "e": evidence_rows,
        "a": atom_rows,
        "x": context_rows,
    }
    return packet, {"evidenceByRef": evidence_by_ref, "atomByRef": atom_by_ref}


def _validate_evidence_decisions(
    payload: Mapping[str, object],
    *,
    expected_refs: set[str],
) -> dict[str, dict[str, object]]:
    if payload.get("v") != 2 or set(payload) != {"v", "d"}:
        raise PersonalMemoryCurationError("Evidence response does not match protocol v2")
    rows = payload.get("d")
    if not isinstance(rows, list):
        raise PersonalMemoryCurationError("Evidence response decisions must be a list")
    result: dict[str, dict[str, object]] = {}
    for row in rows:
        if not isinstance(row, list) or len(row) != 4:
            raise PersonalMemoryCurationError("Evidence decision row has an invalid shape")
        ref = compact_whitespace(str(row[0] or ""))
        code = compact_whitespace(str(row[1] or "")).lower()
        confidence = _confidence(row[2])
        reason = _reason(row[3])
        if ref not in expected_refs or ref in result or code not in _EVIDENCE_CODES:
            raise PersonalMemoryCurationError("Evidence response contains an unknown or duplicate ref")
        if code in {"p", "c", "f"} and confidence < MIN_DURABLE_CONFIDENCE:
            code = "r"
            reason = "below_automatic_evidence_threshold"
        result[ref] = {"code": code, "confidence": confidence, "reason": reason}
    if set(result) != expected_refs:
        raise PersonalMemoryCurationError("Evidence response did not cover every frozen ref")
    return result


def _validate_atom_operations(
    payload: Mapping[str, object],
    *,
    eligible_refs: set[str],
    evidence_decisions: Mapping[str, Mapping[str, object]],
    index: Mapping[str, Mapping[str, dict[str, object]]],
) -> list[dict[str, object]]:
    if payload.get("v") != 2 or set(payload) != {"v", "o"}:
        raise PersonalMemoryCurationError("Atom response does not match protocol v2")
    raw_operations = payload.get("o")
    if not isinstance(raw_operations, list):
        raise PersonalMemoryCurationError("Atom operations must be a list")
    result: list[dict[str, object]] = []
    covered: set[str] = set()
    atom_by_ref = index["atomByRef"]
    evidence_by_ref = index["evidenceByRef"]
    existing_by_claim = {
        compact_whitespace(str(atom.get("claimKey") or "")): atom
        for atom in atom_by_ref.values()
    }
    for raw in raw_operations:
        if not isinstance(raw, list) or not raw:
            raise PersonalMemoryCurationError("Atom operation has an invalid shape")
        code = compact_whitespace(str(raw[0] or "")).lower()
        if code == "c" and len(raw) == 7:
            kind = _kind(raw[1])
            claim_key = _claim_key(raw[2])
            canonical = _canonical(raw[3])
            refs = _operation_refs(raw[4], eligible_refs=eligible_refs, covered=covered)
            confidence = _confidence(raw[5])
            tags = _safe_tags(raw[6])
            if confidence < MIN_DURABLE_CONFIDENCE:
                raise PersonalMemoryCurationError("Atom create confidence is below 0.92")
            if any(evidence_decisions[ref]["code"] != "p" for ref in refs):
                raise PersonalMemoryCurationError("Atom create requires durable-personal Evidence")
            if claim_key in existing_by_claim:
                raise PersonalMemoryCurationError("Atom create conflicts with a current claim key")
            result.append(
                {"op": "create", "kind": kind, "claimKey": claim_key, "canonicalText": canonical,
                 "refs": refs, "confidence": confidence, "tags": tags}
            )
        elif code == "a" and len(raw) == 4:
            atom_ref = _atom_ref(raw[1], atom_by_ref)
            refs = _operation_refs(raw[2], eligible_refs=eligible_refs, covered=covered)
            confidence = _confidence(raw[3])
            if confidence < MIN_DURABLE_CONFIDENCE:
                raise PersonalMemoryCurationError("Atom attach confidence is below 0.92")
            if any(evidence_decisions[ref]["code"] != "p" for ref in refs):
                raise PersonalMemoryCurationError("Atom attach requires durable-personal Evidence")
            result.append({"op": "attach", "atomRef": atom_ref, "refs": refs, "confidence": confidence})
        elif code == "s" and len(raw) == 8:
            atom_ref = _atom_ref(raw[1], atom_by_ref)
            kind = _kind(raw[2])
            claim_key = _claim_key(raw[3])
            canonical = _canonical(raw[4])
            refs = _operation_refs(raw[5], eligible_refs=eligible_refs, covered=covered)
            confidence = _confidence(raw[6])
            tags = _safe_tags(raw[7])
            target = atom_by_ref[atom_ref]
            if confidence < MIN_CORRECTION_CONFIDENCE:
                raise PersonalMemoryCurationError("Atom supersession confidence is below 0.95")
            if any(evidence_decisions[ref]["code"] != "c" for ref in refs):
                raise PersonalMemoryCurationError("Atom supersession requires correction Evidence")
            if claim_key != compact_whitespace(str(target.get("claimKey") or "")):
                raise PersonalMemoryCurationError("Atom supersession changed the claim key")
            if kind != compact_whitespace(str(target.get("kind") or "")):
                raise PersonalMemoryCurationError("Atom supersession changed the claim kind")
            if not any(_UPDATE_SIGNAL_RE.search(str(evidence_by_ref[ref].get("text") or "")) for ref in refs):
                raise PersonalMemoryCurationError("Atom supersession lacks explicit correction language")
            result.append(
                {"op": "supersede", "atomRef": atom_ref, "kind": kind, "claimKey": claim_key,
                 "canonicalText": canonical, "refs": refs, "confidence": confidence, "tags": tags}
            )
        elif code == "x" and len(raw) == 4:
            atom_ref = _atom_ref(raw[1], atom_by_ref)
            refs = _operation_refs(raw[2], eligible_refs=eligible_refs, covered=covered)
            confidence = _confidence(raw[3])
            if confidence < MIN_CORRECTION_CONFIDENCE:
                raise PersonalMemoryCurationError("Atom retraction confidence is below 0.95")
            if any(evidence_decisions[ref]["code"] != "f" for ref in refs):
                raise PersonalMemoryCurationError("Atom retraction requires forget Evidence")
            if not any(_FORGET_SIGNAL_RE.search(str(evidence_by_ref[ref].get("text") or "")) for ref in refs):
                raise PersonalMemoryCurationError("Atom retraction lacks explicit forget language")
            result.append({"op": "retract", "atomRef": atom_ref, "refs": refs, "confidence": confidence})
        elif code == "r" and len(raw) == 3:
            refs = _operation_refs(raw[1], eligible_refs=eligible_refs, covered=covered)
            result.append({"op": "review", "refs": refs, "reason": _reason(raw[2])})
        else:
            raise PersonalMemoryCurationError("Atom response contains an unsupported operation")
        covered.update(result[-1]["refs"])
    if covered != eligible_refs:
        raise PersonalMemoryCurationError("Atom response did not cover every eligible Evidence ref")
    return result


def _validate_verifier(
    payload: Mapping[str, object],
    *,
    evidence_refs: set[str],
    operation_count: int,
) -> None:
    if payload.get("v") != 2 or set(payload) != {"v", "ok", "r", "o", "errors"}:
        raise PersonalMemoryCurationError("verifier response does not match protocol v2")
    if payload.get("ok") not in {1, True} or payload.get("errors") != []:
        raise PersonalMemoryCurationError("independent verifier rejected the curation batch")
    refs = _verified_pairs(payload.get("r"), key_type=str)
    operations = _verified_pairs(payload.get("o"), key_type=int)
    if refs != evidence_refs or operations != set(range(operation_count)):
        raise PersonalMemoryCurationError("independent verifier did not cover the frozen batch")


def _compile_output(
    *,
    evidence_decisions: Mapping[str, Mapping[str, object]],
    operations: list[dict[str, object]],
    index: Mapping[str, Mapping[str, dict[str, object]]],
    executor: Any,
    receipts: Mapping[str, Mapping[str, object]],
    packet: Mapping[str, object],
    elapsed_ms: int,
) -> dict[str, object]:
    evidence_by_ref = index["evidenceByRef"]
    atom_by_ref = index["atomByRef"]
    operation_by_ref = {
        ref: operation for operation in operations for ref in operation["refs"]
    }
    source_decisions: list[dict[str, object]] = []
    for ref in sorted(evidence_decisions, key=_ref_ordinal):
        decision = evidence_decisions[ref]
        operation = operation_by_ref.get(ref)
        code = str(decision["code"])
        if code == "n":
            disposition, state = "not_for_memory", "rejected"
        elif code == "r" or operation is None or operation["op"] == "review":
            disposition, state = "needs_review", "needs_review"
        else:
            disposition, state = "remember", "admitted"
        source = evidence_by_ref[ref]
        source_decisions.append(
            {
                "sourceRef": str(source["sourceRef"]),
                "evidenceId": str(source["evidenceId"]),
                "evidenceRef": ref,
                "disposition": disposition,
                "evidenceAdmissionState": state,
                "reasonCode": str(decision["reason"]),
                "confidence": float(decision["confidence"]),
            }
        )

    atoms: list[dict[str, object]] = []
    retractions: list[dict[str, object]] = []
    for operation in operations:
        if operation["op"] == "review":
            continue
        refs = list(operation["refs"])
        evidence_ids = [str(evidence_by_ref[ref]["evidenceId"]) for ref in refs]
        event_ids = sorted(
            {
                int(event_id)
                for ref in refs
                for event_id in evidence_by_ref[ref].get("sourceEventIds") or []
                if str(event_id).isdigit() and int(event_id) > 0
            }
        )
        occurred_ms = max(
            (int(evidence_by_ref[ref].get("sourceOccurredAtMs") or evidence_by_ref[ref].get("createdAtMs") or 0) for ref in refs),
            default=0,
        )
        if operation["op"] == "retract":
            target = atom_by_ref[str(operation["atomRef"])]
            retractions.append(
                {
                    "targetAtomId": str(target["atomId"]),
                    "reason": "explicit_user_forget",
                    "sourceEventIds": event_ids,
                    "evidenceIds": evidence_ids,
                    "confidence": float(operation["confidence"]),
                    "project": "",
                    "knowledgeDomain": "personal_memory",
                    "scopeKind": "user",
                    "scopeId": "default",
                    "visibility": "private",
                    "scopeMode": "authoritative",
                }
            )
            continue
        if operation["op"] == "attach":
            target = atom_by_ref[str(operation["atomRef"])]
            atom = {
                **target,
                "operation": "attach",
                "atomId": str(target["atomId"]),
                "canonicalText": compact_whitespace(str(target.get("canonicalText") or target.get("text") or "")),
                "sourceEventIds": sorted({*event_ids, *_positive_ints(target.get("sourceEventIds"))}),
                "evidenceIds": list(dict.fromkeys([*_strings(target.get("evidenceIds")), *evidence_ids])),
                "confidence": max(float(operation["confidence"]), float(target.get("confidence") or 0.0)),
                "tags": _safe_tags([*_strings(target.get("tags")), *list(target.get("tags") or [])]),
                "validFromMs": int(target.get("validFromMs") or occurred_ms),
            }
        else:
            target = atom_by_ref.get(str(operation.get("atomRef") or ""), {})
            atom = {
                "operation": str(operation["op"]),
                "kind": str(operation["kind"]),
                "claimKey": str(operation["claimKey"]),
                "canonicalText": str(operation["canonicalText"]),
                "sourceEventIds": event_ids,
                "evidenceIds": evidence_ids,
                "confidence": float(operation["confidence"]),
                "qualityScore": float(operation["confidence"]),
                "tags": list(operation.get("tags") or []),
                "validFromMs": occurred_ms,
                "supersedesId": str(target.get("atomId") or ""),
            }
        atom.update(
            {
                "project": "",
                "app": "",
                "ownerKind": "user",
                "ownerId": "default",
                "knowledgeDomain": "personal_memory",
                "scopeKind": "user",
                "scopeId": "default",
                "visibility": "private",
                "authorizationRevision": "memory-atom-v2",
                "bindingId": "personal-memory:user:default",
                "scopeMode": "authoritative",
                "directCandidateAllowed": False,
            }
        )
        atoms.append(atom)

    return {
        "schemaVersion": PERSONAL_CURATION_SCHEMA_VERSION,
        "provider": compact_whitespace(str(getattr(executor, "provider", ""))),
        "model": compact_whitespace(str(getattr(executor, "model_id", ""))),
        "sourceDecisions": source_decisions,
        "memoryAtoms": atoms,
        "memoryRetractions": retractions,
        "dailyBooks": [],
        "topicBooks": [],
        "semanticGroups": [],
        "semanticTags": [],
        "tagMerges": [],
        "tagEdges": [],
        "phraseCandidates": [],
        "negativePhrases": [],
        "supersedes": [],
        "warnings": [],
        "elapsedMs": elapsed_ms,
        "modelBundleStats": {
            "sourceCount": len(evidence_by_ref),
            "existingAtomCount": len(atom_by_ref),
            "contextOnlyCount": len(packet.get("x") or []),
            "packetChars": len(json.dumps(packet, ensure_ascii=False, separators=(",", ":"))),
        },
        "modelDiagnostics": {
            name: _receipt_summary(receipt) for name, receipt in receipts.items()
        },
        "personalCurationV2": {
            "protocol": PERSONAL_CURATION_PROTOCOL_VERSION,
            "promptVersion": PERSONAL_CURATION_POLICY_REVISION,
            "independentlyVerified": True,
            "evidenceCount": len(evidence_by_ref),
            "operationCount": len(operations),
            "thresholds": {
                "durable": MIN_DURABLE_CONFIDENCE,
                "correction": MIN_CORRECTION_CONFIDENCE,
            },
        },
    }


def _complete_json(
    executor: Any,
    *,
    phase: str,
    system: str,
    packet: Mapping[str, object],
    max_tokens: int,
    isolated: bool = False,
) -> tuple[dict[str, object], dict[str, object]]:
    try:
        response = executor.complete(
            phase=phase,
            isolated=isolated,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": json.dumps(packet, ensure_ascii=False, separators=(",", ":")),
                },
            ],
        )
        text = _response_text(response)
        payload = json.loads(text)
    except PersonalMemoryCurationError:
        raise
    except Exception as exc:
        raise PersonalMemoryCurationError(
            f"{phase} failed: {compact_whitespace(str(exc))[:320]}"
        ) from exc
    if not isinstance(payload, dict):
        raise PersonalMemoryCurationError(f"{phase} returned a non-object JSON value")
    return dict(payload), _receipt_summary(response)


def _response_text(response: Mapping[str, object]) -> str:
    choices = response.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], Mapping):
        raise PersonalMemoryCurationError("model response has no single assistant choice")
    message = choices[0].get("message")
    if not isinstance(message, Mapping):
        raise PersonalMemoryCurationError("model response has no assistant message")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise PersonalMemoryCurationError("model response is empty")
    return content.strip()


def _evidence_prompt() -> str:
    return (
        f"Personal Memory Evidence pass; prompt {PERSONAL_CURATION_POLICY_REVISION}. "
        "Upstream has already reconstructed cumulative IME snapshots, removed duplicates, excluded "
        "sensitive or contextless fragments, and emitted complete source expressions. Do not denoise, "
        "merge, repair, or infer missing words here. The packet is compact JSON, not JSONL. p.e rows are "
        "[Eref,deltaMs,channelIndex,appIndex,boundaryKind,text]; p.a is the complete current "
        "Atom catalog; p.x is context-only; i may narrow the run but cannot relax this contract. "
        "Classify every E ref exactly once, using this decision procedure in order. The E-row text is "
        "the only claim-bearing source. "
        "Context x and metadata may disambiguate what the text refers to, but cannot add missing "
        "subject, scope, durability, polarity, intent, or facts. Repetition, app use, timing, and "
        "observed behavior do not prove a personal trait. "
        "First, use c only for an explicit correction or replacement of a specific current personal "
        "Atom, and f only for an explicit request to forget one; an ordinary edit request is neither. "
        "Second, scan every clause for a directly stated user-owned fact, habit, preference, principle, "
        "or rule for how the assistant should communicate, collaborate, explain, ask, review, decide, "
        "build, or present information. Judge that clause rather than the row's dominant project topic. "
        "A mixed task row can therefore contain a personal-memory candidate, while its task clauses stay "
        "outside Memory. Do not invent a 'current UI', 'current project', or 'current memory structure' "
        "scope merely from the surrounding topic, app, or timeline. "
        "Third, classify each personal candidate by scope. Use p at >=0.92 only when the text directly "
        "supports a durable claim useful beyond the immediate artifact. Use r whenever that personal "
        "reading is plausible but durability, scope, target, or claim boundaries are unclear. A direct "
        "first-person preference, a request for visibility into ongoing work, an information-organization "
        "preference, or an assistant-behavior rule must be p or r unless the same clause explicitly makes "
        "it one-off. Mentioning a UI, memory structure, or project does not by itself make the preference "
        "one-off; 'change this UI' is n, while 'I understand progress better when it stays visible' is r "
        "or p. Imperative wording alone does not decide durability. "
        "Use n only after this clause scan and only when every clause is non-personal: project or feature "
        "requirements, architecture choices, plans, tasks, tickets, progress, implementation state, "
        "commands, Tool or assistant output, docs, questions, temporary activity, or one-off artifact "
        "feedback. A model, Provider, Skill, Agent, Tool, language, or workflow selected for this run is n "
        "unless the text explicitly states a recurring cross-project habit. Calibration: p: 'When "
        "implementation is unclear, ask me and use natural wording.' r: 'I prefer this evidence/Atom "
        "structure' when future scope is not explicit. n: 'Use Luna for this batch; change this UI.' "
        "Preserve negation, modality, conditions, and qualifiers. Return exactly "
        "{\"v\":2,\"d\":[[\"E1\",\"p\",0.97,\"short_reason\"]]}. "
        "No prose or extra keys."
    )


def _atom_prompt() -> str:
    return (
        f"Personal Memory Atom pass; prompt {PERSONAL_CURATION_POLICY_REVISION}. "
        "Use only listed E refs as evidence and compare them with the complete current Atom catalog a. "
        "Produce operations that cover every E ref exactly once. Each Atom is one current user claim, "
        "not a topic summary, biography, activity log, or project record. "
        "When an E row mixes one personal claim with project content, extract only the directly "
        "supported personal claim and omit the project clause. "
        "Kinds: f=personal_fact,h=personal_habit,d=durable_preference,p=personal_principle. "
        "Attach to an existing Atom only when the meaning is equivalent, including its subject, scope, "
        "conditions, polarity, and strength. Merge several E refs only when they directly support that "
        "same claim. Do not merge related but independent claims. If one E row contains several "
        "independent durable claims that cannot be represented as one Atom without loss, send that ref "
        "to review rather than creating a compound Atom. "
        "For create or supersede, write a concise user-owned canonical claim. Preserve qualifiers, "
        "negation, modality, conditions, and scope; do not generalize a project-local choice into a "
        "global preference, invent a reason, or strengthen 'sometimes/prefer' into 'always'. Use a "
        "stable semantic claimKey, not a content hash or project/task name. Use a few stable human topic "
        "tags, not app names or transient project labels. Do not turn a model, Provider, Skill, Tool, "
        "language, or workflow selected for the current run into a personal claim. "
        "Operations: [\"c\",kind,claimKey,text,[refs],confidence,[tags]], "
        "[\"a\",atomRef,[refs],confidence], "
        "[\"s\",atomRef,kind,sameClaimKey,newText,[refs],confidence,[tags]], "
        "[\"x\",atomRef,[refs],confidence], or [\"r\",[refs],reason]. "
        "Create/attach needs >=0.92. Supersede needs >=0.95, the same claimKey and kind, and explicit "
        "correction language. Retract needs >=0.95 and explicit forget language targeting that Atom. "
        "Use review for ambiguity, conflict, uncertain target, unsupported scope, or unsafe merge/split. "
        "Never emit a Book, project claim, task state, command, Tool result, or unsupported fact. "
        "Return exactly {\"v\":2,\"o\":[...]}. No prose or extra keys."
    )


def _verifier_prompt() -> str:
    return (
        f"Personal Memory independent verifier; prompt {PERSONAL_CURATION_POLICY_REVISION}. "
        "Re-derive the result from packet p before reading decisions d and operations o; do not "
        "rubber-stamp either pass. Check every classification for both false positive and false negative "
        "errors. The E-row text must directly support a durable cross-project personal claim; context x, "
        "metadata, repetition, time, app use, and behavior may disambiguate but cannot supply a fact. "
        "Project requirements, artifact choices, plans, tasks, progress, commands, Tool/assistant output, "
        "docs, questions, and temporary activity must not become personal Memory. An explicit personal "
        "preference inside project discussion may remain personal when the E text itself states it. "
        "Inspect a mixed project row clause by clause so its dominant project topic does not hide a "
        "direct, ongoing interaction preference. "
        "Reject any current model/Provider/Skill/Tool choice promoted to a habit without explicit "
        "recurring cross-project language in the E text. "
        "Treat assistant-behavior ambiguity or a direct first-person preference with unclear durability "
        "as review; reject a batch that silently turns either into n. "
        "For every Atom operation, check exact ref coverage, current-catalog conflicts, duplicate claims, "
        "wrong attach, unsafe merge or split, compound claims, over-generalization, invented rationale, "
        "lost qualifier, polarity or modality, unstable claimKey, and project/app tags. Check that "
        "correction and forget operations explicitly target the current Atom, keep kind/key rules, and "
        "meet thresholds. A justified review is valid; silent loss of a directly supported durable claim "
        "is not. "
        "Mark every E ref and zero-based operation index exactly once. The second value is a verification "
        "flag, not the Evidence classification: a correct n (not-memory) decision still receives 1. "
        "Every row must be 1 when ok=1. If any row would be 0, return ok=0 and concise errors. Return "
        "exactly {\"v\":2,\"ok\":1,\"r\":[[\"E1\",1]],\"o\":[[0,1]],\"errors\":[]}. "
        "No prose or extra keys."
    )


def _operation_refs(value: object, *, eligible_refs: set[str], covered: set[str]) -> list[str]:
    refs = _strings(value)
    if not refs or len(refs) != len(set(refs)):
        raise PersonalMemoryCurationError("Atom operation refs are empty or duplicated")
    if any(ref not in eligible_refs or ref in covered for ref in refs):
        raise PersonalMemoryCurationError("Atom operation contains an unknown or reused Evidence ref")
    return refs


def _atom_ref(value: object, atoms: Mapping[str, object]) -> str:
    ref = compact_whitespace(str(value or ""))
    if ref not in atoms:
        raise PersonalMemoryCurationError("Atom operation targets an unknown current Atom")
    return ref


def _kind(value: object) -> str:
    code = compact_whitespace(str(value or "")).lower()
    if code not in _KIND_BY_CODE:
        raise PersonalMemoryCurationError("Atom operation contains an unsupported kind")
    return _KIND_BY_CODE[code]


def _claim_key(value: object) -> str:
    key = compact_whitespace(str(value or ""))[:120]
    if not key or key.startswith("sha256:"):
        raise PersonalMemoryCurationError("Atom claimKey is missing or content-addressed")
    return key


def _canonical(value: object) -> str:
    text = compact_whitespace(str(value or ""))[:500]
    if not text or contains_sensitive_content(text):
        raise PersonalMemoryCurationError("Atom canonical text is empty or sensitive")
    return text


def _safe_tags(value: object) -> list[str]:
    result: list[str] = []
    for raw in value if isinstance(value, (list, tuple)) else []:
        tag = compact_whitespace(str(raw or ""))[:48]
        if tag and not contains_sensitive_content(tag) and tag not in result:
            result.append(tag)
        if len(result) >= 6:
            break
    return result


def _confidence(value: object) -> float:
    if isinstance(value, bool):
        raise PersonalMemoryCurationError("confidence must be numeric")
    try:
        confidence = float(value)
    except (TypeError, ValueError) as exc:
        raise PersonalMemoryCurationError("confidence must be numeric") from exc
    if not 0.0 <= confidence <= 1.0:
        raise PersonalMemoryCurationError("confidence is outside [0,1]")
    return confidence


def _reason(value: object) -> str:
    reason = compact_whitespace(str(value or ""))[:160]
    if not reason:
        raise PersonalMemoryCurationError("a compact reason is required")
    return re.sub(r"[^a-zA-Z0-9_:-]+", "_", reason).strip("_") or "model_decision"


def _verified_pairs(value: object, *, key_type: type[str] | type[int]) -> set[Any]:
    if not isinstance(value, list):
        raise PersonalMemoryCurationError("verifier coverage must be a list")
    result: set[Any] = set()
    for row in value:
        if not isinstance(row, list) or len(row) != 2 or row[1] not in {1, True}:
            raise PersonalMemoryCurationError("verifier coverage row is invalid")
        try:
            key = key_type(row[0])
        except (TypeError, ValueError) as exc:
            raise PersonalMemoryCurationError("verifier coverage key is invalid") from exc
        if key in result:
            raise PersonalMemoryCurationError("verifier coverage contains a duplicate")
        result.add(key)
    return result


def _receipt_summary(value: Mapping[str, object]) -> dict[str, object]:
    receipt = value.get("receipt") if isinstance(value.get("receipt"), Mapping) else {}
    return {
        "requestId": compact_whitespace(str(value.get("requestId") or "")),
        "sessionId": compact_whitespace(str(receipt.get("sessionId") or "")),
        "turnId": compact_whitespace(str(value.get("turnId") or receipt.get("turnId") or "")),
        "inputSha256": compact_whitespace(str(receipt.get("inputSha256") or "")),
        "inputChars": int(receipt.get("inputChars") or 0),
    }


def _dictionary(values: object) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values))


def _strings(value: object) -> list[str]:
    values = value if isinstance(value, (list, tuple)) else []
    return list(
        dict.fromkeys(
            compact_whitespace(str(item or ""))
            for item in values
            if compact_whitespace(str(item or ""))
        )
    )


def _positive_ints(value: object) -> list[int]:
    values = value if isinstance(value, (list, tuple)) else []
    return sorted({int(item) for item in values if str(item).isdigit() and int(item) > 0})


def _estimated_tokens(value: str) -> int:
    cjk = len(re.findall(r"[\u3400-\u9fff]", value))
    return cjk + max(1, (len(value) - cjk + 3) // 4)


def _ref_ordinal(value: str) -> int:
    try:
        return int(value[1:])
    except (TypeError, ValueError):
        return 0


__all__ = [
    "MAX_CONTEXT_ONLY_ROWS",
    "MIN_CORRECTION_CONFIDENCE",
    "MIN_DURABLE_CONFIDENCE",
    "PERSONAL_CURATION_POLICY_REVISION",
    "PERSONAL_CURATION_PROTOCOL_VERSION",
    "PERSONAL_CURATION_SCHEMA_VERSION",
    "PersonalMemoryCurationError",
    "build_personal_memory_packet",
    "curate_personal_memory_v2",
]
