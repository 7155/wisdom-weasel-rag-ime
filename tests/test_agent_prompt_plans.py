from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from rag_ime.agent_prompt_plans import (
    PromptLayer,
    PromptPlanConflict,
    PromptProducerConflict,
    RoomPromptPlanStore,
)
from rag_ime.agent_room_context import ProviderProjectionJournalStore, RoomContextLedgerStore


class RoomPromptPlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="room-prompt-plan-")
        self.db_path = Path(self.tmp.name) / "rag-ime.sqlite"
        self.context = RoomContextLedgerStore(self.db_path)
        self.journals = ProviderProjectionJournalStore(self.db_path)
        self.store = RoomPromptPlanStore(self.db_path)
        self.context.initialize()
        self.journals.initialize()
        self.store.initialize()
        self._open_journal("journal:1", context_epoch=1)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_duplicate_instruction_producer_is_rejected_before_receipt(self) -> None:
        layers = list(self._layers())
        layers[2] = PromptLayer(
            **{**layers[2].__dict__, "instruction_domains": ("identity",)}
        )
        with self.assertRaisesRegex(PromptProducerConflict, "both"):
            self._compile("receipt:duplicate", layers=layers)
        with sqlite3.connect(self.db_path) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM room_v2_prompt_compile_receipts").fetchone()[0], 0)

    def test_semantic_hard_rule_is_rejected_outside_its_single_owner(self) -> None:
        layers = list(self._layers())
        layers[1] = PromptLayer(
            **{
                **layers[1].__dict__,
                "content": "PERSONA\n收工前必须选择已交付、已交接、等待或阻塞",
            }
        )

        with self.assertRaisesRegex(
            PromptProducerConflict,
            "settle-decision rule belongs to collaboration_role",
        ):
            self._compile("receipt:semantic-owner", layers=layers)

    def test_stable_prefix_is_byte_identical_when_dynamic_tail_appends(self) -> None:
        first_entry = self._entry("task_state", "task:1", "任务：实现 PromptPlan", 1)
        self._append("journal:1", first_entry, "task:1", 10)
        first = self._compile("receipt:1")
        second_entry = self._entry("control_receipt", "control:2", "预算剩余 42", 2)
        self._append("journal:1", second_entry, "control:2", 20)
        second = self._compile("receipt:2")

        self.assertEqual(first["stablePrefixBytes"], second["stablePrefixBytes"])
        self.assertEqual(
            first["receipt"]["plan"]["stablePrefixHash"],
            second["receipt"]["plan"]["stablePrefixHash"],
        )
        self.assertNotEqual(first["dynamicTailBytes"], second["dynamicTailBytes"])
        self.assertEqual(len(second["receipt"]["plan"]["dynamicTailRefs"]), 2)
        first_provider = self.store.provider_payload("receipt:1")
        second_provider = self.store.provider_payload("receipt:2")
        self.assertEqual(
            first_provider["stableSystemPrompt"], second_provider["stableSystemPrompt"]
        )
        stable_prompt = str(first_provider["stableSystemPrompt"])
        positions = [
            stable_prompt.index(f'order="{order}"') for order in range(1, 6)
        ]
        self.assertEqual(positions, sorted(positions))
        self.assertNotIn(" ref=", stable_prompt)
        self.assertNotIn("sha256:", stable_prompt)
        self.assertIn("任务：实现 PromptPlan", first_provider["providerContext"])
        self.assertIn("预算剩余 42", second_provider["providerContext"])

    def test_crash_before_provider_receipt_replays_same_pending_plan(self) -> None:
        entry = self._entry("room_post", "post:1", "未封口事实", 1)
        self._append("journal:1", entry, "post:1", 10)
        compiled = self._compile("receipt:pending")

        restarted = RoomPromptPlanStore(self.db_path)
        restarted.initialize()
        replayed = restarted.compile(**self._compile_args("receipt:pending"))

        self.assertFalse(replayed["created"])
        self.assertEqual(replayed["stablePrefixBytes"], compiled["stablePrefixBytes"])
        self.assertEqual(replayed["dynamicTailBytes"], compiled["dynamicTailBytes"])
        projection = self.journals.projection("journal:1", expected_generation=3)
        self.assertEqual(len(projection["pendingTail"]), 1)
        self.assertEqual(projection["sealedPrefix"], [])

    def test_provider_receipt_moves_pending_tail_into_sealed_prefix(self) -> None:
        entry = self._entry("room_post", "post:seal", "待发送事实", 1)
        self._append("journal:1", entry, "post:seal", 10)
        pending = self._compile("receipt:pre-seal")
        projection = self.journals.projection("journal:1", expected_generation=3)
        self.journals.record_provider_receipt(
            "journal:1", receipt_id="provider:1", provider_request_id="request:1",
            through_sequence=1, projection_hash=projection["projectionHash"],
            expected_generation=3, created_at_ms=20,
        )
        sealed = self._compile("receipt:sealed")

        self.assertEqual(pending["receipt"]["plan"]["dynamicTailRefs"], [entry])
        self.assertEqual(sealed["receipt"]["plan"]["dynamicTailRefs"], [])
        self.assertEqual(sealed["receipt"]["plan"]["sealedProjectionRefs"], [entry])
        self.assertEqual(sealed["dynamicTailBytes"], b"")
        self.assertNotEqual(pending["stablePrefixBytes"], sealed["stablePrefixBytes"])

    def test_compaction_recovery_starts_new_context_epoch_without_changing_prefix(self) -> None:
        first_entry = self._entry("task_state", "task:1", "原始任务", 1)
        self._append("journal:1", first_entry, "task:1", 10)
        before = self._compile("receipt:before")

        self._open_journal("journal:2", context_epoch=2)
        recovery = self._entry(
            "recovery_packet", "recovery:1",
            "需求锚点；当前任务；负责人；验收条件；阻塞项；取消代际", 2,
        )
        self._append("journal:2", recovery, "recovery:1", 30)
        after = self.store.compile(
            **self._compile_args("receipt:after", journal_id="journal:2", context_epoch=2)
        )

        self.assertEqual(before["stablePrefixBytes"], after["stablePrefixBytes"])
        self.assertEqual(after["receipt"]["plan"]["contextEpoch"], 2)
        self.assertEqual(after["receipt"]["plan"]["dynamicTailRefs"], [recovery])
        self.assertIn("需求锚点", after["dynamicTailBytes"].decode("utf-8"))

    def test_provider_payload_hides_context_diagnostics_but_ledger_keeps_them(self) -> None:
        audit_content = json.dumps(
            {
                "objective": "验证 Room 取消传播",
                "relevance": 0.97,
                "scoreBreakdown": {"vector": 0.8},
                "rank": 1,
                "internalId": "row:4",
                "contentHash": "sha256:secret",
                "debugReason": "vector lane",
                "sources": [
                    {"title": "取消设计", "path": "docs/cancel.md", "sourceId": "chunk:2"}
                ],
            },
            ensure_ascii=False,
        )
        entry = self._entry("knowledge_receipt", "knowledge:1", audit_content, 1)
        self._append("journal:1", entry, "knowledge:1", 10)
        self._compile("receipt:noise-filter")

        provider = self.store.provider_payload("receipt:noise-filter")
        visible = str(provider["providerContext"])
        for forbidden in (
            "relevance", "score", "rank", "internalid", "hash", "debugreason",
            "receipt", "row:4", "chunk:2",
        ):
            self.assertNotIn(forbidden, visible.casefold())
        self.assertIn("验证 Room 取消传播", visible)
        self.assertIn("取消设计", visible)
        self.assertIn("docs/cancel.md", visible)
        self.assertEqual(self.context.replay_root("root:1")[0]["content"], audit_content)

    def test_capability_revision_and_epoch_are_pinned_and_stale_receipt_conflicts(self) -> None:
        first = self._compile("receipt:capability")
        room, participant = self._bindings(capability_revision="cap-revoked", capability_epoch=2)
        with self.assertRaisesRegex(PromptPlanConflict, "identity changed"):
            self.store.compile(
                **{
                    **self._compile_args("receipt:capability"),
                    "room_binding": room,
                    "participant_binding": participant,
                }
            )
        with self.assertRaisesRegex(PromptPlanConflict, "new Context epoch"):
            self.store.compile(
                **{
                    **self._compile_args("receipt:capability:stale"),
                    "room_binding": room,
                    "participant_binding": participant,
                }
            )
        self._open_journal("journal:revoked", context_epoch=2)
        second = self.store.compile(
            **{
                **self._compile_args(
                    "receipt:capability:2", journal_id="journal:revoked", context_epoch=2
                ),
                "room_binding": room,
                "participant_binding": participant,
            }
        )
        self.assertEqual(second["receipt"]["plan"]["capabilityEpoch"], 2)
        self.assertNotEqual(first["receipt"]["plan"]["planHash"], second["receipt"]["plan"]["planHash"])

    def test_compare_records_only_diff_and_ordinary_agent_is_total_noop(self) -> None:
        compiled = self._compile("receipt:compare")
        before_projection = self.journals.projection("journal:1", expected_generation=3)
        diff, created = self.store.record_compare_diff(
            diff_id="diff:1", binding_id="participant-binding:1",
            legacy_prompt_hash=hashlib.sha256(b"legacy").hexdigest(),
            prompt_plan_hash=compiled["receipt"]["plan"]["planHash"],
            added_layer_refs=("persona:1",), removed_legacy_refs=("legacy-wrapper",),
            created_at_ms=10,
        )
        after_projection = self.journals.projection("journal:1", expected_generation=3)
        self.assertTrue(created)
        self.assertEqual(diff["addedLayerRefs"], ["persona:1"])
        repeated, repeated_created = self.store.record_compare_diff(
            diff_id="diff:1", binding_id="participant-binding:1",
            legacy_prompt_hash=hashlib.sha256(b"legacy").hexdigest(),
            prompt_plan_hash=compiled["receipt"]["plan"]["planHash"],
            added_layer_refs=("persona:1",), removed_legacy_refs=("legacy-wrapper",),
            created_at_ms=10,
        )
        self.assertFalse(repeated_created)
        self.assertEqual(repeated, diff)
        self.assertEqual(before_projection, after_projection)

        untouched = Path(self.tmp.name) / "ordinary.sqlite"
        ordinary = RoomPromptPlanStore(untouched).compile(
            **{
                **self._compile_args("receipt:none"),
                "room_binding": None,
                "participant_binding": None,
            }
        )
        self.assertIsNone(ordinary)
        self.assertFalse(untouched.exists())
        with self.assertRaisesRegex(PromptPlanConflict, "handshake is incomplete"):
            self.store.compile(
                **{
                    **self._compile_args("receipt:incomplete"),
                    "participant_binding": None,
                }
            )

    def _compile(self, receipt_id: str, *, layers=None):
        return self.store.compile(**self._compile_args(receipt_id, layers=layers))

    def _compile_args(self, receipt_id: str, *, journal_id="journal:1", context_epoch=1, layers=None):
        room, participant = self._bindings()
        return {
            "receipt_id": receipt_id, "room_binding": room,
            "participant_binding": participant, "journal_id": journal_id,
            "session_epoch": 1, "context_epoch": context_epoch,
            "skill_policy_revision": "skills-v1", "context_policy_revision": "context-v1",
            "layers": tuple(layers or self._layers()), "created_at_ms": 100,
        }

    def _bindings(self, *, capability_revision="cap-v1", capability_epoch=1):
        room = {
            "schemaVersion": "wisdom-weasel.room-binding.v2", "bindingId": "room-binding:1",
            "rootId": "root:1", "roomId": "room:1", "participantId": "participant:1",
            "taskId": "task:1", "generation": 3, "protocolRevision": "room-v2",
            "capabilityRevision": capability_revision, "access": "write",
        }
        digest = "a" * 64
        participant = {
            "schemaVersion": "wisdom-weasel.room-participant-binding.v2",
            "bindingId": "participant-binding:1", "sessionId": "session:1",
            "personaRef": f"rag-ime-definition://persona/p?version=1&contentHash=sha256:{digest}",
            "collaborationRoleRef": f"rag-ime-definition://collaboration-role/r?version=1&contentHash=sha256:{digest}",
            "agentTemplateRef": f"rag-ime-definition://agent-template/t?version=1&contentHash=sha256:{digest}",
            "collaborationProfileRef": None,
            "compiledRuntimeProfileRef": {"profileId": "compiled:1", "revision": "1", "contentHash": "sha256:abcdef"},
            "capabilityRevision": capability_revision, "capabilityEpoch": capability_epoch,
            "roomBindingRef": {"bindingId": "room-binding:1", "schemaVersion": "wisdom-weasel.room-binding.v2"},
        }
        return room, participant

    @staticmethod
    def _layers():
        return (
            PromptLayer("core_rails", "pi-core-safety", "core:v1", "CORE\n", ("safety", "authorization")),
            PromptLayer("persona", "persona-compiler", "persona:v1", "PERSONA  ", ("identity",)),
            PromptLayer("collaboration_role", "collaboration-role-compiler", "role:v1", "ROLE\n", ("collaboration-duty",)),
            PromptLayer("agent_template_policy", "template-capability-compiler", "template:v1", "TOOLS\n", ("tool-policy", "skill-policy")),
            PromptLayer("room_profile_overlay", "profile-room-kernel-compiler", "profile:none", "", ("room-overlay",), "no-profile"),
            PromptLayer("provider_dynamic_facts", "room-context-compiler", "journal:1", "", ("dynamic-facts",)),
        )

    def _open_journal(self, journal_id: str, *, context_epoch: int):
        self.journals.open_journal(
            journal_id=journal_id, root_id="root:1", room_id="room:1",
            binding_id="participant-binding:1", session_id="session:1",
            session_epoch=1, context_epoch=context_epoch, generation=3, created_at_ms=1,
        )

    def _entry(self, kind: str, source: str, content: str, sequence: int):
        entry, _ = self.context.append_entry(
            root_id="root:1", room_id="room:1", generation=3, entry_kind=kind,
            source_ref=source, dedupe_key=source, content=content, created_at_ms=sequence,
        )
        return str(entry["entryId"])

    def _append(self, journal_id: str, entry_id: str, dedupe: str, created: int):
        self.journals.append_entry(
            journal_id, entry_id, dedupe_key=dedupe,
            expected_generation=3, appended_at_ms=created,
        )


if __name__ == "__main__":
    unittest.main()
