from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


class LegacyNameGuardTests(unittest.TestCase):
    def test_legacy_bundle_names_stay_out_of_current_product_files(self) -> None:
        root = Path(__file__).resolve().parents[1]
        tracked = subprocess.run(
            ["git", "ls-files"],
            cwd=root,
            check=True,
            text=True,
            capture_output=True,
        ).stdout.splitlines()
        legacy_needles = (
            "RAG-IME.app",
            "RagIme.app",
            "im.rag-ime.inputmethod.RagIme",
        )
        allowed_prefixes = (
            "docs/agent/",
            "tests/",
        )
        allowed_paths = {
            "scripts/build_patched_squirrel.sh",
            "scripts/clean_macos_input_source_registrations.sh",
            "scripts/stop_rag_ime_runtime.sh",
        }

        offenders: list[str] = []
        for rel_path in tracked:
            if rel_path in allowed_paths or rel_path.startswith(allowed_prefixes):
                continue
            path = root / rel_path
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for needle in legacy_needles:
                if needle in text:
                    offenders.append(f"{rel_path}: {needle}")

        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
