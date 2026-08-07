#!/usr/bin/env python3
"""Build two self-contained, current-source review bundles for external models."""

from __future__ import annotations

import hashlib
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path


PAW_ROOT = Path(__file__).resolve().parents[1]
PI_ROOT = Path(
    os.environ.get(
        "PAW_PI_REVIEW_WORKTREE",
        "/Volumes/undo 4t/git/learnA/.worktrees/pi-room-runtime-98cfe6a3",
    )
).resolve()
PI_BASE = "98cfe6a3a0a420ac6de4f85153c55fbc8809b845"

PAW_OUTPUT = PAW_ROOT / "docs/agent/room-external-model-review-bundle-20260807.md"
PI_OUTPUT = PAW_ROOT / "docs/agent/pi-runtime-sdk-v2-external-model-review-bundle-20260807.md"


CURRENT_AUTHORITY_SLICES = [
    (
        "docs/agent/room-facilitated-workflow-requirements.md",
        [
            (None, "### Current follow-up evidence"),
            (
                "## Latest user corrections (verbatim)",
                "## Implementation and acceptance ledger",
            ),
            (
                "## Required native foreground acceptance",
                "## 2026-08-07 execution-frame and alignment amendment",
            ),
            (
                "## 2026-08-07 execution-frame and alignment amendment",
                "### Phase 0 — preserve evidence and close the current legacy conflict",
            ),
            ("### Phase 1 — one frontend screen model", None),
        ],
    ),
    (
        "docs/agent/room-production-acceptance-handoff.md",
        [
            ("## 7. Fresh GUI acceptance journey", "## 8. Deferred work after Room acceptance"),
            ("## 11. 2026-08-07 Pi Runtime SDK v2", None),
        ],
    ),
]


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=root, text=True, stderr=subprocess.DEVNULL
    ).strip()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def language(path: Path) -> str:
    return {
        ".json": "json",
        ".md": "markdown",
        ".py": "python",
        ".sql": "sql",
        ".ts": "typescript",
        ".tsx": "tsx",
        ".yaml": "yaml",
        ".yml": "yaml",
    }.get(path.suffix, "text")


def fence_for(text: str) -> str:
    longest = 0
    current = 0
    for char in text:
        if char == "`":
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return "`" * max(4, longest + 1)


def source_block(root: Path, relative: str) -> tuple[str, str]:
    path = root / relative
    data = path.read_bytes()
    content = data.decode("utf-8")
    digest = sha256(data)
    fence = fence_for(content)
    block = "\n".join(
        [
            f"### `{relative}`",
            "",
            f"- bytes: `{len(data)}`",
            f"- SHA-256: `{digest}`",
            "- inclusion: complete current file; no deleted lines or historical diff",
            "",
            f"{fence}{language(path)}",
            content.rstrip("\n"),
            fence,
            "",
        ]
    )
    return block, f"- `{relative}` `{len(data)}` bytes `{digest}`"


def authority_block(
    relative: str, ranges: list[tuple[str | None, str | None]]
) -> tuple[str, str]:
    path = PAW_ROOT / relative
    raw = path.read_bytes()
    source = raw.decode("utf-8")
    fragments: list[str] = []
    labels: list[str] = []
    for start, end in ranges:
        start_at = 0 if start is None else source.index(start)
        end_at = len(source) if end is None else source.index(end, start_at)
        fragments.append(source[start_at:end_at].strip())
        labels.append(f"{start or 'BOF'} -> {end or 'EOF'}")
    current_text = "\n\n".join(fragments)
    current = current_text.encode("utf-8")
    fence = fence_for(current_text)
    block = "\n".join(
        [
            f"### `{relative}` current authority sections",
            "",
            f"- source bytes: `{len(raw)}`",
            f"- source SHA-256: `{sha256(raw)}`",
            f"- included bytes: `{len(current)}`",
            f"- included SHA-256: `{sha256(current)}`",
            f"- sections: `{'; '.join(labels)}`",
            "- inclusion: only current vision, current architecture and current acceptance gates; superseded baselines and completed historical ledgers are excluded",
            "",
            f"{fence}markdown",
            current_text,
            fence,
            "",
        ]
    )
    return block, f"- `{relative}` current sections `{len(current)}` bytes `{sha256(current)}`"


