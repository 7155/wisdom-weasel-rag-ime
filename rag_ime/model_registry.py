from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import math
import os
import shlex
import tempfile
import time
import urllib.parse
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Iterable


MODEL_REGISTRY_SCHEMA_VERSION = "rag-ime.model-registry.v3"
SUPPORTED_MODEL_REGISTRY_SCHEMAS = {
    "rag-ime.model-registry.v1",
    "rag-ime.model-registry.v2",
    MODEL_REGISTRY_SCHEMA_VERSION,
}
MODEL_REGISTRY_WRITE_SCHEMA_VERSION = MODEL_REGISTRY_SCHEMA_VERSION
MODEL_ARTIFACT_PATTERNS = (
    "config.json",
    "generation_config.json",
    "adapter_config.json",
    "quantize_config.json",
    "quantization_config.json",
    "params.json",
    "*.safetensors",
    "*.safetensors.index.json",
    "*.gguf",
    "tokenizer*.json",
    "tokenizer*.model",
    "special_tokens_map.json",
    "added_tokens.json",
    "vocab.json",
    "vocab.txt",
    "merges.txt",
    "spiece.model",
    "*.tiktoken",
    "chat_template*.jinja",
)
TOKENIZER_ARTIFACT_PATTERNS = (
    "tokenizer*.json",
    "tokenizer*.model",
    "special_tokens_map.json",
    "added_tokens.json",
    "vocab.json",
    "vocab.txt",
    "merges.txt",
    "spiece.model",
    "*.tiktoken",
    "chat_template*.jinja",
)


@dataclass(frozen=True)
class ModelDeployment:
    model_id: str
    path: str
    format: str
    fingerprint: str
    profile: str
    runtime: str = ""
    endpoint: str = ""
    model_name: str = ""
    lane: str = "hot"
    prompt_mode: str = ""
    max_tokens: int = 0
    temperature: float | None = None
    top_p: float | None = None
    active: bool = True
    created_at_ms: int = 0
    updated_at_ms: int = 0

    @classmethod
    def from_payload(cls, payload: dict[str, object]) -> "ModelDeployment":
        artifact_format = str(payload.get("format") or "mlx").strip().lower()
        runtime = normalize_model_runtime(str(payload.get("runtime") or infer_model_runtime(artifact_format)))
        return cls(
            model_id=str(payload.get("modelId") or payload.get("model_id") or "").strip(),
            path=str(payload.get("path") or "").strip(),
            format=artifact_format,
            fingerprint=str(payload.get("fingerprint") or "").strip(),
            profile=str(payload.get("profile") or "").strip(),
            runtime=runtime,
            endpoint=normalize_model_endpoint(runtime, str(payload.get("endpoint") or "")),
            model_name=str(payload.get("modelName") or payload.get("model_name") or "").strip(),
            lane=str(payload.get("lane") or "hot").strip().lower(),
            prompt_mode=str(payload.get("promptMode") or payload.get("prompt_mode") or "").strip(),
            max_tokens=_integer(payload.get("maxTokens") or payload.get("max_tokens")),
            temperature=_optional_float(payload.get("temperature")),
            top_p=_optional_float(payload.get("topP") if "topP" in payload else payload.get("top_p")),
            active=bool(payload.get("active", True)),
            created_at_ms=_integer(payload.get("createdAtMs") or payload.get("created_at_ms")),
            updated_at_ms=_integer(payload.get("updatedAtMs") or payload.get("updated_at_ms")),
        )

    def payload(self) -> dict[str, object]:
        values = asdict(self)
        return {
            "modelId": values["model_id"],
            "path": values["path"],
            "format": values["format"],
            "fingerprint": values["fingerprint"],
            "fingerprintAlgorithm": fingerprint_algorithm(values["fingerprint"]),
            "profile": values["profile"],
            "runtime": values["runtime"] or infer_model_runtime(values["format"]),
            "endpoint": values["endpoint"],
            "modelName": values["model_name"],
            "lane": values["lane"],
            "promptMode": values["prompt_mode"],
            "maxTokens": values["max_tokens"],
            "temperature": values["temperature"],
            "topP": values["top_p"],
            "active": values["active"],
            "createdAtMs": values["created_at_ms"],
            "updatedAtMs": values["updated_at_ms"],
        }


