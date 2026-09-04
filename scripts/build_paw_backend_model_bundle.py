#!/usr/bin/env python3
"""Build the vision-first, text-only PAW backend model inspection bundle.

Source files are never modified. Credential-like material and machine-local
paths are redacted only in the rendered bundle copy; metadata records the byte
count and SHA-256 of the original source file.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
from collections import Counter
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = REPOSITORY_ROOT / "docs/handoffs/model-bundles/PAW_BACKEND_MODEL_BUNDLE.md"

AUTHORITY_DOCUMENTS = (
    "AGENTS.md",
    "PROJECT.md",
    "OUTCOMES.md",
    "CONTEXT.md",
    "DECISIONS.md",
    "ARCHITECTURE.md",
    "control-center-web/docs/pawos/PAWOS_REQUIREMENTS.md",
)

PAWOS_REQUIREMENTS_PATH = "control-center-web/docs/pawos/PAWOS_REQUIREMENTS.md"
PAWOS_REQUIREMENTS_GLOB = "control-center-web/docs/pawos/requirements/PAWOS_REQUIREMENTS_*.md"

ROOT_BACKEND_FILES = ("pyproject.toml",)

TEXT_SUFFIXES = {
    ".cjs",
    ".json",
    ".md",
    ".mjs",
    ".py",
    ".sh",
    ".sql",
    ".toml",
    ".ts",
    ".txt",
    ".yaml",
    ".yml",
}

EXCLUDED_DIRECTORY_NAMES = {
    ".cache",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "build",
    "cache",
    "credentials",
    "dist",
    "logs",
    "model-cache",
    "node_modules",
    "output",
    "playwright-report",
    "private",
    "test-results",
}

EXCLUDED_FILE_NAMES = {
    "package-lock.json",
    "pnpm-lock.yaml",
    "uv.lock",
    "yarn.lock",
    # Transcript-import fixtures are not part of an external architecture
    # review and may contain history-shaped examples.
    "test_codex_history.py",
    "PAW_BACKEND_MODEL_BUNDLE.md",
    "PAWOS_FRONTEND_MODEL_BUNDLE.md",
    "build_paw_backend_model_bundle.py",
    "build_pawos_frontend_model_bundle.py",
}

BACKEND_SHELL_KEYWORDS = (
    "agent",
    "browser",
    "contract",
    "control",
    "ego",
    "hybrid",
    "input",
    "knowledge",
    "memory",
    "model",
    "pi_",
    "predict",
    "product",
    "rag",
    "route",
    "runtime",
    "sidecar",
)

FRONTEND_ONLY_SCRIPT_NAMES = {
    "build_control_center.sh",
    "build_control_center_web.sh",
    "check_control_center_footprint.sh",
    "check_control_center_web_dist.sh",
    "install_frontend_launch_agent.sh",
    "run_control_center_web_qa.sh",
    "test_control_center_web.sh",
}

LANGUAGE_BY_SUFFIX = {
    ".cjs": "javascript",
    ".json": "json",
    ".md": "markdown",
    ".mjs": "javascript",
    ".py": "python",
    ".sh": "bash",
    ".sql": "sql",
    ".toml": "toml",
    ".ts": "typescript",
    ".txt": "text",
    ".yaml": "yaml",
    ".yml": "yaml",
}

REQUIRED_SYMBOLS = {
    "rag_ime/agent_runtime_driver.py": ("class AgentRuntimeDriver",),
    "rag_ime/agent_rooms.py": ("class AgentRoomStore", "class AgentRoomEventHub"),
    "rag_ime/agent_delegation.py": ("class AgentDelegationCoordinator",),
    "rag_ime/browser_control.py": ("class BrowserControlService",),
    "rag_ime/paw_browser_runtime.py": ("class PawBrowserRuntime",),
    "rag_ime/system_terminal.py": ("class SystemTerminalService",),
    "rag_ime/memory_book_compiler.py": (
        "def build_memory_book_source_bundle",
        "def apply_memory_book_plan",
    ),
    "rag_ime/knowledge_library/service.py": ("class KnowledgeLibraryService",),
    "rag_ime/control_api/route_policy.py": ("class ControlRoutePolicy",),
    "rag_ime/control_api/route_table.py": ("ROUTE_TABLE", "BROWSER_ROUTES", "SYSTEM_TERMINAL_ROUTES"),
    "rag_ime/contracts/json_schema.py": ("def validate_json_schema",),
}

REQUIRED_SCHEMAS = (
    "rag_ime/contracts/json/agent-session.v1.json",
    "rag_ime/contracts/json/agent-room.v1.json",
    "rag_ime/contracts/json/agent-room-work-item.v1.json",
    "rag_ime/contracts/json/memory-bootstrap.v1.json",
    "rag_ime/contracts/json/knowledge-library.v1.json",
    "rag_ime/contracts/json/frontend-capabilities.v1.json",
)

PREFIXED_SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{12,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"(?i)Bearer\s+[A-Za-z0-9._~+/=-]{16,}"),
    re.compile(r"eyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}"),
)

SECRET_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)(\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|"
    r"password|authorization)\b[\"']?\s*[:=]\s*)([\"'])([^\"'\n]{4,})([\"'])"
)

PRIVATE_KEY_PATTERN = re.compile(
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----.*?"
    r"-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
    flags=re.DOTALL,
)

PRIVATE_KEY_MARKER_LINE_PATTERN = re.compile(
    r"(?m)^.*-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*(?:\n|$)|"
    r"^.*-----END [A-Z0-9 ]*PRIVATE KEY-----.*(?:\n|$)"
)


def repository_relative(path: Path) -> str:
    return path.relative_to(REPOSITORY_ROOT).as_posix()


def original_bytes(path: Path) -> bytes:
    return path.read_bytes()


def original_text(path: Path) -> str:
    data = original_bytes(path)
    if b"\x00" in data:
        raise ValueError(f"NUL byte found in selected text source: {repository_relative(path)}")
    return data.decode("utf-8").replace("\r\n", "\n").rstrip() + "\n"


def selectable_text_file(path: Path) -> bool:
    if not path.is_file() or path.name in EXCLUDED_FILE_NAMES:
        return False
    relative_parts = path.relative_to(REPOSITORY_ROOT).parts
    if any(part in EXCLUDED_DIRECTORY_NAMES for part in relative_parts):
        return False
    if path.suffix not in TEXT_SUFFIXES:
        return False
    return path.stat().st_size <= 1_500_000


def collect_files() -> tuple[list[Path], dict[str, str]]:
    selected: dict[Path, str] = {}

    def add(path: Path, category: str) -> None:
        if not path.is_file():
            raise FileNotFoundError(f"required bundle source is missing: {repository_relative(path)}")
        if selectable_text_file(path):
            selected[path] = category

    for relative in AUTHORITY_DOCUMENTS:
        add(REPOSITORY_ROOT / relative, "authority")
    for path in sorted(REPOSITORY_ROOT.glob(PAWOS_REQUIREMENTS_GLOB)):
        add(path, "authority")
    for relative in ROOT_BACKEND_FILES:
        add(REPOSITORY_ROOT / relative, "package")

    rag_root = REPOSITORY_ROOT / "rag_ime"
    for path in rag_root.rglob("*"):
        if selectable_text_file(path):
            selected[path] = "backend"

    ego_root = REPOSITORY_ROOT / "integrations/ego-browser"
    for path in ego_root.rglob("*"):
        if selectable_text_file(path):
            selected[path] = "ego-browser"

    scripts_root = REPOSITORY_ROOT / "scripts"
    for path in scripts_root.iterdir():
        if not selectable_text_file(path):
            continue
        if path.name in FRONTEND_ONLY_SCRIPT_NAMES:
            continue
        if path.suffix in {".py", ".mjs", ".cjs"}:
            selected[path] = "backend-script"
            continue
        lowered = path.name.lower()
        if path.suffix == ".sh" and any(keyword in lowered for keyword in BACKEND_SHELL_KEYWORDS):
            selected[path] = "backend-script"

    tests_root = REPOSITORY_ROOT / "tests"
    for path in tests_root.rglob("*"):
        if not selectable_text_file(path):
            continue
        if path.suffix == ".py" or "fixtures" in path.relative_to(tests_root).parts:
            selected[path] = "backend-test"

    ordered = sorted(selected, key=repository_relative)
    categories = {repository_relative(path): selected[path] for path in ordered}
    return ordered, categories


def git_state() -> tuple[set[str], dict[str, str]]:
    tracked_result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPOSITORY_ROOT,
        check=True,
        stdout=subprocess.PIPE,
    )
    tracked = {
        item.decode("utf-8", errors="surrogateescape")
        for item in tracked_result.stdout.split(b"\0")
        if item
    }
    status_result = subprocess.run(
        ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
        cwd=REPOSITORY_ROOT,
        check=True,
        stdout=subprocess.PIPE,
    )
    statuses: dict[str, str] = {}
    entries = status_result.stdout.split(b"\0")
    index = 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if not entry:
            continue
        decoded = entry.decode("utf-8", errors="surrogateescape")
        status = decoded[:2]
        path = decoded[3:]
        statuses[path] = status
        if status[:1] in {"R", "C"} or status[1:2] in {"R", "C"}:
            index += 1
    return tracked, statuses


def status_for(relative: str, tracked: set[str], statuses: dict[str, str]) -> str:
    if relative in statuses:
        return statuses[relative]
    if relative in tracked:
        return "clean"
    return "untracked-or-ignored"


def redact_bundle_copy(text: str) -> tuple[str, int]:
    redactions = 0

    def replace_pattern(pattern: re.Pattern[str], value: str) -> str:
        nonlocal redactions

        def replacement(_: re.Match[str]) -> str:
            nonlocal redactions
            redactions += 1
            return "[REDACTED_BUNDLE_COPY]"

        return pattern.sub(replacement, value)

    text = replace_pattern(PRIVATE_KEY_PATTERN, text)
    text = replace_pattern(PRIVATE_KEY_MARKER_LINE_PATTERN, text)
    for pattern in PREFIXED_SECRET_PATTERNS:
        text = replace_pattern(pattern, text)

    def assignment_replacement(match: re.Match[str]) -> str:
        nonlocal redactions
        redactions += 1
        return f"{match.group(1)}{match.group(2)}[REDACTED_BUNDLE_COPY]{match.group(4)}"

    text = SECRET_ASSIGNMENT_PATTERN.sub(assignment_replacement, text)

    local_paths = {
        str(Path.home()): "/Users/[REDACTED_USER]",
        str(REPOSITORY_ROOT): "[REPOSITORY_ROOT]",
        str(REPOSITORY_ROOT.parent): "[REPOSITORY_PARENT]",
        str(REPOSITORY_ROOT.parent.parent): "/Volumes/[REDACTED_VOLUME]",
    }
    for source, replacement in sorted(local_paths.items(), key=lambda item: len(item[0]), reverse=True):
        occurrences = text.count(source)
        if occurrences:
            redactions += occurrences
            text = text.replace(source, replacement)
    return text, redactions


def code_fence(content: str) -> str:
    longest = max((len(match.group(0)) for match in re.finditer(r"`+", content)), default=0)
    return "`" * max(3, longest + 1)


def render_file(
    path: Path,
    category: str,
    tracked: set[str],
    statuses: dict[str, str],
) -> tuple[str, int]:
    relative = repository_relative(path)
    source = original_bytes(path)
    content, redaction_count = redact_bundle_copy(original_text(path))
    digest = hashlib.sha256(source).hexdigest()
    fence = code_fence(content)
    language = LANGUAGE_BY_SUFFIX.get(path.suffix, "text")
    metadata = (
        f"- Category: `{category}`\n"
        f"- Git status: `{status_for(relative, tracked, statuses)}`\n"
        f"- Source bytes: `{len(source)}`\n"
        f"- Source SHA256: `{digest}`\n"
        f"- Bundle-copy redactions: `{redaction_count}`"
    )
    return f"### `{relative}`\n\n{metadata}\n\n{fence}{language}\n{content}{fence}\n", redaction_count


def validate_required_sources(selected_paths: set[str]) -> None:
    requirement_sources = [REPOSITORY_ROOT / PAWOS_REQUIREMENTS_PATH]
    requirement_sources.extend(sorted(REPOSITORY_ROOT.glob(PAWOS_REQUIREMENTS_GLOB)))
    requirements = "\n".join(original_text(path) for path in requirement_sources)
    if "### UR-105" not in requirements or "不要Ghostty" not in requirements:
        raise ValueError("PAWOS_REQUIREMENTS.md must retain the controlling embedded-terminal correction")
    for relative, symbols in REQUIRED_SYMBOLS.items():
        if relative not in selected_paths:
            raise ValueError(f"required backend owner omitted: {relative}")
        content = original_text(REPOSITORY_ROOT / relative)
        for symbol in symbols:
            if symbol not in content:
                raise ValueError(f"required owner symbol missing: {relative}: {symbol}")
    for relative in REQUIRED_SCHEMAS:
        if relative not in selected_paths:
            raise ValueError(f"required JSON contract omitted: {relative}")


def requirement_ledger() -> str:
    return """## User Requirement Ledger / 用户愿景与不可越界边界

