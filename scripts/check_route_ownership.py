#!/usr/bin/env python3
"""Prove every dispatched HTTP route has exactly one owner.

`debug_server` dispatches routes with long if/elif chains while
`control_api/route_policy` declares them for the remote surface. Two owners
means a route can drift: the chain can gain a branch the policy never sees, or
a chain can test the same path twice so the second branch is unreachable.

This gate does not require the two owners to be merged. It enforces the
invariants that make merging them safe, and that a reviewer would otherwise
have to check by eye across two thousand lines:

1. No if/elif chain tests the *same condition* twice. Comparing whole branch
   conditions rather than bare path literals matters: two branches may share a
   prefix and differ by suffix (".../apply" vs ".../rollback"), which is
   correct routing, whereas an identical condition means the later branch can
   never run.
2. The set of dispatched-but-undeclared paths only shrinks. Those are the
   local-only surfaces; the recorded budget stops new ones appearing silently
   while the migration to a single owner proceeds.

Declared-but-not-dispatched is deliberately NOT checked: templated policy
routes are matched by segment parsing inside the chain, never as whole string
literals, so any such check reports dozens of false positives.

Run: python3 scripts/check_route_ownership.py [--json]
"""

from __future__ import annotations

import argparse
import ast
import inspect
import json
import re
import sys
from pathlib import Path


DISPATCH_SOURCE = Path("rag_ime/debug_server.py")
POLICY_SOURCE = Path("rag_ime/control_api/route_policy.py")
TABLE_SOURCE = Path("rag_ime/control_api/route_table.py")

# Chain-dispatched routes with no policy entry: local-only surfaces whose
# exposure is stated nowhere. This is a ratchet, not an approval. Migrating a
# family to the descriptor table lowers it, because a descriptor states
# exposure explicitly; a rise means a route appeared with no policy decision.
UNDECLARED_DISPATCH_BUDGET = 41


