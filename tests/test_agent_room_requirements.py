from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from rag_ime.agent_room_requirements import (
    RequirementEvidenceError,
    RequirementGovernanceStore,
    RequirementRevisionConflict,
)
from rag_ime.agent_room_kernel import RoomKernelStore
from rag_ime.agent_room_task_context import (
    RoomTaskContextProjector,
)
from tests.test_agent_room_kernel import dispatch, root, task


class RequirementGovernanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="room-requirements-")
        self.db_path = Path(self.tmp.name) / "rag-ime.sqlite"
        self.store = RequirementGovernanceStore(self.db_path)
        self.store.initialize()
        self.original = "原始需求：保留原文，并完成可验证的用户流程。".encode("utf-8")
        self.anchor, _ = self.store.append_anchor(
            anchor_id="anchor:1", root_id="root:1", original_content=self.original,
            created_by="user:1", provenance={"roomEventId": "event:1"}, created_at_ms=1,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_original_bytes_are_permanent_while_catalog_revision_is_derived(self) -> None:
        first = self._catalog("catalog:1", expected=0, statement="必须保留原始需求字节")
        second_anchor, _ = self.store.append_anchor(
            anchor_id="anchor:2", root_id="root:1", original_content=b"discovery follow-up",
            created_by="user:1", provenance={"roomEventId": "event:2"}, created_at_ms=2,
        )
        second = self._catalog(
            "catalog:2", expected=1, statement="必须永久保留原始需求字节",
            anchors=("anchor:1", "anchor:2"), supersedes=("requirement:1",),
        )

        self.assertEqual(self.store.original_bytes("anchor:1"), self.original)
        self.assertEqual(first["revision"], 1)
        self.assertEqual(second["revision"], 2)
        self.assertEqual(second["supersedesRevisionId"], "catalog:1")
        self.assertEqual(second["anchorRefs"], ["anchor:1", "anchor:2"])
        self.assertNotEqual(first["payloadHash"], second["payloadHash"])
        self.assertEqual(second_anchor["rootSequence"], 2)
        with sqlite3.connect(self.db_path) as conn, self.assertRaisesRegex(
            sqlite3.IntegrityError, "RequirementAnchor is immutable"
        ):
            conn.execute(
                "UPDATE room_v2_requirement_anchors SET original_bytes = ? WHERE anchor_id = 'anchor:1'",
                (b"rewritten",),
            )

    def test_repeated_identical_user_messages_remain_distinct_append_only_anchors(self) -> None:
        repeated, created = self.store.append_anchor(
            anchor_id="anchor:repeat", root_id="root:1", original_content=self.original,
            created_by="user:1", provenance={"roomEventId": "event:repeat"}, created_at_ms=2,
        )

        self.assertTrue(created)
        self.assertEqual(repeated["rootSequence"], 2)
        self.assertEqual(repeated["originalContentSha256"], self.anchor["originalContentSha256"])
        self.assertEqual(self.store.original_bytes("anchor:repeat"), self.original)

    def test_forged_agent_statement_cannot_become_proof(self) -> None:
        catalog = self._catalog("catalog:1", expected=0)
        with self.assertRaisesRegex(RequirementEvidenceError, "typed verification receipt"):
            self.store.record_verification_receipt("测试已经通过")
        forged = {**self._receipt("receipt:fake", catalog["catalogRevisionId"]), "receiptType": "agent_statement"}
        with self.assertRaises(RequirementEvidenceError):
            self.store.record_verification_receipt(forged)
        self_report = {
            **self._receipt("receipt:self", catalog["catalogRevisionId"]),
            "verifier": "agent:self",
        }
        with self.assertRaisesRegex(RequirementEvidenceError, "self-report"):
            self.store.record_verification_receipt(self_report)
        with self.assertRaises(RequirementEvidenceError):
            self.store.link_proof(
                proof_id="proof:fake", root_id="root:1",
                catalog_revision_id="catalog:1", criterion_id="criterion:req",
                receipt_id="missing-free-text", linked_by="agent:1", created_at_ms=4,
            )

    def test_all_requirement_criteria_green_but_failed_user_journey_warns(self) -> None:
        self._catalog("catalog:1", expected=0, include_journey=True)
        passed = self._receipt("receipt:test", "catalog:1", receipt_type="test", exit_status=0)
        failed_journey = self._receipt(
            "receipt:journey", "catalog:1", receipt_type="evidence", exit_status=1
        )
        self.store.record_verification_receipt(passed)
        self.store.record_verification_receipt(failed_journey)
        self.store.link_proof(
            proof_id="proof:req", root_id="root:1", catalog_revision_id="catalog:1",
            criterion_id="criterion:req", receipt_id="receipt:test", linked_by="runner", created_at_ms=4,
        )
        self.store.link_proof(
            proof_id="proof:journey", root_id="root:1", catalog_revision_id="catalog:1",
            criterion_id="criterion:journey", receipt_id="receipt:journey", linked_by="runner", created_at_ms=4,
        )
        gate = self.store.observe_delivery_gate(
            gate_receipt_id="gate:1", root_id="root:1", catalog_revision_id="catalog:1",
            target_commit="commit:1", blind_review_status="passed", created_at_ms=5,
        )

        matrix = {item["criterionId"]: item for item in gate["proofMatrix"]}
        self.assertTrue(matrix["criterion:req"]["passed"])
        self.assertFalse(matrix["criterion:journey"]["passed"])
        self.assertIn("user_journey_failed", gate["reasons"])
        self.assertEqual(gate["gateStatus"], "warn_blocked")
        self.assertFalse(gate["enforcementApplied"])

    def test_unknown_conflict_and_obstacle_block_observation(self) -> None:
        self._catalog("catalog:1", expected=0, second_item=True)
        self.store.record_conflict(
            conflict_id="conflict:1", root_id="root:1", catalog_revision_id="catalog:1",
            left_item_id="requirement:1", right_item_id="requirement:2",
            conflict_kind="unknown", created_at_ms=3,
        )
        self.store.record_obstacle(
            obstacle_id="unknown:1", root_id="root:1", catalog_revision_id="catalog:1",
            obstacle_kind="unknown", statement="正式安装环境尚未确认", created_at_ms=3,
        )
        gate = self.store.observe_delivery_gate(
            gate_receipt_id="gate:unknown", root_id="root:1",
            catalog_revision_id="catalog:1", target_commit="commit:1",
            blind_review_status="pending", created_at_ms=4,
        )
        self.assertIn("unresolved_conflict_or_unknown", gate["reasons"])
        self.assertIn("unresolved_unknown", gate["reasons"])
        self.assertIn("blind_review_not_passed", gate["reasons"])

    def test_fully_typed_matrix_observes_pass_without_enforcement(self) -> None:
        self._catalog("catalog:1", expected=0, include_journey=True)
        for receipt, criterion in (
            (self._receipt("receipt:test", "catalog:1", receipt_type="test"), "criterion:req"),
            (self._receipt("receipt:journey", "catalog:1", receipt_type="evidence"), "criterion:journey"),
        ):
            self.store.record_verification_receipt(receipt)
            self.store.link_proof(
                proof_id="proof:" + criterion, root_id="root:1",
                catalog_revision_id="catalog:1", criterion_id=criterion,
                receipt_id=receipt["receiptId"], linked_by="runner", created_at_ms=4,
            )
        gate = self.store.observe_delivery_gate(
            gate_receipt_id="gate:pass", root_id="root:1",
            catalog_revision_id="catalog:1", target_commit="commit:1",
            blind_review_status="passed", created_at_ms=5,
        )
        self.assertEqual(gate["gateStatus"], "observed_pass")
        self.assertEqual(gate["reasons"], [])
        self.assertFalse(gate["enforcementApplied"])

    def test_dispatch_task_packet_freezes_original_catalog_proof_and_blocker(self) -> None:
        kernel = RoomKernelStore(self.db_path, mode="test")
        kernel.initialize()
        kernel.create_root(
            root("root:1"),
            budget=8,
            max_hops=3,
            max_depth=2,
            acceptance_criteria=("criterion:req",),
            now_ms=1,
        )
        kernel.create_task(task("task:1"), now_ms=1)
        kernel.enqueue_dispatch(
            dispatch("dispatch:1", key="requirements:1"),
            now_ms=1,
        )
        self._catalog("catalog:1", expected=0)
        receipt = self._receipt("receipt:test", "catalog:1")
        self.store.record_verification_receipt(receipt)
        self.store.link_proof(
            proof_id="proof:req",
            root_id="root:1",
            catalog_revision_id="catalog:1",
            criterion_id="criterion:req",
            receipt_id="receipt:test",
            linked_by="runner",
            created_at_ms=4,
        )
        self.store.record_obstacle(
            obstacle_id="blocker:1",
            root_id="root:1",
            catalog_revision_id="catalog:1",
            obstacle_kind="blocker",
            statement="等待正式安装环境",
            created_at_ms=4,
        )
        self.store.prepare_dispatch_binding(
            dispatch_id="dispatch:1",
            root_id="root:1",
            task_id="task:1",
            session_id="session:1",
            generation=0,
            requirement_anchor_ref="anchor:1@sha256:test",
            created_at_ms=5,
        )
        snapshot = self.store.dispatch_context("dispatch:1")
        self.assertEqual(
            snapshot["originalRequirements"][0]["text"],
            self.original.decode("utf-8"),
        )
        criterion = snapshot["catalog"]["acceptanceCriteria"][0]
        self.assertEqual(criterion["proofs"][0]["receiptId"], "receipt:test")
        self.assertEqual(
            snapshot["catalog"]["openObstacles"][0]["statement"],
            "等待正式安装环境",
        )

        rendered = RoomTaskContextProjector(self.store).render(
            {
                "taskId": "task:1",
                "parentTaskId": None,
                "ownerParticipantId": "participant:owner",
                "assigneeParticipantId": "participant:target",
                "objective": "完成有证据的交付",
                "expectedOutput": "可复核结果",
                "requirementItemIds": ["requirement:1"],
                "acceptanceCriterionIds": ["criterion:req"],
                "revision": 0,
                "state": "active",
            },
            {
                "dispatchId": "dispatch:1",
                "rootId": "root:1",
                "taskId": "task:1",
                "targetSessionId": "session:1",
                "targetParticipantId": "participant:target",
                "parentDispatchId": None,
                "generation": 0,
                "intentKind": "execute",
                "hopCount": 1,
                "depth": 1,
            },
        )
        packet = json.loads(rendered)
        self.assertEqual(
            packet["requirements"]["original"][0]["text"],
            self.original.decode("utf-8"),
        )
        self.assertTrue(
            packet["acceptance"]["criteria"][0]["passed"]
        )
        self.assertEqual(
            packet["blockers"]["obstacles"][0]["statement"],
            "等待正式安装环境",
        )

    def test_dispatch_packet_references_identical_original_instead_of_copying_it(self) -> None:
        original_text = self.original.decode("utf-8")
        kernel = RoomKernelStore(self.db_path, mode="test")
        kernel.initialize()
        kernel.create_root(
            root("root:1"),
            budget=4,
            max_hops=2,
            max_depth=1,
            acceptance_criteria=(),
            now_ms=1,
        )
        kernel.create_task(task("task:1"), now_ms=1)
        kernel.enqueue_dispatch(
            dispatch("dispatch:identical", key="identical"),
            now_ms=1,
        )
        self._catalog(
            "catalog:identical",
            expected=0,
            statement=original_text,
        )
        self.store.prepare_dispatch_binding(
            dispatch_id="dispatch:identical",
            root_id="root:1",
            task_id="task:1",
            session_id="session:participant:a",
            generation=0,
            requirement_anchor_ref="anchor:1@sha256:test",
            created_at_ms=5,
        )

        rendered = RoomTaskContextProjector(self.store).render(
            {
                "taskId": "task:1",
                "parentTaskId": None,
                "ownerParticipantId": "participant:owner",
                "assigneeParticipantId": "participant:target",
                "objective": "验证需求投影去重",
                "expectedOutput": "原文只出现一次",
                "requirementItemIds": ["requirement:1"],
                "acceptanceCriterionIds": [],
                "revision": 0,
                "state": "active",
            },
            {
                "dispatchId": "dispatch:identical",
                "rootId": "root:1",
                "taskId": "task:1",
                "targetSessionId": "session:participant:a",
                "targetParticipantId": "participant:a",
                "parentDispatchId": None,
                "generation": 0,
                "intentKind": "execute",
                "hopCount": 0,
                "depth": 0,
            },
        )

        packet = json.loads(rendered)
        item = packet["requirements"]["items"][0]
        self.assertEqual(item["statementSource"], "original[0]")
        self.assertNotIn("statement", item)
        self.assertEqual(rendered.count(original_text), 1)

    def test_concurrent_catalog_revision_fails_closed_and_old_revision_cannot_gate(self) -> None:
        self._catalog("catalog:1", expected=0)
        self._catalog("catalog:2", expected=1, statement="第二版目录")
        with self.assertRaisesRegex(RequirementRevisionConflict, "revision changed"):
            self._catalog("catalog:racing", expected=1, statement="并发旧写入")
        with self.assertRaisesRegex(RequirementRevisionConflict, "old RequirementCatalog"):
            self.store.observe_delivery_gate(
                gate_receipt_id="gate:old", root_id="root:1",
                catalog_revision_id="catalog:1", target_commit="commit:1",
                blind_review_status="passed", created_at_ms=5,
            )

    def test_legacy_objective_is_quarantined_and_cannot_claim_original_provenance(self) -> None:
        legacy, _ = self.store.import_legacy_objective(
            anchor_id="legacy:1", root_id="root:legacy", objective="旧 WorkItem objective",
            legacy_ref="work:42", created_at_ms=1,
        )
        self.assertEqual(legacy["authenticity"], "legacy_quarantined")
        with self.assertRaisesRegex(RequirementRevisionConflict, "cannot masquerade"):
            self.store.revise_catalog(
                catalog_revision_id="legacy-catalog:1", root_id="root:legacy",
                expected_current_revision=0, anchor_refs=("legacy:1",),
                items=(self._item(anchor="legacy:1"),),
                acceptance_criteria=(self._criterion(),),
                change_reason="导入旧数据", provenance={"kind": "legacy_import"},
                created_by="migration", created_at_ms=2,
            )

    def _catalog(
        self,
        catalog_id,
        *,
        expected,
        statement="必须保留原始需求字节",
        anchors=("anchor:1",),
        supersedes=(),
        include_journey=False,
        second_item=False,
    ):
        items = [self._item(statement=statement, supersedes=supersedes)]
        criteria = [self._criterion()]
        if second_item:
            items.append(
                self._item(
                    item_id="requirement:2", statement="安装环境必须明确",
                    kind="agent_inferred_requirement", state="needs_confirmation",
                )
            )
        if include_journey:
            criteria.append(
                self._criterion(
                    criterion_id="criterion:journey", kind="user_journey",
                    receipt_types=("evidence",), full_name="用户旅程验收标准",
                    statement="真实用户流程必须成功",
                )
            )
        payload, _ = self.store.revise_catalog(
            catalog_revision_id=catalog_id, root_id="root:1",
            expected_current_revision=expected, anchor_refs=anchors,
            items=items, acceptance_criteria=criteria,
            change_reason="根据讨论修订需求目录",
            provenance={"derivedFrom": list(anchors), "notOriginalText": True},
            created_by="agent:requirements", created_at_ms=2 + expected,
        )
        return payload

    def _item(
        self,
        *,
        item_id="requirement:1",
        anchor="anchor:1",
        statement="必须保留原始需求字节",
        kind="explicit_user_requirement",
        state="active",
        supersedes=(),
    ):
        return {
            "itemId": item_id, "kind": kind, "statement": statement,
            "origin": "derived_catalog", "state": state,
            "sourceSpans": (
                [{"anchorId": anchor, "startByte": 0, "endByte": len(self.original)}]
                if kind in {"explicit_user_requirement", "system_hard_constraint"}
                else []
            ),
            "supersedes": list(supersedes), "ambiguity": "" if state == "active" else "待确认",
            "confirmation": "user-confirmed" if state == "active" else "",
        }

    @staticmethod
    def _criterion(
        *,
        criterion_id="criterion:req",
        kind="requirement",
        receipt_types=("test",),
        full_name="需求验收标准",
        statement="原始字节哈希保持一致",
    ):
        return {
            "criterionId": criterion_id, "itemId": "requirement:1",
            "acceptanceCriterionFullNameZh": full_name,
            "criterionKind": kind, "expectedReceiptTypes": receipt_types,
            "statement": statement,
        }

    @staticmethod
    def _receipt(receipt_id, catalog_id, *, receipt_type="test", exit_status=0):
        verifiers = {
            "test": "managed-test-runner", "build": "managed-build-runner",
            "install": "managed-install-verifier", "evidence": "managed-evidence-verifier",
        }
        return {
            "schemaVersion": "wisdom-weasel.typed-verification-receipt.v1",
            "receiptId": receipt_id, "rootId": "root:1", "catalogRevisionId": catalog_id,
            "receiptType": receipt_type, "sourceCommit": "commit:1",
            "environment": "local-test", "commandOrAction": "python -m unittest",
            "exitStatus": exit_status, "outputHash": "a" * 64,
            "artifactHash": "b" * 64, "verifier": verifiers[receipt_type], "createdAtMs": 3,
        }


if __name__ == "__main__":
    unittest.main()