### VISION-BE-001 — PAW owns product authority | current / P0

- **Current controlling requirement:** PAW owns Room, Memory, Knowledge,
  Browser/Terminal contracts, persistence, policy, public events, projections,
  and allowlisted product APIs.
- **User-visible acceptance:** refresh, recovery, multi-window projection, and
  API reads return the same durable product facts rather than frontend guesses
  or model-authored claims.
- **Must preserve:** local-first storage, explicit owner services, versioned
  contracts, append-only migrations, route policy, audit/receipt evidence.
- **Must not do:** move product authority into UI state, prose, a model prompt,
  an external reference project, or a second ungoverned store.
- **Dependencies:** VISION-BE-002, VISION-BE-003, and the ownership table in
  `docs/project/ARCHITECTURE.md`.
- **Source quotes:**
  > 以后我就要用 Session 来开发本项目，自举，就像 DeepSeek Harness 那种。

  > 一个 Agent，然后调用几个 Session 实例。这些读 docs 和传过来的上下文，自己 loop；事件型地响应，再由一个 Agent 检查汇总。
- **Source refs:** `docs/project/PROJECT.md > Original Vision`; `AGENTS.md > Product
  Boundaries`; `docs/project/ARCHITECTURE.md > System Map` and `Primary Flows`.

### VISION-BE-002 — Pi is the sole Session/Provider/Tool loop | current / P0

