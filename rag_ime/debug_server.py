from __future__ import annotations

import copy
import hashlib
import json
import mimetypes
import time
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Event, RLock
from typing import Any
from urllib.parse import unquote, urlparse

from .adapter import InputMethodAdapter, SuggestionRequest
from .cli import seed_demo_memories
from .core_client import CoreClient, default_fixture_memories
from .history_context import build_prediction_context
from .local_sqlite_core import LocalSqliteCoreClient
from .models import MemoryAction
from .payloads import action_response_payload, suggestions_response_payload
from .predictor import PredictionProvider, prediction_provider_from_env, prediction_provider_status
from .rime_sidecar import (
    build_rime_sidecar_response,
    choose_semantic_query,
    decide_side_candidate_refresh,
    parse_rime_context_payload,
    record_rime_side_candidate_selection,
    rime_context_to_payload,
    semantic_signal_length,
)
from .text_utils import now_ms


@dataclass(frozen=True)
class DebugServerConfig:
    host: str = "127.0.0.1"
    port: int = 8765
    db_path: Path = Path(".rag-ime-data/rag-ime.sqlite")
    project: str = "wisdom-weasel-rag-ime"
    static_dir: Path = Path("debug")
    seed_if_empty: bool = True
    core: CoreClient | None = None
    predictor: PredictionProvider | None = None
    server_name: str = "debug server"
    rime_cache_ttl_ms: int = 400


@dataclass
class _RimeSuggestCacheEntry:
    expires_at: float
    response: dict[str, object]


@dataclass
class _RimeSuggestInflightEntry:
    event: Event
    response: dict[str, object] | None = None
    error: BaseException | None = None
    waiters: int = 0


