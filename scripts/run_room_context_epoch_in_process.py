#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import plistlib
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Iterator, Mapping
from urllib.parse import urlsplit


PRODUCT_ROOT = Path(__file__).resolve().parents[1]
if str(PRODUCT_ROOT) not in sys.path:
    sys.path.insert(0, str(PRODUCT_ROOT))

from in_process_control_api import FileFetchBridge, InProcessControlApi
from agent_session_dialogue_canary import (
    READ_BOUNDARY_PATH,
    READ_BOUNDARY_SOURCE,
    run as run_agent_session_canary,
)
from room_context_epoch_canary import run as run_epoch_canary
from room_project_task_canary import (
    PROJECT_MEMORY_TEXT,
    TEST_COMMAND,
    run as run_project_task_canary,
    seed_project_workspace,
)
from room_three_member_canary import run as run_three_member_canary

from rag_ime.agent_configuration import default_agent_configuration
from rag_ime.agent_service import AgentService
from rag_ime.agent_workspace import PreparedWorkspaceCommand, WorkspaceHarness
from rag_ime.debug_server import DebugImeService, DebugServerConfig
from rag_ime.embeddings import HashingEmbeddingProvider, embedding_provider_from_env
from rag_ime.local_sqlite_core import LocalSqliteCoreClient
from rag_ime.pi_runtime import PiRuntimeConfig
from rag_ime.retrieval_docs import rebuild_retrieval_docs


PROJECT = "wisdom-weasel-rag-ime"
COLLABORATION_SCENARIO = "project-collaboration"
AGENT_SESSION_SCENARIO = "agent-session"
COLLABORATION_COMPACTION_KEEP_RECENT_TOKENS = 1
PROJECT_SCENARIOS = frozenset(
    {"project-task", "project-resilience", COLLABORATION_SCENARIO}
)
WORKSPACE_SCENARIOS = PROJECT_SCENARIOS | {AGENT_SESSION_SCENARIO}
BRIDGE_URL = "http://rag-ime-file-bridge.invalid/api/agent/tool/execute"
DETERMINISTIC_PROVIDER = "rag-ime-deterministic"
DETERMINISTIC_MODEL = "room-v2-test"
_EXCLUDED_LAUNCH_ENV = {
    "RAG_IME_AGENT_GATEWAY_WEB_DIST",
    "RAG_IME_AGENT_TOOL_URL",
    "RAG_IME_APP_SUPPORT_DIR",
    "RAG_IME_DB_PATH",
    "RAG_IME_INSTALL_MARKER",
    "RAG_IME_ROOT",
    "RAG_IME_SOURCE_ROOT",
}


class _NoopPredictionProvider:
    def predict(
        self,
        *,
        current_input: str,
        recent_context: str = "",
        max_candidates: int = 5,
    ) -> list[object]:
        _ = current_input, recent_context, max_candidates
        return []


def _launch_environment(path: Path) -> dict[str, str]:
    payload = plistlib.loads(path.expanduser().read_bytes())
    raw = payload.get("EnvironmentVariables")
    if not isinstance(raw, dict):
        raise RuntimeError("Agent Gateway LaunchAgent has no EnvironmentVariables")
    return {
        str(key): str(value)
        for key, value in raw.items()
        if str(key) not in _EXCLUDED_LAUNCH_ENV
    }


@contextmanager
def _temporary_environment(values: Mapping[str, str]) -> Iterator[None]:
    previous = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@contextmanager
def _state_directory(root: Path, *, keep: bool) -> Iterator[Path]:
    root.mkdir(parents=True, exist_ok=True)
    if keep:
        yield Path(
            tempfile.mkdtemp(
                prefix="rag-ime-context-epoch-api-",
                dir=root,
            )
        )
        return
    with tempfile.TemporaryDirectory(
        prefix="rag-ime-context-epoch-api-",
        dir=root,
    ) as temporary:
        yield Path(temporary)


def _copy_failure_state(state: Path, destination: Path, db_path: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)

    def ignore(_directory: str, names: list[str]) -> set[str]:
        return {
            name
            for name in names
            if name in {"auth.json", "file-fetch-bridge"}
            or name.startswith("rag-ime.sqlite")
        }

    shutil.copytree(state, destination, ignore=ignore)
    with (
        sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as source,
        sqlite3.connect(destination / "rag-ime.sqlite") as target,
    ):
        source.backup(target)