def dedupe_existing(root: Path, paths: list[str]) -> list[str]:
    unique = sorted(dict.fromkeys(paths))
    missing = [path for path in unique if not (root / path).is_file()]
    if missing:
        raise SystemExit(f"missing bundle paths under {root}: {missing}")
    return unique


def paw_source_paths() -> list[str]:
    paths: list[str] = []
    paths.extend(str(path.relative_to(PAW_ROOT)) for path in (PAW_ROOT / "rag_ime").glob("agent_*.py"))
    paths.extend(str(path.relative_to(PAW_ROOT)) for path in (PAW_ROOT / "rag_ime/room_application").glob("*.py"))
    paths.extend(str(path.relative_to(PAW_ROOT)) for path in (PAW_ROOT / "rag_ime/room_domain").glob("*.py"))
    paths.extend(
        [
            "rag_ime/deepseek_memory_organizer.py",
            "rag_ime/knowledge_control.py",
            "rag_ime/knowledge_scope.py",
            "rag_ime/knowledge_workbench.py",
            "rag_ime/knowledge_worker_supervisor.py",
            "rag_ime/input_quality.py",
            "rag_ime/managed_pi_runtime.py",
            "rag_ime/memory_model_executor.py",
            "rag_ime/owner_memory_curation.py",
            "rag_ime/owner_memory_maintenance.py",
            "rag_ime/personal_memory_luna_evaluation.py",
            "rag_ime/pi_runtime.py",
            "rag_ime/pi_runtime_protocols.py",
            "rag_ime/pi_runtime_public.py",
            "rag_ime/pi_runtime_v2.py",
            "rag_ime/pi_runtime_values.py",
            "rag_ime/room_runtime_host_kill_gate.py",
            "rag_ime/session_memory_recall.py",
            "rag_ime/work_documents.py",
            "integrations/pi/room-runtime-host-contract.json",
            "integrations/pi/room-runtime-host.ts",
            "scripts/build_managed_pi_runtime_v2.py",
            "scripts/install_managed_pi_runtime.py",
            "scripts/prepare_managed_pi_runtime.py",
            "scripts/install_product_stack.sh",
            "scripts/curate_historical_memory_luna.py",
        ]
    )
    paths.extend(
        str(path.relative_to(PAW_ROOT))
        for path in (PAW_ROOT / "rag_ime/knowledge_library").glob("*.py")
    )
    paths.extend(
        str(path.relative_to(PAW_ROOT))
        for path in (PAW_ROOT / "rag_ime/contracts/json").glob("room-*.json")
    )
    for pattern in (
        "agent-session*.json",
        "agent-message*.json",
        "agent-runtime*.json",
        "agent-tool*.json",
        "agent-goal*.json",
        "agent-workflow*.json",
        "agent-context*.json",
        "agent-participant*.json",
    ):
        paths.extend(
            str(path.relative_to(PAW_ROOT))
            for path in (PAW_ROOT / "rag_ime/contracts/json").glob(pattern)
        )
    paths.extend(
        [
            "rag_ime/db/migrations/0068_room_kernel_core.sql",
            "rag_ime/db/migrations/0069_room_kernel_projection.sql",
            "rag_ime/db/migrations/0108_room_post_immediate_publication.sql",
            "rag_ime/db/migrations/0113_work_documents.sql",
            "rag_ime/db/migrations/0127_room_requirement_alignment.sql",
            "rag_ime/db/migrations/0134_room_dispatch_deferred_concurrency.sql",
            "rag_ime/db/migrations/0135_agent_todo_cutover.sql",
            "rag_ime/db/migrations/0141_room_workspace_ledger.sql",
            "rag_ime/db/migrations/0142_agent_todo_room_lineage.sql",
            "rag_ime/db/migrations/0147_room_application_unit_of_work.sql",
            "rag_ime/db/migrations/0148_room_plan_revisions.sql",
            "rag_ime/db/migrations/0149_room_interventions_and_document_deltas.sql",
            "rag_ime/db/migrations/0150_room_application_outbox_lease_tokens.sql",
            "rag_ime/db/migrations/0125_agent_approval_model_decisions.sql",
            "rag_ime/db/migrations/0126_agent_approval_model_context.sql",
        ]
    )
    return dedupe_existing(PAW_ROOT, paths)


