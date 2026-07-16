"""Key-policy contract for the v1 foreground IME route."""

from __future__ import annotations

from collections.abc import Mapping

KEY_POLICY_NUMBER_KEYS = "numberKeys"
KEY_POLICY_TAB = "tab"
KEY_POLICY_OPTION_NUMBER = "optionNumber"
KEY_POLICY_ESCAPE = "escape"

NUMBER_KEYS_PASS_THROUGH = "pass_through"
NUMBER_KEYS_SELECT_RIME_CANDIDATE = "select_rime_candidate"
TAB_ACCEPT_TOP_PREDICTION = "accept_top_prediction"
TAB_RIME_DEFAULT = "rime_default"
TAB_PASS_THROUGH_OR_RIME = "pass_through_or_rime"
OPTION_NUMBER_SELECT_PREDICTION_BY_ORDINAL = "select_prediction_by_ordinal"
OPTION_NUMBER_DISABLED = "disabled"
OPTION_NUMBER_PASS_THROUGH = "pass_through"
ESCAPE_DISMISS_PREDICTION = "dismiss_prediction"
ESCAPE_RIME_CANCEL = "rime_cancel"
ESCAPE_PASS_THROUGH_OR_CLEAR_RIME = "pass_through_or_clear_rime"

SELECTION_ACTION_COMMIT_SIDE_CANDIDATE = "commit_side_candidate"
SELECTION_ACTION_SELECT_RIME_CANDIDATE = "select_rime_candidate"
SELECTION_ACTION_START_ACTIVE_RAG_FROM_CONTEXT = "start_active_rag_from_context"
SELECTION_ACTION_START_VISUAL_RAG_FROM_CONTEXT = "start_visual_rag_from_context"
SELECTION_ACTION_NONE = "none"

ROUTE_NUMBER_KEY = "number_key_route"
ROUTE_TAB_KEY = "tab_key_route"
ROUTE_OPTION_NUMBER = "option_number_route"
SIDE_SELECTION_ROUTE_EVENTS = frozenset({ROUTE_NUMBER_KEY, ROUTE_TAB_KEY, ROUTE_OPTION_NUMBER})

POST_COMMIT_KEY_POLICY = {
    KEY_POLICY_NUMBER_KEYS: NUMBER_KEYS_PASS_THROUGH,
    KEY_POLICY_TAB: TAB_ACCEPT_TOP_PREDICTION,
    KEY_POLICY_OPTION_NUMBER: OPTION_NUMBER_SELECT_PREDICTION_BY_ORDINAL,
    KEY_POLICY_ESCAPE: ESCAPE_DISMISS_PREDICTION,
}
COMPOSITION_KEY_POLICY = {
    KEY_POLICY_NUMBER_KEYS: NUMBER_KEYS_SELECT_RIME_CANDIDATE,
    KEY_POLICY_TAB: TAB_RIME_DEFAULT,
    KEY_POLICY_OPTION_NUMBER: OPTION_NUMBER_DISABLED,
    KEY_POLICY_ESCAPE: ESCAPE_RIME_CANCEL,
}
PASSTHROUGH_KEY_POLICY = {
    KEY_POLICY_NUMBER_KEYS: NUMBER_KEYS_PASS_THROUGH,
    KEY_POLICY_TAB: TAB_PASS_THROUGH_OR_RIME,
    KEY_POLICY_OPTION_NUMBER: OPTION_NUMBER_PASS_THROUGH,
    KEY_POLICY_ESCAPE: ESCAPE_PASS_THROUGH_OR_CLEAR_RIME,
}


def key_policy_for_prediction_session(prediction_session_payload: Mapping[str, object]) -> dict[str, object]:
    """Return the v1 key policy for a prediction-session payload."""

    phase = _string(prediction_session_payload.get("phase"))
    input_mode = _string(prediction_session_payload.get("inputMode"))
    if phase == "post_commit" or input_mode == "post_commit_predicting":
        return dict(POST_COMMIT_KEY_POLICY)
    if phase in {"prefix_constrained", "anchor_composing"} or input_mode in {
        "prefix_constrained_composing",
        "anchor_composing",
    }:
        return dict(COMPOSITION_KEY_POLICY)
    return dict(PASSTHROUGH_KEY_POLICY)


def _string(value: object) -> str:
    return str(value or "").strip()
