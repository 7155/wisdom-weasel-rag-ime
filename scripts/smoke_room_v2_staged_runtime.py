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


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Exercise a staged Room V2 payload with the explicit offline test Provider"
    )
    parser.add_argument("--payload", type=Path, required=True)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--deterministic-test-gate", action="store_true", required=True)
    args = parser.parse_args()

    payload = args.payload.resolve()
    node = payload / "bin" / "node"
    entrypoint = payload / "runtime-host" / "cli.mjs"
    manifest = json.loads((payload / "manifest.json").read_text(encoding="utf-8"))
    if not node.is_file() or not entrypoint.is_file():
        raise SystemExit("staged Runtime Host payload is incomplete")

    with tempfile.TemporaryDirectory(prefix="room-v2-staged-runtime-") as state_root:
        env = {
            **os.environ,
            "NODE_ENV": "test",
            "RAG_IME_PI_DETERMINISTIC_ADAPTER": "room-v2",
            "RAG_IME_PI_DETERMINISTIC_SLOW": "1",
            "RAG_IME_APP_SUPPORT_DIR": state_root,
            "RAG_IME_WORKSPACE_ROOTS": str(args.workspace_root.resolve()),
        }
        process = subprocess.Popen(
            [str(node), str(entrypoint)],
            cwd=args.workspace_root.resolve(),
            env=env,
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
        seen: list[dict[str, object]] = []

        def wait_for(predicate, timeout: float = 15.0) -> dict[str, object]:
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                try:
                    message = messages.get(timeout=min(0.2, deadline - time.monotonic()))
                except queue.Empty:
                    continue
                seen.append(message)
                if predicate(message):
                    return message
            stderr = process.stderr.read() if process.poll() is not None and process.stderr else ""
            raise RuntimeError(f"staged Runtime Host timed out; stderr={stderr[:1000]}")

        def request(request_id: str, method: str, params: dict[str, object]) -> dict[str, object]:
            process.stdin.write(json.dumps({
                "protocolVersion": "2", "id": request_id, "method": method, "params": params,
            }, separators=(",", ":")) + "\n")
            process.stdin.flush()
            response = wait_for(lambda item: item.get("id") == request_id)
            if response.get("ok") is not True:
                raise RuntimeError(f"{method} failed: {response}")
            result = response.get("result")
            if not isinstance(result, dict):
                raise RuntimeError(f"{method} returned no object result")
            return result

        try:
            hello = request("hello", "hello", {})
            prompt_hash = hashlib.sha256(b"room-v2-staged-prompt").hexdigest()
            opened = request("open", "session.open", {
                "sessionId": "session:staged-e2e",
                "cwd": str(args.workspace_root.resolve()),
                "provider": "rag-ime-deterministic",
                "modelId": "room-v2-test",
                "noContextFiles": True,
                "toolManifest": [],
                "roomCapability": {
                    "manifestId": "manifest:staged-e2e",
                    "manifestHash": prompt_hash,
                    "capabilityEpoch": 1,
                    "promptCompileReceiptId": "prompt-receipt:staged-e2e",
                    "promptPlanHash": prompt_hash,
                    "toolNames": ["room_post"],
                },
                "roomResourceLimits": {
                    "deadlineAtMs": int(time.time() * 1000) + 60_000,
                    "maxInputTokens": 64_000,
                    "maxOutputTokens": 4_096,
                    "maxToolCalls": 8,
                    "maxToolCost": 8,
                    "retryRemaining": 1,
                    "repairRemaining": 1,
                },
            })
            snapshot = opened.get("snapshot")
            if not isinstance(snapshot, dict) or snapshot.get("roomCapability", {}).get("promptPlanHash") != prompt_hash:
                raise RuntimeError("staged Runtime Host did not preserve the PromptPlan cache-prefix hash")
            first = request("dispatch-a", "room.dispatch", {
                "sessionId": "session:staged-e2e", "rootId": "root:staged-e2e",
                "dispatchId": "dispatch:a", "generation": 1,
                "idempotencyKey": "root:staged-e2e/a", "leaseToken": "lease:a",
                "message": "Inspect package.json and keep the bounded run active.",
            })
            second = request("dispatch-b", "room.dispatch", {
                "sessionId": "session:staged-e2e", "rootId": "root:staged-e2e",
                "dispatchId": "dispatch:b", "generation": 1,
                "idempotencyKey": "root:staged-e2e/b", "leaseToken": "lease:b",
                "message": "Continue the same bounded run.",
            })
            cancelled = request("cancel", "room.cancel", {
                "sessionId": "session:staged-e2e", "rootId": "root:staged-e2e", "generation": 2,
            })
            surfaces = cancelled.get("cancellationSurfaces")
            expected = {"provider", "tool", "exec", "retry", "compaction", "branch_summary", "timer", "continuation", "session"}
            if not isinstance(surfaces, dict) or set(surfaces) != expected:
                raise RuntimeError("staged Runtime Host returned incomplete cancellation surfaces")
            if cancelled.get("pendingTargets") != [] or any(
                not isinstance(proof, dict)
                or proof.get("schemaVersion") != "wisdom-weasel.runtime-surface-termination-receipt.v1"
                or proof.get("state") != "terminated"
                for proof in surfaces.values()
            ):
                raise RuntimeError("staged Runtime Host did not return terminal typed surface proofs")
            print(json.dumps({
                "schemaVersion": "rag-ime.room-v2-staged-runtime-e2e.v1",
                "status": "passed_not_installed",
                "productionEnabled": False,
                "runtimeVersion": manifest.get("runtimeVersion"),
                "sourceCommit": manifest.get("source", {}).get("commit"),
                "protocolVersion": hello.get("protocolVersion"),
                "cachePrefixHash": prompt_hash,
                "firstDelivery": first.get("delivery"),
                "secondDelivery": second.get("delivery"),
                "cancelledSurfaceCount": len(surfaces),
            }, ensure_ascii=False, indent=2, sort_keys=True))
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
