#!/usr/bin/env python3
"""Run one real Luna/max Agent through the benchmark-only RAG lifecycle Tool."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
from dataclasses import replace
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag_ime.agent_service import AgentService  # noqa: E402
from rag_ime.managed_pi_runtime import snapshot_managed_pi_runtime  # noqa: E402
from rag_ime.pi_runtime import PiRuntimeConfig  # noqa: E402
from rag_ime.rag_benchmark_agent import (  # noqa: E402
    RagBenchmarkAgentGateway,
    RagBenchmarkAgentGatewayServer,
    RagBenchmarkAgentSpoolGateway,
)
from rag_ime.rag_benchmark_sandbox import (  # noqa: E402
    DELETE_CONFIRMATION,
    RagBenchmarkSandbox,
    RagBenchmarkSandboxTool,
)


SCHEMA_VERSION = "rag-ime.rag-benchmark-agent-canary.v4"
REQUIRED_OPERATIONS = (
    "create_run",
    "create_base",
    "import_documents",
    "configure_base",
    "rebuild_preview",
    "rebuild",
    "evaluate_validation",
    "search",
    "status",
    "cleanup",
)
CANARY_VALIDATION_SUITE_ID = "canary-validation-v1"
CANARY_VALIDATION_SUITES = {
    CANARY_VALIDATION_SUITE_ID: [
        {
            "caseId": "travel-approver",
            "split": "validation",
            "query": "北斗项目 差旅 审批人",
            "relevant": {"policy-001": 1},
        },
        {
            "caseId": "security-log",
            "split": "validation",
            "query": "生产 密钥 日志",
            "relevant": {"policy-002": 1},
        },
    ]
}


def main(argv: list[str] | None = None) -> int:
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--private-root",
        type=Path,
        default=ROOT / ".rag-ime-data" / "runs" / "rag-agent-canary",
    )
    parser.add_argument(
        "--source-agent-config",
        type=Path,
        default=(
            Path.home()
            / "Library"
            / "Application Support"
            / "RagIme"
            / "Agent"
            / "config"
        ),
    )
    parser.add_argument("--timeout-seconds", type=float, default=300.0)
    parser.add_argument("--without-skill", action="store_true")
    args = parser.parse_args(argv)

    private_root = args.private_root.expanduser().resolve(strict=False)
    private_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    private_root.chmod(0o700)
    output = args.output.expanduser().resolve(strict=False)
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

    with tempfile.TemporaryDirectory(
        prefix="run-",
        dir=private_root,
    ) as temporary:
        run_root = Path(temporary).resolve(strict=True)
        run_root.chmod(0o700)
        report = _run_canary(
            run_root,
            source_agent_config=args.source_agent_config.expanduser().resolve(strict=True),
            include_skill=not args.without_skill,
            timeout_seconds=max(30.0, float(args.timeout_seconds)),
        )
    _write_json(output, report)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report.get("passed") is True else 1


def _run_canary(
    run_root: Path,
    *,
    source_agent_config: Path,
    include_skill: bool,
    timeout_seconds: float,
) -> dict[str, object]:
    started_at_ms = int(time.time() * 1_000)
    agent_config = run_root / "agent" / "config"
    _copy_private_agent_config(source_agent_config, agent_config)
    runtime_config = _isolated_runtime_config(
        run_root,
        agent_config=agent_config,
    )
    sandbox = RagBenchmarkSandbox(
        run_root / "knowledge-runs",
        evaluation_suites=CANARY_VALIDATION_SUITES,
    )
    gateway = RagBenchmarkAgentGateway(RagBenchmarkSandboxTool(sandbox))
    server: RagBenchmarkAgentGatewayServer | RagBenchmarkAgentSpoolGateway | None = None
    gateway_transport = ""
    service: AgentService | None = None
    session_id = ""
    binding: dict[str, object] = {}
    ensure_before: dict[str, object] = {}
    prompt_receipt: dict[str, object] = {}
    event_payloads: list[dict[str, object]] = []
    terminal_type = ""
    harness_cleanup: list[dict[str, object]] = []
    failure = ""
    try:
        server = _start_rag_benchmark_gateway(
            gateway,
            spool_dir=run_root / "agent" / "tool-spool",
        )
        gateway_transport = server.transport
        service = AgentService(
            db_path=run_root / "agent.sqlite",
            runtime_config=runtime_config,
            project="rag-benchmark-agent-canary",
            tool_gateway_url=server.tool_gateway_url,
            tool_gateway_token=server.token,
            wake_scheduler_enabled=False,
            background_job_execution_owner=False,
        )
        gateway.session_loader = service.sessions.get
        service.bind_tool_manifest_provider(gateway.runtime_manifests)
        session = service.create_session(
            {
                "title": "RAG benchmark Agent canary",
                "mode": "assistant",
                "roleId": "companion-firstlight-v1",
                "roleVersion": "1",
                "toolProfileVersion": "subagent-readonly-v1",
            }
        )["session"]
        session_id = str(session["id"])
        service.update_session(
            session_id,
            {
                "mode": "assistant",
                "executionMode": "read_only",
                "toolProfileVersion": "subagent-readonly-v1",
                "projectContextEnabled": False,
                "piSkillsEnabled": include_skill,
                "codexSkillsEnabled": False,
                "workspaceRoots": [],
            },
        )
        binding = gateway.bind_session(session_id)
        ensure_before = service.ensure_runtime({"sessionId": session_id})
        _assert_luna_max(ensure_before)
        prompt_receipt = service.prompt(
            session_id,
            {
                "message": _canary_prompt(include_skill=include_skill),
                "clientMessageId": f"rag-canary:{started_at_ms}",
            },
        )
        turn_id = str(prompt_receipt.get("turnId") or "")
        event_payloads, terminal_type = _wait_for_terminal(
            service,
            session_id=session_id,
            turn_id=turn_id,
            timeout_seconds=timeout_seconds,
        )
    except Exception as exc:
        failure = f"{type(exc).__name__}: {exc}"
    finally:
        ledger = gateway.ledger(session_id=session_id)
        if session_id:
            created_run_ids = {
                str(item.get("resultSummary", {}).get("runId") or "")
                for item in ledger.get("items") or []
                if isinstance(item, dict)
                and item.get("operation") == "create_run"
                and isinstance(item.get("resultSummary"), dict)
            }
            deleted_run_ids = {
                str(item.get("resultSummary", {}).get("runId") or "")
                for item in ledger.get("items") or []
                if isinstance(item, dict)
                and item.get("operation") == "cleanup"
                and isinstance(item.get("resultSummary"), dict)
                and item["resultSummary"].get("deleted") is True
            }
            for run_id in sorted(created_run_ids - deleted_run_ids - {""}):
                try:
                    cleanup = sandbox.cleanup(
                        session_id,
                        run_id,
                        confirm_text=DELETE_CONFIRMATION,
                    )
                except Exception as exc:
                    harness_cleanup.append(
                        {
                            "runId": run_id,
                            "deleted": False,
                            "errorType": type(exc).__name__,
                        }
                    )
                else:
                    harness_cleanup.append(dict(cleanup))
            gateway.unbind_session(session_id)
        if service is not None:
            service.close()
        if server is not None:
            server.close()
        sandbox.close()

    ledger = gateway.ledger(session_id=session_id)
    operations = [
        str(item.get("operation") or "")
        for item in ledger.get("items") or []
        if isinstance(item, dict) and item.get("ok") is True
    ]
    event_types = [
        str(item.get("eventType") or "")
        for item in event_payloads
    ]
    tool_names = [
        str(item.get("payload", {}).get("toolName") or "")
        for item in event_payloads
        if isinstance(item.get("payload"), dict)
        and item.get("eventType") in {"tool_started", "tool_finished"}
    ]
    tool_diagnostics = _public_tool_diagnostics(event_payloads)
    search_hits = [
        hit
        for item in ledger.get("items") or []
        if isinstance(item, dict)
        and item.get("operation") == "search"
        and isinstance(item.get("resultSummary"), dict)
        for hit in item["resultSummary"].get("hits") or []
        if isinstance(hit, dict)
    ]
    evaluations = [
        item.get("resultSummary")
        for item in ledger.get("items") or []
        if isinstance(item, dict)
        and item.get("operation") == "evaluate_validation"
        and item.get("ok") is True
        and isinstance(item.get("resultSummary"), dict)
    ]
    assistant_text = _last_assistant_text(event_payloads)
    terminal_failure = _terminal_failure(event_payloads)
    effective_failure = failure or (
        str(terminal_failure.get("error") or "Agent turn failed")
        if terminal_type == "turn_failed"
        else ""
    )
    required_tools = {"tool_load", "rag_benchmark"}
    if include_skill:
        required_tools.add("skill_load")
    checks = {
        "lunaMax": _is_luna_max(ensure_before),
        "terminalCompleted": terminal_type == "turn_completed",
        "requiredToolsObserved": required_tools.issubset(set(tool_names)),
        "fullLifecycle": all(name in operations for name in REQUIRED_OPERATIONS),
        "searchFoundExpectedDocument": any(
            hit.get("externalDocumentId") == "policy-001"
            for hit in search_hits
        ),
        "answerUsedEvidence": "林岚" in assistant_text,
        "validationEvaluatedBeforeAndAfter": len(evaluations) == 2,
        "validationMetricsUsable": len(evaluations) == 2
        and all(_validation_has_retrieval_signal(item) for item in evaluations),
        "validationLabelsStayedHidden": len(evaluations) == 2
        and all(
            item.get("split") == "validation"
            and item.get("qrelsVisibleToAgent") is False
            and item.get("perCaseResultsVisible") is False
            and item.get("heldOutLabelsObserved") is False
            and bool(item.get("evaluationReceiptSha256"))
            for item in evaluations
        ),
        "agentCleanup": "cleanup" in operations,
        "harnessCleanupSucceeded": all(
            item.get("deleted") is True for item in harness_cleanup
        ),
        "noMemoryTool": "memory" not in tool_names,
    }
    completed_at_ms = int(time.time() * 1_000)
    report: dict[str, object] = {
        "schemaVersion": SCHEMA_VERSION,
        "passed": not effective_failure and all(checks.values()),
        "localArtifactsOnly": True,
        "providerDisclosure": "synthetic fixture prompt and Tool results only",
        "uploadedToLeaderboard": False,
        "startedAtMs": started_at_ms,
        "completedAtMs": completed_at_ms,
        "elapsedMs": completed_at_ms - started_at_ms,
        "model": _public_model_state(ensure_before),
        "skillEnabled": include_skill,
        "binding": binding,
        "gatewayTransport": gateway_transport,
        "prompt": {
            "accepted": prompt_receipt.get("ok") is True,
            "turnId": str(prompt_receipt.get("turnId") or ""),
        },
        "terminalEvent": terminal_type,
        "terminalFailure": terminal_failure,
        "eventTypes": event_types,
        "toolNames": tool_names,
        "toolDiagnostics": tool_diagnostics,
        "operations": operations,
        "validationEvaluations": evaluations,
        "assistantAnswerSha256": hashlib.sha256(
            assistant_text.encode("utf-8")
        ).hexdigest(),
        "assistantAnswerPreview": assistant_text[:1_000],
        "assistantAnswerContainsExpectedEvidence": "林岚" in assistant_text,
        "checks": checks,
        "gatewayLedger": ledger,
        "harnessCleanup": harness_cleanup,
        "failure": effective_failure,
    }
    report["reportSha256"] = _sha256_json(report)
    return report


def _isolated_runtime_config(
    run_root: Path,
    *,
    agent_config: Path,
) -> PiRuntimeConfig:
    source_app_support = Path(
        os.environ.get("RAG_IME_APP_SUPPORT_DIR")
        or Path.home() / "Library" / "Application Support" / "RagIme"
    ).expanduser()
    installation = snapshot_managed_pi_runtime(
        source_app_support,
        expected_pi_version=os.environ.get("RAG_IME_PI_VERSION", "").strip(),
    )
    overrides = {
        "RAG_IME_APP_SUPPORT_DIR": str(run_root / "runtime-support"),
        "RAG_IME_PI_EXECUTABLE": str(installation.executable),
        "RAG_IME_PI_EXTENSION": str(installation.extension_path),
        "RAG_IME_PI_NODE": installation.node_executable,
        "RAG_IME_PI_VERSION": installation.pi_version,
        "RAG_IME_PI_PROTOCOL_VERSION": installation.protocol_version,
        "RAG_IME_PI_TOOLS": ",".join(installation.tools),
    }
    missing = object()
    previous: dict[str, str | object] = {
        name: os.environ.get(name, missing) for name in overrides
    }
    try:
        os.environ.update(overrides)
        discovered = PiRuntimeConfig.from_environment(enabled_default=True)
    finally:
        for name, value in previous.items():
            if value is missing:
                os.environ.pop(name, None)
            else:
                os.environ[name] = str(value)
    if discovered.executable is None or discovered.extension_path is None:
        raise RuntimeError(
            "managed Pi v2 runtime is unavailable: "
            + str(discovered.installation_error or "missing executable/extension")
        )
    provider_environment = dict(discovered.provider_environment)
    spool_dir = run_root / "agent" / "tool-spool"
    spool_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    spool_dir.chmod(0o700)
    provider_environment.update(
        {
            "RAG_IME_BENCHMARK_GATEWAY_SPOOL": str(
                spool_dir
            ),
            "RAG_IME_BENCHMARK_RUNTIME_ENTRYPOINT": str(installation.executable),
            "RAG_IME_PI_SKILL_PATHS": str(
                ROOT / "integrations" / "pi" / "skills" / "rag-retrieval-optimization"
            ),
            "RAG_IME_PI_SKILL_ROUTING_CARDS": str(
                ROOT / "integrations" / "pi" / "skill-routing-cards.json"
            ),
        }
    )
    return replace(
        discovered,
        enabled=True,
        executable=ROOT / "scripts" / "rag_agent_spool_runtime_wrapper.mjs",
        agent_dir=agent_config,
        session_dir=run_root / "agent" / "sessions",
        logs_dir=run_root / "agent" / "logs",
        debug_context_dir=run_root / "agent" / "debug-context",
        provider="openai-codex",
        model="gpt-5.6-luna",
        model_configured=True,
        model_configuration_error="",
        provider_environment=provider_environment,
        protocol_version="2",
        idle_timeout_seconds=0,
        command_timeout_seconds=60.0,
        max_sessions=1,
    )


def _start_rag_benchmark_gateway(
    gateway: RagBenchmarkAgentGateway,
    *,
    spool_dir: Path,
) -> RagBenchmarkAgentGatewayServer | RagBenchmarkAgentSpoolGateway:
    """Prefer ordinary capability-token loopback; fall back when bind is denied."""

    loopback = RagBenchmarkAgentGatewayServer(gateway)
    try:
        return loopback.start()
    except PermissionError:
        loopback.close()
    spool = RagBenchmarkAgentSpoolGateway(
        gateway,
        spool_dir=spool_dir,
    )
    return spool.start()


def _copy_private_agent_config(source: Path, target: Path) -> None:
    target.mkdir(parents=True, mode=0o700)
    target.chmod(0o700)
    copied = []
    for name in ("auth.json", "models.json", "models-store.json", "settings.json"):
        source_path = source / name
        if not source_path.is_file():
            continue
        target_path = target / name
        shutil.copy2(source_path, target_path)
        target_path.chmod(0o600)
        copied.append(name)
    if "auth.json" not in copied:
        raise RuntimeError("isolated Agent config requires an existing auth.json")


def _canary_prompt(*, include_skill: bool) -> str:
    skill_step = (
        "1. 先调用 skill_load，name 必须是 rag-retrieval-optimization。\n"
        if include_skill
        else "1. 本轮禁止调用任何 Skill。\n"
    )
    return (
        "这是只含合成文本的隔离 benchmark canary，不是生产知识库。必须严格执行完整生命周期，"
        "不得调用 memory、workspace、shell 或浏览器。\n"
        + skill_step
        + "2. 调用 tool_load，name=rag_benchmark。\n"
        "3. 用 rag_benchmark.create_run 创建 run，label=agent-canary。\n"
        "4. create_base：baseAlias=policies，name=Canary Policies，初始 chunkingConfig 为 "
        '{"strategy":"fixed","size":320,"overlap":32}，retrievalConfig 为 '
        '{"mode":"lexical","topK":2,"threshold":0,"lexicalWeight":1,"denseWeight":1,"rrfK":60,"candidateMultiplier":4}。\n'
        "5. import_documents 导入两个文档："
        'policy-001 / travel.md / "# 差旅制度\\n北斗项目 差旅 审批人 林岚，报销期限 三十天。"；'
        'policy-002 / security.md / "# 安全制度\\n生产 密钥 不得写入日志或知识库。"。\n'
        "6. 调用 evaluate_validation 建立基线：evaluationSuiteId=canary-validation-v1，"
        "mode=lexical，topK=2，threshold=0；不得索取 qrels 或逐题结果。\n"
        "7. configure_base 使用 create_base 返回的 configRevision，把 expectedRevision 设为该值，"
        "并把 chunkingConfig 改为 "
        '{"strategy":"fixed","size":240,"overlap":24}，retrievalConfig 保持 lexical/topK=2。\n'
        "8. rebuild_preview，再用它返回的 previewToken 和 configRevision 调用 rebuild，confirmText=REBUILD。\n"
        "9. 使用完全相同的 evaluationSuiteId、mode、topK、threshold 再调用一次 "
        "evaluate_validation，比较两个聚合结果，不得猜测逐题标签。\n"
        "10. search 查询“北斗项目 差旅 审批人”，mode=lexical，topK=2，threshold=0。\n"
        "11. status 检查运行状态。\n"
        "12. cleanup，confirmText=DELETE_BENCHMARK_RUN。\n"
        '13. 最终只输出一行 JSON：{"answer":"北斗项目差旅审批人是林岚",'
        '"citations":["policy-001"],"cleanup":true}。'
    )


def _validation_has_retrieval_signal(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    metrics = value.get("metrics")
    if not isinstance(metrics, dict):
        return False
    recall = metrics.get("recallAtK")
    if not isinstance(recall, dict):
        return False
    return float(metrics.get("mrr") or 0.0) > 0.0 and any(
        float(item or 0.0) > 0.0 for item in recall.values()
    )


def _wait_for_terminal(
    service: AgentService,
    *,
    session_id: str,
    turn_id: str,
    timeout_seconds: float,
) -> tuple[list[dict[str, object]], str]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        events, gap = service.events.replay(session_id)
        if gap:
            raise RuntimeError("Agent event replay developed a gap")
        selected = [
            event.to_payload()
            for event in events
            if not turn_id or event.turn_id in {"", turn_id}
        ]
        terminal = next(
            (
                event.event_type
                for event in reversed(events)
                if event.turn_id == turn_id
                and event.event_type in {"turn_completed", "turn_failed"}
            ),
            "",
        )
        if terminal:
            return selected, terminal
        time.sleep(0.1)
    service.abort(session_id)
    raise TimeoutError(f"Agent turn did not settle within {timeout_seconds:.1f}s")


def _assert_luna_max(ensure: dict[str, object]) -> None:
    if not _is_luna_max(ensure):
        raise RuntimeError(
            "managed Agent runtime did not open openai-codex/gpt-5.6-luna at max"
        )


def _is_luna_max(ensure: dict[str, object]) -> bool:
    state = ensure.get("state")
    if not isinstance(state, dict):
        return False
    model = state.get("model")
    return (
        isinstance(model, dict)
        and model.get("provider") == "openai-codex"
        and model.get("id") == "gpt-5.6-luna"
        and state.get("thinkingLevel") == "max"
        and str(state.get("protocolVersion") or "2") == "2"
    )


def _public_model_state(ensure: dict[str, object]) -> dict[str, object]:
    state = ensure.get("state")
    if not isinstance(state, dict):
        return {}
    model = state.get("model")
    return {
        "provider": str(model.get("provider") or "") if isinstance(model, dict) else "",
        "id": str(model.get("id") or "") if isinstance(model, dict) else "",
        "thinkingLevel": str(state.get("thinkingLevel") or ""),
        "protocolVersion": str(state.get("protocolVersion") or "2"),
        "runtimeVersion": str(state.get("runtimeVersion") or ""),
    }


def _last_assistant_text(events: list[dict[str, object]]) -> str:
    for event in reversed(events):
        if event.get("eventType") != "message_completed":
            continue
        payload = event.get("payload")
        message = payload.get("message") if isinstance(payload, dict) else None
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        blocks = message.get("blocks") if isinstance(message, dict) else None
        if not isinstance(blocks, list):
            continue
        text = "\n".join(
            str(block.get("data", {}).get("text") or "")
            for block in blocks
            if isinstance(block, dict)
            and block.get("type") == "text"
            and isinstance(block.get("data"), dict)
        ).strip()
        if text:
            return text
    return ""


def _terminal_failure(events: list[dict[str, object]]) -> dict[str, object]:
    for event in reversed(events):
        if event.get("eventType") != "turn_failed":
            continue
        payload = event.get("payload")
        if not isinstance(payload, dict):
            return {"error": "Agent turn failed"}
        return {
            key: payload[key]
            for key in (
                "error",
                "category",
                "retryable",
                "hadToolActivity",
                "providerTransient",
            )
            if key in payload
            and isinstance(payload[key], (str, bool, int, float))
        }
    return {}


def _public_tool_diagnostics(
    events: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Keep enough bounded Tool evidence to diagnose a failed canary.

    Argument values and successful raw results are deliberately omitted.  The
    operation name, field names and a redacted error summary are sufficient to
    distinguish model/schema mistakes from Gateway or Provider failures.
    """

    diagnostics: list[dict[str, object]] = []
    for event in events:
        event_type = str(event.get("eventType") or "")
        if event_type not in {"tool_started", "tool_finished"}:
            continue
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        args = payload.get("args") if isinstance(payload.get("args"), dict) else {}
        public_result = (
            payload.get("publicResult")
            if isinstance(payload.get("publicResult"), dict)
            else {}
        )
        raw_result = (
            payload.get("result")
            if isinstance(payload.get("result"), dict)
            else {}
        )
        result = public_result or raw_result
        item: dict[str, object] = {
            "eventType": event_type,
            "toolName": _diagnostic_text(payload.get("toolName"), maximum=120),
            "toolCallIdSha256": hashlib.sha256(
                str(payload.get("toolCallId") or "").encode("utf-8")
            ).hexdigest(),
            "operation": _diagnostic_text(args.get("op"), maximum=120),
            "argumentKeys": sorted(
                str(key)[:120]
                for key in args
                if not _diagnostic_secret_key(str(key))
            )[:50],
            "isError": payload.get("isError") is True,
        }
        if event_type == "tool_finished":
            item["resultKeys"] = sorted(
                str(key)[:120]
                for key in result
                if not _diagnostic_secret_key(str(key))
            )[:50]
            for key in ("status", "code", "reason", "summary", "error"):
                value = result.get(key)
                if value is not None:
                    item[key] = _diagnostic_text(value, maximum=1_000)
            if payload.get("isError") is True and not item.get("error"):
                item["error"] = _diagnostic_error_preview(result)
        diagnostics.append(item)
    return diagnostics


