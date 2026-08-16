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
    "room_partner": {"op": "list"},
    "browser": {"op": "status"},
    "todo": {"op": "view"},
    "agent_goal": {"op": "list"},
    "plugins": {"op": "list"},
    "work_documents": {"op": "list", "limit": 1},
    "desktop_semantic": {"op": "status"},
    "ls": {"path": "."},
    "workspace_lsp": {"op": "status"},
    "read": {"path": "sample.txt"},
    "grep": {"path": ".", "pattern": "hello matrix", "literal": True},
    "find": {"path": ".", "pattern": "sample.txt"},
    "workspace_patch": {
        "op": "apply",
        "path": "sample.txt",
        "oldText": "hello",
        "newText": "patched",
    },
    "edit": {
        "path": "sample.txt",
        "resourceRevision": "",
        "edits": [{"oldText": "patched", "newText": "edited"}],
    },
    "write": {
        "path": "created.txt",
        "resourceRevision": "missing",
        "content": "created by Agent Tool matrix\n",
    },
    "workspace_job": {"op": "list"},
    "bash": {
        "command": "python3 -c \"print('agent-tool-matrix-shell-ok')\"",
        "cwd": ".",
        "timeout": 10,
    },
}

EXPECTED_TOOL_IDS = frozenset(TOOL_CALLS)
HIDDEN_BACKEND_ONLY_TOOL_IDS = frozenset({"work_documents", "workspace_patch"})
EXPECTED_PROVIDER_TOOL_IDS = EXPECTED_TOOL_IDS - HIDDEN_BACKEND_ONLY_TOOL_IDS


def provider_tool_names(manifests: list[object]) -> tuple[str, ...]:
    """Project the hidden PAW targets into the names actually owned by Pi."""

    names: list[str] = []
    for value in manifests:
        if not isinstance(value, dict):
            continue
        if value.get("modelVisible") is False:
            projections = value.get("runtimeProjections")
            if not isinstance(projections, list):
                continue
            names.extend(
                str(projection.get("name") or "")
                for projection in projections
                if isinstance(projection, dict)
                and str(projection.get("name") or "").strip()
            )
            continue
        name = str(value.get("name") or "").strip()
        if name:
            names.append(name)
    return tuple(names)


def run_matrix(*, keep_workspace: bool = False) -> dict[str, object]:
    temporary = tempfile.TemporaryDirectory(prefix="rag-ime-agent-tool-matrix-")
    workspace = Path(temporary.name).resolve()
    (workspace / "sample.txt").write_text("hello matrix\n", encoding="utf-8")
    previous_environment = {
        key: os.environ.get(key)
        for key in (
            "RAG_IME_PI_ENABLED",
            "RAG_IME_AGENT_GATEWAY_ENABLED",
        )
    }
    os.environ.update(
        {
            "RAG_IME_PI_ENABLED": "1",
            "RAG_IME_AGENT_GATEWAY_ENABLED": "1",
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
        created_room = service.agent.create_room(
            {
                "title": "Agent Tool execution matrix Room",
                "workspaceRoots": [str(workspace)],
                "participants": [
                    {
                        "roleId": "companion-present-v1",
                        "roleVersion": "1",
                    },
                    {
                        "roleId": "companion-firstlight-v1",
                        "roleVersion": "1",
                    },
                ],
            }
        )
        room = dict(created_room["room"])
        facilitator = dict(room["participants"][0])
        session = service.agent.sessions.get(str(facilitator["sessionId"]))
        session_id = str(session["id"])
        service.agent._begin_room_turn(
            session_id,
            "agent-tool-matrix:root",
            dispatch_id="agent-tool-matrix:dispatch",
        )
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

        runtime_tools = provider_tool_names(
            list(service.agent_tools.runtime_manifests(session))
        )
        expected_provider_order = tuple(
            name for name in TOOL_CALLS if name in EXPECTED_PROVIDER_TOOL_IDS
        )
        if runtime_tools != expected_provider_order:
            raise RuntimeError(
                "Pi runtime Tool matrix differs from the reviewed Provider surface: "
                f"missing={sorted(EXPECTED_PROVIDER_TOOL_IDS - set(runtime_tools))}, "
                f"unexpected={sorted(set(runtime_tools) - EXPECTED_PROVIDER_TOOL_IDS)}, "
                f"actualOrder={list(runtime_tools)}"
            )

        for index, (tool, args) in enumerate(TOOL_CALLS.items(), start=1):
            call_started = time.perf_counter()
            try:
                call_args = dict(args)
                if tool == "edit":
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
