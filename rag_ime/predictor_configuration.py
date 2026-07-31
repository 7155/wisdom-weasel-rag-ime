from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Mapping

from .model_profiles import (
    DEFAULT_MODEL_PROFILES,
    canonical_runtime_profile_id,
    profile_by_id,
)
from .model_registry import (
    ModelDeployment,
    ModelRegistry,
    default_model_registry_path,
    fingerprint_model_artifact,
    infer_model_runtime,
    normalize_model_runtime,
)
from .settings_store import ManagementSettingsStore


PREDICTOR_SETTING_KEYS = frozenset(
    {
        "models.modelId",
        "models.hot",
        "models.path",
        "models.promptMode",
        "models.maxTokens",
        "models.temperature",
        "models.topP",
    }
)
_ALLOWED_HOT_PROFILES = frozenset(
    profile.id for profile in DEFAULT_MODEL_PROFILES if profile.lane == "hot"
)
_ALLOWED_PROMPT_MODES = frozenset({"base-completion", "chat-json"})


@dataclass(frozen=True)
class PredictorConfiguration:
    model_id: str
    model_path: str
    profile_id: str
    prompt_mode: str
    max_tokens: int
    temperature: float
    top_p: float
    registry_revision: int

    def payload(self) -> dict[str, object]:
        return {
            "modelId": self.model_id,
            "modelPath": self.model_path,
            "profileId": self.profile_id,
            "promptMode": self.prompt_mode,
            "maxTokens": self.max_tokens,
            "temperature": self.temperature,
            "topP": self.top_p,
            "registryRevision": self.registry_revision,
        }


def resolve_predictor_configuration(
    settings: Mapping[str, object],
    *,
    registry: ModelRegistry,
    require_model_exists: bool = True,
) -> PredictorConfiguration:
    models = settings.get("models")
    desired = dict(models) if isinstance(models, Mapping) else {}
    requested_model_id = str(desired.get("modelId") or "").strip()
    deployment = _deployment_by_id(registry, requested_model_id) if requested_model_id else registry.resolve(
        lane="hot",
        require_exists=False,
    )
    if deployment is None:
        if requested_model_id:
            raise ValueError(f"registered hot model was not found: {requested_model_id}")
        raise ValueError("model registry has no active hot model")
    if deployment.lane != "hot":
        raise ValueError(f"model is not registered for the hot lane: {deployment.model_id}")
    runtime = normalize_model_runtime(
        deployment.runtime or infer_model_runtime(deployment.format)
    )
    if runtime != "mlx":
        raise ValueError("local predictor settings currently require an MLX hot model")

    model_path = str(desired.get("path") or deployment.path).strip()
    path = Path(model_path).expanduser()
    if not path.is_absolute():
        raise ValueError("local predictor model path must be absolute")
    if require_model_exists and not path.is_dir():
        raise ValueError(f"local predictor model directory does not exist: {path}")
    registered_path = Path(deployment.path).expanduser().resolve(strict=False)
    requested_path = path.resolve(strict=False)
    if (
        require_model_exists
        and requested_path != registered_path
        and not (requested_path / "config.json").is_file()
    ):
        raise ValueError("local predictor model directory must contain config.json")

    profile_id = canonical_runtime_profile_id(
        str(desired.get("hot") or deployment.profile)
    )
    if profile_id not in _ALLOWED_HOT_PROFILES:
        raise ValueError(f"unsupported hot predictor profile: {profile_id}")
    registered_profile_id = canonical_runtime_profile_id(deployment.profile)
    if profile_id != registered_profile_id:
        raise ValueError(
            f"models.hot must match registered model profile {registered_profile_id}"
        )
    profile = profile_by_id(profile_id)
    prompt_mode = str(
        desired.get("promptMode") or deployment.prompt_mode or profile.prompt_mode
    ).strip()
    if prompt_mode not in _ALLOWED_PROMPT_MODES:
        raise ValueError(f"unsupported predictor prompt mode: {prompt_mode}")
    if prompt_mode != profile.prompt_mode:
        raise ValueError(
            f"{profile_id} requires promptMode={profile.prompt_mode}"
        )

    max_tokens = _bounded_int(
        desired.get("maxTokens"),
        default=deployment.max_tokens or profile.max_tokens,
        minimum=1,
        maximum=64,
        field="models.maxTokens",
    )
    temperature = _bounded_float(
        desired.get("temperature"),
        default=(
            profile.temperature
            if deployment.temperature is None
            else deployment.temperature
        ),
        minimum=0.0,
        maximum=2.0,
        field="models.temperature",
    )
    top_p = _bounded_float(
        desired.get("topP"),
        default=profile.top_p if deployment.top_p is None else deployment.top_p,
        minimum=0.05,
        maximum=1.0,
        field="models.topP",
    )
    return PredictorConfiguration(
        model_id=deployment.model_id,
        model_path=str(path.resolve(strict=False)),
        profile_id=profile_id,
        prompt_mode=prompt_mode,
        max_tokens=max_tokens,
        temperature=temperature,
        top_p=top_p,
        registry_revision=registry.revision,
    )


