from __future__ import annotations

import unittest

from rag_ime.settings_schema import default_settings, flatten_settings, settings_schema, unflatten_settings


class SettingsSchemaTests(unittest.TestCase):
    def test_schema_contains_management_console_v3_sections(self) -> None:
        schema = settings_schema()
        section_ids = {str(item["id"]) for item in schema["sections"]}

        self.assertIn("interaction", section_ids)
        self.assertIn("display", section_ids)
        self.assertIn("rag", section_ids)
        self.assertIn("models", section_ids)
        self.assertIn("activeRag", section_ids)
        self.assertIn("pinyin", section_ids)
        self.assertIn("privacy", section_ids)

    def test_defaults_include_user_customization_controls(self) -> None:
        defaults = default_settings()

        self.assertTrue(defaults["interaction"]["postCommit"]["showPendingStatus"])
        self.assertEqual(defaults["display"]["badges"]["model"], "模")
        self.assertEqual(defaults["display"]["badges"]["action"], "生成")
        self.assertEqual(defaults["display"]["colors"]["action"], "blue")
        self.assertTrue(defaults["rag"]["lanes"]["bm25Raw"])
        self.assertEqual(defaults["activeRag"]["shortcut"], "ctrl+enter")
        self.assertTrue(defaults["activeRag"]["capture"]["accessibility"])
        self.assertTrue(defaults["activeRag"]["capture"]["clipboardFallback"])
        self.assertEqual(defaults["activeRag"]["defaultPlacement"], "replace_selection")
        self.assertEqual(defaults["activeRag"]["maxCandidates"], 1)
        self.assertEqual(defaults["pinyin"]["fuzzyProfile"], "sichuan-mild")
        self.assertTrue(defaults["pinyin"]["rerankUsesFuzzy"])
        self.assertTrue(defaults["pinyin"]["pairs"]["sSh"])
        self.assertFalse(defaults["pinyin"]["pairs"]["nL"])
        self.assertFalse(defaults["privacy"]["debugIncludeText"])

    def test_flatten_roundtrip(self) -> None:
        original = {"interaction": {"postCommit": {"panelTtlMs": 4200}}, "display": {"badges": {"model": "模"}}}

        self.assertEqual(unflatten_settings(flatten_settings(original)), original)


if __name__ == "__main__":
    unittest.main()