def paw_skill_paths() -> list[str]:
    return dedupe_existing(
        PAW_ROOT,
        [
            str(path.relative_to(PAW_ROOT))
            for path in (PAW_ROOT / "integrations/pi/skills").rglob("*")
            if path.is_file()
        ],
    )


def paw_test_paths() -> list[str]:
    paths: list[str] = []
    for pattern in (
        # The backend source bundle contains every live ``agent_*.py`` owner.
        # Include the matching contract tests as a family so an external model
        # can audit full-auto policy, Luna adjudication, workspace hard fences,
        # lifecycle cancellation and event projection instead of seeing only
        # the broad Room/Session happy paths.
        "test_agent_*.py",
        "test_agent_room*.py",
        "test_agent_session*.py",
        "test_agent_service*.py",
        "test_pi_runtime*.py",
        "test_managed_pi_runtime*.py",
        "test_room_application*.py",
        "test_room_v2*.py",
        "test_work_documents*.py",
        "test_memory_model_executor.py",
        "test_owner_memory_curation.py",
        "test_owner_memory_maintenance.py",
        "test_personal_memory_luna_evaluation.py",
        "test_knowledge*.py",
        "test_build_managed_pi_runtime_v2.py",
        "test_control_center_cutover.py",
    ):
        paths.extend(
            str(path.relative_to(PAW_ROOT))
            for path in (PAW_ROOT / "tests").glob(pattern)
        )
    return dedupe_existing(PAW_ROOT, paths)


def build_paw_bundle() -> tuple[Path, int, str]:
    generated = datetime.now(timezone.utc).isoformat(timespec="seconds")
    head = git(PAW_ROOT, "rev-parse", "HEAD")
    branch = git(PAW_ROOT, "branch", "--show-current")
    dirty = git(PAW_ROOT, "status", "--short") or "clean"
    body = [
        "# PAW 聊天后端、Room、Session 与 Skills 当前源码审查包",
        "",
        f"> Generated: `{generated}`  ",
        f"> Branch: `{branch}`  ",
        f"> Parent Git HEAD (provenance only): `{head}`  ",
        "> Snapshot rule: every embedded file is the complete file read from this worktree at generation time; per-file SHA-256 is the authority.  ",
        "> Exclusion rule: no deleted source, no diff hunk, no build/install output, no runtime database, no screenshots, and no historical baseline is embedded. Files still imported by the current backend remain visible even if their names contain compatibility terminology, so the reviewer can identify remaining live migration debt.",
        "",
        "## 当前审查目标与完整愿景",
        "",
        "请只审查本包内的当前源码是否实现以下产品：普通聊天与 Room 共用可靠的 Pi Agent 生命周期，但 RoomTask、PlanRevision、依赖图、WorkDocument、审批、集成、独立复核和最终交付仍由 PAW 拥有。Room 先用用户语言一次问清真正影响方案的问题，合理默认值直接决定；在用户确认并点击开始行动前，不得读写项目、测试或分派伙伴。开始后，多位能力平等的伙伴按完整用户功能纵向拆分，先锁公共契约，再按依赖分波次真正并行。运行中用户可以补充、更正、改优先级或询问进度，消息必须留在同一 Root 并原位更新 RequirementCatalog 与已存在的 WorkDocument。所有状态、Todo、谁在做什么、工具、交接、恢复和复核都来自单一后端事实并以简短中文投影；前端不得重猜业务状态。每个 Dispatch 必须可恢复、幂等、可取消、可审计；只有实现、集成、真实验证及范围独立复核全部通过，才允许唯一最终交付。Session 必须原位迁移，不能丢 transcript、重复回复或在 Room 与普通 Agent 页面间错误跳转。废弃路径应在消费者迁移后渐进删除，不保留双状态机。",
        "",
        "## 当前工作树状态（仅用于诚实标注，不是源码差异）",
        "",
        "```text",
        dirty,
        "```",
        "",
        "## 1. 当前权威需求与验收边界",
        "",
    ]
    manifest: list[str] = []
    for relative, ranges in CURRENT_AUTHORITY_SLICES:
        block, record = authority_block(relative, ranges)
        body.append(block)
        manifest.append(record)
    groups = [
        ("当前渐进加载 Skills 全套", paw_skill_paths()),
        ("当前聊天、Session、Room 与 Runtime 后端", paw_source_paths()),
        ("当前后端契约回归测试", paw_test_paths()),
    ]
    for index, (title, paths) in enumerate(groups, start=2):
        body.extend([f"## {index}. {title}", ""])
        for relative in paths:
            block, record = source_block(PAW_ROOT, relative)
            body.append(block)
            manifest.append(record)
    body.extend([f"## {len(groups) + 2}. 文件清单与完整性", "", *manifest, ""])
    PAW_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    PAW_OUTPUT.write_text("\n".join(body), encoding="utf-8")
    data = PAW_OUTPUT.read_bytes()
    return PAW_OUTPUT, len(data), sha256(data)


