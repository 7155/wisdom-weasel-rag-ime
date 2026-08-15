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
from collections.abc import Mapping
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Exercise a staged Pi Session with the offline deterministic Provider"
    )
    parser.add_argument("--payload", type=Path, required=True)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--deterministic-test-gate", action="store_true", required=True)
    parser.add_argument(
        "--report-path",
        type=Path,
        help="Optionally write the acceptance receipt as a new mode-600 file",
    )
    args = parser.parse_args()

    payload = args.payload.resolve()
    workspace_root = args.workspace_root.resolve()
    node = payload / "bin" / "node"
    entrypoint = payload / "runtime-host" / "cli.mjs"
    manifest_path = payload / "manifest.json"
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    if not node.is_file() or not entrypoint.is_file():
        raise SystemExit("staged Runtime Host payload is incomplete")

    with tempfile.TemporaryDirectory(prefix="pi-session-staged-runtime-") as state_root:
        process = subprocess.Popen(
            [str(node), str(entrypoint)],
            cwd=workspace_root,
            env={
                **os.environ,
                "NODE_ENV": "test",
                "RAG_IME_PI_DETERMINISTIC_ADAPTER": "room-v2",
                "RAG_IME_PI_DETERMINISTIC_SLOW": "1",
                "RAG_IME_APP_SUPPORT_DIR": state_root,
                "RAG_IME_WORKSPACE_ROOTS": str(workspace_root),
            },
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        assert process.stdin is not None and process.stdout is not None
        messages: queue.Queue[dict[str, object]] = queue.Queue()

        def read_messages() -> None:
            for line in process.stdout:
                messages.put(json.loads(line))

        threading.Thread(target=read_messages, daemon=True).start()

        def wait_for(predicate, timeout: float = 15.0) -> dict[str, object]:
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                try:
                    message = messages.get(timeout=min(0.2, deadline - time.monotonic()))
                except queue.Empty:
                    continue
                if predicate(message):
                    return message
            stderr = process.stderr.read() if process.poll() is not None and process.stderr else ""
            raise RuntimeError(f"staged Runtime Host timed out; stderr={stderr[:1000]}")

        def request(request_id: str, method: str, params: dict[str, object]) -> dict[str, object]:
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
            response = wait_for(lambda item: item.get("id") == request_id)
            if response.get("ok") is not True:
                raise RuntimeError(f"{method} failed: {response}")
            result = response.get("result")
            if not isinstance(result, dict):
                raise RuntimeError(f"{method} returned no object result")
            return result

        session_id = "session:staged-e2e"
        try:
            hello = request("hello", "hello", {})
            request(
                "open",
                "session.open",
                {
                    "sessionId": session_id,
                    "cwd": str(workspace_root),
                    "provider": "rag-ime-deterministic",
                    "modelId": "room-v2-test",
                    "noContextFiles": True,
                },
            )
            prompted = request(
                "prompt",
                "session.prompt",
                {
                    "sessionId": session_id,
                    "clientMessageId": "staged-prompt",
                    "message": "Keep this Session active until the next steering message.",
                },
            )
            turn_id = str(prompted.get("turnId") or "")
            if not turn_id:
                raise RuntimeError("session.prompt returned no turnId")
            steered = request(
                "steer",
                "session.steer",
                {
                    "sessionId": session_id,
                    "clientMessageId": "staged-steer",
                    "message": "Stop the original work and acknowledge this steer.",
                },
            )
            debug_available = False
            for attempt in range(20):
                inspected = request(
                    f"debug-{attempt}",
                    "session.debug.context",
                    {"sessionId": session_id, "turnId": turn_id},
                )
                if inspected.get("available") is True:
                    debug_available = True
                    break
                time.sleep(0.02)
            aborted = request("abort", "session.abort", {"sessionId": session_id})
            abort_lifecycle = aborted.get("lifecycle")
            abort_acknowledged = bool(
                aborted.get("schemaVersion")
                == "rag-ime.pi-session-abort-receipt.v1"
                and aborted.get("sessionId") == session_id
                and isinstance(abort_lifecycle, Mapping)
                and abort_lifecycle.get("schemaVersion")
                == "pi.agent-abort-receipt.v1"
                and abort_lifecycle.get("drained") is True
                and abort_lifecycle.get("idle") is True
            )
            terminal_idle = False
            for attempt in range(40):
                snapshot = request(
                    f"snapshot-{attempt}",
                    "session.snapshot",
                    {"sessionId": session_id},
                )
                if snapshot.get("isIdle") is True:
                    terminal_idle = True
                    break
                time.sleep(0.025)
            if not abort_acknowledged or not debug_available or not terminal_idle:
                raise RuntimeError(
                    "Pi Session did not acknowledge abort, expose context, or settle"
                )
            receipt = {
                "schemaVersion": "rag-ime.pi-session-staged-runtime-e2e.v1",
                "status": "passed_not_installed",
                "productionEnabled": False,
                "runtimeVersion": manifest.get("runtimeVersion"),
                "manifestSha256": hashlib.sha256(manifest_bytes).hexdigest(),
                "sourceCommit": (manifest.get("source") or {}).get("commit"),
                "protocolVersion": hello.get("protocolVersion"),
                "verifiedMethods": [
                    "session.open",
                    "session.prompt",
                    "session.steer",
                    "session.debug.context",
                    "session.abort",
                    "session.snapshot",
                ],
                "promptDelivery": "prompt",
                "steerDelivery": steered.get("delivery"),
                "abortAcknowledged": abort_acknowledged,
                "debugContextAvailable": debug_available,
                "terminalSessionIdle": terminal_idle,
            }
            encoded = json.dumps(
                receipt,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ) + "\n"
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