def dispatched_routes(root: Path) -> dict[str, list[tuple[str, int]]]:
    """Map path literal -> [(verb handler, line), ...] from the dispatch chains."""

    tree = ast.parse((root / DISPATCH_SOURCE).read_text(encoding="utf-8"))
    found: dict[str, list[tuple[str, int]]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or not node.name.startswith("do_"):
            continue
        for literal in ast.walk(node):
            if (
                isinstance(literal, ast.Constant)
                and isinstance(literal.value, str)
                and literal.value.startswith("/api/")
            ):
                found.setdefault(literal.value, []).append((node.name, literal.lineno))
    return found


def table_routes(root: Path) -> set[str]:
    """Paths owned by the descriptor table rather than by a dispatch chain."""

    table = root / TABLE_SOURCE
    if not table.exists():
        return set()
    tree = ast.parse(table.read_text(encoding="utf-8"))
    paths: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "path":
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                paths.add(node.value.value)
    return paths


def table_route_pairs(root: Path) -> set[tuple[str, str]]:
    """(method, path) pairs owned by the descriptor table, aliases included."""

    table = root / TABLE_SOURCE
    if not table.exists():
        return set()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    try:
        from rag_ime.control_api.route_table import ROUTE_TABLE
    except ImportError:
        return set()
    return set(ROUTE_TABLE)


def declared_routes(root: Path) -> set[str]:
    return set(re.findall(r'"(/api/[^"]*)"', (root / POLICY_SOURCE).read_text(encoding="utf-8")))


def _template_to_regex(template: str) -> re.Pattern[str]:
    return re.compile("^" + re.sub(r"\{[^}]+\}", "[^/]+", re.escape(template).replace(r"\{", "{").replace(r"\}", "}")) + "$")


def _chain_tests(node: ast.If) -> list[ast.If]:
    """Every link of one if/elif chain, following the single-If else branch."""

    links: list[ast.If] = []
    current: ast.If | None = node
    while isinstance(current, ast.If):
        links.append(current)
        rest = current.orelse
        current = rest[0] if len(rest) == 1 and isinstance(rest[0], ast.If) else None
    return links


def shadowed_branches(root: Path) -> list[str]:
    tree = ast.parse((root / DISPATCH_SOURCE).read_text(encoding="utf-8"))
    problems: list[str] = []
    for handler in ast.walk(tree):
        if not isinstance(handler, ast.FunctionDef) or not handler.name.startswith("do_"):
            continue
        seen_chain_heads: set[int] = set()
        for node in ast.walk(handler):
            if not isinstance(node, ast.If) or node.lineno in seen_chain_heads:
                continue
            links = _chain_tests(node)
            for link in links[1:]:
                seen_chain_heads.add(link.lineno)
            first: dict[str, int] = {}
            for link in links:
                source = ast.unparse(link.test)
                if "/api/" not in source:
                    continue
                if source in first:
                    problems.append(
                        f"{handler.name}: condition `{source}` is tested again at "
                        f"line {link.lineno} after line {first[source]}; the later "
                        f"branch is unreachable"
                    )
                else:
                    first[source] = link.lineno
    return problems


def _service_attribute_names(root: Path) -> set[str]:
    """Attributes DebugImeService assigns to itself in __init__.

    Sub-services such as `management` only exist on an instance, so a dotted
    handler cannot be resolved against the class. Reading the assignments lets
    the gate verify the first segment is real instead of skipping the check.
    """

    tree = ast.parse((root / DISPATCH_SOURCE).read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "DebugImeService":
            for assign in ast.walk(node):
                if isinstance(assign, ast.Attribute) and isinstance(assign.value, ast.Name):
                    if assign.value.id == "self" and isinstance(assign.ctx, ast.Store):
                        names.add(assign.attr)
    return names


def unknown_handlers(root: Path) -> list[str]:
    """Every descriptor must name a handler that exists.

    A typo would otherwise surface as a 500 on the first real request. The
    import is made to work when this runs as a script -- an earlier version
    swallowed the ImportError and returned no problems, which silently turned
    this check off in exactly the context CI uses.
    """

    if not (root / TABLE_SOURCE).exists():
        return []
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    try:
        from rag_ime.control_api.route_table import MIGRATED_ROUTES
        from rag_ime.debug_server import DebugImeService
    except ImportError as error:
        return [f"cannot verify route handlers: {error}"]

    instance_attributes = _service_attribute_names(root)
    problems: list[str] = []
    for route in MIGRATED_ROUTES:
        head, _, rest = route.handler.partition(".")
        if not rest:
            if not hasattr(DebugImeService, head):
                problems.append(
                    f"route {route.method} {route.path} names handler "
                    f"{route.handler!r}, which DebugImeService does not define"
                )
            continue
        # Dotted: the sub-service is created at runtime, so the gate verifies
        # the attribute is assigned rather than resolving the whole path.
        if head not in instance_attributes and not hasattr(DebugImeService, head):
            problems.append(
                f"route {route.method} {route.path} names handler "
                f"{route.handler!r}, but DebugImeService never sets {head!r}"
            )
    return problems


def handler_arity(root: Path) -> list[str]:
    """Every descriptor must call its handler the way the handler is written.

    `unknown_handlers` proves the attribute exists; it does not prove the
    dispatcher can call it. The dispatcher passes exactly one positional
    argument when `takes_arguments` is true and none when it is false, so a
    handler taking a different shape -- `memory_page(kind, request)` is a real
    example still in the chains -- would raise TypeError on the first request
    rather than at import. Only unbound functions on the class can be checked,
    which is why a handler reached through a runtime sub-service is skipped
    rather than guessed at.
    """

    if not (root / TABLE_SOURCE).exists():
        return []
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    try:
        from rag_ime.control_api.route_table import MIGRATED_ROUTES
        from rag_ime.debug_server import DebugImeService
    except ImportError as error:
        return [f"cannot verify route handler arity: {error}"]

    problems: list[str] = []
    for route in MIGRATED_ROUTES:
        if "." in route.handler:
            continue  # sub-service instance attribute; not resolvable statically
        function = getattr(DebugImeService, route.handler, None)
        if not callable(function):
            continue  # unknown_handlers already reports this
        try:
            parameters = list(inspect.signature(function).parameters.values())[1:]
        except (TypeError, ValueError):  # pragma: no cover - builtins
            continue
        if any(p.kind is inspect.Parameter.VAR_POSITIONAL for p in parameters):
            continue
        required = [
            p for p in parameters
            if p.default is inspect.Parameter.empty
            and p.kind in {p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD}
        ]
        supplied = 1 if route.takes_arguments else 0
        supplied_names = set(route.payload_args)
        outstanding = [p.name for p in required[supplied:] if p.name not in supplied_names]
        if outstanding:
            problems.append(
                f"route {route.method} {route.path} passes {supplied} positional "
                f"argument(s) to {route.handler!r}, which still needs "
                f"{', '.join(outstanding)}"
            )
        elif len(required) < supplied:
            problems.append(
                f"route {route.method} {route.path} passes a payload to "
                f"{route.handler!r}, which takes no positional argument; set "
                f"takes_arguments=False"
            )

        # Keyword-only arguments are how a shared handler is pinned to one
        # variant -- `vocabulary_item_save(payload, *, action)` serves add,
        # edit and phonetic-correction. Omitting `payload_args` for one of
        # those is a TypeError on the first request, so it is checked with the
        # same weight as the positional shape.
        missing_keywords = sorted(
            p.name for p in parameters
            if p.kind is inspect.Parameter.KEYWORD_ONLY
            and p.default is inspect.Parameter.empty
            and p.name not in supplied_names
        )
        if missing_keywords:
            problems.append(
                f"route {route.method} {route.path} does not supply "
                f"{', '.join(missing_keywords)} to {route.handler!r}, which "
                f"requires it as a keyword argument; add it to payload_args"
            )
    return problems


def check(root: Path) -> list[str]:
    problems = shadowed_branches(root)
    problems.extend(unknown_handlers(root))
    problems.extend(handler_arity(root))
    dispatched = dispatched_routes(root)
    chain = set(dispatched)
    table = table_routes(root)

    # Dual ownership is per (method, path), not per path: a family may migrate
    # its GET while POST stays in a chain, and treating that as a conflict
    # would block partial migration for no reason. Only the same verb serving
    # one path from both owners is a real conflict.
    chain_pairs = {
        (handler.removeprefix("do_"), path)
        for path, sites in dispatched.items()
        for handler, _line in sites
    }
    for method, path in sorted(table_route_pairs(root) & chain_pairs):
        problems.append(
            f"{method} {path} is owned by both the route table and a dispatch "
            f"chain; remove the chain branch so the route has one owner"
        )

    # A route in the descriptor table is declared by its descriptor, which
    # states its exposure explicitly. Only chain routes with no policy entry
    # are undeclared, so migrating a family lowers this count.
    undeclared = sorted(chain - declared_routes(root) - table)
    if len(undeclared) > UNDECLARED_DISPATCH_BUDGET:
        problems.append(
            f"dispatched-but-undeclared routes rose to {len(undeclared)} "
            f"(budget {UNDECLARED_DISPATCH_BUDGET}); declare the new route in "
            f"route_policy or lower the budget deliberately"
        )
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    problems = check(root)
    dispatched = dispatched_routes(root)
    declared = declared_routes(root)
    if args.json:
        print(json.dumps({
            "schemaVersion": "rag-ime.route-ownership.v1",
            "dispatchedPathCount": len(dispatched),
            "declaredPathCount": len(declared),
            "undeclaredDispatchCount": len(set(dispatched) - declared),
            "undeclaredDispatchBudget": UNDECLARED_DISPATCH_BUDGET,
            "problemCount": len(problems),
            "problems": problems,
            "ok": not problems,
        }, ensure_ascii=False, indent=2))
    elif problems:
        print("Route ownership problems:")
        for problem in problems:
            print(f"- {problem}")
    else:
        print(
            f"Route ownership OK ({len(dispatched)} dispatched, {len(declared)} declared, "
            f"{len(set(dispatched) - declared)}/{UNDECLARED_DISPATCH_BUDGET} undeclared)"
        )
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
