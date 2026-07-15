from __future__ import annotations

import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing, redirect_stdout
from pathlib import Path

import rag_ime.cli as cli_module
from rag_ime.agent_memory_sources import AgentMemorySourceStore
from rag_ime.agent_sessions import AgentSessionStore
from rag_ime.cli import main
from rag_ime.local_sqlite_core import LocalSqliteCoreClient
from rag_ime.memory_book_compiler import (
    apply_memory_book_plan,
    apply_stored_memory_book_run,
    build_memory_book_source_bundle,
    find_newer_applied_memory_book_run,
    find_memory_book_draft_for_bundle,
    inspect_memory_book_plan,
    memory_compile_due,
    memory_compile_state,
    memory_book_plan_from_compile_output,
    memory_book_plan_from_stored_run,
    rollback_memory_book_run,
    store_memory_book_plan,
    update_stored_memory_book_diff,
)
from rag_ime.memory_graph import MemoryGraphPrincipal, MemoryGraphStore
from rag_ime.models import InputEvent
from rag_ime.rime_rank_export import record_rime_rank_feedback
from rag_ime.text_utils import now_ms


class FakeMemoryBookOrganizer:
    def __init__(self, config) -> None:
        self.config = config

    @property
    def provider_name(self) -> str:
        return "deepseek"

    def compile_memory_book(self, *, bundle: dict[str, object], project: str) -> dict[str, object]:
        event_id = int((bundle.get("recentEvents") or [{"eventId": 1}])[0]["eventId"])
        return sample_compile_output(event_id)


class MemoryBookCompilerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-memory-book-")
        self.db_path = Path(self.tmp.name) / "rag-ime.sqlite"
        self.core = LocalSqliteCoreClient(self.db_path)
        self.core.initialize()
        self.event_id = int(
            self.core.record_event(
                InputEvent(
                    event_id=None,
                    created_at_ms=now_ms(),
                    source="manual",
                    committed_text="RAG 输入法多路召回方案",
                    privacy_disposition="allowed",
                    recent_context="BM25 向量 TagMemo Time DeepSeek",
                    project="wisdom-weasel-rag-ime",
                    tags=("RAG", "输入法"),
                )
            ).split(":", 1)[1]
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _run_cli_json(self, *args: str) -> tuple[int, dict[str, object]]:
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            code = main(["--db-path", str(self.db_path), *args])
        return code, json.loads(stdout.getvalue())

    def test_memory_book_preview_is_dry_run(self) -> None:
        original = cli_module.DeepSeekMemoryOrganizer
        cli_module.DeepSeekMemoryOrganizer = FakeMemoryBookOrganizer
        try:
            env_path = Path(self.tmp.name) / "deepseek.env"
            env_path.write_text("DEEPSEEK_API_KEY=fake\nRAG_IME_DEEPSEEK_MODEL=deepseek-v4-flash\n", encoding="utf-8")
            output = Path(self.tmp.name) / "memory-book-preview.json"

            code, payload = self._run_cli_json(
                "memory-book-preview",
                "--project",
                "wisdom-weasel-rag-ime",
                "--model-env-path",
                str(env_path),
                "--output",
                str(output),
            )
        finally:
            cli_module.DeepSeekMemoryOrganizer = original

        self.assertEqual(code, 0)
        self.assertTrue(payload["dryRun"])
        self.assertTrue(payload["validation"]["ok"])
        self.assertTrue(output.exists())
        plan = json.loads(output.read_text(encoding="utf-8"))
        phrase = next(item for item in plan["diffs"] if item["op"] == "add_phrase_candidate")
        self.assertEqual(phrase["payload"]["pinyin"], "duo lu zhao hui")
        self.assertEqual(phrase["payload"]["reviewSource"], "dsv4")
        with closing(sqlite3.connect(self.db_path)) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM memory_books").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM memory_cleanup_runs WHERE run_id LIKE 'memory_book_%'").fetchone()[0], 0)

    def test_memory_book_preview_saved_draft_reuses_identical_source_bundle(self) -> None:
        class CountingOrganizer(FakeMemoryBookOrganizer):
            calls = 0

            def compile_memory_book(self, *, bundle: dict[str, object], project: str) -> dict[str, object]:
                type(self).calls += 1
                return super().compile_memory_book(bundle=bundle, project=project)

        original = cli_module.DeepSeekMemoryOrganizer
        cli_module.DeepSeekMemoryOrganizer = CountingOrganizer
        try:
            env_path = Path(self.tmp.name) / "deepseek.env"
            env_path.write_text("DEEPSEEK_API_KEY=fake\nRAG_IME_DEEPSEEK_MODEL=deepseek-v4-flash\n", encoding="utf-8")
            output = Path(self.tmp.name) / "memory-book-review.json"
            arguments = (
                "memory-book-preview",
                "--project",
                "wisdom-weasel-rag-ime",
                "--model-env-path",
                str(env_path),
                "--output",
                str(output),
                "--save-draft",
            )
            first_code, first = self._run_cli_json(*arguments)
            second_code, second = self._run_cli_json(*arguments)
        finally:
            cli_module.DeepSeekMemoryOrganizer = original

        self.assertEqual((first_code, second_code), (0, 0))
        self.assertTrue(first["storedDraft"])
        self.assertFalse(first["reusedDraft"])
        self.assertTrue(second["storedDraft"])
        self.assertTrue(second["reusedDraft"])
        self.assertEqual(CountingOrganizer.calls, 1)
        self.assertEqual(first["run"]["runId"], second["run"]["runId"])
        with self.core._connect() as conn:  # type: ignore[attr-defined]
            existing = find_memory_book_draft_for_bundle(
                conn,
                project="wisdom-weasel-rag-ime",
                bundle_hash=str(first["source"]["bundleHash"]),
            )
            assert existing is not None
            restored = memory_book_plan_from_stored_run(existing)
            draft_count = conn.execute(
                "SELECT COUNT(*) FROM memory_cleanup_runs WHERE status = 'draft' AND run_id LIKE 'memory_book_%'"
            ).fetchone()[0]
        self.assertEqual(restored["runId"], first["run"]["runId"])
        self.assertTrue(inspect_memory_book_plan(restored)["ok"])
        self.assertEqual(draft_count, 1)

    def test_coalesced_memory_book_draft_supersedes_older_project_draft(self) -> None:
        with self.core._connect() as conn:  # type: ignore[attr-defined]
            bundle = build_memory_book_source_bundle(
                conn,
                project="wisdom-weasel-rag-ime",
                since_days=7,
                limit=80,
            )
            first_plan = memory_book_plan_from_compile_output(
                sample_compile_output(self.event_id),
                project="wisdom-weasel-rag-ime",
                provider="deepseek",
                model="deepseek-v4-flash",
                source_bundle=bundle,
            )
            store_memory_book_plan(conn, first_plan, supersede_project_drafts=True)
            second_plan = json.loads(json.dumps(first_plan))
            second_plan["runId"] = "memory_book_newer_review"
            second_plan["metadata"]["bundleHash"] = "sha256:newer-bundle"
            store_memory_book_plan(conn, second_plan, supersede_project_drafts=True)
            statuses = {
                str(row["run_id"]): str(row["status"])
                for row in conn.execute(
                    "SELECT run_id, status FROM memory_cleanup_runs WHERE run_id IN (?, ?)",
                    (first_plan["runId"], second_plan["runId"]),
                ).fetchall()
            }
            rejected = conn.execute(
                "SELECT COUNT(*) FROM memory_cleanup_diffs WHERE run_id = ? AND status = 'rejected'",
                (first_plan["runId"],),
            ).fetchone()[0]

        self.assertEqual(statuses[first_plan["runId"]], "superseded")
        self.assertEqual(statuses[second_plan["runId"]], "draft")
        self.assertGreater(rejected, 0)

    def test_stale_memory_book_draft_cannot_apply_or_be_reused(self) -> None:
        with self.core._connect() as conn:  # type: ignore[attr-defined]
            first_bundle = build_memory_book_source_bundle(
                conn,
                project="wisdom-weasel-rag-ime",
                since_days=7,
                limit=80,
            )
            stale_plan = memory_book_plan_from_compile_output(
                sample_compile_output(self.event_id),
                project="wisdom-weasel-rag-ime",
                provider="deepseek",
                model="deepseek-v4-flash",
                source_bundle=first_bundle,
            )
            stale_plan["runId"] = "memory_book_stale_review"
            store_memory_book_plan(conn, stale_plan)

        second_event_id = int(
            self.core.record_event(
                InputEvent(
                    event_id=None,
                    created_at_ms=now_ms(),
                    source="manual",
                    committed_text="后续证据已经生成并应用新的记忆草案",
                    privacy_disposition="allowed",
                    recent_context="",
                    project="wisdom-weasel-rag-ime",
                )
            ).split(":", 1)[1]
        )
        with self.core._connect() as conn:  # type: ignore[attr-defined]
            newer_bundle = build_memory_book_source_bundle(
                conn,
                project="wisdom-weasel-rag-ime",
                since_days=7,
                limit=80,
            )
            newer_plan = memory_book_plan_from_compile_output(
                sample_compile_output(second_event_id),
                project="wisdom-weasel-rag-ime",
                provider="deepseek",
                model="deepseek-v4-flash",
                source_bundle=newer_bundle,
            )
            newer_plan["runId"] = "memory_book_newer_apply"
            apply_memory_book_plan(conn, newer_plan)

            with self.assertRaisesRegex(ValueError, "draft is stale"):
                apply_stored_memory_book_run(conn, run_id="memory_book_stale_review")
            reused = find_memory_book_draft_for_bundle(
                conn,
                project="wisdom-weasel-rag-ime",
                bundle_hash=str(stale_plan["metadata"]["bundleHash"]),
            )

        self.assertIsNone(reused)

    def test_source_bundle_exposes_delete_and_correction_feedback_to_dsv4(self) -> None:
        self.core.record_memory_feedback(
            {
                "event": "backspace_after_accept",
                "candidateId": "candidate:错别字",
                "candidateText": "错别宇",
                "sourceType": "rime",
                "sourceEventId": self.event_id,
                "project": "wisdom-weasel-rag-ime",
                "metadata": {"deleteCount": 3},
            }
        )
        record_rime_rank_feedback(
            self.db_path,
            preedit="cuo bie zi",
            rejected_text="错别宇",
            accepted_text="错别字",
            action="correction_pair",
            project="wisdom-weasel-rag-ime",
        )

        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            bundle = build_memory_book_source_bundle(
                conn,
                project="wisdom-weasel-rag-ime",
                since_days=7,
                limit=20,
                after_event_id=0,
            )

        feedback = bundle["feedback"]
        self.assertTrue(any(item["action"] == "backspace_after_accept" for item in feedback))
        self.assertTrue(any(item["deleteCount"] == 3 for item in feedback))
        rank_feedback = bundle["rimeRankFeedback"]
        correction = next(item for item in rank_feedback if item["action"] == "correction_pair")
        self.assertEqual(correction["rejectedText"], "错别宇")
        self.assertEqual(correction["acceptedText"], "错别字")
        self.assertEqual(correction["preedit"], "cuo bie zi")

    def test_memory_book_compile_requires_source_event_ids(self) -> None:
        output = sample_compile_output(self.event_id)
        output["dailyBooks"][0]["sourceEventIds"] = []
        plan = memory_book_plan_from_compile_output(output, project="wisdom-weasel-rag-ime", provider="deepseek", model="deepseek-v4-flash")

        report = inspect_memory_book_plan(plan)

        self.assertFalse(report["ok"])
        self.assertTrue(any(item["code"] == "missing_source_event_ids" for item in report["errors"]))

    def test_memory_book_compile_limits_new_semantic_groups(self) -> None:
        output = sample_compile_output(self.event_id)
        output["semanticGroups"] = [
            {
                "groupId": f"group:topic-{index}",
                "title": f"主题 {index}",
                "description": f"第 {index} 个粗粒度内容主题",
                "sourceEventIds": [self.event_id],
            }
            for index in range(5)
        ]
        bundle = {
            "recentEvents": [{"eventId": self.event_id, "text": "RAG 输入法多路召回方案"}],
            "existingSemanticGroups": [],
        }

        plan = memory_book_plan_from_compile_output(
            output,
            project="wisdom-weasel-rag-ime",
            provider="deepseek",
            model="deepseek-v4-flash",
            source_bundle=bundle,
        )
        report = inspect_memory_book_plan(plan)

        self.assertTrue(report["ok"])
        self.assertEqual(report["counts"]["semanticGroups"], 3)
        self.assertIn("semantic_group_new_limit_applied", plan["metadata"]["warnings"])

    def test_tag_edge_accepts_dsv4_descriptive_field_names(self) -> None:
        output = sample_compile_output(self.event_id)
        output["tagEdges"] = [
            {
                "sourceTagName": "输入法",
                "targetTagName": "记忆清洗",
                "relationType": "depends_on",
                "confidence": 0.83,
                "evidenceEventIds": [self.event_id],
            }
        ]
        plan = memory_book_plan_from_compile_output(
            output,
            project="wisdom-weasel-rag-ime",
            provider="deepseek",
            model="deepseek-v4-flash",
        )
        edge = next(item for item in plan["diffs"] if item["op"] == "upsert_tag_edge")
        self.assertEqual(edge["payload"]["src"], "输入法")
        self.assertEqual(edge["payload"]["dst"], "记忆清洗")
        self.assertEqual(edge["payload"]["edgeType"], "depends_on")
        self.assertAlmostEqual(edge["payload"]["weight"], 0.83)

    def test_memory_book_compile_rejects_hallucinated_source_event_id(self) -> None:
        output = sample_compile_output(self.event_id)
        output["memoryAtoms"][0]["sourceEventIds"] = [self.event_id + 999]
        bundle = {
            "recentEvents": [{"eventId": self.event_id, "text": "RAG 输入法多路召回方案"}],
            "existingMemoryBooks": [],
            "existingSemanticGroups": [],
            "existingSemanticTags": [],
        }

        plan = memory_book_plan_from_compile_output(
            output,
            project="wisdom-weasel-rag-ime",
            provider="deepseek",
            model="deepseek-v4-flash",
            source_bundle=bundle,
        )
        report = inspect_memory_book_plan(plan)

        self.assertFalse(report["ok"])
        self.assertTrue(any(item["code"] == "source_event_not_in_bundle" for item in report["errors"]))

    def test_memory_book_compile_backfills_source_ids_from_bundle(self) -> None:
        output = sample_compile_output(self.event_id)
        output["dailyBooks"][0]["sourceEventIds"] = []
        output["memoryAtoms"][0]["sourceEventIds"] = []
        output["tagEdges"][0]["evidenceEventIds"] = []
        output["phraseCandidates"][0]["sourceEventIds"] = []
        bundle = {
            "bundleHash": "sha256:test-empty-organizer",
            "cursor": {
                "fromEventId": 0,
                "toEventId": self.event_id + 2,
                "pendingEventCount": 3,
            },
            "recentEvents": [
                {
                    "eventId": self.event_id,
                    "createdAtMs": now_ms(),
                    "text": "RAG 输入法多路召回方案，需要用 DeepSeek 整理真实历史。",
                    "recentContext": "BM25 向量 TagMemo Time",
                    "tags": ["RAG", "输入法"],
                }
            ]
        }

        plan = memory_book_plan_from_compile_output(
            output,
            project="wisdom-weasel-rag-ime",
            provider="deepseek",
            model="deepseek-v4-flash",
            source_bundle=bundle,
        )
        report = inspect_memory_book_plan(plan)

        self.assertTrue(report["ok"])
        payloads = [item["payload"] for item in plan["diffs"]]
        self.assertTrue(all(self.event_id in item.get("sourceEventIds", item.get("evidenceEventIds", [])) for item in payloads))

    def test_memory_book_compile_drops_empty_edges_and_bad_phrases(self) -> None:
        output = sample_compile_output(self.event_id)
        output["dailyBooks"] = []
        output["tagEdges"] = [{}, {"src": "", "dst": "RAG"}, {"src": "RAG", "dst": ""}]
        output["phraseCandidates"] = [{}, {"text": ""}, {"text": "这是一个很长很长的历史原句不应该作为短候选"}]

        plan = memory_book_plan_from_compile_output(
            output,
            project="wisdom-weasel-rag-ime",
            provider="deepseek",
            model="deepseek-v4-flash",
        )
        report = inspect_memory_book_plan(plan)

        self.assertTrue(report["ok"])
        self.assertEqual(report["counts"]["tagEdges"], 0)
        self.assertEqual(report["counts"]["phraseCandidates"], 0)

    def test_memory_book_compile_synthesizes_daily_book_when_model_omits_books(self) -> None:
        output = sample_compile_output(self.event_id)
        output["dailyBooks"] = []
        bundle = {
            "recentEvents": [
                {
                    "eventId": self.event_id,
                    "createdAtMs": now_ms(),
                    "text": "RAG 输入法多路召回方案，需要用 DeepSeek 整理真实历史。",
                    "recentContext": "Memory Book preview validate apply",
                    "tags": ["RAG", "输入法"],
                }
            ]
        }

        plan = memory_book_plan_from_compile_output(
            output,
            project="wisdom-weasel-rag-ime",
            provider="deepseek",
            model="deepseek-v4-flash",
            source_bundle=bundle,
        )
        report = inspect_memory_book_plan(plan)

        self.assertTrue(report["ok"])
        self.assertEqual(report["counts"]["memoryBooks"], 1)
        self.assertIn("daily_book_synthesized_from_atoms", plan["metadata"]["warnings"])
        book = next(item["payload"] for item in plan["diffs"] if item["op"] == "upsert_memory_book")
        self.assertEqual(book["title"], f"本地记忆归档 {book['bookKey']}")
        self.assertEqual(book["queryExpansions"], [])
        self.assertNotIn("真实 Codex 历史", book["summary"])

    def test_memory_book_compile_accepts_stable_topic_books(self) -> None:
        output = sample_compile_output(self.event_id)
        output["dailyBooks"] = []
        output["topicBooks"] = [
            {
                "bookId": "book:topic:ai-input-method",
                "bookKey": "ai-input-method",
                "bookType": "topic",
                "title": "AI 输入法项目",
                "summary": "持续开发基于 Squirrel 的本地预测、RAG 记忆和显式知识生成链路。",
                "tags": ["输入法", "RAG", "Squirrel"],
                "queryExpansions": ["AI 输入法", "个人记忆输入法"],
                "sourceEventIds": [self.event_id],
                "confidence": 0.9,
                "qualityScore": 0.88,
            }
        ]

        plan = memory_book_plan_from_compile_output(
            output,
            project="wisdom-weasel-rag-ime",
            provider="deepseek",
            model="deepseek-v4-flash",
        )
        report = inspect_memory_book_plan(plan)

        self.assertTrue(report["ok"])
        self.assertEqual(report["counts"]["memoryBooks"], 1)
        book = next(item["payload"] for item in plan["diffs"] if item["op"] == "upsert_memory_book")
        self.assertEqual(book["bookId"], "book:topic:ai-input-method")
        self.assertEqual(book["bookType"], "topic")
        self.assertEqual(book["bookKey"], "ai-input-method")

    def test_similar_topic_book_reuses_existing_id_even_when_model_invents_a_new_one(self) -> None:
        output = sample_compile_output(self.event_id)
        output["dailyBooks"] = []
        output["topicBooks"] = [
            {
                "bookId": "book:topic:new-invented-id",
                "bookKey": "new-invented-key",
                "bookType": "topic",
                "title": "AI 输入法项目优化",
                "summary": "继续优化 Squirrel 输入法、RAG 记忆与本地预测。",
                "tags": ["输入法", "RAG"],
                "sourceEventIds": [self.event_id],
            }
        ]
        bundle = {
            "recentEvents": [{"eventId": self.event_id, "text": "继续优化 AI 输入法项目"}],
            "existingMemoryBooks": [
                {
                    "bookId": "book:topic:ai-input-method",
                    "bookKey": "ai-input-method",
                    "bookType": "topic",
                    "title": "AI 输入法项目",
                    "summary": "Squirrel 输入法、RAG 记忆与本地预测的长期主题。",
                    "tags": ["Squirrel", "RAG"],
                    "sourceEventIds": [self.event_id + 100],
                    "memoryAtomIds": ["atom:existing"],
                    "status": "archived",
                }
            ],
        }

        plan = memory_book_plan_from_compile_output(
            output,
            project="wisdom-weasel-rag-ime",
            provider="deepseek",
            model="deepseek-v4-flash",
            source_bundle=bundle,
        )
        book = next(item["payload"] for item in plan["diffs"] if item["op"] == "upsert_memory_book")

        self.assertEqual(book["bookId"], "book:topic:ai-input-method")
        self.assertEqual(book["bookKey"], "ai-input-method")
        self.assertEqual(book["reusedExistingBookId"], "book:topic:ai-input-method")
        self.assertEqual(book["previousStatus"], "archived")
        self.assertEqual(set(book["sourceEventIds"]), {self.event_id, self.event_id + 100})
        self.assertIn("atom:existing", book["memoryAtomIds"])

    def test_memory_book_compile_keeps_raw_history_pending_when_model_returns_empty(self) -> None:
        bundle = {
            "bundleHash": "sha256:test-empty-organizer",
            "cursor": {
                "fromEventId": 0,
                "toEventId": self.event_id + 2,
                "pendingEventCount": 3,
            },
            "recentEvents": [
                {
                    "eventId": self.event_id,
                    "createdAtMs": now_ms(),
                    "text": "周五上午十点和设计团队复盘新版支付流程。",
                    "recentContext": "会议安排",
                    "tags": ["团队复盘", "支付流程"],
                },
                {
                    "eventId": self.event_id + 1,
                    "createdAtMs": now_ms(),
                    "text": "周五上午十点和设计团队复盘新版支付流程。",
                    "recentContext": "重复记录应该合并",
                    "tags": ["团队复盘", "支付流程"],
                },
                {
                    "eventId": self.event_id + 2,
                    "createdAtMs": now_ms(),
                    "text": "采购清单需要补充燕麦和咖啡豆。",
                    "recentContext": "生活记录",
                    "tags": ["采购清单"],
                },
            ]
        }
        empty_output = {
            "schemaVersion": "rag-ime.memory-book-compile.v1",
            "dailyBooks": [],
            "memoryAtoms": [],
            "tagEdges": [],
            "phraseCandidates": [],
            "warnings": [],
        }

        plan = memory_book_plan_from_compile_output(
            empty_output,
            project="wisdom-weasel-rag-ime",
            provider="deepseek",
            model="deepseek-v4-flash",
            source_bundle=bundle,
        )
        report = inspect_memory_book_plan(plan)

        self.assertFalse(report["ok"])
        self.assertEqual(report["diffCount"], 0)
        self.assertEqual(report["counts"]["memoryBooks"], 0)
        self.assertEqual(report["counts"]["memoryAtoms"], 0)
        self.assertEqual(report["counts"]["phraseCandidates"], 0)
        self.assertIn("organizer_returned_no_governed_memory", plan["metadata"]["warnings"])
        self.assertTrue(any(item["code"] == "organizer_returned_no_governed_memory" for item in report["errors"]))
        serialized = json.dumps(plan, ensure_ascii=False)
        for injected_term in (
            "周五上午十点",
            "采购清单",
            "DeepSeek",
            "Squirrel",
            "RAG 输入法",
            "面试展示",
            "eval gate",
        ):
            self.assertNotIn(injected_term, serialized)
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            with self.assertRaises(ValueError):
                apply_memory_book_plan(conn, plan)
            state = memory_compile_state(conn, project="wisdom-weasel-rag-ime")
        self.assertEqual(state["lastCompiledEventId"], 0)
        self.assertGreaterEqual(state["pendingEventCount"], 1)

    def test_memory_book_compile_rejects_long_surface_hint(self) -> None:
        output = sample_compile_output(self.event_id)
        output["memoryAtoms"][0]["surfaceHints"] = ["这是一个很长很长的历史原句不应该作为候选"]
        plan = memory_book_plan_from_compile_output(output, project="wisdom-weasel-rag-ime", provider="deepseek", model="deepseek-v4-flash")

        report = inspect_memory_book_plan(plan)

        self.assertFalse(report["ok"])
        self.assertTrue(any(item["code"] == "term_length_out_of_range" for item in report["errors"]))

    def test_memory_book_compile_rejects_secret_path_email(self) -> None:
        output = sample_compile_output(self.event_id)
        output["memoryAtoms"][0]["aliases"] = ["sk-secret-value"]
        plan = memory_book_plan_from_compile_output(output, project="wisdom-weasel-rag-ime", provider="deepseek", model="deepseek-v4-flash")

        report = inspect_memory_book_plan(plan)

        self.assertFalse(report["ok"])
        self.assertTrue(any(item["code"] == "sensitive_text_detected" for item in report["errors"]))

    def test_memory_book_compile_rejects_extended_sensitive_values(self) -> None:
        cases = {
            "phone": "13812345678",
            "identity": "11010519491231002X",
            "payment_card": "6222021234567890123",
            "ipv4": "192.168.1.10",
            "ipv6": "2001:db8::1",
            "url_query": "https://example.com/cb?access_token=supersecret&x=1",
            "private_key": "-----BEGIN PRIVATE KEY----- material -----END PRIVATE KEY-----",
            "linux_path": "/home/alice/private/note.txt",
            "windows_path": r"C:\Users\alice\private\note.txt",
        }
        for label, value in cases.items():
            with self.subTest(label=label):
                output = sample_compile_output(self.event_id)
                output["memoryAtoms"][0]["aliases"] = [value]
                plan = memory_book_plan_from_compile_output(
                    output,
                    project="wisdom-weasel-rag-ime",
                    provider="deepseek",
                    model="deepseek-v4-flash",
                )

                report = inspect_memory_book_plan(plan)

                self.assertFalse(report["ok"])
                self.assertTrue(any(item["code"] == "sensitive_text_detected" for item in report["errors"]))

    def test_memory_book_apply_requires_apply_flag(self) -> None:
        plan_path = self._write_sample_plan()

        code, payload = self._run_cli_json("memory-book-apply", "--run", str(plan_path))

        self.assertEqual(code, 2)
        self.assertFalse(payload["ok"])
        self.assertIn("--apply", payload["error"])

    def test_memory_book_apply_and_rollback(self) -> None:
        plan_path = self._write_sample_plan()
        plan = json.loads(plan_path.read_text(encoding="utf-8"))

        code, applied = self._run_cli_json("memory-book-apply", "--run", str(plan_path), "--apply")

        self.assertEqual(code, 0)
        self.assertTrue(applied["ok"])
        self.assertEqual(applied["run"]["status"], "applied")
        with closing(sqlite3.connect(self.db_path)) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM memory_books").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM memory_atoms").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM memory_aliases").fetchone()[0], 5)
            edge_count = conn.execute(
                """
                SELECT COUNT(*)
                FROM memory_tag_edges e
                JOIN memory_tags s ON s.id = e.src_tag_id
                JOIN memory_tags d ON d.id = e.dst_tag_id
                WHERE s.tag = '输入法' AND d.tag = '大模型' AND e.edge_type = 'related'
                """
            ).fetchone()[0]
            self.assertEqual(edge_count, 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM memory_items WHERE memory_id = 'phrase:多路召回'").fetchone()[0], 1)

        code, rolled_back = self._run_cli_json("memory-book-rollback", "--run-id", plan["runId"])

        self.assertEqual(code, 0)
        self.assertEqual(rolled_back["run"]["status"], "rolled_back")
        with closing(sqlite3.connect(self.db_path)) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM memory_books").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM memory_atoms").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM memory_aliases").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM memory_items WHERE memory_id = 'phrase:多路召回'").fetchone()[0], 0)

    def test_stored_workbench_draft_can_be_applied_and_rolled_back(self) -> None:
        plan = memory_book_plan_from_compile_output(
            sample_compile_output(self.event_id),
            project="wisdom-weasel-rag-ime",
            provider="deepseek",
            model="deepseek-v4-flash",
        )
        with self.core._connect() as conn:  # type: ignore[attr-defined]
            draft = store_memory_book_plan(conn, plan)
            applied = apply_stored_memory_book_run(conn, run_id=plan["runId"])
            rolled_back = rollback_memory_book_run(conn, run_id=plan["runId"])

        self.assertEqual(draft["status"], "draft")
        self.assertEqual(applied["status"], "applied")
        self.assertEqual(rolled_back["status"], "rolled_back")
        with closing(sqlite3.connect(self.db_path)) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM memory_books").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM memory_atoms").fetchone()[0], 0)

    def test_stored_draft_revalidates_source_scope_privacy_and_lifecycle_atomically(self) -> None:
        def store_draft(event_id: int, suffix: str) -> str:
            with self.core._connect() as conn:  # type: ignore[attr-defined]
                bundle = build_memory_book_source_bundle(
                    conn,
                    project="wisdom-weasel-rag-ime",
                    after_event_id=0,
                )
                output = sample_compile_output(event_id)
                output["entities"] = [
                    {
                        "entityId": f"entity:source-revalidation-{suffix}",
                        "entityType": "project",
                        "canonicalName": "RAG 输入法",
                        "sourceEventIds": [event_id],
                    }
                ]
                plan = memory_book_plan_from_compile_output(
                    output,
                    project="wisdom-weasel-rag-ime",
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    source_bundle=bundle,
                )
                plan["runId"] = f"memory_book_source_revalidation_{suffix}"
                self.assertTrue(inspect_memory_book_plan(plan)["ok"])
                store_memory_book_plan(conn, plan)
            return str(plan["runId"])

        def assert_rejected_without_writes(run_id: str) -> None:
            tables = ("memory_books", "memory_atoms", "memory_tags", "memory_entities")
            with self.core._connect() as conn:  # type: ignore[attr-defined]
                before = {
                    table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                    for table in tables
                }
                with self.assertRaisesRegex(ValueError, "source events are no longer eligible"):
                    apply_stored_memory_book_run(conn, run_id=run_id)
                after = {
                    table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                    for table in tables
                }
                self.assertEqual(after, before)
                self.assertEqual(
                    conn.execute(
                        "SELECT status FROM memory_cleanup_runs WHERE run_id = ?",
                        (run_id,),
                    ).fetchone()[0],
                    "superseded",
                )
                self.assertEqual(
                    conn.execute(
                        "SELECT COUNT(*) FROM memory_cleanup_diffs WHERE run_id = ? AND status = 'applied'",
                        (run_id,),
                    ).fetchone()[0],
                    0,
                )

        project_run = store_draft(self.event_id, "project")
        with self.core._connect() as conn:  # type: ignore[attr-defined]
            conn.execute("UPDATE input_events SET project = 'other-project' WHERE id = ?", (self.event_id,))
        assert_rejected_without_writes(project_run)

        deleted_id = int(
            self.core.record_event(
                InputEvent(
                    event_id=None,
                    created_at_ms=now_ms(),
                    source="manual",
                    committed_text="RAG 输入法删除后不应编译",
                    privacy_disposition="allowed",
                    project="wisdom-weasel-rag-ime",
                )
            ).split(":", 1)[1]
        )
        deleted_run = store_draft(deleted_id, "deleted")
        with self.core._connect() as conn:  # type: ignore[attr-defined]
            conn.execute("UPDATE memory_state SET deleted = 1 WHERE event_id = ?", (deleted_id,))
        assert_rejected_without_writes(deleted_run)

        sensitive_id = int(
            self.core.record_event(
                InputEvent(
                    event_id=None,
                    created_at_ms=now_ms(),
                    source="manual",
                    committed_text="RAG 输入法隐私检查",
                    privacy_disposition="allowed",
                    project="wisdom-weasel-rag-ime",
                )
            ).split(":", 1)[1]
        )
        sensitive_run = store_draft(sensitive_id, "sensitive")
        with self.core._connect() as conn:  # type: ignore[attr-defined]
            conn.execute(
                "UPDATE input_events SET committed_text = 'api_key=stale-draft-secret' WHERE id = ?",
                (sensitive_id,),
            )
        assert_rejected_without_writes(sensitive_run)

        changed_id = int(
            self.core.record_event(
                InputEvent(
                    event_id=None,
                    created_at_ms=now_ms(),
                    source="manual",
                    committed_text="RAG 输入法原始证据",
                    privacy_disposition="allowed",
                    project="wisdom-weasel-rag-ime",
                )
            ).split(":", 1)[1]
        )
        changed_run = store_draft(changed_id, "ordinary-edit")
        with self.core._connect() as conn:  # type: ignore[attr-defined]
            conn.execute(
                "UPDATE input_events SET committed_text = '完全不同但不敏感的新内容' WHERE id = ?",
                (changed_id,),
            )
        assert_rejected_without_writes(changed_run)

        session = AgentSessionStore(self.db_path).create(
            title="draft source lifecycle",
            role_id="memory-owner",
            created_at_ms=now_ms(),
        )
        source = AgentMemorySourceStore(
            self.db_path,
            project="wisdom-weasel-rag-ime",
        ).checkpoint_user_message(
            session_id=str(session["id"]),
            pi_entry_id="draft-source-user",
            turn_id="turn-source-user",
            text="RAG 输入法 Agent 用户证据",
            created_at_ms=now_ms(),
        )
        agent_event_id = int(source["source"]["inputEventId"])
        lifecycle_run = store_draft(agent_event_id, "tool-lifecycle")
        with self.core._connect() as conn:  # type: ignore[attr-defined]
            conn.execute(
                """
                UPDATE agent_memory_sources
                SET source_role = 'tool_receipt', status = 'archived'
                WHERE input_event_id = ?
                """,
                (agent_event_id,),
            )
            conn.execute(
                "UPDATE agent_sessions SET status = 'archived', archived_at_ms = ? WHERE id = ?",
                (now_ms(), str(session["id"])),
            )
        assert_rejected_without_writes(lifecycle_run)

    def test_memory_book_runs_must_roll_back_in_reverse_apply_order(self) -> None:
        first = memory_book_plan_from_compile_output(
            sample_compile_output(self.event_id),
            project="wisdom-weasel-rag-ime",
            provider="deepseek",
            model="deepseek-v4-flash",
        )
        first["runId"] = "memory_book_first_apply"
        second = json.loads(json.dumps(first))
        second["runId"] = "memory_book_second_apply"
        second["summary"] = "later memory state"

        with self.core._connect() as conn:  # type: ignore[attr-defined]
            apply_memory_book_plan(conn, first)
            apply_memory_book_plan(conn, second)
            newer = find_newer_applied_memory_book_run(conn, run_id=first["runId"])
            with self.assertRaisesRegex(ValueError, "newer applied run"):
                rollback_memory_book_run(conn, run_id=first["runId"])
            rollback_memory_book_run(conn, run_id=second["runId"])
            rolled_back = rollback_memory_book_run(conn, run_id=first["runId"])

        self.assertEqual(newer["runId"], second["runId"])
        self.assertEqual(rolled_back["status"], "rolled_back")

    def test_stored_workbench_draft_supports_review_edit_and_exclusion(self) -> None:
        plan = memory_book_plan_from_compile_output(
            sample_compile_output(self.event_id),
            project="wisdom-weasel-rag-ime",
            provider="deepseek",
            model="deepseek-v4-flash",
        )
        with self.core._connect() as conn:  # type: ignore[attr-defined]
            draft = store_memory_book_plan(conn, plan)
            book = next(item for item in draft["diffs"] if item["op"] == "upsert_memory_book")
            atom = next(item for item in draft["diffs"] if item["op"] == "upsert_memory_atom")
            edited_payload = dict(book["payload"])
            edited_payload["title"] = "输入法记忆与召回"
            reviewed = update_stored_memory_book_diff(
                conn,
                run_id=plan["runId"],
                diff_id=book["diffId"],
                payload=edited_payload,
                selected=True,
            )
            excluded = update_stored_memory_book_diff(
                conn,
                run_id=plan["runId"],
                diff_id=atom["diffId"],
                selected=False,
            )
            applied = apply_stored_memory_book_run(conn, run_id=plan["runId"])

        reviewed_book = next(item for item in reviewed["diffs"] if item["diffId"] == book["diffId"])
        excluded_atom = next(item for item in excluded["diffs"] if item["diffId"] == atom["diffId"])
        self.assertEqual(reviewed_book["payload"]["title"], "输入法记忆与召回")
        self.assertEqual(reviewed_book["status"], "approved")
        self.assertEqual(excluded_atom["status"], "rejected")
        self.assertEqual(next(item for item in applied["diffs"] if item["diffId"] == atom["diffId"])["status"], "rejected")
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT title FROM memory_books LIMIT 1").fetchone()
            self.assertEqual(row["title"], "输入法记忆与召回")
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM memory_atoms").fetchone()[0], 0)

    def test_dsv4_semantic_groups_tags_and_members_are_applied_and_rolled_back(self) -> None:
        output = sample_compile_output(self.event_id)
        output["semanticGroups"] = [
            {
                "groupId": "group:input-method",
                "title": "输入法",
                "description": "输入法、候选预测、语音与个人知识召回相关的长期主题。",
                "aliases": ["RAG 输入法"],
                "tags": ["输入法"],
                "sourceEventIds": [self.event_id],
                "confidence": 0.92,
                "qualityScore": 0.9,
            }
        ]
        output["semanticTags"] = [
            {
                "name": "混合召回",
                "description": "BM25、向量、标签与时间信号共同参与的检索策略。",
                "aliases": ["Hybrid RAG"],
                "semanticGroupIds": ["group:input-method"],
                "sourceEventIds": [self.event_id],
                "confidence": 0.88,
                "qualityScore": 0.86,
            }
        ]
        output["memoryAtoms"][0]["semanticGroupIds"] = ["group:input-method"]
        output["phraseCandidates"][0]["semanticGroupIds"] = ["group:input-method"]
        plan = memory_book_plan_from_compile_output(
            output,
            project="wisdom-weasel-rag-ime",
            provider="deepseek",
            model="deepseek-v4-flash",
        )
        report = inspect_memory_book_plan(plan)
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["counts"]["semanticGroups"], 1)
        self.assertEqual(report["counts"]["semanticTags"], 1)
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            apply_memory_book_plan(conn, plan)
            self.assertEqual(
                conn.execute("SELECT title FROM memory_semantic_groups WHERE group_id = 'group:input-method'").fetchone()[0],
                "输入法",
            )
            tag = conn.execute("SELECT description, source FROM memory_tags WHERE tag = '混合召回'").fetchone()
            self.assertEqual(tag["source"], "dsv4")
            self.assertIn("BM25", tag["description"])
            members = conn.execute(
                "SELECT member_type FROM memory_semantic_group_members WHERE group_id = 'group:input-method' ORDER BY member_type"
            ).fetchall()
            self.assertEqual({row[0] for row in members}, {"atom", "book", "phrase", "tag"})
            rollback_memory_book_run(conn, run_id=plan["runId"])
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM memory_semantic_groups").fetchone()[0], 0)

    def test_group_membership_is_inferred_from_shared_source_evidence(self) -> None:
        output = sample_compile_output(self.event_id)
        output["semanticGroups"] = [
            {
                "groupId": "group:input-method",
                "title": "输入法",
                "description": "输入法、候选预测、语音与个人知识召回相关的长期主题。",
                "sourceEventIds": [self.event_id],
            }
        ]
        output["semanticTags"] = [
            {
                "name": "混合召回",
                "description": "BM25 与向量共同参与的检索策略。",
                "sourceEventIds": [self.event_id],
            }
        ]
        bundle = {
            "recentEvents": [
                {
                    "eventId": self.event_id,
                    "sourceEventIds": [self.event_id],
                    "text": "RAG 输入法多路召回方案",
                }
            ],
            "existingSemanticGroups": [],
        }

        plan = memory_book_plan_from_compile_output(
            output,
            project="wisdom-weasel-rag-ime",
            provider="deepseek",
            model="deepseek-v4-flash",
            source_bundle=bundle,
        )

        for op in ("upsert_semantic_tag", "upsert_memory_book", "upsert_memory_atom", "add_phrase_candidate"):
            payload = next(item["payload"] for item in plan["diffs"] if item["op"] == op)
            self.assertEqual(payload["semanticGroupIds"], ["group:input-method"])

    def test_source_bundle_exposes_existing_tag_graph_to_dsv4(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            first = int(
                conn.execute(
                    "INSERT INTO memory_tags(tag, normalized_tag, tag_type, quality_score, created_at_ms, updated_at_ms, "
                    "description, source, status, metadata_json) VALUES ('BM25', 'bm25', 'tech', 0.9, 1, 1, "
                    "'词法召回', 'dsv4', 'active', '{}')"
                ).lastrowid
            )
            second = int(
                conn.execute(
                    "INSERT INTO memory_tags(tag, normalized_tag, tag_type, quality_score, created_at_ms, updated_at_ms, "
                    "description, source, status, metadata_json) VALUES ('混合召回', '混合召回', 'concept', 0.85, 1, 1, "
                    "'多路融合', 'dsv4', 'active', '{}')"
                ).lastrowid
            )
            conn.execute(
                "INSERT INTO memory_tag_edges(src_tag_id, dst_tag_id, edge_type, weight, direction_bias, evidence_count, "
                "updated_at_ms, metadata_json) VALUES (?, ?, 'part_of', 0.88, 0, 3, 1, '{}')",
                (first, second),
            )
            bundle = build_memory_book_source_bundle(conn, project="wisdom-weasel-rag-ime")

        self.assertEqual(len(bundle["existingTagEdges"]), 1)
        self.assertEqual(bundle["existingTagEdges"][0]["src"], "BM25")
        self.assertEqual(bundle["existingTagEdges"][0]["dst"], "混合召回")
        bm25 = next(item for item in bundle["existingSemanticTags"] if item["name"] == "BM25")
        self.assertEqual(bm25["degree"], 1)

    def test_reviewed_tag_merge_moves_graph_and_rolls_back(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            canonical_id = int(
                conn.execute(
                    "INSERT INTO memory_tags(tag, normalized_tag, tag_type, quality_score, created_at_ms, updated_at_ms, "
                    "description, source, status, metadata_json) VALUES ('BM25', 'bm25', 'tech', 0.9, 1, 1, "
                    "'词法召回', 'dsv4', 'active', '{}')"
                ).lastrowid
            )
            duplicate_id = int(
                conn.execute(
                    "INSERT INTO memory_tags(tag, normalized_tag, tag_type, quality_score, created_at_ms, updated_at_ms, "
                    "description, source, status, metadata_json) VALUES ('BM25算法', 'bm25算法', 'tech', 0.8, 1, 1, "
                    "'BM25 别名', 'dsv4', 'active', '{}')"
                ).lastrowid
            )
            related_id = int(
                conn.execute(
                    "INSERT INTO memory_tags(tag, normalized_tag, tag_type, quality_score, created_at_ms, updated_at_ms, "
                    "description, source, status, metadata_json) VALUES ('混合召回', '混合召回', 'concept', 0.85, 1, 1, "
                    "'多路融合', 'dsv4', 'active', '{}')"
                ).lastrowid
            )
            conn.execute(
                "INSERT INTO memory_tag_profiles(tag_id, color_token, aliases_json, updated_at_ms) VALUES (?, 'blue', '[\"BM25算法\"]', 1)",
                (canonical_id,),
            )
            conn.execute(
                "INSERT INTO memory_tag_edges(src_tag_id, dst_tag_id, edge_type, weight, direction_bias, evidence_count, "
                "updated_at_ms, metadata_json) VALUES (?, ?, 'part_of', 0.8, 0, 2, 1, '{}')",
                (duplicate_id, related_id),
            )
            bundle = build_memory_book_source_bundle(conn, project="wisdom-weasel-rag-ime")

        output = {
            "schemaVersion": "rag-ime.memory-book-compile.v1",
            "semanticGroups": [],
            "semanticTags": [],
            "tagMerges": [
                {
                    "source": "BM25算法",
                    "target": "BM25",
                    "reason": "同义术语",
                    "evidenceEventIds": [self.event_id],
                    "confidence": 0.98,
                }
            ],
            "tagEdges": [],
        }
        plan = memory_book_plan_from_compile_output(
            output,
            project="wisdom-weasel-rag-ime",
            provider="deepseek",
            model="deepseek-v4-flash",
            source_bundle=bundle,
        )
        report = inspect_memory_book_plan(plan)
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["counts"]["tagMerges"], 1)

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            applied = apply_memory_book_plan(conn, plan)
            self.assertEqual(applied["status"], "applied")
            self.assertIsNone(conn.execute("SELECT id FROM memory_tags WHERE id = ?", (duplicate_id,)).fetchone())
            moved = conn.execute(
                "SELECT 1 FROM memory_tag_edges WHERE src_tag_id = ? AND dst_tag_id = ? AND edge_type = 'part_of'",
                (canonical_id, related_id),
            ).fetchone()
            self.assertIsNotNone(moved)
            aliases = json.loads(
                conn.execute("SELECT aliases_json FROM memory_tag_profiles WHERE tag_id = ?", (canonical_id,)).fetchone()[0]
            )
            self.assertIn("BM25算法", aliases)
            rollback_memory_book_run(conn, run_id=plan["runId"])
            self.assertIsNotNone(conn.execute("SELECT id FROM memory_tags WHERE id = ?", (duplicate_id,)).fetchone())
            restored = conn.execute(
                "SELECT 1 FROM memory_tag_edges WHERE src_tag_id = ? AND dst_tag_id = ? AND edge_type = 'part_of'",
                (duplicate_id, related_id),
            ).fetchone()
            self.assertIsNotNone(restored)

    def test_virtual_tag_merge_canonicalizes_without_creating_an_unapplicable_diff(self) -> None:
        output = {
            "schemaVersion": "rag-ime.memory-book-compile.v1",
            "semanticGroups": [],
            "semanticTags": [
                {
                    "name": "BM25算法",
                    "description": "SQLite FTS5 的词法相关性算法。",
                    "sourceEventIds": [self.event_id],
                }
            ],
            "tagMerges": [
                {
                    "source": "BM25",
                    "target": "BM25算法",
                    "reason": "本批术语规范化",
                    "evidenceEventIds": [self.event_id],
                }
            ],
        }
        source_bundle = {
            "recentEvents": [{"eventId": self.event_id, "sourceEventIds": [self.event_id], "text": "BM25 算法"}],
            "existingSemanticGroups": [],
            "existingSemanticTags": [],
        }

        plan = memory_book_plan_from_compile_output(
            output,
            project="wisdom-weasel-rag-ime",
            provider="deepseek",
            model="deepseek-v4-flash",
            source_bundle=source_bundle,
        )

        self.assertFalse(any(item["op"] == "merge_semantic_tag" for item in plan["diffs"]))
        tag = next(item for item in plan["diffs"] if item["op"] == "upsert_semantic_tag")
        self.assertEqual(tag["payload"]["name"], "BM25算法")
        self.assertIn("virtual_tag_merge_canonicalized:BM25->BM25算法", plan["metadata"]["warnings"])

    def test_tag_merge_plan_drops_reverse_cycles(self) -> None:
        with self.core._connect() as conn:  # type: ignore[attr-defined]
            conn.execute(
                "INSERT INTO memory_tags(tag, normalized_tag, tag_type, quality_score, created_at_ms, updated_at_ms, "
                "description, source, status, metadata_json) VALUES ('BM25', 'bm25', 'tech', 0.9, 1, 1, "
                "'词法召回', 'dsv4', 'active', '{}')"
            )
            conn.execute(
                "INSERT INTO memory_tags(tag, normalized_tag, tag_type, quality_score, created_at_ms, updated_at_ms, "
                "description, source, status, metadata_json) VALUES ('BM25算法', 'bm25算法', 'tech', 0.8, 1, 1, "
                "'BM25 别名', 'dsv4', 'active', '{}')"
            )
            bundle = build_memory_book_source_bundle(conn, project="wisdom-weasel-rag-ime")
        output = {
            "schemaVersion": "rag-ime.memory-book-compile.v1",
            "tagMerges": [
                {"source": "BM25算法", "target": "BM25", "reason": "规范到短名称"},
                {"source": "BM25", "target": "BM25算法", "reason": "反向循环"},
            ],
        }

        plan = memory_book_plan_from_compile_output(
            output,
            project="wisdom-weasel-rag-ime",
            provider="deepseek",
            model="deepseek-v4-flash",
            source_bundle=bundle,
        )
        merges = [item for item in plan["diffs"] if item["op"] == "merge_semantic_tag"]

        self.assertEqual(len(merges), 1)
        self.assertEqual(merges[0]["payload"]["source"], "BM25算法")
        self.assertEqual(merges[0]["payload"]["target"], "BM25")

    def test_legacy_stored_draft_skips_a_missing_merge_source_instead_of_aborting(self) -> None:
        output = {
            "schemaVersion": "rag-ime.memory-book-compile.v1",
            "semanticGroups": [],
            "semanticTags": [
                {
                    "name": "BM25算法",
                    "description": "SQLite FTS5 的词法相关性算法。",
                    "sourceEventIds": [self.event_id],
                }
            ],
        }
        plan = memory_book_plan_from_compile_output(
            output,
            project="wisdom-weasel-rag-ime",
            provider="deepseek",
            model="deepseek-v4-flash",
        )
        plan["diffs"].append(
            {
                "op": "merge_semantic_tag",
                "targetId": "tag-merge:BM25->BM25算法",
                "payload": {
                    "source": "BM25",
                    "target": "BM25算法",
                    "reason": "旧版草案留下的虚拟合并",
                    "evidenceEventIds": [self.event_id],
                },
                "status": "pending",
            }
        )

        with self.core._connect() as conn:  # type: ignore[attr-defined]
            store_memory_book_plan(conn, plan)
            applied = apply_stored_memory_book_run(conn, run_id=plan["runId"])
            merge = next(item for item in applied["diffs"] if item["op"] == "merge_semantic_tag")
            rollback = json.loads(
                conn.execute(
                    "SELECT rollback_json FROM memory_cleanup_diffs WHERE id = ?",
                    (merge["diffId"],),
                ).fetchone()[0]
            )

        self.assertEqual(applied["status"], "applied")
        self.assertEqual(merge["status"], "applied")
        self.assertTrue(rollback["noOp"])
        self.assertEqual(rollback["reason"], "missing_source")

    def test_memory_graph_diffs_apply_incrementally_and_rollback_with_outbox(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            bundle = build_memory_book_source_bundle(conn, project="wisdom-weasel-rag-ime")
        plan = memory_book_plan_from_compile_output(
            {
                "schemaVersion": "rag-ime.memory-book-compile.v1",
                "entities": [
                    {
                        "entityId": "entity:rag-ime",
                        "entityType": "project",
                        "canonicalName": "RAG 输入法",
                        "sourceEventIds": [self.event_id],
                        "confidence": 0.9,
                    },
                    {
                        "entityId": "entity:vector-search",
                        "entityType": "concept",
                        "canonicalName": "向量检索",
                        "sourceEventIds": [self.event_id],
                        "confidence": 0.85,
                    },
                ],
                "relations": [
                    {
                        "relationId": "relation:rag-vector",
                        "sourceEntityId": "entity:rag-ime",
                        "targetEntityId": "entity:vector-search",
                        "relationType": "uses",
                        "fact": "RAG 输入法多路召回使用向量检索",
                        "evidenceEventIds": [self.event_id],
                        "confidence": 0.9,
                    }
                ],
            },
            project="wisdom-weasel-rag-ime",
            provider="deepseek",
            model="deepseek-v4-flash",
            source_bundle=bundle,
        )
        report = inspect_memory_book_plan(plan)
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["counts"]["memoryEntities"], 2)
        self.assertEqual(report["counts"]["memoryRelations"], 1)

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            applied = apply_memory_book_plan(conn, plan)
            self.assertEqual(applied["status"], "applied")
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM memory_entities WHERE status = 'active'").fetchone()[0], 2)
            relation = conn.execute(
                "SELECT status, revision FROM memory_relations WHERE relation_id = 'relation:rag-vector'"
            ).fetchone()
            self.assertEqual(tuple(relation), ("active", 1))
            self.assertEqual(
                tuple(
                    conn.execute(
                        "SELECT source_type, source_id FROM memory_relation_sources WHERE relation_id = 'relation:rag-vector'"
                    ).fetchone()
                ),
                ("input_event", str(self.event_id)),
            )
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM memory_projection_outbox").fetchone()[0], 3)

            rollback_memory_book_run(conn, run_id=plan["runId"])
            self.assertEqual(
                conn.execute("SELECT status FROM memory_relations WHERE relation_id = 'relation:rag-vector'").fetchone()[0],
                "tombstoned",
            )
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM memory_entities WHERE status = 'tombstoned'").fetchone()[0], 2)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM memory_projection_outbox").fetchone()[0], 6)

    def test_memory_entity_without_supporting_source_is_rejected(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            bundle = build_memory_book_source_bundle(conn, project="wisdom-weasel-rag-ime")
        plan = memory_book_plan_from_compile_output(
            {
                "entities": [
                    {
                        "entityId": "entity:hallucinated-exam",
                        "entityType": "event",
                        "canonicalName": "八月考试",
                    }
                ]
            },
            project="wisdom-weasel-rag-ime",
            provider="deepseek",
            model="deepseek-v4-flash",
            source_bundle=bundle,
        )

        self.assertFalse(any(item["op"] == "upsert_memory_entity" for item in plan["diffs"]))
        self.assertIn("memory_entity_evidence_mismatch:entity:hallucinated-exam", plan["metadata"]["warnings"])

    def test_memory_relation_with_unrelated_legal_evidence_is_rejected(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            bundle = build_memory_book_source_bundle(conn, project="wisdom-weasel-rag-ime")
        plan = memory_book_plan_from_compile_output(
            {
                "entities": [
                    {"entityId": "entity:rag", "entityType": "project", "canonicalName": "RAG 输入法", "sourceEventIds": [self.event_id]},
                    {"entityId": "entity:vector", "entityType": "concept", "canonicalName": "向量检索", "sourceEventIds": [self.event_id]},
                ],
                "relations": [
                    {
                        "sourceEntityId": "entity:rag",
                        "targetEntityId": "entity:vector",
                        "relationType": "related_to",
                        "fact": "用户喜欢海鲜",
                        "evidenceEventIds": [self.event_id],
                        "confidence": 0.9,
                    }
                ],
            },
            project="wisdom-weasel-rag-ime",
            provider="deepseek",
            model="deepseek-v4-flash",
            source_bundle=bundle,
        )

        self.assertEqual(sum(item["op"] == "upsert_memory_entity" for item in plan["diffs"]), 2)
        self.assertFalse(any(item["op"] == "upsert_memory_relation" for item in plan["diffs"]))
        self.assertTrue(any(str(item).startswith("memory_relation_evidence_mismatch:") for item in plan["metadata"]["warnings"]))

    def test_user_agent_prompt_enters_user_bundle_but_tool_receipt_stays_private(self) -> None:
        session = AgentSessionStore(self.db_path).create(
            title="memory owner",
            role_id="memory-owner",
            created_at_ms=now_ms(),
        )
        sources = AgentMemorySourceStore(self.db_path, project="wisdom-weasel-rag-ime")
        sources.checkpoint_user_message(
            session_id=str(session["id"]),
            pi_entry_id="user-entry",
            turn_id="turn-1",
            text="用户今天讨论输入法记忆重构",
            created_at_ms=now_ms(),
        )
        sources.checkpoint_tool_receipt(
            {
                "state": "applied",
                "sessionId": str(session["id"]),
                "approvalId": "private-tool",
                "receipt": {"mutationApplied": True, "summary": "Agent 私有工具执行细节"},
            },
            created_at_ms=now_ms(),
        )
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            bundle = build_memory_book_source_bundle(conn, project="wisdom-weasel-rag-ime", after_event_id=0)
        source_text = " ".join(str(item.get("text") or "") for item in bundle["recentEvents"])

        self.assertIn("用户今天讨论输入法记忆重构", source_text)
        self.assertNotIn("Agent 私有工具执行细节", source_text)

    def test_deleted_and_archived_tool_events_do_not_keep_incremental_compile_pending(self) -> None:
        session = AgentSessionStore(self.db_path).create(
            title="private source",
            role_id="private-agent",
            created_at_ms=now_ms(),
        )
        sources = AgentMemorySourceStore(self.db_path, project="wisdom-weasel-rag-ime")
        tool = sources.checkpoint_tool_receipt(
            {
                "state": "applied",
                "sessionId": str(session["id"]),
                "approvalId": "trailing-private-tool",
                "receipt": {"mutationApplied": True, "summary": "只能由 Agent 自己看到的结果"},
            },
            created_at_ms=now_ms(),
        )
        deleted_event_id = int(
            self.core.record_event(
                InputEvent(
                    event_id=None,
                    created_at_ms=now_ms(),
                    source="manual",
                    committed_text="无法合并的原子碎片",
                    privacy_disposition="allowed",
                    project="wisdom-weasel-rag-ime",
                )
            ).split(":", 1)[1]
        )
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute(
                "UPDATE agent_memory_sources SET status = 'archived' WHERE source_id = ?",
                (tool["source"]["sourceId"],),
            )
            conn.execute("UPDATE memory_state SET deleted = 1 WHERE event_id = ?", (deleted_event_id,))
            conn.execute(
                """
                INSERT INTO memory_compile_state(
                    project, last_compiled_event_id, last_run_ms, pending_event_count, last_bundle_hash
                ) VALUES ('wisdom-weasel-rag-ime', ?, 1, 0, '')
                ON CONFLICT(project) DO UPDATE SET last_compiled_event_id = excluded.last_compiled_event_id
                """,
                (self.event_id,),
            )
            bundle = build_memory_book_source_bundle(conn, project="wisdom-weasel-rag-ime")
            state = memory_compile_state(conn, project="wisdom-weasel-rag-ime")
            due, reason, _ = memory_compile_due(
                conn,
                project="wisdom-weasel-rag-ime",
                idle_ms=24 * 60 * 60 * 1000,
                current_ms=now_ms(),
            )

        self.assertEqual(bundle["recentEvents"], [])
        self.assertEqual(bundle["cursor"]["pendingEventCount"], 0)
        self.assertEqual(state["pendingEventCount"], 0)
        self.assertFalse(due)
        self.assertEqual(reason, "not_due")

    def test_existing_entity_identity_is_stable_and_stale_draft_cannot_overwrite(self) -> None:
        store = MemoryGraphStore(self.db_path)
        store.upsert_entity(
            entity_id="entity:stable-project",
            entity_type="project",
            name="RAG 输入法",
            project="wisdom-weasel-rag-ime",
        )
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            bundle = build_memory_book_source_bundle(conn, project="wisdom-weasel-rag-ime", after_event_id=0)

        mismatch = memory_book_plan_from_compile_output(
            {
                "entities": [
                    {
                        "entityId": "entity:stable-project",
                        "entityType": "project",
                        "canonicalName": "向量检索",
                        "sourceEventIds": [self.event_id],
                    }
                ]
            },
            project="wisdom-weasel-rag-ime",
            provider="deepseek",
            model="deepseek-v4-flash",
            source_bundle=bundle,
        )
        self.assertFalse(any(item["op"] == "upsert_memory_entity" for item in mismatch["diffs"]))
        self.assertIn(
            "memory_entity_identity_mismatch:entity:stable-project",
            mismatch["metadata"]["warnings"],
        )

        plan = memory_book_plan_from_compile_output(
            {
                "entities": [
                    {
                        "entityId": "entity:stable-project",
                        "entityType": "project",
                        "canonicalName": "RAG 输入法",
                        "sourceEventIds": [self.event_id],
                    }
                ]
            },
            project="wisdom-weasel-rag-ime",
            provider="deepseek",
            model="deepseek-v4-flash",
            source_bundle=bundle,
        )
        entity_diff = next(item for item in plan["diffs"] if item["op"] == "upsert_memory_entity")
        self.assertEqual(entity_diff["payload"]["expectedRevision"], 1)
        store.upsert_entity(
            entity_id="entity:stable-project",
            entity_type="project",
            name="RAG 输入法",
            description="并发更新",
            project="wisdom-weasel-rag-ime",
            expected_revision=1,
        )
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            with self.assertRaisesRegex(ValueError, "revision conflict"):
                apply_memory_book_plan(conn, plan)
            row = conn.execute(
                "SELECT canonical_name, description, revision FROM memory_entities WHERE entity_id = 'entity:stable-project'"
            ).fetchone()
        self.assertEqual(tuple(row), ("RAG 输入法", "并发更新", 2))

        base_bundle = {
            "recentEvents": [
                {
                    "eventId": self.event_id,
                    "sourceEventIds": [self.event_id],
                    "text": "RAG 输入法多路召回方案",
                }
            ],
            "cursor": {"pendingEventCount": 1},
        }
        generated_ids = []
        for project in ("project-a", "project-b"):
            generated = memory_book_plan_from_compile_output(
                {
                    "entities": [
                        {
                            "entityType": "project",
                            "canonicalName": "RAG 输入法",
                            "sourceEventIds": [self.event_id],
                        }
                    ]
                },
                project=project,
                provider="deepseek",
                model="deepseek-v4-flash",
                source_bundle=base_bundle,
            )
            generated_ids.append(
                next(item for item in generated["diffs"] if item["op"] == "upsert_memory_entity")["targetId"]
            )
        self.assertNotEqual(*generated_ids)

    def test_relation_correction_closes_old_fact_and_rollback_restores_history(self) -> None:
        old_time = now_ms() - 20_000
        old_event_id = int(
            self.core.record_event(
                InputEvent(
                    event_id=None,
                    created_at_ms=old_time,
                    source="manual",
                    committed_text="用户将在八月参加考试",
                    privacy_disposition="allowed",
                    project="wisdom-weasel-rag-ime",
                )
            ).split(":", 1)[1]
        )
        store = MemoryGraphStore(self.db_path)
        store.upsert_entity(
            entity_id="entity:user",
            entity_type="person",
            name="用户",
            project="wisdom-weasel-rag-ime",
        )
        store.upsert_entity(
            entity_id="entity:exam",
            entity_type="event",
            name="考试",
            project="wisdom-weasel-rag-ime",
        )
        store.upsert_relation(
            relation_id="relation:exam-august",
            source_entity_id="entity:user",
            target_entity_id="entity:exam",
            relation_type="plans",
            fact="用户将在八月参加考试",
            idempotency_key="exam-august-v1",
            sources=[{"sourceType": "input_event", "sourceId": str(old_event_id)}],
            project="wisdom-weasel-rag-ime",
            valid_from_ms=old_time,
        )
        correction_time = now_ms()
        correction_event_id = int(
            self.core.record_event(
                InputEvent(
                    event_id=None,
                    created_at_ms=correction_time,
                    source="manual",
                    committed_text="考试改到九月，八月安排作废",
                    privacy_disposition="allowed",
                    project="wisdom-weasel-rag-ime",
                )
            ).split(":", 1)[1]
        )
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            bundle = build_memory_book_source_bundle(
                conn,
                project="wisdom-weasel-rag-ime",
                after_event_id=old_event_id,
            )
        plan = memory_book_plan_from_compile_output(
            {
                "relations": [
                    {
                        "sourceEntityId": "entity:user",
                        "targetEntityId": "entity:exam",
                        "relationType": "plans",
                        "fact": "用户将在九月参加考试",
                        "evidenceEventIds": [correction_event_id],
                        "confidence": 0.9,
                    }
                ],
                "relationRetractions": [
                    {
                        "relationId": "relation:exam-august",
                        "reason": "考试从八月改到九月",
                        "evidenceEventIds": [correction_event_id],
                    }
                ],
            },
            project="wisdom-weasel-rag-ime",
            provider="deepseek",
            model="deepseek-v4-flash",
            source_bundle=bundle,
        )
        report = inspect_memory_book_plan(plan)
        self.assertTrue(report["ok"], report)
        close_diff = next(item for item in plan["diffs"] if item["op"] == "close_memory_relation")
        close_at = int(close_diff["payload"]["validToMs"])
        new_relation_id = next(
            item["targetId"] for item in plan["diffs"] if item["op"] == "upsert_memory_relation"
        )

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            apply_memory_book_plan(conn, plan)
            principal = MemoryGraphPrincipal(project="wisdom-weasel-rag-ime")
            current = store.expand(principal, anchor_ids=["entity:user"], as_of_ms=close_at + 1)
            historical = store.expand(principal, anchor_ids=["entity:user"], as_of_ms=old_time + 1)
            self.assertEqual({item["relationId"] for item in current["relations"]}, {new_relation_id})
            self.assertEqual(
                {item["relationId"] for item in historical["relations"]},
                {"relation:exam-august"},
            )
            rollback_memory_book_run(conn, run_id=plan["runId"])

        restored = store.expand(
            MemoryGraphPrincipal(project="wisdom-weasel-rag-ime"),
            anchor_ids=["entity:user"],
            as_of_ms=close_at + 1,
        )
        self.assertEqual(
            {item["relationId"] for item in restored["relations"]},
            {"relation:exam-august"},
        )

    def _write_sample_plan(self) -> Path:
        plan = memory_book_plan_from_compile_output(
            sample_compile_output(self.event_id),
            project="wisdom-weasel-rag-ime",
            provider="deepseek",
            model="deepseek-v4-flash",
        )
        path = Path(self.tmp.name) / "memory-book-plan.json"
        path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
        return path


def sample_compile_output(event_id: int) -> dict[str, object]:
    return {
        "schemaVersion": "rag-ime.memory-book-compile.v1",
        "dailyBooks": [
            {
                "bookKey": "2026-07-06",
                "title": "RAG 输入法多路召回方案",
                "summary": "用户希望借鉴 VCP 的 BM25、向量、TagMemo 和 Time。",
                "tags": ["RAG", "输入法", "VCP"],
                "surfaceHints": ["多路召回", "TagMemo"],
                "queryExpansions": ["VCP RAG", "Daily Book"],
                "sourceEventIds": [event_id],
                "confidence": 0.86,
            }
        ],
        "memoryAtoms": [
            {
                "atomId": "atom:vcp-style-rag-core",
                "kind": "project_fact",
                "canonicalText": "RAG core 应使用 BM25、向量、TagMemo 和 Time 多路召回。",
                "summary": "用户希望底层 RAG core 成为通用上下文预测层。",
                "tags": ["RAG core", "BM25", "TagMemo"],
                "aliases": ["VCP式RAG"],
                "surfaceHints": ["混合召回", "语义图召回"],
                "queryExpansions": ["输入法 RAG", "千问三 Qwen3"],
                "sourceEventIds": [event_id],
                "directCandidateAllowed": False,
                "confidence": 0.88,
                "qualityScore": 0.82,
            }
        ],
        "tagEdges": [
            {"src": "输入法", "dst": "大模型", "edgeType": "related", "weight": 0.72, "evidenceEventIds": [event_id]}
        ],
        "phraseCandidates": [
            {
                "text": "多路召回",
                "pinyin": "duo lu zhao hui",
                "tags": ["RAG", "检索"],
                "sourceEventIds": [event_id],
                "weight": 0.74,
                "reason": "用户反复讨论的领域术语",
            }
        ],
        "warnings": [],
    }


if __name__ == "__main__":
    unittest.main()
