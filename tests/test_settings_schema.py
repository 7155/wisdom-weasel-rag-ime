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
        self.assertIn("externalMemorySources", section_ids)
        self.assertIn("agent", section_ids)
        self.assertIn("pinyin", section_ids)
        self.assertIn("privacy", section_ids)

    def test_defaults_include_user_customization_controls(self) -> None:
        defaults = default_settings()

        self.assertFalse(defaults["interaction"]["composition"]["showPrediction"])
        self.assertTrue(defaults["interaction"]["composition"]["showOnlyRime"])
        self.assertEqual(defaults["models"]["hot"], "minimind_ime_v2")
        self.assertFalse(defaults["interaction"]["postCommit"]["showPendingStatus"])
        self.assertEqual(defaults["interaction"]["postCommit"]["idleTriggerMs"], 220)
        self.assertEqual(defaults["interaction"]["postCommit"]["minDeltaChars"], 2)
        self.assertEqual(defaults["interaction"]["postCommit"]["maxCallsPer10s"], 6)
        self.assertEqual(defaults["interaction"]["postCommit"]["cooldownMs"], 1500)
        self.assertEqual(defaults["interaction"]["postCommit"]["pendingStatusDelayMs"], 600)
        self.assertEqual(defaults["interaction"]["postCommit"]["panelTtlMs"], 5000)
        self.assertEqual(defaults["display"]["badges"]["model"], "模")
        self.assertEqual(defaults["display"]["badges"]["action"], "生成")
        self.assertEqual(defaults["display"]["colors"]["action"], "blue")
        self.assertTrue(defaults["rag"]["lanes"]["bm25Raw"])
        self.assertEqual(defaults["rag"]["hybrid"]["budgetMs"], 400)
        self.assertEqual(defaults["activeRag"]["shortcut"], "ctrl+.")
        self.assertTrue(defaults["activeRag"]["capture"]["accessibility"])
        self.assertTrue(defaults["activeRag"]["capture"]["clipboardFallback"])
        self.assertEqual(defaults["activeRag"]["defaultPlacement"], "replace_selection")
        self.assertEqual(defaults["activeRag"]["maxCandidates"], 1)
        self.assertEqual(defaults["activeRag"]["quickModel"], "deepseek/deepseek-v4-flash")
        self.assertEqual(defaults["activeRag"]["quickThinkingLevel"], "off")
        self.assertNotIn("visualModel", defaults["activeRag"])
        self.assertTrue(defaults["activeRag"]["allowRemoteModel"])
        self.assertTrue(defaults["privacy"]["allowRemoteModelForActiveRag"])
        self.assertEqual(defaults["models"]["activeRag"], "deepseek-v4")
        self.assertEqual(defaults["pinyin"]["fuzzyProfile"], "sichuan-mild")
        self.assertTrue(defaults["pinyin"]["rerankUsesFuzzy"])
        self.assertTrue(defaults["pinyin"]["pairs"]["sSh"])
        self.assertTrue(defaults["pinyin"]["pairs"]["ongOn"])
        self.assertFalse(defaults["pinyin"]["pairs"]["nL"])
        self.assertFalse(defaults["privacy"]["debugIncludeText"])
        self.assertEqual(defaults["context"]["tokenBudget"], 4096)
        self.assertEqual(defaults["context"]["reservedOutputTokens"], 1024)
        self.assertFalse(defaults["agent"]["pi"]["enabled"])
        self.assertEqual(defaults["agent"]["pi"]["idleTimeoutSeconds"], 900)
        self.assertTrue(defaults["memory"]["automaticOrganization"]["enabled"])
        self.assertEqual(
            defaults["memory"]["automaticOrganization"]["model"],
            "deepseek-v4-flash",
        )
        self.assertEqual(
            defaults["memory"]["automaticOrganization"]["runsPerDay"],
            2,
        )
        self.assertTrue(defaults["memory"]["dreaming"]["enabled"])
        self.assertEqual(defaults["memory"]["dreaming"]["runsPerDay"], 2)
        self.assertFalse(
            defaults["memory"]["externalSources"]["codexMemory"]["enabled"]
        )
        self.assertEqual(
            defaults["memory"]["externalSources"]["codexMemory"]["lookbackDays"],
            90,
        )
        self.assertEqual(defaults["memory"]["recall"]["detailLevel"], "compact")

        fields = {field["key"]: field for section in settings_schema()["sections"] for field in section["fields"]}
        self.assertFalse(fields["interaction.composition.showPrediction"]["default"])
        self.assertTrue(fields["interaction.composition.showOnlyRime"]["default"])
        self.assertEqual(fields["interaction.postCommit.maxCallsPer10s"]["default"], 6)
        self.assertEqual(fields["interaction.postCommit.panelTtlMs"]["default"], 5000)
        self.assertEqual(fields["models.hot"]["default"], "minimind_ime_v2")
        self.assertEqual(fields["context.tokenBudget"]["default"], 4096)
        self.assertEqual(fields["activeRag.quickModel"]["type"], "pi-model")
        self.assertEqual(fields["activeRag.quickThinkingLevel"]["options"], ["off", "low"])
        self.assertNotIn("activeRag.visualModel", fields)
        self.assertEqual(
            fields["memory.automaticOrganization.enabled"]["label"],
            "自动整理",
        )
        self.assertEqual(
            fields["memory.dreaming.enabled"]["label"],
            "记忆做梦",
        )
        self.assertEqual(
            fields["memory.externalSources.codexMemory.enabled"]["label"],
            "读取 Codex 记忆",
        )
        self.assertEqual(
            fields["memory.externalSources.codexMemory.lookbackDays"]["max"],
            90,
        )

    def test_flatten_roundtrip(self) -> None:
        original = {"interaction": {"postCommit": {"panelTtlMs": 4200}}, "display": {"badges": {"model": "模"}}}

        self.assertEqual(unflatten_settings(flatten_settings(original)), original)

    def test_every_field_declares_runtime_application_metadata(self) -> None:
        schema = settings_schema()
        required = {"description", "applyMode", "risk", "expert", "min", "max", "step", "unit", "validation", "restartComponent"}
        fields = [field for section in schema["sections"] for field in section["fields"]]

        self.assertTrue(fields)
        self.assertTrue(all(required.issubset(field) for field in fields))
        shortcut = next(field for field in fields if field["key"] == "activeRag.shortcut")
        self.assertEqual(shortcut["type"], "shortcut")
        self.assertEqual(shortcut["applyMode"], "restart_input_method")


if __name__ == "__main__":
    unittest.main()
