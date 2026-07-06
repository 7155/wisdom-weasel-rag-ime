#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", required=True)
    parser.add_argument("--max-hot-first-candidate-p95-ms", type=float, default=500)
    parser.add_argument("--max-hot-three-candidates-p95-ms", type=float, default=900)
    parser.add_argument("--min-format-valid-rate", type=float, default=0.99)
    parser.add_argument("--max-generic-filler-rate", type=float, default=0.02)
    parser.add_argument("--max-duplicate-rate", type=float, default=0.05)
    args = parser.parse_args()
    payload = json.loads(Path(args.report).read_text(encoding="utf-8"))
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    checks = [
        ("firstCandidateP95Ms", float(summary.get("firstCandidateP95Ms") or 0), "<=", args.max_hot_first_candidate_p95_ms),
        ("threeCandidatesP95Ms", float(summary.get("threeCandidatesP95Ms") or 0), "<=", args.max_hot_three_candidates_p95_ms),
        ("formatValidRate", float(summary.get("formatValidRate") or 0), ">=", args.min_format_valid_rate),
        ("genericFillerRate", float(summary.get("genericFillerRate") or 0), "<=", args.max_generic_filler_rate),
        ("duplicateRate", float(summary.get("duplicateRate") or 0), "<=", args.max_duplicate_rate),
    ]
    failed = []
    for name, actual, op, expected in checks:
        ok = actual >= expected if op == ">=" else actual <= expected
        if not ok:
            failed.append(f"{name}={actual} {op} {expected}")
    if failed:
        print("Predictor latency gate failed: " + "; ".join(failed))
        return 1
    print("Predictor latency gate passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
