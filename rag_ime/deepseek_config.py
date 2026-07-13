from __future__ import annotations

import os
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping
from urllib.parse import urlsplit

from .keychain_secrets import MODEL_KEYCHAIN_SERVICE, MODEL_KNOWLEDGE_ACCOUNT, read_keychain_secret


@dataclass(frozen=True)
class DeepSeekConfig:
    provider_name: str = "deepseek"
    api_base_url: str = "https://api.deepseek.com/v1"
    api_key: str = ""
    model: str = "deepseek-v4-flash"
    wire_api: str = "chat_completions"
    stream: bool = False
    json_mode: bool = True
    request_timeout_seconds: float = 60.0
    thinking: str = ""
    reasoning_effort: str = "low"
    max_tokens: int = 96
    # Zero means no application-side cap. Providers still enforce their own
    # context/output limits, while users can opt into an explicit positive cap.
    active_rag_max_tokens: int = 0
    memory_book_max_tokens: int = 3072
    knowledge_max_tokens: int = 4096
    extra_headers: dict[str, str] = field(default_factory=dict)
    env_path: Path | None = None


def load_deepseek_config(env_path: str | Path | None = None, env: Mapping[str, str] | None = None) -> DeepSeekConfig:
    source_values = dict(os.environ if env is None else env)
    default_env_path = (
        str(env_path or "").strip()
        or _first_value(source_values, "RAG_IME_DEEPSEEK_ENV", "RAG_IME_MODEL_ENV")
    )
    values: dict[str, str] = {}
    resolved = Path(default_env_path).expanduser() if default_env_path else None
    if resolved is not None and resolved.exists():
        values.update(_read_env_file(resolved))
    if env is None:
        # The LaunchAgent carries conservative defaults while the local env
        # file is the user-owned provider slot.  Let the explicit local file
        # override those defaults without weakening test/CLI overrides.
        values = {**source_values, **values}
    else:
        values.update(source_values)
    provider_name = _normalized_provider_name(
        _first_value(values, "RAG_IME_KNOWLEDGE_PROVIDER", "RAG_IME_DEEPSEEK_PROVIDER", default="deepseek")
    )
    model = _first_value(values, "RAG_IME_DEEPSEEK_MODEL", "DEEPSEEK_MODEL", default="deepseek-v4-flash")
    if provider_name == "deepseek" and not _is_deepseek_v4_model(model):
        raise ValueError("high-intelligence routes require a DeepSeek V4 model")
    api_key = _first_value(values, "DEEPSEEK_API_KEY", "RAG_IME_DEEPSEEK_API_KEY")
    if not api_key and env is None:
        api_key = read_keychain_secret(MODEL_KEYCHAIN_SERVICE, MODEL_KNOWLEDGE_ACCOUNT)
    return DeepSeekConfig(
        provider_name=provider_name,
        api_base_url=_canonical_model_base_url(
            _first_value(values, "RAG_IME_DEEPSEEK_BASE_URL", "DEEPSEEK_BASE_URL", default="https://api.deepseek.com")
        ),
        api_key=api_key,
        model=model,
        wire_api=_first_value(values, "RAG_IME_DEEPSEEK_WIRE_API", "DEEPSEEK_WIRE_API", default="chat_completions"),
        stream=_bool_value(_first_value(values, "RAG_IME_DEEPSEEK_STREAM", "DEEPSEEK_STREAM"), default=False),
        json_mode=_bool_value(_first_value(values, "RAG_IME_DEEPSEEK_JSON", "DEEPSEEK_JSON"), default=True),
        request_timeout_seconds=_float_value(
            _first_value(values, "RAG_IME_DEEPSEEK_TIMEOUT_SECONDS", "DEEPSEEK_TIMEOUT_SECONDS"),
            default=60.0,
        ),
        thinking=_first_value(
            values,
            "RAG_IME_DEEPSEEK_THINKING",
            "DEEPSEEK_THINKING",
            default="disabled",
        ),
        reasoning_effort=_first_value(
            values,
            "RAG_IME_DEEPSEEK_REASONING_EFFORT",
            "DEEPSEEK_REASONING_EFFORT",
            default="low",
        ),
        max_tokens=_int_value(
            _first_value(values, "RAG_IME_DEEPSEEK_MAX_TOKENS", "DEEPSEEK_MAX_TOKENS"),
            default=96,
        ),
        active_rag_max_tokens=_int_value(
            _first_value(
                values,
                "RAG_IME_DEEPSEEK_ACTIVE_RAG_MAX_TOKENS",
                "DEEPSEEK_ACTIVE_RAG_MAX_TOKENS",
            ),
            default=0,
        ),
        memory_book_max_tokens=_int_value(
            _first_value(values, "RAG_IME_DEEPSEEK_MEMORY_BOOK_MAX_TOKENS", "DEEPSEEK_MEMORY_BOOK_MAX_TOKENS"),
            default=3072,
        ),
        knowledge_max_tokens=_int_value(
            _first_value(values, "RAG_IME_DEEPSEEK_KNOWLEDGE_MAX_TOKENS", "DEEPSEEK_KNOWLEDGE_MAX_TOKENS"),
            default=4096,
        ),
        extra_headers=_json_string_map(
            _first_value(values, "RAG_IME_KNOWLEDGE_EXTRA_HEADERS_JSON", "RAG_IME_DEEPSEEK_EXTRA_HEADERS_JSON")
        ),
        env_path=resolved,
    )


def _canonical_model_base_url(value: str) -> str:
    base = value.strip().rstrip("/") or "https://api.deepseek.com"
    if urlsplit(base).hostname in {"x1api.top", "x2app.top"}:
        raise ValueError("legacy proxy route is disabled; configure a DeepSeek V4 endpoint")
    if base.endswith("/v1"):
        return base
    return f"{base}/v1"


def _normalized_provider_name(value: str) -> str:
    normalized = value.strip().lower().replace("_", "-")
    if normalized in {"deepseek", "deepseek-v4", "dsv4"}:
        return "deepseek"
    if normalized in {"openai", "openai-compatible", "custom", "compatible"}:
        return "openai-compatible"
    raise ValueError(f"unsupported knowledge provider: {value}")


def _is_deepseek_v4_model(value: str) -> bool:
    return value.strip().lower().replace("_", "-").startswith("deepseek-v4")


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, raw_value = stripped.split("=", 1)
        values[key.strip()] = raw_value.strip().strip("'\"")
    return values


def _first_value(values: Mapping[str, str], *names: str, default: str = "") -> str:
    for name in names:
        value = str(values.get(name, "")).strip()
        if value:
            return value
    return default


def _bool_value(value: str, *, default: bool) -> bool:
    raw = value.strip().lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


def _float_value(value: str, *, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int_value(value: str, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _json_string_map(value: str) -> dict[str, str]:
    if not value.strip():
        return {}
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}
    return {
        str(key).strip(): str(item).strip()
        for key, item in payload.items()
        if str(key).strip() and str(item).strip()
    }
