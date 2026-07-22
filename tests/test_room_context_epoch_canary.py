from __future__ import annotations

import importlib.util
import hashlib
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "room_context_epoch_canary.py"
SPEC = importlib.util.spec_from_file_location("room_context_epoch_canary", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
CANARY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CANARY)
sys.modules.setdefault("room_context_epoch_canary", CANARY)
REPORT_SCRIPT = ROOT / "scripts" / "report_room_context_epoch_canary.py"
REPORT_SPEC = importlib.util.spec_from_file_location(
    "report_room_context_epoch_canary", REPORT_SCRIPT
)
assert REPORT_SPEC is not None and REPORT_SPEC.loader is not None
REPORT = importlib.util.module_from_spec(REPORT_SPEC)
REPORT_SPEC.loader.exec_module(REPORT)


class RoomContextEpochCanaryTest(unittest.TestCase):
    def test_workload_files_are_two_real_files_inside_the_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            source = workspace / "rag_ime"
            source.mkdir()
            first = source / "agent_service.py"
            second = source / "agent_room_kernel.py"
            first.write_text("service\n", encoding="utf-8")
            second.write_text("kernel\n", encoding="utf-8")

            resolved = CANARY.resolve_workload_files(workspace)

        self.assertEqual(resolved, (first.resolve(), second.resolve()))

    def test_tool_receipt_evidence_requires_two_applied_fenced_calls(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "receipts.sqlite"
            with sqlite3.connect(path) as connection:
                connection.executescript(
                    """
                    CREATE TABLE room_v2_capability_manifests(
                        manifest_id TEXT, manifest_hash TEXT, dispatch_id TEXT
                    );
                    CREATE TABLE room_v2_capability_runtime_bindings(
                        manifest_id TEXT, session_id TEXT
                    );
                    CREATE TABLE room_v2_tool_disclosure_receipts(
                        receipt_id TEXT, receipt_kind TEXT,
                        tool_name TEXT, schema_hash TEXT
                    );
                    CREATE TABLE room_v2_tool_invocation_receipts(
                        receipt_id TEXT, manifest_id TEXT, manifest_hash TEXT,
                        load_receipt_id TEXT, canonical_tool_name TEXT,
                        created_at_ms INTEGER
                    );
                    CREATE TABLE room_v2_tool_execution_receipts(
                        execution_receipt_id TEXT, invocation_receipt_id TEXT,
                        status TEXT, result_hash TEXT
                    );
                    """
                )
                connection.execute(
                    "INSERT INTO room_v2_capability_manifests VALUES (?, ?, ?)",
                    ("manifest:1", "m" * 64, "dispatch:1"),
                )
                connection.execute(
                    "INSERT INTO room_v2_capability_runtime_bindings VALUES (?, ?)",
                    ("manifest:1", "session:1"),
                )
                connection.execute(
                    "INSERT INTO room_v2_tool_disclosure_receipts VALUES (?, ?, ?, ?)",
                    ("load:read", "load", "workspace_read", "s" * 64),
                )
                for index in (1, 2):
                    connection.execute(
                        "INSERT INTO room_v2_tool_invocation_receipts VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            f"invoke:{index}",
                            "manifest:1",
                            "m" * 64,
                            "load:read",
                            "workspace_read",
                            index,
                        ),
                    )
                    connection.execute(
                        "INSERT INTO room_v2_tool_execution_receipts VALUES (?, ?, ?, ?)",
                        (f"execute:{index}", f"invoke:{index}", "applied", "r" * 64),
                    )

            evidence = CANARY.tool_receipt_evidence(
                path,
                session_id="session:1",
                dispatch_ids=["dispatch:1"],
                tool_name="workspace_read",
            )

        self.assertEqual(evidence["loadReceiptIds"], ["load:read"])
        self.assertEqual(evidence["invocationCount"], 2)
        self.assertEqual(evidence["appliedExecutionCount"], 2)

    def test_transition_report_resolves_exact_skill_and_tool_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "transition.sqlite"
            evidence = {
                "originalRequirementCount": 1,
                "currentTaskPresent": True,
                "acceptanceCount": 3,
                "blockerCount": 0,
                "handoffPresent": True,
                "skillReceiptId": "skill:1",
                "toolReceiptIds": ["load:workspace", "load:commit"],
                "roomProviderEntryHash": "a" * 64,
                "sessionProviderEntryHash": "b" * 64,
            }
            with sqlite3.connect(path) as connection:
                connection.executescript(
                    """
                    CREATE TABLE room_v2_session_context_epoch_transitions(
                        session_id TEXT, source_ref TEXT, from_epoch INTEGER,
                        to_epoch INTEGER, epoch_reason TEXT, evidence_json TEXT
                    );
                    CREATE TABLE room_v2_tool_disclosure_receipts(
                        receipt_id TEXT, tool_name TEXT,
                        schema_hash TEXT, receipt_kind TEXT
                    );
                    CREATE TABLE room_v2_skill_load_receipts(
                        receipt_id TEXT, skill_id TEXT,
                        skill_hash TEXT, load_reason TEXT
                    );
                    """
                )
                connection.execute(
                    "INSERT INTO room_v2_session_context_epoch_transitions VALUES (?, ?, ?, ?, ?, ?)",
                    ("session:1", "compact:1", 1, 2, "compaction", json.dumps(evidence)),
                )
                connection.executemany(
                    "INSERT INTO room_v2_tool_disclosure_receipts VALUES (?, ?, ?, ?)",
                    [
                        ("load:workspace", "workspace_read", "c" * 64, "load"),
                        ("load:commit", "room_commit", "d" * 64, "load"),
                    ],
                )
                connection.execute(
                    "INSERT INTO room_v2_skill_load_receipts VALUES (?, ?, ?, ?)",
                    ("skill:1", "room-implementation", "e" * 64, "compaction_restore"),
                )

            transition = REPORT._transition_evidence(
                path,
                session_id="session:1",
                source_ref="compact:1",
            )

        self.assertEqual(transition["skillReceipt"]["receiptId"], "skill:1")
        self.assertEqual(
            {item["toolName"] for item in transition["toolReceipts"]},
            {"workspace_read", "room_commit"},
        )

    def test_message_acceptance_requires_the_v2_root_contract(self) -> None:
        self.assertEqual(
            CANARY.accepted_root_id(
                {
                    "schemaVersion": "wisdom-weasel.room-ingress-accepted.v1",
                    "rootId": "room-root:1",
                }
            ),
            "room-root:1",
        )
        with self.assertRaisesRegex(RuntimeError, "Room V2 is not active"):
            CANARY.accepted_root_id(
                {
                    "schemaVersion": "rag-ime.agent-room-message.v1",
                    "roomTurnId": "room-turn:legacy",
                }
            )

    def test_memory_check_is_scoped_to_the_session_memory_envelope(self) -> None:
        requests = [
            {
                "payload": {
                    "input": [
                        {
                            "role": "developer",
                            "content": (
                                "Core 规则：不输出相关度、分数或内部 ID。\n"
                                '<rag-ime-context type="session_memory">\n'
                                "## Session 记忆\n"
                                "- **项目偏好**: 每个 epoch 只补一份恢复包。\n"
                                "</rag-ime-context>"
                            ),
                        }
                    ]
                }
            }
        ]

        blocks = CANARY._provider_session_memory_blocks(requests)

        self.assertEqual(len(blocks), 1)
        self.assertIn("每个 epoch 只补一份恢复包", blocks[0])
        self.assertNotIn("相关度", blocks[0])

    def test_memory_check_finds_internal_retrieval_metadata(self) -> None:
        requests = [
            {
                "payload": {
                    "input": (
                        '<rag-ime-context type="session_memory">'
                        "## Session 记忆\nsourceId=atom:private\n相关度：0.92"
                        "</rag-ime-context>"
                    )
                }
            }
        ]

        block = CANARY._provider_session_memory_blocks(requests)[0]
        leaked = {
            token for token in CANARY._FORBIDDEN_MEMORY_METADATA if token in block
        }

        self.assertEqual(leaked, {"sourceId", "相关度："})

    def test_transcript_evidence_rejects_room_projection_as_user_message(self) -> None:
        entries = [
            {"type": "session", "version": 3},
            {
                "type": "message",
                "message": {
                    "role": "user",
                    "content": "执行当前受管 Room 任务；任务事实以 Provider Context 为准。",
                },
            },
            {
                "type": "message",
                "message": {
                    "role": "user",
                    "content": (
                        "收工检查未通过：请使用精确验收 ID。"
                        '<room-projection state="pending">不应进入 Session</room-projection>'
                    ),
                },
            },
        ]
        payload = "".join(
            json.dumps(entry, ensure_ascii=False) + "\n" for entry in entries
        ).encode("utf-8")
        digest = hashlib.sha256(payload).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.jsonl"
            path.write_bytes(payload)

            evidence = CANARY.transcript_evidence(Path(directory), digest)

        self.assertEqual(evidence["privateTriggerCount"], 1)
        self.assertEqual(evidence["repairContinuationCount"], 1)
        self.assertEqual(evidence["roomEnvelopeCount"], 1)

    def test_offline_report_reuses_recorded_session_memory_receipt(self) -> None:
        receipt = REPORT._recorded_memory_evidence(
            {
                "blockCount": 2,
                "nonEmptyBlockCount": 2,
                "forbiddenMetadata": [],
            },
            turn_id="turn:1",
            source="canary_report",
        )

        self.assertEqual(
            receipt,
            {
                "turnId": "turn:1",
                "blockCount": 2,
                "nonEmptyBlockCount": 2,
                "forbiddenMetadata": [],
                "source": "canary_report",
            },
        )

    def test_offline_report_reuses_sealed_transcript_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.json"
            path.write_text(
                json.dumps(
                    {
                        "epochs": [],
                        "observations": {"transcript": {"sha256": "a" * 64}},
                    }
                ),
                encoding="utf-8",
            )

            digest = REPORT._prior_transcript_sha(path)

        self.assertEqual(digest, "a" * 64)

    def test_transcript_boundary_does_not_require_a_repair_per_epoch(self) -> None:
        checks = REPORT._transcript_boundary_checks(
            {
                "privateTriggerCount": 3,
                "repairContinuationCount": 1,
                "roomEnvelopeCount": 0,
                "publicCanaryPostCount": 0,
            },
            epoch_count=3,
        )

        self.assertEqual(
            checks,
            {
                "repairContinuationsAreBounded": True,
                "roomContextAbsentFromSessionTranscript": True,
            },
        )

    def test_transcript_boundary_rejects_an_unbounded_repair_loop(self) -> None:
        checks = REPORT._transcript_boundary_checks(
            {
                "privateTriggerCount": 3,
                "repairContinuationCount": 4,
                "roomEnvelopeCount": 0,
                "publicCanaryPostCount": 0,
            },
            epoch_count=3,
        )

        self.assertFalse(checks["repairContinuationsAreBounded"])


if __name__ == "__main__":
    unittest.main()
