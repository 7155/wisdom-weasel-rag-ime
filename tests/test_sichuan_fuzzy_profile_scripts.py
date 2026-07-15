from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


class SichuanFuzzyProfileScriptTests(unittest.TestCase):
    def test_apply_dry_run_reports_change_without_writing(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-sichuan-dry-run-") as tmp:
            rime_dir = Path(tmp) / "Rime"
            result = subprocess.run(
                ["bash", str(root / "scripts" / "apply_sichuan_fuzzy_profile.sh"), "--dry-run"],
                cwd=root,
                env={**os.environ, "RAG_IME_RIME_USER_DIR": str(rime_dir)},
                text=True,
                capture_output=True,
                check=True,
            )

            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"])
            self.assertTrue(payload["dryRun"])
            self.assertFalse(payload["applied"])
            self.assertTrue(payload["changed"])
            self.assertFalse((rime_dir / "luna_pinyin_simp.custom.yaml").exists())

    def test_apply_replaces_legacy_strong_fuzzy_profile_and_preserves_backup(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-sichuan-apply-") as tmp:
            rime_dir = Path(tmp) / "Rime"
            rime_dir.mkdir()
            target = rime_dir / "luna_pinyin_simp.custom.yaml"
            target.write_text(
                "\n".join(
                    [
                        "patch:",
                        "  translator/dictionary: luna_pinyin",
                        "# rag-ime-managed-sichuan-fuzzy-pinyin",
                        "patch:",
                        "  speller/algebra:",
                        "    - derive/^zh/z/",
                        "    - derive/^n/l/",
                        "    - derive/^f/h/",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                ["bash", str(root / "scripts" / "apply_sichuan_fuzzy_profile.sh"), "--apply"],
                cwd=root,
                env={**os.environ, "RAG_IME_RIME_USER_DIR": str(rime_dir)},
                text=True,
                capture_output=True,
                check=True,
            )

            payload = json.loads(result.stdout)
            text = target.read_text(encoding="utf-8")
            backup = Path(payload["backupPath"])
            self.assertTrue(payload["applied"])
            self.assertTrue(backup.exists())
            self.assertIn("translator/dictionary: luna_pinyin", text)
            self.assertIn("rag-ime-managed-sichuan-fuzzy-pinyin: begin", text)
            self.assertIn("translator/enable_user_dict: true", text)
            self.assertIn("translator/enable_sentence: true", text)
            self.assertIn("translator/encode_commit_history: true", text)
            self.assertIn("derive/^zh/z/", text)
            self.assertIn("derive/eng$/en/", text)
            self.assertIn("derive/ing$/in/", text)
            self.assertIn("derive/ong$/on/", text)
            self.assertNotIn("derive/^n/l/", text)
            self.assertNotIn("derive/^f/h/", text)

    def test_check_reports_json_success_for_mild_profile(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-sichuan-check-") as tmp:
            rime_dir = Path(tmp) / "Rime"
            subprocess.run(
                ["bash", str(root / "scripts" / "apply_sichuan_fuzzy_profile.sh"), "--apply"],
                cwd=root,
                env={**os.environ, "RAG_IME_RIME_USER_DIR": str(rime_dir)},
                text=True,
                capture_output=True,
                check=True,
            )

            result = subprocess.run(
                ["bash", str(root / "scripts" / "check_sichuan_fuzzy_profile.sh")],
                cwd=root,
                env={**os.environ, "RAG_IME_RIME_USER_DIR": str(rime_dir)},
                text=True,
                capture_output=True,
                check=True,
            )

        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["enabled"]["z_zh"])
        self.assertTrue(payload["enabled"]["c_ch"])
        self.assertTrue(payload["enabled"]["s_sh"])
        self.assertTrue(payload["enabled"]["en_eng"])
        self.assertTrue(payload["enabled"]["in_ing"])
        self.assertTrue(payload["enabled"]["ong_on"])
        self.assertTrue(payload["disabled"]["n_l"])
        self.assertTrue(payload["disabled"]["f_h"])
        self.assertEqual(payload["missingRules"], [])
        self.assertEqual(payload["forbiddenRulesPresent"], [])

        apply_payload = json.loads(
            subprocess.run(
                ["bash", str(root / "scripts" / "apply_sichuan_fuzzy_profile.sh"), "--dry-run"],
                cwd=root,
                env={**os.environ, "RAG_IME_RIME_USER_DIR": str(rime_dir)},
                text=True,
                capture_output=True,
                check=True,
            ).stdout
        )
        self.assertTrue(apply_payload["nativeRanking"]["enableUserDict"])
        self.assertTrue(apply_payload["nativeRanking"]["enableSentence"])
        self.assertTrue(apply_payload["nativeRanking"]["encodeCommitHistory"])


if __name__ == "__main__":
    unittest.main()
