from __future__ import annotations

import hashlib
import tempfile
import unittest
from http import HTTPStatus
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from rag_ime.agent_tools import ControlToolGateway
from rag_ime.agent_tool_ids import FULL_ACCESS_TOOL_PROFILE
from rag_ime.agent_workspace import WorkspaceHarness, WorkspaceHarnessError
from rag_ime.control_api import ControlAccessContext, ControlApiError, ControlRequest, default_route_policy
from rag_ime.debug_server import DebugRequestHandler


class WorkspaceFileEditorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="paw-files-editor-")
        self.root = Path(self.temp.name).resolve() / "workspace"
        self.root.mkdir()
        self.path = self.root / "notes.md"
        self.path.write_bytes(b"first\r\n")
        self.path.chmod(0o640)
        self.session = {"id": "agent:files", "mode": "coordinator", "workspaceRoots": [str(self.root)]}
        self.harness = WorkspaceHarness(lsp_servers=())
        self.gateway = ControlToolGateway.__new__(ControlToolGateway)
        self.gateway.sessions = SimpleNamespace(get=lambda session_id: self.session)
        self.gateway.workspace_harness = self.harness

    def tearDown(self) -> None:
        self.harness.close_lsp()
        self.temp.cleanup()

    def read(self):
        return self.gateway.workspace_read("agent:files", {"path": str(self.path)})

    def save(self, revision: str, content: str = "saved 澄\r\n"):
        return self.gateway.workspace_save("agent:files", {
            "path": str(self.path), "content": content, "resourceRevision": revision,
        })

    def test_explicit_save_updates_real_file_and_returns_new_revision(self) -> None:
        original = self.read()
        self.assertTrue(original["editability"]["editable"])
        receipt = self.save(original["resourceRevision"])
        self.assertEqual(self.path.read_bytes(), "saved 澄\r\n".encode())
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o640)
        self.assertEqual(receipt["sessionId"], "agent:files")
        self.assertEqual(receipt["path"], str(self.path))
        self.assertEqual(receipt["resourceRevision"], "sha256:" + hashlib.sha256(self.path.read_bytes()).hexdigest())
        self.assertTrue(receipt["saved"])

    def test_alias_read_binds_request_to_canonical_target_and_saves_without_replacing_link(self) -> None:
        alias = self.root / "alias.md"
        alias.symlink_to(self.path)
        read = self.gateway.workspace_read("agent:files", {"path": str(alias)})
        self.assertEqual(read["requestedPath"], str(alias))
        self.assertEqual(read["path"], str(self.path))
        self.assertEqual(read["sessionId"], "agent:files")
        self.assertTrue(read["editability"]["editable"])
        receipt = self.gateway.workspace_save("agent:files", {"path": read["path"], "content": "through alias\n", "resourceRevision": read["resourceRevision"]})
        self.assertEqual(receipt["path"], str(self.path))
        self.assertEqual(self.path.read_text(), "through alias\n")
        self.assertTrue(alias.is_symlink())
        with self.assertRaisesRegex(WorkspaceHarnessError, "symlink"):
            self.gateway.workspace_save("agent:files", {"path": str(alias), "content": "must not replace link", "resourceRevision": receipt["resourceRevision"]})

    def test_alias_identity_does_not_bypass_read_only_or_authorized_roots(self) -> None:
        alias = self.root / "alias.md"
        alias.symlink_to(self.path)
        self.session["executionMode"] = "read_only"
        read = self.gateway.workspace_read("agent:files", {"path": str(alias)})
        self.assertFalse(read["editability"]["editable"])
        with self.assertRaises(WorkspaceHarnessError):
            self.gateway.workspace_save("agent:files", {"path": read["path"], "content": "blocked", "resourceRevision": read["resourceRevision"]})
        outside = Path(self.temp.name).resolve() / "outside.md"
        outside.write_text("outside", encoding="utf-8")
        alias.unlink()
        alias.symlink_to(outside)
        with self.assertRaises(WorkspaceHarnessError):
            self.gateway.workspace_read("agent:files", {"path": str(alias)})
        self.assertEqual(self.path.read_bytes(), b"first\r\n")

    def test_external_change_rejects_stale_save_even_in_full_access_mode(self) -> None:
        for policy in ({}, {"toolProfileVersion": FULL_ACCESS_TOOL_PROFILE, "executionMode": "per_action"}):
            with self.subTest(policy=policy):
                self.session.update(policy)
                self.path.write_text("first", encoding="utf-8")
                revision = self.read()["resourceRevision"]
                self.path.write_text("external", encoding="utf-8")
                with self.assertRaises(WorkspaceHarnessError) as raised:
                    self.save(revision)
                self.assertEqual(getattr(raised.exception, "code", ""), "stale_snapshot")
                self.assertEqual(self.path.read_text(), "external")

    def test_explicit_editor_save_does_not_inherit_the_unused_tool_diff_preview_limit(self) -> None:
        self.path.write_text("a" * 70_000 + "\n", encoding="utf-8")
        original = self.read()
        self.assertTrue(original["editability"]["editable"])
        updated = "b" * 70_000 + "\n"
        receipt = self.save(original["resourceRevision"], updated)
        self.assertTrue(receipt["saved"])
        self.assertEqual(self.path.read_text(), updated)
        # Tool callers still own their existing bounded, reviewable diff contract.
        with self.assertRaisesRegex(WorkspaceHarnessError, "diff is too large"):
            self.harness.prepare_write(self.session, {"path": str(self.path), "content": "c" * 70_000 + "\n", "resourceRevision": receipt["resourceRevision"]})

    def test_read_only_policy_or_disk_permissions_are_truthful_and_enforced(self) -> None:
        for source in ("session", "file"):
            with self.subTest(source=source):
                self.session.pop("executionMode", None)
                self.path.chmod(0o640)
                if source == "session":
                    self.session["executionMode"] = "read_only"
                else:
                    self.path.chmod(0o444)
                read = self.read()
                self.assertFalse(read["editability"]["editable"])
                with self.assertRaises(WorkspaceHarnessError):
                    self.save(read["resourceRevision"])
                self.assertEqual(self.path.read_bytes(), b"first\r\n")

    def test_save_rejects_missing_revision_outside_symlink_binary_and_deleted_file(self) -> None:
        revision = self.read()["resourceRevision"]
        with self.assertRaises(WorkspaceHarnessError):
            self.save("")
        outside = Path(self.temp.name) / "outside.txt"
        outside.write_text("outside", encoding="utf-8")
        link = self.root / "link.md"
        link.symlink_to(outside)
        for target in (outside, link):
            with self.subTest(target=target), self.assertRaises(WorkspaceHarnessError):
                self.gateway.workspace_save("agent:files", {"path": str(target), "content": "bad", "resourceRevision": revision})
        self.path.write_bytes(b"binary\x00")
        with self.assertRaises(WorkspaceHarnessError):
            self.save("sha256:" + hashlib.sha256(self.path.read_bytes()).hexdigest())
        self.path.unlink()
        with self.assertRaises(WorkspaceHarnessError):
            self.save(revision)
        self.assertFalse(self.path.exists())
        self.assertEqual(outside.read_text(), "outside")

    def test_change_while_temporary_file_is_flushed_does_not_get_overwritten(self) -> None:
        revision = self.read()["resourceRevision"]
        with patch("rag_ime.agent_workspace.os.fsync", side_effect=lambda _fd: self.path.write_text("late external", encoding="utf-8")):
            with self.assertRaises(WorkspaceHarnessError):
                self.save(revision)
        self.assertEqual(self.path.read_text(), "late external")
        self.assertEqual([path.name for path in self.root.iterdir()], ["notes.md"])

    def test_local_route_forwards_save_and_returns_classified_conflict(self) -> None:
        handler = DebugRequestHandler.__new__(DebugRequestHandler)
        handler.service = SimpleNamespace(agent_tools=self.gateway)
        handler._authorize_gateway_request = lambda _method, _parsed: True
        handler._management_post_security_error = lambda _path, require_json=True: None
        written = []
        handler._write_json = lambda status, body: written.append((status, body))
        original = self.read()["resourceRevision"]
        handler.path = "/api/agent/sessions/agent%3Afiles/workspace-file"
        handler._read_json = lambda: {"path": str(self.path), "content": "new", "resourceRevision": original}
        handler.do_POST()
        self.assertEqual(written[-1][0], HTTPStatus.OK)
        self.assertEqual(self.path.read_text(), "new")
        handler.do_POST()
        self.assertEqual(written[-1][0], HTTPStatus.CONFLICT)
        self.assertEqual(written[-1][1]["errorCode"], "stale_snapshot")

    def test_route_contract_requires_snapshot_and_stays_local(self) -> None:
        policy = default_route_policy()
        request = ControlRequest(request_id="file-save", path_id="agent.session.workspace.save", params={"sessionId": "agent:files"}, body={"path": str(self.path), "content": "new", "resourceRevision": "sha256:" + "a" * 64})
        policy.authorize(request, ControlAccessContext.native())
        route = policy.resolve(request.path_id)
        self.assertFalse(route.remote_safe)
        self.assertIsNone(route.gateway_8768_path)
        with self.assertRaises(ControlApiError):
            policy.authorize(ControlRequest(request_id="file-missing-version", path_id=request.path_id, params=request.params, body={"path": str(self.path), "content": "new"}), ControlAccessContext.native())


if __name__ == "__main__":
    unittest.main()