- **Current controlling requirement:** Pi owns the Session transcript,
  Provider/model interaction, Tool loop, context/compaction, Steer, follow-up,
  Stop/cancellation, and Session recovery. PAW integrates through bounded public
  protocols and projections.
- **User-visible acceptance:** a Session resumes, streams, uses Tools, compacts,
  steers, stops, and recovers with one truthful Pi lifecycle.
- **Must preserve:** Pi protocol adapters, stable Session identity, explicit
  cancellation and terminal receipts.
- **Must not do:** implement a second Session engine, Provider client loop,
  Tool executor loop, transcript authority, or compaction engine in PAW.
- **Dependencies:** VISION-BE-001; managed Pi public protocol compatibility.
- **Source quotes:** the two Original Vision quotations in VISION-BE-001.
- **Source refs:** `docs/project/PROJECT.md > Hard Boundaries`; `docs/project/ARCHITECTURE.md > Agent
  Session`; `docs/pawos/PAWOS_REQUIREMENTS.md > Agent Is The Single Session And Room Entry`.

### VISION-BE-003 — Room is a lightweight composition of ordinary Sessions | current / P0

- **Current controlling requirement:** PAW Room owns Room/participant identity,
  explicit dispatch, WorkItems, ordered public events, peer routing,
  cancellation fan-out, and one Root terminal result while each participant
  remains an ordinary Pi Session.
