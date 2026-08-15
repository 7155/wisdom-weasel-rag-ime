#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag_ime.agent_tool_ids import CONTROL_TOOL_IDS
from rag_ime.managed_pi_runtime import (
    MANIFEST_NAME,
    ManagedPiRuntimeError,
    build_managed_pi_runtime_manifest,
    discover_managed_pi_runtime,
    write_managed_pi_runtime_manifest,
)


SESSION_RUNTIME_CONTRACT = (
    ROOT / "integrations" / "pi" / "session-runtime-host-contract.json"
)
SKILL_ROUTING_CARDS = ROOT / "integrations" / "pi" / "skill-routing-cards.json"
BUNDLED_SKILL_SUPPORT_DIRS: frozenset[str] = frozenset()
PROJECT_ROUTING_SKILLS = frozenset(
    {"memory-curation", "plugin-creator"}
)
ROUTING_CARD_FIELDS = ("name", "when", "notFor", "does", "input", "output")
MAX_ROUTING_CARD_CHARS = 420
SKILL_SOURCE_KINDS = ("bundled", "configured", "pi-installed")
REQUIRED_PI_RUNTIME_BASE_COMMIT = "0fd0564af34cb40bbcd6b8903c01b36191c4f90d"
_SESSION_RUNTIME_SOURCE_KEYS = (
    "protocol",
    "runtimeHost",
    "contextInspection",
    "toolBridge",
    "session",
)
_OAUTH_RUNTIME_MODULES = {
    "anthropic.ts": (
        "packages/ai/src/auth/oauth/anthropic.ts",
        "anthropicOAuth",
    ),
    "github-copilot.ts": (
        "packages/ai/src/auth/oauth/github-copilot.ts",
        "githubCopilotOAuth",
    ),
    "openai-codex.ts": (
        "packages/ai/src/auth/oauth/openai-codex.ts",
        "openaiCodexOAuth",
    ),
    "radius.ts": (
        "packages/ai/src/auth/oauth/radius.ts",
        "createRadiusOAuth",
    ),
}


