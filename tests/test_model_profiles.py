from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rag_ime.model_profile_store import ModelProfileStore
from rag_ime.model_profiles import (
    ModelProfile,
    canonical_runtime_profile_id,
    profile_by_id,
    validate_profile,
)


class ModelProfilesTests(unittest.TestCase):
    def test_known_minimind_deployments_share_one_runtime_contract(self) -> None:
        for deployment_profile in (
            "minimind_ime_60m_v8",
            "minimind_ime_100m_v1",
            "minimind_ime_v2",
        ):
            with self.subTest(deployment_profile=deployment_profile):
                self.assertEqual(
                    canonical_runtime_profile_id(deployment_profile),
                    "minimind_ime_v2",
                )
                self.assertEqual(
                    profile_by_id(deployment_profile).id,
                    "minimind_ime_v2",
                )

        self.assertEqual(
            canonical_runtime_profile_id("qwen3_06b_ime_hot"),
            "qwen3_06b_ime_hot",
        )

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

    def test_generation_contract_is_bounded(self) -> None:
        profile = ModelProfile(
            id="bad_sampling",
            lane="hot",
            model_path="x",
            max_tokens=65,
            prompt_mode="free-form",
            temperature=2.1,
            top_p=0.0,
        )

        errors = validate_profile(profile)

        self.assertIn("max tokens must be between 1 and 64", errors)
        self.assertIn("prompt mode must be base-completion or chat-json", errors)
        self.assertIn("temperature must be between 0 and 2", errors)
        self.assertIn("top p must be greater than 0 and at most 1", errors)

    def test_profile_store_loads_json_and_exposes_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "profiles.json"
            path.write_text(
                '{"profiles":[{"id":"custom_hot","lane":"hot","modelPath":"m","maxTokens":16,"promptMode":"base-completion","temperature":0.2,"topP":0.9,"latencyBudgetMs":400}]}',
                encoding="utf-8",
            )
            store = ModelProfileStore.from_json_file(path)

        payload = store.payload()
        profile = store.resolve("custom_hot")
        self.assertEqual(profile.latency_budget_ms, 400)
        self.assertEqual(profile.prompt_mode, "base-completion")
        self.assertEqual(profile.temperature, 0.2)
        self.assertEqual(profile.top_p, 0.9)
        self.assertEqual(payload["profiles"][0]["latencyBudgetMs"], 400)


if __name__ == "__main__":
    unittest.main()
