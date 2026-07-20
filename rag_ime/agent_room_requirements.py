from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path

from .contracts.json_schema import validate_contract
from .db import apply_database_migrations


_ITEM_KINDS = frozenset(
    {
        "explicit_user_requirement",
        "system_hard_constraint",
        "agent_inferred_requirement",
        "implementation_suggestion",
    }
)
_ITEM_STATES = frozenset({"active", "needs_confirmation", "withdrawn", "superseded"})
_RECEIPT_TYPES = frozenset({"test", "build", "install", "evidence"})
_TRUSTED_VERIFIERS = {
    "test": "managed-test-runner",
    "build": "managed-build-runner",
    "install": "managed-install-verifier",
    "evidence": "managed-evidence-verifier",
}


class RequirementRevisionConflict(RuntimeError):
    """The caller attempted to revise a stale or foreign RequirementCatalog."""


class RequirementEvidenceError(ValueError):
    """A proof attempted to use untyped, stale, or cross-scope evidence."""


class RequirementGovernanceStore:
    """Immutable original requirements plus revisioned derived catalogs and proof."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def initialize(self) -> int:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            return apply_database_migrations(conn).current_version

    def append_anchor(
        self,
        *,
        anchor_id: str,
        root_id: str,
        original_content: bytes | str,
        created_by: str,
        provenance: Mapping[str, object],
        created_at_ms: int,
        authenticity: str = "original_user_bytes",
    ) -> tuple[dict[str, object], bool]:
        content = original_content if isinstance(original_content, bytes) else original_content.encode("utf-8")
        if not content:
            raise ValueError("original requirement bytes must not be empty")
        if authenticity not in {"original_user_bytes", "legacy_quarantined"}:
            raise ValueError("unsupported RequirementAnchor authenticity")
        anchor = _required(anchor_id, "anchor_id")
        root = _required(root_id, "root_id")
        digest = _sha256(content)
        with self._connect(immediate=True) as conn:
            existing = conn.execute(
                "SELECT * FROM room_v2_requirement_anchors WHERE anchor_id = ?",
                (anchor,),
            ).fetchone()
            if existing is not None:
                payload = _anchor_payload(existing)
                if (
                    payload["rootId"] != root
                    or payload["originalContentSha256"] != digest
                    or payload["authenticity"] != authenticity
                ):
                    raise RequirementRevisionConflict("RequirementAnchor identity changed")
                return payload, False
            sequence = int(
                conn.execute(
                    "SELECT COALESCE(MAX(root_sequence), 0) + 1 FROM room_v2_requirement_anchors WHERE root_id = ?",
                    (root,),
                ).fetchone()[0]
            )
            conn.execute(
                """
                INSERT INTO room_v2_requirement_anchors(
                    anchor_id, root_id, root_sequence, original_bytes,
                    original_sha256, created_by, authenticity, provenance_json, created_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    anchor, root, sequence, content, digest,
                    _required(created_by, "created_by"), authenticity,
                    _json(dict(provenance)), _non_negative(created_at_ms, "created_at_ms"),
                ),
            )
            row = conn.execute(
                "SELECT * FROM room_v2_requirement_anchors WHERE anchor_id = ?",
                (anchor,),
            ).fetchone()
        return _anchor_payload(row), True

    def import_legacy_objective(
        self,
        *,
        anchor_id: str,
        root_id: str,
        objective: str,
        legacy_ref: str,
        created_at_ms: int,
    ) -> tuple[dict[str, object], bool]:
        return self.append_anchor(
            anchor_id=anchor_id,
            root_id=root_id,
            original_content=objective,
            created_by="legacy-import",
            provenance={"legacyRef": _required(legacy_ref, "legacy_ref"), "warning": "not_original_user_bytes"},
            created_at_ms=created_at_ms,
            authenticity="legacy_quarantined",
        )

    def original_bytes(self, anchor_id: str) -> bytes:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT original_bytes FROM room_v2_requirement_anchors WHERE anchor_id = ?",
                (_required(anchor_id, "anchor_id"),),
            ).fetchone()
        if row is None:
            raise KeyError(anchor_id)
        return bytes(row["original_bytes"])

    def revise_catalog(
        self,
        *,
        catalog_revision_id: str,
        root_id: str,
        expected_current_revision: int,
        anchor_refs: Sequence[str],
        items: Sequence[Mapping[str, object]],
        acceptance_criteria: Sequence[Mapping[str, object]],
        change_reason: str,
        provenance: Mapping[str, object],
        created_by: str,
        created_at_ms: int,
    ) -> tuple[dict[str, object], bool]:
        root = _required(root_id, "root_id")
        anchors = list(_refs(anchor_refs))
        if not anchors:
            raise ValueError("RequirementCatalog requires at least one RequirementAnchor")
        normalized_items = [_normalize_item(value) for value in items]
        if len({value["itemId"] for value in normalized_items}) != len(normalized_items):
            raise ValueError("RequirementCatalog item ids must be unique")
        normalized_criteria = [_normalize_criterion(value) for value in acceptance_criteria]
        item_ids = {value["itemId"] for value in normalized_items}
        if any(value["itemId"] not in item_ids for value in normalized_criteria):
            raise ValueError("AcceptanceCriterion must reference an item in the same revision")
        with self._connect(immediate=True) as conn:
            anchor_rows = conn.execute(
                f"SELECT * FROM room_v2_requirement_anchors WHERE anchor_id IN ({','.join('?' for _ in anchors)})",
                anchors,
            ).fetchall()
            if len(anchor_rows) != len(anchors) or any(str(row["root_id"]) != root for row in anchor_rows):
                raise RequirementRevisionConflict("RequirementAnchor belongs to another Root")
            quarantined = {str(row["anchor_id"]) for row in anchor_rows if row["authenticity"] != "original_user_bytes"}
            anchor_lengths = {
                str(row["anchor_id"]): len(bytes(row["original_bytes"])) for row in anchor_rows
            }
            for item in normalized_items:
                for span in item["sourceSpans"]:
                    if span["anchorId"] not in anchors:
                        raise ValueError("RequirementItem source span is outside catalog anchors")
                    if span["anchorId"] in quarantined:
                        raise RequirementRevisionConflict("legacy quarantined text cannot masquerade as original requirement")
                    if int(span["endByte"]) > anchor_lengths[span["anchorId"]]:
                        raise ValueError("RequirementItem source span exceeds original bytes")
            current = conn.execute(
                """
                SELECT * FROM room_v2_requirement_catalog_revisions
                WHERE root_id = ? ORDER BY revision DESC LIMIT 1
                """,
                (root,),
            ).fetchone()
            current_revision = int(current["revision"]) if current is not None else 0
            if current_revision != int(expected_current_revision):
                raise RequirementRevisionConflict(
                    f"RequirementCatalog revision changed: expected {expected_current_revision}, current {current_revision}"
                )
            revision = current_revision + 1
            supersedes = str(current["catalog_revision_id"]) if current is not None else None
            material = {
                "catalogRevisionId": _required(catalog_revision_id, "catalog_revision_id"),
                "rootId": root, "revision": revision,
                "supersedesRevisionId": supersedes, "anchorRefs": anchors,
                "items": normalized_items, "acceptanceCriteria": normalized_criteria,
                "changeReason": _required(change_reason, "change_reason"),
                "provenance": dict(provenance),
                "createdBy": _required(created_by, "created_by"),
                "createdAtMs": _non_negative(created_at_ms, "created_at_ms"),
            }
            payload = {
                "schemaVersion": "wisdom-weasel.requirement-catalog-revision.v1",
                **material,
                "payloadHash": _hash_json(material),
            }
            validate_contract(payload, "requirement-catalog-revision.v1.json")
            conn.execute(
                """
                INSERT INTO room_v2_requirement_catalog_revisions(
                    catalog_revision_id, root_id, revision, supersedes_revision_id,
                    anchor_refs_json, change_reason, provenance_json, payload_hash,
                    created_by, created_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["catalogRevisionId"], root, revision, supersedes,
                    _json(anchors), payload["changeReason"], _json(payload["provenance"]),
                    payload["payloadHash"], payload["createdBy"], payload["createdAtMs"],
                ),
            )
            for item in normalized_items:
                conn.execute(
                    """
                    INSERT INTO room_v2_requirement_items(
                        catalog_revision_id, item_id, kind, statement, origin, state,
                        source_spans_json, supersedes_json, ambiguity, confirmation
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        payload["catalogRevisionId"], item["itemId"], item["kind"],
                        item["statement"], item["origin"], item["state"],
                        _json(item["sourceSpans"]), _json(item["supersedes"]),
                        item["ambiguity"], item["confirmation"],
                    ),
                )
            for criterion in normalized_criteria:
                conn.execute(
                    """
                    INSERT INTO room_v2_acceptance_criteria(
                        catalog_revision_id, criterion_id, item_id,
                        acceptance_criterion_full_name_zh, criterion_kind,
                        expected_receipt_types_json, statement
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        payload["catalogRevisionId"], criterion["criterionId"],
                        criterion["itemId"], criterion["acceptanceCriterionFullNameZh"],
                        criterion["criterionKind"], _json(criterion["expectedReceiptTypes"]),
                        criterion["statement"],
                    ),
                )
        return payload, True

    def record_verification_receipt(
        self,
        receipt: Mapping[str, object] | object,
    ) -> tuple[dict[str, object], bool]:
        if not isinstance(receipt, Mapping):
            raise RequirementEvidenceError("proof requires a typed verification receipt, not Agent text")
        payload = dict(receipt)
        try:
            validate_contract(payload, "typed-verification-receipt.v1.json")
        except ValueError as exc:
            raise RequirementEvidenceError(str(exc)) from exc
        if payload["verifier"] != _TRUSTED_VERIFIERS[payload["receiptType"]]:
            raise RequirementEvidenceError(
                "Agent self-report is not a trusted typed verification receipt"
            )
        with self._connect(immediate=True) as conn:
            catalog = self._catalog_row(conn, str(payload["catalogRevisionId"]))
            if str(catalog["root_id"]) != payload["rootId"]:
                raise RequirementEvidenceError("verification receipt belongs to another Root")
            existing = conn.execute(
                "SELECT * FROM room_v2_verification_receipts WHERE receipt_id = ?",
                (payload["receiptId"],),
            ).fetchone()
            if existing is not None:
                stored = _verification_payload(existing)
                if stored != payload:
                    raise RequirementEvidenceError("verification receipt identity changed")
                return stored, False
            digest = _hash_json(payload)
            conn.execute(
                """
                INSERT INTO room_v2_verification_receipts(
                    receipt_id, root_id, catalog_revision_id, receipt_type,
                    source_commit, environment, command_or_action, exit_status,
                    output_hash, artifact_hash, verifier, payload_hash, created_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["receiptId"], payload["rootId"], payload["catalogRevisionId"],
                    payload["receiptType"], payload["sourceCommit"], payload["environment"],
                    payload["commandOrAction"], payload["exitStatus"], payload["outputHash"],
                    payload["artifactHash"], payload["verifier"], digest, payload["createdAtMs"],
                ),
            )
        return payload, True

    def link_proof(
        self,
        *,
        proof_id: str,
        root_id: str,
        catalog_revision_id: str,
        criterion_id: str,
        receipt_id: str,
        linked_by: str,
        created_at_ms: int,
    ) -> dict[str, object]:
        with self._connect(immediate=True) as conn:
            criterion = conn.execute(
                """
                SELECT * FROM room_v2_acceptance_criteria
                WHERE catalog_revision_id = ? AND criterion_id = ?
                """,
                (catalog_revision_id, criterion_id),
            ).fetchone()
            receipt = conn.execute(
                "SELECT * FROM room_v2_verification_receipts WHERE receipt_id = ?",
                (receipt_id,),
            ).fetchone()
            if criterion is None or receipt is None:
                raise RequirementEvidenceError("proof requires existing typed criterion and receipt")
            if (
                str(receipt["root_id"]) != root_id
                or str(receipt["catalog_revision_id"]) != catalog_revision_id
                or str(receipt["receipt_type"]) not in json.loads(str(criterion["expected_receipt_types_json"]))
            ):
                raise RequirementEvidenceError("proof receipt scope or type does not match criterion")
            conn.execute(
                """
                INSERT INTO room_v2_criterion_proofs(
                    proof_id, root_id, catalog_revision_id, criterion_id,
                    receipt_id, linked_by, created_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _required(proof_id, "proof_id"), _required(root_id, "root_id"),
                    _required(catalog_revision_id, "catalog_revision_id"),
                    _required(criterion_id, "criterion_id"), _required(receipt_id, "receipt_id"),
                    _required(linked_by, "linked_by"), _non_negative(created_at_ms, "created_at_ms"),
                ),
            )
        return {"proofId": proof_id, "criterionId": criterion_id, "receiptId": receipt_id}

    def record_conflict(
        self,
        *,
        conflict_id: str,
        root_id: str,
        catalog_revision_id: str,
        left_item_id: str,
        right_item_id: str,
        conflict_kind: str,
        status: str = "open",
        resolution: str = "",
        created_at_ms: int,
    ) -> None:
        if conflict_kind not in {"contradiction", "unknown", "ambiguity"}:
            raise ValueError("unsupported requirement conflict kind")
        if status not in {"open", "resolved"}:
            raise ValueError("unsupported conflict status")
        with self._connect(immediate=True) as conn:
            catalog = self._catalog_row(conn, catalog_revision_id)
            if str(catalog["root_id"]) != root_id:
                raise RequirementRevisionConflict("conflict belongs to another Root")
            item_count = conn.execute(
                "SELECT COUNT(*) FROM room_v2_requirement_items WHERE catalog_revision_id = ? AND item_id IN (?, ?)",
                (catalog_revision_id, left_item_id, right_item_id),
            ).fetchone()[0]
            if int(item_count) != len({left_item_id, right_item_id}):
                raise ValueError("conflict must reference RequirementItems in the same revision")
            conn.execute(
                """
                INSERT INTO room_v2_requirement_conflicts(
                    conflict_id, root_id, catalog_revision_id, left_item_id,
                    right_item_id, conflict_kind, status, resolution, created_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    conflict_id, root_id, catalog_revision_id, left_item_id,
                    right_item_id, conflict_kind, status, resolution, created_at_ms,
                ),
            )

    def record_obstacle(
        self,
        *,
        obstacle_id: str,
        root_id: str,
        catalog_revision_id: str,
        obstacle_kind: str,
        statement: str,
        status: str = "open",
        created_at_ms: int,
    ) -> None:
        if obstacle_kind not in {"blocker", "unknown"} or status not in {"open", "resolved"}:
            raise ValueError("unsupported delivery obstacle")
        with self._connect(immediate=True) as conn:
            catalog = self._catalog_row(conn, catalog_revision_id)
            if str(catalog["root_id"]) != root_id:
                raise RequirementRevisionConflict("obstacle belongs to another Root")
            conn.execute(
                """
                INSERT INTO room_v2_delivery_obstacles(
                    obstacle_id, root_id, catalog_revision_id, obstacle_kind,
                    statement, status, created_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (obstacle_id, root_id, catalog_revision_id, obstacle_kind, statement, status, created_at_ms),
            )

    def observe_delivery_gate(
        self,
        *,
        gate_receipt_id: str,
        root_id: str,
        catalog_revision_id: str,
        target_commit: str,
        blind_review_status: str,
        created_at_ms: int,
    ) -> dict[str, object]:
        if blind_review_status not in {"pending", "passed", "failed", "unavailable"}:
            raise ValueError("unsupported blind review status")
        with self._connect(immediate=True) as conn:
            catalog = self._catalog_row(conn, catalog_revision_id)
            current = conn.execute(
                "SELECT catalog_revision_id FROM room_v2_requirement_catalog_revisions WHERE root_id = ? ORDER BY revision DESC LIMIT 1",
                (root_id,),
            ).fetchone()
            if str(catalog["root_id"]) != root_id or current is None or current[0] != catalog_revision_id:
                raise RequirementRevisionConflict("old RequirementCatalog revision cannot gate a new/current Root state")
            items = conn.execute(
                "SELECT * FROM room_v2_requirement_items WHERE catalog_revision_id = ?",
                (catalog_revision_id,),
            ).fetchall()
            criteria = conn.execute(
                "SELECT * FROM room_v2_acceptance_criteria WHERE catalog_revision_id = ?",
                (catalog_revision_id,),
            ).fetchall()
            criterion_item_ids = {str(row["item_id"]) for row in criteria}
            reasons: list[str] = []
            effective_items = [
                row for row in items
                if row["state"] == "active"
                and row["kind"] in {"explicit_user_requirement", "system_hard_constraint"}
            ]
            uncovered = [str(row["item_id"]) for row in effective_items if row["item_id"] not in criterion_item_ids]
            if uncovered:
                reasons.append("requirements_without_acceptance_criteria:" + ",".join(uncovered))
            if any(row["state"] == "needs_confirmation" for row in items):
                reasons.append("requirements_need_confirmation")
            matrix: list[dict[str, object]] = []
            for criterion in criteria:
                proofs = conn.execute(
                    """
                    SELECT receipt.* FROM room_v2_criterion_proofs proof
                    JOIN room_v2_verification_receipts receipt ON receipt.receipt_id = proof.receipt_id
                    WHERE proof.catalog_revision_id = ? AND proof.criterion_id = ?
                    """,
                    (catalog_revision_id, criterion["criterion_id"]),
                ).fetchall()
                valid = [
                    row for row in proofs
                    if int(row["exit_status"]) == 0 and str(row["source_commit"]) == target_commit
                ]
                passed = bool(valid)
                matrix.append(
                    {
                        "criterionId": str(criterion["criterion_id"]),
                        "acceptanceCriterionFullNameZh": str(criterion["acceptance_criterion_full_name_zh"]),
                        "criterionKind": str(criterion["criterion_kind"]),
                        "passed": passed,
                        "receiptIds": [str(row["receipt_id"]) for row in valid],
                    }
                )
                if not passed:
                    reasons.append("criterion_without_valid_proof:" + str(criterion["criterion_id"]))
            journeys = [item for item in matrix if item["criterionKind"] == "user_journey"]
            if not journeys:
                reasons.append("user_journey_missing")
            elif not all(bool(item["passed"]) for item in journeys):
                reasons.append("user_journey_failed")
            open_conflicts = conn.execute(
                "SELECT conflict_kind FROM room_v2_requirement_conflicts WHERE catalog_revision_id = ? AND status = 'open'",
                (catalog_revision_id,),
            ).fetchall()
            if open_conflicts:
                reasons.append("unresolved_conflict_or_unknown")
            open_obstacles = conn.execute(
                "SELECT obstacle_kind FROM room_v2_delivery_obstacles WHERE catalog_revision_id = ? AND status = 'open'",
                (catalog_revision_id,),
            ).fetchall()
            if any(row[0] == "blocker" for row in open_obstacles):
                reasons.append("unresolved_blocker")
            if any(row[0] == "unknown" for row in open_obstacles):
                reasons.append("unresolved_unknown")
            if blind_review_status != "passed":
                reasons.append("blind_review_not_passed")
            payload = {
                "schemaVersion": "wisdom-weasel.delivery-gate-observation.v1",
                "gateReceiptId": _required(gate_receipt_id, "gate_receipt_id"),
                "rootId": root_id, "catalogRevisionId": catalog_revision_id,
                "targetCommit": _required(target_commit, "target_commit"),
                "mode": "observe_warn",
                "gateStatus": "warn_blocked" if reasons else "observed_pass",
                "enforcementApplied": False,
                "blindReviewStatus": blind_review_status,
                "reasons": list(dict.fromkeys(reasons)), "proofMatrix": matrix,
                "createdAtMs": _non_negative(created_at_ms, "created_at_ms"),
            }
            validate_contract(payload, "delivery-gate-observation.v1.json")
            conn.execute(
                """
                INSERT INTO room_v2_delivery_gate_receipts(
                    gate_receipt_id, root_id, catalog_revision_id, target_commit,
                    mode, gate_status, enforcement_applied, blind_review_status,
                    reasons_json, proof_matrix_json, created_at_ms
                ) VALUES (?, ?, ?, ?, 'observe_warn', ?, 0, ?, ?, ?, ?)
                """,
                (
                    payload["gateReceiptId"], root_id, catalog_revision_id, target_commit,
                    payload["gateStatus"], blind_review_status, _json(payload["reasons"]),
                    _json(matrix), payload["createdAtMs"],
                ),
            )
        return payload

    @staticmethod
    def _catalog_row(conn: sqlite3.Connection, catalog_revision_id: str) -> sqlite3.Row:
        row = conn.execute(
            "SELECT * FROM room_v2_requirement_catalog_revisions WHERE catalog_revision_id = ?",
            (_required(catalog_revision_id, "catalog_revision_id"),),
        ).fetchone()
        if row is None:
            raise KeyError(catalog_revision_id)
        return row

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


def _anchor_payload(row: sqlite3.Row) -> dict[str, object]:
    payload = {
        "schemaVersion": "wisdom-weasel.requirement-anchor.v1",
        "anchorId": str(row["anchor_id"]), "rootId": str(row["root_id"]),
        "rootSequence": int(row["root_sequence"]),
        "originalContentSha256": str(row["original_sha256"]),
        "originalByteLength": len(bytes(row["original_bytes"])),
        "createdBy": str(row["created_by"]), "authenticity": str(row["authenticity"]),
        "provenance": json.loads(str(row["provenance_json"])),
        "createdAtMs": int(row["created_at_ms"]),
    }
    validate_contract(payload, "requirement-anchor.v1.json")
    return payload


def _verification_payload(row: sqlite3.Row) -> dict[str, object]:
    return {
        "schemaVersion": "wisdom-weasel.typed-verification-receipt.v1",
        "receiptId": str(row["receipt_id"]), "rootId": str(row["root_id"]),
        "catalogRevisionId": str(row["catalog_revision_id"]),
        "receiptType": str(row["receipt_type"]), "sourceCommit": str(row["source_commit"]),
        "environment": str(row["environment"]),
        "commandOrAction": str(row["command_or_action"]), "exitStatus": int(row["exit_status"]),
        "outputHash": str(row["output_hash"]), "artifactHash": str(row["artifact_hash"]),
        "verifier": str(row["verifier"]), "createdAtMs": int(row["created_at_ms"]),
    }


def _normalize_item(value: Mapping[str, object]) -> dict[str, object]:
    kind = _required(value.get("kind"), "RequirementItem.kind")
    state = _required(value.get("state") or "active", "RequirementItem.state")
    if kind not in _ITEM_KINDS or state not in _ITEM_STATES:
        raise ValueError("unsupported RequirementItem kind/state")
    spans: list[dict[str, object]] = []
    for raw in value.get("sourceSpans") or []:
        if not isinstance(raw, Mapping):
            raise ValueError("RequirementItem source span must be structured")
        start, end = int(raw.get("startByte", -1)), int(raw.get("endByte", -1))
        if start < 0 or end <= start:
            raise ValueError("RequirementItem source span must be a positive byte range")
        spans.append({"anchorId": _required(raw.get("anchorId"), "span.anchorId"), "startByte": start, "endByte": end})
    if kind in {"explicit_user_requirement", "system_hard_constraint"} and not spans:
        raise ValueError("effective RequirementItem requires source spans")
    return {
        "itemId": _required(value.get("itemId"), "RequirementItem.itemId"),
        "kind": kind, "statement": _required(value.get("statement"), "RequirementItem.statement"),
        "origin": _required(value.get("origin"), "RequirementItem.origin"), "state": state,
        "sourceSpans": spans, "supersedes": list(_refs(value.get("supersedes") or [])),
        "ambiguity": str(value.get("ambiguity") or ""),
        "confirmation": str(value.get("confirmation") or ""),
    }


def _normalize_criterion(value: Mapping[str, object]) -> dict[str, object]:
    types = list(_refs(value.get("expectedReceiptTypes") or []))
    if not types or any(receipt_type not in _RECEIPT_TYPES for receipt_type in types):
        raise ValueError("AcceptanceCriterion requires supported typed receipt types")
    kind = _required(value.get("criterionKind") or "requirement", "criterionKind")
    if kind not in {"requirement", "user_journey"}:
        raise ValueError("unsupported AcceptanceCriterion kind")
    full_name_zh = _required(
        value.get("acceptanceCriterionFullNameZh"), "acceptanceCriterionFullNameZh"
    )
    if not any("\u4e00" <= character <= "\u9fff" for character in full_name_zh):
        raise ValueError("acceptanceCriterionFullNameZh must contain a Chinese full name")
    return {
        "criterionId": _required(value.get("criterionId"), "criterionId"),
        "itemId": _required(value.get("itemId"), "itemId"),
        "acceptanceCriterionFullNameZh": full_name_zh,
        "criterionKind": kind, "expectedReceiptTypes": types,
        "statement": _required(value.get("statement"), "criterion.statement"),
    }


def _refs(values: Sequence[object]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))


def _required(value: object, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field} is required")
    return normalized


def _non_negative(value: object, field: str) -> int:
    normalized = int(value)
    if normalized < 0:
        raise ValueError(f"{field} must be non-negative")
    return normalized


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _hash_json(value: object) -> str:
    return _sha256(_json(value).encode("utf-8"))


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
