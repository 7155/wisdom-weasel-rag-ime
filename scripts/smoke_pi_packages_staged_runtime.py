#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import queue
import subprocess
import tempfile
import threading
import time
from pathlib import Path


APPROVAL_TOKEN = "staged-pi-package-canary"
PACKAGE_EXPECTATIONS = {
    "@paw/pi-session-workflow": {
        "commands": {"goal", "plan", "todos", "workflow", "skill:session-workflow"},
        "tools": {"session_workflow"},
    },
}
DISABLED_PACKAGE_IDS = {"@paw/pi-subagent"}


def _names(values: object) -> set[str]:
    if not isinstance(values, list):
        return set()
    return {
        str(item.get("name") or "")
        for item in values
        if isinstance(item, dict) and item.get("name")
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Exercise bundled Pi Package install, enable, disable, projection, "
            "and uninstall against an isolated staged Runtime Host"
        )
    )
    parser.add_argument("--payload", type=Path, required=True)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument(
        "--report-path",
        type=Path,
        help="Optionally write the acceptance receipt as a new mode-600 file",
    )
    args = parser.parse_args()

    payload = args.payload.expanduser().resolve()
    workspace_root = args.workspace_root.expanduser().resolve()
    node = payload / "bin" / "node"
    entrypoint = payload / "runtime-host" / "cli.mjs"
    manifest_path = payload / "manifest.json"
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    if not node.is_file() or not entrypoint.is_file():
        raise SystemExit("staged Runtime Host payload is incomplete")

    with tempfile.TemporaryDirectory(prefix="pi-package-staged-runtime-") as state_root:
        process = subprocess.Popen(
            [str(node), str(entrypoint)],
            cwd=workspace_root,
            env={
                **os.environ,
                "NODE_ENV": "test",
                "RAG_IME_PI_DETERMINISTIC_ADAPTER": "room-v2",
                "RAG_IME_APP_SUPPORT_DIR": state_root,
                "RAG_IME_WORKSPACE_ROOTS": str(workspace_root),
                "RAG_IME_PLUGIN_APPROVAL_TOKEN": APPROVAL_TOKEN,
            },
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        assert process.stdin is not None and process.stdout is not None
        messages: queue.Queue[dict[str, object]] = queue.Queue()
        observed_notifications: list[dict[str, object]] = []

        def read_messages() -> None:
            for line in process.stdout:
                messages.put(json.loads(line))

        threading.Thread(target=read_messages, daemon=True).start()

        def wait_for(request_id: str, timeout: float = 20.0) -> dict[str, object]:
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                try:
                    message = messages.get(timeout=min(0.2, deadline - time.monotonic()))
                except queue.Empty:
                    continue
                if message.get("id") == request_id:
                    return message
                observed_notifications.append(message)
            stderr = process.stderr.read() if process.poll() is not None and process.stderr else ""
            raise RuntimeError(
                f"staged Runtime Host timed out for {request_id}; stderr={stderr[:1200]}"
            )

        request_sequence = 0

        def request(method: str, params: dict[str, object]) -> dict[str, object]:
            nonlocal request_sequence
            request_sequence += 1
            request_id = f"package-canary-{request_sequence}"
            process.stdin.write(
                json.dumps(
                    {
                        "protocolVersion": "2",
                        "id": request_id,
                        "method": method,
                        "params": params,
                    },
                    separators=(",", ":"),
                )
                + "\n"
            )
            process.stdin.flush()
            response = wait_for(request_id)
            if response.get("ok") is not True:
                raise RuntimeError(f"{method} failed: {response}")
            result = response.get("result")
            if not isinstance(result, dict):
                raise RuntimeError(f"{method} returned no object result")
            return result

        session_id = "session:staged-package-canary"
        installed: dict[str, dict[str, object]] = {}
        try:
            hello = request("hello", {})
            catalog_result = request("plugins.catalog", {})
            packages = catalog_result.get("packages")
            if not isinstance(packages, list):
                raise RuntimeError("plugins.catalog returned no packages")
            catalog = {
                str(item.get("id") or ""): item
                for item in packages
                if isinstance(item, dict) and item.get("id")
            }
            leaked_disabled_packages = DISABLED_PACKAGE_IDS & set(catalog)
            if leaked_disabled_packages:
                raise RuntimeError(
                    "blocked legacy Packages leaked into the bundled catalog: "
                    f"{sorted(leaked_disabled_packages)}"
                )
            if set(PACKAGE_EXPECTATIONS) - set(catalog):
                raise RuntimeError(
                    "bundled Package catalog is incomplete: "
                    f"available={sorted(catalog)}"
                )

            for package_id in PACKAGE_EXPECTATIONS:
                source = str(catalog[package_id].get("source") or "")
                if not source:
                    raise RuntimeError(f"bundled Package has no source: {package_id}")
                prepared = request("plugins.package.prepare", {"source": source})
                prepared_id = str(prepared.get("preparedPackageId") or "")
                digest = str(prepared.get("digest") or "")
                if not prepared_id or len(digest) != 64:
                    raise RuntimeError(f"Package prepare receipt is incomplete: {package_id}")
                preview = request(
                    "plugins.install.preview",
                    {
                        "preparedPackageId": prepared_id,
                        "expectedDigest": digest,
                        "enable": False,
                    },
                )
                plugin = request(
                    "plugins.install",
                    {
                        "preparedPackageId": prepared_id,
                        "expectedDigest": digest,
                        "enable": False,
                        "approvalToken": APPROVAL_TOKEN,
                        "previewToken": preview.get("previewToken"),
                        "payloadSha256": preview.get("payloadSha256"),
                        "confirmText": "apply",
                    },
                )
                if plugin.get("id") != package_id or plugin.get("enabled") is not False:
                    raise RuntimeError(f"Package did not install disabled: {plugin}")
                installed[package_id] = plugin

            request(
                "session.open",
                {
                    "sessionId": session_id,
                    "cwd": str(workspace_root),
                    "provider": "rag-ime-deterministic",
                    "modelId": "room-v2-test",
                    "noContextFiles": True,
                },
            )

            command_result = request("session.commands", {"sessionId": session_id})
            commands = _names(command_result.get("commands"))
            tools = _names(request("tools.list", {"sessionId": session_id}).get("tools"))
            for expectation in PACKAGE_EXPECTATIONS.values():
                if commands & expectation["commands"] or tools & expectation["tools"]:
                    raise RuntimeError("disabled Package leaked commands or tools into the Session")

            for package_id, plugin in installed.items():
                enabled = request(
                    "plugins.enable",
                    {
                        "pluginId": package_id,
                        "expectedActiveDigest": plugin.get("digest"),
                        "expectedEnabled": False,
                        "approvalToken": APPROVAL_TOKEN,
                    },
                )
                if enabled.get("enabled") is not True:
                    raise RuntimeError(f"Package did not enable: {package_id}")
                installed[package_id] = enabled

            command_result = request("session.commands", {"sessionId": session_id})
            commands = _names(command_result.get("commands"))
            tools = _names(request("tools.list", {"sessionId": session_id}).get("tools"))
            expected_commands = set().union(
                *(value["commands"] for value in PACKAGE_EXPECTATIONS.values())
            )
            expected_tools = set().union(
                *(value["tools"] for value in PACKAGE_EXPECTATIONS.values())
            )
            if not expected_commands <= commands or not expected_tools <= tools:
                raise RuntimeError(
                    "enabled Package resources were not projected: "
                    f"commands={sorted(commands)} tools={sorted(tools)} "
                    f"diagnostics={command_result.get('diagnostics')} "
                    f"notifications={observed_notifications[-12:]}"
                )

            goal_text = "Keep optional workflow state in the Pi Session"
            plan_steps = ["verify command discovery", "verify restart recovery"]
            request(
                "session.command.invoke",
                {"sessionId": session_id, "command": f"/goal {goal_text}"},
            )
            request(
                "session.command.invoke",
                {
                    "sessionId": session_id,
                    "command": f"/plan {'; '.join(plan_steps)}",
                },
            )
            session_file = str(
                request("session.snapshot", {"sessionId": session_id}).get(
                    "sessionFile"
                )
                or ""
            )
            if not session_file or not Path(session_file).is_file():
                raise RuntimeError(
                    "Package command state was not persisted before the first assistant reply"
                )
            if request("session.close", {"sessionId": session_id}).get("closed") is not True:
                raise RuntimeError("staged Package Session did not close for recovery canary")
            request(
                "session.open",
                {
                    "sessionId": session_id,
                    "cwd": str(workspace_root),
                    "sessionFile": session_file,
                    "provider": "rag-ime-deterministic",
                    "modelId": "room-v2-test",
                    "noContextFiles": True,
                },
            )
            restored = request(
                "session.command.invoke",
                {"sessionId": session_id, "command": "/workflow"},
            )
            restored_result = restored.get("result")
            restored_message = (
                str(restored_result.get("message") or "")
                if isinstance(restored_result, dict)
                else ""
            )
            if goal_text not in restored_message or not all(
                step in restored_message for step in plan_steps
            ):
                raise RuntimeError(
                    "Package workflow state did not survive Session close/reopen: "
                    f"result={restored}"
                )

            workflow_id = "@paw/pi-session-workflow"
            workflow = installed[workflow_id]
            disabled_workflow = request(
                "plugins.disable",
                {
                    "pluginId": workflow_id,
                    "expectedActiveDigest": workflow.get("digest"),
                    "expectedEnabled": True,
                    "approvalToken": APPROVAL_TOKEN,
                },
            )
            commands = _names(request("session.commands", {"sessionId": session_id}).get("commands"))
            tools = _names(request("tools.list", {"sessionId": session_id}).get("tools"))
            workflow_expected = PACKAGE_EXPECTATIONS[workflow_id]
            if commands & workflow_expected["commands"] or tools & workflow_expected["tools"]:
                raise RuntimeError("disabled Workflow Package still owns Session resources")
            for package_id, plugin in ((workflow_id, disabled_workflow),):
                request(
                    "plugins.uninstall",
                    {
                        "pluginId": package_id,
                        "expectedActiveDigest": plugin.get("digest"),
                        "expectedEnabled": False,
                        "approvalToken": APPROVAL_TOKEN,
                    },
                )

            remaining = request("plugins.list", {}).get("plugins")
            if not isinstance(remaining, list):
                raise RuntimeError("plugins.list returned no plugin array")
            remaining_ids = {
                str(item.get("id") or "")
                for item in remaining
                if isinstance(item, dict)
            }
            if set(PACKAGE_EXPECTATIONS) & remaining_ids:
                raise RuntimeError(f"uninstalled Packages remain active: {sorted(remaining_ids)}")

            receipt = {
                "schemaVersion": "rag-ime.pi-package-staged-runtime-e2e.v1",
                "status": "passed_ephemeral_not_activated",
                "runtimeVersion": manifest.get("runtimeVersion"),
                "piVersion": manifest.get("piVersion"),
                "manifestSha256": hashlib.sha256(manifest_bytes).hexdigest(),
                "protocolVersion": hello.get("protocolVersion"),
                "packages": sorted(PACKAGE_EXPECTATIONS),
                "disabledPackages": sorted(DISABLED_PACKAGE_IDS),
                "verifiedMethods": [
                    "plugins.catalog",
                    "plugins.package.prepare",
                    "plugins.install.preview",
                    "plugins.install",
                    "plugins.enable",
                    "plugins.disable",
                    "plugins.uninstall",
                    "plugins.list",
                    "session.commands",
                    "session.command.invoke",
                    "session.snapshot",
                    "session.close",
                    "tools.list",
                ],
                "disabledResourcesAbsent": True,
                "disabledPackagesAbsent": True,
                "enabledResourcesPresent": True,
                "independentCapabilityRemoval": True,
                "preAssistantStatePersisted": True,
                "sessionStateRecovered": True,
                "uninstallRemovedPackages": True,
            }
            encoded = json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
            if args.report_path is not None:
                report_path = args.report_path.expanduser().resolve(strict=False)
                report_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                descriptor = os.open(
                    report_path,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                )
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    handle.write(encoded)
            print(encoded, end="")
        finally:
            process.stdin.close()
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
