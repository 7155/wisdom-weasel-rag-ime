from __future__ import annotations

import json
import mimetypes
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .adapter import InputMethodAdapter, SuggestionRequest
from .cli import seed_demo_memories
from .core_client import CoreClient, default_fixture_memories
from .local_sqlite_core import LocalSqliteCoreClient
from .models import MemoryAction
from .payloads import action_response_payload, suggestions_response_payload
from .predictor import PredictionProvider, prediction_provider_from_env
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


class DebugImeService:
    """Small local HTTP facade for browser-based IME debugging."""

    def __init__(self, config: DebugServerConfig):
        self.config = config
        self.core = config.core or LocalSqliteCoreClient(config.db_path)
        self.predictor = config.predictor or prediction_provider_from_env()
        self.adapter = InputMethodAdapter(self.core, project=config.project)
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
        }

    def seed(self) -> dict[str, object]:
        event_ids = seed_demo_memories(self.adapter, default_fixture_memories())
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
        model_predictions = self.predictor.predict(
            current_input=current_input,
            recent_context=recent_context,
            max_candidates=5,
        )
        suggestions = self.adapter.suggest(
            SuggestionRequest(
                current_input=current_input,
                recent_context=recent_context,
                project=project,
                top_k=top_k,
            )
        )
        return suggestions_response_payload(
            current_input=current_input,
            recent_context=recent_context,
            project=project,
            model_predictions=model_predictions,
            suggestions=suggestions,
        )

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
            source="debug_page_commit",
        )
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
        return action_response_payload(action)

    def _event_count(self) -> int | None:
        count = getattr(self.core, "event_count", None)
        return int(count()) if callable(count) else None

    def _action_count(self) -> int | None:
        count = getattr(self.core, "action_count", None)
        return int(count()) if callable(count) else None


class DebugRequestHandler(BaseHTTPRequestHandler):
    service: DebugImeService
    static_dir: Path

    def do_GET(self) -> None:  # noqa: N802 - stdlib API
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            self._write_json(HTTPStatus.OK, self.service.health())
            return
        self._serve_static(parsed.path)

    def do_POST(self) -> None:  # noqa: N802 - stdlib API
        try:
            payload = self._read_json()
            if self.path == "/api/suggest":
                self._write_json(HTTPStatus.OK, self.service.suggest(payload))
            elif self.path == "/api/commit":
                self._write_json(HTTPStatus.OK, self.service.commit(payload))
            elif self.path == "/api/action":
                self._write_json(HTTPStatus.OK, self.service.action(payload))
            elif self.path == "/api/seed":
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
    print(f"RAG IME debug server: {url}")
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
