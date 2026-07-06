from __future__ import annotations

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
    env_path: Path | None = None


def load_deepseek_config(env_path: str | Path | None = None, env: Mapping[str, str] | None = None) -> DeepSeekConfig:
    values: dict[str, str] = {}
    resolved = Path(env_path).expanduser() if env_path else None
    if resolved is not None and resolved.exists():
        values.update(_read_env_file(resolved))
    if env:
        values.update(dict(env))
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
