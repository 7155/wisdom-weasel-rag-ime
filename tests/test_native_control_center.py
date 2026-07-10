from __future__ import annotations

import plistlib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class NativeControlCenterTests(unittest.TestCase):
    def test_native_app_has_six_pages_and_no_web_runtime(self) -> None:
        root = ROOT / "macos" / "RagImeControl"
        text = "\n".join(path.read_text(encoding="utf-8") for path in root.rglob("*.swift"))

        for page in ("OverviewPage", "InputMethodPage", "MemoryPage", "RagAndModelsPage", "HistoryPage", "DiagnosticsPage"):
            self.assertIn(page, text)
        for forbidden in ("WKWebView", "Electron", "Tauri", "node_modules"):
            self.assertNotIn(forbidden, text)
        self.assertIn("NSTableView", text)
        self.assertIn("applicationShouldTerminateAfterLastWindowClosed", text)
        self.assertIn("defaultSize(width: 920, height: 640)", text)
        self.assertIn("frame(minWidth: 820, minHeight: 560)", text)

    def test_bundle_and_build_script_contract(self) -> None:
        with (ROOT / "macos" / "RagImeControl" / "Info.plist").open("rb") as handle:
            info = plistlib.load(handle)
        script = (ROOT / "scripts" / "build_control_center.sh").read_text(encoding="utf-8")

        self.assertEqual(info["CFBundleIdentifier"], "com.rag-ime.control")
        self.assertIn("$HOME/Applications/RagImeControl.app", script)
        self.assertIn("codesign --verify", script)
        self.assertNotIn("open \"$DEST\"", script)


if __name__ == "__main__":
    unittest.main()
