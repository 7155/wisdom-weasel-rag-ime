from __future__ import annotations

import unittest

from rag_ime.runtime_flags import (
    HybridRagRuntimeFlags,
    assert_deepseek_not_called,
    assert_deepseek_scene_allowed,
    deepseek_scene_enabled,
    load_hybrid_rag_runtime_flags,
)


class HybridRagRuntimeFlagsTests(unittest.TestCase):
    def test_hybrid_rag_core_flag_defaults_off(self) -> None:
        flags = load_hybrid_rag_runtime_flags({})

        self.assertFalse(flags.hybrid_rag_core)
        self.assertEqual(flags.rag_core_v3_budget_ms, 25)

    def test_deepseek_passive_per_key_disabled_by_default(self) -> None:
        flags = load_hybrid_rag_runtime_flags({})

        self.assertFalse(flags.deepseek_passive_per_key)
        self.assertFalse(deepseek_scene_enabled("passive_per_key", flags))
        with self.assertRaisesRegex(RuntimeError, "passive per-key path is disabled"):
            assert_deepseek_scene_allowed("passive_per_key", flags)

    def test_deepseek_passive_per_key_rejected_even_when_flag_is_set(self) -> None:
        flags = load_hybrid_rag_runtime_flags({"RAG_IME_DEEPSEEK_PASSIVE_PER_KEY": "1"})

        self.assertTrue(flags.deepseek_passive_per_key)
        self.assertFalse(deepseek_scene_enabled("passive_per_key", flags))
        with self.assertRaisesRegex(RuntimeError, "disabled in v1"):
            assert_deepseek_scene_allowed("passive_per_key", flags)

    def test_deepseek_post_commit_requires_flag(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "RAG_IME_DEEPSEEK_POST_COMMIT=1"):
            assert_deepseek_scene_allowed("post_commit", load_hybrid_rag_runtime_flags({}))

        flags = load_hybrid_rag_runtime_flags({"RAG_IME_DEEPSEEK_POST_COMMIT": "1"})
        self.assertTrue(deepseek_scene_enabled("post_commit", flags))
        assert_deepseek_scene_allowed("post_commit", flags)

    def test_deepseek_active_rag_requires_flag(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "RAG_IME_DEEPSEEK_ACTIVE_RAG=1"):
            assert_deepseek_scene_allowed("active_rag", load_hybrid_rag_runtime_flags({}))

        flags = load_hybrid_rag_runtime_flags({"RAG_IME_DEEPSEEK_ACTIVE_RAG": "true"})
        self.assertTrue(deepseek_scene_enabled("active_rag", flags))
        assert_deepseek_scene_allowed("active_rag", flags)

    def test_deepseek_offline_compile_requires_flag(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "RAG_IME_DEEPSEEK_OFFLINE_COMPILE=1"):
            assert_deepseek_scene_allowed("offline_compile", load_hybrid_rag_runtime_flags({}))

        flags = load_hybrid_rag_runtime_flags({"RAG_IME_DEEPSEEK_OFFLINE_COMPILE": "on"})
        self.assertTrue(deepseek_scene_enabled("offline_compile", flags))
        assert_deepseek_scene_allowed("offline_compile", flags)

    def test_deepseek_not_called_guard_detects_passive_provider(self) -> None:
        assert_deepseek_not_called("post_commit", provider_name="deepseek-v4-flash")
        assert_deepseek_not_called("passive_per_key", provider_name="local-mlx")
        with self.assertRaisesRegex(RuntimeError, "must not be called"):
            assert_deepseek_not_called("passive_per_key", provider_name="DeepSeek", model="deepseek-v4-flash")

    def test_budget_env_is_clamped_to_positive_integer(self) -> None:
        self.assertEqual(load_hybrid_rag_runtime_flags({"RAG_IME_RAG_CORE_V3_BUDGET_MS": "-5"}).rag_core_v3_budget_ms, 1)
        self.assertEqual(load_hybrid_rag_runtime_flags({"RAG_IME_RAG_CORE_V3_BUDGET_MS": "abc"}).rag_core_v3_budget_ms, 25)

    def test_dataclass_can_be_constructed_for_direct_injection(self) -> None:
        flags = HybridRagRuntimeFlags(deepseek_post_commit=True, rag_core_v3_budget_ms=40)

        self.assertTrue(flags.deepseek_post_commit)
        self.assertEqual(flags.rag_core_v3_budget_ms, 40)


if __name__ == "__main__":
    unittest.main()
