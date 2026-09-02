#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import time
from collections.abc import Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import ProxyHandler, Request, build_opener


TERMINAL_STATES = frozenset({"completed", "failed", "expired"})


def main() -> int:
    try:
        endpoint = _endpoint(
            os.environ.get(
                "RAG_IME_AGENT_GATEWAY_URL",
                "http://127.0.0.1:8768",
            )
        )
        timeout = _bounded_float(
            os.environ.get("RAG_IME_MEMORY_MAINTENANCE_TIMEOUT_SECONDS"),
            default=3_600.0,
            minimum=1.0,
            maximum=7_200.0,
        )
        poll_interval = _bounded_float(
            os.environ.get("RAG_IME_MEMORY_MAINTENANCE_POLL_SECONDS"),
            default=0.5,
            minimum=0.05,
            maximum=5.0,
        )
        trigger_mode = str(
            os.environ.get("RAG_IME_MEMORY_BOOK_MAINTENANCE_TRIGGER")
            or "scheduled"
        ).strip().lower()
        payload = {
            "project": str(os.environ.get("RAG_IME_PROJECT") or "").strip(),
            "manual": trigger_mode == "manual",
        }
        report = _trigger_and_wait(
            endpoint,
            payload,
            timeout_seconds=timeout,
            poll_interval=poll_interval,
        )
    except Exception as exc:
        report = {
            "schemaVersion": "rag-ime.gateway-memory-maintenance-client.v1",
            "ok": False,
            "state": "failed",
            "error": " ".join(str(exc).split())[:800] or exc.__class__.__name__,
        }
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    result = report.get("result")
    succeeded = (
        report.get("state") == "completed"
        and isinstance(result, Mapping)
        and result.get("ok") is True
    )
    return 0 if succeeded else 1


def _trigger_and_wait(
    endpoint: str,
    payload: Mapping[str, object],
    *,
    timeout_seconds: float,
    poll_interval: float,
) -> dict[str, object]:
    opener = build_opener(ProxyHandler({}))
    current = _request_json(
        opener,
        Request(
            endpoint,
            data=json.dumps(
                dict(payload),
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "RagIme-Memory-Maintenance/1",
            },
            method="POST",
        ),
        timeout=min(30.0, timeout_seconds),
    )
    job_id = str(current.get("jobId") or "").strip()
    if not job_id:
        raise RuntimeError("Agent Gateway did not return a Memory maintenance job id")
    deadline = time.monotonic() + timeout_seconds
    while str(current.get("state") or "") not in TERMINAL_STATES:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(
                f"Gateway Memory maintenance job timed out: {job_id}"
            )
        time.sleep(min(poll_interval, remaining))
        current = _request_json(
            opener,
            Request(
                f"{endpoint}?{urlencode({'jobId': job_id})}",
                headers={
                    "Accept": "application/json",
                    "User-Agent": "RagIme-Memory-Maintenance/1",
                },
                method="GET",
            ),
            timeout=min(30.0, max(1.0, remaining)),
        )
    return current


def _endpoint(value: object) -> str:
    base = str(value or "").strip().rstrip("/")
    parsed = urlparse(base)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ValueError("Memory maintenance Gateway URL must be a loopback HTTP origin")
    return f"{base}/api/agent/memory-maintenance"


def _request_json(opener: object, request: Request, *, timeout: float) -> dict[str, object]:
    try:
        with opener.open(request, timeout=timeout) as response:  # type: ignore[attr-defined]
            raw = response.read()
    except HTTPError as exc:
        raw = exc.read()
        detail = _response_error(raw) or str(exc.reason or "HTTP error")
        raise RuntimeError(f"Agent Gateway returned HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"Agent Gateway is unavailable: {exc.reason}") from exc
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("Agent Gateway returned invalid JSON") from exc
    if not isinstance(decoded, dict):
        raise RuntimeError("Agent Gateway returned a non-object JSON response")
    return decoded


def _response_error(raw: bytes) -> str:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        return ""
    if not isinstance(payload, dict):
        return ""
    return " ".join(str(payload.get("error") or "").split())[:800]


def _bounded_float(
    value: object,
    *,
    default: float,
    minimum: float,
    maximum: float,
) -> float:
    try:
        parsed = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


if __name__ == "__main__":
    raise SystemExit(main())
