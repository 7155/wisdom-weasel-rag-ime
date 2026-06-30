from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag_ime.adapter import InputMethodAdapter
from rag_ime.cli import run_acceptance
from rag_ime.core_client import FixtureCoreClient


def main() -> int:
    report = run_acceptance(InputMethodAdapter(FixtureCoreClient()))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    failures = []
    if not report["local_first"]:
        failures.append("local_first must be true")
    if report["cloud_default"]:
        failures.append("cloud_default must be false")
    if report["fine_tuning"]:
        failures.append("fine_tuning must be false")
    for result in report["scenario_results"]:
        if result["candidate_count"] < 3:
            failures.append(f"{result['scenario_id']} needs at least 3 candidates")
        if not result["has_evidence_preview"]:
            failures.append(f"{result['scenario_id']} missing evidence preview")
        if not result["has_actions"]:
            failures.append(f"{result['scenario_id']} missing governance actions")
    if not report["action_result"]["deleted_removed"]:
        failures.append("delete action did not remove candidate from later ranking")
    if not report["agent_hook"]["has_project_memory_block"]:
        failures.append("agent hook missing PROJECT_MEMORY_BLOCK")
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
