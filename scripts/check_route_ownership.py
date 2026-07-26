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
import json
import re
from pathlib import Path


DISPATCH_SOURCE = Path("rag_ime/debug_server.py")
POLICY_SOURCE = Path("rag_ime/control_api/route_policy.py")

# Local-only surfaces dispatched by the server but deliberately not exposed to
# the remote Agent Gateway. This is a ratchet, not an approval: it may fall as
# families migrate to one owner, and a rise means a route appeared without a
# policy decision. Measured at the commit that introduced this gate.
UNDECLARED_DISPATCH_BUDGET = 129


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


def check(root: Path) -> list[str]:
    problems = shadowed_branches(root)
    undeclared = sorted(set(dispatched_routes(root)) - declared_routes(root))
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
