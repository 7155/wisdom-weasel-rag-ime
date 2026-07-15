from __future__ import annotations

import hashlib
import json
import math
import os
import urllib.error
import urllib.request
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock
from typing import Any, Protocol

from .text_utils import compact_whitespace, token_terms


class EmbeddingProvider(Protocol):
    fingerprint: str

    def embed(self, text: str) -> list[float]:
        ...

    def embed_many(self, texts: list[str], *, batch_size: int = 32) -> list[list[float]]:
        ...


def embed_query(provider: EmbeddingProvider, text: str) -> list[float]:
    query_method = getattr(provider, "embed_query", None)
    if callable(query_method):
        return query_method(text)
    return provider.embed(text)


@dataclass(frozen=True)
class NullEmbeddingProvider:
    fingerprint: str = "none"

    def embed(self, text: str) -> list[float]:
        return []

    def embed_many(self, texts: list[str], *, batch_size: int = 32) -> list[list[float]]:
        return [[] for _ in texts]


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

    def embed_many(self, texts: list[str], *, batch_size: int = 32) -> list[list[float]]:
        return [self.embed(text) for text in texts]


@dataclass
class SentenceTransformerEmbeddingProvider:
    """Lazy local Sentence Transformers provider for the optional BGE lane."""

    model: str
    query_prefix: str = ""
    document_prefix: str = ""
    cache_size: int = 32
    cache_dir: str = ""
    local_files_only: bool = True
    fingerprint: str = field(init=False)
    _model: Any = field(default=None, init=False, repr=False)
    _cache: OrderedDict[tuple[str, str], list[float]] = field(default_factory=OrderedDict, init=False, repr=False)
    _lock: RLock = field(default_factory=RLock, init=False, repr=False)

    def __post_init__(self) -> None:
        material = json.dumps(
            {"model": self.model, "queryPrefix": self.query_prefix, "documentPrefix": self.document_prefix},
            ensure_ascii=False,
            sort_keys=True,
        )
        digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:12]
        self.fingerprint = f"sentence-transformers:{self.model}:cfg-{digest}"

    def embed(self, text: str) -> list[float]:
        return self._encode(text, role="document", prefix=self.document_prefix)

    def embed_query(self, text: str) -> list[float]:
        return self._encode(text, role="query", prefix=self.query_prefix)

    def embed_many(self, texts: list[str], *, batch_size: int = 32) -> list[list[float]]:
        normalized = [compact_whitespace(text) for text in texts]
        results: list[list[float]] = [[] for _ in normalized]
        missing_indexes = [index for index, text in enumerate(normalized) if text]
        if not missing_indexes:
            return results
        step = max(1, min(128, int(batch_size)))
        model = self._load_model()
        for offset in range(0, len(missing_indexes), step):
            indexes = missing_indexes[offset : offset + step]
            encoded = model.encode(
                [self.document_prefix + normalized[index] for index in indexes],
                normalize_embeddings=True,
                show_progress_bar=False,
            )
            for index, vector in zip(indexes, encoded.tolist()):
                results[index] = [float(value) for value in vector]
        return results

    def _encode(self, text: str, *, role: str, prefix: str) -> list[float]:
        normalized_text = compact_whitespace(text)
        if not normalized_text:
            return []
        cache_key = (role, normalized_text)
        with self._lock:
            cached = self._cache.get(cache_key)
            if cached is not None:
                self._cache.move_to_end(cache_key)
                return list(cached)
            model = self._load_model()
            encoded = model.encode(prefix + normalized_text, normalize_embeddings=True, show_progress_bar=False)
            vector = [float(value) for value in encoded.tolist()]
            cache_limit = max(0, int(self.cache_size))
            if vector and cache_limit > 0:
                self._cache[cache_key] = vector
                self._cache.move_to_end(cache_key)
                while len(self._cache) > cache_limit:
                    self._cache.popitem(last=False)
            return list(vector)

    def _load_model(self):
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise RuntimeError(
                    "local sentence-transformers embedding requires the 'embedding-local' optional dependencies"
                ) from exc
            self._model = SentenceTransformer(
                self.model,
                cache_folder=str(Path(self.cache_dir).expanduser()) if self.cache_dir else None,
                local_files_only=self.local_files_only,
                trust_remote_code=False,
            )
        return self._model


