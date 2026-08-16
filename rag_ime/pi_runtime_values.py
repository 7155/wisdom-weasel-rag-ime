"""Value coercion shared by both Pi runtime protocol implementations.

`pi_runtime_v2` imported 22 private names from `pi_runtime`, which made v1 the
de-facto owner of helpers that neither version owns conceptually and left the
two modules coupled through their privates. These eight are the subset that is
purely value coercion: they depend on nothing but the standard library, so
they can move without dragging Pi behaviour with them.

Semantics are exactly the private helpers they replace; the names became
public when this module became the owner, because a shared contract imported
by three modules is not private to any of them. `__all__` is that contract,
and the import-boundary gate rejects private imports and public-looking names
absent from `__all__`, so the back channel cannot regrow.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from .agent_runtime_driver import AgentRuntimeError

__all__ = [
    "PiRuntimeCommandRejected",
    "PiRuntimeError",
    "PiRuntimeTurnConflict",
    "as_integer",
    "as_mapping",
    "effective_thinking_level",
    "message_delivery",
    "model_reference_part",
    "path_is_within",
    "public_message_queue",
    "redact_runtime_text",
]


class PiRuntimeError(AgentRuntimeError):
    """Raised by either Pi protocol implementation.

    It lives here rather than in `pi_runtime` because `pi_runtime_public`
    raises it, and importing it back from `pi_runtime` would make the two
    modules cyclic. `pi_runtime` re-exports it, so existing importers are
    unaffected.
    """


class PiRuntimeTurnConflict(PiRuntimeError):
    """A new prompt cannot start while this runtime owns an active turn."""

    error_code = "AGENT_TURN_CONFLICT"


class PiRuntimeCommandRejected(PiRuntimeError):
    """The Pi Host returned a terminal error response for one command.

    This is different from a transport timeout or a broken Host connection:
    the response proves that Pi rejected the command, so callers may close the
    durable receipt instead of leaving it permanently pending.
    """

    error_code = "PI_RUNTIME_COMMAND_REJECTED"

    def __init__(
        self,
        message: str,
        *,
        host_error_code: str = "RUNTIME_REJECTED",
    ) -> None:
        super().__init__(message)
        normalized = re.sub(
            r"[^A-Z0-9_]",
            "_",
            str(host_error_code).strip().upper(),
        ).strip("_")
        self.host_error_code = normalized[:80] or "RUNTIME_REJECTED"


def as_mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def as_integer(value: object) -> int:
    try:
        # Preserve the runtime boundary's deliberately permissive coercion:
        # Provider payload objects may implement Python's numeric protocols
        # even though this public contract accepts the safer static `object`.
        return max(0, int(cast(Any, value) or 0))
    except (TypeError, ValueError):
        return 0


def path_is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def effective_thinking_level(value: object, selected: Mapping[str, object]) -> str:
    normalized = str(value or "off").strip().lower() or "off"
    supported = selected.get("thinkingLevels")
    if not isinstance(supported, list) or normalized not in supported:
        return "off"
    return normalized


def message_delivery(value: object) -> str:
    delivery = str(value or "prompt").strip()
    if delivery not in {"prompt", "steer", "followUp"}:
        raise ValueError("agent message delivery must be prompt, steer, or followUp")
    return delivery


def redact_runtime_text(value: str) -> str:
    text = " ".join(str(value).split())[:500]
    text = re.sub(r"\bsk-[A-Za-z0-9_-]{6,}\b", "[REDACTED_SECRET]", text)
    text = re.sub(r"(?:/Users/|/Volumes/|/private/var/|/var/folders/)[^\s，。；;]+", "[REDACTED_PATH]", text)
    return text


def public_message_queue(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item)[:4_000] for item in value[:100] if isinstance(item, str) and item]


def model_reference_part(value: object, *, field: str, maximum: int) -> str:
    normalized = str(value or "").strip()
    if not normalized or len(normalized) > maximum:
        raise ValueError(f"{field} must be a non-empty Pi model identifier")
    if any(character.isspace() for character in normalized) or (field == "provider" and "/" in normalized):
        raise ValueError(f"{field} contains unsupported characters")
    return normalized
