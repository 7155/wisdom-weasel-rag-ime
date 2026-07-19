from __future__ import annotations

import sqlite3
import unittest

from rag_ime.collaboration_profile_store import (
    CollaborationProfileStore,
    sign_profile_bundle,
)
from rag_ime.db.migration_runner import apply_database_migrations


class CollaborationProfileStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        apply_database_migrations(self.conn, applied_at_ms=1)
        self.store = CollaborationProfileStore(
            self.conn,
            trusted_signers={"builtin-test": b"fixture-signing-key"},
            clock=lambda: 1_800_000_000_000,
        )

    def tearDown(self) -> None:
        self.conn.close()

    def test_pipeline_is_ordered_content_addressed_and_can_only_shrink_capabilities(self) -> None:
        candidate = self.store.inspect(self._bundle(version="1", capabilities=["rag", "review", "control"]))
        self.assertEqual(candidate["stage"], "inspected")
        with self.assertRaisesRegex(ValueError, "requires validated"):
            self.store.compile(
                candidate["candidateId"], baseline_capabilities=("rag",),
                binding_revision="binding-revision-7",
            )
        self.assertEqual(self.store.validate(candidate["candidateId"])["stage"], "validated")
        compilation = self.store.compile(
            candidate["candidateId"],
            baseline_capabilities=("memory", "rag", "review"),
            binding_revision="binding-revision-7",
        )
        self.assertEqual(compilation["effectiveCapabilities"], ["rag", "review"])
        self.assertEqual(compilation["rejectedCapabilities"], ["control"])
        self.assertEqual(compilation["schemaVersion"], "rag-ime.collaboration-profile-compile-receipt.v1")
        self.assertEqual(self.store.dry_run(candidate["candidateId"])["stage"], "dry_run")
        staged = self.store.stage(candidate["candidateId"])
        self.assertEqual(staged["contentHash"], candidate["contentHash"])

        activated = self.store.activate(
            profile_id="evidence-review",
            content_hash=candidate["contentHash"],
            expected_pointer_revision=0,
        )
        self.assertEqual(activated["pointerRevision"], 1)
        self.assertEqual(self.store.active_ref("evidence-review")["contentHash"], candidate["contentHash"])
        inspection = self.store.inspect_profile("evidence-review")
        self.assertEqual(inspection["active"]["compileReceiptId"], compilation["receiptId"])
        self.assertEqual(inspection["versions"][0]["manifest"]["summary"], "研究与独立复核")

    def test_same_profile_version_cannot_be_overwritten_and_packages_reject_executable_paths(self) -> None:
        first = self._stage(self._bundle(version="1", summary="first"))
        duplicate_name = self._bundle(version="1", summary="different bytes")
        candidate = self.store.inspect(duplicate_name)
        self.store.validate(candidate["candidateId"])
        self.store.compile(candidate["candidateId"], baseline_capabilities=("rag",), binding_revision="binding-1")
        self.store.dry_run(candidate["candidateId"])
        with self.assertRaisesRegex(ValueError, "same profile version"):
            self.store.stage(candidate["candidateId"])
        self.assertTrue(first["contentHash"].startswith("sha256:"))

        for unsafe_files in (
            {"../escape.md": "bad"}, {"nested//alias.md": "bad"},
            {"hooks/run.sh": "bad"}, {"plugin.js": "bad"},
        ):
            with self.subTest(files=unsafe_files):
                with self.assertRaisesRegex(ValueError, "unsafe|executable"):
                    self.store.inspect(self._bundle(version="2", files=unsafe_files))

    def test_validation_rejects_non_strict_manifest_and_tampered_signature(self) -> None:
        extra = self._bundle(version="3")
        extra["manifest"]["entrypoint"] = "run.js"
        candidate = self.store.inspect(extra)
        with self.assertRaisesRegex(ValueError, "fields are not strict"):
            self.store.validate(candidate["candidateId"])

        tampered = self._bundle(version="4")
        tampered["signature"]["value"] = "hmac-sha256:" + "0" * 64
        candidate = self.store.inspect(tampered)
        with self.assertRaisesRegex(ValueError, "signature does not match"):
            self.store.validate(candidate["candidateId"])

    def test_activation_is_atomic_on_crash_and_rollback_restores_previous_version(self) -> None:
        version_one = self._stage(self._bundle(version="1", summary="one"))
        version_two = self._stage(self._bundle(version="2", summary="two"))
        self.store.activate(
            profile_id="evidence-review", content_hash=version_one["contentHash"],
            expected_pointer_revision=0,
        )

        with self.assertRaisesRegex(RuntimeError, "simulated activation crash"):
            self.store.activate(
                profile_id="evidence-review", content_hash=version_two["contentHash"],
                expected_pointer_revision=1, _fail_after_pointer=True,
            )
        self.assertEqual(self.store.active_ref("evidence-review")["contentHash"], version_one["contentHash"])
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM collaboration_profile_activation_receipts").fetchone()[0],
            1,
        )

        activated = self.store.activate(
            profile_id="evidence-review", content_hash=version_two["contentHash"],
            expected_pointer_revision=1,
        )
        rolled_back = self.store.rollback(
            profile_id="evidence-review", expected_pointer_revision=activated["pointerRevision"],
        )
        self.assertEqual(rolled_back["activeContentHash"], version_one["contentHash"])

    def test_activation_does_not_hot_swap_existing_root_binding_and_revoke_blocks_new_bindings(self) -> None:
        version_one = self._stage(self._bundle(version="1", summary="one"), binding_revision="binding-revision-1")
        version_two = self._stage(self._bundle(version="2", summary="two"), binding_revision="binding-revision-2")
        self.store.activate(profile_id="evidence-review", content_hash=version_one["contentHash"], expected_pointer_revision=0)
        old_root_binding = {
            "rootId": "root-existing",
            "profileContentHash": version_one["contentHash"],
            "bindingRevision": "binding-revision-1",
        }
        activated = self.store.activate(profile_id="evidence-review", content_hash=version_two["contentHash"], expected_pointer_revision=1)

        self.assertEqual(old_root_binding["profileContentHash"], version_one["contentHash"])
        self.assertEqual(old_root_binding["bindingRevision"], "binding-revision-1")
        self.assertEqual(self.store.active_ref("evidence-review")["contentHash"], version_two["contentHash"])

        revoked = self.store.revoke(
            content_hash=version_two["contentHash"], reason="test compromise",
            expected_pointer_revision=activated["pointerRevision"],
        )
        self.assertTrue(revoked["revoked"])
        self.assertIsNone(self.store.active_ref("evidence-review"))
        with self.assertRaisesRegex(ValueError, "revoked"):
            self.store.activate(
                profile_id="evidence-review", content_hash=version_two["contentHash"],
                expected_pointer_revision=revoked["pointerRevision"],
            )

    def _stage(self, bundle: dict[str, object], *, binding_revision: str = "binding-revision-1") -> dict[str, object]:
        candidate = self.store.inspect(bundle)
        self.store.validate(candidate["candidateId"])
        self.store.compile(candidate["candidateId"], baseline_capabilities=("memory", "rag", "review"), binding_revision=binding_revision)
        self.store.dry_run(candidate["candidateId"])
        return self.store.stage(candidate["candidateId"])

    def _bundle(
        self,
        *,
        version: str,
        summary: str = "研究与独立复核",
        capabilities: list[str] | None = None,
        files: dict[str, str] | None = None,
    ) -> dict[str, object]:
        manifest = {
            "schemaVersion": "rag-ime.collaboration-profile.v1",
            "profileId": "evidence-review",
            "version": version,
            "displayName": "证据研究与独立复核",
            "summary": summary,
            "collaborationRoleRefs": ["researcher@1", "reviewer@1"],
            "capabilityRequests": capabilities or ["rag", "review"],
            "requiredGateIds": ["evidence-required", "peer-review-required"],
            "promptGuidance": ["区分事实与推断", "引用可见证据"],
            "trustTier": "builtin",
        }
        return sign_profile_bundle(
            manifest=manifest,
            files=files if files is not None else {"README.md": "只包含声明式说明。"},
            signer_id="builtin-test",
            signing_key=b"fixture-signing-key",
        )


if __name__ == "__main__":
    unittest.main()
