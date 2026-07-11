from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from .text_utils import compact_whitespace


NOTION_QUERY_SCHEMA_VERSION = "rag-ime.notion-query.v1"
NOTION_RESULT_SCHEMA_VERSION = "rag-ime.notion-result.v1"
NOTION_API_VERSION = "2026-03-11"


class NotionKnowledgeError(RuntimeError):
    pass


class NotionStaleResultError(NotionKnowledgeError):
    pass


@dataclass(frozen=True)
class NotionKnowledgeConfig:
    worker_url: str = ""
    status_url: str = ""
    status_token: str = ""
    api_token: str = ""
    data_source_id: str = ""
    request_secret: str = ""
    poll_interval_ms: int = 900
    timeout_ms: int = 120_000
    env_path: Path | None = None

    @property
    def submit_configured(self) -> bool:
        return bool(self.worker_url)

    @property
    def poll_configured(self) -> bool:
        return bool(self.status_url or (self.api_token and self.data_source_id))


def load_notion_knowledge_config(
    env_path: str | Path | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> NotionKnowledgeConfig:
    source = dict(os.environ if env is None else env)
    pointer = str(env_path or "").strip() or str(source.get("RAG_IME_NOTION_ENV") or "").strip()
    resolved = Path(pointer).expanduser() if pointer else None
    values: dict[str, str] = {}
    if resolved is not None and resolved.exists():
        values.update(_read_env_file(resolved))
    values.update(source)
    return NotionKnowledgeConfig(
        worker_url=_value(values, "RAG_IME_NOTION_WORKER_URL"),
        status_url=_value(values, "RAG_IME_NOTION_STATUS_URL"),
        status_token=_value(values, "RAG_IME_NOTION_STATUS_TOKEN"),
        api_token=_value(values, "RAG_IME_NOTION_TOKEN", "NOTION_API_TOKEN"),
        data_source_id=_value(values, "RAG_IME_NOTION_DATA_SOURCE_ID"),
        request_secret=_value(values, "RAG_IME_NOTION_WEBHOOK_SECRET"),
        poll_interval_ms=_positive_int(_value(values, "RAG_IME_NOTION_POLL_INTERVAL_MS"), 900),
        timeout_ms=_positive_int(_value(values, "RAG_IME_NOTION_TIMEOUT_MS"), 120_000),
        env_path=resolved,
    )


class NotionAsyncKnowledgeClient:
    """Submit an asynchronous Notion task and poll a separate result channel.

    Notion Worker webhooks acknowledge with HTTP 202 and do not return a custom
    application response. The result channel is therefore deliberately separate:
    either a user-operated status relay or the Notion API with a local read token.
    """

    def __init__(
        self,
        config: NotionKnowledgeConfig,
        *,
        urlopen: Callable[..., Any] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.config = config
        self.urlopen = urlopen or urllib.request.urlopen
        self.sleep = sleep

    def route_status(self) -> dict[str, object]:
        poll_mode = "status_relay" if self.config.status_url else (
            "notion_api" if self.config.api_token and self.config.data_source_id else "none"
        )
        return {
            "schemaVersion": "rag-ime.notion-route-status.v1",
            "submitConfigured": self.config.submit_configured,
            "pollConfigured": self.config.poll_configured,
            "ready": self.config.submit_configured and self.config.poll_configured,
            "pollMode": poll_mode,
            "requestSigning": bool(self.config.request_secret),
            "timeoutMs": self.config.timeout_ms,
            "missing": [
                name
                for name, present in (
                    ("worker_url", self.config.submit_configured),
                    ("status_channel", self.config.poll_configured),
                )
                if not present
            ],
        }

    def submit(
        self,
        *,
        query_id: str,
        question: str,
        context: str,
        context_hash: str,
        generation: int,
        project: str,
        mode: str,
    ) -> dict[str, object]:
        if not self.config.worker_url:
            raise NotionKnowledgeError("Notion Worker webhook is not configured")
        payload = {
            "schemaVersion": NOTION_QUERY_SCHEMA_VERSION,
            "queryId": query_id,
            "question": question,
            "context": context,
            "contextHash": context_hash,
            "generation": max(0, int(generation)),
            "project": project,
            "mode": mode,
        }
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "rag-ime/1.0 notion-knowledge",
        }
        if self.config.request_secret:
            signature = hmac.new(self.config.request_secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
            headers["X-RAG-IME-Signature"] = f"sha256={signature}"
        request = urllib.request.Request(self.config.worker_url, data=raw, headers=headers, method="POST")
        started = time.perf_counter()
        try:
            with self.urlopen(request, timeout=max(1.0, min(30.0, self.config.timeout_ms / 1000))) as response:
                status_code = int(getattr(response, "status", 200) or 200)
                response.read()
        except (TimeoutError, urllib.error.URLError, OSError) as exc:
            raise NotionKnowledgeError(f"Notion Worker submit failed: {exc}") from exc
        if not 200 <= status_code < 300:
            raise NotionKnowledgeError(f"Notion Worker submit returned HTTP {status_code}")
        return {
            "schemaVersion": NOTION_RESULT_SCHEMA_VERSION,
            "queryId": query_id,
            "status": "queued",
            "accepted": True,
            "httpStatus": status_code,
            "elapsedMs": int((time.perf_counter() - started) * 1000),
        }

    def poll(
        self,
        *,
        query_id: str,
        context_hash: str,
        generation: int,
        timeout_ms: int | None = None,
    ) -> dict[str, object]:
        if not self.config.poll_configured:
            raise NotionKnowledgeError("Notion result polling is not configured")
        budget = self.config.timeout_ms if timeout_ms is None else max(100, int(timeout_ms))
        deadline = time.monotonic() + budget / 1000
        last: dict[str, object] = {
            "schemaVersion": NOTION_RESULT_SCHEMA_VERSION,
            "queryId": query_id,
            "status": "queued",
        }
        while time.monotonic() < deadline:
            last = self.status(query_id=query_id)
            state = compact_whitespace(str(last.get("status") or "queued")).lower()
            if state in {"done", "failed", "cancelled"}:
                self._validate_fresh_result(
                    last,
                    query_id=query_id,
                    context_hash=context_hash,
                    generation=generation,
                )
                return last
            self.sleep(max(0.05, self.config.poll_interval_ms / 1000))
        return {**last, "status": "timeout", "error": "notion_result_timeout"}

    def status(self, *, query_id: str) -> dict[str, object]:
        if self.config.status_url:
            payload = self._status_from_relay(query_id=query_id)
        elif self.config.api_token and self.config.data_source_id:
            payload = self._status_from_notion_api(query_id=query_id)
        else:
            raise NotionKnowledgeError("Notion result polling is not configured")
        return _normalize_result(payload, fallback_query_id=query_id)

    def _status_from_relay(self, *, query_id: str) -> dict[str, object]:
        encoded = urllib.parse.quote(query_id, safe="")
        if "{query_id}" in self.config.status_url:
            url = self.config.status_url.replace("{query_id}", encoded)
        else:
            separator = "&" if "?" in self.config.status_url else "?"
            url = f"{self.config.status_url}{separator}query_id={encoded}"
        headers = {"Accept": "application/json", "User-Agent": "rag-ime/1.0 notion-knowledge"}
        if self.config.status_token:
            headers["Authorization"] = f"Bearer {self.config.status_token}"
        request = urllib.request.Request(url, headers=headers, method="GET")
        return self._read_json_request(request)

    def _status_from_notion_api(self, *, query_id: str) -> dict[str, object]:
        data_source_id = urllib.parse.quote(self.config.data_source_id, safe="")
        body = json.dumps(
            {
                "filter": {"property": "query_id", "title": {"equals": query_id}},
                "page_size": 1,
            },
            separators=(",", ":"),
        ).encode("utf-8")
        request = urllib.request.Request(
            f"https://api.notion.com/v1/data_sources/{data_source_id}/query",
            data=body,
            headers={
                "Authorization": f"Bearer {self.config.api_token}",
                "Notion-Version": NOTION_API_VERSION,
                "Content-Type": "application/json",
                "User-Agent": "rag-ime/1.0 notion-knowledge",
            },
            method="POST",
        )
        payload = self._read_json_request(request)
        results = payload.get("results") if isinstance(payload.get("results"), list) else []
        page = results[0] if results and isinstance(results[0], dict) else None
        if page is None:
            return {"queryId": query_id, "status": "queued"}
        return _result_from_notion_page(page, fallback_query_id=query_id)

    def _read_json_request(self, request: urllib.request.Request) -> dict[str, object]:
        try:
            with self.urlopen(request, timeout=max(1.0, min(30.0, self.config.timeout_ms / 1000))) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (TimeoutError, urllib.error.URLError, json.JSONDecodeError, OSError) as exc:
            raise NotionKnowledgeError(f"Notion status request failed: {exc}") from exc
        if not isinstance(payload, dict):
            raise NotionKnowledgeError("Notion status response must be a JSON object")
        return payload

    @staticmethod
    def _validate_fresh_result(
        payload: dict[str, object],
        *,
        query_id: str,
        context_hash: str,
        generation: int,
    ) -> None:
        actual_query_id = compact_whitespace(str(payload.get("queryId") or ""))
        actual_hash = compact_whitespace(str(payload.get("contextHash") or ""))
        try:
            actual_generation = int(payload.get("generation") or 0)
        except (TypeError, ValueError):
            actual_generation = -1
        if actual_query_id != query_id:
            raise NotionStaleResultError("Notion result queryId mismatch")
        if actual_hash != context_hash:
            raise NotionStaleResultError("Notion result contextHash mismatch")
        if actual_generation != int(generation):
            raise NotionStaleResultError("Notion result generation mismatch")


def _normalize_result(payload: dict[str, object], *, fallback_query_id: str) -> dict[str, object]:
    sources = payload.get("sources")
    if isinstance(sources, str):
        sources = _parse_sources(sources)
    if not isinstance(sources, list):
        sources = []
    return {
        "schemaVersion": NOTION_RESULT_SCHEMA_VERSION,
        "queryId": compact_whitespace(str(payload.get("queryId") or payload.get("query_id") or fallback_query_id)),
        "status": compact_whitespace(str(payload.get("status") or "queued")).lower(),
        "answer": str(payload.get("answer") or "").strip(),
        "sources": [item for item in sources if isinstance(item, (str, dict))],
        "contextHash": compact_whitespace(str(payload.get("contextHash") or payload.get("context_hash") or "")),
        "generation": _integer(payload.get("generation"), 0),
        "createdAt": str(payload.get("createdAt") or payload.get("created_at") or ""),
        "completedAt": str(payload.get("completedAt") or payload.get("completed_at") or ""),
        "error": compact_whitespace(str(payload.get("error") or "")),
    }


def _result_from_notion_page(page: dict[str, object], *, fallback_query_id: str) -> dict[str, object]:
    properties = page.get("properties") if isinstance(page.get("properties"), dict) else {}
    assert isinstance(properties, dict)
    return {
        "queryId": _property_text(properties.get("query_id")) or fallback_query_id,
        "status": _property_text(properties.get("status")) or "queued",
        "answer": _property_text(properties.get("answer")),
        "sources": _parse_sources(_property_text(properties.get("sources"))),
        "contextHash": _property_text(properties.get("context_hash")),
        "generation": _property_number(properties.get("generation")),
        "createdAt": _property_text(properties.get("created_at")),
        "completedAt": _property_text(properties.get("completed_at")),
        "error": _property_text(properties.get("error")),
    }


def _property_text(raw: object) -> str:
    if not isinstance(raw, dict):
        return ""
    for key in ("title", "rich_text"):
        parts = raw.get(key)
        if isinstance(parts, list):
            return "".join(_rich_text_value(item) for item in parts if isinstance(item, dict)).strip()
    selected = raw.get("status") if isinstance(raw.get("status"), dict) else raw.get("select")
    if isinstance(selected, dict):
        return compact_whitespace(str(selected.get("name") or ""))
    date = raw.get("date")
    if isinstance(date, dict):
        return str(date.get("start") or "")
    for key in ("url", "email", "phone_number"):
        if isinstance(raw.get(key), str):
            return str(raw[key])
    return ""


def _rich_text_value(item: dict[str, object]) -> str:
    if isinstance(item.get("plain_text"), str):
        return str(item["plain_text"])
    text = item.get("text")
    return str(text.get("content") or "") if isinstance(text, dict) else ""


def _property_number(raw: object) -> int:
    if isinstance(raw, dict):
        return _integer(raw.get("number"), 0)
    return 0


def _parse_sources(raw: str) -> list[object]:
    text = raw.strip()
    if not text:
        return []
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return [item.strip() for item in text.splitlines() if item.strip()]
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, (str, dict))]
    return []


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, raw = stripped.split("=", 1)
        values[key.strip()] = raw.strip().strip("'\"")
    return values


def _value(values: Mapping[str, str], *names: str) -> str:
    for name in names:
        value = str(values.get(name, "")).strip()
        if value:
            return value
    return ""


def _positive_int(raw: object, default: int) -> int:
    value = _integer(raw, default)
    return value if value > 0 else default


def _integer(raw: object, default: int) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default
