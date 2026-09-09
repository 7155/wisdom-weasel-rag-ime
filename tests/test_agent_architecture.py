from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AGENT_SERVICE = ROOT / "rag_ime" / "agent_service.py"

# Application dependencies are explicit; no whole-facade exceptions remain.
RETIRED_ROLE_IDS = {
    "vcp-v1",
    "zhiyou-v1",
    "hermes-v1",
    "flash-v1",
}
RETIRED_ROOM_TOOL_NAMES = {
    "room_send",
    "room_ask",
    "room_reply",
    "room_mailbox",
    "room_assign",
    "room_submit",
    "room_accept",
    "room_return",
    "room_block",
    "room_escalate",
}


class AgentArchitectureTest(unittest.TestCase):
    def test_no_new_service_receives_the_agent_service_facade(
        self,
    ) -> None:
        tree = ast.parse(
            AGENT_SERVICE.read_text(encoding="utf-8")
        )
        service = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef)
            and node.name == "AgentService"
        )
        initializer = next(
            node
            for node in service.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "__init__"
        )
        actual: set[str] = set()
        for node in ast.walk(initializer):
            if not isinstance(node, ast.Call):
                continue
            if not any(
                isinstance(argument, ast.Name)
                and argument.id == "self"
                for argument in [*node.args, *(keyword.value for keyword in node.keywords)]
            ):
                continue
            name = _call_name(node.func)
            if name.endswith(("Service", "ApplicationService")):
                actual.add(name)
        self.assertEqual(
            actual,
            set(),
            "Application services must receive explicit stores/ports, "
            "not the entire AgentService facade.",
        )

    def test_agent_modules_do_not_import_the_composition_root(
        self,
    ) -> None:
        offenders: list[str] = []
        paths = [*(ROOT / "rag_ime").glob("agent_*.py"), *(ROOT / "rag_ime" / "rooms").glob("*.py")]
        for path in sorted(paths):
            if path == AGENT_SERVICE:
                continue
            tree = ast.parse(
                path.read_text(encoding="utf-8")
            )
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.ImportFrom)
                    and node.module
                    in {
                        "agent_service",
                        "rag_ime.agent_service",
                    }
                ):
                    offenders.append(path.name)
        self.assertEqual(
            offenders,
            [],
            "Domain/application modules must not depend back on "
            "the AgentService composition root.",
        )

    def test_retired_names_stay_out_of_runtime_and_ui_surfaces(self) -> None:
        roots = (
            ROOT / "rag_ime",
            ROOT / "integrations" / "pi",
            ROOT / "control-center-web" / "src",
            ROOT / "control-center-web" / "public",
        )
        offenders: list[str] = []
        for root in roots:
            for path in sorted(root.rglob("*")):
                if not path.is_file() or path.suffix not in {
                    ".json",
                    ".md",
                    ".py",
                    ".ts",
                    ".tsx",
                }:
                    continue
                if path.name == "agent_role_identity.py":
                    continue
                text = path.read_text(encoding="utf-8")
                for retired in RETIRED_ROLE_IDS | RETIRED_ROOM_TOOL_NAMES:
                    if re.search(
                        rf"(?<![A-Za-z0-9_-]){re.escape(retired)}"
                        rf"(?![A-Za-z0-9_-])",
                        text,
                    ):
                        offenders.append(
                            f"{path.relative_to(ROOT)}: {retired}"
                        )
        self.assertEqual(
            offenders,
            [],
            "Retired names may exist only in agent_role_identity.py and "
            "dedicated negative compatibility tests.",
        )


def _call_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


if __name__ == "__main__":
    unittest.main()