def pi_paths() -> list[str]:
    # Compare the integration base to the complete worktree, not only HEAD, so
    # a fresh external review also sees tested fixes that have not been
    # committed yet. Per-file hashes remain the snapshot authority.
    changed = git(PI_ROOT, "diff", "--name-only", PI_BASE).splitlines()
    supporting = [
        "package.json",
        "packages/agent/package.json",
        "packages/coding-agent/package.json",
        "packages/rag-ime-runtime-host/package.json",
    ]
    return dedupe_existing(PI_ROOT, [*supporting, *changed])


def build_pi_bundle() -> tuple[Path, int, str]:
    generated = datetime.now(timezone.utc).isoformat(timespec="seconds")
    head = git(PI_ROOT, "rev-parse", "HEAD")
    branch = git(PI_ROOT, "branch", "--show-current")
    dirty = git(PI_ROOT, "status", "--short") or "clean"
    commits = git(PI_ROOT, "log", "--oneline", f"{PI_BASE}..HEAD")
    body = [
        "# Pi Runtime SDK v2 当前改后源码审查包",
        "",
        f"> Generated: `{generated}`  ",
        f"> Branch: `{branch}`  ",
        f"> Git HEAD: `{head}`  ",
        f"> Integration base (provenance only): `{PI_BASE}`  ",
        "> Snapshot rule: only complete current files are embedded. The base implementation, deleted lines, draft ZIP content and historical patch hunks are not embedded.",
        "",
        "## 当前边界与审查目标",
        "",
        "Pi 只拥有通用 Agent Runtime Plane：层级 RunScope、可靠 Continuation、精确 Agent settlement、ContextProvider 装配与 Host 级 session.await_settled。PAW 继续拥有 RoomTask、PlanRevision、依赖图、WorkDocument、Goal、Todo、Knowledge、Memory、审批、Workspace 权限、集成、独立复核和最终交付。请检查当前代码能否让普通聊天和 Room 共享同一套可靠执行、取消、续跑与终态凭据，同时不把 Room 业务状态复制进 Pi；重点检查 lease/ack 崩溃窗、generation/turn/session identity、晚到事件、suspended 与 completed 区分、transcript 持久化、ContextProvider freshness/provenance/budget，以及旧 Session 的原位兼容迁移。",
        "",
        "## 当前工作树状态",
        "",
        "```text",
        dirty,
        "```",
        "",
        "## 从产品集成基线到当前 HEAD 的提交",
        "",
        "```text",
        commits,
        "```",
        "",
        "## 当前改后源码、契约与测试",
        "",
    ]
    manifest: list[str] = []
    for relative in pi_paths():
        block, record = source_block(PI_ROOT, relative)
        body.append(block)
        manifest.append(record)
    body.extend(["## 文件清单与完整性", "", *manifest, ""])
    PI_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    PI_OUTPUT.write_text("\n".join(body), encoding="utf-8")
    data = PI_OUTPUT.read_bytes()
    return PI_OUTPUT, len(data), sha256(data)


def main() -> int:
    if not PI_ROOT.is_dir():
        raise SystemExit(f"Pi worktree not found: {PI_ROOT}")
    for path, size, digest in (build_pi_bundle(), build_paw_bundle()):
        print(path)
        print(f"bytes={size}")
        print(f"sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
