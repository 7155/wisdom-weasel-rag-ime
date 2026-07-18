from __future__ import annotations

import hashlib
import json
import os
import queue
import re
import subprocess
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import quote, urlsplit

from .agent_events import AgentEventHub
from .agent_tool_ids import (
    ASSISTANT_CONTROL_TOOL_IDS,
    CONTROL_TOOL_IDS,
    COORDINATOR_TOOL_IDS,
    DANGEROUS_AUTO_APPROVE_TOOL_PROFILE,
)
from .agent_protocol import AgentBlock, AgentMessage, normalize_agent_block
from .agent_runtime_driver import (
    AgentRuntimeError,
    AgentRuntimePolicy,
    AgentRuntimeDriver,
    CompactionObserver,
    RuntimeDriverContext,
    SessionContextProvider,
)
from .agent_roles import PersonaManifest, agent_role
from .agent_sessions import AgentSessionStore
from .agent_templates import agent_template
from .deepseek_config import load_deepseek_config
from .managed_pi_runtime import ManagedPiRuntimeError, discover_managed_pi_runtime
from .pi_provider_config import PiProviderConfigError, load_pi_provider_config


class PiRuntimeError(AgentRuntimeError):
    pass


_READ_ONLY_CONTROL_TOOLS = ASSISTANT_CONTROL_TOOL_IDS
_COORDINATOR_TOOLS = COORDINATOR_TOOL_IDS
_SUBAGENT_READ_ONLY_TOOLS = (
    "ime_overview",
    "ime_memory",
    "ime_knowledge",
    "ime_models",
    "ime_runtime",
    "ime_agents",
    "agent_plan",
    "workspace_list",
    "workspace_read",
    "workspace_search",
)
_APPROVAL_TITLE_PREFIX = "RAG-IME-APPROVAL:"
_REVIEW_TITLE_PREFIX = "RAG-IME-REVIEW:"
_MAX_PERSISTED_TRANSCRIPT_BYTES = 64 * 1024 * 1024
_MAX_PERSISTED_TRANSCRIPT_ENTRIES = 100_000
_MAX_PERSISTED_TRANSCRIPT_LINE_BYTES = 4 * 1024 * 1024
_IME_SURFACE_SYSTEM_PROMPT = """你是输入法中的连续联想引擎，只处理用户明确点击触发的文字生成。

输出规则：
- 只输出可以直接插入光标或替换选区的正文，不解释过程，不加标题、引号、Markdown 围栏或候选编号。
- 延续当前文字的语言、语气、时态与格式；需要改写时只返回改写结果。
- 请求附带当前应用截图时，把可见界面作为辅助上下文，但不要复述界面、泄露无关内容或猜测不可见信息。
- 没有足够上下文时给出最保守、最短的自然续写，不调用工具，也不声称执行了任何操作。
"""
_VOICE_REFINEMENT_SYSTEM_PROMPT = """你是语音转写的第三遍文字校对器。

只输出校对后的原文，不解释、不回答原文中的问题、不使用 Markdown。
只修正有把握的识别错误、口头重复、无意义语气词、标点和空格。
必须保留原意、事实、语气、人称、数字、英文、代码和专有名词；不得扩写、总结或补充信息。
"""


def _empty_role_book_prompt(_session: Mapping[str, object]) -> str:
    return ""


def _tools_for_session(
    available: tuple[str, ...],
    session: Mapping[str, object],
) -> tuple[str, ...]:
    selected = available
    if str(session.get("toolAllowlistMode") or "profile") == "explicit":
        explicit = {str(value) for value in session.get("allowedTools") or []}
        selected = tuple(tool for tool in selected if tool in explicit)
    mode = str(session.get("mode") or "assistant")
    profile = str(session.get("toolProfileVersion") or "control-center-v1")
    if profile == "subagent-readonly-v1":
        allowed = set(_SUBAGENT_READ_ONLY_TOOLS)
        return tuple(tool for tool in selected if tool in allowed)
    return tuple(
        tool
        for tool in selected
        if mode == "coordinator" or tool not in _COORDINATOR_TOOLS
    )


