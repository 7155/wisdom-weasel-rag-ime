#!/usr/bin/env python3
"""Build one self-contained review file from current authoritative Room sources."""

from __future__ import annotations

import hashlib
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs/agent/room-external-model-review-bundle-20260807.md"

CURRENT_AUTHORITY_SLICES = [
    (
        "docs/agent/room-facilitated-workflow-requirements.md",
        [
            (None, "### Current follow-up evidence"),
            ("## Latest user corrections (verbatim)", "## Implementation and acceptance ledger"),
            ("## Required native foreground acceptance", "## 2026-08-07 execution-frame and alignment amendment"),
            ("## 2026-08-07 execution-frame and alignment amendment", "### Phase 0 — preserve evidence and close the current legacy conflict"),
            ("### Phase 1 — one frontend screen model", None),
        ],
    ),
    (
        "docs/agent/room-production-acceptance-handoff.md",
        [("## 7. Fresh GUI acceptance journey", "## 8. Deferred work after Room acceptance")],
    ),
]

SKILLS = [
    "integrations/pi/skills/alignment-and-decision/SKILL.md",
    "integrations/pi/skills/implementation-planning/SKILL.md",
    "integrations/pi/skills/implementation-execution/SKILL.md",
    "integrations/pi/skills/implementation-execution/references/execution-continuity-contract.md",
    "integrations/pi/skills/quality-gate/SKILL.md",
    "integrations/pi/skills/independent-review/SKILL.md",
    "integrations/pi/skills/review-feedback-resolution/SKILL.md",
    "integrations/pi/skills/structured-handoff/SKILL.md",
]

CURRENT_SOURCES = [
    "rag_ime/contracts/json/room-plan-revision.v1.json",
    "rag_ime/contracts/json/room-screen-state.v1.json",
    "rag_ime/contracts/json/room-event-envelope.v2.json",
    "rag_ime/contracts/json/room-dispatch-envelope.v2.json",
    "rag_ime/contracts/json/room-kernel-receipt.v1.json",
    "rag_ime/contracts/json/room-task.v3.json",
    "rag_ime/db/migrations/0147_room_application_unit_of_work.sql",
    "rag_ime/db/migrations/0148_room_plan_revisions.sql",
    "rag_ime/db/migrations/0149_room_interventions_and_document_deltas.sql",
    "rag_ime/db/migrations/0150_room_application_outbox_lease_tokens.sql",
    "rag_ime/room_application/__init__.py",
    "rag_ime/room_application/outbox.py",
    "rag_ime/room_application/plans.py",
    "rag_ime/room_application/repositories.py",
    "rag_ime/room_application/unit_of_work.py",
    "rag_ime/room_domain/__init__.py",
    "rag_ime/room_domain/completion.py",
    "rag_ime/room_domain/events.py",
    "rag_ime/room_domain/model.py",
    "rag_ime/room_domain/review.py",
    "rag_ime/room_domain/scheduling.py",
    "rag_ime/room_domain/settlement.py",
    "rag_ime/room_domain/waiting.py",
    "rag_ime/agent_room_application.py",
    "rag_ime/agent_room_capabilities.py",
    "rag_ime/agent_room_kernel.py",
    "rag_ime/agent_room_kernel_application.py",
    "rag_ime/agent_room_kernel_contracts.py",
    "rag_ime/agent_room_kernel_projection.py",
    "rag_ime/agent_room_requirements.py",
    "rag_ime/agent_room_settlement.py",
    "rag_ime/agent_service.py",
    "rag_ime/work_documents.py",
    "rag_ime/pi_runtime.py",
    "rag_ime/pi_runtime_v2.py",
    "rag_ime/managed_pi_runtime.py",
    "integrations/pi/room-runtime-host-contract.json",
    "integrations/pi/room-runtime-host.ts",
    "scripts/build_managed_pi_runtime_v2.py",
    "scripts/smoke_room_v2_staged_runtime.py",
    "scripts/install_managed_pi_runtime.py",
    "scripts/install_agent_gateway_launch_agent.sh",
    "scripts/install_product_stack.sh",
    "control-center-web/src/contracts/generated.ts",
    "control-center-web/src/contracts/generated/room-plan-revision.v1.ts",
    "control-center-web/src/contracts/generated/room-screen-state.v1.ts",
    "control-center-web/src/contracts/generated/room-event-envelope.v2.ts",
    "control-center-web/src/contracts/generated/room-dispatch-envelope.v2.ts",
    "control-center-web/src/contracts/generated/room-kernel-receipt.v1.ts",
    "control-center-web/src/contracts/generated/room-task.v3.ts",
    "control-center-web/src/contracts/room-kernel-reducer.ts",
    "control-center-web/src/features/rooms/model/room-screen-model.ts",
    "control-center-web/src/features/rooms/room-types.ts",
    "control-center-web/src/features/rooms/room-copy.ts",
    "control-center-web/src/features/rooms/room-presentation.tsx",
    "control-center-web/src/features/rooms/room-question.ts",
    "control-center-web/src/features/rooms/rooms.css",
    "control-center-web/src/features/rooms/RoomStatusPanel.tsx",
    "control-center-web/src/features/rooms/composer/RoomComposer.tsx",
    "control-center-web/src/features/rooms/index.tsx",
    "control-center-web/src/features/rooms/state/live-store.ts",
    "control-center-web/src/features/rooms/runtime/accepted-room-timeline.ts",
    "control-center-web/src/features/rooms/runtime/room-execution-lanes.ts",
    "control-center-web/src/features/rooms/runtime/use-room-live-session.ts",
    "control-center-web/src/features/rooms/timeline/RoomStartActionGate.tsx",
    "control-center-web/src/features/rooms/timeline/RoomTurn.tsx",
    "control-center-web/src/features/rooms/timeline/room-tool-presentation.ts",
    "control-center-web/src/features/rooms/kernel/RoomKernelControlPlane.tsx",
    "control-center-web/src/features/rooms/kernel/RoomKernelLivePanel.tsx",
    "control-center-web/src/features/rooms/kernel/RoomTaskAuthorityDetails.tsx",
    "control-center-web/src/features/rooms/kernel/RoomTaskFlowGraph.tsx",
    "control-center-web/src/features/rooms/kernel/room-kernel-command-transport.ts",
    "control-center-web/src/features/rooms/kernel/room-kernel-control-gate.ts",
    "control-center-web/src/features/rooms/kernel/room-kernel-control-plane.css",
    "control-center-web/src/features/rooms/requirements/RoomRequirementsControlPlane.tsx",
    "control-center-web/src/features/rooms/requirements/room-requirements-read-model.ts",
    "control-center-web/src/features/rooms/requirements/room-requirements-control-plane.css",
]

