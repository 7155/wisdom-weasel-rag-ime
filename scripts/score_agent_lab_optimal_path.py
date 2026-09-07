#!/usr/bin/env python3
"""Score a user-defined Agent Lab candidate tree without running new agents.

This command is intentionally read-only with respect to source, runtime and
old experiment receipts.  It writes one append-only path-selection receipt.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag_ime.agent_lab.optimal_path import evaluate_path_search

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    request_path = args.request.expanduser().resolve(strict=True)
    output_path = args.output.expanduser().resolve()
    request = json.loads(request_path.read_text(encoding="utf-8"))
    if not isinstance(request, dict):
        raise SystemExit("--request must contain a JSON object")
    receipt = evaluate_path_search(request, generated_at_ms=int(time.time() * 1_000))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(f".{output_path.name}.tmp")
    temporary.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(output_path)
    selected = receipt["selectedPath"][-1]["nodeId"]
    claim = receipt["claim"]
    print(json.dumps({
        "status": "completed",
        "output": str(output_path),
        "selectedNode": selected,
        "claimStatus": claim["status"],
        "summary": claim["summary"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
