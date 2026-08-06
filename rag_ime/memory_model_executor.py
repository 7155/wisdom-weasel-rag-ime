from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Protocol

from .agent_events import AgentEventHub
from .agent_sessions import AgentSessionStore
from .agent_tool_ids import MEMORY_CURATION_TOOL_PROFILE


MEMORY_CURATION_PROFILE = "MEMORY_CURATION"
REQUIRED_MEMORY_MODEL_REFERENCE = "openai-codex/gpt-5.6-luna"
REQUIRED_MEMORY_THINKING_LEVEL = "max"
MINIMUM_MEMORY_CONTEXT_TOKENS = 272_000
MAXIMUM_MEMORY_PROMPT_CHARS = 1_000_000
DEFAULT_MEMORY_CURATION_TIMEOUT_SECONDS = 1_200.0


class MemoryModelUnavailable(RuntimeError):
    """The selected governed Provider/runtime cannot execute memory work."""


class MemoryModelTimeout(MemoryModelUnavailable):
    """A resumable Memory Session did not settle inside its bounded lease."""


class MemorySessionRuntime(Protocol):
    sessions: AgentSessionStore
    events: AgentEventHub

    def available_models(self) -> list[dict[str, object]]: ...

    def set_model(
        self,
        session_id: str,
        *,
        provider: str,
        model_id: str,
    ) -> dict[str, object]: ...

    def set_thinking_level(
        self,
        session_id: str,
        *,
        level: str,
    ) -> dict[str, object]: ...

    def prompt(
        self,
        session_id: str,
        message: str,
        *,
        images: list[Mapping[str, str]] | None = None,
        client_message_id: str = "",
        delivery: str = "prompt",
    ) -> dict[str, object]: ...

    def abort(self, session_id: str) -> dict[str, object]: ...

    def close_session(self, session_id: str) -> bool: ...


