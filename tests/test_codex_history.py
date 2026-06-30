from __future__ import annotations

import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from rag_ime.cli import main
from rag_ime.codex_history import (
    evaluate_suggestions,
    input_event_from_codex_record,
    load_codex_history_records,
    load_eval_cases,
)
from rag_ime.local_sqlite_core import LocalSqliteCoreClient


class CodexHistoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-codex-history-")
        self.root = Path(self.tmp.name)
        self.history = self.root / "codex.jsonl"
        self.history.write_text(
            "\n".join(
                [
                    json.dumps(
                        {
                            "type": "response_item",
                            "created_at": "2026-06-30T10:00:00Z",
                            "payload": {
                                "role": "user",
                                "content": [
                                    {
                                        "type": "input_text",
                                        "text": "我想把 RAG 输入法接入 Squirrel, 让候选词使用本地记忆。",
                                    }
                                ],
                            },
                        },
                        ensure_ascii=False,
                    ),
                    "{not valid json",
                    json.dumps(
                        {
                            "event_msg": {
                                "message": "FTS5 排序和 local-first 记忆要能服务 Codex 历史评测。",
                                "timestamp_ms": 1782813600000,
                            }
                        },
                        ensure_ascii=False,
                    ),
                ]
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_load_codex_history_records_skips_invalid_jsonl_and_extracts_text(self) -> None:
        records = load_codex_history_records(self.history, limit=10)
        self.assertEqual(len(records), 2)
        self.assertIn("RAG 输入法", records[0].text)
        self.assertIn("FTS5 排序", records[1].text)
        self.assertIn("codex-history", records[0].tags)
        self.assertEqual(records[0].role, "user")
        self.assertGreater(records[0].created_at_ms, 0)

    def test_record_can_be_converted_to_input_event(self) -> None:
        record = load_codex_history_records(self.history, limit=1)[0]
        event = input_event_from_codex_record(record, project="wisdom-weasel-rag-ime")
        self.assertEqual(event.source, "codex_history")
        self.assertEqual(event.schema_id, "codex_history")
        self.assertEqual(event.app, "codex")
        self.assertIn("codex_history:codex.jsonl:1", event.recent_context)

    def test_cli_import_dry_run_does_not_write_database(self) -> None:
        db_path = self.root / "dry-run.sqlite"
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            code = main(
                [
                    "--db-path",
                    str(db_path),
                    "import-codex-history",
                    "--path",
                    str(self.history),
                    "--dry-run",
                ]
            )
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["schemaVersion"], "rag-ime.codex-history-import.v1")
        self.assertEqual(payload["records"], 2)
        self.assertEqual(payload["imported"], 0)
        if db_path.exists():
            with sqlite3.connect(db_path) as conn:
                table = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'input_events'"
                ).fetchone()
            self.assertIsNone(table)

    def test_cli_import_and_eval_cases(self) -> None:
        db_path = self.root / "codex-history.sqlite"
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            import_code = main(
                [
                    "--db-path",
                    str(db_path),
                    "import-codex-history",
                    "--path",
                    str(self.history),
                    "--project",
                    "wisdom-weasel-rag-ime",
                ]
            )
        self.assertEqual(import_code, 0)
        import_payload = json.loads(stdout.getvalue())
        self.assertEqual(import_payload["imported"], 2)
        self.assertEqual(import_payload["duplicateSkipped"], 0)

        second_stdout = io.StringIO()
        with redirect_stdout(second_stdout):
            second_import_code = main(
                [
                    "--db-path",
                    str(db_path),
                    "import-codex-history",
                    "--path",
                    str(self.history),
                    "--project",
                    "wisdom-weasel-rag-ime",
                ]
            )
        self.assertEqual(second_import_code, 0)
        second_payload = json.loads(second_stdout.getvalue())
        self.assertEqual(second_payload["imported"], 0)
        self.assertEqual(second_payload["duplicateSkipped"], 2)

        cases_file = self.root / "cases.jsonl"
        cases_file.write_text(
            json.dumps(
                {
                    "id": "squirrel-rag",
                    "query": "Squirrel RAG 输入法候选",
                    "expectedTerms": ["Squirrel", "本地记忆"],
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        eval_stdout = io.StringIO()
        with redirect_stdout(eval_stdout):
            eval_code = main(
                [
                    "--db-path",
                    str(db_path),
                    "eval-codex-history",
                    "--cases-file",
                    str(cases_file),
                    "--match",
                    "all",
                ]
            )
        self.assertEqual(eval_code, 0)
        report = json.loads(eval_stdout.getvalue())
        self.assertEqual(report["schemaVersion"], "rag-ime.codex-history-eval.v1")
        self.assertEqual(report["passed"], 1)
        self.assertEqual(report["passRate"], 1.0)

    def test_load_eval_cases_and_match_results(self) -> None:
        cases_file = self.root / "manual-cases.jsonl"
        cases_file.write_text(
            json.dumps({"query": "FTS5", "expected_terms": "local-first"}, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        cases = load_eval_cases(cases_file)
        self.assertEqual(cases[0].expected_terms, ("local-first",))
        core = LocalSqliteCoreClient(self.root / "manual.sqlite")
        core.record_event(
            input_event_from_codex_record(
                load_codex_history_records(self.history, limit=2)[1],
                project="wisdom-weasel-rag-ime",
            )
        )
        suggestions = core.suggest_for_input(current_input="FTS5", project="wisdom-weasel-rag-ime")
        result = evaluate_suggestions(cases[0], suggestions, match="any")
        self.assertTrue(result.passed)


if __name__ == "__main__":
    unittest.main()
