#!/usr/bin/env python3
"""Build a privacy-safe PAW backend review ZIP for a web model.

The package keeps PAW, Pi, Tutti prompt-reference, Tutti DuoAgent-reference,
and PAW Skill provenance separate. Source worktrees are read-only; redactions
apply only to package copies.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from types import ModuleType
from typing import Iterable


PAW_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TUTTI_ROOT = PAW_ROOT.parent / "tutti"
DEFAULT_PI_ROOT = PAW_ROOT.parent / "pi"
DEFAULT_SKILLS_ROOT = PAW_ROOT.parent / "pi-skills"
DEFAULT_OUTPUT = PAW_ROOT / "output" / "model-review" / "paw-backend-web-model-review.zip"

GUIDE_FILES = (
    "docs/handoffs/model-bundles/README_FOR_BACKEND_WEB_MODEL.md",
    "docs/handoffs/model-bundles/TUTTI_SYSTEM_PROMPT_INVENTORY.md",
    "docs/handoffs/model-bundles/TUTTI_DUOAGENT_REFERENCE.md",
    "docs/handoffs/model-bundles/PAW_SKILL_INVENTORY.md",
)
AUTHORITY_FILES = (
    "AGENTS.md",
    "docs/README.md",
    "docs/project/PROJECT.md",
    "docs/project/PRODUCT.md",
    "docs/project/OUTCOMES.md",
    "docs/project/CONTEXT.md",
    "docs/project/DECISIONS.md",
    "docs/project/ARCHITECTURE.md",
    "docs/pawos/PAWOS_REQUIREMENTS.md",
    "control-center-web/docs/pawos/PAWOS_FRONTEND_HISTORY.md",
)
INTERFACE_FILES = (
    "control-center-web/docs/handoffs/PAWOS_FUNCTION_INTERFACE_GUIDE.md",
    "control-center-web/docs/handoffs/PAWOS_WEB_MODEL_APP_FUNCTIONS.md",
    "control-center-web/docs/handoffs/PAWOS_WEB_MODEL_REAL_DATA_FIXTURES.md",
)

TUTTI_EXACT_PROMPT_FILES = (
    "packages/agent/daemon/runtime/prompt_content.go",
    "packages/agent/daemon/runtime/prompt_content_test.go",
    "packages/agent/daemon/runtime/tutti_mode_host_context.go",
    "packages/agent/daemon/runtime/tutti_mode_host_context_test.go",
    "packages/agent/daemon/runtime/codex_appserver_event_params.go",
    "packages/agent/daemon/runtime/codex_appserver_side.go",
    "packages/agent/daemon/runtime/codex_appserver_turn.go",
    "packages/agent/daemon/runtime/codex_appserver_adapter.go",
    "packages/agent/daemon/runtime/acp_auto_continue.go",
    "packages/agent/daemon/runtime/tutti_mention_routing.go",
    "packages/agent/daemon/runtime/claude_provider_meta.go",
    "packages/agent/daemon/runtime/claude_sdk_execution.go",
    "packages/agent/daemon/runtime/claude_sdk_compaction_notice.go",
    "packages/agent/daemon/runtime/standard_acp_turn.go",
    "packages/agent/daemon/runtime/acp_provider_cursor.go",
    "packages/agent/host/runtime_operation_plan.go",
    "packages/agent/host/runtime_operation_plan_test.go",
    "packages/agent/claude-sdk-sidecar/src/options.ts",
    "packages/agent/claude-sdk-sidecar/src/options.test.ts",
    "packages/agent/claude-sdk-sidecar/src/compaction.ts",
    "packages/agent/claude-sdk-sidecar/src/compaction.test.ts",
    "packages/agent/claude-sdk-sidecar/src/queryGeneration.ts",
    "packages/agent/claude-sdk-sidecar/src/sessionRuntime.ts",
    "packages/agent/claude-sdk-sidecar/src/sdkMessages.ts",
    "services/tuttid/service/collabrun/service.go",
    "services/tuttid/service/collabrun/service_test.go",
    "services/tuttid/service/workspace/app_factory_prompts.go",
    "services/tuttid/service/workspace/app_factory_prompts_test.go",
    "services/tuttid/service/workspace/issue_sequential_dispatch.go",
    "services/tuttid/service/agent/native_provider_probe.go",
    "services/tuttid/service/agent/external_import_parse.go",
    "services/tuttid/data/workspace/migrations_automation_rules.go",
    "services/tuttid/tutti_mode_plan_feedback_dispatcher.go",
    "services/tuttid/tutti_mode_goal_review_agent_adapter.go",
    "packages/workspace/issue-manager/src/core/runPrompt.ts",
    "apps/desktop/scripts/generate-release-summary.mjs",
)
TUTTI_PROMPT_GLOBS = (
    "packages/agent/runtimeprep/**/*",
    "services/tuttid/service/tuttimodeexecution/**/*",
    "services/tuttid/service/workspace/app_factory_reference/**/*",
)
TUTTI_SCAN_ROOTS = (
    "packages/agent/runtimeprep",
    "packages/agent/daemon/runtime",
    "packages/agent/host",
    "packages/agent/claude-sdk-sidecar/src",
    "services/tuttid",
    "packages/workspace",
    "apps/desktop/scripts",
)

# "DuoAgent" is the handoff vocabulary. Tutti's current source calls the two
# relevant vertical slices Tutti Mode execution and CollaborationRun. Keep the
# selection explicit at its architectural seams, then scan only bounded owner
# roots for the current symbol closure so renamed integration files are not
# silently omitted.
TUTTI_DUOAGENT_EXACT_FILES = (
    "docs/architecture/workspace-workflows.md",
    "docs/architecture/issue-execution.md",
    "docs/architecture/model-access-plans.md",
    "services/tuttid/api/openapi/tuttid.v1.yaml",
    "services/tuttid/api/routes.go",
    "services/tuttid/api/routes_tutti_mode_execution.go",
    "services/tuttid/api/daemon_collab_runs.go",
    "services/tuttid/api/daemon_tutti_mode_activation.go",
    "services/tuttid/api/daemon_tutti_mode_activation_test.go",
    "services/tuttid/api/daemon_tutti_mode_execution.go",
    "services/tuttid/api/daemon_tutti_mode_execution_test.go",
    "services/tuttid/api/daemon_tutti_mode_goal_review.go",
    "services/tuttid/api/daemon_tutti_mode_goal_review_contract_test.go",
    "services/tuttid/data/workspace/migrations.go",
    "services/tuttid/data/workspace/store.go",
    "services/tuttid/service/agent/collab_timeline.go",
    "services/tuttid/service/agent/collab_timeline_test.go",
    "services/tuttid/service/workspace/issue_budget_gate.go",
    "services/tuttid/service/workspace/issue_budget_history.go",
    "services/tuttid/service/workspace/issue_execution_coordinator.go",
    "services/tuttid/service/workspace/issue_execution_ports.go",
    "services/tuttid/service/workspace/issue_run_observer.go",
    "services/tuttid/service/workspace/issue_sequential_dispatch.go",
    "services/tuttid/service/workspace/issue_sequential_dispatch_test.go",
    "services/tuttid/service/workspace/issue_tutti_mode_mutation.go",
    "services/tuttid/agent_collaboration_canceller.go",
    "services/tuttid/tutti_mode_execution_agent_adapter.go",
    "services/tuttid/tutti_mode_execution_agent_adapter_test.go",
    "services/tuttid/tutti_mode_execution_watchdog_wiring.go",
    "services/tuttid/tutti_mode_execution_watchdog_wiring_test.go",
    "services/tuttid/tutti_mode_goal_review_agent_adapter.go",
    "services/tuttid/tutti_mode_goal_review_agent_adapter_test.go",
    "services/tuttid/tutti_mode_plan_feedback_dispatcher.go",
    "services/tuttid/tutti_mode_plan_feedback_dispatcher_test.go",
    "services/tuttid/wiring_daemon_api.go",
    "services/tuttid/wiring_issue_execution_startup.go",
    "packages/agent/activity-core/src/collaboration.types.ts",
    "packages/agent/gui/agentActivityRuntime.tsx",
    "packages/agent/gui/shared/agentConversation/components/AgentCollaborationRow.tsx",
    "packages/agent/gui/shared/agentConversation/components/AgentMessageBlock.tsx",
    "packages/agent/gui/shared/agentConversation/contracts/agentCollaborationVM.ts",
    "packages/agent/gui/shared/agentConversation/projection/agentCollaborationProjection.ts",
    "packages/agent/gui/shared/agentConversation/projection/agentCollaborationProjection.spec.ts",
    "packages/clients/tuttid-ts/src/collaborationRunsClient.ts",
    "packages/clients/tuttid-ts/src/workspaceIssueOrchestrationClient.ts",
    "packages/events/protocol/definitions/agent/collaboration.updated.event.json",
    "apps/desktop/src/renderer/src/features/workspace-agent/services/internal/workspaceAgentActivityService.ts",
    "apps/desktop/src/renderer/src/features/workspace-agent/services/internal/workspaceAgentActivityService.test.ts",
)
TUTTI_DUOAGENT_GLOBS = (
    "services/tuttid/biz/collabrun/**/*",
    "services/tuttid/service/collabrun/**/*",
    "services/tuttid/biz/tuttimodeactivation/**/*",
    "services/tuttid/service/tuttimodeactivation/**/*",
    "services/tuttid/biz/tuttimodeexecution/**/*",
    "services/tuttid/service/tuttimodeexecution/**/*",
    "services/tuttid/service/tuttimodeplan/**/*",
    "services/tuttid/service/cli/providers/tuttimodeplan/**/*",
    "services/tuttid/data/workspace/*collab_run*",
    "services/tuttid/data/workspace/*tutti_mode*",
    "services/tuttid/service/eventstream/*collaboration*",
    "services/tuttid/service/eventstream/*tutti_mode*",
    "packages/agent/daemon/runtime/*tutti_mode*",
    "packages/agent/runtimeprep/*tutti_mode*",
    "packages/agent/runtimeprep/skill_templates/tutti-model-allocation*",
    "packages/agent/gui/workspaceWorkflow/tuttiModePlan/**/*",
    "packages/agent/gui/app/renderer/i18n/locales/*agentGuiCollaboration*",
)
TUTTI_DUOAGENT_SCAN_ROOTS = (
    "services/tuttid/api",
    "services/tuttid/data/workspace",
    "services/tuttid/service/agent",
    "services/tuttid/service/eventstream",
    "services/tuttid/service/workspace",
    "services/tuttid",
    "packages/agent",
    "packages/clients/tuttid-ts/src",
    "packages/events/protocol/definitions/agent",
    "apps/desktop/src/renderer/src/features/workspace-agent",
    "apps/desktop/src/renderer/src/features/workspace-workbench",
)
TUTTI_DUOAGENT_SCAN_PATTERNS = (
    re.compile(r"(?i)\bcollabrun|\bCollaborationRun"),
    re.compile(r"(?i)\btutti[_ -]?mode[_ -]?execution|\bTuttiModeExecution"),
    re.compile(r"(?i)\btutti(?:[_ -]?mode)?[_ -]?plan|\bTutti Mode\b"),
    re.compile(r"(?i)\bgoal[_ -]?review|\bGoalReview"),
)

TEXT_SUFFIXES = {
    ".cjs", ".css", ".go", ".html", ".js", ".json", ".md", ".mjs",
    ".mod", ".py", ".sh", ".sql", ".sum", ".toml", ".ts", ".tsx",
    ".txt", ".yaml", ".yml",
}
TEXT_NAMES = {"LICENSE", "NOTICE"}
EXCLUDED_PARTS = {
    ".cache", ".git", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    "__pycache__", "build", "cache", "coverage", "credentials",
    "dist", "history", "logs", "model-cache", "node_modules", "output",
    "playwright-report", "private", "test-results",
}
EXCLUDED_NAMES = {
    ".DS_Store", ".env", ".env.local", "auth.json", "credentials.json",
    "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "uv.lock",
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
SECRET_ASSIGNMENT = re.compile(
    r"(?i)(\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|"
    r"password|authorization)\b[\"']?\s*[:=]\s*)([\"'])([^\"'\n]{4,})([\"'])"
)

PROMPT_SCAN_PATTERNS = (
    ("system-prompt", re.compile(r"(?i)\bsystem[_ -]?prompt\b")),
    ("developer-instructions", re.compile(r"(?i)\bdeveloper[_ -]?instructions\b")),
    ("system-reminder", re.compile(r"<system-reminder>")),
    ("prompt-constant", re.compile(r"\b(?:const|var)\s+[A-Za-z0-9_]*(?:Prompt|Instructions|Reminder)[A-Za-z0-9_]*")),
    ("prompt-field", re.compile(r"\b(?:Prompt|System|Instruction):\s*[\"'`]")),
    ("prompt-builder", re.compile(r"\b(?:func|function)\s+[A-Za-z0-9_]*(?:Prompt|Instructions)[A-Za-z0-9_]*")),
    ("model-role", re.compile(r"(?:\bYou are\b|\bYou have been\b)")),
)

LANGUAGE_BY_SUFFIX = {
    ".cjs": "javascript", ".css": "css", ".go": "go", ".html": "html",
    ".js": "javascript", ".json": "json", ".md": "markdown",
    ".mjs": "javascript", ".mod": "text", ".py": "python", ".sh": "bash",
    ".sql": "sql", ".sum": "text", ".toml": "toml", ".ts": "typescript",
    ".tsx": "tsx", ".txt": "text", ".yaml": "yaml", ".yml": "yaml",
}


@dataclass(frozen=True)
class RepoSnapshot:
    label: str
    head: str
    branch: str
    dirty_count: int


@dataclass
class SourceReceipt:
    repository: str
    category: str
    source_relative: str
    target: str
    git_status: str
    original_bytes: int
    original_sha256: str
    package_bytes: int
    package_sha256: str
    redactions: dict[str, int]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tutti-root", type=Path, default=DEFAULT_TUTTI_ROOT)
    parser.add_argument("--pi-root", type=Path, default=DEFAULT_PI_ROOT)
    parser.add_argument("--skills-root", type=Path, default=DEFAULT_SKILLS_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    return parser.parse_args()


def load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def run(command: list[str], cwd: Path) -> str:
    completed = subprocess.run(
        command, cwd=cwd, check=True, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True,
    )
    return completed.stdout.strip()


def snapshot(root: Path, label: str) -> RepoSnapshot:
    status = run(["git", "status", "--porcelain=v1", "--untracked-files=all"], root)
    return RepoSnapshot(
        label=label,
        head=run(["git", "rev-parse", "HEAD"], root),
        branch=run(["git", "branch", "--show-current"], root) or "detached",
        dirty_count=len(status.splitlines()) if status else 0,
    )


def git_file_status(root: Path) -> tuple[set[str], dict[str, str]]:
    tracked = set(run(["git", "ls-files"], root).splitlines())
    raw = run(["git", "status", "--porcelain=v1", "--untracked-files=all"], root)
    statuses: dict[str, str] = {}
    for line in raw.splitlines():
        if len(line) < 4:
            continue
        relative = line[3:]
        if " -> " in relative:
            relative = relative.split(" -> ", 1)[1]
        statuses[relative.strip('"')] = f"git-{line[:2].strip() or line[:2].replace(' ', '_')}"
    return tracked, statuses


def status_for(relative: str, tracked: set[str], statuses: dict[str, str]) -> str:
    if relative in statuses:
        return statuses[relative]
    return "tracked-clean" if relative in tracked else "outside-git-index"


def eligible(path: Path) -> bool:
    if not path.is_file() or path.is_symlink() or path.name in EXCLUDED_NAMES:
        return False
    if any(part in EXCLUDED_PARTS for part in path.parts):
        return False
    if path.name not in TEXT_NAMES and path.suffix.lower() not in TEXT_SUFFIXES:
        return False
    return path.stat().st_size <= MAX_SOURCE_BYTES


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sanitize(text: str, roots: Iterable[Path]) -> tuple[str, dict[str, int]]:
    counts: dict[str, int] = {}
    sanitized = text
    for label, pattern in SECRET_PATTERNS:
        sanitized, count = pattern.subn(f"[REDACTED_PACKAGE_COPY:{label}]", sanitized)
        if count:
            counts[label] = counts.get(label, 0) + count

    def replace_assignment(match: re.Match[str]) -> str:
        counts["secret-assignment"] = counts.get("secret-assignment", 0) + 1
        return f"{match.group(1)}{match.group(2)}[REDACTED_PACKAGE_COPY:secret-assignment]{match.group(4)}"

    sanitized = SECRET_ASSIGNMENT.sub(replace_assignment, sanitized)
    replacements = {
        str(Path.home()): "/Users/[REDACTED_USER]",
        str(PAW_ROOT.parent.parent): "/Volumes/[REDACTED_VOLUME]",
    }
    for root in roots:
        replacements[str(root)] = f"[SOURCE_ROOT:{root.name}]"
    for source, replacement in sorted(replacements.items(), key=lambda item: len(item[0]), reverse=True):
        count = sanitized.count(source)
        if count:
            sanitized = sanitized.replace(source, replacement)
            counts["machine-path"] = counts.get("machine-path", 0) + count
    return sanitized, counts


def add_text_source(
    staging: Path,
    receipts: list[SourceReceipt],
    *,
    repository: str,
    category: str,
    root: Path,
    path: Path,
    target: str,
    git_status: str,
    roots: tuple[Path, ...],
) -> None:
    if not eligible(path):
        raise ValueError(f"ineligible required source: {path}")
    raw = path.read_bytes()
    if b"\0" in raw:
        raise ValueError(f"NUL byte in selected source: {path}")
    text = raw.decode("utf-8")
    copied, redactions = sanitize(text, roots)
    encoded = copied.encode("utf-8")
    destination = staging / target
    if destination.exists():
        if destination.read_bytes() != encoded:
            raise ValueError(f"package target collision: {target}")
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(encoded)
    receipts.append(SourceReceipt(
        repository=repository,
        category=category,
        source_relative=path.relative_to(root).as_posix(),
        target=target,
        git_status=git_status,
        original_bytes=len(raw),
        original_sha256=sha256(raw),
        package_bytes=len(encoded),
        package_sha256=sha256(encoded),
        redactions=redactions,
    ))


def walk_eligible(root: Path) -> list[Path]:
    return sorted((path for path in root.rglob("*") if eligible(path)), key=lambda path: path.relative_to(root).as_posix())


def collect_tutti_prompt_paths(tutti_root: Path) -> list[Path]:
    selected: set[Path] = set()
    for relative in TUTTI_EXACT_PROMPT_FILES:
        path = tutti_root / relative
        if path.is_file() and eligible(path):
            selected.add(path)
    for pattern in TUTTI_PROMPT_GLOBS:
        selected.update(path for path in tutti_root.glob(pattern) if eligible(path))
    for relative_root in TUTTI_SCAN_ROOTS:
        scan_root = tutti_root / relative_root
        if not scan_root.is_dir():
            continue
        for path in walk_eligible(scan_root):
            relative = path.relative_to(tutti_root).as_posix()
            if "/generated/" in f"/{relative}/" or "/i18n/" in f"/{relative}/" or "/testdata/" in f"/{relative}/":
                continue
            if path.name.endswith(("_test.go", ".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx")):
                continue
            text = path.read_text(encoding="utf-8")
            if any(pattern.search(text) for _, pattern in PROMPT_SCAN_PATTERNS):
                selected.add(path)
    return sorted(selected, key=lambda path: path.relative_to(tutti_root).as_posix())


def collect_tutti_duoagent_paths(tutti_root: Path) -> list[Path]:
    selected: set[Path] = set()
    for relative in TUTTI_DUOAGENT_EXACT_FILES:
        path = tutti_root / relative
        if path.is_file() and eligible(path):
            selected.add(path)
    for pattern in TUTTI_DUOAGENT_GLOBS:
        selected.update(path for path in tutti_root.glob(pattern) if eligible(path))
    for relative_root in TUTTI_DUOAGENT_SCAN_ROOTS:
        scan_root = tutti_root / relative_root
        if not scan_root.is_dir():
            continue
        for path in walk_eligible(scan_root):
            relative = path.relative_to(tutti_root).as_posix()
            if "/generated/" in f"/{relative}/" or "/testdata/" in f"/{relative}/":
                continue
            text = path.read_text(encoding="utf-8")
            if any(pattern.search(text) for pattern in TUTTI_DUOAGENT_SCAN_PATTERNS):
                selected.add(path)
    return sorted(selected, key=lambda path: path.relative_to(tutti_root).as_posix())


def render_prompt_candidates(tutti_root: Path, roots: tuple[Path, ...]) -> str:
    rows = ["path\tline\tclassifiers\tpreview"]
    for relative_root in TUTTI_SCAN_ROOTS:
        scan_root = tutti_root / relative_root
        if not scan_root.is_dir():
            continue
        for path in walk_eligible(scan_root):
            relative = path.relative_to(tutti_root).as_posix()
            if "/generated/" in f"/{relative}/" or "/i18n/" in f"/{relative}/" or "/testdata/" in f"/{relative}/":
                continue
            if path.name.endswith(("_test.go", ".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx")):
                continue
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                labels = [label for label, pattern in PROMPT_SCAN_PATTERNS if pattern.search(line)]
                if not labels:
                    continue
                preview, _ = sanitize(line.strip().replace("\t", " "), roots)
                rows.append(f"{relative}\t{number}\t{','.join(labels)}\t{preview[:600]}")
    return "\n".join(rows) + "\n"


def fence_for(text: str) -> str:
    longest = max((len(match.group(0)) for match in re.finditer(r"`+", text)), default=0)
    return "`" * max(3, longest + 1)


def render_tutti_extraction(staging: Path, receipts: list[SourceReceipt]) -> str:
    prompt_receipts = sorted(
        (receipt for receipt in receipts if receipt.category == "tutti-prompt-source"),
        key=lambda receipt: receipt.source_relative,
    )
    sections = [
        "# Tutti System Prompts — Embedded Source Extraction",
        "",
        "This is the source-authoritative extraction for the Tutti prompt snapshot. "
        "Dynamic final prompts depend on current host facts, capability packs and provider transport; "
        "review the builders together with their templates rather than treating one literal as the final prompt.",
        "",
        f"Selected prompt-related source files: `{len(prompt_receipts)}`.",
        "",
    ]
    for index, receipt in enumerate(prompt_receipts, 1):
        path = staging / receipt.target
        content = path.read_text(encoding="utf-8")
        fence = fence_for(content)
        language = LANGUAGE_BY_SUFFIX.get(Path(receipt.source_relative).suffix.lower(), "text")
        sections.extend((
            f"## PROMPT-SOURCE-{index:04d} — `{receipt.source_relative}`",
            "",
            f"- Git status: `{receipt.git_status}`",
            f"- Original bytes: `{receipt.original_bytes}`",
            f"- Original SHA-256: `{receipt.original_sha256}`",
            f"- Package-copy redactions: `{sum(receipt.redactions.values())}`",
            "",
            f"{fence}{language}",
            content.rstrip("\n"),
            fence,
            "",
        ))
    return "\n".join(sections)


def duoagent_layer(relative: str) -> str:
    if relative.startswith("docs/"):
        return "architecture"
    if "/biz/" in relative:
        return "domain"
    if "/data/" in relative:
        return "persistence"
    if "/api/" in relative or relative.startswith("packages/clients/"):
        return "transport"
    if "/eventstream/" in relative or "collab_timeline" in relative:
        return "events-and-timeline"
    if relative.startswith("packages/agent/gui/") or relative.startswith("apps/desktop/"):
        return "frontend-projection"
    if "/runtimeprep/" in relative or "/daemon/runtime/" in relative:
        return "runtime-context"
    if "/service/" in relative or relative.startswith("services/tuttid/"):
        return "orchestration-and-adapters"
    return "supporting-contract"


def render_duoagent_index(receipts: list[SourceReceipt]) -> str:
    selected = sorted(
        (receipt for receipt in receipts if receipt.category == "tutti-duoagent-reference"),
        key=lambda receipt: receipt.source_relative,
    )
    layer_counts: dict[str, int] = {}
    rows: list[str] = []
    for receipt in selected:
        layer = duoagent_layer(receipt.source_relative)
        layer_counts[layer] = layer_counts.get(layer, 0) + 1
        test_kind = "test" if receipt.source_relative.endswith(
            ("_test.go", ".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx")
        ) else "source"
        rows.append(
            f"| `{layer}` | `{test_kind}` | [`{receipt.source_relative}`](source/{receipt.source_relative}) "
            f"| `{receipt.git_status}` | {receipt.original_bytes} | `{receipt.original_sha256}` |"
        )
    count_rows = "\n".join(
        f"| `{layer}` | {count} |" for layer, count in sorted(layer_counts.items())
    )
    return f"""# Tutti DuoAgent Reference Source Index

