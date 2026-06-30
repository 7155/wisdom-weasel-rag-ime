from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .models import InputEvent, InputSuggestion
from .text_utils import compact_whitespace, now_ms, truncate_text


TEXT_KEYS = {
    "text",
    "content",
    "message",
    "prompt",
    "summary",
    "objective",
    "input",
    "output",
}
ROLE_KEYS = ("role", "author")
FALLBACK_ROLE_KEYS = ("source", "type")
TIMESTAMP_KEYS = ("created_at_ms", "timestamp_ms", "time_ms", "createdAtMs", "created_at", "timestamp")


@dataclass(frozen=True)
class CodexHistoryRecord:
    record_id: str
    source_path: str
    line_number: int
    text: str
    role: str = ""
    created_at_ms: int = 0
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class CodexEvalCase:
    case_id: str
    query: str
    expected_terms: tuple[str, ...]
    recent_context: str = ""
    project: str = ""


@dataclass(frozen=True)
class CodexEvalResult:
    case_id: str
    query: str
    passed: bool
    matched_terms: tuple[str, ...]
    expected_terms: tuple[str, ...]
    top_surfaces: tuple[str, ...]


def iter_codex_jsonl_paths(path: Path) -> Iterable[Path]:
    if path.is_file():
        yield path
        return
    if not path.exists():
        raise FileNotFoundError(path)
    if not path.is_dir():
        raise ValueError(f"expected file or directory: {path}")
    yield from sorted(item for item in path.rglob("*.jsonl") if item.is_file())


def iter_jsonl_objects(path: Path) -> Iterable[tuple[int, Any]]:
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                yield line_number, json.loads(stripped)
            except json.JSONDecodeError:
                continue


def load_codex_history_records(
    path: Path,
    *,
    limit: int | None = None,
    min_chars: int = 12,
    max_chars: int = 1600,
) -> list[CodexHistoryRecord]:
    if limit is not None and limit <= 0:
        return []
    records: list[CodexHistoryRecord] = []
    for jsonl_path in iter_codex_jsonl_paths(path):
        for line_number, obj in iter_jsonl_objects(jsonl_path):
            role = truncate_text(_find_first_string(obj, ROLE_KEYS) or _find_first_string(obj, FALLBACK_ROLE_KEYS), 40)
            created_at_ms = _find_timestamp_ms(obj)
            seen_texts: set[str] = set()
            for text in _extract_text_fragments(obj):
                normalized = truncate_text(text, max_chars)
                if len(normalized) < min_chars or normalized in seen_texts:
                    continue
                seen_texts.add(normalized)
                record_id = _record_id(jsonl_path, line_number, normalized)
                tags = ("codex-history",) + ((f"role:{role}",) if role else ())
                records.append(
                    CodexHistoryRecord(
                        record_id=record_id,
                        source_path=str(jsonl_path),
                        line_number=line_number,
                        text=normalized,
                        role=role,
                        created_at_ms=created_at_ms,
                        tags=tags,
                    )
                )
                if limit is not None and len(records) >= limit:
                    return records
    return records


def input_event_from_codex_record(record: CodexHistoryRecord, *, project: str) -> InputEvent:
    source_label = f"{Path(record.source_path).name}:{record.line_number}"
    role = f" role:{record.role}" if record.role else ""
    return InputEvent(
        event_id=None,
        created_at_ms=record.created_at_ms or now_ms(),
        source="codex_history",
        committed_text=record.text,
        recent_context=compact_whitespace(f"codex_history:{source_label}{role}"),
        preedit="",
        schema_id="codex_history",
        app="codex",
        project=project,
        provider_name="codex-history-import",
        tags=record.tags + (f"record:{record.record_id[:12]}",),
    )


def load_eval_cases(path: Path) -> list[CodexEvalCase]:
    cases: list[CodexEvalCase] = []
    for line_number, obj in iter_jsonl_objects(path):
        if not isinstance(obj, dict):
            continue
        query = compact_whitespace(str(obj.get("query") or obj.get("currentInput") or ""))
        raw_terms = obj.get("expectedTerms", obj.get("expected_terms", []))
        if isinstance(raw_terms, str):
            terms = [raw_terms]
        elif isinstance(raw_terms, list):
            terms = [str(item) for item in raw_terms]
        else:
            terms = []
        expected_terms = tuple(compact_whitespace(item) for item in terms if compact_whitespace(item))
        if not query or not expected_terms:
            continue
        case_id = compact_whitespace(str(obj.get("id") or obj.get("caseId") or f"case-{line_number}"))
        cases.append(
            CodexEvalCase(
                case_id=case_id,
                query=query,
                expected_terms=expected_terms,
                recent_context=compact_whitespace(str(obj.get("recentContext") or obj.get("recent_context") or "")),
                project=compact_whitespace(str(obj.get("project") or "")),
            )
        )
    return cases