def _configure_compaction_for_audit(
    agent_dir: Path,
    *,
    auto_compaction_enabled: bool,
    keep_recent_tokens: int | None = None,
) -> None:
    agent_dir.mkdir(parents=True, exist_ok=True)
    compaction: dict[str, object] = {"enabled": auto_compaction_enabled}
    if keep_recent_tokens is not None:
        compaction["keepRecentTokens"] = max(1, int(keep_recent_tokens))
    (agent_dir / "settings.json").write_text(
        json.dumps(
            {"compaction": compaction},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )


def _seed_relevant_memory(
    db_path: Path,
    *,
    embedding_provider: object,
    scenario: str,
) -> None:
    now_ms = int(time.time() * 1000)
    project_task = scenario in WORKSPACE_SCENARIOS
    atom_id = (
        "atom:room-project-task-canary"
        if project_task
        else "atom:room-context-epoch-canary"
    )
    atom_text = (
        PROJECT_MEMORY_TEXT
        if project_task
        else (
            "Room 压缩后每个 context epoch 只补回一份恢复包，永久保留原始需求、"
            "当前任务、验收、阻塞、交接和精确能力回执。"
        )
    )
    claim_key = (
        "room-project-task-workflow"
        if project_task
        else "room-context-epoch-recovery"
    )
    book_id = (
        "book:room-project-task-canary"
        if project_task
        else "book:room-context-epoch-canary"
    )
    book_title = "代码任务交付偏好" if project_task else "Room 上下文恢复约定"
    book_summary = (
        "代码任务使用最小改动、真实测试和证据化交付。"
        if project_task
        else "上下文恢复使用简洁、直接、可执行的用户偏好。"
    )
    normalized_text = (
        f"代码 项目 测试 最小改动 交付 Room Agent {book_summary}"
        if project_task
        else f"Room 上下文 恢复 压缩 epoch 原始需求 验收 交接 {book_summary}"
    )
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute(
            """
            INSERT INTO memory_atoms(
                id, kind, text, canonical_text, source_event_ids_json,
                source_memory_ids_json, scope_app, scope_project, language,
                confidence, quality_score, echo_risk, privacy_level, status,
                created_at_ms, updated_at_ms, last_used_at_ms, claim_key,
                lineage_id, claim_state, valid_from_ms, valid_to_ms,
                supersedes_id
            ) VALUES (?, 'preference', ?, ?, '[]', '[]', NULL, ?, 'zh',
                      1.0, 1.0, 0.0, 'local', 'active', ?, ?, NULL,
                      ?, ?, 'current', ?, NULL, NULL)
            """,
            (
                atom_id,
                atom_text,
                atom_text,
                PROJECT,
                now_ms,
                now_ms,
                claim_key,
                f"lineage:{claim_key}",
                now_ms,
            ),
        )
        connection.execute(
            """
            INSERT INTO memory_books(
                book_id, book_type, book_key, title, summary, normalized_text,
                project, app, tags_json, surface_hints_json,
                query_expansions_json, source_event_ids_json,
                memory_atom_ids_json, status, confidence, quality_score,
                created_at_ms, updated_at_ms, metadata_json
            ) VALUES (
                ?, 'topic', ?, ?, ?, ?, ?, '',
                '["Room","压缩","恢复"]', '[]', '[]', '[]', ?, 'active',
                1.0, 1.0, ?, ?, '{}'
            )
            """,
            (
                book_id,
                claim_key,
                book_title,
                book_summary,
                normalized_text,
                PROJECT,
                json.dumps([atom_id], ensure_ascii=False),
                now_ms,
                now_ms,
            ),
        )
        rebuild_retrieval_docs(connection, project=PROJECT)
    # Force one real embedding before the model turn so a broken configured
    # provider cannot silently degrade this canary to lexical-only retrieval.
    vector = embedding_provider.embed(atom_text)  # type: ignore[attr-defined]
    if not vector:
        raise RuntimeError("configured embedding provider returned an empty vector")


def _report_session_ids(report: Mapping[str, object]) -> tuple[str, ...]:
    members = report.get("members")
    session_ids = tuple(dict.fromkeys(
        str(item.get("sessionId") or "")
        for item in members.values()
        if isinstance(item, Mapping) and str(item.get("sessionId") or "")
    )) if isinstance(members, Mapping) else ()
    if not session_ids:
        fallback = str(report.get("sessionId") or "")
        session_ids = (fallback,) if fallback else ()
    if not session_ids:
        raise RuntimeError("Room canary report has no Session for capability audit")
    return session_ids


def _room_tool_surface_evidence(
    service: DebugImeService,
    db_path: Path,
    report: Mapping[str, object],
) -> dict[str, object]:
    session_ids = _report_session_ids(report)
    normal_tool_sets = [
        {
            str(item["name"])
            for item in service.agent_tools.runtime_manifests(
                service.agent.sessions.get(session_id)
            )
        }
        for session_id in session_ids
    ]
    normal_tools = set().union(*normal_tool_sets)
    normal_surfaces_consistent = all(
        tools == normal_tools for tools in normal_tool_sets
    )
    dispatch = report.get("dispatch")
    if not isinstance(dispatch, Mapping):
        epochs = report.get("epochs")
        if isinstance(epochs, list) and epochs and isinstance(epochs[-1], Mapping):
            dispatch = epochs[-1].get("dispatch")
    dispatch_ids = (
        [str(value) for value in dispatch.get("dispatchIds") or []]
        if isinstance(dispatch, Mapping)
        else []
    )
    if not dispatch_ids:
        raise RuntimeError("Room canary has no Dispatch for capability audit")
    placeholders = ",".join("?" for _ in dispatch_ids)
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            f"""
            SELECT payload_json
            FROM room_v2_capability_manifests
            WHERE dispatch_id IN ({placeholders})
            ORDER BY created_at_ms, manifest_id
            """,
            dispatch_ids,
        ).fetchall()
    if not rows:
        raise RuntimeError("Room canary has no Capability Manifest")
    product_tools: set[str] = set()
    denied_product_tools: set[str] = set()
    for row in rows:
        payload = json.loads(str(row[0]))
        for item in payload.get("tools") or []:
            if not isinstance(item, dict) or not str(
                item.get("operation") or ""
            ).startswith("product."):
                continue
            target = product_tools if item.get("authorized") is True else denied_product_tools
            target.add(str(item.get("name") or ""))
    material = "\n".join(sorted(product_tools)).encode("utf-8")
    normal_material = "\n".join(sorted(normal_tools)).encode("utf-8")
    critical = {
        "workspace_read",
        "workspace_search",
        "workspace_patch",
        "workspace_shell",
        "ime_memory",
        "ime_browser",
        "desktop_semantic",
    }
    return {
        "passed": (
            normal_surfaces_consistent
            and product_tools == normal_tools
            and not denied_product_tools
        ),
        "normalAgentSessionCount": len(session_ids),
        "normalAgentSurfacesConsistent": normal_surfaces_consistent,
        "normalAgentToolCount": len(normal_tools),
        "roomAuthorizedProductToolCount": len(product_tools),
        "roomDeniedProductToolCount": len(denied_product_tools),
        "normalAgentToolsSha256": hashlib.sha256(normal_material).hexdigest(),
        "roomAuthorizedToolsSha256": hashlib.sha256(material).hexdigest(),
        "criticalWorkToolsPresent": critical <= product_tools,
    }