class ModelRegistry:
    def __init__(self, path: str | Path, deployments: Iterable[ModelDeployment] = (), *, revision: int = 0) -> None:
        self.path = Path(path).expanduser()
        self.deployments = tuple(deployments)
        self.revision = max(0, int(revision))

    @classmethod
    def load(cls, path: str | Path | None = None) -> "ModelRegistry":
        registry_path = Path(path).expanduser() if path is not None else default_model_registry_path()
        if not registry_path.exists():
            return cls(registry_path)
        payload = json.loads(registry_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("model registry must contain a JSON object")
        schema_version = str(payload.get("schemaVersion") or "")
        if schema_version and schema_version not in SUPPORTED_MODEL_REGISTRY_SCHEMAS:
            raise ValueError(f"unsupported model registry schema: {schema_version}")
        raw_models = payload.get("models")
        if raw_models is None:
            raw_models = []
        if not isinstance(raw_models, list):
            raise ValueError("model registry models must be a list")
        deployments = tuple(
            ModelDeployment.from_payload(item)
            for item in raw_models
            if isinstance(item, dict)
        )
        registry = cls(registry_path, deployments, revision=_integer(payload.get("revision")))
        registry.validate()
        return registry

    def validate(self) -> None:
        seen: set[str] = set()
        active_lanes: set[str] = set()
        for deployment in self.deployments:
            runtime = normalize_model_runtime(deployment.runtime or infer_model_runtime(deployment.format))
            if not deployment.model_id:
                raise ValueError("modelId is required")
            if deployment.model_id in seen:
                raise ValueError(f"duplicate modelId: {deployment.model_id}")
            seen.add(deployment.model_id)
            if runtime == "mlx" and not deployment.path:
                raise ValueError(f"model path is required: {deployment.model_id}")
            if deployment.format not in {"mlx", "gguf", "safetensors", "remote"}:
                raise ValueError(f"unsupported model format: {deployment.format}")
            if runtime not in {"mlx", "ollama", "openai-compatible"}:
                raise ValueError(f"unsupported model runtime: {deployment.runtime}")
            if runtime == "mlx" and deployment.format not in {"mlx", "safetensors"}:
                raise ValueError(f"mlx runtime cannot load {deployment.format}: {deployment.model_id}")
            if runtime == "mlx" and deployment.endpoint and not is_loopback_endpoint(deployment.endpoint):
                raise ValueError(f"managed mlx endpoint must be loopback: {deployment.model_id}")
            if runtime != "mlx":
                if not deployment.endpoint:
                    raise ValueError(f"endpoint is required for {runtime}: {deployment.model_id}")
                if deployment.lane == "hot" and not is_loopback_endpoint(deployment.endpoint):
                    raise ValueError(f"hot lane endpoint must be loopback: {deployment.model_id}")
                if not (deployment.model_name or deployment.path):
                    raise ValueError(f"modelName is required for {runtime}: {deployment.model_id}")
            if deployment.max_tokens < 0 or deployment.max_tokens > 64:
                raise ValueError(f"maxTokens must be between 0 and 64: {deployment.model_id}")
            if deployment.temperature is not None and (
                not math.isfinite(deployment.temperature)
                or not 0.0 <= deployment.temperature <= 2.0
            ):
                raise ValueError(f"temperature must be finite and between 0 and 2: {deployment.model_id}")
            if deployment.top_p is not None and (
                not math.isfinite(deployment.top_p)
                or not 0.0 < deployment.top_p <= 1.0
            ):
                raise ValueError(f"topP must be finite, greater than 0, and at most 1: {deployment.model_id}")
            if deployment.active:
                if deployment.lane in active_lanes:
                    raise ValueError(f"multiple active models for lane: {deployment.lane}")
                active_lanes.add(deployment.lane)

    def resolve(self, *, lane: str = "hot", require_exists: bool = True) -> ModelDeployment | None:
        normalized_lane = str(lane or "hot").strip().lower()
        candidates = [item for item in self.deployments if item.active and item.lane == normalized_lane]
        candidates.sort(key=lambda item: (item.updated_at_ms, item.model_id), reverse=True)
        for deployment in candidates:
            runtime = normalize_model_runtime(deployment.runtime or infer_model_runtime(deployment.format))
            artifact_exists = Path(deployment.path).expanduser().exists()
            if not require_exists or runtime != "mlx" or artifact_exists:
                return deployment
        return None

    def register(self, deployment: ModelDeployment, *, activate: bool = True) -> ModelDeployment:
        now = int(time.time() * 1000)
        runtime = normalize_model_runtime(deployment.runtime or infer_model_runtime(deployment.format))
        path = str(Path(deployment.path).expanduser().resolve()) if runtime == "mlx" else deployment.path
        lane = str(deployment.lane or "hot").strip().lower() or "hot"
        created_at = deployment.created_at_ms or now
        fingerprint = deployment.fingerprint
        if not fingerprint:
            fingerprint = fingerprint_model_artifact(path) if runtime == "mlx" else f"runtime:{runtime}:unverified"
        normalized = replace(
            deployment,
            model_id=deployment.model_id.strip(),
            path=path,
            format=deployment.format.strip().lower(),
            fingerprint=fingerprint,
            profile=deployment.profile.strip(),
            lane=lane,
            runtime=runtime,
            endpoint=normalize_model_endpoint(runtime, deployment.endpoint),
            model_name=deployment.model_name.strip() or (deployment.path.strip() if runtime != "mlx" else ""),
            prompt_mode=deployment.prompt_mode.strip(),
            max_tokens=int(deployment.max_tokens),
            temperature=(
                None if deployment.temperature is None else float(deployment.temperature)
            ),
            top_p=None if deployment.top_p is None else float(deployment.top_p),
            active=activate,
            created_at_ms=created_at,
            updated_at_ms=now,
        )
        updated: list[ModelDeployment] = []
        found = False
        for item in self.deployments:
            if item.model_id == normalized.model_id:
                normalized = replace(normalized, created_at_ms=item.created_at_ms or created_at)
                updated.append(normalized)
                found = True
            elif activate and item.lane.strip().lower() == normalized.lane and item.active:
                updated.append(replace(item, active=False, updated_at_ms=now))
            else:
                updated.append(item)
        if not found:
            updated.append(normalized)
        self.deployments = tuple(updated)
        self.revision += 1
        self.validate()
        self.save()
        return normalized

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schemaVersion": MODEL_REGISTRY_WRITE_SCHEMA_VERSION,
            "revision": self.revision,
            "models": [item.payload() for item in self.deployments],
        }
        body = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=self.path.parent,
            prefix=f".{self.path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(body)
            temporary = Path(handle.name)
        os.replace(temporary, self.path)

    def payload(self) -> dict[str, object]:
        active = {
            item.lane: item.model_id
            for item in self.deployments
            if item.active
        }
        return {
            "schemaVersion": MODEL_REGISTRY_SCHEMA_VERSION,
            "revision": self.revision,
            "path": str(self.path),
            "active": active,
            "models": [item.payload() for item in self.deployments],
        }


