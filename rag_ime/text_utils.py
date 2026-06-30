from __future__ import annotations

import re
import textwrap
from collections.abc import Iterable


_ASCII_TOKEN_RE = re.compile(r"[A-Za-z0-9_+#.\-]{2,}")
_CJK_RUN_RE = re.compile(r"[\u3400-\u9fff]+")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？!?；;])\s*|\n+")


def now_ms() -> int:
    import time

    return int(time.time() * 1000)


def compact_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def truncate_text(text: str, max_chars: int) -> str:
    text = compact_whitespace(text)
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 1)].rstrip() + "…"


def split_sentences(text: str) -> list[str]:
    parts = [compact_whitespace(part) for part in _SENTENCE_SPLIT_RE.split(text or "")]
    return [part for part in parts if part]


def token_terms(text: str, *, max_terms: int = 32) -> list[str]:
    """Return FTS-friendly terms for mixed Chinese/English personal text."""

    terms: list[str] = []
    seen: set[str] = set()

    def add(term: str) -> None:
        term = term.strip().lower()
        if not term or term in seen:
            return
        seen.add(term)
        terms.append(term)

    for match in _ASCII_TOKEN_RE.finditer(text or ""):
        add(match.group(0))

    for match in _CJK_RUN_RE.finditer(text or ""):
        run = match.group(0)
        if 1 <= len(run) <= 8:
            add(run)
        for size in (2, 3):
            for idx in range(0, max(0, len(run) - size + 1)):
                add(run[idx : idx + size])
        if len(run) == 1:
            add(run)

    return terms[:max_terms]


def build_fts_document(*parts: str) -> str:
    raw = " ".join(part for part in parts if part)
    expanded_terms = " ".join(token_terms(raw, max_terms=96))
    return compact_whitespace(f"{raw} {expanded_terms}")


def build_fts_query(query: str) -> str:
    terms = token_terms(query, max_terms=24)
    escaped = [f'"{term.replace(chr(34), chr(34) + chr(34))}"' for term in terms]
    return " OR ".join(escaped)


def overlap_terms(query: str, text: str) -> list[str]:
    text_lower = (text or "").lower()
    hits: list[str] = []
    for term in token_terms(query, max_terms=32):
        if term.lower() in text_lower:
            hits.append(term)
    return hits


def first_non_empty(values: Iterable[str]) -> str:
    for value in values:
        if compact_whitespace(value):
            return compact_whitespace(value)
    return ""


def wrap_block(text: str, *, width: int = 88) -> str:
    lines: list[str] = []
    for line in (text or "").splitlines():
        line = compact_whitespace(line)
        if not line:
            lines.append("")
            continue
        lines.extend(textwrap.wrap(line, width=width, replace_whitespace=False) or [""])
    return "\n".join(lines).strip()
