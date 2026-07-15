from __future__ import annotations

import unittest

from rag_ime.mlx_prefix_cache import MlxPrefixCache, PrefixCacheEntry


class MlxPrefixCacheTests(unittest.TestCase):
    def test_prefix_cache_longest_prefix_match(self) -> None:
        cache = MlxPrefixCache(max_entries=8)
        cache.put(_entry("short", (1, 2)))
        cache.put(_entry("long", (1, 2, 3, 4)))

        hit = cache.lookup_longest_prefix(profile_id="hot", prompt_format="IMEV1", token_ids=(1, 2, 3, 4, 5))

        self.assertIsNotNone(hit)
        self.assertEqual(hit.cache_id, "long")
        self.assertEqual(hit.hit_count, 1)

    def test_prefix_cache_misses_different_profile(self) -> None:
        cache = MlxPrefixCache(max_entries=8)
        cache.put(_entry("short", (1, 2), profile="quality"))

        self.assertIsNone(cache.lookup_longest_prefix(profile_id="hot", prompt_format="IMEV1", token_ids=(1, 2, 3)))

    def test_prefix_cache_evicts_by_entry_budget(self) -> None:
        cache = MlxPrefixCache(max_entries=1)
        cache.put(_entry("one", (1,)))
        cache.put(_entry("two", (2,)))

        self.assertEqual(cache.stats()["entries"], 1)

    def test_reused_prefix_survives_newer_one_shot_entry(self) -> None:
        cache = MlxPrefixCache(max_entries=2)
        cache.put(_entry("reused", (1, 2)))
        self.assertIsNotNone(
            cache.lookup_longest_prefix(profile_id="hot", prompt_format="IMEV1", token_ids=(1, 2, 3))
        )
        cache.put(_entry("one-shot-a", (4,), last_used_at_ms=2))
        cache.put(_entry("one-shot-b", (5,), last_used_at_ms=3))

        self.assertIsNotNone(
            cache.lookup_longest_prefix(profile_id="hot", prompt_format="IMEV1", token_ids=(1, 2, 9))
        )
        stats = cache.stats()
        self.assertEqual(stats["lookups"], 2)
        self.assertEqual(stats["misses"], 0)
        self.assertEqual(stats["hitRatePermille"], 1000)
        self.assertEqual(stats["evictions"], 1)

    def test_single_oversized_entry_is_rejected_by_byte_budget(self) -> None:
        cache = MlxPrefixCache(max_entries=8, max_bytes=32)
        cache.put(_entry("oversized", (1, 2), bytes_estimate=64))

        self.assertEqual(cache.stats()["entries"], 0)
        self.assertEqual(cache.stats()["bytesEstimate"], 0)
        self.assertEqual(cache.stats()["evictions"], 1)

    def test_miss_metrics_are_reported_without_exposing_tokens(self) -> None:
        cache = MlxPrefixCache(max_entries=8)

        self.assertIsNone(
            cache.lookup_longest_prefix(profile_id="hot", prompt_format="IMEV1", token_ids=(7, 8, 9))
        )

        self.assertEqual(cache.stats()["lookups"], 1)
        self.assertEqual(cache.stats()["misses"], 1)
        self.assertEqual(cache.stats()["hitRatePermille"], 0)


def _entry(
    cache_id: str,
    tokens: tuple[int, ...],
    *,
    profile: str = "hot",
    last_used_at_ms: int = 1,
    bytes_estimate: int = 0,
) -> PrefixCacheEntry:
    return PrefixCacheEntry(
        cache_id=cache_id,
        profile_id=profile,
        prompt_format="IMEV1",
        token_ids=tokens,
        token_count=len(tokens),
        cache_obj=None,
        created_at_ms=1,
        last_used_at_ms=last_used_at_ms,
        bytes_estimate=bytes_estimate,
    )


if __name__ == "__main__":
    unittest.main()
