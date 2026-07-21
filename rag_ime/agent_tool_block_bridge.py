from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from .agent_blocks import MAX_BLOCKS_PER_TURN, normalize_trusted_agent_blocks
from .agent_protocol import AgentBlock


@dataclass
class AgentToolBlockBuffer:
    """Carry trusted tool artifacts to the next final assistant message."""

    _blocks: list[dict[str, object]] = field(default_factory=list)

    def clear(self) -> None:
        self._blocks.clear()

    def capture(self, result: object, *, source_ref: str) -> tuple[dict[str, object], ...]:
        raw_blocks = _result_agent_blocks(result)
        if raw_blocks is None:
            return ()
        try:
            normalized = normalize_trusted_agent_blocks(
                raw_blocks,
                source_kind="pi_tool_result",
                source_ref=source_ref,
            )
        except (TypeError, ValueError):
            return ()
        captured: list[dict[str, object]] = []
        existing = {_block_identity(block) for block in self._blocks}
        for block in normalized:
            try:
                AgentBlock.from_payload(block)
            except (TypeError, ValueError):
                continue
            identity = _block_identity(block)
            if identity in existing or len(self._blocks) >= MAX_BLOCKS_PER_TURN:
                continue
            value = dict(block)
            self._blocks.append(value)
            captured.append(value)
            existing.add(identity)
        return tuple(captured)

    def blocks_for_message(self, message: Mapping[str, object], event_blocks: object) -> object:
        if _message_requests_tools(message) or not self._blocks:
            return event_blocks
        if event_blocks is not None and not isinstance(event_blocks, list):
            return event_blocks
        combined = list(event_blocks) if isinstance(event_blocks, list) else []
        identities = {
            _block_identity(value)
            for value in combined
            if isinstance(value, Mapping)
        }
        for block in self._blocks:
            if len(combined) >= MAX_BLOCKS_PER_TURN:
                break
            identity = _block_identity(block)
            if identity not in identities:
                combined.append(dict(block))
                identities.add(identity)
        self.clear()
        return combined


def _result_agent_blocks(value: object) -> object:
    if not isinstance(value, Mapping):
        return None
    direct = value.get("agentBlocks")
    if direct is not None:
        return direct
    details = value.get("details")
    if isinstance(details, Mapping):
        blocks = details.get("agentBlocks")
        if blocks is not None:
            return blocks
        approval = details.get("approval")
        if isinstance(approval, Mapping):
            receipt = approval.get("receipt")
            if isinstance(receipt, Mapping):
                return receipt.get("agentBlocks")
    return None


def _message_requests_tools(message: Mapping[str, object]) -> bool:
    content = message.get("content")
    if not isinstance(content, list):
        return False
    return any(
        isinstance(item, Mapping)
        and str(item.get("type") or "") in {"toolCall", "tool_call"}
        for item in content
    )


def _block_identity(value: Mapping[str, object]) -> tuple[str, str, str]:
    data = value.get("data") if isinstance(value.get("data"), Mapping) else {}
    return (
        str(value.get("type") or ""),
        str(data.get("mediaId") or value.get("id") or ""),
        str(data.get("sha256") or value.get("digest") or ""),
    )
