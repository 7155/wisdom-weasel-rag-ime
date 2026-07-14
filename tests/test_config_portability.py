from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from rag_ime.config_portability import (
    USER_CONFIG_SCHEMA_VERSION,
    apply_user_configuration,
    export_portable_backup,
    preview_portable_restore,
    preview_user_configuration,
    restore_portable_backup,
)
from rag_ime.local_sqlite_core import LocalSqliteCoreClient
from rag_ime.models import InputEvent
from rag_ime.settings_store import ManagementSettingsStore


class ConfigurationPortabilityTests(unittest.TestCase):
    def test_configuration_preview_validates_known_settings_and_typos(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-config-preview-") as temporary:
            store = ManagementSettingsStore(Path(temporary) / "rag-ime.sqlite")
            valid = preview_user_configuration(
                {
                    "schemaVersion": USER_CONFIG_SCHEMA_VERSION,
                    "settings": {
                        "context": {"recentInputMaximum": 120},
                        "planning": {"enabled": True},
                    },
                },
                settings_store=store,
            )
            invalid = preview_user_configuration(
                {
                    "schemaVersion": USER_CONFIG_SCHEMA_VERSION,
                    "setings": {},
                },
                settings_store=store,
            )

        self.assertTrue(valid["valid"])
        self.assertEqual(valid["settingCount"], 2)
        self.assertFalse(invalid["valid"])
        self.assertIn("unknown configuration field: setings", invalid["errors"])

    def test_configuration_import_updates_settings_without_requiring_secrets(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-config-apply-") as temporary:
            root = Path(temporary)
            store = ManagementSettingsStore(root / "rag-ime.sqlite")
            result = apply_user_configuration(
                {
                    "schemaVersion": USER_CONFIG_SCHEMA_VERSION,
                    "settings": {
                        "context": {"recentInputBaseline": 24},
                        "memory": {"archiveInactiveDays": 90},
                    },
                    "providers": {
                        "instant": {
                            "provider": "mlx",
                            "endpoint": "http://127.0.0.1:8767",
                            "model": "",
                        }
                    },
                },
                settings_store=store,
                support_directory=root / "support",
            )
            settings = store.get_settings(include_sensitive=True)
            predictor_env = (root / "support" / "predictor.env").read_text(encoding="utf-8")

        self.assertEqual(settings["context"]["recentInputBaseline"], 24)
        self.assertEqual(settings["memory"]["archiveInactiveDays"], 90)
        self.assertFalse(result["providers"]["instant"]["secretImportedToKeychain"])
        self.assertNotIn("API_KEY", predictor_env)

    def test_provider_import_can_restore_an_explicitly_empty_model(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-config-empty-model-") as temporary:
            root = Path(temporary)
            support = root / "support"
            support.mkdir()
            predictor_env = support / "predictor.env"
            predictor_env.write_text(
                "RAG_IME_PREDICTOR_PROVIDER=ollama\n"
                "RAG_IME_PREDICTOR_BASE_URL=http://127.0.0.1:11434/v1\n"
                "RAG_IME_PREDICTOR_MODEL=qwen3:0.6b\n",
                encoding="utf-8",
            )
            store = ManagementSettingsStore(root / "rag-ime.sqlite")
            apply_user_configuration(
                {
                    "schemaVersion": USER_CONFIG_SCHEMA_VERSION,
                    "providers": {
                        "instant": {
                            "provider": "mlx",
                            "endpoint": "http://127.0.0.1:8767",
                            "model": "",
                        }
                    },
                },
                settings_store=store,
                support_directory=support,
            )
            text = predictor_env.read_text(encoding="utf-8")

        self.assertIn("RAG_IME_PREDICTOR_PROVIDER=mlx", text)
        self.assertIn("RAG_IME_PREDICTOR_MODEL=\n", text)
        self.assertNotIn("qwen3:0.6b", text)

    def test_yaml_configuration_file_is_hardened_and_imports_secret_to_keychain(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-yaml-config-") as temporary:
            root = Path(temporary)
            config_path = root / "rag-ime.config.yaml"
            config_path.write_text(
                "schemaVersion: rag-ime.user-config.v1\n"
                "settings:\n"
                "  context:\n"
                "    tokenBudget: 4096\n"
                "    reservedOutputTokens: 1024\n"
                "providers:\n"
                "  instant:\n"
                "    provider: openai_compatible\n"
                "    endpoint: https://example.com/v1\n"
                "    model: local-test\n"
                "    apiKey: local-secret\n",
                encoding="utf-8",
            )
            config_path.chmod(0o644)
            store = ManagementSettingsStore(root / "rag-ime.sqlite")

            preview = preview_user_configuration({"path": str(config_path)}, settings_store=store)
            with mock.patch("rag_ime.config_portability.write_keychain_secret") as keychain_write:
                result = apply_user_configuration(
                    {"path": str(config_path)},
                    settings_store=store,
                    support_directory=root / "support",
                )
            settings = store.get_settings(include_sensitive=True)
            predictor_env = (root / "support" / "predictor.env").read_text(encoding="utf-8")
            hardened_mode = config_path.stat().st_mode & 0o777

        self.assertTrue(preview["valid"])
        self.assertTrue(preview["source"]["permissionsHardened"])
        self.assertEqual(hardened_mode, 0o600)
        self.assertEqual(settings["context"]["tokenBudget"], 4096)
        self.assertEqual(settings["context"]["reservedOutputTokens"], 1024)
        self.assertTrue(result["providers"]["instant"]["secretImportedToKeychain"])
        keychain_write.assert_called_once()
        self.assertNotIn("local-secret", predictor_env)

    def test_backup_excludes_provider_secrets_and_sensitive_rime_yaml(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-backup-secrets-") as temporary:
            root = Path(temporary)
            db_path = root / "rag-ime.sqlite"
            core = LocalSqliteCoreClient(db_path)
            core.initialize()
            support = root / "support"
            support.mkdir()
            (support / "predictor.env").write_text(
                "RAG_IME_PREDICTOR_PROVIDER=openai_compatible\n"
                "RAG_IME_PREDICTOR_BASE_URL=https://user:pass@example.com/v1?token=url-secret\n"
                "RAG_IME_PREDICTOR_API_KEY=super-secret-value\n",
                encoding="utf-8",
            )
            rime = root / "Rime"
            rime.mkdir()
            (rime / "safe.custom.yaml").write_text("patch:\n  menu/page_size: 7\n", encoding="utf-8")
            (rime / "private.custom.yaml").write_text("api_key: super-secret-value\n", encoding="utf-8")
            destination = root / "portable.ragime-backup"

            result = export_portable_backup(
                db_path=db_path,
                settings_store=ManagementSettingsStore(db_path),
                destination=destination,
                rime_user_dir=rime,
                support_directory=support,
            )
            with zipfile.ZipFile(destination, "r") as archive:
                names = set(archive.namelist())
                contents = b"\n".join(archive.read(name) for name in names if not name.endswith("/"))
                metadata = json.loads(archive.read("configuration/provider-metadata.json"))
                manifest = json.loads(archive.read("manifest.json"))

        self.assertFalse(result["secretsIncluded"])
        self.assertNotIn(b"super-secret-value", contents)
        self.assertIn("rime/safe.custom.yaml", names)
        self.assertNotIn("rime/private.custom.yaml", names)
        self.assertEqual(metadata["instant"]["endpoint"], "https://example.com/v1")
        self.assertEqual(manifest["rimeFilesSkippedAsSensitive"], ["private.custom.yaml"])

    def test_restore_recovers_database_rime_and_provider_metadata_but_preserves_current_key(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-backup-restore-") as temporary:
            root = Path(temporary)
            db_path = root / "rag-ime.sqlite"
            core = LocalSqliteCoreClient(db_path)
            core.initialize()
            _record(core, "归档前的唯一输入")
            store = ManagementSettingsStore(db_path)
            store.update_settings({"context": {"recentInputBaseline": 24}})
            support = root / "support"
            support.mkdir()
            predictor = support / "predictor.env"
            predictor.write_text(
                "RAG_IME_PREDICTOR_PROVIDER=ollama\n"
                "RAG_IME_PREDICTOR_BASE_URL=http://127.0.0.1:11434/v1\n"
                "RAG_IME_PREDICTOR_API_KEY=source-secret\n",
                encoding="utf-8",
            )
            rime = root / "Rime"
            rime.mkdir()
            rime_file = rime / "weasel.custom.yaml"
            rime_file.write_text("patch:\n  menu/page_size: 7\n", encoding="utf-8")
            archive_path = root / "portable.ragime-backup"
            export_portable_backup(
                db_path=db_path,
                settings_store=store,
                destination=archive_path,
                rime_user_dir=rime,
                support_directory=support,
            )

            _record(core, "归档后新增、恢复时应移除的输入")
            store.update_settings({"context": {"recentInputBaseline": 40}})
            predictor.write_text(
                "RAG_IME_PREDICTOR_PROVIDER=mlx\n"
                "RAG_IME_PREDICTOR_BASE_URL=http://127.0.0.1:8767\n"
                "RAG_IME_PREDICTOR_API_KEY=current-secret\n",
                encoding="utf-8",
            )
            rime_file.write_text("patch:\n  menu/page_size: 9\n", encoding="utf-8")
            preview = preview_portable_restore(archive_path=archive_path)

            result = restore_portable_backup(
                archive_path=archive_path,
                db_path=db_path,
                settings_store=store,
                restore_token=preview["restoreToken"],
                confirm_text="RESTORE RAG-IME",
                rime_user_dir=rime,
                support_directory=support,
            )
            with core._connect() as conn:
                input_count = int(conn.execute("SELECT COUNT(*) FROM input_events").fetchone()[0])
            restored_settings = store.get_settings(include_sensitive=True)
            restored_env = predictor.read_text(encoding="utf-8")
            restored_rime = rime_file.read_text(encoding="utf-8")
            rollback_exists = Path(result["rollbackPath"]).exists()

        self.assertEqual(input_count, 1)
        self.assertEqual(restored_settings["context"]["recentInputBaseline"], 24)
        self.assertIn("RAG_IME_PREDICTOR_PROVIDER=ollama", restored_env)
        self.assertIn("RAG_IME_PREDICTOR_BASE_URL=http://127.0.0.1:11434/v1", restored_env)
        self.assertIn("RAG_IME_PREDICTOR_API_KEY=current-secret", restored_env)
        self.assertIn("page_size: 7", restored_rime)
        self.assertIn("instant", result["providerMetadataRestored"])
        self.assertTrue(rollback_exists)

    def test_restore_rolls_database_rime_and_provider_files_back_on_failure(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-restore-rollback-") as temporary:
            root = Path(temporary)
            db_path = root / "rag-ime.sqlite"
            core = LocalSqliteCoreClient(db_path)
            core.initialize()
            _record(core, "备份中的输入")
            store = ManagementSettingsStore(db_path)
            support = root / "support"
            support.mkdir()
            predictor = support / "predictor.env"
            predictor.write_text("RAG_IME_PREDICTOR_PROVIDER=ollama\n", encoding="utf-8")
            rime = root / "Rime"
            rime.mkdir()
            rime_file = rime / "weasel.custom.yaml"
            rime_file.write_text("patch:\n  menu/page_size: 7\n", encoding="utf-8")
            archive_path = root / "portable.ragime-backup"
            export_portable_backup(
                db_path=db_path,
                settings_store=store,
                destination=archive_path,
                rime_user_dir=rime,
                support_directory=support,
            )
            _record(core, "当前输入必须在失败后保留")
            predictor.write_text("RAG_IME_PREDICTOR_PROVIDER=mlx\n", encoding="utf-8")
            rime_file.write_text("patch:\n  menu/page_size: 9\n", encoding="utf-8")
            preview = preview_portable_restore(archive_path=archive_path)

            with mock.patch(
                "rag_ime.config_portability._restore_provider_metadata",
                side_effect=RuntimeError("forced provider failure"),
            ):
                with self.assertRaisesRegex(RuntimeError, "forced provider failure"):
                    restore_portable_backup(
                        archive_path=archive_path,
                        db_path=db_path,
                        settings_store=store,
                        restore_token=preview["restoreToken"],
                        confirm_text="RESTORE RAG-IME",
                        rime_user_dir=rime,
                        support_directory=support,
                    )
            with core._connect() as conn:
                input_count = int(conn.execute("SELECT COUNT(*) FROM input_events").fetchone()[0])
            current_rime = rime_file.read_text(encoding="utf-8")
            current_predictor = predictor.read_text(encoding="utf-8")

        self.assertEqual(input_count, 2)
        self.assertIn("page_size: 9", current_rime)
        self.assertIn("RAG_IME_PREDICTOR_PROVIDER=mlx", current_predictor)


def _record(core: LocalSqliteCoreClient, text: str) -> None:
    core.record_event(
        InputEvent(
            event_id=None,
            created_at_ms=None,
            source="manual",
            committed_text=text,
            privacy_disposition="allowed",
        )
    )


if __name__ == "__main__":
    unittest.main()
