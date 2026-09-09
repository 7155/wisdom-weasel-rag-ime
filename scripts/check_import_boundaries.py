#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


PACKAGE_RULES = {
    "rag_ime.contracts": (
        "rag_ime.sidecar",
        "rag_ime.prediction",
        "rag_ime.providers",
        "rag_ime.memory",
        "rag_ime.ops",
        "rag_ime.debug_tools",
        "rag_ime.active_rag",
        "rag_ime.debug_server",
        "rag_ime.rime_sidecar",
    ),
    "rag_ime.providers": (
        "rag_ime.sidecar",
        "rag_ime.debug_tools",
        "rag_ime.debug_server",
        "rag_ime.active_rag",
    ),
    "rag_ime.memory": (
        "rag_ime.sidecar",
        "rag_ime.debug_tools",
        "rag_ime.debug_server",
        "rag_ime.active_rag",
    ),
    "rag_ime.prediction": (
        "rag_ime.sidecar",
        "rag_ime.debug_tools",
        "rag_ime.debug_server",
        "rag_ime.active_rag",
        "rag_ime.deepseek",
        "rag_ime.sequence_fork",
    ),
    "rag_ime.sidecar": (
        "rag_ime.debug_tools",
        "rag_ime.debug_server",
        "rag_ime.active_rag",
    ),
    "rag_ime.feature_bridge": (
        "rag_ime.debug_tools",
        "rag_ime.debug_server",
    ),
}

# The Agent/Room lane is flat modules rather than packages, so PACKAGE_RULES
# cannot express it. These rules are checked against *module-level* imports
# only: a deferred import inside a function is not a dependency edge, and
# treating it as one would flag the intentional lazy imports that break
# start-up ordering.
#
# Layer order, one direction only:
#   entry (debug_server, cli) -> application (*_service, *_application)
#                             -> domain (agent_room_*, agent_definitions)
ENTRY_MODULES = ("rag_ime.debug_server", "rag_ime.cli")
APPLICATION_SUFFIXES = ("_service", "_application")
DOMAIN_PREFIXES = ("rag_ime.rooms.", "rag_ime.agent_room_", "rag_ime.agent_definitions")

V1_CORE_FILES = (
    Path("rag_ime/contracts/key_policy.py"),
    Path("rag_ime/contracts/source.py"),
    Path("rag_ime/contracts/trace.py"),
    Path("rag_ime/feature_bridge/foreground_acceptance.py"),
    Path("rag_ime/feature_bridge/registry.py"),
    Path("rag_ime/prediction/quality.py"),
    Path("rag_ime/memory/curated_store.py"),
)

FROZEN_REALTIME_PREFIXES = (
    "rag_ime.active_rag",
    "rag_ime.debug_server",
    "rag_ime.deepseek",
    "rag_ime.memory_generator",
    "rag_ime.memory_compiler",
    "rag_ime.sequence_fork",
)


@dataclass(frozen=True)
class ImportViolation:
    path: str
    module: str
    imported: str
    reason: str


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate RAG-IME v1 package import boundaries.")
    parser.add_argument("--root", default=".", help="Repository root, default: current directory.")
    parser.add_argument("--json", action="store_true", help="Print a JSON report instead of text.")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    violations = check_import_boundaries(root)
    report = {
        "schemaVersion": "rag-ime.import-boundaries.v1",
        "root": str(root),
        "checkedPackageRules": sorted(PACKAGE_RULES),
        "checkedV1CoreFiles": [str(path) for path in V1_CORE_FILES],
        "violationCount": len(violations),
        "violations": [violation.__dict__ for violation in violations],
        "ok": not violations,
    }
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        if violations:
            print("Import boundary violations:")
            for violation in violations:
                print(f"- {violation.path}: {violation.module} imports {violation.imported} ({violation.reason})")
        else:
            print("Import boundaries OK")
    return 0 if not violations else 1


def check_import_boundaries(root: Path) -> list[ImportViolation]:
    violations: list[ImportViolation] = []
    for package, forbidden_prefixes in PACKAGE_RULES.items():
        package_path = root / Path(package.replace(".", "/"))
        if not package_path.exists():
            continue
        for path in iter_python_files(package_path):
            module = module_name_for(root, path)
            for imported in imported_modules(path, current_module=module):
                matched = first_matching_prefix(imported, forbidden_prefixes)
                if matched:
                    violations.append(
                        ImportViolation(
                            path=str(path.relative_to(root)),
                            module=module,
                            imported=imported,
                            reason=f"{package} must not import {matched}",
                        )
                    )
    violations.extend(check_flat_layers(root))
    violations.extend(check_module_level_cycles(root))
    violations.extend(check_pi_family_public_contracts(root))
    for relative_path in V1_CORE_FILES:
        path = root / relative_path
        if not path.exists():
            continue
        module = module_name_for(root, path)
        for imported in imported_modules(path, current_module=module):
            matched = first_matching_prefix(imported, FROZEN_REALTIME_PREFIXES)
            if matched:
                violations.append(
                    ImportViolation(
                        path=str(path.relative_to(root)),
                        module=module,
                        imported=imported,
                        reason=f"v1 realtime core must not import frozen lane {matched}",
                    )
                )
    return violations


