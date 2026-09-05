"""Trusted startup gate before the existing sandboxed background command.

Only lifecycle work runs here. The user command runs after durable admission,
through the exact environment and sandbox argv prepared by WorkspaceHarness.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rag_ime.room_runtime_host_kill_gate import _process_identity


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt-fd", type=int, required=True)
    parser.add_argument("--exit-fd", type=int, required=True)
    parser.add_argument("--release-path", type=Path, required=True)
    parser.add_argument("--command-sha256", required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    try:
        if not command:
            raise ValueError("background launch command is missing")
        pid = os.getpid()
        identity = _process_identity(pid)
        if identity is None or identity[0] != pid:
            raise RuntimeError("background launcher lacks a dedicated process identity")
        receipt = {
            "schemaVersion": "rag-ime.background-launch.v1",
            "pid": pid, "processGroupId": identity[0], "processBirthToken": identity[1],
            "commandSha256": args.command_sha256,
        }
        with os.fdopen(args.receipt_fd, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(receipt, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        deadline = time.monotonic() + 60
        while not args.release_path.is_file():
            if time.monotonic() >= deadline:
                raise TimeoutError("background launch admission did not arrive")
            time.sleep(0.01)
        os.execvpe(command[0], command, dict(os.environ))
    except Exception as exc:
        # The sandbox command has not executed. Preserve a real failed exit
        # receipt instead of leaving a completed-looking command or replaying.
        os.write(args.exit_fd, b"125\n")
        print(f"background launch failed: {exc}", file=sys.stderr, flush=True)
        return 125
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
