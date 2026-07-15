from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path


SCREEN_LOCK_RE = re.compile(r'"CGSSessionScreenIsLocked"\s*=\s*(Yes|No)')
SECURE_INPUT_PID_RE = re.compile(r'"kCGSSessionSecureInputPID"\s*=\s*(-?\d+)')


def parse_session_state(text: str) -> dict[str, object]:
    lock_matches = SCREEN_LOCK_RE.findall(text)
    secure_matches = SECURE_INPUT_PID_RE.findall(text)
    screen_locked = lock_matches[-1] == "Yes" if lock_matches else None
    secure_input_pid = int(secure_matches[-1]) if secure_matches else 0
    blockers: list[str] = []
    warnings: list[str] = []
    if screen_locked is None:
        # Recent macOS versions omit the lock key while the GUI session is
        # unlocked. Only an explicit locked value is a blocker; otherwise the
        # foreground probe itself remains the source of truth.
        warnings.append("screen_lock_state_unavailable")
    elif screen_locked:
        blockers.append("screen_locked")
    if secure_input_pid > 0:
        blockers.append("secure_input_active")
    return {
        "screenLocked": screen_locked,
        "secureInputPid": secure_input_pid,
        "blockers": blockers,
        "warnings": warnings,
        "ready": not blockers,
    }


def secure_input_owner(pid: int) -> str:
    if pid <= 0:
        return ""
    result = subprocess.run(
        ["ps", "-p", str(pid), "-o", "comm="],
        check=False,
        text=True,
        capture_output=True,
    )
    raw = result.stdout.strip()
    return Path(raw).name if raw else ""


def read_ioreg(path: str) -> tuple[str, str]:
    if path:
        try:
            return Path(path).read_text(encoding="utf-8", errors="replace"), "fixture"
        except OSError as exc:
            return f"", f"fixture_error:{type(exc).__name__}"
    result = subprocess.run(
        ["ioreg", "-l", "-w", "0", "-c", "IOHIDSystem"],
        check=False,
        capture_output=True,
        timeout=5,
    )
    if result.returncode != 0:
        return "", f"ioreg_exit:{result.returncode}"
    # Some HID registry properties contain arbitrary bytes. They are unrelated
    # to the two ASCII session keys below and must not abort foreground checks.
    return result.stdout.decode("utf-8", errors="replace"), "ioreg"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check whether macOS can run a real foreground input-method acceptance test."
    )
    parser.add_argument("--require-ready", action="store_true")
    parser.add_argument("--report-path", default="")
    parser.add_argument("--ioreg-file", default="", help=argparse.SUPPRESS)
    args = parser.parse_args()

    raw, source = read_ioreg(args.ioreg_file)
    state = parse_session_state(raw)
    secure_pid = int(state["secureInputPid"])
    payload = {
        "schemaVersion": "rag-ime.macos-foreground-environment.v1",
        "source": source,
        **state,
        "secureInputOwner": secure_input_owner(secure_pid),
        "nextAction": (
            "unlock the Mac and leave password/account fields before foreground verification"
            if not state["ready"]
            else "run the foreground Squirrel acceptance gate"
        ),
    }
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.report_path:
        report_path = Path(args.report_path).expanduser()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    if args.require_ready and not state["ready"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
