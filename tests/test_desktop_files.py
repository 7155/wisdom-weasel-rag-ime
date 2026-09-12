from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from rag_ime.agent_workspace import WorkspaceHarness
from rag_ime.control_api import ControlAccessContext, ControlApiError, ControlRequest, default_route_policy
from rag_ime.control_api.route_table import find_route
from rag_ime.debug_server import DebugRequestHandler
from rag_ime.desktop_files import DesktopFiles, file_error_response


class DesktopFilesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="paw-desktop-files-")
        self.root = Path(self.temp.name).resolve()
        self.files = DesktopFiles()

    def tearDown(self):
        self.temp.cleanup()

    def test_lists_folders_and_reads_files_without_any_session(self):
        (self.root / "folder").mkdir()
        (self.root / ".hidden").mkdir()
        path = self.root / "note.txt"
        path.write_text("独立浏览", encoding="utf-8")
        listing = self.files.list({"path": str(self.root)})
        self.assertEqual([row["name"] for row in listing["items"]], [".hidden", "folder", "note.txt"])
        self.assertEqual(listing["parentPath"], str(self.root.parent))
        self.assertEqual(self.files.read({"path": str(path)})["content"], "独立浏览")

    def test_browses_absolute_file_paths_home_and_cross_directory_symlinks(self):
        folder = self.root / "another-volume"
        folder.mkdir()
        target = folder / "材料.md"
        target.write_text("# Hello", encoding="utf-8")
        alias = self.root / "alias.md"
        alias.symlink_to(target)
        read = self.files.read({"path": str(alias)})
        self.assertEqual(read["requestedPath"], str(alias))
        self.assertEqual(read["path"], str(target))
        self.assertEqual(self.files.list({"path": str(alias)})["selectedPath"], str(target))
        with patch("pathlib.Path.home", return_value=self.root):
            self.assertEqual(self.files.list({})["path"], str(self.root))

    def test_pages_directories_without_hiding_entries_after_the_limit(self):
        for name in ("a", "b", "c"):
            (self.root / name).mkdir()
        first = self.files.list({"path": str(self.root), "limit": 2})
        second = self.files.list({"path": str(self.root), "offset": first["nextOffset"], "limit": 2})
        self.assertTrue(first["truncated"])
        self.assertEqual([row["name"] for row in second["items"]], ["c"])
        self.assertFalse(second["truncated"])

    def test_utf8_paging_and_revision_change(self):
        path = self.root / "text"
        path.write_text("a中b", encoding="utf-8")
        first = self.files.read({"path": str(path), "limit": 2})
        second = self.files.read({"path": str(path), "offset": first["nextOffset"]})
        self.assertEqual(first["content"] + second["content"], "a中b")
        self.assertEqual(first["resourceRevision"], second["resourceRevision"])
        path.write_text("new", encoding="utf-8")
        self.assertNotEqual(first["resourceRevision"], self.files.read({"path": str(path)})["resourceRevision"])

    def test_session_missing_or_outside_roots_only_affects_existing_editor(self):
        owned = self.root / "owned"
        owned.mkdir()
        path = self.root / "outside.txt"
        path.write_text("outside", encoding="utf-8")
        inside = owned / "inside.txt"
        inside.write_text("inside", encoding="utf-8")
        harness = WorkspaceHarness(lsp_servers=())
        def permission(session_id, target):
            if session_id == "missing":
                raise KeyError(session_id)
            return harness.file_editability({"id": session_id, "mode": "coordinator", "workspaceRoots": [str(owned)]}, target)
        files = DesktopFiles(editability=permission)
        try:
            for session_id in ("missing", "session-1"):
                read = files.read({"path": str(path), "sessionId": session_id})
                self.assertEqual(read["content"], "outside")
                self.assertFalse(read["editability"]["editable"])
            read = files.read({"path": str(inside), "sessionId": "session-1"})
            self.assertTrue(read["editability"]["editable"])
            self.assertTrue(read["resourceRevision"].startswith("sha256:"))
        finally:
            harness.close_lsp()

    def test_refuses_special_files_and_reports_system_errors_without_session_language(self):
        pipe = self.root / "pipe"
        os.mkfifo(pipe)
        with self.assertRaisesRegex(ValueError, "管道"):
            self.files.read({"path": str(pipe)})
        with self.assertRaisesRegex(ValueError, "绝对路径"):
            self.files.list({"path": "relative"})
        self.assertEqual(file_error_response(PermissionError())[0], 403)
        self.assertNotIn("Session", file_error_response(PermissionError())[1]["error"])

    def test_real_descriptor_dispatch_and_routes_are_local_only(self):
        path = self.root / "note.txt"
        path.write_text("through handler", encoding="utf-8")
        handler = DebugRequestHandler.__new__(DebugRequestHandler)
        handler.service = SimpleNamespace(desktop_files=self.files)
        output = []
        handler._write_json = lambda status, value: output.append((status, value))
        for path_id, route in (("files.list", "/api/files/list"), ("files.read", "/api/files/read")):
            spec = find_route("GET", route)
            handler._dispatch_descriptor_route(spec, query={"path": [str(path)]})
            self.assertTrue(output[-1][1]["ok"])
            with self.assertRaises(ControlApiError):
                default_route_policy().authorize(ControlRequest(request_id="local-files-test", path_id=path_id, query={"path": str(path)}),
                    ControlAccessContext.remote(device_id="phone", scopes={"*"}))
        self.assertEqual(output[-1][1]["content"], "through handler")


if __name__ == "__main__":
    unittest.main()
