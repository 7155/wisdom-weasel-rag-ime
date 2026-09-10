from __future__ import annotations

import re
from dataclasses import dataclass


_AUTH_FAILURE = re.compile(
    r"\b(?:401|403|unauthori[sz]ed|forbidden|invalid[_ -]?(?:api[_ -]?)?key|"
    r"authentication failed|invalidated oauth token|invalid[_ -]grant|"
    r"refresh[_ -]token[_ -](?:reused|expired|invalid)|"
    r"(?:access|oauth)[_ -]token (?:is |has )?(?:expired|invalid))\b",
    re.IGNORECASE,
)


def provider_auth_failure_message(error: object) -> str:
    """Give a recovery action only when the Provider reported authentication failure."""
    if not _AUTH_FAILURE.search(str(error or "")):
        return ""
    return (
        "模型账号登录已失效或凭据无效。请在系统设置的“模型账号”中"
        "重新登录或更新密钥，再继续当前对话。"
    )


_CANCEL_FAILURE = re.compile(
    r"\b(?:abort(?:ed)?|cancel(?:led|ed)?|user interrupt)\b",
    re.IGNORECASE,
)
_CONTRACT_FAILURE = re.compile(
    r"\b(?:schema|validation|invalid (?:request|argument)|context (?:length|window)|"
    r"maximum context|too many tokens)\b",
    re.IGNORECASE,
)
_RATE_LIMIT_FAILURE = re.compile(
    r"(?:\b429\b|rate[_ -]?limit|too many requests)",
    re.IGNORECASE,
)
_OVERLOAD_FAILURE = re.compile(
    r"(?:overload|temporar(?:y|ily) unavailable|service unavailable|"
    r"\b(?:502|503|504)\b)",
    re.IGNORECASE,
)
_TIMEOUT_FAILURE = re.compile(
    r"(?:timed? out|timeout|deadline exceeded)",
    re.IGNORECASE,
)
_TRANSPORT_FAILURE = re.compile(
    r"(?:fetch failed|network (?:error|failure)|connection (?:reset|closed|refused)|"
    r"websocket (?:error|failure|closed)|econn(?:reset|refused)|socket hang up|"
    r"broken pipe|remote end closed|"
    r"^error:\s*terminated$|^terminated$)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class RuntimeFailureClassification:
    failure_kind: str
    reason_code: str
    retryable: bool
    had_tool_activity: bool

    def event_payload(self) -> dict[str, object]:
        return {
            "failureKind": self.failure_kind,
            "reasonCode": self.reason_code,
            "retryable": self.retryable,
            "hadToolActivity": self.had_tool_activity,
        }


def classify_runtime_failure(
    error: object,
    *,
    had_tool_activity: bool,
) -> RuntimeFailureClassification:
    """Classify a terminal Provider turn without inferring side-effect safety.

    Pi already owns retries while a turn is alive.  This classification is
    only consumed after Pi has emitted its final failure.  A Room may replay
    that Dispatch only when the failure is transient *and* no Tool activity
    was observed during the turn.
    """

    text = str(error or "").strip()
    if had_tool_activity:
        return RuntimeFailureClassification(
            failure_kind="provider_failure",
            reason_code="tool_activity_observed",
            retryable=False,
            had_tool_activity=True,
        )
    if _AUTH_FAILURE.search(text):
        reason_code = "provider_auth_failure"
    elif _CANCEL_FAILURE.search(text):
        reason_code = "provider_cancelled"
    elif _CONTRACT_FAILURE.search(text):
        reason_code = "provider_contract_failure"
    elif _RATE_LIMIT_FAILURE.search(text):
        return RuntimeFailureClassification(
            failure_kind="transient_provider_failure",
            reason_code="provider_rate_limited",
            retryable=True,
            had_tool_activity=False,
        )
    elif _OVERLOAD_FAILURE.search(text):
        return RuntimeFailureClassification(
            failure_kind="transient_provider_failure",
            reason_code="provider_overloaded",
            retryable=True,
            had_tool_activity=False,
        )
    elif _TIMEOUT_FAILURE.search(text):
        return RuntimeFailureClassification(
            failure_kind="transient_provider_failure",
            reason_code="provider_timeout",
            retryable=True,
            had_tool_activity=False,
        )
    elif _TRANSPORT_FAILURE.search(text):
        return RuntimeFailureClassification(
            failure_kind="transient_provider_failure",
            reason_code="provider_transport_failure",
            retryable=True,
            had_tool_activity=False,
        )
    else:
        reason_code = "provider_failure_unclassified"
    return RuntimeFailureClassification(
        failure_kind="provider_failure",
        reason_code=reason_code,
        retryable=False,
        had_tool_activity=False,
    )
