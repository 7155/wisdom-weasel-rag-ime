#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag_ime.agent_execution_policy import WORKSPACE_SCOPE_CONFIRMATION
from rag_ime.agent_tool_ids import CONTROL_TOOL_IDS
from rag_ime.debug_server import DebugImeService, DebugServerConfig


TOOL_CALLS: dict[str, dict[str, object]] = {
    "overview": {"op": "status"},
    "input": {"op": "get_settings"},
    "voice": {"op": "status"},
    "planning": {"op": "dashboard"},
    "agent_schedule": {"op": "list"},
    "memory": {"op": "catalog"},
    "agent_role_book": {"op": "get"},
    "knowledge": {"op": "list_bases"},
    "models": {"op": "status"},
    "runtime": {"op": "health"},
    "configuration": {"op": "history"},
    "agents": {"op": "catalog"},
    "browser": {"op": "status"},
    "todo": {"op": "view"},
    "agent_goal": {"op": "list"},
    "plugins": {"op": "list"},
    "work_documents": {"op": "list", "limit": 1},
    "desktop_semantic": {"op": "status"},
    "workspace_list": {"op": "list", "path": "."},
    "workspace_lsp": {"op": "status"},
    "workspace_read": {"op": "read", "path": "sample.txt"},
    "workspace_search": {"op": "search", "path": ".", "query": "hello matrix"},
    "workspace_patch": {
        "op": "apply",
        "path": "sample.txt",
        "oldText": "hello",
        "newText": "patched",
    },
    "workspace_edit": {
        "op": "apply",
        "path": "sample.txt",
        "resourceRevision": "",
        "edits": [{"oldText": "patched", "newText": "edited"}],
    },
    "workspace_write": {
        "op": "apply",
        "path": "created.txt",
        "resourceRevision": "missing",
        "content": "created by Agent Tool matrix\n",
    },
    "workspace_job": {"op": "list"},
    "workspace_shell": {
        "op": "run",
        "command": "python3 -c \"print('agent-tool-matrix-shell-ok')\"",
        "cwd": ".",
        "timeoutSeconds": 10,
    },
}

EXPECTED_TOOL_IDS = frozenset(CONTROL_TOOL_IDS)
PUBLIC_CODING_TOOL_IDS = ("read", "edit", "write", "bash")
LEGACY_PUBLIC_CODING_TOOL_IDS = frozenset(
    {
        "read_file",
        "edit_file",
        "apply_patch",
        "write_file",
        "shell",
    }
)


