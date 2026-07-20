from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path

from .contracts.json_schema import validate_contract
from .db import apply_database_migrations


class PeerReviewFenceError(RuntimeError):
    pass


class RunnerReceiptError(ValueError):
    pass


_FORBIDDEN_BLIND_KEYS = {
    "author", "authorid", "authorparticipantid", "authorparticipantids",
    "authoridentity", "conclusion", "verdict", "recommendation", "agentanswer",
}
_BLIND_INPUT_KEYS = {"requirements", "artifactRefs", "proofRefs", "reviewInstructions"}


class RoomPeerReviewStore:
    """Sealed blind review, independent judgments, and signed runner evidence."""

    def __init__(self, db_path: str | Path, *, runner_secrets: Mapping[str, bytes | str] | None = None) -> None:
        self.db_path = Path(db_path)
        self._runner_secrets = {
            str(key): value if isinstance(value, bytes) else str(value).encode("utf-8")
            for key, value in (runner_secrets or {}).items()
        }

    def initialize(self) -> int:
        with self._connect() as conn:
            return apply_database_migrations(conn).current_version

    def issue_runner_receipt(self, material: Mapping[str, object], *, issuer_secret: bytes | str) -> dict[str, object]:
        payload = dict(material)
        payload["schemaVersion"] = "wisdom-weasel.runner-verification-receipt.v2"
        payload.pop("contentHash", None)
        payload.pop("issuerSignature", None)
        content_hash = _hash_json(payload)
        secret = issuer_secret if isinstance(issuer_secret, bytes) else issuer_secret.encode("utf-8")
        return {**payload, "contentHash": content_hash, "issuerSignature": hmac.new(secret, content_hash.encode(), hashlib.sha256).hexdigest()}

    def record_runner_receipt(self, receipt: Mapping[str, object]) -> tuple[dict[str, object], bool]:
        payload = dict(receipt)
        try:
            validate_contract(payload, "runner-verification-receipt.v2.json")
        except ValueError as exc:
            raise RunnerReceiptError(str(exc)) from exc
        secret = self._runner_secrets.get(str(payload["issuerId"]))
        unsigned = {key: value for key, value in payload.items() if key not in {"contentHash", "issuerSignature"}}
        expected_hash = _hash_json(unsigned)
        expected_signature = hmac.new(secret or b"", expected_hash.encode(), hashlib.sha256).hexdigest()
        if secret is None or not hmac.compare_digest(str(payload["contentHash"]), expected_hash) or not hmac.compare_digest(str(payload["issuerSignature"]), expected_signature):
            raise RunnerReceiptError("runner receipt signature/content hash is not trusted")
        with self._connect(immediate=True) as conn:
            catalog = conn.execute("SELECT root_id FROM room_v2_requirement_catalog_revisions WHERE catalog_revision_id = ?", (payload["catalogRevisionId"],)).fetchone()
            if catalog is None or str(catalog[0]) != payload["rootId"]:
                raise RunnerReceiptError("runner receipt uses an old or foreign catalog revision")
            current = conn.execute("SELECT catalog_revision_id FROM room_v2_requirement_catalog_revisions WHERE root_id = ? ORDER BY revision DESC LIMIT 1", (payload["rootId"],)).fetchone()
            if current is None or str(current[0]) != payload["catalogRevisionId"]:
                raise RunnerReceiptError("runner receipt uses an old or foreign catalog revision")
            existing = conn.execute("SELECT receipt_content_hash FROM room_v2_verification_receipts WHERE receipt_id = ?", (payload["receiptId"],)).fetchone()
            if existing is not None:
                if str(existing[0]) != expected_hash:
                    raise RunnerReceiptError("receipt id replay changed content")
                return payload, False
            duplicate = conn.execute(
                """SELECT receipt_id FROM room_v2_verification_receipts
                   WHERE issuer_trust = 'runner_signed' AND issuer_id = ? AND root_id = ?
                     AND catalog_revision_id = ? AND runner_receipt_type = ?
                     AND source_commit = ? AND worktree_hash = ? AND command_or_action = ?
                     AND output_hash = ? AND artifact_hash = ?""",
                (payload["issuerId"], payload["rootId"], payload["catalogRevisionId"],
                 payload["receiptType"], payload["sourceCommit"], payload["worktreeHash"],
                 payload["commandOrAction"], payload["outputHash"], payload["artifactHash"]),
            ).fetchone()
            if duplicate is not None:
                raise RunnerReceiptError("copied runner receipt replay")
            conn.execute(
                """INSERT INTO room_v2_verification_receipts(
                   receipt_id, root_id, catalog_revision_id, receipt_type, source_commit,
                   environment, command_or_action, exit_status, output_hash, artifact_hash,
                   verifier, payload_hash, created_at_ms, receipt_schema_version, worktree_hash,
                   tool_version, receipt_content_hash, issuer_id, issuer_signature, issuer_trust,
                   runner_receipt_type
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'runner_signed', ?)""",
                (payload["receiptId"], payload["rootId"], payload["catalogRevisionId"], "evidence" if payload["receiptType"] == "browser" else payload["receiptType"], payload["sourceCommit"], payload["environment"], payload["commandOrAction"], payload["exitStatus"], payload["outputHash"], payload["artifactHash"], payload["issuerId"], expected_hash, payload["createdAtMs"], payload["schemaVersion"], payload["worktreeHash"], payload["toolVersion"], expected_hash, payload["issuerId"], payload["issuerSignature"], payload["receiptType"]),
            )
        return payload, True

    def open_round(self, *, round_id: str, room_id: str, root_id: str, catalog_revision_id: str, target_commit: str, artifact_content_hash: str, blind_input: Mapping[str, object], author_participant_ids: Sequence[str], minimum_reviewers: int, created_at_ms: int) -> dict[str, object]:
        if minimum_reviewers < 2:
            raise PeerReviewFenceError("blind peer review requires at least two reviewers")
        _assert_blind(blind_input)
        if not blind_input or any(str(key) not in _BLIND_INPUT_KEYS for key in blind_input):
            raise PeerReviewFenceError("blind phase input only accepts server-curated refs and instructions")
        if any(
            not isinstance(value, Sequence)
            or isinstance(value, (str, bytes))
            or any(not isinstance(item, str) for item in value)
            for value in blind_input.values()
        ):
            raise PeerReviewFenceError("blind phase input values must be server-curated string lists")
        authors = _refs(author_participant_ids)
        if not authors:
            raise PeerReviewFenceError("author chain must be server recorded")
        blind_serialized = _json(blind_input)
        if any(author in blind_serialized for author in authors):
            raise PeerReviewFenceError("blind phase input leaks an author identity value")
        with self._connect(immediate=True) as conn:
            catalog = conn.execute("SELECT root_id FROM room_v2_requirement_catalog_revisions WHERE catalog_revision_id = ?", (catalog_revision_id,)).fetchone()
            if catalog is None or str(catalog[0]) != root_id:
                raise PeerReviewFenceError("round catalog is foreign")
            current = conn.execute("SELECT catalog_revision_id FROM room_v2_requirement_catalog_revisions WHERE root_id = ? ORDER BY revision DESC LIMIT 1", (root_id,)).fetchone()
            if current is None or str(current[0]) != catalog_revision_id:
                raise PeerReviewFenceError("round catalog revision is stale")
            count = conn.execute(f"SELECT COUNT(*) FROM agent_room_participants WHERE room_id = ? AND id IN ({','.join('?' for _ in authors)})", (room_id, *authors)).fetchone()[0]
            if int(count) != len(authors):
                raise PeerReviewFenceError("author chain is not canonical Room participation")
            payload = {"roundId": round_id, "roomId": room_id, "rootId": root_id, "catalogRevisionId": catalog_revision_id, "targetCommit": target_commit, "artifactContentHash": artifact_content_hash, "blindInputHash": _hash_json(blind_input), "minimumReviewers": minimum_reviewers, "createdAtMs": created_at_ms}
            conn.execute("INSERT INTO room_v2_peer_judgment_rounds VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (round_id, room_id, root_id, catalog_revision_id, target_commit, artifact_content_hash, payload["blindInputHash"], blind_serialized, _json(authors), minimum_reviewers, created_at_ms))
        return payload

    def blind_input(self, round_id: str) -> dict[str, object]:
        with self._connect() as conn:
            row = conn.execute("SELECT blind_input_json FROM room_v2_peer_judgment_rounds WHERE round_id = ?", (round_id,)).fetchone()
        if row is None:
            raise KeyError(round_id)
        return json.loads(str(row[0]))

    def submit_judgment(self, *, judgment_id: str, round_id: str, reviewer_participant_id: str, verdict: str, findings: Sequence[Mapping[str, object]], requirement_coverage: Sequence[str], created_at_ms: int) -> dict[str, object]:
        if verdict not in {"pass", "fail", "abstain"}:
            raise ValueError("unsupported peer verdict")
        with self._connect(immediate=True) as conn:
            round_row = conn.execute("SELECT * FROM room_v2_peer_judgment_rounds WHERE round_id = ?", (round_id,)).fetchone()
            if round_row is None:
                raise KeyError(round_id)
            authors = set(json.loads(str(round_row["author_participant_ids_json"])))
            participant = conn.execute("SELECT * FROM agent_room_participants WHERE id = ? AND room_id = ? AND participant_status = 'active'", (reviewer_participant_id, round_row["room_id"])).fetchone()
            if participant is None or reviewer_participant_id in authors:
                raise PeerReviewFenceError("author cannot self-review or reviewer is ineligible")
            binding = self._eligible_binding(conn, str(participant["session_id"]), str(round_row["room_id"]), str(round_row["root_id"]), role="reviewer")
            criteria = {str(row[0]) for row in conn.execute("SELECT criterion_id FROM room_v2_acceptance_criteria WHERE catalog_revision_id = ?", (round_row["catalog_revision_id"],)).fetchall()}
            coverage = set(_refs(requirement_coverage))
            if verdict == "pass" and coverage != criteria:
                raise PeerReviewFenceError("pass verdict must cover every acceptance criterion")
            normalized_findings = [_finding(item, criteria) for item in findings]
            material = {"judgmentId": judgment_id, "roundId": round_id, "reviewerParticipantId": reviewer_participant_id, "verdict": verdict, "findings": normalized_findings, "requirementCoverage": sorted(coverage), "createdAtMs": created_at_ms}
            independence = str(participant["session_id"])
            try:
                conn.execute("INSERT INTO room_v2_peer_judgments VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (judgment_id, round_id, reviewer_participant_id, participant["session_id"], binding["bindingId"], independence, verdict, _json(material["findings"]), _json(material["requirementCoverage"]), _hash_json(material), created_at_ms))
            except sqlite3.IntegrityError as exc:
                raise PeerReviewFenceError("duplicate or colluding reviewer identity") from exc
        return material

    def finalize_round(self, *, final_receipt_id: str, round_id: str, matrix_revision_id: str, created_at_ms: int) -> dict[str, object]:
        with self._connect(immediate=True) as conn:
            round_row = conn.execute("SELECT * FROM room_v2_peer_judgment_rounds WHERE round_id = ?", (round_id,)).fetchone()
            judgments = conn.execute("SELECT * FROM room_v2_peer_judgments WHERE round_id = ? ORDER BY judgment_id", (round_id,)).fetchall()
            if round_row is None or len(judgments) < int(round_row["minimum_reviewers"]):
                raise PeerReviewFenceError("insufficient independent judgments")
            verdicts = {str(row["verdict"]) for row in judgments}
            matrix_id = None
            if verdicts == {"pass"}: status = "passed"
            elif verdicts <= {"fail", "abstain"}: status = "failed"
            else:
                status, matrix_id = "conflict", matrix_revision_id
                entries = [{"judgmentId": str(row["judgment_id"]), "verdict": str(row["verdict"]), "findingCodes": [str(x.get("code") or "") for x in json.loads(str(row["findings_json"]))]} for row in judgments]
                conn.execute("INSERT INTO room_v2_conflict_matrix_revisions VALUES (?, ?, 1, NULL, 'open', ?, ?, ?)", (matrix_id, round_id, _json(entries), _hash_json(entries), created_at_ms))
            ids = [str(row["judgment_id"]) for row in judgments]
            material = {"finalReceiptId": final_receipt_id, "roundId": round_id, "status": status, "judgmentIds": ids, "conflictMatrixRevisionId": matrix_id, "createdAtMs": created_at_ms}
            conn.execute("INSERT INTO room_v2_peer_judgment_final_receipts VALUES (?, ?, ?, ?, ?, NULL, ?, ?)", (final_receipt_id, round_id, status, _json(ids), matrix_id, _hash_json(material), created_at_ms))
        return material

    def resolve_conflict(self, *, resolution_receipt_id: str, round_id: str, open_matrix_revision_id: str, resolved_matrix_revision_id: str, authority_kind: str, authority_ref: str, resolution_verdict: str, rationale: str, created_at_ms: int) -> dict[str, object]:
        if authority_kind not in {"independent_arbiter", "user"} or resolution_verdict not in {"pass", "fail"}:
            raise ValueError("unsupported conflict resolution")
        with self._connect(immediate=True) as conn:
            matrix = conn.execute("SELECT * FROM room_v2_conflict_matrix_revisions WHERE matrix_revision_id = ? AND round_id = ? AND status = 'open'", (open_matrix_revision_id, round_id)).fetchone()
            if matrix is None:
                raise PeerReviewFenceError("conflict matrix is not current/open")
            if authority_kind == "independent_arbiter":
                participant = conn.execute("SELECT session_id FROM agent_room_participants WHERE id = ? AND participant_status = 'active'", (authority_ref,)).fetchone()
                if participant is None:
                    raise PeerReviewFenceError("arbiter is not canonical")
                round_row = conn.execute("SELECT room_id, root_id, author_participant_ids_json FROM room_v2_peer_judgment_rounds WHERE round_id = ?", (round_id,)).fetchone()
                reviewer_ids = {str(row[0]) for row in conn.execute("SELECT reviewer_participant_id FROM room_v2_peer_judgments WHERE round_id = ?", (round_id,)).fetchall()}
                if authority_ref in reviewer_ids or authority_ref in set(json.loads(str(round_row[2]))):
                    raise PeerReviewFenceError("arbiter must be independent of authors and reviewers")
                self._eligible_binding(conn, str(participant[0]), str(round_row[0]), str(round_row[1]), role="coordinator")
            elif not authority_ref.startswith("user:"):
                raise PeerReviewFenceError("user resolution requires authenticated user authority ref")
            entries = json.loads(str(matrix["entries_json"]))
            resolution = {"resolutionReceiptId": resolution_receipt_id, "roundId": round_id, "matrixRevisionId": resolved_matrix_revision_id, "authorityKind": authority_kind, "authorityRef": authority_ref, "resolutionVerdict": resolution_verdict, "rationale": rationale, "createdAtMs": created_at_ms}
            conn.execute("INSERT INTO room_v2_conflict_matrix_revisions VALUES (?, ?, ?, ?, 'resolved', ?, ?, ?)", (resolved_matrix_revision_id, round_id, int(matrix["revision"]) + 1, open_matrix_revision_id, _json({"entries": entries, "resolution": resolution}), _hash_json(resolution), created_at_ms))
            conn.execute("INSERT INTO room_v2_conflict_resolution_receipts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (resolution_receipt_id, round_id, resolved_matrix_revision_id, authority_kind, authority_ref, resolution_verdict, rationale, _hash_json(resolution), created_at_ms))
        return resolution

    def preview_delivery_gate(self, *, preview_receipt_id: str, root_id: str, catalog_revision_id: str, peer_round_id: str, target_commit: str, environment: str, created_at_ms: int) -> dict[str, object]:
        with self._connect(immediate=True) as conn:
            current = conn.execute("SELECT catalog_revision_id FROM room_v2_requirement_catalog_revisions WHERE root_id = ? ORDER BY revision DESC LIMIT 1", (root_id,)).fetchone()
            reasons: list[str] = []
            if current is None or str(current[0]) != catalog_revision_id: reasons.append("stale_catalog_revision")
            round_row = conn.execute("SELECT * FROM room_v2_peer_judgment_rounds WHERE round_id = ?", (peer_round_id,)).fetchone()
            final = conn.execute("SELECT * FROM room_v2_peer_judgment_final_receipts WHERE round_id = ?", (peer_round_id,)).fetchone()
            if round_row is None or str(round_row["root_id"]) != root_id or str(round_row["catalog_revision_id"]) != catalog_revision_id or str(round_row["target_commit"]) != target_commit: reasons.append("blind_review_scope_mismatch")
            review_passed = final is not None and str(final["status"]) == "passed"
            if final is not None and str(final["status"]) == "conflict":
                resolution = conn.execute("SELECT resolution_verdict FROM room_v2_conflict_resolution_receipts WHERE round_id = ? ORDER BY created_at_ms DESC LIMIT 1", (peer_round_id,)).fetchone()
                review_passed = resolution is not None and str(resolution[0]) == "pass"
            if not review_passed: reasons.append("blind_review_not_passed")
            unsigned = conn.execute("""SELECT COUNT(*) FROM room_v2_criterion_proofs p JOIN room_v2_verification_receipts r ON r.receipt_id=p.receipt_id WHERE p.catalog_revision_id=? AND (r.issuer_trust!='runner_signed' OR r.source_commit!=?)""", (catalog_revision_id, target_commit)).fetchone()[0]
            criteria = conn.execute("SELECT criterion_id, criterion_kind FROM room_v2_acceptance_criteria WHERE catalog_revision_id = ?", (catalog_revision_id,)).fetchall()
            for criterion in criteria:
                valid = conn.execute("""SELECT 1 FROM room_v2_criterion_proofs p JOIN room_v2_verification_receipts r ON r.receipt_id=p.receipt_id WHERE p.catalog_revision_id=? AND p.criterion_id=? AND r.issuer_trust='runner_signed' AND r.source_commit=? AND r.exit_status=0 LIMIT 1""", (catalog_revision_id, criterion[0], target_commit)).fetchone()
                if valid is None: reasons.append("criterion_without_signed_proof:" + str(criterion[0]))
            if not any(str(row[1]) == "user_journey" for row in criteria): reasons.append("user_journey_missing")
            obstacles = conn.execute("SELECT obstacle_kind FROM room_v2_delivery_obstacles WHERE catalog_revision_id=? AND status='open'", (catalog_revision_id,)).fetchall()
            reasons.extend("unresolved_" + str(row[0]) for row in obstacles)
            conflicts = conn.execute("SELECT 1 FROM room_v2_requirement_conflicts WHERE catalog_revision_id=? AND status='open' LIMIT 1", (catalog_revision_id,)).fetchone()
            if conflicts is not None: reasons.append("unresolved_conflict_or_unknown")
            if unsigned: reasons.append("untrusted_or_stale_proof_present")
            enforce = environment == "room-v2-test"
            mode = "room_v2_test_enforce_preview" if enforce else "observe_warn"
            terminal_allowed = enforce and not reasons
            material = {"previewReceiptId": preview_receipt_id, "rootId": root_id, "catalogRevisionId": catalog_revision_id, "peerRoundId": peer_round_id, "environment": environment, "mode": mode, "terminalAllowed": terminal_allowed, "reasons": list(dict.fromkeys(reasons)), "createdAtMs": created_at_ms}
            conn.execute("INSERT INTO room_v2_delivery_gate_preview_receipts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (preview_receipt_id, root_id, catalog_revision_id, peer_round_id, environment, mode, int(terminal_allowed), _json(material["reasons"]), _hash_json(material), created_at_ms))
        return material

    @staticmethod
    def _eligible_binding(conn: sqlite3.Connection, session_id: str, room_id: str, root_id: str, *, role: str) -> dict[str, object]:
        rows = conn.execute("SELECT participant_binding_json, room_binding_json FROM room_v2_capability_runtime_bindings WHERE session_id = ? AND state IN ('prepared','active') ORDER BY capability_epoch DESC", (session_id,)).fetchall()
        for row in rows:
            participant, room = json.loads(str(row[0])), json.loads(str(row[1]))
            room_ref = participant.get("roomBindingRef") or {}
            if (
                str(participant.get("sessionId")) == session_id
                and str(room.get("rootId")) == root_id
                and str(room.get("roomId")) == room_id
                and str(room.get("bindingId")) == str(room_ref.get("bindingId"))
                and f"/collaboration-role/{role}?" in str(participant.get("collaborationRoleRef"))
            ):
                validate_contract(participant, "room-participant-binding.v2.json")
                return participant
        raise PeerReviewFenceError(f"ParticipantBinding is not eligible for {role}")

    @contextmanager
    def _connect(self, *, immediate: bool = False):
        conn = sqlite3.connect(self.db_path, timeout=10); conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            if immediate: conn.execute("BEGIN IMMEDIATE")
            yield conn; conn.commit()
        except BaseException:
            conn.rollback(); raise
        finally: conn.close()


def _assert_blind(value: object) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if str(key).lower().replace("_", "") in _FORBIDDEN_BLIND_KEYS:
                raise PeerReviewFenceError("blind phase input leaks author identity or conclusion")
            _assert_blind(child)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for child in value: _assert_blind(child)


def _refs(values: Sequence[object]) -> list[str]:
    return list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))


def _finding(value: Mapping[str, object], criteria: set[str]) -> dict[str, str]:
    severity = str(value.get("severity") or "").strip()
    code = str(value.get("code") or "").strip()
    criterion = str(value.get("criterionId") or "").strip()
    if severity not in {"critical", "high", "medium", "low"} or not code or criterion not in criteria:
        raise PeerReviewFenceError("finding must have severity, code, and current requirement criterion")
    return {"severity": severity, "code": code, "criterionId": criterion}


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash_json(value: object) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()
