from __future__ import annotations

import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing, redirect_stdout
from pathlib import Path

import rag_ime.cli as cli_module
from rag_ime.cli import main
from rag_ime.local_sqlite_core import LocalSqliteCoreClient
from rag_ime.memory_book_compiler import (
    apply_stored_memory_book_run,
    inspect_memory_book_plan,
    memory_book_plan_from_compile_output,
    rollback_memory_book_run,
    store_memory_book_plan,
)
from rag_ime.models import InputEvent
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
        with closing(sqlite3.connect(self.db_path)) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM memory_books").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM memory_cleanup_runs WHERE run_id LIKE 'memory_book_%'").fetchone()[0], 0)

    def test_memory_book_compile_requires_source_event_ids(self) -> None:
        output = sample_compile_output(self.event_id)
        output["dailyBooks"][0]["sourceEventIds"] = []
        plan = memory_book_plan_from_compile_output(output, project="wisdom-weasel-rag-ime", provider="deepseek", model="deepseek-v4-flash")

        report = inspect_memory_book_plan(plan)

        self.assertFalse(report["ok"])
        self.assertTrue(any(item["code"] == "missing_source_event_ids" for item in report["errors"]))

    def test_memory_book_compile_backfills_source_ids_from_bundle(self) -> None:
        output = sample_compile_output(self.event_id)
        output["dailyBooks"][0]["sourceEventIds"] = []
        output["memoryAtoms"][0]["sourceEventIds"] = []
        output["tagEdges"][0]["evidenceEventIds"] = []
        output["phraseCandidates"][0]["sourceEventIds"] = []
        bundle = {
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

    def test_memory_book_compile_uses_generic_source_archive_when_model_returns_empty(self) -> None:
        bundle = {
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

        self.assertTrue(report["ok"])
        self.assertEqual(report["counts"]["memoryBooks"], 1)
        self.assertEqual(report["counts"]["memoryAtoms"], 2)
        self.assertGreaterEqual(report["counts"]["phraseCandidates"], 3)
        self.assertIn("local_source_bundle_fallback_used", plan["metadata"]["warnings"])
        atoms = [item["payload"] for item in plan["diffs"] if item["op"] == "upsert_memory_atom"]
        duplicate = next(item for item in atoms if item["canonicalText"].startswith("周五上午十点"))
        self.assertEqual(duplicate["sourceEventIds"], [self.event_id, self.event_id + 1])
        self.assertTrue(all(item["kind"] == "source_event_archive" for item in atoms))
        serialized = json.dumps(plan, ensure_ascii=False)
        for injected_term in ("DeepSeek", "Squirrel", "RAG 输入法", "面试展示", "eval gate"):
            self.assertNotIn(injected_term, serialized)

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
            {"text": "多路召回", "tags": ["RAG", "检索"], "sourceEventIds": [event_id], "weight": 0.74}
        ],
        "warnings": [],
    }


if __name__ == "__main__":
    unittest.main()
