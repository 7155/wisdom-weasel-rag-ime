"""Pure UI request/response wire shaping; Runtime owns pending state and timers."""

from __future__ import annotations

from collections.abc import Mapping

from .public import (
    GROUPED_QUESTIONS_SCHEMA_VERSION,
    canonical_grouped_answers,
    grouped_questions_from_wire,
    ui_confirmation_value,
)
from .values import PiRuntimeError

__all__ = ["grouped_question_request", "public_ui_request", "resolve_ui_response"]


def grouped_question_request(request_id: str, prefill: object) -> dict[str, object]:
    questions = grouped_questions_from_wire(prefill)
    return {
        "requestId": request_id,
        "requestKind": "grouped_questions",
        "schemaVersion": GROUPED_QUESTIONS_SCHEMA_VERSION,
        "groupId": request_id,
        "method": "editor",
        "title": "需要你做几个选择",
        "message": "请把相关问题全部选完后一次提交；如果不想继续，可以取消本次提问。",
        "questions": questions,
    }


def public_ui_request(
    raw: Mapping[str, object],
    *,
    request_id: str,
    method: str,
    title: str,
) -> dict[str, object]:
    safe: dict[str, object] = {
        "requestId": request_id,
        "method": method,
        "title": title[:160],
        "message": str(raw.get("message") or "")[:500],
    }
    options = raw.get("options")
    if isinstance(options, list):
        safe["options"] = [str(value)[:240] for value in options[:100]]
    for field, maximum in (
        ("placeholder", 500),
        ("prefill", 4_000),
        ("defaultValue", 4_000),
    ):
        if raw.get(field) is not None:
            safe[field] = str(raw.get(field) or "")[:maximum]
    timeout = raw.get("timeout")
    if isinstance(timeout, (str, int, float, bytes, bytearray)):
        try:
            safe["timeout"] = max(0, int(timeout))
        except (TypeError, ValueError):
            pass
    return safe


def resolve_ui_response(
    request: Mapping[str, object],
    response: Mapping[str, object],
) -> tuple[dict[str, object], str]:
    method = str(request.get("method") or "")
    cancelled = response.get("cancelled") is True
    source = str(response.get("resolutionSource") or "").strip() or (
        "user_cancelled" if cancelled else "direct_user"
    )
    if source not in {"direct_user", "user_cancelled", "timeout", "runtime_cancelled"}:
        raise ValueError("unsupported UI response provenance")
    if source in {"timeout", "runtime_cancelled"} and not cancelled:
        raise ValueError("automatic UI resolution must be a cancellation")
    if cancelled:
        return {"cancelled": True}, source
    value = str(response.get("value") or "")
    if method == "confirm":
        confirmed = response.get("confirmed")
        if not isinstance(confirmed, bool):
            confirmed = ui_confirmation_value(value)
        return {"confirmed": confirmed}, source
    if request.get("requestKind") == "grouped_questions":
        try:
            value = canonical_grouped_answers(value, request.get("questions"))
        except ValueError as exc:
            raise PiRuntimeError("提交答案与当前问题或可选项不一致") from exc
    elif method == "select":
        options = request.get("options") or []
        # Pending requests are created by public_ui_request, which emits lists.
        assert isinstance(options, list)
        if options and value not in [str(item) for item in options]:
            raise PiRuntimeError("UI response is not one of the offered options")
    return {"value": value}, source
