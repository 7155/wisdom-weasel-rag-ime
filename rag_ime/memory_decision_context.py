"""Bind an explicit selection to a recorded question, without inventing facts."""

from __future__ import annotations

import re
import sqlite3

from .sensitive_content import contains_sensitive_content
from .text_utils import compact_whitespace

_ANSWER = re.compile(
    r"(?:推荐后者|后者|前者|全部推荐|推荐|选择?[ABCabc123]|[ABCabc123]|选第[一二三]个)[。！!\s]*$"
)
_OPTION = re.compile(r"(?:^|\s)([ABCabc123])[.、):：]\s*")
_RECOMMENDED = re.compile(r"[（(\[]\s*(?:推荐|recommended)\s*[）)\]]", re.I)


def resolve_decision_context(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    project: str,
    answer_entry_id: str,
    answer_text: str,
    occurred_at_ms: int,
    answer_source_id: str = "",
    expected_question_evidence_id: str = "",
) -> dict[str, object] | None:
    """Resolve a single recorded question with two or three explicit options."""
    answer = compact_whitespace(answer_text)
    if not session_id or not answer_entry_id or not _ANSWER.fullmatch(answer):
        return None
    # Read the latest turn before checking scope or visibility. Filtering those
    # first could silently fall back to an older, unrelated question.
    row = conn.execute(
        """SELECT evidence_id, source_id, source_kind, content_text,
                  occurred_at_ms, status, admission_state, project
        FROM agent_memory_evidence
        WHERE session_id = ?
          AND source_kind IN ('assistant_message', 'user_message') AND source_id NOT IN (?, ?)
          AND occurred_at_ms <= ?
        ORDER BY occurred_at_ms DESC, recorded_at_ms DESC, evidence_id DESC LIMIT 1""",
        (session_id, answer_entry_id, answer_source_id, occurred_at_ms),
    ).fetchone()
    if (
        row is None
        or row["source_kind"] != "assistant_message"
        or row["project"] != project
        or row["status"] != "active"
        or row["admission_state"] == "forgotten"
        or (expected_question_evidence_id and row["evidence_id"] != expected_question_evidence_id)
    ):
        return None
    tombstoned = conn.execute(
        """SELECT 1 FROM memory_tombstones WHERE active = 1
        AND target_type = 'memory_id' AND target_value = ? LIMIT 1""",
        (row["evidence_id"],),
    ).fetchone()
    if tombstoned:
        return None
    intervening = conn.execute(
        """SELECT 1 FROM agent_memory_sources
        WHERE session_id = ? AND source_kind = 'user_final' AND pi_entry_id != ?
          AND created_at_ms > ? AND created_at_ms <= ? LIMIT 1""",
        (session_id, answer_entry_id, row["occurred_at_ms"], occurred_at_ms),
    ).fetchone()
    if intervening:
        return None
    question = str(row["content_text"] or "")
    if (
        len(question) > 4000
        or contains_sensitive_content(question)
        or "```" in question
        or re.search(r"(?:^|\s)>", question)
    ):
        return None
    markers = list(_OPTION.finditer(question))
    labels = [match[1].upper() for match in markers]
    if labels not in (["A", "B"], ["A", "B", "C"], ["1", "2"], ["1", "2", "3"]):
        return None
    prompt = question[:markers[0].start()].strip()
    if not (prompt.endswith(("?", "？")) or "请选择" in prompt):
        return None
    if prompt.count("?") + prompt.count("？") > 1:
        return None
    options = []
    for index, match in enumerate(markers):
        end = markers[index + 1].start() if index + 1 < len(markers) else len(question)
        options.append(question[match.end():end].strip())
    if any(not option or "？" in option or "?" in option for option in options):
        return None
    normalized = answer.rstrip("。！! ").upper()
    if normalized in {"推荐后者", "后者", "前者"}:
        if len(options) != 2:
            return None
        selected = 0 if normalized == "前者" else len(options) - 1
    elif normalized in {"全部推荐", "推荐"}:
        recommended = [
            index for index, option in enumerate(options) if _RECOMMENDED.search(option)
        ]
        if len(recommended) != 1:
            return None
        selected = recommended[0]
    else:
        label = normalized.removeprefix("选择").removeprefix("选")
        if label.startswith("第"):
            selected = "一二三".index(label[1])
        elif label in labels:
            selected = labels.index(label)
        else:
            return None
    if selected >= len(options):
        return None
    return {
        "schemaVersion": "rag-ime.memory-decision-context.v1",
        "sessionId": session_id,
        "project": project,
        "questionEvidenceId": str(row["evidence_id"]),
        "questionEntryId": str(row["source_id"]),
        "questionText": question,
        "questionOccurredAtMs": int(row["occurred_at_ms"]),
        "answerEntryId": answer_entry_id,
        "answerText": answer,
        "selectedOptions": [_RECOMMENDED.sub("", options[selected]).strip()],
        "scope": "this_question_only",
    }
