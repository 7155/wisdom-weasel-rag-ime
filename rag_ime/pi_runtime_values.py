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

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from .agent_runtime_driver import AgentRuntimeError

__all__ = [
    "PiRuntimeError",
    "PiRuntimeTurnConflict",
    "ToolRetryLineageTracker",
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


@dataclass(frozen=True)
class _ToolAttempt:
    call_id: str
    tool_name: str
    target_signature: str
    retry_parent_id: str = ""


@dataclass
class ToolRetryLineageTracker:
    """Annotate one direct autonomous recovery after a failed Tool call.

    Pi's public lifecycle does not currently carry retry lineage. The runtime
    boundary can still state one narrow fact truthfully: within the same model
    turn, the immediately following call is a recovery attempt when the prior
    call failed and both calls address the same Tool target. Successful
    repeated calls are never grouped, and a different intervening Tool clears
    the recovery window.
    """

    _turn_id: str = ""
    _attempts: dict[str, _ToolAttempt] = field(default_factory=dict)
    _pending_failure: _ToolAttempt | None = None

    def reset(self, turn_id: str = "") -> None:
        self._turn_id = str(turn_id or "")
        self._attempts.clear()
        self._pending_failure = None

    def observe(
        self,
        *,
        event_type: str,
        turn_id: str,
        tool_call_id: str,
        tool_name: str,
        arguments: Mapping[str, object],
        is_error: bool = False,
        explicit_parent_id: str = "",
    ) -> str:
        normalized_turn = str(turn_id or "")
        if normalized_turn != self._turn_id:
            self.reset(normalized_turn)
        call_id = str(tool_call_id or "").strip()
        normalized_tool = str(tool_name or "").strip().lower()
        if not call_id or not normalized_tool:
            return ""
        explicit_parent = str(explicit_parent_id or "").strip()
        if explicit_parent == call_id:
            explicit_parent = ""

        attempt = self._attempts.get(call_id)
        if attempt is None:
            target_signature = _tool_recovery_target(arguments)
            parent_id = ""
            if event_type == "tool_execution_start":
                pending = self._pending_failure
                if (
                    pending is not None
                    and pending.tool_name == normalized_tool
                    and _same_recovery_target(
                        pending.target_signature,
                        target_signature,
                    )
                    and (
                        not explicit_parent
                        or explicit_parent == pending.call_id
                    )
                ):
                    parent_id = pending.call_id
                # Only a directly following Tool call can own the failure.
                self._pending_failure = None
            attempt = _ToolAttempt(
                call_id=call_id,
                tool_name=normalized_tool,
                target_signature=target_signature,
                retry_parent_id=parent_id,
            )
            self._attempts[call_id] = attempt

        if event_type == "tool_execution_end":
            self._pending_failure = attempt if is_error else None
        return attempt.retry_parent_id


def _same_recovery_target(previous: str, current: str) -> bool:
    # Target-less capability calls such as room_commit are still concrete: the
    # bound Session/Dispatch owns their target. A direct same-Tool retry is the
    # only case where two empty signatures match.
    return previous == current


def _tool_recovery_target(arguments: Mapping[str, object]) -> str:
    identity: list[tuple[str, str]] = []
    for key in (
        "path",
        "file",
        "filePath",
        "targetPath",
        "directory",
        "cwd",
        "workdir",
        "workspace",
        "repository",
        "root",
        "roomId",
        "dispatchId",
        "taskId",
        "workItemId",
        "url",
        "query",
        "pattern",
    ):
        value = arguments.get(key)
        if isinstance(value, (str, int, float, bool)) and str(value).strip():
            identity.append((key.lower(), str(value).strip()))
    command = arguments.get("command") or arguments.get("cmd")
    if isinstance(command, str) and command.strip():
        # The executable alone is not a stable command target: two adjacent
        # `python` calls may operate on unrelated files. Normalize whitespace
        # but retain the complete command inside the one-way signature so only
        # an exact direct retry is inferred without persisting command text.
        normalized_command = re.sub(r"\s+", " ", command.strip())
        identity.append(("command", normalized_command))
    if not identity:
        return ""
    encoded = json.dumps(identity, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


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
    text = re.sub(
        r"(?<![A-Za-z0-9_-])(?P<quote>[\"']?)"
        r"(?P<key>[A-Za-z0-9_-]*(?:api[_-]?key|access[_-]?token|password|secret|"
        r"authorization|token|cookie|bearer))(?P=quote)"
        r"(?P<separator>\s*(?:=|:)\s*)"
        r"(?:(?:Bearer|Basic|Token)\s+)?"
        r"(?:\"[^\"\r\n]*\"|'[^'\r\n]*'|[^\s'\"&,}]+)",
        r"\g<quote>\g<key>\g<quote>\g<separator>[REDACTED_SECRET]",
        text,
        flags=re.IGNORECASE,
    )
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
