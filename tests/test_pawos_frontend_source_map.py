from __future__ import annotations

import copy
import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/check_pawos_frontend_source_map.py"
MANIFEST = ROOT / "control-center-web/docs/handoffs/PAWOS_REAL_FRONTEND_SOURCE_MAP.v1.json"

SPEC = importlib.util.spec_from_file_location("check_pawos_frontend_source_map", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
CHECKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECKER)


class PawOsFrontendSourceMapTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    def test_current_map_follows_registry_and_selection_markers(self) -> None:
        self.assertEqual(CHECKER.check_manifest(ROOT, self.manifest), [])

    def test_missing_app_is_reported_as_registry_drift(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        manifest["apps"] = manifest["apps"][:-1]

        errors = CHECKER.check_manifest(ROOT, manifest)

        self.assertTrue(
            any("differs from pawOsAppRegistry" in error for error in errors),
            errors,
        )

    def test_preview_file_cannot_be_promoted_to_render_owner(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        manifest["apps"][0]["renderOwners"].append(
            "control-center-web/src/app/preview-control-transport.tsx"
        )

        errors = CHECKER.check_manifest(ROOT, manifest)

        self.assertTrue(
            any("non-authoritative area" in error for error in errors),
            errors,
        )


if __name__ == "__main__":
    unittest.main()