def _agent_tool_surface_evidence(
    service: DebugImeService,
    report: Mapping[str, object],
) -> dict[str, object]:
    session_id = str(report.get("sessionId") or "")
    if not session_id:
        raise RuntimeError("Agent Session canary report has no Session")
    tools = {
        str(item["name"])
        for item in service.agent_tools.runtime_manifests(
            service.agent.sessions.get(session_id)
        )
    }
    critical = {
        "workspace_read",
        "workspace_search",
        "workspace_patch",
        "workspace_shell",
        "ime_memory",
        "ime_browser",
        "desktop_semantic",
    }
    material = "\n".join(sorted(tools)).encode("utf-8")
    return {
        "passed": critical <= tools,
        "normalAgentSessionCount": 1,
        "normalAgentToolCount": len(tools),
        "normalAgentToolsSha256": hashlib.sha256(material).hexdigest(),
        "criticalWorkToolsPresent": critical <= tools,
        "roomCapabilityManifestRequired": False,
    }


def _isolated_project_command_executor(
    prepared: PreparedWorkspaceCommand,
    *,
    workspace: Path,
) -> dict[str, object]:
    resolved_workspace = workspace.resolve(strict=True)
    if (
        prepared.command != TEST_COMMAND
        or prepared.cwd != resolved_workspace
        or prepared.roots != (resolved_workspace,)
        or prepared.allow_network
    ):
        raise RuntimeError("isolated Room project executor rejected an unexpected command")
    started_at_ms = int(time.time() * 1_000)
    try:
        completed = subprocess.run(
            TEST_COMMAND.split(),
            cwd=resolved_workspace,
            env={
                "HOME": str(resolved_workspace),
                "TMPDIR": str(resolved_workspace),
                "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                "LANG": "en_US.UTF-8",
                "LC_ALL": "en_US.UTF-8",
            },
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=prepared.timeout_seconds,
            check=False,
        )
        output = completed.stdout[: 1024 * 1024]
        exit_code = int(completed.returncode)
        timed_out = False
        output_limited = len(completed.stdout) > len(output)
    except subprocess.TimeoutExpired as error:
        output = bytes(error.stdout or b"")[: 1024 * 1024]
        exit_code = 124
        timed_out = True
        output_limited = len(bytes(error.stdout or b"")) > len(output)
    duration_ms = max(0, int(time.time() * 1_000) - started_at_ms)
    succeeded = exit_code == 0 and not timed_out and not output_limited
    return {
        "schemaVersion": "rag-ime.workspace-command-receipt.v1",
        "mutationApplied": succeeded,
        "summary": f"命令执行完成，退出码 {exit_code}",
        "commandSha256": hashlib.sha256(prepared.command.encode("utf-8")).hexdigest(),
        "cwd": str(prepared.cwd),
        "exitCode": exit_code,
        "durationMs": duration_ms,
        "timedOut": timed_out,
        "outputLimited": output_limited,
        "networkAllowed": False,
        "output": output.decode("utf-8", errors="replace"),
        "outputBytes": len(output),
        "undoAvailable": False,
    }