- **User-visible acceptance:** participants can work as accountable peers,
  communicate directly when allowed, expose real progress/evidence, and return
  one integrated final without fake completion.
- **Must preserve:** equal peer meaning, explicit owner/dispatch identity,
  causal event ordering, late-result fences, bounded private Tool Agents.
- **Must not do:** add a second Agent Runtime, mandatory natural-language
  Kernel validator, mandatory review pipeline, message relay hierarchy, or
  infer completion from a finished Pi turn without the Room receipt.
- **Dependencies:** VISION-BE-002; Room event/schema and persistence owners.
- **Source quotes:**
  > 本轮只结束了伙伴的 Pi 回合，没有提交结构化交付回执；若这是执行任务，不能视为已经完成。不显示这个。为什么没有去中心化是互相@吗，我要确保你们每个人是平等的，不是要通过上级转交

  > Rooms多人协作、Room 列表、工作流图；每个 Room 可独立开窗。这个我又更好的想法，就是每个patent可以成为一个小窗口，因为桌面嘛，就可以多个windows
- **Source refs:** `docs/pawos/PAWOS_REQUIREMENTS.md > Raw User Source Evidence` and
  `Room Collaboration And Workflow`; `docs/project/PROJECT.md > Current Destination`.

### VISION-BE-004 — Memory and Knowledge remain separate governed systems | current / P0