# Every Pi runtime family module declares its supported cross-module surface in
# a literal `__all__`. v2 once imported 22 private names from v1; moving those
# helpers to shared owners removed the coupling, but merely banning underscores
# still allowed an undeclared public-looking helper to become a new back
# channel. This gate therefore enforces both halves of the contract:
#
# - a private name may never cross a Pi-family module boundary;
# - every imported public name must be listed by the target module's `__all__`.
#
# Module-level and deferred imports are both checked, because hiding an import
# inside a function does not make it a private implementation detail.
PI_FAMILY_MODULES = (
    "rag_ime.pi.config",
    "rag_ime.pi.factory",
    "rag_ime.pi.host_client",
    "rag_ime.pi.runtime",
    "rag_ime.pi.public",
    "rag_ime.pi.values",
    "rag_ime.pi.transcript",
    "rag_ime.pi.transcript_io",
    "rag_ime.pi.event_projection",
    "rag_ime.pi.ui_requests",
    "rag_ime.pi.protocols",
    "rag_ime.agent_runtime_driver",
)


def check_pi_family_public_contracts(root: Path) -> list[ImportViolation]:
    violations: list[ImportViolation] = []
    retired_path = root / "rag_ime/pi_runtime.py"
    if retired_path.exists():
        violations.append(ImportViolation(
            path="rag_ime/pi_runtime.py", module="rag_ime.pi_runtime", imported="",
            reason="The retired Pi v1 adapter must not be restored; use config, factory and Host owners",
        ))
    trees: dict[str, ast.Module] = {}
    public_exports: dict[str, frozenset[str]] = {}

    for module in PI_FAMILY_MODULES:
        path = root / Path(module.replace(".", "/") + ".py")
        if not path.exists():
            violations.append(
                ImportViolation(
                    path=str(path.relative_to(root)),
                    module=module,
                    imported="",
                    reason="Pi family module is missing; update PI_FAMILY_MODULES",
                )
            )
            continue

        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        trees[module] = tree
        exports = _literal_module_exports(tree)
        if exports is None:
            violations.append(
                ImportViolation(
                    path=str(path.relative_to(root)),
                    module=module,
                    imported="",
                    reason=(
                        "Pi family modules must declare a literal __all__ "
                        "public contract"
                    ),
                )
            )
            continue
        public_exports[module] = exports

    for module, tree in trees.items():
        path = root / Path(module.replace(".", "/") + ".py")
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            imported_module = resolve_import_from(node, current_package="rag_ime")
            if imported_module not in PI_FAMILY_MODULES:
                continue
            for alias in node.names:
                if alias.name.startswith("_"):
                    violations.append(
                        ImportViolation(
                            path=str(path.relative_to(root)),
                            module=module,
                            imported=f"{imported_module}.{alias.name}",
                            reason=(
                                "Pi family modules share only the public "
                                "projection contract; private names stay "
                                "module-local"
                            ),
                        )
                    )
                    continue
                target_exports = public_exports.get(imported_module)
                if target_exports is not None and alias.name not in target_exports:
                    violations.append(
                        ImportViolation(
                            path=str(path.relative_to(root)),
                            module=module,
                            imported=f"{imported_module}.{alias.name}",
                            reason=(
                                "Pi family modules may import only names "
                                "declared by the target module's __all__"
                            ),
                        )
                    )

    return violations


def _literal_module_exports(tree: ast.Module) -> frozenset[str] | None:
    """Return a static ``__all__`` contract without importing runtime code."""

    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if not any(
            isinstance(target, ast.Name) and target.id == "__all__"
            for target in targets
        ):
            continue
        value = node.value
        if not isinstance(value, (ast.List, ast.Tuple)):
            return None
        exports: list[str] = []
        for element in value.elts:
            if not isinstance(element, ast.Constant) or not isinstance(element.value, str):
                return None
            exports.append(element.value)
        return frozenset(exports)
    return None


def _matches_any(module: str, prefixes: Iterable[str]) -> bool:
    return any(
        module == prefix
        or module.startswith(f"{prefix}.")
        or module.startswith(prefix)
        for prefix in prefixes
    )