def _git_revision(root: Path) -> dict[str, object]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    dirty = bool(
        subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    )
    return {"commit": commit, "dirty": dirty}


def _provider_endpoint(runtime: PiRuntimeConfig) -> str:
    if runtime.provider == "openai-codex":
        return "https://chatgpt.com"
    base_url = runtime.model_base_url if runtime.provider == "deepseek" else ""
    if not base_url:
        provider = runtime.model_providers.get(runtime.provider)
        if isinstance(provider, Mapping):
            base_url = str(provider.get("baseUrl") or "")
    parsed = urlsplit(base_url)
    if parsed.scheme != "https" or not parsed.hostname:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


def _configured_model_available(
    runtime: PiRuntimeConfig,
    *,
    provider: str,
    model: str,
) -> bool:
    """Mirror Pi's model validation for built-in and imported providers."""

    configured = runtime.model_providers.get(provider)
    if not isinstance(configured, Mapping):
        return False
    raw_models = configured.get("models")
    if not isinstance(raw_models, list) or not raw_models:
        # Built-in provider catalogs, such as DeepSeek, are resolved by Pi and
        # therefore do not duplicate their model list in managed models.json.
        return True
    configured_model_ids = {
        str(item.get("id") or "").strip()
        for item in raw_models
        if isinstance(item, Mapping)
    }
    return model in configured_model_ids


def _external_network_audit(
    path: Path,
    *,
    expected_endpoint: str,
) -> dict[str, object]:
    entries: list[dict[str, object]] = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                entries.append(item)
    expected = urlsplit(expected_endpoint)
    expected_host = expected.netloc
    matching = [
        item
        for item in entries
        if str(item.get("protocol") or "") == "https:"
        and str(item.get("host") or "") == expected_host
    ]
    matching_success = [
        200 <= int(item.get("status") or 0) < 300
        for item in matching
    ]
    first_failed_index = next(
        (index for index, succeeded in enumerate(matching_success) if not succeeded),
        None,
    )
    recovered_after_failure = (
        first_failed_index is not None
        and any(matching_success[first_failed_index + 1 :])
    )
    return {
        "schemaVersion": "wisdom-weasel.external-provider-network-evidence.v2",
        "expectedEndpoint": expected_endpoint,
        "requestCount": len(entries),
        "matchingRequestCount": len(matching),
        "successfulMatchingRequestCount": sum(matching_success),
        "failedMatchingRequestCount": len(matching_success) - sum(matching_success),
        "allMatchingRequestsSucceeded": bool(matching) and all(matching_success),
        "terminalMatchingRequestSucceeded": bool(matching_success)
        and matching_success[-1],
        "recoveredAfterFailure": recovered_after_failure,
        "requests": [
            {
                "requestId": str(item.get("requestId") or ""),
                "host": str(item.get("host") or ""),
                "pathname": str(item.get("pathname") or ""),
                "method": str(item.get("method") or ""),
                "status": int(item.get("status") or 0),
                "durationMs": max(
                    0,
                    int(item.get("completedAtMs") or 0)
                    - int(item.get("startedAtMs") or 0),
                ),
            }
            for item in entries
        ],
    }


def _create_deterministic_canary_roles(
    api: InProcessControlApi,
    *,
    collaboration: bool = False,
) -> list[dict[str, str]]:
    roles: list[dict[str, str]] = []
    specs = (
        (
            ("A", "terra", "implementer"),
            ("B", "sol", "reviewer"),
            ("C", "terra", "coordinator"),
        )
        if collaboration
        else (
            ("A", "terra", ""),
            ("B", "sol", ""),
        )
    )
    for suffix, timeline, collaboration_role in specs:
        created = api.request_json(
            "http://in-process.invalid",
            "POST",
            "/api/agent/roles",
            {
                "displayName": f"压缩验收伙伴 {suffix}",
                "tagline": "只在隔离验收中驱动确定性 Room 生命周期",
                "summary": "用于验证工具发现、责任提交、压缩和恢复，不进入正式数据。",
                "traits": ["精确", "可复核"],
                "timelineModel": timeline,
                "selectableModes": ["assistant", "coordinator"],
                "suitableTasks": ["Room 上下文验收", "压缩恢复验收"],
                "unsuitableTasks": ["正式用户任务"],
            },
        )["role"]
        role = {
            "roleId": str(created["roleId"]),
            "roleVersion": str(created["version"]),
        }
        if collaboration_role:
            role["collaborationRole"] = collaboration_role
        roles.append(role)
    return roles


