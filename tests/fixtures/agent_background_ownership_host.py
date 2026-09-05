"""Private multiprocess lease fault fixture. Never targets the installed app."""
from pathlib import Path
import json
import shlex
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from rag_ime.agent_background_jobs import AgentBackgroundJobService
from rag_ime.agent_sessions import AgentSessionStore


def main():
    root = Path(sys.argv[1])
    session_id, name = sys.argv[2:4]
    service = AgentBackgroundJobService(
        root / "jobs.sqlite", events=lambda *a, **k: None, lease_seconds=2,
    )
    service.initialize()
    try:
        if name == "a":
            prepared = service.workspace_harness.prepare_background_command(
                AgentSessionStore(root / "jobs.sqlite").get(session_id), {
                    "command": shlex.join([sys.executable, str(root / "command.py")]),
                    "cwd": str(root), "timeoutSeconds": 30,
                },
            )
            job = service.start(session_id, prepared)["job"]
            job_id = job["jobId"]
            original_live = service._live[job_id]
            (root / "a-ready").write_text(json.dumps(job))
        else:
            (root / "b-ready").touch()
        while not (root / "stop-hosts").exists():
            if name == "a" and (root / "probe-old-owner").exists() and not (root / "probe-result").exists():
                rejected = {}
                for operation, action in {
                    "progress": lambda: service._persist_live_progress(job_id, original_live, force=True),
                    "terminal": lambda: service._mark_launch_failed(job_id, "stale result"),
                    "result": lambda: service._commit_result(job_id, original_live, exit_code=0, timed_out=False),
                    "timeout": lambda: service._request_timeout(job_id),
                    "release": lambda: service._release_launch(job_id),
                    "terminate": lambda: service._terminate_live(original_live),
                    "cleanup": lambda: service._cleanup_runtime_files(original_live),
                }.items():
                    try:
                        action()
                    except Exception as exc:
                        rejected[operation] = type(exc).__name__
                    else:
                        rejected[operation] = "NOT_REJECTED"
                (root / "probe-result").write_text(json.dumps(rejected))
            time.sleep(0.02)
    finally:
        service.close()


if __name__ == "__main__":
    main()
