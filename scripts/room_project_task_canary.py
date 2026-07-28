#!/usr/bin/env python3
"""Run one complete managed Room task in an isolated real workspace."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
import time
from pathlib import Path
from typing import Any

from room_context_epoch_canary import (
    JsonRequester,
    accepted_root_id,
    cancel_root,
    debug_evidence,
    encoded,
    latest_transition,
    progressive_discovery_check,
    request_json,
    tool_receipt_evidence,
    transcript_evidence,
)


PROJECT_MARKER = "PROJECT-TASK-CANARY"
RESILIENCE_MARKER = "PROJECT-TOOL-RECOVERY-CANARY"
PUBLIC_MARKER = "PROJECT-CANARY-OK"
PROJECT_MEMORY_TEXT = (
    "代码任务先读取现有测试，只做满足验收的最小改动，"
    "运行真实测试后再提交交付。"
)
MISSING_READ_PATH = "missing_requirements.md"
TEST_COMMAND = "/usr/bin/python3 -m unittest -v"
PATCH_OLD_TEXT = '    raise NotImplementedError("ROOM_PROJECT_TASK")'
PATCH_NEW_TEXT = (
    "    if not values:\n"
    "        return []\n"
    "    minimum = min(values)\n"
    "    return [value - minimum for value in values]"
)
CALCULATOR_BEFORE = f'''"""Tiny project used by the managed Room vertical canary."""


def normalize_scores(values: list[int]) -> list[int]:
    """Shift every score so the minimum value becomes zero."""
{PATCH_OLD_TEXT}
'''
TEST_SOURCE = '''import unittest

from calculator import normalize_scores


class NormalizeScoresTest(unittest.TestCase):
    def test_positive_values(self) -> None:
        self.assertEqual(normalize_scores([5, 7, 6]), [0, 2, 1])

    def test_negative_values(self) -> None:
        self.assertEqual(normalize_scores([-2, 1]), [0, 3])

    def test_empty_values(self) -> None:
        self.assertEqual(normalize_scores([]), [])


if __name__ == "__main__":
    unittest.main()
'''
README_SOURCE = f'''# Room project task canary

Implement `normalize_scores` in `calculator.py` without changing the tests.
The placeholder marker is `{PROJECT_MARKER}` and the required verification is:

```text
{TEST_COMMAND}
```
'''
_EXPECTED_TOOL_COUNTS = {
    "workspace_list": 1,
    "workspace_search": 2,
    "workspace_read": 2,
    "workspace_edit": 1,
    "workspace_shell": 1,
    "room_post": 1,
}


def _approved_normalize_scores_body(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        module = ast.parse(f"def _candidate(values):\n{value}\n")
    except SyntaxError:
        return False
    function = module.body[0] if len(module.body) == 1 else None
    if not isinstance(function, ast.FunctionDef):
        return False
    if len(function.body) == 1:
        result = function.body[0]
        expression = result.value if isinstance(result, ast.Return) else None
        return _approved_inline_normalize_expression(expression)
    if len(function.body) != 3:
        return False
    guard, assignment, result = function.body
    if not (
        isinstance(guard, ast.If)
        and isinstance(guard.test, ast.UnaryOp)
        and isinstance(guard.test.op, ast.Not)
        and isinstance(guard.test.operand, ast.Name)
        and guard.test.operand.id == "values"
        and len(guard.body) == 1
        and isinstance(guard.body[0], ast.Return)
        and isinstance(guard.body[0].value, ast.List)
        and not guard.body[0].value.elts
        and not guard.orelse
    ):
        return False
    if not (
        isinstance(assignment, ast.Assign)
        and len(assignment.targets) == 1
        and isinstance(assignment.targets[0], ast.Name)
        and assignment.targets[0].id != "values"
        and isinstance(assignment.value, ast.Call)
        and isinstance(assignment.value.func, ast.Name)
        and assignment.value.func.id == "min"
        and len(assignment.value.args) == 1
        and isinstance(assignment.value.args[0], ast.Name)
        and assignment.value.args[0].id == "values"
        and not assignment.value.keywords
    ):
        return False
    minimum_name = assignment.targets[0].id
    expression = result.value if isinstance(result, ast.Return) else None
    if not isinstance(expression, ast.ListComp) or len(expression.generators) != 1:
        return False
    generator = expression.generators[0]
    if not (
        isinstance(generator.target, ast.Name)
        and isinstance(generator.iter, ast.Name)
        and generator.iter.id == "values"
        and not generator.ifs
        and generator.is_async == 0
        and isinstance(expression.elt, ast.BinOp)
        and isinstance(expression.elt.op, ast.Sub)
        and isinstance(expression.elt.left, ast.Name)
        and expression.elt.left.id == generator.target.id
        and isinstance(expression.elt.right, ast.Name)
        and expression.elt.right.id == minimum_name
    ):
        return False
    return True


def _approved_inline_normalize_expression(value: ast.expr | None) -> bool:
    if not (
        isinstance(value, ast.IfExp)
        and isinstance(value.test, ast.Name)
        and value.test.id == "values"
        and isinstance(value.orelse, ast.List)
        and not value.orelse.elts
        and isinstance(value.body, ast.ListComp)
        and len(value.body.generators) == 1
    ):
        return False
    generator = value.body.generators[0]
    right = value.body.elt.right if isinstance(value.body.elt, ast.BinOp) else None
    return bool(
        isinstance(generator.target, ast.Name)
        and isinstance(generator.iter, ast.Name)
        and generator.iter.id == "values"
        and not generator.ifs
        and generator.is_async == 0
        and isinstance(value.body.elt, ast.BinOp)
        and isinstance(value.body.elt.op, ast.Sub)
        and isinstance(value.body.elt.left, ast.Name)
        and value.body.elt.left.id == generator.target.id
        and isinstance(right, ast.Call)
        and isinstance(right.func, ast.Name)
        and right.func.id == "min"
        and len(right.args) == 1
        and isinstance(right.args[0], ast.Name)
        and right.args[0].id == "values"
        and not right.keywords
    )


def _approved_project_source(value: str) -> bool:
    prefix, marker, suffix = CALCULATOR_BEFORE.partition(PATCH_OLD_TEXT)
    if not marker or not value.startswith(prefix) or not value.endswith(suffix):
        return False
    end = len(value) - len(suffix) if suffix else len(value)
    return _approved_normalize_scores_body(value[len(prefix) : end])


def seed_project_workspace(workspace: Path) -> dict[str, Any]:
    root = workspace.expanduser().resolve(strict=False)
    root.mkdir(parents=True, exist_ok=True)
    if any(root.iterdir()):
        raise RuntimeError(f"Room project canary workspace must be empty: {root}")
    files = {
        "README.md": README_SOURCE,
        "calculator.py": CALCULATOR_BEFORE,
        "test_calculator.py": TEST_SOURCE,
    }
    for relative, content in files.items():
        (root / relative).write_text(content, encoding="utf-8")
    return {
        "path": str(root),
        "files": {
            relative: {
                "bytes": len(content.encode("utf-8")),
                "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            }
            for relative, content in files.items()
        },
    }


def _approval_action(approval: dict[str, Any]) -> dict[str, Any]:
    preview = approval.get("preview")
    if not isinstance(preview, dict):
        raise RuntimeError("Room project approval has no structured preview")
    action = preview.get("actionPayload")
    base_state = preview.get("baseState")
    if not isinstance(action, dict) or not isinstance(base_state, dict):
        raise RuntimeError("Room project approval is not hash-bound to an action")
    invocation_id = str(base_state.get("roomInvocationReceiptId") or "")
    if not invocation_id:
        raise RuntimeError("Room project approval is not bound to its Room invocation")
    return {
        "toolId": str(approval.get("toolId") or ""),
        "action": action,
        "invocationReceiptId": invocation_id,
    }


def validate_project_approval(
    approval: dict[str, Any],
    *,
    session_id: str,
    workspace: Path,
    allow_edit: bool = True,
) -> dict[str, Any]:
    if approval.get("state") != "pending":
        raise RuntimeError("Room project approval is no longer pending")
    if str(approval.get("sessionId") or "") != session_id:
        raise RuntimeError("Room project approval belongs to another Session")
    payload_sha256 = str(approval.get("payloadSha256") or "")
    if len(payload_sha256) != 64:
        raise RuntimeError("Room project approval payload hash is invalid")
    resolved_workspace = workspace.resolve(strict=True)
    parsed = _approval_action(approval)
    action = parsed["action"]
    tool_id = parsed["toolId"]
    if tool_id == "workspace_edit":
        if not allow_edit:
            raise RuntimeError(
                "Room project reviewer or closer attempted a forbidden edit"
            )
        if set(action) != {"path", "edits"}:
            raise RuntimeError(
                "Room project edit is outside the approved implementation shape"
            )
        target = Path(str(action.get("path") or "")).resolve(strict=True)
        if target != resolved_workspace / "calculator.py":
            raise RuntimeError("Room project attempted to edit an unexpected file")
        edits = action.get("edits")
        current_source = target.read_text(encoding="utf-8")
        shape_valid = isinstance(edits, list) and len(edits) == 1
        candidate_source = ""
        if shape_valid:
            edit = edits[0]
            shape_valid = (
                isinstance(edit, dict)
                and set(edit) == {"oldText", "newText"}
                and isinstance(edit.get("oldText"), str)
                and bool(edit["oldText"])
                and isinstance(edit.get("newText"), str)
                and current_source.count(edit["oldText"]) == 1
            )
            if shape_valid:
                candidate_source = current_source.replace(
                    edit["oldText"],
                    edit["newText"],
                    1,
                )
        if not shape_valid or not _approved_project_source(candidate_source):
            raise RuntimeError(
                "Room project edit is outside the approved implementation shape"
            )
    elif tool_id == "workspace_shell":
        cwd = Path(str(action.get("cwd") or "")).resolve(strict=True)
        timeout_seconds = action.get("timeoutSeconds")
        if (
            cwd != resolved_workspace
            or action.get("command") != TEST_COMMAND
            or action.get("allowNetwork") is not False
            or not isinstance(timeout_seconds, int)
            or isinstance(timeout_seconds, bool)
            or not 1 <= timeout_seconds <= 120
        ):
            raise RuntimeError("Room project attempted an unexpected command")
    else:
        raise RuntimeError(f"Room project requested an unexpected approval: {tool_id}")
    return {
        "approvalId": str(approval.get("approvalId") or ""),
        "toolId": tool_id,
        "payloadSha256": payload_sha256,
        "invocationReceiptId": parsed["invocationReceiptId"],
    }


def approve_pending_project_actions(
    base_url: str,
    *,
    requester: JsonRequester,
    session_id: str,
    workspace: Path,
    decided_ids: set[str],
    allow_expected_shell_failure: bool = False,
    allow_edit: bool = True,
) -> list[dict[str, Any]]:
    listed = requester(
        base_url,
        "GET",
        (
            "/api/agent/approvals"
            f"?sessionId={encoded(session_id)}&state=pending&limit=20"
        ),
        timeout=10,
    )
    decisions: list[dict[str, Any]] = []
    for raw in listed.get("items") or []:
        if not isinstance(raw, dict):
            continue
        approval_id = str(raw.get("approvalId") or "")
        if not approval_id or approval_id in decided_ids:
            continue
        preview = raw.get("preview")
        base_state = (
            preview.get("baseState")
            if isinstance(preview, dict)
            and isinstance(preview.get("baseState"), dict)
            else {}
        )
        if not str(base_state.get("roomInvocationReceiptId") or ""):
            # The durable approval row is created and then CAS-bound before the
            # Product Tool response reaches Pi. A concurrent list can observe
            # that short staging window; it is not actionable until bound.
            continue
        expected = validate_project_approval(
            raw,
            session_id=session_id,
            workspace=workspace,
            allow_edit=allow_edit,
        )
        registration_started = time.monotonic()
        while True:
            try:
                decided = requester(
                    base_url,
                    "POST",
                    f"/api/agent/approvals/{encoded(approval_id)}/decision",
                    {
                        "decision": "approve",
                        "payloadSha256": expected["payloadSha256"],
                    },
                    timeout=45,
                )
                break
            except RuntimeError as error:
                if (
                    "approval is no longer active in Pi" not in str(error)
                    or time.monotonic() - registration_started >= 2.0
                ):
                    raise
                # The DB preview is committed just before Pi emits approval_required.
                # Wait for that bounded handoff instead of racing the native decision.
                time.sleep(0.02)
        final = decided.get("approval")
        allowed_states = (
            {"applied", "failed"}
            if allow_expected_shell_failure and expected["toolId"] == "workspace_shell"
            else {"applied"}
        )
        if not isinstance(final, dict) or final.get("state") not in allowed_states:
            raise RuntimeError(f"Room project approval did not apply: {approval_id}")
        if decided.get("runtimeNotified") is not True:
            raise RuntimeError(f"Pi did not receive Room approval result: {approval_id}")
        if str(decided.get("runtimeWarning") or ""):
            raise RuntimeError(str(decided["runtimeWarning"]))
        receipt = final.get("receipt") if isinstance(final.get("receipt"), dict) else {}
        decided_ids.add(approval_id)
        decisions.append(
            {
                **expected,
                "state": str(final.get("state") or ""),
                "runtimeNotified": True,
                "mutationApplied": receipt.get("mutationApplied") is True,
                "exitCode": receipt.get("exitCode"),
                "timedOut": receipt.get("timedOut") is True,
                "roomExecutionStatus": str(
                    (
                        receipt.get("roomExecutionReceipt")
                        if isinstance(receipt.get("roomExecutionReceipt"), dict)
                        else {}
                    ).get("status")
                    or ""
                ),
                "runtimeRegistrationWaitMs": max(
                    0,
                    int((time.monotonic() - registration_started) * 1_000),
                ),
            }
        )
    return decisions


def wait_for_project_settlement(
    base_url: str,
    room_id: str,
    root_id: str,
    *,
    requester: JsonRequester,
    session_id: str,
    workspace: Path,
    timeout: float,
    allow_expected_shell_failure: bool = False,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    deadline = time.monotonic() + timeout
    decisions: list[dict[str, Any]] = []
    decided_ids: set[str] = set()
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        decisions.extend(
            approve_pending_project_actions(
                base_url,
                requester=requester,
                session_id=session_id,
                workspace=workspace,
                decided_ids=decided_ids,
                allow_expected_shell_failure=allow_expected_shell_failure,
            )
        )
        snapshot = requester(
            base_url,
            "GET",
            f"/api/agent/rooms/{encoded(room_id)}/kernel/snapshot",
            timeout=10,
        )
        roots = [
            item
            for item in snapshot.get("roots") or []
            if isinstance(item, dict) and item.get("rootId") == root_id
        ]
        dispatches = [
            item
            for item in snapshot.get("dispatches") or []
            if isinstance(item, dict) and item.get("rootId") == root_id
        ]
        last = {
            "rootState": roots[0].get("state") if roots else None,
            "dispatchStates": [item.get("state") for item in dispatches],
            "dispatchIds": [str(item.get("dispatchId") or "") for item in dispatches],
        }
        if dispatches and all(
            state in {"committed", "blocked", "failed", "cancelled"}
            for state in last["dispatchStates"]
        ):
            if any(state != "committed" for state in last["dispatchStates"]):
                raise RuntimeError(f"Room project did not commit: {last}")
            return last, decisions
        time.sleep(0.1)
    raise TimeoutError(f"Room project did not settle: {last}")


def _independent_project_verification(workspace: Path) -> dict[str, Any]:
    completed = subprocess.run(
        TEST_COMMAND.split(),
        cwd=workspace,
        check=False,
        capture_output=True,
        text=True,
        timeout=45,
    )
    output = f"{completed.stdout}\n{completed.stderr}".encode("utf-8")
    return {
        "exitCode": completed.returncode,
        "outputBytes": len(output),
        "outputSha256": hashlib.sha256(output).hexdigest(),
    }


def run(
    args: argparse.Namespace,
    *,
    requester: JsonRequester = request_json,
) -> dict[str, Any]:
    stamp = int(time.time() * 1000)
    workspace = args.workspace.expanduser().resolve(strict=True)
    failure_probe = bool(getattr(args, "failure_probe", False))
    participant_roles = list(args.participant_roles)
    if len(participant_roles) != 2:
        raise RuntimeError("Room project canary requires exactly two role references")
    created = requester(
        args.base_url,
        "POST",
        "/api/agent/rooms",
        {
            "title": f"Project task canary {stamp}",
            "routingPolicy": "manual_mentions",
            "workspaceRoots": [str(workspace)],
            "participants": participant_roles,
        },
    )
    room = created["room"]
    target = room["participants"][1]
    room_id = str(room["id"])
    session_id = str(target["sessionId"])
    execution_mode = str(room.get("executionMode") or "")
    managed_execution = execution_mode == "workspace_managed"
    if args.model_provider and args.model_id:
        requester(
            args.base_url,
            "POST",
            f"/api/agent/sessions/{encoded(session_id)}/model",
            {"provider": args.model_provider, "modelId": args.model_id},
        )
    if args.thinking_level:
        requester(
            args.base_url,
            "POST",
            f"/api/agent/sessions/{encoded(session_id)}/thinking",
            {"level": args.thinking_level},
        )

    marker = RESILIENCE_MARKER if failure_probe else PROJECT_MARKER
    acceptance_criteria = (
        [
            (
                f"常驻 read 先读取不存在的 {MISSING_READ_PATH} 一次并失败，"
                "不得同参数重试；随后正确读取两份项目文件"
            ),
            (
                f"修改前运行 {TEST_COMMAND} 一次并保留非零退出回执，"
                "不得把预期失败冒充通过"
            ),
            (
                "常驻 edit 只修改 calculator.py，且必须留下哈希绑定的 Room 执行回执"
                if managed_execution
                else "常驻 edit 只修改 calculator.py，且必须经过哈希绑定的原生批准"
            ),
            (
                f"修改后再次运行 {TEST_COMMAND}，无网络且退出码为 0；"
                f"公开 {PUBLIC_MARKER} 并提交全部验收条件"
            ),
        ]
        if failure_probe
        else [
            "直接调用常驻 ls、find、grep 和 read；不得为这些基础工具调用 tool_search 或 tool_load",
            (
                "常驻 edit 只修改 calculator.py，且必须留下哈希绑定的 Room 执行回执"
                if managed_execution
                else "常驻 edit 只修改 calculator.py，且必须经过哈希绑定的原生批准"
            ),
            f"常驻 bash 只运行 {TEST_COMMAND}，无网络且退出码为 0",
            f"公开 {PUBLIC_MARKER}，并用 room_commit 覆盖全部验收条件",
        ]
    )
    work = requester(
        args.base_url,
        "POST",
        f"/api/agent/rooms/{encoded(room_id)}/work-items",
        {
            "currentOwnerParticipantId": target["id"],
            "createdByParticipantId": room["participants"][0]["id"],
            "clientMessageId": f"project-canary-work-{stamp}",
            "objective": (
                f"{marker}：在隔离项目中实现 normalize_scores 并运行真实测试"
            ),
            "expectedOutput": (
                "只修改 calculator.py，通过全部 unittest，公开 PROJECT-CANARY-OK，"
                "提交全部验收条件并结束本轮"
            ),
            "acceptanceCriteria": acceptance_criteria,
            "state": "active",
        },
    )["workItem"]
    message = (
        (
            f"@{target['displayName']} 执行 {marker}。基础编程工具已常驻，"
            "不得用 tool_search 或 tool_load 查找它们。先直接用 read "
            f"只读取一次 {workspace / MISSING_READ_PATH}；这个文件不存在，收到失败回执后"
            "不要用相同参数重试。随后用 ls 查看目录、find 定位 Python 文件、grep 搜索 "
            "ROOM_PROJECT_TASK，并并行 read calculator.py 与 test_calculator.py。"
            "修改前直接用 bash 运行 "
            f"{TEST_COMMAND}，{'由 Room 工作区托管策略执行' if managed_execution else '等待原生批准'}；"
            "这次应非零退出，必须如实识别为预期失败。"
            "然后只用 edit 实现 normalize_scores，"
            f"{'保留哈希绑定的 Room 执行回执' if managed_execution else '等待原生批准'}；"
            f"最后再次用 bash 运行 {TEST_COMMAND}，"
            f"{'保留 Room 执行回执' if managed_execution else '等待原生批准'}且禁止网络。只有第二次测试"
            f"退出码为 0 后，才发布 {PUBLIC_MARKER} 和一句恢复说明，提交全部验收条件并收工。"
        )
        if failure_probe
        else (
            f"@{target['displayName']} 执行 {marker}。基础编程工具已常驻，"
            "不得用 tool_search 或 tool_load 查找它们。直接用 ls 查看目录、"
            "find 定位 Python 文件、grep 搜索 ROOM_PROJECT_TASK，再并行 read "
            "calculator.py 与 test_calculator.py；只用 edit 实现 normalize_scores，"
            f"{'保留哈希绑定的 Room 执行回执' if managed_execution else '等待原生批准'}；"
            f"然后只用 bash 运行 {TEST_COMMAND}，"
            f"{'保留 Room 执行回执' if managed_execution else '等待原生批准'}且禁止网络。测试通过后"
            f"发布 {PUBLIC_MARKER} 和一句结果，最后提交全部验收条件并收工。"
        )
    )
    message_payload = {
        "message": message,
        "clientMessageId": f"project-canary-message-{stamp}",
        "workItemId": work["id"],
    }
    accepted = requester(
        args.base_url,
        "POST",
        f"/api/agent/rooms/{encoded(room_id)}/messages",
        message_payload,
    )
    root_id = accepted_root_id(accepted)
    duplicate_root_id = root_id
    if failure_probe:
        duplicate_root_id = accepted_root_id(
            requester(
                args.base_url,
                "POST",
                f"/api/agent/rooms/{encoded(room_id)}/messages",
                message_payload,
            )
        )
    try:
        settled, approvals = wait_for_project_settlement(
            args.base_url,
            room_id,
            root_id,
            requester=requester,
            session_id=session_id,
            workspace=workspace,
            timeout=args.turn_timeout,
            allow_expected_shell_failure=failure_probe,
        )
    except BaseException:
        cancel_root(
            args.base_url,
            room_id,
            root_id,
            requester=requester,
        )
        raise

    finalized = requester(
        args.base_url,
        "POST",
        f"/api/agent/rooms/{encoded(room_id)}/kernel/finalize",
        {"rootId": root_id},
        timeout=20,
    )
    terminal_receipt = finalized.get("receipt")
    if not isinstance(terminal_receipt, dict):
        raise RuntimeError("Room project finalization returned no terminal receipt")
    terminal_snapshot = requester(
        args.base_url,
        "GET",
        f"/api/agent/rooms/{encoded(room_id)}/kernel/snapshot",
        timeout=10,
    )
    terminal_roots = [
        item
        for item in terminal_snapshot.get("roots") or []
        if isinstance(item, dict) and item.get("rootId") == root_id
    ]
    room_commit_posts = [
        item
        for item in terminal_snapshot.get("posts") or []
        if isinstance(item, dict)
        and isinstance(item.get("publicationSource"), dict)
        and item["publicationSource"].get("kind") == "room_commit"
    ]

    dispatch_ids = [str(value) for value in settled["dispatchIds"]]
    expected_tool_counts = dict(_EXPECTED_TOOL_COUNTS)
    expected_applied_counts = dict(_EXPECTED_TOOL_COUNTS)
    if failure_probe:
        expected_tool_counts.update(workspace_read=3, workspace_shell=2)
        expected_applied_counts.update(workspace_read=2, workspace_shell=1)
    tool_receipts = {
        tool_name: tool_receipt_evidence(
            args.db_path,
            session_id=session_id,
            dispatch_ids=dispatch_ids,
            tool_name=tool_name,
        )
        for tool_name in (*_EXPECTED_TOOL_COUNTS, "room_commit")
    }
    before = debug_evidence(
        args.base_url,
        session_id,
        requester=requester,
        timeout=args.turn_timeout,
    )
    independent = _independent_project_verification(workspace)
    compact_after = bool(getattr(args, "compact_after", False))
    if compact_after:
        compacted = requester(
            args.base_url,
            "POST",
            f"/api/agent/sessions/{encoded(session_id)}/compact",
            {
                "instructions": (
                    "Preserve one bounded recovery packet containing the original requirement, "
                    "current task, acceptance, blockers, handoff, and exact Skill/Tool receipts."
                )
            },
            timeout=args.turn_timeout,
        )
        after = debug_evidence(
            args.base_url,
            session_id,
            requester=requester,
            timeout=args.turn_timeout,
        )
        transition = latest_transition(args.db_path, session_id)
        compact_result = compacted.get("result") or {}
    else:
        after = before
        transition = {}
        compact_result = {}
    final_source = (workspace / "calculator.py").read_text(encoding="utf-8")
    final_transcript = None
    if args.pi_session_dir is not None:
        transcript_sha = str(after["transcript"].get("sha256") or "")
        if not transcript_sha:
            raise RuntimeError("Room project canary has no sealed Pi transcript receipt")
        final_transcript = transcript_evidence(args.pi_session_dir, transcript_sha)

    prompt = before["promptGovernance"]
    checks = {
        "roomTaskCommitted": settled["dispatchStates"]
        and all(state == "committed" for state in settled["dispatchStates"]),
        "roomRootCompleted": (
            terminal_receipt.get("status") == "applied"
            and terminal_receipt.get("receiptKind") == "terminal"
            and len(terminal_roots) == 1
            and terminal_roots[0].get("state") == "completed"
            and terminal_roots[0].get("terminalReceiptId")
            == terminal_receipt.get("receiptId")
        ),
        "uniquePublicPost": (
            len(room_commit_posts) == 1
            and PUBLIC_MARKER in str(room_commit_posts[0].get("content") or "")
        ),
        "projectImplementationApproved": _approved_project_source(final_source),
        "independentTestsPass": independent["exitCode"] == 0,
        "nativeApprovalsApplied": (
            (
                [item["toolId"] for item in approvals]
                == ["workspace_shell", "workspace_edit", "workspace_shell"]
                and [item["state"] for item in approvals]
                == ["failed", "applied", "applied"]
                and approvals[0]["mutationApplied"] is False
                and isinstance(approvals[0]["exitCode"], int)
                and approvals[0]["exitCode"] != 0
                and approvals[0]["timedOut"] is False
                and approvals[1]["mutationApplied"] is True
                and approvals[2]["exitCode"] == 0
                and all(item["runtimeNotified"] for item in approvals)
                and [item["roomExecutionStatus"] for item in approvals]
                == ["failed", "applied", "applied"]
            )
            if failure_probe
            else (
                [item["toolId"] for item in approvals]
                == ["workspace_edit", "workspace_shell"]
                and all(item["state"] == "applied" for item in approvals)
                and all(item["runtimeNotified"] for item in approvals)
                and all(
                    item["roomExecutionStatus"] == "applied"
                    for item in approvals
                )
                and approvals[0]["mutationApplied"] is True
                and approvals[1]["exitCode"] == 0
            )
        )
        or (
            managed_execution
            and not approvals
            and tool_receipts["workspace_edit"]["invocationCount"] == 1
            and tool_receipts["workspace_edit"]["appliedExecutionCount"] == 1
            and tool_receipts["workspace_shell"]["invocationCount"]
            == (2 if failure_probe else 1)
            and tool_receipts["workspace_shell"]["appliedExecutionCount"]
            == (1 if failure_probe else 1)
        ),
        "actualToolWorkloadExact": all(
            tool_receipts[name]["invocationCount"] == expected
            and tool_receipts[name]["appliedExecutionCount"]
            == expected_applied_counts[name]
            and len(tool_receipts[name]["loadReceiptIds"]) == 1
            for name, expected in expected_tool_counts.items()
            if name != "room_post"
        )
        # room_post stages a proposal. The following room_commit atomically
        # publishes it and seals the staged invocation as applied.
        and tool_receipts["room_post"]["invocationCount"] == 1
        and tool_receipts["room_post"]["appliedExecutionCount"] == 1
        and len(tool_receipts["room_post"]["loadReceiptIds"]) == 1
        and 1 <= tool_receipts["room_commit"]["invocationCount"] <= 2
        and tool_receipts["room_commit"]["appliedExecutionCount"]
        == tool_receipts["room_commit"]["invocationCount"],
        "providerPrefixStable": before["providerPrefix"]["passed"] is True,
        "managedRoomAuthorityClear": (
            prompt["managedRoomAuthorityEveryCall"] is True
            and not prompt["conflictingWorkflowMarkers"]
            and prompt["lifecycleHookBlockCount"] == 0
            and prompt["volatileCurrentTimeCount"] == 0
        ),
        "agentMdDefaultOff": prompt["projectContextBlockCount"] == 0,
        "roomContextProjectionDeduplicated": (
            prompt["originalRequirementProjectionDeduplicatedEveryCall"] is True
            and prompt["roomContextOmissionAuditBlockCount"] == 0
            and prompt["roomFactFramingValidEveryCall"] is True
            and prompt["catalogOriginalReferenceCount"]
            >= prompt["capturedPromptCount"]
        ),
        "skillToolDiscoveryProgressive": (
            progressive_discovery_check([prompt])
        ),
        "boundedUsefulRag": (
            before["sessionMemory"]["blockCount"] > 0
            and not before["sessionMemory"]["forbiddenMetadata"]
        ),
        "settlementQueuesDrained": before["pendingContinuations"] == 0,
    }
    if failure_probe:
        checks["idempotentUserIngress"] = (
            duplicate_root_id == root_id and len(dispatch_ids) == 1
        )
        checks["failedToolsRecoveredWithoutDuplicateRetry"] = (
            [item["status"] for item in tool_receipts["workspace_read"]["items"]]
            == ["failed", "applied", "applied"]
            and [
                item["status"]
                for item in tool_receipts["workspace_shell"]["items"]
            ]
            == ["failed", "applied"]
        )
    if compact_after:
        expected_load_receipts = {
            receipt_id
            for evidence in tool_receipts.values()
            for receipt_id in evidence["loadReceiptIds"]
        }
        recovered_load_receipts = set(transition["recovery"]["toolReceiptIds"])
        checks["oneRecoveryPacketAfterCompaction"] = (
            compact_result.get("contextRefreshApplied") is True
            and after["journal"]["entryCount"] == 2
            and transition["reason"] == "compaction"
            and transition["recovery"]["providerHashes"] == after["journal"]["hashes"]
        )
        checks["recoveryFactsComplete"] = (
            int(transition["recovery"]["originalRequirements"] or 0) >= 1
            and transition["recovery"]["currentTask"] is True
            and int(transition["recovery"]["acceptance"] or 0) >= 4
            and bool(transition["recovery"]["skillReceiptId"])
            and expected_load_receipts <= recovered_load_receipts
        )
    if final_transcript is not None:
        checks["roomContextAbsentFromSessionTranscript"] = (
            final_transcript["roomEnvelopeCount"] == 0
            and final_transcript["publicCanaryPostCount"] == 0
            and final_transcript["privateTriggerCount"] == 1
        )
    return {
        "schemaVersion": "wisdom-weasel.room-project-task-canary.v1",
        "roomId": room_id,
        "sessionId": session_id,
        "rootId": root_id,
        "faultProfile": "tool-recovery" if failure_probe else "none",
        "dispatch": settled,
        "terminal": {
            "receiptId": terminal_receipt.get("receiptId"),
            "status": terminal_receipt.get("status"),
            "rootState": (
                terminal_roots[0].get("state") if terminal_roots else None
            ),
            "roomCommitPostCount": len(room_commit_posts),
            "publicMarkerPresent": any(
                PUBLIC_MARKER in str(item.get("content") or "")
                for item in room_commit_posts
            ),
        },
        "project": {
            "workspace": str(workspace),
            "executionMode": execution_mode,
            "calculatorSha256": hashlib.sha256(final_source.encode("utf-8")).hexdigest(),
            "calculatorBytes": len(final_source.encode("utf-8")),
            "independentTest": independent,
        },
        "approvals": approvals,
        "toolReceipts": tool_receipts,
        "beforeCompaction": before,
        "compaction": {
            "attempted": compact_after,
            "entryId": compact_result.get("compactionEntryId"),
            "epochBefore": compact_result.get("contextEpochBefore"),
            "epochAfter": compact_result.get("contextEpochAfter"),
            "refreshApplied": compact_result.get("contextRefreshApplied"),
        },
        "afterCompaction": after,
        "productTransition": transition,
        "transcript": final_transcript,
        "checks": checks,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:18768")
    parser.add_argument("--db-path", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--pi-session-dir", type=Path)
    parser.add_argument("--turn-timeout", type=float, default=300)
    parser.add_argument("--model-provider", default="")
    parser.add_argument("--model-id", default="")
    parser.add_argument("--thinking-level", default="")
    parser.add_argument("--failure-probe", action="store_true")
    parser.add_argument("--participant-role", action="append", default=[])
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit("Use run_room_context_epoch_in_process.py --scenario project-task")
