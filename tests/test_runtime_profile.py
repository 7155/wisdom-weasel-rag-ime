from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

from rag_ime.runtime_profile import get_runtime_profile
from rag_ime.settings_schema import default_settings


class RuntimeProfileTests(unittest.TestCase):
    def test_foreground_rag_proof_enables_direct_rag_without_composition_ai(self) -> None:
        profile = get_runtime_profile("foreground-rag-proof")

        self.assertTrue(profile.hybrid_rag_core)
        self.assertTrue(profile.rag_direct_display)
        self.assertFalse(profile.composition_ai)
        self.assertFalse(profile.pinyin_constrained_model)

    def test_v1_proof_keeps_composition_local_and_enables_hybrid_evidence(self) -> None:
        profile = get_runtime_profile("v1-proof")

        self.assertEqual(profile.squirrel_latency_budget_ms, 900)
        self.assertEqual(profile.squirrel_timeout_ms, 1200)
        self.assertTrue(profile.strict_foreground_context)
        self.assertTrue(profile.hybrid_rag_core)
        self.assertFalse(profile.rag_direct_display)
        self.assertFalse(profile.composition_ai)

    def test_shell_output_is_consumable_by_install_scripts(self) -> None:
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            ["python3", "-m", "rag_ime.runtime_profile", "--profile", "production", "--format", "shell"],
            cwd=root,
            text=True,
            capture_output=True,
            check=True,
        )

        self.assertIn("RAG_IME_PROFILE_SQUIRREL_LATENCY_BUDGET_MS=900", result.stdout)
        self.assertIn("RAG_IME_PROFILE_HYBRID_RAG_CORE=1", result.stdout)
        self.assertIn("RAG_IME_PROFILE_RAG_DIRECT_DISPLAY=0", result.stdout)

    def test_control_plane_defaults_match_composition_off_profiles(self) -> None:
        composition = default_settings()["interaction"]["composition"]

        self.assertFalse(composition["showPrediction"])
        self.assertTrue(composition["showOnlyRime"])
        for profile_name in ("v1-proof", "production"):
            profile = get_runtime_profile(profile_name)
            self.assertFalse(profile.composition_ai)
            self.assertFalse(profile.pinyin_constrained_model)


if __name__ == "__main__":
    unittest.main()
