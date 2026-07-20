from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from collections.abc import Mapping, Sequence
from pathlib import Path

from .agent_role_book import AgentRoleBookStore
from .contracts.json_schema import validate_contract
from .management_work_contract import (
    ManagementWorkContract,
    ManagementWorkError,
    StoredReceipt,
    WorkExecution,
    canonical_json,
)
from .personal_context_observability import PersonalContextObservability


_APPLY_PATH = "agent.roleBook.activation.apply"
_ROLLBACK_PATH = "agent.roleBook.activation.rollback"
_SELECTION_FIELDS = frozenset(
    {
        "roleId",
        "roleVersion",
        "revisionId",
        "draftId",
        "traitIndexes",
        "capabilityIndexes",
        "lessonIndexes",
        "commitmentIndexes",
    }
)
_ROLE_BOOK_SECTION_ORDER = (
    "personality",
    "capabilities",
    "recentWork",
    "lessonsAndLimits",
    "activeCommitments",
)
_ROLE_BOOK_SECTION_LABELS = {
    "personality": "协作特征",
    "capabilities": "已验证能力",
    "recentWork": "近期工作",
    "lessonsAndLimits": "经验与边界",
    "activeCommitments": "当前承诺",
}


class AgentRoleBookControlService:
    """User-controlled Role Book review, activation, and rollback boundary."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        project: str,
        work_contract: ManagementWorkContract,
        role_books: AgentRoleBookStore,
        observability: PersonalContextObservability,
    ) -> None:
        self.db_path = Path(db_path)
        self.project = _text(project, field="project", maximum=200, allow_empty=True)
        self.work_contract = work_contract
        self.role_books = role_books
        self.observability = observability

    def catalog(
        self,
        *,
        role_id: object,
        role_version: object,
        limit: int = 30,
    ) -> dict[str, object]:
        role, version = self._role_scope(role_id, role_version)
        bounded_limit = max(1, min(int(limit), 100))
        active = self.role_books.active(role, version)
        if active is None:
            raise ValueError("role book does not exist")
        history = self.role_books.history(role, version, limit=bounded_limit)
        with self._connect(readonly=True) as conn:
            daily = self._daily_drafts(
                conn,
                role=role,
                version=version,
                limit=bounded_limit,
            )
            decisions = self._latest_decisions(
                conn,
                role=role,
                version=version,
            )
        for draft in daily:
            decision = decisions.get(str(draft["draftId"]))
            draft["decision"] = decision
        return {
            "schemaVersion": "rag-ime.agent-role-book-control.v1",
            "ok": True,
            "project": self.project,
            "roleId": role,
            "roleVersion": version,
            "active": active,
            "history": history,
            "dailyDrafts": daily,
            "activationPolicy": {
                "agentCanActivate": False,
                "controlCenterConfirmation": "R1",
                "mutableSections": [
                    "personality",
                    "capabilities",
                    "lessonsAndLimits",
                    "activeCommitments",
                ],
                "immutableSections": [
                    "identity",
                    "permissions",
                    "tools",
                    "safety",
                ],
            },
        }

    def activation_preview(self, payload: Mapping[str, object]) -> dict[str, object]:
        try:
            selection = self._selection(payload)
            with self._connect(readonly=True) as conn:
                prepared = self._prepare(conn, selection)
                revision = self._revision_state(conn, prepared)
            return self.work_contract.create_preview(
                path_id=_APPLY_PATH,
                payload=selection,
                expected_revision=revision,
                required_confirm="apply",
                summary={
                    "title": "启用角色书修订",
                    "items": list(prepared["summaryItems"]),
                    "risk": "R1",
                    "diff": prepared["diff"],
                    "evidenceCount": int(
                        prepared.get("evidenceCount") or 0
                    ),
                    "proposedBy": str(prepared.get("proposedBy") or ""),
                    "changeSummary": str(
                        prepared.get("changeSummary") or ""
                    ),
                },
            )
        except Exception as exc:
            return self.work_contract.error_payload(
                exc,
                current_revision=self._fallback_revision(payload),
            )

    def activation_apply(self, payload: Mapping[str, object]) -> dict[str, object]:
        try:
            required = {"previewToken", "payloadSha256", "confirmText"}
            missing = sorted(key for key in required if key not in payload)
            unexpected = sorted(
                str(key)
                for key in payload
                if key not in _SELECTION_FIELDS | required
            )
            if missing or unexpected:
                raise ManagementWorkError(
                    "invalid_request",
                    _field_error(missing=missing, unexpected=unexpected),
                )
            selection = self._selection(
                {
                    key: payload.get(key)
                    for key in _SELECTION_FIELDS
                }
            )

            def current_revision(conn: sqlite3.Connection) -> Mapping[str, object]:
                return self._revision_state(conn, self._prepare(conn, selection))

            def execute(conn: sqlite3.Connection) -> WorkExecution:
                prepared = self._prepare(conn, selection)
                before_id = str(prepared["activeRevisionId"])
                revision_id = str(prepared.get("revisionId") or "")
                if not revision_id:
                    updates = self._daily_updates(prepared)
                    draft = self.role_books.propose_revision_in_connection(
                        conn,
                        prepared["roleId"],
                        prepared["roleVersion"],
                        updates,
                        proposed_by="control-center:daily-role-book-review",
                        change_summary=(
                            "User-approved daily Role Book proposals; "
                            f"draft={prepared['draftId']}"
                        ),
                    )
                    revision_id = str(draft["revisionId"])
                activated = self.role_books.activate_revision_in_connection(
                    conn,
                    revision_id,
                    activated_by="control-center-user",
                    reason="R1 confirmed Role Book activation",
                )
                decision = self.observability.record_draft_decision_in_connection(
                    conn,
                    draft_kind="role_book",
                    draft_id=str(prepared.get("draftId") or revision_id),
                    decision="accepted",
                    role_id=prepared["roleId"],
                    role_version=prepared["roleVersion"],
                    run_id=prepared.get("runId") or "",
                    decided_by="control-center-user",
                    reason="R1 confirmed Role Book activation",
                )
                return WorkExecution(
                    result={
                        "schemaVersion": "rag-ime.agent-role-book-activation.v1",
                        "ok": True,
                        "revision": activated,
                        "decision": decision,
                    },
                    audit_action="agent_role_book_activation",
                    target_type="agent_role_book_revision",
                    target_id=revision_id,
                    rollback_available=True,
                    rollback_path_id=_ROLLBACK_PATH,
                    rollback_confirm="rollback",
                    rollback_authority={
                        "roleId": prepared["roleId"],
                        "roleVersion": prepared["roleVersion"],
                        "fromRevisionId": before_id,
                        "toRevisionId": revision_id,
                    },
                    rollback_data={
                        "activeRevisionId": revision_id,
                    },
                )

            return self.work_contract.execute_apply(
                path_id=_APPLY_PATH,
                payload=selection,
                preview_token=_text(
                    payload.get("previewToken"),
                    field="previewToken",
                    maximum=512,
                ),
                payload_sha256=_text(
                    payload.get("payloadSha256"),
                    field="payloadSha256",
                    maximum=80,
                ),
                confirm_text=_text(
                    payload.get("confirmText"),
                    field="confirmText",
                    maximum=40,
                ),
                current_revision=current_revision,
                executor=execute,
            )
        except Exception as exc:
            return self.work_contract.error_payload(
                exc,
                current_revision=self._fallback_revision(payload),
            )

    def activation_rollback(self, payload: Mapping[str, object]) -> dict[str, object]:
        try:
            expected = {"receiptId", "rollbackToken", "payloadSha256", "confirmText"}
            missing = sorted(key for key in expected if key not in payload)
            unexpected = sorted(str(key) for key in payload if key not in expected)
            if missing or unexpected:
                raise ManagementWorkError(
                    "invalid_request",
                    _field_error(missing=missing, unexpected=unexpected),
                )

            def execute(
                conn: sqlite3.Connection,
                receipt: StoredReceipt,
            ) -> WorkExecution:
                authority = receipt.rollback_authority
                role = _text(
                    authority.get("roleId"),
                    field="roleId",
                    maximum=120,
                )
                version = _text(
                    authority.get("roleVersion"),
                    field="roleVersion",
                    maximum=80,
                )
                before_id = _text(
                    authority.get("fromRevisionId"),
                    field="fromRevisionId",
                    maximum=240,
                )
                after_id = _text(
                    authority.get("toRevisionId"),
                    field="toRevisionId",
                    maximum=240,
                )
                active = conn.execute(
                    """
                    SELECT revision_id
                    FROM agent_role_book_revisions
                    WHERE role_id = ? AND role_version = ? AND status = 'active'
                    """,
                    (role, version),
                ).fetchone()
                if active is None or str(active["revision_id"]) != after_id:
                    raise ManagementWorkError(
                        "rollback_state_changed",
                        "The active Role Book changed after this receipt was issued.",
                    )
                rolled_back = self.role_books.rollback_in_connection(
                    conn,
                    role,
                    version,
                    before_id,
                    rolled_back_by="control-center-user",
                    reason="Control Center Role Book rollback",
                )
                return WorkExecution(
                    result={
                        "schemaVersion": "rag-ime.agent-role-book-activation.v1",
                        "ok": True,
                        "revision": rolled_back,
                    },
                    audit_action="agent_role_book_rollback",
                    target_type="agent_role_book_revision",
                    target_id=before_id,
                )

            return self.work_contract.execute_rollback(
                path_id=_ROLLBACK_PATH,
                receipt_id=_text(
                    payload.get("receiptId"),
                    field="receiptId",
                    maximum=240,
                ),
                rollback_token=_text(
                    payload.get("rollbackToken"),
                    field="rollbackToken",
                    maximum=512,
                ),
                payload_sha256=_text(
                    payload.get("payloadSha256"),
                    field="payloadSha256",
                    maximum=80,
                ),
                confirm_text=_text(
                    payload.get("confirmText"),
                    field="confirmText",
                    maximum=40,
                ),
                expected_apply_path_id=_APPLY_PATH,
                executor=execute,
            )
        except Exception as exc:
            return self.work_contract.error_payload(exc, current_revision={})

    def decide_daily_draft(
        self,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        allowed = {"roleId", "roleVersion", "draftId", "decision"}
        unexpected = sorted(str(key) for key in payload if key not in allowed)
        missing = sorted(key for key in allowed if key not in payload)
        if missing or unexpected:
            raise ValueError(_field_error(missing=missing, unexpected=unexpected))
        role, version = self._role_scope(
            payload.get("roleId"),
            payload.get("roleVersion"),
        )
        draft_id = _text(payload.get("draftId"), field="draftId", maximum=240)
        decision = _text(payload.get("decision"), field="decision", maximum=40)
        if decision not in {"rejected", "deferred"}:
            raise ValueError("daily Role Book decision must be rejected or deferred")
        with self._connect(immediate=True) as conn:
            prepared = self._prepare(
                conn,
                {
                    "roleId": role,
                    "roleVersion": version,
                    "revisionId": "",
                    "draftId": draft_id,
                    "traitIndexes": [],
                    "capabilityIndexes": [],
                    "lessonIndexes": [],
                    "commitmentIndexes": [],
                },
                allow_empty_selection=True,
            )
            result = self.observability.record_draft_decision_in_connection(
                conn,
                draft_kind="role_book",
                draft_id=draft_id,
                decision=decision,
                role_id=role,
                role_version=version,
                run_id=prepared.get("runId") or "",
                decided_by="control-center-user",
                reason=f"Control Center marked Role Book draft {decision}",
            )
        return {
            "schemaVersion": "rag-ime.agent-role-book-draft-decision.v1",
            "ok": True,
            "decision": result,
        }

    def _selection(self, payload: Mapping[str, object]) -> dict[str, object]:
        unexpected = sorted(str(key) for key in payload if key not in _SELECTION_FIELDS)
        if unexpected:
            raise ManagementWorkError(
                "invalid_request",
                f"Unsupported Role Book fields: {', '.join(unexpected)}.",
            )
        role, version = self._role_scope(
            payload.get("roleId"),
            payload.get("roleVersion"),
        )
        revision_id = _text(
            payload.get("revisionId"),
            field="revisionId",
            maximum=240,
            allow_empty=True,
        )
        draft_id = _text(
            payload.get("draftId"),
            field="draftId",
            maximum=240,
            allow_empty=True,
        )
        if bool(revision_id) == bool(draft_id):
            raise ManagementWorkError(
                "invalid_request",
                "Select exactly one stored revision or daily Role Book draft.",
            )
        trait_indexes = _indexes(payload.get("traitIndexes"))
        capability_indexes = _indexes(payload.get("capabilityIndexes"))
        lesson_indexes = _indexes(payload.get("lessonIndexes"))
        commitment_indexes = _indexes(payload.get("commitmentIndexes"))
        proposal_indexes = (
            trait_indexes,
            capability_indexes,
            lesson_indexes,
            commitment_indexes,
        )
        if revision_id and any(proposal_indexes):
            raise ManagementWorkError(
                "invalid_request",
                "Stored revisions cannot carry daily-draft selection indexes.",
            )
        if draft_id and not any(proposal_indexes):
            raise ManagementWorkError(
                "domain_not_applicable",
                "Select at least one Role Book proposal.",
            )
        return {
            "roleId": role,
            "roleVersion": version,
            "revisionId": revision_id,
            "draftId": draft_id,
            "traitIndexes": trait_indexes,
            "capabilityIndexes": capability_indexes,
            "lessonIndexes": lesson_indexes,
            "commitmentIndexes": commitment_indexes,
        }

    def _prepare(
        self,
        conn: sqlite3.Connection,
        selection: Mapping[str, object],
        *,
        allow_empty_selection: bool = False,
    ) -> dict[str, object]:
        role = str(selection["roleId"])
        version = str(selection["roleVersion"])
        active_row = conn.execute(
            """
            SELECT revision_id, revision_number, content_json
            FROM agent_role_book_revisions
            WHERE role_id = ? AND role_version = ? AND status = 'active'
            """,
            (role, version),
        ).fetchone()
        if active_row is None:
            raise ManagementWorkError(
                "domain_not_found",
                "The Role Book has no active revision.",
            )
        base = {
            "roleId": role,
            "roleVersion": version,
            "activeRevisionId": str(active_row["revision_id"]),
            "activeRevisionNumber": int(active_row["revision_number"]),
            "activeSections": _json_object(active_row["content_json"]),
        }
        revision_id = str(selection.get("revisionId") or "")
        if revision_id:
            target = conn.execute(
                """
                SELECT revision_id, role_id, role_version, revision_number,
                       status, content_json, source_revision_id,
                       change_summary, proposed_by
                FROM agent_role_book_revisions
                WHERE revision_id = ?
                """,
                (revision_id,),
            ).fetchone()
            if target is None:
                raise ManagementWorkError(
                    "domain_not_found",
                    "The Role Book draft revision does not exist.",
                )
            if (str(target["role_id"]), str(target["role_version"])) != (role, version):
                raise ManagementWorkError(
                    "domain_scope_mismatch",
                    "The Role Book draft belongs to another role.",
                )
            if str(target["status"]) != "draft":
                raise ManagementWorkError(
                    "domain_not_applicable",
                    "Only a draft Role Book revision can be activated.",
                )
            source_revision_id = str(target["source_revision_id"] or "")
            if source_revision_id != str(base["activeRevisionId"]):
                raise ManagementWorkError(
                    "revision_mismatch",
                    "The Role Book draft was created from an older active revision.",
                )
            target_sections = _json_object(target["content_json"])
            evidence_state = _validated_revision_evidence(
                conn,
                project=self.project,
                role=role,
                sections=target_sections,
            )
            diff = _role_book_diff(
                base["activeSections"],
                target_sections,
            )
            if not int(diff["totals"]["changedItems"]):
                raise ManagementWorkError(
                    "domain_not_applicable",
                    "The Role Book draft does not change the active revision.",
                )
            return {
                **base,
                "revisionId": revision_id,
                "draftId": "",
                "targetSections": target_sections,
                "diff": diff,
                "evidenceCount": len(evidence_state),
                "proposedBy": str(target["proposed_by"] or ""),
                "changeSummary": str(target["change_summary"] or ""),
                "sourceHash": _sha256(
                    {
                        "revisionId": revision_id,
                        "status": str(target["status"]),
                        "content": target_sections,
                        "sourceRevisionId": source_revision_id,
                        "evidenceState": evidence_state,
                    }
                ),
                "summaryItems": _diff_summary_items(
                    int(target["revision_number"]),
                    diff,
                    evidence_count=len(evidence_state),
                ),
            }

        draft_id = str(selection.get("draftId") or "")
        daily = self._daily_draft(
            conn,
            draft_id=draft_id,
            role=role,
            version=version,
        )
        patch = daily["patch"]
        assert isinstance(patch, Mapping)
        traits = _mapping_list(patch.get("traitProposals"))
        capabilities = _mapping_list(patch.get("capabilityProposals"))
        lessons = _mapping_list(patch.get("lessonProposals"))
        commitments = _mapping_list(patch.get("commitmentProposals"))
        trait_indexes = list(selection.get("traitIndexes") or [])
        capability_indexes = list(selection.get("capabilityIndexes") or [])
        lesson_indexes = list(selection.get("lessonIndexes") or [])
        commitment_indexes = list(selection.get("commitmentIndexes") or [])
        if not allow_empty_selection:
            _validate_selected_indexes(trait_indexes, traits, field="traitIndexes")
            _validate_selected_indexes(
                capability_indexes,
                capabilities,
                field="capabilityIndexes",
            )
            _validate_selected_indexes(
                lesson_indexes,
                lessons,
                field="lessonIndexes",
            )
            _validate_selected_indexes(
                commitment_indexes,
                commitments,
                field="commitmentIndexes",
            )
        prepared = {
            **base,
            "revisionId": "",
            "draftId": draft_id,
            "runId": daily["runId"],
            "dailyDraft": daily["draft"],
            "selectedTraits": [traits[index] for index in trait_indexes],
            "selectedCapabilities": [
                capabilities[index] for index in capability_indexes
            ],
            "selectedLessons": [lessons[index] for index in lesson_indexes],
            "selectedCommitments": [
                commitments[index] for index in commitment_indexes
            ],
            "sourceHash": _sha256(
                {
                    "draft": daily["draft"],
                    "evidenceState": daily["evidenceState"],
                }
            ),
        }
        if not allow_empty_selection:
            updates = self._daily_updates(prepared)
            target_sections = dict(base["activeSections"])
            target_sections.update(updates)
            evidence_state = _validated_revision_evidence(
                conn,
                project=self.project,
                role=role,
                sections=target_sections,
            )
            diff = _role_book_diff(base["activeSections"], target_sections)
            prepared.update(
                {
                    "targetSections": target_sections,
                    "diff": diff,
                    "evidenceCount": len(evidence_state),
                    "sourceHash": _sha256(
                        {
                            "draft": daily["draft"],
                            "evidenceState": evidence_state,
                        }
                    ),
                    "summaryItems": [
                        f"采用 {len(trait_indexes)} 条协作特征",
                        f"采用 {len(capability_indexes)} 条能力证据",
                        f"采用 {len(lesson_indexes)} 条经验与边界",
                        f"采用 {len(commitment_indexes)} 条当前承诺",
                        "不会修改身份、权限、工具或安全规则",
                    ],
                }
            )
        else:
            prepared["summaryItems"] = []
        return prepared

    def _revision_state(
        self,
        conn: sqlite3.Connection,
        prepared: Mapping[str, object],
    ) -> dict[str, object]:
        return {
            "roleId": prepared["roleId"],
            "roleVersion": prepared["roleVersion"],
            "activeRevisionId": prepared["activeRevisionId"],
            "activeRevisionNumber": prepared["activeRevisionNumber"],
            "sourceHash": prepared["sourceHash"],
        }

    def _daily_updates(
        self,
        prepared: Mapping[str, object],
    ) -> dict[str, object]:
        active_sections = prepared["activeSections"]
        if not isinstance(active_sections, Mapping):
            raise ManagementWorkError(
                "stored_contract_invalid",
                "The active Role Book sections are invalid.",
            )
        draft_id = str(prepared["draftId"])
        observed_at_ms = int(
            prepared["dailyDraft"].get("createdAtMs")  # type: ignore[union-attr]
            or time.time() * 1000
        )
        updates: dict[str, object] = {}
        selected_traits = _mapping_list(prepared.get("selectedTraits"))
        if selected_traits:
            updates["personality"] = _merge_items(
                active_sections.get("personality"),
                [
                    _proposal_item(
                        item,
                        section="personality",
                        draft_id=draft_id,
                        observed_at_ms=observed_at_ms,
                    )
                    for item in selected_traits
                ],
                limit=6,
            )
        selected_capabilities = _mapping_list(
            prepared.get("selectedCapabilities")
        )
        if selected_capabilities:
            updates["capabilities"] = _merge_items(
                active_sections.get("capabilities"),
                [
                    _proposal_item(
                        item,
                        section="capabilities",
                        draft_id=draft_id,
                        observed_at_ms=observed_at_ms,
                    )
                    for item in selected_capabilities
                ],
                limit=12,
            )
        selected_lessons = _mapping_list(prepared.get("selectedLessons"))
        if selected_lessons:
            updates["lessonsAndLimits"] = _merge_items(
                active_sections.get("lessonsAndLimits"),
                [
                    _proposal_item(
                        item,
                        section="lessonsAndLimits",
                        draft_id=draft_id,
                        observed_at_ms=observed_at_ms,
                    )
                    for item in selected_lessons
                ],
                limit=8,
            )
        selected_commitments = _mapping_list(
            prepared.get("selectedCommitments")
        )
        if selected_commitments:
            updates["activeCommitments"] = _merge_items(
                active_sections.get("activeCommitments"),
                [
                    _proposal_item(
                        item,
                        section="activeCommitments",
                        draft_id=draft_id,
                        observed_at_ms=observed_at_ms,
                    )
                    for item in selected_commitments
                ],
                limit=8,
            )
        if not updates:
            raise ManagementWorkError(
                "domain_not_applicable",
                "The selected daily draft has no usable Role Book proposals.",
            )
        return updates

    def _daily_drafts(
        self,
        conn: sqlite3.Connection,
        *,
        role: str,
        version: str,
        limit: int,
    ) -> list[dict[str, object]]:
        rows = conn.execute(
            """
            SELECT run_id, output_json
            FROM personal_context_consolidation_runs
            WHERE project = ? AND role_id = ? AND role_version = ?
              AND status = 'succeeded'
            ORDER BY completed_at_ms DESC, run_id DESC
            LIMIT ?
            """,
            (self.project, role, version, limit),
        ).fetchall()
        drafts: list[dict[str, object]] = []
        for row in rows:
            output = _json_object(row["output_json"])
            draft = output.get("roleBookDraft")
            if not isinstance(draft, Mapping):
                continue
            validate_contract(dict(draft), "role-book-revision-draft.v1.json")
            patch = draft.get("patch")
            patch = patch if isinstance(patch, Mapping) else {}
            drafts.append(
                {
                    "draftId": str(draft["draftId"]),
                    "runId": str(row["run_id"]),
                    "createdAtMs": int(draft["createdAtMs"]),
                    "traitProposals": _mapping_list(
                        patch.get("traitProposals")
                    ),
                    "capabilityProposals": _mapping_list(
                        patch.get("capabilityProposals")
                    ),
                    "lessonProposals": _mapping_list(
                        patch.get("lessonProposals")
                    ),
                    "commitmentProposals": _mapping_list(
                        patch.get("commitmentProposals")
                    ),
                    "proposalDiagnostics": _json_object(
                        draft.get("proposalDiagnostics")
                    ),
                    "sourceEvidenceCount": len(
                        list(draft.get("sourceEvidenceIds") or [])
                    ),
                }
            )
        return drafts

    def _daily_draft(
        self,
        conn: sqlite3.Connection,
        *,
        draft_id: str,
        role: str,
        version: str,
    ) -> dict[str, object]:
        rows = conn.execute(
            """
            SELECT run_id, output_json
            FROM personal_context_consolidation_runs
            WHERE project = ? AND role_id = ? AND role_version = ?
              AND status = 'succeeded'
            ORDER BY completed_at_ms DESC, run_id DESC
            LIMIT 200
            """,
            (self.project, role, version),
        ).fetchall()
        for row in rows:
            output = _json_object(row["output_json"])
            draft = output.get("roleBookDraft")
            if not isinstance(draft, Mapping):
                continue
            if str(draft.get("draftId") or "") != draft_id:
                continue
            selected = dict(draft)
            validate_contract(selected, "role-book-revision-draft.v1.json")
            if (
                str(selected["project"]) != self.project
                or str(selected["roleId"]) != role
                or str(selected["baseRoleVersion"]) != version
            ):
                raise ManagementWorkError(
                    "domain_scope_mismatch",
                    "The daily Role Book draft belongs to another scope.",
                )
            evidence_ids = [
                str(value)
                for value in list(selected.get("sourceEvidenceIds") or [])
            ]
            if not evidence_ids:
                raise ManagementWorkError(
                    "stored_contract_invalid",
                    "The daily Role Book draft has no source evidence.",
                )
            proposal_evidence_ids = _draft_proposal_evidence_ids(selected)
            if not proposal_evidence_ids or not set(
                proposal_evidence_ids
            ).issubset(set(evidence_ids)):
                raise ManagementWorkError(
                    "stored_contract_invalid",
                    "A daily Role Book proposal references evidence outside its source window.",
                )
            placeholders = ",".join("?" for _ in evidence_ids)
            evidence_rows = conn.execute(
                f"""
                SELECT evidence_id, status, content_text, content_sha256
                FROM agent_memory_evidence
                WHERE project = ? AND role_id = ?
                  AND evidence_id IN ({placeholders})
                """,  # noqa: S608 - placeholders are generated, never values
                (self.project, role, *evidence_ids),
            ).fetchall()
            if (
                len(evidence_rows) != len(set(evidence_ids))
                or any(str(item["status"]) != "active" for item in evidence_rows)
            ):
                raise ManagementWorkError(
                    "revision_mismatch",
                    "The daily Role Book evidence changed after consolidation.",
                )
            evidence_state = _verified_evidence_state(evidence_rows)
            return {
                "runId": str(row["run_id"]),
                "draft": selected,
                "patch": selected["patch"],
                "evidenceState": evidence_state,
            }
        raise ManagementWorkError(
            "domain_not_found",
            "The daily Role Book draft does not exist.",
        )

    def _latest_decisions(
        self,
        conn: sqlite3.Connection,
        *,
        role: str,
        version: str,
    ) -> dict[str, dict[str, object]]:
        rows = conn.execute(
            """
            SELECT *
            FROM personal_context_draft_decisions
            WHERE project = ? AND role_id = ? AND role_version = ?
              AND draft_kind = 'role_book'
            ORDER BY created_at_ms DESC, decision_id DESC
            """,
            (self.project, role, version),
        ).fetchall()
        latest: dict[str, dict[str, object]] = {}
        for row in rows:
            draft_id = str(row["draft_id"])
            latest.setdefault(
                draft_id,
                {
                    "decisionId": str(row["decision_id"]),
                    "decision": str(row["decision"]),
                    "createdAtMs": int(row["created_at_ms"]),
                },
            )
        return latest

    def _fallback_revision(
        self,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        try:
            role, version = self._role_scope(
                payload.get("roleId"),
                payload.get("roleVersion"),
            )
            active = self.role_books.active(role, version)
            return {
                "roleId": role,
                "roleVersion": version,
                "activeRevisionId": (
                    str(active.get("revisionId") or "")
                    if isinstance(active, Mapping)
                    else ""
                ),
            }
        except Exception:
            return {}

    @staticmethod
    def _role_scope(
        role_id: object,
        role_version: object,
    ) -> tuple[str, str]:
        return (
            _text(role_id, field="roleId", maximum=120),
            _text(role_version, field="roleVersion", maximum=80),
        )

    def _connect(
        self,
        *,
        readonly: bool = False,
        immediate: bool = False,
    ) -> "_Connection":
        return _Connection(
            self.db_path,
            readonly=readonly,
            immediate=immediate,
        )


class _Connection:
    def __init__(
        self,
        db_path: Path,
        *,
        readonly: bool,
        immediate: bool,
    ) -> None:
        self.db_path = db_path
        self.readonly = readonly
        self.immediate = immediate
        self.conn: sqlite3.Connection | None = None

    def __enter__(self) -> sqlite3.Connection:
        if self.readonly:
            conn = sqlite3.connect(
                f"file:{self.db_path}?mode=ro",
                uri=True,
                timeout=5.0,
            )
        else:
            conn = sqlite3.connect(self.db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        if self.readonly:
            conn.execute("PRAGMA query_only=ON")
        if self.immediate:
            conn.execute("BEGIN IMMEDIATE")
        self.conn = conn
        return conn

    def __exit__(
        self,
        exc_type: object,
        exc: object,
        traceback: object,
    ) -> None:
        assert self.conn is not None
        if self.immediate:
            if exc_type is None:
                self.conn.commit()
            else:
                self.conn.rollback()
        self.conn.close()


def _validated_revision_evidence(
    conn: sqlite3.Connection,
    *,
    project: str,
    role: str,
    sections: object,
) -> list[dict[str, str]]:
    evidence_ids: set[str] = set()
    for section in _ROLE_BOOK_SECTION_ORDER:
        for item in _strict_role_book_items(sections, section=section):
            raw_ids = item.get("evidenceIds")
            if not isinstance(raw_ids, Sequence) or isinstance(
                raw_ids,
                (str, bytes, bytearray),
            ):
                raise ManagementWorkError(
                    "stored_contract_invalid",
                    f"Role Book section {section} has invalid evidence IDs.",
                )
            item_ids = {
                _text(value, field="evidenceId", maximum=240)
                for value in raw_ids
            }
            if not item_ids:
                raise ManagementWorkError(
                    "stored_contract_invalid",
                    f"Role Book section {section} has an item without evidence.",
                )
            provenance = item.get("provenance")
            if (
                isinstance(provenance, Mapping)
                and str(provenance.get("sourceType") or "")
                == "builtin_persona_manifest"
            ):
                source_id = _text(
                    provenance.get("sourceId"),
                    field="sourceId",
                    maximum=240,
                )
                if (
                    item_ids != {source_id}
                    or not source_id.startswith(f"builtin-persona:{role}@")
                ):
                    raise ManagementWorkError(
                        "stored_contract_invalid",
                        "Built-in Role Book evidence does not match its Persona manifest.",
                    )
                continue
            evidence_ids.update(item_ids)
    if not evidence_ids:
        return []
    placeholders = ",".join("?" for _ in evidence_ids)
    rows = conn.execute(
        f"""
        SELECT evidence_id, status, content_text, content_sha256
        FROM agent_memory_evidence
        WHERE project = ? AND role_id = ?
          AND evidence_id IN ({placeholders})
        """,  # noqa: S608 - placeholders are generated, never values
        (project, role, *sorted(evidence_ids)),
    ).fetchall()
    if len(rows) != len(evidence_ids):
        raise ManagementWorkError(
            "revision_mismatch",
            "The Role Book draft references missing or out-of-scope evidence.",
        )
    return _verified_evidence_state(rows)


def _verified_evidence_state(
    rows: Sequence[sqlite3.Row],
) -> list[dict[str, str]]:
    state: list[dict[str, str]] = []
    for row in rows:
        status = str(row["status"] or "")
        digest = str(row["content_sha256"] or "")
        actual = hashlib.sha256(
            str(row["content_text"] or "").encode(
                "utf-8",
                errors="replace",
            )
        ).hexdigest()
        if status != "active" or not digest or digest != actual:
            raise ManagementWorkError(
                "revision_mismatch",
                "The Role Book evidence was tombstoned or failed its content hash check.",
            )
        state.append(
            {
                "evidenceId": str(row["evidence_id"]),
                "status": status,
                "contentSha256": digest,
            }
        )
    return sorted(state, key=lambda item: item["evidenceId"])


def _draft_proposal_evidence_ids(
    draft: Mapping[str, object],
) -> list[str]:
    patch = draft.get("patch")
    if not isinstance(patch, Mapping):
        return []
    evidence_ids: list[str] = []
    for field in (
        "traitProposals",
        "capabilityProposals",
        "lessonProposals",
        "commitmentProposals",
    ):
        for proposal in _mapping_list(patch.get(field)):
            values = proposal.get("sourceEvidenceIds")
            if not isinstance(values, Sequence) or isinstance(
                values,
                (str, bytes, bytearray),
            ):
                return []
            evidence_ids.extend(
                _text(value, field="evidenceId", maximum=240)
                for value in values
            )
    return evidence_ids


def _role_book_diff(
    active_sections: object,
    target_sections: object,
) -> dict[str, object]:
    section_diffs: list[dict[str, object]] = []
    added_total = 0
    removed_total = 0
    changed_total = 0
    for section in _ROLE_BOOK_SECTION_ORDER:
        active_items = _strict_role_book_items(
            active_sections,
            section=section,
        )
        target_items = _strict_role_book_items(
            target_sections,
            section=section,
        )
        active_by_id = _items_by_id(active_items, section=section)
        target_by_id = _items_by_id(target_items, section=section)
        added = [
            _diff_item(target_by_id[item_id])
            for item_id in target_by_id.keys() - active_by_id.keys()
        ]
        removed = [
            _diff_item(active_by_id[item_id])
            for item_id in active_by_id.keys() - target_by_id.keys()
        ]
        changed = [
            {
                "itemId": item_id,
                "before": _diff_item(active_by_id[item_id]),
                "after": _diff_item(target_by_id[item_id]),
            }
            for item_id in active_by_id.keys() & target_by_id.keys()
            if canonical_json(active_by_id[item_id])
            != canonical_json(target_by_id[item_id])
        ]
        added.sort(key=lambda item: str(item["itemId"]))
        removed.sort(key=lambda item: str(item["itemId"]))
        changed.sort(key=lambda item: str(item["itemId"]))
        if added or removed or changed:
            section_diffs.append(
                {
                    "section": section,
                    "label": _ROLE_BOOK_SECTION_LABELS[section],
                    "added": added,
                    "removed": removed,
                    "changed": changed,
                }
            )
        added_total += len(added)
        removed_total += len(removed)
        changed_total += len(changed)
    return {
        "sections": section_diffs,
        "totals": {
            "added": added_total,
            "removed": removed_total,
            "changed": changed_total,
            "changedItems": added_total + removed_total + changed_total,
        },
    }


def _strict_role_book_items(
    sections: object,
    *,
    section: str,
) -> list[dict[str, object]]:
    if not isinstance(sections, Mapping):
        raise ManagementWorkError(
            "stored_contract_invalid",
            "The stored Role Book sections are invalid.",
        )
    values = sections.get(section)
    if not isinstance(values, Sequence) or isinstance(
        values,
        (str, bytes, bytearray),
    ):
        raise ManagementWorkError(
            "stored_contract_invalid",
            f"The stored Role Book section {section} is invalid.",
        )
    if any(not isinstance(item, Mapping) for item in values):
        raise ManagementWorkError(
            "stored_contract_invalid",
            f"The stored Role Book section {section} contains an invalid item.",
        )
    return [dict(item) for item in values]


def _items_by_id(
    items: Sequence[Mapping[str, object]],
    *,
    section: str,
) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for item in items:
        item_id = _text(item.get("itemId"), field="itemId", maximum=160)
        if item_id in result:
            raise ManagementWorkError(
                "stored_contract_invalid",
                f"Role Book section {section} contains duplicate item IDs.",
            )
        result[item_id] = dict(item)
    return result


def _diff_item(item: Mapping[str, object]) -> dict[str, object]:
    evidence = item.get("evidenceIds")
    evidence_ids = (
        [
            _text(value, field="evidenceId", maximum=240)
            for value in evidence
        ]
        if isinstance(evidence, Sequence)
        and not isinstance(evidence, (str, bytes, bytearray))
        else []
    )
    return {
        "itemId": _text(item.get("itemId"), field="itemId", maximum=160),
        "text": _text(item.get("text"), field="text", maximum=280),
        "evidenceIds": evidence_ids,
    }


def _diff_summary_items(
    revision_number: int,
    diff: Mapping[str, object],
    *,
    evidence_count: int,
) -> list[str]:
    totals = diff.get("totals")
    totals = totals if isinstance(totals, Mapping) else {}
    return [
        f"启用 revision {revision_number}",
        (
            f"新增 {int(totals.get('added') or 0)} 项，"
            f"删除 {int(totals.get('removed') or 0)} 项，"
            f"修改 {int(totals.get('changed') or 0)} 项"
        ),
        f"已校验 {evidence_count} 条原始证据",
        "旧 Session 继续固定原 revision",
    ]


def _proposal_item(
    proposal: Mapping[str, object],
    *,
    section: str,
    draft_id: str,
    observed_at_ms: int,
) -> dict[str, object]:
    text = " ".join(str(proposal.get("text") or "").split())[:280]
    if not text:
        raise ManagementWorkError(
            "stored_contract_invalid",
            "The selected Role Book proposal is empty.",
        )
    evidence_ids = [
        _text(value, field="evidenceId", maximum=240)
        for value in list(proposal.get("sourceEvidenceIds") or [])
    ]
    if not evidence_ids or len(evidence_ids) > 16:
        raise ManagementWorkError(
            "stored_contract_invalid",
            "The selected Role Book proposal has invalid evidence.",
        )
    item_id = (
        "role-review:"
        + section
        + ":"
        + hashlib.sha256(
            f"{draft_id}\x1f{text}".encode("utf-8")
        ).hexdigest()[:24]
    )
    return {
        "itemId": item_id,
        "text": text,
        "provenance": {
            "sourceType": f"daily_{section}_proposal",
            "sourceId": draft_id,
            "observedAtMs": observed_at_ms,
        },
        "evidenceIds": evidence_ids,
    }


def _merge_items(
    existing: object,
    incoming: Sequence[Mapping[str, object]],
    *,
    limit: int,
) -> list[dict[str, object]]:
    values = _mapping_list(existing)
    seen = {" ".join(str(item.get("text") or "").split()).casefold() for item in values}
    for item in incoming:
        key = " ".join(str(item.get("text") or "").split()).casefold()
        if key and key not in seen:
            values.append(dict(item))
            seen.add(key)
    return values[-limit:]


def _indexes(value: object) -> list[int]:
    if value is None:
        return []
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ManagementWorkError("invalid_request", "Selection indexes must be arrays.")
    indexes: list[int] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int) or item < 0:
            raise ManagementWorkError(
                "invalid_request",
                "Selection indexes must be non-negative integers.",
            )
        indexes.append(item)
    if len(indexes) > 32 or len(indexes) != len(set(indexes)):
        raise ManagementWorkError(
            "invalid_request",
            "Selection indexes are duplicated or exceed the limit.",
        )
    return sorted(indexes)


def _validate_selected_indexes(
    indexes: Sequence[object],
    values: Sequence[Mapping[str, object]],
    *,
    field: str,
) -> None:
    if any(not isinstance(index, int) or index >= len(values) for index in indexes):
        raise ManagementWorkError(
            "invalid_request",
            f"{field} contains an out-of-range proposal.",
        )


def _mapping_list(value: object) -> list[dict[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _json_object(value: object) -> dict[str, object]:
    if isinstance(value, Mapping):
        return dict(value)
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return dict(parsed) if isinstance(parsed, Mapping) else {}


def _sha256(value: object) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _field_error(*, missing: Sequence[str], unexpected: Sequence[str]) -> str:
    messages = []
    if missing:
        messages.append("Missing fields: " + ", ".join(missing))
    if unexpected:
        messages.append("Unsupported fields: " + ", ".join(unexpected))
    return ". ".join(messages) + "."


def _text(
    value: object,
    *,
    field: str,
    maximum: int,
    allow_empty: bool = False,
) -> str:
    normalized = " ".join(str(value or "").split())
    if not normalized and not allow_empty:
        raise ManagementWorkError("invalid_request", f"{field} must not be empty.")
    if len(normalized) > maximum:
        raise ManagementWorkError("invalid_request", f"{field} is too long.")
    return normalized


__all__ = ["AgentRoleBookControlService"]
