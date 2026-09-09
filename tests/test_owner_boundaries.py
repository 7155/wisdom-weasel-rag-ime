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
            if owner == "rag_ime.pi_runtime_transcript":
                self.write("rag_ime/pi_runtime_transcript.py", "")
            else:
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

    def test_transcript_projection_cannot_depend_on_runtime_or_storage(self) -> None:
        samples = [
            "def later():\n    from .pi_runtime import PiRuntimeConfig\n",
            "from . import pi_runtime_v2 as runtime\n",
            "from .pi_runtime_protocols import resolve_protocol_manager\n",
            "from .agent_sessions import AgentSessionStore\n",
            "from .db import sqlite_connection\n",
            "import sqlite3\n",
            "import subprocess\n",
            "from .agent_service import AgentService\n",
            "import importlib as loader\nloader.import_module('.pi_runtime_v2', 'rag_ime')\n",
            "__import__('rag_ime.pi_runtime')\n",
            "from .pi_runtime_public_extra import hidden_dependency\n",
        ]
        for source in samples:
            with self.subTest(source=source):
                self.write("rag_ime/pi_runtime_transcript.py", source)
                self.assertEqual(len(CHECKER.check_owner_boundaries(self.root)), 1)

    def test_transcript_projection_can_use_shared_public_contracts(self) -> None:
        self.write("rag_ime/pi_runtime_transcript.py", """
from .agent_protocol import AgentEventEnvelope
from .pi_runtime_public import pi_message_payload
from .pi_runtime_values import as_mapping
""")
        self.assertEqual(CHECKER.check_owner_boundaries(self.root), [])

    def test_control_api_cannot_import_http_entry_or_composition(self) -> None:
        samples = [
            "def later():\n    from ..debug_server import DebugRequestHandler\n",
            "from ..agent_service import AgentService\n",
            "import importlib\nimportlib.import_module('rag_ime.debug_server')\n",
        ]
        for source in samples:
            with self.subTest(source=source):
                self.write("rag_ime/control_api/lab_errors.py", source)
                self.assertEqual(len(CHECKER.check_owner_boundaries(self.root)), 1)

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

    def test_missing_transcript_module_is_not_a_passing_check(self) -> None:
        (self.root / "rag_ime/pi_runtime_transcript.py").unlink()
        process = subprocess.run(
            [sys.executable, str(SCRIPT), "--root", str(self.root), "--json"],
            check=False, capture_output=True, text=True,
        )
        self.assertEqual(process.returncode, 1)
        self.assertEqual(json.loads(process.stdout)["missingOwners"], ["rag_ime.pi_runtime_transcript"])

    def test_non_python_file_cannot_stand_in_for_owner_package(self) -> None:
        owner = self.root / "rag_ime/db"
        owner.rmdir()
        owner.write_text("")
        process = subprocess.run(
            [sys.executable, str(SCRIPT), "--root", str(self.root), "--json"],
            check=False, capture_output=True, text=True,
        )
        self.assertEqual(process.returncode, 1)
        self.assertIn("rag_ime.db", json.loads(process.stdout)["missingOwners"])


if __name__ == "__main__":
    unittest.main()
