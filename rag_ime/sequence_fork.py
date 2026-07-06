from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Sequence


@dataclass(frozen=True)
class BranchSpec:
    branch_id: str
    seed_text: str
    temperature: float
    max_tokens: int
    max_candidate_chars: int


@dataclass
class ForkedBranchResult:
    branch_id: str
    candidate: str
    tokens_generated: int
    elapsed_ms: float
    cache_fork_supported: bool
    fallback_reason: str = ""


def run_sequence_fork(
    *,
    prompt_tokens: Sequence[int],
    branches: Sequence[BranchSpec],
    prefill: Callable[[Sequence[int]], object],
    clone_cache: Callable[[object], object],
    decode_branch: Callable[[object, BranchSpec], tuple[str, int]],
    is_cancelled: Callable[[], bool] | None = None,
) -> list[ForkedBranchResult]:
    cancel = is_cancelled or (lambda: False)
    base_cache = prefill(prompt_tokens)
    results: list[ForkedBranchResult] = []
    for branch in branches:
        if cancel():
            break
        started = time.perf_counter()
        try:
            branch_cache = clone_cache(base_cache)
        except Exception:
            results.append(
                ForkedBranchResult(
                    branch_id=branch.branch_id,
                    candidate="",
                    tokens_generated=0,
                    elapsed_ms=(time.perf_counter() - started) * 1000.0,
                    cache_fork_supported=False,
                    fallback_reason="cache_clone_unsupported",
                )
            )
            break
        candidate, tokens_generated = decode_branch(branch_cache, branch)
        results.append(
            ForkedBranchResult(
                branch_id=branch.branch_id,
                candidate=candidate,
                tokens_generated=max(0, int(tokens_generated)),
                elapsed_ms=(time.perf_counter() - started) * 1000.0,
                cache_fork_supported=True,
            )
        )
    return results
