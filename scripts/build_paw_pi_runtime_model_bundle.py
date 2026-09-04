#!/usr/bin/env python3
"""Build a provenance-rich, text-only PAW/Pi Runtime review bundle.

The generator reads source worktrees and installed manifests without modifying
them. Credential-like values are redacted only in the generated copy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


PAW_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PI_ROOT = PAW_ROOT.parent / "pi"
DEFAULT_OUTPUT = PAW_ROOT / "docs/handoffs/model-bundles/PAW_PI_RUNTIME_MODEL_BUNDLE.md"
APP_SUPPORT = Path.home() / "Library" / "Application Support" / "RagIme"

AUTHORITY_FILES = (
    "AGENTS.md",
    "PROJECT.md",
    "OUTCOMES.md",
    "CONTEXT.md",
    "DECISIONS.md",
    "ARCHITECTURE.md",
    "control-center-web/docs/pawos/PAWOS_REQUIREMENTS.md",
)
AUTHORITY_GLOBS = (
    "control-center-web/docs/pawos/requirements/PAWOS_REQUIREMENTS_*.md",
)

PAW_EXACT_FILES = (
    "pyproject.toml",
    "rag_ime/agent_service.py",
    "rag_ime/agent_sessions.py",
    "rag_ime/agent_runtime_driver.py",
    "rag_ime/agent_tools.py",
    "rag_ime/agent_delegation.py",
    "rag_ime/agent_background_jobs.py",
    "rag_ime/managed_pi_runtime.py",
    "rag_ime/node/pi_provider_bridge.mjs",
    "scripts/build_managed_pi_runtime_v2.py",
    "scripts/install_managed_pi_runtime.py",
    "scripts/prepare_managed_pi_runtime.py",
    "scripts/prune_managed_pi_runtime.py",
    "scripts/install_product_stack.sh",
    "scripts/smoke_pi_session_staged_runtime.py",
    "scripts/smoke_pi_room_composition.py",
    "scripts/pi_canary_support.py",
    "control-center-web/src/contracts/agent-reducer.ts",
    "control-center-web/src/contracts/agent-reducer.test.ts",
    "control-center-web/src/contracts/room-reducer.ts",
    "control-center-web/src/contracts/room-reducer.test.ts",
    "control-center-web/src/features/rooms/runtime/use-room-live-session.ts",
    "control-center-web/src/features/rooms/runtime/use-room-live-session.test.tsx",
)

PAW_GLOBS = (
    "rag_ime/pi_runtime*.py",
    "rag_ime/agent_room*.py",
    "rag_ime/contracts/json/agent-*.json",
    "rag_ime/contracts/json/pi-runtime-manifest.v1.json",
    "integrations/pi/**/*",
    "tests/test_pi_runtime*.py",
    "tests/test_managed_pi_runtime*.py",
    "tests/test_build_managed_pi_runtime*.py",
    "tests/test_agent_service*.py",
    "tests/test_agent_sessions*.py",
    "tests/test_agent_tools*.py",
    "tests/test_agent_delegation*.py",
    "tests/test_agent_background_jobs*.py",
    "tests/test_agent_room*.py",
)

PI_EXACT_FILES = (
    "package.json",
    "tsconfig.json",
    "packages/agent/package.json",
    "packages/agent/README.md",
    "packages/ai/package.json",
    "packages/ai/README.md",
    "packages/coding-agent/package.json",
    "packages/coding-agent/README.md",
    "packages/coding-agent/src/index.ts",
    "packages/coding-agent/src/config.ts",
    "integrations/rag-ime-runtime-host/package.json",
    "integrations/rag-ime-runtime-host/README.md",
    "integrations/rag-ime-runtime-host/tsconfig.build.json",
    "integrations/rag-ime-runtime-host/vitest.config.ts",
)

PI_GLOBS = (
    "integrations/rag-ime-runtime-host/src/**/*.ts",
    "integrations/rag-ime-runtime-host/test/**/*.ts",
    "packages/agent/src/**/*.ts",
    "packages/agent/test/**/*.ts",
    "packages/ai/src/**/*.ts",
    "packages/coding-agent/src/core/**/*.ts",
    "packages/coding-agent/src/modes/rpc/**/*.ts",
    "packages/coding-agent/test/agent-session*.test.ts",
    "packages/coding-agent/test/compaction*.test.ts",
    "packages/coding-agent/test/extensions*.test.ts",
    "packages/coding-agent/test/model-runtime*.test.ts",
    "packages/coding-agent/test/package-manager*.test.ts",
    "packages/coding-agent/test/resource-loader*.test.ts",
    "packages/coding-agent/test/rpc*.test.ts",
    "packages/coding-agent/test/sdk*.test.ts",
    "packages/coding-agent/test/session-manager/**/*.test.ts",
    "packages/coding-agent/test/suite/agent-session*.test.ts",
    "packages/coding-agent/test/suite/harness.ts",
)

TEXT_SUFFIXES = {
    ".cjs", ".css", ".html", ".js", ".json", ".md", ".mjs", ".py",
    ".sh", ".toml", ".ts", ".tsx", ".yaml", ".yml",
}
EXCLUDED_PARTS = {
    ".cache", ".git", "bin", "binary", "build", "cache", "credentials",
    "db", "dist", "history", "log", "logs", "model", "models",
    "node_modules", "output", "test-results", "__pycache__",
}
EXCLUDED_NAMES = {
    ".DS_Store", ".env", ".env.local", "auth.json", "credentials.json",
    "bun.lock", "bun.lockb", "Cargo.lock", "composer.lock", "Gemfile.lock",
    "package-lock.json", "Pipfile.lock", "pnpm-lock.yaml", "poetry.lock",
    "npm-shrinkwrap.json", "uv.lock", "yarn.lock",
}
MAX_SOURCE_BYTES = 1_500_000

SECRET_PATTERNS = (
    ("private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL)),
    ("openai-key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("github-token", re.compile(r"\bgh(?:p|o|u|s|r)_[A-Za-z0-9]{24,}\b")),
    ("aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}\b")),
    ("bearer", re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]{32,}={0,2}")),
)

LANGUAGE_BY_SUFFIX = {
    ".cjs": "javascript", ".css": "css", ".html": "html", ".js": "javascript",
    ".json": "json", ".md": "markdown", ".mjs": "javascript", ".py": "python",
    ".sh": "bash", ".toml": "toml", ".ts": "typescript", ".tsx": "tsx",
    ".yaml": "yaml", ".yml": "yaml",
}

OWNER_MARKERS = (
    "export async function runAgentLoop(",
    "export class AgentSession",
    "export class Agent",
    "export class AgentSessionRuntime",
    "export class RagImeRuntimeHost",
    "class PiRuntimeManager",
    "class PiRuntimeHostManager",
    "def resolve_protocol_manager(",
    "class AgentService",
)


@dataclass(frozen=True)
class GitSnapshot:
    root: Path
    label: str
    head: str
    branch: str
    remote: str
    status: dict[str, str]
    tracked: frozenset[str]
    dirty_count: int

    def file_status(self, relative: str) -> str:
        if relative in self.status:
            return self.status[relative]
        return "tracked-clean" if relative in self.tracked else "outside-git-index"


@dataclass(frozen=True)
class SourceFile:
    group: str
    repository: str
    root: Path
    path: Path
    status: str

    @property
    def relative(self) -> str:
        return self.path.relative_to(self.root).as_posix()


def run(command: list[str], *, cwd: Path) -> str:
    completed = subprocess.run(
        command,
        cwd=cwd,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return completed.stdout.strip()


def git_snapshot(root: Path, label: str, *, ignored_dirty: set[str] | None = None) -> GitSnapshot:
    ignored_dirty = ignored_dirty or set()
    head = run(["git", "rev-parse", "HEAD"], cwd=root)
    branch = run(["git", "branch", "--show-current"], cwd=root) or "detached"
    try:
        remote = run(["git", "remote", "get-url", "origin"], cwd=root)
    except subprocess.CalledProcessError:
        remote = "none"
    tracked = frozenset(run(["git", "ls-files"], cwd=root).splitlines())
    raw_status = run(["git", "status", "--porcelain=v1", "--untracked-files=all"], cwd=root)
    statuses: dict[str, str] = {}
    for line in raw_status.splitlines():
        if len(line) < 4:
            continue
        code, relative = line[:2], line[3:]
        if " -> " in relative:
            relative = relative.split(" -> ", 1)[1]
        relative = relative.strip('"')
        if relative in ignored_dirty:
            continue
        statuses[relative] = f"git-{code.strip() or code.replace(' ', '_')}"
    return GitSnapshot(root, label, head, branch, scrub_remote(remote), statuses, tracked, len(statuses))


def scrub_remote(remote: str) -> str:
    return re.sub(r"(https?://)[^/@\s]+@", r"\1[redacted]@", remote)


def eligible(path: Path) -> bool:
    if not path.is_file() or path.is_symlink() or path.name in EXCLUDED_NAMES:
        return False
    if path.suffix.lower() not in TEXT_SUFFIXES:
        return False
    if any(part in EXCLUDED_PARTS for part in path.parts):
        return False
    return path.stat().st_size <= MAX_SOURCE_BYTES


def collect_paths(root: Path, exact: tuple[str, ...], globs: tuple[str, ...]) -> list[Path]:
    paths: set[Path] = set()
    for relative in exact:
        path = root / relative
        if not path.is_file():
            raise FileNotFoundError(f"required source is missing: {path}")
        if eligible(path):
            paths.add(path)
    for pattern in globs:
        paths.update(path for path in root.glob(pattern) if eligible(path))
    return sorted(paths, key=lambda item: item.relative_to(root).as_posix())


def collect_sources(paw: GitSnapshot, pi: GitSnapshot) -> list[SourceFile]:
    sources: list[SourceFile] = []
    authority_paths = collect_paths(PAW_ROOT, AUTHORITY_FILES, AUTHORITY_GLOBS)
    paw_paths = collect_paths(PAW_ROOT, PAW_EXACT_FILES, PAW_GLOBS)
    pi_paths = collect_paths(pi.root, PI_EXACT_FILES, PI_GLOBS)
    for path in authority_paths:
        relative = path.relative_to(PAW_ROOT).as_posix()
        sources.append(SourceFile("01-authorities", paw.label, PAW_ROOT, path, paw.file_status(relative)))
    for path in paw_paths:
        if path in authority_paths:
            continue
        relative = path.relative_to(PAW_ROOT).as_posix()
        sources.append(SourceFile("02-paw-adapters-contracts-build-tests", paw.label, PAW_ROOT, path, paw.file_status(relative)))
    for path in pi_paths:
        relative = path.relative_to(pi.root).as_posix()
        sources.append(SourceFile("03-pi-core-runtime-host-tests", pi.label, pi.root, path, pi.file_status(relative)))
    sources.extend(installed_evidence_sources())
    return sorted(sources, key=lambda item: (item.group, item.repository, item.relative))


def installed_evidence_sources() -> list[SourceFile]:
    pointer = APP_SUPPORT / "PiRuntime" / "current.json"
    if not pointer.is_file():
        return []
    payload = json.loads(pointer.read_text(encoding="utf-8"))
    version = str(payload.get("version") or "")
    manifest = pointer.parent / version / "manifest.json"
    sources = [SourceFile("04-installed-runtime-evidence", "installed-runtime", pointer.parent, pointer, "read-only-runtime-state")]
    if manifest.is_file():
        sources.append(SourceFile("04-installed-runtime-evidence", "installed-runtime", pointer.parent, manifest, "read-only-runtime-state"))
    return sources


def sanitize_copy(text: str) -> tuple[str, dict[str, int]]:
    counts: dict[str, int] = {}
    sanitized = text
    for label, pattern in SECRET_PATTERNS:
        sanitized, count = pattern.subn(f"[REDACTED_COPY_ONLY:{label}]", sanitized)
        if count:
            counts[label] = count
    return sanitized, counts


def fence_for(text: str) -> str:
    longest = max((len(match.group(0)) for match in re.finditer(r"`+", text)), default=0)
    return "`" * max(3, longest + 1)


def source_bytes(path: Path) -> bytes:
    payload = path.read_bytes()
    if b"\0" in payload:
        raise ValueError(f"NUL byte rejected: {path}")
    return payload


def render_ledger() -> str:
    return """## User Requirement Ledger / 用户愿景与不可越界边界