def run_matrix(*, keep_workspace: bool = False) -> dict[str, object]:
    temporary = tempfile.TemporaryDirectory(prefix="rag-ime-agent-tool-matrix-")
    workspace = Path(temporary.name).resolve()
    (workspace / "sample.txt").write_text("hello matrix\n", encoding="utf-8")
    previous_environment = {
        key: os.environ.get(key)
        for key in (
            "RAG_IME_PI_ENABLED",
            "RAG_IME_AGENT_GATEWAY_ENABLED",
            "RAG_IME_ROOM_KERNEL_MODE",
        )
    }
    os.environ.update(
        {
            "RAG_IME_PI_ENABLED": "1",
            "RAG_IME_AGENT_GATEWAY_ENABLED": "1",
            # This isolated matrix exercises the Tool gateway only and does
            # not bind a typed Pi Room RPC transport.
            "RAG_IME_ROOM_KERNEL_MODE": "off",
        }
    )
    service = DebugImeService(
        DebugServerConfig(
            db_path=workspace / "matrix.sqlite",
            seed_if_empty=True,
            server_name="agent gateway",
        )
    )
    started = time.perf_counter()
    rows: list[dict[str, object]] = []
    try:
        created = service.agent.create_session(
            {
                "title": "Agent Tool execution matrix",
                "mode": "coordinator",
                "roleId": "companion-present-v1",
                "roleVersion": "1",
                "toolProfileVersion": "control-center-v1",
                "executionMode": "workspace_managed",
                "workspaceScopeConfirmation": WORKSPACE_SCOPE_CONFIRMATION,
                "workspaceRoots": [str(workspace)],
            }
        )
        session = dict(created["session"])
        session_id = str(session["id"])
        todo_task = "在隔离工作区验证读、写与命令工具"
        service.agent.sessions.mutate_agent_todo(
            session_id,
            {
                "op": "init",
                "list": [
                    {
                        "phase": "验证",
                        "items": [todo_task],
                    }
                ],
            },
            actor="agent-tool-matrix",
        )
        service.agent.sessions.mutate_agent_todo(
            session_id,
            {"op": "start", "task": todo_task},
            actor="agent-tool-matrix",
        )

        public_catalog = service.agent_tools.manifests(session_id=session_id)
        public_tool_ids = [
            str(item["id"])
            for item in public_catalog["items"]
            if item.get("kind") == "tool"
        ]
        public_coding_counts = {
            tool_id: public_tool_ids.count(tool_id)
            for tool_id in PUBLIC_CODING_TOOL_IDS
        }
        leaked_target_ids = {
            tool_id
            for tool_id in public_tool_ids
            if tool_id.startswith("workspace_")
            or tool_id in LEGACY_PUBLIC_CODING_TOOL_IDS
        }
        if (
            any(count != 1 for count in public_coding_counts.values())
            or leaked_target_ids
        ):
            raise RuntimeError(
                "public coding Tool catalog differs from the canonical contract: "
                f"counts={public_coding_counts}, "
                f"leaked={sorted(leaked_target_ids)}"
            )

        runtime_tool_ids = {
            str(item["name"])
            for item in service.agent_tools.runtime_manifests(session)
        }
        if runtime_tool_ids != EXPECTED_TOOL_IDS:
            raise RuntimeError(
                "runtime Tool target matrix differs from the reviewed inventory: "
                f"missing={sorted(EXPECTED_TOOL_IDS - runtime_tool_ids)}, "
                f"unexpected={sorted(runtime_tool_ids - EXPECTED_TOOL_IDS)}"
            )

        for index, (tool, args) in enumerate(TOOL_CALLS.items(), start=1):
            call_started = time.perf_counter()
            try:
                call_args = dict(args)
                if tool == "workspace_edit":
                    digest = hashlib.sha256((workspace / "sample.txt").read_bytes()).hexdigest()
                    call_args["resourceRevision"] = f"sha256:{digest}"
                response = service.agent_tools.execute(
                    {
                        "schemaVersion": "rag-ime.agent-tool-call.v1",
                        "sessionId": session_id,
                        "tool": tool,
                        "toolCallId": f"agent-tool-matrix:{index}:{tool}",
                        "args": call_args,
                    }
                )
                result = response.get("result")
                rows.append(
                    {
                        "tool": tool,
                        "operation": response.get("operation"),
                        "ok": response.get("ok") is True,
                        "elapsedMs": round((time.perf_counter() - call_started) * 1000, 1),
                        "summary": (
                            str(result.get("summary") or "")[:240]
                            if isinstance(result, dict)
                            else ""
                        ),
                    }
                )
            except Exception as exc:
                rows.append(
                    {
                        "tool": tool,
                        "operation": args.get("op"),
                        "ok": False,
                        "elapsedMs": round((time.perf_counter() - call_started) * 1000, 1),
                        "errorType": type(exc).__name__,
                        "error": str(exc)[:400],
                    }
                )

        sample_path = workspace / "sample.txt"
        created_path = workspace / "created.txt"
        file_checks = {
            "editChainApplied": sample_path.is_file()
            and sample_path.read_text(encoding="utf-8") == "edited matrix\n",
            "writeApplied": created_path.is_file()
            and created_path.read_text(encoding="utf-8")
            == "created by Agent Tool matrix\n",
        }
        passed = all(row["ok"] is True for row in rows) and all(file_checks.values())
        report: dict[str, object] = {
            "schemaVersion": "rag-ime.agent-tool-execution-matrix.v1",
            "ok": passed,
            "toolCount": len(rows),
            "expectedToolCount": len(EXPECTED_TOOL_IDS),
            "publicCodingToolCounts": public_coding_counts,
            "runtimeTargetCount": len(runtime_tool_ids),
            "elapsedMs": round((time.perf_counter() - started) * 1000, 1),
            "workspace": str(workspace) if keep_workspace else "<temporary>",
            "fileChecks": file_checks,
            "items": rows,
        }
        return report
    finally:
        service.close()
        for key, value in previous_environment.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        if keep_workspace:
            # TemporaryDirectory cleanup is intentionally detached only for a
            # local debugging run requested with --keep-workspace.
            temporary._finalizer.detach()  # type: ignore[attr-defined]
        else:
            temporary.cleanup()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Execute every enabled Agent product Tool against an isolated real service/workspace."
    )
    parser.add_argument("--output", default="")
    parser.add_argument("--keep-workspace", action="store_true")
    args = parser.parse_args(argv)
    report = run_matrix(keep_workspace=args.keep_workspace)
    encoded = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        output = Path(args.output).expanduser()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    return 0 if report["ok"] is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
