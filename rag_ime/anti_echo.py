from __future__ import annotations

import re

from .text_utils import compact_whitespace


def repeat_norm(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", compact_whitespace(text), flags=re.UNICODE).lower()


def collapse_repeated_tail(text: str, *, min_unit_chars: int = 2, max_unit_chars: int = 16) -> str:
    """Keep only one copy of a phrase repeated at the very end of the text."""

    surface = compact_whitespace(text)
    if len(surface) < min_unit_chars * 2:
        return surface
    max_width = min(max_unit_chars, len(surface) // 2)
    for width in range(max_width, min_unit_chars - 1, -1):
        unit = surface[-width:]
        if not compact_whitespace(unit):
            continue
        repeats = 1
        cursor = len(surface) - width
        while cursor >= width and surface[cursor - width : cursor] == unit:
            repeats += 1
            cursor -= width
        if repeats >= 2:
            return surface[: len(surface) - (repeats - 1) * width]
    return surface


def candidate_has_self_repetition(candidate: str, *, min_unit_chars: int = 2, max_unit_chars: int = 16) -> bool:
    norm = repeat_norm(candidate)
    if re.search(r"([能再先在给把要可很就让还都也并])\1", norm):
        return True
    if len(norm) < min_unit_chars * 2:
        return False
    max_width = min(max_unit_chars, len(norm) // 2)
    for width in range(min_unit_chars, max_width + 1):
        if len(norm) % width == 0 and norm == norm[:width] * (len(norm) // width):
            return True
    return False


def candidate_has_keyword_echo(candidate: str, *, max_chars: int = 20) -> bool:
    text = compact_whitespace(candidate)
    if len(text) > max_chars:
        return False
    lowered = text.lower()
    return any(lowered.count(keyword) >= 2 for keyword in ("llm", "rag", "deepseek", "ds"))


def candidate_echoes_text(
    candidate: str,
    text: str,
    *,
    reject_tail: bool = True,
    reject_single_occurrence: bool = False,
    min_candidate_chars: int = 2,
) -> bool:
    candidate_norm = repeat_norm(candidate)
    text_norm = repeat_norm(text)
    if len(candidate_norm) < min_candidate_chars or not text_norm:
        return False
    if candidate_norm == text_norm:
        return True
    if reject_single_occurrence and candidate_norm in text_norm:
        return True
    if text_norm.count(candidate_norm) >= 2:
        return True
    return reject_tail and text_norm.endswith(candidate_norm)
