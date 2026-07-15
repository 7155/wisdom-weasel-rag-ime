from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rag_ime.rime_rank_export import (
    apply_rime_rank_export,
    preview_rime_rank_export,
    record_rime_rank_feedback,
    rollback_rime_rank_export,
)


class RimeRankExportTests(unittest.TestCase):
    def test_preview_apply_and_rollback_rank_feedback_dictionary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "rag-ime.sqlite"
            target = Path(tmp) / "rag_ime.user.dict.yaml"
            record_rime_rank_feedback(
                db_path,
                preedit="ji xu wan shan",
                accepted_text="继续完善",
                action="accepted",
                project="wisdom-weasel-rag-ime",
                candidate_rank=1,
            )
            record_rime_rank_feedback(
                db_path,
                preedit="ji xu wan shan",
                rejected_text="继续完美",
                accepted_text="继续完善",
                action="correction_pair",
                project="wisdom-weasel-rag-ime",
                candidate_rank=2,
            )

            preview = preview_rime_rank_export(db_path, project="wisdom-weasel-rag-ime")
            self.assertEqual(preview["schemaVersion"], "rag-ime.rime-rank-export.v1")
            self.assertIn("继续完善\tji xu wan shan", preview["yaml"])
            self.assertNotIn("继续完美\tji xu wan shan", preview["yaml"])

            target.write_text("old\n", encoding="utf-8")
            applied = apply_rime_rank_export(
                db_path,
                target_file=target,
                project="wisdom-weasel-rag-ime",
                confirm_text="APPLY_RIME_RANK_EXPORT",
            )
            self.assertTrue(applied["applied"])
            self.assertIn("继续完善\tji xu wan shan", target.read_text(encoding="utf-8"))

            rolled_back = rollback_rime_rank_export(target_file=target, backup_file=str(applied["backupFile"]))
            self.assertTrue(rolled_back["rolledBack"])
            self.assertEqual(target.read_text(encoding="utf-8"), "old\n")

    def test_yon_feedback_is_exported_under_canonical_yong_spelling(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "rag-ime.sqlite"
            record_rime_rank_feedback(
                db_path,
                preedit="yon",
                rejected_text="哟",
                accepted_text="用",
                action="correction_pair",
                candidate_rank=4,
                metadata={"candidateSource": "rime"},
            )
            record_rime_rank_feedback(
                db_path,
                preedit="yo n",
                accepted_text="用",
                action="accepted",
                candidate_rank=2,
                metadata={"candidateSource": "rime"},
            )

            preview = preview_rime_rank_export(db_path)

            self.assertEqual(preview["entryCount"], 1)
            self.assertEqual(preview["entries"][0]["text"], "用")
            self.assertEqual(preview["entries"][0]["pinyin"], "yong")
            self.assertIn("用\tyong\t", preview["yaml"])
            self.assertNotIn("\tyon\t", preview["yaml"])

    def test_weak_top_candidate_acceptance_requires_repetition(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "rag-ime.sqlite"
            record_rime_rank_feedback(
                db_path,
                preedit="chi xu you hua",
                accepted_text="持续优化",
                action="accepted",
                candidate_rank=1,
                context_hash="ctx-1",
            )
            self.assertEqual(preview_rime_rank_export(db_path)["entryCount"], 0)

            record_rime_rank_feedback(
                db_path,
                preedit="chi xu you hua",
                accepted_text="持续优化",
                action="accepted",
                candidate_rank=1,
                context_hash="ctx-2",
            )
            preview = preview_rime_rank_export(db_path)
            self.assertEqual(preview["entryCount"], 1)
            self.assertEqual(preview["entries"][0]["positiveCount"], 2)

    def test_single_character_requires_more_passive_acceptance_but_correction_is_immediate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            passive_db = Path(tmp) / "passive.sqlite"
            for index in range(2):
                record_rime_rank_feedback(
                    passive_db,
                    preedit="yong",
                    accepted_text="用",
                    action="accepted",
                    candidate_rank=1,
                    context_hash=f"ctx-{index}",
                )
            self.assertEqual(preview_rime_rank_export(passive_db)["entryCount"], 0)
            record_rime_rank_feedback(
                passive_db,
                preedit="yong",
                accepted_text="用",
                action="accepted",
                candidate_rank=1,
                context_hash="ctx-3",
            )
            self.assertEqual(preview_rime_rank_export(passive_db)["entries"][0]["text"], "用")

            correction_db = Path(tmp) / "correction.sqlite"
            record_rime_rank_feedback(
                correction_db,
                preedit="yong",
                rejected_text="永",
                accepted_text="用",
                action="correction_pair",
                candidate_rank=2,
            )
            preview = preview_rime_rank_export(correction_db)
            self.assertEqual([entry["text"] for entry in preview["entries"]], ["用"])
            self.assertNotIn("永\tyong", preview["yaml"])

    def test_negative_feedback_can_suppress_an_old_preference(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "rag-ime.sqlite"
            for index in range(2):
                record_rime_rank_feedback(
                    db_path,
                    preedit="mo xing",
                    accepted_text="模型",
                    action="accepted",
                    candidate_rank=1,
                    context_hash=f"accept-{index}",
                )
            record_rime_rank_feedback(
                db_path,
                preedit="mo xing",
                rejected_text="模型",
                action="downrank",
                context_hash="reject-1",
            )

            self.assertEqual(preview_rime_rank_export(db_path)["entryCount"], 0)

    def test_model_and_rag_feedback_never_enters_the_rime_user_dictionary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "rag-ime.sqlite"
            for source, text in (("model", "模型续写"), ("active_rag", "知识召回")):
                record_rime_rank_feedback(
                    db_path,
                    preedit="ce shi",
                    accepted_text=text,
                    action="boost",
                    candidate_rank=1,
                    metadata={"candidate": {"sourceType": source}},
                )
            record_rime_rank_feedback(
                db_path,
                preedit="ce shi",
                accepted_text="测试",
                action="boost",
                candidate_rank=3,
                metadata={"candidateSource": "rime"},
            )

            preview = preview_rime_rank_export(db_path)

            self.assertEqual([entry["text"] for entry in preview["entries"]], ["测试"])
            self.assertNotIn("模型续写", preview["yaml"])
            self.assertNotIn("知识召回", preview["yaml"])

    def test_duplicate_delivery_for_one_context_is_counted_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "rag-ime.sqlite"
            for _ in range(3):
                record_rime_rank_feedback(
                    db_path,
                    preedit="shu ru fa",
                    accepted_text="输入法",
                    action="accepted",
                    candidate_rank=1,
                    context_hash="same-selection",
                )

            self.assertEqual(preview_rime_rank_export(db_path)["entryCount"], 0)

    def test_downrank_action_does_not_accidentally_boost_accepted_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "rag-ime.sqlite"
            record_rime_rank_feedback(
                db_path,
                preedit="pu tong",
                accepted_text="不应提升",
                action="downrank",
                candidate_rank=1,
            )

            self.assertEqual(preview_rime_rank_export(db_path)["entryCount"], 0)


if __name__ == "__main__":
    unittest.main()