def active_predictor_configuration(
    registry: ModelRegistry,
    *,
    require_model_exists: bool = False,
) -> PredictorConfiguration:
    deployment = registry.resolve(lane="hot", require_exists=require_model_exists)
    if deployment is None:
        raise ValueError("model registry has no active hot model")
    profile_id = canonical_runtime_profile_id(deployment.profile)
    profile = profile_by_id(profile_id)
    return PredictorConfiguration(
        model_id=deployment.model_id,
        model_path=str(Path(deployment.path).expanduser().resolve(strict=False)),
        profile_id=profile_id,
        prompt_mode=deployment.prompt_mode or profile.prompt_mode,
        max_tokens=deployment.max_tokens or profile.max_tokens,
        temperature=(
            profile.temperature
            if deployment.temperature is None
            else float(deployment.temperature)
        ),
        top_p=profile.top_p if deployment.top_p is None else float(deployment.top_p),
        registry_revision=registry.revision,
    )


def apply_predictor_configuration(
    settings: Mapping[str, object],
    *,
    registry: ModelRegistry,
) -> PredictorConfiguration:
    desired = resolve_predictor_configuration(
        settings,
        registry=registry,
        require_model_exists=True,
    )
    deployment = _deployment_by_id(registry, desired.model_id)
    if deployment is None:
        raise ValueError(f"registered hot model was not found: {desired.model_id}")
    path_changed = Path(deployment.path).expanduser().resolve(strict=False) != Path(
        desired.model_path
    ).resolve(strict=False)
    fingerprint = (
        fingerprint_model_artifact(desired.model_path)
        if path_changed
        else deployment.fingerprint
    )
    registry.register(
        replace(
            deployment,
            path=desired.model_path,
            fingerprint=fingerprint,
            profile=desired.profile_id,
            prompt_mode=desired.prompt_mode,
            max_tokens=desired.max_tokens,
            temperature=desired.temperature,
            top_p=desired.top_p,
            lane="hot",
        ),
        activate=True,
    )
    return active_predictor_configuration(registry, require_model_exists=True)


def configuration_matches(
    desired: PredictorConfiguration,
    actual: PredictorConfiguration,
) -> bool:
    return (
        desired.model_id == actual.model_id
        and Path(desired.model_path).resolve(strict=False)
        == Path(actual.model_path).resolve(strict=False)
        and desired.profile_id == actual.profile_id
        and desired.prompt_mode == actual.prompt_mode
        and desired.max_tokens == actual.max_tokens
        and abs(desired.temperature - actual.temperature) <= 1e-9
        and abs(desired.top_p - actual.top_p) <= 1e-9
    )


def _deployment_by_id(
    registry: ModelRegistry,
    model_id: str,
) -> ModelDeployment | None:
    normalized = str(model_id or "").strip()
    return next(
        (item for item in registry.deployments if item.model_id == normalized),
        None,
    )


def _bounded_int(
    value: object,
    *,
    default: int,
    minimum: int,
    maximum: int,
    field: str,
) -> int:
    try:
        parsed = int(default if value is None else value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an integer") from exc
    if parsed < minimum or parsed > maximum:
        raise ValueError(f"{field} must be between {minimum} and {maximum}")
    return parsed


def _bounded_float(
    value: object,
    *,
    default: float,
    minimum: float,
    maximum: float,
    field: str,
) -> float:
    try:
        parsed = float(default if value is None else value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a number") from exc
    if not math.isfinite(parsed):
        raise ValueError(f"{field} must be finite")
    if parsed < minimum or parsed > maximum:
        raise ValueError(f"{field} must be between {minimum} and {maximum}")
    return parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Resolve or apply the Control Center local predictor configuration."
    )
    parser.add_argument(
        "command",
        choices=("preview", "apply", "status"),
    )
    parser.add_argument("--db", required=True)
    parser.add_argument(
        "--registry",
        default=str(default_model_registry_path()),
    )
    args = parser.parse_args(argv)

    store = ManagementSettingsStore(args.db)
    settings = store.get_settings(include_sensitive=True)
    registry = ModelRegistry.load(args.registry)
    desired = resolve_predictor_configuration(settings, registry=registry)
    actual_before = active_predictor_configuration(registry)
    applied = args.command == "apply"
    actual = (
        apply_predictor_configuration(settings, registry=registry)
        if applied
        else actual_before
    )
    payload = {
        "schemaVersion": "rag-ime.predictor-configuration.v1",
        "ok": True,
        "applied": applied,
        "pending": not configuration_matches(desired, actual),
        "desired": desired.payload(),
        "active": actual.payload(),
        "registryPath": str(registry.path),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
