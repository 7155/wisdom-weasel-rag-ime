from __future__ import annotations

import hashlib
import json
import math
import os
import urllib.error
import urllib.request
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Protocol

from .text_utils import compact_whitespace, token_terms


class EmbeddingProvider(Protocol):
    fingerprint: str

    def embed(self, text: str) -> list[float]:
        ...


@dataclass(frozen=True)
class NullEmbeddingProvider:
    fingerprint: str = "none"

    def embed(self, text: str) -> list[float]:
        return []


@dataclass(frozen=True)
class HashingEmbeddingProvider:
    """Deterministic local term-vector baseline.

    This is not a semantic embedding model. It gives the SQLite core a local
    vector side-index contract that can be swapped for a real local/WSL embedding
    endpoint without changing the IME adapter.
    """

    dimensions: int = 96
    fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "fingerprint", f"local-hash:{max(8, int(self.dimensions))}:v1")

    def embed(self, text: str) -> list[float]:
        dimensions = max(8, int(self.dimensions))
        vector = [0.0] * dimensions
        for term in token_terms(text, max_terms=160):
            digest = hashlib.blake2b(term.encode("utf-8", errors="ignore"), digest_size=8).digest()
            raw = int.from_bytes(digest, "big", signed=False)
            index = raw % dimensions
            sign = 1.0 if ((raw >> 8) & 1) else -1.0
            vector[index] += sign
        return normalize_vector(vector)


@dataclass(frozen=True)
class OpenAICompatibleEmbeddingConfig:
    base_url: str
    model: str
    api_key: str = ""
    timeout_s: float = 0.8
    dimensions: int = 0
    cache_size: int = 256
    extra_body: dict[str, Any] = field(default_factory=dict)
    extra_headers: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class OpenAICompatibleEmbeddingProvider:
    config: OpenAICompatibleEmbeddingConfig
    fingerprint: str = field(init=False)
    _cache: OrderedDict[tuple[str, str], list[float]] = field(
        default_factory=OrderedDict,
        init=False,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "fingerprint",
            _openai_embedding_fingerprint(
                base_url=self.config.base_url,
                model=self.config.model,
                dimensions=self.config.dimensions,
                extra_body=self.config.extra_body,
            ),
        )

    def embed(self, text: str) -> list[float]:
        normalized_text = compact_whitespace(text)
        if not normalized_text:
            return []
        cache_key = (self.fingerprint, normalized_text)
        cache_limit = max(0, int(self.config.cache_size))
        if cache_limit > 0:
            cached = self._cache.get(cache_key)
            if cached is not None:
                self._cache.move_to_end(cache_key)
                return list(cached)
        vector = self._embed_uncached(normalized_text)
        if vector and cache_limit > 0:
            self._cache[cache_key] = list(vector)
            self._cache.move_to_end(cache_key)
            while len(self._cache) > cache_limit:
                self._cache.popitem(last=False)
        return vector

    def _embed_uncached(self, normalized_text: str) -> list[float]:
        payload = {
            "model": self.config.model,
            "input": normalized_text,
            **dict(self.config.extra_body),
        }
        if self.config.dimensions > 0:
            payload["dimensions"] = self.config.dimensions
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            **self.config.extra_headers,
        }
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        request = urllib.request.Request(
            self.config.base_url.rstrip("/") + "/v1/embeddings",
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_s) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (OSError, urllib.error.URLError, json.JSONDecodeError, TimeoutError):
            return []
        embedding = (((data or {}).get("data") or [{}])[0] or {}).get("embedding")
        if not isinstance(embedding, list):
            return []
        return normalize_vector([float(value) for value in embedding if isinstance(value, (int, float))])


def embedding_provider_from_env(env: dict[str, str] | None = None) -> EmbeddingProvider:
    source = env or os.environ
    provider = source.get("RAG_IME_EMBEDDING_PROVIDER", "none").strip().lower()
    if provider in {"local-hash", "hash", "term-vector", "local-term-vector"}:
        return HashingEmbeddingProvider(dimensions=int(_float_env(source, "RAG_IME_EMBEDDING_DIMENSIONS", 96)))
    if provider in {"openai", "openai-compatible"}:
        base_url = source.get("RAG_IME_EMBEDDING_BASE_URL", "").strip()
        model = source.get("RAG_IME_EMBEDDING_MODEL", "").strip()
        if not base_url or not model:
            return NullEmbeddingProvider()
        return OpenAICompatibleEmbeddingProvider(
            OpenAICompatibleEmbeddingConfig(
                base_url=base_url,
                model=model,
                api_key=source.get("RAG_IME_EMBEDDING_API_KEY", "").strip(),
                timeout_s=_float_env(source, "RAG_IME_EMBEDDING_TIMEOUT_MS", 800) / 1000,
                dimensions=int(_float_env(source, "RAG_IME_EMBEDDING_DIMENSIONS", 0)),
                cache_size=int(_float_env(source, "RAG_IME_EMBEDDING_CACHE_SIZE", 256)),
                extra_body=_json_object_env(source, "RAG_IME_EMBEDDING_EXTRA_BODY_JSON"),
                extra_headers=_json_string_map_env(source, "RAG_IME_EMBEDDING_EXTRA_HEADERS_JSON"),
            )
        )
    return NullEmbeddingProvider()


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 0.0
    size = min(len(left), len(right))
    if size <= 0:
        return 0.0
    numerator = sum(left[index] * right[index] for index in range(size))
    left_norm = math.sqrt(sum(value * value for value in left[:size]))
    right_norm = math.sqrt(sum(value * value for value in right[:size]))
    if left_norm <= 0 or right_norm <= 0:
        return 0.0
    return numerator / (left_norm * right_norm)


def normalize_vector(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm <= 0:
        return []
    return [value / norm for value in vector]


def _openai_embedding_fingerprint(
    *,
    base_url: str,
    model: str,
    dimensions: int,
    extra_body: dict[str, Any],
) -> str:
    endpoint = base_url.rstrip("/")
    endpoint_hash = hashlib.sha256(endpoint.encode("utf-8", errors="ignore")).hexdigest()[:10] if endpoint else "none"
    suffix = f":endpoint-{endpoint_hash}"
    if dimensions:
        suffix += f":{dimensions}"
    if extra_body:
        material = json.dumps(
            extra_body,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        body_hash = hashlib.sha256(material.encode("utf-8")).hexdigest()[:12]
        suffix += f":body-{body_hash}"
    return f"openai-compatible:{model}{suffix}"


def _float_env(env: dict[str, str], name: str, default: float) -> float:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _json_object_env(env: dict[str, str], name: str) -> dict[str, Any]:
    raw = env.get(name, "").strip()
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _json_string_map_env(env: dict[str, str], name: str) -> dict[str, str]:
    raw = _json_object_env(env, name)
    result: dict[str, str] = {}
    for key, value in raw.items():
        if isinstance(key, str) and isinstance(value, str):
            result[key] = value
    return result
