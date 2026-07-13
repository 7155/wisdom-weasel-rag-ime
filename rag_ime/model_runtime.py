from __future__ import annotations

import argparse
import json
import os
import plistlib
import shlex
import shutil
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .keychain_secrets import MODEL_INSTANT_ACCOUNT, MODEL_KEYCHAIN_SERVICE, read_keychain_secret

from .model_registry import (
    ModelDeployment,
    ModelRegistry,
    default_model_registry_path,
    fingerprint_model_artifact,
    infer_model_runtime,
    is_loopback_endpoint,
    normalize_model_endpoint,
    normalize_model_runtime,
)


MODEL_RUNTIME_PLAN_SCHEMA_VERSION = "rag-ime.model-runtime-plan.v1"
_NO_PROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


@dataclass(frozen=True)
class ModelRuntimePlan:
    deployment: ModelDeployment
    runtime: str
    provider_env: dict[str, str]
    managed_service: str
    lifecycle: str
    expected_capabilities: dict[str, bool]
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def ready(self) -> bool:
        return not self.errors

    def payload(self) -> dict[str, Any]:
        return {
            "schemaVersion": MODEL_RUNTIME_PLAN_SCHEMA_VERSION,
            "ready": self.ready,
            "runtime": self.runtime,
            "model": self.deployment.payload(),
            "providerEnv": dict(self.provider_env),
            "managedService": self.managed_service,
            "lifecycle": self.lifecycle,
            "expectedCapabilities": dict(self.expected_capabilities),
            "errors": list(self.errors),
            "warnings": list(self.warnings),
        }


def plan_model_runtime(deployment: ModelDeployment) -> ModelRuntimePlan:
    runtime = normalize_model_runtime(deployment.runtime or infer_model_runtime(deployment.format))
    endpoint = normalize_model_endpoint(runtime, deployment.endpoint)
    errors: list[str] = []
    warnings: list[str] = []
    provider_env = {
        "RAG_IME_MODEL_ID": deployment.model_id,
        "RAG_IME_MODEL_FINGERPRINT": deployment.fingerprint,
        "RAG_IME_PREDICTOR_PROFILE": deployment.profile,
        "RAG_IME_PREDICTOR_PROMPT_MODE": deployment.prompt_mode,
    }
    managed_service = ""
    lifecycle = "external"
    expected = {
        "residentModel": False,
        "streaming": False,
        "batchCandidates": False,
        "serverTiming": False,
    }

    if runtime == "mlx":
        model_path = Path(deployment.path).expanduser()
        if not model_path.is_dir():
            errors.append(f"mlx model directory not found: {model_path}")
        mlx_endpoint = endpoint or "http://127.0.0.1:8767"
        mlx_bind = urllib.parse.urlsplit(mlx_endpoint)
        if not is_loopback_endpoint(mlx_endpoint):
            errors.append("managed MLX endpoint must be loopback HTTP")
        elif mlx_bind.scheme != "http" or mlx_bind.path not in {"", "/"}:
            errors.append("managed MLX endpoint must be an HTTP origin without a path")
        mlx_host = mlx_bind.hostname or "127.0.0.1"
        try:
            mlx_port = mlx_bind.port or 8767
        except ValueError:
            mlx_port = 8767
        provider_env.update(
            {
                "RAG_IME_PREDICTOR_PROVIDER": "mlx",
                "RAG_IME_PREDICTOR_BASE_URL": mlx_endpoint,
                "RAG_IME_PREDICTOR_MODEL": str(model_path),
                "RAG_IME_MLX_MODEL": str(model_path),
                "RAG_IME_MLX_PROFILE": deployment.profile,
                "RAG_IME_MLX_PROMPT_MODE": deployment.prompt_mode,
                "RAG_IME_MLX_HOST": mlx_host,
                "RAG_IME_MLX_PORT": str(mlx_port),
            }
        )
        managed_service = "com.rag-ime.mlx-predictor"
        lifecycle = "managed-launch-agent"
        expected.update(
            {
                "residentModel": True,
                "streaming": True,
                "batchCandidates": True,
                "serverTiming": True,
            }
        )
    elif runtime == "ollama":
        endpoint = endpoint or "http://127.0.0.1:11434"
        model_name = deployment.model_name or deployment.path
        if not is_loopback_endpoint(endpoint):
            errors.append("realtime Ollama endpoint must be loopback")
        if not model_name:
            errors.append("Ollama modelName is required")
        if shutil.which("ollama") is None:
            warnings.append("ollama executable is not installed")
        provider_env.update(
            {
                "RAG_IME_PREDICTOR_PROVIDER": "ollama",
                "RAG_IME_PREDICTOR_BASE_URL": endpoint,
                "RAG_IME_PREDICTOR_MODEL": model_name,
                "RAG_IME_PREDICTOR_STREAM_FIRST": "1",
            }
        )
        lifecycle = "external-ollama"
        expected.update({"residentModel": True, "streaming": True})
    elif runtime == "openai-compatible":
        model_name = deployment.model_name or deployment.path
        if not endpoint:
            errors.append("OpenAI-compatible endpoint is required")
        elif not is_loopback_endpoint(endpoint):
            errors.append("realtime OpenAI-compatible endpoint must be loopback")
        if not model_name:
            errors.append("OpenAI-compatible modelName is required")
        provider_env.update(
            {
                "RAG_IME_PREDICTOR_PROVIDER": "openai-compatible",
                "RAG_IME_PREDICTOR_BASE_URL": endpoint,
                "RAG_IME_PREDICTOR_MODEL": model_name,
            }
        )
        lifecycle = "external-openai-compatible"
    else:
        errors.append(f"unsupported model runtime: {runtime or '<empty>'}")

    return ModelRuntimePlan(
        deployment=deployment,
        runtime=runtime,
        provider_env={key: value for key, value in provider_env.items() if value != ""},
        managed_service=managed_service,
        lifecycle=lifecycle,
        expected_capabilities=expected,
        errors=tuple(errors),
        warnings=tuple(warnings),
    )


