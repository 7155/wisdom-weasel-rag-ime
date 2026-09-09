#!/usr/bin/env python3
"""Check new owner boundaries without changing legacy startup-cycle semantics.

All static imports count, including functions, try blocks and TYPE_CHECKING.
Literal importlib/__import__ calls are checked too; computed import targets and
arbitrary import wrappers require review. This is not a Python security sandbox.
"""
from __future__ import annotations

import argparse
import ast
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterator


ENTRY_AND_COMPOSITION = (
    "rag_ime.agent_service",
    "rag_ime.debug_server",
    "rag_ime.cli",
)
OWNER_RULES = {
    "rag_ime.agent_lab": ENTRY_AND_COMPOSITION,
    "rag_ime.knowledge_library": ENTRY_AND_COMPOSITION + ("rag_ime.agent_lab",),
    "rag_ime.db": ENTRY_AND_COMPOSITION + (
        "rag_ime.agent_lab",
        "rag_ime.knowledge_library",
    ),
}


@dataclass(frozen=True)
class OwnerImportViolation:
    path: str
    line: int
    module: str
    imported: str
    reason: str


def _matches(module: str, prefix: str) -> bool:
    return module == prefix or module.startswith(prefix + ".") or module.startswith(prefix + "_")


def _absolute_import(module: str, level: int, package: str) -> str:
    if level == 0:
        return module
    parts = package.split(".")
    keep = len(parts) - level + 1
    if keep <= 0:
        return ""
    return ".".join(parts[:keep] + ([module] if module else []))


def _literal_string(node: ast.AST | None) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _import_targets(tree: ast.Module, package: str) -> Iterator[tuple[int, str]]:
    importlib_names = {"importlib"}
    import_module_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "importlib":
                    importlib_names.add(alias.asname or alias.name)
                yield node.lineno, alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module == "importlib":
                import_module_names.update(
                    alias.asname or alias.name
                    for alias in node.names if alias.name == "import_module"
                )
            base = _absolute_import(node.module or "", node.level, package)
            if base:
                yield node.lineno, base
                for alias in node.names:
                    if alias.name != "*":
                        # Parent imports are dependency edges too:
                        # `from .. import agent_service` must not bypass a rule.
                        yield node.lineno, base + "." + alias.name

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        is_import_module = (
            isinstance(fn, ast.Attribute) and fn.attr == "import_module"
            and isinstance(fn.value, ast.Name) and fn.value.id in importlib_names
        ) or (isinstance(fn, ast.Name) and fn.id in import_module_names)
        is_builtin_import = isinstance(fn, ast.Name) and fn.id == "__import__"
        if not (is_import_module or is_builtin_import):
            continue
        name_node = node.args[0] if node.args else next(
            (kw.value for kw in node.keywords if kw.arg == "name"), None
        )
        target = _literal_string(name_node)
        if not target:
            continue
        if target.startswith("."):
            if not is_import_module:
                continue
            package_node = node.args[1] if len(node.args) > 1 else next(
                (kw.value for kw in node.keywords if kw.arg == "package"), None
            )
            explicit_package = _literal_string(package_node)
            if not explicit_package:
                continue
            level = len(target) - len(target.lstrip("."))
            target = _absolute_import(target.lstrip("."), level, explicit_package)
        if target:
            yield node.lineno, target


def check_owner_boundaries(root: Path) -> list[OwnerImportViolation]:
    root = root.resolve()
    violations: list[OwnerImportViolation] = []
    seen: set[tuple[str, int, str]] = set()
    for owner, forbidden in OWNER_RULES.items():
        directory = root.joinpath(*owner.split("."))
        for path in sorted(directory.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            relative = path.relative_to(root)
            parts = list(relative.with_suffix("").parts)
            if parts[-1] == "__init__":
                parts.pop()
                package = ".".join(parts)
            else:
                package = ".".join(parts[:-1])
            module = ".".join(parts)
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(relative))
            for line, imported in _import_targets(tree, package):
                for prefix in forbidden:
                    key = (relative.as_posix(), line, prefix)
                    if _matches(imported, prefix) and key not in seen:
                        seen.add(key)
                        violations.append(OwnerImportViolation(
                            path=relative.as_posix(), line=line, module=module,
                            imported=imported,
                            reason=f"{owner} must not depend on {prefix}",
                        ))
    return sorted(violations, key=lambda item: (item.path, item.line, item.imported))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="Full repository root.")
    parser.add_argument("--json", action="store_true", help="Emit a machine-readable report.")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    missing = [owner for owner in OWNER_RULES if not root.joinpath(*owner.split(".")).is_dir()]
    # A partial checkout is not evidence that all boundaries passed.
    violations = check_owner_boundaries(root) if not missing else []
    report = {
        "schemaVersion": "paw.owner-boundaries.v1",
        "checkedOwners": sorted(OWNER_RULES),
        "missingOwners": missing,
        "violationCount": len(violations),
        "violations": [asdict(item) for item in violations],
        "ok": not missing and not violations,
    }
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    elif missing:
        print("Missing owner directories: " + ", ".join(missing))
    elif violations:
        for item in violations:
            print(f"{item.path}:{item.line}: {item.reason} ({item.imported})")
    else:
        print("Agent Lab, Knowledge and database owner boundaries OK")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
