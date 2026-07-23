from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping
from urllib.parse import urlsplit


_MAX_PROVIDER_CONFIG_BYTES = 2 * 1024 * 1024
_PROVIDER_ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]{0,62}[a-z0-9]$")
_MODEL_ID_PATTERN = re.compile(r"^[^\s]{1,160}$")


class PiProviderConfigError(ValueError):
    pass


@dataclass(frozen=True)
class PiProviderBundle:
    providers: Mapping[str, Mapping[str, object]] = field(default_factory=dict, repr=False)
    environment: Mapping[str, str] = field(default_factory=dict, repr=False)
    first_provider: str = ""
    first_model: str = ""


def load_pi_provider_config(path: str | Path) -> PiProviderBundle:
    """Translate a user-owned OpenCode provider file into Pi's models.json shape.

    Secrets never enter the returned provider JSON. Each key is replaced by a
    child-process-only environment reference so the generated Pi config remains
    safe to inspect and back up.
    """

    source = Path(path).expanduser()
    if not source.is_file() or source.is_symlink():
        raise PiProviderConfigError("Pi Provider 配置文件不存在或不是普通文件")
    if source.stat().st_size > _MAX_PROVIDER_CONFIG_BYTES:
        raise PiProviderConfigError("Pi Provider 配置文件过大")
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PiProviderConfigError("Pi Provider 配置不是有效 JSON") from exc
    if not isinstance(payload, dict):
        raise PiProviderConfigError("Pi Provider 配置根节点必须是对象")

    raw_providers = payload.get("provider")
    if not isinstance(raw_providers, dict):
        raise PiProviderConfigError("Pi Provider 配置缺少 provider 对象")

    providers: dict[str, Mapping[str, object]] = {}
    environment: dict[str, str] = {}
    first_provider = ""
    first_model = ""
    for source_id, raw_provider in raw_providers.items():
        if not isinstance(raw_provider, dict):
            continue
        provider_id = _pi_provider_id(str(source_id))
        model_catalog_provider = "openai" if provider_id == "gpt" else provider_id
        options = raw_provider.get("options")
        if not isinstance(options, dict):
            options = {}
        base_url = _remote_base_url(options.get("baseURL") or options.get("baseUrl"))
        api_key = str(options.get("apiKey") or "").strip()
        models = _models(raw_provider.get("models"))
        if not base_url or not api_key or not models:
            continue

        environment_name = f"RAG_IME_PI_{provider_id.upper().replace('-', '_')}_API_KEY"
        environment[environment_name] = api_key
        providers[provider_id] = {
            # Inherit the catalog model's public capabilities, but do not
            # assume an arbitrary OpenAI-compatible gateway implements the
            # native client-side tool-search protocol. Loaded tools stay in
            # the ordinary append-only tool list unless a verified endpoint
            # explicitly opts in at the Pi configuration boundary.
            "modelCatalogProvider": model_catalog_provider,
            "baseUrl": base_url,
            "apiKey": f"${environment_name}",
            **(
                {"compat": {"supportsToolSearch": False}}
                if model_catalog_provider == "openai"
                else {}
            ),
            "models": models,
        }
        if not first_provider:
            first_provider = provider_id
            first_model = str(models[0]["id"])

    if not providers:
        raise PiProviderConfigError("Pi Provider 配置中没有可用的 HTTPS 模型入口")
    return PiProviderBundle(
        providers=providers,
        environment=environment,
        first_provider=first_provider,
        first_model=first_model,
    )


def _pi_provider_id(value: str) -> str:
    normalized = value.strip().lower().replace("_", "-")
    # Do not override Pi's built-in OpenAI catalog and redirect unrelated
    # models to a user gateway. Give imported GPT gateways their own namespace.
    if normalized in {"openai", "openai-compatible", "gpt"}:
        return "gpt"
    normalized = re.sub(r"[^a-z0-9-]+", "-", normalized).strip("-")
    if not _PROVIDER_ID_PATTERN.fullmatch(normalized):
        raise PiProviderConfigError("Pi Provider 名称不合法")
    return normalized


def _remote_base_url(value: object) -> str:
    base_url = str(value or "").strip().rstrip("/")
    if not base_url:
        return ""
    parsed = urlsplit(base_url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise PiProviderConfigError("远程 Pi Provider 必须使用有效的 HTTPS 地址")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise PiProviderConfigError("远程 Pi Provider 地址不能包含凭据、查询参数或片段")
    return base_url


def _models(value: object) -> list[dict[str, object]]:
    if not isinstance(value, dict):
        return []
    models: list[dict[str, object]] = []
    for raw_id in value:
        model_id = str(raw_id).strip()
        if not _MODEL_ID_PATTERN.fullmatch(model_id):
            continue
        models.append({"id": model_id})
    return models
