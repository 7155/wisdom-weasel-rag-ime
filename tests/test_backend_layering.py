from __future__ import annotations

import ast
import collections
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1] / "rag_ime"

# Entry points own transport and process startup. The application layer owns
# product commands. The Room domain owns Kernel state. Imports may only point
# downward through those layers.
ENTRY = "entry"
APPLICATION = "application"
DOMAIN = "domain"


def _layer(module: str) -> str | None:
    if module.startswith("debug_server") or module.startswith("cli"):
        return ENTRY
    if module.endswith("_service") or "application" in module:
        return APPLICATION
    if module.startswith("agent_room_") or module.startswith("agent_definitions"):
        return DOMAIN
    return None


def _module_level_imports() -> dict[str, set[str]]:
    """Only real module-level imports; a function-local import is not an edge."""

    edges: dict[str, set[str]] = collections.defaultdict(set)
    for path in sorted(ROOT.rglob("*.py")):
        module = str(path.relative_to(ROOT)).removesuffix(".py").replace("/", ".")
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ImportFrom) and node.level and node.module:
                edges[module].add(node.module)
    return edges


class BackendLayeringTests(unittest.TestCase):
    """Keep the dependency direction that the architecture pass established.

    Each of these once had a real violation, and each was removed by moving an
    owner rather than by adding an abstraction. They are checked structurally
    because a behavioural test cannot observe an import direction.
    """

    def setUp(self) -> None:
        self.edges = _module_level_imports()

    def test_no_module_level_import_cycles(self) -> None:
        colour: dict[str, int] = collections.defaultdict(int)
        found: list[list[str]] = []

        def visit(node: str, stack: list[str]) -> None:
            colour[node] = 1
            stack.append(node)
            for target in sorted(self.edges.get(node, ())):
                if target not in self.edges:
                    continue
                if colour[target] == 1:
                    found.append(stack[stack.index(target):] + [target])
                elif colour[target] == 0:
                    visit(target, stack)
            stack.pop()
            colour[node] = 2

        for module in sorted(self.edges):
            if colour[module] == 0:
                visit(module, [])

        self.assertEqual(found, [], f"import cycles reintroduced: {found}")

    def test_room_domain_never_imports_the_application_or_entry_layer(self) -> None:
        upward = {
            (module, target)
            for module, targets in self.edges.items()
            if _layer(module) == DOMAIN
            for target in targets
            if _layer(target) in {ENTRY, APPLICATION}
        }
        self.assertEqual(upward, set(), f"Room domain imported upward: {sorted(upward)}")

    def test_entry_points_do_not_depend_on_each_other(self) -> None:
        # `debug_server` importing `cli` made the HTTP server depend on the
        # command line; fixture seeding now lives below both.
        mutual = {
            (module, target)
            for module, targets in self.edges.items()
            if _layer(module) == ENTRY
            for target in targets
            if _layer(target) == ENTRY
        }
        self.assertEqual(mutual, set(), f"entry points coupled: {sorted(mutual)}")

    def test_agent_service_does_not_write_room_owned_tables_directly(self) -> None:
        # Authoritative Room/Kernel state is written by the store that owns it,
        # never by the service orchestrating above it.
        source = (ROOT / "agent_service.py").read_text(encoding="utf-8")
        offenders = [
            line.strip()
            for line in source.splitlines()
            if any(
                verb in line for verb in ("INSERT INTO", "UPDATE ", "DELETE FROM")
            )
            and ("room_kernel_" in line or "room_v2_" in line)
        ]
        self.assertEqual(offenders, [], f"service layer wrote Room tables: {offenders}")


if __name__ == "__main__":
    unittest.main()
