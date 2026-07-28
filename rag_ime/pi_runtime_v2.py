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
from .agent_tool_block_bridge import AgentToolBlockBuffer
from .agent_runtime_driver import AgentRuntimeError, CompactionObserver
from .agent_sessions import AgentSessionStore
from .pi_runtime import (
    PiRuntimeConfig,
    PiRuntimeError,
)
from .pi_runtime_public import (
    pi_message_payload,
    APPROVAL_TITLE_PREFIX,
    REVIEW_TITLE_PREFIX,
    last_assistant_error,
    last_assistant_preview,
    pi_message_id,
    pi_message_is_public,
    provider_retry_status,
    public_code_tool_activity,
    public_fork_candidate_text,
    public_pi_model,
    public_usage,
    redact_mapping,
    ui_confirmation_value,
)
from .pi_runtime_values import (
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
_CANCELLATION_SURFACES = (
    "provider", "tool", "exec", "retry", "compaction",
    "branch_summary", "timer", "continuation", "session",
)
_CANCELLATION_SURFACE_STATES = {"requested", "acknowledged", "terminated", "unknown"}


def _room_generation(value: object) -> int:
    generation = as_integer(value)
    if generation < 0:
        raise ValueError("Room generation must be non-negative")
    return generation


def _room_context_rebind(
    current: Mapping[str, object],
    desired: Mapping[str, object],
) -> dict[str, object]:
    """Validate one in-place managed Room binding transition."""

    current_epoch = as_integer(current.get("contextEpoch"))
    desired_epoch = as_integer(desired.get("contextEpoch"))
    if current_epoch < 1 or desired_epoch < 1:
        raise PiRuntimeError("managed Room binding has no positive context epoch")
    if desired_epoch == current_epoch:
        current_root = str(current.get("rootId") or "").strip()
        desired_root = str(desired.get("rootId") or "").strip()
        current_generation = as_integer(current.get("generation"))
        desired_generation = as_integer(desired.get("generation"))
        if (
            not current_root
            or current_root != desired_root
            or current_generation != desired_generation
        ):
            raise PiRuntimeError(
                "managed Room binding changed task without advancing context epoch"
            )
        return {"contextEpochChanged": False, "contextEpoch": desired_epoch}
    if (
        desired_epoch == current_epoch + 1
        and str(desired.get("contextEpochReason") or "") == "task_switch"
    ):
        return {"contextEpochChanged": True, "contextEpoch": desired_epoch}
    raise PiRuntimeError("managed Room context epoch transition is not monotonic")


def _live_room_capability(value: object) -> dict[str, object]:
    capability = as_mapping(value)
    if str(capability.get("status") or "") == "revoked":
        return {}
    return capability


def _runtime_primitive_capabilities(value: object) -> dict[str, object]:
    source = as_mapping(value)
    operations = as_mapping(source.get("sessionCancelOperations"))
    return {
        "continuationEnvelope": (
            str(source.get("continuationEnvelope") or "")
            if source.get("continuationEnvelope") == "1"
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
        "roomTypes": bool(source.get("roomTypes")),
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
            self._write_record(process, request)
        except (BrokenPipeError, OSError) as exc:
            with self._lock:
                self._pending.pop(request_id, None)
            raise PiRuntimeError("Pi Runtime Host stdin closed") from exc
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
            raise PiRuntimeError(str(error.get("message") or f"Pi Runtime Host command failed: {method}"))
        return dict(as_mapping(response.get("result")))

    def _write_record(self, process: subprocess.Popen[bytes], request: Mapping[str, object]) -> None:
        encoded = json.dumps(dict(request), ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
        with self._write_lock:
            if process.stdin is None:
                raise BrokenPipeError("Pi Runtime Host stdin is unavailable")
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
    stream_pi_message_id: str = ""
    tool_blocks: AgentToolBlockBuffer = field(default_factory=AgentToolBlockBuffer)
    last_agent_messages: list[object] = field(default_factory=list)
    final_error: str = ""
    pending_approvals: dict[str, str] = field(default_factory=dict)
    pending_reviews: dict[str, str] = field(default_factory=dict)
    pending_ui_requests: dict[str, dict[str, object]] = field(default_factory=dict)
    abort_timer: threading.Timer | None = field(default=None, repr=False)
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
            busy = sorted(session_id for session_id, state in self._states.items() if state.turn_id)
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
        return self._ensure_session(
            session_id,
            lightweight_existing=False,
        )

    def _ensure_room_dispatch(self, session_id: str) -> dict[str, object]:
        """Prepare a Dispatch without serializing the resident transcript.

        Room delivery only needs the Session lifecycle fence and current Room
        capability. The full snapshot also contains messages, entries,
        telemetry, and Tool manifests; reading it on the hot handoff path can
        hold a short Dispatch lease behind unrelated transcript work.
        """

        return self._ensure_session(
            session_id,
            lightweight_existing=True,
        )

    def _ensure_session(
        self,
        session_id: str,
        *,
        lightweight_existing: bool,
    ) -> dict[str, object]:
        with self._lifecycle_lock:
            if not self.config.model_configured:
                raise PiRuntimeError(self.config.model_configuration_error or "Pi model is not configured")
            client = self._host()
            session = dict(self.sessions.get(session_id))
            binding = self.sessions.runtime_binding(session_id)
            if binding is not None:
                if binding.get("driverId") != self.driver_id or binding.get("runtimeKind") != self.runtime_kind:
                    raise PiRuntimeError("Agent session belongs to another runtime driver")
                session["_runtimeBinding"] = binding
            if self._session_context_provider is not None:
                session.update(dict(self._session_context_provider(session)))
            desired_room = _live_room_capability(
                session.get("roomCapability")
            )
            with self._lock:
                already_open = session_id in self._open_sessions
            if already_open:
                use_control_state = (
                    lightweight_existing
                    and bool(
                        self._host_capabilities.get(
                            "sessionControlState"
                        )
                    )
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
                current_room = _live_room_capability(
                    snapshot.get("roomCapability")
                )
                rebind = (
                    _room_context_rebind(current_room, desired_room)
                    if current_room and desired_room
                    else None
                )
                current_binding_hash = str(
                    current_room.get("runtimeBindingHash") or ""
                )
                desired_binding_hash = str(
                    desired_room.get("runtimeBindingHash") or ""
                )
                same_mode_binding = (
                    current_room
                    and desired_room
                    and (
                        not bool(rebind and rebind["contextEpochChanged"])
                        and
                        (
                            (
                                bool(desired_binding_hash)
                                and current_binding_hash
                                == desired_binding_hash
                            )
                            or (
                                not desired_binding_hash
                                and current_room.get("promptPlanHash")
                                == desired_room.get("promptPlanHash")
                            )
                        )
                    )
                )
                if (
                    (not current_room and not desired_room)
                    or same_mode_binding
                ):
                    self._sync_idle_snapshot(session_id, snapshot)
                    with self._lock:
                        self._schedule_idle_locked()
                    return {"state": snapshot, "reused": True}
                if not bool(snapshot.get("isIdle")):
                    if bool(current_room) != bool(desired_room):
                        raise PiRuntimeError(
                            "Session must settle before switching between "
                            "Agent and Room modes"
                        )
                    raise PiRuntimeError(
                        "managed Room Session must settle before rebinding PromptPlan"
                    )
                if current_room and desired_room and rebind is not None:
                    self._sync_idle_snapshot(session_id, snapshot)
                    with self._lock:
                        self._schedule_idle_locked()
                    return {
                        "state": snapshot,
                        "reused": True,
                        "roomRebind": True,
                        **rebind,
                    }
                client.send("session.close", {"sessionId": session_id})
                with self._lock:
                    self._open_sessions.discard(session_id)
                    self._states.pop(session_id, None)
            roots = [str(value) for value in session.get("workspaceRoots") or [] if str(value).strip()]
            cwd = roots[0] if roots else str(self.config.agent_dir)
            provider, model_id = self.config.resolved_model_reference(session)
            session_file = str((binding or {}).get("transcriptRef") or session.get("sessionFile") or "").strip()
            managed_system_prompt = (
                str(session.get("managedSystemPrompt") or "")
                if desired_room
                else ""
            )
            if desired_room and not managed_system_prompt:
                raise PiRuntimeError("managed Room Session has no live PromptPlan payload")
            params: dict[str, object] = {
                "sessionId": session_id,
                "cwd": cwd,
                "systemPrompt": managed_system_prompt or self.config.system_prompt_for_session(session),
                "toolManifest": self.tool_catalog(session_id),
                "noContextFiles": (
                    str(session.get("toolProfileVersion") or "")
                    in {"ime-surface-v1", "voice-refinement-v1"}
                    or not bool(session.get("projectContextEnabled", False))
                ),
                "piSkillsEnabled": bool(session.get("piSkillsEnabled", False)),
                "codexSkillsEnabled": bool(session.get("codexSkillsEnabled", False)),
            }
            session_context = str(
                session.get("sessionContext") or ""
            ).strip()
            if session_context:
                params["sessionContext"] = session_context
            if desired_room:
                params["roomCapability"] = dict(desired_room)
                params.setdefault("sessionContext", "")
                room_bootstrap = str(
                    session.get("providerContext") or ""
                )
                room_recovery = str(
                    session.get("roomRecoveryContext")
                    or room_bootstrap
                )
                params["roomContext"] = room_bootstrap
                # Provider delivery may use only a delta after the first
                # Dispatch. Keep the current full bounded projection out of
                # band so Pi can rebase a new context epoch after compaction.
                params["roomRecoveryContext"] = room_recovery
                if isinstance(session.get("roomProviderContext"), Mapping):
                    params["roomProviderContext"] = dict(session["roomProviderContext"])
                if isinstance(session.get("roomResourceLimits"), Mapping):
                    params["roomResourceLimits"] = dict(session["roomResourceLimits"])
                room_skill = session.get("roomSkillPolicy")
                if isinstance(room_skill, Mapping) and room_skill.get("selection") == "required":
                    params["roomSkillPolicy"] = dict(room_skill)
            if provider and model_id:
                params.update({"provider": provider, "modelId": model_id})
            thinking_level = str(session.get("thinkingLevel") or "").strip().lower()
            if thinking_level:
                params["thinkingLevel"] = thinking_level
            if session_file:
                params["sessionFile"] = session_file
            result = client.send("session.open", params, timeout=max(60.0, self.config.command_timeout_seconds))
            snapshot = dict(as_mapping(result.get("snapshot")))
            model = as_mapping(snapshot.get("model"))
            if model.get("provider") and model.get("id"):
                self.sessions.set_model_profile(session_id, f"{model['provider']}/{model['id']}")
            bound = self.sessions.bind_runtime_session(
                session_id,
                driver_id=self.driver_id,
                runtime_kind=self.runtime_kind,
                external_session_id=str(snapshot.get("piSessionId") or session_id),
                transcript_ref=str(snapshot.get("sessionFile") or ""),
                branch_anchor=str(snapshot.get("leafId") or ""),
                binding_state="active",
                metadata={"protocolVersion": _PROTOCOL_VERSION},
                message_count=len(snapshot.get("messages") or []),
            )
            idle_session = self._sync_idle_snapshot(session_id, snapshot)
            if idle_session is not None:
                bound = idle_session
            evicted = str(result.get("evictedSessionId") or "")
            with self._lock:
                self._open_sessions.add(session_id)
                self._states.setdefault(session_id, _HostedSessionState())
                if evicted:
                    self._open_sessions.discard(evicted)
                    evicted_state = self._states.pop(evicted, None)
                    if evicted_state is not None and evicted_state.abort_timer is not None:
                        evicted_state.abort_timer.cancel()
                self._status = "ready"
                self._schedule_idle_locked()
            self.events.publish(session_id, "status_changed", {"status": "ready"})
            return {
                "state": snapshot,
                "session": bound,
                "evictedSessionId": evicted or None,
                "roomSkillLoad": result.get("roomSkillLoad"),
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
            if state is not None and state.turn_id:
                return None
        return self.sessions.set_status(
            session_id,
            "idle",
            message_count=len(snapshot.get("messages") or []),
        )

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
                if not turn_id or state.abort_requested_turn_id:
                    raise PiRuntimeError("Pi 当前没有可接收排队消息的活动回合")
                self._cancel_idle_locked()
            client = self._require_client()
            method = "session.steer" if normalized_delivery == "steer" else "session.follow_up"
            response = client.send(method, params)
            response_turn_id = str(response.get("turnId") or turn_id)
            if response_turn_id != turn_id:
                raise PiRuntimeError("Pi 返回了不匹配的排队消息回合")
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
        with self._lock:
            state = self._states.setdefault(session_id, _HostedSessionState())
            if state.turn_id:
                raise PiRuntimeTurnConflict(
                    "Pi 正在处理上一轮，请等待结束或停止完成后再发送"
                )
            self._cancel_idle_locked()
            state.stream_pi_message_id = ""
            state.tool_blocks.clear()
            state.last_agent_messages = []
            state.final_error = ""
            state.abort_requested_turn_id = ""
        try:
            accepted = client.send("session.prompt", params)
        except Exception as exc:
            self._turn_failed(session_id, "", exc)
            raise
        turn_id = str(accepted.get("turnId") or "")
        with self._lock:
            state = self._states.setdefault(session_id, _HostedSessionState())
            state.turn_id = turn_id
            state.client_message_id = str(client_message_id).strip()
            self._status = "busy"
        self.sessions.set_status(session_id, "busy", last_message_preview=text)
        self.events.publish(session_id, "status_changed", {"status": "busy"}, turn_id=turn_id)
        result: dict[str, object] = {
            "accepted": True,
            "turnId": turn_id,
            "piEntryId": turn_id,
            "response": accepted,
        }
        if client_message_id:
            result["clientMessageId"] = str(client_message_id).strip()
        return result

    def messages(self, session_id: str) -> list[dict[str, object]]:
        return list(self.session_snapshot(session_id).get("messages") or [])

    def session_snapshot(self, session_id: str) -> dict[str, object]:
        try:
            prepared = self._ensure_for_sealed_room_operation(
                session_id,
                operation="message inspection",
                ordinary_fallback=True,
            )
            prepared_state = prepared.get("state")
            snapshot = (
                dict(prepared_state)
                if isinstance(prepared_state, Mapping)
                else self._require_client().send(
                    "session.snapshot",
                    {"sessionId": session_id},
                )
            )
        except AgentRuntimeError:
            return {"messages": [], "telemetry": None, "messageQueue": None}
        raw_messages = snapshot.get("messages") if isinstance(snapshot.get("messages"), list) else []
        raw_entries = snapshot.get("entries") if isinstance(snapshot.get("entries"), list) else []
        tool_history_events = _pi_tool_history_events(
            raw_messages,
            session_id=session_id,
            raw_entries=raw_entries,
        )
        result: list[dict[str, object]] = []
        current_turn_id = ""
        last_assistant_fingerprint: tuple[str, str] | None = None
        durable_assistant_counts = _durable_public_assistant_counts(
            raw_entries,
            session_id=session_id,
        )
        emitted_assistant_counts: dict[str, int] = {}
        for raw in raw_messages:
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
            self._ensure_for_sealed_room_operation(
                session_id,
                operation="debug context",
                ordinary_fallback=True,
            )
        params: dict[str, object] = {"sessionId": session_id}
        if str(turn_id).strip():
            params["turnId"] = str(turn_id).strip()
        result = self._require_client().send("session.debug.context", params)
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
                        if evicted_state is not None and evicted_state.abort_timer is not None:
                            evicted_state.abort_timer.cancel()
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
                        if target_state is not None and target_state.abort_timer is not None:
                            target_state.abort_timer.cancel()
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
        self.ensure(session_id)
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
        self.ensure(session_id)
        client = self._require_client()
        snapshot = client.send("session.snapshot", {"sessionId": session_id})
        selected = public_pi_model(as_mapping(snapshot.get("model")))
        models = self.available_models()
        return {
            "selected": selected or None,
            "models": models,
            "thinkingLevel": effective_thinking_level(snapshot.get("thinkingLevel"), selected),
        }

    def available_models(self) -> list[dict[str, object]]:
        catalog = self._host().send(
            "models.list",
            timeout=max(30.0, self.config.command_timeout_seconds),
        )
        models = [
            model
            for value in catalog.get("models") or []
            if isinstance(value, Mapping)
            for model in [public_pi_model(value)]
            if model
        ]
        models.sort(key=lambda item: (str(item["provider"]).lower(), str(item["name"]).lower()))
        return models

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
        finally:
            with self._lock:
                self._active_completion_ids.discard(normalized_request_id)
                self._completion_sinks.pop(normalized_request_id, None)
                if not any(state.turn_id for state in self._states.values()):
                    self._status = "ready"
                self._schedule_idle_locked()

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
        client = self._require_client()
        with self._lock:
            state = self._states.setdefault(session_id, _HostedSessionState())
            turn_id = state.turn_id
            if not turn_id:
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
        if (
            result.get("schemaVersion") != "rag-ime.pi-session-abort-receipt.v1"
            or result.get("sessionId") != session_id
            or result.get("turnId") != turn_id
            or not isinstance(result.get("lifecycle"), Mapping)
        ):
            raise PiRuntimeError("Pi Runtime Host returned an invalid Session abort receipt")
        with self._lock:
            state = self._states.setdefault(session_id, _HostedSessionState())
            # The host can emit agent_settled before the abort ACK arrives.
            # Do not regress an already terminal turn back to "aborting".
            if state.turn_id != turn_id:
                return dict(result)
            self.events.publish(session_id, "status_changed", {"status": "aborting"}, turn_id=turn_id)
        return dict(result)

    def dispatch_room(
        self,
        payload: Mapping[str, object],
        *,
        message: str,
        lease_token: str,
    ) -> dict[str, object]:
        """Deliver one Kernel-leased Dispatch through Pi's typed Room RPC."""

        session_id = str(payload.get("targetSessionId") or "").strip()
        root_id = str(payload.get("rootId") or "").strip()
        dispatch_id = str(payload.get("dispatchId") or "").strip()
        idempotency_key = str(payload.get("idempotencyKey") or "").strip()
        if not all((session_id, root_id, dispatch_id, idempotency_key, message.strip(), lease_token.strip())):
            raise ValueError("Room dispatch requires target, identity, message, and lease token")
        generation = as_integer(payload.get("generation"))
        if generation < 0:
            raise ValueError("Room dispatch generation must be non-negative")
        capability_epoch = as_integer(payload.get("capabilityEpoch"))
        if capability_epoch < 0:
            raise ValueError("Room dispatch capabilityEpoch must be non-negative")
        opened = self._ensure_room_dispatch(session_id)
        client = self._require_client()
        session = dict(self.sessions.get(session_id))
        if self._session_context_provider is not None:
            session.update(
                dict(self._session_context_provider(session))
            )
        with self._lock:
            negotiated = _runtime_primitive_capabilities(
                self._host_capabilities.get("runtimePrimitives")
            )
        if not negotiated["roomTypes"]:
            raise PiRuntimeError("Pi Runtime Host did not negotiate typed Room RPC")
        dispatch_params: dict[str, object] = {
            "sessionId": session_id,
            "rootId": root_id,
            "dispatchId": dispatch_id,
            "generation": generation,
            "capabilityEpoch": capability_epoch,
            "idempotencyKey": idempotency_key,
            "leaseToken": lease_token,
            "message": message,
        }
        session_context = str(
            session.get("sessionContext") or ""
        ).strip()
        delta_available = "providerContextDelta" in session
        full_room_context = str(
            session.get("providerContext") or ""
        ).strip()
        use_delta = (
            opened.get("reused") is True
            and opened.get("contextEpochChanged") is not True
            and delta_available
        )
        context_value = (
            session.get("providerContextDelta")
            if use_delta
            else full_room_context
        )
        room_context = str(context_value or "").strip()
        if session_context:
            dispatch_params["sessionContext"] = session_context
        if not full_room_context:
            raise PiRuntimeError(
                "managed Room Dispatch has no provider-only task context"
            )
        if not room_context and not use_delta:
            raise PiRuntimeError(
                "managed Room Dispatch has no provider-only task context"
            )
        dispatch_params["roomContext"] = room_context
        dispatch_params["roomRecoveryContext"] = str(
            session.get("roomRecoveryContext")
            or full_room_context
        ).strip()
        if isinstance(session.get("roomProviderContext"), Mapping):
            dispatch_params["roomProviderContext"] = dict(
                session["roomProviderContext"]
            )
        if isinstance(session.get("roomCapability"), Mapping):
            dispatch_params["roomCapability"] = dict(session["roomCapability"])
        if isinstance(session.get("roomResourceLimits"), Mapping):
            dispatch_params["roomResourceLimits"] = dict(
                session["roomResourceLimits"]
            )
        result = client.send("room.dispatch", dispatch_params)
        if (
            result.get("schemaVersion") != "wisdom-weasel.room-runtime-receipt.v1"
            or result.get("rootId") != root_id
            or result.get("dispatchId") != dispatch_id
            or int(result.get("generation", -1)) != generation
            or int(result.get("capabilityEpoch", -1)) != capability_epoch
            or result.get("status") != "accepted"
        ):
            raise PiRuntimeError("Pi Runtime Host returned an invalid Room dispatch receipt")
        if "roomSkillLoad" not in result and isinstance(opened.get("roomSkillLoad"), Mapping):
            result["roomSkillLoad"] = dict(opened["roomSkillLoad"])
        return dict(result)

    def cancel_room(
        self,
        *,
        session_id: str,
        root_id: str,
        generation: int,
    ) -> dict[str, object]:
        # Cancellation must target the already-running host Session exactly as
        # it exists. Calling ensure() here can try to rebind a revoked Room
        # PromptPlan before the active turn has settled, preventing abort.
        with self._lock:
            negotiated = _runtime_primitive_capabilities(
                self._host_capabilities.get("runtimePrimitives")
            )
        if not negotiated["roomTypes"]:
            raise PiRuntimeError("Pi Runtime Host did not negotiate typed Room RPC")
        client = self._require_client()
        try:
            result = client.send(
                "room.cancel",
                {
                    "sessionId": session_id,
                    "rootId": str(root_id).strip(),
                    "generation": _room_generation(generation),
                },
            )
        except PiRuntimeError as exc:
            if "timed out" in str(exc).lower():
                receipt = self._kill_gate.request_kill(
                    client.host_identity,
                    request_kind="cancel_timeout",
                    requested_by=f"session:{session_id}",
                    reason=f"room.cancel timeout for {root_id}",
                    now_ms=int(time.time() * 1000),
                )
                with self._lock:
                    self._last_kill_receipt = dict(receipt)
            raise
        if (
            result.get("schemaVersion") != "wisdom-weasel.room-runtime-receipt.v1"
            or result.get("receiptKind") != "cancel_applied"
            or result.get("rootId") != root_id
        ):
            raise PiRuntimeError("Pi Runtime Host returned an invalid Room cancellation receipt")
        surfaces = dict(as_mapping(result.get("cancellationSurfaces")))
        if set(surfaces) != set(_CANCELLATION_SURFACES):
            raise PiRuntimeError("Pi Runtime Host cancellation lacks typed per-surface proof")
        typed_surfaces: dict[str, dict[str, object]] = {}
        for surface in _CANCELLATION_SURFACES:
            proof = dict(as_mapping(surfaces.get(surface)))
            if (
                proof.get("schemaVersion")
                != "wisdom-weasel.runtime-surface-termination-receipt.v1"
                or proof.get("surface") != surface
                or str(proof.get("state")) not in _CANCELLATION_SURFACE_STATES
                or not isinstance(proof.get("targetIds", []), list)
            ):
                raise PiRuntimeError("Pi Runtime Host cancellation lacks typed per-surface proof")
            typed_surfaces[surface] = proof
        derived_pending = [
            surface for surface in _CANCELLATION_SURFACES
            if typed_surfaces[surface]["state"] in {"requested", "acknowledged", "unknown"}
        ]
        declared_pending = [
            str(value) for value in result.get("pendingTargets") or [] if str(value).strip()
        ]
        if sorted(declared_pending) != sorted(derived_pending):
            raise PiRuntimeError("Pi Runtime Host cancellation pendingTargets mismatch")
        result["pendingTargets"] = derived_pending
        result["cancellationSurfaces"] = typed_surfaces
        return dict(result)

    def compact(self, session_id: str, instructions: str = "") -> dict[str, object]:
        self._ensure_for_sealed_room_operation(session_id, operation="compaction")
        result = self._require_client().send(
            "session.compact",
            {"sessionId": session_id, "instructions": str(instructions).strip()[:2000]},
            timeout=max(60.0, self.config.command_timeout_seconds),
        )
        checkpoint = self._observe_compaction(session_id, result, "manual")
        if checkpoint:
            result["memoryCheckpoint"] = checkpoint
        return result

    def _ensure_for_sealed_room_operation(
        self,
        session_id: str,
        *,
        operation: str,
        ordinary_fallback: bool = False,
    ) -> dict[str, object]:
        """Reuse an idle settled Room Session for a read/maintenance operation.

        A successful Room Commit revokes the product capability before the user
        can inspect or compact the sealed Session. Rebinding that tombstone as a
        live Room capability would be unsafe, while closing the resident Pi
        Session would discard the exact context and Skill/Tool receipts.
        """

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
            desired_room = as_mapping(session.get("roomCapability"))
            with self._lock:
                already_open = session_id in self._open_sessions
            if str(desired_room.get("status") or "") != "revoked":
                return self.ensure(session_id)
            if not already_open:
                if ordinary_fallback:
                    return self.ensure(session_id)
                raise PiRuntimeError(
                    "settled managed Room Session is no longer resident; "
                    f"its sealed {operation} context cannot be reopened as a live capability"
                )
            snapshot = dict(
                client.send("session.snapshot", {"sessionId": session_id})
            )
            current_room = as_mapping(snapshot.get("roomCapability"))
            same_manifest = (
                current_room.get("manifestId") == desired_room.get("manifestId")
                and current_room.get("manifestHash")
                == desired_room.get("manifestHash")
            )
            if not current_room and ordinary_fallback:
                self._sync_idle_snapshot(session_id, snapshot)
                with self._lock:
                    self._schedule_idle_locked()
                return {
                    "state": snapshot,
                    "reused": True,
                    "ordinaryAfterRoom": True,
                }
            if not same_manifest:
                raise PiRuntimeError(
                    f"settled managed Room Session {operation} fence changed"
                )
            if not bool(snapshot.get("isIdle")):
                raise PiRuntimeError(
                    f"managed Room Session must be idle before {operation}"
                )
            with self._lock:
                self._schedule_idle_locked()
            return {
                "state": snapshot,
                "reused": True,
                "sealedRoomOperation": operation,
            }

    def has_pending_approval(self, session_id: str, approval_id: str) -> bool:
        with self._lock:
            return approval_id in self._states.get(session_id, _HostedSessionState()).pending_approvals

    def has_pending_review(self, session_id: str, run_id: str) -> bool:
        with self._lock:
            return run_id in self._states.get(session_id, _HostedSessionState()).pending_reviews

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
                request = {"requestId": normalized_request_id, "method": "confirm"}
        if request is None:
            raise PiRuntimeError("UI request is no longer pending")
        method = str(request.get("method") or "")
        resolved: dict[str, object] = {"cancelled": True}
        if response.get("cancelled") is not True:
            value = str(response.get("value") or "")
            if method == "confirm":
                confirmed = response.get("confirmed")
                if not isinstance(confirmed, bool):
                    confirmed = ui_confirmation_value(value)
                resolved = {"confirmed": confirmed}
            else:
                if method == "select":
                    options = [str(item) for item in request.get("options") or []]
                    if options and value not in options:
                        raise PiRuntimeError("UI response is not one of the offered options")
                resolved = {"value": value}
        result = self._require_client().send(
            "ui.resolve",
            {
                "sessionId": session_id,
                "requestId": normalized_request_id,
                "response": resolved,
            },
        )
        with self._lock:
            if state:
                state.pending_ui_requests.pop(normalized_request_id, None)
                if review_run_id:
                    state.pending_reviews.pop(review_run_id, None)
        return {
            "requestId": normalized_request_id,
            "resolved": True,
            "method": method,
            "host": dict(result),
        }

    def plugin_list(self) -> list[dict[str, object]]:
        return [dict(value) for value in self._require_host_result("plugins.list").get("plugins") or [] if isinstance(value, Mapping)]

    def plugin_create(self, payload: Mapping[str, object]) -> dict[str, object]:
        return self._require_host_result("plugins.create", payload)

    def plugin_validate(self, source_path: str) -> dict[str, object]:
        return self._require_host_result("plugins.validate", {"sourcePath": source_path})

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
                if retired is not None and retired.abort_timer is not None:
                    retired.abort_timer.cancel()
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
                self.events.publish(session_id, "status_changed", {"status": "analyzing"}, turn_id=turn_id)
            return
        if event_type == "message_end":
            raw_message = as_mapping(raw.get("message"))
            if not pi_message_is_public(raw_message) or str(raw_message.get("role") or "").lower() == "user":
                return
            role = str(raw_message.get("role") or "assistant").lower()
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
            self.events.publish(
                session_id,
                "message_completed",
                {
                    "message": message.to_payload(),
                    "usage": public_usage(raw.get("message")),
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
            public_result = public_code_tool_activity(tool_name, raw_args)
            if public_result:
                payload["publicResult"] = public_result
            result_key = "partialResult" if event_type == "tool_execution_update" else "result"
            if raw.get(result_key) is not None:
                payload[result_key] = redact_mapping(as_mapping(raw.get(result_key)))
            if event_type == "tool_execution_end" and not bool(raw.get("isError")):
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
        if event_type == "agent_end":
            messages = raw.get("messages") if isinstance(raw.get("messages"), list) else []
            with self._lock:
                state.last_agent_messages = list(messages)
                state.final_error = "" if raw.get("willRetry") is True else last_assistant_error(messages)
            # agent_end is not terminal: retries, follow-ups, and extension work can continue.
            return
        if event_type == "agent_settled":
            with self._lock:
                if state.turn_id != turn_id:
                    return
                messages = list(state.last_agent_messages)
                final_error = state.final_error
                aborted = state.abort_requested_turn_id == turn_id
                if state.abort_timer is not None:
                    state.abort_timer.cancel()
                    state.abort_timer = None
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
                    state.abort_requested_turn_id = ""
                    state.pending_approvals.clear()
                    state.pending_reviews.clear()
                    state.pending_ui_requests.clear()
                    self._status = "ready"
                    self._schedule_idle_locked()
            if aborted:
                self.sessions.set_status(session_id, "idle")
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
            self.sessions.set_status(
                session_id,
                "idle",
                message_count=len(messages),
                last_message_preview=last_assistant_preview(messages),
            )
            self.events.publish(
                session_id,
                "turn_completed",
                {"messageCount": len(messages), "terminalEvent": "agent_settled"},
                turn_id=turn_id,
            )
            return
        if event_type == "extension_error":
            self.events.publish(
                session_id,
                "status_changed",
                {
                    "status": "working" if turn_id else "ready",
                    "phase": "extension_warning",
                    "extensionEvent": str(raw.get("event") or ""),
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
            with self._lock:
                state.pending_ui_requests[request_id] = dict(safe)
            self.events.publish(
                session_id,
                "user_input_required",
                safe,
                turn_id=turn_id,
            )

    def _turn_failed(self, session_id: str, turn_id: str, error: BaseException) -> None:
        message = redact_runtime_text(str(error))
        with self._lock:
            state = self._states.setdefault(session_id, _HostedSessionState())
            if state.abort_timer is not None:
                state.abort_timer.cancel()
                state.abort_timer = None
            state.turn_id = ""
            state.client_message_id = ""
            state.stream_pi_message_id = ""
            state.tool_blocks.clear()
            state.abort_requested_turn_id = ""
            state.pending_approvals.clear()
            state.pending_reviews.clear()
            state.pending_ui_requests.clear()
            self._last_error = message
            self._status = "ready" if self._client is not None and self._client.running else "faulted"
            self._schedule_idle_locked()
        self.sessions.set_status(session_id, "faulted", last_message_preview=message)
        self.events.publish(session_id, "turn_failed", {"error": message}, turn_id=turn_id)

    def _handle_host_exit(self, exit_code: int | None, error: str) -> None:
        with self._lock:
            if self._intentional_stop:
                return
            message = redact_runtime_text(error or f"Pi Runtime Host exited with code {exit_code}")
            active = [(session_id, state.turn_id) for session_id, state in self._states.items() if state.turn_id]
            for state in self._states.values():
                if state.abort_timer is not None:
                    state.abort_timer.cancel()
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
        self.sessions.set_status(session_id, "idle")
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
                "status": "aborting",
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


def _pi_tool_history_events(
    raw_messages: list[object],
    *,
    session_id: str,
    raw_entries: list[object] | None = None,
    maximum_tools: int = 256,
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
    tool_order: list[str] = []
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
                    tool_order.append(tool_call_id)
                tool_names[tool_call_id] = tool_name
            continue
        if role not in {"toolresult", "tool_result"}:
            continue
        tool_call_id = str(raw.get("toolCallId") or raw.get("tool_call_id") or "").strip()
        if not tool_call_id:
            continue
        tool_name = str(raw.get("toolName") or raw.get("tool_name") or tool_names.get(tool_call_id) or "tool").strip()
        if tool_call_id not in tool_names:
            tool_order.append(tool_call_id)
        tool_names[tool_call_id] = tool_name
        payload = {
            "toolCallId": tool_call_id,
            "toolName": tool_name,
            "args": {},
            "result": _pi_tool_result(raw),
            "isError": bool(raw.get("isError") or raw.get("is_error")),
        }
        events.append((tool_call_id, "tool_finished", turn_id, created_at_ms, payload))

    allowed_ids = set(tool_order[-max(1, maximum_tools) :])
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
            return redact_mapping(value)
    content = raw.get("content")
    values = content if isinstance(content, list) else [content]
    fragments: list[str] = []
    for value in values[:16]:
        if isinstance(value, Mapping):
            text = str(value.get("text") or value.get("content") or "").strip()
        else:
            text = str(value or "").strip()
        if text:
            fragments.append(text)
    summary = redact_runtime_text(" ".join(fragments))
    return {"summary": summary} if summary else {}
