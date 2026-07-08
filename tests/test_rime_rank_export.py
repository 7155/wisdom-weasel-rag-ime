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


if __name__ == "__main__":
    unittest.main()
