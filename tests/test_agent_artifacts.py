from __future__ import annotations

import hashlib
import json
import stat
import tempfile
import unittest
from pathlib import Path

from rag_ime.agent_artifacts import AgentArtifactStore


class AgentArtifactStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-agent-artifacts-")
        self.root = Path(self.tmp.name)
        self.store = AgentArtifactStore(
            self.root / "rag-ime.sqlite",
            root=self.root / "artifacts",
        )
        self.store.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_lifecycle_is_append_only_idempotent_and_public_ref_hides_paths(self) -> None:
        run_id = "subagent-run:test-one"
        self.store.append_records(
            owner_kind="subagent_run",
            owner_id=run_id,
            records=[
                {
                    "recordId": "run:1",
                    "eventType": "queued",
                    "createdAtMs": 1,
                    "payload": {},
                },
                {
                    "recordId": "run:2",
                    "eventType": "started",
                    "createdAtMs": 2,
                    "payload": {},
                },
            ],
        )
        reference = self.store.append_records(
            owner_kind="subagent_run",
            owner_id=run_id,
            records=[
                {
                    "recordId": "run:2",
                    "eventType": "started",
                    "createdAtMs": 2,
                    "payload": {},
                }
            ],
        )

        records = self.store.lifecycle_records(
            owner_kind="subagent_run",
            owner_id=run_id,
        )
        self.assertEqual([item["recordId"] for item in records], ["run:1", "run:2"])
        self.assertEqual(reference["recordCount"], 2)
        self.assertEqual(reference["ownerId"], run_id)
        self.assertNotIn(str(self.root), json.dumps(reference))

        lifecycle = next((self.root / "artifacts").rglob("lifecycle.jsonl"))
        self.assertEqual(stat.S_IMODE(lifecycle.stat().st_mode), 0o600)
        self.assertEqual(reference["sha256"], hashlib.sha256(lifecycle.read_bytes()).hexdigest())

    def test_atomic_snapshot_merges_runtime_and_supervision_checkpoints(self) -> None:
        run_id = "subagent-run:test-two"
        first = self.store.checkpoint(
            owner_kind="subagent_run",
            owner_id=run_id,
            projection={"id": run_id, "state": "running"},
            runtime_checkpoint={"usage": {"turnCount": 1}},
        )
        second = self.store.checkpoint(
            owner_kind="subagent_run",
            owner_id=run_id,
            runtime_checkpoint={"terminalState": "completed"},
            supervision={"phase": "soft", "reason": "near limit"},
        )
        snapshot = self.store.snapshot(owner_kind="subagent_run", owner_id=run_id)

        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertEqual(snapshot["revision"], 2)
        self.assertEqual(snapshot["projection"]["state"], "running")
        self.assertEqual(snapshot["runtimeCheckpoint"]["usage"]["turnCount"], 1)
        self.assertEqual(snapshot["runtimeCheckpoint"]["terminalState"], "completed")
        self.assertEqual(snapshot["supervision"]["phase"], "soft")
        self.assertEqual(first["snapshotRevision"], 1)
        self.assertEqual(second["snapshotRevision"], 2)

        snapshot_path = next((self.root / "artifacts").rglob("lifecycle-snapshot.json"))
        self.assertEqual(stat.S_IMODE(snapshot_path.stat().st_mode), 0o600)
        self.assertFalse(list(snapshot_path.parent.glob("*.tmp")))

    def test_public_inspection_is_bounded_redacted_and_never_returns_snapshot(self) -> None:
        run_id = "subagent-run:inspect"
        reference = self.store.append_records(
            owner_kind="subagent_run",
            owner_id=run_id,
            records=[
                {
                    "recordId": f"run:{index}",
                    "eventType": "tool_finished",
                    "createdAtMs": index,
                    "payload": {
                        "summary": f"record {index}",
                        "apiToken": "must-not-leak",
                    },
                }
                for index in range(1, 5)
            ],
        )
        self.store.checkpoint(
            owner_kind="subagent_run",
            owner_id=run_id,
            runtime_checkpoint={"lastMessage": {"secret": "private snapshot"}},
        )

        inspected = self.store.inspect(str(reference["artifactId"]), limit=2)

        self.assertEqual(
            [item["recordId"] for item in inspected["records"]],
            ["run:3", "run:4"],
        )
        self.assertEqual(inspected["totalRecords"], 4)
        self.assertEqual(inspected["returnedRecords"], 2)
        self.assertTrue(inspected["truncated"])
        serialized = json.dumps(inspected)
        self.assertNotIn("must-not-leak", serialized)
        self.assertNotIn("private snapshot", serialized)
        self.assertNotIn(str(self.root), serialized)
        self.assertEqual(
            self.store.reference_by_id(str(reference["artifactId"])),
            inspected["artifact"],
        )

    def test_symlinked_artifact_root_is_rejected(self) -> None:
        target = self.root / "outside"
        target.mkdir()
        symlink = self.root / "linked-artifacts"
        symlink.symlink_to(target, target_is_directory=True)
        store = AgentArtifactStore(self.root / "other.sqlite", root=symlink)

        with self.assertRaisesRegex(ValueError, "must not be a symlink"):
            store.initialize()


if __name__ == "__main__":
    unittest.main()