- **Current controlling requirement:** Memory is the governed personal second
  brain; Knowledge is the governed document/library retrieval system. They keep
  separate sources, stores, indexes, permissions, retrieval behavior, write
  policy, and evaluation claims.
- **User-visible acceptance:** Memory preferences and recall affect the user's
  personal context without silently becoming Knowledge documents; Knowledge
  imports/search remain attributable without becoming personal-memory writes.
- **Must preserve:** provenance, preview/apply/revision checks, rollback,
  source-specific permissions, independent quality evidence.
- **Must not do:** merge stores or scores, silently promote personal evidence to
  Knowledge, or claim Knowledge retrieval quality from Memory evaluation.
- **Dependencies:** VISION-BE-001 and the separate Memory/Knowledge services,
  contracts, migrations, and route families.
- **Source quotes:**
  > 记忆app精心调整，还有增加一个页面，因为这个记忆相当于第二大脑，用户可以在这个页面指定记忆的偏好

  > Memory 我的记忆

  > Knowledge 知识库
- **Source refs:** `docs/pawos/PAWOS_REQUIREMENTS.md > UR-089`, `Raw User Source
  Evidence`, and `Files, Browser, And Terminal`; `docs/project/PROJECT.md > Hard Boundaries`.

### VISION-BE-005 — Browser is one embedded, isolated, jointly visible target | current / P0

- **Current controlling requirement:** PAW owns one isolated Browser profile
  embedded in PAWOS. The human and authorized Agent/Ego Browser control the
  exact same visible target/tab, including truthful History and Settings.
- **User-visible acceptance:** the user can browse normally while Agent actions
  appear on that same page; exact target identity, navigation, login state,
  cookies, history, and trace survive through the owning contracts.
- **Must preserve:** isolation from the user's everyday browser, exact targetId,
  fixed PAW profile, direct Agent capability policy, real visible trace.
- **Must not do:** require a Chrome extension, attach to the personal browser,
  open a second hidden Browser authority, or substitute screenshots for the
  live page.
- **Dependencies:** Browser control/runtime owner, route policy, Ego Browser
  integration, VISION-BE-001.
- **Source quotes:**
  > 然后浏览器因为是我们paw内置的，所以agent有着无与伦比的控制权，就是给他用的，都能干的，本身就相当于沙箱了。现在就不用插件这些，就直接是浏览器，但是ai直接打通，ai全权控制的浏览器。不用中间层了

  > 就这种完整浏览器就行，配合上egolite的控制，就天下无敌
- **Source refs:** `docs/pawos/PAWOS_REQUIREMENTS.md > UR-088`, `PAW Browser`, and
  `Raw User Source Evidence`.

### VISION-BE-006 — Terminal is an embedded PAWOS PTY surface | current / P0

- **Current controlling requirement:** Terminal stays inside its PAWOS window.
  Pi shell/background runs reuse a stable terminalId/run projection there; no
  external macOS terminal is launched.
- **User-visible acceptance:** command, output, input, focus, exit state,
  closure, and recovery all remain in one PAWOS Terminal window.
- **Must preserve:** real PTY/run identity, streaming output, explicit Stop,
  audit authority, non-focus-stealing background updates.
- **Must not do:** launch Ghostty or Terminal.app, expose an external-open
  action, fake a terminal with preview text, or create one window per event.
- **Dependencies:** `SystemTerminalService`, route table/policy, PAWOS terminal
  projection, VISION-BE-001 and VISION-BE-002.