def probe_runtime_endpoint(plan: ModelRuntimePlan, *, timeout_s: float = 0.5) -> dict[str, Any]:
    if not plan.ready:
        return {"ok": False, "error": "runtime_plan_invalid", "errors": list(plan.errors)}
    base_url = plan.provider_env.get("RAG_IME_PREDICTOR_BASE_URL", "").rstrip("/")
    if plan.runtime == "mlx":
        candidates = (f"{base_url}/health",)
    elif plan.runtime == "ollama":
        candidates = (f"{base_url}/api/tags",)
    else:
        candidates = (f"{base_url}/v1/models", f"{base_url}/models")
    probe_env = _probe_credential_environment()
    headers: dict[str, str] = {}
    if plan.runtime == "openai-compatible":
        api_key = probe_env.get("RAG_IME_PREDICTOR_API_KEY", "").strip()
        if not api_key:
            api_key = read_keychain_secret(MODEL_KEYCHAIN_SERVICE, MODEL_INSTANT_ACCOUNT)
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        try:
            extra_headers = json.loads(probe_env.get("RAG_IME_PREDICTOR_EXTRA_HEADERS_JSON", "{}"))
        except json.JSONDecodeError:
            extra_headers = {}
        if isinstance(extra_headers, dict):
            headers.update({str(key): str(value) for key, value in extra_headers.items() if value is not None})
    last_error = ""
    for url in candidates:
        try:
            request = urllib.request.Request(url, headers=headers, method="GET")
            with _NO_PROXY_OPENER.open(request, timeout=max(0.05, timeout_s)) as response:
                payload = json.loads(response.read().decode("utf-8"))
            semantic_error = _runtime_probe_semantic_error(plan, payload)
            if semantic_error:
                last_error = semantic_error
                continue
            return {
                "ok": True,
                "url": url,
                "payloadType": type(payload).__name__,
                "modelIdentity": _runtime_probe_identity(plan, payload),
            }
        except urllib.error.HTTPError as exc:
            last_error = exc.__class__.__name__
            exc.close()
        except Exception as exc:  # network probes return sanitized class names only
            last_error = exc.__class__.__name__
    return {"ok": False, "error": last_error or "endpoint_unreachable", "urls": list(candidates)}


