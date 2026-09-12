from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

from rag_ime.local_sqlite_core import LocalSqliteCoreClient
from rag_ime.memory_book_compiler import (
    apply_memory_book_plan,
    apply_stored_memory_book_run,
    build_memory_book_source_bundle,
    memory_book_plan_from_compile_output,
    memory_compile_due,
    memory_compile_state,
    inspect_memory_book_plan,
    store_memory_book_plan,
    rollback_memory_book_run,
)
from rag_ime.models import InputEvent
from rag_ime.text_utils import now_ms


class MemoryCompileStateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-compile-state-")
        self.db_path = Path(self.tmp.name) / "rag-ime.sqlite"
        self.core = LocalSqliteCoreClient(self.db_path)
        self.core.initialize()
        self.capture_ordinal = 0

    def tearDown(self) -> None:
        self.tmp.cleanup()

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def test_apply_advances_incremental_cursor_and_next_bundle_only_reads_new_events(self) -> None:
        first_id = int(self.core.record_event(self._event("完成真实前台闭环", "doc:a")).split(":", 1)[1])
        with self._connect() as conn:
            bundle = build_memory_book_source_bundle(conn, project="ime")
            plan = memory_book_plan_from_compile_output(
                {
                    "phraseCandidates": [
                        {
                            "text": "完成前台闭环",
                            "sourceEventIds": [first_id],
                            "groupId": "doc:a",
                        }
                    ]
                },
                project="ime",
                provider="deepseek",
                model="v4-flash",
                source_bundle=bundle,
            )
            apply_memory_book_plan(conn, plan)
            state = memory_compile_state(conn, project="ime")
            self.assertEqual(state["lastCompiledEventId"], first_id)
            self.assertEqual(build_memory_book_source_bundle(conn, project="ime")["recentEvents"], [])

        second_id = int(self.core.record_event(self._event("限制模型调用频率", "doc:a")).split(":", 1)[1])
        with self._connect() as conn:
            next_bundle = build_memory_book_source_bundle(conn, project="ime")
            self.assertEqual([item["eventId"] for item in next_bundle["recentEvents"]], [second_id])

    def test_invalid_apply_does_not_advance_cursor(self) -> None:
        self.core.record_event(self._event("保持普通拼音稳定", "doc:a"))
        with self._connect() as conn:
            before = memory_compile_state(conn, project="ime")
            with self.assertRaises(ValueError):
                apply_memory_book_plan(conn, {"schemaVersion": "bad", "runId": "bad", "diffs": []})
            after = memory_compile_state(conn, project="ime")
            self.assertEqual(after["lastCompiledEventId"], before["lastCompiledEventId"])

    def test_global_catalog_bundle_audits_catalog_without_consuming_pending_evidence(self) -> None:
        [
            self.core.record_event(self._event(text, "doc:a"))
            for text in (
                "第一条完整历史输入用于全库整理",
                "第二条完整历史输入用于全库整理",
                "第三条完整历史输入用于全库整理",
            )
        ]
        with self._connect() as conn:
            bundle = build_memory_book_source_bundle(
                conn,
                project="ime",
                after_event_id=0,
                limit=2,
                newest_first=True,
                curation_scope="global",
                catalog_only=True,
            )

        self.assertEqual(bundle["recentEvents"], [])
        self.assertEqual(bundle["curationScope"], "global")
        self.assertTrue(bundle["catalogAudit"])
        self.assertEqual(bundle["evidenceOrder"], "catalog_only")
        self.assertEqual(bundle["cursor"]["fromEventId"], 0)
        self.assertEqual(bundle["cursor"]["toEventId"], 0)
        self.assertEqual(bundle["cursor"]["pendingEventCount"], 3)

    def test_due_policy_supports_event_idle_daily_and_manual_triggers(self) -> None:
        self.core.record_event(self._event("保持普通拼音稳定", "doc:a"))
        with self._connect() as conn:
            self.assertEqual(memory_compile_due(conn, project="ime", manual=True)[1], "manual")
            self.assertEqual(memory_compile_due(conn, project="ime", idle_ms=20 * 60 * 1000)[1], "idle")
            due, reason, _ = memory_compile_due(conn, project="ime", current_ms=24 * 60 * 60 * 1000 + 1)
            self.assertTrue(due)
            self.assertEqual(reason, "daily")

    def test_saved_review_draft_covers_events_without_advancing_applied_cursor(self) -> None:
        first_id = int(
            self.core.record_event(self._event("自动生成草案但不直接应用", "doc:a")).split(":", 1)[1]
        )
        with self._connect() as conn:
            bundle = build_memory_book_source_bundle(conn, project="ime")
            plan = memory_book_plan_from_compile_output(
                {
                    "memoryAtoms": [
                        {
                            "canonicalText": "记忆整理只自动生成草案，不自动应用。",
                            "sourceEventIds": [first_id],
                        }
                    ],
                    "curationArchitecture": "atom-first-v1",
                    "curationOutcome": "changes",
                },
                project="ime",
                provider="deepseek",
                model="v4-flash",
                source_bundle=bundle,
            )
            store_memory_book_plan(conn, plan)
            state = memory_compile_state(conn, project="ime")
            due, reason, _ = memory_compile_due(
                conn,
                project="ime",
                idle_ms=24 * 60 * 60 * 1000,
            )

        self.assertEqual(state["lastCompiledEventId"], 0)
        self.assertEqual(state["lastDraftedEventId"], first_id)
        self.assertEqual(state["pendingEventCount"], 1)
        self.assertEqual(state["undraftedEventCount"], 0)
        self.assertTrue(state["draftCoversPending"])
        self.assertTrue(state["activeDraftPendingReview"])
        self.assertFalse(due)
        self.assertEqual(reason, "draft_pending_review")

        self.core.record_event(self._event("新增证据会进入下一份草案", "doc:a"))
        with self._connect() as conn:
            next_state = memory_compile_state(conn, project="ime")
            self.assertEqual(next_state["undraftedEventCount"], 1)
            due, reason, blocked_state = memory_compile_due(
                conn,
                project="ime",
                idle_ms=20 * 60 * 1000,
            )
            self.assertFalse(due)
            self.assertEqual(reason, "draft_pending_review")
            self.assertEqual(blocked_state["undraftedEventCount"], 1)

    def test_no_change_review_advances_cursor_without_waiting_for_approval(self) -> None:
        event_id = int(
            self.core.record_event(self._event("这个输入没有长期记忆价值", "doc:a")).split(":", 1)[1]
        )
        with self._connect() as conn:
            bundle = build_memory_book_source_bundle(conn, project="ime")
            plan = memory_book_plan_from_compile_output(
                {
                    "curationArchitecture": "atom-first-v1",
                    "curationOutcome": "no_changes",
                    "curationDiagnostics": {"ignoredDecisionCount": 1},
                },
                project="ime",
                provider="deepseek",
                model="v4-flash",
                source_bundle=bundle,
            )
            stored = store_memory_book_plan(conn, plan)
            state = memory_compile_state(conn, project="ime")

        self.assertEqual(stored["status"], "empty")
        self.assertEqual(state["lastCompiledEventId"], event_id)
        self.assertEqual(state["pendingEventCount"], 0)
        self.assertFalse(state["activeDraftPendingReview"])

    def test_review_can_exclude_every_change_and_still_complete_the_batch(self) -> None:
        event_id = int(
            self.core.record_event(self._event("候选建议可以全部排除", "doc:a")).split(":", 1)[1]
        )
        with self._connect() as conn:
            bundle = build_memory_book_source_bundle(conn, project="ime")
            plan = memory_book_plan_from_compile_output(
                {
                    "memoryAtoms": [
                        {
                            "canonicalText": "这条建议稍后由用户排除。",
                            "sourceEventIds": [event_id],
                        }
                    ],
                    "curationArchitecture": "atom-first-v1",
                    "curationOutcome": "changes",
                },
                project="ime",
                provider="deepseek",
                model="v4-flash",
                source_bundle=bundle,
            )
            draft = store_memory_book_plan(conn, plan)
            for diff in draft["diffs"]:
                conn.execute(
                    "UPDATE memory_cleanup_diffs SET status = 'rejected' WHERE id = ?",
                    (diff["diffId"],),
                )
            completed = apply_stored_memory_book_run(conn, run_id=plan["runId"])
            state = memory_compile_state(conn, project="ime")

        self.assertEqual(completed["status"], "dismissed")
        self.assertEqual(state["lastCompiledEventId"], event_id)
        self.assertEqual(state["pendingEventCount"], 0)
        self.assertFalse(state["activeDraftPendingReview"])

    def test_negative_phrase_and_supersede_apply_with_source_provenance(self) -> None:
        event_id = int(self.core.record_event(self._event("旧事实需要更新", "doc:a")).split(":", 1)[1])
        with self._connect() as conn:
            bundle = build_memory_book_source_bundle(conn, project="ime")
            plan = memory_book_plan_from_compile_output(
                {
                    "memoryAtoms": [
                        {
                            "atomId": "atom:old",
                            "claimKey": "fixture:fact.current",
                            "canonicalText": "旧事实",
                            "sourceEventIds": [event_id],
                            "groupId": "doc:a",
                        },
                        {
                            "atomId": "atom:new",
                            "claimKey": "fixture:fact.next",
                            "canonicalText": "新事实",
                            "sourceEventIds": [event_id],
                            "groupId": "doc:a",
                        },
                    ],
                    "negativePhrases": [
                        {"text": "根据上述", "sourceEventIds": [event_id]}
                    ],
                    "supersedes": [
                        {"oldId": "atom:old", "newId": "atom:new", "sourceEventIds": [event_id]}
                    ],
                },
                project="ime",
                provider="deepseek",
                model="v4-flash",
                source_bundle=bundle,
            )
            self.assertTrue(inspect_memory_book_plan(plan)["ok"])
            apply_memory_book_plan(conn, plan)
            self.assertEqual(conn.execute("SELECT status FROM memory_atoms WHERE id = 'atom:old'").fetchone()[0], "superseded")
            self.assertEqual(
                conn.execute("SELECT match_value FROM memory_candidate_suppressions WHERE match_value = '根据上述'").fetchone()[0],
                "根据上述",
            )

    def test_same_claim_key_closes_old_fact_even_when_model_omits_supersedes(self) -> None:
        event_id = int(
            self.core.record_event(
                self._event("输入法已经从 0.8B 模型切换到 100M 自训练模型", "doc:model")
            ).split(":", 1)[1]
        )

        def plan_for(
            atom_id: str,
            text: str,
            valid_from_ms: int,
            *,
            kind: str = "project_fact",
            owner_id: str = "default",
        ) -> dict[str, object]:
            return memory_book_plan_from_compile_output(
                {
                    "schemaVersion": "rag-ime.memory-book-compile.v1",
                    "memoryAtoms": [
                        {
                            "atomId": atom_id,
                            "kind": kind,
                            "claimKey": "project:rag-ime.runtime-model",
                            "canonicalText": text,
                            "sourceEventIds": [event_id],
                            "validFromMs": valid_from_ms,
                        }
                    ],
                    # This is the bug boundary: the organizer forgot to emit
                    # an explicit oldId -> newId edge.
                    "supersedes": [],
                },
                project="ime",
                provider="deepseek",
                model="v4-flash",
                owner_id=owner_id,
            )

        old_plan = plan_for("atom:model-0.8b", "输入法当前使用 Qwen 0.8B 模型。", 100)
        # The model may reclassify a fact as a decision. claimKey, not the
        # mutable category label, is the version identity.
        new_plan = plan_for(
            "atom:model-100m",
            "输入法当前使用 100M 自训练模型。",
            200,
            kind="project_decision",
        )
        with self._connect() as conn:
            apply_memory_book_plan(conn, old_plan)
            apply_memory_book_plan(conn, new_plan)

            rows = conn.execute(
                """
                SELECT id, status, claim_state, valid_from_ms, valid_to_ms, supersedes_id
                FROM memory_atoms
                WHERE claim_key = 'project:rag-ime.runtime-model'
                ORDER BY valid_from_ms
                """
            ).fetchall()
            self.assertEqual(
                [(row["id"], row["status"], row["claim_state"]) for row in rows],
                [
                    ("atom:model-0.8b", "superseded", "superseded"),
                    ("atom:model-100m", "active", "current"),
                ],
            )
            self.assertEqual(rows[0]["valid_to_ms"], 200)
            self.assertEqual(rows[1]["supersedes_id"], "atom:model-0.8b")
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM memory_supersessions "
                    "WHERE old_memory_id = 'atom:model-0.8b' "
                    "AND new_memory_id = 'atom:model-100m' AND status = 'active'"
                ).fetchone()[0],
                1,
            )

            rollback_memory_book_run(conn, run_id=str(new_plan["runId"]))
            restored = conn.execute(
                "SELECT status, claim_state, valid_to_ms FROM memory_atoms "
                "WHERE id = 'atom:model-0.8b'"
            ).fetchone()
            self.assertEqual(tuple(restored), ("active", "current", None))
            self.assertIsNone(
                conn.execute(
                    "SELECT id FROM memory_atoms WHERE id = 'atom:model-100m'"
                ).fetchone()
            )

    def test_same_claim_key_does_not_cross_owner_boundary(self) -> None:
        event_id = int(
            self.core.record_event(
                self._event("两个 owner 可以各自维护同名事实槽。", "doc:owner")
            ).split(":", 1)[1]
        )

        def plan_for(owner_id: str, atom_id: str, text: str) -> dict[str, object]:
            return memory_book_plan_from_compile_output(
                {
                    "memoryAtoms": [
                        {
                            "atomId": atom_id,
                            "kind": "project_fact",
                            "claimKey": "shared-name:current-model",
                            "canonicalText": text,
                            "sourceEventIds": [event_id],
                            "validFromMs": 100,
                        }
                    ]
                },
                project="ime",
                provider="deepseek",
                model="v4-flash",
                owner_kind="agent",
                owner_id=owner_id,
            )

        with self._connect() as conn:
            apply_memory_book_plan(
                conn,
                plan_for("role-a", "atom:role-a", "角色 A 使用模型 Alpha。"),
            )
            apply_memory_book_plan(
                conn,
                plan_for("role-b", "atom:role-b", "角色 B 使用模型 Beta。"),
            )
            rows = conn.execute(
                """
                SELECT owner_id, id, status, claim_state
                FROM memory_atoms
                WHERE claim_key = 'shared-name:current-model'
                ORDER BY owner_id
                """
            ).fetchall()

        self.assertEqual(
            [tuple(row) for row in rows],
            [
                ("role-a", "atom:role-a", "active", "current"),
                ("role-b", "atom:role-b", "active", "current"),
            ],
        )

    def test_validator_rejects_unplanned_semantic_group(self) -> None:
        event_id = int(self.core.record_event(self._event("合法 Group", "doc:a")).split(":", 1)[1])
        with self._connect() as conn:
            bundle = build_memory_book_source_bundle(conn, project="ime")
            plan = memory_book_plan_from_compile_output(
                {
                    "phraseCandidates": [
                        {
                            "text": "完成前台闭环",
                            "sourceEventIds": [event_id],
                            "semanticGroupIds": ["group:invented"],
                        }
                    ]
                },
                project="ime",
                provider="deepseek",
                model="v4-flash",
                source_bundle=bundle,
            )
            report = inspect_memory_book_plan(plan)
            self.assertFalse(report["ok"])
            self.assertTrue(any(item["code"] == "semantic_group_not_in_plan" for item in report["errors"]))

    def test_source_bundle_redacts_structured_personal_and_network_identifiers(self) -> None:
        sensitive_values = (
            "13812345678",
            "11010519491231002X",
            "6222021234567890123",
            "192.168.1.10",
            "2001:db8::1",
            "supersecret",
            "private-key-material",
            "/home/alice/private/note.txt",
            r"C:\Users\alice\private\note.txt",
        )
        texts = (
            f"联系电话 {sensitive_values[0]}",
            f"证件号码 {sensitive_values[1]}",
            f"银行卡号 {sensitive_values[2]}",
            f"服务地址 {sensitive_values[3]} 和 {sensitive_values[4]}",
            f"访问 https://example.com/cb?access_token={sensitive_values[5]}&x=1",
            f"-----BEGIN PRIVATE KEY----- {sensitive_values[6]} -----END PRIVATE KEY-----",
            f"Linux 文件 {sensitive_values[7]}",
            f"Windows 文件 {sensitive_values[8]}",
        )
        legacy_rows = []
        for index, text in enumerate(texts, start=1):
            event = self._event(f"旧版输入 {index}", f"doc:privacy-{index}")
            event_id = int(self.core.record_event(event).split(":", 1)[1])
            legacy_capture = {
                **event.capture_metadata,
                "contentSha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "fieldContextChars": len(text),
                "imeBufferChars": len(text),
            }
            legacy_rows.append((text, json.dumps(legacy_capture), event_id))

        with self._connect() as conn:
            # Current ingress redacts before storage. Exercise the compiler's
            # separate protection for raw rows captured by older versions.
            conn.executemany(
                "UPDATE input_events SET committed_text = ?, capture_metadata_json = ? WHERE id = ?",
                legacy_rows,
            )
            bundle = build_memory_book_source_bundle(conn, project="ime")

        serialized = json.dumps(bundle, ensure_ascii=False)
        for value in sensitive_values:
            self.assertNotIn(value, serialized)
        stats = bundle["redactionStats"]
        for key in ("secret", "path", "phone", "identity", "paymentCard", "ipAddress"):
            self.assertGreater(int(stats[key]), 0)

    def test_source_bundle_quarantines_legacy_rime_fragments_without_enter_boundary(self) -> None:
        base = now_ms()
        ids = [
            int(
                self.core.record_event(
                    InputEvent(
                        event_id=None,
                        created_at_ms=base + offset,
                        source="squirrel_rime_commit_burst",
                        committed_text=committed,
                        recent_context=context,
                        privacy_disposition="allowed",
                        app="com.openai.codex",
                        project="ime",
                        context_group_id="app:codex",
                    )
                ).split(":", 1)[1]
            )
            for offset, committed, context in (
                (0, "BM", "目前BM"),
                (1_000, "25", "目前BM25"),
                (2_000, "这些", "目前BM25这些"),
                (3_000, "真实", "目前BM25这些真实实现"),
            )
        ]
        self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=base + 2_500,
                source="squirrel_rime_sidecar",
                committed_text="这是模型生成的文字，不应重新学习",
                recent_context="目前BM25这些",
                privacy_disposition="allowed",
                app="squirrel",
                project="ime",
            )
        )

        with self._connect() as conn:
            bundle = build_memory_book_source_bundle(conn, project="ime", after_event_id=0)
            events = bundle["recentEvents"]
            self.assertEqual(events, [])
            self.assertEqual(bundle["rawEventCount"], 5)
            self.assertEqual(bundle["reconstruction"]["excludedGeneratedEventCount"], 1)
            self.assertEqual(bundle["reconstruction"]["droppedLowSignalEventCount"], 1)
            self.assertEqual(
                bundle["reconstruction"]["droppedQualityReasons"]["missing_finalized_boundary"],
                1,
            )

            plan = memory_book_plan_from_compile_output(
                {
                    "memoryAtoms": [
                        {
                            "claimKey": "project:ime.bm25-status",
                            "canonicalText": "BM25 已在输入法项目中真实实现。",
                            "sourceEventIds": [ids[0], ids[-1]],
                        }
                    ]
                },
                project="ime",
                provider="deepseek",
                model="deepseek-v4-flash",
                source_bundle=bundle,
            )

    def test_source_bundle_filters_runtime_probes_and_merges_duplicate_user_text(self) -> None:
        base = now_ms()
        for offset in (0, 2_000):
            self.core.record_event(
                self._event(
                    "输入法记忆应由模型清洗后再索引",
                    "app:codex",
                    created_at_ms=base + offset,
                    app="com.openai.codex",
                )
            )
        self.core.record_event(
            self._event(
                "Type: ceshiwendang. Wait for LLM/model. Press a visible candidate and wait for the next prediction.",
                "app:textedit",
                created_at_ms=base + 3_000,
            )
        )
        self.core.record_event(
            self._event(
                "我想设计一个候选展示方式",
                "app:doctor-prediction",
                created_at_ms=base + 4_000,
            )
        )

        with self._connect() as conn:
            bundle = build_memory_book_source_bundle(conn, project="ime", after_event_id=0)

        self.assertEqual(len(bundle["recentEvents"]), 1)
        self.assertEqual(bundle["recentEvents"][0]["text"], "输入法记忆应由模型清洗后再索引")
        self.assertEqual(len(bundle["recentEvents"][0]["sourceEventIds"]), 2)
        self.assertEqual(bundle["reconstruction"]["mergedDuplicateEventCount"], 1)
        self.assertEqual(bundle["reconstruction"]["droppedRuntimeProbeCount"], 1)
        self.assertEqual(bundle["reconstruction"]["droppedDoctorEventCount"], 1)

    def _event(
        self,
        text: str,
        group_id: str,
        *,
        created_at_ms: int | None = None,
        app: str = "com.apple.TextEdit",
    ) -> InputEvent:
        self.capture_ordinal += 1
        ordinal = self.capture_ordinal
        timestamp = now_ms() if created_at_ms is None else created_at_ms
        return InputEvent(
            event_id=None,
            created_at_ms=timestamp,
            source="squirrel_input_segment",
            committed_text=text,
            privacy_disposition="allowed",
            app=app,
            project="ime",
            context_group_id=group_id,
            context_group_level="document",
            capture_metadata={
                "schemaVersion": "rag-ime.input-capture.v2",
                "captureId": f"capture:compile-state:{ordinal}",
                "transactionId": f"transaction:compile-state:{ordinal}",
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
                "appBundleId": app,
                "fieldIdentitySha256": hashlib.sha256(group_id.encode("utf-8")).hexdigest(),
                "privacyRevision": "foreground-privacy.v1",
                "occurredStartMs": timestamp,
                "occurredEndMs": timestamp + 20,
                "contentSha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "captureSource": "text_input_client",
                "fallbackReason": "",
                "fieldContextChars": len(text),
                "imeBufferChars": len(text),
                "selectionRule": "final_committed_segment",
            },
        )


if __name__ == "__main__":
    unittest.main()