- **Source quotes:**
  > 终端不是打开新应用

  > 那就不要Ghostty
- **Source refs:** `docs/pawos/PAWOS_REQUIREMENTS.md > UR-105`.
- **Correction:** supersedes VISION-BE-009 / UR-099.

### VISION-BE-007 — API, persistence, policy, and projections stay truthful | current / P0

- **Current controlling requirement:** typed routes parse and authorize;
  application services own use cases; durable stores own state; projections
  reduce authoritative snapshots/events. Invalid contracts fail recoverably.
- **User-visible acceptance:** loading, success, failure, recovery, retry,
  cancellation, and completion states match the actual owner after refresh.
- **Must preserve:** allowlisted routes, schema validation, idempotency,
  revision/hash checks, append-only migrations, transaction boundaries, audit
  receipts, and explicit degraded/error states.
- **Must not do:** accept model prose as authority, return `{}` for a malformed
  contract, keep dual state authorities, or turn UI/mock data into production
  success.
- **Dependencies:** VISION-BE-001 through VISION-BE-006.
- **Source quotes:** no additional standalone user quotation is required; this
  entry organizes the controlling ownership/acceptance constraints already
  attached to those user requirements.
- **Source refs:** `AGENTS.md > Coding And Verification`; `docs/project/ARCHITECTURE.md >
  Control Center Request`; `docs/pawos/PAWOS_REQUIREMENTS.md > Global Integrity Rules`.

### VISION-BE-008 — Private data and credentials remain outside inspection artifacts | current / P0

- **Current controlling requirement:** source inspection may include contracts
  and safe fixtures, but credentials, private runtime data, histories, local
  databases, model weights, logs, and machine-specific configuration do not
  enter this bundle. Suspected secrets are redacted only in the bundle copy.
- **User-visible acceptance:** the inspection artifact can be shared with a web
  model without exposing live keys, private memories, or machine data.
- **Must preserve:** original source bytes and hashes, repository-relative
  provenance, source files unchanged.
- **Must not do:** edit source to remove evidence, include local DB/log/history
  contents, or claim that pattern scanning proves universal absence of secrets.
- **Dependencies:** repository safety policy and the generator's bounded
  selection/redaction checks.
- **Source quotes:** exact wording for this packaging-only constraint is not in
  the embedded repository documents; the active delegated TaskBrief is the
  available source and has no stable user-message identifier in this bundle.
- **Source refs:** current delegated TaskBrief; `AGENTS.md > Safety And Git`.

### VISION-BE-009 — External Ghostty/System Terminal hosting | superseded by VISION-BE-006

- **Superseded meaning:** prefer an installed Ghostty surface and fall back to
  the system terminal.
- **Why retained:** it is user-source history and migration context, not a
  current implementation instruction.
- **Must not do:** re-enable it from historical code, tests, or prose.
- **Source refs:** `docs/pawos/PAWOS_REQUIREMENTS.md > UR-099`, explicitly superseded by
  `UR-105`.

### VISION-BE-010 — Extension-mediated or second-browser control | superseded by VISION-BE-005

- **Superseded meaning:** control a browser through a separate extension,
  co-pilot surface, or intermediate browser authority.
- **Why retained:** it explains deleted compatibility paths; the current PAW
  Browser is embedded, isolated, and directly Agent-controlled.
- **Must not do:** restore the extension as the default path or create a second
  visible/hidden Browser owner.
- **Source refs:** `docs/pawos/PAWOS_REQUIREMENTS.md > UR-008`, `UR-022`, `UR-069`, and
  `PAW Browser`.

### Source coverage audit

- `AGENTS.md`: VISION-BE-001, 002, 007, 008.
- `docs/project/PROJECT.md`: VISION-BE-001 through 005.
- `docs/project/OUTCOMES.md`: current backend work remains contextual; prose is not used as
  Runtime completion proof.
- `docs/project/CONTEXT.md`: owner terminology for Project, Session, Room, Tool Agent,
  Runtime Projection, PAW Browser, Memory, and Knowledge.
- `docs/project/DECISIONS.md`: cross-owner decisions are embedded verbatim below.
- `docs/project/ARCHITECTURE.md`: VISION-BE-001 through 007 and dependency direction.
- `docs/pawos/PAWOS_REQUIREMENTS.md`: complete ledger and raw user evidence, including
  current corrections and superseded Browser/Terminal meanings.