def _diagnostic_error_preview(value: object) -> str:
    pieces: list[str] = []

    def visit(item: object, *, depth: int = 0) -> None:
        if depth > 4 or len(pieces) >= 12:
            return
        if isinstance(item, dict):
            for raw_key, child in list(item.items())[:50]:
                key = str(raw_key)
                if _diagnostic_secret_key(key):
                    continue
                normalized = key.lower().replace("_", "")
                if normalized in {
                    "error",
                    "message",
                    "reason",
                    "summary",
                    "text",
                    "outputpreview",
                }:
                    text = _diagnostic_text(child, maximum=1_000)
                    if text:
                        pieces.append(text)
                else:
                    visit(child, depth=depth + 1)
        elif isinstance(item, list):
            for child in item[:20]:
                visit(child, depth=depth + 1)

    visit(value)
    return " | ".join(dict.fromkeys(pieces))[:2_000]


def _diagnostic_secret_key(key: str) -> bool:
    normalized = "".join(character for character in key.lower() if character.isalnum())
    return any(
        marker in normalized
        for marker in (
            "apikey",
            "authorization",
            "cookie",
            "credential",
            "password",
            "secret",
            "token",
        )
    )


def _diagnostic_text(value: object, *, maximum: int) -> str:
    return " ".join(str(value or "").split())[:maximum]


def _write_json(path: Path, value: object) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.chmod(0o600)
    temporary.replace(path)


def _sha256_json(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