### VISION-PI-001 — 用真实 Session 自举开发 PAW | `current / P0`

- **Current controlling requirement:** PAW 的主要开发单元是真实、可恢复、可继续的 Pi Session；Agent 可以调用多个独立 Session 完成工作并汇总。
- **User-visible acceptance:** 长任务、Tool、Steer、Stop、compaction、恢复和结果在同一真实 Session 生命周期中连续可见，不由文档或前端模拟完成态。
- **Must preserve:** Pi 的 Session/Tool loop、真实 transcript、Provider 调用、事件与终态。
- **Must not do:** 把静态聊天页、Markdown 工作项或 mock 事件称作 Session Runtime。
- **Dependencies / ordering:** 先确认 Pi 内核与 PAW adapter 的真实来源，再审阅 Room、Web projection 和 managed packaging。
- **Source quote:** “以后我就要用 Session 来开发本项目，自举，就像 DeepSeek Harness 那种。”；“一个 Agent，然后调用几个 Session 实例。这些读 docs 和传过来的上下文，自己 loop；事件型地响应，再由一个 Agent 检查汇总。”
- **Source refs:** `docs/project/PROJECT.md:14-16`.
- **Corrections / superseded meanings:** supersedes 把普通网页对话或 PAW 自建循环视为 Agent Runtime 的含义。

