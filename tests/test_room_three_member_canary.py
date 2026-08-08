from __future__ import annotations

import hashlib
import importlib.util
import sys
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


ROOT_ID = "room-root:1"
TASK_ID = "room-task:1"
PARTICIPANTS = {"A": "participant-a", "B": "participant-b", "C": "participant-c"}
SESSIONS = {"A": "session-a", "B": "session-b", "C": "session-c"}


def anchor(text: str) -> dict[str, object]:
    return {
        "rootId": ROOT_ID,
        "originalText": text,
        "originalContentSha256": hashlib.sha256(text.encode()).hexdigest(),
        "originalByteLength": len(text.encode()),
        "integrityStatus": "verified",
    }


def base_snapshot() -> dict[str, object]:
    return {
        "roots": [{"rootId": ROOT_ID, "facilitatorParticipantId": PARTICIPANTS["A"], "reporterParticipantId": PARTICIPANTS["A"]}],
        "tasks": [{"rootId": ROOT_ID, "taskId": TASK_ID}],
        "dispatches": [{
            "rootId": ROOT_ID,
            "taskId": TASK_ID,
            "dispatchId": "dispatch-align",
            "intentKind": "align",
            "targetParticipantId": PARTICIPANTS["A"],
            "targetSessionId": SESSIONS["A"],
        }],
        "requirementsByRootId": {ROOT_ID: {"anchors": [anchor(CANARY.OPENING_MESSAGE)]}},
        "posts": [],
    }


