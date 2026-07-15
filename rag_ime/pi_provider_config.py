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
        supports_reasoning = any(bool(model.get("reasoning")) for model in models)
        providers[provider_id] = {
            "baseUrl": base_url,
            "api": "openai-completions",
            "apiKey": f"${environment_name}",
            "compat": {
                "supportsStore": True,
                "supportsDeveloperRole": True,
                "supportsReasoningEffort": supports_reasoning,
                "supportsUsageInStreaming": True,
                "maxTokensField": "max_completion_tokens",
                "thinkingFormat": "openai",
            },
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
    declared_ids = {str(raw_id).strip() for raw_id in value}
    persona_families = {
        base_id
        for model_id in declared_ids
        for base_id in [_persona_alias_base(model_id)]
        if base_id
    }
    models: list[dict[str, object]] = []
    for raw_id, raw_model in value.items():
        model_id = str(raw_id).strip()
        if not _MODEL_ID_PATTERN.fullmatch(model_id):
            continue
        # Luna/Terra/Sol are product timeline personas, not model IDs proven by
        # the upstream API. If a provider file contains that family, fail
        # closed for the entire invented family instead of letting Pi expose a
        # catalog entry that will only fail later with an upstream 404.
        if model_id in persona_families or _persona_alias_base(model_id):
            continue
        definition = raw_model if isinstance(raw_model, dict) else {}
        limit = definition.get("limit") if isinstance(definition.get("limit"), dict) else {}
        context_window = _positive_int(limit.get("context"), default=128_000)
        max_tokens = _positive_int(limit.get("output"), default=32_000)
        reasoning, thinking_level_map = _reasoning_capabilities(definition)
        model: dict[str, object] = {
            "id": model_id,
            "name": str(definition.get("name") or model_id).strip()[:160] or model_id,
            "reasoning": reasoning,
            "input": _input_modalities(definition),
            "contextWindow": context_window,
            "maxTokens": max_tokens,
        }
        if thinking_level_map:
            model["thinkingLevelMap"] = thinking_level_map
        models.append(model)
    return models


def _persona_alias_base(model_id: str) -> str:
    match = re.fullmatch(
        r"(gpt-[a-z0-9][a-z0-9.-]*?)-(?:luna|terra|sol)",
        model_id,
        flags=re.IGNORECASE,
    )
    return match.group(1) if match else ""


def _reasoning_capabilities(
    definition: Mapping[str, object],
) -> tuple[bool, dict[str, str | None]]:
    explicit_reasoning = definition.get("reasoning")
    explicit_map = definition.get("thinkingLevelMap")
    if isinstance(explicit_map, Mapping):
        level_map = _sanitize_thinking_level_map(explicit_map)
        inferred = any(value is not None for key, value in level_map.items() if key != "off")
        reasoning = explicit_reasoning if isinstance(explicit_reasoning, bool) else inferred
        return bool(reasoning), level_map if reasoning else {}

    declared_levels = _declared_thinking_levels(definition)
    inferred = any(level != "off" for level in declared_levels)
    reasoning = explicit_reasoning if isinstance(explicit_reasoning, bool) else inferred
    if not reasoning:
        return False, {}

    # Pi keeps ordinary reasoning levels unless a model explicitly disables
    # them. Only xhigh needs a declared mapping.
    level_map: dict[str, str | None] = {}
    if "max" in declared_levels:
        level_map["xhigh"] = "max"
    elif "xhigh" in declared_levels:
        level_map["xhigh"] = "xhigh"
    return True, level_map


def _declared_thinking_levels(definition: Mapping[str, object]) -> set[str]:
    declared: set[str] = set()
    raw_levels = definition.get("thinkingLevels")
    if isinstance(raw_levels, list):
        declared.update(str(item).strip().lower() for item in raw_levels)
    variants = definition.get("variants")
    if isinstance(variants, Mapping):
        declared.update(str(item).strip().lower() for item in variants)
    return declared.intersection({"off", "minimal", "low", "medium", "high", "xhigh", "max"})


def _sanitize_thinking_level_map(value: Mapping[object, object]) -> dict[str, str | None]:
    result: dict[str, str | None] = {}
    for raw_level, raw_mapping in value.items():
        level = str(raw_level).strip().lower()
        if level == "max":
            level = "xhigh"
        if level not in {"off", "minimal", "low", "medium", "high", "xhigh"}:
            continue
        if raw_mapping is None:
            result[level] = None
            continue
        mapped = str(raw_mapping).strip().lower()
        if mapped:
            result[level] = mapped[:32]
    return result


def _input_modalities(definition: Mapping[str, object]) -> list[str]:
    raw_input = definition.get("input")
    if isinstance(raw_input, list):
        declared = [
            str(item).strip().lower()
            for item in raw_input
            if str(item).strip().lower() in {"text", "image"}
        ]
        if declared:
            return list(dict.fromkeys(["text", *declared]))

    raw_modalities = definition.get("modalities")
    if isinstance(raw_modalities, Mapping) and isinstance(raw_modalities.get("image"), bool):
        return ["text", "image"] if raw_modalities["image"] else ["text"]
    if isinstance(raw_modalities, list) and "image" in {
        str(item).strip().lower() for item in raw_modalities
    }:
        return ["text", "image"]
    return ["text"]


def _positive_int(value: object, *, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number if number > 0 else default
