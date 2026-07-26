"""Value coercion shared by both Pi runtime protocol implementations.

`pi_runtime_v2` imported 22 private names from `pi_runtime`, which made v1 the
de-facto owner of helpers that neither version owns conceptually and left the
two modules coupled through their privates. These eight are the subset that is
purely value coercion: they depend on nothing but the standard library, so
they can move without dragging Pi behaviour with them.

They keep their names and semantics exactly; this is a relocation, not a
rewrite. The remaining private imports involve Pi message shaping, redaction
and public projection, which reach further into v1 and are left for their own
change.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

from .agent_runtime_driver import AgentRuntimeError


class PiRuntimeError(AgentRuntimeError):
    """Raised by either Pi protocol implementation.

    It lives here rather than in `pi_runtime` because `pi_runtime_public`
    raises it, and importing it back from `pi_runtime` would make the two
    modules cyclic. `pi_runtime` re-exports it, so existing importers are
    unaffected.
    """


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _integer(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _effective_thinking_level(value: object, selected: Mapping[str, object]) -> str:
    normalized = str(value or "off").strip().lower() or "off"
    supported = selected.get("thinkingLevels")
    if not isinstance(supported, list) or normalized not in supported:
        return "off"
    return normalized


def _message_delivery(value: object) -> str:
    delivery = str(value or "prompt").strip()
    if delivery not in {"prompt", "steer", "followUp"}:
        raise ValueError("agent message delivery must be prompt, steer, or followUp")
    return delivery


def _redact_runtime_text(value: str) -> str:
    text = " ".join(str(value).split())[:500]
    text = re.sub(r"\bsk-[A-Za-z0-9_-]{6,}\b", "[REDACTED_SECRET]", text)
    text = re.sub(r"(?:/Users/|/Volumes/|/private/var/|/var/folders/)[^\s，。；;]+", "[REDACTED_PATH]", text)
    return text


def _public_message_queue(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item)[:4_000] for item in value[:100] if isinstance(item, str) and item]


def _model_reference_part(value: object, *, field: str, maximum: int) -> str:
    normalized = str(value or "").strip()
    if not normalized or len(normalized) > maximum:
        raise ValueError(f"{field} must be a non-empty Pi model identifier")
    if any(character.isspace() for character in normalized) or (field == "provider" and "/" in normalized):
        raise ValueError(f"{field} contains unsupported characters")
    return normalized
