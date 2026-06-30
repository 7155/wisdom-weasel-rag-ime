from __future__ import annotations

import json
import sys
from tempfile import TemporaryDirectory
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag_ime.adapter import InputMethodAdapter
from rag_ime.cli import run_acceptance, seed_demo_memories
from rag_ime.core_client import default_fixture_memories
from rag_ime.local_sqlite_core import LocalSqliteCoreClient


def main() -> int:
    with TemporaryDirectory(prefix="rag-ime-acceptance-") as tmp:
        core = LocalSqliteCoreClient(Path(tmp) / "rag-ime.sqlite")
        core.initialize()
        adapter = InputMethodAdapter(core)
        seed_demo_memories(adapter, default_fixture_memories())
        report = run_acceptance(adapter)
        report["db_backend"] = "local_sqlite_fts5"
        report["event_count"] = core.event_count()
        report["action_count"] = core.action_count()
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
    trigger = report["trigger_policy"]
    if trigger["single_char"]:
        failures.append("trigger policy should not refresh on a single character")
    if not trigger["idle_semantic"]:
        failures.append("trigger policy should refresh after semantic idle threshold")
    if trigger["sensitive"]:
        failures.append("trigger policy should not refresh in sensitive fields")
    if report["db_backend"] != "local_sqlite_fts5":
        failures.append("acceptance must use local SQLite/FTS5 backend")
    if report["event_count"] < 3:
        failures.append("acceptance did not seed enough local input events")
    if report["action_count"] < 2:
        failures.append("acceptance did not write memory actions")
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