@dataclass
class GovernedMemoryModelExecutor:
    """Run curation in one hidden Session owned by the resident Gateway.

    SQLite owns the frozen request and terminal response. The Pi transcript is
    only a resumable transport artifact and is retired when the curation run is
    terminal.
    """

    runtime: MemorySessionRuntime
    provider: str
    model_id: str
    thinking_level: str
    timeout_seconds: float = DEFAULT_MEMORY_CURATION_TIMEOUT_SECONDS
    sessions: AgentSessionStore | None = None
    events: AgentEventHub | None = None
    db_path: str | Path | None = None

    def __post_init__(self) -> None:
        self.provider = _model_part(self.provider, field="provider", maximum=80)
        self.model_id = _model_part(self.model_id, field="modelId", maximum=160)
        self.thinking_level = str(self.thinking_level or "").strip().lower()
        if self.reference != REQUIRED_MEMORY_MODEL_REFERENCE:
            raise MemoryModelUnavailable(
                "memory curation requires the canonical live model "
                f"{REQUIRED_MEMORY_MODEL_REFERENCE}; received {self.reference}"
            )
        if self.thinking_level != REQUIRED_MEMORY_THINKING_LEVEL:
            raise MemoryModelUnavailable(
                "memory curation requires thinking=max"
            )
        self.timeout_seconds = max(1.0, min(3_600.0, float(self.timeout_seconds)))
        self.sessions = self.sessions or getattr(self.runtime, "sessions", None)
        self.events = self.events or getattr(self.runtime, "events", None)
        if not isinstance(self.sessions, AgentSessionStore):
            raise MemoryModelUnavailable(
                "Gateway Memory executor requires the resident Agent Session store"
            )
        if not isinstance(self.events, AgentEventHub):
            raise MemoryModelUnavailable(
                "Gateway Memory executor requires the resident Agent event hub"
            )
        resolved_db_path = self.db_path or self.sessions.db_path
        self.db_path = Path(resolved_db_path)
        self.sessions.initialize()
        self._lock = threading.RLock()
        self._active_run_id = ""
        self._active_session_id = ""
        self.selected_model = self._resolve_live_model()

    @property
    def reference(self) -> str:
        return f"{self.provider}/{self.model_id}"

    def begin_run(
        self,
        run_id: object,
        *,
        frozen_input_sha256: object = "",
    ) -> dict[str, object]:
        normalized_run_id = _identifier(run_id, field="runId", maximum=240)
        frozen_hash = _sha256_value(frozen_input_sha256, allow_empty=True)
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT * FROM memory_curation_model_runs WHERE run_id = ?",
                    (normalized_run_id,),
                ).fetchone()
            if row is None:
                session = self._create_internal_session(
                    title=f"Memory curation · {_short_run_label(normalized_run_id)}",
                )
                timestamp = _now_ms()
                with self._connect() as conn:
                    conn.execute(
                        """
                        INSERT INTO memory_curation_model_runs(
                            run_id, session_id, profile, provider, model_id,
                            thinking_level, frozen_input_sha256, state,
                            created_at_ms, updated_at_ms
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'prepared', ?, ?)
                        """,
                        (
                            normalized_run_id,
                            str(session["id"]),
                            MEMORY_CURATION_PROFILE,
                            self.provider,
                            self.model_id,
                            self.thinking_level,
                            frozen_hash,
                            timestamp,
                            timestamp,
                        ),
                    )
                    row = conn.execute(
                        "SELECT * FROM memory_curation_model_runs WHERE run_id = ?",
                        (normalized_run_id,),
                    ).fetchone()
            assert row is not None
            self._validate_run_row(row, frozen_hash=frozen_hash)
            self._active_run_id = normalized_run_id
            self._active_session_id = str(row["session_id"] or "")
            if not self._active_session_id:
                raise MemoryModelUnavailable(
                    "memory curation run has no resumable internal Session"
                )
            return _run_payload(row)

    def complete(
        self,
        *,
        messages: list[dict[str, str]],
        max_tokens: int | None = None,
        phase: str = "model-call",
        isolated: bool = False,
    ) -> dict[str, object]:
        normalized_messages = _messages(messages)
        frozen_json = json.dumps(
            normalized_messages,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        input_sha256 = hashlib.sha256(frozen_json.encode("utf-8")).hexdigest()
        normalized_phase = _identifier(phase, field="phase", maximum=80)
        with self._lock:
            if not self._active_run_id:
                self.begin_run(f"memory-model-run:{uuid.uuid4()}")
            run_id = self._active_run_id
            session_id = self._active_session_id
            request = self._prepare_request(
                run_id=run_id,
                phase=normalized_phase,
                input_sha256=input_sha256,
                messages_json=frozen_json,
                isolated=bool(isolated),
            )
            if str(request["state"]) == "completed":
                return self._response_from_request(request)
            session_id = str(request["session_id"] or session_id)
            if not session_id:
                raise MemoryModelUnavailable(
                    "memory curation request has no resumable internal Session"
                )

            prompt = _session_prompt(
                normalized_messages,
                request_id=str(request["request_id"]),
                input_sha256=input_sha256,
                max_tokens=max_tokens,
            )
            if len(prompt) > MAXIMUM_MEMORY_PROMPT_CHARS:
                raise MemoryModelUnavailable(
                    "memory curation packet exceeds the managed Session input limit"
                )

            waiter = _MemoryTurnWaiter(session_id)
            remove_observer = self.events.add_observer(waiter.observe)
            model_receipt: dict[str, object] = {}
            thinking_receipt: dict[str, object] = {}
            started = time.monotonic()
            try:
                model_receipt = dict(
                    self.runtime.set_model(
                        session_id,
                        provider=self.provider,
                        model_id=self.model_id,
                    )
                )
                thinking_receipt = dict(
                    self.runtime.set_thinking_level(
                        session_id,
                        level=self.thinking_level,
                    )
                )
                _verify_runtime_receipts(
                    model_receipt,
                    thinking_receipt,
                    provider=self.provider,
                    model_id=self.model_id,
                    thinking_level=self.thinking_level,
                )
                self._mark_request_running(
                    request_id=str(request["request_id"]),
                )
                accepted = self.runtime.prompt(
                    session_id,
                    prompt,
                    images=[],
                    client_message_id=str(request["request_id"]),
                )
                turn_id = str(accepted.get("turnId") or "").strip()
                if not turn_id:
                    raise MemoryModelUnavailable(
                        "managed Pi did not return a Memory Session turn id"
                    )
                self._bind_turn(
                    request_id=str(request["request_id"]),
                    turn_id=turn_id,
                )
                terminal = waiter.wait(
                    turn_id,
                    timeout_seconds=self.timeout_seconds,
                )
                if terminal["state"] == "failed":
                    raise MemoryModelUnavailable(
                        str(terminal.get("error") or "Memory Session turn failed")
                    )
                output_text = str(terminal.get("text") or "").strip()
                if not output_text:
                    raise MemoryModelUnavailable(
                        "Memory Session completed without assistant JSON"
                    )
                elapsed_ms = max(0, int((time.monotonic() - started) * 1_000))
                receipt = {
                    "schemaVersion": "rag-ime.memory-curation-model-receipt.v1",
                    "profile": MEMORY_CURATION_PROFILE,
                    "transport": "gateway_internal_session",
                    "runId": run_id,
                    "requestId": str(request["request_id"]),
                    "sessionId": session_id,
                    "turnId": turn_id,
                    "provider": self.provider,
                    "modelId": self.model_id,
                    "thinkingLevel": self.thinking_level,
                    "contextWindow": int(self.selected_model.get("contextWindow") or 0),
                    "maxTokens": int(self.selected_model.get("maxTokens") or 0),
                    "inputSha256": input_sha256,
                    "inputChars": len(prompt),
                    "elapsedMs": elapsed_ms,
                    "usage": dict(terminal.get("usage") or {}),
                    "modelSelection": model_receipt,
                    "thinkingSelection": thinking_receipt,
                }
                completed = self._complete_request(
                    request_id=str(request["request_id"]),
                    output_text=output_text,
                    receipt=receipt,
                )
                return self._response_from_request(completed)
            except TimeoutError as exc:
                cancellation: dict[str, object] = {}
                try:
                    cancellation = dict(self.runtime.abort(session_id))
                except Exception as cancel_exc:
                    cancellation = {"error": _public_error(cancel_exc)}
                self._mark_request_resumable(
                    request_id=str(request["request_id"]),
                    error="memory_curation_timeout",
                    receipt={"cancellation": cancellation},
                )
                raise MemoryModelTimeout(
                    "Memory Session timed out; the frozen request remains resumable"
                ) from exc
            except MemoryModelUnavailable:
                self._mark_request_resumable(
                    request_id=str(request["request_id"]),
                    error="memory_model_request_failed",
                )
                raise
            except Exception as exc:
                self._mark_request_resumable(
                    request_id=str(request["request_id"]),
                    error=_public_error(exc),
                )
                raise MemoryModelUnavailable(
                    f"selected memory model request failed ({self.reference}): "
                    f"{_public_error(exc)}"
                ) from exc
            finally:
                remove_observer()

    def finish_run(self, *, state: str = "completed") -> dict[str, object]:
        normalized_state = str(state or "").strip().lower()
        if normalized_state not in {"completed", "failed", "cancelled"}:
            raise ValueError("terminal memory model run state is invalid")
        with self._lock:
            run_id = self._active_run_id
            if not run_id:
                return {}
            with self._connect() as conn:
                request_sessions = [
                    str(row["session_id"] or "")
                    for row in conn.execute(
                        """
                        SELECT DISTINCT session_id
                        FROM memory_curation_model_requests
                        WHERE run_id = ? AND session_id != ''
                        ORDER BY session_id
                        """,
                        (run_id,),
                    ).fetchall()
                ]
            session_ids = list(
                dict.fromkeys(
                    session_id
                    for session_id in [self._active_session_id, *request_sessions]
                    if session_id
                )
            )
            timestamp = _now_ms()
            try:
                for session_id in session_ids:
                    self.runtime.close_session(session_id)
                    self.sessions.retire_system_internal(
                        session_id,
                        tool_profile_version=MEMORY_CURATION_TOOL_PROFILE,
                        updated_at_ms=timestamp,
                    )
            except Exception as exc:
                self._set_run_error(
                    run_id,
                    state="resumable",
                    error=f"memory_session_retirement_failed: {_public_error(exc)}",
                )
                raise MemoryModelUnavailable(
                    "Memory run could not retire its internal Session; "
                    "the database run remains resumable"
                ) from exc
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE memory_curation_model_runs
                    SET state = ?, last_error = '', updated_at_ms = ?,
                        completed_at_ms = ?
                    WHERE run_id = ?
                    """,
                    (normalized_state, timestamp, timestamp, run_id),
                )
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT * FROM memory_curation_model_runs WHERE run_id = ?",
                    (run_id,),
                ).fetchone()
            self._active_run_id = ""
            self._active_session_id = ""
            return _run_payload(row) if row is not None else {}

    def fail_run(self, error: BaseException) -> dict[str, object]:
        with self._lock:
            if not self._active_run_id:
                return {}
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT state FROM memory_curation_model_runs WHERE run_id = ?",
                    (self._active_run_id,),
                ).fetchone()
            if row is not None and str(row["state"]) == "resumable":
                return self.run_status(self._active_run_id)
            self._set_run_error(
                self._active_run_id,
                state="failed",
                error=_public_error(error),
            )
            return self.finish_run(state="failed")

    def cancel_run(self) -> dict[str, object]:
        with self._lock:
            run_id = self._active_run_id
            session_id = self._active_session_id
            if not run_id:
                return {}
            if session_id:
                try:
                    self.runtime.abort(session_id)
                except Exception:
                    pass
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE memory_curation_model_requests
                    SET state = 'cancelled', updated_at_ms = ?, completed_at_ms = ?
                    WHERE run_id = ? AND state IN ('prepared', 'running', 'resumable')
                    """,
                    (_now_ms(), _now_ms(), run_id),
                )
            return self.finish_run(state="cancelled")

    def run_status(self, run_id: object) -> dict[str, object]:
        normalized = _identifier(run_id, field="runId", maximum=240)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM memory_curation_model_runs WHERE run_id = ?",
                (normalized,),
            ).fetchone()
            if row is None:
                return {}
            requests = conn.execute(
                """
                SELECT request_id, phase, ordinal, input_sha256, input_chars,
                       session_id, state, turn_id, attempt_count, receipt_json, last_error,
                       created_at_ms, updated_at_ms, completed_at_ms
                FROM memory_curation_model_requests
                WHERE run_id = ?
                ORDER BY ordinal
                """,
                (normalized,),
            ).fetchall()
        payload = _run_payload(row)
        payload["requests"] = [_request_public_payload(item) for item in requests]
        return payload

    def close(self) -> None:
        """Release this adapter without ever stopping the shared Gateway Host."""

        with self._lock:
            self._active_run_id = ""
            self._active_session_id = ""

    def _resolve_live_model(self) -> dict[str, object]:
        try:
            models = self.runtime.available_models()
        except Exception as exc:
            raise MemoryModelUnavailable(
                f"selected memory runtime is unavailable for {self.reference}: "
                f"{_public_error(exc)}"
            ) from exc
        selected = next(
            (
                dict(model)
                for model in models
                if isinstance(model, Mapping)
                and str(model.get("provider") or "") == self.provider
                and str(model.get("id") or "") == self.model_id
            ),
            None,
        )
        if selected is None:
            raise MemoryModelUnavailable(
                f"selected memory model is unavailable: {self.reference}"
            )
        levels = selected.get("thinkingLevels")
        if not isinstance(levels, list) or self.thinking_level not in {
            str(level) for level in levels
        }:
            raise MemoryModelUnavailable(
                f"selected memory model does not support thinking level "
                f"{self.thinking_level}: {self.reference}"
            )
        context_window = int(selected.get("contextWindow") or 0)
        if context_window < MINIMUM_MEMORY_CONTEXT_TOKENS:
            raise MemoryModelUnavailable(
                f"selected memory model context window is below "
                f"{MINIMUM_MEMORY_CONTEXT_TOKENS}: {context_window}"
            )
        return selected

    def _prepare_request(
        self,
        *,
        run_id: str,
        phase: str,
        input_sha256: str,
        messages_json: str,
        isolated: bool,
    ) -> sqlite3.Row:
        timestamp = _now_ms()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM memory_curation_model_requests
                WHERE run_id = ? AND phase = ? AND input_sha256 = ?
                """,
                (run_id, phase, input_sha256),
            ).fetchone()
            if row is not None:
                return row
        request_session_id = self._active_session_id
        if isolated:
            isolated_session = self._create_internal_session(
                title=(
                    "Memory verification · "
                    f"{_short_run_label(run_id)} · {phase[:32]}"
                ),
            )
            request_session_id = str(isolated_session["id"])
        with self._connect() as conn:
            ordinal = int(
                conn.execute(
                    """
                    SELECT COALESCE(MAX(ordinal), 0) + 1
                    FROM memory_curation_model_requests
                    WHERE run_id = ?
                    """,
                    (run_id,),
                ).fetchone()[0]
            )
            request_id = "memory-request:" + hashlib.sha256(
                f"{run_id}\0{phase}\0{input_sha256}".encode("utf-8")
            ).hexdigest()[:32]
            conn.execute(
                """
                INSERT INTO memory_curation_model_requests(
                    request_id, run_id, phase, ordinal, input_sha256,
                    messages_json, input_chars, session_id, state, created_at_ms,
                    updated_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'prepared', ?, ?)
                """,
                (
                    request_id,
                    run_id,
                    phase,
                    ordinal,
                    input_sha256,
                    messages_json,
                    len(messages_json),
                    request_session_id,
                    timestamp,
                    timestamp,
                ),
            )
            conn.execute(
                """
                UPDATE memory_curation_model_runs
                SET frozen_input_sha256 = CASE
                        WHEN frozen_input_sha256 = '' THEN ?
                        ELSE frozen_input_sha256
                    END,
                    updated_at_ms = ?
                WHERE run_id = ?
                """,
                (input_sha256, timestamp, run_id),
            )
            return conn.execute(
                "SELECT * FROM memory_curation_model_requests WHERE request_id = ?",
                (request_id,),
            ).fetchone()

    def _create_internal_session(self, *, title: str) -> dict[str, object]:
        session = self.sessions.create(
            title=title,
            mode="assistant",
            role_id="memory-curator",
            role_version="1",
            model_profile=self.reference,
            thinking_level=self.thinking_level,
            tool_profile_version=MEMORY_CURATION_TOOL_PROFILE,
            project_context_enabled=False,
            pi_skills_enabled=False,
            codex_skills_enabled=False,
            workspace_roots=[],
            session_kind="subagent_runtime",
        )
        return self.sessions.set_runtime_policy(
            str(session["id"]),
            mode="assistant",
            tool_profile_version=MEMORY_CURATION_TOOL_PROFILE,
            allowed_tools=[],
            project_context_enabled=False,
            pi_skills_enabled=False,
            codex_skills_enabled=False,
            workspace_roots=[],
        )

    def _mark_request_running(self, *, request_id: str) -> None:
        timestamp = _now_ms()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE memory_curation_model_requests
                SET state = 'running', attempt_count = attempt_count + 1,
                    last_error = '', updated_at_ms = ?
                WHERE request_id = ?
                """,
                (timestamp, request_id),
            )
            conn.execute(
                """
                UPDATE memory_curation_model_runs
                SET state = 'running', last_error = '', updated_at_ms = ?
                WHERE run_id = ?
                """,
                (timestamp, self._active_run_id),
            )

    def _bind_turn(self, *, request_id: str, turn_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE memory_curation_model_requests
                SET turn_id = ?, updated_at_ms = ?
                WHERE request_id = ?
                """,
                (turn_id, _now_ms(), request_id),
            )

    def _complete_request(
        self,
        *,
        request_id: str,
        output_text: str,
        receipt: Mapping[str, object],
    ) -> sqlite3.Row:
        timestamp = _now_ms()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE memory_curation_model_requests
                SET state = 'completed', output_text = ?, receipt_json = ?,
                    last_error = '', updated_at_ms = ?, completed_at_ms = ?
                WHERE request_id = ?
                """,
                (
                    output_text,
                    json.dumps(dict(receipt), ensure_ascii=False, separators=(",", ":")),
                    timestamp,
                    timestamp,
                    request_id,
                ),
            )
            return conn.execute(
                "SELECT * FROM memory_curation_model_requests WHERE request_id = ?",
                (request_id,),
            ).fetchone()

    def _mark_request_resumable(
        self,
        *,
        request_id: str,
        error: str,
        receipt: Mapping[str, object] | None = None,
    ) -> None:
        timestamp = _now_ms()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE memory_curation_model_requests
                SET state = 'resumable', receipt_json = ?, last_error = ?,
                    updated_at_ms = ?
                WHERE request_id = ? AND state != 'completed'
                """,
                (
                    json.dumps(dict(receipt or {}), ensure_ascii=False, separators=(",", ":")),
                    str(error)[:800],
                    timestamp,
                    request_id,
                ),
            )
        self._set_run_error(self._active_run_id, state="resumable", error=error)

    def _set_run_error(self, run_id: str, *, state: str, error: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE memory_curation_model_runs
                SET state = ?, last_error = ?, updated_at_ms = ?
                WHERE run_id = ?
                """,
                (state, str(error)[:800], _now_ms(), run_id),
            )

    def _response_from_request(self, row: sqlite3.Row) -> dict[str, object]:
        receipt = _json_object(row["receipt_json"])
        text = str(row["output_text"] or "").strip()
        if not text:
            raise MemoryModelUnavailable(
                "completed Memory request has no database-owned output"
            )
        return {
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": text},
                    "finish_reason": "stop",
                }
            ],
            "provider": self.provider,
            "model": self.model_id,
            "thinkingLevel": self.thinking_level,
            "profile": MEMORY_CURATION_PROFILE,
            "requestId": str(row["request_id"]),
            "turnId": str(row["turn_id"] or ""),
            "elapsedMs": max(0, int(receipt.get("elapsedMs") or 0)),
            "usage": dict(receipt.get("usage") or {}),
            "receipt": receipt,
        }

    def _validate_run_row(
        self,
        row: sqlite3.Row,
        *,
        frozen_hash: str,
    ) -> None:
        if (
            str(row["profile"]) != MEMORY_CURATION_PROFILE
            or str(row["provider"]) != self.provider
            or str(row["model_id"]) != self.model_id
            or str(row["thinking_level"]) != self.thinking_level
        ):
            raise MemoryModelUnavailable(
                "existing Memory run uses a different frozen model profile"
            )
        existing_hash = str(row["frozen_input_sha256"] or "")
        if frozen_hash and existing_hash and frozen_hash != existing_hash:
            raise MemoryModelUnavailable(
                "existing Memory run input hash does not match the frozen batch"
            )
        if str(row["state"]) in {"failed", "cancelled"}:
            raise MemoryModelUnavailable(
                f"Memory run is terminal: {str(row['state'])}"
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


class _MemoryTurnWaiter:
    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self._condition = threading.Condition()
        self._turns: dict[str, dict[str, object]] = {}

    def observe(self, event: object) -> None:
        if str(getattr(event, "session_id", "")) != self.session_id:
            return
        turn_id = str(getattr(event, "turn_id", "") or "")
        if not turn_id:
            return
        event_type = str(getattr(event, "event_type", "") or "")
        payload = getattr(event, "payload", {})
        if not isinstance(payload, Mapping):
            payload = {}
        with self._condition:
            turn = self._turns.setdefault(
                turn_id,
                {"state": "running", "text": "", "usage": {}, "error": ""},
            )
            if event_type == "message_completed":
                message = payload.get("message")
                if isinstance(message, Mapping) and str(message.get("role") or "") == "assistant":
                    turn["text"] = _assistant_message_text(message)
                usage = payload.get("usage")
                if isinstance(usage, Mapping):
                    turn["usage"] = dict(usage)
            elif event_type == "turn_failed":
                turn["state"] = "failed"
                turn["error"] = str(payload.get("error") or "Memory Session turn failed")
            elif event_type == "turn_completed":
                turn["state"] = "completed"
            self._condition.notify_all()

    def wait(self, turn_id: str, *, timeout_seconds: float) -> dict[str, object]:
        deadline = time.monotonic() + timeout_seconds
        with self._condition:
            while True:
                turn = self._turns.get(turn_id)
                if turn is not None and str(turn.get("state")) in {"completed", "failed"}:
                    return dict(turn)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Memory Session turn timed out")
                self._condition.wait(min(remaining, 0.25))


def split_memory_model_reference(value: object) -> tuple[str, str]:
    reference = " ".join(str(value or "").strip().split())
    if reference == "gpt/gpt-5.6-luna":
        reference = REQUIRED_MEMORY_MODEL_REFERENCE
    provider, separator, model_id = reference.partition("/")
    if not separator:
        raise ValueError("memory model must be a provider/model reference")
    return (
        _model_part(provider, field="provider", maximum=80),
        _model_part(model_id, field="modelId", maximum=160),
    )


def build_governed_memory_model_executor(
    runtime: MemorySessionRuntime,
    model_reference: object,
    thinking_level: object,
    *,
    timeout_seconds: float = DEFAULT_MEMORY_CURATION_TIMEOUT_SECONDS,
    db_path: str | Path | None = None,
    sessions: AgentSessionStore | None = None,
    events: AgentEventHub | None = None,
) -> GovernedMemoryModelExecutor:
    provider, model_id = split_memory_model_reference(model_reference)
    return GovernedMemoryModelExecutor(
        runtime,
        provider,
        model_id,
        str(thinking_level or "").strip().lower(),
        timeout_seconds=timeout_seconds,
        sessions=sessions,
        events=events,
        db_path=db_path,
    )


def build_managed_pi_memory_model_executor(
    db_path: str | Path,
    model_reference: object,
    thinking_level: object,
    *,
    timeout_seconds: float = DEFAULT_MEMORY_CURATION_TIMEOUT_SECONDS,
) -> GovernedMemoryModelExecutor:
    del db_path, model_reference, thinking_level, timeout_seconds
    raise MemoryModelUnavailable(
        "standalone Memory model execution is disabled; trigger the running Agent Gateway"
    )


def memory_curation_model_status(
    conn: sqlite3.Connection,
    *,
    limit: int = 8,
) -> dict[str, object]:
    """Expose persisted run/phase receipts without prompt or response contents."""

    bounded_limit = max(1, min(30, int(limit)))
    runs = conn.execute(
        """
        SELECT *
        FROM memory_curation_model_runs
        ORDER BY updated_at_ms DESC, run_id DESC
        LIMIT ?
        """,
        (bounded_limit,),
    ).fetchall()
    payloads: list[dict[str, object]] = []
    for run in runs:
        requests = conn.execute(
            """
            SELECT request_id, phase, ordinal, input_sha256, input_chars,
                   session_id, state, turn_id, attempt_count, receipt_json,
                   last_error, created_at_ms, updated_at_ms, completed_at_ms
            FROM memory_curation_model_requests
            WHERE run_id = ?
            ORDER BY ordinal
            """,
            (str(run["run_id"]),),
        ).fetchall()
        payload = _run_payload(run)
        payload["requests"] = [_request_public_payload(row) for row in requests]
        payloads.append(payload)
    state_counts = {
        str(row["state"]): int(row["count"])
        for row in conn.execute(
            """
            SELECT state, COUNT(*) AS count
            FROM memory_curation_model_runs
            GROUP BY state
            ORDER BY state
            """
        ).fetchall()
    }
    return {
        "schemaVersion": "rag-ime.memory-curation-model-status.v1",
        "ok": True,
        "profile": MEMORY_CURATION_PROFILE,
        "requiredModel": REQUIRED_MEMORY_MODEL_REFERENCE,
        "requiredThinkingLevel": REQUIRED_MEMORY_THINKING_LEVEL,
        "minimumContextTokens": MINIMUM_MEMORY_CONTEXT_TOKENS,
        "stateCounts": state_counts,
        "runs": payloads,
    }


def _messages(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list) or not value:
        raise ValueError("memory model messages are required")
    normalized: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise ValueError("memory model message must be an object")
        role = str(item.get("role") or "").strip().lower()
        content = str(item.get("content") or "")
        if role not in {"system", "user", "assistant"} or not content:
            raise ValueError("memory model message role/content is invalid")
        normalized.append({"role": role, "content": content})
    return normalized


def _session_prompt(
    messages: list[dict[str, str]],
    *,
    request_id: str,
    input_sha256: str,
    max_tokens: int | None,
) -> str:
    parts = [
        "MEMORY_CURATION\n",
        f"request_id={request_id}\n",
        f"frozen_input_sha256={input_sha256}\n",
        f"requested_output_tokens={max(0, int(max_tokens or 0))}\n",
        "Each section below is length-delimited application data. ",
        "Return exactly one JSON object.\n",
    ]
    for index, message in enumerate(messages, start=1):
        content = message["content"]
        parts.extend(
            (
                f"\nSECTION {index} role={message['role']} ",
                f"utf8_bytes={len(content.encode('utf-8'))}\n",
                content,
                "\nEND_SECTION\n",
            )
        )
    return "".join(parts)


def _verify_runtime_receipts(
    model_receipt: Mapping[str, object],
    thinking_receipt: Mapping[str, object],
    *,
    provider: str,
    model_id: str,
    thinking_level: str,
) -> None:
    selected = model_receipt.get("selected")
    if not isinstance(selected, Mapping):
        raise MemoryModelUnavailable("Pi model-selection receipt is missing")
    if (
        str(selected.get("provider") or "") != provider
        or str(selected.get("id") or selected.get("modelId") or "") != model_id
    ):
        raise MemoryModelUnavailable("Pi selected a different Memory model")
    if str(thinking_receipt.get("thinkingLevel") or "") != thinking_level:
        raise MemoryModelUnavailable("Pi selected a different Memory thinking level")


def _assistant_message_text(message: Mapping[str, object]) -> str:
    blocks = message.get("blocks")
    if not isinstance(blocks, list):
        return str(message.get("content") or message.get("text") or "").strip()
    chunks: list[str] = []
    for block in blocks:
        if not isinstance(block, Mapping):
            continue
        data = block.get("data")
        if isinstance(data, Mapping):
            text = str(data.get("text") or "")
        else:
            text = str(block.get("text") or "")
        if text:
            chunks.append(text)
    return "\n\n".join(chunks).strip()


def _run_payload(row: sqlite3.Row) -> dict[str, object]:
    return {
        "schemaVersion": "rag-ime.memory-curation-model-run.v1",
        "runId": str(row["run_id"]),
        "sessionId": str(row["session_id"] or ""),
        "profile": str(row["profile"]),
        "provider": str(row["provider"]),
        "modelId": str(row["model_id"]),
        "thinkingLevel": str(row["thinking_level"]),
        "frozenInputSha256": str(row["frozen_input_sha256"]),
        "state": str(row["state"]),
        "lastError": str(row["last_error"]),
        "createdAtMs": int(row["created_at_ms"]),
        "updatedAtMs": int(row["updated_at_ms"]),
        "completedAtMs": int(row["completed_at_ms"] or 0),
    }


def _request_public_payload(row: sqlite3.Row) -> dict[str, object]:
    receipt = _json_object(row["receipt_json"])
    return {
        "requestId": str(row["request_id"]),
        "sessionId": str(row["session_id"] or ""),
        "phase": str(row["phase"]),
        "ordinal": int(row["ordinal"]),
        "inputSha256": str(row["input_sha256"]),
        "inputChars": int(row["input_chars"]),
        "state": str(row["state"]),
        "turnId": str(row["turn_id"]),
        "attemptCount": int(row["attempt_count"]),
        "receipt": receipt,
        "lastError": str(row["last_error"]),
        "createdAtMs": int(row["created_at_ms"]),
        "updatedAtMs": int(row["updated_at_ms"]),
        "completedAtMs": int(row["completed_at_ms"] or 0),
    }


def _json_object(value: object) -> dict[str, object]:
    try:
        decoded = json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return dict(decoded) if isinstance(decoded, Mapping) else {}


def _model_part(value: object, *, field: str, maximum: int) -> str:
    normalized = str(value or "").strip()
    if (
        not normalized
        or len(normalized) > maximum
        or any(character.isspace() for character in normalized)
    ):
        raise ValueError(f"memory {field} is invalid")
    return normalized


def _identifier(value: object, *, field: str, maximum: int) -> str:
    normalized = str(value or "").strip()
    if (
        not normalized
        or len(normalized) > maximum
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]*", normalized)
    ):
        raise ValueError(f"memory {field} is invalid")
    return normalized


def _sha256_value(value: object, *, allow_empty: bool) -> str:
    normalized = str(value or "").strip().lower()
    if normalized.startswith("sha256:"):
        normalized = normalized[7:]
    if not normalized and allow_empty:
        return ""
    if not re.fullmatch(r"[0-9a-f]{64}", normalized):
        raise ValueError("memory frozen input sha256 is invalid")
    return normalized


def _short_run_label(run_id: str) -> str:
    return hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:12]


def _now_ms() -> int:
    return int(time.time() * 1_000)


def _public_error(exc: BaseException) -> str:
    return " ".join(str(exc).split())[:800] or exc.__class__.__name__