`DuoAgent` is the handoff label. The current Tutti source uses Tutti Mode
execution and CollaborationRun names. This is a bounded reference-source
closure, not a complete Tutti checkout and not proof of PAW migration.

Selected files: `{len(selected)}`.

## Coverage by layer

| Layer | Files |
| --- | ---: |
{count_rows}

## Source receipts

| Layer | Kind | Tutti source path | Git status | Original bytes | Original SHA-256 |
| --- | --- | --- | --- | ---: | --- |
{chr(10).join(rows)}
"""


def copy_generated_text(staging: Path, source: Path, target: str, roots: tuple[Path, ...]) -> None:
    raw = source.read_text(encoding="utf-8")
    copied, _ = sanitize(raw, roots)
    destination = staging / target
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(copied, encoding="utf-8")


def skill_names(root: Path) -> list[str]:
    return sorted(path.name for path in root.iterdir() if path.is_dir() and not path.name.startswith("."))


def write_entrypoint(
    staging: Path,
    snapshots: list[RepoSnapshot],
    receipts: list[SourceReceipt],
    private_skills: list[str],
    current_skills: list[str],
) -> None:
    category_counts: dict[str, int] = {}
    for receipt in receipts:
        category_counts[receipt.category] = category_counts.get(receipt.category, 0) + 1
    snapshot_rows = "\n".join(
        f"| {item.label} | `{item.head}` | `{item.branch}` | {item.dirty_count} |"
        for item in snapshots
    )
    category_rows = "\n".join(
        f"| `{category}` | {count} |" for category, count in sorted(category_counts.items())
    )
    content = f"""# PAW Backend Web-Model Review Workspace

