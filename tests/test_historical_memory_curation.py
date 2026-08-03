from __future__ import annotations

import hashlib
import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from rag_ime.agent_memory_sources import AgentMemorySourceStore
from rag_ime.agent_sessions import AgentSessionStore
from rag_ime.historical_memory_curation import (
    HistoricalMemoryCurationError,
    _quarantine_noncanonical_legacy_atoms,
    curate_historical_memory_database,
    prepare_atom_first_historical_recuration,
    resume_atom_first_historical_recuration,
)
from rag_ime.local_sqlite_core import LocalSqliteCoreClient
from rag_ime.memory_curation import MEMORY_CURATION_ARCHITECTURE
from rag_ime.models import InputEvent
from rag_ime.memory_evidence_admission import (
    curatable_personal_evidence_sql,
    transition_evidence_admission,
)
from rag_ime.owner_memory_curation import OwnerMemoryCurator


PROJECT = "wisdom-weasel-rag-ime"


class _HistoricalOrganizer:
    provider_name = "fixture"
    curation_protocol_version = "personal-v2"

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def begin_run(self, _run_id: str, *, frozen_input_sha256: str) -> None:
        if len(frozen_input_sha256) != 64:
            raise AssertionError("frozen input hash missing")

    def finish_run(self) -> None:
        return

    def fail_run(self, _error: BaseException) -> None:
        return

    def curate_owner_memory(
        self,
        *,
        bundle: dict[str, object],
        project: str,
        owner_kind: str,
        owner_id: str,
        instruction: str = "",
    ) -> dict[str, object]:
        del instruction
        inputs = [dict(item) for item in bundle.get("inputs") or []]
        self.calls.append(
            {
                "date": dict(bundle.get("activityContext") or {}).get("date"),
                "ownerKind": owner_kind,
                "ownerId": owner_id,
                "texts": [str(item.get("text") or "") for item in inputs],
            }
        )
        atoms = []
        for index, item in enumerate(inputs, start=1):
            atoms.append(
                {
                    "atomId": f"atom:history:{len(self.calls)}:{index}",
                    "claimKey": f"history:{len(self.calls)}:{index}",
                    "canonicalText": str(item["text"]),
                    "summary": "历史迁移中的稳定个人记忆",
                    "kind": "project_decision",
                    "sourceEventIds": list(item["sourceEventIds"]),
                    "evidenceIds": list(item.get("evidenceIds") or []),
                    "confidence": 0.92,
                    "qualityScore": 0.9,
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
        return {
            "schemaVersion": "rag-ime.personal-memory-curation.v2",
            "provider": "fixture",
            "model": "fixture-history",
            "sourceDecisions": [
                {
                    "sourceRef": item["sourceRef"],
                    "evidenceId": item["evidenceId"],
                    "evidenceIds": list(item.get("evidenceIds") or []),
                    "disposition": "remember",
                    "evidenceAdmissionState": "admitted",
                    "reasonCode": "durable_historical_memory",
                    "confidence": 0.95,
                }
                for item in inputs
            ],
            "topicBooks": [
                {
                    "title": "个人长期记忆",
                    "summary": "保留经过证据审阅的历史项目决定。",
                    "sourceEventIds": [
                        int(event_id)
                        for item in inputs
                        for event_id in item["sourceEventIds"]
                    ],
                    "memoryAtomIds": [str(item["atomId"]) for item in atoms],
                    "confidence": 0.9,
                    "qualityScore": 0.88,
                }
            ],
            "memoryAtoms": atoms,
            "memoryRetractions": [],
            "warnings": [],
            "personalCurationV2": {
                "protocol": "personal-v2",
                "independentlyVerified": True,
            },
            "modelDiagnostics": {
                "verifier": {"sessionId": "isolated-history-verifier"}
            },
            "modelBundleStats": {"sourceCount": len(inputs)},
        }


class _AtomFirstHistoricalOrganizer(_HistoricalOrganizer):
    curation_protocol_version = MEMORY_CURATION_ARCHITECTURE

    def __init__(self, db_path: Path, session_id: str) -> None:
        super().__init__()
        self.db_path = db_path
        self.session_id = session_id
        self.active_run_id = ""
        self.model_run_count = 0

    def begin_run(self, run_id: str, *, frozen_input_sha256: str) -> None:
        super().begin_run(run_id, frozen_input_sha256=frozen_input_sha256)
        self.active_run_id = run_id
        session_id = self.session_id
        if self.model_run_count:
            session_id = str(
                AgentSessionStore(self.db_path).create(
                    title=f"history model run {self.model_run_count + 1}",
                    created_at_ms=self.model_run_count + 1,
                )["id"]
            )
        self.model_run_count += 1
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO memory_curation_model_runs(
                    run_id, session_id, profile, provider, model_id,
                    thinking_level, frozen_input_sha256, state,
                    created_at_ms, updated_at_ms
                ) VALUES (?, ?, 'MEMORY_CURATION', 'fixture',
                          'fixture-history', 'max', ?, 'running', 1, 1)
                """,
                (run_id, session_id, frozen_input_sha256),
            )
            conn.commit()

    def finish_run(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE memory_curation_model_runs
                SET state = 'completed', updated_at_ms = 2, completed_at_ms = 2
                WHERE run_id = ?
                """,
                (self.active_run_id,),
            )
            conn.commit()

    def fail_run(self, _error: BaseException) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE memory_curation_model_runs
                SET state = 'failed', updated_at_ms = 2, completed_at_ms = 2
                WHERE run_id = ?
                """,
                (self.active_run_id,),
            )
            conn.commit()

    def curate_owner_memory(self, **kwargs: object) -> dict[str, object]:
        result = super().curate_owner_memory(**kwargs)
        result["curationArchitecture"] = MEMORY_CURATION_ARCHITECTURE
        result["personalCurationV2"] = {
            **dict(result.get("personalCurationV2") or {}),
            "protocol": "personal-v2",
            "curationArchitecture": MEMORY_CURATION_ARCHITECTURE,
        }
        result["memoryAtoms"] = [
            {**dict(item), "kind": "personal_principle"}
            for item in result.get("memoryAtoms") or []
            if isinstance(item, dict)
        ]
        return result


class HistoricalMemoryCurationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-history-curation-")
        self.db_path = Path(self.tmp.name) / "rag-ime.sqlite"
        self.sessions = AgentSessionStore(self.db_path)
        self.sessions.initialize()
        self.session = self.sessions.create(title="history", created_at_ms=1)
        self.core = LocalSqliteCoreClient(self.db_path)
        self.core.initialize()
        self.sources = AgentMemorySourceStore(self.db_path, project=PROJECT)
        self.sources.initialize()
        self.capture_ordinal = 0

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_full_history_resolves_old_draft_and_organizes_all_dates(self) -> None:
        transient_source_id = self._capture(
            text="AI 辅助已暂停，普通 Rime 拼音仍可使用。",
            created_at_ms=self._ms(2026, 7, 14, 10),
        )
        old_curator = OwnerMemoryCurator(
            self.db_path,
            organizer=_HistoricalOrganizer(),
            project=PROJECT,
            initial_settle_ms=0,
        )
        old_curator.initialize()
        old = old_curator.run_due(
            manual=True,
            owner_kind="user",
            owner_id="default",
            current_ms=self._ms(2026, 7, 14, 11),
        )
        self.assertEqual(old["results"][0]["runStatus"], "waiting_review")

        self._capture(
            text="输入法已经切换到 100M 自训练模型，旧 0.8B 模型不再作为热路径。",
            created_at_ms=self._ms(2026, 7, 15, 10),
        )
        self._capture(
            text="个人记忆在 Session 开始时召回一次，后续由 Agent 按需使用工具检索。",
            created_at_ms=self._ms(2026, 7, 16, 10),
        )
        organizer = _AtomFirstHistoricalOrganizer(
            self.db_path,
            str(self.session["id"]),
        )

        report = curate_historical_memory_database(
            self.db_path,
            organizer=organizer,
            project=PROJECT,
            timezone_name="Asia/Shanghai",
            max_batches=20,
        )

        self.assertTrue(report["ok"])
        self.assertEqual(report["ownerCuration"]["pendingSourceCount"], 0)
        self.assertEqual(report["after"]["draftOwnerRuns"], 0)
        self.assertEqual(report["timelines"]["dateCount"], 3)
        self.assertEqual(
            {item["status"] for item in report["timelines"]["items"]},
            {"approved"},
        )
        self.assertTrue(report["reviewedRuns"][0]["transientSourcesRejected"])
        self.assertEqual(
            self.sources.get(transient_source_id)["disposition"],
            "not_for_memory",
        )
        self.assertEqual(len(organizer.calls), 2)
        with sqlite3.connect(self.db_path) as conn:
            current_atoms = [
                str(row[0])
                for row in conn.execute(
                    "SELECT canonical_text FROM memory_atoms WHERE status IN ('active', 'approved')"
                ).fetchall()
            ]
            approved_timelines = int(
                conn.execute(
                    "SELECT COUNT(*) FROM daily_activity_timelines WHERE status = 'approved'"
                ).fetchone()[0]
            )
        self.assertFalse(any("已暂停" in text for text in current_atoms))
        self.assertTrue(any("100M" in text for text in current_atoms))
        self.assertTrue(any("Session" in text for text in current_atoms))
        self.assertEqual(approved_timelines, 3)

    def test_full_history_combines_one_local_day_beyond_online_window(self) -> None:
        self._capture(
            text="上午确认输入法仍由 Rime 解码。",
            created_at_ms=self._ms(2026, 7, 17, 8),
        )
        self._capture(
            text="晚上确认长期记忆只提供辅助候选。",
            created_at_ms=self._ms(2026, 7, 17, 22),
        )
        organizer = _HistoricalOrganizer()

        report = curate_historical_memory_database(
            self.db_path,
            organizer=organizer,
            project=PROJECT,
            timezone_name="Asia/Shanghai",
            max_batches=3,
        )

        self.assertTrue(report["ok"])
        self.assertEqual(len(organizer.calls), 1)
        self.assertEqual(len(organizer.calls[0]["texts"]), 2)

    def test_full_history_splits_dense_day_without_losing_chronology(self) -> None:
        texts = [f"同一天的第 {index} 条完整表达。" for index in range(1, 6)]
        for index, text in enumerate(texts):
            self._capture(
                text=text,
                created_at_ms=self._ms(2026, 7, 17, 8) + index * 1_000,
            )
        organizer = _HistoricalOrganizer()

        report = curate_historical_memory_database(
            self.db_path,
            organizer=organizer,
            project=PROJECT,
            timezone_name="Asia/Shanghai",
            max_sources=2,
            max_batches=5,
        )

        self.assertTrue(report["ok"], report)
        self.assertEqual(
            [len(call["texts"]) for call in organizer.calls],
            [2, 2, 1],
        )
        self.assertEqual(
            [text for call in organizer.calls for text in call["texts"]],
            texts,
        )
        self.assertEqual(
            {call["date"] for call in organizer.calls},
            {"2026-07-17"},
        )
        self.assertEqual(report["ownerCuration"]["pendingSourceCount"], 0)

    def test_full_history_groups_by_occurrence_day_not_migration_write_time(self) -> None:
        first_day_morning = "第一天上午确认输入法仍由 Rime 解码。"
        second_day_morning = "第二天上午确认记忆召回必须保留证据。"
        first_day_evening = "第一天晚上确认长期记忆只提供辅助候选。"
        second_day_evening = "第二天晚上确认完成后保存测试报告。"
        for text, occurred_at_ms in (
            (first_day_morning, self._ms(2026, 7, 17, 8)),
            (second_day_morning, self._ms(2026, 7, 18, 8)),
            (first_day_evening, self._ms(2026, 7, 17, 22)),
            (second_day_evening, self._ms(2026, 7, 18, 22)),
        ):
            source_id = self._capture(text=text, created_at_ms=occurred_at_ms)
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """
                    UPDATE agent_memory_sources
                    SET created_at_ms = ?,
                        metadata_json = json_set(
                            metadata_json,
                            '$.sourceOccurredAtMs',
                            ?
                        )
                    WHERE source_id = ?
                    """,
                    (self._ms(2026, 8, 2, 12), occurred_at_ms, source_id),
                )
                conn.commit()
        organizer = _HistoricalOrganizer()

        report = curate_historical_memory_database(
            self.db_path,
            organizer=organizer,
            project=PROJECT,
            timezone_name="Asia/Shanghai",
            max_batches=4,
        )

        self.assertTrue(report["ok"])
        self.assertEqual(len(organizer.calls), 2)
        self.assertEqual(
            organizer.calls[0]["texts"],
            [first_day_morning, first_day_evening],
        )
        self.assertEqual(
            organizer.calls[1]["texts"],
            [second_day_morning, second_day_evening],
        )

    def test_historical_rime_revision_is_one_atom_with_all_evidence(self) -> None:
        occurred_at_ms = self._ms(2026, 7, 18, 10)
        earlier_context = "记忆整理需要保留每条原始证据，不能因为降噪丢失证据链。"
        final_context = "记忆整理需要保留每条原始证据，不能因为降噪而丢失证据链。"
        source_ids = [
            self._capture(text="证据", created_at_ms=occurred_at_ms),
            self._capture(text="链", created_at_ms=occurred_at_ms + 200),
        ]
        legacy_evidence_ids: list[str] = []
        for source_id, recent_context in zip(
            source_ids,
            (earlier_context, final_context),
            strict=True,
        ):
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """
                    UPDATE input_events
                    SET source = 'squirrel_rime_commit_burst',
                        recent_context = ?, context_group_id = 'app:codex'
                    WHERE id = (
                        SELECT input_event_id FROM agent_memory_sources
                        WHERE source_id = ?
                    )
                    """,
                    (recent_context, source_id),
                )
                conn.commit()
            legacy_evidence_ids.append(
                self._mark_capture_as_recovered_legacy(
                    source_id,
                    disposition="not_for_memory",
                    reason="legacy_fragment_requires_reconstruction",
                    deleted=False,
                )
            )

        prepare_atom_first_historical_recuration(
            self.db_path,
            project=PROJECT,
            reset_run_id="historical-reset:rime-revision",
        )
        with sqlite3.connect(self.db_path) as conn:
            promoted_evidence_ids = [
                str(row[0])
                for row in conn.execute(
                    """
                    SELECT promoted_evidence_id
                    FROM memory_evidence_historical_promotion_receipts
                    WHERE legacy_evidence_id IN (?, ?)
                    ORDER BY input_event_id
                    """,
                    tuple(legacy_evidence_ids),
                ).fetchall()
            ]

        organizer = _AtomFirstHistoricalOrganizer(
            self.db_path,
            str(self.session["id"]),
        )
        report = curate_historical_memory_database(
            self.db_path,
            organizer=organizer,
            project=PROJECT,
            timezone_name="Asia/Shanghai",
            max_batches=3,
        )

        self.assertTrue(report["ok"], report)
        self.assertEqual(organizer.calls[0]["texts"], [final_context])
        self.assertEqual(report["ownerCuration"]["pendingSourceCount"], 0)
        with sqlite3.connect(self.db_path) as conn:
            admitted = {
                str(row[0])
                for row in conn.execute(
                    """
                    SELECT evidence_id FROM agent_memory_evidence
                    WHERE evidence_id IN (?, ?) AND admission_state = 'admitted'
                    """,
                    tuple(promoted_evidence_ids),
                ).fetchall()
            }
            linked = {
                str(row[0])
                for row in conn.execute(
                    """
                    SELECT evidence_id FROM memory_atom_evidence_links
                    WHERE evidence_id IN (?, ?)
                    """,
                    tuple(promoted_evidence_ids),
                ).fetchall()
            }
        self.assertEqual(admitted, set(promoted_evidence_ids))
        self.assertEqual(linked, set(promoted_evidence_ids))

    def test_full_history_reclaims_an_interrupted_offline_cursor(self) -> None:
        interrupted_at_ms = self._ms(2026, 7, 19, 12)
        self._capture(
            text="中断恢复后仍应整理这条长期记忆。",
            created_at_ms=self._ms(2026, 7, 19, 10),
        )
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO memory_curation_cursors(
                    owner_kind, owner_id, project, lane, status, updated_at_ms
                ) VALUES ('user', 'default', ?, 'daily', 'running', ?)
                """,
                (PROJECT, interrupted_at_ms),
            )
            conn.commit()
        organizer = _HistoricalOrganizer()

        with patch(
            "rag_ime.historical_memory_curation.now_ms",
            return_value=interrupted_at_ms,
        ):
            report = curate_historical_memory_database(
                self.db_path,
                organizer=organizer,
                project=PROJECT,
                timezone_name="Asia/Shanghai",
                max_batches=4,
            )

        self.assertTrue(report["ok"])
        self.assertEqual(report["ownerCuration"]["pendingSourceCount"], 0)
        self.assertEqual(len(organizer.calls), 1)

    def test_atom_first_reset_reopens_canonical_evidence_without_touching_inputs(self) -> None:
        self._capture(
            text="我长期要求删除数据前保留可恢复路径。",
            created_at_ms=self._ms(2026, 7, 14, 10),
        )
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            evidence_id = str(
                conn.execute(
                    "SELECT evidence_id FROM agent_memory_evidence"
                ).fetchone()[0]
            )
            transition_evidence_admission(
                conn,
                evidence_id,
                new_state="admitted",
                reason_code="earlier_test_review",
                actor_kind="luna",
                created_at_ms=self._ms(2026, 7, 14, 11),
                run_id="old-curation",
            )
            conn.commit()
            before_text = str(
                conn.execute("SELECT committed_text FROM input_events").fetchone()[0]
            )

        report = prepare_atom_first_historical_recuration(
            self.db_path,
            project=PROJECT,
            reset_run_id="historical-reset:test",
        )

        self.assertTrue(report["ok"])
        self.assertEqual(report["eligibleEvidenceCount"], 1)
        self.assertEqual(report["changedEvidenceCount"], 1)
        self.assertFalse(report["rawInputEventsMutated"])
        with sqlite3.connect(self.db_path) as conn:
            state = str(
                conn.execute(
                    "SELECT admission_state FROM agent_memory_evidence"
                ).fetchone()[0]
            )
            disposition = str(
                conn.execute(
                    "SELECT disposition FROM agent_memory_sources"
                ).fetchone()[0]
            )
            after_text = str(
                conn.execute("SELECT committed_text FROM input_events").fetchone()[0]
            )
        self.assertEqual(state, "candidate")
        self.assertEqual(disposition, "pending")
        self.assertEqual(after_text, before_text)

    def test_historical_cutover_quarantines_unlinked_legacy_atom(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO memory_atoms(
                    id, kind, text, canonical_text,
                    source_event_ids_json, source_memory_ids_json,
                    confidence, quality_score, echo_risk, privacy_level,
                    status, created_at_ms, updated_at_ms,
                    owner_kind, owner_id, claim_key, lineage_id,
                    claim_state, valid_from_ms, knowledge_domain,
                    scope_project
                ) VALUES (
                    'atom:legacy-unlinked', 'preference', '旧兼容结论',
                    '旧兼容结论', '[]', '[]', 0.8, 0.8, 0.0, 'local',
                    'active', 10, 10, 'user', 'default',
                    'legacy:unlinked', 'lineage:legacy:unlinked',
                    'current', 10, 'legacy', ?
                )
                """,
                (PROJECT,),
            )
            conn.commit()

        report = _quarantine_noncanonical_legacy_atoms(
            self.db_path,
            project=PROJECT,
        )

        with sqlite3.connect(self.db_path) as conn:
            atom = conn.execute(
                "SELECT status, claim_state FROM memory_atoms WHERE id = ?",
                ("atom:legacy-unlinked",),
            ).fetchone()
            receipts = int(
                conn.execute(
                    """
                    SELECT COUNT(*) FROM knowledge_scope_quarantine
                    WHERE source_table = 'memory_atoms'
                      AND source_id = 'atom:legacy-unlinked'
                      AND reason_code = ?
                    """,
                    (report["reasonCode"],),
                ).fetchone()[0]
            )
        self.assertEqual(report["quarantinedNow"], 1)
        self.assertEqual(tuple(atom or ()), ("hidden", "retracted"))
        self.assertEqual(receipts, 1)

    def test_historical_promotion_is_idempotent_receipted_and_preserves_audit(self) -> None:
        eligible_source = self._capture(
            text="输入法保留 Rime 解码，长期记忆只提供可区分的辅助候选。",
            created_at_ms=self._ms(2026, 7, 17, 10),
        )
        assistant_source = self._capture(
            text="这是助手生成的结论，不能当成用户长期事实。",
            created_at_ms=self._ms(2026, 7, 17, 11),
        )
        sensitive_source = self._capture(
            text="临时密钥是 synthetic-key-fixture-not-a-real-secret。",
            created_at_ms=self._ms(2026, 7, 17, 12),
        )
        eligible_evidence = self._mark_capture_as_recovered_legacy(
            eligible_source,
            disposition="not_for_memory",
            reason="reviewed_non_durable_source",
            deleted=True,
        )
        assistant_evidence = self._mark_capture_as_recovered_legacy(
            assistant_source,
            disposition="not_for_memory",
            reason="reviewed_non_durable_source",
            deleted=False,
            trust_class="assistant_claim",
        )
        sensitive_evidence = self._mark_capture_as_recovered_legacy(
            sensitive_source,
            disposition="not_for_memory",
            reason="sensitive_input",
            deleted=False,
        )
        with sqlite3.connect(self.db_path) as conn:
            before = conn.execute(
                """
                SELECT evidence_id, content_sha256, evidence_domain, scope_mode,
                       admission_state, admission_reason
                FROM agent_memory_evidence
                WHERE evidence_id IN (?, ?, ?)
                ORDER BY evidence_id
                """,
                (eligible_evidence, assistant_evidence, sensitive_evidence),
            ).fetchall()
            input_before = conn.execute(
                "SELECT id, committed_text FROM input_events ORDER BY id"
            ).fetchall()

        first = prepare_atom_first_historical_recuration(
            self.db_path,
            project=PROJECT,
            reset_run_id="historical-reset:promotion-test",
        )

        self.assertTrue(first["ok"])
        self.assertFalse(first["legacyEvidenceMutated"])
        promotion = first["historicalPromotion"]
        self.assertEqual(promotion["createdPromotedEvidenceCount"], 1)
        self.assertEqual(promotion["skippedSensitiveEvidenceCount"], 1)
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            after = conn.execute(
                """
                SELECT evidence_id, content_sha256, evidence_domain, scope_mode,
                       admission_state, admission_reason
                FROM agent_memory_evidence
                WHERE evidence_id IN (?, ?, ?)
                ORDER BY evidence_id
                """,
                (eligible_evidence, assistant_evidence, sensitive_evidence),
            ).fetchall()
            input_after = conn.execute(
                "SELECT id, committed_text FROM input_events ORDER BY id"
            ).fetchall()
            promoted = conn.execute(
                """
                SELECT evidence.*
                FROM memory_evidence_historical_promotion_receipts AS promotion
                JOIN agent_memory_evidence AS evidence
                  ON evidence.evidence_id = promotion.promoted_evidence_id
                WHERE promotion.legacy_evidence_id = ?
                """,
                (eligible_evidence,),
            ).fetchone()
            receipt_count = int(
                conn.execute(
                    "SELECT COUNT(*) FROM memory_evidence_historical_promotion_receipts"
                ).fetchone()[0]
            )
            curatable_count = int(
                conn.execute(
                    f"""
                    SELECT COUNT(*) FROM agent_memory_evidence AS evidence
                    WHERE {curatable_personal_evidence_sql('evidence')}
                    """
                ).fetchone()[0]
            )
        self.assertEqual([tuple(row) for row in after], [tuple(row) for row in before])
        self.assertEqual([tuple(row) for row in input_after], [tuple(row) for row in input_before])
        self.assertIsNotNone(promoted)
        self.assertEqual(str(promoted["admission_state"]), "candidate")
        self.assertEqual(str(promoted["boundary_kind"]), "historical_reconstruction")
        self.assertEqual(receipt_count, 1)
        self.assertEqual(curatable_count, 1)

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            transition_evidence_admission(
                conn,
                str(promoted["evidence_id"]),
                new_state="admitted",
                reason_code="verified_durable_history",
                actor_kind="luna",
                run_id="historical-curation:test",
                created_at_ms=self._ms(2026, 7, 17, 13),
            )
            conn.commit()
        second = prepare_atom_first_historical_recuration(
            self.db_path,
            project=PROJECT,
            reset_run_id="historical-reset:promotion-test-2",
        )
        self.assertEqual(
            second["historicalPromotion"]["createdPromotedEvidenceCount"], 0
        )
        self.assertEqual(
            second["historicalPromotion"]["reusedPromotedEvidenceCount"], 1
        )
        with sqlite3.connect(self.db_path) as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM memory_evidence_historical_promotion_receipts"
                ).fetchone()[0],
                1,
            )
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    """
                    UPDATE memory_evidence_historical_promotion_receipts
                    SET authorization_run_id = 'changed'
                    """
                )

    def test_resume_verifies_reset_without_reopening_decided_evidence(self) -> None:
        self._capture(
            text="输入法继续由 Rime 解码，长期记忆只提供辅助候选。",
            created_at_ms=self._ms(2026, 7, 17, 10),
        )
        source_db = Path(self.tmp.name) / "recovery-source.sqlite"
        with sqlite3.connect(self.db_path) as source_conn, sqlite3.connect(
            source_db
        ) as destination_conn:
            source_conn.backup(destination_conn)

        reset_run_id = "historical-reset:resume-test"
        prepared = prepare_atom_first_historical_recuration(
            self.db_path,
            project=PROJECT,
            reset_run_id=reset_run_id,
        )
        self.assertTrue(prepared["ok"])
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            promoted_id = str(
                conn.execute(
                    "SELECT evidence_id FROM agent_memory_evidence "
                    "WHERE scope_mode = 'authoritative' "
                    "AND evidence_domain = 'personal_memory'"
                ).fetchone()[0]
            )
            transition_evidence_admission(
                conn,
                promoted_id,
                new_state="admitted",
                reason_code="verified_durable_history",
                actor_kind="luna",
                run_id="historical-curation:accepted-batch",
                created_at_ms=self._ms(2026, 7, 17, 11),
            )
            conn.commit()

        resumed = resume_atom_first_historical_recuration(
            self.db_path,
            source_db_path=source_db,
            project=PROJECT,
            reset_run_id=reset_run_id,
        )

        self.assertTrue(resumed["ok"])
        self.assertTrue(resumed["resumed"])
        self.assertTrue(resumed["sourceImmutableStateMatched"])
        with sqlite3.connect(self.db_path) as conn:
            state = str(
                conn.execute(
                    "SELECT admission_state FROM agent_memory_evidence "
                    "WHERE evidence_id = ?",
                    (promoted_id,),
                ).fetchone()[0]
            )
        self.assertEqual(state, "admitted")

    def test_resume_accepts_retried_rejections_when_latest_receipt_restores_them(self) -> None:
        self._capture(
            text="这条重复输入不应形成长期记忆。",
            created_at_ms=self._ms(2026, 7, 17, 10),
        )
        source_db = Path(self.tmp.name) / "recovery-source-retry.sqlite"
        with sqlite3.connect(self.db_path) as source_conn, sqlite3.connect(
            source_db
        ) as destination_conn:
            source_conn.backup(destination_conn)
        reset_run_id = "historical-reset:retry-test"
        reset_at_ms = self._ms(2026, 7, 17, 11)
        with patch(
            "rag_ime.historical_memory_curation.now_ms",
            return_value=reset_at_ms,
        ):
            prepare_atom_first_historical_recuration(
                self.db_path,
                project=PROJECT,
                reset_run_id=reset_run_id,
            )
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            evidence_id = str(
                conn.execute(
                    "SELECT evidence_id FROM agent_memory_evidence "
                    "WHERE scope_mode = 'authoritative'"
                ).fetchone()[0]
            )
            transition_evidence_admission(
                conn,
                evidence_id,
                new_state="rejected",
                reason_code="duplicate_repeated_input",
                actor_kind="rule",
                run_id="historical-curation:failed-attempt",
                created_at_ms=reset_at_ms + 1,
            )
            conn.commit()
        with patch(
            "rag_ime.historical_memory_curation.now_ms",
            return_value=reset_at_ms + 2,
        ):
            prepare_atom_first_historical_recuration(
                self.db_path,
                project=PROJECT,
                reset_run_id=reset_run_id,
            )
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            transition_evidence_admission(
                conn,
                evidence_id,
                new_state="rejected",
                reason_code="duplicate_repeated_input",
                actor_kind="rule",
                run_id="historical-curation:restored-attempt",
                created_at_ms=reset_at_ms + 3,
            )
            conn.commit()

        resumed = resume_atom_first_historical_recuration(
            self.db_path,
            source_db_path=source_db,
            project=PROJECT,
            reset_run_id=reset_run_id,
        )

        self.assertEqual(resumed["eligibleEvidenceCount"], 1)
        self.assertEqual(resumed["resetReceiptCount"], 2)
        self.assertEqual(resumed["duplicateResetEvidenceCount"], 1)
        self.assertEqual(resumed["recoveredRetryEvidenceCount"], 1)

    def test_resume_rejects_retry_that_reopened_admitted_evidence(self) -> None:
        self._capture(
            text="这个长期约束已经通过审阅。",
            created_at_ms=self._ms(2026, 7, 17, 10),
        )
        source_db = Path(self.tmp.name) / "recovery-source-admitted.sqlite"
        with sqlite3.connect(self.db_path) as source_conn, sqlite3.connect(
            source_db
        ) as destination_conn:
            source_conn.backup(destination_conn)
        reset_run_id = "historical-reset:admitted-retry-test"
        reset_at_ms = self._ms(2026, 7, 17, 11)
        with patch(
            "rag_ime.historical_memory_curation.now_ms",
            return_value=reset_at_ms,
        ):
            prepare_atom_first_historical_recuration(
                self.db_path,
                project=PROJECT,
                reset_run_id=reset_run_id,
            )
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            evidence_id = str(
                conn.execute(
                    "SELECT evidence_id FROM agent_memory_evidence "
                    "WHERE scope_mode = 'authoritative'"
                ).fetchone()[0]
            )
            transition_evidence_admission(
                conn,
                evidence_id,
                new_state="admitted",
                reason_code="atom_create",
                actor_kind="luna",
                run_id="historical-curation:accepted-attempt",
                created_at_ms=reset_at_ms + 1,
            )
            conn.commit()
        with patch(
            "rag_ime.historical_memory_curation.now_ms",
            return_value=reset_at_ms + 2,
        ):
            prepare_atom_first_historical_recuration(
                self.db_path,
                project=PROJECT,
                reset_run_id=reset_run_id,
            )

        with self.assertRaisesRegex(
            HistoricalMemoryCurationError,
            "reopened an already admitted Evidence",
        ):
            resume_atom_first_historical_recuration(
                self.db_path,
                source_db_path=source_db,
                project=PROJECT,
                reset_run_id=reset_run_id,
            )

    def _mark_capture_as_recovered_legacy(
        self,
        source_id: str,
        *,
        disposition: str,
        reason: str,
        deleted: bool,
        trust_class: str = "user_claim",
    ) -> str:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            source = conn.execute(
                "SELECT input_event_id FROM agent_memory_sources WHERE source_id = ?",
                (source_id,),
            ).fetchone()
            assert source is not None
            event_id = int(source["input_event_id"])
            evidence = conn.execute(
                """
                SELECT evidence.evidence_id
                FROM agent_memory_evidence AS evidence
                JOIN memory_evidence_input_event_links AS source_link
                  ON source_link.evidence_id = evidence.evidence_id
                 AND source_link.relation = 'source'
                WHERE source_link.input_event_id = ?
                """,
                (event_id,),
            ).fetchone()
            assert evidence is not None
            evidence_id = str(evidence["evidence_id"])
            conn.execute(
                """
                UPDATE agent_memory_sources
                SET disposition = ?, disposition_reason = ?,
                    trust_class = ?, knowledge_domain = 'legacy',
                    scope_kind = 'legacy', scope_id = '', visibility = 'legacy',
                    authorization_revision = '', binding_id = '',
                    scope_mode = 'legacy'
                WHERE source_id = ?
                """,
                (disposition, reason, trust_class, source_id),
            )
            conn.execute(
                """
                UPDATE agent_memory_evidence
                SET source_id = ?, knowledge_domain = 'legacy',
                    scope_kind = 'legacy', scope_id = '', visibility = 'legacy',
                    authorization_revision = '', binding_id = '',
                    scope_mode = 'legacy', evidence_domain = 'audit_context',
                    origin_kind = 'legacy_untyped_input',
                    admission_state = 'rejected', admission_reason = ?,
                    trust_class = ?, boundary_kind = ''
                WHERE evidence_id = ?
                """,
                (source_id, reason, trust_class, evidence_id),
            )
            conn.execute(
                "UPDATE memory_state SET deleted = ? WHERE event_id = ?",
                (int(deleted), event_id),
            )
            conn.commit()
        return evidence_id

    def _capture(self, *, text: str, created_at_ms: int) -> str:
        self.capture_ordinal += 1
        ordinal = self.capture_ordinal
        metadata = {
            "schemaVersion": "rag-ime.input-capture.v2",
            "captureId": f"capture:history:{ordinal}",
            "transactionId": f"transaction:history:{ordinal}",
            "sequence": ordinal,
            "channel": "input_method",
            "boundaryKind": "host_return",
            "boundaryConfidence": "strong",
            "nativeCompositionBefore": False,
            "rimeHandled": False,
            "hostForwarded": True,
            "modifiedReturn": False,
            "finalCommitted": True,
            "controllerEpoch": 1,
            "focusEpoch": 1,
            "appBundleId": "com.apple.TextEdit",
            "fieldIdentitySha256": hashlib.sha256(b"history-field").hexdigest(),
            "privacyRevision": "foreground-privacy.v1",
            "occurredStartMs": created_at_ms,
            "occurredEndMs": created_at_ms + 20,
            "contentSha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "captureSource": "text_input_client",
            "fallbackReason": "",
            "fieldContextChars": len(text),
            "imeBufferChars": len(text),
            "selectionRule": "final_committed_segment",
        }
        event_ref, _receipt = self.core.record_event_with_capture_receipt(
            InputEvent(
                event_id=None,
                created_at_ms=created_at_ms,
                source="squirrel_input_segment",
                committed_text=text,
                privacy_disposition="allowed",
                app="com.apple.TextEdit",
                project=PROJECT,
                capture_metadata=metadata,
            )
        )
        return f"input-memory:{event_ref.removeprefix('event:')}"

    @staticmethod
    def _ms(year: int, month: int, day: int, hour: int) -> int:
        return int(
            datetime(
                year,
                month,
                day,
                hour,
                tzinfo=ZoneInfo("Asia/Shanghai"),
            ).timestamp()
            * 1000
        )


if __name__ == "__main__":
    unittest.main()
