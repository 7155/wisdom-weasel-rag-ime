from __future__ import annotations

import hashlib
import importlib.util
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
SCRIPT = SCRIPTS / "room_three_member_canary.py"
SPEC = importlib.util.spec_from_file_location("room_three_member_canary", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
CANARY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CANARY)


class RoomThreeMemberCanaryTest(unittest.TestCase):
    def test_public_posts_come_from_the_ui_timeline_and_include_both_sources(
        self,
    ) -> None:
        events = []
        for index, source in enumerate(
            ("room_post", "room_commit", "room_post", "room_commit"),
            start=1,
        ):
            events.append(
                {
                    "eventType": "room_post",
                    "payload": {
                        "post": {
                            "postId": f"post-{index}",
                            "rootId": "root-1",
                            "createdAtMs": index,
                            "publicationSource": {
                                "kind": source,
                                "ref": f"source-{index}",
                            },
                        }
                    },
                }
            )
        events.append(
            {
                "eventType": "room_post",
                "payload": {
                    "post": {
                        "postId": "other-root",
                        "rootId": "root-2",
                        "createdAtMs": 0,
                        "publicationSource": {
                            "kind": "room_post",
                            "ref": "other",
                        },
                    }
                },
            }
        )

        posts = CANARY._public_posts_from_timeline_snapshot(
            {"events": events},
            root_id="root-1",
        )

        self.assertEqual(
            [item["postId"] for item in posts],
            ["post-1", "post-2", "post-3", "post-4"],
        )
        self.assertEqual(
            [
                item["publicationSource"]["kind"]
                for item in posts
            ],
            ["room_post", "room_commit", "room_post", "room_commit"],
        )

    def test_natural_posts_publish_each_terminal_summary_once(self) -> None:
        terminal_posts = {
            member: [
                {
                    "postId": f"terminal-{member}",
                    "kind": "result",
                    "content": f"{member} 已完成",
                    "publicationSource": {"kind": "room_commit"},
                }
            ]
            for member in ("A", "B", "C")
        }
        progress = {
            "postId": "progress-A",
            "kind": "progress",
            "content": "A 仍在继续实现",
            "publicationSource": {"kind": "room_post"},
        }
        terminal_posts["A"].insert(0, progress)
        public_posts = [
            item
            for member in ("A", "B", "C")
            for item in terminal_posts[member]
        ]

        checks = CANARY.natural_public_post_checks(
            public_posts,
            posts_by_member=terminal_posts,
            timeline_truncated=False,
        )

        self.assertTrue(all(checks.values()))
        independent_evidence = {
            "postId": "evidence-B",
            "kind": "evidence",
            "content": "B 发现当前实现仍是占位符",
            "publicationSource": {"kind": "room_post"},
        }
        terminal_posts["B"].insert(0, independent_evidence)
        evidence_checks = CANARY.natural_public_post_checks(
            [*public_posts, independent_evidence],
            posts_by_member=terminal_posts,
            timeline_truncated=False,
        )
        self.assertTrue(all(evidence_checks.values()))

        duplicate_summary = {
            "postId": "duplicate-C",
            "kind": "evidence",
            "content": "C 已完成",
            "publicationSource": {"kind": "room_post"},
        }
        terminal_posts["C"].insert(0, duplicate_summary)
        duplicate_checks = CANARY.natural_public_post_checks(
            [*public_posts, independent_evidence, duplicate_summary],
            posts_by_member=terminal_posts,
            timeline_truncated=False,
        )
        self.assertFalse(
            duplicate_checks["terminalSummaryNotDoublePosted"]
        )

    def test_workflow_timeout_is_distinct_from_one_provider_turn(self) -> None:
        self.assertEqual(
            CANARY.workflow_timeout_seconds(
                SimpleNamespace(turn_timeout=300, workflow_timeout=None)
            ),
            900,
        )
        self.assertEqual(
            CANARY.workflow_timeout_seconds(
                SimpleNamespace(turn_timeout=300, workflow_timeout=480)
            ),
            480,
        )
        with self.assertRaisesRegex(ValueError, "must be positive"):
            CANARY.workflow_timeout_seconds(
                SimpleNamespace(turn_timeout=300, workflow_timeout=0)
            )

    def test_natural_request_does_not_disclose_execution_script(self) -> None:
        request = CANARY.collaboration_request(
            CANARY.NATURAL_REQUEST_STYLE,
            a_name="实现伙伴",
            b_name="复核伙伴",
            c_name="验收伙伴",
            workspace=Path("/private/tmp/project"),
        )

        self.assertEqual(request.style, "natural")
        self.assertEqual(CANARY.natural_request_leaks(request), [])
        self.assertIn("自行选择能力和执行方法", request.message)
        self.assertNotIn("calculator.py", request.model_visible_text())
        self.assertNotIn("test_calculator.py", request.model_visible_text())

    def test_natural_request_leak_guard_detects_tool_contract_terms(self) -> None:
        request = CANARY.CollaborationRequest(
            style="natural",
            objective="修复项目",
            expected_output="测试通过",
            acceptance_criteria=("调用 workspace_read",),
            message="然后 room_commit",
        )

        self.assertEqual(
            CANARY.natural_request_leaks(request),
            ["room_commit", "workspace_read"],
        )

    def test_quiescence_waits_only_for_target_sessions(self) -> None:
        statuses = iter(
            [
                {
                    "status": "busy",
                    "activeSessionIds": [
                        "session-A",
                        "session-unrelated",
                    ],
                },
                {
                    "status": "busy",
                    "activeSessionIds": ["session-unrelated"],
                },
            ]
        )

        result = CANARY.wait_for_sessions_quiescent(
            "http://127.0.0.1:8768",
            requester=lambda *_args, **_kwargs: next(statuses),
            session_ids=["session-A", "session-B"],
            timeout=1,
            poll_interval=0.001,
        )

        self.assertTrue(result["passed"])
        self.assertEqual(result["pollCount"], 2)
        self.assertEqual(result["remainingTargetSessionIds"], [])
        self.assertEqual(result["runtimeStatus"], "busy")

    def test_settlement_waits_while_root_is_waiting_on_running_children(
        self,
    ) -> None:
        snapshots = iter(
            [
                self._kernel_snapshot(
                    root_state="waiting",
                    dispatch_states=("committed", "running", "running"),
                ),
                self._kernel_snapshot(
                    root_state="waiting",
                    dispatch_states=("committed", "committed", "committed"),
                ),
            ]
        )

        def requester(
            _base_url: str,
            method: str,
            path: str,
            **_kwargs: object,
        ) -> dict[str, object]:
            self.assertEqual(method, "GET")
            if path.startswith("/api/agent/approvals"):
                return {"items": []}
            self.assertIn("/kernel/snapshot", path)
            return next(snapshots)

        result = CANARY.wait_for_three_member_settlement(
            "http://in-process.invalid",
            "room-1",
            "root-1",
            requester=requester,
            sessions={"A": "session-a", "B": "session-b", "C": "session-c"},
            timeout=1,
        )

        self.assertEqual(
            result["dispatchStates"],
            ["committed", "committed", "committed"],
        )

    def test_quiescence_times_out_when_target_session_stays_busy(
        self,
    ) -> None:
        with self.assertRaisesRegex(
            TimeoutError,
            "target Pi sessions did not settle",
        ):
            CANARY.wait_for_sessions_quiescent(
                "http://127.0.0.1:8768",
                requester=lambda *_args, **_kwargs: {
                    "status": "busy",
                    "activeSessionIds": [
                        "session-A",
                        "session-unrelated",
                    ],
                },
                session_ids=["session-A"],
                timeout=0.01,
                poll_interval=0.001,
            )

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

    def test_bounded_rag_allows_zero_hit_member_but_rejects_placeholder(self) -> None:
        useful = (
            "代码任务先做最小改动，运行真实测试，并以证据完成交付。"
        )
        contexts = {
            "A": {
                "sessionMemory": {
                    "blockCount": 1,
                    "blocks": [useful],
                    "forbiddenMetadata": [],
                }
            },
            "B": {
                "sessionMemory": {
                    "blockCount": 0,
                    "blocks": [],
                    "forbiddenMetadata": [],
                }
            },
            "C": {
                "sessionMemory": {
                    "blockCount": 1,
                    "blocks": [useful],
                    "forbiddenMetadata": [],
                }
            },
        }

        self.assertTrue(CANARY.bounded_useful_rag_check(contexts))
        contexts["B"]["sessionMemory"] = {
            "blockCount": 1,
            "blocks": ["没有召回到相关记忆。"],
            "forbiddenMetadata": [],
        }
        self.assertFalse(CANARY.bounded_useful_rag_check(contexts))

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

    def test_compaction_expects_each_current_tasks_exact_acceptance_set(self) -> None:
        tasks = [
            self._task(
                "t1",
                None,
                "pa",
                acceptance_criterion_ids=[f"criterion-{index}" for index in range(6)],
            ),
            self._task(
                "t2",
                "t1",
                "pb",
                acceptance_criterion_ids=["criterion-3"],
            ),
            self._task(
                "t3",
                "t1",
                "pc",
                acceptance_criterion_ids=[
                    f"criterion-{index}" for index in range(6)
                ],
            ),
        ]
        dispatches = [
            self._dispatch("d1", "t1", None, 0, 0, "execute", "pa", "sa"),
            self._dispatch("d2", "t2", "d1", 1, 1, "review", "pb", "sb"),
            self._dispatch("d3", "t3", "d1", 1, 0, "close", "pc", "sc"),
        ]

        self.assertEqual(
            CANARY.task_acceptance_counts(tasks, dispatches),
            {"A": 6, "B": 1, "C": 6},
        )

    def test_tool_workload_requires_parallel_review_and_formal_handoff(self) -> None:
        receipts = {
            "A": self._tool_set(
                room_state=["applied"],
                room_collaborate=["applied"],
                workspace_list=["applied"],
                workspace_search=["applied"],
                workspace_read=["failed", "applied", "applied", "applied"],
                workspace_patch=["failed", "applied"],
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
        receipts["B"]["room_collaborate"] = self._receipt(["failed"])
        self.assertFalse(
            CANARY.tool_workload_checks(receipts)[
                "bDidNotDelegateItsOwnReview"
            ]
        )

    def test_tool_workload_rejects_unbounded_executor_retries(self) -> None:
        receipts = {
            "A": self._tool_set(
                room_state=["applied"],
                room_collaborate=["applied"],
                workspace_list=["applied"],
                workspace_search=["applied"],
                workspace_read=[
                    "failed",
                    "applied",
                    "applied",
                    "applied",
                    "applied",
                ],
                workspace_patch=["failed", "failed", "applied"],
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
                room_commit=["applied"],
            ),
        }

        checks = CANARY.tool_workload_checks(receipts)

        self.assertFalse(checks["aReadFailureRecoveredWithoutLoop"])
        self.assertFalse(checks["aPatchAppliedOnceWithBoundedRepair"])

    def test_tool_workload_accepts_one_settlement_repair_then_delivery(self) -> None:
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
                room_commit=["", "applied"],
            ),
            "C": self._tool_set(
                room_state=["applied", "applied"],
                workspace_read=["applied", "applied"],
                workspace_shell=["applied"],
                room_post=["applied"],
                room_commit=["", "applied"],
            ),
        }

        checks = CANARY.tool_workload_checks(receipts)

        self.assertTrue(all(checks.values()))
        receipts["B"]["room_commit"] = self._receipt(["", "", "applied"])
        self.assertTrue(
            CANARY.tool_workload_checks(receipts)[
                "bCommitValidationPathBounded"
            ]
        )
        receipts["B"]["room_commit"] = self._receipt(["", "applied"])
        receipts["C"]["room_commit"] = self._receipt(
            ["", "", "", "applied"]
        )
        self.assertFalse(
            CANARY.tool_workload_checks(receipts)[
                "cCommitValidationPathBounded"
            ]
        )

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

    def test_natural_approval_checks_accept_discovery_and_distinct_failures(
        self,
    ) -> None:
        approvals = {
            "A": [
                self._approval(
                    "workspace_shell",
                    "applied",
                    1,
                    command='rg -n "normalize" .',
                ),
                self._approval(
                    "workspace_shell",
                    "failed",
                    2,
                    command=CANARY.TEST_COMMAND,
                ),
                self._approval("workspace_patch", "applied", 3),
                self._approval(
                    "workspace_shell",
                    "failed",
                    4,
                    command="git status --short",
                ),
                self._approval(
                    "workspace_shell",
                    "applied",
                    5,
                    command=CANARY.TEST_COMMAND,
                ),
            ],
            "B": [],
            "C": [
                self._approval(
                    "workspace_shell",
                    "applied",
                    6,
                    command=CANARY.TEST_COMMAND,
                )
            ],
        }

        self.assertTrue(
            all(CANARY.natural_managed_approval_checks(approvals).values())
        )
        approvals["A"][3]["receipt"].pop("networkAllowed")
        self.assertTrue(
            CANARY.natural_managed_approval_checks(approvals)[
                "shellNetworkDenied"
            ]
        )
        approvals["C"][0]["receipt"]["networkAllowed"] = True
        self.assertFalse(
            CANARY.natural_managed_approval_checks(approvals)[
                "shellNetworkDenied"
            ]
        )
        approvals["C"][0]["receipt"]["networkAllowed"] = False
        approvals["A"].append(
            self._approval(
                "workspace_shell",
                "failed",
                7,
                command="apply_patch <<'PATCH'\nPATCH",
            )
        )
        self.assertFalse(
            CANARY.natural_managed_approval_checks(approvals)[
                "noShellPatchWrapper"
            ]
        )
        approvals["A"].pop()
        approvals["A"].append(
            self._approval(
                "workspace_shell",
                "applied",
                8,
                command="sleep 2",
            )
        )
        self.assertFalse(
            CANARY.natural_managed_approval_checks(approvals)[
                "noStandaloneSleepPolling"
            ]
        )

    def test_natural_tool_workload_checks_outcomes_not_scripted_discovery(
        self,
    ) -> None:
        receipts = {
            "A": self._tool_set(
                room_state=["applied"],
                room_collaborate=["applied"],
                workspace_read=["applied", "applied"],
                workspace_patch=["applied"],
                workspace_shell=["applied", "failed", "applied"],
                room_commit=["applied"],
            ),
            "B": self._tool_set(
                room_state=["applied"],
                workspace_read=["applied", "applied"],
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
        approvals = {
            "A": [
                self._approval(
                    "workspace_shell",
                    "failed",
                    1,
                    command=CANARY.TEST_COMMAND,
                ),
                self._approval("workspace_patch", "applied", 2),
                self._approval(
                    "workspace_shell",
                    "applied",
                    3,
                    command=CANARY.TEST_COMMAND,
                ),
            ],
            "B": [],
            "C": [
                self._approval(
                    "workspace_shell",
                    "applied",
                    4,
                    command=CANARY.TEST_COMMAND,
                )
            ],
        }

        checks = CANARY.natural_tool_workload_checks(
            receipts,
            approvals=approvals,
            repeated_failed_commands=[],
        )

        self.assertTrue(all(checks.values()))
        checks = CANARY.natural_tool_workload_checks(
            receipts,
            approvals=approvals,
            repeated_failed_commands=[
                {
                    "member": "A",
                    "toolName": "workspace_shell",
                    "commandHash": "same",
                    "count": 2,
                }
            ],
        )
        self.assertFalse(checks["noRepeatedFailedToolLoop"])

    def test_agent_window_continuity_uses_same_session_turn_not_copied_posts(
        self,
    ) -> None:
        request = CANARY.collaboration_request(
            CANARY.NATURAL_REQUEST_STYLE,
            a_name="实现伙伴",
            b_name="复核伙伴",
            c_name="验收伙伴",
            workspace=Path("/private/tmp/project"),
        )
        snapshot = {
            "items": [
                {
                    "role": "assistant",
                    "blocks": [
                        {
                            "type": "text",
                            "data": {"text": "已交接最终验收。"},
                        }
                    ],
                },
            ]
        }

        self.assertTrue(
            CANARY._room_session_turn_visible(snapshot, request)
        )
        self.assertNotIn(request.message, json.dumps(snapshot, ensure_ascii=False))
        self.assertNotIn("最终验收结论", json.dumps(snapshot, ensure_ascii=False))

    def test_repeated_failed_invocations_group_by_exact_command_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "failed-replays.sqlite"
            with sqlite3.connect(database) as connection:
                connection.executescript(
                    """
                    CREATE TABLE room_v2_capability_manifests(
                        manifest_id TEXT PRIMARY KEY,
                        manifest_hash TEXT NOT NULL,
                        dispatch_id TEXT NOT NULL
                    );
                    CREATE TABLE room_v2_capability_runtime_bindings(
                        manifest_id TEXT NOT NULL,
                        session_id TEXT NOT NULL
                    );
                    CREATE TABLE room_v2_tool_invocation_receipts(
                        receipt_id TEXT PRIMARY KEY,
                        manifest_id TEXT NOT NULL,
                        manifest_hash TEXT NOT NULL,
                        canonical_tool_name TEXT NOT NULL,
                        command_hash TEXT NOT NULL
                    );
                    CREATE TABLE room_v2_tool_execution_receipts(
                        invocation_receipt_id TEXT NOT NULL,
                        status TEXT NOT NULL
                    );
                    """
                )
                for member in ("A", "B", "C"):
                    connection.execute(
                        "INSERT INTO room_v2_capability_manifests VALUES (?, ?, ?)",
                        (f"manifest-{member}", "hash", f"dispatch-{member}"),
                    )
                    connection.execute(
                        "INSERT INTO room_v2_capability_runtime_bindings VALUES (?, ?)",
                        (f"manifest-{member}", f"session-{member}"),
                    )
                for receipt_id, command_hash in (
                    ("invoke-a-1", "same-command"),
                    ("invoke-a-2", "same-command"),
                    ("invoke-a-3", "different-command"),
                ):
                    connection.execute(
                        "INSERT INTO room_v2_tool_invocation_receipts "
                        "VALUES (?, 'manifest-A', 'hash', 'workspace_shell', ?)",
                        (receipt_id, command_hash),
                    )
                    connection.execute(
                        "INSERT INTO room_v2_tool_execution_receipts VALUES (?, 'failed')",
                        (receipt_id,),
                    )

            repeated = CANARY.repeated_failed_invocation_commands(
                database,
                session_ids={
                    member: f"session-{member}" for member in ("A", "B", "C")
                },
                dispatches=[
                    {"dispatchId": f"dispatch-{member}"}
                    for member in ("A", "B", "C")
                ],
            )

        self.assertEqual(
            repeated,
            [
                {
                    "member": "A",
                    "toolName": "workspace_shell",
                    "commandHash": "same-command",
                    "count": 2,
                }
            ],
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
            leaked_result = {
                "type": "message",
                "message": {
                    "role": "toolResult",
                    "toolCallId": "tool-A",
                    "toolName": "workspace_read",
                    "content": [{"type": "text", "text": "private result leaked"}],
                },
            }
            b_path.write_text(
                "\n".join((json.dumps(b_payload), json.dumps(leaked_result))) + "\n",
                encoding="utf-8",
            )
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
                    {
                        "receiptId": "load-B-used",
                        "toolName": "room_state",
                        "createdAtMs": 2,
                    },
                    {
                        "receiptId": "load-B-unused",
                        "toolName": "room_collaborate",
                        "createdAtMs": 20,
                    },
                ],
            )

    def test_effective_tool_receipts_keep_latest_model_visible_schema_only(
        self,
    ) -> None:
        loaded = [
            {"receiptId": "bootstrap-state", "toolName": "room_state"},
            {"receiptId": "bootstrap-memory", "toolName": "ime_memory"},
            {"receiptId": "rebind-state", "toolName": "room_state"},
            {"receiptId": "load-read", "toolName": "workspace_read"},
            {"receiptId": "load-hidden", "toolName": "workspace_shell"},
        ]

        effective = CANARY._effective_loaded_tool_receipts(
            loaded,
            {"room_state", "workspace_read"},
        )

        self.assertEqual(
            effective,
            [
                {"receiptId": "rebind-state", "toolName": "room_state"},
                {"receiptId": "load-read", "toolName": "workspace_read"},
            ],
        )

    def test_quality_gate_commit_evidence_binds_receipts_and_evidence(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "quality.sqlite"
            tasks = [
                self._task(
                    f"task-{member}",
                    None,
                    f"participant-{member}",
                    acceptance_criterion_ids=(
                        [] if member == "B" else [f"criterion-{member}"]
                    ),
                )
                for member in ("A", "B", "C")
            ]
            dispatches = [
                {
                    **self._dispatch(
                        f"dispatch-{member}",
                        f"task-{member}",
                        None,
                        index,
                        0,
                        "execute",
                        f"participant-{member}",
                        f"session-{member}",
                    ),
                    "rootId": "root-1",
                    "generation": 0,
                }
                for index, member in enumerate(("A", "B", "C"))
            ]
            with sqlite3.connect(database) as connection:
                connection.executescript(
                    """
                    CREATE TABLE room_kernel_commits(
                        dispatch_id TEXT PRIMARY KEY,
                        payload_json TEXT NOT NULL
                    );
                    CREATE TABLE room_kernel_settle_attempt_receipts(
                        settle_receipt_id TEXT PRIMARY KEY,
                        dispatch_id TEXT NOT NULL,
                        kernel_receipt_json TEXT NOT NULL,
                        created_at_ms INTEGER NOT NULL
                    );
                    """
                )
                for member in ("A", "B", "C"):
                    criterion_ids = (
                        [] if member == "B" else [f"criterion-{member}"]
                    )
                    evidence_refs = (
                        [] if member == "B" else [f"evidence-{member}"]
                    )
                    payload = {
                        "schemaVersion": "wisdom-weasel.room-commit.v3",
                        "dispatchId": f"dispatch-{member}",
                        "continuation": {"decision": "complete"},
                        "evidenceRefs": evidence_refs,
                        "requirementCoverage": criterion_ids,
                        "qualityGateReceipt": {
                            "schemaVersion": (
                                "wisdom-weasel.room-quality-gate-receipt.v1"
                            ),
                            "receiptId": f"quality-{member}",
                            "rootId": "root-1",
                            "taskId": f"task-{member}",
                            "dispatchId": f"dispatch-{member}",
                            "generation": 0,
                            "originalRequestChecked": True,
                            "verdict": "ready_to_deliver",
                            "items": [
                                {
                                    "criterionId": criterion_id,
                                    "status": "pass",
                                    "evidenceRefs": evidence_refs,
                                }
                                for criterion_id in criterion_ids
                            ],
                        },
                    }
                    connection.execute(
                        "INSERT INTO room_kernel_commits VALUES (?, ?)",
                        (
                            f"dispatch-{member}",
                            json.dumps(payload),
                        ),
                    )

            valid = CANARY.quality_gate_commit_evidence(
                database,
                tasks=tasks,
                dispatches=dispatches,
            )
            self.assertTrue(valid["passed"])

            with sqlite3.connect(database) as connection:
                payload = json.loads(
                    connection.execute(
                        "SELECT payload_json FROM room_kernel_commits "
                        "WHERE dispatch_id = 'dispatch-C'"
                    ).fetchone()[0]
                )
                original_items = list(
                    payload["qualityGateReceipt"]["items"]
                )
                payload["qualityGateReceipt"]["items"] = [
                    *original_items,
                    dict(original_items[0]),
                ]
                connection.execute(
                    "UPDATE room_kernel_commits SET payload_json = ? "
                    "WHERE dispatch_id = 'dispatch-C'",
                    (json.dumps(payload),),
                )

            duplicate = CANARY.quality_gate_commit_evidence(
                database,
                tasks=tasks,
                dispatches=dispatches,
            )
            self.assertFalse(duplicate["passed"])
            self.assertFalse(
                duplicate["members"]["C"]["checks"][
                    "criterionCoverageExact"
                ]
            )

            with sqlite3.connect(database) as connection:
                payload["qualityGateReceipt"]["items"] = original_items
                payload["evidenceRefs"] = []
                connection.execute(
                    "UPDATE room_kernel_commits SET payload_json = ? "
                    "WHERE dispatch_id = 'dispatch-C'",
                    (json.dumps(payload),),
                )

            invalid = CANARY.quality_gate_commit_evidence(
                database,
                tasks=tasks,
                dispatches=dispatches,
            )
            self.assertFalse(invalid["passed"])
            self.assertFalse(
                invalid["members"]["C"]["checks"][
                    "passEvidenceCommitted"
                ]
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
        acceptance_criterion_ids: list[str] | None = None,
    ) -> dict[str, object]:
        return {
            "taskId": task_id,
            "parentTaskId": parent_id,
            "ownerParticipantId": owner_participant_id or participant_id,
            "assigneeParticipantId": participant_id,
            "acceptanceCriterionIds": acceptance_criterion_ids or [],
            "state": "completed",
        }

    @staticmethod
    def _kernel_snapshot(
        *,
        root_state: str,
        dispatch_states: tuple[str, str, str],
    ) -> dict[str, object]:
        return {
            "roots": [{"rootId": "root-1", "state": root_state}],
            "tasks": [
                {"rootId": "root-1", "taskId": f"task-{index}"}
                for index in range(1, 4)
            ],
            "dispatches": [
                {
                    "rootId": "root-1",
                    "taskId": f"task-{index}",
                    "dispatchId": f"dispatch-{index}",
                    "hopCount": 0 if index == 1 else 1,
                    "state": state,
                }
                for index, state in enumerate(dispatch_states, start=1)
            ],
        }

    @staticmethod
    def _receipt(statuses: list[str]) -> dict[str, object]:
        return {
            "invocationCount": len(statuses),
            "appliedExecutionCount": statuses.count("applied"),
            "loadReceiptIds": ["load:one"] if statuses else [],
            "items": [{"status": status} for status in statuses],
        }

    @staticmethod
    def _approval(
        tool: str,
        state: str,
        requested_at_ms: int,
        *,
        command: str = "",
        network_allowed: bool = False,
    ) -> dict[str, object]:
        return {
            "approvalId": f"approval:{requested_at_ms}",
            "toolId": tool,
            "state": state,
            "requestedAtMs": requested_at_ms,
            "decidedBy": "execution-policy:workspace_managed",
            "preview": {
                "actionPayload": {
                    "command": command,
                }
            },
            "receipt": {
                "summary": "done",
                "networkAllowed": network_allowed,
            },
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
