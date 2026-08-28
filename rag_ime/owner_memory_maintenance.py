from __future__ import annotations

import argparse
import json
import os
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import ProxyHandler, Request, build_opener

from .owner_memory_curation import (
    DEFAULT_MAX_SOURCES,
    MAX_PERSONAL_V2_SOURCES,
)


_DEFAULT_GATEWAY_URL = "http://127.0.0.1:8768"
_TERMINAL_JOB_STATES = frozenset({"completed", "failed", "expired"})


class GatewayMemoryMaintenanceJobs:
    """One process-local trigger lane; curation truth remains in SQLite."""

    def __init__(
        self,
        execute: Callable[[Mapping[str, object]], Mapping[str, object]],
    ) -> None:
        self._execute = execute
        self._lock = threading.RLock()
        self._jobs: dict[str, dict[str, object]] = {}
        self._active_job_id = ""
        self._closed = False

    def trigger(self, payload: Mapping[str, object]) -> dict[str, object]:
        with self._lock:
            if self._closed:
                raise RuntimeError("Gateway memory maintenance is closed")
            if self._active_job_id:
                active = self._jobs.get(self._active_job_id)
                if active is not None and str(active.get("state")) in {
                    "queued",
                    "running",
                }:
                    return self._payload(active, reused=True)
            job_id = f"memory-maintenance:{uuid.uuid4()}"
            timestamp = int(time.time() * 1_000)
            job: dict[str, object] = {
                "jobId": job_id,
                "state": "queued",
                "request": dict(payload),
                "result": {},
                "progress": {},
                "error": "",
                "createdAtMs": timestamp,
                "updatedAtMs": timestamp,
                "completedAtMs": 0,
            }
            self._jobs[job_id] = job
            self._active_job_id = job_id
            thread = threading.Thread(
                target=self._run,
                args=(job_id,),
                name="rag-ime-gateway-memory-maintenance",
                daemon=True,
            )
            job["thread"] = thread
            thread.start()
            return self._payload(job, reused=False)

    def status(self, job_id: object) -> dict[str, object]:
        normalized = str(job_id or "").strip()
        with self._lock:
            job = self._jobs.get(normalized)
            if job is None:
                # Jobs deliberately live in the Gateway process because the
                # durable maintenance truth is recorded by the SQLite owner.
                # A refresh after a Gateway restart therefore cannot recover
                # the old worker, and must not look like an active/failed run
                # with invented progress. Return a terminal, retryable
                # projection so HTTP clients can stop polling and start a new
                # run explicitly.
                return self._expired_payload(normalized)
            return self._payload(job, reused=False)

    def activity_timeline_status(self, *, project: str = "") -> dict[str, object]:
        """Return one safe timeline-job projection for refresh recovery."""

        normalized_project = str(project or "").strip()
        with self._lock:
            candidates = sorted(
                self._jobs.values(),
                key=lambda item: int(item.get("updatedAtMs") or 0),
                reverse=True,
            )
            active = self._jobs.get(self._active_job_id)
            if active is not None and self._matches_project(
                active,
                normalized_project,
            ):
                return self._timeline_payload(active)
            for job in candidates:
                if not self._matches_project(job, normalized_project):
                    continue
                request = (
                    job.get("request")
                    if isinstance(job.get("request"), Mapping)
                    else {}
                )
                if request.get("timelineDate") or request.get("timelineThroughDate"):
                    return self._timeline_payload(job)
                if self._automatic_timeline_result(job):
                    return self._timeline_payload(job)
            return {}

    def close(self) -> None:
        with self._lock:
            self._closed = True

    def _run(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job["state"] = "running"
            job["updatedAtMs"] = int(time.time() * 1_000)
            request = dict(job["request"])
            timeline_date = str(request.get("timelineDate") or "").strip()
            timeline_through_date = str(
                request.get("timelineThroughDate") or ""
            ).strip()
            if timeline_through_date:
                job["progress"] = {
                    "phase": "activity_timeline_catch_up",
                    "throughDate": timeline_through_date,
                    "currentDate": "",
                    "totalDayCount": 0,
                    "completedDayCount": 0,
                }
            elif timeline_date:
                job["progress"] = {
                    "phase": "activity_timeline_single",
                    "currentDate": timeline_date,
                    "totalDayCount": 1,
                    "completedDayCount": 0,
                }
            else:
                job["progress"] = {
                    "phase": "memory_maintenance",
                    "currentDate": "",
                    "totalDayCount": 0,
                    "completedDayCount": 0,
                }
            request["_progressCallback"] = lambda value: self._set_progress(
                job_id,
                value,
            )
        state = "failed"
        result: dict[str, object] = {}
        error = ""
        try:
            result = dict(self._execute(request))
            state = "completed" if result.get("ok") is True else "failed"
            if state == "failed":
                error = " ".join(str(result.get("error") or "maintenance_failed").split())[:800]
        except Exception as exc:
            error = " ".join(str(exc).split())[:800] or exc.__class__.__name__
        timestamp = int(time.time() * 1_000)
        with self._lock:
            job = self._jobs[job_id]
            job["state"] = state
            job["result"] = result
            job["error"] = error
            job["updatedAtMs"] = timestamp
            job["completedAtMs"] = timestamp
            job.pop("thread", None)
            if self._active_job_id == job_id:
                self._active_job_id = ""
            self._prune_locked()

    def _set_progress(
        self,
        job_id: str,
        value: Mapping[str, object],
    ) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or str(job.get("state")) not in {"queued", "running"}:
                return
            job["progress"] = dict(value)
            job["updatedAtMs"] = int(time.time() * 1_000)

    def _prune_locked(self) -> None:
        terminal = sorted(
            (
                job
                for job in self._jobs.values()
                if str(job.get("state")) in _TERMINAL_JOB_STATES
            ),
            key=lambda item: int(item.get("completedAtMs") or 0),
            reverse=True,
        )
        for stale in terminal[64:]:
            self._jobs.pop(str(stale.get("jobId") or ""), None)

    @staticmethod
    def _matches_project(job: Mapping[str, object], project: str) -> bool:
        request = (
            job.get("request")
            if isinstance(job.get("request"), Mapping)
            else {}
        )
        requested_project = str(request.get("project") or "").strip()
        # A blank request project means "use this Gateway's configured
        # project".  That is how the installed scheduled trigger runs, so it
        # must remain visible when the calendar queries the resolved project.
        return not project or not requested_project or requested_project == project

    @classmethod
    def _timeline_payload(cls, job: Mapping[str, object]) -> dict[str, object]:
        request = (
            job.get("request")
            if isinstance(job.get("request"), Mapping)
            else {}
        )
        mode = (
            "manual_catch_up"
            if request.get("timelineThroughDate")
            else "single_day"
            if request.get("timelineDate")
            else "automatic_catch_up"
        )
        timeline_result = cls._automatic_timeline_result(job)
        result_summary = {
            key: timeline_result[key]
            for key in (
                "ok",
                "throughDate",
                "pendingDayCount",
                "batchDayCount",
                "completedDayCount",
                "remainingDayCount",
                "failedDate",
                "error",
                "status",
                "autoPublished",
                "semanticOrganization",
                "activityTimelineSummary",
                "warningCount",
                "activityTimelines",
            )
            if key in timeline_result
        }
        return {
            "schemaVersion": "rag-ime.activity-timeline-job-status.v1",
            "ok": str(job.get("state") or "") != "failed",
            "jobId": str(job.get("jobId") or ""),
            "state": str(job.get("state") or ""),
            "mode": mode,
            "progress": (
                dict(job.get("progress") or {})
                if isinstance(job.get("progress"), Mapping)
                else {}
            ),
            "result": result_summary,
            "error": str(result_summary.get("error") or job.get("error") or ""),
            "createdAtMs": int(job.get("createdAtMs") or 0),
            "updatedAtMs": int(job.get("updatedAtMs") or 0),
            "completedAtMs": int(job.get("completedAtMs") or 0),
        }

    @staticmethod
    def _automatic_timeline_result(job: Mapping[str, object]) -> dict[str, object]:
        request = (
            job.get("request")
            if isinstance(job.get("request"), Mapping)
            else {}
        )
        result = (
            job.get("result")
            if isinstance(job.get("result"), Mapping)
            else {}
        )
        if request.get("timelineDate") or request.get("timelineThroughDate"):
            return dict(result)
        dreaming = (
            result.get("dreaming")
            if isinstance(result.get("dreaming"), Mapping)
            else result
        )
        catch_up = (
            dreaming.get("activityTimelineCatchUp")
            if isinstance(dreaming, Mapping)
            and isinstance(dreaming.get("activityTimelineCatchUp"), Mapping)
            else {}
        )
        return dict(catch_up)

    @staticmethod
    def _payload(
        job: Mapping[str, object],
        *,
        reused: bool,
    ) -> dict[str, object]:
        return {
            "schemaVersion": "rag-ime.gateway-memory-maintenance-job.v1",
            "ok": str(job.get("state")) != "failed",
            "jobId": str(job.get("jobId") or ""),
            "state": str(job.get("state") or ""),
            "reused": bool(reused),
            "result": (
                dict(job.get("result") or {})
                if isinstance(job.get("result"), Mapping)
                else {}
            ),
            "progress": (
                dict(job.get("progress") or {})
                if isinstance(job.get("progress"), Mapping)
                else {}
            ),
            "error": str(job.get("error") or ""),
            "createdAtMs": int(job.get("createdAtMs") or 0),
            "updatedAtMs": int(job.get("updatedAtMs") or 0),
            "completedAtMs": int(job.get("completedAtMs") or 0),
        }

    @staticmethod
    def _expired_payload(job_id: str) -> dict[str, object]:
        return {
            "schemaVersion": "rag-ime.gateway-memory-maintenance-job.v1",
            "ok": False,
            "jobId": job_id,
            "state": "expired",
            "reused": False,
            "result": {},
            "progress": {},
            "errorCode": "memory_maintenance_job_expired",
            "error": (
                "Gateway restarted before this process-local Memory maintenance "
                "job could be read; the old job cannot be recovered."
            ),
            "recovery": {
                "recoverable": False,
                "retryable": True,
                "action": "trigger_new_job",
                "reason": "process_local_job_registry_lost",
            },
            "createdAtMs": 0,
            "updatedAtMs": 0,
            "completedAtMs": 0,
        }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Ask the resident Agent Gateway to run Memory maintenance.",
    )
    parser.add_argument(
        "--gateway-url",
        default=os.environ.get("RAG_IME_AGENT_GATEWAY_URL", _DEFAULT_GATEWAY_URL),
    )
    parser.add_argument("--project", default="")
    parser.add_argument("--owner-kind", default="")
    parser.add_argument("--owner-id", default="")
    parser.add_argument("--instruction", default="")
    parser.add_argument("--manual", action="store_true")
    parser.add_argument("--max-sources", type=int, default=DEFAULT_MAX_SOURCES)
    parser.add_argument("--timeout-seconds", type=float, default=3_600.0)
    parser.add_argument("--poll-interval", type=float, default=0.5)
    # Accepted only so old manual invocations fail over to the new Gateway
    # owner without launching a second Runtime Host or reading SQLite here.
    parser.add_argument("--db-path", default="", help=argparse.SUPPRESS)
    parser.add_argument("--model-env-path", default="", help=argparse.SUPPRESS)
    parser.add_argument("--model", default="", help=argparse.SUPPRESS)
    auto_apply = parser.add_mutually_exclusive_group()
    auto_apply.add_argument(
        "--auto-apply",
        dest="auto_apply",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    auto_apply.add_argument(
        "--no-auto-apply",
        dest="auto_apply",
        action="store_false",
        help=argparse.SUPPRESS,
    )
    parser.set_defaults(auto_apply=None)
    return parser


def run_gateway_memory_maintenance(
    gateway_url: object,
    payload: Mapping[str, object],
    *,
    timeout_seconds: float = 3_600.0,
    poll_interval: float = 0.5,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, object]:
    endpoint = _gateway_endpoint(gateway_url)
    timeout = max(1.0, min(7_200.0, float(timeout_seconds)))
    interval = max(0.05, min(5.0, float(poll_interval)))
    opener = build_opener(ProxyHandler({}))
    triggered = _request_json(
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
        timeout=min(30.0, timeout),
    )
    job_id = str(triggered.get("jobId") or "").strip()
    if not job_id:
        raise RuntimeError("Agent Gateway did not return a Memory maintenance job id")
    deadline = time.monotonic() + timeout
    current = triggered
    while str(current.get("state") or "") not in _TERMINAL_JOB_STATES:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(
                f"Gateway Memory maintenance job timed out: {job_id}"
            )
        time.sleep(min(interval, remaining))
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


def _gateway_endpoint(value: object) -> str:
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
    return " ".join(str(payload.get("error") or "").split())[:800] if isinstance(payload, dict) else ""


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = {
        "project": str(args.project or "").strip(),
        "ownerKind": str(args.owner_kind or "").strip(),
        "ownerId": str(args.owner_id or "").strip(),
        "instruction": str(args.instruction or "").strip(),
        "manual": bool(args.manual),
        "maxSources": max(1, min(MAX_PERSONAL_V2_SOURCES, int(args.max_sources))),
    }
    try:
        report = run_gateway_memory_maintenance(
            args.gateway_url,
            payload,
            timeout_seconds=args.timeout_seconds,
            poll_interval=args.poll_interval,
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
    result_ok = isinstance(result, Mapping) and result.get("ok") is True
    return 0 if report.get("state") == "completed" and result_ok else 1


if __name__ == "__main__":
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    raise SystemExit(main())
