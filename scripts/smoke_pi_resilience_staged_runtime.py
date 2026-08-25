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
from typing import Callable


class RuntimeHost:
    def __init__(
        self,
        *,
        payload: Path,
        workspace_root: Path,
        state_root: Path,
        scenario: str,
    ) -> None:
        self.messages: list[dict[str, object]] = []
        self._queue: queue.Queue[dict[str, object]] = queue.Queue()
        self._process = subprocess.Popen(
            [str(payload / "bin" / "node"), str(payload / "runtime-host" / "cli.mjs")],
            cwd=workspace_root,
            env={
                **os.environ,
                "NODE_ENV": "test",
                "RAG_IME_PI_DETERMINISTIC_ADAPTER": "room-v2",
                "RAG_IME_PI_DETERMINISTIC_SCENARIO": scenario,
                "RAG_IME_APP_SUPPORT_DIR": str(state_root),
                "RAG_IME_WORKSPACE_ROOTS": str(workspace_root),
            },
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        assert self._process.stdin is not None
        assert self._process.stdout is not None
        threading.Thread(target=self._read_messages, daemon=True).start()

    def _read_messages(self) -> None:
        assert self._process.stdout is not None
        for line in self._process.stdout:
            message = json.loads(line)
            self.messages.append(message)
            self._queue.put(message)

    def wait_for(
        self,
        predicate: Callable[[dict[str, object]], bool],
        *,
        timeout: float = 30.0,
    ) -> dict[str, object]:
        for message in self.messages:
            if predicate(message):
                return message
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                message = self._queue.get(timeout=min(0.2, deadline - time.monotonic()))
            except queue.Empty:
                continue
            if predicate(message):
                return message
        stderr = ""
        if self._process.poll() is not None and self._process.stderr is not None:
            stderr = self._process.stderr.read()
        raise RuntimeError(f"staged Runtime Host timed out; stderr={stderr[:1200]}")

    def request(
        self,
        request_id: str,
        method: str,
        params: dict[str, object],
        *,
        timeout: float = 30.0,
    ) -> dict[str, object]:
        assert self._process.stdin is not None
        self._process.stdin.write(
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
        self._process.stdin.flush()
        response = self.wait_for(lambda item: item.get("id") == request_id, timeout=timeout)
        if response.get("ok") is not True:
            raise RuntimeError(f"{method} failed: {response}")
        result = response.get("result")
        if not isinstance(result, dict):
            raise RuntimeError(f"{method} returned no object result")
        return result

    def wait_settled(self, client_message_id: str, *, timeout: float = 30.0) -> None:
        self.wait_for(
            lambda item: item.get("event") == "agent.event"
            and item.get("clientMessageId") == client_message_id
            and isinstance(item.get("payload"), dict)
            and item["payload"].get("type") == "agent_settled",
            timeout=timeout,
        )

    def close(self) -> None:
        if self._process.stdin is not None and not self._process.stdin.closed:
            self._process.stdin.close()
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=3)


def _open(host: RuntimeHost, workspace_root: Path, session_id: str) -> dict[str, object]:
    host.request("hello", "hello", {})
    return host.request(
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


def _event_count(host: RuntimeHost, event_type: str) -> int:
    return sum(
        1
        for item in host.messages
        if item.get("event") == "agent.event"
        and isinstance(item.get("payload"), dict)
        and item["payload"].get("type") == event_type
    )


def _threshold_compaction(payload: Path, workspace_root: Path, state_root: Path) -> dict[str, object]:
    host = RuntimeHost(
        payload=payload,
        workspace_root=workspace_root,
        state_root=state_root,
        scenario="threshold-continuation",
    )
    session_id = "session:staged-threshold-compaction"
    try:
        opened = _open(host, workspace_root, session_id)
        snapshot = opened.get("snapshot")
        telemetry = snapshot.get("telemetry") if isinstance(snapshot, dict) else None
        context = telemetry.get("context") if isinstance(telemetry, dict) else None
        if not isinstance(context, dict) or context.get("contextWindow") != 64_000:
            raise RuntimeError("threshold canary did not use its bounded-context model")

        prompts = (
            ("threshold-history", "threshold-continuation-history", "THRESHOLD-COMPACTION-EARLY-HISTORY"),
            (
                "threshold-seed",
                "threshold-continuation-seed",
                f"THRESHOLD-COMPACTION-SEED\n{'bounded-context-evidence ' * 3_500}",
            ),
            (
                "threshold-task",
                "threshold-continuation-e2e",
                f"THRESHOLD-COMPACTION-ORIGINAL-TASK\n{'current-task-evidence ' * 2_200}",
            ),
        )
        for request_id, client_message_id, message in prompts:
            host.request(
                request_id,
                "session.prompt",
                {
                    "sessionId": session_id,
                    "message": message,
                    "clientMessageId": client_message_id,
                },
                timeout=45.0,
            )
            host.wait_settled(client_message_id, timeout=45.0)

        final_snapshot = host.request(
            "threshold-snapshot",
            "session.snapshot",
            {"sessionId": session_id},
        )
        final_telemetry = final_snapshot.get("telemetry")
        latest = final_telemetry.get("latestCompaction") if isinstance(final_telemetry, dict) else None
        serialized = json.dumps(final_snapshot, ensure_ascii=False)
        starts = [
            item
            for item in host.messages
            if item.get("event") == "agent.event"
            and isinstance(item.get("payload"), dict)
            and item["payload"].get("type") == "compaction_start"
            and item["payload"].get("reason") == "threshold"
        ]
        ends = [
            item
            for item in host.messages
            if item.get("event") == "agent.event"
            and isinstance(item.get("payload"), dict)
            and item["payload"].get("type") == "compaction_end"
            and item["payload"].get("reason") == "threshold"
        ]
        if (
            len(starts) != 1
            or len(ends) != 1
            or not isinstance(latest, dict)
            or latest.get("status") != "completed"
            or "THRESHOLD-COMPACTION-CONTINUED-OK" not in serialized
            or "threshold-compaction-continuation" not in serialized
        ):
            raise RuntimeError(
                "threshold compaction did not settle exactly once: "
                f"starts={len(starts)} ends={len(ends)} latest={latest}"
            )
        return {
            "compactionStarts": len(starts),
            "compactionEnds": len(ends),
            "compactionStatus": latest.get("status"),
            "continuationObserved": True,
            "agentSettledCount": _event_count(host, "agent_settled"),
        }
    finally:
        host.close()


def _tool_failure_stop(payload: Path, workspace_root: Path, state_root: Path) -> dict[str, object]:
    host = RuntimeHost(
        payload=payload,
        workspace_root=workspace_root,
        state_root=state_root,
        scenario="no-progress",
    )
    session_id = "session:staged-tool-failure"
    try:
        _open(host, workspace_root, session_id)
        host.request(
            "failure-prompt",
            "session.prompt",
            {
                "sessionId": session_id,
                "message": "Keep reading the missing proof path until the Runtime guard stops the loop.",
                "clientMessageId": "staged-tool-failure",
            },
        )
        host.wait_for(
            lambda item: item.get("event") == "agent.event"
            and isinstance(item.get("payload"), dict)
            and item["payload"].get("type") == "tool_loop_no_progress"
        )
        host.wait_settled("staged-tool-failure")
        snapshot = host.request(
            "failure-snapshot",
            "session.snapshot",
            {"sessionId": session_id},
        )
        stop = snapshot.get("toolLoopProgressStop")
        executions = _event_count(host, "tool_execution_end")
        no_progress = _event_count(host, "tool_loop_no_progress")
        if (
            executions != 3
            or no_progress != 1
            or not isinstance(stop, dict)
            or stop.get("reason") != "repeated_failure_signature"
            or stop.get("consecutiveAllErrorTurns") != 3
        ):
            raise RuntimeError(
                "repeated Tool failures did not terminate deterministically: "
                f"executions={executions} noProgress={no_progress} stop={stop}"
            )
        return {
            "failedToolExecutions": executions,
            "noProgressEvents": no_progress,
            "terminalReason": stop.get("reason"),
            "consecutiveAllErrorTurns": stop.get("consecutiveAllErrorTurns"),
        }
    finally:
        host.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Exercise staged Pi compaction continuation and repeated Tool-failure termination"
    )
    parser.add_argument("--payload", type=Path, required=True)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--deterministic-test-gate", action="store_true", required=True)
    args = parser.parse_args()

    payload = args.payload.expanduser().resolve()
    workspace_root = args.workspace_root.expanduser().resolve()
    manifest_bytes = (payload / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    if not (payload / "bin" / "node").is_file() or not (payload / "runtime-host" / "cli.mjs").is_file():
        raise SystemExit("staged Runtime Host payload is incomplete")

    with tempfile.TemporaryDirectory(prefix="pi-resilience-staged-runtime-") as temporary:
        root = Path(temporary)
        compaction = _threshold_compaction(payload, workspace_root, root / "compaction")
        tool_failure = _tool_failure_stop(payload, workspace_root, root / "tool-failure")

    print(
        json.dumps(
            {
                "schemaVersion": "rag-ime.pi-resilience-staged-runtime-e2e.v1",
                "status": "passed_not_installed",
                "productionEnabled": False,
                "runtimeVersion": manifest.get("runtimeVersion"),
                "piVersion": manifest.get("piVersion"),
                "manifestSha256": hashlib.sha256(manifest_bytes).hexdigest(),
                "compaction": compaction,
                "toolFailure": tool_failure,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
