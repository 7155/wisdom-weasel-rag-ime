"""Pure adapters from existing metadata-only observability records.

The adapter is intentionally not an ObservationStore consumer: callers can
pass a snapshot or a bounded list from any producer, and the result remains a
common TraceEnvelope.  No persistence, event acknowledgement, or producer
side effect happens here.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from numbers import Real
import math
import re

from .trace_runtime import (
    TraceContractError,
    TraceEnvelope,
    build_trace_envelope,
    make_span,
    project_public_span_attributes,
    project_public_span_metrics,
)


_OBSERVATION_STATUSES = frozenset({"queued", "running", "waiting", "completed", "failed", "cancelled", "expired", "info"})
_TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})
_MEMORY_TERMINAL_STATUSES = _TERMINAL_STATUSES | {"expired"}
_BROWSER_COMMAND_STATUSES = frozenset({"queued", "claimed", "completed", "failed", "cancelled"})
_SENSITIVE_KEY_PARTS = frozenset({"arg", "args", "content", "input", "message", "output", "prompt", "query", "reasoning", "result", "response", "text", "transcript"})
_BINDING_KEYS = (
    "sessionId",
    "turnId",
    "roomId",
    "runId",
    "sourceLoopId",
    "workItemId",
    "caseId",
)
_TRACE_LINK_REF_KINDS = frozenset({"trace_link", "traceLink", "trace-link"})
_STRUCTURED_EVIDENCE_REF_KINDS = frozenset(
    {"retrieval_evidence", "memory_evidence", "knowledge_evidence"}
)
_OPERATIONAL_REF_KINDS = frozenset(
    {
        "active_rag",
        "agent_event",
        "agent_message",
        "approval",
        "browser_command",
        "dispatch",
        "input_generation",
        "intercom",
        "knowledge_retrieval",
        "memory_recall",
        "memory_run",
        "participant",
        "room_event",
        "room_post",
        "tool_call",
        "work_item",
    }
)
_TRACE_TURN_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}\Z")


def envelope_from_browser_trace(trace: Mapping[str, object]) -> TraceEnvelope:
    """Project one BrowserControl public command trace into a common envelope.

    ``BrowserControlService.traces`` is the authority for command lifecycle
    and timestamps.  Its redacted ``result`` is deliberately ignored here:
    URLs, snapshot identifiers, page text, and extension result payloads are
    not common-trace data.  Browser commands have no native ``traceId`` yet,
    so the stable command ID is used to derive a deterministic trace identity.
    """

    command_id = _required(trace.get("commandId"), "browser commandId")
    action = _required(trace.get("action"), "browser action")
    raw_status = _required(trace.get("status"), "browser command status")
    if raw_status not in _BROWSER_COMMAND_STATUSES:
        raise TraceContractError(f"unsupported browser command status: {raw_status}")
    span_status = "running" if raw_status == "claimed" else raw_status
    started_at = _integer(trace.get("createdAtMs"), "browser createdAtMs")
    completed_at = trace.get("completedAtMs")
    completed = _integer(completed_at, "browser completedAtMs") if completed_at is not None else None
    duration_value = trace.get("durationMs")
    duration = _integer(duration_value, "browser durationMs") if duration_value is not None else None
    measured = (
        completed is not None
        and duration is not None
        and completed >= started_at
        and duration == completed - started_at
    )
    span_id = f"span:browser:command:{command_id}"
    attributes: dict[str, object] = {
        "commandId": command_id,
        "action": action,
        "lifecycleAuthority": "browser_control",
    }
    device_id = _optional_text(trace.get("deviceId"))
    if device_id:
        attributes["deviceId"] = device_id
    session_id = _optional_text(trace.get("sessionId"))
    binding = {
        **({"sessionId": session_id} if session_id else {}),
        "sourceLoopId": f"browser-command:{command_id}",
    }
    span = make_span(
        span_id=span_id,
        name=f"browser.command.{action}",
        status=span_status,
        started_at_ms=started_at,
        ended_at_ms=completed if measured else None,
        recorded=measured,
        unavailable_reason=("duration_not_recorded" if duration is None else "inconsistent_timing")
        if not measured
        else "",
        attributes=attributes,
    )
    envelope_status = (
        raw_status
        if raw_status in _TERMINAL_STATUSES
        else "building"
    )
    updated_at = completed if completed is not None else started_at
    explicit_trace_id = _optional_text(trace.get("traceId"))
    return build_trace_envelope(
        trace_id=explicit_trace_id or f"trace:browser:command:{command_id}",
        source_kind="browser_control",
        input_text="",
        binding=binding,
        spans=(span,),
        status=envelope_status,
        input_normalization="browser-command-redacted",
        created_at_ms=started_at,
        updated_at_ms=max(started_at, updated_at),
    )


def envelope_from_prediction_frame(frame: Mapping[str, object]) -> TraceEnvelope:
    """Project one redacted prediction-live frame into a common envelope.

    Prediction frames are point-in-time frontend diagnostics.  They carry no
    authoritative start/end pair, so lane ``elapsedMs`` values remain metrics
    and the common span stays explicitly unrecorded.  Raw input, preedit,
    committed context, candidate text, trace-event reasons, and snapshot IDs
    are never copied.
    """

    recorded_at = _integer(frame.get("recordedAtMs"), "prediction recordedAtMs")
    explicit_trace_id = _optional_text(frame.get("traceId"))
    session_id = _optional_text(frame.get("sessionId"))
    request_value = frame.get("requestSeq")
    request_seq = _integer(request_value, "prediction requestSeq") if request_value is not None else None
    if explicit_trace_id:
        trace_id = explicit_trace_id
        source_loop_id = f"prediction-frame:{trace_id}"
    else:
        if not session_id or request_seq is None or request_seq < 1:
            raise TraceContractError("prediction frame identity unavailable")
        trace_id = f"trace:prediction:{session_id}:request-{request_seq}"
        source_loop_id = f"prediction-frame:{session_id}:{request_seq}"

    attributes: dict[str, object] = {"lifecycleAuthority": "rime_prediction_frame"}
    metrics: dict[str, object] = {}
    safe_lane_attributes = (
        "called",
        "timedOut",
        "staleDropped",
        "waitingForLatest",
        "predictionCount",
        "suggestionCount",
        "activeGeneration",
    )
    for lane_name, lane_key in (("rag", "ragLane"), ("model", "modelLane")):
        lane = frame.get(lane_key)
        if not isinstance(lane, Mapping):
            continue
        if "elapsedMs" in lane:
            elapsed = lane.get("elapsedMs")
            if isinstance(elapsed, bool) or not isinstance(elapsed, Real):
                raise TraceContractError(f"prediction {lane_name} duration must be numeric")
            elapsed_number = float(elapsed)
            if not math.isfinite(elapsed_number) or elapsed_number < 0:
                raise TraceContractError(f"prediction {lane_name} duration must be finite")
            metrics[f"{lane_name}ElapsedMs"] = int(elapsed_number) if elapsed_number.is_integer() else elapsed_number
        for field in safe_lane_attributes:
            value = lane.get(field)
            if isinstance(value, bool):
                attributes[f"{lane_name}{field[0].upper()}{field[1:]}"] = value
            elif isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                attributes[f"{lane_name}{field[0].upper()}{field[1:]}"] = value

    for key in ("requestSeq", "frontendRevision", "selectionEpoch"):
        value = frame.get(key)
        if value is None:
            continue
        normalized = _integer(value, f"prediction {key}")
        attributes[key] = normalized
    panel_session_id = _optional_text(frame.get("panelSessionId"))
    if panel_session_id:
        attributes["panelSessionId"] = panel_session_id
    prediction_session = frame.get("predictionSession")
    if isinstance(prediction_session, Mapping):
        phase = _optional_text(prediction_session.get("phase"))
        if phase and len(phase) <= 80 and re.fullmatch(r"[A-Za-z0-9_.:-]+", phase):
            attributes["phase"] = phase
    display = frame.get("display")
    if isinstance(display, Mapping):
        visible_count = display.get("visibleCandidateCount")
        if visible_count is not None:
            attributes["visibleCandidateCount"] = _integer(
                visible_count,
                "prediction visibleCandidateCount",
            )

    span = make_span(
        span_id=f"span:prediction:frame:{session_id or trace_id}",
        name="input.prediction",
        status="completed",
        started_at_ms=recorded_at,
        recorded=False,
        unavailable_reason="duration_not_recorded",
        metrics=metrics,
        attributes=attributes,
    )
    binding = {"sourceLoopId": source_loop_id}
    if session_id:
        binding["sessionId"] = session_id
    return build_trace_envelope(
        trace_id=trace_id,
        source_kind="rime_prediction",
        input_text="",
        binding=binding,
        spans=(span,),
        status="completed",
        input_normalization="prediction-frame-redacted",
        created_at_ms=recorded_at,
        updated_at_ms=recorded_at,
    )


def envelope_from_observations(
    observations: Sequence[Mapping[str, object]],
    *,
    input_text: str = "",
    input_fingerprint: str | None = None,
) -> TraceEnvelope:
    """Project a bounded ObservationStore list into one common trace.

    Existing explicit duration is used only when it agrees with the recorded
    start/end bounds.  A missing or inconsistent duration becomes an
    unavailable span; the adapter never invents latency from a terminal event.
    """

    if not observations:
        raise TraceContractError("at least one observation is required")
    trace_ids = {_required(item.get("traceId"), "traceId") for item in observations}
    if len(trace_ids) != 1:
        raise TraceContractError("all observations must belong to the same trace")
    ordered = sorted(enumerate(observations), key=_observation_order)
    trace_id = next(iter(trace_ids))
    _reject_contradictory_input_generation_terminals(ordered)
    groups = _aggregate_span_groups(ordered)
    span_ids = {span_id for span_id, _ in groups}
    spans = _settle_room_root_spans(
        tuple(_span_from_group(span_id, records, span_ids) for span_id, records in groups)
    )
    spans = _settle_memory_phase_spans(
        spans,
        trace_id=trace_id,
        latest_status=str(ordered[-1][1].get("status") or "info"),
    )
    statuses = [span.status for span in spans]
    latest_status = str(ordered[-1][1].get("status") or "info")
    if trace_id.startswith("trace:memory:") and latest_status in _MEMORY_TERMINAL_STATUSES:
        # A maintenance run may retry under the same durable run id.  Its
        # current terminal phase is authoritative for the envelope status;
        # earlier failed/waiting phases remain visible as historical spans.
        envelope_status = "failed" if latest_status == "expired" else latest_status
    elif "failed" in statuses:
        envelope_status = "failed"
    elif "cancelled" in statuses:
        envelope_status = "cancelled"
    elif any(status not in _TERMINAL_STATUSES for status in statuses):
        envelope_status = "building"
    else:
        envelope_status = "completed"

    evidence = _dedupe_evidence(ordered)
    artifacts = _dedupe_artifacts(ordered)
    created_at = min(_integer(item.get("createdAtMs"), "createdAtMs") for _, item in ordered)
    updated_at = max(_integer(item.get("createdAtMs"), "createdAtMs") for _, item in ordered)
    binding = _aggregate_binding(ordered)
    categories = [_optional_text(item.get("category")) for _, item in ordered]
    explicit_source_kinds = {
        value
        for _, item in ordered
        if isinstance(item.get("attributes"), Mapping)
        and (value := _optional_text(item["attributes"].get("sourceKind")))
    }
    source_kind = (
        next(iter(explicit_source_kinds))
        if len(explicit_source_kinds) == 1
        else categories[0] or "observability"
    )
    explicit_fingerprint = input_fingerprint or next(
        (
            fingerprint
            for _, observation in ordered
            if (fingerprint := _input_fingerprint(observation))
        ),
        None,
    )
    links = _related_partner_turn_links(ordered, trace_id=trace_id)
    return build_trace_envelope(
        trace_id=trace_id,
        source_kind=source_kind,
        input_text=input_text,
        input_fingerprint=explicit_fingerprint,
        binding=binding,
        spans=spans,
        evidence=evidence,
        artifacts=artifacts,
        status=envelope_status,
        input_normalization="observation-redacted",
        created_at_ms=created_at,
        updated_at_ms=updated_at,
        links=links,
    )


def _settle_memory_phase_spans(
    spans,
    *,
    trace_id: str,
    latest_status: str,
):
    """Close prior point-in-time maintenance stages when a real terminal phase arrives.

    Memory maintenance emits one metadata observation per phase and currently
    has no measured operation end.  A later ``applied``, ``rolled_back``,
    ``draft_finished`` or failed observation is enough to say that an earlier
    waiting stage is no longer current, but it is not timing evidence.  Keep
    ``recorded=False`` and annotate the status derivation instead of inventing
    an end timestamp or duration.
    """

    if not trace_id.startswith("trace:memory:") or latest_status not in _MEMORY_TERMINAL_STATUSES:
        return spans
    terminal_status = "failed" if latest_status == "expired" else latest_status
    result = []
    for span in spans:
        if span.status not in {"queued", "running", "waiting"}:
            result.append(span)
            continue
        result.append(
            replace(
                span,
                status="completed" if terminal_status == "completed" else terminal_status,
                attributes={
                    **dict(span.attributes),
                    "terminalDerivedFromMaintenancePhase": True,
                    "terminalPhaseStatus": latest_status,
                },
            )
        )
    return tuple(result)


def _settle_room_root_spans(spans):
    """Apply the Room reducer's terminal fence to its common Trace root.

    A public Room Root has no separate Runtime process event. Its mechanical
    terminal fact is that every known direct dispatch is terminal. Keep the
    Root timing unavailable—the child fence proves status, not a measured
    Root duration—and mark the derivation explicitly for inspection.
    """

    result = list(spans)
    for index, span in enumerate(result):
        if not span.span_id.startswith("span:room-turn:") or span.status in _TERMINAL_STATUSES:
            continue
        dispatches = [
            child
            for child in result
            if child.parent_span_id == span.span_id and child.name == "room.dispatch"
        ]
        if not dispatches or any(child.status not in _TERMINAL_STATUSES for child in dispatches):
            continue
        status = (
            "failed"
            if any(child.status == "failed" for child in dispatches)
            else "cancelled"
            if any(child.status == "cancelled" for child in dispatches)
            else "completed"
        )
        result[index] = replace(
            span,
            status=status,
            attributes={
                **dict(span.attributes),
                "terminalDerivedFromDispatches": True,
                "terminalDispatchCount": len(dispatches),
            },
        )
    return tuple(result)


def _observation_order(pair: tuple[int, Mapping[str, object]]) -> tuple[float | int, float | int, int]:
    """Order by explicit sequence, including sequence zero, then creation time."""

    index, observation = pair
    sequence = _number(observation.get("sequence"), default=None)
    if sequence is None and _optional_text(observation.get("traceId")).startswith(
        "trace:input-generation:"
    ):
        # A source callback may be adapted before the journal assigns a
        # sequence.  Wall time can move backwards, so lifecycle phase order is
        # the only truthful fallback for this one producer-owned trace.
        phase_order = {
            "started": 0,
            "completed": 1,
            "failed": 1,
            "cancelled": 1,
        }
        phase = _optional_text(observation.get("phase"))
        return (
            phase_order.get(phase, 2),
            _number(observation.get("createdAtMs"), default=0) or 0,
            index,
        )
    order = sequence if sequence is not None else _number(observation.get("createdAtMs"), default=0)
    return (1, order if order is not None else 0, index)


def _aggregate_span_groups(
    ordered: Sequence[tuple[int, Mapping[str, object]]],
) -> list[tuple[str, list[Mapping[str, object]]]]:
    groups: dict[str, list[Mapping[str, object]]] = {}
    for _, observation in ordered:
        span_id = _required(observation.get("spanId"), "spanId")
        groups.setdefault(span_id, []).append(observation)
    return list(groups.items())


def _reject_contradictory_input_generation_terminals(
    ordered: Sequence[tuple[int, Mapping[str, object]]],
) -> None:
    """Do not turn competing input-generation terminals into one latest status.

    The journal fences this lifecycle at persistence time.  The adapter also
    receives bounded source-owned lists in a few paths, so it must fail closed
    when a caller supplies an impossible completed/failed/cancelled history
    instead of silently selecting whichever record happens to be latest.
    """

    terminal_by_span: dict[str, set[str]] = {}
    for _, observation in ordered:
        trace_id = _optional_text(observation.get("traceId"))
        name = _optional_text(observation.get("name"))
        attributes = observation.get("attributes")
        source_kind = (
            _optional_text(attributes.get("sourceKind"))
            if isinstance(attributes, Mapping)
            else ""
        )
        if not (
            trace_id.startswith("trace:input-generation:")
            and (name == "input.generation" or source_kind == "input_generation")
        ):
            continue
        status = _optional_text(observation.get("status"))
        if status not in _TERMINAL_STATUSES:
            continue
        span_id = _required(observation.get("spanId"), "spanId")
        terminal_by_span.setdefault(span_id, set()).add(status)
    for span_id, statuses in terminal_by_span.items():
        if len(statuses) > 1:
            raise TraceContractError(
                "contradictory input-generation terminal statuses for "
                f"{span_id}: {', '.join(sorted(statuses))}"
            )


def _span_from_group(
    span_id: str,
    records: Sequence[Mapping[str, object]],
    span_ids: set[str],
):
    latest = records[-1]
    status = str(latest.get("status") or "info")
    if status not in _OBSERVATION_STATUSES:
        raise TraceContractError(f"unsupported observation status: {status}")
    if status == "expired":
        # TraceEnvelope v1 has no public expired state. Preserve the source
        # lifecycle phase in a bounded attribute while projecting expiry as a
        # terminal failure so consumers do not mistake it for an active run.
        status = "failed"
    started = min(_integer(record.get("startedAtMs"), "startedAtMs") for record in records)
    ended = _number(latest.get("endedAtMs"), default=None)
    duration = _number(latest.get("durationMs"), default=None)
    measured = (
        duration is not None
        and ended is not None
        and ended >= started
        and abs((ended - started) - duration) < 1e-9
    )
    parent = _last_nonempty(records, "parentSpanId")
    attributes = project_public_span_attributes(
        _merged_scalar_mapping(records, "attributes"),
        strict=False,
    )
    if str(latest.get("status") or "") == "expired":
        attributes["terminalPhaseStatus"] = "expired"
    if parent and parent not in span_ids:
        attributes["parentUnavailable"] = True
        attributes["parentUnavailableReason"] = "span_not_in_trace"
        parent = None
    kwargs = {
        "span_id": span_id,
        "name": _last_nonempty(records, "name") or _required(latest.get("name"), "name"),
        "parent_span_id": parent or None,
        "status": status,
        "started_at_ms": started,
        "metrics": project_public_span_metrics(
            _merged_scalar_mapping(records, "metrics"),
            strict=False,
        ),
        "attributes": attributes,
    }
    if measured:
        return make_span(**kwargs, ended_at_ms=int(ended), recorded=True)
    reason = "duration_not_recorded" if duration is None else "inconsistent_timing"
    return make_span(**kwargs, recorded=False, unavailable_reason=reason)


def _last_nonempty(records: Sequence[Mapping[str, object]], key: str) -> str:
    for record in reversed(records):
        value = _optional_text(record.get(key))
        if value:
            return value
    return ""


def _merged_scalar_mapping(
    records: Sequence[Mapping[str, object]],
    key: str,
) -> dict[str, object]:
    """Fold lifecycle metadata in order while letting later values win.

    A terminal observation may intentionally be sparse.  Absence is not a
    deletion signal, so already-recorded evidence counts and provenance must
    survive the fold.  An explicit later scalar (including ``None``) still
    replaces the earlier value before the public contract projection.
    """

    result: dict[str, object] = {}
    for record in records:
        result.update(_scalar_mapping(record.get(key)))
    return result


def _aggregate_binding(ordered: Sequence[tuple[int, Mapping[str, object]]]) -> dict[str, str]:
    binding: dict[str, str] = {}
    for key in _BINDING_KEYS:
        values = {
            value
            for _, observation in ordered
            for value in _observation_metadata_values(observation, key)
        }
        if len(values) == 1:
            binding[key] = next(iter(values))
    return binding


def _observation_metadata_values(
    observation: Mapping[str, object],
    key: str,
) -> tuple[str, ...]:
    """Read one binding/link value only from persisted-safe observation metadata."""

    values: list[str] = []
    for container in (observation, observation.get("attributes")):
        if not isinstance(container, Mapping):
            continue
        value = _optional_text(container.get(key))
        if value and value not in values:
            values.append(value)
    return tuple(values)


def _related_partner_turn_links(
    ordered: Sequence[tuple[int, Mapping[str, object]]],
    *,
    trace_id: str,
) -> tuple[dict[str, str], ...]:
    """Project explicit Room-to-Partner turn edges, never participant guesses.

    ``acceptedTurnId`` is the durable acceptance identity for a Partner
    Session turn.  ``sourceTurnId`` is accepted only when a Room producer has
    explicitly carried that source turn through its safe metadata.  Room's
    own ``turnId`` and participant refs are deliberately not candidates.
    """

    links: list[dict[str, str]] = []
    seen: set[str] = set()
    for _, observation in ordered:
        for key in ("acceptedTurnId", "sourceTurnId"):
            for turn_id in _observation_metadata_values(observation, key):
                if not _TRACE_TURN_ID_PATTERN.fullmatch(turn_id):
                    continue
                target_trace_id = f"trace:turn:{turn_id}"
                if target_trace_id == trace_id or target_trace_id in seen:
                    continue
                seen.add(target_trace_id)
                links.append(
                    {
                        "traceId": target_trace_id,
                        "relation": "related",
                        "targetKind": "trace",
                    }
                )
    return tuple(links)


def _dedupe_evidence(
    ordered: Sequence[tuple[int, Mapping[str, object]]],
) -> tuple[dict[str, object], ...]:
    structured = [
        item
        for _, observation in ordered
        for item in _trace_evidence(observation)
    ]
    structured_ids = {str(item["evidenceId"]) for item in structured}
    evidence: list[dict[str, object]] = []
    positions: dict[tuple[str, str], int] = {}
    for _, observation in ordered:
        for ref in _refs(observation.get("refs")):
            ref_id = _required(ref.get("id"), "evidence ref id")
            kind = _required(ref.get("kind"), "evidence ref kind")
            if _is_trace_link_ref(kind):
                continue
            # Lifecycle correlations describe how an operation ran; they are
            # not retrieved or cited evidence.  Counting them would let a
            # Tool/Room event inflate deterministic Eval precision even when
            # the producer returned no Knowledge/Memory/RAG evidence.
            if kind in _OPERATIONAL_REF_KINDS:
                continue
            if kind in _STRUCTURED_EVIDENCE_REF_KINDS and ref_id in structured_ids:
                continue
            item = _evidence_from_observation(observation, ref)
            key = (str(item["evidenceId"]), str(item["evidenceStage"]))
            if key not in positions:
                positions[key] = len(evidence)
                evidence.append(item)
    for item in structured:
        key = (str(item["evidenceId"]), str(item["evidenceStage"]))
        position = positions.get(key)
        if position is None:
            positions[key] = len(evidence)
            evidence.append(item)
        else:
            evidence[position] = item
    return tuple(evidence)


def _is_trace_link_ref(kind: str) -> bool:
    return kind in _TRACE_LINK_REF_KINDS


def _dedupe_artifacts(
    ordered: Sequence[tuple[int, Mapping[str, object]]],
) -> tuple[Mapping[str, object], ...]:
    artifacts: list[Mapping[str, object]] = []
    seen: set[str] = set()
    for _, observation in ordered:
        for artifact in _artifact_refs(observation):
            artifact_id = str(artifact["artifactId"])
            if artifact_id not in seen:
                seen.add(artifact_id)
                artifacts.append(artifact)
    return tuple(artifacts)


def _evidence_from_observation(observation: Mapping[str, object], ref: Mapping[str, object]):
    ref_id = _required(ref.get("id"), "evidence ref id")
    kind = _required(ref.get("kind"), "evidence ref kind")
    return {
        "evidenceId": f"{kind}:{ref_id}",
        "sourceKind": kind,
        "sourceRef": ref_id,
        "sourceLane": "",
        "evidenceStage": "observation_ref",
        "disposition": "included",
        "scores": {},
        "rankBefore": None,
        "rankAfter": None,
        "omissionReason": "",
    }


def _trace_evidence(observation: Mapping[str, object]) -> tuple[dict[str, object], ...]:
    attributes = observation.get("attributes")
    if not isinstance(attributes, Mapping):
        return ()
    candidates = attributes.get("traceEvidence")
    if not isinstance(candidates, Sequence) or isinstance(candidates, (str, bytes, bytearray)):
        return ()
    stage = _optional_text(attributes.get("evidenceStage")) or "observation_ref"
    result: list[dict[str, object]] = []
    for raw in candidates:
        if not isinstance(raw, Mapping):
            continue
        disposition = _optional_text(raw.get("disposition")) or "included"
        if disposition not in {"included", "omitted", "filtered", "redacted"}:
            raise TraceContractError(f"unsupported evidence disposition: {disposition}")
        omission_reason = _optional_text(raw.get("omissionReason"))
        if disposition != "included" and not omission_reason:
            raise TraceContractError("omitted evidence requires omissionReason")
        result.append(
            {
                "evidenceId": _required(raw.get("evidenceId"), "evidenceId"),
                "sourceKind": _required(raw.get("sourceKind"), "sourceKind"),
                "sourceRef": _required(raw.get("sourceRef"), "sourceRef"),
                "sourceLane": _optional_text(raw.get("sourceLane")),
                "evidenceStage": stage,
                "disposition": disposition,
                "scores": _safe_scores(raw.get("scores")),
                "rankBefore": _positive_exact_integer(raw.get("rankBefore")),
                "rankAfter": _positive_exact_integer(raw.get("rankAfter")),
                "omissionReason": omission_reason,
            }
        )
    return tuple(result)


def _safe_scores(value: object) -> dict[str, float]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, float] = {}
    for raw_key, raw_value in list(value.items())[:16]:
        key = _optional_text(raw_key)[:80]
        if not key or isinstance(raw_value, bool) or not isinstance(raw_value, Real):
            continue
        score = float(raw_value)
        if math.isfinite(score):
            result[key] = max(-1_000_000.0, min(1_000_000.0, score))
    return result


def _positive_exact_integer(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    number = float(value)
    if not math.isfinite(number) or number < 1 or not number.is_integer():
        return None
    return int(number)


def _refs(value: object) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return ()
    return tuple(item for item in value if isinstance(item, Mapping) and item.get("id") and item.get("kind"))


def _artifact_refs(observation: Mapping[str, object]) -> tuple[Mapping[str, object], ...]:
    attributes = observation.get("attributes")
    if not isinstance(attributes, Mapping):
        return ()
    candidates = attributes.get("artifactRefs")
    if not isinstance(candidates, Sequence) or isinstance(candidates, (str, bytes, bytearray)):
        return ()
    required = ("artifactId", "kind", "mediaType", "sha256", "byteSize", "recordCount")
    return tuple(dict(item) for item in candidates if isinstance(item, Mapping) and all(item.get(key) is not None for key in required))


def _scalar_mapping(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, object] = {}
    for key, item in value.items():
        safe_key = str(key)
        if _key_tokens(safe_key) & _SENSITIVE_KEY_PARTS:
            continue
        if isinstance(item, (str, int, float, bool)) or item is None:
            result[safe_key] = item
    return result


def _key_tokens(key: str) -> frozenset[str]:
    """Split camelCase/snake_case keys before applying sensitive-key policy."""

    separated = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", key)
    return frozenset(token for token in re.split(r"[^a-z0-9]+", separated.lower()) if token)


def _input_fingerprint(observation: Mapping[str, object]) -> str | None:
    for candidate in (observation.get("inputFingerprint"),):
        value = _optional_text(candidate)
        if value and re.fullmatch(r"sha256:[0-9a-f]{64}", value):
            return value
    attributes = observation.get("attributes")
    if isinstance(attributes, Mapping):
        value = _optional_text(attributes.get("inputFingerprint"))
        if value and re.fullmatch(r"sha256:[0-9a-f]{64}", value):
            return value
    return None


def _required(value: object, name: str) -> str:
    text = _optional_text(value)
    if not text:
        raise TraceContractError(f"{name} is required")
    return text


def _optional_text(value: object) -> str:
    return str(value).strip() if value is not None else ""


def _integer(value: object, name: str) -> int:
    number = _number(value, default=None)
    if number is None or int(number) != number or number < 0:
        raise TraceContractError(f"{name} must be a non-negative integer")
    return int(number)


def _number(value: object, *, default: float | int | None) -> float | int | None:
    if value is None or isinstance(value, bool) or not isinstance(value, Real):
        return default
    return value
