from __future__ import annotations

import re

from .text_utils import compact_whitespace


_FILLER = {
    "下一步",
    "接下来",
    "根据上述",
    "可以进行",
    "候选如下",
    "以下是",
    "输入法候选",
    "模型候选",
}


class ImeCandidateStreamParser:
    def __init__(
        self,
        *,
        max_candidates: int = 3,
        current_input: str = "",
        recent_context: str = "",
    ) -> None:
        self.max_candidates = max(1, int(max_candidates))
        self.current_input = compact_whitespace(current_input)
        self.recent_context = compact_whitespace(recent_context)
        self.buffer = ""
        self.candidates: list[str] = []
        self.stopped_by_prompt_echo = False

    def feed(self, text_delta: str) -> list[str]:
        if self.done():
            return []
        self.buffer += str(text_delta or "")
        before = len(self.candidates)
        for candidate in _candidate_parts(self.buffer):
            normalized = _normalize_candidate(candidate)
            if not self._accept(normalized):
                continue
            self.candidates.append(normalized)
            if len(self.candidates) >= self.max_candidates:
                break
        if "<IMEV1>" in self.buffer or self.buffer.count("<CAND>") > 1:
            self.stopped_by_prompt_echo = True
        return self.candidates[before:]

    def done(self) -> bool:
        return (
            len(self.candidates) >= self.max_candidates
            or "</CAND>" in self.buffer
            or self.stopped_by_prompt_echo
        )

    def _accept(self, candidate: str) -> bool:
        if not candidate or candidate in self.candidates or candidate in _FILLER:
            return False
        if len(candidate) <= 1 or len(candidate) > 24:
            return False
        if "<" in candidate or ">" in candidate:
            return False
        if self.current_input and candidate == self.current_input:
            return False
        if self.recent_context and (candidate == self.recent_context or candidate in self.recent_context[-120:]):
            return False
        if re.fullmatch(r"[A-Za-z0-9_./:\-\s]+", candidate):
            return False
        return True


def _candidate_parts(text: str) -> list[str]:
    content = text
    if "<CAND>" in content:
        content = content.split("<CAND>", 1)[1]
    if "</CAND>" in content:
        content = content.split("</CAND>", 1)[0]
    rows = re.split(r"[\t\n\r,，、;；|/]+", content)
    return [item for item in rows if compact_whitespace(item)]


def _normalize_candidate(text: str) -> str:
    surface = compact_whitespace(text)
    surface = re.sub(r"^[0-9]+[.)、．]\s*", "", surface)
    return surface.strip(" \t\r\n\"'`[]{}(),，。！？:：;；、|")