### VISION-PI-002 — Pi 是唯一 Agent Runtime | `current / P0`

- **Current controlling requirement:** Pi alone owns Agent/Tool loops, transcript, Provider interaction, compaction, Steer, Stop/cancel and Session recovery；PAW 只提供产品合同、adapter、治理与投影。
- **User-visible acceptance:** 同一命令不会被 PAW 与 Pi 各执行一次；Stop、重试、压缩和恢复只有一个权威结果。
- **Must preserve:** Pi public contract、真实 Pi source、typed receipts 和 PAW adapter 边界。
- **Must not do:** 在 Python、Room 或 Web 中复制第二套 Provider/Tool/Session loop。
- **Dependencies / ordering:** Runtime 修复从真实 Pi owner 或最薄 adapter seam 开始。
- **Source quote:** “还有现在模型层交给了pi，所以模型必定能够成功，对吧。我会补的是同一套 WorkDocument/WorkItem 绑定与按引用加载，不再造第二套上下文系统这个用软的，告诉大家去哪找就行，还有得知道docs里面哪些正在干活，怎么找对应session”
- **Source refs:** raw user quote `docs/pawos/PAWOS_REQUIREMENTS.md:2056`; controlling authority `docs/pawos/PAWOS_REQUIREMENTS.md:88-90`; `docs/project/DECISIONS.md:D-001`; `docs/project/ARCHITECTURE.md:166-192`.
- **Corrections / superseded meanings:** supersedes 任何“PAWOS/Tutti/Room 可成为另一内核”的解释。