- Packaging-only credential/bundle wording is mapped to VISION-BE-008 with an
  explicit source-identity gap rather than a manufactured quotation.
"""


def build_bundle(files: list[Path], categories: dict[str, str]) -> tuple[str, int]:
    tracked, statuses = git_state()
    counts = Counter(categories.values())
    sections = ["# PAW Backend Model Bundle", requirement_ledger().rstrip()]
    sections.append(
        """## Repository Snapshot / 仓库快照与打包边界

This artifact is a source inspection snapshot, not Runtime, installation, or
foreground acceptance. Every source block records repository-relative path,
current Git status, original byte count, and original SHA-256. Content is copied
verbatim except for bundle-only secret and machine-path redactions.

Included: authority documents; `pyproject.toml`; production `rag_ime` Python,
SQL migrations, JSON contracts/schemas, and supporting text; the source-only
Ego Browser integration without dependencies/build output; backend scripts; and
Python backend tests plus compact fixtures.

Excluded: the Web frontend, `node_modules`, `dist`, build/output/cache/report
trees, lockfiles, logs, databases, credentials, histories, model weights,
binaries, private Runtime data, and files larger than the bounded text ceiling.

Category counts: """
        + ", ".join(f"`{key}={counts[key]}`" for key in sorted(counts))
        + f". Total files: `{len(files)}`."
    )
    sections.append("## Embedded Authorities And Backend Source / 权威文档与后端源码")
    total_redactions = 0
    for path in files:
        rendered, redactions = render_file(path, categories[repository_relative(path)], tracked, statuses)
        sections.append(rendered.rstrip())
        total_redactions += redactions
    return "\n\n".join(sections) + "\n", total_redactions


def validate_bundle(bundle: str, selected_paths: set[str]) -> None:
    if not bundle.startswith("# PAW Backend Model Bundle\n\n## User Requirement Ledger / 用户愿景与不可越界边界"):
        raise ValueError("User Requirement Ledger must be the first section after the title")
    if "\x00" in bundle:
        raise ValueError("generated bundle contains a NUL byte")
    if len(bundle.encode("utf-8")) < 1_000_000:
        raise ValueError("generated backend bundle is unexpectedly small")
    if any(
        local_path in bundle
        for local_path in (
            str(Path.home()),
            str(REPOSITORY_ROOT),
            str(REPOSITORY_ROOT.parent.parent),
        )
    ):
        raise ValueError("generated bundle still contains a machine-local path")
    for pattern in (PRIVATE_KEY_PATTERN, PRIVATE_KEY_MARKER_LINE_PATTERN, *PREFIXED_SECRET_PATTERNS):
        match = pattern.search(bundle)
        if match:
            raise ValueError(f"generated bundle still matches sensitive pattern: {pattern.pattern}")
    forbidden_path_fragments = (
        "/node_modules/",
        "/dist/",
        "/build/",
        "/cache/",
        "/logs/",
    )
    headings = re.findall(r"^### `([^`]+)`$", bundle, flags=re.MULTILINE)
    for heading in headings:
        if any(fragment in f"/{heading}/" for fragment in forbidden_path_fragments):
            raise ValueError(f"excluded path leaked into bundle: {heading}")
    validate_required_sources(selected_paths)


def main() -> None:
    files, categories = collect_files()
    selected_paths = {repository_relative(path) for path in files}
    validate_required_sources(selected_paths)
    bundle, redaction_count = build_bundle(files, categories)
    validate_bundle(bundle, selected_paths)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = OUTPUT_PATH.with_suffix(".md.tmp")
    temporary_path.write_text(bundle, encoding="utf-8")
    temporary_path.replace(OUTPUT_PATH)
    digest = hashlib.sha256(OUTPUT_PATH.read_bytes()).hexdigest()
    print(
        f"wrote {repository_relative(OUTPUT_PATH)}: files={len(files)}, "
        f"bytes={OUTPUT_PATH.stat().st_size}, sha256={digest}, redactions={redaction_count}"
    )


if __name__ == "__main__":
    main()
