from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol


SUPPORTED_MEMORY_THINKING_LEVELS = (
    "off",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
    "max",
)


class MemoryModelUnavailable(RuntimeError):
    """The selected governed Provider/runtime cannot execute memory work."""


class MemoryCompletionRuntime(Protocol):
    def available_models(self) -> list[dict[str, object]]: ...

    def complete_once(
        self,
        *,
        request_id: str,
        provider: str,
        model_id: str,
        thinking_level: str,
        message: str,
        on_text_delta: Callable[[str], None] | None = None,
        timeout_seconds: float = 120.0,
    ) -> dict[str, object]: ...


@dataclass
class GovernedMemoryModelExecutor:
    """Adapt memory prompts to the existing managed-Pi stateless completion RPC."""

    runtime: MemoryCompletionRuntime
    provider: str
    model_id: str
    thinking_level: str
    timeout_seconds: float = 180.0
    owns_runtime: bool = False

    def __post_init__(self) -> None:
        self.provider = _model_part(self.provider, field="provider", maximum=80)
        self.model_id = _model_part(self.model_id, field="modelId", maximum=160)
        self.thinking_level = str(self.thinking_level or "").strip().lower()
        if self.thinking_level not in SUPPORTED_MEMORY_THINKING_LEVELS:
            raise ValueError("memory thinking level is not supported")
        self.timeout_seconds = max(1.0, min(300.0, float(self.timeout_seconds)))
        try:
            models = self.runtime.available_models()
        except Exception as exc:
            raise MemoryModelUnavailable(
                f"selected memory runtime is unavailable for {self.reference}: {_public_error(exc)}"
            ) from exc
        selected = next(
            (
                dict(model)
                for model in models
                if isinstance(model, Mapping)
                and str(model.get("provider") or "") == self.provider
                and str(model.get("id") or "") == self.model_id
            ),
            None,
        )
        if selected is None:
            raise MemoryModelUnavailable(
                f"selected memory model is unavailable: {self.reference}"
            )
        supported = selected.get("thinkingLevels")
        if not isinstance(supported, list) or self.thinking_level not in {
            str(level) for level in supported
        }:
            raise MemoryModelUnavailable(
                f"selected memory model does not support thinking level "
                f"{self.thinking_level}: {self.reference}"
            )
        self.selected_model = selected

    @property
    def reference(self) -> str:
        return f"{self.provider}/{self.model_id}"

    def complete(
        self,
        *,
        messages: list[dict[str, str]],
        max_tokens: int | None = None,
    ) -> dict[str, object]:
        request_id = f"memory-{uuid.uuid4().hex}"
        prompt = json.dumps(
            {
                "messages": messages,
                "responseFormat": "json_object",
                "maxTokens": max_tokens,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        try:
            result = self.runtime.complete_once(
                request_id=request_id,
                provider=self.provider,
                model_id=self.model_id,
                thinking_level=self.thinking_level,
                message=prompt,
                on_text_delta=None,
                timeout_seconds=self.timeout_seconds,
            )
        except Exception as exc:
            raise MemoryModelUnavailable(
                f"selected memory model request failed ({self.reference}): {_public_error(exc)}"
            ) from exc
        if not isinstance(result, Mapping):
            raise MemoryModelUnavailable(
                f"selected memory model returned an invalid response: {self.reference}"
            )
        text = str(result.get("text") or "").strip()
        if not text:
            raise MemoryModelUnavailable(
                f"selected memory model returned no text: {self.reference}"
            )
        usage = result.get("usage")
        return {
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": text},
                    "finish_reason": "stop",
                }
            ],
            "provider": self.provider,
            "model": self.model_id,
            "thinkingLevel": self.thinking_level,
            "elapsedMs": max(0, int(result.get("elapsedMs") or 0)),
            "firstTokenMs": max(0, int(result.get("firstTokenMs") or 0)),
            "usage": dict(usage) if isinstance(usage, Mapping) else {},
        }

    def close(self) -> None:
        if self.owns_runtime:
            stop = getattr(self.runtime, "stop", None)
            if callable(stop):
                stop()


def split_memory_model_reference(value: object) -> tuple[str, str]:
    reference = " ".join(str(value or "").strip().split())
    provider, separator, model_id = reference.partition("/")
    if not separator:
        normalized = reference.casefold().replace("_", "-")
        if normalized.startswith("deepseek-v4"):
            return "deepseek", reference
        raise ValueError("memory model must be a provider/model reference")
    return (
        _model_part(provider, field="provider", maximum=80),
        _model_part(model_id, field="modelId", maximum=160),
    )


def build_governed_memory_model_executor(
    runtime: MemoryCompletionRuntime,
    model_reference: object,
    thinking_level: object,
    *,
    timeout_seconds: float = 180.0,
) -> GovernedMemoryModelExecutor:
    provider, model_id = split_memory_model_reference(model_reference)
    return GovernedMemoryModelExecutor(
        runtime,
        provider,
        model_id,
        str(thinking_level or "").strip().lower(),
        timeout_seconds=timeout_seconds,
        owns_runtime=False,
    )


def build_managed_pi_memory_model_executor(
    db_path: str | Path,
    model_reference: object,
    thinking_level: object,
    *,
    timeout_seconds: float = 180.0,
) -> GovernedMemoryModelExecutor:
    """Build the same managed-Pi runtime boundary used by Agent Sessions."""

    from .agent_events import AgentEventHub
    from .agent_sessions import AgentSessionStore
    from .pi_runtime import PiRuntimeConfig
    from .pi_runtime_v2 import PiRuntimeHostManager

    provider, model_id = split_memory_model_reference(model_reference)
    config = PiRuntimeConfig.from_environment(enabled_default=True)
    if not config.enabled:
        raise MemoryModelUnavailable("managed Pi runtime is disabled")
    if not config.model_configured:
        raise MemoryModelUnavailable(
            "selected memory runtime is unavailable: "
            f"{config.model_configuration_error or 'Pi model is not configured'}"
        )
    configured_provider = str(config.model_providers.get(provider) or "")
    if not configured_provider:
        raise MemoryModelUnavailable(
            f"selected memory provider is unavailable: {provider}"
        )
    selected_config = replace(config, provider=provider, model=model_id)
    sessions = AgentSessionStore(db_path)
    sessions.initialize()
    runtime = PiRuntimeHostManager(
        config=selected_config,
        sessions=sessions,
        events=AgentEventHub(),
    )
    try:
        return GovernedMemoryModelExecutor(
            runtime,
            provider,
            model_id,
            str(thinking_level or "").strip().lower(),
            timeout_seconds=timeout_seconds,
            owns_runtime=True,
        )
    except Exception:
        runtime.stop()
        raise


def _model_part(value: object, *, field: str, maximum: int) -> str:
    normalized = str(value or "").strip()
    if not normalized or len(normalized) > maximum or any(character.isspace() for character in normalized):
        raise ValueError(f"memory {field} is invalid")
    return normalized


def _public_error(exc: BaseException) -> str:
    return " ".join(str(exc).split())[:240] or exc.__class__.__name__
