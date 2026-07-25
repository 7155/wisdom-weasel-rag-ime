from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

import yaml

from rag_ime.agent_room_skills import (
    RoomSkillEpochRevoked,
    RoomSkillPolicy,
    RoomSkillPolicyConflict,
    RoomSkillPolicyStore,
    SkillCatalogRevisionMismatch,
    SkillContentRevisionMismatch,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = REPO_ROOT / "integrations/pi/room-skill-policy.json"
SKILLS_ROOT = REPO_ROOT / "integrations/pi/skills"
GENERAL_WORK_SKILLS = (
    "grill-me",
    "improve-codebase-architecture",
    "managed-task-execution",
    "quality-gate",
)


def _frontmatter(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8")
    _empty, raw, _body = text.split("---", 2)
    value = yaml.safe_load(raw)
    if not isinstance(value, dict):
        raise AssertionError(f"invalid frontmatter: {path}")
    return value


class RoomNativeSkillTests(unittest.TestCase):
    def test_general_work_skills_are_bounded_progressive_entries(self) -> None:
        expected_keys = {
            "name",
            "description",
            "when",
            "notFor",
            "input",
            "output",
            "does",
        }

        for skill_id in GENERAL_WORK_SKILLS:
            with self.subTest(skill_id=skill_id):
                path = SKILLS_ROOT / skill_id / "SKILL.md"
                frontmatter = _frontmatter(path)
                body = path.read_text(encoding="utf-8").split("---", 2)[2]
                self.assertEqual(set(frontmatter), expected_keys)
                self.assertEqual(frontmatter["name"], skill_id)
                self.assertTrue(frontmatter["when"])
                self.assertTrue(frontmatter["notFor"])
                # Full bodies arrive only through skill_load Tool Results. They
                # may be structured enough to guide real work, but stay bounded.
                self.assertLessEqual(len(body.splitlines()), 120)
                self.assertLessEqual(len(body.encode()), 6_000)
                self.assertIn("## Self-Check", body)
                self.assertNotIn("create a Dispatch", body)
                self.assertNotIn("mark work complete", body)

        architecture = (
            SKILLS_ROOT / "improve-codebase-architecture/SKILL.md"
        ).read_text(encoding="utf-8")
        grilling = (SKILLS_ROOT / "grill-me/SKILL.md").read_text(
            encoding="utf-8"
        )
        managed = (
            SKILLS_ROOT / "managed-task-execution/SKILL.md"
        ).read_text(encoding="utf-8")
        quality = (SKILLS_ROOT / "quality-gate/SKILL.md").read_text(
            encoding="utf-8"
        )
        review = (SKILLS_ROOT / "independent-review/SKILL.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("File size alone is not evidence", architecture)
        self.assertIn("**depth**", architecture)
        self.assertIn("**deletion test**", architecture)
        self.assertIn("Ask exactly one decision question", grilling)
        self.assertIn("ordinary chat", managed)
        self.assertIn("materially different legal", managed)
        self.assertIn("another participant or model capability", managed)
        self.assertIn("two consecutive attempts", managed)
        self.assertIn("The Kernel binds", quality)
        self.assertIn("derives coverage and readiness", quality)
        self.assertIn("human-readable aliases", quality)
        self.assertIn("No completion claim without fresh", quality)
        self.assertIn("Do not send", quality)
        self.assertIn("acceptanceAliases", quality)
        self.assertIn("decision=handoff", quality)
        self.assertIn("do not send", review)
        self.assertIn("acceptanceAliases", review)

    def test_nine_governed_skills_are_native_pi_skills_with_compact_routing_cards(self) -> None:
        policy = RoomSkillPolicy(POLICY_PATH, SKILLS_ROOT)
        expected_keys = {"name", "when", "notFor", "input", "output", "does"}

        self.assertEqual(len(policy.skill_ids), 9)
        for skill_id, routing in zip(policy.skill_ids, policy.catalog(), strict=True):
            with self.subTest(skill_id=skill_id):
                path = SKILLS_ROOT / skill_id / "SKILL.md"
                frontmatter = _frontmatter(path)
                self.assertEqual(frontmatter["name"], skill_id)
                self.assertTrue(frontmatter["description"])
                self.assertTrue(frontmatter["when"])
                self.assertTrue(frontmatter["notFor"])
                self.assertTrue(frontmatter["input"])
                self.assertTrue(frontmatter["output"])
                self.assertTrue(frontmatter["does"])
                self.assertEqual(set(routing), expected_keys)
                self.assertNotIn("body", routing)
                encoded = json.dumps(routing, ensure_ascii=False, separators=(",", ":"))
                self.assertLessEqual(len(encoded.encode()), 450, encoded)
                body = path.read_text(encoding="utf-8").split("---", 2)[2]
                self.assertLessEqual(len(body.encode()), 6_000)
                self.assertIn("## Workflow", body)
                self.assertIn("## Output Contract", body)
                self.assertIn("## Self-Check", body)
                self.assertIn("## Boundaries", body)

    def test_exact_load_adds_only_one_skill_body_and_revision(self) -> None:
        policy = RoomSkillPolicy(POLICY_PATH, SKILLS_ROOT)
        expected_catalog_keys = {"name", "when", "notFor", "input", "output", "does"}

        catalog = policy.catalog()
        loaded = policy.load_exact("structured-handoff")

        self.assertTrue(all(set(item) == expected_catalog_keys for item in catalog))
        self.assertEqual(set(loaded), expected_catalog_keys | {"body", "contentRevision"})
        self.assertIn("## Output Contract", loaded["body"])
        self.assertIn("current model cannot finish", loaded["body"])
        self.assertIn("exact takeover point", loaded["body"])
        self.assertIn("## Five-Part Packet", loaded["body"])
        self.assertIn("## Complete Example", loaded["body"])
        self.assertEqual(len(loaded["contentRevision"]), 64)
        self.assertFalse(any("body" in item for item in catalog))
        self.assertNotIn("nextCandidates", loaded)
        self.assertNotIn("risk", loaded)
        self.assertNotIn("stages", loaded)

    def test_policy_references_only_governance_metadata_not_skill_content(self) -> None:
        raw = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
        allowed_root = {"schemaVersion", "policyId", "version", "hashRule", "skills"}
        allowed_entry = {"skillId", "stages", "risk", "nextCandidates"}

        self.assertEqual(set(raw), allowed_root)
        for entry in raw["skills"]:
            self.assertLessEqual(set(entry), allowed_entry)
        serialized = json.dumps(raw, ensure_ascii=False)
        for duplicated_field in ('"description"', '"when"', '"does"', '"notFor"', '"prompt"', '"content"'):
            self.assertNotIn(duplicated_field, serialized)

    def test_real_confusions_are_excluded_by_skill_source_truth(self) -> None:
        debugging = _frontmatter(SKILLS_ROOT / "systematic-debugging/SKILL.md")
        implementation = _frontmatter(SKILLS_ROOT / "test-driven-implementation/SKILL.md")
        handoff = _frontmatter(SKILLS_ROOT / "structured-handoff/SKILL.md")
        quality = _frontmatter(SKILLS_ROOT / "quality-gate/SKILL.md")

        self.assertTrue(any("普通实现" in item for item in debugging["notFor"]))
        self.assertTrue(any("未知故障" in item for item in implementation["notFor"]))
        self.assertTrue(any("最终收口" in item for item in handoff["notFor"]))
        self.assertTrue(any("降低阈值" in item for item in quality["notFor"]))

    def test_governed_stages_select_one_exact_skill(self) -> None:
        policy = RoomSkillPolicy(POLICY_PATH, SKILLS_ROOT)

        required = policy.select_stage("requirements")
        review = policy.select_stage("review")
        missing = policy.select_stage("unknown-stage")

        self.assertEqual(required["selection"], "required")
        self.assertEqual(required["skillId"], "requirement-alignment")
        self.assertEqual(required["candidateSkillIds"], [])
        self.assertEqual(review["selection"], "required")
        self.assertEqual(review["skillId"], "independent-review")
        self.assertEqual(review["candidateSkillIds"], [])
        self.assertEqual(missing["selection"], "none")
        self.assertEqual(missing["candidateSkillIds"], [])
        for result in (required, review, missing):
            self.assertFalse(any("dispatch" in key.lower() for key in result))

    def test_next_candidates_are_advice_and_have_no_dispatch_side_effect(self) -> None:
        with tempfile.TemporaryDirectory(prefix="room-skills-next-") as tmp:
            store = RoomSkillPolicyStore(
                Path(tmp) / "room.sqlite",
                RoomSkillPolicy(POLICY_PATH, SKILLS_ROOT),
            )
            store.initialize()
            with sqlite3.connect(Path(tmp) / "room.sqlite") as conn:
                dispatch_tables = [
                    row[0]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE '%dispatch%'"
                    )
                ]
                before = {
                    name: conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
                    for name in dispatch_tables
                }
            advice = store.next_candidates("requirement-alignment")

            self.assertEqual(advice, ["solution-convergence"])
            with sqlite3.connect(Path(tmp) / "room.sqlite") as conn:
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM room_v2_skill_load_receipts").fetchone()[0],
                    0,
                )
                after = {
                    name: conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
                    for name in dispatch_tables
                }
            self.assertEqual(after, before)


class RoomSkillReceiptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="room-skill-receipts-")
        self.root = Path(self.tmp.name)
        self.skills_root = self.root / "skills"
        shutil.copytree(SKILLS_ROOT, self.skills_root)
        self.policy_path = self.root / "room-skill-policy.json"
        shutil.copy2(POLICY_PATH, self.policy_path)
        self.policy = RoomSkillPolicy(self.policy_path, self.skills_root)
        self.store = RoomSkillPolicyStore(self.root / "room.sqlite", self.policy)
        self.store.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _pin(self, **overrides: object) -> tuple[dict[str, object], bool]:
        values: dict[str, object] = {
            "receipt_id": "skill-receipt:1",
            "root_id": "root:1",
            "task_id": "task:1",
            "dispatch_id": "dispatch:1",
            "session_id": "session:1",
            "skill_id": "requirement-alignment",
            "skill_hash": self.policy.skill_hash("requirement-alignment"),
            "catalog_revision": "a" * 64,
            "load_reason": "stage_required",
            "capability_epoch": 4,
            "idempotency_key": "dispatch:1/requirements",
            "created_at_ms": 100,
        }
        values.update(overrides)
        return self.store.pin_skill(**values)  # type: ignore[arg-type]

    def _restore(
        self,
        receipt: dict[str, object],
        *,
        store: RoomSkillPolicyStore | None = None,
        **overrides: object,
    ) -> dict[str, object]:
        values: dict[str, object] = {
            "expected_root_id": receipt["rootId"],
            "expected_task_id": receipt["taskId"],
            "expected_dispatch_id": receipt["dispatchId"],
            "expected_session_id": receipt["sessionId"],
            "expected_capability_epoch": receipt["capabilityEpoch"],
            "catalog_revision": receipt["catalogRevision"],
        }
        values.update(overrides)
        return (store or self.store).restore_for_compaction(
            str(receipt["receiptId"]),
            **values,  # type: ignore[arg-type]
        )

    def test_load_receipt_pins_policy_catalog_and_body_hash_idempotently(self) -> None:
        first, created = self._pin()
        repeated, repeated_created = self._pin()

        self.assertTrue(created)
        self.assertFalse(repeated_created)
        self.assertEqual(repeated, first)
        self.assertEqual(first["schemaVersion"], "wisdom-weasel.room-skill-load-receipt.v1")
        self.assertEqual(first["catalogRevision"], "a" * 64)
        self.assertEqual(first["skillHash"], self.policy.skill_hash(str(first["skillId"])))
        self.assertEqual(first["hashRule"], "sha256-skill-body-utf8-v1")
        self.assertEqual(first["state"], "active")

    def test_compaction_restores_exact_receipt_not_stage_reselection(self) -> None:
        receipt, _ = self._pin()

        recovered = self._restore(receipt)

        self.assertEqual(recovered["restoredFromReceiptId"], receipt["receiptId"])
        self.assertEqual(recovered["skillId"], receipt["skillId"])
        self.assertEqual(recovered["skillHash"], receipt["skillHash"])
        self.assertNotIn("stage", recovered)
        self.assertNotIn("candidateSkillIds", recovered)

    def test_compaction_restore_fails_closed_on_catalog_or_content_change(self) -> None:
        receipt, _ = self._pin()

        with self.assertRaises(SkillCatalogRevisionMismatch):
            self._restore(
                receipt,
                catalog_revision="b" * 64,
            )

        path = self.skills_root / "requirement-alignment/SKILL.md"
        path.write_text(path.read_text(encoding="utf-8") + "\nchanged\n", encoding="utf-8")
        with self.assertRaises(SkillContentRevisionMismatch):
            self._restore(receipt)

    def test_compaction_restore_keeps_the_pinned_policy_version(self) -> None:
        receipt, _ = self._pin()
        raw = json.loads(self.policy_path.read_text(encoding="utf-8"))
        raw["version"] = int(raw["version"]) + 1
        self.policy_path.write_text(
            json.dumps(raw, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        changed_store = RoomSkillPolicyStore(
            self.root / "room.sqlite",
            RoomSkillPolicy(self.policy_path, self.skills_root),
        )

        with self.assertRaises(RoomSkillPolicyConflict):
            self._restore(receipt, store=changed_store)

    def test_revocation_blocks_live_use_but_preserves_exact_sealed_session(self) -> None:
        receipt, _ = self._pin()
        revoked = self.store.revoke_before_epoch(
            "root:1",
            new_capability_epoch=5,
            revoked_at_ms=200,
        )

        self.assertEqual(revoked, 1)
        self.assertEqual(
            self.store.revoke_before_epoch(
                "root:1",
                new_capability_epoch=5,
                revoked_at_ms=201,
            ),
            0,
        )
        with self.assertRaisesRegex(ValueError, "advance monotonically"):
            self.store.revoke_before_epoch(
                "root:1",
                new_capability_epoch=4,
                revoked_at_ms=202,
            )
        with self.assertRaises(RoomSkillEpochRevoked):
            self._restore(receipt)
        sealed = self._restore(receipt, allow_revoked=True)
        self.assertEqual(sealed["restoredFromReceiptId"], receipt["receiptId"])
        next_receipt, created = self._pin(
            receipt_id="skill-receipt:2",
            task_id="task:2",
            dispatch_id="dispatch:2",
            session_id="session:2",
            idempotency_key="dispatch:2/requirements",
            capability_epoch=5,
            created_at_ms=201,
        )
        self.assertTrue(created)
        self.assertEqual(next_receipt["capabilityEpoch"], 5)
        self.store.revoke_before_epoch(
            "root:1",
            new_capability_epoch=6,
            revoked_at_ms=202,
        )
        self.assertEqual(
            self._restore(receipt, allow_revoked=True)[
                "restoredFromReceiptId"
            ],
            receipt["receiptId"],
        )
        self.assertEqual(
            self._restore(next_receipt, allow_revoked=True)[
                "restoredFromReceiptId"
            ],
            next_receipt["receiptId"],
        )

    def test_sealed_restore_rejects_wrong_lineage_and_newer_session_receipt(self) -> None:
        receipt, _ = self._pin()
        self.store.revoke_before_epoch(
            "root:1",
            new_capability_epoch=5,
            revoked_at_ms=200,
        )

        for field, value in (
            ("expected_root_id", "root:other"),
            ("expected_task_id", "task:other"),
            ("expected_dispatch_id", "dispatch:other"),
            ("expected_session_id", "session:other"),
        ):
            with self.subTest(field=field), self.assertRaises(
                RoomSkillEpochRevoked
            ):
                self._restore(
                    receipt,
                    allow_revoked=True,
                    **{field: value},
                )

        self._pin(
            receipt_id="skill-receipt:session-reused",
            dispatch_id="dispatch:2",
            session_id="session:1",
            idempotency_key="dispatch:2/requirements",
            capability_epoch=5,
            created_at_ms=201,
        )
        with self.assertRaises(RoomSkillEpochRevoked):
            self._restore(receipt, allow_revoked=True)

    def test_parallel_dispatch_revocation_keeps_shared_epoch_available(self) -> None:
        first, _ = self._pin()
        second, _ = self._pin(
            receipt_id="skill-receipt:2",
            task_id="task:2",
            dispatch_id="dispatch:2",
            session_id="session:2",
            idempotency_key="dispatch:2/requirements",
            created_at_ms=101,
        )

        revoked = self.store.revoke_dispatch(
            root_id="root:1",
            dispatch_id="dispatch:1",
            session_id="session:1",
            capability_epoch=4,
            revoked_at_ms=200,
        )

        self.assertEqual(revoked, 1)
        self.assertEqual(self.store.latest_for_session("session:1")["state"], "revoked")
        self.assertEqual(self.store.latest_for_session("session:2")["state"], "active")
        restored = self._restore(second)
        self.assertEqual(restored["restoredFromReceiptId"], second["receiptId"])
        self.assertEqual(first["capabilityEpoch"], second["capabilityEpoch"])

    def test_receipt_requires_an_explicit_skill_id(self) -> None:
        selection = self.policy.select_stage("review")
        self.assertEqual(selection["selection"], "required")
        self.assertEqual(selection["skillId"], "independent-review")
        with self.assertRaisesRegex(ValueError, "explicit skillId"):
            self._pin(skill_id="")

    def test_pin_requires_the_exact_current_epoch_and_native_body_hash(self) -> None:
        self._pin()
        with self.assertRaises(RoomSkillEpochRevoked):
            self._pin(
                receipt_id="skill-receipt:future",
                dispatch_id="dispatch:future",
                idempotency_key="dispatch:future/requirements",
                capability_epoch=99,
            )
        with self.assertRaises(SkillContentRevisionMismatch):
            self._pin(
                receipt_id="skill-receipt:wrong-hash",
                dispatch_id="dispatch:wrong-hash",
                idempotency_key="dispatch:wrong-hash/requirements",
                skill_hash="f" * 64,
            )


if __name__ == "__main__":
    unittest.main()