This ZIP contains the current PAW backend, the selected authoritative Pi Runtime
source, the Tutti system/developer prompt reference corpus, the bounded Tutti
DuoAgent/Tutti Mode implementation reference, PAW-owned Skills, interfaces,
production-shaped privacy-safe fixtures, licenses and a per-file manifest.

Start with `guides/PAW_BACKEND_WEB_MODEL_GUIDE.md`.

## Responsibility warning

- Pi is the sole Agent Runtime.
- PAW owns product backend capabilities and adapters.
- Tutti prompts and DuoAgent/Tutti Mode code are reference source only and must
  not become a production dependency or proof that the behavior was migrated.
- Skills are conditional methods, not Runtime state or authority.

## Source snapshots

| Repository | HEAD | Branch | Dirty entries |
| --- | --- | --- | ---: |
{snapshot_rows}

The PAW dirty working tree is intentional: this package captures current source
without resetting, stashing, committing or pushing it. Tutti, Pi and pi-skills
were clean when the package was built.

## Coverage

| Category | Source files copied |
| --- | ---: |
{category_rows}

- Private Pi Skill package: `{len(private_skills)}` Skills.
- Current PAW Skill checkout: `{len(current_skills)}` Skills.
- Tutti extraction includes dynamic builders, templates, provider transports,
  recovery/compaction paths and specialized synthetic prompts.
