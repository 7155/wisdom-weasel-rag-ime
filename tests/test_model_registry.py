from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from rag_ime.model_registry import (
    MODEL_REGISTRY_SCHEMA_VERSION,
    ModelDeployment,
    ModelRegistry,
    default_model_registry_path,
    fingerprint_model,
    fingerprint_model_artifact,
    fingerprint_tokenizer_artifact,
    infer_model_runtime,
    is_loopback_endpoint,
    main,
)


class ModelRegistryTests(unittest.TestCase):
    def test_register_persists_one_active_model_per_lane(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-model-registry-") as tmp:
            root = Path(tmp)
            first = _model_dir(root / "first", architecture="MiniMindForCausalLM", size=17)
            second = _model_dir(root / "second", architecture="MiniMindForCausalLM", size=29)
            registry_path = root / "models.json"
            registry = ModelRegistry.load(registry_path)

            registry.register(_deployment("minimind-v1", first))
            registry.register(_deployment("minimind-v2", second))

            reloaded = ModelRegistry.load(registry_path)
            active = reloaded.resolve(lane="hot")
            self.assertIsNotNone(active)
            self.assertEqual(active.model_id, "minimind-v2")
            self.assertEqual(sum(item.active for item in reloaded.deployments), 1)
            payload = json.loads(registry_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["schemaVersion"], MODEL_REGISTRY_SCHEMA_VERSION)
            self.assertEqual(payload["revision"], 2)
            active_payload = next(item for item in payload["models"] if item["active"])
            self.assertEqual(len(active_payload["fingerprint"].removeprefix("sha256:")), 64)
            self.assertEqual(active_payload["fingerprintAlgorithm"], "rag-ime-model-artifact-sha256-v1")

    def test_register_normalizes_lane_before_deactivating_previous_model(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-model-registry-lane-") as tmp:
            root = Path(tmp)
            first = _model_dir(root / "first", architecture="MiniMindForCausalLM", size=17)
            second = _model_dir(root / "second", architecture="MiniMindForCausalLM", size=29)
            registry_path = root / "models.json"
            registry = ModelRegistry.load(registry_path)
            registry.register(_deployment("first", first))

            registry.register(replace(_deployment("second", second), lane=" HOT "))

            reloaded = ModelRegistry.load(registry_path)
            active = reloaded.resolve(lane="hot")
            self.assertIsNotNone(active)
            self.assertEqual(active.model_id, "second")
            self.assertEqual(sum(item.active for item in reloaded.deployments), 1)

    def test_resolve_ignores_active_deployment_when_model_is_missing(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-model-registry-missing-") as tmp:
            registry = ModelRegistry(
                Path(tmp) / "models.json",
                (
                    ModelDeployment(
                        model_id="missing",
                        path=str(Path(tmp) / "missing"),
                        format="mlx",
                        fingerprint="sha256:missing",
                        profile="minimind_ime_v2",
                    ),
                ),
            )

            self.assertIsNone(registry.resolve())
            self.assertEqual(registry.resolve(require_exists=False).model_id, "missing")

    def test_fingerprint_changes_with_model_metadata(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-model-fingerprint-") as tmp:
            model = _model_dir(Path(tmp) / "model", architecture="MiniMindForCausalLM", size=10)
            first = fingerprint_model(model)
            (model / "model.safetensors").write_bytes(b"x" * 11)
            second = fingerprint_model(model)

            self.assertRegex(first, r"^sha256:[0-9a-f]{16}$")
            self.assertNotEqual(first, second)

    def test_qualification_fingerprint_uses_full_sha256(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-model-full-fingerprint-") as tmp:
            model = _model_dir(Path(tmp) / "model", architecture="MiniMindForCausalLM", size=10)
            fingerprint = fingerprint_model_artifact(model)

        self.assertEqual(len(fingerprint.removeprefix("sha256:")), 64)

    def test_fingerprint_changes_when_weights_change_without_changing_file_size(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-model-fingerprint-content-") as tmp:
            model = _model_dir(Path(tmp) / "model", architecture="MiniMindForCausalLM", size=10)
            first = fingerprint_model(model)
            (model / "model.safetensors").write_bytes(b"y" * 10)

            second = fingerprint_model(model)

            self.assertNotEqual(first, second)

    def test_full_fingerprint_covers_runtime_tokenizer_metadata(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-model-tokenizer-fingerprint-") as tmp:
            model = _model_dir(Path(tmp) / "model", architecture="MiniMindForCausalLM", size=10)
            (model / "tokenizer.json").write_text('{"version":1}', encoding="utf-8")
            (model / "special_tokens_map.json").write_text('{"eos_token":"one"}', encoding="utf-8")
            model_before = fingerprint_model_artifact(model)
            tokenizer_before = fingerprint_tokenizer_artifact(model)

            (model / "special_tokens_map.json").write_text('{"eos_token":"two"}', encoding="utf-8")

            self.assertNotEqual(model_before, fingerprint_model_artifact(model))
            self.assertNotEqual(tokenizer_before, fingerprint_tokenizer_artifact(model))

    def test_full_fingerprint_rejects_runtime_file_symlink_escape(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-model-fingerprint-symlink-") as tmp:
            root = Path(tmp)
            model = _model_dir(root / "model", architecture="MiniMindForCausalLM", size=10)
            outside = root / "outside.json"
            outside.write_text("{}", encoding="utf-8")
            (model / "special_tokens_map.json").symlink_to(outside)

            with self.assertRaisesRegex(ValueError, "escapes"):
                fingerprint_model_artifact(model)

    def test_cli_register_and_resolve_field(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-model-registry-cli-") as tmp:
            root = Path(tmp)
            model = _model_dir(root / "portable", architecture="MiniMindForCausalLM", size=13)
            registry_path = root / "models.json"

            code = main(
                [
                    "--registry",
                    str(registry_path),
                    "register",
                    "--model-id",
                    "minimind-ime-v2-q8",
                    "--path",
                    str(model),
                    "--profile",
                    "minimind_ime_v2",
                    "--prompt-mode",
                    "base-completion",
                ]
            )

            self.assertEqual(code, 0)
            self.assertEqual(main(["--registry", str(registry_path), "resolve", "--field", "path"]), 0)

    def test_default_registry_lives_in_application_support(self) -> None:
        path = default_model_registry_path("/Users/example")
        self.assertEqual(path, Path("/Users/example/Library/Application Support/RagIme/models.json"))

    def test_v1_registry_infers_mlx_runtime_and_upgrades_on_save(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-model-registry-v1-") as tmp:
            root = Path(tmp)
            model = _model_dir(root / "model", architecture="Qwen3ForCausalLM", size=8)
            registry_path = root / "models.json"
            registry_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": "rag-ime.model-registry.v1",
                        "models": [
                            {
                                "modelId": "legacy-mlx",
                                "path": str(model),
                                "format": "mlx",
                                "profile": "minimind_ime_v2",
                                "active": True,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            registry = ModelRegistry.load(registry_path)
            self.assertEqual(registry.resolve().runtime, "mlx")
            registry.save()
            self.assertEqual(
                json.loads(registry_path.read_text(encoding="utf-8"))["schemaVersion"],
                MODEL_REGISTRY_SCHEMA_VERSION,
            )

    def test_hot_external_runtime_requires_loopback_endpoint(self) -> None:
        registry = ModelRegistry(
            "/tmp/models.json",
            (
                ModelDeployment(
                    model_id="remote-hot",
                    path="model",
                    format="remote",
                    fingerprint="remote",
                    profile="custom",
                    runtime="openai-compatible",
                    endpoint="https://example.com/v1",
                    model_name="model",
                ),
            ),
        )

        with self.assertRaisesRegex(ValueError, "loopback"):
            registry.validate()

    def test_remote_runtime_accepts_model_name_without_fake_artifact_path(self) -> None:
        registry = ModelRegistry(
            "/tmp/models.json",
            (
                ModelDeployment(
                    model_id="local-openai",
                    path="",
                    format="remote",
                    fingerprint="runtime:openai-compatible:test",
                    profile="custom",
                    runtime="openai-compatible",
                    endpoint="http://127.0.0.1:8080",
                    model_name="served-model",
                ),
            ),
        )

        registry.validate()

    def test_runtime_helpers_do_not_confuse_artifact_format_with_backend(self) -> None:
        self.assertEqual(infer_model_runtime("mlx"), "mlx")
        self.assertEqual(infer_model_runtime("gguf"), "openai-compatible")
        self.assertTrue(is_loopback_endpoint("http://127.0.0.1:8080/v1"))
        self.assertFalse(is_loopback_endpoint("https://api.example.com/v1"))

    def test_loopback_guard_rejects_dns_prefixes_and_non_http_schemes(self) -> None:
        self.assertFalse(is_loopback_endpoint("http://127.attacker.example:8080/v1"))
        self.assertFalse(is_loopback_endpoint("file://127.0.0.1/tmp/predictor.json"))
        self.assertTrue(is_loopback_endpoint("http://127.0.0.42:8080/v1"))


def _deployment(model_id: str, path: Path) -> ModelDeployment:
    return ModelDeployment(
        model_id=model_id,
        path=str(path),
        format="mlx",
        fingerprint="",
        profile="minimind_ime_v2",
        prompt_mode="base-completion",
    )


def _model_dir(path: Path, *, architecture: str, size: int) -> Path:
    path.mkdir(parents=True)
    (path / "config.json").write_text(json.dumps({"architectures": [architecture]}), encoding="utf-8")
    (path / "model.safetensors").write_bytes(b"x" * size)
    return path


if __name__ == "__main__":
    unittest.main()
