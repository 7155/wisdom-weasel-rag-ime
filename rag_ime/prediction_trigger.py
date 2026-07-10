from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Callable, Literal

from .text_utils import compact_whitespace, now_ms, stable_text_hash


TriggerAction = Literal[
    "dirty",
    "coalesced",
    "fire",
    "skip",
    "rate_limited",
    "direct_memory_hit",
]


@dataclass(frozen=True)
class PredictionTriggerConfig:
    idle_ms: int = 500
    min_delta_chars: int = 6
    max_calls_per_10s: int = 2
    ignore_cooldown_ms: int = 1500
    direct_memory_threshold: float = 0.86


@dataclass(frozen=True)
class TriggerDecision:
    action: TriggerAction
    reason: str
    group_id: str
    generation: int
    context_hash: str = ""
    should_call_predictor: bool = False
    direct_candidate: str = ""
    trace_event: str = "prediction_trigger_skipped"


@dataclass
class _GroupState:
    generation: int = 0
    due_at_ms: int = 0
    dirty_chars: int = 0
    punctuation: bool = False
    accepted_continuation: bool = False
    reliable: bool = False
    context_hash: str = ""
    last_called_hash: str = ""
    in_flight_generation: int = 0
    cooldown_until_ms: int = 0
    call_times_ms: deque[int] = field(default_factory=deque)


