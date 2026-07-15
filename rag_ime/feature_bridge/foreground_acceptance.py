"""Foreground acceptance helpers for feature-bridge status decisions."""

from __future__ import annotations

from typing import Mapping


def feature_requires_foreground_trace(feature: Mapping[str, object]) -> bool:
    return str(feature.get("v1Status") or "") == "foreground_verified"


def acceptance_command_mentions_foreground_trace(feature: Mapping[str, object]) -> bool:
    command = str(feature.get("acceptanceCommand") or "")
    return "verify_squirrel_foreground_trace" in command or "check_squirrel_soak_report" in command


def feature_has_panel_trace_event(feature: Mapping[str, object]) -> bool:
    events = feature.get("foregroundTraceEvents")
    if not isinstance(events, list):
        return False
    return "panel_display_candidates" in {str(event) for event in events}


def feature_has_visible_prediction_trace_event(feature: Mapping[str, object]) -> bool:
    events = feature.get("foregroundTraceEvents")
    if not isinstance(events, list):
        return False
    event_names = {str(event) for event in events}
    return bool(event_names & {"panel_display_candidates", "assistant_overlay_candidate_visible"})