### VISION-PI-003 — Room 只是普通 Pi Sessions 的轻量组合 | `current / P0`

- **Current controlling requirement:** Room owns collaboration identity, dispatch, public ordering, cancellation fan-out and one Root；每个 Partner 仍是普通 Pi Session。
- **User-visible acceptance:** Room 可展示真实伙伴分工、并发、Stop fan-out 和一个 Root 最终结果，但不会生成一套与 Session 冲突的运行状态。
- **Must preserve:** Session identity、Room dispatch lineage、公开事件顺序、one Root terminal。
- **Must not do:** second Provider loop、second Event Bus、merged Session/Room state、把 Facilitator 做成所有消息的中心转发器。
- **Dependencies / ordering:** Session owner 先稳定；Room 只组合，不接管。
- **Source quote:** “一个 Agent，然后调用几个 Session 实例。这些读 docs 和传过来的上下文，自己 loop；事件型地响应，再由一个 Agent 检查汇总。”
- **Source refs:** `docs/project/PROJECT.md:16`; accepted authority `docs/project/DECISIONS.md:D-002`; `docs/project/ARCHITECTURE.md:164-205`; `docs/pawos/PAWOS_REQUIREMENTS.md:2246-2248`.
- **Corrections / superseded meanings:** supersedes 旧 Room kernel、Room-as-Session-subtype 和 merged Runtime 设计。

