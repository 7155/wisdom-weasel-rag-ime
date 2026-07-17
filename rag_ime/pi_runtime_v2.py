from __future__ import annotations

import json
import queue
import re
import subprocess
import threading
import uuid
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from .agent_events import AgentEventHub
from .agent_runtime_driver import AgentRuntimeError, CompactionObserver
from .agent_sessions import AgentSessionStore
from .pi_runtime import (
    _APPROVAL_TITLE_PREFIX,
    _REVIEW_TITLE_PREFIX,
    PiRuntimeConfig,
    PiRuntimeError,
    _effective_thinking_level,
    _integer,
    _is_within,
    _last_assistant_error,
    _last_assistant_preview,
    _mapping,
    _message_delivery,
    _model_reference_part,
    _pi_message_id,
    _pi_message_is_public,
    _pi_message_payload,
    _public_fork_candidate_text,
    _public_code_tool_activity,
    _public_pi_model,
    _public_message_queue,
    _public_usage,
    _redact_mapping,
    _redact_runtime_text,
)


_PROTOCOL_VERSION = "2"


class PiRuntimeHostClient:
    """One long-lived process connection shared by the bounded Session host."""

    def __init__(
        self,
        config: PiRuntimeConfig,
        *,
        on_event: Callable[[dict[str, object]], None],
        on_exit: Callable[[int | None, str], None],
    ) -> None:
        self.config = config
        self.on_event = on_event
        self.on_exit = on_exit
        self._lock = threading.RLock()
        self._write_lock = threading.Lock()
        self._pending: dict[str, queue.Queue[object]] = {}
        self._stderr: deque[str] = deque(maxlen=32)
        self._process: subprocess.Popen[bytes] | None = None
        self._stdout_thread: threading.Thread | None = None
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
                self._process = subprocess.Popen(
                    self.config.launch_host_command(),
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=self.config.agent_dir,
                    env=self.config.child_environment(),
                    bufsize=0,
                )
            except OSError as exc:
                raise PiRuntimeError(f"failed to start managed Pi Runtime Host: {exc}") from exc
            self._stopping = False
            self._stdout_thread = threading.Thread(
                target=self._read_stdout,
                name="rag-ime-pi-host-stdout",
                daemon=True,
            )
            self._stderr_thread = threading.Thread(
                target=self._read_stderr,
                name="rag-ime-pi-host-stderr",
                daemon=True,
            )
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
            error = _mapping(response.get("error"))
            raise PiRuntimeError(str(error.get("message") or f"Pi Runtime Host command failed: {method}"))
        return dict(_mapping(response.get("result")))

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
        for thread in (self._stdout_thread, self._stderr_thread):
            if thread is not None and thread is not current:
                thread.join(timeout=2)
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None:
                stream.close()
        with self._lock:
            self._process = None

    def diagnostic_error(self) -> str:
        return _redact_runtime_text(self._stderr[-1] if self._stderr else "")

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
            try:
                self.on_event(value)
            except Exception as exc:  # Keep other Sessions alive when one adapter fails.
                protocol_error = f"Pi Runtime Host event adapter failed: {exc}"
        exit_code = process.poll()
        if exit_code is None:
            try:
                exit_code = process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                exit_code = None
        error = protocol_error or self.diagnostic_error()
        self._fail_pending(PiRuntimeError(error or "Pi Runtime Host exited"))
        self.on_exit(exit_code, error)

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
    last_agent_messages: list[object] = field(default_factory=list)
    final_error: str = ""
    pending_approvals: dict[str, str] = field(default_factory=dict)
    pending_reviews: dict[str, str] = field(default_factory=dict)
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
        self._status = "stopped" if config.enabled else "disabled"
        self._last_error = ""
        self._host_capabilities: dict[str, object] = {}
        self._idle_timer: threading.Timer | None = None
        self._intentional_stop = False

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
            last_error = last_error or _redact_runtime_text(self.config.installation_error)
        elif self.config.enabled and installed and not self.config.model_configured:
            status = "needs_configuration"
            last_error = last_error or _redact_runtime_text(self.config.model_configuration_error)
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
                "sessionSnapshot": True,
                "settledEvents": True,
                "statelessCompletion": (
                    bool(capabilities.get("statelessCompletion"))
                    if host_negotiated
                    else installed and str(self.config.protocol_version or "") == _PROTOCOL_VERSION
                ),
                "transientContext": bool(capabilities.get("transientContext")),
                "imageAttachments": True,
                "coordinator": True,
                "modelConfigured": self.config.model_configured,
            },
        }

    def _host(self) -> PiRuntimeHostClient:
        with self._lock:
            if self._client is not None and self._client.running:
                return self._client
        if not self.config.enabled:
            raise PiRuntimeError("Pi runtime is disabled")
        if self.config.executable is None:
            raise PiRuntimeError(self.config.installation_error or "managed Pi runtime is not installed")
        client = PiRuntimeHostClient(
            self.config,
            on_event=self._handle_host_event,
            on_exit=self._handle_host_exit,
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
                self._last_error = _redact_runtime_text(str(exc))
            client.stop()
            raise
        with self._lock:
            self._host_capabilities = dict(_mapping(hello.get("capabilities")))
            self._status = "ready"
        return client

    def ensure(self, session_id: str) -> dict[str, object]:
        with self._lifecycle_lock:
            if not self.config.model_configured:
                raise PiRuntimeError(self.config.model_configuration_error or "Pi model is not configured")
            client = self._host()
            with self._lock:
                if session_id in self._open_sessions:
                    self._schedule_idle_locked()
                    return {"state": client.send("session.snapshot", {"sessionId": session_id})}
            session = dict(self.sessions.get(session_id))
            binding = self.sessions.runtime_binding(session_id)
            if binding is not None:
                if binding.get("driverId") != self.driver_id or binding.get("runtimeKind") != self.runtime_kind:
                    raise PiRuntimeError("Agent session belongs to another runtime driver")
                session["_runtimeBinding"] = binding
            if self._session_context_provider is not None:
                session.update(dict(self._session_context_provider(session)))
            roots = [str(value) for value in session.get("workspaceRoots") or [] if str(value).strip()]
            cwd = roots[0] if roots else str(self.config.agent_dir)
            provider, model_id = self.config.resolved_model_reference(session)
            session_file = str((binding or {}).get("transcriptRef") or session.get("sessionFile") or "").strip()
            params: dict[str, object] = {
                "sessionId": session_id,
                "cwd": cwd,
                "systemPrompt": self.config.system_prompt_for_session(session),
                "toolManifest": self.tool_catalog(session_id),
                "noContextFiles": str(session.get("toolProfileVersion") or "")
                in {"ime-surface-v1", "voice-refinement-v1"},
            }
            if provider and model_id:
                params.update({"provider": provider, "modelId": model_id})
            thinking_level = str(session.get("thinkingLevel") or "").strip().lower()
            if thinking_level:
                params["thinkingLevel"] = thinking_level
            if session_file:
                params["sessionFile"] = session_file
            result = client.send("session.open", params, timeout=max(60.0, self.config.command_timeout_seconds))
            snapshot = dict(_mapping(result.get("snapshot")))
            model = _mapping(snapshot.get("model"))
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
            return {"state": snapshot, "session": bound, "evictedSessionId": evicted or None}

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
        normalized_delivery = _message_delivery(delivery)
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
                raise PiRuntimeError("Pi 正在处理上一轮，请等待结束或停止完成后再发送")
            self._cancel_idle_locked()
            state.stream_pi_message_id = ""
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
            self.ensure(session_id)
            snapshot = self._require_client().send("session.snapshot", {"sessionId": session_id})
        except AgentRuntimeError:
            return {"messages": [], "telemetry": None, "messageQueue": None}
        raw_messages = snapshot.get("messages") if isinstance(snapshot.get("messages"), list) else []
        result: list[dict[str, object]] = []
        current_turn_id = ""
        for raw in raw_messages:
            if not isinstance(raw, Mapping) or not _pi_message_is_public(raw):
                continue
            role = str(raw.get("role") or "assistant").lower()
            message_id = _pi_message_id(raw, "history")
            if role == "user" or not current_turn_id:
                current_turn_id = f"history:{message_id}"
            result.append(
                _pi_message_payload(
                    raw,
                    session_id=session_id,
                    turn_id=current_turn_id,
                    media_resolver=self._media_resolver,
                    message_id=message_id,
                ).to_payload()
            )
        telemetry = snapshot.get("telemetry")
        raw_queue = _mapping(snapshot.get("messageQueue"))
        message_queue = {
            "steering": _public_message_queue(raw_queue.get("steering")),
            "followUp": _public_message_queue(raw_queue.get("followUp")),
            "steeringMode": str(raw_queue.get("steeringMode") or ""),
            "followUpMode": str(raw_queue.get("followUpMode") or ""),
        }
        return {
            "messages": result,
            "telemetry": dict(telemetry) if isinstance(telemetry, Mapping) else None,
            "messageQueue": message_queue,
        }

    def debug_context(self, session_id: str, turn_id: str = "") -> dict[str, object]:
        self.ensure(session_id)
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
                snapshot = dict(_mapping(forked.get("snapshot")))
                external_session_id = str(snapshot.get("piSessionId") or "").strip()
                transcript_ref = str(snapshot.get("sessionFile") or "").strip()
                if not external_session_id or not transcript_ref:
                    raise PiRuntimeError("Pi returned an incomplete conversation fork identity")
                branch_candidate = Path(transcript_ref).expanduser()
                if branch_candidate.is_symlink():
                    raise PiRuntimeError("Pi conversation fork file must not be a symlink")
                branch_transcript = branch_candidate.resolve(strict=False)
                session_root = self.config.session_dir.expanduser().resolve(strict=False)
                if not _is_within(branch_transcript, session_root):
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
        if state.pending_approvals or state.pending_reviews:
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
            created_at_ms = _integer(raw.get("createdAtMs"))
            text = _public_fork_candidate_text(raw.get("text"), role=role)
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
        selected = _public_pi_model(_mapping(snapshot.get("model")))
        models = self.available_models()
        return {
            "selected": selected or None,
            "models": models,
            "thinkingLevel": _effective_thinking_level(snapshot.get("thinkingLevel"), selected),
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
            for model in [_public_pi_model(value)]
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
        timeout_seconds: float = 120.0,
    ) -> dict[str, object]:
        normalized_request_id = _model_reference_part(
            request_id,
            field="requestId",
            maximum=200,
        )
        normalized_provider = _model_reference_part(provider, field="provider", maximum=80)
        normalized_model = _model_reference_part(model_id, field="modelId", maximum=160)
        normalized_thinking = str(thinking_level or "").strip().lower()
        if normalized_thinking not in {"off", "low"}:
            raise ValueError("stateless Pi completion only supports off or low thinking")
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
                self._status = "busy"
        try:
            return client.send(
                "completion.once",
                params,
                timeout=bounded_timeout + 5.0,
            )
        finally:
            with self._lock:
                self._active_completion_ids.discard(normalized_request_id)
                if not any(state.turn_id for state in self._states.values()):
                    self._status = "ready"
                self._schedule_idle_locked()

    def cancel_completion(self, request_id: str) -> bool:
        try:
            normalized = _model_reference_part(request_id, field="requestId", maximum=200)
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
        normalized_provider = _model_reference_part(provider, field="provider", maximum=80)
        normalized_model = _model_reference_part(model_id, field="modelId", maximum=160)
        self.ensure(session_id)
        selected = _public_pi_model(
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

    def abort(self, session_id: str) -> None:
        client = self._require_client()
        with self._lock:
            state = self._states.setdefault(session_id, _HostedSessionState())
            turn_id = state.turn_id
            if not turn_id:
                self.sessions.set_status(session_id, "idle")
                return
            # Mark the exact turn before sending the RPC. The host is allowed
            # to emit agent_settled before the abort ACK reaches this thread.
            state.abort_requested_turn_id = turn_id
        try:
            client.send("session.abort", {"sessionId": session_id})
        except Exception:
            with self._lock:
                state = self._states.get(session_id)
                if state is not None and state.abort_requested_turn_id == turn_id:
                    state.abort_requested_turn_id = ""
            raise
        with self._lock:
            state = self._states.setdefault(session_id, _HostedSessionState())
            # The host can emit agent_settled before the abort ACK arrives.
            # Do not regress an already terminal turn back to "aborting".
            if state.turn_id != turn_id:
                return
            if state.abort_timer is not None:
                state.abort_timer.cancel()
            self.events.publish(session_id, "status_changed", {"status": "aborting"}, turn_id=turn_id)
            timer = threading.Timer(1.0, self._abort_fallback_expired, args=(session_id, turn_id))
            timer.daemon = True
            state.abort_timer = timer
            timer.start()

    def compact(self, session_id: str, instructions: str = "") -> dict[str, object]:
        self.ensure(session_id)
        result = self._require_client().send(
            "session.compact",
            {"sessionId": session_id, "instructions": str(instructions).strip()[:2000]},
            timeout=max(60.0, self.config.command_timeout_seconds),
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

    def plugin_list(self) -> list[dict[str, object]]:
        return [dict(value) for value in self._require_host_result("plugins.list").get("plugins") or [] if isinstance(value, Mapping)]

    def plugin_create(self, payload: Mapping[str, object]) -> dict[str, object]:
        return self._require_host_result("plugins.create", payload)

    def plugin_validate(self, source_path: str) -> dict[str, object]:
        return self._require_host_result("plugins.validate", {"sourcePath": source_path})

    def plugin_install(self, payload: Mapping[str, object]) -> dict[str, object]:
        return self._require_host_result("plugins.install", {**dict(payload), "approvalToken": self.config.tool_gateway_token})

    def plugin_enable(self, plugin_id: str, *, enabled: bool) -> dict[str, object]:
        return self._require_host_result(
            "plugins.enable" if enabled else "plugins.disable",
            {"pluginId": plugin_id, "approvalToken": self.config.tool_gateway_token},
        )

    def plugin_rollback(self, plugin_id: str) -> dict[str, object]:
        return self._require_host_result(
            "plugins.rollback",
            {"pluginId": plugin_id, "approvalToken": self.config.tool_gateway_token},
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
                self._states.clear()
                self._status = "stopped" if self.config.enabled else "disabled"
            if client is not None:
                client.stop()
            for session_id in session_ids:
                try:
                    self.sessions.set_status(session_id, "idle")
                except KeyError:
                    pass

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
        session_id = str(envelope.get("sessionId") or "")
        if not session_id:
            return
        raw = dict(_mapping(envelope.get("payload")))
        turn_id = str(envelope.get("turnId") or "")
        client_message_id = str(envelope.get("clientMessageId") or "")
        event_type = str(raw.get("type") or "")
        with self._lock:
            state = self._states.setdefault(session_id, _HostedSessionState())
            if turn_id and turn_id in state.retired_turn_ids:
                return
            if turn_id:
                state.turn_id = turn_id
            if client_message_id:
                state.client_message_id = client_message_id
        if event_type == "message_update":
            update = _mapping(raw.get("assistantMessageEvent"))
            update_type = str(update.get("type") or "")
            if update_type == "text_delta":
                raw_message = _mapping(raw.get("message"))
                pi_message_id = _pi_message_id(raw_message, turn_id)
                with self._lock:
                    replace_block = pi_message_id != state.stream_pi_message_id
                    state.stream_pi_message_id = pi_message_id
                self.events.publish(
                    session_id,
                    "text_delta",
                    {
                        "messageId": f"{turn_id}:assistant",
                        "blockId": f"{turn_id}:assistant:text",
                        "contentIndex": _integer(update.get("contentIndex")),
                        "delta": str(update.get("delta") or ""),
                        "replaceBlock": replace_block,
                    },
                    turn_id=turn_id,
                )
            elif update_type == "thinking_start":
                self.events.publish(session_id, "status_changed", {"status": "analyzing"}, turn_id=turn_id)
            return
        if event_type == "message_end":
            raw_message = _mapping(raw.get("message"))
            if not _pi_message_is_public(raw_message) or str(raw_message.get("role") or "").lower() == "user":
                return
            role = str(raw_message.get("role") or "assistant").lower()
            message = _pi_message_payload(
                raw_message,
                session_id=session_id,
                turn_id=turn_id,
                media_resolver=self._media_resolver,
                message_id=f"{turn_id}:assistant" if role == "assistant" else None,
            )
            self.events.publish(
                session_id,
                "message_completed",
                {
                    "message": message.to_payload(),
                    "usage": _public_usage(raw.get("message")),
                    "telemetry": dict(_mapping(raw.get("telemetry"))),
                },
                turn_id=turn_id,
            )
            return
        if event_type == "queue_update":
            self.events.publish(
                session_id,
                "message_queue_updated",
                {
                    "steering": _public_message_queue(raw.get("steering")),
                    "followUp": _public_message_queue(raw.get("followUp")),
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
                    "telemetry": dict(_mapping(raw.get("telemetry"))),
                },
                turn_id=turn_id,
            )
            return
        if event_type == "compaction_end":
            result = _mapping(raw.get("result"))
            payload: dict[str, object] = {
                "reason": str(raw.get("reason") or "threshold"),
                "aborted": bool(raw.get("aborted")),
                "willRetry": bool(raw.get("willRetry")),
                "tokensBefore": _integer(result.get("tokensBefore")),
                "estimatedTokensAfter": _integer(result.get("estimatedTokensAfter")),
                "telemetry": dict(_mapping(raw.get("telemetry"))),
            }
            if raw.get("errorMessage"):
                payload["error"] = _redact_runtime_text(str(raw.get("errorMessage")))
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
        if event_type in {"tool_execution_start", "tool_execution_update", "tool_execution_end"}:
            mapped_type = {
                "tool_execution_start": "tool_started",
                "tool_execution_update": "tool_progress",
                "tool_execution_end": "tool_finished",
            }[event_type]
            raw_args = _mapping(raw.get("args"))
            tool_name = str(raw.get("toolName") or "")
            payload: dict[str, object] = {
                "toolCallId": str(raw.get("toolCallId") or ""),
                "toolName": tool_name,
                "args": _redact_mapping(raw_args),
                "isError": bool(raw.get("isError")),
            }
            public_result = _public_code_tool_activity(tool_name, raw_args)
            if public_result:
                payload["publicResult"] = public_result
            result_key = "partialResult" if event_type == "tool_execution_update" else "result"
            if raw.get(result_key) is not None:
                payload[result_key] = _redact_mapping(_mapping(raw.get(result_key)))
            self.events.publish(session_id, mapped_type, payload, turn_id=turn_id)
            return
        if event_type == "extension_ui_request":
            self._handle_ui_request(session_id, turn_id, raw)
            return
        if event_type == "agent_end":
            messages = raw.get("messages") if isinstance(raw.get("messages"), list) else []
            with self._lock:
                state.last_agent_messages = list(messages)
                state.final_error = "" if raw.get("willRetry") is True else _last_assistant_error(messages)
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
                    state.last_agent_messages = []
                    state.final_error = ""
                    state.abort_requested_turn_id = ""
                    state.pending_approvals.clear()
                    state.pending_reviews.clear()
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
                last_message_preview=_last_assistant_preview(messages),
            )
            self.events.publish(
                session_id,
                "turn_completed",
                {"messageCount": len(messages), "terminalEvent": "agent_settled"},
                turn_id=turn_id,
            )
            return
        if event_type == "extension_error":
            self._turn_failed(session_id, turn_id, PiRuntimeError(str(raw.get("error") or "Pi extension failed")))

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
                "error": _redact_runtime_text(str(exc)),
            }
        return dict(checkpoint or {})

    def _handle_ui_request(self, session_id: str, turn_id: str, raw: Mapping[str, object]) -> None:
        method = str(raw.get("method") or "")
        request_id = str(raw.get("id") or "")
        title = str(raw.get("title") or "")
        with self._lock:
            state = self._states.setdefault(session_id, _HostedSessionState())
        if method == "confirm" and title.startswith(_APPROVAL_TITLE_PREFIX):
            approval_id = title[len(_APPROVAL_TITLE_PREFIX) :].strip()
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
        if method == "confirm" and title.startswith(_REVIEW_TITLE_PREFIX):
            run_id = title[len(_REVIEW_TITLE_PREFIX) :].strip()
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
            self.events.publish(
                session_id,
                "user_input_required",
                {
                    "requestId": request_id,
                    "method": method,
                    "title": title[:160],
                    "message": str(raw.get("message") or "")[:500],
                },
                turn_id=turn_id,
            )

    def _turn_failed(self, session_id: str, turn_id: str, error: BaseException) -> None:
        message = _redact_runtime_text(str(error))
        with self._lock:
            state = self._states.setdefault(session_id, _HostedSessionState())
            if state.abort_timer is not None:
                state.abort_timer.cancel()
                state.abort_timer = None
            state.turn_id = ""
            state.client_message_id = ""
            state.stream_pi_message_id = ""
            state.abort_requested_turn_id = ""
            state.pending_approvals.clear()
            state.pending_reviews.clear()
            self._last_error = message
            self._status = "ready" if self._client is not None and self._client.running else "faulted"
            self._schedule_idle_locked()
        self.sessions.set_status(session_id, "faulted", last_message_preview=message)
        self.events.publish(session_id, "turn_failed", {"error": message}, turn_id=turn_id)

    def _handle_host_exit(self, exit_code: int | None, error: str) -> None:
        with self._lock:
            if self._intentional_stop:
                return
            message = _redact_runtime_text(error or f"Pi Runtime Host exited with code {exit_code}")
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
            self.events.publish(session_id, "turn_failed", {"error": message}, turn_id=turn_id)

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
            if len(state.retired_turn_ids) >= 64:
                state.retired_turn_ids.pop()
            state.retired_turn_ids.add(turn_id)
            state.turn_id = ""
            state.client_message_id = ""
            state.stream_pi_message_id = ""
            state.last_agent_messages = []
            state.final_error = ""
            state.abort_requested_turn_id = ""
            state.pending_approvals.clear()
            state.pending_reviews.clear()
            self._status = "ready"
            self._schedule_idle_locked()
            self.sessions.set_status(session_id, "idle")
            self.events.publish(
                session_id,
                "turn_completed",
                {"status": "aborted", "aborted": True, "terminalEvent": "abort_timeout"},
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