def evaluate_suggestions(
    case: CodexEvalCase,
    suggestions: list[InputSuggestion],
    *,
    match: str = "any",
) -> CodexEvalResult:
    haystack = "\n".join(
        compact_whitespace(
            " ".join(
                [
                    item.surface_text,
                    item.evidence_preview,
                    item.expanded_evidence,
                    str(item.metadata.get("insert_text") or ""),
                ]
            )
        )
        for item in suggestions
    ).lower()
    matched = tuple(term for term in case.expected_terms if term.lower() in haystack)
    if match == "all":
        passed = len(matched) == len(case.expected_terms)
    elif match == "any":
        passed = bool(matched)
    else:
        raise ValueError("match must be 'any' or 'all'")
    return CodexEvalResult(
        case_id=case.case_id,
        query=case.query,
        passed=passed,
        matched_terms=matched,
        expected_terms=case.expected_terms,
        top_surfaces=tuple(item.surface_text for item in suggestions[:5]),
    )


def eval_report(results: list[CodexEvalResult]) -> dict[str, Any]:
    passed = sum(1 for item in results if item.passed)
    total = len(results)
    return {
        "schemaVersion": "rag-ime.codex-history-eval.v1",
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "passRate": (passed / total) if total else 0.0,
        "cases": [
            {
                "caseId": item.case_id,
                "query": item.query,
                "passed": item.passed,
                "matchedTerms": list(item.matched_terms),
                "expectedTerms": list(item.expected_terms),
                "topSurfaces": list(item.top_surfaces),
            }
            for item in results
        ],
    }


def _extract_text_fragments(value: Any, *, parent_key: str = "") -> Iterable[str]:
    if isinstance(value, str):
        if parent_key in TEXT_KEYS:
            text = compact_whitespace(value)
            if text and not _looks_like_metadata(text):
                yield text
        return
    if isinstance(value, list):
        for item in value:
            yield from _extract_text_fragments(item, parent_key=parent_key)
        return
    if not isinstance(value, dict):
        return
    for key, item in value.items():
        normalized_key = str(key)
        if normalized_key in TEXT_KEYS:
            yield from _extract_text_fragments(item, parent_key=normalized_key)
        elif isinstance(item, (dict, list)):
            yield from _extract_text_fragments(item, parent_key=normalized_key)


def _find_first_string(value: Any, keys: Iterable[str]) -> str:
    key_set = set(keys)
    if isinstance(value, dict):
        for key, item in value.items():
            if key in key_set and isinstance(item, str):
                return compact_whitespace(item)
        for item in value.values():
            found = _find_first_string(item, keys)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _find_first_string(item, keys)
            if found:
                return found
    return ""


def _find_timestamp_ms(value: Any) -> int:
    found = _find_timestamp_value(value)
    if isinstance(found, int):
        return found
    if isinstance(found, float):
        return int(found)
    if isinstance(found, str):
        return _parse_timestamp_string(found)
    return 0


def _find_timestamp_value(value: Any) -> Any:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in TIMESTAMP_KEYS:
                return item
        for item in value.values():
            found = _find_timestamp_value(item)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _find_timestamp_value(item)
            if found:
                return found
    return None


def _parse_timestamp_string(value: str) -> int:
    text = value.strip()
    if not text:
        return 0
    if text.isdigit():
        number = int(text)
        return number if number > 10_000_000_000 else number * 1000
    try:
        normalized = text.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return int(parsed.timestamp() * 1000)
    except ValueError:
        return 0


def _record_id(path: Path, line_number: int, text: str) -> str:
    payload = f"{path}:{line_number}:{text[:240]}".encode("utf-8", errors="replace")
    return hashlib.sha256(payload).hexdigest()


def _looks_like_metadata(text: str) -> bool:
    if len(text) > 3 and text[0] in "[{" and text[-1] in "]}":
        return True
    if text.startswith(("/", "~/")) and len(text.split()) <= 2:
        return True
    return False
