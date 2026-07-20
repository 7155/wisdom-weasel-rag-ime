from __future__ import annotations

import sqlite3
import unittest

from rag_ime.collaboration_profile_control import (
    COLLABORATION_PROFILE_ROUTE_HASH,
    CollaborationProfileControl,
)
from rag_ime.collaboration_profile_store import sign_profile_bundle
from rag_ime.db.migration_runner import apply_database_migrations
from rag_ime.control_api.models import ControlAccessContext, ControlRequest
from rag_ime.control_api.route_policy import default_route_policy
from rag_ime.control_api.errors import ControlApiError


class CollaborationProfileControlTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        apply_database_migrations(self.conn, applied_at_ms=1)
        self.cancelled: list[str] = []
        self.control = CollaborationProfileControl(
            self.conn,
            trusted_signers={"admin": b"profile-key"},
            baseline_capabilities=("rag", "review"),
            binding_revision="binding-9",
            cancel_root=lambda root_id, _now: self.cancelled.append(root_id) or {"ok": True},
            clock=lambda: 1_900_000_000_000,
        )

    def tearDown(self) -> None:
        self.conn.close()

    def test_all_pipeline_steps_are_typed_idempotent_and_capabilities_only_shrink(self) -> None:
        inspect = self.control.execute(self._command("inspect", payload={"bundle": self._bundle("1")}))
        duplicate = self.control.execute(self._command("inspect", payload={"bundle": self._bundle("1")}))
        self.assertEqual(duplicate["receiptId"], inspect["receiptId"])
        candidate_id = inspect["result"]["candidateId"]

        self.control.execute(self._command("validate", candidate_id=candidate_id))
        compiled = self.control.execute(self._command("compile", candidate_id=candidate_id))
        self.assertEqual(compiled["result"]["effectiveCapabilities"], ["rag", "review"])
        self.assertEqual(compiled["result"]["rejectedCapabilities"], ["control"])
        self.control.execute(self._command("dry_run", candidate_id=candidate_id))
        staged = self.control.execute(self._command("stage", candidate_id=candidate_id))
        activated = self.control.execute(
            self._command(
                "activate",
                profile_id="evidence-review",
                content_hash=staged["result"]["contentHash"],
                expected_revision=0,
                confirmation="ACTIVATE PROFILE",
            )
        )
        self.assertEqual(activated["routeHash"], COLLABORATION_PROFILE_ROUTE_HASH)
        projection = self.control.projection("evidence-review")
        self.assertTrue(projection["normalAgentFallback"])
        self.assertEqual(projection["requiredWriteScopes"], ["agent.write", "agent.approve"])

    def test_tamper_stale_revision_double_activate_and_admin_confirmation_fail_closed(self) -> None:
        tampered = self._bundle("1")
        tampered["signature"]["value"] = "hmac-sha256:" + "0" * 64
        inspected = self.control.execute(self._command("inspect", payload={"bundle": tampered}))
        with self.assertRaisesRegex(ValueError, "signature does not match"):
            self.control.execute(self._command("validate", candidate_id=inspected["result"]["candidateId"]))

        staged = self._stage("2")
        command = self._command(
            "activate", profile_id="evidence-review", content_hash=staged,
            expected_revision=0, confirmation="ACTIVATE PROFILE",
        )
        first = self.control.execute(command)
        self.assertEqual(self.control.execute(command)["receiptId"], first["receiptId"])
        changed = dict(command)
        changed["actorRef"] = "admin:other"
        with self.assertRaisesRegex(ValueError, "reused with different content"):
            self.control.execute(changed)
        with self.assertRaisesRegex(ValueError, "pointer revision changed"):
            self.control.execute(self._command(
                "activate", profile_id="evidence-review", content_hash=staged,
                expected_revision=0, confirmation="ACTIVATE PROFILE", suffix="stale",
            ))
        with self.assertRaises(PermissionError):
            self.control.execute(self._command(
                "activate", profile_id="evidence-review", content_hash=staged,
                expected_revision=1, confirmation="", suffix="no-admin",
            ))

    def test_active_root_is_pinned_and_rollback_revoke_epoch_cancel_and_fence_bindings(self) -> None:
        one = self._stage("1")
        two = self._stage("2")
        self.control.execute(self._command(
            "activate", profile_id="evidence-review", content_hash=one,
            expected_revision=0, confirmation="ACTIVATE PROFILE",
        ))
        self._active_binding(one)
        with self.assertRaisesRegex(ValueError, "active Root pins"):
            self.control.execute(self._command(
                "activate", profile_id="evidence-review", content_hash=two,
                expected_revision=1, confirmation="ACTIVATE PROFILE", suffix="pinned",
            ))
        activated = self.control.execute(self._command(
            "activate", profile_id="evidence-review", content_hash=two,
            expected_revision=1, confirmation="ACTIVATE PROFILE",
            activation_scope="new_roots_only", suffix="new-roots",
        ))
        self.assertEqual(activated["result"]["affectedRootIds"], ["root-1"])

        rolled = self.control.execute(self._command(
            "rollback", profile_id="evidence-review", expected_revision=2,
            confirmation="ROLLBACK PROFILE",
        ))
        self.assertGreaterEqual(rolled["guardEpoch"], 3)
        self.assertEqual(self.cancelled, [])  # old Root remains pinned to version one

        revoked = self.control.execute(self._command(
            "revoke", content_hash=one, expected_revision=3,
            confirmation="REVOKE PROFILE", payload={"reason": "compromised"},
        ))
        self.assertEqual(revoked["result"]["affectedRootIds"], ["root-1"])
        self.assertEqual(self.cancelled, ["root-1"])
        state, epoch = self.conn.execute(
            "SELECT state, capability_epoch FROM room_v2_capability_runtime_bindings WHERE session_id = 'session-1'"
        ).fetchone()
        self.assertEqual(state, "revoked")
        self.assertEqual(epoch, 2)

    def test_activation_pointer_and_typed_receipt_share_one_transaction(self) -> None:
        staged = self._stage("1")
        self.conn.execute(
            """CREATE TRIGGER reject_profile_command_receipt BEFORE INSERT
               ON collaboration_profile_command_receipts BEGIN SELECT RAISE(ABORT, 'receipt crash'); END"""
        )
        with self.assertRaisesRegex(sqlite3.IntegrityError, "receipt crash"):
            self.control.execute(self._command(
                "activate", profile_id="evidence-review", content_hash=staged,
                expected_revision=0, confirmation="ACTIVATE PROFILE",
            ))
        self.assertIsNone(self.control.store.active_ref("evidence-review"))

    def test_profile_routes_require_remote_auth_scopes_and_admin_confirmation(self) -> None:
        policy = default_route_policy()
        request = ControlRequest(
            request_id="profile-route",
            path_id="agent.collaborationProfile.command",
            body=self._command("inspect", payload={"bundle": self._bundle("1")}),
        )
        with self.assertRaises(ControlApiError):
            policy.authorize(
                request,
                ControlAccessContext.remote(device_id="phone", scopes={"agent.write"}),
            )
        route = policy.authorize(
            request,
            ControlAccessContext.remote(
                device_id="phone", scopes={"agent.write", "agent.approve"}
            ),
        )
        self.assertEqual(
            route.remote_scopes,
            frozenset({"agent.write", "agent.approve"}),
        )
        staged = self._stage("2")
        with self.assertRaises(PermissionError):
            self.control.execute(self._command(
                "activate", profile_id="evidence-review", content_hash=staged,
                expected_revision=0, suffix="missing-confirm",
            ))

    def _stage(self, version: str) -> str:
        inspected = self.control.execute(self._command("inspect", payload={"bundle": self._bundle(version)}, suffix=version))
        candidate = inspected["result"]["candidateId"]
        self.control.execute(self._command("validate", candidate_id=candidate, suffix=version))
        self.control.execute(self._command("compile", candidate_id=candidate, suffix=version))
        self.control.execute(self._command("dry_run", candidate_id=candidate, suffix=version))
        staged = self.control.execute(self._command("stage", candidate_id=candidate, suffix=version))
        return staged["result"]["contentHash"]

    def _active_binding(self, content_hash: str) -> None:
        self.conn.execute("INSERT INTO room_kernel_roots VALUES ('root-1','room-1',1,'running','owner','req',10,0,4,4,'[]','[]',NULL,'{}',1,1)")
        self.conn.execute("INSERT INTO room_kernel_tasks VALUES ('task-1','root-1',NULL,'running','{}',1)")
        self.conn.execute("INSERT INTO room_kernel_dispatches VALUES ('dispatch-1','root-1','task-1',NULL,1,1,1,1,'session-1','participant-1','trigger','delegation','idem','running','{}',1,1)")
        participant = '{"collaborationProfileRef":"rag-ime-definition://collaboration-profile/evidence-review?version=1&contentHash=' + content_hash + '"}'
        self.conn.execute(
            """INSERT INTO room_v2_capability_runtime_bindings VALUES
               ('session-1','manifest-1','hash','compile','plan','compiled','1','compiled-hash','{}',?,1,'active',1,1)""",
            (participant,),
        )
        self.conn.commit()

    def _bundle(self, version: str) -> dict[str, object]:
        return sign_profile_bundle(
            manifest={
                "schemaVersion": "rag-ime.collaboration-profile.v1",
                "profileId": "evidence-review", "version": version,
                "displayName": "证据复核", "summary": f"version {version}",
                "collaborationRoleRefs": ["researcher@1"],
                "capabilityRequests": ["rag", "review", "control"],
                "requiredGateIds": ["evidence-required"],
                "promptGuidance": ["区分事实与推断"], "trustTier": "signed",
            },
            files={"README.md": "声明式协作说明。"}, signer_id="admin", signing_key=b"profile-key",
        )

    def _command(
        self, action: str, *, candidate_id: str = "", profile_id: str = "",
        content_hash: str = "", expected_revision: int | None = None,
        confirmation: str = "", activation_scope: str = "immediate",
        payload: dict[str, object] | None = None, suffix: str = "",
    ) -> dict[str, object]:
        key = f"{action}-{suffix or 'default'}"
        command: dict[str, object] = {
            "schemaVersion": "rag-ime.collaboration-profile-command.v1",
            "commandId": f"profile-command:{key}", "action": action,
            "idempotencyKey": key, "actorRef": "admin:test",
            "payload": payload or {}, "createdAtMs": 1_900_000_000_000,
        }
        if candidate_id:
            command["candidateId"] = candidate_id
        if profile_id:
            command["profileId"] = profile_id
        if content_hash:
            command["contentHash"] = content_hash
        if expected_revision is not None:
            command["expectedPointerRevision"] = expected_revision
            command["activationScope"] = activation_scope
        if confirmation:
            command["adminConfirmation"] = confirmation
        return command


if __name__ == "__main__":
    unittest.main()
