from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Sequence


@dataclass
class PrefixCacheEntry:
    cache_id: str
    profile_id: str
    prompt_format: str
    token_ids: tuple[int, ...]
    token_count: int
    cache_obj: object | None
    created_at_ms: int
    last_used_at_ms: int
    hit_count: int = 0
    bytes_estimate: int = 0


class MlxPrefixCache:
    def __init__(self, *, max_entries: int = 64, max_bytes: int = 256 * 1024 * 1024) -> None:
        self.max_entries = max(1, int(max_entries))
        self.max_bytes = max(0, int(max_bytes))
        self._entries: list[PrefixCacheEntry] = []

    def lookup_longest_prefix(
        self,
        *,
        profile_id: str,
        prompt_format: str,
        token_ids: Sequence[int],
    ) -> PrefixCacheEntry | None:
        query = tuple(int(item) for item in token_ids)
        best: PrefixCacheEntry | None = None
        for entry in self._entries:
            if entry.profile_id != profile_id or entry.prompt_format != prompt_format:
                continue
            if len(entry.token_ids) > len(query):
                continue
            if tuple(query[: len(entry.token_ids)]) != entry.token_ids:
                continue
            if best is None or entry.token_count > best.token_count:
                best = entry
        if best is not None:
            best.hit_count += 1
            best.last_used_at_ms = _now_ms()
        return best

    def put(self, entry: PrefixCacheEntry) -> None:
        self._entries = [item for item in self._entries if item.cache_id != entry.cache_id]
        self._entries.append(entry)
        self.evict()

    def evict(self) -> None:
        self._entries.sort(key=lambda item: (item.last_used_at_ms, item.hit_count), reverse=True)
        self._entries = self._entries[: self.max_entries]
        if self.max_bytes <= 0:
            return
        kept: list[PrefixCacheEntry] = []
        total = 0
        for entry in self._entries:
            size = max(0, int(entry.bytes_estimate))
            if kept and total + size > self.max_bytes:
                continue
            kept.append(entry)
            total += size
        self._entries = kept

    def stats(self) -> dict[str, int]:
        return {
            "entries": len(self._entries),
            "maxEntries": self.max_entries,
            "bytesEstimate": sum(max(0, int(item.bytes_estimate)) for item in self._entries),
            "maxBytes": self.max_bytes,
            "hits": sum(max(0, int(item.hit_count)) for item in self._entries),
        }

    def clear(self) -> None:
        self._entries.clear()


class MlxCacheAdapter:
    def prefill(self, token_ids: Sequence[int]) -> object:
        raise NotImplementedError("mlx cache prefill is runtime-adapter specific")

    def clone(self, cache_obj: object) -> object:
        clone = getattr(cache_obj, "copy", None)
        if callable(clone):
            return clone()
        raise NotImplementedError("cache_clone_unsupported")

    def trim(self, cache_obj: object, token_count: int) -> object:
        _ = token_count
        return cache_obj

    def append_decode(self, cache_obj: object, token_ids: Sequence[int]) -> object:
        _ = token_ids
        return cache_obj


def _now_ms() -> int:
    return int(time.time() * 1000)
