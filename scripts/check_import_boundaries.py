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
    return ""


if __name__ == "__main__":
    raise SystemExit(main())