def default_model_registry_path(home: str | Path | None = None) -> Path:
    root = Path(home).expanduser() if home is not None else Path.home()
    return root / "Library" / "Application Support" / "RagIme" / "models.json"


def default_models_dir(home: str | Path | None = None) -> Path:
    return default_model_registry_path(home).parent / "Models"


def fingerprint_model(path: str | Path) -> str:
    """Return the legacy compact fingerprint used by existing registry entries."""

    return fingerprint_model_artifact(path, compact=True)


def fingerprint_model_artifact(path: str | Path, *, compact: bool = False) -> str:
    """Hash model metadata, weights, and tokenizer files by content.

    Qualification evidence uses the full digest. ``fingerprint_model`` keeps
    the historical 16-hex registry representation for compatibility.
    """

    model_path = Path(path).expanduser()
    if not model_path.exists():
        raise ValueError(f"model path does not exist: {model_path}")
    digest = hashlib.sha256()
    artifact_root = model_path if model_path.is_dir() else model_path.parent
    files = _artifact_files(model_path, MODEL_ARTIFACT_PATTERNS) if model_path.is_dir() else (model_path,)
    for item in files:
        digest.update(item.relative_to(artifact_root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(item.stat().st_size.to_bytes(8, "big", signed=False))
        with item.open("rb") as handle:
            while chunk := handle.read(8 * 1024 * 1024):
                digest.update(chunk)
    if not files:
        digest.update(str(model_path.resolve()).encode("utf-8"))
    value = digest.hexdigest()
    return "sha256:" + (value[:16] if compact else value)


def fingerprint_tokenizer_artifact(path: str | Path) -> str:
    model_path = Path(path).expanduser()
    if not model_path.exists():
        raise ValueError(f"model path does not exist: {model_path}")
    files = _artifact_files(model_path, TOKENIZER_ARTIFACT_PATTERNS)
    if not files:
        return "missing"
    digest = hashlib.sha256()
    for item in files:
        digest.update(item.relative_to(model_path).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(item.stat().st_size.to_bytes(8, "big", signed=False))
        digest.update(item.read_bytes())
    return "sha256:" + digest.hexdigest()


def _artifact_files(model_path: Path, patterns: tuple[str, ...]) -> tuple[Path, ...]:
    root = model_path.resolve()
    files = tuple(
        sorted(
            {
                item
                for pattern in patterns
                for item in model_path.glob(pattern)
                if item.is_file()
            }
        )
    )
    for item in files:
        try:
            item.resolve().relative_to(root)
        except ValueError as exc:
            raise ValueError(f"model artifact file escapes its directory: {item}") from exc
    return files


def fingerprint_algorithm(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized.startswith("sha256:"):
        digest = normalized.removeprefix("sha256:")
        if len(digest) == 64 and all(character in "0123456789abcdef" for character in digest):
            return "rag-ime-model-artifact-sha256-v1"
        if len(digest) == 16 and all(character in "0123456789abcdef" for character in digest):
            return "legacy-truncated-sha256"
    if normalized.startswith("runtime:"):
        return "runtime-declared"
    return "unknown"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage portable RAG-IME model deployments.")
    parser.add_argument("--registry", default=str(default_model_registry_path()))
    subparsers = parser.add_subparsers(dest="command", required=True)

    register = subparsers.add_parser("register", help="Register and optionally activate a local model.")
    register.add_argument("--model-id", required=True)
    register.add_argument("--path", default="")
    register.add_argument("--format", default="mlx")
    register.add_argument("--profile", required=True)
    register.add_argument("--runtime", choices=("mlx", "ollama", "openai-compatible"), default="")
    register.add_argument("--endpoint", default="")
    register.add_argument("--model-name", default="")
    register.add_argument("--lane", default="hot")
    register.add_argument("--prompt-mode", default="")
    register.add_argument("--max-tokens", type=int, default=0)
    register.add_argument("--temperature", type=float)
    register.add_argument("--top-p", type=float)
    register.add_argument("--inactive", action="store_true")

    resolve = subparsers.add_parser("resolve", help="Resolve the active model for a lane.")
    resolve.add_argument("--lane", default="hot")
    resolve.add_argument("--format", choices=("json", "shell"), default="json")
    resolve.add_argument("--field", choices=("path", "profile", "prompt-mode", "model-id", "fingerprint", "runtime", "endpoint", "model-name"))
    resolve.add_argument("--allow-missing", action="store_true")

    subparsers.add_parser("list", help="Print the registry.")

    args = parser.parse_args(argv)
    registry = ModelRegistry.load(args.registry)
    if args.command == "register":
        deployment = registry.register(
            ModelDeployment(
                model_id=args.model_id,
                path=args.path,
                format=args.format,
                fingerprint="",
                profile=args.profile,
                runtime=args.runtime,
                endpoint=args.endpoint,
                model_name=args.model_name,
                lane=args.lane,
                prompt_mode=args.prompt_mode,
                max_tokens=args.max_tokens,
                temperature=args.temperature,
                top_p=args.top_p,
            ),
            activate=not args.inactive,
        )
        print(json.dumps({"ok": True, "revision": registry.revision, "model": deployment.payload()}, ensure_ascii=False, indent=2))
        return 0
    if args.command == "resolve":
        deployment = registry.resolve(lane=args.lane, require_exists=not args.allow_missing)
        if deployment is None:
            return 1
        if args.field:
            fields = {
                "path": deployment.path,
                "profile": deployment.profile,
                "prompt-mode": deployment.prompt_mode,
                "model-id": deployment.model_id,
                "fingerprint": deployment.fingerprint,
                "runtime": deployment.runtime or infer_model_runtime(deployment.format),
                "endpoint": deployment.endpoint,
                "model-name": deployment.model_name or deployment.path,
            }
            print(fields[args.field])
        elif args.format == "shell":
            values = {
                "RAG_IME_REGISTERED_MODEL_ID": deployment.model_id,
                "RAG_IME_REGISTERED_MODEL_PATH": deployment.path,
                "RAG_IME_REGISTERED_MODEL_FORMAT": deployment.format,
                "RAG_IME_REGISTERED_MODEL_FINGERPRINT": deployment.fingerprint,
                "RAG_IME_REGISTERED_MODEL_PROFILE": deployment.profile,
                "RAG_IME_REGISTERED_MODEL_PROMPT_MODE": deployment.prompt_mode,
                "RAG_IME_REGISTERED_MODEL_RUNTIME": deployment.runtime or infer_model_runtime(deployment.format),
                "RAG_IME_REGISTERED_MODEL_ENDPOINT": deployment.endpoint,
                "RAG_IME_REGISTERED_MODEL_NAME": deployment.model_name or deployment.path,
            }
            for key, value in values.items():
                print(f"{key}={shlex.quote(value)}")
        else:
            print(json.dumps(deployment.payload(), ensure_ascii=False, indent=2))
        return 0
    print(json.dumps(registry.payload(), ensure_ascii=False, indent=2))
    return 0


def _integer(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _optional_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def infer_model_runtime(artifact_format: str) -> str:
    normalized = str(artifact_format or "").strip().lower()
    if normalized in {"mlx", "safetensors"}:
        return "mlx"
    if normalized == "gguf":
        return "openai-compatible"
    if normalized == "remote":
        return "openai-compatible"
    return ""


def normalize_model_runtime(runtime: str) -> str:
    normalized = str(runtime or "").strip().lower().replace("_", "-")
    aliases = {
        "mlx-lm": "mlx",
        "mlx-service": "mlx",
        "openai": "openai-compatible",
        "llama-cpp": "openai-compatible",
        "llamacpp": "openai-compatible",
    }
    return aliases.get(normalized, normalized)


def is_loopback_endpoint(endpoint: str) -> bool:
    try:
        parsed = urllib.parse.urlsplit(str(endpoint or "").strip())
        host = (parsed.hostname or "").lower()
        port = parsed.port
    except (TypeError, ValueError):
        return False
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    if parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment:
        return False
    if port is not None and not 1 <= port <= 65535:
        return False
    if host in {"localhost", "localhost."}:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def is_local_network_endpoint(endpoint: str) -> bool:
    """Accept loopback and explicit LAN endpoints for the hot-model slot.

    Arbitrary public hosts stay rejected because per-keystroke traffic has a
    different privacy and latency contract from the explicit knowledge slot.
    """

    try:
        parsed = urllib.parse.urlsplit(str(endpoint or "").strip())
        host = (parsed.hostname or "").lower()
    except (TypeError, ValueError):
        return False
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    if parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment:
        return False
    if host in {"localhost", "localhost."} or host.endswith(".local"):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_loopback or address.is_private or address.is_link_local


def normalize_model_endpoint(runtime: str, endpoint: str) -> str:
    normalized = str(endpoint or "").strip().rstrip("/")
    if not normalized:
        return ""
    parsed = urllib.parse.urlsplit(normalized)
    path = parsed.path.rstrip("/")
    resolved_runtime = normalize_model_runtime(runtime)
    if resolved_runtime in {"ollama", "openai-compatible"} and path.endswith("/v1"):
        path = path[:-3].rstrip("/")
    return urllib.parse.urlunsplit((parsed.scheme.lower(), parsed.netloc, path, parsed.query, parsed.fragment)).rstrip("/")


if __name__ == "__main__":
    raise SystemExit(main())
