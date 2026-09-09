from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/check_owner_boundaries.py"
SPEC = importlib.util.spec_from_file_location("paw_owner_boundary_check", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
CHECKER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = CHECKER
SPEC.loader.exec_module(CHECKER)


class OwnerBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        for owner in CHECKER.OWNER_RULES:
            self.root.joinpath(*owner.split(".")).mkdir(parents=True)

    def write(self, path: str, source: str) -> None:
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source, encoding="utf-8")

    def test_allowed_ports_and_downstream_owners(self) -> None:
        self.write("rag_ime/agent_lab/example.py", """
from ..agent_runtime_driver import AgentRuntimeDriver
from ..knowledge_library import HttpKnowledgeClient
from ..db import sqlite_connection
from .trials import AgentLabTrialStore
""")
        self.assertEqual(CHECKER.check_owner_boundaries(self.root), [])

    def test_lab_cannot_import_composition(self) -> None:
        self.write("rag_ime/agent_lab/example.py", "from ..agent_service import AgentService\n")
        found = CHECKER.check_owner_boundaries(self.root)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].line, 1)
        self.assertIn("rag_ime.agent_service", found[0].imported)

    def test_deferred_and_conditional_imports_are_checked(self) -> None:
        samples = [
            "def later():\n    from ..agent_service import AgentService\n",
            "async def later():\n    from ..agent_service import AgentService\n",
            "try:\n    from ..agent_service import AgentService\nexcept ImportError:\n    pass\n",
            "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from ..agent_service import AgentService\n",
            "class Service:\n    from ..agent_service import AgentService\n",
        ]
        for source in samples:
            with self.subTest(source=source):
                self.write("rag_ime/agent_lab/example.py", source)
                self.assertEqual(len(CHECKER.check_owner_boundaries(self.root)), 1)

    def test_parent_alias_does_not_bypass_boundary(self) -> None:
        for source in [
            "from .. import agent_service as service\n",
            "from rag_ime import agent_service as service\n",
            "import rag_ime.agent_service as service\n",
        ]:
            with self.subTest(source=source):
                self.write("rag_ime/agent_lab/example.py", source)
                self.assertEqual(len(CHECKER.check_owner_boundaries(self.root)), 1)

    def test_package_initializer_relative_imports(self) -> None:
        self.write("rag_ime/knowledge_library/__init__.py", "from .. import agent_lab\n")
        found = CHECKER.check_owner_boundaries(self.root)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].module, "rag_ime.knowledge_library")
        self.assertEqual(found[0].imported, "rag_ime.agent_lab")

    def test_nested_package_relative_imports(self) -> None:
        self.write("rag_ime/agent_lab/nested/__init__.py", "from ... import agent_service\n")
        self.assertEqual(len(CHECKER.check_owner_boundaries(self.root)), 1)

    def test_knowledge_cannot_depend_on_lab(self) -> None:
        self.write("rag_ime/knowledge_library/store.py", "from ..agent_lab import projects\n")
        self.assertEqual(len(CHECKER.check_owner_boundaries(self.root)), 1)

    def test_database_cannot_depend_on_product_owners(self) -> None:
        self.write("rag_ime/db/example.py", """
from .. import agent_lab
from ..knowledge_library import store
from ..agent_service import AgentService
""")
        self.assertEqual(len(CHECKER.check_owner_boundaries(self.root)), 3)

    def test_literal_dynamic_imports(self) -> None:
        samples = [
            "import importlib\nimportlib.import_module('rag_ime.agent_service')\n",
            "import importlib as loader\nloader.import_module('rag_ime.agent_service')\n",
            "from importlib import import_module as load\nload('rag_ime.agent_service')\n",
            "__import__('rag_ime.agent_service')\n",
            "import importlib\nimportlib.import_module('.agent_service', 'rag_ime')\n",
            "import importlib\nimportlib.import_module(name='.agent_service', package='rag_ime')\n",
        ]
        for source in samples:
            with self.subTest(source=source):
                self.write("rag_ime/agent_lab/example.py", source)
                self.assertEqual(len(CHECKER.check_owner_boundaries(self.root)), 1)

    def test_multiple_symbols_produce_one_violation_per_edge(self) -> None:
        self.write("rag_ime/agent_lab/example.py", "from ..agent_service import AgentService, OTHER\n")
        self.assertEqual(len(CHECKER.check_owner_boundaries(self.root)), 1)

    def test_similar_but_unrelated_names_are_allowed(self) -> None:
        self.write("rag_ime/knowledge_library/example.py", "import rag_ime.agent_laboratory\n")
        self.assertEqual(CHECKER.check_owner_boundaries(self.root), [])

    def test_check_does_not_execute_modules(self) -> None:
        self.write("rag_ime/agent_lab/example.py", "raise RuntimeError('must not execute')\n")
        self.assertEqual(CHECKER.check_owner_boundaries(self.root), [])

    def test_composition_can_import_owners(self) -> None:
        self.write("rag_ime/agent_service.py", "from .agent_lab import projects\n")
        self.assertEqual(CHECKER.check_owner_boundaries(self.root), [])

    def test_cli_json_and_failure_code(self) -> None:
        self.write("rag_ime/agent_lab/example.py", "from .. import agent_service\n")
        process = subprocess.run(
            [sys.executable, str(SCRIPT), "--root", str(self.root), "--json"],
            check=False, capture_output=True, text=True,
        )
        self.assertEqual(process.returncode, 1)
        report = json.loads(process.stdout)
        self.assertFalse(report["ok"])
        self.assertEqual(report["violationCount"], 1)

    def test_cli_success_code(self) -> None:
        process = subprocess.run(
            [sys.executable, str(SCRIPT), "--root", str(self.root), "--json"],
            check=False, capture_output=True, text=True,
        )
        self.assertEqual(process.returncode, 0)
        self.assertTrue(json.loads(process.stdout)["ok"])

    def test_missing_checkout_is_not_a_passing_check(self) -> None:
        with tempfile.TemporaryDirectory() as empty:
            process = subprocess.run(
                [sys.executable, str(SCRIPT), "--root", empty, "--json"],
                check=False, capture_output=True, text=True,
            )
        self.assertEqual(process.returncode, 1)
        self.assertTrue(json.loads(process.stdout)["missingOwners"])


if __name__ == "__main__":
    unittest.main()
