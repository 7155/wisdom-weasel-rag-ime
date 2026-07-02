from __future__ import annotations

import unittest
from pathlib import Path


class SelectMacosInputSourceScriptTests(unittest.TestCase):
    def test_select_script_accepts_successful_final_state_after_tis_error(self) -> None:
        root = Path(__file__).resolve().parents[1]
        source = (root / "scripts" / "select_macos_input_source.sh").read_text(encoding="utf-8")

        self.assertIn("if selectStatus != noErr", source)
        self.assertIn("currentInputSourceID() != target", source)
        self.assertIn("but current source is already", source)

    def test_select_script_defaults_to_native_rag_ime_input_source(self) -> None:
        root = Path(__file__).resolve().parents[1]
        source = (root / "scripts" / "select_macos_input_source.sh").read_text(encoding="utf-8")

        self.assertIn("RAG_IME_MACOS_INPUT_SOURCE_ID", source)
        self.assertIn("dev.local.inputmethod.RagImeMac", source)


if __name__ == "__main__":
    unittest.main()
