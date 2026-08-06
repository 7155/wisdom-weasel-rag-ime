#!/usr/bin/env python3
"""Run one real Luna researcher child against a tiny bound RAG sandbox."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import time
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag_ime.agent_service import AgentService  # noqa: E402
from rag_ime.agent_tools import ControlToolGateway  # noqa: E402
from rag_ime.rag_benchmark_agent import (  # noqa: E402
    RagBenchmarkAgentGateway,
    RagBenchmarkAgentGatewayServer,
)
from rag_ime.rag_benchmark_sandbox import (  # noqa: E402
    DELETE_CONFIRMATION,
    RagBenchmarkSandbox,
    RagBenchmarkSandboxTool,
)
from scripts.canary_rag_benchmark_agent import (  # noqa: E402
    _copy_private_agent_config,
    _is_luna_max,
    _isolated_runtime_config,
)


SCHEMA_VERSION = "rag-ime.delegated-rag-benchmark-agent-canary.v1"


def main(argv: list[str] | None = None) -> int:
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--private-root",
        type=Path,
        default=ROOT / ".rag-ime-data" / "runs" / "delegated-rag-canary",
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
    args = parser.parse_args(argv)

    private_root = args.private_root.expanduser().resolve(strict=False)
    private_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    private_root.chmod(0o700)
    output = args.output.expanduser().resolve(strict=False)
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(prefix="run-", dir=private_root) as temporary:
        report = _run(
            Path(temporary).resolve(strict=True),
            source_agent_config=args.source_agent_config.expanduser().resolve(strict=True),
        )
    _write_json(output, report)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report.get("passed") is True else 1


def _run(run_root: Path, *, source_agent_config: Path) -> dict[str, object]:
    started_at_ms = int(time.time() * 1_000)
    agent_config = run_root / "agent" / "config"
    _copy_private_agent_config(source_agent_config, agent_config)
    runtime_config = replace(
        _isolated_runtime_config(run_root, agent_config=agent_config),
        max_sessions=4,
    )
    sandbox = RagBenchmarkSandbox(run_root / "knowledge-runs")
    gateway = RagBenchmarkAgentGateway(RagBenchmarkSandboxTool(sandbox))
    server = RagBenchmarkAgentGatewayServer(gateway)
    service: AgentService | None = None
    parent_session_id = ""
    run_id = ""
    binding: dict[str, object] = {}
    delegation: dict[str, object] = {}
    ledger: dict[str, object] = {}
    cleanup_passed = False
    failure = ""
    try:
        server.start()
        service = AgentService(
            db_path=run_root / "agent.sqlite",
            runtime_config=runtime_config,
            project="delegated-rag-benchmark-canary",
            tool_gateway_url=server.tool_gateway_url,
            tool_gateway_token=server.token,
            wake_scheduler_enabled=False,
            room_kernel_worker_enabled=False,
            background_job_execution_owner=False,
        )
        gateway.session_loader = service.sessions.get
        gateway.base_gateway = ControlToolGateway(
            sessions=service.sessions,
            management=object(),
            core=object(),
            project=service.project,
            background_jobs=service.background_jobs,
            delegation=service.delegation,
            configuration_store=service.configuration_store,
            governed_skills=service.room_skill_policy,
            work_documents=service.work_documents,
        )
        gateway.delegated_parent_loader = lambda child_session_id: (
            str(child.get("parentSessionId") or "")
            if isinstance(
                child := service.delegation.store.run_for_child_session(
                    child_session_id
                ),
                Mapping,
            )
            else None
        )
        service.bind_tool_manifest_provider(gateway.runtime_manifests)

        owner = "delegated-rag-canary"
        run = sandbox.create_run(owner, label="delegated-rag-canary")
        run_id = str(run["runId"])
        sandbox.create_base(
            owner,
            run_id,
            alias="benchmark",
            name="Delegated RAG canary",
            description="Synthetic Chinese delegation fixture",
            chunking_config={"strategy": "fixed", "size": 320, "overlap": 32},
            retrieval_config={
                "mode": "lexical",
                "topK": 2,
                "threshold": 0,
                "lexicalWeight": 1,
                "denseWeight": 1,
                "rrfK": 60,
                "candidateMultiplier": 4,
            },
        )
        sandbox.import_documents(
            owner,
            run_id,
            base_alias="benchmark",
            documents=[
                {
                    "externalId": "policy-001",
                    "name": "travel.md",
                    "text": "# 差旅制度\n北斗项目 差旅 审批人 为林岚，报销期限为三十天。",
                    "mimeType": "text/plain",
                },
                {
                    "externalId": "policy-002",
                    "name": "security.md",
                    "text": "# 安全制度\n生产密钥不得写入日志或知识库。",
                    "mimeType": "text/plain",
                },
            ],
        )

        parent = service.create_session(
            {
                "title": "Delegated RAG canary parent",
                "mode": "assistant",
                "roleId": "companion-firstlight-v1",
                "roleVersion": "1",
                "toolProfileVersion": "subagent-readonly-v1",
            }
        )["session"]
        parent_session_id = str(parent["id"])
        service.update_session(
            parent_session_id,
            {
                "mode": "assistant",
                "executionMode": "read_only",
                "toolProfileVersion": "subagent-readonly-v1",
                "projectContextEnabled": False,
                "piSkillsEnabled": False,
                "codexSkillsEnabled": False,
                "workspaceRoots": [],
            },
        )
        binding = gateway.bind_session(
            parent_session_id,
            allowed_operations=("search", "status"),
            sandbox_owner_id=owner,
            sandbox_run_id=run_id,
            allowed_base_tools=("agents",),
        )
        ensure = service.ensure_runtime({"sessionId": parent_session_id})
        if not _is_luna_max(ensure):
            raise RuntimeError("parent did not open Luna Max")
        delegation = service.delegation.delegate(
            parent_session_id,
            {
                "agent": "researcher",
                "version": "1",
                "task": (
                    "这是只读合成 Knowledge RAG canary。先 tool_load name=rag_benchmark，"
                    "再调用一次 rag_benchmark.search：op=search、baseAlias=benchmark、"
                    "evaluationCaseId=case-01、query=北斗项目 差旅 审批人、mode=lexical、"
                    "topK=2、threshold=0，不要传 runId。最后只输出"
                    '{"answer":"...","citations":["policy-001"]}。'
                ),
                "expectedOutput": "带 policy-001 引用的单行 JSON",
                "acceptanceCriteria": [
                    "必须实际调用 rag_benchmark.search",
                    "答案包含林岚并引用 policy-001",
                    "不得调用 Memory 或写入工具",
                ],
                "contextMode": "fresh",
                "wait": True,
            },
        )
        ledger = gateway.lineage_ledger(parent_session_id)
    except Exception as exc:
        failure = f"{type(exc).__name__}: {exc}"
        if service is not None and parent_session_id:
            batches = service.delegation.store.list_batches(
                parent_session_id=parent_session_id,
                limit=10,
            )
            if batches:
                delegation = {"batch": batches[0]}
            ledger = gateway.lineage_ledger(parent_session_id)
    finally:
        if parent_session_id:
            gateway.unbind_lineage(parent_session_id)
        if run_id:
            try:
                cleanup = sandbox.cleanup(
                    "delegated-rag-canary",
                    run_id,
                    confirm_text=DELETE_CONFIRMATION,
                )
            except Exception:
                cleanup_passed = False
            else:
                cleanup_passed = cleanup.get("deleted") is True
        if service is not None:
            service.close()
        server.close()
        sandbox.close()

    batch = delegation.get("batch")
    batch = dict(batch) if isinstance(batch, Mapping) else {}
    runs = [dict(item) for item in batch.get("runs") or [] if isinstance(item, Mapping)]
    searches = [
        item
        for item in ledger.get("items") or []
        if isinstance(item, Mapping)
        and item.get("operation") == "search"
        and item.get("ok") is True
    ]
    expected_hit = any(
        hit.get("externalDocumentId") == "policy-001"
        for item in searches
        if isinstance(item.get("resultSummary"), Mapping)
        for hit in item["resultSummary"].get("hits") or []
        if isinstance(hit, Mapping)
    )
    child = runs[0] if len(runs) == 1 else {}
    checks = {
        "oneChild": len(runs) == 1,
        "childCompleted": child.get("state") == "completed",
        "childUsedRag": bool(searches),
        "expectedDocumentFound": expected_hit,
        "lineageBound": int(ledger.get("childSessionCount") or 0) == 1,
        "cleanup": cleanup_passed,
        "noMemoryTool": all(
            str(item.get("tool") or "") != "memory"
            for item in ledger.get("items") or []
            if isinstance(item, Mapping)
        ),
    }
    report: dict[str, object] = {
        "schemaVersion": SCHEMA_VERSION,
        "passed": not failure and all(checks.values()),
        "localOnly": True,
        "uploaded": False,
        "startedAtMs": started_at_ms,
        "completedAtMs": int(time.time() * 1_000),
        "binding": binding,
        "checks": checks,
        "child": {
            "state": str(child.get("state") or ""),
            "templateId": str(child.get("templateId") or ""),
            "usage": dict(child.get("usage") or {}),
            "error": str(child.get("error") or "")[:500],
            "errorSha256": hashlib.sha256(
                str(child.get("error") or "").encode("utf-8")
            ).hexdigest(),
        },
        "gatewayLedger": ledger,
        "cleanupPassed": cleanup_passed,
        "failure": failure,
    }
    report["elapsedMs"] = int(report["completedAtMs"]) - started_at_ms
    report["reportSha256"] = _sha256_json(report)
    return report


def _sha256_json(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _write_json(path: Path, value: object) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.chmod(0o600)
    os.replace(temporary, path)


if __name__ == "__main__":
    raise SystemExit(main())
