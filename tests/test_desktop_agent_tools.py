from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rag_ime.agent_sessions import AgentSessionStore
from rag_ime.agent_tools import ControlToolGateway
from rag_ime.desktop_bridge import DesktopBridgeError


class _DesktopClient:
    def __init__(self) -> None:
        self.applied: list[dict[str, object]] = []
        self.stale = False

    def list_applications(self, *, include_background: bool):
        return {
            "schemaVersion": "rag-ime.desktop-application-list.v1",
            "captureMode": "accessibility_semantics",
            "items": [{"pid": 42, "bundleId": "com.example.Editor", "windows": []}],
            "includeBackground": include_background,
        }

    def status(self):
        return {
            "schemaVersion": "rag-ime.desktop-bridge-status.v1",
            "accessibilityTrusted": True,
            "captureMode": "accessibility_semantics",
            "usesScreenCapture": False,
        }

    def inspect(self, **_kwargs):
        return {
            "schemaVersion": "rag-ime.desktop-snapshot.v1",
            "snapshotId": "axsnap_1",
            "revision": 7,
            "captureMode": "accessibility_semantics",
            "nodes": [
                {
                    "nodeRef": "ax_button",
                    "role": "AXButton",
                    "label": "发送",
                    "actions": ["press"],
                }
            ],
            "diff": {"fullSnapshot": True, "added": ["ax_button"]},
        }

    def prepare_action(self, **kwargs):
        return {
            "schemaVersion": "rag-ime.desktop-action-preview.v1",
            "summary": "在编辑器的发送按钮执行 press",
            "actionPayload": {
                "snapshotId": kwargs["snapshot_id"],
                "revision": kwargs["revision"],
                "nodeRef": kwargs["node_ref"],
                "action": kwargs["action"],
                "pid": 42,
                "bundleId": "com.example.Editor",
            },
            "baseState": {
                "snapshotId": kwargs["snapshot_id"],
                "revision": kwargs["revision"],
                "nodeStateSha256": "a" * 64,
                "applicationStateSha256": "b" * 64,
            },
        }

    def act(self, *, action_payload, base_state):
        if self.stale:
            raise DesktopBridgeError("stale_state", "desktop_changed_after_snapshot")
        self.applied.append(
            {"actionPayload": dict(action_payload), "baseState": dict(base_state)}
        )
        return {
            "schemaVersion": "rag-ime.desktop-action-receipt.v1",
            "applied": True,
            "postSnapshot": {"snapshotId": "axsnap_2", "revision": 8},
        }


class DesktopAgentToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.store = AgentSessionStore(Path(self.temporary.name) / "agent.sqlite")
        self.store.initialize()
        self.session = self.store.create(title="desktop", created_at_ms=1)
        self.desktop = _DesktopClient()
        self.gateway = ControlToolGateway(
            sessions=self.store,
            management=object(),
            core=object(),
            project="test",
            desktop_client=self.desktop,
        )

    def call(self, operation: str, **args: object) -> dict[str, object]:
        return {
            "schemaVersion": "rag-ime.agent-tool-call.v1",
            "sessionId": self.session["id"],
            "tool": "desktop_semantic",
            "toolCallId": f"call:{operation}",
            "args": {"op": operation, **args},
        }

    def test_read_operations_return_semantics_without_approval(self) -> None:
        status = self.gateway.execute(self.call("status"))["result"]
        listed = self.gateway.execute(self.call("list"))["result"]
        inspected = self.gateway.execute(self.call("inspect", bundleId="com.example.Editor"))[
            "result"
        ]

        self.assertTrue(status["accessibilityTrusted"])
        self.assertFalse(status["usesScreenCapture"])
        self.assertEqual(listed["captureMode"], "accessibility_semantics")
        self.assertEqual(inspected["snapshotId"], "axsnap_1")
        self.assertEqual(inspected["nodes"][0]["label"], "发送")

    def test_action_is_hash_bound_and_runs_only_after_native_approval(self) -> None:
        prepared = self.gateway.execute(
            self.call(
                "act",
                snapshotId="axsnap_1",
                revision=7,
                nodeRef="ax_button",
                action="press",
            )
        )["result"]

        self.assertTrue(prepared["approvalRequired"])
        self.assertEqual(self.desktop.applied, [])
        approval = prepared["approval"]
        decided = self.store.decide_approval(
            approval["approvalId"],
            approved=True,
            payload_sha256=approval["payloadSha256"],
        )
        receipt = self.gateway.apply_approval(decided)

        self.assertTrue(receipt["receipt"]["applied"])
        self.assertEqual(len(self.desktop.applied), 1)
        self.assertEqual(
            self.desktop.applied[0]["baseState"]["nodeStateSha256"],
            "a" * 64,
        )

    def test_full_trust_model_approval_executes_the_hash_bound_action_without_a_dialog(self) -> None:
        workspace = Path(self.temporary.name) / "workspace"
        workspace.mkdir()
        trusted = self.store.create(
            title="trusted desktop",
            mode="coordinator",
            execution_mode="full_trust",
            workspace_roots=[str(workspace)],
            created_at_ms=2,
        )
        applied_approvals: list[str] = []

        def auto_approve(approval):
            applied_approvals.append(str(approval["approvalId"]))
            decided = self.store.decide_approval(
                str(approval["approvalId"]),
                approved=True,
                payload_sha256=str(approval["payloadSha256"]),
                decided_by="approval-model:test",
            )
            receipt = self.gateway.apply_approval(decided)
            return {
                "summary": receipt["summary"],
                "approvalRequired": False,
                "autoApproved": True,
                "approvalId": approval["approvalId"],
                "receipt": receipt,
                "modelDecided": True,
                "decisionMode": "model",
            }

        self.gateway.bind_auto_approval_executor(auto_approve)
        request = self.call(
            "act",
            snapshotId="axsnap_1",
            revision=7,
            nodeRef="ax_button",
            action="press",
        )
        request["sessionId"] = trusted["id"]
        result = self.gateway.execute(request)["result"]

        self.assertFalse(result["approvalRequired"])
        self.assertTrue(result["autoApproved"])
        self.assertEqual(len(applied_approvals), 1)
        self.assertEqual(len(self.desktop.applied), 1)

    def test_stale_desktop_state_never_retargets(self) -> None:
        prepared = self.gateway.execute(
            self.call(
                "act",
                snapshotId="axsnap_1",
                revision=7,
                nodeRef="ax_button",
                action="press",
            )
        )["result"]
        approval = prepared["approval"]
        decided = self.store.decide_approval(
            approval["approvalId"],
            approved=True,
            payload_sha256=approval["payloadSha256"],
        )
        self.desktop.stale = True

        with self.assertRaisesRegex(DesktopBridgeError, "stale_state"):
            self.gateway.apply_approval(decided)
        self.assertEqual(self.desktop.applied, [])


if __name__ == "__main__":
    unittest.main()
