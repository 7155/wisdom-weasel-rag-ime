import ast
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from scripts.check_import_boundaries import (
    PI_FAMILY_MODULES,
    check_pi_family_public_contracts,
)


ROOT = Path(__file__).resolve().parents[1]
V1_CORE_MODULES = [
    ROOT / "rag_ime" / "contracts" / "key_policy.py",
    ROOT / "rag_ime" / "contracts" / "source.py",
    ROOT / "rag_ime" / "contracts" / "trace.py",
    ROOT / "rag_ime" / "feature_bridge" / "foreground_acceptance.py",
    ROOT / "rag_ime" / "feature_bridge" / "registry.py",
    ROOT / "rag_ime" / "prediction" / "quality.py",
    ROOT / "rag_ime" / "memory" / "curated_store.py",
]
FROZEN_PREFIXES = (
    "rag_ime.active_rag",
    "rag_ime.debug_server",
    "rag_ime.deepseek",
    "rag_ime.memory_generator",
    "rag_ime.memory_compiler",
    "rag_ime.sequence_fork",
)


class ImportBoundaryTests(unittest.TestCase):
    def test_check_import_boundaries_script_passes_current_tree(self) -> None:
        result = subprocess.run(
            ["python3", "scripts/check_import_boundaries.py", "--json"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=True,
        )

        report = json.loads(result.stdout)
        self.assertTrue(report["ok"])
        self.assertEqual(report["violationCount"], 0)
        self.assertIn("rag_ime.prediction", report["checkedPackageRules"])
        self.assertIn("rag_ime.feature_bridge", report["checkedPackageRules"])
        self.assertIn("rag_ime/contracts/key_policy.py", report["checkedV1CoreFiles"])
        self.assertIn("rag_ime/contracts/source.py", report["checkedV1CoreFiles"])
        self.assertIn("rag_ime/contracts/trace.py", report["checkedV1CoreFiles"])
        self.assertIn("rag_ime/feature_bridge/registry.py", report["checkedV1CoreFiles"])
        self.assertIn("rag_ime/prediction/quality.py", report["checkedV1CoreFiles"])

    def test_v1_core_quality_modules_do_not_import_frozen_debug_or_offline_lanes(self) -> None:
        violations: list[str] = []
        for path in V1_CORE_MODULES:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                module = _imported_module_name(node)
                if module and module.startswith(FROZEN_PREFIXES):
                    violations.append(f"{path.relative_to(ROOT)} imports {module}")

        self.assertEqual(violations, [])

    def test_pi_family_import_must_be_declared_by_target_all(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self._write_pi_family(
                root,
                {
                    "rag_ime.pi_runtime": (
                        "__all__ = []\n"
                        "from .pi_runtime_public import undeclared\n"
                    ),
                    "rag_ime.pi_runtime_public": (
                        "__all__ = ['declared']\n"
                        "declared = object()\n"
                        "undeclared = object()\n"
                    ),
                },
            )

            violations = check_pi_family_public_contracts(root)

        self.assertTrue(
            any(
                violation.imported
                == "rag_ime.pi_runtime_public.undeclared"
                and "target module's __all__" in violation.reason
                for violation in violations
            )
        )

    def test_pi_family_private_import_fails_even_if_exported(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self._write_pi_family(
                root,
                {
                    "rag_ime.pi_runtime": (
                        "__all__ = []\n"
                        "from .pi_runtime_public import _private\n"
                    ),
                    "rag_ime.pi_runtime_public": (
                        "__all__ = ['_private']\n"
                        "_private = object()\n"
                    ),
                },
            )

            violations = check_pi_family_public_contracts(root)

        self.assertTrue(
            any(
                violation.imported == "rag_ime.pi_runtime_public._private"
                and "private names stay module-local" in violation.reason
                for violation in violations
            )
        )

    def test_pi_family_missing_literal_all_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self._write_pi_family(
                root,
                {"rag_ime.pi_runtime_public": "visible = object()\n"},
            )

            violations = check_pi_family_public_contracts(root)

        self.assertTrue(
            any(
                violation.module == "rag_ime.pi_runtime_public"
                and "literal __all__" in violation.reason
                for violation in violations
            )
        )

    def test_pi_protocol_manager_must_be_exported_by_target(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self._write_pi_family(
                root,
                {
                    "rag_ime.pi_runtime": (
                        "__all__ = []\n"
                        "class PiRuntimeManager: pass\n"
                    ),
                    "rag_ime.pi_runtime_protocols": (
                        "__all__ = []\n"
                        "PROTOCOL_MANAGERS = {\n"
                        "    '1': ('rag_ime.pi_runtime', 'PiRuntimeManager'),\n"
                        "}\n"
                    ),
                },
            )

            violations = check_pi_family_public_contracts(root)

        self.assertTrue(
            any(
                violation.imported == "rag_ime.pi_runtime.PiRuntimeManager"
                and "protocol 1 manager" in violation.reason
                for violation in violations
            )
        )

    def test_pi_family_declared_import_and_protocol_manager_pass(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self._write_pi_family(
                root,
                {
                    "rag_ime.pi_runtime": (
                        "__all__ = ['PiRuntimeManager']\n"
                        "from .pi_runtime_public import declared\n"
                        "class PiRuntimeManager: pass\n"
                    ),
                    "rag_ime.pi_runtime_public": (
                        "__all__ = ['declared']\n"
                        "declared = object()\n"
                    ),
                    "rag_ime.pi_runtime_protocols": (
                        "__all__ = []\n"
                        "PROTOCOL_MANAGERS = {\n"
                        "    '1': ('rag_ime.pi_runtime', 'PiRuntimeManager'),\n"
                        "}\n"
                    ),
                },
            )

            violations = check_pi_family_public_contracts(root)

        self.assertEqual(violations, [])

    def _write_pi_family(
        self,
        root: Path,
        sources: dict[str, str],
    ) -> None:
        for module in PI_FAMILY_MODULES:
            path = root / Path(module.replace(".", "/") + ".py")
            path.parent.mkdir(parents=True, exist_ok=True)
            default = (
                "__all__ = []\nPROTOCOL_MANAGERS = {}\n"
                if module == "rag_ime.pi_runtime_protocols"
                else "__all__ = []\n"
            )
            path.write_text(sources.get(module, default), encoding="utf-8")


def _imported_module_name(node: ast.AST) -> str:
    if isinstance(node, ast.Import):
        return str(node.names[0].name or "")
    if isinstance(node, ast.ImportFrom):
        if node.level:
            return ""
        return str(node.module or "")
    return ""
