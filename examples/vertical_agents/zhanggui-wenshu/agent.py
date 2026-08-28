"""Minimal executable 掌柜问数 vertical-Agent example.

The process emits only one canonical Trace envelope.  The parent process
performs verification and persistence; this example stands in for a custom
vertical Agent's own RAG and Memory adapters.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from rag_ime.trace_runtime import (
    EvidenceRef,
    build_trace_envelope,
    fingerprint_text,
    make_span,
)


def build_zhanggui_trace(*, run_id: str = "demo") -> dict[str, object]:
    example_root = Path(__file__).resolve().parent
    manifest = json.loads(
        (example_root.parent / "zhanggui-wenshu.json").read_text(encoding="utf-8")
    )
    document = (example_root / "orders-ledger.md").read_text(encoding="utf-8")
    match = re.search(r"订单总额为\s*([0-9.]+)\s*万元", document)
    if match is None:
        raise RuntimeError("orders ledger contains no order total")
    answer = f"{match.group(1)} 万元"
    self_test = manifest["selfTest"]
    fixture = manifest["fixtures"][0]
    rag_evidence = fixture["ragEvidence"]
    memory = self_test["memory"]
    start_ms = 1_700_000_000_000
    return build_trace_envelope(
        trace_id=f"trace:vertical:zhanggui-wenshu:custom-process:{run_id}",
        source_kind="vertical_agent",
        input_text=str(self_test["query"]),
        binding={
            "sourceLoopId": f"vertical-custom-process:zhanggui-wenshu:{run_id}",
        },
        spans=(
            make_span(
                span_id="span:zhanggui:input",
                name="agent.input",
                started_at_ms=start_ms,
                ended_at_ms=start_ms + 1,
            ),
            make_span(
                span_id="span:zhanggui:retrieve",
                name="rag.retrieve",
                parent_span_id="span:zhanggui:input",
                started_at_ms=start_ms + 1,
                ended_at_ms=start_ms + 2,
                attributes={
                    "producerKind": "custom_process",
                    "retrievalMode": "local_fixture_scan",
                    "resultCount": 1,
                },
            ),
            make_span(
                span_id="span:zhanggui:memory",
                name="memory.recall",
                parent_span_id="span:zhanggui:input",
                started_at_ms=start_ms + 2,
                ended_at_ms=start_ms + 3,
                attributes={"producerKind": "custom_process"},
            ),
            make_span(
                span_id="span:zhanggui:answer",
                name="agent.answer",
                parent_span_id="span:zhanggui:input",
                started_at_ms=start_ms + 3,
                ended_at_ms=start_ms + 4,
                attributes={
                    "producerKind": "custom_process",
                    "answerFingerprint": fingerprint_text(answer),
                },
            ),
        ),
        evidence=(
            EvidenceRef(
                str(rag_evidence["evidenceId"]),
                "knowledge",
                str(rag_evidence["sourceRef"]),
                source_lane=str(rag_evidence["sourceLane"]),
                evidence_stage="retrieval_output",
            ),
            EvidenceRef(
                str(memory["memoryId"]),
                "memory",
                str(memory["sourceRef"]),
                source_lane="fixture_memory",
                evidence_stage="memory_recall",
            ),
        ),
        now_ms=start_ms,
    ).to_dict()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default="demo")
    args = parser.parse_args()
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}", args.run_id) is None:
        raise SystemExit("run id is invalid")
    print(
        json.dumps(
            build_zhanggui_trace(run_id=args.run_id),
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )
