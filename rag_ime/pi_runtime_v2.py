from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .agent_events import AgentEventHub
from .agent_protocol import AgentEventEnvelope
from .agent_runtime_failure import classify_runtime_failure
from .agent_tool_block_bridge import AgentToolBlockBuffer
from .agent_tool_ids import MEMORY_CURATION_TOOL_PROFILE
from .agent_runtime_driver import AgentRuntimeError, CompactionObserver
from .agent_sessions import AgentSessionStore
from .pi_runtime import (
    PiRuntimeConfig,
    PiRuntimeError,
)
from .pi_runtime_public import (
    pi_message_payload,
    APPROVAL_TITLE_PREFIX,
    GROUPED_QUESTIONS_SCHEMA_VERSION,
    GROUPED_QUESTIONS_TITLE_PREFIX,
    REVIEW_TITLE_PREFIX,
    canonical_grouped_answers,
    grouped_questions_from_wire,
    inspectable_tool_result,
    last_assistant_error,
    last_assistant_preview,
    pi_message_id,
    pi_message_completes_public_turn,
    pi_message_is_public,
    provider_retry_status,
    public_code_tool_activity,
    public_fork_candidate_text,
    public_pi_model,
    public_reasoning_summaries,
    public_usage,
    public_usage_evidence,
    redact_mapping,
    runtime_tool_result_is_error,
    ui_confirmation_value,
    visible_message_text,
)
from .pi_runtime_values import (
    PiRuntimeCommandRejected,
    PiRuntimeTurnConflict,
    effective_thinking_level,
    as_integer,
    path_is_within,
    as_mapping,
    message_delivery,
    model_reference_part,
    public_message_queue,
    redact_runtime_text,
)
from .room_runtime_host_kill_gate import RuntimeHostKillGate, process_birth_token


__all__ = ["PiRuntimeHostManager"]


_PROTOCOL_VERSION = "2"
_MODEL_CATALOG_CACHE_SECONDS = 1_800.0
_PROMPT_TIMEOUT_SECONDS = 60.0 * 60.0


def _failed_settlement_receipt(
    raw: Mapping[str, object],
    *,
    allow_aborted: bool,
) -> tuple[bool, str] | None:
    """Return terminality and error for one failed V2 settlement receipt."""

    receipt = as_mapping(raw.get("receipt"))
    if receipt.get("schemaVersion") != "pi.agent-settled.v2":
        return None
    disposition = str(receipt.get("disposition") or "")
    allowed = {"failed", "aborted"} if allow_aborted else {"failed"}
    if disposition not in allowed:
        return None

    operations = as_mapping(receipt.get("operations"))
    pending_values = []
    if "pendingOperations" in receipt:
        pending_values.append(receipt.get("pendingOperations"))
    if "pending" in operations:
        pending_values.append(operations.get("pending"))
    terminal = bool(pending_values) and all(
        isinstance(value, int)
        and not isinstance(value, bool)
        and value == 0
        for value in pending_values
    )
    final_message = as_mapping(receipt.get("finalMessage"))
    error = redact_runtime_text(
        str(
            raw.get("error")
            or final_message.get("errorMessage")
            or receipt.get("stopReason")
            or "Pi settlement failed"
        )
    )
    return terminal, error


def _runtime_primitive_capabilities(value: object) -> dict[str, object]:
    source = as_mapping(value)
    operations = as_mapping(source.get("sessionCancelOperations"))
    continuation_envelope = source.get("continuationEnvelope")
    return {
        "continuationEnvelope": (
            continuation_envelope
            if continuation_envelope in {"1", "2"}
            else ""
        ),
        "cancelScope": (
            str(source.get("cancelScope") or "")
            if source.get("cancelScope") == "1"
            else ""
        ),
        "sessionContinuationQueue": bool(source.get("sessionContinuationQueue")),
        "sessionCancelOperationRegistry": bool(
            source.get("sessionCancelOperationRegistry")
        ),
        "sessionCancelOperations": {
            key: bool(operations.get(key))
            for key in (
                "provider",
                "tool",
                "retrySleep",
                "manualCompaction",
                "autoCompaction",
                "branchSummary",
                "bashProcess",
                "continuationTimer",
            )
        },
    }