def run(args: argparse.Namespace) -> dict[str, object]:
    product_root = PRODUCT_ROOT
    source_workspace = args.workspace.expanduser().resolve(strict=True)
    payload = args.pi_payload.expanduser().resolve(strict=True)
    manifest_path = payload / "manifest.json"
    node = payload / "bin" / "node"
    entrypoint = payload / "runtime-host" / "cli.mjs"
    for required in (manifest_path, node, entrypoint):
        if not required.is_file():
            raise RuntimeError(f"managed Pi payload is incomplete: {required}")
    pi_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    launch_environment = _launch_environment(args.launch_agent_plist)
    with _state_directory(args.temp_root, keep=args.keep_state) as state:
        project_seed: dict[str, object] = {}
        if args.scenario in WORKSPACE_SCENARIOS:
            workspace = state / "project-workspace"
            project_seed = seed_project_workspace(workspace)
            if args.scenario == AGENT_SESSION_SCENARIO:
                boundary_path = workspace / READ_BOUNDARY_PATH
                boundary_path.write_text(
                    READ_BOUNDARY_SOURCE,
                    encoding="utf-8",
                )
                project_seed["files"][READ_BOUNDARY_PATH] = {
                    "bytes": len(READ_BOUNDARY_SOURCE.encode("utf-8")),
                    "sha256": hashlib.sha256(
                        READ_BOUNDARY_SOURCE.encode("utf-8")
                    ).hexdigest(),
                }
        else:
            workspace = source_workspace
        bridge_root = state / "file-fetch-bridge"
        bridge_script = bridge_root / "bridge.cjs"
        network_audit_path = state / "external-network-audit.jsonl"
        bridge_root.mkdir(parents=True, mode=0o700)
        shutil.copy2(product_root / "scripts" / "pi_file_fetch_bridge.cjs", bridge_script)
        app_support = state / "app-support"
        agent_dir = app_support / "Agent" / "config"
        _configure_compaction_for_audit(
            agent_dir,
            auto_compaction_enabled=not args.disable_auto_compaction,
            keep_recent_tokens=(
                # The three members can legitimately produce very different
                # amounts of private history. Keep one token in this isolated
                # audit so even a concise reviewer has a deterministic
                # compaction boundary; production settings are untouched.
                COLLABORATION_COMPACTION_KEEP_RECENT_TOKENS
                if args.scenario
                in {COLLABORATION_SCENARIO, AGENT_SESSION_SCENARIO}
                else None
            ),
        )
        db_path = state / "rag-ime.sqlite"
        debug_context = state / "context-inspection"
        environment = {
            **launch_environment,
            "RAG_IME_APP_SUPPORT_DIR": str(app_support),
            "RAG_IME_PI_ENABLED": "1",
            "RAG_IME_PI_EXECUTABLE": str(entrypoint),
            "RAG_IME_PI_NODE": str(node),
            "RAG_IME_PI_PROTOCOL_VERSION": "2",
            "RAG_IME_PI_DEBUG_CONTEXT_DIR": str(debug_context),
            "RAG_IME_PI_DEBUG_CONTEXT_MAX_BYTES": str(128 * 1024 * 1024),
            "RAG_IME_PI_DEBUG_CONTEXT_MAX_CALLS": "128",
            "RAG_IME_AGENT_TOOL_URL": BRIDGE_URL,
            "RAG_IME_ROOM_KERNEL_MODE": "cohort",
            "RAG_IME_ROOM_KERNEL_COHORT_ID": "room-v2-test",
        }
        with _temporary_environment(environment):
            base_runtime = PiRuntimeConfig.from_environment(enabled_default=True)
            if args.provider_mode == "configured" and not base_runtime.model_configured:
                raise RuntimeError(base_runtime.model_configuration_error)
            selected_provider = str(args.model_provider or "").strip() or base_runtime.provider
            selected_model = str(args.model_id or "").strip() or base_runtime.model
            if args.provider_mode == "configured" and not _configured_model_available(
                base_runtime,
                provider=selected_provider,
                model=selected_model,
            ):
                raise RuntimeError(
                    f"configured model is unavailable: {selected_provider}/{selected_model}"
                )
            model_environment = (
                dict(base_runtime.provider_environment)
                if args.provider_mode == "configured"
                else {
                    "NODE_ENV": "test",
                    "RAG_IME_PI_DETERMINISTIC_ADAPTER": "room-v2",
                    "RAG_IME_PI_DETERMINISTIC_SCENARIO": (
                        "project-task"
                        if args.scenario in {
                            "project-task",
                            "project-resilience",
                        }
                        else args.scenario
                    ),
                }
            )
            provider_environment = {
                **model_environment,
                "NODE_OPTIONS": f"--require={json.dumps(str(bridge_script))}",
                "RAG_IME_FILE_FETCH_BRIDGE_DIR": str(bridge_root),
                "RAG_IME_FILE_FETCH_BRIDGE_TIMEOUT_MS": str(
                    int(args.turn_timeout * 1000)
                ),
                "RAG_IME_EXTERNAL_NETWORK_AUDIT_PATH": str(network_audit_path),
            }
            runtime = replace(
                base_runtime,
                enabled=True,
                executable=entrypoint,
                node_executable=str(node),
                extension_path=None,
                agent_dir=agent_dir,
                session_dir=app_support / "Agent" / "sessions",
                logs_dir=app_support / "Agent" / "logs",
                debug_context_dir=debug_context,
                protocol_version="2",
                command_timeout_seconds=max(30.0, args.turn_timeout),
                idle_timeout_seconds=0,
                provider_environment=provider_environment,
                provider=(
                    selected_provider
                    if args.provider_mode == "configured"
                    else DETERMINISTIC_PROVIDER
                ),
                model=(
                    selected_model
                    if args.provider_mode == "configured"
                    else DETERMINISTIC_MODEL
                ),
                model_providers=(
                    base_runtime.model_providers
                    if args.provider_mode == "configured"
                    else {}
                ),
                model_base_url=(
                    base_runtime.model_base_url
                    if args.provider_mode == "configured"
                    else ""
                ),
                model_configured=True,
                model_configuration_error="",
            )
            embedding_provider = (
                HashingEmbeddingProvider(dimensions=192)
                if args.embedding_mode == "hashing"
                else embedding_provider_from_env()
            )
            core = LocalSqliteCoreClient(
                db_path,
                embedding_provider=embedding_provider,
            )
            core.initialize()
            agent = AgentService(
                db_path=db_path,
                runtime_config=runtime,
                configuration_defaults=default_agent_configuration(
                    enabled=True,
                    idle_timeout_seconds=0,
                    role_id="companion-future-v1",
                    role_version="1",
                    model_profile=f"{runtime.provider}/{runtime.model}",
                    tool_profile_version="control-center-v1",
                    resume_last_session=False,
                    coordinator_enabled=True,
                ),
                project=PROJECT,
                tool_gateway_url=BRIDGE_URL,
                memory_embedding_provider=embedding_provider,
                wake_scheduler_enabled=False,
                room_kernel_mode="cohort",
                room_delivery_gate_enforcement=False,
                room_kernel_poll_seconds=0.05,
            )
            service = DebugImeService(
                DebugServerConfig(
                    db_path=db_path,
                    project=PROJECT,
                    static_dir=product_root / "control-center-web" / "dist",
                    seed_if_empty=False,
                    core=core,
                    predictor=_NoopPredictionProvider(),
                    server_name="agent gateway",
                    include_raw_text=True,
                    agent_service=agent,
                    knowledge_client=object(),
                    memory_projection_worker_enabled=False,
                )
            )
            if (
                args.scenario in WORKSPACE_SCENARIOS
                and args.workspace_shell_mode == "isolated-test"
            ):
                service.agent_tools.workspace_harness = WorkspaceHarness(
                    executor=lambda prepared: _isolated_project_command_executor(
                        prepared,
                        workspace=workspace,
                    )
                )
            api = InProcessControlApi(
                service,
                static_dir=service.config.static_dir,
                max_response_bytes=128 * 1024 * 1024,
            )
            bridge = FileFetchBridge(bridge_root, api)
            bridge.start()
            try:
                _seed_relevant_memory(
                    db_path,
                    embedding_provider=embedding_provider,
                    scenario=args.scenario,
                )
                participant_roles = (
                    _create_deterministic_canary_roles(
                        api,
                        collaboration=(
                            args.scenario == COLLABORATION_SCENARIO
                        ),
                    )
                    if args.provider_mode == "deterministic"
                    else (
                        [
                            {
                                "roleId": "companion-present-v1",
                                "roleVersion": "1",
                                "collaborationRole": "implementer",
                            },
                            {
                                "roleId": "companion-firstlight-v1",
                                "roleVersion": "1",
                                "collaborationRole": "reviewer",
                            },
                            {
                                "roleId": "companion-future-v1",
                                "roleVersion": "1",
                                "collaborationRole": "coordinator",
                            },
                        ]
                        if args.scenario == COLLABORATION_SCENARIO
                        else [
                        {"roleId": "companion-future-v1", "roleVersion": "1"},
                        {"roleId": "companion-present-v1", "roleVersion": "1"},
                        ]
                    )
                )
                common_canary_args = {
                    "base_url": "http://in-process.invalid",
                    "db_path": db_path,
                    "workspace": workspace,
                    "pi_session_dir": runtime.session_dir,
                    "turn_timeout": args.turn_timeout,
                    "participant_roles": participant_roles,
                    "thinking_level": (
                        str(args.thinking_level or "").strip()
                        or ("off" if args.provider_mode == "deterministic" else "")
                    ),
                    "model_provider": runtime.provider,
                    "model_id": runtime.model,
                    "compact_after": args.scenario == "project-resilience",
                    "require_cache_evidence": (
                        args.provider_mode == "configured"
                    ),
                    "provider_mode": args.provider_mode,
                }
                if args.scenario == AGENT_SESSION_SCENARIO:
                    report = run_agent_session_canary(
                        argparse.Namespace(**common_canary_args),
                        requester=api.request_json,
                    )
                    report["projectSeed"] = project_seed
                elif args.scenario == COLLABORATION_SCENARIO:
                    report = run_three_member_canary(
                        argparse.Namespace(**common_canary_args),
                        requester=api.request_json,
                    )
                    report["projectSeed"] = project_seed
                elif args.scenario in PROJECT_SCENARIOS:
                    report = run_project_task_canary(
                        argparse.Namespace(
                            **common_canary_args,
                            failure_probe=args.scenario == "project-resilience",
                        ),
                        requester=api.request_json,
                    )
                    report["projectSeed"] = project_seed
                else:
                    report = run_epoch_canary(
                        argparse.Namespace(
                            **common_canary_args,
                            workload_file=list(args.workload_file or []),
                            epochs=args.epochs,
                            require_cache_evidence=(
                                args.provider_mode == "configured"
                            ),
                        ),
                        requester=api.request_json,
                    )
                tool_surface = (
                    _agent_tool_surface_evidence(service, report)
                    if args.scenario == AGENT_SESSION_SCENARIO
                    else _room_tool_surface_evidence(
                        service,
                        db_path,
                        report,
                    )
                )
                report["toolSurface"] = tool_surface
                report_checks = dict(report.get("checks") or {})
                report_checks["completeNormalAgentToolSurface"] = (
                    tool_surface["passed"] is True
                    and tool_surface["criticalWorkToolsPresent"] is True
                )
                if args.provider_mode == "configured":
                    endpoint = _provider_endpoint(runtime)
                    network_audit = _external_network_audit(
                        network_audit_path,
                        expected_endpoint=endpoint,
                    )
                    report["externalNetworkAudit"] = network_audit
                    report_checks["externalProviderRequestObserved"] = (
                        bool(endpoint)
                        and network_audit["matchingRequestCount"] > 0
                        and network_audit["successfulMatchingRequestCount"] > 0
                        and network_audit["terminalMatchingRequestSucceeded"] is True
                    )
                report["checks"] = report_checks
                if args.scenario in WORKSPACE_SCENARIOS and args.artifact_dir is not None:
                    artifact_dir = args.artifact_dir.expanduser().resolve()
                    if artifact_dir.exists():
                        shutil.rmtree(artifact_dir)
                    shutil.copytree(workspace, artifact_dir)
                    project_report = report.get("project")
                    if isinstance(project_report, dict):
                        project_report["retainedArtifact"] = str(artifact_dir)
            except BaseException as error:
                runtime_status = service.agent.runtime_status()
                diagnostic = {
                    key: runtime_status.get(key)
                    for key in (
                        "status",
                        "enabled",
                        "installed",
                        "modelConfigured",
                        "lastError",
                        "hostNegotiated",
                    )
                }
                if args.failure_state_dir is not None:
                    failure_state = args.failure_state_dir.expanduser().resolve()
                    _copy_failure_state(state, failure_state, db_path)
                    diagnostic["failureState"] = str(failure_state)
                raise RuntimeError(
                    f"{args.scenario} canary failed: {error}; "
                    f"runtime={json.dumps(diagnostic, ensure_ascii=False)}; "
                    f"state={state if args.keep_state else 'ephemeral'}"
                ) from error
            finally:
                service.close()
                bridge.close()

    checks = dict(report.get("checks") or {})
    return {
        **report,
        "execution": {
            "status": "passed_not_installed" if all(checks.values()) else "failed",
            "productionEnabled": False,
            "transport": "canonical-http-handler-over-socketpair",
            "toolFetchTransport": "ephemeral-file-adapter",
            "product": _git_revision(product_root),
            "piSourceCommit": (pi_manifest.get("source") or {}).get("commit"),
            "piRuntimeVersion": pi_manifest.get("runtimeVersion"),
            "provider": runtime.provider,
            "model": runtime.model,
            "providerMode": args.provider_mode,
            "scenario": args.scenario,
            "providerEvidence": (
                "network-audit-and-provider-usage"
                if checks.get("externalProviderRequestObserved") is True
                else (
                    "configured-without-network-proof"
                    if args.provider_mode == "configured"
                    else "deterministic-test-adapter"
                )
            ),
            "providerEndpoint": str(
                (report.get("externalNetworkAudit") or {}).get(
                    "expectedEndpoint", ""
                )
            ),
            "realProviderKvEvidence": (
                checks.get("realProviderKvCacheObserved") is True
            ),
            "workspaceShellMode": args.workspace_shell_mode,
            "nativeSandboxExecEvidence": (
                args.scenario in WORKSPACE_SCENARIOS
                and args.workspace_shell_mode == "native"
            ),
            "embeddingProvider": getattr(embedding_provider, "fingerprint", ""),
            "embeddingMode": args.embedding_mode,
            "autoCompactionDuringTask": not args.disable_auto_compaction,
            "manualCompactionKeepRecentTokens": (
                COLLABORATION_COMPACTION_KEEP_RECENT_TOKENS
                if args.scenario
                in {COLLABORATION_SCENARIO, AGENT_SESSION_SCENARIO}
                else None
            ),
            "state": str(state) if args.keep_state else "ephemeral",
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the real Room context epoch API canary without binding a local port "
            "or touching the formal installation"
        )
    )
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--pi-payload", type=Path, required=True)
    parser.add_argument(
        "--scenario",
        choices=(
            "context-epoch",
            "project-task",
            "project-resilience",
            COLLABORATION_SCENARIO,
            AGENT_SESSION_SCENARIO,
        ),
        default="context-epoch",
    )
    parser.add_argument(
        "--launch-agent-plist",
        type=Path,
        default=Path.home() / "Library" / "LaunchAgents" / "com.rag-ime.agent-gateway.plist",
    )
    parser.add_argument("--temp-root", type=Path, default=Path("/tmp"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        help="Retain the successful isolated project for manual inspection",
    )
    parser.add_argument(
        "--workspace-shell-mode",
        choices=("native", "isolated-test"),
        default="native",
        help=(
            "Use production sandbox-exec, or a strict test-only executor when this "
            "canary itself already runs inside a sandbox that forbids nested profiles"
        ),
    )
    parser.add_argument(
        "--failure-state-dir",
        type=Path,
        help="Optional private diagnostic copy retained only when the canary fails",
    )
    parser.add_argument("--turn-timeout", type=float, default=240)
    parser.add_argument("--epochs", type=int, choices=(1, 2, 3), default=1)
    parser.add_argument("--workload-file", type=Path, action="append")
    parser.add_argument(
        "--disable-auto-compaction",
        action="store_true",
        help=(
            "Disable only during the task so the audit can trigger one explicit "
            "post-finalization compaction per epoch. Production defaults stay enabled."
        ),
    )
    parser.add_argument(
        "--keep-state",
        action="store_true",
        help="Keep the isolated test database, transcripts and context receipts for diagnosis",
    )
    parser.add_argument(
        "--provider-mode",
        choices=("configured", "deterministic"),
        default="configured",
        help=(
            "Use the installed Provider configuration, or the explicit offline "
            "Pi test adapter. Deterministic cache usage is synthetic and is never "
            "real Provider KV-cache evidence."
        ),
    )
    parser.add_argument(
        "--model-provider",
        default="",
        help="Override the configured Provider for this isolated canary only.",
    )
    parser.add_argument(
        "--model-id",
        default="",
        help="Override the configured model for this isolated canary only.",
    )
    parser.add_argument(
        "--thinking-level",
        default="",
        help="Override the Session thinking level for this isolated canary only.",
    )
    parser.add_argument(
        "--embedding-mode",
        choices=("configured", "hashing"),
        default="configured",
        help=(
            "Use the installed embedding backend, or the deterministic local "
            "hashing backend when Metal is unavailable in a sandbox"
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    checks = dict(report.get("checks") or {})
    summary = {
        "ok": all(checks.values()),
        "output": str(args.output),
        "checks": checks,
        "execution": report.get("execution"),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
