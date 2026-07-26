"""Demo and evaluation memory seeding.

`seed_demo_memories` used to live in `cli`, but `debug_server` needed it too
and imported it directly, so the two largest entry modules formed an import
cycle (`cli -> debug_server -> cli`). The CLI side had already been worked
around with seven function-local imports of `debug_server`, which hid the cycle
rather than removing it.

Seeding fixture memories is its own responsibility that sits above the adapter
and below any entry point, so it lives here and both entries depend on it in
one direction only. `cli` re-exports the two public functions, so existing
`from rag_ime.cli import seed_demo_memories` callers are unaffected.
"""

from __future__ import annotations

from .adapter import InputMethodAdapter
from .codex_history import CodexEvalCase
from .core_client import CoreMemory
from .models import InputEvent
from .text_utils import compact_whitespace, now_ms


def seed_demo_memories(adapter: InputMethodAdapter, memories: list[CoreMemory]) -> list[str]:
    event_ids: list[str] = []
    created_at = now_ms()
    for index, memory in enumerate(memories):
        tags = tuple(dict.fromkeys((*memory.tags, "curated")))
        event_id = adapter.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=created_at + index,
                source="demo_seed",
                committed_text=memory.text,
                privacy_disposition="allowed",
                recent_context=memory.evidence_preview,
                preedit="",
                schema_id="demo",
                app="cli",
                project=memory.project or adapter.project,
                provider_name="demo-fixture",
                tags=tags,
            )
        )
        event_ids.append(event_id)
        recorder = getattr(adapter.core, "record_memory_feedback", None)
        source_event_id = _event_id_from_memory_id_for_seed(event_id)
        if callable(recorder) and source_event_id is not None:
            for accept_index in range(3):
                recorder(
                    {
                        "event": "accepted",
                        "candidateId": event_id,
                        "candidateText": memory.text,
                        "sourceType": "memory",
                        "contextHash": f"demo-seed:{index}",
                        "timestampMs": created_at + index + accept_index,
                        "project": memory.project or adapter.project,
                        "sourceEventId": source_event_id,
                        "query": memory.text,
                    }
                )
    _materialize_seed_memory_projection(adapter, event_count=len(event_ids))
    return event_ids


def seed_eval_case_memories(adapter: InputMethodAdapter, cases: list[CodexEvalCase], *, project: str) -> list[str]:
    event_ids: list[str] = []
    created_at = now_ms()
    for index, case in enumerate(cases):
        expected = " ".join(case.expected_terms)
        committed_text = compact_whitespace(f"{expected} {case.query}" if expected else case.query)
        if not committed_text:
            continue
        event_id = adapter.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=created_at + index,
                source="eval_case_seed",
                committed_text=committed_text,
                privacy_disposition="allowed",
                recent_context=compact_whitespace(f"eval_case:{case.case_id} expected:{expected}"),
                preedit="",
                schema_id="eval_case",
                app="product-readiness-gate",
                project=case.project or project or adapter.project,
                provider_name="eval-case-fixture",
                tags=("eval-case", "curated", f"case:{case.case_id}"),
            )
        )
        event_ids.append(event_id)
        recorder = getattr(adapter.core, "record_memory_feedback", None)
        source_event_id = _event_id_from_memory_id_for_seed(event_id)
        if callable(recorder) and source_event_id is not None:
            recorder(
                {
                    "event": "accepted",
                    "candidateId": event_id,
                    "candidateText": committed_text,
                    "sourceType": "memory",
                    "contextHash": f"eval-case:{case.case_id}",
                    "timestampMs": created_at + index,
                    "project": case.project or project or adapter.project,
                    "sourceEventId": source_event_id,
                    "query": case.query,
                }
            )
    _materialize_seed_memory_projection(adapter, event_count=len(event_ids))
    return event_ids


def _materialize_seed_memory_projection(
    adapter: InputMethodAdapter,
    *,
    event_count: int,
) -> None:
    """Make explicit fixture/eval imports queryable before their CLI exits."""

    processor = getattr(adapter.core, "process_memory_projection_outbox", None)
    if not callable(processor) or event_count <= 0:
        return
    processor(max_events=max(32, event_count * 2 + 4))


def _event_id_from_memory_id_for_seed(memory_id: str) -> int | None:
    if not memory_id.startswith("event:"):
        return None
    try:
        return int(memory_id.split(":", 1)[1])
    except ValueError:
        return None
