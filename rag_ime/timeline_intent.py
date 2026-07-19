from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from .text_utils import compact_whitespace


_EXACT_DATE_RE = re.compile(
    r"(?<!\d)(?:20\d{2}[-/.](?:0?[1-9]|1[0-2])[-/.](?:0?[1-9]|[12]\d|3[01])|"
    r"20\d{2}年(?:0?[1-9]|1[0-2])月(?:0?[1-9]|[12]\d|3[01])日|"
    r"(?:0?[1-9]|1[0-2])月(?:0?[1-9]|[12]\d|3[01])日)(?!\d)",
    re.IGNORECASE,
)
_EXPLICIT_TIMELINE_RE = re.compile(
    r"(?:时间线|活动记录|工作记录|daily\s*book|timeline|"
    r"activity\s*(?:log|history)|recent\s+work)",
    re.IGNORECASE,
)
_TIMELINE_TOPIC_QUESTION_RE = re.compile(
    r"(?:为什么|为何|如何(?:设计|实现|存储|召回|整理|工作)|"
    r"怎么(?:设计|实现|存储|召回|整理|工作)|架构|机制|索引|边界|区别|定义|是什么)",
    re.IGNORECASE,
)
_RELATIVE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?:今天|今日|\btoday\b)", re.IGNORECASE), "today"),
    (re.compile(r"(?:昨天|昨日|\byesterday\b)", re.IGNORECASE), "yesterday"),
    (re.compile(r"(?:前天)", re.IGNORECASE), "day_before_yesterday"),
    (
        re.compile(
            r"(?:最近(?:几天)?|近期|这几天|近几天|过去(?:几|[1-9]\d?)天|"
            r"recent\s+(?:days|activity))",
            re.IGNORECASE,
        ),
        "recent_days",
    ),
    (re.compile(r"(?:本周|这周|这个星期|\bthis\s+week\b)", re.IGNORECASE), "current_week"),
    (re.compile(r"(?:上周|上个星期|\blast\s+week\b)", re.IGNORECASE), "previous_week"),
    (re.compile(r"(?:本月|这个月|\bthis\s+month\b)", re.IGNORECASE), "current_month"),
    (re.compile(r"(?:上月|上个月|\blast\s+month\b)", re.IGNORECASE), "previous_month"),
)


@dataclass(frozen=True)
class TimelineIntent:
    requested: bool
    reason: str = "none"
    matched: tuple[str, ...] = ()
    range: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "requested": self.requested,
            "reason": self.reason,
            "matched": list(self.matched),
            "range": self.range,
        }


def classify_timeline_intent(
    query_text: str,
    *,
    raw_input: str = "",
    committed_tail: str = "",
    enabled: bool = True,
) -> TimelineIntent:
    if not enabled:
        return TimelineIntent(requested=False, reason="disabled")

    primary = compact_whitespace(query_text)
    committed = compact_whitespace(committed_tail)
    raw = compact_whitespace(raw_input)
    primary_context = " ".join(part for part in (primary, committed) if part)
    all_context = " ".join(part for part in (primary_context, raw) if part)

    date_matches = _unique_matches(_EXACT_DATE_RE, all_context)
    if date_matches:
        return TimelineIntent(
            requested=True,
            reason="exact_date",
            matched=tuple(date_matches),
            range=_normalized_date_range(date_matches[0]),
        )

    # Relative words are intentionally limited to the current question and
    # committed tail. A stale "昨天" inside broad RAG history must not unlock
    # Timeline for an unrelated semantic query.
    for pattern, range_name in _RELATIVE_PATTERNS:
        matches = _unique_matches(pattern, primary_context)
        if matches:
            return TimelineIntent(
                requested=True,
                reason="relative_time",
                matched=tuple(matches),
                range=range_name,
            )

    explicit_matches = _unique_matches(_EXPLICIT_TIMELINE_RE, all_context)
    if explicit_matches:
        # “时间线为什么不放主题书” asks about the memory architecture, not
        # for activity records. Without a date or relative-time word, keep the
        # Timeline lane closed so Topic Books and Atoms can answer the question.
        if _TIMELINE_TOPIC_QUESTION_RE.search(primary_context):
            return TimelineIntent(requested=False)
        return TimelineIntent(
            requested=True,
            reason="explicit_timeline",
            matched=tuple(explicit_matches),
            range=(
                "recent_days"
                if any("recent" in item.casefold() for item in explicit_matches)
                else "unspecified"
            ),
        )

    return TimelineIntent(requested=False)


def timeline_date_bounds(
    intent: TimelineIntent,
    *,
    now: datetime | None = None,
) -> tuple[str, str] | None:
    """Resolve a bounded Timeline intent to inclusive local calendar dates."""

    if not intent.requested or not intent.range or intent.range == "unspecified":
        return None
    current = (now or datetime.now().astimezone()).date()
    range_name = intent.range
    if range_name == "today":
        start = end = current
    elif range_name == "yesterday":
        start = end = current - timedelta(days=1)
    elif range_name == "day_before_yesterday":
        start = end = current - timedelta(days=2)
    elif range_name == "recent_days":
        count = _relative_day_count(intent.matched)
        start, end = current - timedelta(days=count - 1), current
    elif range_name == "current_week":
        start, end = current - timedelta(days=current.weekday()), current
    elif range_name == "previous_week":
        current_week_start = current - timedelta(days=current.weekday())
        start = current_week_start - timedelta(days=7)
        end = current_week_start - timedelta(days=1)
    elif range_name == "current_month":
        start, end = current.replace(day=1), current
    elif range_name == "previous_month":
        end = current.replace(day=1) - timedelta(days=1)
        start = end.replace(day=1)
    else:
        exact = _exact_date(range_name, current=current)
        if exact is None:
            return None
        start = end = exact
    return start.isoformat(), end.isoformat()


def _unique_matches(pattern: re.Pattern[str], value: str) -> list[str]:
    return list(
        dict.fromkeys(
            compact_whitespace(match.group(0))
            for match in pattern.finditer(value)
            if compact_whitespace(match.group(0))
        )
    )[:8]


def _normalized_date_range(value: str) -> str:
    normalized = value.replace("年", "-").replace("月", "-").replace("日", "")
    normalized = normalized.replace("/", "-").replace(".", "-")
    return normalized.strip("-")


def _relative_day_count(matches: tuple[str, ...]) -> int:
    for value in matches:
        match = re.search(r"过去([1-9]\d?)天", value)
        if match is not None:
            return max(1, min(int(match.group(1)), 31))
    return 7


def _exact_date(value: str, *, current: date) -> date | None:
    parts = value.split("-")
    try:
        if len(parts) == 3:
            year, month, day = (int(part) for part in parts)
        elif len(parts) == 2:
            year = current.year
            month, day = (int(part) for part in parts)
        else:
            return None
        return date(year, month, day)
    except ValueError:
        return None
