from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

from rag_ime.memory_maintenance_settings import MemoryMaintenanceSettings
from rag_ime.owner_memory_maintenance import main as maintenance_main
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
        self.assertEqual(settings.automatic_organization_model, "gpt/gpt-5.6-luna")
        self.assertEqual(settings.automatic_organization_thinking_level, "max")
        self.assertEqual(settings.dreaming_model, "gpt/gpt-5.6-luna")
        self.assertEqual(settings.dreaming_thinking_level, "max")
        self.assertEqual(settings.automatic_organization_interval_seconds, 43_200)
        self.assertEqual(settings.dreaming_interval_seconds, 43_200)
        self.assertEqual(settings.recall_detail_level, "compact")
        self.assertEqual(settings.timeline_max_items, 2)

    def test_management_updates_drive_next_maintenance_run(self) -> None:
        self.store.update_settings(
            {
                "memory.automaticOrganization.enabled": False,
                "memory.automaticOrganization.model": "deepseek/deepseek-v4-pro",
                "memory.automaticOrganization.thinkingLevel": "high",
                "memory.automaticOrganization.runsPerDay": 4,
                "memory.dreaming.model": "gpt/gpt-5.6-sol",
                "memory.dreaming.thinkingLevel": "low",
                "memory.dreaming.runsPerDay": 1,
                "memory.recall.detailLevel": "balanced",
                "memory.recall.timelineEnabled": False,
            }
        )

        settings = MemoryMaintenanceSettings.load(self.db_path)

        self.assertFalse(settings.automatic_organization_enabled)
        self.assertEqual(settings.automatic_organization_model, "deepseek/deepseek-v4-pro")
        self.assertEqual(settings.automatic_organization_thinking_level, "high")
        self.assertEqual(settings.dreaming_model, "gpt/gpt-5.6-sol")
        self.assertEqual(settings.dreaming_thinking_level, "low")
        self.assertEqual(settings.automatic_organization_interval_seconds, 21_600)
        self.assertEqual(settings.dreaming_interval_seconds, 86_400)
        self.assertEqual(settings.recall_detail_level, "balanced")
        self.assertFalse(settings.timeline_recall_enabled)
    def test_legacy_explicit_deepseek_choice_is_preserved_with_provider_prefix(self) -> None:
        self.store.update_settings(
            {"memory.dreaming.model": "deepseek-v4-flash"}
        )

        settings = MemoryMaintenanceSettings.load(self.db_path)

        self.assertEqual(
            settings.dreaming_model,
            "deepseek/deepseek-v4-flash",
        )


    def test_non_provider_memory_model_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "provider/model reference"):
            self.store.update_settings(
                {"memory.dreaming.model": "deepseek-v3"}
            )
    def test_manual_run_cannot_shorten_cadence_or_auto_apply(self) -> None:
        captured: dict[str, object] = {}

        class CapturingCurator:
            def __init__(self, _db_path: object, **kwargs: object) -> None:
                captured.update(kwargs)

            def initialize(self) -> None:
                return None

            def run_due(self, **kwargs: object) -> dict[str, object]:
                captured["runDue"] = dict(kwargs)
                return {
                    "schemaVersion": "rag-ime.owner-memory-curation-run.v1",
                    "ok": True,
                    "results": [],
                }

        output = io.StringIO()
        with (
            patch(
                "rag_ime.owner_memory_maintenance.run_due_lexicon_organization",
                return_value={"ok": True},
            ) as lexicon_run,
            patch(
                "rag_ime.owner_memory_maintenance.build_managed_pi_memory_model_executor",
                return_value=Mock(),
            ),
            patch(
                "rag_ime.owner_memory_maintenance.ManagedPiMemoryOrganizer",
                return_value=Mock(),
            ),
            patch(
                "rag_ime.owner_memory_maintenance.OwnerMemoryCurator",
                CapturingCurator,
            ),
            patch(
                "rag_ime.owner_memory_maintenance.embedding_provider_from_env",
                return_value=None,
            ),
            patch.dict(
                "os.environ",
                {"RAG_IME_OWNER_MEMORY_INTERVAL_SECONDS": "1"},
                clear=False,
            ),
            redirect_stdout(output),
        ):
            exit_code = maintenance_main(
                [
                    "--db-path",
                    str(self.db_path),
                    "--manual",
                    "--auto-apply",
                ]
            )

        report = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertFalse(captured["auto_apply"])
        self.assertEqual(captured["daily_interval_ms"], 43_200_000)
        self.assertTrue(captured["runDue"]["manual"])
        lexicon_run.assert_called_once_with(
            str(self.db_path),
            project="",
            force=True,
        )
        self.assertFalse(report["autoApply"])
        self.assertEqual(report["effectiveIntervalSeconds"], 43_200)


if __name__ == "__main__":
    unittest.main()
