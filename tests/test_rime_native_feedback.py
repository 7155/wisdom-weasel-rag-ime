from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from rag_ime.contracts.json_schema import validate_contract
from rag_ime.debug_server import DebugImeService, DebugServerConfig
from rag_ime.rime_native_feedback import record_native_rime_selection
from rag_ime.rime_rank_export import preview_rime_rank_export


class NativeRimeFeedbackTests(unittest.TestCase):
    def test_contract_and_service_route_store_native_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "rag-ime.sqlite"
            payload = {
                "schemaVersion": "rag-ime.rime-rank-selection.v1",
                "selectionId": "service-selection",
                "sourceType": "rime",
                "privacyDisposition": "allowed",
                "preedit": "chi xu you hua",
                "acceptedText": "持续优化",
                "candidateRank": 2,
                "shownCandidateCount": 8,
                "app": "com.apple.TextEdit",
            }
            validate_contract(payload, "rime-rank-selection.v1.json")
            service = DebugImeService(DebugServerConfig(db_path=db_path, seed_if_empty=False))

            response = service.rime_rank_feedback(payload)

            self.assertTrue(response["recorded"])
            with closing(sqlite3.connect(db_path)) as conn, conn:
                row = conn.execute(
                    "SELECT preedit, accepted_text, candidate_rank FROM rime_rank_feedback"
                ).fetchone()
            self.assertEqual(row, ("chi xu you hua", "持续优化", 2))

    def test_non_top_rime_selection_records_a_reviewable_correction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "rag-ime.sqlite"
            response = record_native_rime_selection(
                {
                    "schemaVersion": "rag-ime.rime-rank-selection.v1",
                    "selectionId": "selection-1",
                    "sourceType": "rime",
                    "privacyDisposition": "allowed",
                    "preedit": "yon",
                    "acceptedText": "用",
                    "rejectedText": "哟",
                    "candidateRank": 4,
                    "shownCandidateCount": 8,
                    "app": "com.apple.TextEdit",
                },
                db_path=db_path,
            )

            self.assertTrue(response["recorded"])
            self.assertEqual(response["action"], "correction_pair")
            preview = preview_rime_rank_export(db_path)
            self.assertEqual(preview["entries"][0]["text"], "用")
            self.assertEqual(preview["entries"][0]["pinyin"], "yong")

    def test_duplicate_delivery_is_deduplicated_by_selection_id_at_export(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "rag-ime.sqlite"
            payload = {
                "schemaVersion": "rag-ime.rime-rank-selection.v1",
                "selectionId": "one-physical-selection",
                "sourceType": "rime",
                "privacyDisposition": "allowed",
                "preedit": "shu ru fa",
                "acceptedText": "输入法",
                "candidateRank": 1,
            }
            record_native_rime_selection(payload, db_path=db_path)
            record_native_rime_selection(payload, db_path=db_path)

            self.assertEqual(preview_rime_rank_export(db_path)["entryCount"], 0)
            with closing(sqlite3.connect(db_path)) as conn, conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM rime_rank_feedback").fetchone()[0], 2)

    def test_model_or_rag_source_is_rejected_before_storage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "rag-ime.sqlite"
            with self.assertRaisesRegex(ValueError, "sourceType=rime"):
                record_native_rime_selection(
                    {
                        "schemaVersion": "rag-ime.rime-rank-selection.v1",
                        "selectionId": "bad-source",
                        "sourceType": "model",
                        "privacyDisposition": "allowed",
                        "preedit": "ce shi",
                        "acceptedText": "模型候选",
                        "candidateRank": 1,
                    },
                    db_path=db_path,
                )

            self.assertFalse(db_path.exists())

    def test_dry_run_validates_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "rag-ime.sqlite"
            response = record_native_rime_selection(
                {
                    "schemaVersion": "rag-ime.rime-rank-selection.v1",
                    "selectionId": "dry-run",
                    "sourceType": "rime",
                    "privacyDisposition": "allowed",
                    "preedit": "yong",
                    "acceptedText": "用",
                    "candidateRank": 1,
                    "dryRun": True,
                },
                db_path=db_path,
            )

            self.assertTrue(response["dryRun"])
            self.assertFalse(response["recorded"])
            self.assertFalse(response["noStore"])
            self.assertEqual(response["storageReceipt"]["outcome"], "dry_run")
            self.assertFalse(db_path.exists())

    def test_missing_unknown_and_sensitive_privacy_return_no_store_without_database(self) -> None:
        base = {
            "schemaVersion": "rag-ime.rime-rank-selection.v1",
            "selectionId": "privacy-gate",
            "sourceType": "rime",
            "preedit": "mi ma",
            "acceptedText": "密码",
            "candidateRank": 1,
        }
        cases = (
            ({}, "unknown", "missing_privacy_disposition"),
            ({"privacyDisposition": "unknown"}, "unknown", "explicit_unknown"),
            (
                {"privacyDisposition": "allowed", "sensitiveField": True},
                "sensitive",
                "sensitive_foreground_flag",
            ),
        )
        for extra, disposition, reason in cases:
            with self.subTest(disposition=disposition, reason=reason), tempfile.TemporaryDirectory() as tmp:
                db_path = Path(tmp) / "rag-ime.sqlite"
                response = record_native_rime_selection({**base, **extra}, db_path=db_path)

                self.assertTrue(response["ok"])
                self.assertTrue(response["noStore"])
                self.assertFalse(response["recorded"])
                self.assertEqual(response["privacyAssessment"]["disposition"], disposition)
                self.assertEqual(response["privacyAssessment"]["reason"], reason)
                self.assertEqual(response["storageReceipt"]["outcome"], "no_store")
                self.assertFalse(db_path.exists())


if __name__ == "__main__":
    unittest.main()