### VISION-PI-004 — Tutti 只作实现参考，不作产品内核或依赖 | `current / P0`

- **Current controlling requirement:** 可直接迁移 Tutti 成熟的窗口、渲染与交互机制，但 Runtime ownership、产品身份和状态必须留在 PAW/Pi。
- **User-visible acceptance:** PAWOS 交互至少达到参考项目的速度与完整度，同时卸载 Tutti 或移动其 worktree 不影响 PAW 运行。
- **Must preserve:** PAW-owned interfaces、Pi authority、可回退的现有 PAW surface。
- **Must not do:** import Tutti Runtime state、依赖 Tutti 绝对路径、复制其产品身份或历史包袱。
- **Dependencies / ordering:** 迁移纵向切片后在 PAW 仓库验证。
- **Source quote:** “反正tutti和egolite还有codexx前端都可以直接把代码拿过来”
- **Source refs:** raw user quote `docs/pawos/PAWOS_REQUIREMENTS.md:1713`; controlling authority `docs/pawos/PAWOS_REQUIREMENTS.md:83-96,1234-1244`; `docs/project/ARCHITECTURE.md:247-279`.
- **Corrections / superseded meanings:** supersedes 把 Tutti 当 PAW runtime/kernel 或持久依赖的方案。

### VISION-PI-005 — 前端只投影权威状态，不复制 Runtime | `current / P0`

- **Current controlling requirement:** Web reducer 和 PAWOS 只能从 versioned transport、snapshot 与 ordered events 构建读模型；窗口快照只保存 presentation state。
- **User-visible acceptance:** 刷新、折叠、开关窗口不会伪造 running/completed，也不会删除真实 trace；关闭窗口不等于 Stop。
- **Must preserve:** reducer ownership、sequence gap recovery、terminal fences、Pi/PAW commands。
- **Must not do:** 在 desktop store/localStorage 重建 Session、Room、WorkItem、approval、Package、Memory、Knowledge 或 terminal truth。
- **Dependencies / ordering:** Runtime state first，projection second，visual state last。
- **Source quote:** “对话轨迹我们有这个功能的，不是让你写原文，而是trace。你看看deepseek的这个实现，和pi导出网页对话记录。我们做过了的”
- **Source refs:** raw user quote `docs/pawos/PAWOS_REQUIREMENTS.md:1721`; controlling authority `docs/pawos/PAWOS_REQUIREMENTS.md:314,415-432,1252`; `docs/project/ARCHITECTURE.md:173-205,247-268`.
- **Corrections / superseded meanings:** supersedes 根据 UI 卡片、动画或本地窗口状态推断 Runtime 完成。

### VISION-PI-006 — 直接复用成熟能力，避免防御性过度设计 | `current / P0`