- Tutti DuoAgent reference includes the current Tutti Mode execution and Goal
  Review path plus the adjacent CollaborationRun vertical slice. Tutti has no
  literal `DuoAgent` source type in this snapshot.
- Room/Session examples are production-shaped fixtures, not private user transcripts.

## Navigation

- `guides/` — vision, review brief, Tutti prompt/DuoAgent maps and PAW Skill map.
- `authorities/` — controlling PAW project and architecture documents.
- `code/paw/` — navigable current PAW backend source/contracts/tests.
- `code/pi/` — navigable selected Pi core/Runtime Host source and tests.
- `single-file-bundles/` — searchable embedded-source backend and Pi bundles.
- `tutti-prompts/` — extracted prompt corpus, conservative scan and source tree.
- `tutti-duoagent/` — bounded Tutti Mode/CollaborationRun reference source and index.
- `skills/` — private {len(private_skills)}-Skill package and current
  {len(current_skills)}-Skill PAW checkout.
- `interfaces-and-fixtures/` — route/function guide and safe real-shape data.
- `licenses/` — PAW notices and upstream license texts.
- `manifest/` — provenance, exclusions, per-file hashes and package checksums.

## Explicit exclusions

API keys, credentials, account state, user configuration, SQLite databases,
chat histories, logs, model weights, dependency directories, caches, compiled
Python, generated binaries and build output are absent. Package-copy redactions
never modify a source worktree.
"""
    (staging / "00_READ_ME_FIRST_BACKEND.md").write_text(content, encoding="utf-8")


def validate_package(staging: Path, receipts: list[SourceReceipt]) -> dict[str, object]:
    if len({receipt.target for receipt in receipts}) != len(receipts):
        raise ValueError("duplicate source targets in receipt ledger")
    required_paths = (
        "guides/TUTTI_DUOAGENT_REFERENCE.md",
        "tutti-duoagent/SOURCE_INDEX.md",
        "tutti-duoagent/source/docs/architecture/workspace-workflows.md",
        "tutti-duoagent/source/services/tuttid/service/tuttimodeexecution/service.go",
        "tutti-duoagent/source/services/tuttid/service/tuttimodeexecution/worker_test.go",
        "tutti-duoagent/source/services/tuttid/service/collabrun/service.go",
        "tutti-duoagent/source/packages/agent/gui/shared/agentConversation/components/AgentCollaborationRow.tsx",
    )
    missing = [relative for relative in required_paths if not (staging / relative).is_file()]
    if missing:
        raise ValueError(f"required DuoAgent reference paths missing: {missing}")
    duoagent_receipts = [
        receipt for receipt in receipts if receipt.category == "tutti-duoagent-reference"
    ]
    if not duoagent_receipts:
        raise ValueError("Tutti DuoAgent reference source selection is empty")
    duoagent_test_count = sum(
        receipt.source_relative.endswith(
            ("_test.go", ".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx")
        )
        for receipt in duoagent_receipts
    )
    if duoagent_test_count == 0:
        raise ValueError("Tutti DuoAgent reference contains no executable tests")
    secret_hits: list[str] = []
    local_path_hits: list[str] = []
    for path in sorted(staging.rglob("*")):
        if not path.is_file():
            continue
        data = path.read_bytes()
        if b"\0" in data:
            raise ValueError(f"NUL byte in package text: {path.relative_to(staging)}")
        text = data.decode("utf-8")
        for label, pattern in SECRET_PATTERNS:
            if pattern.search(text):
                secret_hits.append(f"{path.relative_to(staging)}:{label}")
        if str(Path.home()) in text or str(PAW_ROOT.parent.parent) in text:
            local_path_hits.append(path.relative_to(staging).as_posix())
    if secret_hits:
        raise ValueError(f"credential-like values remain: {secret_hits[:10]}")
    if local_path_hits:
        raise ValueError(f"machine-local paths remain: {local_path_hits[:10]}")
    return {
        "sourceReceiptCount": len(receipts),
        "sourceOriginalBytes": sum(receipt.original_bytes for receipt in receipts),
        "sourcePackageBytes": sum(receipt.package_bytes for receipt in receipts),
        "sourceRedactions": sum(sum(receipt.redactions.values()) for receipt in receipts),
        "tuttiDuoAgentSourceCount": len(duoagent_receipts),
        "tuttiDuoAgentTestCount": duoagent_test_count,
    }


def deterministic_zip(staging: Path, output: Path, package_name: str) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(staging.rglob("*"), key=lambda item: item.relative_to(staging).as_posix()):
            if not path.is_file():
                continue
            relative = path.relative_to(staging).as_posix()
            info = zipfile.ZipInfo(f"{package_name}/{relative}", date_time=(2026, 8, 23, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o100644 & 0xFFFF) << 16
            archive.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    temporary.replace(output)


def build(args: argparse.Namespace, output: Path) -> dict[str, object]:
    tutti_root = args.tutti_root.expanduser().resolve()
    pi_root = args.pi_root.expanduser().resolve()
    skills_root = args.skills_root.expanduser().resolve()
    roots = (PAW_ROOT, tutti_root, pi_root, skills_root)
    for root in roots:
        if not root.is_dir():
            raise FileNotFoundError(root)

    backend_builder = load_module("paw_backend_bundle_builder", PAW_ROOT / "scripts/build_paw_backend_model_bundle.py")
    pi_builder = load_module("paw_pi_bundle_builder", PAW_ROOT / "scripts/build_paw_pi_runtime_model_bundle.py")
    subprocess.run([sys.executable, str(PAW_ROOT / "scripts/build_paw_backend_model_bundle.py")], cwd=PAW_ROOT, check=True)
    subprocess.run([
        sys.executable, str(PAW_ROOT / "scripts/build_paw_pi_runtime_model_bundle.py"),
        "--pi-worktree", str(pi_root),
    ], cwd=PAW_ROOT, check=True)

    snapshots = [
        snapshot(PAW_ROOT, "PAW product/backend"),
        snapshot(pi_root, "Pi Runtime"),
        snapshot(tutti_root, "Tutti prompt and DuoAgent reference"),
        snapshot(skills_root, "PAW private Pi Skills"),
    ]
    paw_tracked, paw_statuses = git_file_status(PAW_ROOT)
    tutti_tracked, tutti_statuses = git_file_status(tutti_root)
    skills_tracked, skills_statuses = git_file_status(skills_root)

    private_skill_names = skill_names(skills_root / "skills")
    current_skill_names = skill_names(PAW_ROOT / "integrations/pi/skills")
    if len(private_skill_names) != 13:
        raise ValueError(f"expected 13 private Skills, found {len(private_skill_names)}")
    if not current_skill_names:
        raise ValueError("current PAW Skill checkout is empty")

    with tempfile.TemporaryDirectory(prefix="paw-backend-web-model-") as temporary_dir:
        staging = Path(temporary_dir)
        receipts: list[SourceReceipt] = []

        backend_paths, backend_categories = backend_builder.collect_files()
        for path in backend_paths:
            relative = path.relative_to(PAW_ROOT).as_posix()
            add_text_source(
                staging, receipts, repository="paw", category=f"paw-{backend_categories[relative]}",
                root=PAW_ROOT, path=path, target=f"code/paw/{relative}",
                git_status=status_for(relative, paw_tracked, paw_statuses), roots=roots,
            )

        paw_pi_snapshot = pi_builder.git_snapshot(PAW_ROOT, "PAW adapter/product")
        pi_snapshot = pi_builder.git_snapshot(pi_root, "Pi core/fork worktree")
        for source in pi_builder.collect_sources(paw_pi_snapshot, pi_snapshot):
            if source.repository == "installed-runtime":
                continue
            repository = "paw" if source.root == PAW_ROOT else "pi"
            target = f"code/{repository}/{source.relative}"
            add_text_source(
                staging, receipts, repository=repository, category=source.group,
                root=source.root, path=source.path, target=target,
                git_status=source.status, roots=roots,
            )

        tutti_prompt_paths = collect_tutti_prompt_paths(tutti_root)
        for path in tutti_prompt_paths:
            relative = path.relative_to(tutti_root).as_posix()
            add_text_source(
                staging, receipts, repository="tutti", category="tutti-prompt-source",
                root=tutti_root, path=path, target=f"tutti-prompts/source/{relative}",
                git_status=status_for(relative, tutti_tracked, tutti_statuses), roots=roots,
            )

        tutti_duoagent_paths = collect_tutti_duoagent_paths(tutti_root)
        for path in tutti_duoagent_paths:
            relative = path.relative_to(tutti_root).as_posix()
            add_text_source(
                staging, receipts, repository="tutti", category="tutti-duoagent-reference",
                root=tutti_root, path=path, target=f"tutti-duoagent/source/{relative}",
                git_status=status_for(relative, tutti_tracked, tutti_statuses), roots=roots,
            )

        for path in walk_eligible(skills_root):
            relative = path.relative_to(skills_root).as_posix()
            add_text_source(
                staging, receipts, repository="pi-skills", category="private-pi-skill-package",
                root=skills_root, path=path, target=f"skills/private-pi-skills/{relative}",
                git_status=status_for(relative, skills_tracked, skills_statuses), roots=roots,
            )

        current_skills_root = PAW_ROOT / "integrations/pi/skills"
        for path in walk_eligible(current_skills_root):
            relative = path.relative_to(current_skills_root).as_posix()
            source_relative = path.relative_to(PAW_ROOT).as_posix()
            add_text_source(
                staging, receipts, repository="paw", category="current-paw-skill",
                root=current_skills_root, path=path, target=f"skills/current-paw/{relative}",
                git_status=status_for(source_relative, paw_tracked, paw_statuses), roots=roots,
            )

        for relative in GUIDE_FILES:
            copy_generated_text(staging, PAW_ROOT / relative, f"guides/{Path(relative).name}", roots)
        for relative in AUTHORITY_FILES:
            path = PAW_ROOT / relative
            if path.is_file():
                copy_generated_text(staging, path, f"authorities/{path.name}", roots)
        for relative in INTERFACE_FILES:
            path = PAW_ROOT / relative
            if path.is_file():
                copy_generated_text(staging, path, f"interfaces-and-fixtures/{path.name}", roots)

        copy_generated_text(
            staging, PAW_ROOT / "docs/handoffs/model-bundles/PAW_BACKEND_MODEL_BUNDLE.md",
            "single-file-bundles/PAW_BACKEND_MODEL_BUNDLE.md", roots,
        )
        copy_generated_text(
            staging, PAW_ROOT / "docs/handoffs/model-bundles/PAW_PI_RUNTIME_MODEL_BUNDLE.md",
            "single-file-bundles/PAW_PI_RUNTIME_MODEL_BUNDLE.md", roots,
        )

        legal_sources = (
            (PAW_ROOT / "LICENSE", "licenses/PAW_LICENSE"),
            (PAW_ROOT / "THIRD_PARTY_NOTICES.md", "licenses/PAW_THIRD_PARTY_NOTICES.md"),
            (tutti_root / "LICENSE", "licenses/TUTTI_APACHE_2.0.txt"),
            (pi_root / "LICENSE", "licenses/PI_MIT.txt"),
            (skills_root / "LICENSES/PAW-GPL-3.0-only.txt", "licenses/PI_SKILLS_PAW_GPL_3.0_ONLY.txt"),
        )
        for source, target in legal_sources:
            if source.is_file():
                copy_generated_text(staging, source, target, roots)

        candidate_text = render_prompt_candidates(tutti_root, roots)
        (staging / "tutti-prompts/prompt-source-candidates.tsv").write_text(candidate_text, encoding="utf-8")
        extraction = render_tutti_extraction(staging, receipts)
        (staging / "tutti-prompts/TUTTI_SYSTEM_PROMPTS_EXTRACTED.md").write_text(extraction, encoding="utf-8")
        duoagent_index = render_duoagent_index(receipts)
        (staging / "tutti-duoagent/SOURCE_INDEX.md").write_text(duoagent_index, encoding="utf-8")

        write_entrypoint(staging, snapshots, receipts, private_skill_names, current_skill_names)
        validation = validate_package(staging, receipts)

        manifest_dir = staging / "manifest"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        manifest = {
            "schemaVersion": 1,
            "packagePurpose": "PAW backend and Pi Runtime review with Tutti prompt and DuoAgent references and PAW Skills",
            "referenceDomains": {
                "tuttiPrompts": "reference-only prompt assembly and provider transport",
                "tuttiDuoAgent": "reference-only Tutti Mode execution, Goal Review, and adjacent CollaborationRun vertical slice",
            },
            "sourceSnapshots": [asdict(item) for item in snapshots],
            "privateSkills": private_skill_names,
            "currentPawSkills": current_skill_names,
            "exclusions": sorted(EXCLUDED_PARTS | EXCLUDED_NAMES | {
                "user configuration", "SQLite databases", "chat history", "logs",
                "model weights", "dependency trees", "build output", "global third-party Skills",
            }),
            "validation": validation,
            "sourceFiles": [asdict(receipt) for receipt in sorted(receipts, key=lambda receipt: receipt.target)],
        }
        manifest_path = manifest_dir / "package-manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        checksums = []
        for path in sorted(staging.rglob("*"), key=lambda item: item.relative_to(staging).as_posix()):
            if path.is_file() and path.name != "SHA256SUMS.txt":
                checksums.append(f"{sha256(path.read_bytes())}  {path.relative_to(staging).as_posix()}")
        (manifest_dir / "SHA256SUMS.txt").write_text("\n".join(checksums) + "\n", encoding="utf-8")

        final_validation = validate_package(staging, receipts)
        package_name = output.stem
        deterministic_zip(staging, output, package_name)

    result = {
        "ok": True,
        "output": str(output),
        "outputBytes": output.stat().st_size,
        "outputSha256": sha256(output.read_bytes()),
        "sourceReceiptCount": len(receipts),
        "tuttiPromptSourceCount": len(tutti_prompt_paths),
        "tuttiDuoAgentSourceCount": len(tutti_duoagent_paths),
        "privateSkillCount": len(private_skill_names),
        "currentPawSkillCount": len(current_skill_names),
        "validation": final_validation,
    }
    return result


def main() -> None:
    args = parse_args()
    output = args.output.expanduser().resolve()
    if args.check:
        with tempfile.TemporaryDirectory(prefix="paw-backend-package-check-") as directory:
            candidate = Path(directory) / output.name
            result = build(args, candidate)
            if not output.is_file() or output.read_bytes() != candidate.read_bytes():
                raise SystemExit(f"package is stale: {output}")
            result["output"] = str(output)
            result["mode"] = "check"
    else:
        result = build(args, output)
        result["mode"] = "write"
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