CURRENT_TESTS = [
    "tests/test_agent_room_execution_plan.py",
    "tests/test_agent_room_domain.py",
    "tests/test_room_application_uow.py",
    "tests/test_room_application_outbox_lease_fencing.py",
    "tests/test_agent_room_kernel.py",
    "tests/test_agent_room_kernel_projection.py",
    "tests/test_agent_room_kernel_service.py",
    "tests/test_agent_room_settlement.py",
    "tests/test_agent_room_skills.py",
    "tests/test_pi_runtime_v2.py",
    "tests/test_build_managed_pi_runtime_v2.py",
    "tests/test_managed_pi_runtime.py",
    "tests/test_room_v2_safety_exit_audit.py",
    "tests/test_control_center_cutover.py",
    "control-center-web/src/contracts/room-kernel-reducer.test.ts",
    "control-center-web/src/features/rooms/model/room-screen-model.test.ts",
    "control-center-web/src/features/rooms/composer/RoomComposer.test.tsx",
    "control-center-web/src/features/rooms/state/live-store.test.ts",
    "control-center-web/src/features/rooms/runtime/accepted-room-timeline.test.ts",
    "control-center-web/src/features/rooms/runtime/room-execution-lanes.test.ts",
    "control-center-web/src/features/rooms/runtime/use-room-live-session.test.tsx",
    "control-center-web/src/features/rooms/timeline/RoomStartActionGate.test.tsx",
    "control-center-web/src/features/rooms/timeline/RoomTurn.activity.test.tsx",
    "control-center-web/src/features/rooms/timeline/RoomTurn.chronology.test.tsx",
    "control-center-web/src/features/rooms/timeline/room-tool-presentation.test.ts",
    "control-center-web/src/features/rooms/kernel/RoomKernelControlPlane.test.tsx",
    "control-center-web/src/features/rooms/kernel/RoomKernelLivePanel.test.tsx",
    "control-center-web/src/features/rooms/kernel/RoomTaskAuthorityDetails.test.tsx",
    "control-center-web/src/features/rooms/kernel/RoomTaskFlowGraph.test.tsx",
    "control-center-web/src/features/rooms/kernel/room-kernel-command-transport.test.ts",
    "control-center-web/src/features/rooms/kernel/room-kernel-control-gate.test.ts",
    "control-center-web/src/features/rooms/kernel/room-task-authority.test.ts",
    "control-center-web/src/features/rooms/requirements/RoomRequirementsControlPlane.test.tsx",
    "control-center-web/src/features/rooms/rooms-feature.test.tsx",
]


def git_value(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
    ).strip()


def language(path: Path) -> str:
    return {
        ".json": "json",
        ".md": "markdown",
        ".py": "python",
        ".sql": "sql",
        ".ts": "typescript",
        ".tsx": "tsx",
    }.get(path.suffix, "text")


