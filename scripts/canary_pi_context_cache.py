#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import queue
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path


def _atomic_write_json(path: Path | None, value: dict[str, object]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a no-tools Pi Provider cache canary without installing the staged runtime"
    )
    parser.add_argument("--payload", type=Path, required=True)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--model", default="")
    parser.add_argument("--provider-env-file", type=Path)
    parser.add_argument("--source-agent-config", type=Path, required=True)
    parser.add_argument("--evidence-output", type=Path)
    args = parser.parse_args()

    payload = args.payload.resolve()
    node = payload / "bin" / "node"
    entrypoint = payload / "runtime-host" / "cli.mjs"
    manifest = json.loads((payload / "manifest.json").read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="pi-context-cache-canary-") as temporary:
        state = Path(temporary)
        agent_dir = state / "Agent" / "config"
        agent_dir.mkdir(parents=True)
        for name in ("models.json", "auth.json", "settings.json"):
            source = args.source_agent_config / name
            if source.is_file():
                shutil.copy2(source, agent_dir / name)
        provider_env: dict[str, str] = {}
        if args.provider_env_file:
            for line in args.provider_env_file.read_text(encoding="utf-8").splitlines():
                if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                provider_env[key.strip()] = value.strip().strip('"').strip("'")
        model = args.model or provider_env.get("RAG_IME_DEEPSEEK_MODEL", "")
        if not model:
            raise RuntimeError("canary model is not configured")
        env = {
            **os.environ,
            **provider_env,
            "RAG_IME_APP_SUPPORT_DIR": str(state),
            "RAG_IME_WORKSPACE_ROOTS": str(args.workspace_root.resolve()),
            "RAG_IME_PI_DEBUG_CONTEXT_DIR": str(state / "context-inspection"),
            "RAG_IME_PI_DEBUG_CONTEXT_MAX_BYTES": str(8 * 1024 * 1024),
        }
        process = subprocess.Popen(
            [str(node), str(entrypoint)],
            cwd=args.workspace_root,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        assert process.stdin is not None and process.stdout is not None
        messages: queue.Queue[dict[str, object]] = queue.Queue()
        stderr_lines: list[str] = []
        evidence_state: dict[str, object] = {
            "schemaVersion": "rag-ime.pi-context-cache-canary-progress.v1",
            "productionEnabled": False,
            "sourceCommit": manifest.get("source", {}).get("commit"),
            "provider": args.provider,
            "model": model,
            "lastCompletedStage": "process_started",
            "stableTurns": [],
        }
        _atomic_write_json(args.evidence_output, evidence_state)

        def read_messages() -> None:
            for line in process.stdout:
                messages.put(json.loads(line))

        threading.Thread(target=read_messages, daemon=True).start()

        def read_stderr() -> None:
            if process.stderr is None:
                return
            for line in process.stderr:
                safe = line.replace(provider_env.get("DEEPSEEK_API_KEY", ""), "[credential omitted]")
                stderr_lines.append(safe.strip()[:500])
                del stderr_lines[:-20]

        threading.Thread(target=read_stderr, daemon=True).start()

        def checkpoint(stage: str, **values: object) -> None:
            evidence_state.update(values)
            evidence_state["lastCompletedStage"] = stage
            evidence_state["hostExitCode"] = process.poll()
            evidence_state["stderrSummary"] = list(stderr_lines)
            _atomic_write_json(args.evidence_output, evidence_state)

        def wait_for(predicate, timeout: float = 120.0) -> dict[str, object]:
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                try:
                    message = messages.get(timeout=min(0.25, deadline - time.monotonic()))
                except queue.Empty:
                    continue
                if predicate(message):
                    return message
            stderr = process.stderr.read() if process.poll() is not None and process.stderr else ""
            raise RuntimeError(f"Pi cache canary timed out: {stderr[:800]}")

        def request(request_id: str, method: str, params: dict[str, object]) -> dict[str, object]:
            process.stdin.write(
                json.dumps(
                    {"protocolVersion": "2", "id": request_id, "method": method, "params": params},
                    separators=(",", ":"),
                )
                + "\n"
            )
            process.stdin.flush()
            response = wait_for(lambda item: item.get("id") == request_id)
            if response.get("ok") is not True:
                raise RuntimeError(f"{method} failed: {response}")
            return dict(response.get("result") or {})

        def run_turn(session_id: str, index: int) -> dict[str, object]:
            prompt = request(
                f"prompt-{session_id}-{index}",
                "session.prompt",
                {
                    "sessionId": session_id,
                    "message": f"Canary turn {index}. Reply with exactly OK.",
                    "clientMessageId": f"canary-{session_id}-{index}",
                },
            )
            turn_id = str(prompt.get("turnId") or "")
            checkpoint(f"{session_id}.turn-{index}.prompt_accepted", turnId=turn_id)
            wait_for(
                lambda item: item.get("event") == "agent.event"
                and item.get("sessionId") == session_id
                and item.get("turnId") == turn_id
                and isinstance(item.get("payload"), dict)
                and item["payload"].get("type") == "agent_settled"
            )
            checkpoint(f"{session_id}.turn-{index}.agent_settled", turnId=turn_id)
            inspected = request(
                f"inspect-{session_id}-{index}",
                "session.debug.context",
                {"sessionId": session_id, "turnId": turn_id},
            )
            checkpoint(f"{session_id}.turn-{index}.context_inspected", turnId=turn_id)
            context = inspected.get("context")
            if not isinstance(context, dict):
                raise RuntimeError("context inspection receipt is unavailable")
            evidence = context.get("cacheEvidence")
            if not isinstance(evidence, list) or not evidence:
                raise RuntimeError("cache evidence is unavailable")
            row = dict(evidence[-1])
            calls = context.get("modelCalls")
            provider_context = calls[-1].get("providerContext") if isinstance(calls, list) and calls else None
            provider_context_bytes = json.dumps(
                provider_context,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            system_prompt = (
                str(provider_context.get("systemPrompt") or "")
                if isinstance(provider_context, dict)
                else ""
            )
            return {
                "turn": index,
                "turnId": turn_id,
                "prefixSha256": row.get("prefixSha256"),
                "prefixBytes": row.get("prefixBytes"),
                "deltaBytes": row.get("deltaBytes"),
                "duplicateBytes": row.get("duplicateBytes"),
                "inputTokens": row.get("inputTokens"),
                "outputTokens": row.get("outputTokens"),
                "cacheReadTokens": row.get("cacheReadTokens"),
                "cacheWriteTokens": row.get("cacheWriteTokens"),
                "capability": row.get("capability"),
                "providerContextSha256": hashlib.sha256(provider_context_bytes).hexdigest(),
                "providerContextBytes": len(provider_context_bytes),
                "systemPromptSha256": hashlib.sha256(system_prompt.encode("utf-8")).hexdigest(),
                "systemPromptBytes": len(system_prompt.encode("utf-8")),
                "transcript": inspected.get("transcript"),
            }

        def emit_evidence(report: dict[str, object]) -> None:
            serialized = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
            if args.evidence_output:
                args.evidence_output.write_text(serialized, encoding="utf-8")
            print(serialized, end="", flush=True)

        try:
            request("hello", "hello", {})
            checkpoint("hello")
            stable_body = "\n".join(
                f"Stable cache policy line {index:04d}: no tools, no side effects, reply only OK."
                for index in range(1, 513)
            )
            stable_prompt = f"STABLE-V1\n{stable_body}"
            request(
                "open-stable",
                "session.open",
                {
                    "sessionId": "cache-stable",
                    "cwd": str(args.workspace_root.resolve()),
                    "provider": args.provider,
                    "modelId": model,
                    "systemPrompt": stable_prompt,
                    "noContextFiles": True,
                    "toolManifest": [],
                },
            )
            checkpoint("cache-stable.open")
            stable = []
            for index in range(1, 4):
                stable.append(run_turn("cache-stable", index))
                checkpoint(f"cache-stable.turn-{index}.receipt", stableTurns=stable)
            request(
                "open-control",
                "session.open",
                {
                    "sessionId": "cache-control",
                    "cwd": str(args.workspace_root.resolve()),
                    "provider": args.provider,
                    "modelId": model,
                    "systemPrompt": f"CHANGED-CONTROL-V2\n{stable_body}",
                    "noContextFiles": True,
                    "toolManifest": [],
                },
            )
            checkpoint("cache-control.open", stableTurns=stable)
            control = run_turn("cache-control", 1)
            checkpoint("cache-control.turn-1.receipt", stableTurns=stable, changedPrefixControl=control)
            provider_cache_fields_reported = all(
                row.get("capability") == "reported" for row in [*stable, control]
            )
            stable_hit_proven = any(int(row.get("cacheReadTokens") or 0) > 0 for row in stable[1:])
            control_prefix_different = control["systemPromptSha256"] != stable[0]["systemPromptSha256"]
            if not control_prefix_different:
                raise RuntimeError("changed-prefix control reused the stable system prompt")
            stable_cache_read = max(int(row.get("cacheReadTokens") or 0) for row in stable[1:])
            control_cache_read = int(control.get("cacheReadTokens") or 0)
            changed_prefix_miss_observed = (
                provider_cache_fields_reported and stable_hit_proven and control_cache_read < stable_cache_read
            )
            if not provider_cache_fields_reported:
                status = "unsupported"
            elif not control_prefix_different:
                status = "failed"
            elif stable_hit_proven and changed_prefix_miss_observed:
                status = "passed_not_installed"
            else:
                status = "inconclusive"
            report = {
                        "schemaVersion": "rag-ime.pi-context-cache-canary.v1",
                        "status": status,
                        "productionEnabled": False,
                        "sourceCommit": manifest.get("source", {}).get("commit"),
                        "provider": args.provider,
                        "model": model,
                        "stableTurns": stable,
                        "changedPrefixControl": control,
                        "providerCacheFieldsReported": provider_cache_fields_reported,
                        "stableHitProven": stable_hit_proven,
                        "controlPrefixDifferent": control_prefix_different,
                        "changedPrefixMissObserved": changed_prefix_miss_observed,
                        "stableCacheReadTokens": stable_cache_read,
                        "controlCacheReadTokens": control_cache_read,
                        "evidenceRule": "cache hit requires positive Provider-reported usage.cacheRead",
                        "lastCompletedStage": "complete",
                        "hostExitCode": process.poll(),
                        "stderrSummary": list(stderr_lines),
            }
            evidence_state.update(report)
            emit_evidence(report)
        finally:
            if evidence_state.get("lastCompletedStage") != "complete":
                checkpoint("shutdown_requested")
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