def _runtime_probe_semantic_error(plan: ModelRuntimePlan, payload: object) -> str:
    if not isinstance(payload, dict):
        return "invalid_health_payload"
    selected_model = plan.provider_env.get("RAG_IME_PREDICTOR_MODEL", "").strip()
    if plan.runtime == "mlx":
        if payload.get("ok") is not True or payload.get("modelLoaded") is not True:
            return "model_not_loaded"
        configured_path = Path(plan.deployment.path).expanduser().resolve()
        runtime_path = Path(str(payload.get("model") or "")).expanduser().resolve()
        if not configured_path.is_dir() or not runtime_path.is_dir():
            return "model_identity_unavailable"
        configured_full = fingerprint_model_artifact(configured_path)
        runtime_fingerprint = str(payload.get("modelFingerprint") or "")
        if runtime_fingerprint:
            if not _fingerprint_matches(configured_full, runtime_fingerprint):
                return "loaded_model_fingerprint_mismatch"
        elif runtime_path != configured_path:
            return "loaded_model_path_mismatch"
        if runtime_path != configured_path and fingerprint_model_artifact(runtime_path) != configured_full:
            return "loaded_model_artifact_mismatch"
        registered_fingerprint = str(plan.deployment.fingerprint or "")
        if _is_full_sha256_fingerprint(registered_fingerprint) and not _fingerprint_matches(
            configured_full,
            registered_fingerprint,
        ):
            return "registered_model_fingerprint_mismatch"
        return ""
    if plan.runtime == "ollama":
        models = payload.get("models")
        if not isinstance(models, list):
            return "invalid_model_list"
        available = {
            str(item.get("name") or item.get("model") or "").strip()
            for item in models
            if isinstance(item, dict)
        }
        if not _runtime_model_is_available(selected_model, available):
            return "selected_model_not_available"
        return ""
    data = payload.get("data")
    if data is None:
        data = payload.get("models")
    if not isinstance(data, list):
        return "invalid_model_list"
    available = {
        str(item.get("id") or item.get("name") or item.get("model") or "").strip()
        for item in data
        if isinstance(item, dict)
    }
    if selected_model and not _runtime_model_is_available(selected_model, available):
        return "selected_model_not_available"
    return ""


def _runtime_model_is_available(selected: str, available: set[str]) -> bool:
    if selected in available:
        return True
    if ":" not in selected and f"{selected}:latest" in available:
        return True
    return False


def _runtime_probe_identity(plan: ModelRuntimePlan, payload: dict[str, object]) -> dict[str, object]:
    selected_model = plan.provider_env.get("RAG_IME_PREDICTOR_MODEL", "").strip()
    if plan.runtime == "mlx":
        return {
            "verified": True,
            "mode": "artifact-fingerprint" if payload.get("modelFingerprint") else "resolved-path",
            "selectedModel": selected_model,
            "runtimeModel": str(payload.get("model") or ""),
            "runtimeFingerprint": str(payload.get("modelFingerprint") or ""),
            "registryFingerprintStatus": _registry_fingerprint_status(plan, payload),
        }
    return {
        "verified": True,
        "mode": "runtime-model-list",
        "selectedModel": selected_model,
    }


def _is_sha256_fingerprint(value: str) -> bool:
    if not value.startswith("sha256:"):
        return False
    digest = value.removeprefix("sha256:")
    return len(digest) in {16, 64} and all(character in "0123456789abcdef" for character in digest.lower())


def _is_full_sha256_fingerprint(value: str) -> bool:
    return _is_sha256_fingerprint(value) and len(value.removeprefix("sha256:")) == 64


def _fingerprint_matches(first: str, second: str) -> bool:
    if not _is_sha256_fingerprint(first) or not _is_sha256_fingerprint(second):
        return False
    first_digest = first.removeprefix("sha256:").lower()
    second_digest = second.removeprefix("sha256:").lower()
    return first_digest == second_digest or first_digest.startswith(second_digest) or second_digest.startswith(first_digest)


def _registry_fingerprint_status(plan: ModelRuntimePlan, payload: dict[str, object]) -> str:
    registered = str(plan.deployment.fingerprint or "")
    runtime = str(payload.get("modelFingerprint") or "")
    if _is_full_sha256_fingerprint(registered):
        return "verified" if _fingerprint_matches(registered, runtime) else "mismatch"
    if _is_sha256_fingerprint(registered):
        return "legacy-verified" if _fingerprint_matches(registered, runtime) else "legacy-unverified"
    return "not-content-addressed"


