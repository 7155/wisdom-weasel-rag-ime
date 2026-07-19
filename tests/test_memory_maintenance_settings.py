from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rag_ime.memory_maintenance_settings import MemoryMaintenanceSettings
from rag_ime.settings_store import ManagementSettingsStore


class MemoryMaintenanceSettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(
            prefix="rag-ime-maintenance-settings-"
        )
        self.db_path = Path(self.temporary.name) / "rag-ime.sqlite"
        self.store = ManagementSettingsStore(self.db_path)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_defaults_enable_both_lanes_twice_daily(self) -> None:
        settings = MemoryMaintenanceSettings.load(self.db_path)

        self.assertTrue(settings.automatic_organization_enabled)
        self.assertTrue(settings.dreaming_enabled)
        self.assertEqual(settings.automatic_organization_model, "deepseek-v4-flash")
        self.assertEqual(settings.dreaming_model, "deepseek-v4-flash")
        self.assertEqual(settings.automatic_organization_interval_seconds, 43_200)
        self.assertEqual(settings.dreaming_interval_seconds, 43_200)
        self.assertFalse(settings.codex_memory_enabled)
        self.assertEqual(settings.codex_memory_root, "~/.codex/memories")
        self.assertEqual(settings.codex_memory_lookback_days, 90)
        self.assertTrue(settings.codex_memory_include_rollout_summaries)
        self.assertEqual(settings.recall_detail_level, "compact")
        self.assertEqual(settings.timeline_max_items, 2)

    def test_management_updates_drive_next_maintenance_run(self) -> None:
        self.store.update_settings(
            {
                "memory.automaticOrganization.enabled": False,
                "memory.automaticOrganization.runsPerDay": 4,
                "memory.dreaming.runsPerDay": 1,
                "memory.externalSources.codexMemory.enabled": True,
                "memory.externalSources.codexMemory.path": "~/custom-codex-memory",
                "memory.externalSources.codexMemory.lookbackDays": 60,
                "memory.externalSources.codexMemory.includeRolloutSummaries": False,
                "memory.recall.detailLevel": "balanced",
                "memory.recall.timelineEnabled": False,
            }
        )

        settings = MemoryMaintenanceSettings.load(self.db_path)

        self.assertFalse(settings.automatic_organization_enabled)
        self.assertEqual(settings.automatic_organization_interval_seconds, 21_600)
        self.assertEqual(settings.dreaming_interval_seconds, 86_400)
        self.assertTrue(settings.codex_memory_enabled)
        self.assertEqual(settings.codex_memory_root, "~/custom-codex-memory")
        self.assertEqual(settings.codex_memory_lookback_days, 60)
        self.assertFalse(settings.codex_memory_include_rollout_summaries)
        self.assertEqual(settings.recall_detail_level, "balanced")
        self.assertFalse(settings.timeline_recall_enabled)

    def test_non_v4_maintenance_model_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "DeepSeek V4"):
            self.store.update_settings(
                {"memory.dreaming.model": "deepseek-v3"}
            )

    def test_codex_memory_window_cannot_exceed_three_months(self) -> None:
        with self.assertRaisesRegex(ValueError, "<= 90"):
            self.store.update_settings(
                {"memory.externalSources.codexMemory.lookbackDays": 91}
            )


if __name__ == "__main__":
    unittest.main()