- **Current controlling requirement:** 对已经存在且适配 seam 明确的能力，迁移完整纵向切片并做薄适配；只保留真实触发过的校验、生命周期和恢复防线。
- **User-visible acceptance:** 功能先真实跑通，交互直接、低延迟，不因抽象层和预防性框架变慢或变复杂。
- **Must preserve:** 真实宿主差异、必要安全边界、可执行回归。
- **Must not do:** 为未出现的异常建立第二套框架、自然语言 Kernel validator 或重复状态机。
- **Dependencies / ordering:** owner seam 明确后做最小实现，再进行成比例验证。
- **Source quote:** “不要防御性编程过度设计”；“反正tutti和egolite还有codexx前端都可以直接把代码拿过来”
- **Source refs:** raw user quotes `docs/pawos/PAWOS_REQUIREMENTS.md:1711,1713`; controlling authority `docs/pawos/PAWOS_REQUIREMENTS.md:1234-1244`.
- **Corrections / superseded meanings:** supersedes 以“未来可能需要”为理由扩张 Runtime/adapter 层。

### VISION-PI-007 — 来源与安装态必须诚实区分 | `current / P0`

- **Current controlling requirement:** 完整 Pi 源不在 PAW 仓库时，必须引用真实本地 Pi worktree，并把 worktree HEAD/dirty、installed manifest provenance 和 PAW adapter 分开陈述。
- **User-visible acceptance:** 审查者可以从每个文件的 repository/path/status/bytes/SHA256 追到源，不会把 adapter、已安装 bundle 或模型描述冒充内核源码。
- **Must preserve:** installed pointer/manifest、source contract、local worktree provenance、每文件 hash。
- **Must not do:** 从 installed bundle 反推不存在的 dirty source，或声称 current clean worktree 等同历史安装快照。
- **Dependencies / ordering:** 先查 installed manifest 与 default worktree，再生成检查包。
- **Source quote:** Exact user wording unavailable in the authority documents; this entry records the current task's explicit provenance requirement without inventing a quotation.
- **Source refs:** current task brief; mechanical owners `scripts/build_managed_pi_runtime_v2.py`, `rag_ime/managed_pi_runtime.py`.
- **Corrections / superseded meanings:** supersedes 仅列 PAW Python files 并称其为“Pi 内核”的检查包。

### Source Coverage Audit

| User-original source | Ledger mapping | Coverage |
| --- | --- | --- |
| `docs/project/PROJECT.md:14` | VISION-PI-001 | exact quoted wording |
| `docs/project/PROJECT.md:16` | VISION-PI-001, VISION-PI-003 | exact quoted wording |
| `docs/pawos/PAWOS_REQUIREMENTS.md:1711` | VISION-PI-006 | exact quoted wording |
| `docs/pawos/PAWOS_REQUIREMENTS.md:1713` | VISION-PI-004, VISION-PI-006 | exact quoted wording |
| `docs/pawos/PAWOS_REQUIREMENTS.md:1721` | VISION-PI-005 | exact quoted wording |
| `docs/pawos/PAWOS_REQUIREMENTS.md:2056` | VISION-PI-002 | exact quoted wording |
| current task brief | VISION-PI-007 | provenance requirement recorded without manufacturing a quote |

