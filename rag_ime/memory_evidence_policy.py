from __future__ import annotations

import re

from .text_utils import compact_whitespace


_MEMORY_WORKFLOW_INSTRUCTION_RE = re.compile(
    r"(?:请(?:调用|使用)\s*memory|"
    r"\bmaintenance_(?:preview|review|apply|rollback)\b|"
    r"\bcuration_prepare\b.{0,160}(?:\brunId\b|审阅|草案))",
    re.IGNORECASE,
)
_MEMORY_WORKFLOW_FUTURE_RE = re.compile(
    r"^(?:我会|接下来(?:我会)?).{0,160}(?:草案|记忆整理)",
    re.IGNORECASE,
)
_MEMORY_WORKFLOW_RECEIPT_RE = re.compile(
    r"^(?:(?:已有|已生成)一份|整理检查已完成|已按.{0,40}执行|"
    r"本轮(?:证据)?已完成整理|我会.{0,120}(?:草案|记忆整理))"
    r".{0,500}(?:\bcuration_prepare\b|\brunId\b|可审阅草案|待审草案|"
    r"没有需要写入的变更|没有通过\s*Atom-first|未生成可审阅草案)",
    re.IGNORECASE,
)


def memory_evidence_exclusion_reason(text: object) -> str:
    """Return a stable reason when text is memory-pipeline control traffic."""

    canonical = compact_whitespace(str(text or ""))
    if not canonical:
        return "empty_input"
    if _MEMORY_WORKFLOW_INSTRUCTION_RE.search(canonical):
        return "memory_workflow_instruction"
    if _MEMORY_WORKFLOW_FUTURE_RE.search(canonical):
        return "memory_workflow_instruction"
    if _MEMORY_WORKFLOW_RECEIPT_RE.search(canonical):
        return "memory_workflow_instruction"
    return ""


__all__ = ["memory_evidence_exclusion_reason"]
