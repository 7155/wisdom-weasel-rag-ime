"""Pure projections of already-loaded Pi transcript data.

The Host adapter and history readers share durable branch selection, recent
windows, append order and stable message/activity identity. Inputs are not
mutated; loading and validating files, Host communication, Session state and
settlement remain with the caller. Media URLs use the caller-supplied resolver.
"""

from __future__ import annotations

import json
import uuid
from collections import deque
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import datetime
from typing import cast

from rag_ime.agent_protocol import AgentEventEnvelope
from rag_ime.pi.public import (
    pi_message_payload,
    inspectable_tool_result,
    pi_message_id,
    pi_message_completes_public_turn,
    pi_message_continues_public_turn,
    pi_message_is_public,
    public_code_tool_activity,
    public_knowledge_tool_activity,
    public_reasoning_summaries,
    redact_mapping,
    runtime_tool_result_is_error,
)
from rag_ime.pi.values import (
    as_integer,
    as_mapping,
    redact_runtime_text,
)


__all__ = [
    "durable_branch_messages",
    "durable_tool_history_events",
    "recent_messages_from_proven_tail",
    "recent_public_message_window",
    "recent_tool_history_events",
    "history_entry_timestamps",
    "history_entry_ordinals",
    "durable_public_assistant_counts",
    "assistant_projection_fingerprint",
    "history_message_fingerprint",
    "DURABLE_TURN_ID_KEY",
]


_RECENT_SESSION_TURN_LIMIT = 6
_RECENT_SESSION_MESSAGE_LIMIT = 24
_RECENT_SESSION_RESPONSE_BYTES = 48 * 1024
_RECENT_SESSION_ACTIVITY_LIMIT = 16
_RECENT_SESSION_ACTIVITY_BYTES = 16 * 1024
_TURN_BINDING_CUSTOM_TYPE = "rag-ime.pi-turn-binding"
DURABLE_TURN_ID_KEY = "_ragImeTurnId"


def durable_branch_messages(
    raw_entries: Sequence[object],
    *,
    leaf_id: str = "",
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Return ordered message values from Pi's selected durable branch.

    Modern Pi snapshots expose the complete append-only entry tree alongside
    a compacted Provider message window.  Parent links and ``leafId`` select
    one branch.  Older test/runtime payloads were flat, so they retain their
    append order instead of being reduced to the last entry.
    """

    entries = [dict(value) for value in raw_entries if isinstance(value, Mapping)]
    if not entries:
        return [], []
    by_id = {
        str(entry.get("id") or ""): entry
        for entry in entries
        if str(entry.get("id") or "")
    }
    has_parent_links = any(str(entry.get("parentId") or "") for entry in entries)
    selected_entries = entries
    selected_leaf = str(leaf_id or "").strip()
    if has_parent_links:
        if selected_leaf not in by_id:
            selected_leaf = next(
                (
                    str(entry.get("id") or "")
                    for entry in reversed(entries)
                    if str(entry.get("id") or "")
                ),
                "",
            )
        branch: list[dict[str, object]] = []
        visited: set[str] = set()
        cursor = selected_leaf
        while cursor and cursor not in visited:
            visited.add(cursor)
            entry = by_id.get(cursor)
            if entry is None:
                break
            branch.append(entry)
            cursor = str(entry.get("parentId") or "")
        if branch:
            selected_entries = list(reversed(branch))

    messages: list[dict[str, object]] = []
    message_entries: list[dict[str, object]] = []
    pending_turn_binding: tuple[str, str] | None = None
    for entry in selected_entries:
        if (
            str(entry.get("type") or "") == "custom"
            and str(entry.get("customType") or "") == _TURN_BINDING_CUSTOM_TYPE
        ):
            binding = as_mapping(entry.get("data"))
            turn_id = str(binding.get("turnId") or "").strip()
            if binding.get("schemaVersion") == "rag-ime.pi-turn-binding.v1" and turn_id:
                pending_turn_binding = (
                    turn_id,
                    str(binding.get("clientMessageId") or "").strip(),
                )
            continue
        if str(entry.get("type") or "") != "message":
            continue
        raw_message = entry.get("message")
        if not isinstance(raw_message, Mapping):
            continue
        message = dict(raw_message)
        if not str(message.get("id") or "") and str(entry.get("id") or ""):
            message["id"] = str(entry["id"])
        if as_integer(message.get("timestamp")) <= 0:
            timestamp = _pi_history_entry_timestamp_ms(entry.get("timestamp"))
            if timestamp > 0:
                message["timestamp"] = timestamp
        if str(
            message.get("role") or ""
        ).strip().lower() == "user" and not pi_message_continues_public_turn(message):
            if pending_turn_binding is not None:
                turn_id, client_message_id = pending_turn_binding
                message[DURABLE_TURN_ID_KEY] = turn_id
                if client_message_id:
                    message["clientMessageId"] = client_message_id
            pending_turn_binding = None
        messages.append(message)
        message_entries.append(entry)
    return messages, message_entries


def recent_messages_from_proven_tail(
    entries: list[dict[str, object]],
    *,
    leaf_id: str,
    header_id: str,
) -> (
    tuple[
        list[dict[str, object]],
        list[dict[str, object]],
        bool,
    ]
    | None
):
    # Older Pi transcripts are flat append-order logs. Their last entry is not
    # a branch leaf, so the bounded suffix cannot prove which earlier messages
    # belong to the visible recent window. Preserve the legacy full-read path.
    if not any(str(entry.get("parentId") or "") for entry in entries):
        return None
    by_id = {
        str(entry.get("id") or ""): entry
        for entry in entries
        if str(entry.get("id") or "")
    }
    if not leaf_id or leaf_id not in by_id:
        return None
    branch: list[dict[str, object]] = []
    visited: set[str] = set()
    cursor = leaf_id
    complete = False
    while cursor:
        if cursor == header_id:
            complete = True
            break
        if cursor in visited:
            return None
        visited.add(cursor)
        entry = by_id.get(cursor)
        if entry is None:
            break
        branch.append(entry)
        cursor = str(entry.get("parentId") or "")
    if not cursor:
        complete = True
    if not branch:
        return None
    selected_entries = list(reversed(branch))
    messages, _message_entries = durable_branch_messages(
        selected_entries,
        leaf_id=leaf_id,
    )
    if complete or _completed_public_turn_count(messages) > _RECENT_SESSION_TURN_LIMIT:
        return messages, selected_entries, True
    # The selected leaf and every entry back to the bounded-tail edge are
    # proven. This suffix is safe for an immediate partial first paint; a
    # background authoritative repair fills older turns and publishes the
    # existing snapshot_required control event. A missing leaf still returns
    # None above and never guesses a branch.
    return (messages, selected_entries, False) if messages else None


def _completed_public_turn_count(raw_messages: Sequence[object]) -> int:
    completed = 0
    current_started = False
    current_completed = False
    for value in raw_messages:
        if not isinstance(value, Mapping) or not pi_message_is_public(value):
            continue
        role = str(value.get("role") or "assistant").strip().lower()
        opens_turn = role == "user" and not pi_message_continues_public_turn(value)
        if opens_turn and current_started:
            if current_completed:
                completed += 1
            current_completed = False
        current_started = True
        if role == "assistant" and pi_message_completes_public_turn(value):
            current_completed = True
    if current_started and current_completed:
        completed += 1
    return completed


def recent_public_message_window(
    raw_messages: Sequence[object],
    *,
    session_id: str,
    media_resolver: Callable[[str, str, str], str] | None,
    raw_entries: Sequence[object] | None = None,
    maximum_turns: int = _RECENT_SESSION_TURN_LIMIT,
    maximum_messages: int = _RECENT_SESSION_MESSAGE_LIMIT,
    maximum_response_bytes: int = _RECENT_SESSION_RESPONSE_BYTES,
) -> list[dict[str, object]]:
    """Return recent complete turns plus the current durable user anchor.

    A hard refresh can happen after Pi has appended the user's message but
    before the assistant has completed the turn.  Omitting that final user
    row makes the refreshed conversation look as if the send never happened,
    especially once a long Tool run pushes the original live event out of the
    bounded event tail.  Keep only the public user rows from that one pending
    turn; assistant progress continues to come from live events.
    """

    entry_timestamps = history_entry_timestamps(raw_entries or [])
    entry_ordinals = history_entry_ordinals(raw_entries or [])
    turns: list[tuple[list[dict[str, object]], bool]] = []
    current: list[dict[str, object]] = []
    current_completed = False
    for value in raw_messages:
        if not isinstance(value, Mapping) or not pi_message_is_public(value):
            continue
        raw = dict(value)
        fingerprint = history_message_fingerprint(raw)
        timestamp_queue = entry_timestamps.get(fingerprint)
        ordinal_queue = entry_ordinals.get(fingerprint)
        if timestamp_queue:
            raw["timestamp"] = timestamp_queue.popleft()
        if ordinal_queue:
            raw["_recentTimelineSequence"] = float(ordinal_queue.popleft())
        role = str(raw.get("role") or "assistant").strip().lower()
        opens_turn = role == "user" and not pi_message_continues_public_turn(raw)
        if opens_turn and current:
            turns.append((current, current_completed))
            current = []
            current_completed = False
        current.append(raw)
        if role == "assistant" and pi_message_completes_public_turn(raw):
            current_completed = True
    if current:
        turns.append((current, current_completed))

    turn_limit = max(1, min(int(maximum_turns), _RECENT_SESSION_TURN_LIMIT))
    eligible_turns: list[list[dict[str, object]]] = [
        messages for messages, completed in turns if completed
    ]
    if turns and not turns[-1][1]:
        pending_user_rows = [
            message
            for message in turns[-1][0]
            if str(message.get("role") or "").strip().lower() == "user"
        ]
        if pending_user_rows:
            eligible_turns.append(pending_user_rows)
    selected_turns = eligible_turns[-turn_limit:]
    selected_reversed: list[list[dict[str, object]]] = []
    selected_message_count = 0
    for raw_turn in reversed(selected_turns):
        first = raw_turn[0]
        first_id = pi_message_id(first, "history")
        turn_id = str(first.get(DURABLE_TURN_ID_KEY) or f"history:{first_id}")
        projected: list[dict[str, object]] = []
        for raw in raw_turn:
            payload = pi_message_payload(
                raw,
                session_id=session_id,
                turn_id=turn_id,
                media_resolver=media_resolver,
                message_id=pi_message_id(raw, "history"),
            ).to_payload()
            timeline_sequence = raw.get("_recentTimelineSequence")
            if isinstance(timeline_sequence, float):
                payload["timelineSequence"] = (
                    timeline_sequence + 0.9
                    if str(raw.get("role") or "assistant").lower() == "assistant"
                    else timeline_sequence
                )
            projected.append(payload)
        if not projected or selected_message_count + len(projected) > maximum_messages:
            break
        candidate = [
            *projected,
            *[message for turn in reversed(selected_reversed) for message in turn],
        ]
        encoded = json.dumps(
            {"messages": candidate},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(encoded) > maximum_response_bytes and not selected_reversed:
            # The newest turn is the first-paint anchor.  A single long answer
            # must not turn a valid recent response into an empty screen or
            # force the UI back onto the blocking full-history path.
            projected = _compact_recent_turn(projected)
            candidate = projected
            encoded = json.dumps(
                {"messages": candidate},
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        if len(encoded) > maximum_response_bytes:
            break
        selected_reversed.append(projected)
        selected_message_count += len(projected)

    return [message for turn in reversed(selected_reversed) for message in turn]


def recent_tool_history_events(
    raw_messages: Sequence[object],
    *,
    raw_entries: Sequence[object],
    projected_messages: list[dict[str, object]],
    session_id: str,
) -> list[dict[str, object]]:
    """Keep only bounded activity belonging to the visible recent turns."""

    visible_turn_ids = {
        str(message.get("turnId") or "")
        for message in projected_messages
        if str(message.get("turnId") or "")
    }
    if not visible_turn_ids:
        return []
    return [
        event
        for event in durable_tool_history_events(
            raw_messages,
            session_id=session_id,
            raw_entries=raw_entries,
            maximum_tools=_RECENT_SESSION_ACTIVITY_LIMIT,
            maximum_public_chars=_RECENT_SESSION_ACTIVITY_BYTES,
        )
        if str(event.get("turnId") or "") in visible_turn_ids
    ]


def _compact_recent_turn(
    messages: list[dict[str, object]],
    *,
    text_limit: int = 2_048,
) -> list[dict[str, object]]:
    """Bound long first-paint text while making the partial projection clear."""

    compacted: list[dict[str, object]] = []
    marker = "\n\n[近期快照已截断；完整内容仍保留在历史中]"
    for message in messages:
        next_message = dict(message)
        blocks: list[dict[str, object]] = []
        for value in cast(Iterable[object], message.get("blocks") or []):
            if not isinstance(value, Mapping):
                continue
            block = dict(value)
            data = block.get("data")
            if isinstance(data, Mapping):
                next_data = dict(data)
                text = next_data.get("text")
                if isinstance(text, str) and len(text) > text_limit:
                    next_data["text"] = text[:text_limit].rstrip() + marker
                    next_data["truncated"] = True
                    next_data["originalChars"] = len(text)
                block["data"] = next_data
            blocks.append(block)
        next_message["blocks"] = blocks
        compacted.append(next_message)
    return compacted


def durable_tool_history_events(
    raw_messages: Sequence[object],
    *,
    session_id: str,
    raw_entries: Sequence[object] | None = None,
    maximum_tools: int | None = 256,
    maximum_public_chars: int | None = 48_000,
) -> list[dict[str, object]]:
    """Rebuild the public tool timeline from Pi's durable transcript.

    The conversation transcript intentionally hides protocol messages, but the
    tool activity strip still needs to survive a Gateway restart or replay
    eviction. Only the same redacted projection used by live events is rebuilt
    here; full arguments and results remain available solely through the
    local-only transient Debug endpoint.
    """

    events: list[tuple[str, str, str, int, dict[str, object], float | None]] = []
    entry_timestamps = history_entry_timestamps(raw_entries or [])
    entry_ordinals = history_entry_ordinals(raw_entries or [])
    # Durable branch projection supplies entry ids to id-less messages. Keep
    # reasoning identity tied to the original wire message, as in live events,
    # so a snapshot during the same turn cannot add a second summary card.
    source_message_ids = {
        str(entry.get("id")): pi_message_id(as_mapping(entry.get("message")), "history")
        for value in raw_entries or []
        for entry in [as_mapping(value)]
        if entry.get("type") == "message" and entry.get("id")
    }
    current_turn_id = ""
    activity_order: list[str] = []
    tool_names: dict[str, str] = {}
    tool_arguments: dict[str, Mapping[str, object]] = {}
    for raw_value in raw_messages:
        if not isinstance(raw_value, Mapping):
            continue
        raw = raw_value
        role = str(raw.get("role") or "assistant").strip().lower()
        message_id = pi_message_id(raw, "history")
        if role == "user":
            if not pi_message_continues_public_turn(raw):
                current_turn_id = str(
                    raw.get(DURABLE_TURN_ID_KEY) or f"history:{message_id}"
                )
            continue
        turn_id = current_turn_id or f"history:{message_id}"
        fingerprint = history_message_fingerprint(raw)
        durable_timestamps = entry_timestamps.get(fingerprint)
        durable_ordinals = entry_ordinals.get(fingerprint)
        created_at_ms = (
            durable_timestamps.popleft()
            if durable_timestamps
            else as_integer(raw.get("timestamp"))
        )
        source_ordinal = durable_ordinals.popleft() if durable_ordinals else None
        source_sequence = float(source_ordinal) if source_ordinal is not None else None
        if role == "assistant":
            summaries = public_reasoning_summaries(raw)
            if summaries:
                source_message_id = source_message_ids.get(message_id, message_id)
                reasoning_id = f"reasoning:{source_message_id}:0"
                events.append(
                    (
                        reasoning_id,
                        "reasoning_summary",
                        turn_id,
                        created_at_ms,
                        {
                            "requestId": reasoning_id,
                            "sourceMessageId": source_message_id,
                            "summary": summaries[-1],
                            "items": summaries,
                            "source": "provider_reasoning_summary",
                            "state": "completed",
                        },
                        source_sequence + 0.1 if source_sequence is not None else None,
                    )
                )
                activity_order.append(reasoning_id)
            # Pi may durably retain a partial assistant message when a
            # Provider request fails and the Tool loop retries.  A toolCall
            # block in that failed message is only a Provider draft: no
            # tool_execution_start was emitted and no side effect occurred.
            # Projecting it as tool_started invents an execution and can make
            # one real delegation look like two after recovery.
            if str(raw.get("stopReason") or "").strip().lower() == "error" or bool(
                str(raw.get("errorMessage") or "").strip()
            ):
                continue
            content = cast(
                list[object],
                raw.get("content") if isinstance(raw.get("content"), list) else [],
            )
            for item_index, item_value in enumerate(content):
                item = as_mapping(item_value)
                if str(item.get("type") or "") not in {"toolCall", "tool_call"}:
                    continue
                tool_call_id = str(
                    item.get("id") or item.get("toolCallId") or ""
                ).strip()
                tool_name = str(item.get("name") or item.get("toolName") or "").strip()
                if not tool_call_id or not tool_name:
                    continue
                raw_args: Mapping[str, object] = _pi_tool_arguments(item)
                payload: dict[str, object] = {
                    "toolCallId": tool_call_id,
                    "toolName": tool_name,
                    "args": redact_mapping(raw_args),
                    "isError": False,
                }
                public_result = public_code_tool_activity(tool_name, raw_args)
                public_result.update(
                    public_knowledge_tool_activity(tool_name, raw_args)
                )
                if public_result:
                    payload["publicResult"] = public_result
                events.append(
                    (
                        tool_call_id,
                        "tool_started",
                        turn_id,
                        created_at_ms + item_index,
                        payload,
                        source_sequence + 0.2 + (item_index / 1_000)
                        if source_sequence is not None
                        else None,
                    )
                )
                if tool_call_id not in tool_names:
                    activity_order.append(tool_call_id)
                tool_names[tool_call_id] = tool_name
                tool_arguments[tool_call_id] = raw_args
            continue
        if role not in {"toolresult", "tool_result"}:
            continue
        tool_call_id = str(
            raw.get("toolCallId") or raw.get("tool_call_id") or ""
        ).strip()
        if not tool_call_id:
            continue
        tool_name = str(
            raw.get("toolName")
            or raw.get("tool_name")
            or tool_names.get(tool_call_id)
            or "tool"
        ).strip()
        if tool_call_id not in tool_names:
            activity_order.append(tool_call_id)
        tool_names[tool_call_id] = tool_name
        raw_result = _pi_tool_result(raw)
        raw_args = tool_arguments.get(tool_call_id, {})
        payload = {
            "toolCallId": tool_call_id,
            "toolName": tool_name,
            "args": {},
            "result": raw_result,
            "isError": runtime_tool_result_is_error(
                tool_name,
                raw,
                reported_is_error=bool(raw.get("isError") or raw.get("is_error")),
            ),
        }
        public_result = public_code_tool_activity(
            tool_name,
            raw_args,
            raw_result,
        )
        public_result.update(
            public_knowledge_tool_activity(
                tool_name,
                raw_args,
                raw_result,
            )
        )
        if public_result:
            payload["publicResult"] = public_result
        events.append(
            (
                tool_call_id,
                "tool_finished",
                turn_id,
                created_at_ms,
                payload,
                source_sequence + 0.8 if source_sequence is not None else None,
            )
        )

    events_by_activity: dict[
        str,
        list[tuple[str, str, str, int, dict[str, object], float | None]],
    ] = {}
    for activity_event in events:
        events_by_activity.setdefault(activity_event[0], []).append(activity_event)
    allowed_order: list[str] = []
    used_chars = 0
    candidate_order = (
        activity_order
        if maximum_tools is None
        else activity_order[-max(1, maximum_tools) :]
    )
    for activity_id in reversed(candidate_order):
        activity_events = events_by_activity.get(activity_id, [])
        activity_chars = sum(
            len(
                json.dumps(
                    {
                        "eventType": event_type,
                        "turnId": turn_id,
                        "payload": payload,
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            )
            + 320
            for _identity, event_type, turn_id, _created_at_ms, payload, _timeline_sequence in activity_events
        )
        if (
            maximum_public_chars is not None
            and allowed_order
            and used_chars + activity_chars
            > max(
                4_000,
                int(maximum_public_chars),
            )
        ):
            break
        allowed_order.append(activity_id)
        used_chars += activity_chars
    allowed_ids = set(allowed_order)
    selected = [event for event in events if event[0] in allowed_ids]
    result: list[dict[str, object]] = []
    for sequence, (
        tool_call_id,
        event_type,
        turn_id,
        created_at_ms,
        payload,
        timeline_sequence,
    ) in enumerate(selected, start=1):
        event_id = (
            f"{session_id}:history-tool:"
            f"{uuid.uuid5(uuid.NAMESPACE_URL, f'{session_id}:{tool_call_id}:{event_type}').hex[:20]}"
        )
        event = AgentEventEnvelope(
            event_id=event_id,
            session_id=session_id,
            turn_id=turn_id,
            sequence=sequence,
            created_at_ms=created_at_ms,
            event_type=event_type,
            payload=payload,
            resume_token=event_id,
        ).to_payload()
        if timeline_sequence is not None:
            event["timelineSequence"] = timeline_sequence
        result.append(event)
    return result


def history_entry_timestamps(raw_entries: Sequence[object]) -> dict[str, deque[int]]:
    """Match Pi context messages to their durable transcript append times.

    Assistant message timestamps mark the beginning of the provider request.
    The enclosing transcript entry is appended when the tool call is emitted,
    which is the correct start time for a restored tool execution.
    """

    timestamps: dict[str, deque[int]] = {}
    for entry_value in raw_entries:
        entry = as_mapping(entry_value)
        if str(entry.get("type") or "") != "message":
            continue
        message = as_mapping(entry.get("message"))
        # `durable_branch_messages` gives id-less transcript messages the
        # enclosing entry id before projection. Normalize the same way here so
        # the append timestamp still matches the projected message.
        if not str(message.get("id") or "") and str(entry.get("id") or ""):
            message = {**message, "id": str(entry["id"])}
        fingerprint = history_message_fingerprint(message)
        created_at_ms = _pi_history_entry_timestamp_ms(entry.get("timestamp"))
        if not fingerprint or created_at_ms <= 0:
            continue
        timestamps.setdefault(fingerprint, deque()).append(created_at_ms)
    return timestamps


def history_entry_ordinals(raw_entries: Sequence[object]) -> dict[str, deque[int]]:
    """Map durable messages to their append order in the selected branch."""

    ordinals: dict[str, deque[int]] = {}
    ordinal = 0
    for entry_value in raw_entries:
        entry = as_mapping(entry_value)
        if str(entry.get("type") or "") != "message":
            continue
        ordinal += 1
        message = as_mapping(entry.get("message"))
        # Keep this identity normalization aligned with
        # `durable_branch_messages` and `history_entry_timestamps`.
        if not str(message.get("id") or "") and str(entry.get("id") or ""):
            message = {**message, "id": str(entry["id"])}
        fingerprint = history_message_fingerprint(message)
        if fingerprint:
            ordinals.setdefault(fingerprint, deque()).append(ordinal)
    return ordinals


def durable_public_assistant_counts(
    raw_entries: Sequence[object],
    *,
    session_id: str,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entry_value in raw_entries:
        entry = as_mapping(entry_value)
        if str(entry.get("type") or "") != "message":
            continue
        message = as_mapping(entry.get("message"))
        if str(
            message.get("role") or ""
        ).lower() != "assistant" or not pi_message_is_public(message):
            continue
        payload = pi_message_payload(
            message,
            session_id=session_id,
            turn_id="durable-transcript",
            message_id=str(entry.get("id") or "durable-transcript"),
        ).to_payload()
        fingerprint = assistant_projection_fingerprint(payload)
        counts[fingerprint] = counts.get(fingerprint, 0) + 1
    return counts


def assistant_projection_fingerprint(
    payload: Mapping[str, object],
) -> str:
    return json.dumps(
        {
            "blocks": [
                {
                    key: block.get(key)
                    for key in (
                        "type",
                        "status",
                        "presentationKind",
                        "data",
                        "summary",
                        "visibility",
                    )
                    if block.get(key) is not None
                }
                for block in cast(Iterable[object], payload.get("blocks") or [])
                if isinstance(block, Mapping)
            ],
            "attachments": payload.get("attachments") or [],
            "citations": payload.get("citations") or [],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def history_message_fingerprint(message: Mapping[str, object]) -> str:
    if not message:
        return ""
    try:
        return json.dumps(
            dict(message),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError):
        return ""


def _pi_history_entry_timestamp_ms(value: object) -> int:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return max(0, int(value))
    text = str(value or "").strip()
    if not text:
        return 0
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return 0
    return max(0, int(parsed.timestamp() * 1_000))


def _pi_tool_arguments(item: Mapping[str, object]) -> dict[str, object]:
    raw = (
        item.get("arguments") if item.get("arguments") is not None else item.get("args")
    )
    if isinstance(raw, Mapping):
        return dict(raw)
    if isinstance(raw, str) and raw.strip():
        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError:
            return {"value": redact_runtime_text(raw)}
        if isinstance(decoded, Mapping):
            return dict(decoded)
    return {}


def _pi_tool_result(raw: Mapping[str, object]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key in ("details", "result"):
        value = raw.get(key)
        if isinstance(value, Mapping):
            # Mapping inputs preserve their shape through credential redaction.
            result.update(cast(Mapping[str, object], inspectable_tool_result(value)))
    content = raw.get("content")
    if content is not None:
        result["content"] = inspectable_tool_result(content)
    return result
