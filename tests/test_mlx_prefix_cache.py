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


def _entry(cache_id: str, tokens: tuple[int, ...], *, profile: str = "hot") -> PrefixCacheEntry:
    return PrefixCacheEntry(
        cache_id=cache_id,
        profile_id=profile,
        prompt_format="IMEV1",
        token_ids=tokens,
        token_count=len(tokens),
        cache_obj=None,
        created_at_ms=1,
        last_used_at_ms=1,
    )


if __name__ == "__main__":
    unittest.main()
