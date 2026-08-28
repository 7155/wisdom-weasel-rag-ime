from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from rag_ime.sandbox_run_store import SandboxRunConflict, SandboxRunStore
from rag_ime.trace_runtime import build_sandbox_run


class SandboxRunStoreTests(unittest.TestCase):
    def _run(self, run_id: str, *, now_ms: int = 10) -> dict[str, object]:
        return build_sandbox_run(
            sandbox_run_id=run_id,
            app_id="sgg",
            workspace_root="/workspace/demo",
            workspace_binding_id="workspace-binding:demo",
            trace_ids=[f"trace:{run_id}"],
            eval_run_ids=[f"eval:{run_id}"],
            now_ms=now_ms,
        ).to_dict()

    def test_persist_is_canonical_and_idempotent_without_payload_hash(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sandbox-run-store-") as temporary:
            store = SandboxRunStore(Path(temporary) / "observability.sqlite")
            run = self._run("sandbox:one")

            persisted = store.persist(run)
            reordered = json.loads(json.dumps(run, ensure_ascii=False))
            reordered = {
                "updatedAtMs": reordered["updatedAtMs"],
                "evalRunIds": reordered["evalRunIds"],
                "policy": reordered["policy"],
                "status": reordered["status"],
                "createdAtMs": reordered["createdAtMs"],
                "appId": reordered["appId"],
                "schemaVersion": reordered["schemaVersion"],
                "traceIds": reordered["traceIds"],
                "sandboxRunId": reordered["sandboxRunId"],
            }

            self.assertEqual(store.persist(reordered), persisted)
            self.assertEqual(store.get("sandbox:one"), persisted)
            self.assertEqual(store.count(), 1)
            columns = {
                str(row[1])
                for row in sqlite3.connect(Path(temporary) / "observability.sqlite")
                .execute("PRAGMA table_info(sandbox_runs)")
            }
            self.assertNotIn("payload_hash", columns)

            changed = dict(run)
            changed["status"] = "failed"
            with self.assertRaises(SandboxRunConflict):
                store.persist(changed)

    def test_list_is_bounded_newest_first(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sandbox-run-list-") as temporary:
            database = Path(temporary) / "observability.sqlite"
            store = SandboxRunStore(database)
            store.persist(self._run("sandbox:old", now_ms=10))
            store.persist(self._run("sandbox:new", now_ms=20))

            self.assertEqual(
                [item["sandboxRunId"] for item in store.list(limit=1)],
                ["sandbox:new"],
            )
            self.assertEqual(store.count(), 2)


if __name__ == "__main__":
    unittest.main()
