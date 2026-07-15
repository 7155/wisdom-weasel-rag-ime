from __future__ import annotations

import tempfile
import unittest
import sqlite3
from pathlib import Path

from rag_ime.db import apply_database_migrations
from rag_ime.memory_ingest import upsert_memory_item
from rag_ime.rime_lexicon_review import (
    CONFIRM_TEXT,
    apply_reviewed_rime_lexicon,
    review_rime_lexicon,
    rollback_reviewed_rime_lexicon,
)
from rag_ime.rime_rank_export import record_rime_rank_feedback
from rag_ime.text_utils import now_ms


class RimeLexiconReviewTests(unittest.TestCase):
    def test_dsv4_memory_phrase_enters_review_but_not_dictionary_without_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "rag-ime.sqlite"
            rime_dir = root / "Rime"
            backup_root = root / "backups"
            rime_dir.mkdir()
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                apply_database_migrations(conn)
                timestamp = now_ms()
                upsert_memory_item(
                    conn,
                    memory_id="phrase:多路召回",
                    kind="phrase",
                    text="多路召回",
                    normalized_text="多路召回",
                    summary="memory-book phrase candidate",
                    source_event_id=None,
                    project="wisdom-weasel-rag-ime",
                    app="",
                    confidence=0.82,
                    quality_score=0.82,
                    status="approved",
                    privacy_class="local",
                    created_at_ms=timestamp,
                    updated_at_ms=timestamp,
                    metadata={
                        "reviewSource": "dsv4",
                        "reviewReason": "用户反复讨论的领域术语",
                        "pinyin": "duo lu zhao hui",
                        "sourceEventIds": [1, 2],
                    },
                    tags=("RAG",),
                    embedding_provider=None,
                )
                conn.commit()

            review = review_rime_lexicon(
                db_path,
                project="wisdom-weasel-rag-ime",
                rime_user_dir=rime_dir,
            )
            self.assertEqual(review["entryCount"], 1)
            self.assertEqual(review["entries"][0]["reviewSource"], "dsv4")
            self.assertEqual(review["entries"][0]["pinyin"], "duo lu zhao hui")
            self.assertFalse((rime_dir / "rag_ime_user.dict.yaml").exists())

            applied = apply_reviewed_rime_lexicon(
                db_path,
                rime_user_dir=rime_dir,
                backup_root=backup_root,
                project="wisdom-weasel-rag-ime",
                review_token=str(review["reviewToken"]),
                selected_keys=[str(review["entries"][0]["reviewKey"])],
                confirm_text=CONFIRM_TEXT,
            )
            self.assertTrue(applied["applied"])
            self.assertIn(
                "多路召回\tduo lu zhao hui\t",
                (rime_dir / "rag_ime_user.dict.yaml").read_text(encoding="utf-8"),
            )

    def test_review_apply_and_rollback_is_token_bound_and_transactional(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "rag-ime.sqlite"
            rime_dir = root / "Rime"
            backup_root = root / "backups"
            rime_dir.mkdir()
            custom = rime_dir / "luna_pinyin_simp.custom.yaml"
            custom.write_text("patch:\n  speller/algebra/+_:\n    - derive/^z/zh/\n", encoding="utf-8")
            for index in range(2):
                record_rime_rank_feedback(
                    db_path,
                    preedit="biao qing bao",
                    accepted_text="表情包",
                    action="accepted",
                    candidate_rank=1,
                    context_hash=f"context-{index}",
                )

            review = review_rime_lexicon(db_path)
            self.assertEqual(review["entryCount"], 1)
            self.assertTrue(review["reviewRequired"])
            self.assertEqual(len(str(review["reviewToken"])), 64)

            stale = apply_reviewed_rime_lexicon(
                db_path,
                rime_user_dir=rime_dir,
                backup_root=backup_root,
                review_token="stale",
                confirm_text=CONFIRM_TEXT,
            )
            self.assertEqual(stale["reason"], "review_token_stale")
            self.assertFalse((rime_dir / "rag_ime_user.dict.yaml").exists())

            applied = apply_reviewed_rime_lexicon(
                db_path,
                rime_user_dir=rime_dir,
                backup_root=backup_root,
                review_token=str(review["reviewToken"]),
                selected_keys=[str(review["entries"][0]["reviewKey"])],
                confirm_text=CONFIRM_TEXT,
            )
            self.assertTrue(applied["applied"])
            self.assertIn("表情包\tbiao qing bao\t", (rime_dir / "rag_ime_user.dict.yaml").read_text(encoding="utf-8"))
            umbrella_dictionary = (rime_dir / "rag_ime.dict.yaml").read_text(encoding="utf-8")
            self.assertIn("rag_ime_user", umbrella_dictionary)
            self.assertIn("use_preset_vocabulary: true", umbrella_dictionary)
            updated_custom = custom.read_text(encoding="utf-8")
            self.assertIn("translator/dictionary: rag_ime", updated_custom)
            self.assertIn("derive/^z/zh/", updated_custom)
            self.assertEqual(review_rime_lexicon(db_path, rime_user_dir=rime_dir)["entryCount"], 0)

            rolled_back = rollback_reviewed_rime_lexicon(
                rollback_id=str(applied["rollbackId"]),
                backup_root=backup_root,
            )
            self.assertTrue(rolled_back["rolledBack"])
            self.assertFalse((rime_dir / "rag_ime_user.dict.yaml").exists())
            self.assertFalse((rime_dir / "rag_ime.dict.yaml").exists())
            self.assertNotIn("translator/dictionary", custom.read_text(encoding="utf-8"))
            self.assertEqual(review_rime_lexicon(db_path, rime_user_dir=rime_dir)["entryCount"], 1)

    def test_incremental_review_preserves_applied_dictionary_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "rag-ime.sqlite"
            rime_dir = root / "Rime"
            rime_dir.mkdir()
            for preedit, accepted_text in (("biao qing bao", "表情包"), ("shu ru fa", "输入法")):
                for index in range(2):
                    record_rime_rank_feedback(
                        db_path,
                        preedit=preedit,
                        accepted_text=accepted_text,
                        action="accepted",
                        candidate_rank=1,
                        context_hash=f"{preedit}-{index}",
                    )

            first_review = review_rime_lexicon(db_path, rime_user_dir=rime_dir)
            first_entry = next(entry for entry in first_review["entries"] if entry["text"] == "表情包")
            first_apply = apply_reviewed_rime_lexicon(
                db_path,
                rime_user_dir=rime_dir,
                backup_root=root / "backups",
                review_token=str(first_review["reviewToken"]),
                selected_keys=[str(first_entry["reviewKey"])],
                confirm_text=CONFIRM_TEXT,
            )
            self.assertTrue(first_apply["applied"])

            second_review = review_rime_lexicon(db_path, rime_user_dir=rime_dir)
            self.assertEqual([entry["text"] for entry in second_review["entries"]], ["输入法"])
            second_apply = apply_reviewed_rime_lexicon(
                db_path,
                rime_user_dir=rime_dir,
                backup_root=root / "backups",
                review_token=str(second_review["reviewToken"]),
                selected_keys=[str(second_review["entries"][0]["reviewKey"])],
                confirm_text=CONFIRM_TEXT,
            )
            self.assertTrue(second_apply["applied"])
            dictionary = (rime_dir / "rag_ime_user.dict.yaml").read_text(encoding="utf-8")
            self.assertIn("表情包\tbiao qing bao\t", dictionary)
            self.assertIn("输入法\tshu ru fa\t", dictionary)
            self.assertEqual(review_rime_lexicon(db_path, rime_user_dir=rime_dir)["entryCount"], 0)

    def test_existing_dictionary_route_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "rag-ime.sqlite"
            rime_dir = root / "Rime"
            rime_dir.mkdir()
            (rime_dir / "luna_pinyin_simp.custom.yaml").write_text(
                "patch:\n  translator/dictionary: personal_dictionary\n",
                encoding="utf-8",
            )
            record_rime_rank_feedback(
                db_path,
                preedit="shu ru fa",
                accepted_text="输入法",
                action="boost",
                candidate_rank=2,
            )
            review = review_rime_lexicon(db_path)

            result = apply_reviewed_rime_lexicon(
                db_path,
                rime_user_dir=rime_dir,
                backup_root=root / "backups",
                review_token=str(review["reviewToken"]),
                selected_keys=[str(review["entries"][0]["reviewKey"])],
                confirm_text=CONFIRM_TEXT,
            )

            self.assertEqual(result["reason"], "translator_dictionary_conflict")
            self.assertFalse((rime_dir / "rag_ime_user.dict.yaml").exists())

    def test_empty_or_unselected_review_cannot_apply(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "rag-ime.sqlite"
            review = review_rime_lexicon(db_path)
            result = apply_reviewed_rime_lexicon(
                db_path,
                rime_user_dir=root / "Rime",
                backup_root=root / "backups",
                review_token=str(review["reviewToken"]),
                confirm_text=CONFIRM_TEXT,
            )
            self.assertEqual(result["reason"], "no_reviewed_entries")


if __name__ == "__main__":
    unittest.main()