class PiRuntimeHostClient:
    """One long-lived process connection shared by the bounded Session host."""

    def __init__(
        self,
        config: PiRuntimeConfig,
        *,
        on_event: Callable[[dict[str, object]], None],
        on_exit: Callable[[int | None, str], None],
        kill_gate: RuntimeHostKillGate,
        owner_instance_id: str,
    ) -> None:
        self.config = config
        self.on_event = on_event
        self.on_exit = on_exit
        self.kill_gate = kill_gate
        self.owner_instance_id = owner_instance_id
        self.host_identity = f"pi-host:{uuid.uuid4()}"
        self.job_identity = f"pi-job:{uuid.uuid4()}"
        self._lock = threading.RLock()
        self._write_lock = threading.Lock()
        self._pending: dict[str, queue.Queue[object]] = {}
        # Host responses and host events share stdout, but they must not share
        # one execution lane. Event projection can touch SQLite, Room state, or
        # even issue a nested control RPC; running it in the stdout reader can
        # therefore delay or deadlock an otherwise immediate command ACK.
        self._event_queue: queue.Queue[object] = queue.Queue()
        self._stderr: deque[str] = deque(maxlen=32)
        self._process: subprocess.Popen[bytes] | None = None
        self._stdout_thread: threading.Thread | None = None
        self._event_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._stopping = False

    @property
    def running(self) -> bool:
        process = self._process
        return process is not None and process.poll() is None

    def start(self) -> dict[str, object]:
        with self._lock:
            if self.running:
                raise PiRuntimeError("Pi Runtime Host is already running")
            self.config.agent_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.config.session_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.config.logs_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.config.prepare_agent_config()
            try:
                environment = self.config.child_environment()
                environment["RAG_IME_RUNTIME_HOST_IDENTITY"] = self.host_identity
                environment["RAG_IME_RUNTIME_JOB_IDENTITY"] = self.job_identity
                self._process = subprocess.Popen(
                    self.config.launch_host_command(),
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=self.config.agent_dir,
                    env=environment,
                    bufsize=0,
                    start_new_session=os.name == "posix",
                )
            except OSError as exc:
                raise PiRuntimeError(f"failed to start managed Pi Runtime Host: {exc}") from exc
            process_group_id = (
                os.getpgid(self._process.pid) if os.name == "posix" else self._process.pid
            )
            try:
                self.kill_gate.register_process(
                    host_identity=self.host_identity,
                    owner_instance_id=self.owner_instance_id,
                    pid=self._process.pid,
                    process_group_id=process_group_id,
                    job_identity=self.job_identity,
                    process_birth_token=process_birth_token(self._process.pid),
                    executable_ref=str(self.config.executable or ""),
                    now_ms=int(time.time() * 1000),
                )
            except Exception:
                process = self._process
                process.kill()
                process.wait(timeout=2)
                for stream in (
                    process.stdin,
                    process.stdout,
                    process.stderr,
                ):
                    if stream is not None:
                        stream.close()
                self._process = None
                raise
            self._stopping = False
            # A client is normally one-shot, but resetting the lane here keeps
            # an explicit stop/start from inheriting the previous sentinel.
            self._event_queue = queue.Queue()
            self._stdout_thread = threading.Thread(
                target=self._read_stdout,
                name="rag-ime-pi-host-stdout",
                daemon=True,
            )
            self._event_thread = threading.Thread(
                target=self._read_events,
                name="rag-ime-pi-host-events",
                daemon=True,
            )
            self._stderr_thread = threading.Thread(
                target=self._read_stderr,
                name="rag-ime-pi-host-stderr",
                daemon=True,
            )
            self._event_thread.start()
            self._stdout_thread.start()
            self._stderr_thread.start()
        return self.send("hello")

    def send(
        self,
        method: str,
        params: Mapping[str, object] | None = None,
        *,
        timeout: float | None = None,
        before_write: Callable[[], None] | None = None,
    ) -> dict[str, object]:
        request_id = str(uuid.uuid4())
        request = {
            "protocolVersion": _PROTOCOL_VERSION,
            "id": request_id,
            "method": method,
            "params": dict(params or {}),
        }
        response_queue: queue.Queue[object] = queue.Queue(maxsize=1)
        with self._lock:
            process = self._process
            if process is None or process.poll() is not None or process.stdin is None:
                raise PiRuntimeError("Pi Runtime Host is not running")
            self._pending[request_id] = response_queue
        try:
            self._write_record(
                process,
                request,
                before_write=before_write,
            )
        except (BrokenPipeError, OSError) as exc:
            with self._lock:
                self._pending.pop(request_id, None)
            raise PiRuntimeError("Pi Runtime Host stdin closed") from exc
        except BaseException:
            with self._lock:
                self._pending.pop(request_id, None)
            raise
        try:
            response = response_queue.get(timeout=timeout or self.config.command_timeout_seconds)
        except queue.Empty as exc:
            with self._lock:
                self._pending.pop(request_id, None)
            raise PiRuntimeError(f"Pi Runtime Host command timed out: {method}") from exc
        if isinstance(response, BaseException):
            raise PiRuntimeError(str(response))
        assert isinstance(response, dict)
        if response.get("ok") is not True:
            error = as_mapping(response.get("error"))
            raise PiRuntimeCommandRejected(
                str(
                    error.get("message")
                    or f"Pi Runtime Host command failed: {method}"
                ),
                host_error_code=str(
                    error.get("code") or "RUNTIME_REJECTED"
                ),
            )
        return dict(as_mapping(response.get("result")))

    def _write_record(
        self,
        process: subprocess.Popen[bytes],
        request: Mapping[str, object],
        *,
        before_write: Callable[[], None] | None = None,
    ) -> None:
        encoded = (
            json.dumps(
                dict(request),
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
            + b"\n"
        )
        with self._write_lock:
            if process.stdin is None:
                raise BrokenPipeError("Pi Runtime Host stdin is unavailable")
            if before_write is not None:
                before_write()
            process.stdin.write(encoded)
            process.stdin.flush()

    def stop(self) -> None:
        with self._lock:
            self._stopping = True
            process = self._process
        if process is None:
            return
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        self._fail_pending(PiRuntimeError("Pi Runtime Host stopped"))
        current = threading.current_thread()
        for thread in (self._stdout_thread, self._event_thread, self._stderr_thread):
            if thread is not None and thread is not current:
                thread.join(timeout=2)
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None:
                stream.close()
        with self._lock:
            self._process = None
        self.kill_gate.mark_terminated(self.host_identity, now_ms=int(time.time() * 1000))

    def diagnostic_error(self) -> str:
        return redact_runtime_text(self._stderr[-1] if self._stderr else "")

    def _read_stdout(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        protocol_error = ""
        while True:
            raw = process.stdout.readline()
            if not raw:
                break
            try:
                value = json.loads(raw.rstrip(b"\r\n").decode("utf-8"))
                if not isinstance(value, dict):
                    raise ValueError("host record is not an object")
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                protocol_error = f"invalid Pi Runtime Host JSONL: {exc}"
                continue
            if value.get("id") and isinstance(value.get("ok"), bool):
                with self._lock:
                    waiter = self._pending.pop(str(value["id"]), None)
                if waiter is not None:
                    waiter.put_nowait(value)
                continue
            # Never run product event projection in the response reader. A slow
            # observer must not hold a Room dispatch lease open while the typed
            # dispatch ACK is already waiting on the next JSONL line.
            self._event_queue.put(value)
        # The stdout reader owns the event-lane sentinel. It is emitted only
        # after every preceding JSONL event has been queued, so stop/EOF cannot
        # cut in front of a terminal agent_settled projection.
        self._event_queue.put(None)
        exit_code = process.poll()
        if exit_code is None:
            try:
                exit_code = process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                exit_code = None
        error = protocol_error or self.diagnostic_error()
        self.on_exit(exit_code, error)
        self.kill_gate.mark_terminated(self.host_identity, now_ms=int(time.time() * 1000))
        # Wake RPC callers only after the manager and durable process registry
        # agree the Host is terminal; callers must not observe a stale ready state.
        self._fail_pending(PiRuntimeError(error or "Pi Runtime Host exited"))
        event_thread = self._event_thread
        if event_thread is not None and event_thread is not threading.current_thread():
            event_thread.join(timeout=2)
        stderr_thread = self._stderr_thread
        if stderr_thread is not None and stderr_thread is not threading.current_thread():
            stderr_thread.join(timeout=1)
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None:
                stream.close()
        with self._lock:
            if self._process is process:
                self._process = None

    def _read_events(self) -> None:
        while True:
            value = self._event_queue.get()
            if value is None:
                return
            assert isinstance(value, dict)
            try:
                self.on_event(value)
            except Exception:
                # Event projections are secondary to the Runtime protocol. A
                # failed projection cannot stop response routing or other
                # Sessions; the event stores keep their own observable errors.
                continue

    def _read_stderr(self) -> None:
        process = self._process
        if process is None or process.stderr is None:
            return
        while True:
            raw = process.stderr.readline()
            if not raw:
                return
            self._stderr.append(raw.decode("utf-8", errors="replace").strip())

    def _fail_pending(self, error: BaseException) -> None:
        with self._lock:
            pending = tuple(self._pending.values())
            self._pending.clear()
        for waiter in pending:
            try:
                waiter.put_nowait(error)
            except queue.Full:
                pass


@dataclass
class _HostedSessionState:
    turn_id: str = ""
    client_message_id: str = ""
    prompt_admission_in_flight: bool = False
    admission_client_message_id: str = ""
    abort_pending_admission: bool = False
    prompt_dispatch_signal: threading.Event = field(
        default_factory=threading.Event,
        repr=False,
    )
    stream_pi_message_id: str = ""
    tool_blocks: AgentToolBlockBuffer = field(default_factory=AgentToolBlockBuffer)
    last_agent_messages: list[object] = field(default_factory=list)
    final_error: str = ""
    had_tool_activity: bool = False
    pending_approvals: dict[str, str] = field(default_factory=dict)
    pending_reviews: dict[str, str] = field(default_factory=dict)
    pending_ui_requests: dict[str, dict[str, object]] = field(default_factory=dict)
    abort_timer: threading.Timer | None = field(default=None, repr=False)
    settle_timer: threading.Timer | None = field(default=None, repr=False)
    settle_extension_failed: bool = False
    abort_requested_turn_id: str = ""
    retired_turn_ids: set[str] = field(default_factory=set)


class PiRuntimeHostManager:
    """Product adapter for the v2 SDK host; Pi owns Sessions, Python owns product state."""

    def __init__(
        self,
        *,
        config: PiRuntimeConfig,
        sessions: AgentSessionStore,
        events: AgentEventHub,
        media_resolver: Callable[[str, str, str], str] | None = None,
        session_context_provider: Callable[[Mapping[str, object]], Mapping[str, object]] | None = None,
        tool_manifest_provider: Callable[[Mapping[str, object]], list[Mapping[str, object]]] | None = None,
        compaction_observer: CompactionObserver | None = None,
    ) -> None:
        self.config = config
        self.sessions = sessions
        self.events = events
        self._media_resolver = media_resolver
        self._session_context_provider = session_context_provider
        self._tool_manifest_provider = tool_manifest_provider
        self._compaction_observer = compaction_observer
        self._lifecycle_lock = threading.RLock()
        self._lock = threading.RLock()
        self._client: PiRuntimeHostClient | None = None
        self._states: dict[str, _HostedSessionState] = {}
        self._open_sessions: set[str] = set()
        self._active_completion_ids: set[str] = set()
        self._completion_sinks: dict[str, Callable[[str], None]] = {}
        self._status = "stopped" if config.enabled else "disabled"
        self._last_error = ""
        self._host_capabilities: dict[str, object] = {}
        self._idle_timer: threading.Timer | None = None
        self._intentional_stop = False
        self._owner_instance_id = f"runtime:{uuid.uuid4()}"
        self._kill_gate = RuntimeHostKillGate(self.sessions.db_path)
        self._kill_gate.initialize()
        self._orphan_kill_receipts = self._kill_gate.reconcile_orphans(
            owner_instance_id=self._owner_instance_id,
            now_ms=int(time.time() * 1000),
        )
        self._last_kill_receipt: dict[str, object] | None = None
        self._retired_host_turns: set[tuple[str, str]] = set()
        self._available_models_cache: tuple[dict[str, object], ...] = ()
        self._available_models_cached_at = 0.0
        self._available_models_cache_ready = False

    @property
    def runtime_kind(self) -> str:
        # Preserve the stable binding identity so v1 transcripts resume in v2.
        return "pi_rpc"

    @property
    def driver_id(self) -> str:
        return "managed-pi"

    @property
    def session_root(self) -> Path:
        return self.config.session_dir

    @property
    def default_model_profile(self) -> str:
        provider = str(self.config.provider or "").strip()
        model = str(self.config.model or "").strip()
        return f"{provider}/{model}" if provider and model else "pi/default"

    def runtime_status(self) -> dict[str, object]:
        installed = self.config.executable is not None and self.config.executable.expanduser().is_file()
        latest_kill_receipt = None
        if self._last_kill_receipt:
            latest_kill_receipt = self._kill_gate.receipt(
                str(self._last_kill_receipt["killReceiptId"])
            )
        with self._lock:
            busy = sorted(
                session_id
                for session_id, state in self._states.items()
                if state.turn_id or state.prompt_admission_in_flight
            )
            open_sessions = sorted(self._open_sessions)
            active_completions = sorted(self._active_completion_ids)
            status = "busy" if busy or active_completions else self._status
            last_error = self._last_error
            capabilities = dict(self._host_capabilities)
            host_negotiated = self._client is not None and self._client.running
        if self.config.enabled and not installed:
            status = "not_installed"
            last_error = last_error or redact_runtime_text(self.config.installation_error)
        elif self.config.enabled and installed and not self.config.model_configured:
            status = "needs_configuration"
            last_error = last_error or redact_runtime_text(self.config.model_configuration_error)
        return {
            "schemaVersion": "rag-ime.agent-runtime.v1",
            "enabled": self.config.enabled,
            "managed": True,
            "status": status,
            "driverId": self.driver_id,
            "runtimeKind": self.runtime_kind,
            "runtimeVersion": self.config.pi_version if installed else "",
            "piVersion": self.config.pi_version if installed else "",
            "protocolVersion": _PROTOCOL_VERSION,
            "idleTimeoutSeconds": self.config.idle_timeout_seconds,
            "activeSessionId": busy[0] if busy else (open_sessions[0] if len(open_sessions) == 1 else None),
            "activeSessionIds": busy,
            "activeCompletionIds": active_completions,
            "openSessionIds": open_sessions,
            "lastError": last_error,
            "capabilities": {
                "rpc": installed,
                "sessions": True,
                "conversationFork": (
                    bool(capabilities.get("conversationFork"))
                    if host_negotiated
                    else installed and str(self.config.protocol_version or "") == _PROTOCOL_VERSION
                ),
                "conversationRewrite": (
                    bool(capabilities.get("conversationRewrite"))
                    if host_negotiated
                    else False
                ),
                "multiSession": True,
                "maxSessions": int(capabilities.get("maxSessions") or self.config.max_sessions),
                "tools": True,
                "dynamicTools": True,
                "managedPlugins": bool(capabilities.get("managedPlugins", True)),
                "sessionControlState": bool(
                    capabilities.get("sessionControlState")
                ),
                "sessionSnapshot": True,
                "settledEvents": True,
                "statelessCompletion": (
                    bool(capabilities.get("statelessCompletion"))
                    if host_negotiated
                    else installed and str(self.config.protocol_version or "") == _PROTOCOL_VERSION
                ),
                "transientContext": bool(capabilities.get("transientContext")),
                "persistentDebugContext": bool(capabilities.get("persistentDebugContext")),
                "runtimePrimitives": _runtime_primitive_capabilities(
                    capabilities.get("runtimePrimitives")
                ),
                "imageAttachments": True,
                "coordinator": True,
                "modelConfigured": self.config.model_configured,
            },
            "runtimeHostKillGate": {
                "ownerInstanceId": self._owner_instance_id,
                "orphanReconcileReceipts": list(self._orphan_kill_receipts),
                "lastKillReceipt": latest_kill_receipt,
            },
        }

    def panic_kill(self, *, requested_by: str, reason: str) -> dict[str, object]:
        """Immediately kill the registered Host process tree after admin auth."""
        with self._lifecycle_lock:
            client = self._require_client()
            receipt = self._kill_gate.request_kill(
                client.host_identity,
                request_kind="admin_panic",
                requested_by=str(requested_by).strip(),
                reason=str(reason).strip() or "administrator panic",
                now_ms=int(time.time() * 1000),
            )
            with self._lock:
                self._last_kill_receipt = dict(receipt)
                if self._status != "faulted":
                    self._status = "stopping"
            return receipt

    def reconcile_runtime_hosts(self) -> list[dict[str, object]]:
        """Retry bounded orphan termination before a new Host is admitted."""
        receipts = self._kill_gate.reconcile_orphans(
            owner_instance_id=self._owner_instance_id,
            now_ms=int(time.time() * 1000),
            include_owner=True,
        )
        with self._lock:
            self._orphan_kill_receipts.extend(receipts)
        return receipts

    def _host(self) -> PiRuntimeHostClient:
        # Host admission is a lifecycle transition, not a cache lookup. Model
        # catalogs, Session restore, and role settings can all request the Host
        # concurrently when the UI opens. Without this lock, two callers can
        # both observe `_client is None`, start two child processes, and let the
        # second registration fault on the first one's durable kill-gate row.
        # The losing caller can then clear `_client`, leaving the successfully
        # started Host registered but unreachable. The lifecycle lock is an
        # RLock because ensure/stop paths already hold it before reaching here.
        with self._lifecycle_lock:
            return self._host_locked()

    def _host_locked(self) -> PiRuntimeHostClient:
        with self._lock:
            if self._client is not None and self._client.running:
                return self._client
        if not self.config.enabled:
            raise PiRuntimeError("Pi runtime is disabled")
        if self.config.executable is None:
            raise PiRuntimeError(self.config.installation_error or "managed Pi runtime is not installed")
        self.reconcile_runtime_hosts()
        client = PiRuntimeHostClient(
            self.config,
            on_event=self._handle_host_event,
            on_exit=self._handle_host_exit,
            kill_gate=self._kill_gate,
            owner_instance_id=self._owner_instance_id,
        )
        with self._lock:
            self._client = client
            self._status = "starting"
            self._last_error = ""
            self._intentional_stop = False
        try:
            hello = client.start()
        except Exception as exc:
            with self._lock:
                if self._client is client:
                    self._client = None
                self._status = "faulted"
                self._last_error = redact_runtime_text(str(exc))
            client.stop()
            raise
        with self._lock:
            self._host_capabilities = dict(as_mapping(hello.get("capabilities")))
            self._status = "ready"
        return client

    def ensure(self, session_id: str) -> dict[str, object]:
        with self._lifecycle_lock:
            if not self.config.model_configured:
                raise PiRuntimeError(
                    self.config.model_configuration_error
                    or "Pi model is not configured"
                )
            client = self._host()
            session = dict(self.sessions.get(session_id))
            binding = self.sessions.runtime_binding(session_id)
            if binding is not None:
                if (
                    binding.get("driverId") != self.driver_id
                    or binding.get("runtimeKind") != self.runtime_kind
                ):
                    raise PiRuntimeError(
                        "Agent session belongs to another runtime driver"
                    )
                session["_runtimeBinding"] = binding
            if self._session_context_provider is not None:
                session.update(dict(self._session_context_provider(session)))

            with self._lock:
                already_open = session_id in self._open_sessions
            if already_open:
                use_control_state = bool(
                    self._host_capabilities.get("sessionControlState")
                )
                snapshot = dict(
                    client.send(
                        (
                            "session.control_state"
                            if use_control_state
                            else "session.snapshot"
                        ),
                        {"sessionId": session_id},
                    )
                )
                if use_control_state and (
                    snapshot.get("schemaVersion")
                    != "rag-ime.pi-session-control-state.v1"
                    or snapshot.get("sessionId") != session_id
                    or not isinstance(snapshot.get("isIdle"), bool)
                ):
                    raise PiRuntimeError(
                        "Pi Runtime Host returned an invalid Session control state"
                    )
                self._sync_idle_snapshot(session_id, snapshot)
                with self._lock:
                    self._schedule_idle_locked()
                return {"state": snapshot, "reused": True}

            roots = [
                str(value)
                for value in session.get("workspaceRoots") or []
                if str(value).strip()
            ]
            cwd = roots[0] if roots else str(self.config.agent_dir)
            provider, model_id = self.config.resolved_model_reference(session)
            session_file = str(
                (binding or {}).get("transcriptRef")
                or session.get("sessionFile")
                or ""
            ).strip()
            memory_curation_session = (
                str(session.get("toolProfileVersion") or "")
                == MEMORY_CURATION_TOOL_PROFILE
            )
            params: dict[str, object] = {
                "sessionId": session_id,
                "cwd": cwd,
                "systemPrompt": self.config.system_prompt_for_session(session),
                "toolManifest": (
                    []
                    if memory_curation_session
                    else self.tool_catalog(session_id)
                ),
                "noContextFiles": (
                    str(session.get("toolProfileVersion") or "")
                    in {
                        "ime-surface-v1",
                        "voice-refinement-v1",
                        MEMORY_CURATION_TOOL_PROFILE,
                    }
                    or not bool(session.get("projectContextEnabled", False))
                ),
                "piSkillsEnabled": (
                    False
                    if memory_curation_session
                    else bool(session.get("piSkillsEnabled", False))
                ),
                "codexSkillsEnabled": (
                    False
                    if memory_curation_session
                    else bool(session.get("codexSkillsEnabled", False))
                ),
            }
            session_context = str(session.get("sessionContext") or "").strip()
            if session_context:
                params["sessionContext"] = session_context
            if provider and model_id:
                params.update({"provider": provider, "modelId": model_id})
            thinking_level = str(
                session.get("thinkingLevel") or ""
            ).strip().lower()
            if thinking_level:
                params["thinkingLevel"] = thinking_level
            if session_file:
                params["sessionFile"] = session_file

            result = client.send(
                "session.open",
                params,
                timeout=max(
                    60.0,
                    self.config.command_timeout_seconds,
                ),
            )
            snapshot = dict(as_mapping(result.get("snapshot")))
            model = as_mapping(snapshot.get("model"))
            if model.get("provider") and model.get("id"):
                self.sessions.set_model_profile(
                    session_id,
                    f"{model['provider']}/{model['id']}",
                )
            bound = self.sessions.bind_runtime_session(
                session_id,
                driver_id=self.driver_id,
                runtime_kind=self.runtime_kind,
                external_session_id=str(
                    snapshot.get("piSessionId") or session_id
                ),
                transcript_ref=str(snapshot.get("sessionFile") or ""),
                branch_anchor=str(snapshot.get("leafId") or ""),
                binding_state="active",
                metadata={"protocolVersion": _PROTOCOL_VERSION},
                # The Host count describes Pi's Provider transcript and can
                # include Tool/protocol entries.  AgentMessageSnapshot owns
                # the public conversation count, so opening a resident Pi
                # Session must preserve that product projection instead of
                # overwriting it with a different unit.
                message_count=max(0, int(session.get("messageCount") or 0)),
            )
            idle_session = self._sync_idle_snapshot(
                session_id,
                snapshot,
            )
            if idle_session is not None:
                bound = idle_session
            evicted = str(result.get("evictedSessionId") or "")
            with self._lock:
                self._open_sessions.add(session_id)
                hosted_state = self._states.setdefault(
                    session_id,
                    _HostedSessionState(),
                )
                if evicted:
                    self._open_sessions.discard(evicted)
                    evicted_state = self._states.pop(evicted, None)
                    if evicted_state is not None:
                        if evicted_state.abort_timer is not None:
                            evicted_state.abort_timer.cancel()
                        if evicted_state.settle_timer is not None:
                            evicted_state.settle_timer.cancel()
                admission_in_flight = (
                    hosted_state.prompt_admission_in_flight
                )
                self._status = (
                    "busy" if admission_in_flight else "ready"
                )
                if not admission_in_flight:
                    self._schedule_idle_locked()
            # Opening a cold Pi Session is part of prompt admission. Do not
            # publish a late `ready` after a concurrent Stop already exposed
            # `aborting`; that would regress the UI while the same admission
            # is still being fenced.
            if not admission_in_flight:
                self.events.publish(
                    session_id,
                    "status_changed",
                    {"status": "ready"},
                )
            return {
                "state": snapshot,
                "session": bound,
                "evictedSessionId": evicted or None,
                "reused": False,
            }

    def _sync_idle_snapshot(
        self,
        session_id: str,
        snapshot: Mapping[str, object],
    ) -> dict[str, object] | None:
        """Project Pi's run lifecycle into product status, not Host residency."""

        if not bool(snapshot.get("isIdle")):
            return None
        with self._lock:
            state = self._states.get(session_id)
            if state is not None and (
                state.turn_id or state.prompt_admission_in_flight
            ):
                return None
        session = self.sessions.get(session_id)
        if str(session.get("status") or "") == "idle":
            return session
        # Pi's snapshot count includes Provider-loop and Tool protocol entries.
        # The public message snapshot owner reconciles the durable human
        # transcript count after projection; writing the Provider count here
        # caused two competing SQLite updates on every history poll.
        return self.sessions.set_status(session_id, "idle")

    def reserve_prompt_admission(
        self,
        session_id: str,
        *,
        client_message_id: str = "",
    ) -> dict[str, object]:
        """Fence Stop before prompt preparation reaches the Pi Host.

        The application service can spend noticeable time assembling context
        before ``prompt()`` is called. Reserving that admission here gives a
        concurrent Stop request one Runtime-owned state to mark, without
        inventing a second turn or cancellation state machine.
        """

        normalized_client_message_id = str(client_message_id).strip()
        with self._lock:
            state = self._states.setdefault(
                session_id,
                _HostedSessionState(),
            )
            same_reservation = (
                state.prompt_admission_in_flight
                and state.admission_client_message_id
                == normalized_client_message_id
            )
            if state.turn_id or (
                state.prompt_admission_in_flight
                and not same_reservation
            ):
                raise PiRuntimeTurnConflict(
                    "Pi 正在处理上一轮，请等待结束或停止完成后再发送"
                )
            if not same_reservation:
                state.prompt_admission_in_flight = True
                state.admission_client_message_id = (
                    normalized_client_message_id
                )
                state.abort_pending_admission = False
                state.prompt_dispatch_signal.clear()
            self._cancel_idle_locked()
        self.sessions.set_status(session_id, "busy")
        return {
            "reserved": True,
            "reused": same_reservation,
            "sessionId": session_id,
            "clientMessageId": normalized_client_message_id,
        }

    def release_prompt_admission(
        self,
        session_id: str,
        *,
        client_message_id: str = "",
    ) -> bool:
        """Release an unconsumed application admission after preparation fails."""

        normalized_client_message_id = str(client_message_id).strip()
        with self._lock:
            state = self._states.get(session_id)
            if (
                state is None
                or state.turn_id
                or not state.prompt_admission_in_flight
                or state.admission_client_message_id
                != normalized_client_message_id
            ):
                return False
            state.prompt_admission_in_flight = False
            state.admission_client_message_id = ""
            state.abort_pending_admission = False
            state.prompt_dispatch_signal.set()
            self._schedule_idle_locked()
        self.sessions.set_status(session_id, "idle")
        return True

    def prompt(
        self,
        session_id: str,
        message: str,
        *,
        images: list[Mapping[str, str]] | None = None,
        client_message_id: str = "",
        delivery: str = "prompt",
    ) -> dict[str, object]:
        text = str(message).strip()
        if not text:
            raise ValueError("agent prompt must not be empty")
        normalized_delivery = message_delivery(delivery)
        public_prompt_preview = visible_message_text("user", text)
        params: dict[str, object] = {
            "sessionId": session_id,
            "message": text,
            "clientMessageId": str(client_message_id).strip(),
        }
        if images:
            params["images"] = [dict(image) for image in images]
        if normalized_delivery != "prompt":
            with self._lock:
                state = self._states.setdefault(session_id, _HostedSessionState())
                turn_id = state.turn_id
                pending_admission = state.prompt_admission_in_flight
                dispatch_signal = state.prompt_dispatch_signal
                if (
                    state.abort_requested_turn_id
                    or state.abort_pending_admission
                    or (not turn_id and not pending_admission)
                ):
                    raise PiRuntimeCommandRejected(
                        "Pi 当前没有可接收排队消息的活动回合",
                        host_error_code="SESSION_IDLE",
                    )
                self._cancel_idle_locked()
            if not turn_id:
                # The application reserves a prompt before it assembles
                # context. A Steer can therefore arrive while the product is
                # already busy but before the prompt JSONL reaches Pi. Wait for
                # that single ownership hand-off; the Host remains the source
                # of truth for whether the turn can accept the message.
                if not dispatch_signal.wait(
                    timeout=max(1.0, self.config.command_timeout_seconds)
                ):
                    raise PiRuntimeCommandRejected(
                        "Pi 仍在准备当前回合，尚不能接收排队消息",
                        host_error_code="PROMPT_ADMISSION_PENDING",
                    )
                with self._lock:
                    state = self._states.setdefault(
                        session_id,
                        _HostedSessionState(),
                    )
                    turn_id = state.turn_id
                    if (
                        state.abort_requested_turn_id
                        or state.abort_pending_admission
                        or (
                            not turn_id
                            and not state.prompt_admission_in_flight
                        )
                    ):
                        raise PiRuntimeCommandRejected(
                            "Pi 当前没有可接收排队消息的活动回合",
                            host_error_code="SESSION_IDLE",
                        )
            client = self._require_client()
            method = "session.steer" if normalized_delivery == "steer" else "session.follow_up"
            response = client.send(method, params)
            response_turn_id = str(response.get("turnId") or turn_id)
            with self._lock:
                state = self._states.setdefault(
                    session_id,
                    _HostedSessionState(),
                )
                active_turn_id = state.turn_id
                if (
                    active_turn_id
                    and response_turn_id != active_turn_id
                ):
                    raise PiRuntimeError(
                        "Pi 返回了不匹配的排队消息回合"
                    )
                if not active_turn_id and response_turn_id:
                    state.turn_id = response_turn_id
                    active_turn_id = response_turn_id
                turn_id = active_turn_id or response_turn_id
            if not turn_id:
                raise PiRuntimeError("Pi 未返回排队消息所属的活动回合")
            result: dict[str, object] = {
                "accepted": True,
                "queued": True,
                "delivery": normalized_delivery,
                "turnId": turn_id,
                "piEntryId": f"queue:{str(client_message_id).strip()}" if client_message_id else "",
                "response": response,
            }
            if client_message_id:
                result["clientMessageId"] = str(client_message_id).strip()
            return result
        self.ensure(session_id)
        client = self._require_client()
        normalized_client_message_id = str(client_message_id).strip()
        with self._lock:
            state = self._states.setdefault(session_id, _HostedSessionState())
            pre_reserved = (
                state.prompt_admission_in_flight
                and state.admission_client_message_id
                == normalized_client_message_id
            )
            if state.turn_id or (
                state.prompt_admission_in_flight and not pre_reserved
            ):
                raise PiRuntimeTurnConflict(
                    "Pi 正在处理上一轮，请等待结束或停止完成后再发送"
                )
            self._cancel_idle_locked()
            if not pre_reserved:
                state.prompt_admission_in_flight = True
                state.admission_client_message_id = (
                    normalized_client_message_id
                )
                state.abort_pending_admission = False
                state.prompt_dispatch_signal.clear()
            state.stream_pi_message_id = ""
            state.tool_blocks.clear()
            state.last_agent_messages = []
            state.final_error = ""
            state.had_tool_activity = False
            state.settle_extension_failed = False
            state.abort_requested_turn_id = ""
        # The browser renders Stop from its optimistic turn before the Host
        # returns a turnId. Persist the admission as busy so a concurrent Stop
        # and snapshot cannot mistake that short window for an idle Session.
        self.sessions.set_status(
            session_id,
            "busy",
            last_message_preview=public_prompt_preview,
        )
        try:
            # The Runtime Host resolves `session.prompt` after Pi accepts the
            # turn preflight. Stop and Steer remain responsive through the
            # Host's concurrent request dispatcher while that ACK is pending.
            accepted = client.send(
                "session.prompt",
                params,
                timeout=max(
                    _PROMPT_TIMEOUT_SECONDS,
                    self.config.command_timeout_seconds,
                ),
                before_write=state.prompt_dispatch_signal.set,
            )
        except Exception as exc:
            with self._lock:
                state = self._states.setdefault(
                    session_id,
                    _HostedSessionState(),
                )
                state.prompt_admission_in_flight = False
                state.admission_client_message_id = ""
                state.abort_pending_admission = False
                state.prompt_dispatch_signal.set()
            self._turn_failed(session_id, "", exc)
            raise
        turn_id = str(accepted.get("turnId") or "")
        with self._lock:
            state = self._states.setdefault(session_id, _HostedSessionState())
            abort_after_admission = state.abort_pending_admission
            state.prompt_admission_in_flight = False
            state.admission_client_message_id = ""
            state.abort_pending_admission = False
            already_retired = (
                turn_id in state.retired_turn_ids
                or (session_id, turn_id) in self._retired_host_turns
            )
            already_aborting = state.abort_requested_turn_id == turn_id
            if not already_retired:
                state.turn_id = turn_id
                state.client_message_id = normalized_client_message_id
                self._status = "busy"
        if not already_retired:
            self.sessions.set_status(
                session_id,
                "busy",
                last_message_preview=public_prompt_preview,
            )
            if not already_aborting and not abort_after_admission:
                self.events.publish(
                    session_id,
                    "status_changed",
                    {"status": "busy"},
                    turn_id=turn_id,
                )
            if abort_after_admission:
                # The original Stop request already returned immediately. Now
                # that Pi supplied the exact turn fence, deliver cancellation
                # through the ordinary Pi Session abort path. Its timer owns
                # the existing one-second escalation if the Host never settles.
                try:
                    self.abort(session_id)
                except Exception:
                    pass
        else:
            self.sessions.set_status(
                session_id,
                "idle",
                last_message_preview="已停止。",
            )
        result: dict[str, object] = {
            "accepted": True,
            "turnId": turn_id,
            "piEntryId": turn_id,
            "response": accepted,
        }
        if abort_after_admission or already_aborting or already_retired:
            result["abortRequested"] = True
        if client_message_id:
            result["clientMessageId"] = str(client_message_id).strip()
        return result

    def messages(self, session_id: str) -> list[dict[str, object]]:
        return list(self.session_snapshot(session_id).get("messages") or [])

    def _durable_history_snapshot(
        self,
        session_id: str,
    ) -> dict[str, object] | None:
        """Read an idle managed Pi transcript without opening Provider context."""

        try:
            session = self.sessions.get(session_id)
            binding = self.sessions.runtime_binding(session_id) or {}
            raw_path = str(
                binding.get("transcriptRef")
                or session.get("sessionFile")
                or ""
            ).strip()
            if not raw_path:
                return None
            candidate = Path(raw_path).expanduser()
            if candidate.is_symlink():
                return None
            transcript = candidate.resolve(strict=True)
            session_root = self.config.session_dir.expanduser().resolve(
                strict=False
            )
            if not path_is_within(transcript, session_root):
                return None
            stat = transcript.stat()
            if not transcript.is_file() or stat.st_size > 64 * 1024 * 1024:
                return None
            entries: list[dict[str, object]] = []
            with transcript.open("r", encoding="utf-8") as source:
                for index, line in enumerate(source):
                    if index >= 200_000 or len(line) > 8 * 1024 * 1024:
                        return None
                    try:
                        value = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(value, Mapping):
                        entries.append(dict(value))
            if not entries:
                return None
            external_session_id = str(
                binding.get("externalSessionId")
                or session.get("piSessionId")
                or ""
            )
            header = entries[0]
            if (
                str(header.get("type") or "") == "session"
                and external_session_id
                and str(header.get("id") or "") != external_session_id
            ):
                return None
            leaf_id = str(binding.get("branchAnchor") or "")
            binding_updated_at_ms = as_integer(binding.get("updatedAtMs"))
            # The binding is refreshed when the Session opens or rewinds. If
            # Pi appended newer entries after that point, the append-only
            # transcript's final entry is the current selected leaf and avoids
            # projecting a stale pre-turn anchor.
            if stat.st_mtime_ns // 1_000_000 > binding_updated_at_ms:
                leaf_id = next(
                    (
                        str(entry.get("id") or "")
                        for entry in reversed(entries)
                        if str(entry.get("id") or "")
                    ),
                    leaf_id,
                )
            messages, _selected_entries = _pi_durable_branch_messages(
                entries,
                leaf_id=leaf_id,
            )
            return {
                "sessionId": session_id,
                "piSessionId": external_session_id,
                "sessionFile": transcript.as_posix(),
                "leafId": leaf_id,
                "isIdle": True,
                "activeTurn": None,
                "messages": messages,
                "entries": entries,
                "messageQueue": {
                    "steering": [],
                    "followUp": [],
                    "steeringMode": "",
                    "followUpMode": "",
                },
            }
        except (KeyError, OSError, ValueError):
            return None

    def _inspection_snapshot(
        self,
        session_id: str,
        *,
        durable_fallback: bool = True,
    ) -> dict[str, object]:
        """Read one Session without rebuilding context when it is resident.

        Dynamic memory and Room projections are compiled when a Session opens
        or rebinds. Historical display is instead reconstructed from Pi's
        managed durable JSONL before taking the Host lifecycle lock, so a slow
        command/context open cannot hold the conversation rail behind it.
        """

        with self._lock:
            active_turn = self._states.get(session_id)
            turn_id = active_turn.turn_id if active_turn is not None else ""
            already_open = session_id in self._open_sessions
        # The append-only transcript is the cheap authority for idle history,
        # including an already resident Session. Large live snapshots may need
        # to rebuild Pi's Provider context and can otherwise hold the timeline
        # blank for several seconds. A resident header-only transcript is the
        # exception: its just-settled messages may still exist only in the Host,
        # so an empty durable projection must not erase that live body.
        if durable_fallback and not turn_id:
            durable = self._durable_history_snapshot(session_id)
            if durable is not None and (
                not already_open or bool(durable.get("messages"))
            ):
                return durable

        with self._lifecycle_lock:
            client = self._host()
            with self._lock:
                already_open = session_id in self._open_sessions
            if already_open:
                snapshot = dict(
                    client.send(
                        "session.snapshot",
                        {"sessionId": session_id},
                    )
                )
                self._sync_idle_snapshot(session_id, snapshot)
                with self._lock:
                    self._schedule_idle_locked()
                return snapshot
            prepared = self.ensure(session_id)
            prepared_state = prepared.get("state")
            if isinstance(prepared_state, Mapping):
                return dict(prepared_state)
            return dict(
                self._require_client().send(
                    "session.snapshot",
                    {"sessionId": session_id},
                )
            )

    def session_snapshot(self, session_id: str) -> dict[str, object]:
        try:
            snapshot = self._inspection_snapshot(session_id)
        except AgentRuntimeError:
            return {"messages": [], "telemetry": None, "messageQueue": None}
        raw_messages = snapshot.get("messages") if isinstance(snapshot.get("messages"), list) else []
        raw_entries = snapshot.get("entries") if isinstance(snapshot.get("entries"), list) else []
        durable_messages, durable_entries = _pi_durable_branch_messages(
            raw_entries,
            leaf_id=str(snapshot.get("leafId") or ""),
        )
        # `snapshot.messages` is Pi's current Provider context.  After
        # compaction or branch restoration it may omit older human messages,
        # even though the durable entries still contain the selected branch.
        # The conversation UI must project that durable branch rather than
        # turning a populated Session into the welcome screen.
        projection_messages = durable_messages or raw_messages
        projection_entries = durable_entries or raw_entries
        tool_history_events = _pi_tool_history_events(
            projection_messages,
            session_id=session_id,
            raw_entries=projection_entries,
        )
        result: list[dict[str, object]] = []
        current_turn_id = ""
        last_assistant_fingerprint: tuple[str, str] | None = None
        durable_assistant_counts = _durable_public_assistant_counts(
            projection_entries,
            session_id=session_id,
        )
        emitted_assistant_counts: dict[str, int] = {}
        for raw in projection_messages:
            if not isinstance(raw, Mapping) or not pi_message_is_public(raw):
                continue
            role = str(raw.get("role") or "assistant").lower()
            message_id = pi_message_id(raw, "history")
            if role == "user" or not current_turn_id:
                current_turn_id = f"history:{message_id}"
                last_assistant_fingerprint = None
            payload = pi_message_payload(
                raw,
                session_id=session_id,
                turn_id=current_turn_id,
                media_resolver=self._media_resolver,
                message_id=message_id,
            ).to_payload()
            if role == "assistant":
                projection_fingerprint = _assistant_projection_fingerprint(
                    payload
                )
                durable_count = durable_assistant_counts.get(
                    projection_fingerprint,
                    0,
                )
                emitted_count = emitted_assistant_counts.get(
                    projection_fingerprint,
                    0,
                )
                # session.messages can replay a previously settled assistant
                # object after a native follow-up. The durable transcript is
                # authoritative for how many semantic copies really exist.
                # This removes a replay even when it crosses a new user turn,
                # while preserving two intentionally identical replies when
                # the transcript contains both.
                if durable_count and emitted_count >= durable_count:
                    continue
                fingerprint = (
                    current_turn_id,
                    projection_fingerprint,
                )
                # Pi may transiently project the same settled assistant object
                # twice after a native follow-up. Its JSONL transcript contains
                # one message, so collapse only an adjacent exact duplicate in
                # the same user turn. Identical replies in later turns remain.
                if fingerprint == last_assistant_fingerprint:
                    continue
                last_assistant_fingerprint = fingerprint
                emitted_assistant_counts[projection_fingerprint] = (
                    emitted_count + 1
                )
            result.append(
                payload
            )
        telemetry = snapshot.get("telemetry")
        raw_queue = as_mapping(snapshot.get("messageQueue"))
        message_queue = {
            "steering": public_message_queue(raw_queue.get("steering")),
            "followUp": public_message_queue(raw_queue.get("followUp")),
            "steeringMode": str(raw_queue.get("steeringMode") or ""),
            "followUpMode": str(raw_queue.get("followUpMode") or ""),
        }
        return {
            "messages": result,
            "toolHistoryEvents": tool_history_events,
            "telemetry": dict(telemetry) if isinstance(telemetry, Mapping) else None,
            "messageQueue": message_queue,
        }

    def debug_context(self, session_id: str, turn_id: str = "") -> dict[str, object]:
        with self._lock:
            already_open = session_id in self._open_sessions
        if not already_open:
            # Context inspection is observational. Reopening an idle historical
            # Session here can restore a large Pi transcript, block the local
            # control server, and evict an actively used Session. The UI can
            # truthfully report that raw Provider context is unavailable until
            # the Session is resident again.
            return {
                "schemaVersion": "rag-ime.pi-debug-context-response.v1",
                "sessionId": session_id,
                "turnId": str(turn_id or "").strip(),
                "available": False,
                "transient": True,
                "context": None,
                "telemetry": None,
                "reason": "session_not_resident",
            }
        params: dict[str, object] = {"sessionId": session_id}
        if str(turn_id).strip():
            params["turnId"] = str(turn_id).strip()
        try:
            result = self._require_client().send(
                "session.debug.context",
                params,
                # Context inspection is optional observability. It must never
                # inherit the ordinary command timeout and hold a control
                # request open while a large or unhealthy Session is resident.
                timeout=min(1.0, max(0.1, self.config.command_timeout_seconds)),
            )
        except PiRuntimeError as exc:
            if "timed out: session.debug.context" not in str(exc):
                raise
            return {
                "schemaVersion": "rag-ime.pi-debug-context-response.v1",
                "sessionId": session_id,
                "turnId": str(turn_id or "").strip(),
                "available": False,
                "transient": True,
                "context": None,
                "telemetry": None,
                "reason": "runtime_unresponsive",
            }
        return dict(result)

    def rewind_session(self, session_id: str, *, entry_id: str) -> dict[str, object]:
        normalized_entry_id = str(entry_id or "").strip()
        if not normalized_entry_id:
            raise ValueError("conversation rewrite entryId must not be empty")
        with self._lifecycle_lock:
            self._require_idle_fork_session(session_id)
            try:
                self.ensure(session_id)
                client = self._require_client()
                with self._lock:
                    self._require_quiescent_fork_locked(session_id)
                    self._cancel_idle_locked()
                candidates = self._fork_candidates_from_result(
                    client.send("session.fork.candidates", {"sessionId": session_id})
                )
                selected = next(
                    (
                        candidate
                        for candidate in candidates
                        if candidate["entryId"] == normalized_entry_id
                        and candidate["role"] == "user"
                    ),
                    None,
                )
                if selected is None:
                    raise PiRuntimeError(
                        "conversation rewrite entry must identify a public user message"
                    )
                response = client.send(
                    "session.rewind",
                    {"sessionId": session_id, "entryId": normalized_entry_id},
                )
                with self._lock:
                    self._schedule_idle_locked()
                return {
                    "entryId": normalized_entry_id,
                    "editorText": str(response.get("editorText") or selected["text"]),
                    "leafId": str(response.get("leafId") or ""),
                }
            finally:
                if str(self.sessions.get(session_id).get("status") or "") == "active":
                    self.sessions.set_status(session_id, "idle")

    def fork_candidates(self, session_id: str) -> list[dict[str, object]]:
        with self._lifecycle_lock:
            self._require_idle_fork_session(session_id)
            try:
                self.ensure(session_id)
                with self._lock:
                    self._require_quiescent_fork_locked(session_id)
                result = self._require_client().send(
                    "session.fork.candidates",
                    {"sessionId": session_id},
                )
                with self._lock:
                    self._schedule_idle_locked()
                return self._fork_candidates_from_result(result)
            finally:
                if str(self.sessions.get(session_id).get("status") or "") == "active":
                    self.sessions.set_status(session_id, "idle")

    def fork_session(
        self,
        source_session_id: str,
        target_session_id: str,
        *,
        entry_id: str,
    ) -> dict[str, object]:
        normalized_entry_id = str(entry_id or "").strip()
        if not normalized_entry_id:
            raise ValueError("conversation fork entryId must not be empty")
        with self._lifecycle_lock:
            self._require_idle_fork_session(source_session_id)
            target = self.sessions.get(target_session_id)
            if str(target.get("status") or "") != "idle":
                raise PiRuntimeError("conversation fork target must be idle")
            if self.sessions.runtime_binding(target_session_id) is not None:
                raise PiRuntimeError("conversation fork target is already bound")
            self.ensure(source_session_id)
            source_binding = self.sessions.runtime_binding(source_session_id)
            if not isinstance(source_binding, Mapping):
                raise PiRuntimeError("conversation fork source has no runtime binding")
            source_transcript = str(source_binding.get("transcriptRef") or "").strip()
            client = self._require_client()
            try:
                with self._lock:
                    self._require_quiescent_fork_locked(source_session_id)
                    self._cancel_idle_locked()
                candidates = self._fork_candidates_from_result(
                    client.send("session.fork.candidates", {"sessionId": source_session_id})
                )
            except Exception:
                self.sessions.set_status(source_session_id, "idle")
                self.sessions.set_status(target_session_id, "idle")
                with self._lock:
                    self._schedule_idle_locked()
                raise
            selected = next(
                (candidate for candidate in candidates if candidate["entryId"] == normalized_entry_id),
                None,
            )
            if selected is None:
                self.sessions.set_status(source_session_id, "idle")
                with self._lock:
                    self._schedule_idle_locked()
                raise PiRuntimeError("conversation fork entry is not available in the source Session")

            opened_target = False
            branch_transcript: Path | None = None
            branch_cleanup_safe = False
            try:
                forked = client.send(
                    "session.fork",
                    {
                        "sessionId": source_session_id,
                        "targetSessionId": target_session_id,
                        "entryId": normalized_entry_id,
                    },
                    timeout=max(60.0, self.config.command_timeout_seconds),
                )
                opened_target = True
                if str(forked.get("sourceSessionId") or "") != source_session_id:
                    raise PiRuntimeError("Pi returned a mismatched conversation fork source")
                if str(forked.get("targetSessionId") or "") != target_session_id:
                    raise PiRuntimeError("Pi returned a mismatched conversation fork target")
                snapshot = dict(as_mapping(forked.get("snapshot")))
                external_session_id = str(snapshot.get("piSessionId") or "").strip()
                transcript_ref = str(snapshot.get("sessionFile") or "").strip()
                if not external_session_id or not transcript_ref:
                    raise PiRuntimeError("Pi returned an incomplete conversation fork identity")
                branch_candidate = Path(transcript_ref).expanduser()
                if branch_candidate.is_symlink():
                    raise PiRuntimeError("Pi conversation fork file must not be a symlink")
                branch_transcript = branch_candidate.resolve(strict=False)
                session_root = self.config.session_dir.expanduser().resolve(strict=False)
                if not path_is_within(branch_transcript, session_root):
                    raise PiRuntimeError("Pi conversation fork file is outside the managed session directory")
                source_path = Path(source_transcript).expanduser().resolve(strict=False) if source_transcript else None
                if source_path is not None and branch_transcript == source_path:
                    raise PiRuntimeError("Pi conversation fork reused the source transcript")
                if external_session_id == str(source_binding.get("externalSessionId") or ""):
                    raise PiRuntimeError("Pi conversation fork reused the source runtime identity")
                branch_cleanup_safe = True

                bound = self.sessions.bind_runtime_session(
                    target_session_id,
                    driver_id=self.driver_id,
                    runtime_kind=self.runtime_kind,
                    external_session_id=external_session_id,
                    transcript_ref=branch_transcript.as_posix(),
                    branch_anchor=str(forked.get("branchAnchor") or normalized_entry_id),
                    binding_state="active",
                    metadata={
                        "protocolVersion": _PROTOCOL_VERSION,
                        "forkedFromSessionId": source_session_id,
                        "forkEntryId": normalized_entry_id,
                    },
                    message_count=len(snapshot.get("messages") or []),
                )
                evicted = str(forked.get("evictedSessionId") or "")
                with self._lock:
                    self._open_sessions.add(target_session_id)
                    self._states.setdefault(target_session_id, _HostedSessionState())
                    if evicted:
                        self._open_sessions.discard(evicted)
                        evicted_state = self._states.pop(evicted, None)
                        if evicted_state is not None:
                            if evicted_state.abort_timer is not None:
                                evicted_state.abort_timer.cancel()
                            if evicted_state.settle_timer is not None:
                                evicted_state.settle_timer.cancel()
                    self._status = "ready"
                    self._schedule_idle_locked()
                self.sessions.set_status(source_session_id, "idle")
                bound = self.sessions.set_status(target_session_id, "idle")
                self.events.publish(
                    target_session_id,
                    "session_configuration_changed",
                    {
                        "kind": "fork",
                        "sourceSessionId": source_session_id,
                        "entryId": normalized_entry_id,
                    },
                )
                return {
                    "sourceSessionId": source_session_id,
                    "targetSessionId": target_session_id,
                    "entryId": normalized_entry_id,
                    # The host response can contain the raw transport prompt.
                    # Restore only the public text confirmed by the catalog.
                    "selectedText": str(selected["text"]) if selected["role"] == "user" else "",
                    "state": snapshot,
                    "session": bound,
                }
            except Exception:
                if opened_target:
                    try:
                        client.send("session.close", {"sessionId": target_session_id})
                    except AgentRuntimeError:
                        pass
                    with self._lock:
                        self._open_sessions.discard(target_session_id)
                        target_state = self._states.pop(target_session_id, None)
                        if target_state is not None:
                            if target_state.abort_timer is not None:
                                target_state.abort_timer.cancel()
                            if target_state.settle_timer is not None:
                                target_state.settle_timer.cancel()
                if (
                    branch_transcript is not None
                    and branch_cleanup_safe
                    and branch_transcript.is_file()
                    and not branch_transcript.is_symlink()
                ):
                    try:
                        branch_transcript.unlink()
                    except OSError:
                        pass
                self.sessions.set_status(source_session_id, "idle")
                self.sessions.set_status(target_session_id, "idle")
                with self._lock:
                    self._schedule_idle_locked()
                raise

    def _require_idle_fork_session(self, session_id: str) -> None:
        session = self.sessions.get(session_id)
        if str(session.get("status") or "") not in {"idle", "active"}:
            raise PiRuntimeError("conversation forks are only available for idle Sessions")

    def _require_quiescent_fork_locked(self, session_id: str) -> None:
        state = self._states.get(session_id)
        if state is None:
            return
        if state.turn_id:
            raise PiRuntimeError("conversation forks are unavailable during an Agent turn")
        if state.pending_approvals or state.pending_reviews or state.pending_ui_requests:
            raise PiRuntimeError("conversation forks are unavailable while user input is pending")

    @staticmethod
    def _fork_candidates_from_result(result: Mapping[str, object]) -> list[dict[str, object]]:
        raw_items = result.get("items")
        if not isinstance(raw_items, list):
            raise PiRuntimeError("Pi returned an invalid conversation fork catalog")
        candidates: list[dict[str, object]] = []
        seen: set[str] = set()
        for raw in raw_items[:500]:
            if not isinstance(raw, Mapping):
                continue
            entry_id = str(raw.get("entryId") or "").strip()[:240]
            role = str(raw.get("role") or "").strip().lower()
            created_at_ms = as_integer(raw.get("createdAtMs"))
            text = public_fork_candidate_text(raw.get("text"), role=role)
            if (
                not entry_id
                or role not in {"user", "assistant"}
                or not text
                or entry_id in seen
            ):
                continue
            seen.add(entry_id)
            candidates.append(
                {
                    "entryId": entry_id,
                    "text": text,
                    "role": role,
                    "createdAtMs": max(0, created_at_ms),
                }
            )
        return candidates

    def command_catalog(self, session_id: str) -> list[dict[str, object]]:
        # Catalog inspection must not rebuild generic RAG/memory context for an
        # already resident Session. That projection is needed when opening or
        # rebinding a Provider turn, not when listing slash commands.
        self._inspection_snapshot(session_id, durable_fallback=False)
        response = self._require_client().send("session.commands", {"sessionId": session_id})
        raw_commands = response.get("commands")
        if not isinstance(raw_commands, list):
            return []
        commands: list[dict[str, object]] = []
        seen: set[str] = set()
        for value in raw_commands[:200]:
            if not isinstance(value, Mapping):
                continue
            source = str(value.get("source") or "").strip()
            name = str(value.get("name") or "").strip()
            if source not in {"extension", "prompt", "skill"}:
                continue
            if not re.fullmatch(r"[\w][\w.:-]{0,79}", name, flags=re.UNICODE):
                continue
            identity = name.casefold()
            if identity in seen:
                continue
            seen.add(identity)
            commands.append(
                {
                    "name": name,
                    "invocation": f"/{name}",
                    "description": " ".join(str(value.get("description") or "").split())[:240],
                    "source": source,
                }
            )
        return commands

    def model_catalog(self, session_id: str) -> dict[str, object]:
        # Model selection and thinking level are persisted after every Pi-owned
        # change. Reading that desired Session state avoids opening a large
        # transcript merely to render the picker; Pi still owns and supplies
        # the live capability catalog below.
        session = self.sessions.get(session_id)
        models = self.available_models()
        provider, model_id = self.config.resolved_model_reference(session)
        selected = next(
            (
                dict(model)
                for model in models
                if model.get("provider") == provider
                and model.get("id") == model_id
            ),
            None,
        )
        return {
            "selected": selected,
            "models": models,
            "thinkingLevel": effective_thinking_level(
                session.get("thinkingLevel"),
                selected or {},
            ),
        }

    def available_models(self) -> list[dict[str, object]]:
        # Opening the Agent page requests roles and the selected Session model
        # concurrently. Pi's catalog refresh may perform Provider discovery, so
        # coalesce those reads and keep one short-lived Pi-confirmed snapshot.
        # This cache never selects a model or fabricates capabilities.
        with self._lifecycle_lock:
            now = time.monotonic()
            with self._lock:
                if (
                    self._available_models_cache_ready
                    and now - self._available_models_cached_at
                    < _MODEL_CATALOG_CACHE_SECONDS
                ):
                    return [
                        dict(model)
                        for model in self._available_models_cache
                    ]
            try:
                catalog = self._host_locked().send(
                    "models.list",
                    timeout=max(30.0, self.config.command_timeout_seconds),
                )
            except Exception:
                # A previously Pi-confirmed catalog is safer and more useful
                # than turning a transient Provider-discovery failure into an
                # empty picker. It never changes the selected Session model;
                # a process with no confirmed cache still fails explicitly.
                with self._lock:
                    if self._available_models_cache_ready:
                        return [
                            dict(model)
                            for model in self._available_models_cache
                        ]
                raise
            models = [
                model
                for value in catalog.get("models") or []
                if isinstance(value, Mapping)
                for model in [public_pi_model(value)]
                if model
            ]
            models.sort(
                key=lambda item: (
                    str(item["provider"]).lower(),
                    str(item["name"]).lower(),
                )
            )
            with self._lock:
                self._available_models_cache = tuple(
                    dict(model) for model in models
                )
                self._available_models_cached_at = time.monotonic()
                self._available_models_cache_ready = True
            return [dict(model) for model in models]

    def complete_once(
        self,
        *,
        request_id: str,
        provider: str,
        model_id: str,
        thinking_level: str,
        message: str,
        on_text_delta: Callable[[str], None] | None = None,
        timeout_seconds: float = 120.0,
    ) -> dict[str, object]:
        normalized_request_id = model_reference_part(
            request_id,
            field="requestId",
            maximum=200,
        )
        normalized_provider = model_reference_part(provider, field="provider", maximum=80)
        normalized_model = model_reference_part(model_id, field="modelId", maximum=160)
        normalized_thinking = str(thinking_level or "").strip().lower()
        if normalized_thinking not in {"off", "minimal", "low", "medium", "high", "xhigh", "max"}:
            raise ValueError("stateless Pi completion received an unsupported thinking level")
        normalized_message = str(message or "").strip()
        if not normalized_message:
            raise ValueError("stateless Pi completion message is required")
        bounded_timeout = max(1.0, min(300.0, float(timeout_seconds)))
        params: dict[str, object] = {
            "requestId": normalized_request_id,
            "provider": normalized_provider,
            "modelId": normalized_model,
            "thinkingLevel": normalized_thinking,
            "message": normalized_message[:64_000],
            "timeoutMs": int(bounded_timeout * 1000),
        }
        with self._lifecycle_lock:
            client = self._host()
            with self._lock:
                if normalized_request_id in self._active_completion_ids:
                    raise PiRuntimeError("Pi stateless completion request is already active")
                self._cancel_idle_locked()
                self._active_completion_ids.add(normalized_request_id)
                if on_text_delta is not None:
                    self._completion_sinks[normalized_request_id] = on_text_delta
                self._status = "busy"
        try:
            result = client.send(
                "completion.once",
                params,
                timeout=bounded_timeout + 5.0,
            )
            return result
        except PiRuntimeError as exc:
            if str(exc) == "Pi Runtime Host command timed out: completion.once":
                self._cancel_timed_out_completion(
                    client,
                    request_id=normalized_request_id,
                    error=exc,
                )
            raise
        finally:
            with self._lock:
                self._active_completion_ids.discard(normalized_request_id)
                self._completion_sinks.pop(normalized_request_id, None)
                if (
                    self._client is client
                    and client.running
                    and not any(state.turn_id for state in self._states.values())
                ):
                    self._status = "ready"
                    self._schedule_idle_locked()

    def _cancel_timed_out_completion(
        self,
        client: PiRuntimeHostClient,
        *,
        request_id: str,
        error: PiRuntimeError,
    ) -> None:
        """Cancel one stateless completion without killing resident Sessions.

        ``completion.once`` is used by approval and other bounded model lanes.
        It shares the Host process with durable Room and conversation Sessions,
        but the Runtime Host dispatches ``completion.cancel`` concurrently and
        owns an AbortController per request.  A one-shot timeout therefore must
        stay inside that request's cancellation domain: killing the Host here
        would turn one slow arbiter into simultaneous, unrelated Session loss.

        A cancel RPC failure is retained as runtime diagnostics.  It still does
        not authorize a process-wide kill; an actually unhealthy Session will
        reach its own typed timeout/cancellation boundary independently.
        """

        message = redact_runtime_text(str(error))
        cancel_error = ""
        try:
            client.send(
                "completion.cancel",
                {"requestId": request_id},
                timeout=min(5.0, max(1.0, self.config.command_timeout_seconds)),
            )
        except Exception as exc:
            cancel_error = redact_runtime_text(str(exc))
        with self._lock:
            if self._client is client:
                self._last_error = (
                    message
                    if not cancel_error
                    else f"{message}; completion cancel failed: {cancel_error}"
                )

    def _retire_timed_out_host(
        self,
        client: PiRuntimeHostClient,
        *,
        requested_by: str,
        error: PiRuntimeError,
    ) -> None:
        """Fence a Host that stopped answering before an RPC boundary.

        A timed-out RPC has no trustworthy completion boundary: the Host may
        still emit a late response after the caller has returned. Reusing it
        also leaves its durable process row registered, so the next request
        either hangs behind the same process or cannot admit a replacement.
        The cancellation kill gate gives this failure a durable receipt;
        stopping the client then drains its reader threads and lets the normal
        Host-exit path fault resident Sessions.
        """

        message = redact_runtime_text(str(error))
        with self._lifecycle_lock:
            with self._lock:
                if self._client is not client:
                    return
                self._status = "stopping"
                self._last_error = message
            receipt: dict[str, object] | None = None
            kill_error = ""
            try:
                receipt = self._kill_gate.request_kill(
                    client.host_identity,
                    request_kind="cancel_timeout",
                    requested_by=requested_by,
                    reason=message,
                    now_ms=int(time.time() * 1000),
                )
            except Exception as exc:  # pragma: no cover - defensive local cleanup
                kill_error = redact_runtime_text(str(exc))
            finally:
                # request_kill is bounded and may return while the process is
                # only acknowledged. stop() completes the local teardown and
                # marks both the process row and any receipt terminal.
                client.stop()
            with self._lock:
                if receipt is not None:
                    self._last_kill_receipt = dict(
                        self._kill_gate.receipt(str(receipt["killReceiptId"]))
                    )
                self._status = "faulted"
                self._last_error = (
                    message
                    if not kill_error
                    else f"{message}; Runtime Host kill receipt failed: {kill_error}"
                )

    def cancel_completion(self, request_id: str) -> bool:
        try:
            normalized = model_reference_part(request_id, field="requestId", maximum=200)
        except ValueError:
            return False
        with self._lock:
            if normalized not in self._active_completion_ids:
                return False
            client = self._client
        if client is None or not client.running:
            return False
        result = client.send(
            "completion.cancel",
            {"requestId": normalized},
            timeout=min(5.0, max(1.0, self.config.command_timeout_seconds)),
        )
        return result.get("cancelled") is True

    def set_model(self, session_id: str, *, provider: str, model_id: str) -> dict[str, object]:
        normalized_provider = model_reference_part(provider, field="provider", maximum=80)
        normalized_model = model_reference_part(model_id, field="modelId", maximum=160)
        self.ensure(session_id)
        selected = public_pi_model(
            self._require_client().send(
                "session.model.set",
                {"sessionId": session_id, "provider": normalized_provider, "modelId": normalized_model},
            )
        )
        if not selected:
            raise PiRuntimeError("Pi did not return the selected model")
        session = self.sessions.set_model_profile(session_id, f"{selected['provider']}/{selected['id']}")
        return {"selected": selected, "session": session}

    def set_thinking_level(self, session_id: str, *, level: str) -> dict[str, object]:
        normalized = str(level or "").strip().lower()
        if normalized not in {"off", "minimal", "low", "medium", "high", "xhigh", "max"}:
            raise ValueError("unsupported Pi thinking level")
        self.ensure(session_id)
        result = self._require_client().send(
            "session.thinking.set",
            {"sessionId": session_id, "level": normalized},
        )
        effective = str(result.get("level") or normalized)
        self.sessions.set_thinking_level(session_id, effective)
        return {"thinkingLevel": effective}

    def tool_catalog(self, session_id: str) -> list[dict[str, object]]:
        session = dict(self.sessions.get(session_id))
        if self._tool_manifest_provider is None:
            return []
        return [dict(item) for item in self._tool_manifest_provider(session)]

    def abort(self, session_id: str) -> dict[str, object]:
        with self._lock:
            state = self._states.setdefault(session_id, _HostedSessionState())
            turn_id = state.turn_id
            if not turn_id:
                if state.prompt_admission_in_flight:
                    state.abort_pending_admission = True
                    state.prompt_dispatch_signal.set()
                    self.events.publish(
                        session_id,
                        "status_changed",
                        {
                            "status": "aborting",
                            "pendingAdmission": True,
                        },
                    )
                    return {
                        "schemaVersion": "rag-ime.pi-session-abort-receipt.v1",
                        "sessionId": session_id,
                        "turnId": "",
                        "pendingAdmission": True,
                        "cancelledDecisionIds": [],
                        "cancelledUIRequestIds": [],
                        "lifecycle": {
                            "schemaVersion": "pi.agent-abort-receipt.v1",
                            "scopeId": session_id,
                            "generation": 0,
                            "reason": "user_abort",
                            "cancelledContinuationIds": [],
                            "cancelledOperationIds": [],
                            "failedOperationIds": [],
                            "operations": [],
                            "pendingOperations": ["prompt_admission"],
                            "drained": False,
                            "idle": False,
                        },
                    }
                self.sessions.set_status(session_id, "idle")
                return {
                    "schemaVersion": "rag-ime.pi-session-abort-receipt.v1",
                    "sessionId": session_id,
                    "turnId": "",
                    "cancelledDecisionIds": [],
                    "cancelledUIRequestIds": [],
                    "lifecycle": {
                        "schemaVersion": "pi.agent-abort-receipt.v1",
                        "scopeId": "",
                        "generation": 0,
                        "reason": "user_abort",
                        "cancelledContinuationIds": [],
                        "cancelledOperationIds": [],
                        "failedOperationIds": [],
                        "operations": [],
                        "pendingOperations": [],
                        "drained": True,
                        "idle": True,
                    },
                }
            # Mark the exact turn before sending the RPC. The host is allowed
            # to emit agent_settled before the abort ACK reaches this thread.
            state.abort_requested_turn_id = turn_id
            if state.abort_timer is not None:
                state.abort_timer.cancel()
            timer = threading.Timer(
                1.0,
                self._abort_fallback_expired,
                args=(session_id, turn_id),
            )
            timer.daemon = True
            state.abort_timer = timer
            timer.start()
            # Publish the user-visible transition before waiting up to one
            # second for the Host ACK. Stop feedback must not depend on a
            # provider, Tool, or process that is precisely what we are
            # attempting to cancel.
            self.events.publish(
                session_id,
                "status_changed",
                {"status": "aborting"},
                turn_id=turn_id,
            )
        client = self._require_client()
        try:
            result = client.send(
                "session.abort",
                {"sessionId": session_id},
                timeout=1.0,
            )
        except Exception:
            with self._lock:
                state = self._states.get(session_id)
                if state is not None and state.abort_requested_turn_id == turn_id:
                    # Keep the exact-turn fence and let the already armed
                    # fallback retire the turn and request a governed host kill.
                    self.events.publish(
                        session_id,
                        "status_changed",
                        {"status": "aborting", "escalated": True},
                        turn_id=turn_id,
                    )
            raise
        lifecycle = result.get("lifecycle")
        lifecycle = lifecycle if isinstance(lifecycle, Mapping) else {}
        response_turn_id = str(result.get("turnId") or "")
        pending_operations = lifecycle.get("pendingOperations")
        host_already_idle = (
            not response_turn_id
            and lifecycle.get("schemaVersion") == "pi.agent-abort-receipt.v1"
            and lifecycle.get("idle") is True
            and lifecycle.get("drained") is True
            and isinstance(pending_operations, list)
            and not pending_operations
        )
        if (
            result.get("schemaVersion") != "rag-ime.pi-session-abort-receipt.v1"
            or result.get("sessionId") != session_id
            or not lifecycle
            or (response_turn_id != turn_id and not host_already_idle)
        ):
            raise PiRuntimeError("Pi Runtime Host returned an invalid Session abort receipt")
        if host_already_idle:
            # Pi owns the live Run. It can settle between PAW reading the local
            # turn fence and handling session.abort, in which case there is no
            # active Host turn left to echo. A typed, drained, idle receipt with
            # no pending operations is sufficient proof to retire only the
            # exact local turn; arbitrary empty or mismatched receipts remain
            # invalid and never reach this branch.
            normalized = dict(result)
            normalized["turnId"] = turn_id
            retired = False
            with self._lock:
                state = self._states.setdefault(session_id, _HostedSessionState())
                if state.turn_id == turn_id:
                    if state.abort_timer is not None:
                        state.abort_timer.cancel()
                        state.abort_timer = None
                    if state.settle_timer is not None:
                        state.settle_timer.cancel()
                        state.settle_timer = None
                    if len(state.retired_turn_ids) >= 64:
                        state.retired_turn_ids.pop()
                    state.retired_turn_ids.add(turn_id)
                    if len(self._retired_host_turns) >= 256:
                        self._retired_host_turns.pop()
                    self._retired_host_turns.add((session_id, turn_id))
                    state.turn_id = ""
                    state.client_message_id = ""
                    state.stream_pi_message_id = ""
                    state.tool_blocks.clear()
                    state.last_agent_messages = []
                    state.final_error = ""
                    state.had_tool_activity = False
                    state.settle_extension_failed = False
                    state.abort_requested_turn_id = ""
                    state.pending_approvals.clear()
                    state.pending_reviews.clear()
                    state.pending_ui_requests.clear()
                    self._status = "ready"
                    self._schedule_idle_locked()
                    retired = True
            if retired:
                self.sessions.set_status(
                    session_id,
                    "idle",
                    last_message_preview="已停止。",
                )
                self.events.publish(
                    session_id,
                    "turn_completed",
                    {
                        "status": "aborted",
                        "aborted": True,
                        "terminalEvent": "idle_abort_receipt",
                    },
                    turn_id=turn_id,
                )
            return normalized
        with self._lock:
            state = self._states.setdefault(session_id, _HostedSessionState())
            # The host can emit agent_settled before the abort ACK arrives.
            # Do not regress an already terminal turn back to "aborting".
            if state.turn_id != turn_id:
                return dict(result)
        return dict(result)

    def compact(self, session_id: str, instructions: str = "") -> dict[str, object]:
        self.ensure(session_id)
        result = self._require_client().send(
            "session.compact",
            {"sessionId": session_id, "instructions": str(instructions).strip()[:2000]},
            timeout=max(300.0, self.config.command_timeout_seconds),
        )
        checkpoint = self._observe_compaction(session_id, result, "manual")
        if checkpoint:
            result["memoryCheckpoint"] = checkpoint
        return result

    def has_pending_approval(self, session_id: str, approval_id: str) -> bool:
        with self._lock:
            return approval_id in self._states.get(session_id, _HostedSessionState()).pending_approvals

    def has_pending_review(self, session_id: str, run_id: str) -> bool:
        with self._lock:
            return run_id in self._states.get(session_id, _HostedSessionState()).pending_reviews

    def pending_ui_requests(self, session_id: str) -> list[dict[str, object]]:
        with self._lock:
            state = self._states.get(session_id)
            if state is None:
                return []
            return [
                {
                    **{
                        key: value
                        for key, value in request.items()
                        if not key.startswith("_")
                    },
                    "turnId": str(request.get("_turnId") or state.turn_id),
                    "createdAtMs": int(request.get("_createdAtMs") or 0),
                }
                for request in state.pending_ui_requests.values()
            ]

    def _expire_ui_request(self, session_id: str, request_id: str) -> None:
        try:
            self.resolve_ui_request(
                session_id,
                request_id,
                response={
                    "cancelled": True,
                    "resolutionSource": "timeout",
                },
            )
        except (PiRuntimeError, ValueError):
            return

    def resolve_review(self, session_id: str, run_id: str, *, reviewed: bool) -> None:
        with self._lock:
            state = self._states.get(session_id)
            request_id = state.pending_reviews.get(run_id) if state else None
            turn_id = state.turn_id if state else ""
        if not request_id:
            raise PiRuntimeError("review request is no longer pending")
        self._require_client().send(
            "review.resolve",
            {"sessionId": session_id, "runId": run_id, "reviewed": bool(reviewed)},
        )
        with self._lock:
            if state:
                state.pending_reviews.pop(run_id, None)
        self.events.publish(
            session_id,
            "approval_resolved",
            {
                "requestId": request_id,
                "runId": run_id,
                "state": "approved",
                "reviewState": "reviewed" if reviewed else "deferred",
            },
            turn_id=turn_id,
        )

    def resolve_approval(
        self,
        session_id: str,
        approval_id: str,
        *,
        approved: bool,
        resolution_state: str = "",
    ) -> None:
        with self._lock:
            state = self._states.get(session_id)
            request_id = state.pending_approvals.get(approval_id) if state else None
            turn_id = state.turn_id if state else ""
        approval = self.sessions.get_approval(approval_id)
        tool_call_id = str(approval.get("toolCallId") or "").strip()
        causal = approval.get("causalMetadata")
        if isinstance(causal, Mapping):
            turn_id = str(causal.get("turnId") or "").strip() or turn_id
        if not request_id:
            raise PiRuntimeError("approval request is no longer pending")
        self._require_client().send(
            "approval.resolve",
            {"sessionId": session_id, "approvalId": approval_id, "approved": bool(approved)},
        )
        with self._lock:
            if state:
                state.pending_approvals.pop(approval_id, None)
        self.events.publish(
            session_id,
            "approval_resolved",
            {
                "requestId": request_id,
                "approvalId": approval_id,
                "state": resolution_state or ("approved" if approved else "rejected"),
                **({"toolCallId": tool_call_id} if tool_call_id else {}),
            },
            turn_id=turn_id,
        )

    def resolve_ui_request(
        self,
        session_id: str,
        request_id: str,
        *,
        response: Mapping[str, object],
    ) -> dict[str, object]:
        normalized_request_id = str(request_id or "").strip()
        with self._lock:
            state = self._states.get(session_id)
            request = state.pending_ui_requests.get(normalized_request_id) if state else None
            review_run_id = (
                next(
                    (
                        run_id
                        for run_id, pending_id in state.pending_reviews.items()
                        if pending_id == normalized_request_id
                    ),
                    "",
                )
                if state
                else ""
            )
            if request is None and review_run_id:
                request = {
                    "requestId": normalized_request_id,
                    "method": "confirm",
                    "_turnId": state.turn_id if state else "",
                }
            if request is None or request.get("_resolving") is True:
                raise PiRuntimeError("UI request is no longer pending")
            request["_resolving"] = True
        method = str(request.get("method") or "")
        cancelled = response.get("cancelled") is True
        resolution_source = str(response.get("resolutionSource") or "").strip() or (
            "user_cancelled" if cancelled else "direct_user"
        )
        if resolution_source not in {
            "direct_user",
            "user_cancelled",
            "timeout",
            "runtime_cancelled",
        }:
            with self._lock:
                request.pop("_resolving", None)
            raise ValueError("unsupported UI response provenance")
        if resolution_source in {"timeout", "runtime_cancelled"} and not cancelled:
            with self._lock:
                request.pop("_resolving", None)
            raise ValueError("automatic UI resolution must be a cancellation")
        resolved: dict[str, object] = {"cancelled": True}
        if not cancelled:
            value = str(response.get("value") or "")
            if method == "confirm":
                confirmed = response.get("confirmed")
                if not isinstance(confirmed, bool):
                    confirmed = ui_confirmation_value(value)
                resolved = {"confirmed": confirmed}
            else:
                if request.get("requestKind") == "grouped_questions":
                    try:
                        value = canonical_grouped_answers(
                            value,
                            request.get("questions"),
                        )
                    except ValueError as exc:
                        with self._lock:
                            request.pop("_resolving", None)
                        raise PiRuntimeError(
                            "提交答案与当前问题或可选项不一致"
                        ) from exc
                elif method == "select":
                    options = [str(item) for item in request.get("options") or []]
                    if options and value not in options:
                        with self._lock:
                            request.pop("_resolving", None)
                        raise PiRuntimeError("UI response is not one of the offered options")
                resolved = {"value": value}
        try:
            result = self._require_client().send(
                "ui.resolve",
                {
                    "sessionId": session_id,
                    "requestId": normalized_request_id,
                    "response": resolved,
                },
            )
        except Exception:
            with self._lock:
                request.pop("_resolving", None)
            raise
        timeout_timer = request.get("_timeoutTimer")
        if isinstance(timeout_timer, threading.Timer):
            timeout_timer.cancel()
        turn_id = str(request.get("_turnId") or (state.turn_id if state else ""))
        with self._lock:
            if state:
                state.pending_ui_requests.pop(normalized_request_id, None)
                if review_run_id:
                    state.pending_reviews.pop(review_run_id, None)
        self.events.publish(
            session_id,
            "user_input_required",
            {
                "requestId": normalized_request_id,
                "method": method,
                "resolutionState": "cancelled" if cancelled else "resolved",
                "resolutionSource": resolution_source,
            },
            turn_id=turn_id,
        )
        return {
            "requestId": normalized_request_id,
            "resolved": True,
            "method": method,
            "resolutionState": "cancelled" if cancelled else "resolved",
            "resolutionSource": resolution_source,
            "host": dict(result),
        }

    def plugin_list(self) -> list[dict[str, object]]:
        return [dict(value) for value in self._require_host_result("plugins.list").get("plugins") or [] if isinstance(value, Mapping)]

    def plugin_create_package(self, payload: Mapping[str, object]) -> dict[str, object]:
        return self._require_host_result("plugins.package.create", payload)

    def plugin_validate(self, source_path: str) -> dict[str, object]:
        return self._require_host_result("plugins.validate", {"sourcePath": source_path})

    def plugin_prepare_package(self, source: str) -> dict[str, object]:
        return self._require_host_result(
            "plugins.package.prepare", {"source": source}
        )

    def plugin_install(self, payload: Mapping[str, object]) -> dict[str, object]:
        return self._require_host_result(
            "plugins.install",
            {**dict(payload), "approvalToken": self.config.plugin_approval_token},
        )

    def plugin_enable(
        self,
        plugin_id: str,
        *,
        enabled: bool,
        expected_active_digest: str,
        expected_enabled: bool,
    ) -> dict[str, object]:
        return self._require_host_result(
            "plugins.enable" if enabled else "plugins.disable",
            {
                "pluginId": plugin_id,
                "approvalToken": self.config.plugin_approval_token,
                "expectedActiveDigest": expected_active_digest,
                "expectedEnabled": expected_enabled,
            },
        )

    def plugin_rollback(
        self,
        plugin_id: str,
        *,
        expected_active_digest: str,
        target_digest: str,
    ) -> dict[str, object]:
        return self._require_host_result(
            "plugins.rollback",
            {
                "pluginId": plugin_id,
                "expectedActiveDigest": expected_active_digest,
                "targetDigest": target_digest,
                "approvalToken": self.config.plugin_approval_token,
            },
        )

    def _require_host_result(
        self,
        method: str,
        params: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        with self._lifecycle_lock:
            return self._host().send(method, params, timeout=max(30.0, self.config.command_timeout_seconds))

    def stop(self) -> None:
        with self._lifecycle_lock:
            with self._lock:
                self._cancel_idle_locked()
                client = self._client
                self._client = None
                self._intentional_stop = True
                session_ids = tuple(self._open_sessions)
                for state in self._states.values():
                    if state.abort_timer is not None:
                        state.abort_timer.cancel()
                    if state.settle_timer is not None:
                        state.settle_timer.cancel()
                self._open_sessions.clear()
                self._active_completion_ids.clear()
                self._completion_sinks.clear()
                self._states.clear()
                self._status = "stopped" if self.config.enabled else "disabled"
            if client is not None:
                client.stop()
            for session_id in session_ids:
                try:
                    self.sessions.set_status(session_id, "idle")
                except KeyError:
                    pass

    def close_session(self, session_id: str) -> bool:
        """Retire one idle hosted Session without restarting the shared Host."""

        normalized = str(session_id or "").strip()
        if not normalized:
            raise ValueError("session_id is required")
        with self._lifecycle_lock:
            with self._lock:
                state = self._states.get(normalized)
                if state is not None and state.turn_id:
                    raise PiRuntimeError(
                        "Session must settle before its runtime policy changes"
                    )
                client = self._client
                opened = normalized in self._open_sessions
            if opened and client is not None and client.running:
                response = client.send(
                    "session.close",
                    {"sessionId": normalized},
                )
                if response.get("closed") is not True:
                    raise PiRuntimeError(
                        "managed Pi Host did not close the requested Session"
                    )
            with self._lock:
                self._open_sessions.discard(normalized)
                retired = self._states.pop(normalized, None)
                if retired is not None:
                    if retired.abort_timer is not None:
                        retired.abort_timer.cancel()
                    if retired.settle_timer is not None:
                        retired.settle_timer.cancel()
                self._schedule_idle_locked()
            try:
                self.sessions.set_status(normalized, "idle")
            except KeyError:
                pass
            return opened

    def _require_client(self) -> PiRuntimeHostClient:
        with self._lock:
            client = self._client
        if client is None or not client.running:
            raise PiRuntimeError("Pi Runtime Host is not running")
        return client

    def _handle_host_event(self, envelope: dict[str, object]) -> None:
        if envelope.get("protocolVersion") != _PROTOCOL_VERSION or envelope.get("event") not in {
            "agent.event",
            "runtime.notice",
        }:
            return
        raw = dict(as_mapping(envelope.get("payload")))
        if envelope.get("event") == "runtime.notice" and str(raw.get("type") or "") == "completion_text_delta":
            request_id = str(raw.get("requestId") or "")
            delta = str(raw.get("delta") or "")
            with self._lock:
                sink = self._completion_sinks.get(request_id)
            if sink is not None and delta:
                try:
                    sink(delta)
                except Exception:
                    pass
            return
        session_id = str(envelope.get("sessionId") or "")
        if not session_id:
            return
        turn_id = str(envelope.get("turnId") or "")
        client_message_id = str(envelope.get("clientMessageId") or "")
        event_type = str(raw.get("type") or "")
        with self._lock:
            if turn_id and (session_id, turn_id) in self._retired_host_turns:
                return
            state = self._states.setdefault(session_id, _HostedSessionState())
            if turn_id and turn_id in state.retired_turn_ids:
                return
            if turn_id:
                state.turn_id = turn_id
            if client_message_id:
                state.client_message_id = client_message_id
        if event_type == "message_update":
            update = as_mapping(raw.get("assistantMessageEvent"))
            update_type = str(update.get("type") or "")
            if update_type == "text_delta":
                raw_message = as_mapping(raw.get("message"))
                streamed_message_id = pi_message_id(raw_message, turn_id)
                with self._lock:
                    replace_block = (
                        streamed_message_id != state.stream_pi_message_id
                    )
                    state.stream_pi_message_id = streamed_message_id
                self.events.publish(
                    session_id,
                    "text_delta",
                    {
                        "messageId": f"{turn_id}:assistant",
                        "blockId": f"{turn_id}:assistant:text",
                        "contentIndex": as_integer(update.get("contentIndex")),
                        "delta": str(update.get("delta") or ""),
                        "replaceBlock": replace_block,
                    },
                    turn_id=turn_id,
                )
            elif update_type == "thinking_start":
                self.events.publish(
                    session_id,
                    "status_changed",
                    {
                        "status": "analyzing",
                        "phase": "reasoning",
                        "summary": "正在等待 Provider 的公开思考摘要",
                    },
                    turn_id=turn_id,
                )
            elif update_type == "thinking_end":
                raw_message = as_mapping(raw.get("message"))
                summaries = public_reasoning_summaries(raw_message)
                if summaries:
                    message_id = pi_message_id(raw_message, turn_id)
                    content_index = as_integer(update.get("contentIndex"))
                    reasoning_id = f"reasoning:{message_id}:{content_index}"
                    self.events.publish(
                        session_id,
                        "reasoning_summary",
                        {
                            "requestId": reasoning_id,
                            "sourceMessageId": message_id,
                            "summary": summaries[-1],
                            "items": summaries,
                            "source": "provider_reasoning_summary",
                            "state": "completed",
                        },
                        turn_id=turn_id,
                    )
            return
        if event_type == "message_end":
            raw_message = as_mapping(raw.get("message"))
            role = str(raw_message.get("role") or "assistant").lower()
            if role == "user" or not pi_message_is_public(raw_message):
                return
            trusted_blocks = raw.get("agentBlocks")
            if role == "assistant":
                trusted_blocks = state.tool_blocks.blocks_for_message(
                    raw_message,
                    trusted_blocks,
                )
            message = pi_message_payload(
                raw_message,
                session_id=session_id,
                turn_id=turn_id,
                media_resolver=self._media_resolver,
                message_id=f"{turn_id}:assistant" if role == "assistant" else None,
                trusted_blocks=trusted_blocks,
            )
            if not pi_message_completes_public_turn(raw_message):
                # Some Providers return a complete public explanation together
                # with another Tool call but emit no text_delta events. Hiding
                # that mixed message leaves the UI blank until Stop forces a
                # snapshot. Project its public text into one replaceable live
                # bubble; a later mixed/final message updates the same bubble.
                progress_text = "\n\n".join(
                    str(as_mapping(block.get("data")).get("text") or "").strip()
                    for block in message.to_payload().get("blocks") or []
                    if isinstance(block, Mapping)
                    and str(block.get("type") or "") == "text"
                    and str(as_mapping(block.get("data")).get("text") or "").strip()
                )
                if progress_text:
                    self.events.publish(
                        session_id,
                        "text_delta",
                        {
                            "messageId": f"{turn_id}:assistant",
                            "blockId": f"{turn_id}:assistant:text",
                            "delta": progress_text,
                            "replaceContent": True,
                        },
                        turn_id=turn_id,
                    )
                return
            self.events.publish(
                session_id,
                "message_completed",
                {
                    "message": message.to_payload(),
                    "usage": public_usage(raw.get("message")),
                    **public_usage_evidence(raw_message),
                    "telemetry": dict(as_mapping(raw.get("telemetry"))),
                },
                turn_id=turn_id,
            )
            return
        if event_type == "queue_update":
            self.events.publish(
                session_id,
                "message_queue_updated",
                {
                    "steering": public_message_queue(raw.get("steering")),
                    "followUp": public_message_queue(raw.get("followUp")),
                },
                turn_id=turn_id,
            )
            return
        if event_type == "compaction_start":
            self.events.publish(
                session_id,
                "compaction_started",
                {
                    "reason": str(raw.get("reason") or "threshold"),
                    "telemetry": dict(as_mapping(raw.get("telemetry"))),
                },
                turn_id=turn_id,
            )
            return
        if event_type == "compaction_end":
            result = as_mapping(raw.get("result"))
            payload: dict[str, object] = {
                "reason": str(raw.get("reason") or "threshold"),
                "aborted": bool(raw.get("aborted")),
                "willRetry": bool(raw.get("willRetry")),
                "tokensBefore": as_integer(result.get("tokensBefore")),
                "estimatedTokensAfter": as_integer(result.get("estimatedTokensAfter")),
                "telemetry": dict(as_mapping(raw.get("telemetry"))),
            }
            if raw.get("errorMessage"):
                payload["error"] = redact_runtime_text(str(raw.get("errorMessage")))
            self.events.publish(
                session_id,
                "compaction_completed",
                payload,
                turn_id=turn_id,
            )
            self._observe_compaction(
                session_id,
                dict(result) if result else dict(raw),
                str(raw.get("trigger") or raw.get("reason") or "").strip() or "automatic",
            )
            return
        if event_type in {"auto_retry_start", "auto_retry_end"}:
            self.events.publish(
                session_id,
                "status_changed",
                provider_retry_status(
                    raw,
                    started=event_type == "auto_retry_start",
                ),
                turn_id=turn_id,
            )
            return
        if event_type in {"tool_execution_start", "tool_execution_update", "tool_execution_end"}:
            with self._lock:
                state.had_tool_activity = True
            mapped_type = {
                "tool_execution_start": "tool_started",
                "tool_execution_update": "tool_progress",
                "tool_execution_end": "tool_finished",
            }[event_type]
            raw_args = as_mapping(raw.get("args"))
            tool_name = str(raw.get("toolName") or "")
            payload: dict[str, object] = {
                "toolCallId": str(raw.get("toolCallId") or ""),
                "toolName": tool_name,
                "args": redact_mapping(raw_args),
                "isError": bool(raw.get("isError")),
            }
            result_key = "partialResult" if event_type == "tool_execution_update" else "result"
            raw_result = raw.get(result_key)
            result_is_error = runtime_tool_result_is_error(
                tool_name,
                raw_result,
                reported_is_error=bool(raw.get("isError")),
            )
            payload["isError"] = result_is_error
            public_result = public_code_tool_activity(
                tool_name,
                raw_args,
                raw_result,
            )
            if (
                result_is_error
                and public_result.get("outputPreview")
            ):
                public_result["error"] = public_result["outputPreview"]
            if public_result:
                payload["publicResult"] = public_result
            if raw_result is not None:
                if event_type == "tool_execution_end":
                    payload[result_key] = inspectable_tool_result(raw_result)
                elif not public_result:
                    payload[result_key] = redact_mapping(as_mapping(raw_result))
            if event_type == "tool_execution_end" and not result_is_error:
                captured = state.tool_blocks.capture(
                    raw.get("result"),
                    source_ref=(
                        f"{session_id}:{turn_id}:"
                        f"{str(raw.get('toolCallId') or '')}"
                    ),
                )
                if captured:
                    payload["agentBlocks"] = [dict(block) for block in captured]
            self.events.publish(session_id, mapped_type, payload, turn_id=turn_id)
            return
        if event_type == "extension_ui_request":
            self._handle_ui_request(session_id, turn_id, raw)
            return
        if event_type == "tool_loop_no_progress":
            message = redact_runtime_text(
                str(raw.get("message") or "Tool Loop 未产生新进展，已停止。")
            )
            with self._lock:
                state.final_error = message
            self.events.publish(
                session_id,
                "status_changed",
                {
                    "status": "working",
                    "phase": "tool_loop_no_progress",
                    "activityState": "failed",
                    "message": message,
                    "reason": str(raw.get("reason") or "no_progress"),
                    "consecutiveAllErrorTurns": as_integer(
                        raw.get("consecutiveAllErrorTurns")
                    ),
                    "repeatedFailureSignature": as_integer(
                        raw.get("repeatedFailureSignature")
                    ),
                    "toolNames": [
                        redact_runtime_text(str(name))
                        for name in (
                            raw.get("toolNames")
                            if isinstance(raw.get("toolNames"), list)
                            else []
                        )
                        if isinstance(name, str)
                    ][:16],
                },
                turn_id=turn_id,
            )
            return
        if event_type == "agent_end":
            messages = raw.get("messages") if isinstance(raw.get("messages"), list) else []
            with self._lock:
                state.last_agent_messages = list(messages)
                state.final_error = (
                    ""
                    if raw.get("willRetry") is True
                    else last_assistant_error(messages) or state.final_error
                )
                # agent_end is normally followed by agent_settled. Probe the
                # lightweight Host control state after a grace period so a
                # lost terminal event cannot leave a Tool-complete turn busy.
                self._schedule_settle_probe_locked(
                    state,
                    session_id,
                    turn_id,
                    delay_seconds=1.0,
                )
            # agent_end is not terminal: retries, follow-ups, and extension work can continue.
            return
        if event_type == "agent_settle_failed":
            failed_settlement = _failed_settlement_receipt(
                raw,
                allow_aborted=True,
            )
            settle_error = redact_runtime_text(
                str(raw.get("error") or "Pi settlement hook failed")
            )
            recovery_turn_id = turn_id
            with self._lock:
                state = self._states.get(session_id)
                if state is not None and state.turn_id:
                    recovery_turn_id = state.turn_id
            if (
                recovery_turn_id
                and failed_settlement is not None
                and failed_settlement[0]
            ):
                self._turn_failed_once(
                    session_id,
                    recovery_turn_id,
                    PiRuntimeError(failed_settlement[1]),
                )
                return
            with self._lock:
                state = self._states.get(session_id)
                if state is not None and state.turn_id:
                    state.final_error = settle_error
                    state.settle_extension_failed = True
                    self._schedule_settle_probe_locked(
                        state,
                        session_id,
                        state.turn_id,
                        delay_seconds=0.1,
                    )
            self.events.publish(
                session_id,
                "status_changed",
                {
                    "status": "working" if recovery_turn_id else "ready",
                    "phase": "settlement_warning",
                    "warning": settle_error,
                },
                turn_id=recovery_turn_id,
            )
            return

        if event_type == "agent_settled":
            failed_settlement = _failed_settlement_receipt(
                raw,
                allow_aborted=False,
            )
            if failed_settlement is not None:
                terminal_turn_id = turn_id or state.turn_id
                if failed_settlement[0] and terminal_turn_id:
                    self._turn_failed_once(
                        session_id,
                        terminal_turn_id,
                        PiRuntimeError(failed_settlement[1]),
                    )
                    return
                # A failed receipt with pending work is not a completion. Keep
                # the existing bounded control-state reconciliation path.
                with self._lock:
                    if state.turn_id == terminal_turn_id and terminal_turn_id:
                        state.final_error = failed_settlement[1]
                        state.settle_extension_failed = True
                        self._schedule_settle_probe_locked(
                            state,
                            session_id,
                            terminal_turn_id,
                            delay_seconds=0.1,
                        )
                return
            with self._lock:
                if state.turn_id != turn_id:
                    return
                messages = list(state.last_agent_messages)
                final_error = state.final_error
                aborted = state.abort_requested_turn_id == turn_id
                if state.abort_timer is not None:
                    state.abort_timer.cancel()
                    state.abort_timer = None
                if state.settle_timer is not None:
                    state.settle_timer.cancel()
                    state.settle_timer = None
                if aborted or not final_error:
                    if aborted:
                        if len(state.retired_turn_ids) >= 64:
                            state.retired_turn_ids.pop()
                        state.retired_turn_ids.add(turn_id)
                    state.turn_id = ""
                    state.client_message_id = ""
                    state.stream_pi_message_id = ""
                    state.tool_blocks.clear()
                    state.last_agent_messages = []
                    state.final_error = ""
                    state.had_tool_activity = False
                    state.settle_extension_failed = False
                    state.abort_requested_turn_id = ""
                    state.pending_approvals.clear()
                    state.pending_reviews.clear()
                    state.pending_ui_requests.clear()
                    self._status = "ready"
                    self._schedule_idle_locked()
            if aborted:
                self.sessions.set_status(
                    session_id,
                    "idle",
                    last_message_preview="已停止。",
                )
                self.events.publish(
                    session_id,
                    "turn_completed",
                    {"status": "aborted", "aborted": True, "terminalEvent": "agent_settled"},
                    turn_id=turn_id,
                )
                return
            if final_error:
                self._turn_failed(session_id, turn_id, PiRuntimeError(final_error))
                return
            public_message_count = sum(
                isinstance(message, Mapping)
                and pi_message_is_public(message)
                for message in messages
            )
            self.sessions.set_status(
                session_id,
                "idle",
                message_count=public_message_count,
                last_message_preview=last_assistant_preview(messages),
            )
            self.events.publish(
                session_id,
                "turn_completed",
                {
                    "messageCount": public_message_count,
                    "terminalEvent": "agent_settled",
                },
                turn_id=turn_id,
            )
            return
        if event_type == "extension_error":
            extension_event = str(raw.get("event") or "")
            if extension_event == "agent_settled":
                # Pi is already idle when agent_settled extensions run. If one
                # fails, the Host can retain only its correlation identity and
                # omit the public terminal event. Reconcile that exact turn
                # through control state instead of leaving it permanently busy.
                with self._lock:
                    state = self._states.get(session_id)
                    if state is not None and state.turn_id:
                        state.settle_extension_failed = True
                        self._schedule_settle_probe_locked(
                            state,
                            session_id,
                            state.turn_id,
                            delay_seconds=0.1,
                        )
            self.events.publish(
                session_id,
                "status_changed",
                {
                    "status": "working" if turn_id else "ready",
                    "phase": "extension_warning",
                    "extensionEvent": extension_event,
                    "warning": redact_runtime_text(
                        str(raw.get("error") or "Pi extension failed")
                    ),
                },
                turn_id=turn_id,
            )
            return

    def _observe_compaction(
        self,
        session_id: str,
        result: Mapping[str, object],
        trigger: str,
    ) -> dict[str, object]:
        if self._compaction_observer is None:
            return {}
        try:
            checkpoint = self._compaction_observer(session_id, result, trigger)
        except Exception as exc:
            return {
                "schemaVersion": "rag-ime.agent-memory-checkpoint.v1",
                "ok": False,
                "stored": False,
                "status": "checkpoint_failed",
                "error": redact_runtime_text(str(exc)),
            }
        return dict(checkpoint or {})

    def _handle_ui_request(self, session_id: str, turn_id: str, raw: Mapping[str, object]) -> None:
        method = str(raw.get("method") or "")
        request_id = str(raw.get("id") or "")
        title = str(raw.get("title") or "")
        with self._lock:
            state = self._states.setdefault(session_id, _HostedSessionState())
        if method == "confirm" and title.startswith(APPROVAL_TITLE_PREFIX):
            approval_id = title[len(APPROVAL_TITLE_PREFIX) :].strip()
            try:
                approval = self.sessions.get_approval(approval_id)
            except (KeyError, ValueError):
                self._require_client().send(
                    "approval.resolve",
                    {"sessionId": session_id, "approvalId": approval_id, "approved": False},
                )
                return
            if approval.get("sessionId") != session_id or approval.get("state") != "pending":
                self._require_client().send(
                    "approval.resolve",
                    {"sessionId": session_id, "approvalId": approval_id, "approved": False},
                )
                return
            with self._lock:
                state.pending_approvals[approval_id] = request_id
            self.events.publish(
                session_id,
                "approval_required",
                {**approval, "requestId": request_id},
                turn_id=turn_id,
            )
            return
        if method == "confirm" and title.startswith(REVIEW_TITLE_PREFIX):
            run_id = title[len(REVIEW_TITLE_PREFIX) :].strip()
            if not run_id:
                return
            with self._lock:
                state.pending_reviews[run_id] = request_id
            self.events.publish(
                session_id,
                "user_input_required",
                {
                    "requestId": request_id,
                    "requestKind": "memory_review",
                    "method": "confirm",
                    "runId": run_id,
                    "title": "审阅记忆草案",
                    "message": "记忆草案已准备好，请逐项审阅后继续本轮。",
                },
                turn_id=turn_id,
            )
            return
        if method == "editor" and title.startswith(GROUPED_QUESTIONS_TITLE_PREFIX):
            try:
                questions = grouped_questions_from_wire(raw.get("prefill"))
            except ValueError:
                self._require_client().send(
                    "ui.resolve",
                    {
                        "sessionId": session_id,
                        "requestId": request_id,
                        "response": {"cancelled": True},
                    },
                )
                return
            safe = {
                "requestId": request_id,
                "requestKind": "grouped_questions",
                "schemaVersion": GROUPED_QUESTIONS_SCHEMA_VERSION,
                "groupId": request_id,
                "method": "editor",
                "title": "需要你做几个选择",
                "message": "请把相关问题全部选完后一次提交；如果不想继续，可以取消本次提问。",
                "questions": questions,
            }
            with self._lock:
                state.pending_ui_requests[request_id] = {
                    **safe,
                    "_turnId": turn_id,
                    "_createdAtMs": int(time.time() * 1000),
                }
            self.events.publish(
                session_id,
                "user_input_required",
                safe,
                turn_id=turn_id,
            )
            return
        if method in {"select", "confirm", "input", "editor"}:
            safe: dict[str, object] = {
                "requestId": request_id,
                "method": method,
                "title": title[:160],
                "message": str(raw.get("message") or "")[:500],
            }
            if isinstance(raw.get("options"), list):
                safe["options"] = [
                    str(value)[:240] for value in raw["options"][:100]
                ]
            for field, maximum in (
                ("placeholder", 500),
                ("prefill", 4_000),
                ("defaultValue", 4_000),
            ):
                if raw.get(field) is not None:
                    safe[field] = str(raw.get(field) or "")[:maximum]
            if raw.get("timeout") is not None:
                try:
                    safe["timeout"] = max(0, int(raw["timeout"]))
                except (TypeError, ValueError):
                    pass
            timeout_timer: threading.Timer | None = None
            stored_request = {
                **safe,
                "_turnId": turn_id,
                "_createdAtMs": int(time.time() * 1000),
            }
            timeout_ms = int(safe.get("timeout") or 0)
            if timeout_ms > 0:
                timeout_timer = threading.Timer(
                    timeout_ms / 1000,
                    self._expire_ui_request,
                    args=(session_id, request_id),
                )
                timeout_timer.daemon = True
                stored_request["_timeoutTimer"] = timeout_timer
            with self._lock:
                state.pending_ui_requests[request_id] = stored_request
            self.events.publish(
                session_id,
                "user_input_required",
                safe,
                turn_id=turn_id,
            )
            if timeout_timer is not None:
                timeout_timer.start()

    def _schedule_settle_probe_locked(
        self,
        state: _HostedSessionState,
        session_id: str,
        turn_id: str,
        *,
        delay_seconds: float,
    ) -> None:
        if state.settle_timer is not None:
            state.settle_timer.cancel()
        settle_timer = threading.Timer(
            delay_seconds,
            self._settle_fallback_probe,
            args=(session_id, turn_id),
        )
        settle_timer.daemon = True
        state.settle_timer = settle_timer
        settle_timer.start()

    def _settle_fallback_probe(self, session_id: str, turn_id: str) -> None:
        """Retire a turn only when the Host confirms it has no active work."""

        with self._lock:
            state = self._states.get(session_id)
            if state is None or state.turn_id != turn_id:
                return
            state.settle_timer = None
            client = self._client
        if client is None or not client.running:
            return
        try:
            control = client.send(
                "session.control_state",
                {"sessionId": session_id},
                timeout=min(
                    2.0,
                    max(1.0, self.config.command_timeout_seconds),
                ),
            )
        except Exception:
            # This is a recovery probe, not the owner of Host lifecycle. A
            # later Stop or Host-exit path remains authoritative on failure.
            return
        active_turn_value = control.get("activeTurn")
        active_turn = as_mapping(active_turn_value)
        with self._lock:
            state = self._states.get(session_id)
            settle_extension_failed = bool(
                state is not None
                and state.turn_id == turn_id
                and state.settle_extension_failed
            )
        if (
            control.get("isIdle") is not True
            or "activeTurn" not in control
            or (
                active_turn_value
                and (
                    not settle_extension_failed
                    or str(active_turn.get("turnId") or "") != turn_id
                )
            )
        ):
            return

        with self._lock:
            state = self._states.get(session_id)
            if state is None or state.turn_id != turn_id:
                return
            messages = list(state.last_agent_messages)
            final_error = state.final_error
            had_tool_activity = state.had_tool_activity
            aborted = state.abort_requested_turn_id == turn_id
            if state.abort_timer is not None:
                state.abort_timer.cancel()
                state.abort_timer = None
            if len(state.retired_turn_ids) >= 64:
                state.retired_turn_ids.pop()
            state.retired_turn_ids.add(turn_id)
            if len(self._retired_host_turns) >= 256:
                self._retired_host_turns.pop()
            self._retired_host_turns.add((session_id, turn_id))
            state.turn_id = ""
            state.client_message_id = ""
            state.stream_pi_message_id = ""
            state.tool_blocks.clear()
            state.last_agent_messages = []
            state.final_error = ""
            state.had_tool_activity = False
            state.settle_extension_failed = False
            state.abort_requested_turn_id = ""
            state.pending_approvals.clear()
            state.pending_reviews.clear()
            state.pending_ui_requests.clear()
            self._status = "ready"
            self._schedule_idle_locked()

        if final_error and not aborted:
            message = redact_runtime_text(final_error)
            classification = classify_runtime_failure(
                final_error,
                had_tool_activity=had_tool_activity,
            )
            self.sessions.set_status(
                session_id,
                "faulted",
                last_message_preview=message,
            )
            self.events.publish(
                session_id,
                "turn_failed",
                {
                    "error": message,
                    **classification.event_payload(),
                    "terminalEvent": "idle_control_reconciliation",
                },
                turn_id=turn_id,
            )
            return
        public_message_count = sum(
            isinstance(message, Mapping) and pi_message_is_public(message)
            for message in messages
        )
        self.sessions.set_status(
            session_id,
            "idle",
            message_count=public_message_count,
            last_message_preview=(
                "已停止。"
                if aborted
                else last_assistant_preview(messages)
            ),
        )
        self.events.publish(
            session_id,
            "turn_completed",
            {
                "status": "aborted" if aborted else "completed",
                "aborted": aborted,
                "messageCount": public_message_count,
                "terminalEvent": "idle_control_reconciliation",
            },
            turn_id=turn_id,
        )

    def _turn_failed_once(
        self,
        session_id: str,
        turn_id: str,
        error: BaseException,
    ) -> bool:
        """Project one exact terminal failure and ignore receipt replays."""

        with self._lock:
            state = self._states.setdefault(session_id, _HostedSessionState())
            if (
                (session_id, turn_id) in self._retired_host_turns
                or turn_id in state.retired_turn_ids
            ):
                return False
            if len(state.retired_turn_ids) >= 64:
                state.retired_turn_ids.pop()
            state.retired_turn_ids.add(turn_id)
            if len(self._retired_host_turns) >= 256:
                self._retired_host_turns.pop()
            self._retired_host_turns.add((session_id, turn_id))
        self._turn_failed(session_id, turn_id, error)
        return True

    def _turn_failed(self, session_id: str, turn_id: str, error: BaseException) -> None:
        message = redact_runtime_text(str(error))
        with self._lock:
            state = self._states.setdefault(session_id, _HostedSessionState())
            aborted = bool(turn_id and state.abort_requested_turn_id == turn_id)
            classification = classify_runtime_failure(
                error,
                had_tool_activity=state.had_tool_activity,
            )
            if state.abort_timer is not None:
                state.abort_timer.cancel()
                state.abort_timer = None
            if state.settle_timer is not None:
                state.settle_timer.cancel()
                state.settle_timer = None
            state.turn_id = ""
            state.client_message_id = ""
            state.stream_pi_message_id = ""
            state.tool_blocks.clear()
            state.last_agent_messages = []
            state.final_error = ""
            state.had_tool_activity = False
            state.settle_extension_failed = False
            state.abort_requested_turn_id = ""
            state.pending_approvals.clear()
            state.pending_reviews.clear()
            state.pending_ui_requests.clear()
            if not aborted:
                self._last_error = message
            self._status = "ready" if self._client is not None and self._client.running else "faulted"
            self._schedule_idle_locked()
        if aborted:
            # A cancelled Provider request may report a transport error after
            # Stop fenced this exact turn. The user action owns the terminal
            # meaning; late cancellation noise must not become a model error.
            self.sessions.set_status(
                session_id,
                "idle",
                last_message_preview="已停止。",
            )
            self.events.publish(
                session_id,
                "turn_completed",
                {
                    "status": "aborted",
                    "aborted": True,
                    "terminalEvent": "abort_failure_race",
                },
                turn_id=turn_id,
            )
            return
        self.sessions.set_status(session_id, "faulted", last_message_preview=message)
        self.events.publish(
            session_id,
            "turn_failed",
            {
                "error": message,
                **classification.event_payload(),
            },
            turn_id=turn_id,
        )

    def _handle_host_exit(self, exit_code: int | None, error: str) -> None:
        with self._lock:
            if self._intentional_stop:
                return
            message = redact_runtime_text(error or f"Pi Runtime Host exited with code {exit_code}")
            active = [(session_id, state.turn_id) for session_id, state in self._states.items() if state.turn_id]
            for state in self._states.values():
                if state.abort_timer is not None:
                    state.abort_timer.cancel()
                if state.settle_timer is not None:
                    state.settle_timer.cancel()
            self._client = None
            self._open_sessions.clear()
            self._states.clear()
            self._status = "faulted"
            self._last_error = message
        for session_id, turn_id in active:
            self.sessions.set_status(session_id, "faulted", last_message_preview=message)
            self.events.publish(
                session_id,
                "turn_failed",
                {
                    "error": message,
                    "failureKind": "runtime_host_exit",
                    "exitCode": exit_code,
                },
                turn_id=turn_id,
            )

    def _abort_fallback_expired(self, session_id: str, turn_id: str) -> None:
        # session.abort is an ACK, not a terminal event. If a host/extension
        # never emits agent_settled, retire that exact turn locally after a
        # short grace period. Late events for it are ignored, so they cannot
        # close a newer turn in the same hosted Session.
        with self._lock:
            state = self._states.get(session_id)
            if state is None or state.turn_id != turn_id:
                return
            state.abort_timer = None
            client = self._client
        if client is None or not client.running:
            return
        with self._lock:
            state = self._states.get(session_id)
            if state is not None and state.turn_id == turn_id:
                if state.settle_timer is not None:
                    state.settle_timer.cancel()
                    state.settle_timer = None
                if len(state.retired_turn_ids) >= 64:
                    state.retired_turn_ids.pop()
                state.retired_turn_ids.add(turn_id)
                if len(self._retired_host_turns) >= 256:
                    self._retired_host_turns.pop()
                self._retired_host_turns.add((session_id, turn_id))
                state.turn_id = ""
                state.client_message_id = ""
                state.stream_pi_message_id = ""
                state.tool_blocks.clear()
                state.last_agent_messages = []
                state.final_error = ""
                state.abort_requested_turn_id = ""
                state.pending_approvals.clear()
                state.pending_reviews.clear()
                state.pending_ui_requests.clear()
        self.sessions.set_status(
            session_id,
            "idle",
            last_message_preview="已停止。",
        )
        self.events.publish(
            session_id,
            "turn_completed",
            {"status": "aborted", "aborted": True, "terminalEvent": "abort_timeout_kill"},
            turn_id=turn_id,
        )
        receipt = self._kill_gate.request_kill(
            client.host_identity,
            request_kind="cancel_timeout",
            requested_by=f"session:{session_id}",
            reason=f"session.abort did not settle turn {turn_id}",
            now_ms=int(time.time() * 1000),
        )
        with self._lock:
            self._last_kill_receipt = dict(receipt)
            if self._status != "faulted":
                self._status = "stopping"
        self.events.publish(
            session_id,
            "status_changed",
            {
                # The Session turn is already durably terminal above. The
                # Runtime Host process may still be stopping, but projecting
                # that process state as Session "aborting" would reopen the
                # completed turn in the frontend reducer and recreate the
                # permanent busy/unstoppable UI this fallback exists to fix.
                "status": "idle",
                "runtimeStatus": "stopping",
                "escalated": True,
                "killReceiptId": receipt["killReceiptId"],
                "pendingTargets": receipt["pendingTargets"],
            },
            turn_id=turn_id,
        )

    def _schedule_idle_locked(self) -> None:
        self._cancel_idle_locked()
        if (
            self.config.idle_timeout_seconds <= 0
            or self._active_completion_ids
            or any(state.turn_id for state in self._states.values())
        ):
            return
        timer = threading.Timer(self.config.idle_timeout_seconds, self.stop)
        timer.daemon = True
        self._idle_timer = timer
        timer.start()

    def _cancel_idle_locked(self) -> None:
        timer = self._idle_timer
        self._idle_timer = None
        if timer is not None:
            timer.cancel()


def _pi_durable_branch_messages(
    raw_entries: list[object],
    *,
    leaf_id: str = "",
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Return ordered message values from Pi's selected durable branch.

    Modern Pi snapshots expose the complete append-only entry tree alongside
    a compacted Provider message window.  Parent links and ``leafId`` select
    one branch.  Older test/runtime payloads were flat, so they retain their
    append order instead of being reduced to the last entry.
    """

    entries = [
        dict(value)
        for value in raw_entries
        if isinstance(value, Mapping)
    ]
    if not entries:
        return [], []
    by_id = {
        str(entry.get("id") or ""): entry
        for entry in entries
        if str(entry.get("id") or "")
    }
    has_parent_links = any(
        str(entry.get("parentId") or "")
        for entry in entries
    )
    selected_entries = entries
    selected_leaf = str(leaf_id or "").strip()
    if has_parent_links:
        if selected_leaf not in by_id:
            selected_leaf = next(
                (
                    str(entry.get("id") or "")
                    for entry in reversed(entries)
                    if str(entry.get("id") or "")
                ),
                "",
            )
        branch: list[dict[str, object]] = []
        visited: set[str] = set()
        cursor = selected_leaf
        while cursor and cursor not in visited:
            visited.add(cursor)
            entry = by_id.get(cursor)
            if entry is None:
                break
            branch.append(entry)
            cursor = str(entry.get("parentId") or "")
        if branch:
            selected_entries = list(reversed(branch))

    messages: list[dict[str, object]] = []
    message_entries: list[dict[str, object]] = []
    for entry in selected_entries:
        if str(entry.get("type") or "") != "message":
            continue
        raw_message = entry.get("message")
        if not isinstance(raw_message, Mapping):
            continue
        message = dict(raw_message)
        if not str(message.get("id") or "") and str(entry.get("id") or ""):
            message["id"] = str(entry["id"])
        if as_integer(message.get("timestamp")) <= 0:
            timestamp = _pi_history_entry_timestamp_ms(entry.get("timestamp"))
            if timestamp > 0:
                message["timestamp"] = timestamp
        messages.append(message)
        message_entries.append(entry)
    return messages, message_entries


def _pi_tool_history_events(
    raw_messages: list[object],
    *,
    session_id: str,
    raw_entries: list[object] | None = None,
    maximum_tools: int = 256,
    maximum_public_chars: int = 48_000,
) -> list[dict[str, object]]:
    """Rebuild the public tool timeline from Pi's durable transcript.

    The conversation transcript intentionally hides protocol messages, but the
    tool activity strip still needs to survive a Gateway restart or replay
    eviction. Only the same redacted projection used by live events is rebuilt
    here; full arguments and results remain available solely through the
    local-only transient Debug endpoint.
    """

    events: list[tuple[str, str, str, int, dict[str, object]]] = []
    entry_timestamps = _pi_history_entry_timestamps(raw_entries or [])
    current_turn_id = ""
    activity_order: list[str] = []
    tool_names: dict[str, str] = {}
    for raw_value in raw_messages:
        if not isinstance(raw_value, Mapping):
            continue
        raw = raw_value
        role = str(raw.get("role") or "assistant").strip().lower()
        message_id = pi_message_id(raw, "history")
        if role == "user":
            current_turn_id = f"history:{message_id}"
            continue
        turn_id = current_turn_id or f"history:{message_id}"
        fingerprint = _pi_history_message_fingerprint(raw)
        durable_timestamps = entry_timestamps.get(fingerprint)
        created_at_ms = (
            durable_timestamps.popleft()
            if durable_timestamps
            else as_integer(raw.get("timestamp"))
        )
        if role == "assistant":
            summaries = public_reasoning_summaries(raw)
            if summaries:
                reasoning_id = f"reasoning:{message_id}:0"
                events.append(
                    (
                        reasoning_id,
                        "reasoning_summary",
                        turn_id,
                        created_at_ms,
                        {
                            "requestId": reasoning_id,
                            "sourceMessageId": message_id,
                            "summary": summaries[-1],
                            "items": summaries,
                            "source": "provider_reasoning_summary",
                            "state": "completed",
                        },
                    )
                )
                activity_order.append(reasoning_id)
            content = raw.get("content") if isinstance(raw.get("content"), list) else []
            for item_index, item_value in enumerate(content):
                item = as_mapping(item_value)
                if str(item.get("type") or "") not in {"toolCall", "tool_call"}:
                    continue
                tool_call_id = str(item.get("id") or item.get("toolCallId") or "").strip()
                tool_name = str(item.get("name") or item.get("toolName") or "").strip()
                if not tool_call_id or not tool_name:
                    continue
                raw_args = _pi_tool_arguments(item)
                payload: dict[str, object] = {
                    "toolCallId": tool_call_id,
                    "toolName": tool_name,
                    "args": redact_mapping(raw_args),
                    "isError": False,
                }
                public_result = public_code_tool_activity(tool_name, raw_args)
                if public_result:
                    payload["publicResult"] = public_result
                events.append(
                    (
                        tool_call_id,
                        "tool_started",
                        turn_id,
                        created_at_ms + item_index,
                        payload,
                    )
                )
                if tool_call_id not in tool_names:
                    activity_order.append(tool_call_id)
                tool_names[tool_call_id] = tool_name
            continue
        if role not in {"toolresult", "tool_result"}:
            continue
        tool_call_id = str(raw.get("toolCallId") or raw.get("tool_call_id") or "").strip()
        if not tool_call_id:
            continue
        tool_name = str(raw.get("toolName") or raw.get("tool_name") or tool_names.get(tool_call_id) or "tool").strip()
        if tool_call_id not in tool_names:
            activity_order.append(tool_call_id)
        tool_names[tool_call_id] = tool_name
        payload = {
            "toolCallId": tool_call_id,
            "toolName": tool_name,
            "args": {},
            "result": _pi_tool_result(raw),
            "isError": runtime_tool_result_is_error(
                tool_name,
                raw,
                reported_is_error=bool(
                    raw.get("isError") or raw.get("is_error")
                ),
            ),
        }
        events.append((tool_call_id, "tool_finished", turn_id, created_at_ms, payload))

    events_by_activity: dict[
        str,
        list[tuple[str, str, str, int, dict[str, object]]],
    ] = {}
    for event in events:
        events_by_activity.setdefault(event[0], []).append(event)
    allowed_order: list[str] = []
    used_chars = 0
    for activity_id in reversed(activity_order[-max(1, maximum_tools) :]):
        activity_events = events_by_activity.get(activity_id, [])
        activity_chars = sum(
            len(
                json.dumps(
                    {
                        "eventType": event_type,
                        "turnId": turn_id,
                        "payload": payload,
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            )
            + 320
            for _identity, event_type, turn_id, _created_at_ms, payload
            in activity_events
        )
        if allowed_order and used_chars + activity_chars > max(
            4_000,
            int(maximum_public_chars),
        ):
            break
        allowed_order.append(activity_id)
        used_chars += activity_chars
    allowed_ids = set(allowed_order)
    selected = [event for event in events if event[0] in allowed_ids]
    result: list[dict[str, object]] = []
    for sequence, (tool_call_id, event_type, turn_id, created_at_ms, payload) in enumerate(selected, start=1):
        event_id = (
            f"{session_id}:history-tool:"
            f"{uuid.uuid5(uuid.NAMESPACE_URL, f'{session_id}:{tool_call_id}:{event_type}').hex[:20]}"
        )
        result.append(
            AgentEventEnvelope(
                event_id=event_id,
                session_id=session_id,
                turn_id=turn_id,
                sequence=sequence,
                created_at_ms=created_at_ms,
                event_type=event_type,
                payload=payload,
                resume_token=event_id,
            ).to_payload()
        )
    return result


def _pi_history_entry_timestamps(raw_entries: list[object]) -> dict[str, deque[int]]:
    """Match Pi context messages to their durable transcript append times.

    Assistant message timestamps mark the beginning of the provider request.
    The enclosing transcript entry is appended when the tool call is emitted,
    which is the correct start time for a restored tool execution.
    """

    timestamps: dict[str, deque[int]] = {}
    for entry_value in raw_entries:
        entry = as_mapping(entry_value)
        if str(entry.get("type") or "") != "message":
            continue
        message = as_mapping(entry.get("message"))
        fingerprint = _pi_history_message_fingerprint(message)
        created_at_ms = _pi_history_entry_timestamp_ms(entry.get("timestamp"))
        if not fingerprint or created_at_ms <= 0:
            continue
        timestamps.setdefault(fingerprint, deque()).append(created_at_ms)
    return timestamps


def _durable_public_assistant_counts(
    raw_entries: list[object],
    *,
    session_id: str,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entry_value in raw_entries:
        entry = as_mapping(entry_value)
        if str(entry.get("type") or "") != "message":
            continue
        message = as_mapping(entry.get("message"))
        if (
            str(message.get("role") or "").lower() != "assistant"
            or not pi_message_is_public(message)
        ):
            continue
        payload = pi_message_payload(
            message,
            session_id=session_id,
            turn_id="durable-transcript",
            message_id=str(entry.get("id") or "durable-transcript"),
        ).to_payload()
        fingerprint = _assistant_projection_fingerprint(payload)
        counts[fingerprint] = counts.get(fingerprint, 0) + 1
    return counts


def _assistant_projection_fingerprint(
    payload: Mapping[str, object],
) -> str:
    return json.dumps(
        {
            "blocks": [
                {
                    key: block.get(key)
                    for key in (
                        "type",
                        "status",
                        "presentationKind",
                        "data",
                        "summary",
                        "visibility",
                    )
                    if block.get(key) is not None
                }
                for block in payload.get("blocks") or []
                if isinstance(block, Mapping)
            ],
            "attachments": payload.get("attachments") or [],
            "citations": payload.get("citations") or [],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _pi_history_message_fingerprint(message: Mapping[str, object]) -> str:
    if not message:
        return ""
    try:
        return json.dumps(
            dict(message),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError):
        return ""


def _pi_history_entry_timestamp_ms(value: object) -> int:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return max(0, int(value))
    text = str(value or "").strip()
    if not text:
        return 0
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return 0
    return max(0, int(parsed.timestamp() * 1_000))


def _pi_tool_arguments(item: Mapping[str, object]) -> dict[str, object]:
    raw = item.get("arguments") if item.get("arguments") is not None else item.get("args")
    if isinstance(raw, Mapping):
        return dict(raw)
    if isinstance(raw, str) and raw.strip():
        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError:
            return {"value": redact_runtime_text(raw)}
        if isinstance(decoded, Mapping):
            return dict(decoded)
    return {}


def _pi_tool_result(raw: Mapping[str, object]) -> dict[str, object]:
    for key in ("details", "result"):
        value = raw.get(key)
        if isinstance(value, Mapping):
            return dict(inspectable_tool_result(value))
    content = raw.get("content")
    if content is not None:
        return {"content": inspectable_tool_result(content)}
    return {}
