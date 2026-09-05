from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from rag_ime.agent_memory_sources import AgentMemorySourceStore
from rag_ime.agent_sessions import AgentSessionStore
from rag_ime.personal_context import AgentMemoryEvidenceStore


class AgentMemorySourceStoreTests(unittest.TestCase):
    def test_short_selection_is_bound_to_exact_same_session_question(self):
        from rag_ime.owner_memory_curation import _build_owner_source_bundle, _deterministic_personal_v2_disposition
        from rag_ime.memory_curation import build_memory_curation_model_bundle
        from rag_ime.memory_evidence_admission import (
            curatable_personal_evidence_sql, evidence_is_admitted, transition_evidence_admission,
        )

        evidence = AgentMemoryEvidenceStore(self.db_path, project="wisdom-weasel-rag-ime")
        evidence.initialize()
        question = evidence.record_assistant_message(session_id=str(self.session["id"]),
            pi_entry_id="question:style", turn_id="turn:question", role_id="",
            text="本次项目界面暂用哪种风格？ A. 深色界面 B. 浅色界面（推荐），发布另行决定。", occurred_at_ms=100)
        result = self.store.checkpoint_user_message(session_id=str(self.session["id"]),
            pi_entry_id="answer:style", turn_id="turn:answer", text="推荐后者", created_at_ms=200)
        context = result["source"]["metadata"]["decisionContext"]
        self.assertEqual(context["questionEvidenceId"], question["evidence"]["evidenceId"])
        self.assertEqual(context["answerEntryId"], "answer:style")
        self.assertEqual(context["answerText"], "推荐后者")
        selected_options = ["浅色界面，发布另行决定。"]
        self.assertEqual(context["selectedOptions"], selected_options)
        self.assertEqual(context["scope"], "this_question_only")
        captured = self.store.capture_hint(session_id=str(self.session["id"]), source_id=result["source"]["sourceId"],
            kind="decision", claim="本次项目界面选择浅色界面。", scope="user",
            basis="explicit_user_statement", future_use="恢复用户对该界面方案的选择。", created_at_ms=201)
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            bundle = _build_owner_source_bundle(conn, owner_kind="user", owner_id="default",
                project="wisdom-weasel-rag-ime", limit=10, canonical_personal=True)
        candidate = bundle["inputs"][0]
        self.assertEqual(candidate["text"], "推荐后者")
        self.assertIsNone(_deterministic_personal_v2_disposition(candidate))
        self.assertEqual(candidate["decisionContext"]["selectedOptions"], selected_options)
        model = build_memory_curation_model_bundle({"recentEvents": [{**candidate, "eventId": candidate["sourceEventIds"][0]}]})
        self.assertEqual(model["inputs"][0]["decisionContext"]["selectedOptions"], selected_options)
        # A subsequently backfilled question must never rebind an already
        # checkpointed answer to different options.
        evidence.record_assistant_message(session_id=str(self.session["id"]), role_id="",
            pi_entry_id="question:backfilled", text="发布到哪里？ A. 测试环境 B. 生产环境（推荐）",
            occurred_at_ms=150)
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            replay = _build_owner_source_bundle(conn, owner_kind="user", owner_id="default",
                project="wisdom-weasel-rag-ime", limit=10, canonical_personal=True)
        self.assertIsNone(replay["inputs"][0]["decisionContext"])
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            transition_evidence_admission(conn, captured["evidenceId"], new_state="admitted",
                reason_code="verified_question_selection", actor_kind="luna", created_at_ms=300)
            self.assertTrue(evidence_is_admitted(conn, captured["evidenceId"]))
            conn.execute("UPDATE agent_memory_evidence SET admission_state = 'forgotten' WHERE evidence_id = ?",
                         (context["questionEvidenceId"],))
            self.assertFalse(evidence_is_admitted(conn, captured["evidenceId"]))
            self.assertIsNone(conn.execute(f"""SELECT 1 FROM agent_memory_evidence AS evidence
                WHERE evidence.evidence_id = ? AND {curatable_personal_evidence_sql()}""",
                (captured["evidenceId"],)).fetchone())

    def test_selection_does_not_cross_project_session_or_intervening_user_message(self):
        from rag_ime.memory_decision_context import resolve_decision_context

        session_id = str(self.session["id"])
        question_text = "本次界面采用哪种风格？ A. 深色界面 B. 浅色界面（推荐）"
        for index, (project, question_session, intervening) in enumerate([
            ("", session_id, False),
            ("wisdom-weasel-rag-ime", "another-session", False),
            ("wisdom-weasel-rag-ime", session_id, True),
        ]):
            with self.subTest(index=index):
                evidence = AgentMemoryEvidenceStore(self.db_path, project=project)
                evidence.record_assistant_message(session_id=question_session, role_id="",
                    pi_entry_id=f"question:boundary:{index}", text=question_text, occurred_at_ms=100 + index * 100)
                if intervening:
                    self.store.checkpoint_user_message(session_id=session_id, pi_entry_id="user:intervening",
                        turn_id="turn:intervening", text="先处理检索失败的问题。", created_at_ms=325)
                with closing(sqlite3.connect(self.db_path)) as conn:
                    conn.row_factory = sqlite3.Row
                    self.assertIsNone(resolve_decision_context(conn, session_id=session_id,
                        project="wisdom-weasel-rag-ime", answer_entry_id=f"answer:boundary:{index}",
                        answer_text="推荐后者", occurred_at_ms=150 + index * 100))

    def test_ambiguous_quoted_and_unrelated_confirmations_are_not_bound(self):
        evidence = AgentMemoryEvidenceStore(self.db_path, project="wisdom-weasel-rag-ime")
        evidence.initialize()
        for index, (question, answer) in enumerate([
            ("项目采用哪种风格？ A. 深色界面 B. 浅色界面", "全部推荐"),
            ("> 项目采用哪种风格？ A. 深色界面 B. 浅色界面（推荐）", "推荐后者"),
            ("你已经完成了两项工作。", "推荐后者"),
            ("缓存选好了吗？界面采用哪种风格？ A. 深色界面 B. 浅色界面（推荐）", "全部推荐"),
            ("界面采用哪种风格？ A. 深色界面 B. 浅色界面 C. 系统主题", "推荐后者"),
        ]):
            with self.subTest(index=index):
                evidence.record_assistant_message(session_id=str(self.session["id"]),
                    pi_entry_id=f"question:{index}", role_id="", text=question, occurred_at_ms=100 + index * 100)
                result = self.store.checkpoint_user_message(session_id=str(self.session["id"]),
                    pi_entry_id=f"answer:{index}", turn_id=f"turn:{index}", text=answer,
                    created_at_ms=150 + index * 100)
                self.assertNotIn("decisionContext", result["source"]["metadata"])

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-agent-memory-")
        self.db_path = Path(self.tmp.name) / "rag-ime.sqlite"
        self.sessions = AgentSessionStore(self.db_path)
        self.sessions.initialize()
        self.session = self.sessions.create(title="记忆检查点", created_at_ms=1)
        self.store = AgentMemorySourceStore(self.db_path, project="wisdom-weasel-rag-ime")
        self.store.initialize()
        self.evidence = AgentMemoryEvidenceStore(
            self.db_path,
            project="wisdom-weasel-rag-ime",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_final_user_message_is_idempotent_and_does_not_touch_phrase_frequency(self) -> None:
        first = self.store.checkpoint_user_message(
            session_id=str(self.session["id"]),
            pi_entry_id="pi-entry:user:1",
            turn_id="turn:1",
            text="把 Pi 的普通生成和深度检索分开",
            created_at_ms=100,
        )
        duplicate = self.store.checkpoint_user_message(
            session_id=str(self.session["id"]),
            pi_entry_id="pi-entry:user:1",
            turn_id="turn:1",
            text="把 Pi 的普通生成和深度检索分开",
            created_at_ms=200,
        )

        self.assertTrue(first["stored"])
        self.assertEqual(duplicate["status"], "already_checkpointed")
        self.assertEqual(first["source"]["sourceRole"], "user")
        self.assertEqual(first["source"]["sourceKind"], "user_final")
        self.assertEqual(
            (first["source"]["ownerKind"], first["source"]["ownerId"]),
            ("user", "default"),
        )
        self.assertEqual(first["source"]["disposition"], "pending")
        with closing(sqlite3.connect(self.db_path)) as conn:
            event = conn.execute(
                "SELECT source, committed_text, project FROM input_events WHERE id = ?",
                (first["source"]["inputEventId"],),
            ).fetchone()
            phrase_count = conn.execute("SELECT COUNT(*) FROM phrase_stats").fetchone()[0]
            raw = conn.execute(
                "SELECT kind, status FROM memory_items WHERE source_event_id = ?",
                (first["source"]["inputEventId"],),
            ).fetchone()
        self.assertEqual(event, ("pi_agent_user", "把 Pi 的普通生成和深度检索分开", "wisdom-weasel-rag-ime"))
        self.assertEqual(phrase_count, 0)
        self.assertEqual(raw, ("raw_event", "hidden"))

    def test_sensitive_message_and_unapplied_receipt_never_create_source_events(self) -> None:
        sensitive = self.store.checkpoint_user_message(
            session_id=str(self.session["id"]),
            pi_entry_id="pi-entry:sensitive",
            turn_id="turn:sensitive",
            text="API key=sk-super-secret-value",
        )
        unapplied = self.store.checkpoint_tool_receipt(
            {
                "approvalId": "approval:rejected",
                "sessionId": self.session["id"],
                "state": "rejected",
                "receipt": {"mutationApplied": False, "summary": "没有执行"},
            }
        )

        self.assertEqual(sensitive["status"], "skipped_sensitive")
        self.assertEqual(unapplied["status"], "skipped_unapplied")
        with closing(sqlite3.connect(self.db_path)) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM input_events").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM agent_memory_sources").fetchone()[0], 0)

    def test_memory_workflow_instruction_never_creates_source_events(self) -> None:
        result = self.store.checkpoint_user_message(
            session_id=str(self.session["id"]),
            pi_entry_id="pi-entry:memory-workflow",
            turn_id="turn:memory-workflow",
            text=(
                "请调用 memory Tool 的 curation_prepare 操作，"
                "只生成可审阅草案并返回 runId。"
            ),
        )

        self.assertEqual(
            result["status"],
            "skipped_memory_workflow_instruction",
        )
        with closing(sqlite3.connect(self.db_path)) as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM input_events").fetchone()[0],
                0,
            )
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM agent_memory_sources"
                ).fetchone()[0],
                0,
            )

    def test_capture_hint_binds_current_user_source_without_creating_an_atom(self) -> None:
        source = self.store.checkpoint_user_message(
            session_id=str(self.session["id"]),
            pi_entry_id="pi-entry:capture",
            turn_id="turn:capture",
            text="以后默认给我聚合报告，不要输出原始隐私文本。",
            created_at_ms=300,
        )["source"]

        result = self.store.capture_hint(
            session_id=str(self.session["id"]),
            kind="preference",
            claim="用户偏好只查看聚合报告。",
            scope="user",
            basis="explicit_user_statement",
            future_use="这会改变未来报告的默认输出方式。",
            created_at_ms=301,
        )

        self.assertTrue(result["captured"])
        self.assertEqual(result["candidate"], "accepted")
        self.assertFalse(result["createsAtom"])
        self.assertFalse(result["createsDurableMemory"])
        self.assertFalse(result["requiresApproval"])
        self.assertEqual(result["sourceId"], source["sourceId"])
        self.assertEqual(result["evidenceState"], "candidate")
        with closing(sqlite3.connect(self.db_path)) as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM memory_capture_hints").fetchone()[0],
                1,
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM memory_atoms").fetchone()[0],
                0,
            )
            self.assertEqual(
                conn.execute(
                    """
                    SELECT evidence_domain, origin_kind, admission_state
                    FROM agent_memory_evidence WHERE evidence_id = ?
                    """,
                    (result["evidenceId"],),
                ).fetchone(),
                ("personal_memory", "explicit_user_memory", "candidate"),
            )

    def test_project_capture_is_audited_but_not_personal_memory(self) -> None:
        self.store.checkpoint_user_message(
            session_id=str(self.session["id"]),
            pi_entry_id="pi-entry:project-capture",
            turn_id="turn:project-capture",
            text="这个项目使用统一的发布门禁。",
            created_at_ms=350,
        )

        result = self.store.capture_hint(
            session_id=str(self.session["id"]),
            kind="decision",
            claim="项目使用统一发布门禁。",
            scope="project",
            basis="explicit_user_statement",
            future_use="仅用于当前项目交付。",
            created_at_ms=351,
        )

        self.assertEqual(result["evidenceState"], "rejected")
        with closing(sqlite3.connect(self.db_path)) as conn:
            self.assertEqual(
                conn.execute(
                    """
                    SELECT evidence_domain, admission_state, admission_reason,
                           scope_mode
                    FROM agent_memory_evidence WHERE evidence_id = ?
                    """,
                    (result["evidenceId"],),
                ).fetchone(),
                (
                    "audit_context",
                    "rejected",
                    "project_scope_not_personal_memory",
                    "quarantined",
                ),
            )

    def test_capture_hint_rejects_workflow_prompt(self) -> None:
        self.store.checkpoint_user_message(
            session_id=str(self.session["id"]),
            pi_entry_id="pi-entry:capture-noise",
            turn_id="turn:capture-noise",
            text="以后保留稳定偏好。",
        )

        with self.assertRaisesRegex(ValueError, "workflow noise"):
            self.store.capture_hint(
                session_id=str(self.session["id"]),
                kind="fact",
                claim="请调用 memory curation_prepare 并返回 runId。",
                scope="project",
                basis="explicit_user_statement",
                future_use="准备记忆流程。",
            )

    def test_capture_hint_accepts_current_user_evidence_but_rejects_assistant_evidence(
        self,
    ) -> None:
        self.store.checkpoint_user_message(
            session_id=str(self.session["id"]),
            pi_entry_id="pi-entry:capture-evidence",
            turn_id="turn:capture-evidence",
            text="以后默认先给结论。",
            created_at_ms=400,
        )
        user_evidence = self.evidence.record_user_message(
            session_id=str(self.session["id"]),
            pi_entry_id="pi-entry:capture-evidence",
            turn_id="turn:capture-evidence",
            role_id=str(self.session["roleId"]),
            text="以后默认先给结论。",
            occurred_at_ms=400,
        )["evidence"]
        assistant_evidence = self.evidence.record_assistant_message(
            session_id=str(self.session["id"]),
            pi_entry_id="pi-entry:assistant-evidence",
            turn_id="turn:capture-evidence",
            role_id=str(self.session["roleId"]),
            text="我以后会先给结论。",
            occurred_at_ms=401,
        )["evidence"]
        tool_evidence = self.evidence.record_tool_receipt(
            receipt_id="receipt:verified-answer-structure",
            text="已应用默认先给结论的回答结构。",
            session_id=str(self.session["id"]),
            role_id=str(self.session["roleId"]),
            applied=True,
            occurred_at_ms=401,
        )["evidence"]

        accepted = self.store.capture_hint(
            session_id=str(self.session["id"]),
            kind="preference",
            claim="用户偏好先看结论。",
            scope="user",
            basis="explicit_user_statement",
            future_use="会改变未来回答结构。",
            evidence_ids=[str(user_evidence["evidenceId"])],
            created_at_ms=402,
        )
        self.assertTrue(accepted["captured"])

        verified = self.store.capture_hint(
            session_id=str(self.session["id"]),
            kind="preference",
            claim="用户偏好并已启用先给结论的回答结构。",
            scope="user",
            basis="verified_outcome",
            future_use="未来回答继续沿用已验证的结构。",
            evidence_ids=[str(tool_evidence["evidenceId"])],
            created_at_ms=403,
        )
        self.assertTrue(verified["captured"])

        with self.assertRaisesRegex(ValueError, "missing or outside this session"):
            self.store.capture_hint(
                session_id=str(self.session["id"]),
                kind="preference",
                claim="助手承诺先给结论。",
                scope="user",
                basis="verified_outcome",
                future_use="助手自述不能成为用户记忆证据。",
                evidence_ids=[str(assistant_evidence["evidenceId"])],
                created_at_ms=404,
            )

    def test_transient_subagent_input_and_compaction_never_become_role_memory(self) -> None:
        child = self.sessions.create(
            title="临时研究子 Agent",
            role_id="companion-present-v1",
            session_kind="subagent_runtime",
            created_at_ms=250,
        )

        user = self.store.checkpoint_user_message(
            session_id=str(child["id"]),
            pi_entry_id="pi-entry:delegated-task",
            turn_id="turn:delegated-task",
            text="请临时检查这段实现",
            created_at_ms=251,
        )
        compaction = self.store.checkpoint_compaction(
            session_id=str(child["id"]),
            result={"summary": "临时子任务认为需要调整实现。"},
            trigger="automatic",
            created_at_ms=252,
        )

        self.assertEqual(user["status"], "skipped_transient_session")
        self.assertEqual(compaction["status"], "skipped_transient_session")
        with closing(sqlite3.connect(self.db_path)) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM input_events").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM agent_memory_sources").fetchone()[0], 0)

    def test_only_applied_tool_receipt_is_checkpointed(self) -> None:
        result = self.store.checkpoint_tool_receipt(
            {
                "approvalId": "approval:applied",
                "sessionId": self.session["id"],
                "state": "applied",
                "receipt": {
                    "mutationApplied": True,
                    "summary": "已将《接入 Pi》标记为已完成",
                },
            },
            created_at_ms=300,
        )

        self.assertTrue(result["stored"])
        self.assertEqual(result["source"]["sourceRole"], "tool_receipt")
        self.assertEqual(result["source"]["sourceKind"], "tool_receipt")
        self.assertEqual(
            (result["source"]["ownerKind"], result["source"]["ownerId"]),
            ("shared", "wisdom-weasel-rag-ime"),
        )
        listed = self.store.list_for_session(str(self.session["id"]))
        self.assertEqual([item["sourceId"] for item in listed], [result["source"]["sourceId"]])
        self.assertNotIn("evidence", result)

        personal = self.store.checkpoint_tool_receipt(
            {
                "approvalId": "approval:personal-memory",
                "sessionId": self.session["id"],
                "state": "applied",
                "receipt": {
                    "mutationApplied": True,
                    "personalMemoryEligible": True,
                    "summary": "用户已验证默认只显示聚合后的隐私安全报告。",
                },
            },
            created_at_ms=301,
        )
        self.assertEqual(personal["evidence"]["admissionState"], "candidate")
        with closing(sqlite3.connect(self.db_path)) as conn:
            self.assertEqual(
                conn.execute(
                    """
                    SELECT evidence_domain, origin_kind, admission_state
                    FROM agent_memory_evidence WHERE evidence_id = ?
                    """,
                    (personal["evidence"]["evidenceId"],),
                ).fetchone(),
                ("personal_memory", "applied_personal_receipt", "candidate"),
            )

    def test_document_knowledge_receipt_cannot_opt_into_personal_memory(self) -> None:
        result = self.store.checkpoint_tool_receipt(
            {
                "approvalId": "approval:knowledge-import",
                "sessionId": self.session["id"],
                "toolId": "knowledge",
                "state": "applied",
                "receipt": {
                    "mutationApplied": True,
                    "memoryDomain": "document_knowledge",
                    # Defense-in-depth: even an erroneous worker field cannot
                    # cross the Knowledge -> personal Memory boundary.
                    "personalMemoryEligible": True,
                    "summary": "已导入公开企业手册到文档知识库。",
                },
            },
            created_at_ms=302,
        )

        self.assertTrue(result["stored"])
        self.assertNotIn("evidence", result)
        self.assertFalse(result["source"]["metadata"]["personalMemoryEligible"])
        self.assertEqual(
            result["source"]["metadata"]["personalMemoryExclusionReason"],
            "document_knowledge_boundary",
        )
        with closing(sqlite3.connect(self.db_path)) as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM agent_memory_evidence"
                ).fetchone()[0],
                0,
            )

    def test_compaction_summary_is_role_owned_and_idempotent(self) -> None:
        first = self.store.checkpoint_compaction(
            session_id=str(self.session["id"]),
            result={
                "summary": "用户决定把桌面感知改为 Accessibility Tree，并保留截图兜底。",
                "firstKeptEntryId": "pi-entry:user:9",
                "tokensBefore": 12_000,
                "estimatedTokensAfter": 2_400,
            },
            trigger="automatic",
            created_at_ms=400,
        )
        duplicate = self.store.checkpoint_compaction(
            session_id=str(self.session["id"]),
            result={
                "summary": "用户决定把桌面感知改为 Accessibility Tree，并保留截图兜底。",
                "firstKeptEntryId": "pi-entry:user:9",
                "tokensBefore": 12_000,
                "estimatedTokensAfter": 2_400,
            },
            trigger="manual",
            created_at_ms=500,
        )

        self.assertTrue(first["stored"])
        self.assertEqual(duplicate["status"], "already_checkpointed")
        source = first["source"]
        self.assertEqual(source["sourceKind"], "session_compaction")
        self.assertEqual(source["trustClass"], "session_summary")
        self.assertEqual(
            (source["ownerKind"], source["ownerId"]),
            ("agent", self.session["roleId"]),
        )
        self.assertEqual(source["coverageEndEntryId"], "pi-entry:user:9")
        self.assertTrue(source["metadata"]["coverageEndExclusive"])

    def test_not_for_memory_is_reversible_and_audited(self) -> None:
        checkpoint = self.store.checkpoint_user_message(
            session_id=str(self.session["id"]),
            pi_entry_id="pi-entry:noise",
            turn_id="turn:noise",
            text="嗯嗯那个这个测试一下",
            created_at_ms=600,
        )
        source_id = str(checkpoint["source"]["sourceId"])

        forgotten = self.store.set_disposition(
            source_id,
            disposition="not_for_memory",
            reason_code="input_noise_filler",
            actor_kind="rule",
            run_id="curation:1",
            created_at_ms=700,
        )
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute(
                """
                INSERT INTO memory_curation_cursors(
                    owner_kind, owner_id, project, lane,
                    last_source_created_at_ms, last_source_id, next_due_at_ms,
                    status, updated_at_ms
                ) VALUES (
                    'user', 'default', 'wisdom-weasel-rag-ime', 'daily',
                    600, ?, 999999, 'idle', 700
                )
                """,
                (source_id,),
            )
        restored = self.store.set_disposition(
            source_id,
            disposition="pending",
            reason_code="user_restored",
            actor_kind="rollback",
            run_id="curation:rollback:1",
            created_at_ms=800,
        )

        self.assertEqual(forgotten["source"]["disposition"], "not_for_memory")
        self.assertEqual(restored["source"]["disposition"], "pending")
        with closing(sqlite3.connect(self.db_path)) as conn:
            cursor = conn.execute(
                """
                SELECT last_source_created_at_ms, last_source_id, next_due_at_ms
                FROM memory_curation_cursors
                WHERE owner_kind = 'user' AND owner_id = 'default'
                """
            ).fetchone()
            transitions = conn.execute(
                """
                SELECT previous_disposition, new_disposition, reason_code, actor_kind
                FROM memory_source_disposition_events
                WHERE source_id = ?
                ORDER BY created_at_ms
                """,
                (source_id,),
            ).fetchall()
        self.assertEqual(cursor, (0, "", 0))
        self.assertEqual(
            transitions,
            [
                ("", "pending", "checkpoint_created", "system"),
                ("pending", "not_for_memory", "input_noise_filler", "rule"),
                ("not_for_memory", "pending", "user_restored", "rollback"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