class RoomThreeMemberCanaryTest(unittest.TestCase):
    def test_exact_opening_preservation_and_no_initial_fanout(self) -> None:
        accepted = {
            "post": {"content": CANARY.OPENING_MESSAGE},
            "requirementAnchor": anchor(CANARY.OPENING_MESSAGE),
            "taskId": TASK_ID,
            "alignmentDispatches": [base_snapshot()["dispatches"][0]],
        }
        checks = CANARY.initial_intake_checks(
            accepted,
            base_snapshot(),
            root_id=ROOT_ID,
            task_id=TASK_ID,
            opening=CANARY.OPENING_MESSAGE,
            facilitator_id=PARTICIPANTS["A"],
            work_items=[],
        )
        self.assertTrue(all(checks.values()), checks)
        self.assertEqual(CANARY.OPENING_MESSAGE, "写 TUI")

    def test_wait_question_requires_structured_options(self) -> None:
        snapshot = base_snapshot()
        post = {
            "postId": "post:wait",
            "rootId": ROOT_ID,
            "taskId": TASK_ID,
            "dispatchId": "dispatch-align",
            "kind": "wait",
            "publicationSource": {
                "kind": "room_commit",
                "ref": "commit:wait",
            },
            "question": {
                "prompt": "这个 TUI 要做什么？",
                "options": [
                    {"value": "terminal", "label": "终端原生 TUI"},
                    {"value": "control", "label": "控制中心界面"},
                ],
            },
        }
        snapshot["posts"] = [post]

        found = CANARY._find_wait_post(
            snapshot,
            root_id=ROOT_ID,
            seen_post_ids=set(),
        )

        self.assertEqual(found, post)
        checks = CANARY.authoritative_wait_post_checks(
            post,
            snapshot["dispatches"][0],
            root_id=ROOT_ID,
            task_id=TASK_ID,
        )
        self.assertTrue(all(checks.values()), checks)
        post["question"]["options"] = [{"value": "only", "label": "只有一项"}]
        self.assertIsNone(
            CANARY._find_wait_post(
                snapshot,
                root_id=ROOT_ID,
                seen_post_ids=set(),
            )
        )

    def test_clarification_answer_binds_the_exact_question_and_root(self) -> None:
        self.assertEqual(
            CANARY.clarification_answer_body(
                answer="终端原生 TUI",
                stamp=20260804,
                index=1,
                post={"postId": "post:wait-2"},
                root_id="root:tui",
            ),
            {
                "message": "终端原生 TUI",
                "clientMessageId": "room-full-auto-answer:20260804:1",
                "answerKind": "custom",
                "answerToPostId": "post:wait-2",
                "answerToRootId": "root:tui",
            },
        )
        with self.assertRaisesRegex(
            RuntimeError,
            "question Post and Root identity",
        ):
            CANARY.clarification_answer_body(
                answer="终端原生 TUI",
                stamp=20260804,
                index=1,
                post={},
                root_id="root:tui",
            )

    def test_initial_execution_fanout_or_work_item_fails(self) -> None:
        bad = base_snapshot()
        bad["dispatches"].append({"rootId": ROOT_ID, "taskId": TASK_ID, "dispatchId": "dispatch-execute", "intentKind": "execute"})
        accepted = {"post": {"content": CANARY.OPENING_MESSAGE}, "requirementAnchor": anchor(CANARY.OPENING_MESSAGE), "taskId": TASK_ID}
        checks = CANARY.initial_intake_checks(
            accepted,
            bad,
            root_id=ROOT_ID,
            task_id=TASK_ID,
            opening=CANARY.OPENING_MESSAGE,
            facilitator_id=PARTICIPANTS["A"],
            work_items=[{"rootTurnId": ROOT_ID}],
        )
        self.assertFalse(checks["noInitialExecutionFanout"])
        self.assertFalse(checks["noWorkItemBeforeDefinition"])

    def test_ordinary_answer_stays_in_root_and_creates_one_resume(self) -> None:
        answer = CANARY.NATURAL_REQUIREMENT_ANSWERS[0]
        before = base_snapshot()
        after = base_snapshot()
        after["dispatches"].append({
            "rootId": ROOT_ID,
            "taskId": TASK_ID,
            "dispatchId": "dispatch-resume",
            "intentKind": "resume",
            "targetParticipantId": PARTICIPANTS["A"],
            "targetSessionId": SESSIONS["A"],
        })
        after["requirementsByRootId"][ROOT_ID]["anchors"].append(anchor(answer))
        after["posts"].append({"rootId": ROOT_ID, "content": answer, "publicationSource": {"kind": "user"}})
        response = {"accepted": True, "rootId": ROOT_ID, "taskId": TASK_ID}
        checks = CANARY.clarification_transition_checks(
            before,
            response,
            after,
            root_id=ROOT_ID,
            task_id=TASK_ID,
            waiting_dispatch=before["dispatches"][0],
            answer=answer,
            work_items_before=[],
            work_items_after=[],
        )
        self.assertTrue(all(checks.values()), checks)
        defined_checks = CANARY.clarification_transition_checks(
            before,
            response,
            after,
            root_id=ROOT_ID,
            task_id=TASK_ID,
            waiting_dispatch=before["dispatches"][0],
            answer=answer,
            work_items_before=[],
            work_items_after=[{"rootTurnId": ROOT_ID}],
            definition_applied=True,
        )
        self.assertTrue(all(defined_checks.values()), defined_checks)

    def test_definition_requires_nonempty_criteria_aliases_and_one_root_work_item(self) -> None:
        criteria = [
            {"criterionId": "criterion:2", "expectedReceiptTypes": ["evidence"]},
            {"criterionId": "criterion:1", "expectedReceiptTypes": ["evidence"]},
        ]
        projection = {
            "catalog": {
                "revision": 2,
                "items": [{"origin": "room_define", "statement": "标题和输入区可用"}],
                "acceptanceCriteria": criteria,
                "acceptanceAliases": {"AC-1": "criterion:1", "AC-2": "criterion:2"},
            }
        }
        work = [{"id": "room-work:1", "rootTurnId": ROOT_ID, "rootWorkId": "room-work:1", "accountableParticipantId": PARTICIPANTS["A"], "createdByParticipantId": PARTICIPANTS["A"]}]
        receipt = [{"toolName": "room_define", "status": "applied", "acceptanceAliases": {"AC-1": "criterion:1", "AC-2": "criterion:2"}}]
        checks = CANARY.definition_checks(projection, work, receipt, root_id=ROOT_ID, facilitator_id=PARTICIPANTS["A"], implementation_id=PARTICIPANTS["B"])
        self.assertTrue(all(checks.values()), checks)
        empty = dict(projection)
        empty["catalog"] = dict(projection["catalog"])
        empty["catalog"]["acceptanceCriteria"] = []
        self.assertFalse(CANARY.definition_checks(empty, work, receipt, root_id=ROOT_ID, facilitator_id=PARTICIPANTS["A"], implementation_id=PARTICIPANTS["B"])["acceptanceCriteriaNonEmpty"])
        self.assertFalse(CANARY._catalog_is_defined({
            "revision": 4,
            "items": [{"origin": "room_user_answer", "statement": "仍在澄清"}],
            "acceptanceCriteria": criteria,
        }))
        self.assertTrue(CANARY._catalog_is_defined(projection["catalog"]))
        merged_receipts = CANARY._definition_receipts(
            [{"toolName": "room_define", "status": "", "invocationReceiptId": "invoke:define"}],
            [{
                "status": "applied",
                "details": {
                    "operation": "room_define",
                    "invocationReceiptId": "invoke:define",
                    "acceptanceAliases": {"AC-1": "criterion:1"},
                },
            }],
        )
        self.assertEqual(len(merged_receipts), 1)
        self.assertEqual(merged_receipts[0]["status"], "applied")

    def test_typed_start_is_the_only_execution_boundary(self) -> None:
        defined = base_snapshot()
        defined["roots"][0]["state"] = "running"
        pre_start = CANARY.pre_start_execution_checks(
            defined,
            [{"toolName": "room_define", "status": "applied"}],
            root_id=ROOT_ID,
        )
        self.assertTrue(all(pre_start.values()), pre_start)
        defined["dispatches"].append(
            {
                "rootId": ROOT_ID,
                "taskId": TASK_ID,
                "dispatchId": "dispatch-execute",
                "intentKind": "execute",
            }
        )
        self.assertFalse(
            CANARY.pre_start_execution_checks(
                defined,
                [],
                root_id=ROOT_ID,
            )["noReleasedExecutionBeforeTypedStart"]
        )
        payload = CANARY.typed_start_body(root_id=ROOT_ID, stamp=20260808)
        self.assertEqual(
            payload,
            {
                "action": "start_execution",
                "rootId": ROOT_ID,
                "clientActionId": "room-full-auto-start:20260808",
            },
        )
        accepted = {
            "ok": True,
            "accepted": True,
            "rootId": ROOT_ID,
            "post": {
                "content": "开始行动",
                "publicationSource": {
                    "kind": "user",
                    "ref": payload["clientActionId"],
                },
            },
            "dispatches": [{"phase": "execution"}],
        }
        checks = CANARY.typed_start_checks(
            accepted,
            root_id=ROOT_ID,
            client_action_id=payload["clientActionId"],
        )
        self.assertTrue(all(checks.values()), checks)

    def test_planned_feature_integration_review_and_report_lifecycle(self) -> None:
        dispatches = [
            {"dispatchId": "d-align", "rootId": ROOT_ID, "taskId": TASK_ID, "intentKind": "align", "targetParticipantId": PARTICIPANTS["A"], "targetSessionId": SESSIONS["A"], "hopCount": 0, "depth": 0},
            {"dispatchId": "d-impl", "rootId": ROOT_ID, "taskId": "task-feature", "intentKind": "execute", "targetParticipantId": PARTICIPANTS["B"], "targetSessionId": SESSIONS["B"]},
            {"dispatchId": "d-integration", "rootId": ROOT_ID, "taskId": "task-integration", "intentKind": "execute", "targetParticipantId": PARTICIPANTS["A"], "targetSessionId": SESSIONS["A"]},
            {"dispatchId": "d-review", "rootId": ROOT_ID, "taskId": "task-review", "intentKind": "review", "targetParticipantId": PARTICIPANTS["C"], "targetSessionId": SESSIONS["C"]},
            {"dispatchId": "d-report", "rootId": ROOT_ID, "taskId": "task-report", "intentKind": "close", "targetParticipantId": PARTICIPANTS["A"], "targetSessionId": SESSIONS["A"]},
        ]
        tasks = [
            {"taskId": TASK_ID, "rootId": ROOT_ID, "currentOwnerParticipantId": PARTICIPANTS["A"]},
            {"taskId": "task-feature", "rootId": ROOT_ID, "parentTaskId": TASK_ID, "taskKind": "work", "planTaskKind": "feature", "planWave": 1},
            {"taskId": "task-integration", "rootId": ROOT_ID, "parentTaskId": TASK_ID, "taskKind": "integration", "planTaskKind": "integration", "planWave": 2},
            {"taskId": "task-review", "rootId": ROOT_ID, "parentTaskId": TASK_ID, "taskKind": "review", "planTaskKind": "review", "planWave": 3, "reviewOfTaskIds": ["task-feature", "task-integration"], "reviewAuthorParticipantIds": [PARTICIPANTS["A"], PARTICIPANTS["B"]], "currentOwnerParticipantId": PARTICIPANTS["C"], "reviewState": "accepted"},
            {"taskId": "task-report", "rootId": ROOT_ID, "taskKind": "report", "currentOwnerParticipantId": PARTICIPANTS["A"]},
        ]
        checks = CANARY.dispatch_lifecycle_checks(tasks, dispatches, participant_ids=PARTICIPANTS, session_ids=SESSIONS)
        self.assertTrue(all(checks.values()), checks)
        self.assertTrue(checks["exactlyOnePlannedImplementationFeature"])
        self.assertTrue(checks["reviewIsDistinctPlannedOwnership"])
        self.assertEqual(
            CANARY._reviewed_task_ids(
                tasks,
                dispatches,
                reviewer_id=PARTICIPANTS["C"],
            ),
            ("task-feature", "task-integration"),
        )

    def test_reviewer_evidence_gates_reporter_delivery_and_summary(self) -> None:
        dispatches = {
            "d-impl": {"taskId": "task-feature", "intentKind": "execute", "targetParticipantId": PARTICIPANTS["B"]},
            "d-integration": {"taskId": "task-integration", "intentKind": "execute", "targetParticipantId": PARTICIPANTS["A"]},
            "d-review": {"taskId": "task-review", "intentKind": "review", "targetParticipantId": PARTICIPANTS["C"]},
            "d-report": {"taskId": "task-report", "intentKind": "close", "targetParticipantId": PARTICIPANTS["A"]},
        }
        commits = [
            {
                "dispatchId": "d-impl",
                "decision": "deliver",
                "evidenceRefs": ["evidence-implementation"],
                "qualityGateReceipt": {"verdict": "ready_to_deliver"},
            },
            {
                "dispatchId": "d-integration",
                "decision": "deliver",
                "evidenceRefs": ["evidence-integrated"],
                "qualityGateReceipt": {"verdict": "ready_to_deliver"},
            },
            {
                "dispatchId": "d-review",
                "decision": "deliver",
                "evidenceRefs": ["evidence-review"],
                "qualityGateReceipt": {"verdict": "ready_to_deliver"},
                "reviewEvidenceBinding": {
                    "taskId": "task-review",
                    "reviewTargetRevision": "sha256:reviewed",
                },
            },
            {
                "dispatchId": "d-report",
                "decision": "deliver",
                "evidenceRefs": ["evidence-review"],
                "qualityGateReceipt": {"verdict": "ready_to_deliver"},
            },
        ]
        checks = CANARY.review_delivery_checks(
            commits,
            reviewer_id=PARTICIPANTS["C"],
            facilitator_id=PARTICIPANTS["A"],
            reviewed_task_ids=["task-feature", "task-integration"],
            dispatches=dispatches,
        )
        self.assertTrue(all(checks.values()), checks)
        bad_dispatches = dict(dispatches)
        bad_dispatches["d-review"] = {
            **bad_dispatches["d-review"],
            "targetParticipantId": PARTICIPANTS["B"],
        }
        self.assertFalse(
            CANARY.review_delivery_checks(
                commits,
                reviewer_id=PARTICIPANTS["C"],
                facilitator_id=PARTICIPANTS["A"],
                reviewed_task_ids=["task-feature", "task-integration"],
                dispatches=bad_dispatches,
            )["exactlyOneReviewerRecommendation"]
        )
        public = [{"rootId": ROOT_ID, "kind": "result", "content": "最终汇总", "authorActorRef": PARTICIPANTS["A"], "publicationSource": {"kind": "room_commit", "ref": "terminal-1"}}]
        terminal = CANARY.reporter_terminal_summary_checks(public, reporter_id=PARTICIPANTS["A"], root_id=ROOT_ID, terminal_receipt={"receiptId": "terminal-1", "status": "applied", "receiptKind": "terminal"})
        self.assertTrue(all(terminal.values()), terminal)

    def test_terminal_receipt_and_quiescence_are_required(self) -> None:
        good = CANARY.terminal_receipt_checks({"state": "completed", "terminalReceiptId": "terminal-1"}, {"receiptId": "terminal-1", "status": "applied", "receiptKind": "terminal"}, {"passed": True, "remainingTargetSessionIds": []})
        self.assertTrue(all(good.values()), good)
        bad = CANARY.terminal_receipt_checks({"state": "completed"}, {}, {"passed": False, "remainingTargetSessionIds": [SESSIONS["A"]]})
        self.assertFalse(all(bad.values()))
        self.assertTrue(bad["rootCompleted"])
        self.assertFalse(bad["terminalReceiptAccepted"])
        self.assertFalse(bad["rootPointsToTerminalReceipt"])
        self.assertFalse(bad["runtimeQuiescent"])

    def test_configured_provider_model_thinking_and_workspace_scope(self) -> None:
        sessions = {member: {"id": SESSIONS[member], "executionMode": "workspace_managed", "workspaceScopeGranted": True, "workspaceRoots": [str(ROOT)]} for member in CANARY.MEMBERS}
        catalogs = {member: {"selected": {"provider": "configured-provider", "id": "configured-model"}, "thinkingLevel": "high"} for member in CANARY.MEMBERS}
        checks = CANARY.participant_configuration_checks(sessions, catalogs, expected_provider="configured-provider", expected_model="configured-model", expected_thinking="high", workspace=ROOT)
        self.assertTrue(all(checks.values()), checks)
        catalogs["C"]["selected"]["id"] = "wrong-model"
        self.assertFalse(CANARY.participant_configuration_checks(sessions, catalogs, expected_provider="configured-provider", expected_model="configured-model", expected_thinking="high", workspace=ROOT)["CModelMatches"])

    def test_b_and_c_workspace_receipts_are_bound_to_their_dispatches(self) -> None:
        rows = [
            {"toolName": "workspace_read", "dispatchId": "d-b", "sessionId": SESSIONS["B"], "status": "applied", "resultHash": "b" * 64, "command": {"path": "src/app.py"}},
            {"toolName": "workspace_read", "dispatchId": "d-c", "sessionId": SESSIONS["C"], "status": "applied", "resultHash": "c" * 64, "command": {"path": "tests/test_app.py"}},
        ]
        dispatches = {
            "d-b": {"taskId": "task:b", "targetSessionId": SESSIONS["B"]},
            "d-c": {"taskId": "task:c", "targetSessionId": SESSIONS["C"]},
        }
        tasks = [
            {"taskId": "task:b", "workspaceBaseRoot": str(ROOT)},
            {"taskId": "task:c", "workspaceBaseRoot": str(ROOT)},
        ]
        checks = CANARY.workspace_receipt_checks(
            rows,
            dispatches=dispatches,
            tasks=tasks,
            session_ids=SESSIONS,
            workspace=ROOT,
        )
        self.assertTrue(all(checks.values()), checks)
        rows[1]["sessionId"] = SESSIONS["A"]
        self.assertFalse(
            CANARY.workspace_receipt_checks(
                rows,
                dispatches=dispatches,
                tasks=tasks,
                session_ids=SESSIONS,
                workspace=ROOT,
            )["reviewerWorkspaceReceiptObserved"]
        )

    def test_authoritative_reporter_and_resume_receipts_are_required(self) -> None:
        receipts = [
            {
                "rootId": ROOT_ID,
                "receiptId": "reporter-receipt",
                "receiptKind": "accepted",
                "status": "applied",
                "details": {
                    "purpose": "reporter_selection",
                    "reporterParticipantId": PARTICIPANTS["A"],
                },
            },
            {
                "rootId": ROOT_ID,
                "receiptId": "resume-receipt",
                "receiptKind": "accepted",
                "status": "applied",
                "details": {"resumedDispatchId": "dispatch-resume"},
            },
        ]
        checks = CANARY.authoritative_receipt_checks(
            receipts,
            root_id=ROOT_ID,
            reporter_id=PARTICIPANTS["A"],
            resume_receipt_ids=["resume-receipt"],
        )
        self.assertTrue(all(checks.values()), checks)
        self.assertFalse(
            CANARY.authoritative_receipt_checks(
                [receipts[0]],
                root_id=ROOT_ID,
                reporter_id=PARTICIPANTS["A"],
                resume_receipt_ids=["resume-receipt"],
            )["resumeReceiptAccepted"]
        )

    def test_tool_receipts_and_natural_language_guard(self) -> None:
        rows = [{"toolName": name, "dispatchId": f"d-{index}", "status": "applied", "resultHash": "a" * 64} for index, name in enumerate(("room_define", "room_commit"))]
        dispatches = {"d-0": {"intentKind": "resume", "targetParticipantId": PARTICIPANTS["A"]}, "d-1": {"intentKind": "wait", "targetParticipantId": PARTICIPANTS["A"]}}
        checks = CANARY._tool_receipt_checks(rows, dispatches=dispatches, facilitator_id=PARTICIPANTS["A"])
        self.assertTrue(all(checks.values()), checks)
        self.assertEqual([], CANARY.natural_message_leaks([CANARY.OPENING_MESSAGE, *CANARY.NATURAL_REQUIREMENT_ANSWERS]))
        self.assertEqual(["room_define"], CANARY.natural_message_leaks(["please call room_define"]))

    def test_workspace_receipts_use_each_tasks_authoritative_root(self) -> None:
        base = Path("/tmp/base-workspace")
        isolated = Path("/tmp/isolated-worktree")
        dispatches = {
            "dispatch:base": {
                "dispatchId": "dispatch:base",
                "taskId": "task:base",
                "targetSessionId": SESSIONS["A"],
            },
            "dispatch:child": {
                "dispatchId": "dispatch:child",
                "taskId": "task:child",
                "targetSessionId": SESSIONS["B"],
            },
            "dispatch:review": {
                "dispatchId": "dispatch:review",
                "taskId": "task:base",
                "targetSessionId": SESSIONS["C"],
            },
        }
        tasks = [
            {"taskId": "task:base", "workspaceBaseRoot": str(base)},
            {"taskId": "task:child", "workspaceRoot": str(isolated)},
        ]
        rows = [
            {"toolName": "workspace_read", "dispatchId": "dispatch:base", "sessionId": SESSIONS["A"], "status": "applied", "resultHash": "a" * 64, "command": {"path": "README.md"}},
            {"toolName": "workspace_edit", "dispatchId": "dispatch:child", "sessionId": SESSIONS["B"], "status": "applied", "resultHash": "b" * 64, "command": {"path": str(isolated / "calculator.py")}},
            {"toolName": "workspace_read", "dispatchId": "dispatch:review", "sessionId": SESSIONS["C"], "status": "applied", "resultHash": "c" * 64, "command": {"path": "calculator.py"}},
        ]

        checks = CANARY.workspace_receipt_checks(
            rows,
            dispatches=dispatches,
            tasks=tasks,
            session_ids=SESSIONS,
            workspace=base,
        )

        self.assertTrue(all(checks.values()), checks)

    def test_runtime_quiescence_uses_canonical_agent_runtime_route(self) -> None:
        requests: list[tuple[str, str]] = []

        def requester(
            _base_url: str,
            method: str,
            path: str,
            **_kwargs: object,
        ) -> dict[str, object]:
            requests.append((method, path))
            return {"status": "ready", "activeSessionIds": []}

        result = CANARY.wait_for_sessions_quiescent(
            "http://in-process.invalid",
            requester=requester,
            session_ids=[SESSIONS["A"]],
            timeout=1,
        )

        self.assertTrue(result["passed"])
        self.assertEqual(requests, [("GET", "/api/agent/runtime")])

    def test_provider_usage_checks_return_member_receipts(self) -> None:
        def requester(
            _base_url: str,
            _method: str,
            _path: str,
            **_kwargs: object,
        ) -> dict[str, object]:
            return {
                "context": {
                    "providerRequestReceipts": [
                        {"usage": {"input": 12, "output": 3}}
                    ]
                }
            }

        checks, evidence = CANARY._provider_usage_checks(
            "http://in-process.invalid",
            requester=requester,
            session_ids={"A": SESSIONS["A"]},
        )

        self.assertEqual(checks, {"AUsageReceiptObserved": True})
        self.assertEqual(evidence["A"]["providerRequestReceiptCount"], 1)


    def test_provider_usage_checks_fall_back_to_model_call_usage(self) -> None:
        def requester(
            _base_url: str,
            _method: str,
            _path: str,
            **_kwargs: object,
        ) -> dict[str, object]:
            return {
                "context": {
                    "modelCalls": [
                        {"assistantMessage": {"usage": {"output": 7}}}
                    ]
                }
            }

        checks, evidence = CANARY._provider_usage_checks(
            "http://in-process.invalid",
            requester=requester,
            session_ids={"A": SESSIONS["A"]},
        )

        self.assertEqual(checks, {"AUsageReceiptObserved": True})
        self.assertEqual(evidence["A"]["modelCallUsageCount"], 1)

    def test_public_timeline_and_timeout_helpers(self) -> None:
        snapshot = {"events": [{"eventType": "room_post", "payload": {"post": {"postId": "p1", "rootId": ROOT_ID, "createdAtMs": 1, "publicationSource": {"kind": "room_commit"}}}}, {"eventType": "room_post", "payload": {"post": {"postId": "other", "rootId": "room-root:2", "publicationSource": {"kind": "room_post"}}}}]}
        self.assertEqual(["p1"], [item["postId"] for item in CANARY._public_posts_from_timeline_snapshot(snapshot, root_id=ROOT_ID)])
        self.assertEqual(900, CANARY.workflow_timeout_seconds(SimpleNamespace(turn_timeout=300, workflow_timeout=None)))
        self.assertEqual(480, CANARY.workflow_timeout_seconds(SimpleNamespace(turn_timeout=300, workflow_timeout=480)))
        with self.assertRaisesRegex(ValueError, "positive"):
            CANARY.workflow_timeout_seconds(SimpleNamespace(turn_timeout=300, workflow_timeout=0))


if __name__ == "__main__":
    unittest.main()
