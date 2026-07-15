from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from rag_ime.model_profile_store import ModelProfileStore
from rag_ime.model_profiles import (
    ModelProfile,
    profile_by_id,
    validate_profile,
    validate_profile_artifact,
)


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

    def test_minimind_100m_and_60m_have_distinct_runtime_contracts(self) -> None:
        profile_100m = profile_by_id("minimind_ime_100m_v1")
        profile_60m = profile_by_id("minimind_ime_60m_v8")

        self.assertEqual(profile_100m.max_tokens, 16)
        self.assertEqual(profile_100m.prompt_mode, "base-completion")
        self.assertEqual(profile_100m.decode_strategy, "bos-sampled-completion-v1")
        self.assertEqual(profile_100m.branch_count, 8)
        self.assertFalse(profile_100m.stream_first)
        self.assertEqual(profile_100m.sampling_temperature, 0.42)
        self.assertEqual(profile_100m.sampling_top_p, 0.92)
        self.assertEqual(profile_100m.sampling_top_k, 50)
        self.assertEqual(profile_100m.max_candidate_chars, 24)
        self.assertEqual(profile_100m.expected_hidden_layers, 14)
        self.assertEqual(profile_100m.expected_attention_heads, 12)
        self.assertEqual(profile_100m.expected_vocab_size, 16384)

        self.assertEqual(profile_60m.max_tokens, 8)
        self.assertEqual(profile_60m.prompt_mode, "base-completion")
        self.assertEqual(profile_60m.decode_strategy, "bos-short-completion-v8")
        self.assertEqual(profile_60m.branch_count, 8)
        self.assertFalse(profile_60m.stream_first)
        self.assertEqual(profile_60m.sampling_temperature, 0.38)
        self.assertEqual(profile_60m.sampling_top_p, 0.90)
        self.assertEqual(profile_60m.sampling_top_k, 50)
        self.assertEqual(profile_60m.max_candidate_chars, 8)
        self.assertEqual(profile_60m.expected_hidden_layers, 8)
        self.assertEqual(profile_60m.expected_attention_heads, 8)
        self.assertEqual(profile_60m.expected_vocab_size, 6400)

    def test_unknown_profile_fails_closed_instead_of_falling_back(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown model profile"):
            profile_by_id("unregistered-minimind")
        with self.assertRaisesRegex(ValueError, "unknown model profile"):
            profile_by_id("")

    def test_minimind_artifact_geometry_must_match_profile(self) -> None:
        profile = profile_by_id("minimind_ime_100m_v1")
        with tempfile.TemporaryDirectory() as tmp:
            model_path = Path(tmp)
            (model_path / "config.json").write_text(
                json.dumps(
                    {
                        "num_hidden_layers": 14,
                        "num_attention_heads": 12,
                        "vocab_size": 16384,
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(validate_profile_artifact(profile, model_path), [])

            (model_path / "config.json").write_text(
                json.dumps(
                    {
                        "num_hidden_layers": 8,
                        "num_attention_heads": 8,
                        "vocab_size": 6400,
                    }
                ),
                encoding="utf-8",
            )
            errors = validate_profile_artifact(profile, model_path)

        self.assertTrue(any("num_hidden_layers=14" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
