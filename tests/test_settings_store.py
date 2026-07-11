from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from rag_ime.settings_models import UserProfile, UserVocabularyItem
from rag_ime.settings_store import ManagementSettingsStore


class SettingsStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-settings-store-")
        self.db_path = Path(self.tmp.name) / "settings.sqlite"
        self.store = ManagementSettingsStore(self.db_path)
        self.store.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_settings_update_writes_audit_and_reset_restores_defaults(self) -> None:
        result = self.store.update_settings({"interaction.postCommit.numberKeys": "select_prediction"})

        self.assertGreater(result.audit_id, 0)
        self.assertEqual(result.settings["interaction"]["postCommit"]["numberKeys"], "select_prediction")
        self.assertIn("interaction.postCommit.numberKeys", result.changed_keys)
        self.assertEqual(self._audit_count("settings_update"), 1)

        reset = self.store.reset_section("interaction")

        self.assertGreater(reset.audit_id, result.audit_id)
        self.assertEqual(reset.settings["interaction"]["postCommit"]["numberKeys"], "pass_through")
        self.assertEqual(self._audit_count("settings_reset_section"), 1)

    def test_remote_model_enable_requires_confirm_text(self) -> None:
        with self.assertRaises(ValueError):
            self.store.update_settings({"activeRag.allowRemoteModel": True})

        result = self.store.update_settings(
            {"activeRag.allowRemoteModel": True},
            confirm_text="ALLOW REMOTE MODEL",
        )

        self.assertTrue(result.settings["activeRag"]["allowRemoteModel"])

    def test_dotted_leaf_update_preserves_persisted_sibling_overrides(self) -> None:
        self.store.update_settings(
            {
                "interaction.postCommit.idleTriggerMs": 180,
                "interaction.postCommit.maxCallsPer10s": 6,
                "interaction.postCommit.cooldownMs": 600,
                "interaction.postCommit.panelTtlMs": 8500,
            }
        )

        self.store.update_settings({"interaction.postCommit.minDeltaChars": 2})
        persisted = self.store.get_settings(include_sensitive=True)
        post_commit = persisted["interaction"]["postCommit"]

        self.assertEqual(post_commit["idleTriggerMs"], 180)
        self.assertEqual(post_commit["minDeltaChars"], 2)
        self.assertEqual(post_commit["maxCallsPer10s"], 6)
        self.assertEqual(post_commit["cooldownMs"], 600)
        self.assertEqual(post_commit["panelTtlMs"], 8500)

    def test_profile_save_and_activate_dry_run(self) -> None:
        saved = self.store.save_profile(
            UserProfile(
                profile_id="focused-writing",
                profile_kind="interaction_profile",
                label="Focused Writing",
                description="longer post-commit TTL",
                settings={"interaction.postCommit.panelTtlMs": 6000},
            )
        )
        listed = self.store.list_profiles(kind="interaction_profile")
        dry_run = self.store.activate_profile_dry_run("focused-writing")

        self.assertTrue(saved["ok"])
        self.assertEqual(len(listed["items"]), 1)
        self.assertTrue(dry_run["ok"])
        self.assertTrue(dry_run["dryRun"])
        self.assertIn("scripts/restart_rag_ime_runtime.sh", dry_run["commands"])

    def test_vocabulary_add_edit_delete_and_rime_export(self) -> None:
        added = self.store.save_vocabulary_item(
            UserVocabularyItem(
                vocab_id="",
                surface="StableCandidateSnapshot",
                aliases=("候选快照",),
                pinyin="hou xuan kuai zhao",
                tags=("输入法",),
                priority=100,
                scope="project:wisdom-weasel-rag-ime",
            )
        )
        preview = self.store.rime_export_preview()
        denied = self.store.rime_export_apply(target_file=str(Path(self.tmp.name) / "rag_ime.user.dict.yaml"), confirm_text="wrong")
        applied = self.store.rime_export_apply(
            target_file=str(Path(self.tmp.name) / "rag_ime.user.dict.yaml"),
            confirm_text="EXPORT RIME",
        )
        deleted = self.store.delete_vocabulary_item(str(added["vocabId"]))

        self.assertTrue(added["ok"])
        self.assertEqual(preview["entryCount"], 1)
        self.assertIn("StableCandidateSnapshot", preview["text"])
        self.assertFalse(denied["ok"])
        self.assertTrue(applied["ok"])
        self.assertTrue(Path(applied["targetFile"]).exists())
        self.assertTrue(deleted["ok"])

    def _audit_count(self, action: str) -> int:
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            row = conn.execute("SELECT COUNT(*) FROM management_audit_log WHERE action = ?", (action,)).fetchone()
        return int(row[0])


if __name__ == "__main__":
    unittest.main()
