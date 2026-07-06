from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rag_ime.model_profile_store import ModelProfileStore
from rag_ime.model_profiles import ModelProfile, profile_by_id, validate_profile


class ModelProfilesTests(unittest.TestCase):
    def test_hot_profile_requires_resident_model(self) -> None:
        profile = ModelProfile(id="bad_hot", lane="hot", model_path="x", resident=False)

        self.assertIn("hot profile must be resident", validate_profile(profile))

    def test_quality_profile_cannot_replace_visible_ordinals(self) -> None:
        profile = profile_by_id("qwen3_17b_ime_quality")

        self.assertEqual(profile.lane, "quality")
        self.assertTrue(profile.append_only)
        self.assertFalse(profile.sequence_fork)

    def test_idle_unload_only_applies_to_quality_lane(self) -> None:
        profile = ModelProfile(id="bad_main", lane="main", model_path="x", idle_unload_ms=10)

        self.assertIn("idle unload only applies to quality lane", validate_profile(profile))

    def test_profile_store_loads_json_and_exposes_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "profiles.json"
            path.write_text(
                '{"profiles":[{"id":"custom_hot","lane":"hot","modelPath":"m","maxTokens":16,"latencyBudgetMs":400}]}',
                encoding="utf-8",
            )
            store = ModelProfileStore.from_json_file(path)

        payload = store.payload()
        profile = store.resolve("custom_hot")
        self.assertEqual(profile.latency_budget_ms, 400)
        self.assertEqual(payload["profiles"][0]["latencyBudgetMs"], 400)


if __name__ == "__main__":
    unittest.main()
