from __future__ import annotations

import hashlib
import importlib.util
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
SCRIPT = SCRIPTS / "room_three_member_canary.py"
SPEC = importlib.util.spec_from_file_location("room_three_member_canary", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
CANARY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CANARY)


class RoomThreeMemberCanaryTest(unittest.TestCase):
    def test_project_memory_check_accepts_meaning_not_one_exact_sentence(self) -> None:
        self.assertTrue(
            CANARY._is_useful_project_memory(
                "代码任务先读测试，只做最小改动，并用测试证据完成交付。"
            )
        )
        self.assertTrue(
            CANARY._is_useful_project_memory(
                "代码任务使用最小修改、真实测试和证据化交付。"
            )
        )
        self.assertFalse(
            CANARY._is_useful_project_memory(
                "喜欢简洁回答，周末可以整理一次笔记。"
            )
        )

    def test_dispatch_chain_requires_collaboration_and_handoff_siblings(self) -> None:
        tasks = [
            self._task("t1", None, "pa"),
            self._task("t2", "t1", "pb", owner_participant_id="pa"),
            self._task("t3", "t1", "pc"),
        ]
        dispatches = [
            self._dispatch("d3", "t3", "d1", 1, 0, "close", "pc", "sc"),
            self._dispatch("d1", "t1", None, 0, 0, "execute", "pa", "sa"),
            self._dispatch("d2", "t2", "d1", 1, 1, "review", "pb", "sb"),
        ]

        evidence = CANARY.dispatch_chain_evidence(
            tasks,
            dispatches,
            participant_ids={"A": "pa", "B": "pb", "C": "pc"},
            session_ids={"A": "sa", "B": "sb", "C": "sc"},
        )

        self.assertTrue(evidence["passed"])
        self.assertTrue(all(evidence["checks"].values()))

    def test_dispatch_chain_rejects_direct_or_extra_routing(self) -> None:
        tasks = [
            self._task("t1", None, "pa"),
            self._task("t2", None, "pb"),
            self._task("t3", "t2", "pc"),
        ]
        dispatches = [
            self._dispatch("d1", "t1", None, 0, 0, "execute", "pa", "sa"),
            self._dispatch("d2", "t2", None, 0, 0, "execute", "pb", "sb"),
            self._dispatch("d3", "t3", "d2", 1, 0, "close", "pc", "sc"),
        ]

        evidence = CANARY.dispatch_chain_evidence(
            tasks,
            dispatches,
            participant_ids={"A": "pa", "B": "pb", "C": "pc"},
            session_ids={"A": "sa", "B": "sb", "C": "sc"},
        )

        self.assertFalse(evidence["passed"])
        self.assertFalse(evidence["checks"]["parents"])
        self.assertFalse(evidence["checks"]["hops"])

    def test_tool_workload_requires_parallel_review_and_formal_handoff(self) -> None:
        receipts = {
            "A": self._tool_set(
                room_state=["applied"],
                room_collaborate=["applied"],
                workspace_list=["applied"],
                workspace_search=["applied"],
                workspace_read=["failed", "applied", "applied"],
                workspace_patch=["applied"],
                workspace_shell=["failed", "applied"],
                room_post=["applied"],
                room_commit=["applied"],
            ),
            "B": self._tool_set(
                room_state=["applied"],
                workspace_read=["applied", "applied"],
                room_post=["applied"],
                room_commit=["applied"],
            ),
            "C": self._tool_set(
                room_state=["applied"],
                workspace_read=["applied", "applied"],
                workspace_shell=["applied"],
                room_post=["applied"],
                room_commit=["applied"],
            ),
        }

        checks = CANARY.tool_workload_checks(receipts)

        self.assertTrue(all(checks.values()))
        receipts["B"]["workspace_patch"] = self._receipt(["applied"])
        self.assertFalse(CANARY.tool_workload_checks(receipts)["bStayedReadOnly"])

    def test_managed_approval_checks_require_policy_owned_receipts(self) -> None:
        approvals = {
            "A": [
                self._approval("workspace_shell", "failed", 1),
                self._approval("workspace_patch", "applied", 2),
                self._approval("workspace_shell", "applied", 3),
            ],
            "B": [],
            "C": [self._approval("workspace_shell", "applied", 4)],
        }

        self.assertTrue(all(CANARY.managed_approval_checks(approvals).values()))
        approvals["C"][0]["decidedBy"] = "native-control-center"
        self.assertFalse(
            CANARY.managed_approval_checks(approvals)["policyOwned"]
        )

    def test_private_transcript_evidence_rejects_cross_session_tool_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            contexts = {}
            for member in ("A", "B", "C"):
                payload = {
                    "type": "message",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "toolCall",
                                "toolCallId": f"tool-{member}",
                            }
                        ],
                    },
                }
                path = root / f"{member}.jsonl"
                path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                contexts[member] = {"transcript": {"sha256": digest}}

            isolated = CANARY.private_transcript_evidence(root, contexts)
            self.assertTrue(isolated["passed"])

            b_path = root / "B.jsonl"
            b_payload = json.loads(b_path.read_text(encoding="utf-8"))
            b_payload["leak"] = "tool-A"
            b_path.write_text(json.dumps(b_payload) + "\n", encoding="utf-8")
            contexts["B"]["transcript"]["sha256"] = hashlib.sha256(
                b_path.read_bytes()
            ).hexdigest()

            leaked = CANARY.private_transcript_evidence(root, contexts)
            self.assertFalse(leaked["passed"])
            self.assertEqual(leaked["leakedAToolCallIds"], ["tool-A"])

    def test_loaded_tool_receipts_include_disclosures_without_invocations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "room.sqlite"
            with sqlite3.connect(database) as connection:
                connection.executescript(
                    """
                    CREATE TABLE room_v2_capability_manifests(
                        manifest_id TEXT PRIMARY KEY,
                        dispatch_id TEXT NOT NULL
                    );
                    CREATE TABLE room_v2_capability_runtime_bindings(
                        session_id TEXT NOT NULL,
                        manifest_id TEXT NOT NULL
                    );
                    CREATE TABLE room_v2_tool_disclosure_receipts(
                        receipt_id TEXT PRIMARY KEY,
                        manifest_id TEXT NOT NULL,
                        receipt_kind TEXT NOT NULL,
                        tool_name TEXT NOT NULL,
                        created_at_ms INTEGER NOT NULL
                    );
                    """
                )
                for index, member in enumerate(("A", "B", "C"), start=1):
                    manifest = f"manifest-{member}"
                    connection.execute(
                        "INSERT INTO room_v2_capability_manifests VALUES (?, ?)",
                        (manifest, f"dispatch-{member}"),
                    )
                    connection.execute(
                        "INSERT INTO room_v2_capability_runtime_bindings VALUES (?, ?)",
                        (f"session-{member}", manifest),
                    )
                    connection.execute(
                        "INSERT INTO room_v2_tool_disclosure_receipts VALUES (?, ?, 'load', ?, ?)",
                        (f"load-{member}-used", manifest, "room_state", index),
                    )
                connection.execute(
                    "INSERT INTO room_v2_tool_disclosure_receipts VALUES (?, ?, 'load', ?, ?)",
                    ("load-B-unused", "manifest-B", "room_collaborate", 20),
                )
                connection.execute(
                    "INSERT INTO room_v2_tool_disclosure_receipts VALUES (?, ?, 'search', '', ?)",
                    ("search-B", "manifest-B", 21),
                )

            evidence = CANARY.loaded_tool_receipt_evidence(
                database,
                session_ids={member: f"session-{member}" for member in ("A", "B", "C")},
                dispatches=[
                    {"dispatchId": f"dispatch-{member}"}
                    for member in ("A", "B", "C")
                ],
            )

            self.assertEqual(
                evidence["B"],
                [
                    {"receiptId": "load-B-used", "toolName": "room_state"},
                    {"receiptId": "load-B-unused", "toolName": "room_collaborate"},
                ],
            )

    @staticmethod
    def _dispatch(
        dispatch_id: str,
        task_id: str,
        parent_id: str | None,
        hop: int,
        depth: int,
        intent: str,
        participant_id: str,
        session_id: str,
    ) -> dict[str, object]:
        return {
            "dispatchId": dispatch_id,
            "taskId": task_id,
            "parentDispatchId": parent_id,
            "hopCount": hop,
            "depth": depth,
            "intentKind": intent,
            "targetParticipantId": participant_id,
            "targetSessionId": session_id,
            "capabilityEpoch": hop + 1,
            "state": "committed",
        }

    @staticmethod
    def _task(
        task_id: str,
        parent_id: str | None,
        participant_id: str,
        *,
        owner_participant_id: str | None = None,
    ) -> dict[str, object]:
        return {
            "taskId": task_id,
            "parentTaskId": parent_id,
            "ownerParticipantId": owner_participant_id or participant_id,
            "assigneeParticipantId": participant_id,
            "state": "completed",
        }

    @staticmethod
    def _receipt(statuses: list[str]) -> dict[str, object]:
        return {
            "invocationCount": len(statuses),
            "loadReceiptIds": ["load:one"] if statuses else [],
            "items": [{"status": status} for status in statuses],
        }

    @staticmethod
    def _approval(tool: str, state: str, requested_at_ms: int) -> dict[str, object]:
        return {
            "approvalId": f"approval:{requested_at_ms}",
            "toolId": tool,
            "state": state,
            "requestedAtMs": requested_at_ms,
            "decidedBy": "execution-policy:workspace_managed",
            "receipt": {"summary": "done"},
        }

    @classmethod
    def _tool_set(cls, **statuses: list[str]) -> dict[str, dict[str, object]]:
        names = (
            "room_state",
            "room_collaborate",
            "workspace_list",
            "workspace_search",
            "workspace_read",
            "workspace_patch",
            "workspace_shell",
            "room_post",
            "room_commit",
        )
        return {name: cls._receipt(statuses.get(name, [])) for name in names}


if __name__ == "__main__":
    unittest.main()
