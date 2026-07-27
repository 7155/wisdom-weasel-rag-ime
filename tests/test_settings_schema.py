from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rag_ime.agent_service import agent_service_from_settings
from rag_ime.settings_schema import default_settings, flatten_settings, settings_schema, unflatten_settings


class SettingsSchemaTests(unittest.TestCase):
    def test_schema_contains_management_console_v3_sections(self) -> None:
        schema = settings_schema()
        section_ids = {str(item["id"]) for item in schema["sections"]}

        self.assertIn("identity", section_ids)
        self.assertIn("interaction", section_ids)
        self.assertIn("display", section_ids)
        self.assertIn("rag", section_ids)
        self.assertIn("models", section_ids)
        self.assertIn("activeRag", section_ids)
        self.assertNotIn("externalMemorySources", section_ids)
        self.assertIn("agent", section_ids)
        self.assertIn("pinyin", section_ids)
        self.assertIn("privacy", section_ids)

    def test_defaults_include_user_customization_controls(self) -> None:
        defaults = default_settings()

        self.assertEqual(defaults["identity"]["productName"], "澄")
        self.assertEqual(defaults["identity"]["assistantName"], "澄")
        self.assertEqual(defaults["identity"]["tagline"], "记得你，也陪你做事")
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
        self.assertEqual(defaults["rag"]["weights"]["bm25Raw"], 1.0)
        self.assertEqual(defaults["rag"]["weights"]["vectorRaw"], 1.05)
        self.assertEqual(defaults["rag"]["hybrid"]["budgetMs"], 400)
        self.assertEqual(defaults["activeRag"]["shortcut"], "ctrl+.")
        self.assertTrue(defaults["activeRag"]["capture"]["accessibility"])
        self.assertTrue(defaults["activeRag"]["capture"]["clipboardFallback"])
        self.assertEqual(defaults["activeRag"]["defaultPlacement"], "replace_selection")
        self.assertEqual(defaults["activeRag"]["maxCandidates"], 1)
        self.assertEqual(defaults["activeRag"]["quickModel"], "deepseek/deepseek-v4-flash")
        self.assertEqual(defaults["activeRag"]["quickThinkingLevel"], "high")
        self.assertNotIn("visualModel", defaults["activeRag"])
        self.assertTrue(defaults["activeRag"]["allowRemoteModel"])
        self.assertTrue(defaults["privacy"]["allowRemoteModelForActiveRag"])
        self.assertEqual(set(defaults["models"]), {"hot"})
        self.assertEqual(defaults["voice"]["refinementModel"], "inherit")
        self.assertEqual(defaults["voice"]["refinementThinkingLevel"], "off")
        self.assertEqual(defaults["pinyin"]["fuzzyProfile"], "sichuan-mild")
        self.assertTrue(defaults["pinyin"]["rerankUsesFuzzy"])
        self.assertTrue(defaults["pinyin"]["pairs"]["sSh"])
        self.assertTrue(defaults["pinyin"]["pairs"]["ongOn"])
        self.assertFalse(defaults["pinyin"]["pairs"]["nL"])
        self.assertFalse(defaults["privacy"]["debugIncludeText"])
        self.assertEqual(defaults["privacy"]["debugContextDirectory"], "")
        self.assertEqual(defaults["privacy"]["debugContextMaxGiB"], 5)
        self.assertEqual(defaults["privacy"]["debugContextMaxCallsPerTurn"], 128)
        self.assertEqual(defaults["context"]["tokenBudget"], 4096)
        self.assertEqual(defaults["context"]["reservedOutputTokens"], 1024)
        self.assertFalse(defaults["agent"]["pi"]["enabled"])
        self.assertEqual(defaults["agent"]["pi"]["idleTimeoutSeconds"], 900)
        self.assertTrue(defaults["agent"]["pi"]["systemProxy"])
        self.assertEqual(defaults["agent"]["pi"]["defaultRoleId"], "companion-future-v1")
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
        self.assertNotIn("externalSources", defaults["memory"])
        self.assertEqual(defaults["memory"]["recall"]["detailLevel"], "compact")

        fields = {field["key"]: field for section in settings_schema()["sections"] for field in section["fields"]}
        self.assertEqual(fields["identity.productName"]["maxLength"], 24)
        self.assertEqual(fields["identity.assistantName"]["maxLength"], 24)
        self.assertEqual(fields["identity.tagline"]["maxLength"], 48)
        self.assertFalse(fields["interaction.composition.showPrediction"]["default"])
        self.assertTrue(fields["interaction.composition.showOnlyRime"]["default"])
        self.assertEqual(fields["interaction.postCommit.maxCallsPer10s"]["default"], 6)
        self.assertEqual(fields["interaction.postCommit.panelTtlMs"]["default"], 5000)
        self.assertEqual(fields["models.hot"]["default"], "minimind_ime_v2")
        self.assertEqual(fields["models.hot"]["label"], "本机预测配置 ID")
        self.assertIn("不是 Pi Provider 模型", fields["models.hot"]["description"])
        self.assertEqual(fields["privacy.debugContextMaxGiB"]["default"], 5)
        self.assertEqual(fields["privacy.debugContextMaxGiB"]["max"], 64)
        self.assertEqual(
            fields["privacy.debugContextMaxCallsPerTurn"]["default"],
            128,
        )
        self.assertEqual(
            fields["privacy.debugContextDirectory"]["maxLength"],
            1024,
        )
        self.assertEqual(fields["context.tokenBudget"]["default"], 4096)
        # Persona selection belongs to the Agent partner flow, not the generic
        # runtime settings form. Keep the internal default without exposing a
        # raw role id as a second, conflicting UI owner.
        self.assertNotIn("agent.pi.defaultRoleId", fields)
        self.assertNotIn("agent.pi.toolProfile", fields)
        self.assertNotIn("agent.pi.startup", fields)
        self.assertEqual(fields["activeRag.quickModel"]["type"], "pi-model")
        self.assertEqual(
            fields["activeRag.quickThinkingLevel"]["options"],
            ["off", "minimal", "low", "medium", "high", "xhigh", "max"],
        )
        self.assertEqual(fields["activeRag.quickThinkingLevel"]["default"], "high")
        self.assertIn(
            "默认使用高思考",
            fields["activeRag.quickThinkingLevel"]["description"],
        )
        self.assertNotIn("activeRag.visualModel", fields)
        self.assertNotIn("models.activeRag", fields)
        self.assertNotIn("models.offlineCleanup", fields)
        self.assertEqual(
            fields["voice.refinementModel"]["type"],
            "pi-model-or-inherit",
        )
        self.assertEqual(
            fields["memory.automaticOrganization.model"]["label"],
            "DeepSeek V4 自动整理模型 ID",
        )
        self.assertIn(
            "不是通用 Pi 模型槽位",
            fields["memory.automaticOrganization.model"]["description"],
        )
        self.assertEqual(
            fields["voice.refinementThinkingLevel"]["modelKey"],
            "voice.refinementModel",
        )
        self.assertEqual(
            fields["memory.automaticOrganization.enabled"]["label"],
            "自动整理",
        )
        self.assertEqual(
            fields["memory.dreaming.enabled"]["label"],
            "记忆做梦",
        )
        self.assertFalse(
            any(key.startswith("memory.externalSources.codexMemory") for key in fields)
        )

    def test_flatten_roundtrip(self) -> None:
        original = {"interaction": {"postCommit": {"panelTtlMs": 4200}}, "display": {"badges": {"model": "模"}}}

        self.assertEqual(unflatten_settings(flatten_settings(original)), original)

    def test_agent_default_is_future_but_an_explicit_legacy_role_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-role-default-") as temporary:
            default_service = agent_service_from_settings(
                Path(temporary) / "default.sqlite",
                {"agent": {"pi": {}}},
                wake_scheduler_enabled=False,
            )
            legacy_service = agent_service_from_settings(
                Path(temporary) / "legacy.sqlite",
                {"agent": {"pi": {"defaultRoleId": "companion-present-v1"}}},
                wake_scheduler_enabled=False,
            )

            self.assertEqual(
                default_service.configuration()["configuration"]["configuration"]["sessionDefaults"]["roleId"],
                "companion-future-v1",
            )
            self.assertEqual(
                legacy_service.configuration()["configuration"]["configuration"]["sessionDefaults"]["roleId"],
                "companion-present-v1",
            )

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