def module_level_imports(root: Path, path: Path) -> list[str]:
    """Imports executed at module import time, excluding deferred ones."""

    module = module_name_for(root, path)
    current_package = module.rpartition(".")[0]
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: list[str] = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            resolved = resolve_import_from(node, current_package=current_package)
            if resolved:
                imports.append(resolved)
    return imports


def _rag_ime_modules(root: Path) -> list[tuple[str, Path]]:
    package_path = root / "rag_ime"
    if not package_path.exists():
        return []
    return [
        (module_name_for(root, path), path)
        for path in iter_python_files(package_path)
    ]


def flat_layer_of(module: str) -> str:
    """Layer of one flat Agent/Room module.

    Application is tested before domain on purpose because Room application
    modules start with the domain prefix; mis-ordering them would let a real
    upward edge pass unnoticed.
    """

    if module in ENTRY_MODULES:
        return "entry"
    if module.endswith(APPLICATION_SUFFIXES):
        return "application"
    if module.startswith(DOMAIN_PREFIXES):
        return "domain"
    return ""


def check_flat_layers(root: Path) -> list[ImportViolation]:
    violations: list[ImportViolation] = []
    for module, path in _rag_ime_modules(root):
        layer = flat_layer_of(module)
        if layer not in {"entry", "domain"}:
            continue
        for imported in module_level_imports(root, path):
            if imported == module:
                continue
            target = flat_layer_of(imported)
            if layer == "domain" and target in {"entry", "application"}:
                reason = f"Room domain must not import the {target} layer"
            elif layer == "entry" and target == "entry":
                reason = "entry points must not depend on each other"
            else:
                continue
            violations.append(
                ImportViolation(
                    path=str(path.relative_to(root)),
                    module=module,
                    imported=imported,
                    reason=f"{reason} ({module} -> {imported})",
                )
            )
    return violations


def check_module_level_cycles(root: Path) -> list[ImportViolation]:
    """A module-level import cycle fails at import time; a lazy one does not."""

    edges: dict[str, set[str]] = {}
    paths: dict[str, Path] = {}
    for module, path in _rag_ime_modules(root):
        paths[module] = path
        edges[module] = set(module_level_imports(root, path))
    colour: dict[str, int] = {}
    violations: list[ImportViolation] = []
    seen: set[tuple[str, ...]] = set()

    def visit(node: str, stack: list[str]) -> None:
        colour[node] = 1
        stack.append(node)
        for target in sorted(edges.get(node, ())):
            if target not in edges:
                continue
            if colour.get(target) == 1:
                cycle = stack[stack.index(target):] + [target]
                key = tuple(sorted(set(cycle)))
                if key not in seen:
                    seen.add(key)
                    violations.append(
                        ImportViolation(
                            path=str(paths[node].relative_to(root)),
                            module=node,
                            imported=target,
                            reason="module-level import cycle: " + " -> ".join(cycle),
                        )
                    )
            elif colour.get(target, 0) == 0:
                visit(target, stack)
        stack.pop()
        colour[node] = 2

    for module in sorted(edges):
        if colour.get(module, 0) == 0:
            visit(module, [])
    return violations


def iter_python_files(package_path: Path) -> Iterable[Path]:
    for path in sorted(package_path.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        yield path


def imported_modules(path: Path, *, current_module: str) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: list[str] = []
    current_package = current_module.rpartition(".")[0]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = resolve_import_from(node, current_package=current_package)
            if module:
                imports.append(module)
    return imports


def resolve_import_from(node: ast.ImportFrom, *, current_package: str) -> str:
    module = node.module or ""
    if node.level <= 0:
        return module
    package_parts = current_package.split(".") if current_package else []
    if node.level > len(package_parts) + 1:
        return module
    base_parts = package_parts[: len(package_parts) - node.level + 1]
    if module:
        base_parts.extend(module.split("."))
    return ".".join(part for part in base_parts if part)


def module_name_for(root: Path, path: Path) -> str:
    relative = path.relative_to(root).with_suffix("")
    parts = [part for part in relative.parts if part != "__init__"]
    return ".".join(parts)


def first_matching_prefix(module: str, prefixes: Iterable[str]) -> str:
    for prefix in prefixes:
        if module == prefix or module.startswith(f"{prefix}."):
            return prefix
        # A lane that was never turned into a package still owns a flat module
        # family: `rag_ime.active_rag_service` belongs to the `rag_ime.active_rag`
        # lane even though no `rag_ime/active_rag/` directory exists. Without
        # this the rule matches nothing and the boundary is silently unenforced
        # rather than merely stale.
        if module.startswith(f"{prefix}_"):
            return prefix
    return ""


if __name__ == "__main__":
    raise SystemExit(main())
