from __future__ import annotations

import os
import plistlib
import subprocess
import tempfile
import unittest
from pathlib import Path


class BrandSquirrelAppScriptTests(unittest.TestCase):
    def test_brands_info_plist_and_localized_input_source_names(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-brand-squirrel-") as tmp:
            tmp_path = Path(tmp)
            app = _write_fake_squirrel_app(tmp_path / "RAG-IME.app")

            result = subprocess.run(
                ["bash", str(root / "scripts" / "brand_squirrel_app.sh"), str(app)],
                cwd=root,
                env={
                    **os.environ,
                    "RAG_IME_SQUIRREL_BUNDLE_ID": "im.rag-ime.inputmethod.RagIme",
                    "RAG_IME_SQUIRREL_INPUT_SOURCE_ID": "im.rag-ime.inputmethod.RagIme.Hans",
                    "RAG_IME_SQUIRREL_HANT_INPUT_SOURCE_ID": "im.rag-ime.inputmethod.RagIme.Hant",
                    "RAG_IME_SQUIRREL_DISPLAY_NAME": "RAG-IME",
                    "RAG_IME_SQUIRREL_CONNECTION_NAME": "RagIme_Connection",
                },
                check=True,
                text=True,
                capture_output=True,
            )

            info = _read_plist(app / "Contents" / "Info.plist")
            strings = _read_plist(app / "Contents" / "Resources" / "en.lproj" / "InfoPlist.strings")

        self.assertIn("bundle_id=im.rag-ime.inputmethod.RagIme", result.stdout)
        self.assertEqual(info["CFBundleIdentifier"], "im.rag-ime.inputmethod.RagIme")
        self.assertEqual(info["CFBundleName"], "RAG-IME")
        self.assertEqual(info["TISInputSourceID"], "im.rag-ime.inputmethod.RagIme")
        self.assertEqual(info["InputMethodConnectionName"], "RagIme_Connection")
        self.assertFalse(info["SUEnableAutomaticChecks"])
        modes = info["ComponentInputModeDict"]["tsInputModeListKey"]
        self.assertEqual(set(modes), {"im.rag-ime.inputmethod.RagIme.Hans", "im.rag-ime.inputmethod.RagIme.Hant"})
        self.assertEqual(modes["im.rag-ime.inputmethod.RagIme.Hans"]["TISInputSourceID"], "im.rag-ime.inputmethod.RagIme.Hans")
        self.assertEqual(
            info["ComponentInputModeDict"]["tsVisibleInputModeOrderedArrayKey"],
            ["im.rag-ime.inputmethod.RagIme.Hans", "im.rag-ime.inputmethod.RagIme.Hant"],
        )
        self.assertNotIn("im.rime.inputmethod.Squirrel.Hans", strings)
        self.assertEqual(strings["im.rag-ime.inputmethod.RagIme.Hans"], "RAG-IME - Simplified")
        self.assertEqual(strings["im.rag-ime.inputmethod.RagIme.Hant"], "RAG-IME - Traditional")


def _write_fake_squirrel_app(path: Path) -> Path:
    contents = path / "Contents"
    resources = contents / "Resources" / "en.lproj"
    resources.mkdir(parents=True)
    info = {
        "CFBundleIdentifier": "im.rime.inputmethod.Squirrel",
        "CFBundleName": "Squirrel",
        "TISInputSourceID": "im.rime.inputmethod.Squirrel",
        "InputMethodConnectionName": "Squirrel_Connection",
        "SUEnableAutomaticChecks": True,
        "ComponentInputModeDict": {
            "tsInputModeListKey": {
                "im.rime.inputmethod.Squirrel.Hans": {
                    "TISInputSourceID": "im.rime.inputmethod.Squirrel.Hans",
                    "TISIntendedLanguage": "zh-Hans",
                    "tsInputModeDefaultStateKey": True,
                },
                "im.rime.inputmethod.Squirrel.Hant": {
                    "TISInputSourceID": "im.rime.inputmethod.Squirrel.Hant",
                    "TISIntendedLanguage": "zh-Hant",
                    "tsInputModeDefaultStateKey": False,
                },
            },
            "tsVisibleInputModeOrderedArrayKey": [
                "im.rime.inputmethod.Squirrel.Hans",
                "im.rime.inputmethod.Squirrel.Hant",
            ],
        },
    }
    strings = {
        "CFBundleName": "Squirrel",
        "CFBundleDisplayName": "Squirrel",
        "im.rime.inputmethod.Squirrel": "Squirrel",
        "im.rime.inputmethod.Squirrel.Hans": "Squirrel - Simplified",
        "im.rime.inputmethod.Squirrel.Hant": "Squirrel - Traditional",
    }
    _write_plist(contents / "Info.plist", info)
    _write_plist(resources / "InfoPlist.strings", strings)
    return path


def _write_plist(path: Path, payload: dict[str, object]) -> None:
    with path.open("wb") as handle:
        plistlib.dump(payload, handle)


def _read_plist(path: Path) -> dict[str, object]:
    with path.open("rb") as handle:
        payload = plistlib.load(handle)
    assert isinstance(payload, dict)
    return payload


if __name__ == "__main__":
    unittest.main()
