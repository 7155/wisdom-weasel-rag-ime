#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag_ime.minimind_quality_gate import DEFAULT_DATASET_ROOT
from rag_ime.minimind_raw_capture import LoopbackMlxRawClient, capture_raw_completion_dataset, write_raw_capture


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Capture decoded MiniMind branches before production candidate parsing/reranking"
    )
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET_ROOT))
    parser.add_argument("--split", choices=("train", "val", "test"), default="test")
    parser.add_argument("--endpoint", default=os.environ.get("RAG_IME_PREDICTOR_BASE_URL", "http://127.0.0.1:8767"))
    parser.add_argument("--model", default=os.environ.get("RAG_IME_PREDICTOR_MODEL", ""), required=False)
    parser.add_argument("--checkpoint", default=os.environ.get("RAG_IME_MODEL_ID", ""))
    parser.add_argument(
        "--checkpoint-path",
        default="",
        help="Require /health to expose the same local artifact fingerprint before capture",
    )
    parser.add_argument("--max-candidates", type=int, default=3)
    parser.add_argument("--max-tokens", type=int, default=8)
    parser.add_argument("--temperature", type=float, default=0.15)
    parser.add_argument("--top-p", type=float, default=0.85)
    parser.add_argument("--timeout-ms", type=int, default=5000)
    parser.add_argument("--output", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args(argv)

    try:
        client = LoopbackMlxRawClient(
            args.endpoint,
            model=args.model,
            max_candidates=args.max_candidates,
            max_tokens=args.max_tokens,
            temperature=args.temperature,
            top_p=args.top_p,
            timeout_s=max(100, args.timeout_ms) / 1000,
        )
        runtime_evidence = client.verify_loaded_model(args.checkpoint_path) if args.checkpoint_path else {}
        rows, report = capture_raw_completion_dataset(
            client.predict,
            dataset_root=args.dataset,
            split=args.split,
            max_candidates=args.max_candidates,
            checkpoint=args.checkpoint or args.model,
        )
        report["endpoint"] = client.url
        if runtime_evidence:
            report.update(runtime_evidence)
        write_raw_capture(rows, report, output_path=args.output, report_path=args.report)
    except (OSError, RuntimeError, ValueError) as exc:
        payload = {"ok": False, "error": str(exc)}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 1

    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