class PredictionTrigger:
    """Coalesces committed text into one local suffix-prediction transaction."""

    def __init__(
        self,
        config: PredictionTriggerConfig | None = None,
        *,
        clock_ms: Callable[[], int] = now_ms,
    ) -> None:
        self.config = config or PredictionTriggerConfig()
        self._clock_ms = clock_ms
        self._states: dict[str, _GroupState] = defaultdict(_GroupState)

    def record_commit(
        self,
        *,
        group_id: str,
        text: str,
        context_hash: str,
        reliable: bool,
        accepted_candidate: bool = False,
        deleted: bool = False,
        now: int | None = None,
    ) -> TriggerDecision:
        current = self._clock_ms() if now is None else max(0, int(now))
        group = compact_whitespace(group_id) or "app:unknown"
        state = self._states[group]
        state.generation += 1
        surface = compact_whitespace(text)
        if deleted or not surface:
            state.dirty_chars = 0
            state.punctuation = False
            state.accepted_continuation = False
            state.cooldown_until_ms = current + self.config.ignore_cooldown_ms
            return self._decision("skip", "empty_or_deleted", group, state)
        was_dirty = state.due_at_ms > current
        state.dirty_chars += _semantic_chars(surface)
        state.punctuation = state.punctuation or _ends_trigger_punctuation(surface)
        state.accepted_continuation = state.accepted_continuation or bool(accepted_candidate)
        state.reliable = bool(reliable)
        state.context_hash = compact_whitespace(context_hash) or stable_text_hash(surface)
        state.due_at_ms = current if accepted_candidate else current + self.config.idle_ms
        action: TriggerAction = "coalesced" if was_dirty else "dirty"
        return TriggerDecision(
            action=action,
            reason="commit_burst_updated",
            group_id=group,
            generation=state.generation,
            context_hash=state.context_hash,
            trace_event="prediction_trigger_coalesced" if was_dirty else "prediction_trigger_dirty",
        )

    def poll(
        self,
        group_id: str,
        *,
        now: int | None = None,
        direct_memory: tuple[str, float] | None = None,
        provider_kind: str = "local",
    ) -> TriggerDecision:
        current = self._clock_ms() if now is None else max(0, int(now))
        group = compact_whitespace(group_id) or "app:unknown"
        state = self._states[group]
        if current < state.due_at_ms:
            return self._decision("skip", "waiting_idle", group, state)
        if not state.reliable:
            return self._consume_skip(group, state, "unreliable_context")
        if state.context_hash and state.context_hash == state.last_called_hash:
            return self._consume_skip(group, state, "duplicate_context_hash")
        if current < state.cooldown_until_ms and not state.accepted_continuation:
            return self._consume_skip(group, state, "cooldown")
        if not (state.dirty_chars >= self.config.min_delta_chars or state.punctuation or state.accepted_continuation):
            return self._decision("skip", "minimum_delta_not_reached", group, state)
        self._prune_calls(state, current)
        if len(state.call_times_ms) >= self.config.max_calls_per_10s:
            return TriggerDecision(
                action="rate_limited",
                reason="max_calls_per_10s",
                group_id=group,
                generation=state.generation,
                context_hash=state.context_hash,
                trace_event="prediction_trigger_rate_limited",
            )
        if direct_memory:
            candidate, confidence = direct_memory
            candidate = compact_whitespace(candidate)
            if candidate and float(confidence) >= self.config.direct_memory_threshold:
                state.last_called_hash = state.context_hash
                self._consume_dirty(state)
                return TriggerDecision(
                    action="direct_memory_hit",
                    reason="strong_t0_phrase",
                    group_id=group,
                    generation=state.generation,
                    context_hash=state.context_hash,
                    direct_candidate=candidate,
                    trace_event="prediction_trigger_direct_memory_hit",
                )
        if compact_whitespace(provider_kind).lower() not in {"local", "mlx", "minimind"}:
            return self._consume_skip(group, state, "remote_provider_forbidden")
        state.in_flight_generation = state.generation
        state.call_times_ms.append(current)
        state.last_called_hash = state.context_hash
        self._consume_dirty(state, preserve_in_flight=True)
        return TriggerDecision(
            action="fire",
            reason="commit_burst_idle",
            group_id=group,
            generation=state.in_flight_generation,
            context_hash=state.last_called_hash,
            should_call_predictor=True,
            trace_event="prediction_trigger_fired",
        )

    def complete(
        self,
        decision: TriggerDecision,
        *,
        result_count: int,
        ignored: bool = False,
        provider_called: bool = True,
        now: int | None = None,
    ) -> bool:
        current = self._clock_ms() if now is None else max(0, int(now))
        state = self._states[decision.group_id]
        latest = state.in_flight_generation == decision.generation and state.generation == decision.generation
        if state.in_flight_generation == decision.generation:
            state.in_flight_generation = 0
        if not provider_called and state.call_times_ms:
            state.call_times_ms.pop()
        if ignored or int(result_count) <= 0:
            state.cooldown_until_ms = current + self.config.ignore_cooldown_ms
        return latest

    def clear(self) -> None:
        self._states.clear()

    def _consume_skip(self, group: str, state: _GroupState, reason: str) -> TriggerDecision:
        self._consume_dirty(state)
        return self._decision("skip", reason, group, state)

    @staticmethod
    def _consume_dirty(state: _GroupState, *, preserve_in_flight: bool = False) -> None:
        state.due_at_ms = 0
        state.dirty_chars = 0
        state.punctuation = False
        state.accepted_continuation = False
        if not preserve_in_flight:
            state.in_flight_generation = 0

    @staticmethod
    def _decision(action: TriggerAction, reason: str, group: str, state: _GroupState) -> TriggerDecision:
        return TriggerDecision(
            action=action,
            reason=reason,
            group_id=group,
            generation=state.generation,
            context_hash=state.context_hash,
            trace_event={
                "dirty": "prediction_trigger_dirty",
                "coalesced": "prediction_trigger_coalesced",
                "fire": "prediction_trigger_fired",
                "rate_limited": "prediction_trigger_rate_limited",
                "direct_memory_hit": "prediction_trigger_direct_memory_hit",
            }.get(action, "prediction_trigger_skipped"),
        )

    @staticmethod
    def _prune_calls(state: _GroupState, current: int) -> None:
        cutoff = current - 10_000
        while state.call_times_ms and state.call_times_ms[0] < cutoff:
            state.call_times_ms.popleft()


def _semantic_chars(text: str) -> int:
    return sum(1 for char in text if not char.isspace())


def _ends_trigger_punctuation(text: str) -> bool:
    return bool(text) and text[-1] in "。！？；\n"