def _run(command: list[str], *, cwd: Path) -> str:
    completed = subprocess.run(
        command,
        cwd=cwd,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return completed.stdout.strip()


def _default_node() -> str:
    configured = os.environ.get("RAG_IME_MANAGED_NODE", "").strip()
    if configured:
        return configured
    try:
        installed = discover_managed_pi_runtime(
            Path.home() / "Library" / "Application Support" / "RagIme"
        )
        installed_node = Path(installed.node_executable)
        if installed_node.is_file():
            return str(installed_node)
    except (OSError, ManagedPiRuntimeError):
        pass
    codex_runtime = (
        Path.home()
        / ".cache"
        / "codex-runtimes"
        / "codex-primary-runtime"
        / "dependencies"
        / "node"
        / "bin"
        / "node"
    )
    if codex_runtime.is_file():
        return str(codex_runtime)
    # Do not bypass discover_managed_pi_runtime with a raw pointer read: a
    # digest-invalid generation must never supply the Node used to build its
    # replacement, and every authoritative pointer read shares the lifecycle
    # lock.
    return shutil.which("node") or ""


def _default_pi_worktree(parent: Path | None = None) -> Path:
    workspace_root = parent or ROOT.parent
    canonical = workspace_root / "pi"
    legacy = workspace_root / "pi-rag-ime-runtime"
    for candidate in (canonical, legacy):
        if (candidate / "packages" / "rag-ime-runtime-host").is_dir():
            return candidate
    return canonical


def _node_relocation_error(node: Path) -> str:
    if sys.platform != "darwin":
        return ""
    try:
        linked = subprocess.run(
            ["otool", "-L", str(node)],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return "could not inspect Node dynamic-library dependencies"
    if "@rpath/libnode." in linked:
        return "Node depends on an external libnode dylib and is not relocatable"
    return ""


def _source_revision(pi_root: Path) -> tuple[str, str]:
    commit = _run(["git", "rev-parse", "HEAD"], cwd=pi_root)
    tracked_diff = subprocess.run(
        [
            "git",
            "diff",
            "--binary",
            "HEAD",
            "--",
            "packages",
            "package.json",
            "package-lock.json",
            "tsconfig.json",
        ],
        cwd=pi_root,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout
    untracked_output = _run(
        [
            "git",
            "ls-files",
            "--others",
            "--exclude-standard",
            "--",
            "packages",
            "package.json",
            "package-lock.json",
            "tsconfig.json",
        ],
        cwd=pi_root,
    )
    untracked = [line for line in untracked_output.splitlines() if line.strip()]
    if not tracked_diff and not untracked:
        return commit, ""
    digest = hashlib.sha256()
    digest.update(tracked_diff)
    for relative in sorted(untracked):
        path = pi_root / relative
        if not path.is_file() or path.is_symlink():
            continue
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
    dirty_digest = digest.hexdigest()[:12]
    return f"{commit}+dirty.{dirty_digest}", dirty_digest


def _verified_session_runtime_contract(pi_root: Path) -> tuple[dict[str, object], str]:
    try:
        contract_bytes = SESSION_RUNTIME_CONTRACT.read_bytes()
        contract = json.loads(contract_bytes)
    except (OSError, json.JSONDecodeError) as exc:
        raise ManagedPiRuntimeError(
            f"Session runtime source contract is unreadable: {exc}"
        ) from exc
    if not isinstance(contract, dict) or contract.get("schemaVersion") != (
        "rag-ime.pi-session-runtime-host-contract.v1"
    ):
        raise ManagedPiRuntimeError(
            "Session runtime source contract schema is unsupported"
        )
    if (
        contract.get("sourceRepository") != "https://github.com/7155/pi.git"
        or contract.get("sourcePackage") != "@earendil-works/pi-rag-ime-runtime-host"
        or contract.get("protocolVersion") != "2"
    ):
        raise ManagedPiRuntimeError(
            "Session runtime source provenance is unsupported"
        )
    methods = contract.get("requiredMethods")
    if methods != [
        "session.open",
        "session.prompt",
        "session.steer",
        "session.debug.context",
        "session.abort",
        "session.snapshot",
    ]:
        raise ManagedPiRuntimeError(
            "Session runtime source contract methods are incomplete"
        )
    minimum_commit = str(contract.get("minimumHandlersCommit") or "").strip()
    if len(minimum_commit) != 40 or any(
        character not in "0123456789abcdef" for character in minimum_commit
    ):
        raise ManagedPiRuntimeError(
            "Session runtime minimum handlers commit is invalid"
        )
    if minimum_commit != REQUIRED_PI_RUNTIME_BASE_COMMIT:
        raise ManagedPiRuntimeError(
            "Session runtime minimum handlers commit is not the reviewed baseline"
        )
    # The product Pi fork can be rebased onto a newer upstream history. The
    # baseline commit identifies the reviewed capability contract; current
    # source is proven below by the complete handler map and exact markers,
    # while the payload records its real HEAD plus dirty-tree digest.
    sources = contract.get("handlerSources")
    if not isinstance(sources, dict) or set(sources) != set(
        _SESSION_RUNTIME_SOURCE_KEYS
    ):
        raise ManagedPiRuntimeError(
            "Session runtime handler source map is missing"
        )
    source_texts: dict[str, str] = {}
    for key in _SESSION_RUNTIME_SOURCE_KEYS:
        relative = Path(str(sources.get(key) or ""))
        if not relative.parts or relative.is_absolute() or ".." in relative.parts:
            raise ManagedPiRuntimeError(
                "Session runtime handler source path is unsafe"
            )
        resolved = (pi_root / relative).resolve()
        if not resolved.is_relative_to(pi_root.resolve()):
            raise ManagedPiRuntimeError(
                "Session runtime handler source escaped the Pi worktree"
            )
        try:
            source_texts[key] = resolved.read_text(encoding="utf-8")
        except OSError as exc:
            raise ManagedPiRuntimeError(
                f"Session runtime handler source is missing: {exc}"
            ) from exc
    required_markers = contract.get("requiredSourceMarkers")
    if not isinstance(required_markers, dict) or set(required_markers) != set(
        _SESSION_RUNTIME_SOURCE_KEYS
    ):
        raise ManagedPiRuntimeError(
            "Session runtime source marker map is incomplete"
        )
    for key in _SESSION_RUNTIME_SOURCE_KEYS:
        markers = required_markers.get(key)
        if not isinstance(markers, list) or not markers:
            raise ManagedPiRuntimeError(
                f"Session runtime source markers are missing: {key}"
            )
        for marker in markers:
            if not isinstance(marker, str) or not marker or marker not in source_texts[key]:
                raise ManagedPiRuntimeError(
                    f"Pi Runtime Host source marker is missing: {key}:{marker}"
                )
    protocol_source = source_texts["protocol"]
    runtime_host_source = source_texts["runtimeHost"]
    for method in methods:
        if f'| "{method}"' not in protocol_source or f'case "{method}"' not in runtime_host_source:
            raise ManagedPiRuntimeError(f"Pi Runtime Host does not implement {method}")
    return contract, hashlib.sha256(contract_bytes).hexdigest()


def _hash_tree(path: Path) -> bytes:
    digest = hashlib.sha256()
    if not path.is_dir():
        return digest.digest()
    for item in sorted(candidate for candidate in path.rglob("*") if candidate.is_file()):
        digest.update(item.relative_to(path).as_posix().encode("utf-8"))
        digest.update(item.read_bytes())
    return digest.digest()


def _product_skill_dirs(
    skills_root: Path,
    *,
    allowed_support_dirs: frozenset[str] = BUNDLED_SKILL_SUPPORT_DIRS,
) -> tuple[Path, ...]:
    if not skills_root.is_dir():
        return ()
    skills: list[Path] = []
    for item in sorted(skills_root.iterdir(), key=lambda candidate: candidate.name):
        if not item.is_dir():
            continue
        if (item / "SKILL.md").is_file():
            skills.append(item)
            continue
        if item.name in allowed_support_dirs:
            continue
        raise ManagedPiRuntimeError(
            "bundled Skill discovery failed: "
            f"direct child directory {item} is missing SKILL.md"
        )
    return tuple(skills)


def _skill_frontmatter(skill_file: Path, *, source: str) -> dict[str, object]:
    try:
        content = skill_file.read_text(encoding="utf-8")
        parts = content.split("---", 2)
        if len(parts) != 3 or parts[0].strip():
            raise ValueError("missing leading YAML frontmatter")
        value = yaml.safe_load(parts[1])
    except (OSError, UnicodeError, yaml.YAMLError, ValueError) as error:
        raise ManagedPiRuntimeError(
            f"{source} Skill frontmatter is invalid at {skill_file}: {error}"
        ) from error
    if not isinstance(value, dict):
        raise ManagedPiRuntimeError(
            f"{source} Skill frontmatter must be an object at {skill_file}"
        )
    name = value.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ManagedPiRuntimeError(
            f"{source} Skill frontmatter has no non-empty name at {skill_file}"
        )
    if name.strip() != skill_file.parent.name:
        raise ManagedPiRuntimeError(
            f"{source} Skill name {name!r} does not match directory "
            f"{skill_file.parent.name!r} at {skill_file}"
        )
    return value


def _discover_skill_files(paths: tuple[Path, ...], *, source: str) -> tuple[Path, ...]:
    discovered: dict[Path, Path] = {}
    for configured_path in paths:
        path = configured_path.expanduser()
        if not path.exists():
            continue
        candidates: tuple[Path, ...]
        if path.is_file():
            candidates = (path,) if path.name == "SKILL.md" else ()
        elif (path / "SKILL.md").is_file():
            candidates = (path / "SKILL.md",)
        else:
            candidates = tuple(sorted(path.rglob("SKILL.md")))
        for candidate in candidates:
            try:
                canonical = candidate.resolve(strict=True)
            except OSError as error:
                raise ManagedPiRuntimeError(
                    f"{source} Skill path cannot be resolved: {candidate}: {error}"
                ) from error
            discovered.setdefault(canonical, candidate)
    return tuple(discovered[key] for key in sorted(discovered, key=lambda item: item.as_posix()))


def _validated_collision_policy(value: object) -> dict[str, frozenset[str]]:
    if not isinstance(value, dict) or value.get("default") != "reject":
        raise ManagedPiRuntimeError(
            "Skill collisionPolicy.default must be the fail-closed value 'reject'"
        )
    bundled_wins = value.get("bundledWins")
    if not isinstance(bundled_wins, dict):
        raise ManagedPiRuntimeError("Skill collisionPolicy.bundledWins must be an object")
    unknown_sources = set(bundled_wins) - {"configured", "pi-installed"}
    if unknown_sources:
        raise ManagedPiRuntimeError(
            "Skill collisionPolicy.bundledWins has unknown sources: "
            + ", ".join(sorted(unknown_sources))
        )
    result: dict[str, frozenset[str]] = {}
    for source in ("configured", "pi-installed"):
        names = bundled_wins.get(source, [])
        if (
            not isinstance(names, list)
            or any(not isinstance(name, str) or not name.strip() for name in names)
            or len(names) != len(set(names))
        ):
            raise ManagedPiRuntimeError(
                f"Skill collisionPolicy.bundledWins.{source} must be a unique string array"
            )
        result[source] = frozenset(names)
    return result


def _resolve_skill_source_collisions(
    *,
    bundled: tuple[Path, ...],
    configured: tuple[Path, ...],
    pi_installed: tuple[Path, ...],
    collision_policy: object,
) -> dict[str, dict[str, str]]:
    bundled_wins = _validated_collision_policy(collision_policy)
    candidates: dict[str, list[dict[str, str]]] = {}
    source_paths = {
        "bundled": bundled,
        "configured": configured,
        "pi-installed": pi_installed,
    }
    for source in SKILL_SOURCE_KINDS:
        files = _discover_skill_files(source_paths[source], source=source)
        for skill_file in files:
            frontmatter = _skill_frontmatter(skill_file, source=source)
            name = str(frontmatter["name"]).strip()
            entry = {
                "name": name,
                "source": source,
                "path": str(skill_file.resolve()),
            }
            candidates.setdefault(name, []).append(entry)

    resolved: dict[str, dict[str, str]] = {}
    for name in sorted(candidates):
        entries = candidates[name]
        if len(entries) == 1:
            resolved[name] = entries[0]
            continue
        bundled_entries = [entry for entry in entries if entry["source"] == "bundled"]
        non_bundled_sources = {entry["source"] for entry in entries if entry["source"] != "bundled"}
        bundled_is_explicit_winner = (
            len(bundled_entries) == 1
            and len(entries) == len({entry["source"] for entry in entries})
            and all(name in bundled_wins[source] for source in non_bundled_sources)
        )
        if bundled_is_explicit_winner:
            resolved[name] = bundled_entries[0]
            continue
        diagnostics = "; ".join(
            f"{entry['source']}={entry['path']}" for entry in entries
        )
        raise ManagedPiRuntimeError(
            f"unresolved Skill name collision for {name!r}: {diagnostics}; "
            "collisionPolicy.default=reject"
        )
    return resolved


def _compact_card_length(card: dict[str, object]) -> int:
    return len(json.dumps(card, ensure_ascii=False, separators=(",", ":")))


def _validated_skill_routing_catalog(
    cards_path: Path,
    skills_root: Path,
) -> dict[str, object]:
    try:
        catalog = json.loads(cards_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ManagedPiRuntimeError(
            f"Skill routing card catalog is invalid at {cards_path}: {error}"
        ) from error
    if not isinstance(catalog, dict) or catalog.get("schemaVersion") != (
        "rag-ime.skill-routing-card-catalog.v1"
    ):
        raise ManagedPiRuntimeError("Skill routing card catalog has an invalid schemaVersion")
    cards = catalog.get("cards")
    if not isinstance(cards, list):
        raise ManagedPiRuntimeError("Skill routing card catalog must contain cards[]")

    cards_by_name: dict[str, dict[str, object]] = {}
    for index, value in enumerate(cards):
        if not isinstance(value, dict):
            raise ManagedPiRuntimeError(f"Skill routing card cards[{index}] must be an object")
        name = value.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ManagedPiRuntimeError(
                f"Skill routing card cards[{index}].name must be non-empty"
            )
        if name in cards_by_name:
            raise ManagedPiRuntimeError(f"duplicate Skill routing card: {name}")
        unexpected = set(value) - set(ROUTING_CARD_FIELDS)
        if unexpected:
            raise ManagedPiRuntimeError(
                f"Skill routing card {name!r} has unsupported fields: "
                + ", ".join(sorted(unexpected))
            )
        when = value.get("when")
        does = value.get("does")
        not_for = value.get("notFor")
        if (
            not isinstance(when, list)
            or not when
            or any(not isinstance(item, str) or not item.strip() for item in when)
            or not isinstance(does, str)
            or not does.strip()
            or (
                not_for is not None
                and (
                    not isinstance(not_for, list)
                    or not not_for
                    or any(
                        not isinstance(item, str) or not item.strip()
                        for item in not_for
                    )
                )
            )
            or any(
                field in value
                and (
                    not isinstance(value[field], str)
                    or not str(value[field]).strip()
                )
                for field in ("input", "output")
            )
        ):
            raise ManagedPiRuntimeError(
                f"Skill routing card {name!r} has invalid routing fields"
            )
        if _compact_card_length(value) > MAX_ROUTING_CARD_CHARS:
            raise ManagedPiRuntimeError(
                f"Skill routing card exceeds {MAX_ROUTING_CARD_CHARS} characters: {name}"
            )
        serialized = json.dumps(value, ensure_ascii=False)
        if any(
            marker in serialized
            for marker in (
                "file://",
                str(ROOT),
                str(skills_root.resolve()),
                "/Users/",
                "/Volumes/",
                "/home/",
                "\\Users\\",
            )
        ):
            raise ManagedPiRuntimeError(
                f"Skill routing card leaks a managed filesystem path: {name}"
            )
        cards_by_name[name] = value

    product_skills = _product_skill_dirs(skills_root)
    product_names = {skill.name for skill in product_skills}
    for name in sorted(PROJECT_ROUTING_SKILLS):
        if name not in product_names:
            raise ManagedPiRuntimeError(
                f"project routing card source Skill is missing: bundled={name}"
            )
        source = _skill_frontmatter(skills_root / name / "SKILL.md", source="bundled")
        try:
            projection = {field: source[field] for field in ROUTING_CARD_FIELDS}
        except KeyError as error:
            raise ManagedPiRuntimeError(
                f"bundled Skill {name!r} is missing routing field {error.args[0]!r}"
            ) from error
        card = cards_by_name.get(name)
        if card != projection:
            raise ManagedPiRuntimeError(
                f"project routing card drift for {name!r}: "
                "card must exactly project bundled SKILL.md frontmatter"
            )

    collision_policy = catalog.get("collisionPolicy")
    bundled_wins = _validated_collision_policy(collision_policy)
    for source, names in bundled_wins.items():
        unknown_names = names - product_names
        if unknown_names:
            raise ManagedPiRuntimeError(
                f"Skill collisionPolicy.bundledWins.{source} references "
                "unknown bundled Skills: "
                + ", ".join(sorted(unknown_names))
            )
    coverage = catalog.get("coverage")
    if not isinstance(coverage, dict):
        raise ManagedPiRuntimeError("Skill routing card coverage must be an object")
    multiplicity = coverage.get("duplicateSourceMultiplicity")
    if not isinstance(multiplicity, dict):
        raise ManagedPiRuntimeError(
            "Skill routing card coverage.duplicateSourceMultiplicity must be an object"
        )
    for name, count in multiplicity.items():
        if (
            not isinstance(name, str)
            or not name.strip()
            or not isinstance(count, int)
            or count < 2
        ):
            raise ManagedPiRuntimeError(
                f"invalid Skill routing source multiplicity for {name!r}: {count!r}"
            )
    represented_entries = len(cards) + sum(
        count - 1 for count in multiplicity.values()
    )
    derived_scope = {
        "bundledSkillEntries": len(product_skills),
        "projectedBundledCards": len(PROJECT_ROUTING_SKILLS),
        "canonicalCards": len(cards),
    }
    if catalog.get("scope") != derived_scope:
        raise ManagedPiRuntimeError(
            f"Skill routing card scope drift: expected {derived_scope!r}"
        )
    if coverage.get("representedSourceEntries") != represented_entries:
        raise ManagedPiRuntimeError(
            "Skill routing card coverage drift: "
            f"expected representedSourceEntries={represented_entries}"
        )
    return catalog


def _copy_product_skills(source_root: Path, runtime_root: Path) -> tuple[str, ...]:
    runtime_root.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    for skill in _product_skill_dirs(source_root):
        shutil.copytree(skill, runtime_root / skill.name, dirs_exist_ok=True)
        copied.append(skill.name)
    return tuple(copied)


def _runtime_host_banner(
    skills_root: Path,
    collision_policy: object | None = None,
) -> str:
    skill_names = [item.name for item in _product_skill_dirs(skills_root)]
    if collision_policy is None:
        collision_policy = json.loads(
            SKILL_ROUTING_CARDS.read_text(encoding="utf-8")
        ).get("collisionPolicy")
    bundled_wins = _validated_collision_policy(collision_policy)
    policy_json = {
        "default": "reject",
        "bundledWins": {
            source: sorted(names) for source, names in bundled_wins.items()
        },
    }
    return (
        'import { createRequire as __createRequire } from "node:module"; '
        'import { basename as __basename, delimiter as __pathDelimiter, dirname as __dirname, join as __join, resolve as __resolve } from "node:path"; '
        'import { existsSync as __existsSync, readdirSync as __readdirSync, readFileSync as __readFileSync, realpathSync as __realpathSync, statSync as __statSync } from "node:fs"; '
        'import { homedir as __homedir } from "node:os"; '
        'import { fileURLToPath as __fileURLToPath } from "node:url"; '
        'const require = __createRequire(import.meta.url); '
        f'const __ragImeSkillNames = {json.dumps(skill_names, ensure_ascii=True)}; '
        f'const __ragImeSkillCollisionPolicy = {json.dumps(policy_json, ensure_ascii=True)}; '
        'const __ragImeRuntimeDir = __dirname(__fileURLToPath(import.meta.url)); '
        'const __ragImeSkillPaths = __ragImeSkillNames.map((name) => __join(__ragImeRuntimeDir, "skills", name)); '
        'const __ragImeRoutingCards = __join(__ragImeRuntimeDir, "skill-routing-cards.json"); '
        'const __ragImeConfiguredSkills = (process.env.RAG_IME_PI_SKILL_PATHS || "").split(__pathDelimiter).filter(Boolean); '
        'const __ragImePiAgentDir = __resolve(process.env.PI_CODING_AGENT_DIR || __join(__homedir(), ".pi", "agent")); '
        'const __ragImePiInstalledSkills = (process.env.RAG_IME_PI_USER_SKILL_PATHS || __join(__ragImePiAgentDir, "skills")).split(__pathDelimiter).filter(Boolean); '
        'const __ragImeFindSkillFiles = (path) => { if (!__existsSync(path)) return []; const stat = __statSync(path); if (!stat.isDirectory()) return path.endsWith("SKILL.md") ? [path] : []; if (__existsSync(__join(path, "SKILL.md"))) return [__join(path, "SKILL.md")]; return __readdirSync(path, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name)).flatMap((entry) => entry.isDirectory() ? __ragImeFindSkillFiles(__join(path, entry.name)) : []); }; '
        'const __ragImeSourcePaths = { bundled: __ragImeSkillPaths, configured: __ragImeConfiguredSkills, "pi-installed": __ragImePiInstalledSkills }; '
        'const __ragImeCandidates = new Map(); '
        'for (const [source, paths] of Object.entries(__ragImeSourcePaths)) for (const path of paths.flatMap(__ragImeFindSkillFiles)) { const canonical = __realpathSync(path); const body = __readFileSync(canonical, "utf8"); const frontmatter = /^---\\s*\\r?\\n([\\s\\S]*?)\\r?\\n---(?:\\s*\\r?\\n|\\s*$)/.exec(body); const match = frontmatter && /^name:\\s*["\']?([^"\'#\\r\\n]+)["\']?\\s*$/m.exec(frontmatter[1]); if (!match) throw new Error(`Invalid ${source} Skill frontmatter at ${canonical}: missing name`); const name = match[1].trim(); if (name !== __basename(__dirname(canonical))) throw new Error(`Invalid ${source} Skill frontmatter at ${canonical}: name "${name}" does not match directory`); const entries = __ragImeCandidates.get(name) || []; if (!entries.some((entry) => entry.path === canonical)) entries.push({ name, source, path: canonical }); __ragImeCandidates.set(name, entries); } '
        'for (const [name, entries] of [...__ragImeCandidates].sort(([a], [b]) => a.localeCompare(b))) { if (entries.length < 2) continue; const bundled = entries.filter((entry) => entry.source === "bundled"); const otherSources = new Set(entries.filter((entry) => entry.source !== "bundled").map((entry) => entry.source)); const explicitBundledWinner = bundled.length === 1 && entries.length === new Set(entries.map((entry) => entry.source)).size && [...otherSources].every((source) => (__ragImeSkillCollisionPolicy.bundledWins[source] || []).includes(name)); if (!explicitBundledWinner) throw new Error(`Unresolved Skill name collision for "${name}": ${entries.map((entry) => `${entry.source}=${entry.path}`).join("; ")}; collisionPolicy.default=reject`); } '
        'process.env.RAG_IME_PI_SKILL_PATHS = '
        '[...__ragImeSkillPaths, ...__ragImeConfiguredSkills].filter(Boolean).join(__pathDelimiter); '
        'process.env.RAG_IME_PI_SKILL_ROUTING_CARDS = '
        'process.env.RAG_IME_PI_SKILL_ROUTING_CARDS || __ragImeRoutingCards;'
    )


def _bundle_oauth_runtime_modules(
    *,
    esbuild: Path,
    pi_root: Path,
    runtime_dir: Path,
) -> None:
    """Package the OAuth modules intentionally left opaque to Pi's main bundle.

    Pi keeps these modules behind variable dynamic imports so browser builds do
    not absorb Node-only callback servers and PKCE code. The managed Runtime
    Host is a self-contained Node payload, so its packager must preserve those
    runtime-loaded files next to ``cli.mjs``. Bundling each module independently
    keeps the browser boundary intact while making the installed Host complete.
    """

    for output_name, (relative_source, _export_name) in _OAUTH_RUNTIME_MODULES.items():
        source = pi_root / relative_source
        if not source.is_file() or source.is_symlink():
            raise ManagedPiRuntimeError(
                f"managed Pi OAuth runtime source is missing: {relative_source}"
            )
        output = runtime_dir / output_name
        _run(
            [
                str(esbuild),
                str(source),
                "--bundle",
                "--platform=node",
                "--format=esm",
                "--target=node22",
                f"--outfile={output}",
                (
                    '--banner:js=import { createRequire as __createRequire } '
                    'from "node:module"; const require = __createRequire(import.meta.url);'
                ),
            ],
            cwd=pi_root,
        )
        output.chmod(0o644)


def _smoke_oauth_runtime_modules(node: Path, runtime_dir: Path) -> dict[str, object]:
    module_specs = [
        {
            "url": (runtime_dir / output_name).as_uri(),
            "exportName": export_name,
        }
        for output_name, (_relative_source, export_name) in _OAUTH_RUNTIME_MODULES.items()
    ]
    probe = (
        f"const specs = {json.dumps(module_specs, separators=(',', ':'))};"
        "const loaded = new Map();"
        "for (const spec of specs) {"
        " const module = await import(spec.url);"
        " if (!(spec.exportName in module))"
        "  throw new Error(`missing OAuth export ${spec.exportName}`);"
        " loaded.set(spec.exportName, module[spec.exportName]);"
        "}"
        "const codex = loaded.get('openaiCodexOAuth');"
        "const resolved = await codex.toAuth({"
        " type:'oauth',access:'managed-runtime-smoke',refresh:'unused',"
        " expires:Date.now()+60000,accountId:'smoke'"
        "});"
        "if (resolved.apiKey !== 'managed-runtime-smoke')"
        " throw new Error('OpenAI Codex OAuth derivation failed');"
        "process.stdout.write(JSON.stringify({ok:true,moduleCount:specs.length}));"
    )
    completed = subprocess.run(
        [str(node), "--input-type=module", "-e", probe],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=30,
    )
    try:
        response = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ManagedPiRuntimeError(
            "managed Pi OAuth runtime smoke returned invalid JSON"
        ) from exc
    if response != {"ok": True, "moduleCount": len(_OAUTH_RUNTIME_MODULES)}:
        raise ManagedPiRuntimeError("managed Pi OAuth runtime smoke did not load every module")
    return response


def _smoke_runtime(node: Path, entrypoint: Path) -> dict[str, object]:
    request = {
        "protocolVersion": "2",
        "id": "managed-runtime-build-smoke",
        "method": "hello",
        "params": {},
    }
    with tempfile.TemporaryDirectory(prefix="rag-ime-pi-runtime-smoke-") as app_support:
        environment = dict(os.environ)
        environment.update(
            {
                "RAG_IME_APP_SUPPORT_DIR": app_support,
                "RAG_IME_PLUGIN_APPROVAL_TOKEN": "managed-runtime-build-smoke",
            }
        )
        completed = subprocess.run(
            [str(node), str(entrypoint)],
            input=json.dumps(request, separators=(",", ":")) + "\n",
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
            env=environment,
        )
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if len(lines) != 1:
        raise ManagedPiRuntimeError("managed Pi Runtime Host smoke test returned an invalid response")
    response = json.loads(lines[0])
    result = response.get("result") if isinstance(response, dict) else None
    capabilities = result.get("capabilities") if isinstance(result, dict) else None
    if (
        not isinstance(response, dict)
        or not response.get("ok")
        or not isinstance(result, dict)
        or result.get("protocolVersion") != "2"
        or not isinstance(capabilities, dict)
        or not capabilities.get("multiSession")
    ):
        raise ManagedPiRuntimeError("managed Pi Runtime Host smoke test did not negotiate protocol v2")
    return response


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build a verified, SDK-backed Pi Runtime Host v2 payload without registry access"
    )
    parser.add_argument(
        "--pi-worktree",
        default=str(_default_pi_worktree()),
    )
    parser.add_argument("--output", default="")
    parser.add_argument(
        "--node",
        default=_default_node(),
        help="Relocatable Node 22+ binary copied into the managed payload",
    )
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--skip-smoke", action="store_true")
    args = parser.parse_args(argv)

    pi_root = Path(args.pi_worktree).expanduser().resolve()
    node = Path(args.node).expanduser().resolve() if args.node else Path()
    package_root = pi_root / "packages" / "rag-ime-runtime-host"
    package_json = pi_root / "packages" / "coding-agent" / "package.json"
    esbuild = pi_root / "node_modules" / ".bin" / "esbuild"
    if not package_root.is_dir() or not package_json.is_file() or not esbuild.is_file():
        print("managed Pi runtime build failed: Pi worktree is incomplete", file=sys.stderr)
        return 1
    if not node.is_file():
        print("managed Pi runtime build failed: Node executable is missing", file=sys.stderr)
        return 1
    node_relocation_error = _node_relocation_error(node)
    if node_relocation_error:
        print(
            "managed Pi runtime build failed: "
            f"{node_relocation_error}; set RAG_IME_MANAGED_NODE to a standalone Node binary",
            file=sys.stderr,
        )
        return 1

    try:
        pi_version = str(json.loads(package_json.read_text(encoding="utf-8"))["version"])
        session_runtime_contract, session_runtime_contract_sha256 = _verified_session_runtime_contract(
            pi_root
        )
        source_commit, dirty_digest = _source_revision(pi_root)
        product_commit = _run(["git", "rev-parse", "HEAD"], cwd=ROOT)
        product_commit_ms = int(
            _run(["git", "show", "-s", "--format=%ct", product_commit], cwd=ROOT)
        ) * 1_000
        provider_bridge_source = ROOT / "rag_ime" / "node" / "pi_provider_bridge_bundled.ts"
        product_skills = ROOT / "integrations" / "pi" / "skills"
        skill_routing_cards = SKILL_ROUTING_CARDS
        routing_catalog = _validated_skill_routing_catalog(
            skill_routing_cards,
            product_skills,
        )
        routing_catalog_bytes = (
            json.dumps(routing_catalog, ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8")
        packager_digest = hashlib.sha256(
            provider_bridge_source.read_bytes()
            + Path(__file__).read_bytes()
            + _hash_tree(product_skills)
            + routing_catalog_bytes
            + SESSION_RUNTIME_CONTRACT.read_bytes()
            + json.dumps(CONTROL_TOOL_IDS, separators=(",", ":")).encode("utf-8")
            + product_commit.encode("ascii")
        ).hexdigest()[:10]
        commit_prefix = source_commit.split("+", 1)[0][:12]
        dirty_suffix = f"-d{dirty_digest[:8]}" if dirty_digest else ""
        runtime_version = f"pi-{pi_version}-{commit_prefix}{dirty_suffix}-raghost-{packager_digest}"
        destination = (
            Path(args.output).expanduser().resolve()
            if args.output
            else ROOT / "build" / "managed-pi-runtime" / runtime_version
        )
        if destination.exists():
            if not args.force:
                raise ManagedPiRuntimeError(f"output already exists: {destination}")
            shutil.rmtree(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        staging = destination.parent / f".{destination.name}.staging-{uuid.uuid4().hex}"
        staging.mkdir(mode=0o700)
        try:
            runtime_dir = staging / "runtime-host"
            bin_dir = staging / "bin"
            runtime_dir.mkdir(mode=0o700)
            bin_dir.mkdir(mode=0o700)
            _copy_product_skills(product_skills, runtime_dir / "skills")
            (runtime_dir / "skill-routing-cards.json").write_bytes(
                routing_catalog_bytes
            )
            shutil.copy2(
                SESSION_RUNTIME_CONTRACT,
                runtime_dir / "session-runtime-host-contract.json",
            )
            bundled_entrypoint = runtime_dir / "cli.mjs"
            _run(
                [
                    str(esbuild),
                    str(package_root / "src" / "cli.ts"),
                    "--bundle",
                    "--platform=node",
                    "--format=esm",
                    "--target=node22",
                    f"--outfile={bundled_entrypoint}",
                    f'--banner:js={_runtime_host_banner(product_skills, routing_catalog["collisionPolicy"])}',
                ],
                cwd=pi_root,
            )
            bundled_entrypoint.chmod(0o755)
            provider_bridge = runtime_dir / "provider-bridge.mjs"
            _run(
                [
                    str(esbuild),
                    str(provider_bridge_source),
                    "--bundle",
                    "--platform=node",
                    "--format=esm",
                    "--target=node22",
                    f"--outfile={provider_bridge}",
                    f"--alias:rag-ime-pi-auth-storage={pi_root / 'packages' / 'coding-agent' / 'src' / 'core' / 'auth-storage.ts'}",
                    f"--alias:rag-ime-pi-model-runtime={pi_root / 'packages' / 'coding-agent' / 'src' / 'core' / 'model-runtime.ts'}",
                    f"--alias:rag-ime-pi-openai-codex-oauth={pi_root / 'packages' / 'ai' / 'src' / 'auth' / 'oauth' / 'openai-codex.ts'}",
                    '--banner:js=import { createRequire as __createRequire } from "node:module"; const require = __createRequire(import.meta.url);',
                ],
                cwd=pi_root,
            )
            provider_bridge.chmod(0o755)
            _bundle_oauth_runtime_modules(
                esbuild=esbuild,
                pi_root=pi_root,
                runtime_dir=runtime_dir,
            )
            packaged_node = bin_dir / "node"
            shutil.copy2(node, packaged_node)
            packaged_node.chmod(0o755)
            placeholder = runtime_dir / "extension-placeholder.mjs"
            placeholder.write_text(
                "// Protocol v2 loads product tools and managed plugins through the Runtime Host.\n"
                "export default function managedRuntimeV2Placeholder() {}\n",
                encoding="ascii",
            )
            if args.skip_smoke:
                smoke: dict[str, object] = {}
                oauth_smoke: dict[str, object] = {}
            else:
                oauth_smoke = _smoke_oauth_runtime_modules(packaged_node, runtime_dir)
                smoke = _smoke_runtime(packaged_node, bundled_entrypoint)
            manifest = build_managed_pi_runtime_manifest(
                staging,
                runtime_version=runtime_version,
                pi_version=pi_version,
                launch_kind="node",
                pi_entrypoint="runtime-host/cli.mjs",
                node_entrypoint="bin/node",
                extension_entrypoint="runtime-host/extension-placeholder.mjs",
                tools=CONTROL_TOOL_IDS,
                source_repository=str(session_runtime_contract["sourceRepository"]),
                source_commit=source_commit,
                source_package=str(session_runtime_contract["sourcePackage"]),
                protocol_version="2",
                runtime_methods=tuple(session_runtime_contract["requiredMethods"]),
                source_contract_sha256=session_runtime_contract_sha256,
                handlers_commit=source_commit.split("+", 1)[0],
            )
            manifest["source"] = {
                **dict(manifest["source"]),
                "productRepository": str(ROOT),
                "productCommit": product_commit,
            }
            # The runtime version is content-addressed. Keep its manifest
            # deterministic so reinstalling the same product commit is an
            # idempotent verification instead of a version collision.
            manifest["createdAtMs"] = product_commit_ms
            write_managed_pi_runtime_manifest(staging / MANIFEST_NAME, manifest)
            os.replace(staging, destination)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
    except (KeyError, json.JSONDecodeError, OSError, subprocess.SubprocessError, ManagedPiRuntimeError) as exc:
        print(f"managed Pi runtime build failed: {exc}", file=sys.stderr)
        return 1

    result = {
        "ok": True,
        "runtimeVersion": runtime_version,
        "piVersion": pi_version,
        "protocolVersion": "2",
        "sourceCommit": source_commit,
        "sourceContractSha256": session_runtime_contract_sha256,
        "runtimeMethods": session_runtime_contract["requiredMethods"],
        "productCommit": product_commit,
        "payload": str(destination),
        "manifest": str(destination / MANIFEST_NAME),
        "fileCount": len(manifest["files"]),
        "smoke": smoke.get("result", {}) if smoke else {"skipped": True},
        "oauthSmoke": oauth_smoke if oauth_smoke else {"skipped": True},
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
