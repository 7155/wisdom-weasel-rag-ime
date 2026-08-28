from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
import sqlite3
from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import NamedTuple

from .db import apply_database_migrations
from .knowledge_scope import KNOWLEDGE_DOMAINS, SCOPE_KINDS, KnowledgeCallerContext


class KnowledgePromotionError(RuntimeError):
    pass


class ConsumedCacheTombstones(NamedTuple):
    """Sessions whose in-process recall state must follow a durable retirement."""

    session_ids: tuple[str, ...]
    consumed: int


_SECRET_PATTERNS = (
    ("api_key", re.compile(r"(?i)(api[_-]?key|token)\s*[:=]\s*[A-Za-z0-9_\-]{12,}")),
    ("credential", re.compile(r"(?i)(password|passwd|secret)\s*[:=]\s*\S{8,}")),
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("email_pii", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("phone_pii", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")),
)

KNOWLEDGE_ROUTE_DESCRIPTOR = {
    "search": {"method": "POST", "path": "/api/agent/sessions/{sessionId}/knowledge-search", "scopes": ["agent.read"]},
    "read": {"method": "POST", "path": "/api/agent/sessions/{sessionId}/knowledge-read", "scopes": ["agent.read"]},
}
KNOWLEDGE_ROUTE_HASH = "sha256:" + hashlib.sha256(
    json.dumps(KNOWLEDGE_ROUTE_DESCRIPTOR, sort_keys=True, separators=(",", ":")).encode()
).hexdigest()


class KnowledgePromotionStore:
    """One-way evidence promotion plus epoch-fenced two-stage resolution."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        authority_secrets: Mapping[str, bytes | str] | None = None,
        index_adapter: Callable[[Mapping[str, object]], Sequence[Mapping[str, object]]] | None = None,
        observation_callback: Callable[[Mapping[str, object]], None] | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self._authority_secrets = {str(key): value if isinstance(value, bytes) else str(value).encode() for key, value in (authority_secrets or {}).items()}
        self._index_adapter = index_adapter
        self._observation_callback = observation_callback

    def initialize(self) -> int:
        with self._connect() as conn:
            return apply_database_migrations(conn).current_version

    def governance_snapshot(self) -> dict[str, list[dict[str, object]]]:
        """Return the sanitized canonical read model; never expose signatures or scans."""

        with self._connect() as conn:
            candidates = conn.execute("SELECT * FROM room_v2_promotion_candidates ORDER BY created_at_ms DESC").fetchall()
            receipts = conn.execute("SELECT * FROM room_v2_promotion_receipts ORDER BY created_at_ms DESC").fetchall()
            claims = conn.execute("SELECT * FROM room_v2_knowledge_claim_versions ORDER BY created_at_ms DESC").fetchall()
            lifecycle = conn.execute("SELECT * FROM room_v2_knowledge_lifecycle_receipts ORDER BY created_at_ms DESC").fetchall()
            epochs = conn.execute("SELECT * FROM room_v2_knowledge_epochs ORDER BY scope_key").fetchall()
            quarantines = conn.execute("SELECT * FROM room_v2_external_import_intakes ORDER BY created_at_ms DESC").fetchall()
            outbox = conn.execute("SELECT * FROM room_v2_knowledge_index_outbox ORDER BY created_at_ms DESC").fetchall()
            tombstones = conn.execute("SELECT * FROM room_v2_knowledge_cache_tombstones ORDER BY created_at_ms DESC").fetchall()
            datasets = conn.execute("SELECT * FROM room_v2_knowledge_eval_fixture_datasets ORDER BY created_at_ms DESC").fetchall()
            eval_runs = conn.execute("SELECT * FROM room_v2_knowledge_search_use_eval_runs ORDER BY created_at_ms DESC").fetchall()
        return {
            "promotionCandidates": [{
                "promotionCandidateId": str(row["promotion_candidate_id"]),
                "evidenceKind": str(row["evidence_kind"]), "evidenceRef": str(row["evidence_ref"]),
                "claimKey": str(row["claim_key"]),
                **({"claimText": str(row["claim_text"])} if row["visibility"] != "private" else {}),
                "ownerKind": str(row["owner_kind"]), "ownerId": str(row["owner_id"]),
                "scopeKind": str(row["scope_kind"]), "scopeId": str(row["scope_id"]),
                "visibility": str(row["visibility"]), "risk": str(row["risk"]),
                "candidateHash": str(row["candidate_hash"]),
                "conflictClaimRefs": json.loads(str(row["conflict_claim_refs_json"])),
            } for row in candidates],
            "promotionReceipts": [{
                "promotionReceiptId": str(row["promotion_receipt_id"]),
                "promotionCandidateId": str(row["promotion_candidate_id"]),
                "claimVersionId": str(row["claim_version_id"]), "scopeKey": str(row["scope_key"]),
                "knowledgeEpoch": int(row["knowledge_epoch"]), "candidateHash": str(row["candidate_hash"]),
            } for row in receipts],
            "claims": [{
                "claimVersionId": str(row["claim_version_id"]), "claimIdentity": str(row["claim_identity"]),
                "claimKey": str(row["claim_key"]),
                **({"claimText": str(row["claim_text"])} if row["visibility"] != "private" else {}),
                "claimHash": str(row["claim_hash"]), "ownerKind": str(row["owner_kind"]),
                "ownerId": str(row["owner_id"]), "scopeKind": str(row["scope_kind"]),
                "scopeId": str(row["scope_id"]), "visibility": str(row["visibility"]),
                "provenance": json.loads(str(row["provenance_json"])),
                "contradictionRefs": json.loads(str(row["contradiction_refs_json"])),
            } for row in claims],
            "conflicts": [{
                "promotionCandidateId": str(row["promotion_candidate_id"]),
                "state": str(row["conflict_status"]),
                "claimRefs": json.loads(str(row["conflict_claim_refs_json"])),
            } for row in candidates if str(row["conflict_status"]) != "clear"],
            "lifecycleReceipts": [{
                "lifecycleReceiptId": str(row["lifecycle_receipt_id"]),
                "claimIdentity": str(row["claim_identity"]), "operation": str(row["operation"]),
                "knowledgeEpoch": int(row["knowledge_epoch"]), "scopeKey": str(row["scope_key"]),
            } for row in lifecycle],
            "epochs": [{"scopeKey": str(row["scope_key"]), "knowledgeEpoch": int(row["knowledge_epoch"])} for row in epochs],
            "quarantines": [{
                "importId": str(row["import_id"]), "sourceName": str(row["source_name"]),
                "status": str(row["scan_status"]), "contentHash": str(row["content_hash"]),
                "findingCount": len(json.loads(str(row["finding_codes_json"]))),
            } for row in quarantines],
            "outbox": [{
                "outboxId": str(row["outbox_id"]), "claimVersionId": str(row["claim_version_id"]),
                "operation": str(row["operation"]), "state": str(row["state"]),
                "attemptCount": int(row["attempt_count"]), "lastError": str(row["last_error"]),
            } for row in outbox],
            "tombstones": [{
                "tombstoneId": str(row["tombstone_id"]), "scopeKey": str(row["scope_key"]),
                "knowledgeEpoch": int(row["knowledge_epoch"]), "sessionId": str(row["session_id"] or ""),
                "reason": str(row["reason"]),
            } for row in tombstones],
            "evalDatasets": [{
                "datasetId": str(row["dataset_id"]), "datasetVersion": int(row["dataset_version"]),
                "thresholds": json.loads(str(row["thresholds_json"])), "contentHash": str(row["content_hash"]),
                "expiresAtMs": int(row["expires_at_ms"]),
            } for row in datasets],
            "searchUseEvalRuns": [{
                "schemaVersion": "wisdom-weasel.knowledge-search-use-eval-run.v1",
                "evalRunId": str(row["eval_run_id"]), "datasetId": str(row["dataset_id"]),
                "datasetContentHash": str(row["dataset_content_hash"]), "roomBindingId": str(row["room_binding_id"]),
                "traceCount": int(row["trace_count"]), "metrics": json.loads(str(row["metrics_json"])),
                "strataMetrics": json.loads(str(row["strata_metrics_json"])), "status": str(row["status"]),
                "failureReasons": json.loads(str(row["failure_reasons_json"])), "reportOnly": True,
                "evaluatorId": str(row["evaluator_id"]), "contentHash": str(row["content_hash"]),
                "evaluatorSignature": "redacted", "createdAtMs": int(row["created_at_ms"]),
            } for row in eval_runs],
        }

    def scan_external_before_copy(self, *, import_id: str, source_name: str, raw_bytes: bytes, created_at_ms: int) -> dict[str, object]:
        """Scan caller bytes before any managed copy, parse, chunk, embedding, or raw DB write."""
        findings = _scan(raw_bytes.decode("utf-8", errors="replace")); status = "quarantined" if findings else "allowed"
        content_hash = hashlib.sha256(raw_bytes).hexdigest()
        with self._connect(immediate=True) as conn:
            existing = conn.execute("SELECT * FROM room_v2_external_import_intakes WHERE import_id=?", (import_id,)).fetchone()
            if existing is None:
                conn.execute("INSERT INTO room_v2_external_import_intakes VALUES (?,?,?,?,?,1,0,?)", (import_id, source_name, content_hash, status, _json(findings), created_at_ms))
            elif existing["content_hash"] != content_hash or status == "quarantined":
                conn.execute("UPDATE room_v2_external_import_intakes SET content_hash=?,scan_status=?,finding_codes_json=?,created_at_ms=? WHERE import_id=?", (content_hash, status, _json(findings), created_at_ms, import_id))
            purged: list[str] = []
            if status == "quarantined":
                rows = conn.execute("SELECT claim_version_id,claim_identity,scope_kind,scope_id,owner_kind,owner_id,knowledge_domain FROM room_v2_knowledge_claim_versions WHERE provenance_json LIKE ?", (f'%"{import_id}"%',)).fetchall()
                for row in rows:
                    scope_key = _scope_key(row)
                    epoch = self._bump_epoch(conn, scope_key, created_at_ms)
                    conn.execute("UPDATE room_v2_knowledge_claim_pointers SET lifecycle_status='revoked',knowledge_epoch=?,updated_at_ms=? WHERE claim_identity=?", (epoch, created_at_ms, row["claim_identity"]))
                    conn.execute("DELETE FROM room_v2_knowledge_search_projections WHERE claim_version_id=?", (row["claim_version_id"],))
                    self._outbox(conn, "purge:" + import_id + ":" + row["claim_version_id"], row["claim_version_id"], "quarantine_purge", created_at_ms)
                    self._cache_tombstones(conn, scope_key, epoch, str(row["scope_kind"]), str(row["scope_id"]), "quarantine_purge", created_at_ms)
                    purged.append(str(row["claim_version_id"]))
        return {"importId": import_id, "contentHash": content_hash, "scanStatus": status, "findingCodes": findings, "dataOnly": True, "rawBytesStored": False, "purgedProjectionRefs": purged}

    def nominate(self, *, promotion_candidate_id: str, evidence_kind: str, evidence_ref: str, claim_key: str, claim_text: str, knowledge_domain: str, owner_kind: str, owner_id: str, scope_kind: str, scope_id: str, visibility: str, promotion_policy: str, provenance: Sequence[str], risk: str, nominated_by: str, created_at_ms: int) -> dict[str, object]:
        if evidence_kind not in {"private_session", "room_post", "external_import"} or visibility not in {"project", "room", "participant", "private"} or risk not in {"low", "medium", "high"}:
            raise KnowledgePromotionError("PromotionCandidate policy fields are invalid")
        if knowledge_domain not in KNOWLEDGE_DOMAINS or scope_kind not in SCOPE_KINDS or not all(str(value).strip() for value in (claim_key, claim_text, owner_kind, owner_id, scope_id, promotion_policy)):
            raise KnowledgePromotionError("PromotionCandidate owner/domain/scope is incomplete")
        if evidence_kind == "private_session" and (knowledge_domain, owner_kind, owner_id, scope_kind, scope_id, visibility) != ("participant_private", "session", owner_id, "session", owner_id, "private"):
            raise KnowledgePromotionError("private Session evidence cannot change owner/scope during nomination")
        if evidence_kind == "room_post" and (knowledge_domain, owner_kind, owner_id, scope_kind, scope_id, visibility) != ("room_public", "room", owner_id, "room", owner_id, "room"):
            raise KnowledgePromotionError("RoomPost evidence requires canonical Room owner/scope")
        if evidence_kind == "external_import" and knowledge_domain != "document_library":
            raise KnowledgePromotionError("external import claims stay in document_library")
        with self._connect(immediate=True) as conn:
            evidence_hash, evidence_text = self._evidence(conn, evidence_kind, evidence_ref, owner_id, scope_id)
            findings = list(dict.fromkeys((*_scan(evidence_text), *_scan(claim_text))))
            identity = _claim_identity(knowledge_domain, owner_kind, owner_id, scope_kind, scope_id, claim_key)
            active = conn.execute("""SELECT version.claim_version_id,version.claim_hash FROM room_v2_knowledge_claim_pointers pointer JOIN room_v2_knowledge_claim_versions version ON version.claim_version_id=pointer.current_claim_version_id WHERE pointer.claim_identity=? AND pointer.lifecycle_status='current'""", (identity,)).fetchone()
            claim_hash = hashlib.sha256(claim_text.encode()).hexdigest()
            conflicts = [str(active["claim_version_id"])] if active is not None and str(active["claim_hash"]) != claim_hash else []
            material = {"promotionCandidateId": promotion_candidate_id, "evidenceKind": evidence_kind, "evidenceRef": evidence_ref, "evidenceHash": evidence_hash, "claimKey": claim_key, "claimText": claim_text, "knowledgeDomain": knowledge_domain, "ownerKind": owner_kind, "ownerId": owner_id, "scopeKind": scope_kind, "scopeId": scope_id, "visibility": visibility, "promotionPolicy": promotion_policy, "provenance": _refs(provenance), "conflictStatus": "open" if conflicts else "clear", "conflictClaimRefs": conflicts, "secretScan": findings, "risk": risk, "nominatedBy": nominated_by, "createdAtMs": created_at_ms}
            candidate_hash = _hash_json(material)
            conn.execute("INSERT INTO room_v2_promotion_candidates VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (promotion_candidate_id, evidence_kind, evidence_ref, evidence_hash, claim_key, claim_text, knowledge_domain, owner_kind, owner_id, scope_kind, scope_id, visibility, promotion_policy, _json(material["provenance"]), material["conflictStatus"], _json(conflicts), _json(findings), risk, nominated_by, candidate_hash, created_at_ms))
        return {**material, "candidateHash": candidate_hash, "state": "candidate_only"}

    def approve(self, *, approval_receipt_id: str, promotion_candidate_id: str, authority_ref: str, authority_secret: bytes | str, conflict_resolution: str, created_at_ms: int) -> dict[str, object]:
        if not (authority_ref.startswith("user:") or authority_ref.startswith("admin:")) or conflict_resolution not in {"none", "replace", "coexist", "reject"}:
            raise KnowledgePromotionError("Promotion approval authority/decision is invalid")
        configured = self._authority_secrets.get(authority_ref); supplied = authority_secret if isinstance(authority_secret, bytes) else authority_secret.encode()
        if configured is None or not hmac.compare_digest(configured, supplied): raise KnowledgePromotionError("Promotion approval secret is not trusted")
        with self._connect(immediate=True) as conn:
            candidate = self._candidate(conn, promotion_candidate_id); self._assert_candidate(candidate)
            if authority_ref == candidate["nominated_by"]: raise KnowledgePromotionError("Promotion nominator cannot self-approve")
            material = {"approvalReceiptId": approval_receipt_id, "promotionCandidateId": promotion_candidate_id, "candidateHash": candidate["candidate_hash"], "authorityRef": authority_ref, "conflictResolution": conflict_resolution, "createdAtMs": created_at_ms}
            content_hash = _hash_json(material); signature = hmac.new(configured, content_hash.encode(), hashlib.sha256).hexdigest()
            conn.execute("INSERT INTO room_v2_promotion_approval_receipts VALUES (?,?,?,?,?,?,?,?)", (approval_receipt_id, promotion_candidate_id, candidate["candidate_hash"], authority_ref, conflict_resolution, content_hash, signature, created_at_ms))
        return {**material, "contentHash": content_hash, "authoritySignature": signature}

    def promote(self, *, promotion_receipt_id: str, claim_version_id: str, promotion_candidate_id: str, approval_receipt_id: str | None, low_risk_rule_id: str | None, outbox_id: str, created_at_ms: int) -> dict[str, object]:
        with self._connect(immediate=True) as conn:
            candidate = self._candidate(conn, promotion_candidate_id); self._assert_candidate(candidate)
            findings = json.loads(str(candidate["secret_scan_json"])); conflict = str(candidate["conflict_status"])
            if findings: raise KnowledgePromotionError("PromotionCandidate contains secret/credential/PII findings")
            approval = conn.execute("SELECT * FROM room_v2_promotion_approval_receipts WHERE approval_receipt_id=? AND promotion_candidate_id=?", (approval_receipt_id, promotion_candidate_id)).fetchone() if approval_receipt_id else None
            user_post = conn.execute("SELECT 1 FROM room_v2_posts WHERE post_id=? AND publication_source_kind='user'", (candidate["evidence_ref"],)).fetchone() if candidate["evidence_kind"] == "room_post" else None
            low_rule = low_risk_rule_id == "room_verified_fact_v1" and candidate["promotion_policy"] == "room_verified_fact_v1" and candidate["nominated_by"] == "policy:room_verified_fact_v1" and user_post is not None and candidate["visibility"] == "room" and candidate["risk"] == "low" and conflict == "clear"
            if approval is None and not low_rule: raise KnowledgePromotionError("Promotion requires approval receipt or explicit low-risk rule")
            if approval is not None:
                self._verify_approval(approval, candidate)
                if approval["conflict_resolution"] == "reject": raise KnowledgePromotionError("Promotion conflict was rejected")
                if conflict == "open" and approval["conflict_resolution"] not in {"replace", "coexist"}: raise KnowledgePromotionError("Promotion conflict lacks explicit resolution")
            identity = _claim_identity_from_row(candidate)
            current = conn.execute("SELECT * FROM room_v2_knowledge_claim_pointers WHERE claim_identity=?", (identity,)).fetchone()
            previous = str(current["current_claim_version_id"]) if current and current["current_claim_version_id"] else None
            version = int(conn.execute("SELECT COALESCE(MAX(version),0)+1 FROM room_v2_knowledge_claim_versions WHERE claim_identity=?", (identity,)).fetchone()[0])
            claim_hash = hashlib.sha256(str(candidate["claim_text"]).encode()).hexdigest(); contradictions = json.loads(str(candidate["conflict_claim_refs_json"]))
            scope_key = _scope_key(candidate); epoch = self._bump_epoch(conn, scope_key, created_at_ms)
            provenance = {"evidenceKind": candidate["evidence_kind"], "evidenceRef": candidate["evidence_ref"], "evidenceHash": candidate["evidence_hash"], "sourceRefs": json.loads(str(candidate["provenance_json"])), "dataOnly": candidate["evidence_kind"] == "external_import"}
            conn.execute("INSERT INTO room_v2_knowledge_claim_versions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (claim_version_id, identity, version, previous, promotion_candidate_id, promotion_receipt_id, candidate["claim_key"], candidate["claim_text"], claim_hash, candidate["knowledge_domain"], candidate["owner_kind"], candidate["owner_id"], candidate["scope_kind"], candidate["scope_id"], candidate["visibility"], _json(provenance), _json(contradictions), created_at_ms))
            material = {"promotionReceiptId": promotion_receipt_id, "promotionCandidateId": promotion_candidate_id, "approvalReceiptId": approval_receipt_id, "lowRiskRuleId": low_risk_rule_id if low_rule else None, "claimVersionId": claim_version_id, "scopeKey": scope_key, "knowledgeEpoch": epoch, "candidateHash": candidate["candidate_hash"], "createdAtMs": created_at_ms}
            conn.execute("INSERT INTO room_v2_promotion_receipts VALUES (?,?,?,?,?,?,?,?,?,?)", (promotion_receipt_id, promotion_candidate_id, approval_receipt_id, material["lowRiskRuleId"], claim_version_id, scope_key, epoch, candidate["candidate_hash"], _hash_json(material), created_at_ms))
            conn.execute("INSERT INTO room_v2_knowledge_claim_pointers VALUES (?,?,'current',?,?,?) ON CONFLICT(claim_identity) DO UPDATE SET current_claim_version_id=excluded.current_claim_version_id,lifecycle_status='current',knowledge_epoch=excluded.knowledge_epoch,updated_at_ms=excluded.updated_at_ms", (identity, claim_version_id, scope_key, epoch, created_at_ms))
            self._outbox(conn, outbox_id, claim_version_id, "index", created_at_ms)
        return material

    def apply_index_outbox(
        self,
        outbox_id: str,
        *,
        applied_at_ms: int,
        fail_after_adapter: bool = False,
    ) -> None:
        leased = self._lease_index_outbox(outbox_id=outbox_id, now_ms=applied_at_ms)
        payload = dict(leased["payload"])
        try:
            receipts = [dict(item) for item in (self._index_adapter(payload) if self._index_adapter else ())]
            if fail_after_adapter:
                raise RuntimeError("injected knowledge index crash")
            with self._connect(immediate=True) as conn:
                current = conn.execute(
                    "SELECT state FROM room_v2_knowledge_index_outbox WHERE outbox_id=?",
                    (outbox_id,),
                ).fetchone()
                if current is None or current[0] != "leased":
                    raise KnowledgePromotionError("knowledge index lease was lost")
                version = conn.execute("SELECT * FROM room_v2_knowledge_claim_versions WHERE claim_version_id=?", (payload["claimVersionId"],)).fetchone()
                if payload["operation"] == "index":
                    conn.execute("INSERT OR REPLACE INTO room_v2_knowledge_search_projections VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (version["claim_version_id"], version["claim_text"], version["claim_hash"], version["knowledge_domain"], version["owner_kind"], version["owner_id"], version["scope_kind"], version["scope_id"], version["visibility"], version["provenance_json"], version["contradiction_refs_json"], applied_at_ms))
                else:
                    conn.execute("DELETE FROM room_v2_knowledge_search_projections WHERE claim_version_id=?", (version["claim_version_id"],))
                conn.execute(
                    """UPDATE room_v2_knowledge_index_outbox SET state='applied',lease_until_ms=0,
                       projection_receipts_json=?,last_error='' WHERE outbox_id=?""",
                    (_json(receipts), outbox_id),
                )
        except Exception as exc:
            with self._connect(immediate=True) as conn:
                row = conn.execute("SELECT attempt_count,max_attempts FROM room_v2_knowledge_index_outbox WHERE outbox_id=?", (outbox_id,)).fetchone()
                dead = row is not None and int(row[0]) >= int(row[1])
                conn.execute(
                    """UPDATE room_v2_knowledge_index_outbox SET state=?,lease_until_ms=0,
                       available_at_ms=?,last_error=? WHERE outbox_id=?""",
                    ("dead_letter" if dead else "retry_wait", applied_at_ms + min(60_000, 1000 * (2 ** int(row[0] if row else 1))), f"{type(exc).__name__}: {exc}"[:500], outbox_id),
                )
            raise

    def run_index_outbox_once(self, *, now_ms: int) -> dict[str, object] | None:
        with self._connect() as conn:
            row = conn.execute(
                """SELECT outbox_id FROM room_v2_knowledge_index_outbox
                   WHERE (state IN ('pending','retry_wait') AND available_at_ms<=?)
                      OR (state='leased' AND lease_until_ms<=?)
                   ORDER BY created_at_ms,outbox_id LIMIT 1""",
                (now_ms, now_ms),
            ).fetchone()
        if row is None:
            return None
        outbox_id = str(row[0])
        try:
            self.apply_index_outbox(outbox_id, applied_at_ms=now_ms)
        except Exception as exc:
            with self._connect() as conn:
                state = conn.execute("SELECT state FROM room_v2_knowledge_index_outbox WHERE outbox_id=?", (outbox_id,)).fetchone()[0]
            return {"outboxId": outbox_id, "state": str(state), "error": str(exc)}
        return {"outboxId": outbox_id, "state": "applied"}

    def _lease_index_outbox(self, *, outbox_id: str, now_ms: int) -> dict[str, object]:
        with self._connect(immediate=True) as conn:
            outbox = conn.execute(
                """SELECT * FROM room_v2_knowledge_index_outbox WHERE outbox_id=? AND
                   ((state IN ('pending','retry_wait') AND available_at_ms<=?) OR
                    (state='leased' AND lease_until_ms<=?))""",
                (outbox_id, now_ms, now_ms),
            ).fetchone()
            if outbox is None:
                raise KnowledgePromotionError("index outbox is missing, busy, or already consumed")
            version = conn.execute("SELECT * FROM room_v2_knowledge_claim_versions WHERE claim_version_id=?", (outbox["claim_version_id"],)).fetchone()
            conn.execute(
                """UPDATE room_v2_knowledge_index_outbox SET state='leased',attempt_count=attempt_count+1,
                   lease_until_ms=? WHERE outbox_id=?""",
                (now_ms + 30_000, outbox_id),
            )
        return {
            "outboxId": outbox_id,
            "payload": {
                "outboxId": outbox_id,
                "claimVersionId": str(version["claim_version_id"]),
                "operation": str(outbox["operation"]),
                "claimHash": str(version["claim_hash"]),
                "text": str(version["claim_text"]),
                "knowledgeDomain": str(version["knowledge_domain"]),
                "ownerKind": str(version["owner_kind"]),
                "ownerId": str(version["owner_id"]),
                "scopeKind": str(version["scope_kind"]),
                "scopeId": str(version["scope_id"]),
                "targets": ["fts", "vector", "graph", "notion", "document_projection"],
            },
        }

    def lifecycle(self, *, lifecycle_receipt_id: str, claim_identity: str, operation: str, authority_ref: str, authority_secret: bytes | str, outbox_id: str, created_at_ms: int) -> dict[str, object]:
        status_map = {"revoke": "revoked", "archive": "archived", "unbind": "unbound", "delete": "deleted"}
        if operation not in status_map: raise KnowledgePromotionError("unsupported knowledge lifecycle operation")
        self._verify_authority(authority_ref, authority_secret)
        with self._connect(immediate=True) as conn:
            pointer = conn.execute("SELECT * FROM room_v2_knowledge_claim_pointers WHERE claim_identity=? AND lifecycle_status='current'", (claim_identity,)).fetchone()
            if pointer is None: raise KnowledgePromotionError("knowledge claim is not current")
            epoch = self._bump_epoch(conn, str(pointer["scope_key"]), created_at_ms); version_id = str(pointer["current_claim_version_id"])
            conn.execute("UPDATE room_v2_knowledge_claim_pointers SET lifecycle_status=?,knowledge_epoch=?,updated_at_ms=? WHERE claim_identity=?", (status_map[operation], epoch, created_at_ms, claim_identity))
            conn.execute("DELETE FROM room_v2_knowledge_search_projections WHERE claim_version_id=?", (version_id,))
            self._outbox(conn, outbox_id, version_id, operation if operation != "revoke" else "invalidate", created_at_ms)
            version = conn.execute("SELECT scope_kind,scope_id FROM room_v2_knowledge_claim_versions WHERE claim_version_id=?", (version_id,)).fetchone()
            self._cache_tombstones(conn, str(pointer["scope_key"]), epoch, str(version[0]), str(version[1]), operation, created_at_ms)
            material = {"lifecycleReceiptId": lifecycle_receipt_id, "claimIdentity": claim_identity, "operation": operation, "fromClaimVersionId": version_id, "toClaimVersionId": None, "scopeKey": pointer["scope_key"], "knowledgeEpoch": epoch, "authorityRef": authority_ref, "createdAtMs": created_at_ms}
            conn.execute("INSERT INTO room_v2_knowledge_lifecycle_receipts VALUES (?,?,?,?,?,?,?,?,?,?)", (lifecycle_receipt_id, claim_identity, operation, version_id, None, pointer["scope_key"], epoch, authority_ref, _hash_json(material), created_at_ms))
        return material

    def change_owner(self, *, lifecycle_receipt_id: str, old_claim_identity: str, new_claim_identity: str, authority_ref: str, authority_secret: bytes | str, outbox_id: str, created_at_ms: int) -> dict[str, object]:
        self._verify_authority(authority_ref, authority_secret)
        with self._connect(immediate=True) as conn:
            old = conn.execute("SELECT * FROM room_v2_knowledge_claim_pointers WHERE claim_identity=? AND lifecycle_status='current'", (old_claim_identity,)).fetchone(); new = conn.execute("SELECT * FROM room_v2_knowledge_claim_pointers WHERE claim_identity=? AND lifecycle_status='current'", (new_claim_identity,)).fetchone()
            if old is None or new is None: raise KnowledgePromotionError("owner change requires separately promoted current destination claim")
            old_epoch = self._bump_epoch(conn, old["scope_key"], created_at_ms); new_epoch = self._bump_epoch(conn, new["scope_key"], created_at_ms)
            conn.execute("UPDATE room_v2_knowledge_claim_pointers SET lifecycle_status='unbound',knowledge_epoch=?,updated_at_ms=? WHERE claim_identity=?", (old_epoch, created_at_ms, old_claim_identity))
            conn.execute("UPDATE room_v2_knowledge_claim_pointers SET knowledge_epoch=?,updated_at_ms=? WHERE claim_identity=?", (new_epoch, created_at_ms, new_claim_identity))
            conn.execute("DELETE FROM room_v2_knowledge_search_projections WHERE claim_version_id=?", (old["current_claim_version_id"],))
            self._outbox(conn, outbox_id, old["current_claim_version_id"], "unbind", created_at_ms)
            old_version = conn.execute("SELECT scope_kind,scope_id FROM room_v2_knowledge_claim_versions WHERE claim_version_id=?", (old["current_claim_version_id"],)).fetchone()
            new_version = conn.execute("SELECT scope_kind,scope_id FROM room_v2_knowledge_claim_versions WHERE claim_version_id=?", (new["current_claim_version_id"],)).fetchone()
            self._cache_tombstones(conn, str(old["scope_key"]), old_epoch, str(old_version[0]), str(old_version[1]), "owner_change_from", created_at_ms)
            self._cache_tombstones(conn, str(new["scope_key"]), new_epoch, str(new_version[0]), str(new_version[1]), "owner_change_to", created_at_ms)
            material = {"lifecycleReceiptId": lifecycle_receipt_id, "claimIdentity": old_claim_identity, "operation": "owner_change", "fromClaimVersionId": old["current_claim_version_id"], "toClaimVersionId": new["current_claim_version_id"], "scopeKey": old["scope_key"], "knowledgeEpoch": old_epoch, "authorityRef": authority_ref, "createdAtMs": created_at_ms}
            conn.execute("INSERT INTO room_v2_knowledge_lifecycle_receipts VALUES (?,?,?,?,?,?,?,?,?,?)", (lifecycle_receipt_id, old_claim_identity, "owner_change", old["current_claim_version_id"], new["current_claim_version_id"], old["scope_key"], old_epoch, authority_ref, _hash_json(material), created_at_ms))
        return material

    def search(self, *, retrieval_receipt_id: str, query: str, caller: KnowledgeCallerContext | None, limit: int, created_at_ms: int) -> dict[str, object]:
        if caller is None: return {"retrievalReceiptId": None, "groups": [], "noRoomBinding": True}
        scopes = caller.allowed_scopes; domains = caller.allowed_domains
        with self._connect(immediate=True) as conn:
            scope_clause = " OR ".join("(projection.scope_kind=? AND projection.scope_id=?)" for _ in scopes)
            rows = conn.execute(f"""SELECT projection.*,pointer.scope_key,pointer.knowledge_epoch,version.created_at_ms FROM room_v2_knowledge_search_projections projection JOIN room_v2_knowledge_claim_versions version ON version.claim_version_id=projection.claim_version_id JOIN room_v2_knowledge_claim_pointers pointer ON pointer.current_claim_version_id=projection.claim_version_id AND pointer.lifecycle_status='current' WHERE projection.knowledge_domain IN ({','.join('?' for _ in domains)}) AND ({scope_clause}) AND projection.claim_text LIKE ? ORDER BY version.created_at_ms DESC LIMIT ?""", (*domains, *(part for scope in scopes for part in scope), f"%{query}%", max(1, min(int(limit), 50)))).fetchall()
            refs = [str(row["claim_version_id"]) for row in rows]; hashes = {str(row["claim_version_id"]): str(row["claim_hash"]) for row in rows}; epochs = {str(row["scope_key"]): int(row["knowledge_epoch"]) for row in rows}
            conn.execute("INSERT INTO room_v2_knowledge_retrieval_receipts VALUES (?,?,?,?,?,?,?,?)", (retrieval_receipt_id, caller.binding_id, caller.authorization_revision, _hash_json({"query": query, "domains": domains, "scopes": scopes}), _json(epochs), _json(refs), _json(hashes), created_at_ms))
        result = {"retrievalReceiptId": retrieval_receipt_id, "groups": [{"claimRef": str(row["claim_version_id"]), "claimHash": str(row["claim_hash"]), "provenance": json.loads(str(row["provenance_json"])), "contradictionRefs": json.loads(str(row["contradiction_refs_json"])), "freshness": {"createdAtMs": int(row["created_at_ms"]), "status": "current"}} for row in rows], "scopeEpochs": epochs}
        self._emit_retrieval_observation(
            retrieval_receipt_id=retrieval_receipt_id,
            caller=caller,
            rows=rows,
            created_at_ms=created_at_ms,
        )
        return result

    def _emit_retrieval_observation(
        self,
        *,
        retrieval_receipt_id: str,
        caller: KnowledgeCallerContext,
        rows: Sequence[Mapping[str, object]],
        created_at_ms: int,
    ) -> None:
        callback = self._observation_callback
        if not callable(callback):
            return
        evidence = []
        for rank, row in enumerate(rows, start=1):
            score = row.get("score") if isinstance(row, Mapping) else None
            if score is None and hasattr(row, "keys") and "score" in row.keys():
                score = row["score"]
            scores = {}
            if (
                not isinstance(score, bool)
                and isinstance(score, (int, float))
                and math.isfinite(float(score))
            ):
                scores["score"] = float(score)
            evidence.append(
                {
                    "evidenceId": str(row["claim_version_id"]),
                    "sourceKind": "knowledge",
                    "sourceRef": str(row["claim_version_id"]),
                    "sourceLane": str(row["knowledge_domain"]),
                    "disposition": "included",
                    **({"scores": scores} if scores else {}),
                    "rankAfter": rank,
                    "omissionReason": "",
                }
            )
        record = {
            "schemaVersion": "rag-ime.knowledge-retrieval-observation.v1",
            "sourceKind": "knowledge",
            "evidenceStage": "retrieval_output",
            "retrievalReceiptId": retrieval_receipt_id,
            "sessionId": caller.session_id,
            "roomId": caller.room_id,
            "timestampMs": created_at_ms,
            "retrieval": {
                "evidenceCount": len(evidence),
                "traceEvidence": evidence,
            },
        }
        try:
            callback(record)
        except Exception:
            # Trace projection is passive and must not fail an authorized search.
            return

    def read(self, *, claim_ref: str, retrieval_receipt_id: str, expected_hash: str, caller: KnowledgeCallerContext) -> dict[str, object]:
        with self._connect() as conn:
            receipt = conn.execute("SELECT * FROM room_v2_knowledge_retrieval_receipts WHERE retrieval_receipt_id=?", (retrieval_receipt_id,)).fetchone()
            if receipt is None or receipt["binding_id"] != caller.binding_id or receipt["authorization_revision"] != caller.authorization_revision: raise KnowledgePromotionError("retrieval receipt caller is stale or foreign")
            refs = json.loads(str(receipt["result_refs_json"])); hashes = json.loads(str(receipt["result_hashes_json"])); epochs = json.loads(str(receipt["scope_epochs_json"]))
            if claim_ref not in refs or hashes.get(claim_ref) != expected_hash: raise KnowledgePromotionError("claim was not authorized by search receipt")
            for scope_key, epoch in epochs.items():
                current = conn.execute("SELECT knowledge_epoch FROM room_v2_knowledge_epochs WHERE scope_key=?", (scope_key,)).fetchone()
                if current is None or int(current[0]) != int(epoch): raise KnowledgePromotionError("knowledge epoch invalidated retrieval receipt")
            row = conn.execute("""SELECT projection.*,version.created_at_ms,pointer.lifecycle_status FROM room_v2_knowledge_search_projections projection JOIN room_v2_knowledge_claim_versions version ON version.claim_version_id=projection.claim_version_id JOIN room_v2_knowledge_claim_pointers pointer ON pointer.current_claim_version_id=projection.claim_version_id WHERE projection.claim_version_id=? AND pointer.lifecycle_status='current'""", (claim_ref,)).fetchone()
            if row is None or row["claim_hash"] != expected_hash or (row["knowledge_domain"] not in caller.allowed_domains) or ((row["scope_kind"], row["scope_id"]) not in caller.allowed_scopes): raise KnowledgePromotionError("claim scope/hash/lifecycle changed")
        return {"claimRef": claim_ref, "text": str(row["claim_text"]), "claimHash": expected_hash, "provenance": json.loads(str(row["provenance_json"])), "contradictionRefs": json.loads(str(row["contradiction_refs_json"])), "freshness": {"createdAtMs": int(row["created_at_ms"]), "status": str(row["lifecycle_status"])}, "dataOnly": True}

    def recovery_packet(self, *, retrieval_receipt_id: str, caller: KnowledgeCallerContext, max_claims: int) -> dict[str, object]:
        with self._connect() as conn:
            receipt = conn.execute("SELECT result_refs_json,result_hashes_json FROM room_v2_knowledge_retrieval_receipts WHERE retrieval_receipt_id=?", (retrieval_receipt_id,)).fetchone()
        if receipt is None: raise KnowledgePromotionError("RecoveryPacket requires retrieval receipt")
        refs = json.loads(str(receipt[0]))[:max(0, min(int(max_claims), 20))]; hashes = json.loads(str(receipt[1]))
        return {"retrievalReceiptId": retrieval_receipt_id, "claims": [self.read(claim_ref=ref, retrieval_receipt_id=retrieval_receipt_id, expected_hash=hashes[ref], caller=caller) for ref in refs], "scopeExpansion": False}

    def _evidence(self, conn: sqlite3.Connection, kind: str, ref: str, owner_id: str, scope_id: str) -> tuple[str, str]:
        if kind == "private_session":
            row = conn.execute("SELECT content_sha256,content_text FROM agent_memory_evidence WHERE evidence_id=? AND owner_id=? AND scope_kind='session' AND scope_id=? AND visibility='private' AND scope_mode='authoritative' AND status='active'", (ref, owner_id, scope_id)).fetchone()
        elif kind == "room_post":
            row = conn.execute("SELECT content_hash,content_bytes FROM room_v2_posts WHERE post_id=? AND room_id=? AND visibility IN ('room','root')", (ref, scope_id)).fetchone()
        else:
            row = conn.execute("SELECT content_hash,'' FROM room_v2_external_import_intakes WHERE import_id=? AND scan_status='allowed' AND data_only=1 AND raw_bytes_stored=0", (ref,)).fetchone()
        if row is None: raise KnowledgePromotionError("PromotionCandidate has no authorized immutable evidence")
        raw = row[1]
        text = bytes(raw).decode("utf-8", errors="replace") if isinstance(raw, (bytes, bytearray)) else str(raw or "")
        return str(row[0]), text

    @staticmethod
    def _candidate(conn: sqlite3.Connection, candidate_id: str) -> sqlite3.Row:
        row = conn.execute("SELECT * FROM room_v2_promotion_candidates WHERE promotion_candidate_id=?", (candidate_id,)).fetchone()
        if row is None: raise KeyError(candidate_id)
        return row

    @staticmethod
    def _assert_candidate(row: sqlite3.Row) -> None:
        material = {"promotionCandidateId": row["promotion_candidate_id"], "evidenceKind": row["evidence_kind"], "evidenceRef": row["evidence_ref"], "evidenceHash": row["evidence_hash"], "claimKey": row["claim_key"], "claimText": row["claim_text"], "knowledgeDomain": row["knowledge_domain"], "ownerKind": row["owner_kind"], "ownerId": row["owner_id"], "scopeKind": row["scope_kind"], "scopeId": row["scope_id"], "visibility": row["visibility"], "promotionPolicy": row["promotion_policy"], "provenance": json.loads(row["provenance_json"]), "conflictStatus": row["conflict_status"], "conflictClaimRefs": json.loads(row["conflict_claim_refs_json"]), "secretScan": json.loads(row["secret_scan_json"]), "risk": row["risk"], "nominatedBy": row["nominated_by"], "createdAtMs": row["created_at_ms"]}
        if _hash_json(material) != row["candidate_hash"]: raise KnowledgePromotionError("PromotionCandidate was tampered")

    def _verify_approval(self, approval: sqlite3.Row, candidate: sqlite3.Row) -> None:
        if approval["candidate_hash"] != candidate["candidate_hash"]: raise KnowledgePromotionError("Promotion approval candidate hash changed")
        material = {"approvalReceiptId": approval["approval_receipt_id"], "promotionCandidateId": candidate["promotion_candidate_id"], "candidateHash": approval["candidate_hash"], "authorityRef": approval["authority_ref"], "conflictResolution": approval["conflict_resolution"], "createdAtMs": approval["created_at_ms"]}
        secret = self._authority_secrets.get(str(approval["authority_ref"])); content_hash = _hash_json(material)
        if secret is None or content_hash != approval["content_hash"] or not hmac.compare_digest(str(approval["authority_signature"]), hmac.new(secret, content_hash.encode(), hashlib.sha256).hexdigest()): raise KnowledgePromotionError("Promotion approval receipt was tampered")

    def _verify_authority(self, authority_ref: str, authority_secret: bytes | str) -> None:
        if not (authority_ref.startswith("user:") or authority_ref.startswith("admin:")): raise KnowledgePromotionError("knowledge lifecycle requires user/admin authority")
        supplied = authority_secret if isinstance(authority_secret, bytes) else authority_secret.encode(); configured = self._authority_secrets.get(authority_ref)
        if configured is None or not hmac.compare_digest(configured, supplied): raise KnowledgePromotionError("knowledge lifecycle authority is not trusted")

    @staticmethod
    def _bump_epoch(conn: sqlite3.Connection, scope_key: str, at_ms: int) -> int:
        row = conn.execute("SELECT knowledge_epoch FROM room_v2_knowledge_epochs WHERE scope_key=?", (scope_key,)).fetchone(); epoch = (int(row[0]) if row else 0) + 1
        conn.execute("INSERT INTO room_v2_knowledge_epochs VALUES (?,?,?) ON CONFLICT(scope_key) DO UPDATE SET knowledge_epoch=excluded.knowledge_epoch,updated_at_ms=excluded.updated_at_ms", (scope_key, epoch, at_ms)); return epoch

    @staticmethod
    def _outbox(conn: sqlite3.Connection, outbox_id: str, claim_version_id: str, operation: str, at_ms: int) -> None:
        material = {"outboxId": outbox_id, "claimVersionId": claim_version_id, "operation": operation}
        conn.execute(
            """INSERT INTO room_v2_knowledge_index_outbox(
               outbox_id,claim_version_id,operation,state,payload_hash,available_at_ms,created_at_ms)
               VALUES (?,?,?,'pending',?,?,?)""",
            (outbox_id, claim_version_id, operation, _hash_json(material), at_ms, at_ms),
        )

    @staticmethod
    def _cache_tombstones(conn: sqlite3.Connection, scope_key: str, epoch: int, scope_kind: str, scope_id: str, reason: str, at_ms: int) -> None:
        if scope_kind == "room":
            rows = conn.execute("SELECT journal_id,session_id FROM room_v2_provider_projection_journals WHERE room_id=?", (scope_id,)).fetchall()
        elif scope_kind == "session":
            rows = conn.execute("SELECT journal_id,session_id FROM room_v2_provider_projection_journals WHERE session_id=?", (scope_id,)).fetchall()
        else:
            rows = []
        if not rows:
            rows = [(None, scope_id if scope_kind == "session" else None)]
        for journal_id, session_id in rows:
            tombstone_id = "knowledge-cache:" + hashlib.sha256(f"{scope_key}\0{epoch}\0{journal_id}\0{session_id}".encode()).hexdigest()[:24]
            conn.execute(
                """INSERT OR IGNORE INTO room_v2_knowledge_cache_tombstones
                   (tombstone_id,scope_key,knowledge_epoch,journal_id,session_id,reason,created_at_ms)
                   VALUES (?,?,?,?,?,?,?)""",
                (tombstone_id, scope_key, epoch, journal_id, session_id, reason, at_ms),
            )

    def consume_cache_tombstones(
        self,
        *,
        consumed_at_ms: int,
    ) -> ConsumedCacheTombstones:
        """Claim every unconsumed cache tombstone and report what to clear.

        This store writes the tombstones, so it also owns retiring them. The
        caller previously ran this SELECT and UPDATE itself with its own
        connection and transaction, which made `AgentService` a second writer
        of a Room table it does not own. It now receives the sessions whose
        process-local recall state must follow, plus how many rows were
        retired, without touching the table.
        """

        with self._connect(immediate=True) as conn:
            rows = conn.execute(
                """SELECT tombstone_id,session_id FROM room_v2_knowledge_cache_tombstones
                   WHERE consumed_at_ms=0 ORDER BY created_at_ms,tombstone_id"""
            ).fetchall()
            if rows:
                conn.executemany(
                    "UPDATE room_v2_knowledge_cache_tombstones SET consumed_at_ms=? WHERE tombstone_id=?",
                    [(int(consumed_at_ms), str(row["tombstone_id"])) for row in rows],
                )
        return ConsumedCacheTombstones(
            session_ids=tuple(
                {str(row["session_id"]) for row in rows if row["session_id"]}
            ),
            consumed=len(rows),
        )

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


def _scan(text: str) -> list[str]:
    return [code for code, pattern in _SECRET_PATTERNS if pattern.search(text)]


def _claim_identity(domain: str, owner_kind: str, owner_id: str, scope_kind: str, scope_id: str, claim_key: str) -> str:
    return hashlib.sha256("\0".join((domain, owner_kind, owner_id, scope_kind, scope_id, claim_key)).encode()).hexdigest()


def _claim_identity_from_row(row: Mapping[str, object]) -> str:
    return _claim_identity(str(row["knowledge_domain"]), str(row["owner_kind"]), str(row["owner_id"]), str(row["scope_kind"]), str(row["scope_id"]), str(row["claim_key"]))


def _scope_key(row: Mapping[str, object]) -> str:
    return ":".join(str(row[key]) for key in ("knowledge_domain", "owner_kind", "owner_id", "scope_kind", "scope_id"))


def _refs(values: Sequence[object]) -> list[str]:
    return list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash_json(value: object) -> str:
    return hashlib.sha256(_json(value).encode()).hexdigest()
