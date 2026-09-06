from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from rag_ime.agent_configuration import AgentConfigurationConflict, AgentConfigurationStore, default_agent_configuration
from rag_ime.agent_prompt_settings import DEFAULT_COMPACTION_INSTRUCTIONS, MAX_PROMPT_CHARS, default_prompt_settings
from rag_ime.pi_runtime import PiRuntimeConfig


class AgentPromptSettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="paw-prompt-settings-")
        self.root = Path(self.temporary.name)
        self.db = self.root / "agent.sqlite"
        self.store = AgentConfigurationStore(self.db)
        self.store.initialize(default_agent_configuration())

    def tearDown(self) -> None:
        self.store.close()
        self.temporary.cleanup()

    def test_prompt_edits_preserve_other_settings_and_survive_reload(self) -> None:
        before = self.store.snapshot()["configuration"]
        update = self.store.update(
            {"prompts.systemInstructions": "用中文。\n先给结论。", "prompts.compactionInstructions": "保留下一步与文档引用。"},
            expected_revision=1,
            updated_by="settings-ui",
        )
        self.assertFalse(update.runtime_sync_required)
        self.store.close()
        self.store = AgentConfigurationStore(self.db)
        self.store.initialize(default_agent_configuration())
        after = self.store.snapshot()["configuration"]
        self.assertEqual(after["prompts"]["systemInstructions"], "用中文。\n先给结论。")
        self.assertEqual(after["prompts"]["compactionInstructions"], "保留下一步与文档引用。")
        self.assertEqual({key: value for key, value in before.items() if key != "prompts"},
                         {key: value for key, value in after.items() if key != "prompts"})
        with self.assertRaises(AgentConfigurationConflict):
            self.store.update({"prompts.systemInstructions": "stale"}, expected_revision=1, updated_by="settings-ui")

    def test_legacy_configuration_gets_defaults_without_losing_existing_values(self) -> None:
        before = self.store.snapshot()["configuration"]
        legacy = {key: value for key, value in before.items() if key != "prompts"}
        with sqlite3.connect(self.db) as connection:
            connection.execute("UPDATE agent_configuration_state SET configuration_json = ?", (json.dumps(legacy),))
        self.store.close()
        self.store = AgentConfigurationStore(self.db)
        self.store.initialize(default_agent_configuration())
        after = self.store.snapshot()["configuration"]
        self.assertEqual(after["prompts"], default_prompt_settings())
        self.assertEqual({key: value for key, value in after.items() if key != "prompts"}, legacy)

    def test_invalid_prompt_edits_are_atomic_and_empty_text_is_valid(self) -> None:
        before = self.store.snapshot()
        for value in (None, 3, "x" * (MAX_PROMPT_CHARS + 1), "bad\x00text"):
            with self.subTest(value_type=type(value).__name__), self.assertRaises(ValueError):
                self.store.update({"prompts.systemInstructions": value}, expected_revision=before["revision"], updated_by="settings-ui")
            self.assertEqual(self.store.snapshot(), before)
        update = self.store.update({"prompts.compactionInstructions": ""}, expected_revision=before["revision"], updated_by="settings-ui")
        self.assertEqual(update.snapshot["configuration"]["prompts"]["compactionInstructions"], "")

    def test_user_instructions_are_one_layer_and_do_not_change_specialized_sessions(self) -> None:
        config = PiRuntimeConfig(enabled=True, executable=None, agent_dir=self.root, session_dir=self.root, logs_dir=self.root, protocol_version="2")
        normal = {"mode": "coordinator", "projectContextEnabled": False}
        custom = {"systemInstructions": "优先提供最小可验证结果。", "compactionInstructions": DEFAULT_COMPACTION_INSTRUCTIONS}
        plain = config.system_prompt_for_session(normal)
        augmented = config.system_prompt_for_session(normal, prompt_settings=custom)
        self.assertEqual(augmented.count(custom["systemInstructions"]), 1)
        self.assertIn(plain.removesuffix("</agent-prompt-plan>\n"), augmented)
        self.assertNotIn(DEFAULT_COMPACTION_INSTRUCTIONS, augmented)
        for profile in ("ime-surface-v1", "voice-refinement-v1", "memory-curation-v1"):
            session = {**normal, "toolProfileVersion": profile}
            self.assertEqual(config.system_prompt_for_session(session), config.system_prompt_for_session(session, prompt_settings=custom))


if __name__ == "__main__":
    unittest.main()
