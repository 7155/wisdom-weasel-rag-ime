from __future__ import annotations

import json
import unittest
from pathlib import Path

from scripts.check_product_status import validate_product_status


class ProductStatusTests(unittest.TestCase):
    def test_repository_status_is_valid_and_does_not_overclaim_foreground(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / "docs" / "product-status.json").read_text(encoding="utf-8"))

        errors = validate_product_status(payload, repo_root=root)

        self.assertEqual(errors, [])
        self.assertFalse(payload["foregroundEvidence"]["strictSoakPassed"])
        self.assertEqual(payload["productStatus"], "backend_only")
        self.assertEqual(payload["releaseStatus"], "blocked")
        self.assertGreater(len(payload["blockers"]), 0)

    def test_foreground_verified_requires_green_strict_soak(self) -> None:
        payload = {
            "schemaVersion": "rag-ime.product-status.v1",
            "sourceCommit": "unused",
            "productStatus": "foreground_verified",
            "releaseStatus": "blocked",
            "blockers": [{"id": "one"}],
            "features": {"one": "backend_only"},
            "foregroundEvidence": {"strictSoakPassed": False},
        }

        errors = validate_product_status(payload)

        self.assertIn("foreground_verified requires strictSoakPassed=true", errors)


if __name__ == "__main__":
    unittest.main()