@dataclass
class MlxBertEmbeddingProvider:
    model: str
    query_prefix: str = ""
    document_prefix: str = ""
    bits: int = 8
    group_size: int = 32
    cache_size: int = 32
    fingerprint: str = field(init=False)
    _model: Any = field(default=None, init=False, repr=False)
    _tokenizer: Any = field(default=None, init=False, repr=False)
    _cache: OrderedDict[tuple[str, str], list[float]] = field(default_factory=OrderedDict, init=False, repr=False)
    _lock: RLock = field(default_factory=RLock, init=False, repr=False)

    def __post_init__(self) -> None:
        material = json.dumps(
            {"model": self.model, "queryPrefix": self.query_prefix, "documentPrefix": self.document_prefix,
             "bits": self.bits, "groupSize": self.group_size},
            ensure_ascii=False, sort_keys=True,
        )
        self.fingerprint = f"mlx-bert:{Path(self.model).name}:cfg-{hashlib.sha256(material.encode()).hexdigest()[:12]}"

    def embed(self, text: str) -> list[float]:
        return self._encode(text, role="document", prefix=self.document_prefix)

    def embed_query(self, text: str) -> list[float]:
        return self._encode(text, role="query", prefix=self.query_prefix)

    def embed_many(self, texts: list[str], *, batch_size: int = 32) -> list[list[float]]:
        # MLX execution remains serialized by the provider lock; this contract
        # still lets the projection layer batch providers that support it.
        return [self.embed(text) for text in texts]

    def _encode(self, text: str, *, role: str, prefix: str) -> list[float]:
        normalized = compact_whitespace(text)
        if not normalized:
            return []
        key = (role, normalized)
        with self._lock:
            cached = self._cache.get(key)
            if cached is not None:
                self._cache.move_to_end(key)
                return list(cached)
            model, tokenizer = self._load_model()
            import mlx.core as mx

            tokens = tokenizer(prefix + normalized, return_tensors="np", padding=True, truncation=True, max_length=512)
            hidden, _ = model(**{name: mx.array(value) for name, value in tokens.items()})
            vector = normalize_vector([float(value) for value in mx.array(hidden[0, 0]).tolist()])
            if vector and self.cache_size > 0:
                self._cache[key] = vector
                while len(self._cache) > self.cache_size:
                    self._cache.popitem(last=False)
            return list(vector)

    def _load_model(self):
        if self._model is None:
            from .mlx_bert import load_mlx_bert

            self._model, self._tokenizer = load_mlx_bert(
                self.model, bits=max(0, int(self.bits)), group_size=max(1, int(self.group_size))
            )
        return self._model, self._tokenizer


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

    def embed_many(self, texts: list[str], *, batch_size: int = 32) -> list[list[float]]:
        normalized = [compact_whitespace(text) for text in texts]
        results: dict[str, list[float]] = {}
        missing: list[str] = []
        for text in dict.fromkeys(item for item in normalized if item):
            cache_key = (self.fingerprint, text)
            cached = self._cache.get(cache_key)
            if cached is not None:
                self._cache.move_to_end(cache_key)
                results[text] = list(cached)
            else:
                missing.append(text)
        step = max(1, min(128, int(batch_size)))
        for offset in range(0, len(missing), step):
            chunk = missing[offset:offset + step]
            vectors = self._embed_batch_uncached(chunk)
            for text, vector in zip(chunk, vectors):
                results[text] = vector
                if vector and self.config.cache_size > 0:
                    cache_key = (self.fingerprint, text)
                    self._cache[cache_key] = list(vector)
                    self._cache.move_to_end(cache_key)
                    while len(self._cache) > self.config.cache_size:
                        self._cache.popitem(last=False)
        return [list(results.get(text, [])) if text else [] for text in normalized]

    def _embed_uncached(self, normalized_text: str) -> list[float]:
        values = self._request_embeddings(normalized_text)
        return values[0] if values else []

    def _embed_batch_uncached(self, normalized_texts: list[str]) -> list[list[float]]:
        if not normalized_texts:
            return []
        values = self._request_embeddings(normalized_texts)
        if len(values) != len(normalized_texts):
            return [[] for _ in normalized_texts]
        return values

    def _request_embeddings(self, input_value: str | list[str]) -> list[list[float]]:
        payload = {
            "model": self.config.model,
            "input": input_value,
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
        items = (data or {}).get("data") or []
        if not isinstance(items, list):
            return []
        ordered = sorted(
            (item for item in items if isinstance(item, dict)),
            key=lambda item: int(item.get("index") or 0),
        )
        return [
            normalize_vector([float(value) for value in item.get("embedding", []) if isinstance(value, (int, float))])
            for item in ordered
        ]


def embedding_provider_from_env(env: dict[str, str] | None = None) -> EmbeddingProvider:
    source = os.environ if env is None else env
    provider = source.get("RAG_IME_EMBEDDING_PROVIDER", "none").strip().lower()
    if provider in {"local-hash", "hash", "term-vector", "local-term-vector"}:
        return HashingEmbeddingProvider(dimensions=int(_float_env(source, "RAG_IME_EMBEDDING_DIMENSIONS", 96)))
    if provider in {"sentence-transformers", "sentence-transformer", "local-model", "local-bge"}:
        model = source.get("RAG_IME_EMBEDDING_MODEL", "BAAI/bge-base-zh-v1.5").strip()
        if not model:
            return NullEmbeddingProvider()
        default_query_prefix = "为这个句子生成表示以用于检索相关文章：" if model == "BAAI/bge-base-zh-v1.5" else ""
        return SentenceTransformerEmbeddingProvider(
            model=model,
            query_prefix=source.get("RAG_IME_EMBEDDING_QUERY_PREFIX", default_query_prefix),
            document_prefix=source.get("RAG_IME_EMBEDDING_DOCUMENT_PREFIX", ""),
            cache_size=int(_float_env(source, "RAG_IME_EMBEDDING_CACHE_SIZE", 32)),
            cache_dir=source.get("RAG_IME_EMBEDDING_CACHE_DIR", "").strip(),
            local_files_only=source.get("RAG_IME_EMBEDDING_LOCAL_FILES_ONLY", "1").strip().lower()
            not in {"0", "false", "no", "off"},
        )
    if provider in {"mlx-bert", "local-bge-mlx", "mlx-bge"}:
        model = source.get("RAG_IME_EMBEDDING_MODEL", "").strip()
        if not model:
            return NullEmbeddingProvider()
        return MlxBertEmbeddingProvider(
            model=model,
            query_prefix=source.get("RAG_IME_EMBEDDING_QUERY_PREFIX", "为这个句子生成表示以用于检索相关文章："),
            document_prefix=source.get("RAG_IME_EMBEDDING_DOCUMENT_PREFIX", ""),
            bits=int(_float_env(source, "RAG_IME_EMBEDDING_BITS", 8)),
            group_size=int(_float_env(source, "RAG_IME_EMBEDDING_GROUP_SIZE", 32)),
            cache_size=int(_float_env(source, "RAG_IME_EMBEDDING_CACHE_SIZE", 32)),
        )
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


def embedding_provider_info(provider: EmbeddingProvider) -> dict[str, Any]:
    """Return public, secret-free provider diagnostics for status surfaces."""

    fingerprint = str(getattr(provider, "fingerprint", "none") or "none")
    if isinstance(provider, NullEmbeddingProvider):
        return {
            "provider": "none",
            "model": "",
            "fingerprint": fingerprint,
            "semantic": False,
            "configured": False,
        }
    if isinstance(provider, HashingEmbeddingProvider):
        return {
            "provider": "local-hash",
            "model": "deterministic-term-vector-v1",
            "dimensions": max(8, int(provider.dimensions)),
            "fingerprint": fingerprint,
            "semantic": False,
            "configured": True,
        }
    if isinstance(provider, SentenceTransformerEmbeddingProvider):
        return {
            "provider": "sentence-transformers",
            "model": provider.model,
            "fingerprint": fingerprint,
            "semantic": True,
            "configured": True,
        }
    if isinstance(provider, MlxBertEmbeddingProvider):
        return {
            "provider": "mlx-bert",
            "model": provider.model,
            "fingerprint": fingerprint,
            "semantic": True,
            "configured": True,
        }
    if isinstance(provider, OpenAICompatibleEmbeddingProvider):
        return {
            "provider": "openai-compatible",
            "model": provider.config.model,
            "fingerprint": fingerprint,
            "semantic": True,
            "configured": True,
        }
    return {
        "provider": type(provider).__name__,
        "model": str(getattr(provider, "model", "") or ""),
        "fingerprint": fingerprint,
        "semantic": True,
        "configured": True,
    }


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
