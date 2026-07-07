import ast
import json
from pathlib import Path
import subprocess
import unittest


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


def _imported_module_name(node: ast.AST) -> str:
    if isinstance(node, ast.Import):
        return str(node.names[0].name or "")
    if isinstance(node, ast.ImportFrom):
        if node.level:
            return ""
        return str(node.module or "")
    return ""