def source_block(relative: str) -> tuple[str, str]:
    path = ROOT / relative
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    text = data.decode("utf-8")
    fence = "````"
    block = "\n".join(
        [
            f"### `{relative}`",
            "",
            f"- bytes: `{len(data)}`",
            f"- SHA-256: `{digest}`",
            "- inclusion: complete current file; no Git diff or deleted lines",
            "",
            f"{fence}{language(path)}",
            text.rstrip("\n"),
            fence,
            "",
        ]
    )
    return block, f"- `{relative}` `{len(data)}` bytes `{digest}`"


def current_authority_block(
    relative: str, ranges: list[tuple[str | None, str | None]]
) -> tuple[str, str]:
    path = ROOT / relative
    raw = path.read_bytes()
    source_digest = hashlib.sha256(raw).hexdigest()
    source = raw.decode("utf-8")
    fragments: list[str] = []
    labels: list[str] = []
    for start, end in ranges:
        start_at = 0 if start is None else source.index(start)
        end_at = len(source) if end is None else source.index(end, start_at)
        fragments.append(source[start_at:end_at].strip())
        labels.append(f"{start or 'BOF'} -> {end or 'EOF'}")
    current = "\n\n".join(fragments).encode("utf-8")
    digest = hashlib.sha256(current).hexdigest()
    label_text = "; ".join(labels)
    fence = "````"
    block = "\n".join(
        [
            f"### `{relative}` current authority sections",
            "",
            f"- source bytes: `{len(raw)}`",
            f"- source SHA-256: `{source_digest}`",
            f"- included bytes: `{len(current)}`",
            f"- included SHA-256: `{digest}`",
            f"- sections: `{label_text}`",
            "- inclusion: current vision, current migration contract and fresh GUI gate only; historical baselines and superseded implementation ledgers are deliberately excluded",
            "",
            f"{fence}markdown",
            current.decode("utf-8"),
            fence,
            "",
        ]
    )
    return block, f"- `{relative}` current sections `{len(current)}` bytes `{digest}`"


def main() -> int:
    groups = [
        ("当前渐进加载 Workflow Skills", SKILLS),
        ("当前 Room 与 Pi 接入源码", CURRENT_SOURCES),
        ("当前契约与回归测试", CURRENT_TESTS),
    ]
    listed = [item for _title, items in groups for item in items]
    listed.extend(relative for relative, _ranges in CURRENT_AUTHORITY_SLICES)
    duplicate = sorted({item for item in listed if listed.count(item) > 1})
    if duplicate:
        raise SystemExit(f"duplicate bundle paths: {duplicate}")
    missing = [item for item in listed if not (ROOT / item).is_file()]
    if missing:
        raise SystemExit(f"missing bundle paths: {missing}")

    generated = datetime.now(timezone.utc).isoformat(timespec="seconds")
    head = git_value("rev-parse", "HEAD")
    branch = git_value("branch", "--show-current")
    body = [
        "# Room 当前实现与完整愿景单文件审查包",
        "",
        f"> Generated: `{generated}`  ",
        f"> Branch: `{branch}`  ",
        f"> Parent Git HEAD (provenance only, not the snapshot): `{head}`  ",
        "> Snapshot rule: every embedded file is read from the current worktree at generation time.  ",
        "> Scope rule: this bundle contains only the current authoritative vision, current Skills, current Room/Pi implementation, and current tests. It deliberately excludes Git diffs, deleted lines, old installation baselines, superseded state machines, screenshots, runtime data, caches, and unrelated dirty files.",
        "",
        "请外部模型按权威愿景逐项审查当前成果：代码是否只有一个业务真相、是否真正纵向并行、是否可恢复且可审计、Session 是否原位迁移、UI 是否只投影后端状态、以及哪些仍有真实消费者的兼容代码应在后续迁移中删除。不要审查已删除实现，不要把历史安装基线当成当前源码，也不要把测试通过推断成真实 GUI 已通过。",
        "",
        "## 1. 当前权威愿景、流程与验收边界",
        "",
    ]
    manifest: list[str] = []
    for relative, ranges in CURRENT_AUTHORITY_SLICES:
        block, record = current_authority_block(relative, ranges)
        body.append(block)
        manifest.append(record)
    for index, (title, paths) in enumerate(groups, start=2):
        body.extend([f"## {index}. {title}", ""])
        for relative in paths:
            block, record = source_block(relative)
            body.append(block)
            manifest.append(record)
    body.extend(
        [
            f"## {len(groups) + 2}. 文件清单与完整性",
            "",
            *manifest,
            "",
            "本包不嵌入自身哈希；分享时请对生成后的单文件另算 SHA-256。",
            "",
        ]
    )
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text("\n".join(body), encoding="utf-8")
    print(OUTPUT)
    print(f"bytes={OUTPUT.stat().st_size}")
    print(f"sha256={hashlib.sha256(OUTPUT.read_bytes()).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