Accepted interpretations and corrections are linked separately as controlling
authority. They are not presented as verbatim user quotations.
"""


def repo_summary(snapshot: GitSnapshot) -> str:
    return (
        f"| {snapshot.label} | `{snapshot.root}` | `{snapshot.head}` | `{snapshot.branch}` | "
        f"`{snapshot.remote}` | {snapshot.dirty_count} |"
    )


def installed_summary(sources: list[SourceFile]) -> str:
    manifest_source = next((
        source for source in sources
        if source.repository == "installed-runtime" and source.path.name == "manifest.json"
    ), None)
    if not manifest_source:
        return "- No active managed Pi Runtime manifest was found under the default PAW App Support root."
    manifest = json.loads(manifest_source.path.read_text(encoding="utf-8"))
    source = manifest.get("source") if isinstance(manifest.get("source"), dict) else {}
    return "\n".join((
        f"- Active runtime version: `{manifest.get('runtimeVersion', 'unknown')}`; Pi `{manifest.get('piVersion', 'unknown')}`; protocol `{manifest.get('runtimeProtocolVersion', 'unknown')}`.",
        f"- Installed source record: `{source.get('commit', 'unknown')}`; handlers commit `{source.get('handlersCommit', 'unknown')}`; package `{source.get('package', 'unknown')}`.",
        f"- Installed product record: `{source.get('productCommit', 'unknown')}` from `{source.get('productRepository', 'unknown')}`.",
        "- Boundary: the manifest is installed-state evidence, not source. Compiled runtime binaries and Node are excluded from this text bundle.",
    ))


def contract_resolution(pi_root: Path) -> str:
    contract_path = PAW_ROOT / "integrations" / "pi" / "session-runtime-host-contract.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    rows = []
    for owner, relative in sorted(contract.get("handlerSources", {}).items()):
        candidate = pi_root / str(relative)
        rows.append(f"| {owner} | `{relative}` | {'present' if candidate.is_file() else 'missing'} |")
    detected = pi_root / "integrations" / "rag-ime-runtime-host"
    if not detected.is_dir():
        detected = None
    return "\n".join((
        f"- Detected local Runtime Host source root: `{detected or 'missing'}`.",
        "- Contract-declared handler paths are checked literally against the current worktree:",
        "",
        "| Owner | Contract path | Current worktree |",
        "| --- | --- | --- |",
        *rows,
    ))


def render_bundle(paw: GitSnapshot, pi: GitSnapshot, sources: list[SourceFile]) -> tuple[str, dict[str, object]]:
    raw_total = 0
    redactions: dict[str, int] = {}
    group_counts: dict[str, int] = {}
    group_bytes: dict[str, int] = {}
    rendered_files: list[str] = []
    owner_corpus: list[str] = []
    for index, source in enumerate(sources, 1):
        raw = source_bytes(source.path)
        raw_total += len(raw)
        group_counts[source.group] = group_counts.get(source.group, 0) + 1
        group_bytes[source.group] = group_bytes.get(source.group, 0) + len(raw)
        text = raw.decode("utf-8")
        owner_corpus.append(text)
        copied, counts = sanitize_copy(text)
        for label, count in counts.items():
            redactions[label] = redactions.get(label, 0) + count
        digest = hashlib.sha256(raw).hexdigest()
        fence = fence_for(copied)
        language = LANGUAGE_BY_SUFFIX.get(source.path.suffix.lower(), "text")
        rendered_files.append("\n".join((
            f"### FILE-{index:04d} — `{source.relative}`",
            "",
            f"- Group: `{source.group}`",
            f"- Repository: `{source.repository}`",
            f"- Repository root: `{source.root}`",
            f"- Source path: `{source.path}`",
            f"- Git/runtime status: `{source.status}`",
            f"- Source bytes: `{len(raw)}`",
            f"- Source SHA256: `{digest}`",
            f"- Generated-copy redactions: `{sum(counts.values())}`",
            "",
            f"{fence}{language}",
            copied.rstrip("\n"),
            fence,
        )))
    corpus = "\n".join(owner_corpus)
    missing_markers = [marker for marker in OWNER_MARKERS if marker not in corpus]
    if missing_markers:
        raise ValueError(f"required owner symbols missing from selected sources: {missing_markers}")
    group_rows = [
        f"| {group} | {group_counts[group]} | {group_bytes[group]} |"
        for group in sorted(group_counts)
    ]
    header = "\n".join((
        "# PAW Pi Runtime Model Review Bundle",
        "",
        render_ledger(),
        "",
        "## Repository and Runtime Snapshot",
        "",
        "This is a read-only text snapshot for architecture and implementation review. PAW adapters are not Pi core. The installed manifest is not source. Tutti is not included because it is a UI/reference repository, not a PAW Runtime dependency.",
        "",
        "| Repository | Root | HEAD | Branch | Origin | Dirty entries |",
        "| --- | --- | --- | --- | --- | ---: |",
        repo_summary(paw),
        repo_summary(pi),
        "",
        "### Installed managed Runtime evidence",
        "",
        installed_summary(sources),
        "",
        "### Source divergence and adapter boundary",
        "",
        "- The PAW repository contains product adapters, contracts, packaging, Room composition and UI projections; it does not contain the complete Pi core.",
        f"- The default future managed build source resolves to the current local worktree `{pi.root}` at `{pi.head}` ({'dirty' if pi.dirty_count else 'clean'}).",
        "- If the installed manifest records another commit or a `+dirty.<digest>` suffix, that exact historical dirty source is not reconstructed from the current worktree. The snapshot records whether each source was dirty or clean; both evidence sets remain intentionally distinct.",
        "- `integrations/rag-ime-runtime-host` is the product adapter living in the Pi fork. `packages/agent`, `packages/ai`, and `packages/coding-agent` contain the Pi-owned runtime/session/provider implementation included below.",
        "- Room composition, PAW persistence and Web reducers remain PAW-owned consumers/projections; they must not become a second Agent Runtime.",
        "",
        "### Runtime Host source-contract resolution",
        "",
        contract_resolution(pi.root),
        "",
        "### Bundle inventory",
        "",
        "| Group | Files | Raw source bytes |",
        "| --- | ---: | ---: |",
        *group_rows,
        f"| **total** | **{len(sources)}** | **{raw_total}** |",
        "",
        f"Generated-copy credential redactions: `{sum(redactions.values())}`. Redactions affect this generated copy only; source files are never edited.",
        "",
        "Exclusions: `node_modules`, `dist`, `build`, caches, logs, databases, credential/config payloads, personal history, model/binary assets, generated output, lockfiles, symlinks, NUL-bearing files and files larger than the bounded text-source limit.",
        "",
        "## Complete Selected Source, Contracts, Packaging and Tests",
        "",
    ))
    bundle = header + "\n\n" + "\n\n".join(rendered_files) + "\n"
    for label, pattern in SECRET_PATTERNS:
        if pattern.search(bundle):
            raise ValueError(f"credential-like value remained after copy sanitization: {label}")
    if "\0" in bundle:
        raise ValueError("generated bundle contains NUL")
    summary: dict[str, object] = {
        "fileCount": len(sources),
        "rawSourceBytes": raw_total,
        "groups": {group: {"files": group_counts[group], "bytes": group_bytes[group]} for group in sorted(group_counts)},
        "copyRedactions": redactions,
        "pawHead": paw.head,
        "piHead": pi.head,
    }
    return bundle, summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pi-worktree", type=Path, default=DEFAULT_PI_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true", help="verify that the existing output matches a fresh render")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    pi_root = args.pi_worktree.expanduser().resolve()
    output = args.output.expanduser().resolve()
    if not (pi_root / "integrations" / "rag-ime-runtime-host").is_dir():
        raise SystemExit(
            "Pi Runtime Host source is unavailable: expected canonical "
            f"integrations/rag-ime-runtime-host under {pi_root}"
        )
    try:
        output_relative = output.relative_to(PAW_ROOT).as_posix()
    except ValueError:
        output_relative = ""
    paw = git_snapshot(PAW_ROOT, "PAW adapter/product", ignored_dirty={output_relative} if output_relative else set())
    pi = git_snapshot(pi_root, "Pi core/fork worktree")
    sources = collect_sources(paw, pi)
    bundle, summary = render_bundle(paw, pi, sources)
    encoded = bundle.encode("utf-8")
    if args.check:
        if not output.is_file() or output.read_bytes() != encoded:
            raise SystemExit(f"bundle is stale: {output}")
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(output.suffix + ".tmp")
        temporary.write_bytes(encoded)
        temporary.replace(output)
    summary.update({
        "ok": True,
        "output": str(output),
        "outputBytes": len(encoded),
        "outputSha256": hashlib.sha256(encoded).hexdigest(),
        "mode": "check" if args.check else "write",
    })
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
