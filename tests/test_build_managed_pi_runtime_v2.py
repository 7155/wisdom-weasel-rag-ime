from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.build_managed_pi_runtime_v2 import _runtime_host_banner


class ManagedPiRuntimeV2BuildTests(unittest.TestCase):
    def test_runtime_banner_loads_all_product_skills_without_enabling_global_discovery(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-runtime-skills-") as temporary:
            root = Path(temporary)
            (root / "rag-ime-memory-curator").mkdir()
            (root / "rag-ime-plugin-creator").mkdir()

            banner = _runtime_host_banner(root)

        self.assertIn('"rag-ime-memory-curator"', banner)
        self.assertIn('"rag-ime-plugin-creator"', banner)
        self.assertIn('process.env.RAG_IME_PI_SKILL_PATHS', banner)
        self.assertIn('__join(__ragImeRuntimeDir, "skills", name)', banner)
        self.assertNotIn("--no-skills", banner)


if __name__ == "__main__":
    unittest.main()
