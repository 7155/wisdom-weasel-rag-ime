from __future__ import annotations

import stat
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from pathlib import Path

from rag_ime.agent_workspace import (
    WorkspaceHarness,
    WorkspaceLspError,
    WorkspaceLspServerConfig,
    _lsp_references_evidence_digest,
    _lsp_sandbox_profile,
)
from rag_ime.contracts.json_schema import validate_contract


_FAKE_SERVER = r'''
import json
import os
import sys
import time
from pathlib import Path

root_uri = ""

def read_message():
    headers = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        if line == b"\r\n":
            break
        name, value = line.decode("ascii").split(":", 1)
        headers[name.lower()] = value.strip()
    return json.loads(sys.stdin.buffer.read(int(headers["content-length"])))

def send(message):
    body = json.dumps(message, separators=(",", ":")).encode()
    sys.stdout.buffer.write(f"Content-Length: {len(body)}\r\n\r\n".encode() + body)
    sys.stdout.buffer.flush()

while True:
    message = read_message()
    if message is None:
        break
    method = message.get("method", "")
    params = message.get("params", {})
    if method:
        with Path(".lsp-methods.log").open("a", encoding="utf-8") as log:
            log.write(method + "\n")
    if "id" not in message:
        if method == "exit":
            break
        continue
    if method == "initialize":
        root_uri = params["rootUri"]
        result = {"capabilities": {"hoverProvider": True, "renameProvider": True}}
    elif method == "shutdown":
        result = None
    elif method == "workspace/symbol":
        result = [{
            "name": "foo",
            "kind": 12,
            "location": {
                "uri": root_uri + "/main.py",
                "range": {"start": {"line": 0, "character": 2}, "end": {"line": 0, "character": 5}},
            },
        }]
    elif method == "textDocument/hover":
        uri = params["textDocument"]["uri"]
        if uri.endswith("timeout.py"):
            time.sleep(1)
        result = {"contents": {"kind": "markdown", "value": "`foo: int`"}}
    elif method == "textDocument/definition":
        result = [{
            "uri": root_uri + "/main.py",
            "range": {"start": {"line": 0, "character": 2}, "end": {"line": 0, "character": 5}},
        }]
    elif method == "textDocument/references":
        result = [{
            "uri": root_uri + "/main.py",
            "range": {"start": {"line": 0, "character": 2}, "end": {"line": 0, "character": 5}},
        }]
    elif method == "textDocument/diagnostic":
        result = {"items": [{
            "range": {"start": {"line": 0, "character": 2}, "end": {"line": 0, "character": 5}},
            "severity": 2,
            "message": "fake warning",
            "source": "fake-lsp",
        }]}
    elif method == "textDocument/rename":
        uri = params["textDocument"]["uri"]
        result = {"changes": {uri: [{
            "range": {"start": {"line": 0, "character": 2}, "end": {"line": 0, "character": 5}},
            "newText": params["newName"],
        }]}}
    elif method == "textDocument/codeAction":
        uri = params["textDocument"]["uri"]
        if uri.endswith("command.py"):
            result = [{"title": "unsafe", "command": {"command": "fake.run"}}]
        else:
            result = [{"title": "fix", "edit": {"changes": {uri: [{
                "range": {"start": {"line": 0, "character": 2}, "end": {"line": 0, "character": 5}},
                "newText": "fixed",
            }]}}}]
    else:
        send({"jsonrpc": "2.0", "id": message["id"], "error": {"code": -32601, "message": "unsupported"}})
        continue
    send({"jsonrpc": "2.0", "id": message["id"], "result": result})
'''


class WorkspaceLspHarnessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="rag-ime-lsp-")
        self.root = Path(self.temp.name) / "project"
        self.root.mkdir()
        (self.root / "pyproject.toml").write_text("[project]\nname='fake'\n", encoding="utf-8")
        self.main = self.root / "main.py"
        self.main.write_text("😀foo\n", encoding="utf-8")
        self.timeout_file = self.root / "timeout.py"
        self.timeout_file.write_text("😀foo\n", encoding="utf-8")
        self.command_file = self.root / "command.py"
        self.command_file.write_text("😀foo\n", encoding="utf-8")
        self.server_script = self.root / "fake_lsp.py"
        self.server_script.write_text(textwrap.dedent(_FAKE_SERVER), encoding="utf-8")
        self.config = WorkspaceLspServerConfig(
            name="fake",
            command=(sys.executable, str(self.server_script)),
            language_ids=("python",),
            file_extensions=(".py",),
            root_markers=("pyproject.toml",),
        )
        self.session = {
            "id": "session:lsp",
            "mode": "coordinator",
            "workspaceRoots": [str(self.root)],
        }
        self.harness = WorkspaceHarness(
            lsp_servers=(self.config,),
            lsp_process_sandbox=False,
            lsp_idle_timeout_seconds=1,
        )

    def tearDown(self) -> None:
        self.harness.close_lsp()
        self.temp.cleanup()

    def test_readonly_operations_are_bounded_and_need_no_approval(self) -> None:
        status = self.harness.lsp_status(self.session, {})
        self.assertEqual(status["state"], "available")
        self.assertIn(status["state"], {"ready", "available", "degraded", "unavailable"})
        validate_contract(status, "workspace-lsp-status.v1.json")
        self.assertTrue(status["current"])
        self.assertRegex(status["runtimeInstanceId"], r"^workspace-lsp-[0-9a-f]{32}$")
        self.assertGreater(status["heartbeatExpiresAtMs"], status["observedAtMs"])

        symbols = self.harness.lsp_read(self.session, "symbols", {"query": "foo"})
        hover = self.harness.lsp_read(
            self.session,
            "hover",
            {"path": str(self.main), "line": 1, "column": 3},
        )
        definition = self.harness.lsp_read(
            self.session,
            "definition",
            {"path": str(self.main), "line": 1, "column": 3},
        )
        references = self.harness.lsp_read(
            self.session,
            "references",
            {"path": str(self.main), "line": 1, "column": 3},
        )
        diagnostics = self.harness.lsp_read(
            self.session,
            "diagnostics",
            {"path": str(self.main)},
        )

        for result in (symbols, hover, definition, references, diagnostics):
            validate_contract(result, "workspace-lsp-result.v1.json")
        self.assertEqual(symbols["items"][0]["name"], "foo")
        self.assertEqual(hover["content"], "`foo: int`")
        self.assertEqual(definition["items"][0]["relativePath"], "main.py")
        self.assertEqual(references["items"][0]["column"], 3)
        self.assertEqual(diagnostics["items"][0]["severity"], "warning")
        self.assertEqual(self.harness.lsp_status(self.session, {})["state"], "ready")

    def test_passive_status_does_not_crawl_markerless_workspaces(self) -> None:
        (self.root / "pyproject.toml").unlink()

        status = self.harness.lsp_status(self.session, {})

        self.assertEqual(status["state"], "unavailable")
        self.assertEqual(status["roots"][0]["servers"], [])
        hover = self.harness.lsp_read(
            self.session,
            "hover",
            {"path": str(self.main), "line": 1, "column": 3},
        )
        self.assertEqual(hover["content"], "`foo: int`")
        self.assertEqual(self.harness.lsp_status(self.session, {})["state"], "ready")


    def test_runtime_projection_epoch_and_heartbeat_invalidate_closed_lifecycle(self) -> None:
        initial = self.harness.lsp_status(self.session, {})
        cancelled_epoch = initial["runtimeEpoch"] + 1

        self.harness.cancel_lsp(self.root)
        after_cancel = self.harness.lsp_status(self.session, {})
        self.assertEqual(after_cancel["runtimeInstanceId"], initial["runtimeInstanceId"])
        self.assertEqual(after_cancel["runtimeEpoch"], cancelled_epoch)
        self.assertTrue(after_cancel["current"])

        self.harness.close_lsp()
        closed = self.harness.lsp_status(self.session, {})
        self.assertEqual(closed["runtimeInstanceId"], initial["runtimeInstanceId"])
        self.assertEqual(closed["runtimeEpoch"], cancelled_epoch + 1)
        self.assertFalse(closed["current"])
        self.assertEqual(closed["state"], "unavailable")
        self.assertEqual(closed["heartbeatExpiresAtMs"], closed["observedAtMs"])
        self.assertTrue(all(root["state"] == "unavailable" for root in closed["roots"]))
        validate_contract(closed, "workspace-lsp-status.v1.json")

    def test_utf16_rename_is_hash_bound_and_stale_files_are_rejected(self) -> None:
        prepared = self.harness.prepare_lsp_mutation(
            self.session,
            "rename",
            {"path": str(self.main), "line": 1, "column": 3, "newName": "bar"},
        )
        self.assertEqual(prepared.files[0].postimage.decode("utf-8"), "😀bar\n")
        preview = self.harness.lsp_mutation_preview(prepared)
        receipt = self.harness.apply_lsp_mutation(
            self.session,
            "rename",
            preview["actionPayload"],
            preview["baseState"],
        )
        self.assertTrue(receipt["mutationApplied"])
        references_evidence = receipt["referencesEvidence"]
        self.assertEqual(references_evidence["root"], str(self.root.resolve()))
        self.assertEqual(references_evidence["path"], str(self.main.resolve()))
        self.assertEqual(references_evidence["line"], 1)
        self.assertEqual(references_evidence["column"], 3)
        self.assertEqual(references_evidence["resourceRevision"].startswith("sha256:"), True)
        self.assertEqual(references_evidence["count"], 1)
        self.assertLess(
            (self.root / ".lsp-methods.log").read_text(encoding="utf-8").splitlines().index(
                "textDocument/references"
            ),
            (self.root / ".lsp-methods.log").read_text(encoding="utf-8").splitlines().index(
                "textDocument/rename"
            ),
        )
        validate_contract(receipt, "workspace-lsp-mutation-receipt.v1.json")
        self.assertEqual(self.main.read_text(encoding="utf-8"), "😀bar\n")

        self.main.write_text("😀foo\n", encoding="utf-8")
        code_action = self.harness.prepare_lsp_mutation(
            self.session,
            "code_action_apply",
            {"path": str(self.main), "line": 1, "column": 3, "title": "fix"},
        )
        code_action_preview = self.harness.lsp_mutation_preview(code_action)
        code_action_receipt = self.harness.apply_lsp_mutation(
            self.session,
            "code_action_apply",
            code_action_preview["actionPayload"],
            code_action_preview["baseState"],
        )
        validate_contract(
            code_action_receipt,
            "workspace-lsp-mutation-receipt.v1.json",
        )
        self.assertEqual(self.main.read_text(encoding="utf-8"), "😀fixed\n")

        self.main.write_text("😀foo\n", encoding="utf-8")
        stale = self.harness.prepare_lsp_mutation(
            self.session,
            "rename",
            {"path": str(self.main), "line": 1, "column": 3, "newName": "baz"},
        )
        stale_preview = self.harness.lsp_mutation_preview(stale)
        self.main.write_text("😀changed\n", encoding="utf-8")
        with self.assertRaises(WorkspaceLspError) as raised:
            self.harness.apply_lsp_mutation(
                self.session,
                "rename",
                stale_preview["actionPayload"],
                stale_preview["baseState"],
            )
        self.assertEqual(raised.exception.code, "stale_snapshot")

    def test_rename_rejects_missing_stale_and_foreign_reference_evidence(self) -> None:
        prepared = self.harness.prepare_lsp_mutation(
            self.session,
            "rename",
            {"path": str(self.main), "line": 1, "column": 3, "newName": "bar"},
        )
        preview = self.harness.lsp_mutation_preview(prepared)
        missing_payload = dict(preview["actionPayload"])
        missing_payload.pop("referencesEvidence")
        with self.assertRaises(WorkspaceLspError) as missing:
            self.harness.apply_lsp_mutation(
                self.session,
                "rename",
                missing_payload,
                preview["baseState"],
            )
        self.assertEqual(missing.exception.code, "references_required")

        stale_payload = dict(preview["actionPayload"])
        stale_state = dict(preview["baseState"])
        stale_evidence = dict(stale_payload["referencesEvidence"])
        stale_evidence["preimageSha256"] = "0" * 64
        stale_evidence["resourceRevision"] = "sha256:" + "0" * 64
        stale_payload["referencesEvidence"] = stale_evidence
        stale_state["referencesEvidence"] = dict(stale_evidence)
        stale_state["referencesEvidenceSha256"] = _lsp_references_evidence_digest(
            stale_evidence
        )
        with self.assertRaises(WorkspaceLspError) as stale:
            self.harness.apply_lsp_mutation(
                self.session,
                "rename",
                stale_payload,
                stale_state,
            )
        self.assertEqual(stale.exception.code, "stale_snapshot")

        foreign_payload = dict(preview["actionPayload"])
        foreign_state = dict(preview["baseState"])
        foreign_evidence = dict(foreign_payload["referencesEvidence"])
        foreign_evidence["root"] = str(self.temp.name) + "/foreign"
        foreign_payload["referencesEvidence"] = foreign_evidence
        foreign_state["referencesEvidence"] = dict(foreign_evidence)
        foreign_state["referencesEvidenceSha256"] = _lsp_references_evidence_digest(
            foreign_evidence
        )
        with self.assertRaises(WorkspaceLspError) as foreign:
            self.harness.apply_lsp_mutation(
                self.session,
                "rename",
                foreign_payload,
                foreign_state,
            )
        self.assertEqual(foreign.exception.code, "references_evidence_invalid")

        original_request = self.harness._lsp_request
        observed_methods: list[str] = []

        def fail_references(
            client: object,
            method: str,
            params: object,
            timeout_seconds: float,
            *,
            discard_on_failure: bool = True,
        ) -> object:
            observed_methods.append(method)
            if method == "textDocument/references":
                raise WorkspaceLspError("request_failed", "references unavailable")
            return original_request(
                client,
                method,
                params,
                timeout_seconds,
                discard_on_failure=discard_on_failure,
            )

        self.harness._lsp_request = fail_references  # type: ignore[method-assign]
        with self.assertRaises(WorkspaceLspError) as failed:
            self.harness.prepare_lsp_mutation(
                self.session,
                "rename",
                {"path": str(self.main), "line": 1, "column": 3, "newName": "bar"},
            )
        self.assertEqual(failed.exception.code, "request_failed")
        self.assertEqual(observed_methods[-1], "textDocument/references")

    def test_security_rejects_roots_symlinks_sensitive_paths_and_resource_ops(self) -> None:
        outside = Path(self.temp.name) / "outside.py"
        outside.write_text("😀foo\n", encoding="utf-8")
        sensitive_dir = self.root / ".git"
        sensitive_dir.mkdir()
        sensitive = sensitive_dir / "secret.py"
        sensitive.write_text("😀foo\n", encoding="utf-8")
        symlink = self.root / "linked.py"
        symlink.symlink_to(outside)

        nested = self.root / "nested"
        nested.mkdir()
        with self.assertRaises(WorkspaceLspError) as root_error:
            self.harness.lsp_status(self.session, {"root": str(nested)})
        self.assertEqual(root_error.exception.code, "root_not_authorized")

        for target in (outside, sensitive, symlink):
            with self.subTest(target=target), self.assertRaises(WorkspaceLspError):
                self.harness.lsp_read(
                    self.session,
                    "hover",
                    {"path": str(target), "line": 1, "column": 3},
                )

        for target in (outside, sensitive, symlink):
            with self.subTest(edit_target=target), self.assertRaises(
                WorkspaceLspError
            ) as edit_error:
                self.harness._prepare_lsp_workspace_edit(
                    operation="rename",
                    root=self.root,
                    server="fake",
                    request={},
                    workspace_edit={
                        "changes": {
                            target.as_uri(): [
                                {
                                    "range": {
                                        "start": {"line": 0, "character": 2},
                                        "end": {"line": 0, "character": 5},
                                    },
                                    "newText": "blocked",
                                }
                            ]
                        }
                    },
                )
            self.assertEqual(edit_error.exception.code, "path_not_allowed")

        with self.assertRaises(WorkspaceLspError) as resource_error:
            self.harness._prepare_lsp_workspace_edit(
                operation="rename",
                root=self.root,
                server="fake",
                request={},
                workspace_edit={
                    "documentChanges": [
                        {"kind": "create", "uri": (self.root / "new.py").as_uri()}
                    ]
                },
            )
        self.assertEqual(resource_error.exception.code, "unsupported_workspace_edit")

        with self.assertRaises(WorkspaceLspError) as command_error:
            self.harness.prepare_lsp_mutation(
                self.session,
                "code_action_apply",
                {"path": str(self.command_file), "title": "unsafe"},
            )
        self.assertEqual(command_error.exception.code, "unsupported_workspace_edit")

    def test_timeout_degrades_and_discards_the_server(self) -> None:
        with self.assertRaises(WorkspaceLspError) as raised:
            self.harness.lsp_read(
                self.session,
                "hover",
                {"path": str(self.timeout_file), "timeoutMs": 100},
            )
        self.assertEqual(raised.exception.code, "request_timeout")
        self.assertEqual(len(self.harness._lsp_clients), 0)
        self.assertEqual(self.harness.lsp_status(self.session, {})["state"], "degraded")

    def test_active_request_can_be_cancelled_by_root(self) -> None:
        errors: list[WorkspaceLspError] = []

        def request() -> None:
            try:
                self.harness.lsp_read(
                    self.session,
                    "hover",
                    {"path": str(self.timeout_file), "timeoutMs": 20_000},
                )
            except WorkspaceLspError as exc:
                errors.append(exc)

        worker = threading.Thread(target=request)
        worker.start()
        deadline = time.monotonic() + 2
        while not self.harness._lsp_clients and time.monotonic() < deadline:
            time.sleep(0.01)
        time.sleep(0.05)
        self.assertEqual(self.harness.cancel_lsp(self.root), 1)
        worker.join(timeout=2)
        self.assertFalse(worker.is_alive())
        self.assertEqual([error.code for error in errors], ["request_cancelled"])
        self.assertEqual(self.harness.lsp_status(self.session, {})["state"], "available")

    def test_sandbox_profile_is_readonly_and_process_cleanup_removes_temp_home(self) -> None:
        temporary = Path(self.temp.name) / "temporary-home"
        temporary.mkdir()
        profile = _lsp_sandbox_profile(root=self.root, temporary=temporary)
        self.assertIn(f'(allow file-read* (subpath "{self.root}"))', profile)
        self.assertNotIn(f'(allow file-write* (subpath "{self.root}"))', profile)
        self.assertIn(f'(allow file-write* (subpath "{temporary}"))', profile)
        self.assertNotIn("allow network", profile)
        self.assertIn(r"/\.(git|ssh|gnupg|aws|azure|keychain)(/|$)", profile)

        missing_sandbox = WorkspaceHarness(
            sandbox_executable=Path(self.temp.name) / "missing-sandbox",
            lsp_servers=(self.config,),
            lsp_process_sandbox=True,
        )
        try:
            self.assertEqual(
                missing_sandbox.lsp_status(self.session, {})["state"],
                "degraded",
            )
            with self.assertRaises(WorkspaceLspError) as sandbox_error:
                missing_sandbox.lsp_read(
                    self.session,
                    "hover",
                    {"path": str(self.main), "line": 1, "column": 3},
                )
            self.assertEqual(sandbox_error.exception.code, "server_degraded")
            self.assertEqual(len(missing_sandbox._lsp_clients), 0)
        finally:
            missing_sandbox.close_lsp()

        wrapper = Path(self.temp.name) / "sandbox-wrapper"
        wrapper.write_text(
            "#!/usr/bin/env python3\nimport os, sys\nos.execv(sys.argv[3], sys.argv[3:])\n",
            encoding="utf-8",
        )
        wrapper.chmod(wrapper.stat().st_mode | stat.S_IXUSR)
        sandboxed = WorkspaceHarness(
            sandbox_executable=wrapper,
            lsp_servers=(self.config,),
            lsp_process_sandbox=True,
        )
        try:
            sandboxed.lsp_read(
                self.session,
                "hover",
                {"path": str(self.main), "line": 1, "column": 3},
            )
            client = next(iter(sandboxed._lsp_clients.values()))
            process = client.process
            temp_home = Path(client.temporary_directory.name)
            self.assertTrue(temp_home.is_dir())
            sandboxed.close_lsp()
            self.assertIsNotNone(process.poll())
            self.assertFalse(temp_home.exists())
        finally:
            sandboxed.close_lsp()


if __name__ == "__main__":
    unittest.main()