@dataclass(frozen=True)
class PiRuntimeConfig:
    enabled: bool
    executable: Path | None
    agent_dir: Path
    session_dir: Path
    logs_dir: Path
    debug_context_dir: Path | None = None
    debug_context_max_bytes: int = 1024 * 1024 * 1024
    node_executable: str = "node"
    idle_timeout_seconds: int = 900
    command_timeout_seconds: float = 15.0
    provider: str = ""
    model: str = ""
    extension_path: Path | None = None
    tools: tuple[str, ...] = ()
    tool_gateway_url: str = "http://127.0.0.1:8766/api/agent/tool/execute"
    tool_gateway_token: str = ""
    provider_environment: Mapping[str, str] = field(default_factory=dict, repr=False)
    model_providers: Mapping[str, Mapping[str, object]] = field(default_factory=dict, repr=False)
    model_base_url: str = ""
    model_configured: bool = True
    model_configuration_error: str = ""
    pi_version: str = "0.80.2"
    installation_error: str = ""
    protocol_version: str = "1"
    max_sessions: int = 8
    role_resolver: Callable[[object, object], PersonaManifest] = field(
        default=agent_role,
        repr=False,
        compare=False,
    )
    role_book_resolver: Callable[[Mapping[str, object]], str] = field(
        default=_empty_role_book_prompt,
        repr=False,
        compare=False,
    )

    @classmethod
    def from_environment(
        cls,
        *,
        enabled_default: bool = False,
        idle_timeout_default: int = 900,
    ) -> PiRuntimeConfig:
        app_support = Path(
            os.environ.get("RAG_IME_APP_SUPPORT_DIR")
            or Path.home() / "Library" / "Application Support" / "RagIme"
        ).expanduser()
        executable_value = os.environ.get("RAG_IME_PI_EXECUTABLE", "").strip()
        extension_value = os.environ.get("RAG_IME_PI_EXTENSION", "").strip()
        debug_context_value = os.environ.get("RAG_IME_PI_DEBUG_CONTEXT_DIR", "").strip()
        node_value = os.environ.get("RAG_IME_PI_NODE", "").strip()
        expected_pi_version = os.environ.get("RAG_IME_PI_VERSION", "0.80.7").strip() or "0.80.7"
        development_tools = tuple(
            item.strip()
            for item in os.environ.get(
                "RAG_IME_PI_TOOLS",
                ",".join(CONTROL_TOOL_IDS),
            ).split(",")
            if item.strip()
        )
        executable: Path | None = None
        extension: Path | None = None
        node_executable = ""
        tools: tuple[str, ...] = ()
        pi_version = expected_pi_version
        installation_error = ""
        protocol_version = os.environ.get("RAG_IME_PI_PROTOCOL_VERSION", "").strip()
        if executable_value:
            # Explicit executable overrides are for source-tree development only.
            # Product discovery never falls back to PATH or a user's global Pi.
            executable = Path(executable_value).expanduser()
            extension = Path(extension_value).expanduser() if extension_value else None
            node_executable = node_value or "node"
            tools = development_tools if extension is not None else ()
        elif node_value or extension_value:
            installation_error = (
                "development Pi node/extension overrides require RAG_IME_PI_EXECUTABLE"
            )
        else:
            try:
                installation = discover_managed_pi_runtime(
                    app_support,
                    expected_pi_version=expected_pi_version,
                )
            except ManagedPiRuntimeError as exc:
                installation_error = str(exc)
            else:
                executable = installation.executable
                extension = installation.extension_path
                node_executable = installation.node_executable
                tools = installation.tools
                pi_version = installation.pi_version
                protocol_version = protocol_version or installation.protocol_version
        provider, model, model_base_url, provider_environment, model_providers, model_error = (
            _pi_model_configuration_from_environment()
        )
        return cls(
            enabled=_env_bool("RAG_IME_PI_ENABLED", enabled_default),
            executable=executable,
            agent_dir=app_support / "Agent" / "config",
            session_dir=app_support / "Agent" / "sessions",
            logs_dir=app_support / "Agent" / "logs",
            debug_context_dir=(
                Path(debug_context_value).expanduser()
                if debug_context_value
                else app_support / "Agent" / "debug-context"
            ),
            debug_context_max_bytes=_env_int(
                "RAG_IME_PI_DEBUG_CONTEXT_MAX_BYTES",
                1024 * 1024 * 1024,
                minimum=1,
                maximum=1024 * 1024 * 1024,
            ),
            node_executable=node_executable,
            idle_timeout_seconds=_env_int(
                "RAG_IME_PI_IDLE_TIMEOUT_SECONDS",
                idle_timeout_default,
                minimum=0,
                maximum=86400,
            ),
            command_timeout_seconds=float(
                _env_int("RAG_IME_PI_COMMAND_TIMEOUT_SECONDS", 15, minimum=1, maximum=300)
            ),
            provider=provider,
            model=model,
            extension_path=extension,
            tools=tools,
            tool_gateway_url=(
                os.environ.get("RAG_IME_AGENT_TOOL_URL", "").strip()
                or "http://127.0.0.1:8766/api/agent/tool/execute"
            ),
            pi_version=pi_version,
            installation_error=installation_error,
            protocol_version=protocol_version or "1",
            max_sessions=_env_int("RAG_IME_PI_MAX_SESSIONS", 8, minimum=1, maximum=32),
            provider_environment=provider_environment,
            model_providers=model_providers,
            model_base_url=model_base_url,
            model_configured=not bool(model_error),
            model_configuration_error=model_error,
        )

    def launch_command(self, *, session: Mapping[str, object]) -> list[str]:
        if self.executable is None:
            raise PiRuntimeError("managed Pi runtime is not installed")
        executable = self.executable.expanduser().resolve(strict=False)
        if not executable.is_file():
            raise PiRuntimeError("managed Pi executable does not exist")
        command = (
            [self.node_executable, str(executable)]
            if executable.suffix.lower() in {".js", ".mjs", ".cjs"}
            else [str(executable)]
        )
        if executable.suffix.lower() in {".js", ".mjs", ".cjs"} and not self.node_executable:
            raise PiRuntimeError("managed Pi Node runtime is unavailable")
        command.extend(
            [
                "--mode",
                "rpc",
                "--session-dir",
                str(self.session_dir),
                "--no-context-files",
                "--no-approve",
                "--no-extensions",
                "--no-skills",
                "--no-prompt-templates",
                "--no-themes",
                "--offline",
            ]
        )
        if self.extension_path is None:
            command.append("--no-tools")
        else:
            extension = self.extension_path.expanduser().resolve(strict=False)
            if not extension.is_file():
                raise PiRuntimeError("managed Pi extension does not exist")
            command.extend(["--no-builtin-tools", "-e", str(extension)])
            if self.tools:
                selected_tools = _tools_for_session(self.tools, session)
                command.extend(["--tools", ",".join(selected_tools)])
        runtime_binding = session.get("_runtimeBinding")
        session_file = ""
        if isinstance(runtime_binding, Mapping):
            if (
                str(runtime_binding.get("driverId") or "") != "managed-pi"
                or str(runtime_binding.get("runtimeKind") or "") != "pi_rpc"
            ):
                raise PiRuntimeError("Agent session belongs to another runtime driver")
            session_file = str(runtime_binding.get("transcriptRef") or "").strip()
        if not session_file:
            # Compatibility fallback for databases created before RuntimeBinding.
            session_file = str(session.get("sessionFile") or "").strip()
        if session_file:
            resolved_session = Path(session_file).expanduser().resolve(strict=False)
            session_root = self.session_dir.expanduser().resolve(strict=False)
            if not _is_within(resolved_session, session_root):
                raise PiRuntimeError("Pi session file is outside the managed session directory")
            if resolved_session.is_file():
                command.extend(["--session", str(resolved_session)])
        title = " ".join(str(session.get("title") or "智鼬").split())[:120]
        if title:
            command.extend(["--name", title])
        command.extend(["--system-prompt", self.system_prompt_for_session(session)])
        selected_provider, selected_model = self.resolved_model_reference(session)
        if selected_provider:
            command.extend(["--provider", selected_provider])
        if selected_model:
            command.extend(["--model", selected_model])
        return command

    def launch_host_command(self) -> list[str]:
        if self.executable is None:
            raise PiRuntimeError("managed Pi runtime is not installed")
        executable = self.executable.expanduser().resolve(strict=False)
        if not executable.is_file():
            raise PiRuntimeError("managed Pi executable does not exist")
        if executable.suffix.lower() in {".js", ".mjs", ".cjs"}:
            if not self.node_executable:
                raise PiRuntimeError("managed Pi Node runtime is unavailable")
            return [self.node_executable, str(executable)]
        return [str(executable)]

    def system_prompt_for_session(self, session: Mapping[str, object]) -> str:
        tool_profile = str(session.get("toolProfileVersion") or "")
        if tool_profile == "ime-surface-v1":
            return _IME_SURFACE_SYSTEM_PROMPT
        if tool_profile == "voice-refinement-v1":
            return _VOICE_REFINEMENT_SYSTEM_PROMPT
        role = self.role_resolver(
            session.get("roleId") or "zhiyou-v1",
            session.get("roleVersion") or "1",
        )
        system_prompt = role.system_prompt
        template_id = str(session.get("agentTemplateId") or "").strip()
        if template_id:
            template = agent_template(
                template_id,
                session.get("agentTemplateVersion") or "1",
            )
            system_prompt = (
                f"{system_prompt.rstrip()}\n\n"
                "你当前是一次有界任务委派中的临时执行单元，不是长期群聊成员。\n"
                f"{template.prompt.strip()}\n"
            )
        role_book_prompt = str(self.role_book_resolver(session) or "").strip()
        if role_book_prompt:
            system_prompt = (
                f"{system_prompt.rstrip()}\n\n"
                "<agent-role-book>\n"
                f"{role_book_prompt}\n"
                "</agent-role-book>\n"
            )
        if str(self.protocol_version or "") == "2":
            system_prompt = (
                f"{system_prompt.rstrip()}\n\n"
                "运行时工具渐进披露规则：\n"
                "- Provider 工具列表只表示本轮已经披露的参数 schema，不代表授权范围；"
                "tool_load 也不授予权限。最终能否执行始终由当前 Session 策略和控制中心网关决定。\n"
                "- 不熟悉目标工具的精确名称或参数时，先调用 tool_search，再对唯一需要的工具调用 tool_load。"
                "不要为预热、激活或盘点而批量加载全部工具，这会浪费上下文。\n"
                "- 若当前对话已经给出仍然准确的工具名与参数，可以直接调用；"
                "运行时会在已授权目录中解析它。解析失败时再 search/load，不要反复尝试不存在的名称。\n"
            )
        if session.get("toolProfileVersion") == DANGEROUS_AUTO_APPROVE_TOOL_PROFILE:
            system_prompt = (
                f"{system_prompt.rstrip()}\n\n"
                "当前 Session 已由用户在原生界面明确启用“完全信任”。受控工具仍会生成结构化预览、"
                "校验哈希、执行边界检查并留下回执，但符合策略的写操作将自动批准，不再逐项等待弹窗。"
                "不要因此扩大任务范围，也不得绕过工作区、路径、备份、审计或回滚约束。\n"
            )
        return system_prompt

    def resolved_model_reference(self, session: Mapping[str, object]) -> tuple[str, str]:
        session_provider, session_model = _split_model_reference(session.get("modelProfile"))
        selected_provider = session_provider or self.provider
        selected_model = session_model or self.model
        configured_ids = _configured_model_ids(self.model_providers.get(selected_provider))
        if configured_ids and selected_model not in configured_ids:
            # Pi/provider configuration is the only model catalog authority.
            # Persona names are not model aliases and must not participate in
            # compatibility fallback.
            if self.provider == selected_provider and self.model in configured_ids:
                selected_model = self.model
            else:
                selected_model = configured_ids[0]
        return selected_provider, selected_model

    def child_environment(self, *, session: Mapping[str, object] | None = None) -> dict[str, str]:
        allowed = ("HOME", "PATH", "TMPDIR", "LANG", "LC_ALL", "SSL_CERT_FILE", "SSL_CERT_DIR")
        environment = {key: os.environ[key] for key in allowed if os.environ.get(key)}
        environment.update({str(key): str(value) for key, value in self.provider_environment.items()})
        environment["RAG_IME_APP_SUPPORT_DIR"] = str(self.agent_dir.parent.parent)
        environment["PI_CODING_AGENT_DIR"] = str(self.agent_dir)
        environment["RAG_IME_PI_AGENT_DIR"] = str(self.agent_dir)
        environment["RAG_IME_PI_SESSION_DIR"] = str(self.session_dir)
        if self.debug_context_dir is not None:
            environment["RAG_IME_PI_DEBUG_CONTEXT_DIR"] = str(self.debug_context_dir)
            environment["RAG_IME_PI_DEBUG_CONTEXT_MAX_BYTES"] = str(
                min(1024 * 1024 * 1024, max(1, int(self.debug_context_max_bytes)))
            )
        environment["RAG_IME_PI_MAX_SESSIONS"] = str(self.max_sessions)
        if self.tool_gateway_token:
            environment["RAG_IME_AGENT_TOOL_TOKEN"] = self.tool_gateway_token
            environment["RAG_IME_AGENT_TOOL_URL"] = self.tool_gateway_url
            environment["RAG_IME_TOOL_GATEWAY_TOKEN"] = self.tool_gateway_token
            environment["RAG_IME_TOOL_GATEWAY_URL"] = self.tool_gateway_url
            environment["RAG_IME_PLUGIN_APPROVAL_TOKEN"] = self.tool_gateway_token
        if session is not None:
            environment["RAG_IME_AGENT_SESSION_ID"] = str(session.get("id") or "")
            environment["RAG_IME_AGENT_SESSION_MODE"] = str(session.get("mode") or "assistant")
            environment["RAG_IME_AGENT_TOOL_PROFILE_VERSION"] = str(
                session.get("toolProfileVersion") or "control-center-v1"
            )
            environment["RAG_IME_AGENT_DELEGATION_DEPTH"] = str(
                session.get("delegationDepth") or 0
            )
        return environment

    def prepare_agent_config(self) -> None:
        if not self.model_configured:
            return
        self.agent_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.agent_dir.is_symlink():
            raise PiRuntimeError("managed Pi agent directory must not be a symlink")
        os.chmod(self.agent_dir, 0o700)
        target = self.agent_dir / "models.json"
        if target.is_symlink():
            raise PiRuntimeError("managed Pi models.json must not be a symlink")
        providers = dict(self.model_providers)
        if not providers and self.provider == "deepseek" and self.model_base_url:
            providers = {
                "deepseek": _deepseek_pi_provider(
                    self.model_base_url,
                    model=self.model,
                ),
            }
        if not providers:
            return
        payload = {"providers": providers}
        encoded = (json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n").encode("utf-8")
        for secret in self.provider_environment.values():
            if secret and secret.encode("utf-8") in encoded:
                raise PiRuntimeError("managed Pi models.json must not contain provider credentials")
        temporary = self.agent_dir / f".models.json.tmp-{uuid.uuid4().hex}"
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
            os.chmod(target, 0o600)
        finally:
            if temporary.exists():
                temporary.unlink()


class PiRuntimeDriverFactory:
    """Pi-specific construction kept behind the runtime-neutral factory contract."""

    runtime_kind = "pi_rpc"
    driver_id = "managed-pi"

    def __init__(self, config: PiRuntimeConfig):
        self._config = config

    @property
    def session_root(self) -> Path:
        return self._config.session_dir

    @property
    def working_root(self) -> Path:
        return self._config.agent_dir

    @property
    def default_model_profile(self) -> str:
        provider = str(self._config.provider or "").strip()
        model = str(self._config.model or "").strip()
        return f"{provider}/{model}" if provider and model else "pi/default"

    @property
    def config(self) -> PiRuntimeConfig:
        return self._config

    def create(
        self,
        context: RuntimeDriverContext,
        *,
        purpose: str,
        session_context_provider: SessionContextProvider | None = None,
    ) -> AgentRuntimeDriver:
        if purpose not in {"interactive", "delegated"}:
            raise ValueError("runtime driver purpose must be interactive or delegated")
        config = replace(
            self._config,
            tool_gateway_token=context.tool_gateway_token,
            tool_gateway_url=context.tool_gateway_url,
            idle_timeout_seconds=(
                0 if purpose == "delegated" else self._config.idle_timeout_seconds
            ),
        )
        if config.protocol_version == "2":
            from .pi_runtime_v2 import PiRuntimeHostManager

            return PiRuntimeHostManager(
                config=config,
                sessions=context.sessions,
                events=context.events,
                media_resolver=context.media_resolver,
                session_context_provider=session_context_provider,
                tool_manifest_provider=context.tool_manifest_provider,
                compaction_observer=context.compaction_observer,
            )
        return PiRuntimeManager(
            config=config,
            sessions=context.sessions,
            events=context.events,
            media_resolver=context.media_resolver,
            session_context_provider=session_context_provider,
            tool_manifest_provider=context.tool_manifest_provider,
            compaction_observer=context.compaction_observer,
        )

    def reconfigure(self, config: object) -> None:
        if not isinstance(config, PiRuntimeConfig):
            raise TypeError("Pi runtime factory requires PiRuntimeConfig")
        self._config = config

    def apply_policy(self, policy: AgentRuntimePolicy) -> None:
        if not isinstance(policy, AgentRuntimePolicy):
            raise TypeError("Pi runtime factory requires AgentRuntimePolicy")
        self._config = replace(
            self._config,
            enabled=policy.enabled,
            idle_timeout_seconds=policy.idle_timeout_seconds,
        )


class PiRpcClient:
    def __init__(
        self,
        config: PiRuntimeConfig,
        *,
        session: Mapping[str, object],
        on_event: Callable[[dict[str, object]], None],
        on_exit: Callable[[int | None, str], None],
    ) -> None:
        self.config = config
        self.session = dict(session)
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
                raise PiRuntimeError("Pi RPC process is already running")
            self.config.agent_dir.mkdir(parents=True, exist_ok=True)
            self.config.session_dir.mkdir(parents=True, exist_ok=True)
            self.config.logs_dir.mkdir(parents=True, exist_ok=True)
            self.config.prepare_agent_config()
            command = self.config.launch_command(session=self.session)
            try:
                self._process = subprocess.Popen(
                    command,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=self.config.agent_dir,
                    env=self.config.child_environment(session=self.session),
                    bufsize=0,
                )
            except OSError as exc:
                raise PiRuntimeError(f"failed to start managed Pi runtime: {exc}") from exc
            self._stopping = False
            self._stdout_thread = threading.Thread(target=self._read_stdout, name="rag-ime-pi-stdout", daemon=True)
            self._stderr_thread = threading.Thread(target=self._read_stderr, name="rag-ime-pi-stderr", daemon=True)
            self._stdout_thread.start()
            self._stderr_thread.start()
        return self.send({"type": "get_state"}, timeout=self.config.command_timeout_seconds)

    def send(self, command: Mapping[str, object], *, timeout: float | None = None) -> dict[str, object]:
        request = dict(command)
        request_id = str(request.get("id") or uuid.uuid4())
        request["id"] = request_id
        response_queue: queue.Queue[object] = queue.Queue(maxsize=1)
        with self._lock:
            process = self._process
            if process is None or process.poll() is not None or process.stdin is None:
                raise PiRuntimeError("Pi RPC process is not running")
            self._pending[request_id] = response_queue
        try:
            self._write_record(process, request)
        except (BrokenPipeError, OSError) as exc:
            with self._lock:
                self._pending.pop(request_id, None)
            raise PiRuntimeError("Pi RPC stdin closed") from exc
        try:
            response = response_queue.get(timeout=timeout or self.config.command_timeout_seconds)
        except queue.Empty as exc:
            with self._lock:
                self._pending.pop(request_id, None)
            raise PiRuntimeError(f"Pi RPC command timed out: {request.get('type')}") from exc
        if isinstance(response, BaseException):
            raise PiRuntimeError(str(response))
        assert isinstance(response, dict)
        if response.get("success") is not True:
            raise PiRuntimeError(str(response.get("error") or f"Pi RPC command failed: {request.get('type')}"))
        return response

    def respond_extension_ui(self, request_id: str, *, confirmed: bool) -> None:
        request = {
            "type": "extension_ui_response",
            "id": str(request_id),
            "confirmed": bool(confirmed),
        }
        with self._lock:
            process = self._process
            if process is None or process.poll() is not None or process.stdin is None:
                raise PiRuntimeError("Pi RPC process is not running")
        try:
            self._write_record(process, request)
        except (BrokenPipeError, OSError) as exc:
            raise PiRuntimeError("Pi RPC stdin closed") from exc

    def _write_record(self, process: subprocess.Popen[bytes], request: Mapping[str, object]) -> None:
        encoded = json.dumps(dict(request), ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
        with self._write_lock:
            if process.stdin is None:
                raise BrokenPipeError("Pi RPC stdin is unavailable")
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
        self._fail_pending(PiRuntimeError("Pi RPC process stopped"))
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
                    raise ValueError("RPC record is not an object")
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                protocol_error = f"invalid Pi RPC JSONL: {exc}"
                continue
            if value.get("type") == "response" and value.get("id"):
                with self._lock:
                    waiter = self._pending.pop(str(value["id"]), None)
                if waiter is not None:
                    waiter.put_nowait(value)
                continue
            try:
                self.on_event(value)
            except Exception as exc:  # Keep the protocol reader alive if a UI adapter fails.
                protocol_error = f"Pi event adapter failed: {exc}"
        exit_code = process.poll()
        if exit_code is None:
            try:
                exit_code = process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                exit_code = None
        error = protocol_error or self.diagnostic_error()
        self._fail_pending(PiRuntimeError(error or "Pi RPC process exited"))
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


class PiRuntimeManager:
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
        self._client: PiRpcClient | None = None
        self._active_session_id = ""
        self._active_turn_id = ""
        self._active_client_message_id = ""
        self._status = "stopped" if config.enabled else "disabled"
        self._last_error = ""
        self._idle_timer: threading.Timer | None = None
        self._abort_timer: threading.Timer | None = None
        self._aborting_turn_id = ""
        self._intentional_stop = False
        self._pending_approval_requests: dict[str, str] = {}
        self._pending_review_requests: dict[str, str] = {}
        self._last_pi_entry_id = ""
        # Pi emits one assistant message before every tool call. The product UI
        # presents those messages as one Agent turn, not as a stack of avatars.
        self._stream_pi_message_id = ""

    @property
    def runtime_kind(self) -> str:
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
            status = self._status
            active_session = self._active_session_id or None
            last_error = self._last_error
        if self.config.enabled and not installed:
            status = "not_installed"
            if not last_error:
                last_error = _redact_runtime_text(self.config.installation_error)
        elif self.config.enabled and installed and not self.config.model_configured:
            status = "needs_configuration"
            if not last_error:
                last_error = _redact_runtime_text(self.config.model_configuration_error)
        return {
            "schemaVersion": "rag-ime.agent-runtime.v1",
            "enabled": self.config.enabled,
            "managed": True,
            "status": status,
            "driverId": self.driver_id,
            "runtimeKind": self.runtime_kind,
            "runtimeVersion": self.config.pi_version if installed else "",
            "piVersion": self.config.pi_version if installed else "",
            "idleTimeoutSeconds": self.config.idle_timeout_seconds,
            "activeSessionId": active_session,
            "lastError": last_error,
            "capabilities": {
                "rpc": installed,
                "sessions": True,
                "conversationFork": installed,
                "conversationRewrite": False,
                "tools": bool(self.config.extension_path),
                "imageAttachments": True,
                "coordinator": set(_COORDINATOR_TOOLS).issubset(set(self.config.tools)),
                "modelConfigured": self.config.model_configured,
            },
        }

    def ensure(self, session_id: str) -> dict[str, object]:
        with self._lifecycle_lock:
            return self._ensure_locked(session_id)

    def _ensure_locked(self, session_id: str) -> dict[str, object]:
        if not self.config.enabled:
            raise PiRuntimeError("Pi runtime is disabled")
        if not self.config.model_configured:
            raise PiRuntimeError(self.config.model_configuration_error or "Pi model is not configured")
        session = dict(self.sessions.get(session_id))
        runtime_binding = self.sessions.runtime_binding(session_id)
        if runtime_binding is not None:
            session["_runtimeBinding"] = runtime_binding
        if self._session_context_provider is not None:
            session.update(dict(self._session_context_provider(session)))
        if session.get("mode") == "coordinator" and not set(_COORDINATOR_TOOLS).issubset(
            set(self.config.tools)
        ):
            raise PiRuntimeError("coordinator mode is not enabled in this runtime build")
        running_client: PiRpcClient | None = None
        with self._lock:
            if self._client is not None and self._client.running and self._active_session_id == session_id:
                self._schedule_idle_locked()
                running_client = self._client
        if running_client is not None:
            return running_client.send({"type": "get_state"})
        self.stop()
        with self._lock:
            self._status = "starting"
            self._last_error = ""
            self._active_session_id = session_id
            self._last_pi_entry_id = ""
            self._intentional_stop = False
            client: PiRpcClient
            client = PiRpcClient(
                self.config,
                session=session,
                on_event=lambda raw: self._handle_pi_event(
                    client,
                    self._session_id_for_client(client),
                    raw,
                ),
                on_exit=lambda code, error: self._handle_process_exit(
                    client,
                    self._session_id_for_client(client),
                    code,
                    error,
                ),
            )
            self._client = client
        try:
            response = client.start()
            state = _mapping(response.get("data"))
            desired_provider, desired_model_id = self.config.resolved_model_reference(session)
            started_model = _mapping(state.get("model"))
            if (
                desired_provider
                and desired_model_id
                and (
                    str(started_model.get("provider") or "") != desired_provider
                    or str(started_model.get("id") or "") != desired_model_id
                )
            ):
                # A resumed Pi transcript can retain its previous model even
                # when the launch arguments have changed. Reconcile the live
                # RPC state before accepting a Web prompt so an old timeline
                # alias cannot leak through to the upstream gateway.
                client.send(
                    {
                        "type": "set_model",
                        "provider": desired_provider,
                        "modelId": desired_model_id,
                    }
                )
                state = _mapping(client.send({"type": "get_state"}).get("data"))
            selected_model = _mapping(state.get("model"))
            selected_provider = str(selected_model.get("provider") or "").strip()
            selected_model_id = str(selected_model.get("id") or "").strip()
            if selected_provider and selected_model_id:
                self.sessions.set_model_profile(
                    session_id,
                    f"{selected_provider}/{selected_model_id}",
                )
            desired_thinking = str(session.get("thinkingLevel") or "").strip().lower()
            if desired_thinking and str(state.get("thinkingLevel") or "") != desired_thinking:
                client.send({"type": "set_thinking_level", "level": desired_thinking})
                state = _mapping(client.send({"type": "get_state"}).get("data"))
            bound = self.sessions.bind_runtime_session(
                session_id,
                driver_id=self.driver_id,
                runtime_kind=self.runtime_kind,
                external_session_id=str(state.get("sessionId") or ""),
                transcript_ref=str(state.get("sessionFile") or ""),
                branch_anchor=str(state.get("leafId") or ""),
                binding_state="active",
                message_count=_integer(state.get("messageCount")),
            )
            with self._lock:
                self._status = "ready"
                self._schedule_idle_locked()
            self.events.publish(session_id, "status_changed", {"status": "ready"})
            return {"state": dict(state), "session": bound}
        except Exception as exc:
            with self._lock:
                if self._client is client:
                    self._client = None
                    self._active_session_id = ""
                    self._active_turn_id = ""
                    self._active_client_message_id = ""
                self._status = "faulted"
                self._last_error = _redact_runtime_text(str(exc))
            client.stop()
            self.sessions.set_status(session_id, "faulted")
            self.events.publish(session_id, "turn_failed", {"error": self._last_error})
            raise

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
        if normalized_delivery != "prompt":
            with self._lock:
                if not self._active_turn_id:
                    raise PiRuntimeError("Pi 当前没有可接收排队消息的活动回合")
                client = self._require_client_locked(session_id)
                turn_id = self._active_turn_id
                self._cancel_idle_locked()
            command: dict[str, object] = {
                "type": "steer" if normalized_delivery == "steer" else "follow_up",
                "message": text,
            }
            if images:
                command["images"] = [dict(image) for image in images]
            response = client.send(command)
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
        turn_id = f"turn:{uuid.uuid4()}"
        with self._lock:
            if self._active_turn_id:
                raise PiRuntimeError("Pi 正在处理上一轮，请等待结束或停止完成后再发送")
            client = self._require_client_locked(session_id)
            self._active_turn_id = turn_id
            self._active_client_message_id = str(client_message_id).strip()
            self._stream_pi_message_id = ""
            self._status = "busy"
            self._cancel_idle_locked()
        self.sessions.set_status(session_id, "busy", last_message_preview=text)
        self.events.publish(session_id, "status_changed", {"status": "busy"}, turn_id=turn_id)
        try:
            command: dict[str, object] = {"type": "prompt", "message": text}
            if images:
                command["images"] = [dict(image) for image in images]
            response = client.send(command)
            pi_entry_id = ""
            try:
                command: dict[str, object] = {"type": "get_entries"}
                with self._lock:
                    if self._last_pi_entry_id:
                        command["since"] = self._last_pi_entry_id
                entries_response = client.send(command)
                entries_data = _mapping(entries_response.get("data"))
                pi_entry_id = _latest_user_entry_id(entries_data.get("entries"), text)
                leaf_id = str(entries_data.get("leafId") or "")
                if leaf_id:
                    with self._lock:
                        self._last_pi_entry_id = leaf_id
            except PiRuntimeError:
                # Prompt acceptance remains authoritative when checkpoint lookup
                # is unavailable in an older or interrupted Pi runtime.
                pass
            result: dict[str, object] = {
                "accepted": True,
                "turnId": turn_id,
                "piEntryId": pi_entry_id,
                "response": response,
            }
            if client_message_id:
                result["clientMessageId"] = str(client_message_id).strip()
            return result
        except Exception as exc:
            self._turn_failed(session_id, turn_id, exc)
            raise

    def messages(self, session_id: str) -> list[dict[str, object]]:
        # Reading a transcript is independent from model/provider readiness. In
        # particular, switching Sessions must not blank persisted conversation
        # history just because Pi cannot currently start.
        with self._lock:
            live = (
                self._active_session_id == session_id
                and self._client is not None
                and self._client.running
            )
        if not live:
            found, persisted = self._persisted_messages(session_id)
            if found:
                return persisted
        try:
            self.ensure(session_id)
        except AgentRuntimeError:
            found, persisted = self._persisted_messages(session_id)
            return persisted if found else []
        with self._lock:
            client = self._require_client_locked(session_id)
        try:
            response = client.send({"type": "get_messages"})
        except AgentRuntimeError:
            found, persisted = self._persisted_messages(session_id)
            return persisted if found else []
        data = _mapping(response.get("data"))
        messages = data.get("messages")
        if not isinstance(messages, list):
            return []
        result: list[dict[str, object]] = []
        current_turn_id = ""
        for raw_message in messages:
            if not isinstance(raw_message, Mapping):
                continue
            value = _mapping(raw_message)
            if not _pi_message_is_public(value):
                continue
            role = str(value.get("role") or "assistant").lower()
            message_id = _pi_message_id(value, "history")
            if role == "user" or not current_turn_id:
                current_turn_id = f"history:{message_id}"
            result.append(
                _pi_message_payload(
                    value,
                    session_id=session_id,
                    turn_id=current_turn_id,
                    media_resolver=self._media_resolver,
                    message_id=message_id,
                ).to_payload()
            )
        return result

    def fork_candidates(self, session_id: str) -> list[dict[str, object]]:
        """List Pi-owned user-message anchors without inventing product checkpoints."""

        with self._lifecycle_lock:
            self._require_idle_fork_session(session_id)
            try:
                self._ensure_locked(session_id)
                with self._lock:
                    client = self._require_client_locked(session_id)
                    self._require_quiescent_fork_locked()
                candidates = self._fork_candidates_from_client(client)
                with self._lock:
                    self._schedule_idle_locked()
                return candidates
            finally:
                # Reading branch anchors must not leave the product Session in
                # the transient active state created by ensure().
                if str(self.sessions.get(session_id).get("status") or "") == "active":
                    self.sessions.set_status(session_id, "idle")

    def fork_session(
        self,
        source_session_id: str,
        target_session_id: str,
        *,
        entry_id: str,
    ) -> dict[str, object]:
        """Move the live Pi process to a real branch and bind only the target Session."""

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
            self._ensure_locked(source_session_id)
            source_binding = self.sessions.runtime_binding(source_session_id)
            if not isinstance(source_binding, Mapping):
                raise PiRuntimeError("conversation fork source has no runtime binding")
            source_transcript = str(source_binding.get("transcriptRef") or "").strip()
            with self._lock:
                client = self._require_client_locked(source_session_id)
                self._require_quiescent_fork_locked()
                self._cancel_idle_locked()
            candidates = self._fork_candidates_from_client(client)
            selected = next(
                (candidate for candidate in candidates if candidate["entryId"] == normalized_entry_id),
                None,
            )
            if selected is None:
                raise PiRuntimeError("conversation fork entry is not available in the source Session")

            fork_started = False
            branch_transcript: Path | None = None
            try:
                fork_started = True
                fork_response = _mapping(
                    client.send({"type": "fork", "entryId": normalized_entry_id}).get("data")
                )
                if bool(fork_response.get("cancelled")):
                    raise PiRuntimeError("Pi cancelled the conversation fork")
                state = _mapping(client.send({"type": "get_state"}).get("data"))
                external_session_id = str(state.get("sessionId") or "").strip()
                transcript_ref = str(state.get("sessionFile") or "").strip()
                if not external_session_id or not transcript_ref:
                    raise PiRuntimeError("Pi returned an incomplete conversation fork identity")
                branch_candidate = Path(transcript_ref).expanduser()
                if branch_candidate.is_symlink():
                    raise PiRuntimeError("Pi conversation fork file must not be a symlink")
                branch_transcript = branch_candidate.resolve(strict=False)
                session_root = self.config.session_dir.expanduser().resolve(strict=False)
                if not _is_within(branch_transcript, session_root):
                    raise PiRuntimeError("Pi conversation fork file is outside the managed session directory")
                if not branch_transcript.is_file():
                    raise PiRuntimeError("Pi conversation fork file was not persisted")
                source_path = Path(source_transcript).expanduser().resolve(strict=False) if source_transcript else None
                if source_path is not None and branch_transcript == source_path:
                    raise PiRuntimeError("Pi conversation fork reused the source transcript")

                bound = self.sessions.bind_runtime_session(
                    target_session_id,
                    driver_id=self.driver_id,
                    runtime_kind=self.runtime_kind,
                    external_session_id=external_session_id,
                    transcript_ref=branch_transcript.as_posix(),
                    branch_anchor=str(state.get("leafId") or normalized_entry_id),
                    binding_state="active",
                    metadata={"forkedFromSessionId": source_session_id, "forkEntryId": normalized_entry_id},
                    message_count=_integer(state.get("messageCount")),
                )
                with self._lock:
                    self._active_session_id = target_session_id
                    self._last_pi_entry_id = str(state.get("leafId") or "")
                    self._active_turn_id = ""
                    self._active_client_message_id = ""
                    self._stream_pi_message_id = ""
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
                    "selectedText": str(selected["text"]),
                    "state": dict(state),
                    "session": bound,
                }
            except Exception:
                if fork_started:
                    # Pi mutates its live Session during fork(). Never let that
                    # mutated client masquerade as the source binding after a
                    # partial failure. The source DB binding remains untouched.
                    with self._lock:
                        if self._client is client:
                            self._client = None
                            self._active_session_id = ""
                            self._active_turn_id = ""
                            self._active_client_message_id = ""
                            self._stream_pi_message_id = ""
                            self._pending_approval_requests.clear()
                            self._pending_review_requests.clear()
                            self._last_pi_entry_id = ""
                            self._status = "stopped" if self.config.enabled else "disabled"
                            self._intentional_stop = True
                    client.stop()
                    if (
                        branch_transcript is not None
                        and branch_transcript.is_file()
                        and not branch_transcript.is_symlink()
                    ):
                        try:
                            branch_transcript.unlink()
                        except OSError:
                            pass
                self.sessions.set_status(source_session_id, "idle")
                self.sessions.set_status(target_session_id, "idle")
                raise

    def _require_idle_fork_session(self, session_id: str) -> None:
        session = self.sessions.get(session_id)
        if str(session.get("status") or "") != "idle":
            raise PiRuntimeError("conversation forks are only available for idle Sessions")

    def _require_quiescent_fork_locked(self) -> None:
        if self._active_turn_id:
            raise PiRuntimeError("conversation forks are unavailable during an Agent turn")
        if self._pending_approval_requests or self._pending_review_requests:
            raise PiRuntimeError("conversation forks are unavailable while user input is pending")

    @staticmethod
    def _fork_candidates_from_client(client: PiRpcClient) -> list[dict[str, object]]:
        response = client.send({"type": "get_fork_messages"})
        data = _mapping(response.get("data"))
        raw_messages = data.get("messages")
        if not isinstance(raw_messages, list):
            raise PiRuntimeError("Pi returned an invalid conversation fork catalog")
        candidates: list[dict[str, object]] = []
        seen: set[str] = set()
        for raw in raw_messages[:500]:
            if not isinstance(raw, Mapping):
                continue
            entry_id = str(raw.get("entryId") or "").strip()[:240]
            text = _public_fork_candidate_text(raw.get("text"), role="user")
            if not entry_id or not text or entry_id in seen:
                continue
            seen.add(entry_id)
            candidates.append(
                {
                    "entryId": entry_id,
                    "text": text,
                    "role": "user",
                    "createdAtMs": 0,
                }
            )
        return candidates

    def _persisted_messages(self, session_id: str) -> tuple[bool, list[dict[str, object]]]:
        session = self.sessions.get(session_id)
        runtime_binding = self.sessions.runtime_binding(session_id)
        transcript_ref = ""
        if isinstance(runtime_binding, Mapping):
            if (
                runtime_binding.get("driverId") == self.driver_id
                and runtime_binding.get("runtimeKind") == self.runtime_kind
            ):
                transcript_ref = str(runtime_binding.get("transcriptRef") or "").strip()
        if not transcript_ref:
            transcript_ref = str(session.get("sessionFile") or "").strip()
        if not transcript_ref:
            return False, []

        transcript_candidate = Path(transcript_ref).expanduser()
        if transcript_candidate.is_symlink():
            raise PiRuntimeError("Pi session file must not be a symlink")
        transcript = transcript_candidate.resolve(strict=False)
        session_root = self.config.session_dir.expanduser().resolve(strict=False)
        if not _is_within(transcript, session_root):
            raise PiRuntimeError("Pi session file is outside the managed session directory")
        try:
            size = transcript.stat().st_size
        except OSError:
            return False, []
        if size > _MAX_PERSISTED_TRANSCRIPT_BYTES:
            raise PiRuntimeError("Pi session file is too large to read safely")

        entries: list[dict[str, object]] = []
        by_id: dict[str, dict[str, object]] = {}
        try:
            with transcript.open("rb") as handle:
                for raw_line in handle:
                    if len(raw_line) > _MAX_PERSISTED_TRANSCRIPT_LINE_BYTES:
                        raise PiRuntimeError("Pi session entry is too large to read safely")
                    if len(entries) >= _MAX_PERSISTED_TRANSCRIPT_ENTRIES:
                        raise PiRuntimeError("Pi session contains too many entries to read safely")
                    try:
                        parsed = json.loads(raw_line)
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        continue
                    if not isinstance(parsed, Mapping):
                        continue
                    entry = dict(parsed)
                    entry_id = str(entry.get("id") or "").strip()
                    if not entry_id:
                        continue
                    entries.append(entry)
                    by_id[entry_id] = entry
        except OSError:
            return False, []
        if not entries or str(entries[0].get("type") or "") != "session":
            return True, []

        path: list[dict[str, object]] = []
        current: dict[str, object] | None = entries[-1]
        visited: set[str] = set()
        while current is not None:
            current_id = str(current.get("id") or "")
            if not current_id or current_id in visited:
                break
            visited.add(current_id)
            path.append(current)
            parent_id = str(current.get("parentId") or "").strip()
            current = by_id.get(parent_id) if parent_id else None
        path.reverse()

        public_messages: list[dict[str, object]] = []
        current_turn_id = ""
        for entry in path:
            if str(entry.get("type") or "") != "message":
                continue
            raw_message = entry.get("message")
            if not isinstance(raw_message, Mapping):
                continue
            value = dict(raw_message)
            if not _pi_message_is_public(value):
                continue
            role = str(value.get("role") or "assistant").lower()
            message_id = str(entry.get("id") or _pi_message_id(value, "history"))
            if role == "user" or not current_turn_id:
                current_turn_id = f"history:{message_id}"
            public_messages.append(
                _pi_message_payload(
                    value,
                    session_id=session_id,
                    turn_id=current_turn_id,
                    media_resolver=self._media_resolver,
                    message_id=message_id,
                ).to_payload()
            )
        return True, public_messages

    def rewind_session(self, session_id: str, *, entry_id: str) -> dict[str, object]:
        del session_id, entry_id
        raise PiRuntimeError(
            "in-place conversation rewrite requires the managed Pi runtime host"
        )

    def command_catalog(self, session_id: str) -> list[dict[str, object]]:
        """Return only commands Pi says are invokable through an RPC prompt."""
        self.ensure(session_id)
        with self._lock:
            client = self._require_client_locked(session_id)
            self._schedule_idle_locked()
        response = client.send({"type": "get_commands"})
        data = _mapping(response.get("data"))
        raw_commands = data.get("commands")
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
            description = " ".join(str(value.get("description") or "").split())[:240]
            commands.append(
                {
                    "name": name,
                    "invocation": f"/{name}",
                    "description": description,
                    "source": source,
                }
            )
        return commands

    def tool_catalog(self, session_id: str) -> list[dict[str, object]]:
        """Return the backend authority catalog used to configure Pi tools."""

        session = dict(self.sessions.get(session_id))
        if self._tool_manifest_provider is None:
            return []
        return [dict(item) for item in self._tool_manifest_provider(session)]

    def model_catalog(self, session_id: str) -> dict[str, object]:
        self.ensure(session_id)
        with self._lock:
            client = self._require_client_locked(session_id)
            self._schedule_idle_locked()
        state_response = client.send({"type": "get_state"})
        models_response = client.send({"type": "get_available_models"})
        state = _mapping(state_response.get("data"))
        data = _mapping(models_response.get("data"))
        raw_models = data.get("models") if isinstance(data.get("models"), list) else []
        selected = _public_pi_model(_mapping(state.get("model")))
        models = [
            model
            for value in raw_models
            if isinstance(value, Mapping)
            for model in [_public_pi_model(value)]
            if model
        ]
        models.sort(key=lambda item: (str(item["provider"]).lower(), str(item["name"]).lower()))
        thinking_level = _effective_thinking_level(state.get("thinkingLevel"), selected)
        return {
            "selected": selected or None,
            "models": models,
            "thinkingLevel": thinking_level,
        }

    def available_models(self) -> list[dict[str, object]]:
        with self._lock:
            client = self._client
        if client is None or not client.running:
            raise PiRuntimeError("Pi model catalog requires an active runtime session")
        response = client.send({"type": "get_available_models"})
        data = _mapping(response.get("data"))
        raw_models = data.get("models") if isinstance(data.get("models"), list) else []
        models = [
            model
            for value in raw_models
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
        on_text_delta: Callable[[str], None] | None = None,
        timeout_seconds: float = 120.0,
    ) -> dict[str, object]:
        del request_id, provider, model_id, thinking_level, message, on_text_delta, timeout_seconds
        raise PiRuntimeError("stateless completion requires Pi Runtime Host protocol v2")

    def cancel_completion(self, request_id: str) -> bool:
        del request_id
        return False

    def set_model(self, session_id: str, *, provider: str, model_id: str) -> dict[str, object]:
        normalized_provider = _model_reference_part(provider, field="provider", maximum=80)
        normalized_model = _model_reference_part(model_id, field="modelId", maximum=160)
        self.ensure(session_id)
        with self._lock:
            if self._active_turn_id:
                raise PiRuntimeError("Pi 正在回复，结束当前回合后才能切换模型")
            client = self._require_client_locked(session_id)
            self._cancel_idle_locked()
        try:
            response = client.send(
                {
                    "type": "set_model",
                    "provider": normalized_provider,
                    "modelId": normalized_model,
                }
            )
            selected = _public_pi_model(_mapping(response.get("data")))
            if not selected:
                raise PiRuntimeError("Pi did not return the selected model")
            session = self.sessions.set_model_profile(
                session_id,
                f"{selected['provider']}/{selected['id']}",
            )
            return {"selected": selected, "session": session}
        finally:
            with self._lock:
                self._schedule_idle_locked()

    def set_thinking_level(self, session_id: str, *, level: str) -> dict[str, object]:
        normalized = str(level or "").strip().lower()
        if normalized not in {"off", "minimal", "low", "medium", "high", "xhigh"}:
            raise ValueError("unsupported Pi thinking level")
        self.ensure(session_id)
        with self._lock:
            if self._active_turn_id:
                raise PiRuntimeError("Pi 正在回复，结束当前回合后才能切换思考强度")
            client = self._require_client_locked(session_id)
            self._cancel_idle_locked()
        try:
            before = _mapping(client.send({"type": "get_state"}).get("data"))
            before_model = _public_pi_model(_mapping(before.get("model")))
            supported = before_model.get("thinkingLevels") if before_model else ["off"]
            if not isinstance(supported, list) or normalized not in supported:
                raise ValueError("当前 Pi 模型不支持这个思考强度")
            client.send({"type": "set_thinking_level", "level": normalized})
            state_response = client.send({"type": "get_state"})
            state = _mapping(state_response.get("data"))
            selected = _public_pi_model(_mapping(state.get("model")))
            effective = _effective_thinking_level(
                state.get("thinkingLevel") or normalized,
                selected,
            )
            self.sessions.set_thinking_level(session_id, effective)
            return {
                "thinkingLevel": effective,
                "selected": selected or None,
            }
        finally:
            with self._lock:
                self._schedule_idle_locked()

    def abort(self, session_id: str) -> None:
        with self._lock:
            client = self._require_client_locked(session_id)
            turn_id = self._active_turn_id
        client.send({"type": "abort"})
        if not turn_id:
            return
        with self._lock:
            # Pi may settle while the abort ACK is in flight. Never append an
            # "aborting" event after the real terminal event in that case.
            if (
                self._client is not client
                or self._active_session_id != session_id
                or self._active_turn_id != turn_id
            ):
                return
            self.events.publish(session_id, "status_changed", {"status": "aborting"}, turn_id=turn_id)
            self._schedule_abort_fallback_locked(session_id, turn_id)

    def compact(self, session_id: str, instructions: str = "") -> dict[str, object]:
        self.ensure(session_id)
        with self._lock:
            client = self._require_client_locked(session_id)
            self._cancel_idle_locked()
        command: dict[str, object] = {"type": "compact"}
        if instructions.strip():
            command["customInstructions"] = instructions.strip()[:2000]
        try:
            response = client.send(command, timeout=max(60.0, self.config.command_timeout_seconds))
            result = dict(_mapping(response.get("data")))
            checkpoint = self._observe_compaction(session_id, result, "manual")
            if checkpoint:
                result["memoryCheckpoint"] = checkpoint
            return result
        finally:
            with self._lock:
                self._schedule_idle_locked()

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

    def stop(self) -> None:
        with self._lifecycle_lock:
            self._stop_locked()

    def _stop_locked(self) -> None:
        client: PiRpcClient | None
        session_id: str
        with self._lock:
            self._cancel_idle_locked()
            self._cancel_abort_locked()
            client = self._client
            session_id = self._active_session_id
            self._intentional_stop = True
            self._client = None
            self._active_turn_id = ""
            self._active_client_message_id = ""
            self._stream_pi_message_id = ""
            self._active_session_id = ""
            self._status = "stopped" if self.config.enabled else "disabled"
            self._pending_approval_requests.clear()
            self._pending_review_requests.clear()
            self._last_pi_entry_id = ""
        if client is not None:
            client.stop()
        if session_id:
            self.sessions.set_status(session_id, "idle")

    def _handle_pi_event(self, client: PiRpcClient, session_id: str, raw: dict[str, object]) -> None:
        with self._lock:
            if self._client is not client or self._active_session_id != session_id:
                return
            turn_id = self._active_turn_id
            client_message_id = self._active_client_message_id
        event_type = str(raw.get("type") or "")
        if event_type == "compaction_end":
            compaction = (
                dict(_mapping(raw.get("result")))
                if isinstance(raw.get("result"), Mapping)
                else dict(raw)
            )
            self._observe_compaction(
                session_id,
                compaction,
                str(raw.get("trigger") or "").strip() or "automatic",
            )
            return
        if event_type == "message_update":
            update = _mapping(raw.get("assistantMessageEvent"))
            update_type = str(update.get("type") or "")
            if update_type == "text_delta":
                raw_message = _mapping(raw.get("message"))
                pi_message_id = _pi_message_id(raw_message, turn_id)
                with self._lock:
                    replace_block = pi_message_id != self._stream_pi_message_id
                    self._stream_pi_message_id = pi_message_id
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
                self.events.publish(
                    session_id,
                    "status_changed",
                    {"status": "analyzing"},
                    turn_id=turn_id,
                )
            return
        if event_type == "message_end":
            raw_message = _mapping(raw.get("message"))
            if not _pi_message_is_public(raw_message):
                return
            role = str(raw_message.get("role") or "assistant").lower()
            # AgentService publishes the accepted user message immediately so
            # it can attach managed-media receipts and reconcile the Web
            # optimistic row. Pi echoes the same user message afterwards;
            # forwarding that echo creates a second bubble for one send.
            if role == "user":
                return
            message = _pi_message_payload(
                raw_message,
                session_id=session_id,
                turn_id=turn_id,
                media_resolver=self._media_resolver,
                message_id=f"{turn_id}:assistant" if role == "assistant" else None,
            )
            event_payload: dict[str, object] = {
                "message": message.to_payload(),
                "usage": _public_usage(raw.get("message")),
            }
            if role == "user" and client_message_id:
                event_payload["clientMessageId"] = client_message_id
            self.events.publish(
                session_id,
                "message_completed",
                event_payload,
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
        if event_type in {"tool_execution_start", "tool_execution_update", "tool_execution_end"}:
            mapped_type = {
                "tool_execution_start": "tool_started",
                "tool_execution_update": "tool_progress",
                "tool_execution_end": "tool_finished",
            }[event_type]
            raw_args = _mapping(raw.get("args"))
            tool_name = str(raw.get("toolName") or "")
            payload = {
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
            method = str(raw.get("method") or "")
            request_id = str(raw.get("id") or "")
            title = str(raw.get("title") or "")
            if method == "confirm" and title.startswith(_APPROVAL_TITLE_PREFIX):
                approval_id = title[len(_APPROVAL_TITLE_PREFIX) :].strip()
                try:
                    approval = self.sessions.get_approval(approval_id)
                except (KeyError, ValueError):
                    client.respond_extension_ui(request_id, confirmed=False)
                    return
                if approval.get("sessionId") != session_id or approval.get("state") != "pending":
                    client.respond_extension_ui(request_id, confirmed=False)
                    return
                with self._lock:
                    if self._client is not client or self._active_session_id != session_id:
                        client.respond_extension_ui(request_id, confirmed=False)
                        return
                    self._pending_approval_requests[approval_id] = request_id
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
                    client.respond_extension_ui(request_id, confirmed=False)
                    return
                with self._lock:
                    if self._client is not client or self._active_session_id != session_id:
                        client.respond_extension_ui(request_id, confirmed=False)
                        return
                    self._pending_review_requests[run_id] = request_id
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
            if method not in {"select", "confirm", "input", "editor"}:
                return
            safe = {
                "requestId": request_id,
                "method": method,
                "title": title[:160],
                "message": str(raw.get("message") or "")[:500],
            }
            self.events.publish(session_id, "user_input_required", safe, turn_id=turn_id)
            return
        if event_type == "agent_end":
            messages = raw.get("messages") if isinstance(raw.get("messages"), list) else []
            preview = _last_assistant_preview(messages)
            provider_error = _last_assistant_error(messages)
            with self._lock:
                if (
                    self._client is not client
                    or self._active_session_id != session_id
                    or self._active_turn_id != turn_id
                ):
                    return
                if provider_error:
                    self._turn_failed(session_id, turn_id, PiRuntimeError(provider_error))
                    return
                # The real terminal event won the race; disarm the abort
                # fallback before publishing so it cannot emit a second
                # terminal receipt while turn_completed is being recorded.
                self._cancel_abort_locked()
            # Publish the terminal receipt before exposing the session as idle.
            # Otherwise a poller can observe idle in the small window before
            # turn_completed is appended and incorrectly treat the same Pi
            # turn as incomplete.
            self.events.publish(
                session_id,
                "turn_completed",
                {"messageCount": len(messages)},
                turn_id=turn_id,
            )
            with self._lock:
                if (
                    self._client is not client
                    or self._active_session_id != session_id
                    or self._active_turn_id != turn_id
                ):
                    return
                self._status = "ready"
                self._active_turn_id = ""
                self._active_client_message_id = ""
                self._stream_pi_message_id = ""
                self._pending_approval_requests.clear()
                self._pending_review_requests.clear()
                self._schedule_idle_locked()
            self.sessions.set_status(session_id, "idle", message_count=len(messages), last_message_preview=preview)
            return
        if event_type == "extension_error":
            self._turn_failed(session_id, turn_id, PiRuntimeError(str(raw.get("error") or "Pi extension failed")))

    def has_pending_approval(self, session_id: str, approval_id: str) -> bool:
        with self._lock:
            return (
                self._active_session_id == session_id
                and self._client is not None
                and self._client.running
                and approval_id in self._pending_approval_requests
            )

    def has_pending_review(self, session_id: str, run_id: str) -> bool:
        with self._lock:
            return (
                self._active_session_id == session_id
                and self._client is not None
                and self._client.running
                and run_id in self._pending_review_requests
            )

    def resolve_review(
        self,
        session_id: str,
        run_id: str,
        *,
        reviewed: bool,
    ) -> None:
        with self._lock:
            if self._active_session_id != session_id or self._client is None or not self._client.running:
                raise PiRuntimeError("review is no longer attached to an active Pi session")
            request_id = self._pending_review_requests.get(run_id)
            if not request_id:
                raise PiRuntimeError("review request is no longer pending")
            client = self._client
            turn_id = self._active_turn_id
        client.respond_extension_ui(request_id, confirmed=reviewed)
        with self._lock:
            self._pending_review_requests.pop(run_id, None)
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
        if resolution_state and resolution_state not in {
            "external_pending",
            "applied",
            "failed",
            "rejected",
            "expired",
            "stale",
        }:
            raise ValueError("unsupported approval resolution state")
        with self._lock:
            if self._active_session_id != session_id or self._client is None or not self._client.running:
                raise PiRuntimeError("approval is no longer attached to an active Pi session")
            request_id = self._pending_approval_requests.get(approval_id)
            if not request_id:
                raise PiRuntimeError("approval request is no longer pending")
            client = self._client
            turn_id = self._active_turn_id
        client.respond_extension_ui(request_id, confirmed=approved)
        with self._lock:
            self._pending_approval_requests.pop(approval_id, None)
        self.events.publish(
            session_id,
            "approval_resolved",
            {
                "approvalId": approval_id,
                "state": resolution_state or ("approved" if approved else "rejected"),
            },
            turn_id=turn_id,
        )

    def _handle_process_exit(
        self,
        client: PiRpcClient,
        session_id: str,
        exit_code: int | None,
        error: str,
    ) -> None:
        with self._lock:
            if self._client is not client:
                return
            intentional = self._intentional_stop
            self._client = None
            self._active_turn_id = ""
            self._active_client_message_id = ""
            self._stream_pi_message_id = ""
            self._cancel_idle_locked()
            self._cancel_abort_locked()
            if intentional:
                self._status = "stopped"
            else:
                self._status = "faulted"
                self._last_error = _redact_runtime_text(error or f"Pi exited with code {exit_code}")
            self._pending_approval_requests.clear()
            self._pending_review_requests.clear()
            self._last_pi_entry_id = ""
        if session_id:
            self.sessions.set_status(session_id, "idle" if intentional else "faulted")
            self.events.publish(
                session_id,
                "status_changed" if intentional else "turn_failed",
                {"status": "stopped"} if intentional else {"error": self._last_error, "exitCode": exit_code},
            )

    def _turn_failed(self, session_id: str, turn_id: str, error: BaseException) -> None:
        safe_error = _redact_runtime_text(str(error))
        self.sessions.set_status(session_id, "idle")
        with self._lock:
            self._cancel_abort_locked()
            self._status = "ready" if self._client is not None and self._client.running else "faulted"
            self._active_turn_id = ""
            self._active_client_message_id = ""
            self._stream_pi_message_id = ""
            self._last_error = safe_error
            self._pending_approval_requests.clear()
            self._pending_review_requests.clear()
            self._schedule_idle_locked()
        self.events.publish(session_id, "turn_failed", {"error": safe_error}, turn_id=turn_id)

    def _require_client_locked(self, session_id: str) -> PiRpcClient:
        if self._active_session_id != session_id or self._client is None or not self._client.running:
            raise PiRuntimeError("requested agent session is not active")
        return self._client

    def _session_id_for_client(self, client: PiRpcClient) -> str:
        with self._lock:
            return self._active_session_id if self._client is client else ""

    def _schedule_idle_locked(self) -> None:
        self._cancel_idle_locked()
        if self.config.idle_timeout_seconds <= 0 or self._status != "ready":
            return
        timer = threading.Timer(self.config.idle_timeout_seconds, self._idle_expired)
        timer.daemon = True
        self._idle_timer = timer
        timer.start()

    def _cancel_idle_locked(self) -> None:
        if self._idle_timer is not None:
            self._idle_timer.cancel()
            self._idle_timer = None

    def _schedule_abort_fallback_locked(self, session_id: str, turn_id: str) -> None:
        self._cancel_abort_locked()
        self._aborting_turn_id = turn_id
        timer = threading.Timer(1.0, self._abort_fallback_expired, args=(session_id, turn_id))
        timer.daemon = True
        self._abort_timer = timer
        timer.start()

    def _cancel_abort_locked(self) -> None:
        timer = self._abort_timer
        self._abort_timer = None
        self._aborting_turn_id = ""
        if timer is not None:
            timer.cancel()

    def _abort_fallback_expired(self, session_id: str, turn_id: str) -> None:
        # Older Pi RPC builds ACK abort before emitting agent_end, and a
        # crashed extension can omit agent_end entirely. Recycle this v1
        # single-session process so no late event can terminate a newer turn.
        with self._lifecycle_lock:
            with self._lock:
                if (
                    self._aborting_turn_id != turn_id
                    or self._active_session_id != session_id
                    or self._active_turn_id != turn_id
                ):
                    return
                self._abort_timer = None
                self._aborting_turn_id = ""
            self._stop_locked()
        self.events.publish(
            session_id,
            "turn_completed",
            {"status": "aborted", "aborted": True, "terminalEvent": "abort_timeout"},
            turn_id=turn_id,
        )

    def _idle_expired(self) -> None:
        with self._lock:
            if self._status != "ready":
                return
        self.stop()


def _pi_message_payload(
    raw: Mapping[str, object],
    *,
    session_id: str,
    turn_id: str,
    media_resolver: Callable[[str, str, str], str] | None = None,
    message_id: str | None = None,
) -> AgentMessage:
    role = str(raw.get("role") or "assistant")
    if role not in {"user", "assistant", "tool", "system"}:
        role = "tool" if role.lower().startswith("tool") else "assistant"
    content = raw.get("content")
    blocks: list[AgentBlock] = []
    attachments: list[str] = []
    if isinstance(content, str):
        visible_content = _visible_message_text(role, content)
        blocks.append(
            normalize_agent_block(
                {
                    "id": f"{turn_id}:text:0",
                    "type": "text",
                    "status": "completed",
                    "presentationKind": "markdown",
                    "data": {"text": visible_content},
                }
            )
        )
    elif isinstance(content, list):
        for index, item in enumerate(content):
            value = _mapping(item)
            content_type = str(value.get("type") or "unknown")
            if content_type == "text":
                visible_content = _visible_message_text(role, str(value.get("text") or ""))
                blocks.append(
                    normalize_agent_block(
                        {
                            "id": f"{turn_id}:text:{index}",
                            "type": "text",
                            "status": "completed",
                            "presentationKind": "markdown",
                            "data": {"text": visible_content},
                        }
                    )
                )
            elif content_type == "image" and media_resolver is not None:
                media_id = media_resolver(
                    session_id,
                    str(value.get("mimeType") or ""),
                    str(value.get("data") or ""),
                )
                if media_id:
                    attachments.append(media_id)
                    receipt_url = _managed_media_content_url(session_id, media_id)
                    blocks.append(
                        normalize_agent_block(
                            {
                                "id": f"{turn_id}:image:{index}",
                                "type": "image",
                                "status": "completed",
                                "presentationKind": "image",
                                "data": {
                                    "mediaId": media_id,
                                    "receiptUrl": receipt_url,
                                },
                            }
                        )
                    )
            elif content_type in {"thinking", "redacted_thinking"}:
                continue
            elif content_type in {"toolCall", "tool_call"}:
                blocks.append(
                    normalize_agent_block(
                        {
                            "id": str(value.get("id") or f"{turn_id}:tool:{index}"),
                            "type": "tool_call",
                            "status": "completed",
                            "presentationKind": "tool_call",
                            "data": {
                                "toolCallId": str(value.get("id") or ""),
                                "toolName": str(value.get("name") or value.get("toolName") or ""),
                                "arguments": _redact_mapping(_mapping(value.get("arguments"))),
                            },
                        }
                    )
                )
    error_message = _redact_runtime_text(str(raw.get("errorMessage") or "").strip())
    failed = str(raw.get("stopReason") or "").lower() == "error" or bool(error_message)
    if failed:
        blocks.append(
            normalize_agent_block(
                {
                    "id": f"{turn_id}:error:0",
                    "type": "error",
                    "status": "failed",
                    "presentationKind": "error",
                    "data": {"message": error_message or "模型请求失败，请重试"},
                }
            )
        )
    if not blocks:
        blocks.append(
            normalize_agent_block(
                {
                    "id": f"{turn_id}:progress:0",
                    "type": "progress",
                    "status": "completed",
                    "presentationKind": "progress",
                    "data": {"label": "本轮没有可展示正文"},
                }
            )
        )
    created_at = _integer(raw.get("timestamp")) or int(time.time() * 1000)
    return AgentMessage(
        message_id=message_id or _pi_message_id(raw, turn_id),
        session_id=session_id,
        turn_id=turn_id,
        role=role,
        status="failed" if failed else "completed",
        blocks=tuple(blocks),
        attachments=tuple(dict.fromkeys(attachments)),
        created_at_ms=created_at,
        completed_at_ms=created_at,
        provider=str(raw.get("provider") or "").strip()[:80],
        model=str(raw.get("responseModel") or raw.get("model") or "").strip()[:160],
        usage=_public_usage(raw) if role == "assistant" else None,
    )


def _pi_message_is_public(raw: Mapping[str, object]) -> bool:
    """Keep Pi's loop protocol out of the human conversation transcript."""

    role = str(raw.get("role") or "assistant").lower()
    if role == "user":
        return True
    if role != "assistant":
        return False
    content = raw.get("content")
    if not isinstance(content, list):
        return bool(str(content or "").strip()) or bool(raw.get("errorMessage"))
    for item in content:
        value = _mapping(item)
        if str(value.get("type") or "") in {"toolCall", "tool_call"}:
            return False
    return any(
        str(_mapping(item).get("type") or "") in {"text", "image"}
        for item in content
    ) or bool(raw.get("errorMessage"))


def _managed_media_content_url(session_id: str, media_id: str) -> str:
    return (
        f"/api/agent/media/{quote(str(media_id), safe='')}/content"
        f"?sessionId={quote(str(session_id), safe='')}"
    )


def _pi_message_id(raw: Mapping[str, object], turn_id: str) -> str:
    value = str(raw.get("id") or "").strip()
    if value:
        return value
    timestamp = _integer(raw.get("timestamp"))
    role = str(raw.get("role") or "assistant").lower()
    if timestamp:
        return f"pi:message:{role}:{timestamp}"
    serialized = json.dumps(raw.get("content"), ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:20]
    return f"pi:message:{role}:{digest}"


def _visible_message_text(role: str, text: str) -> str:
    if role != "user":
        return text
    tagged = re.search(
        r"<rag-ime-user-query>\s*(.*?)\s*</rag-ime-user-query>",
        text,
        flags=re.DOTALL,
    )
    if tagged:
        return tagged.group(1).strip()
    legacy_prefix = "请在当前连续会话中处理这个输入法深度查找任务。"
    marker = "\n用户问题：\n"
    if text.startswith(legacy_prefix) and marker in text:
        question = text.split(marker, 1)[1].split("\n\n本地时间：", 1)[0].strip()
        if question:
            return question
    return text


def _public_fork_candidate_text(value: object, *, role: str = "user") -> str:
    """Return a public transcript preview without leaking injected context."""

    normalized = " ".join(str(value or "").split())[:8000]
    visible = (
        " ".join(_visible_message_text("user", normalized).split())[:8000]
        if role == "user"
        else normalized
    )
    if any(
        marker in visible
        for marker in ("<rag-ime-deep-search-context", "<rag-ime-user-query>")
    ):
        return ""
    return visible


def _last_assistant_error(messages: list[object]) -> str:
    for item in reversed(messages):
        message = _mapping(item)
        if str(message.get("role") or "") != "assistant":
            continue
        if str(message.get("stopReason") or "").lower() != "error" and not message.get("errorMessage"):
            return ""
        return _redact_runtime_text(str(message.get("errorMessage") or "模型请求失败，请重试"))
    return ""


def _last_assistant_preview(messages: list[object]) -> str:
    for item in reversed(messages):
        message = _mapping(item)
        if str(message.get("role") or "") != "assistant":
            continue
        content = message.get("content")
        if isinstance(content, str):
            return " ".join(content.split())[:240]
        if isinstance(content, list):
            text = " ".join(
                str(_mapping(block).get("text") or "")
                for block in content
                if str(_mapping(block).get("type") or "") == "text"
            )
            return " ".join(text.split())[:240]
    return ""


def _latest_user_entry_id(entries: object, expected_text: str) -> str:
    if not isinstance(entries, list):
        return ""
    expected = " ".join(expected_text.split())
    for value in reversed(entries):
        entry = _mapping(value)
        if str(entry.get("type") or "") != "message":
            continue
        message = _mapping(entry.get("message"))
        if str(message.get("role") or "") != "user":
            continue
        if _message_text(message) == expected:
            return str(entry.get("id") or "")
    return ""


def _message_text(message: Mapping[str, object]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return " ".join(content.split())
    if not isinstance(content, list):
        return ""
    text = " ".join(
        str(_mapping(block).get("text") or "")
        for block in content
        if str(_mapping(block).get("type") or "") == "text"
    )
    return " ".join(text.split())


def _public_usage(value: object) -> dict[str, int]:
    message = _mapping(value)
    usage = _mapping(message.get("usage"))
    input_tokens = _integer(usage.get("input"))
    output_tokens = _integer(usage.get("output"))
    cache_read = _integer(usage.get("cacheRead"))
    cache_write = _integer(usage.get("cacheWrite"))
    total = _integer(usage.get("totalTokens"))
    if total <= 0:
        total = input_tokens + output_tokens + cache_read + cache_write
    return {
        "input": input_tokens,
        "output": output_tokens,
        "cacheRead": cache_read,
        "cacheWrite": cache_write,
        "totalTokens": total,
    }


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _message_delivery(value: object) -> str:
    delivery = str(value or "prompt").strip()
    if delivery not in {"prompt", "steer", "followUp"}:
        raise ValueError("agent message delivery must be prompt, steer, or followUp")
    return delivery


def _public_message_queue(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item)[:4_000] for item in value[:100] if isinstance(item, str) and item]


def _integer(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _redact_mapping(value: Mapping[str, object], *, depth: int = 0) -> dict[str, object]:
    if depth >= 4:
        return {"truncated": True}
    result: dict[str, object] = {}
    for raw_key, raw_value in list(value.items())[:64]:
        key = str(raw_key)[:120]
        if re.search(r"token|secret|password|api.?key|authorization|cookie", key, re.IGNORECASE):
            result[key] = "[REDACTED_SECRET]"
        elif isinstance(raw_value, Mapping):
            result[key] = _redact_mapping(raw_value, depth=depth + 1)
        elif isinstance(raw_value, list):
            result[key] = [
                _redact_mapping(item, depth=depth + 1) if isinstance(item, Mapping) else _safe_scalar(item)
                for item in raw_value[:64]
            ]
        else:
            result[key] = _safe_scalar(raw_value)
    return result


def _public_code_tool_activity(tool_name: str, args: Mapping[str, object]) -> dict[str, object]:
    normalized_tool = str(tool_name or "").strip().lower()
    file_tools = {
        "read", "read_file", "workspace_read",
        "write", "write_file", "workspace_write_file",
        "edit", "edit_file", "workspace_edit_file",
    }
    if normalized_tool not in file_tools:
        return {}
    raw_path = str(args.get("relativePath") or args.get("fileName") or args.get("file_path") or args.get("path") or "")
    file_name = _public_file_name(raw_path)
    result: dict[str, object] = {}
    if file_name:
        result["fileName"] = file_name
    if normalized_tool in {"write", "write_file", "workspace_write_file"}:
        content = args.get("content")
        if isinstance(content, str) and content:
            normalized = content.replace("\r\n", "\n").replace("\r", "\n")
            lines = normalized.split("\n")
            while lines and not lines[-1]:
                lines.pop()
            line_count = max(1, len(lines))
            result.update({"lineCount": line_count, "additions": line_count})
            if file_name:
                result["summary"] = f"{file_name} +{line_count}"
    return result


def _public_file_name(value: str) -> str:
    normalized = str(value or "").replace("\\", "/").rstrip("/")
    file_name = normalized.rsplit("/", 1)[-1].strip()
    if not file_name or len(file_name) > 240 or any(ord(character) < 32 for character in file_name):
        return ""
    if re.search(r"token|secret|password|api.?key|authorization|cookie", file_name, re.IGNORECASE):
        return ""
    return file_name


def _safe_scalar(value: object) -> object:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _redact_runtime_text(str(value))[:2000]


def _redact_runtime_text(value: str) -> str:
    text = " ".join(str(value).split())[:500]
    text = re.sub(r"\bsk-[A-Za-z0-9_-]{6,}\b", "[REDACTED_SECRET]", text)
    text = re.sub(r"(?:/Users/|/Volumes/|/private/var/|/var/folders/)[^\s，。；;]+", "[REDACTED_PATH]", text)
    return text


def _split_model_reference(value: object) -> tuple[str, str]:
    reference = str(value or "").strip()
    if reference == "pi/default" or "/" not in reference:
        return "", ""
    provider, model = (part.strip() for part in reference.split("/", 1))
    if not provider or not model:
        return "", ""
    return provider, model


def _model_reference_part(value: object, *, field: str, maximum: int) -> str:
    normalized = str(value or "").strip()
    if not normalized or len(normalized) > maximum:
        raise ValueError(f"{field} must be a non-empty Pi model identifier")
    if any(character.isspace() for character in normalized) or (field == "provider" and "/" in normalized):
        raise ValueError(f"{field} contains unsupported characters")
    return normalized


def _public_pi_model(raw: Mapping[str, object]) -> dict[str, object]:
    provider = str(raw.get("provider") or "").strip()
    model_id = str(raw.get("id") or "").strip()
    if not provider or not model_id:
        return {}
    inputs = raw.get("input") if isinstance(raw.get("input"), list) else []
    return {
        "provider": provider[:80],
        "id": model_id[:160],
        "name": str(raw.get("name") or model_id).strip()[:160] or model_id[:160],
        "api": str(raw.get("api") or "").strip()[:80],
        "reasoning": bool(raw.get("reasoning")),
        "thinkingLevels": _supported_thinking_levels(raw),
        "supportsImages": "image" in {str(item) for item in inputs},
        "contextWindow": _integer(raw.get("contextWindow")),
        "maxTokens": _integer(raw.get("maxTokens")),
    }


def _supported_thinking_levels(raw: Mapping[str, object]) -> list[str]:
    if not bool(raw.get("reasoning")):
        return ["off"]
    explicit = raw.get("thinkingLevels")
    if isinstance(explicit, list):
        allowed = {"off", "minimal", "low", "medium", "high", "xhigh", "max"}
        levels = [str(level) for level in explicit if str(level) in allowed]
        return list(dict.fromkeys(levels)) or ["off"]
    mapping = _mapping(raw.get("thinkingLevelMap"))
    levels: list[str] = []
    for level in ("off", "minimal", "low", "medium", "high", "xhigh", "max"):
        mapped = mapping.get(level)
        if mapped is None and level in mapping:
            continue
        if level in {"xhigh", "max"} and level not in mapping:
            continue
        levels.append(level)
    return levels or ["off"]


def _effective_thinking_level(value: object, selected: Mapping[str, object]) -> str:
    normalized = str(value or "off").strip().lower() or "off"
    supported = selected.get("thinkingLevels")
    if not isinstance(supported, list) or normalized not in supported:
        return "off"
    return normalized


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _pi_model_configuration_from_environment() -> tuple[
    str,
    str,
    str,
    dict[str, str],
    dict[str, Mapping[str, object]],
    str,
]:
    explicit_provider = os.environ.get("RAG_IME_PI_PROVIDER", "").strip()
    explicit_model = os.environ.get("RAG_IME_PI_MODEL", "").strip()
    providers: dict[str, Mapping[str, object]] = {}
    provider_environment: dict[str, str] = {}
    deepseek_error = ""
    try:
        knowledge = load_deepseek_config()
    except (OSError, ValueError) as exc:
        knowledge = None
        deepseek_error = f"DeepSeek 配置不可用：{exc}"

    model_base_url = ""
    deepseek_model = ""
    if knowledge is not None and knowledge.provider_name == "deepseek":
        model_base_url = knowledge.api_base_url
        deepseek_model = knowledge.model
        endpoint = urlsplit(model_base_url)
        if endpoint.scheme != "https" or not endpoint.hostname:
            deepseek_error = "Pi DeepSeek 网关必须使用有效的 HTTPS 地址"
        elif not deepseek_model:
            deepseek_error = "尚未选择 Pi DeepSeek 模型"
        elif not knowledge.api_key:
            deepseek_error = "尚未在模型设置中配置 DeepSeek 凭据"
        elif knowledge.extra_headers:
            deepseek_error = "带自定义请求头的 DeepSeek 网关尚未接入 Pi 隔离配置"
        else:
            providers["deepseek"] = _deepseek_pi_provider(
                model_base_url,
                model=deepseek_model,
                supports_reasoning=knowledge.pi_supports_reasoning,
                supports_reasoning_effort=knowledge.pi_supports_reasoning_effort,
                supports_usage_in_streaming=knowledge.pi_supports_usage_in_streaming,
                requires_reasoning_content=knowledge.pi_requires_reasoning_content,
                thinking_format=knowledge.pi_thinking_format,
            )
            provider_environment["DEEPSEEK_API_KEY"] = knowledge.api_key
            deepseek_error = ""

    imported_error = ""
    imported_first_provider = ""
    imported_first_model = ""
    provider_config_path = os.environ.get("RAG_IME_PI_PROVIDER_CONFIG", "").strip()
    if provider_config_path:
        try:
            imported = load_pi_provider_config(provider_config_path)
        except (OSError, PiProviderConfigError) as exc:
            imported_error = str(exc)
        else:
            providers.update(imported.providers)
            provider_environment.update(imported.environment)
            imported_first_provider = imported.first_provider
            imported_first_model = imported.first_model

    provider = explicit_provider or ("deepseek" if "deepseek" in providers else imported_first_provider)
    if provider == "deepseek":
        model = explicit_model or deepseek_model
    else:
        model = explicit_model or _first_provider_model(providers.get(provider)) or imported_first_model
    configured_ids = _configured_model_ids(providers.get(provider))
    if configured_ids and model not in configured_ids:
        model = configured_ids[0]

    if not providers:
        error = imported_error or deepseek_error or "尚未配置 Pi 对话模型"
        return provider, model, model_base_url, {}, {}, error
    if provider not in providers:
        return (
            provider,
            model,
            model_base_url,
            provider_environment,
            providers,
            f"当前 Pi Provider 不可用：{provider or '<empty>'}",
        )
    if not model:
        return provider, model, model_base_url, provider_environment, providers, "尚未选择 Pi 对话模型"
    # An optional imported provider must not take a working DeepSeek route down.
    # It becomes fatal only when the user explicitly selected that provider.
    if imported_error and explicit_provider and explicit_provider != "deepseek":
        return provider, model, model_base_url, provider_environment, providers, imported_error
    return provider, model, model_base_url, provider_environment, providers, ""


def _deepseek_pi_provider(
    base_url: str,
    *,
    model: str = "",
    supports_reasoning: bool = True,
    supports_reasoning_effort: bool = True,
    supports_usage_in_streaming: bool = True,
    requires_reasoning_content: bool = True,
    thinking_format: str = "deepseek",
) -> dict[str, object]:
    provider: dict[str, object] = {
        "baseUrl": base_url,
        "apiKey": "$DEEPSEEK_API_KEY",
        "compat": {
            "supportsStore": False,
            "supportsDeveloperRole": False,
            "supportsReasoningEffort": supports_reasoning_effort,
            "supportsUsageInStreaming": supports_usage_in_streaming,
            "requiresReasoningContentOnAssistantMessages": requires_reasoning_content,
            "thinkingFormat": thinking_format,
        },
    }
    if not supports_reasoning:
        model_ids = {"deepseek-v4-flash", "deepseek-v4-pro"}
        if model.strip():
            model_ids.add(model.strip())
        provider["modelOverrides"] = {
            model_id: {"reasoning": False}
            for model_id in sorted(model_ids)
        }
    return provider


def _first_provider_model(provider: Mapping[str, object] | None) -> str:
    if not isinstance(provider, Mapping):
        return ""
    models = provider.get("models")
    if not isinstance(models, list) or not models:
        return ""
    first = models[0]
    return str(first.get("id") or "").strip() if isinstance(first, Mapping) else ""


def _configured_model_ids(provider: Mapping[str, object] | None) -> list[str]:
    if not isinstance(provider, Mapping):
        return []
    raw_models = provider.get("models")
    if not isinstance(raw_models, list):
        return []
    return [
        model_id
        for value in raw_models
        if isinstance(value, Mapping)
        for model_id in [str(value.get("id") or "").strip()]
        if model_id
    ]


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        value = default
    return min(maximum, max(minimum, value))
