from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import closing, redirect_stdout
from pathlib import Path

from rag_ime.ime_demo_pack import (
    DEFAULT_FIXTURE_PATH,
    LIVE_CONFIRMATION,
    assert_isolated_demo_db_path,
    main,
    reset_demo_database,
    seed_demo_database,
    verify_demo_database,
)


class ImeFirstDemoPackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-first-demo-")
        self.db_path = Path(self.tmp.name) / "demo.sqlite"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_seed_verify_reset_is_deterministic_and_traceable(self) -> None:
        first = seed_demo_database(self.db_path, reset=True)
        first_report = verify_demo_database(self.db_path)
        second = seed_demo_database(self.db_path, reset=True)
        second_report = verify_demo_database(self.db_path)

        self.assertTrue(first_report["ok"], first_report)
        self.assertTrue(second_report["ok"], second_report)
        self.assertEqual(first["counts"], second["counts"])
        self.assertEqual(first_report["fixtureSha256"], second_report["fixtureSha256"])
        self.assertEqual(
            [item["text"] for item in first_report["checks"]["ragMemory"]["candidates"]],
            [item["text"] for item in second_report["checks"]["ragMemory"]["candidates"]],
        )
        self.assertGreater(first_report["checks"]["ragMemory"]["traceableCandidateCount"], 0)

        reset = reset_demo_database(self.db_path)
        self.assertTrue(reset["ok"])
        self.assertTrue(self.db_path.exists())
        self.assertEqual(reset["removed"]["inputEvents"], 5)
        self.assertEqual(verify_count(self.db_path, "input_events"), 0)
        self.assertEqual(verify_count(self.db_path, "memory_books"), 0)
        self.assertEqual(verify_count(self.db_path, "memory_atoms"), 0)
        self.assertEqual(verify_count(self.db_path, "memory_retrieval_docs"), 0)
        self.assertEqual(verify_count(self.db_path, "rime_rank_feedback"), 0)

    def test_demo_covers_pinyin_three_tab_candidates_rag_workbench_and_quiet_short_commit(self) -> None:
        seed_demo_database(self.db_path, reset=True)
        report = verify_demo_database(self.db_path)
        checks = report["checks"]

        self.assertEqual(
            report["sceneOrder"],
            ["ordinaryPinyin", "continuousTab", "ragMemory", "knowledgeWorkbench"],
        )
        self.assertEqual(checks["ordinaryPinyin"]["dictionaryEntry"]["text"], "用")
        self.assertEqual(checks["ordinaryPinyin"]["canonicalPinyin"], "yong")
        self.assertTrue(all(len(frame["candidates"]) == 3 for frame in checks["continuousTab"]["frames"]))
        self.assertTrue(all(frame["continuationTriggered"] for frame in checks["continuousTab"]["frames"]))
        self.assertTrue(checks["continuousTab"]["notEveryCommit"]["ok"])
        self.assertTrue(checks["ragMemory"]["ok"])
        self.assertTrue(checks["knowledgeWorkbench"]["contextInjected"])
        self.assertGreater(checks["knowledgeWorkbench"]["localEvidenceCount"], 0)
        self.assertFalse(checks["knowledgeWorkbench"]["networkCalled"])

    def test_unknown_and_sensitive_demo_fields_do_not_store(self) -> None:
        seed_demo_database(self.db_path, reset=True)
        report = verify_demo_database(self.db_path)
        no_store = report["checks"]["noStoreBaseline"]

        self.assertTrue(no_store["ok"])
        self.assertEqual(no_store["rowCountBefore"], no_store["rowCountAfter"])

    def test_guard_rejects_real_data_directory_and_seed_requires_clean_db(self) -> None:
        with self.assertRaises(ValueError):
            assert_isolated_demo_db_path(Path(self.tmp.name) / ".rag-ime-data" / "rag-ime.sqlite")
        with self.assertRaises(ValueError):
            assert_isolated_demo_db_path(self.db_path, live=True)

        seed_demo_database(self.db_path, reset=True)
        with self.assertRaises(ValueError):
            seed_demo_database(self.db_path)

    def test_live_opt_in_reset_preserves_unrelated_rows(self) -> None:
        from rag_ime.adapter import InputMethodAdapter
        from rag_ime.local_sqlite_core import LocalSqliteCoreClient

        core = LocalSqliteCoreClient(self.db_path)
        InputMethodAdapter(core, project="user-project").commit_text(
            "用户自己的数据",
            project="user-project",
            source="manual_commit",
            provider_name="ime-adapter",
            privacy_disposition="allowed",
        )
        seed_demo_database(
            self.db_path,
            reset=True,
            live=True,
            confirmation=LIVE_CONFIRMATION,
        )
        reset = reset_demo_database(
            self.db_path,
            live=True,
            confirmation=LIVE_CONFIRMATION,
        )

        self.assertEqual(reset["removed"]["inputEvents"], 5)
        self.assertEqual(verify_count(self.db_path, "input_events"), 1)
        self.assertEqual(read_only_texts(self.db_path), ["用户自己的数据"])
        self.assertEqual(verify_count(self.db_path, "memory_books"), 0)
        self.assertEqual(verify_count(self.db_path, "memory_atoms"), 0)
        self.assertGreaterEqual(verify_count(self.db_path, "memory_retrieval_docs"), 1)

    def test_fixture_is_public_safe_and_cli_uses_explicit_temp_path(self) -> None:
        source = DEFAULT_FIXTURE_PATH.read_text(encoding="utf-8")
        payload = json.loads(source)
        lowered = source.lower()

        self.assertEqual(payload["schemaVersion"], "rag-ime.ime-first-demo-pack.v1")
        self.assertNotIn("access_token", lowered)
        self.assertNotIn("secret_key", lowered)
        self.assertNotIn("api_key", lowered)
        report_path = Path(self.tmp.name) / "verify-report.json"
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(["seed", "--db-path", str(self.db_path), "--reset"]), 0)
            self.assertEqual(main(["verify", "--db-path", str(self.db_path), "--report", str(report_path)]), 0)
        self.assertTrue(json.loads(report_path.read_text(encoding="utf-8"))["ok"])


def verify_count(db_path: Path, table: str) -> int:
    import sqlite3

    with closing(sqlite3.connect(db_path)) as conn, conn:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def read_only_texts(db_path: Path) -> list[str]:
    import sqlite3

    with closing(sqlite3.connect(db_path)) as conn, conn:
        return [str(row[0]) for row in conn.execute("SELECT committed_text FROM input_events ORDER BY id")]


if __name__ == "__main__":
    unittest.main()
