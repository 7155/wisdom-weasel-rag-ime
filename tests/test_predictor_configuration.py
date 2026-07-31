from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rag_ime.debug_server import (
    _predictor_probe_matches_configuration,
    _predictor_status_matches_configuration,
)
from rag_ime.model_registry import ModelDeployment, ModelRegistry
from rag_ime.predictor_configuration import (
    active_predictor_configuration,
    apply_predictor_configuration,
    configuration_matches,
    resolve_predictor_configuration,
)
from rag_ime.settings_store import ManagementSettingsStore


class PredictorConfigurationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-predictor-settings-")
        self.root = Path(self.tmp.name)
        self.model_path = self.root / "minimind-ime-v2"
        self.model_path.mkdir()
        (self.model_path / "config.json").write_text(
            '{"model_type":"minimind"}',
            encoding="utf-8",
        )
        (self.model_path / "tokenizer.json").write_text("{}", encoding="utf-8")
        self.registry_path = self.root / "models.json"
        self.registry = ModelRegistry(self.registry_path)
        self.registry.register(
            ModelDeployment(
                model_id="minimind-ime-v2",
                path=str(self.model_path),
                format="mlx",
                fingerprint="",
                profile="minimind_ime_v2",
                runtime="mlx",
                lane="hot",
                prompt_mode="base-completion",
            ),
            activate=True,
        )
        self.store = ManagementSettingsStore(self.root / "rag-ime.sqlite")
        self.store.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_resolve_and_apply_updates_the_active_registry_contract(self) -> None:
        self.store.update_settings(
            {
                "models.modelId": "minimind-ime-v2",
                "models.path": str(self.model_path),
                "models.hot": "minimind_ime_v2",
                "models.promptMode": "base-completion",
                "models.maxTokens": 12,
                "models.temperature": 0.2,
                "models.topP": 0.9,
            }
        )
        settings = self.store.get_settings(include_sensitive=True)

        desired = resolve_predictor_configuration(settings, registry=self.registry)
        before = active_predictor_configuration(self.registry)
        self.assertFalse(configuration_matches(desired, before))

        applied = apply_predictor_configuration(settings, registry=self.registry)
        reloaded = ModelRegistry.load(self.registry_path)
        active = active_predictor_configuration(reloaded)

        self.assertTrue(configuration_matches(desired, applied))
        self.assertTrue(configuration_matches(desired, active))
        self.assertEqual(active.max_tokens, 12)
        self.assertEqual(active.temperature, 0.2)
        self.assertEqual(active.top_p, 0.9)
        self.assertGreater(active.registry_revision, before.registry_revision)

    def test_blank_model_id_and_path_inherit_the_active_registration(self) -> None:
        desired = resolve_predictor_configuration(
            self.store.get_settings(include_sensitive=True),
            registry=self.registry,
        )

        self.assertEqual(desired.model_id, "minimind-ime-v2")
        self.assertEqual(desired.model_path, str(self.model_path.resolve()))
        self.assertEqual(desired.profile_id, "minimind_ime_v2")
        self.assertEqual(desired.prompt_mode, "base-completion")

    def test_sidecar_and_mlx_health_must_match_the_active_generation_contract(self) -> None:
        active = active_predictor_configuration(self.registry)
        sidecar = {
            "configured": True,
            "model": active.model_path,
            "providerProfile": active.profile_id,
            "promptMode": active.prompt_mode,
            "maxTokens": active.max_tokens,
            "temperature": active.temperature,
            "topP": active.top_p,
        }
        probe = {
            "ok": True,
            "modelLoaded": True,
            "model": active.model_path,
            "runtimeConfig": {
                "profileId": active.profile_id,
                "promptMode": active.prompt_mode,
                "maxTokens": active.max_tokens,
                "temperature": active.temperature,
                "topP": active.top_p,
            },
        }

        self.assertTrue(_predictor_status_matches_configuration(sidecar, active))
        self.assertTrue(_predictor_probe_matches_configuration(probe, active))
        sidecar["topP"] = 0.5
        probe["runtimeConfig"]["maxTokens"] = active.max_tokens + 1  # type: ignore[index]
        self.assertFalse(_predictor_status_matches_configuration(sidecar, active))
        self.assertFalse(_predictor_probe_matches_configuration(probe, active))

    def test_rejects_unknown_model_missing_path_and_incompatible_minimind_prompt(self) -> None:
        settings = self.store.get_settings(include_sensitive=True)
        settings["models"]["modelId"] = "unknown"  # type: ignore[index]
        with self.assertRaisesRegex(ValueError, "was not found"):
            resolve_predictor_configuration(settings, registry=self.registry)

        settings["models"].update(  # type: ignore[index]
            {
                "modelId": "minimind-ime-v2",
                "path": str(self.root / "missing"),
            }
        )
        with self.assertRaisesRegex(ValueError, "does not exist"):
            resolve_predictor_configuration(settings, registry=self.registry)

        settings["models"].update(  # type: ignore[index]
            {
                "path": str(self.model_path),
                "promptMode": "chat-json",
            }
        )
        with self.assertRaisesRegex(ValueError, "requires promptMode=base-completion"):
            resolve_predictor_configuration(settings, registry=self.registry)


if __name__ == "__main__":
    unittest.main()