class DebugImeService:
    """Small local HTTP facade for browser-based IME debugging."""

    def __init__(self, config: DebugServerConfig):
        self.config = config
        self.core = config.core or LocalSqliteCoreClient(config.db_path)
        self.predictor = config.predictor or prediction_provider_from_env()
        self.adapter = InputMethodAdapter(self.core, project=config.project)
        self._rime_cache: dict[str, _RimeSuggestCacheEntry] = {}
        self._rime_inflight: dict[str, _RimeSuggestInflightEntry] = {}
        self._rime_cache_lock = RLock()
        self._rime_cache_hits = 0
        self._rime_cache_misses = 0
        self._rime_inflight_hits = 0
        self._rime_inflight_errors = 0
        if isinstance(self.core, LocalSqliteCoreClient):
            self.core.initialize()
        if config.seed_if_empty and self._event_count() == 0:
            seed_demo_memories(self.adapter, default_fixture_memories())

    def health(self) -> dict[str, object]:
        return {
            "ok": True,
            "project": self.config.project,
            "coreMode": "local" if isinstance(self.core, LocalSqliteCoreClient) else "json",
            "dbPath": str(self.config.db_path),
            "eventCount": self._event_count(),
            "actionCount": self._action_count(),
            "rimeSuggestCache": {
                "ttlMs": self._cache_ttl_ms(),
                "size": self._rime_cache_size(),
                "hits": self._rime_cache_hits,
                "misses": self._rime_cache_misses,
                "inFlight": self._rime_inflight_size(),
                "inFlightHits": self._rime_inflight_hits,
                "inFlightErrors": self._rime_inflight_errors,
            },
            "predictor": prediction_provider_status(self.predictor),
            "suggestionCache": self._suggestion_cache_stats(),
            "vectorStats": self._vector_index_stats(),
        }

    def seed(self) -> dict[str, object]:
        event_ids = seed_demo_memories(self.adapter, default_fixture_memories())
        self._clear_rime_cache()
        return {
            "ok": True,
            "seeded": len(event_ids),
            "eventCount": self._event_count(),
        }

    def suggest(self, payload: dict[str, Any]) -> dict[str, object]:
        current_input = _string(payload.get("currentInput"))
        recent_context = _string(payload.get("recentContext"))
        project = _string(payload.get("project")) or self.config.project
        top_k = _bounded_int(payload.get("topK"), default=5, minimum=1, maximum=10)
        prediction_context = build_prediction_context(
            self.core,
            explicit_recent_context=recent_context,
            project=project,
        )
        model_predictions = self.predictor.predict(
            current_input=current_input,
            recent_context=prediction_context,
            max_candidates=5,
        )
        suggestions = self.adapter.suggest(
            SuggestionRequest(
                current_input=current_input,
                recent_context=prediction_context,
                project=project,
                top_k=top_k,
            )
        )
        return suggestions_response_payload(
            current_input=current_input,
            recent_context=recent_context,
            project=project,
            history_context=prediction_context,
            model_predictions=model_predictions,
            suggestions=suggestions,
        )

    def rime_suggest(self, payload: dict[str, Any]) -> dict[str, object]:
        cache_key = self._rime_suggest_cache_key(payload)
        cached = self._get_cached_rime_response(cache_key, payload)
        if cached is not None:
            return cached
        owner, inflight = self._begin_rime_inflight(cache_key)
        if not owner:
            return self._wait_for_rime_inflight(cache_key, inflight, payload)
        try:
            response = build_rime_sidecar_response(
                payload=payload,
                adapter=self.adapter,
                core=self.core,
                predictor=self.predictor,
                default_project=self.config.project,
            )
        except BaseException as exc:
            self._finish_rime_inflight(cache_key, error=exc)
            raise
        self._store_rime_response(cache_key, response)
        self._finish_rime_inflight(cache_key, response=response)
        response = copy.deepcopy(response)
        response["cache"] = self._cache_payload(hit=False, cache_key=cache_key)
        return response

    def rime_select(self, payload: dict[str, Any]) -> dict[str, object]:
        response = record_rime_side_candidate_selection(
            payload=payload,
            adapter=self.adapter,
            core=self.core,
            default_project=self.config.project,
        )
        self._clear_rime_cache()
        return response

    def commit(self, payload: dict[str, Any]) -> dict[str, object]:
        text = _string(payload.get("text")).strip()
        if not text:
            raise ValueError("text must not be empty")
        event_id = self.adapter.commit_text(
            text,
            recent_context=_string(payload.get("recentContext")),
            preedit=_string(payload.get("preedit")),
            project=_string(payload.get("project")) or self.config.project,
            candidate_rank=_optional_int(payload.get("candidateRank")),
            provider_name=_string(payload.get("providerName")) or "debug-page",
            tags=tuple(_string_list(payload.get("tags"))),
            source=_string(payload.get("source")) or "debug_page_commit",
        )
        self._clear_rime_cache()
        return {"ok": True, "eventId": event_id, "eventCount": self._event_count()}

    def action(self, payload: dict[str, Any]) -> dict[str, object]:
        action_type = _canonical_action(_string(payload.get("actionType")))
        memory_id = _string(payload.get("memoryId"))
        if not memory_id:
            raise ValueError("memoryId must not be empty")
        action = self.core.apply_action(
            MemoryAction(
                action_id=None,
                created_at_ms=now_ms(),
                memory_id=memory_id,
                action_type=action_type,
                query=_string(payload.get("query")),
                suggestion_id=_string(payload.get("suggestionId")),
                source_event_id=_optional_int(payload.get("sourceEventId")),
                metadata={"surface_text": _string(payload.get("surfaceText"))},
            )
        )
        self._clear_rime_cache()
        return action_response_payload(action)

    def _event_count(self) -> int | None:
        count = getattr(self.core, "event_count", None)
        return int(count()) if callable(count) else None

    def _action_count(self) -> int | None:
        count = getattr(self.core, "action_count", None)
        return int(count()) if callable(count) else None

    def _suggestion_cache_stats(self) -> dict[str, object] | None:
        stats = getattr(self.core, "suggestion_cache_stats", None)
        return stats() if callable(stats) else None

    def _vector_index_stats(self) -> dict[str, object] | None:
        stats = getattr(self.core, "vector_index_stats", None)
        return stats() if callable(stats) else None

    def _cache_ttl_ms(self) -> int:
        return max(0, int(self.config.rime_cache_ttl_ms))

    def _rime_cache_size(self) -> int:
        with self._rime_cache_lock:
            self._prune_rime_cache()
            return len(self._rime_cache)

    def _rime_inflight_size(self) -> int:
        with self._rime_cache_lock:
            return len(self._rime_inflight)

    def _rime_suggest_cache_key(self, payload: dict[str, Any]) -> str:
        snapshot = parse_rime_context_payload(payload, default_project=self.config.project)
        semantic_query, query_basis = choose_semantic_query(snapshot)
        trigger_decision = decide_side_candidate_refresh(
            snapshot=snapshot,
            semantic_query=semantic_query,
            query_basis=query_basis,
        )
        raw_sensitive_input = {}
        if query_basis in ("preedit", "rawInputFallback") or snapshot.force_side_candidates:
            raw_sensitive_input = {
                "rawInput": snapshot.raw_input,
                "preedit": snapshot.preedit,
            }
        normalized_snapshot = {
            "project": snapshot.project or self.config.project,
            "semanticQuery": semantic_query,
            "queryBasis": query_basis,
            "triggerDecision": {
                "shouldRefresh": trigger_decision.should_refresh,
                "reason": trigger_decision.reason,
                "forceSideCandidates": snapshot.force_side_candidates,
            },
            "committedContext": snapshot.committed_context,
            "commitTextPreview": snapshot.commit_text_preview,
            "rimeContext": rime_context_to_payload(snapshot),
            "latencyBudgetMs": snapshot.latency_budget_ms,
            "maxVisibleCandidates": snapshot.max_visible_candidates,
            "maxSideCandidates": snapshot.max_side_candidates,
            **raw_sensitive_input,
        }
        material = {
            "snapshot": normalized_snapshot,
            "project": self.config.project,
            "eventCount": self._event_count(),
            "actionCount": self._action_count(),
            "vectorStats": self._vector_index_stats(),
            "predictor": self._predictor_fingerprint(),
        }
        raw = json.dumps(material, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _predictor_fingerprint(self) -> str:
        config = getattr(self.predictor, "config", None)
        if config is None:
            return self.predictor.__class__.__name__
        return f"{self.predictor.__class__.__name__}:{config!r}"

    def _get_cached_rime_response(self, cache_key: str, payload: dict[str, Any]) -> dict[str, object] | None:
        ttl_ms = self._cache_ttl_ms()
        if ttl_ms <= 0:
            return None
        now = time.monotonic()
        with self._rime_cache_lock:
            self._prune_rime_cache(now=now)
            entry = self._rime_cache.get(cache_key)
            if entry is None or entry.expires_at <= now:
                if entry is not None:
                    self._rime_cache.pop(cache_key, None)
                return None
            self._rime_cache_hits += 1
            response = copy.deepcopy(entry.response)
        self._refresh_cached_rime_response(response, payload)
        response["sessionId"] = _string(payload.get("sessionId")) or str(response.get("sessionId") or "default")
        response["requestSeq"] = _bounded_int(payload.get("requestSeq"), default=0, minimum=0, maximum=2**63 - 1)
        response["cache"] = self._cache_payload(hit=True, cache_key=cache_key)
        return response

    def _refresh_cached_rime_response(self, response: dict[str, object], payload: dict[str, Any]) -> None:
        snapshot = parse_rime_context_payload(payload, default_project=self.config.project)
        semantic_query, query_basis = choose_semantic_query(snapshot)
        trigger_decision = decide_side_candidate_refresh(
            snapshot=snapshot,
            semantic_query=semantic_query,
            query_basis=query_basis,
        )
        response.update(
            {
                "project": snapshot.project or self.config.project,
                "rawInput": snapshot.raw_input,
                "preedit": snapshot.preedit,
                "commitTextPreview": snapshot.commit_text_preview,
                "committedContext": snapshot.committed_context,
                "semanticQuery": semantic_query,
                "queryBasis": query_basis,
                "latencyBudgetMs": snapshot.latency_budget_ms,
                "rimeContext": rime_context_to_payload(snapshot),
                "triggerDecision": {
                    "shouldRefresh": trigger_decision.should_refresh,
                    "reason": trigger_decision.reason,
                    "idleMs": snapshot.idle_ms,
                    "semanticSignalLength": semantic_signal_length(semantic_query),
                    "forceSideCandidates": snapshot.force_side_candidates,
                },
            }
        )

    def _store_rime_response(self, cache_key: str, response: dict[str, object]) -> None:
        ttl_ms = self._cache_ttl_ms()
        if ttl_ms <= 0:
            return
        with self._rime_cache_lock:
            self._rime_cache_misses += 1
            self._rime_cache[cache_key] = _RimeSuggestCacheEntry(
                expires_at=time.monotonic() + ttl_ms / 1000,
                response=copy.deepcopy(response),
            )
            self._prune_rime_cache()

    def _clear_rime_cache(self) -> None:
        with self._rime_cache_lock:
            self._rime_cache.clear()

    def _prune_rime_cache(self, *, now: float | None = None) -> None:
        current = time.monotonic() if now is None else now
        expired = [key for key, entry in self._rime_cache.items() if entry.expires_at <= current]
        for key in expired:
            self._rime_cache.pop(key, None)

    def _cache_payload(self, *, hit: bool, cache_key: str) -> dict[str, object]:
        return {
            "hit": hit,
            "inFlightHit": False,
            "key": cache_key[:16],
            "ttlMs": self._cache_ttl_ms(),
            "size": self._rime_cache_size(),
            "hits": self._rime_cache_hits,
            "misses": self._rime_cache_misses,
            "inFlight": self._rime_inflight_size(),
            "inFlightHits": self._rime_inflight_hits,
        }

    def _begin_rime_inflight(self, cache_key: str) -> tuple[bool, _RimeSuggestInflightEntry]:
        with self._rime_cache_lock:
            entry = self._rime_inflight.get(cache_key)
            if entry is not None:
                entry.waiters += 1
                self._rime_inflight_hits += 1
                return False, entry
            entry = _RimeSuggestInflightEntry(event=Event())
            self._rime_inflight[cache_key] = entry
            return True, entry

    def _wait_for_rime_inflight(
        self,
        cache_key: str,
        entry: _RimeSuggestInflightEntry,
        payload: dict[str, Any],
    ) -> dict[str, object]:
        entry.event.wait()
        if entry.error is not None:
            raise entry.error
        response = copy.deepcopy(entry.response or {})
        self._refresh_cached_rime_response(response, payload)
        response["sessionId"] = _string(payload.get("sessionId")) or str(response.get("sessionId") or "default")
        response["requestSeq"] = _bounded_int(payload.get("requestSeq"), default=0, minimum=0, maximum=2**63 - 1)
        response["cache"] = {
            **self._cache_payload(hit=False, cache_key=cache_key),
            "inFlightHit": True,
        }
        return response

    def _finish_rime_inflight(
        self,
        cache_key: str,
        *,
        response: dict[str, object] | None = None,
        error: BaseException | None = None,
    ) -> None:
        with self._rime_cache_lock:
            entry = self._rime_inflight.pop(cache_key, None)
            if entry is None:
                return
            if error is not None:
                self._rime_inflight_errors += 1
            entry.response = copy.deepcopy(response) if response is not None else None
            entry.error = error
            entry.event.set()


class DebugRequestHandler(BaseHTTPRequestHandler):
    service: DebugImeService
    static_dir: Path

    def do_GET(self) -> None:  # noqa: N802 - stdlib API
        parsed = urlparse(self.path)
        if parsed.path in ("/api/health", "/health"):
            self._write_json(HTTPStatus.OK, self.service.health())
            return
        self._serve_static(parsed.path)

    def do_POST(self) -> None:  # noqa: N802 - stdlib API
        try:
            payload = self._read_json()
            path = urlparse(self.path).path
            if path in ("/api/suggest", "/suggest"):
                self._write_json(HTTPStatus.OK, self.service.suggest(payload))
            elif path in ("/api/rime-suggest", "/rime-suggest"):
                self._write_json(HTTPStatus.OK, self.service.rime_suggest(payload))
            elif path in ("/api/rime-select", "/rime-select"):
                self._write_json(HTTPStatus.OK, self.service.rime_select(payload))
            elif path in ("/api/commit", "/commit"):
                self._write_json(HTTPStatus.OK, self.service.commit(payload))
            elif path in ("/api/action", "/action"):
                self._write_json(HTTPStatus.OK, self.service.action(payload))
            elif path in ("/api/seed", "/seed"):
                self._write_json(HTTPStatus.OK, self.service.seed())
            else:
                self._write_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "unknown endpoint"})
        except Exception as exc:  # pragma: no cover - exercised through browser/manual debugging
            self._write_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"[rag-ime-debug] {self.address_string()} - {fmt % args}")

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or "0")
        raw = self.rfile.read(length) if length else b"{}"
        if not raw:
            return {}
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("JSON payload must be an object")
        return data

    def _write_json(self, status: HTTPStatus, payload: dict[str, object]) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_static(self, request_path: str) -> None:
        relative = "index.html" if request_path in ("", "/") else unquote(request_path.lstrip("/"))
        candidate = (self.static_dir / relative).resolve()
        static_root = self.static_dir.resolve()
        if static_root not in candidate.parents and candidate != static_root:
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        if not candidate.exists() or not candidate.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        body = candidate.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run_debug_server(config: DebugServerConfig) -> None:
    service = DebugImeService(config)
    static_dir = config.static_dir

    class Handler(DebugRequestHandler):
        pass

    Handler.service = service
    Handler.static_dir = static_dir
    server = ThreadingHTTPServer((config.host, config.port), Handler)
    url = f"http://{config.host}:{config.port}/"
    print(f"RAG IME {config.server_name}: {url}")
    print(f"DB: {config.db_path}")
    server.serve_forever()


def _string(value: object) -> str:
    return value if isinstance(value, str) else ""


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _bounded_int(value: object, *, default: int, minimum: int, maximum: int) -> int:
    parsed = _optional_int(value)
    if parsed is None:
        return default
    return max(minimum, min(maximum, parsed))


def _canonical_action(value: str) -> str:
    aliases = {"accepted": "accepted", "accept": "accepted", "skipped": "skipped", "skip": "skipped"}
    action = aliases.get(value, value)
    allowed = {"accepted", "skipped", "pin", "unpin", "downrank", "delete", "hide", "restore"}
    if action not in allowed:
        raise ValueError(f"unsupported actionType: {value}")
    return action
