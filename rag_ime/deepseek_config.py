from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class DeepSeekConfig:
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
    active_rag_max_tokens: int = 1024
    memory_book_max_tokens: int = 2048
    env_path: Path | None = None


def load_deepseek_config(env_path: str | Path | None = None, env: Mapping[str, str] | None = None) -> DeepSeekConfig:
    source_values = dict(os.environ if env is None else env)
    default_env_path = (
        str(env_path or "").strip()
        or _first_value(source_values, "RAG_IME_DEEPSEEK_ENV", "RAG_IME_MODEL_ENV", "RAG_IME_X1API_ENV")
    )
    values: dict[str, str] = {}
    resolved = Path(default_env_path).expanduser() if default_env_path else None
    if resolved is not None and resolved.exists():
        values.update(_read_env_file(resolved))
    values.update(source_values)
    return DeepSeekConfig(
        api_base_url=_canonical_deepseek_base_url(
            _first_value(values, "RAG_IME_DEEPSEEK_BASE_URL", "DEEPSEEK_BASE_URL", "X1API_BASE_URL", default="https://api.deepseek.com")
        ),
        api_key=_first_value(values, "DEEPSEEK_API_KEY", "RAG_IME_DEEPSEEK_API_KEY", "X1API_API_KEY", "API_KEY"),
        model=_first_value(values, "RAG_IME_DEEPSEEK_MODEL", "DEEPSEEK_MODEL", "X1API_MODEL", "MODEL", default="deepseek-v4-flash"),
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
            default=1024,
        ),
        memory_book_max_tokens=_int_value(
            _first_value(values, "RAG_IME_DEEPSEEK_MEMORY_BOOK_MAX_TOKENS", "DEEPSEEK_MEMORY_BOOK_MAX_TOKENS"),
            default=2048,
        ),
        env_path=resolved,
    )


def _canonical_deepseek_base_url(value: str) -> str:
    base = value.strip().rstrip("/") or "https://api.deepseek.com"
    if base.endswith("/v1"):
        return base
    return f"{base}/v1"


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
