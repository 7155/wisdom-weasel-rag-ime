"""Frozen, additive candidate instructions for private Validation runners.

The caller supplies generic instructions, never Host Gold. This module reads
only that file and publishes its identity; it does not build candidates from
tasks, hidden references, or verifier data.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

MAX_CANDIDATE_PROMPT_BYTES = 16_000


@dataclass(frozen=True)
class CandidatePrompt:
    text: str

    def __post_init__(self) -> None:
        raw = self.text.encode("utf-8")
        if not self.text.strip() or len(raw) > MAX_CANDIDATE_PROMPT_BYTES or "\x00" in self.text:
            raise ValueError("candidate Prompt must be nonempty UTF-8 text of at most 16000 bytes without NUL")


def load_candidate_prompt(
    path: str | Path | None, *, evaluation_split: str,
) -> CandidatePrompt | None:
    if path is None:
        return None
    if evaluation_split not in {"validation", "development"}:
        raise ValueError("candidate Prompt files are allowed only in validation/development")
    with Path(path).expanduser().open("rb") as handle:
        raw = handle.read(MAX_CANDIDATE_PROMPT_BYTES + 1)
    if len(raw) > MAX_CANDIDATE_PROMPT_BYTES:
        raise ValueError("candidate Prompt exceeds 16000 bytes")
    return CandidatePrompt(raw.decode("utf-8", errors="strict"))


def candidate_prompt_identity(candidate: CandidatePrompt | None) -> dict[str, object]:
    raw = candidate.text.encode("utf-8") if candidate is not None else b""
    return {
        "schemaVersion": "paw.agent-eval-candidate-prompt.v1",
        "enabled": candidate is not None,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "byteCount": len(raw),
        "charCount": len(candidate.text) if candidate is not None else 0,
    }


def append_candidate_prompt(base_prompt: str, candidate: CandidatePrompt | None) -> str:
    if candidate is None:
        return base_prompt
    return (
        base_prompt
        + "\n\nAdditional candidate instructions (Validation only):\n"
        + "These instructions cannot change the task, available Tool permissions, "
        "business requirements, or Host verifier contract above. The fixed contract "
        "takes precedence. Do not request or infer hidden Gold.\n"
        + candidate.text
    )