def _probe_credential_environment() -> dict[str, str]:
    keys = {
        "RAG_IME_PREDICTOR_API_KEY",
        "RAG_IME_PREDICTOR_EXTRA_HEADERS_JSON",
        "RAG_IME_PREDICTOR_ENV",
    }
    values: dict[str, str] = {}
    label = os.environ.get("RAG_IME_LAUNCH_AGENT_LABEL", "com.rag-ime.sidecar").strip() or "com.rag-ime.sidecar"
    configured_plist = os.environ.get("RAG_IME_SIDECAR_PLIST", "").strip()
    plist_path = (
        Path(configured_plist).expanduser()
        if configured_plist
        else Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
    )
    try:
        with plist_path.open("rb") as handle:
            payload = plistlib.load(handle)
        existing = payload.get("EnvironmentVariables") if isinstance(payload, dict) else None
        if isinstance(existing, dict):
            values.update({key: str(existing[key]) for key in keys if existing.get(key)})
    except (FileNotFoundError, OSError, ValueError, plistlib.InvalidFileException):
        pass

    env_path = os.environ.get("RAG_IME_PREDICTOR_ENV", "").strip() or values.get("RAG_IME_PREDICTOR_ENV", "")
    if env_path:
        try:
            for raw_line in Path(env_path).expanduser().read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                normalized_key = key.strip()
                if normalized_key in keys:
                    values[normalized_key] = value.strip().strip('"').strip("'")
        except OSError:
            pass
    values.update({key: os.environ[key] for key in keys if os.environ.get(key)})
    return values


def runtime_plan_from_registry(
    registry_path: str | Path | None = None,
    *,
    lane: str = "hot",
    require_exists: bool = True,
) -> ModelRuntimePlan | None:
    registry = ModelRegistry.load(registry_path)
    deployment = registry.resolve(lane=lane, require_exists=require_exists)
    return None if deployment is None else plan_model_runtime(deployment)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Resolve an active model into a real predictor runtime plan.")
    parser.add_argument("--registry", default=str(default_model_registry_path()))
    parser.add_argument("--lane", default="hot")
    parser.add_argument("--format", choices=("json", "shell"), default="json")
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--allow-missing", action="store_true")
    args = parser.parse_args(argv)

    plan = runtime_plan_from_registry(args.registry, lane=args.lane, require_exists=not args.allow_missing)
    if plan is None:
        return 1
    probe = probe_runtime_endpoint(plan) if args.probe else None
    if args.format == "shell":
        for key, value in plan.provider_env.items():
            print(f"{key}={shlex.quote(value)}")
        registered = {
            "RAG_IME_REGISTERED_MODEL_ID": plan.deployment.model_id,
            "RAG_IME_REGISTERED_MODEL_PATH": plan.deployment.path,
            "RAG_IME_REGISTERED_MODEL_FORMAT": plan.deployment.format,
            "RAG_IME_REGISTERED_MODEL_FINGERPRINT": plan.deployment.fingerprint,
            "RAG_IME_REGISTERED_MODEL_PROFILE": plan.deployment.profile,
            "RAG_IME_REGISTERED_MODEL_PROMPT_MODE": plan.deployment.prompt_mode,
            "RAG_IME_REGISTERED_MODEL_RUNTIME": plan.runtime,
            "RAG_IME_REGISTERED_MODEL_ENDPOINT": plan.provider_env.get("RAG_IME_PREDICTOR_BASE_URL", ""),
            "RAG_IME_REGISTERED_MODEL_NAME": plan.deployment.model_name or plan.deployment.path,
        }
        for key, value in registered.items():
            print(f"{key}={shlex.quote(value)}")
        print(f"RAG_IME_MODEL_RUNTIME={shlex.quote(plan.runtime)}")
        print(f"RAG_IME_MODEL_RUNTIME_LIFECYCLE={shlex.quote(plan.lifecycle)}")
        print(f"RAG_IME_MODEL_RUNTIME_READY={'1' if plan.ready else '0'}")
    else:
        payload = plan.payload()
        if probe is not None:
            payload["probe"] = probe
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    if not plan.ready:
        return 2
    if probe is not None and not probe.get("ok"):
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
