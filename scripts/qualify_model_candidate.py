#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag_ime.minimind_quality_gate import DEFAULT_DATASET_ROOT
from rag_ime.model_candidate_qualification import (
    finalize_model_candidate_qualification,
    prepare_model_candidate_plan,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare or finalize an inactive model-candidate qualification")
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--model-path", required=True)
    prepare.add_argument("--model-id", required=True)
    prepare.add_argument("--profile", default="minimind_ime_v2")
    prepare.add_argument("--dataset", default=str(DEFAULT_DATASET_ROOT))
    prepare.add_argument("--output", required=True)
    finalize = subparsers.add_parser("finalize")
    finalize.add_argument("--plan", required=True)
    finalize.add_argument("--raw-quality", required=True)
    finalize.add_argument("--production-quality", required=True)
    finalize.add_argument("--foreground-evidence", default="")
    finalize.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            result = prepare_model_candidate_plan(
                model_path=args.model_path,
                model_id=args.model_id,
                profile=args.profile,
                dataset_root=args.dataset,
                output_path=args.output,
            )
        else:
            result = finalize_model_candidate_qualification(
                plan_path=args.plan,
                raw_quality_path=args.raw_quality,
                production_quality_path=args.production_quality,
                foreground_evidence_path=args.foreground_evidence or None,
                output_path=args.output,
            )
    except (FileNotFoundError, json.JSONDecodeError, OSError, RuntimeError, ValueError) as exc:
        result = {"ok": False, "error": str(exc)}
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
