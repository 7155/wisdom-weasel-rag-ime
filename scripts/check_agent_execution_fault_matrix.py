#!/usr/bin/env python3
"""Run isolated execution faults; retain case results and exact source hashes.

These tests use temporary databases, synthetic effects and loopback fixtures.
They do not exercise the installed application or configured model Providers.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
from pathlib import Path
import platform
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

GROUPS = (
    ("R1/R4/R5", "durable attempts and bounded retry; fixture Pi runtime", (
        "tests.test_agent_execution_attempts",
        "tests.test_agent_delegation.AgentDelegationTests.test_retry_policy_allows_only_one_receipt_free_runtime_retry",
        "tests.test_agent_delegation.AgentDelegationTests.test_first_terminal_result_is_ingested_once_and_late_terminal_is_ignored",
    )),
    ("F1", "real host and worker processes", (
        "tests.test_agent_background_job_process_faults",
        "tests.test_agent_background_launch_recovery",
    )),
    ("F1/F2/F3", "real loopback transport and Lab owner; synthetic effects", (
        "tests.test_agent_execution_network_faults",
    )),
    ("F3", "real background admission and processes; Gateway contract", (
        "tests.test_agent_background_job_idempotency",
        "tests.test_workspace_job_idempotency_gateway",
    )),
    ("F1/F4", "two real supervisor processes; lease heartbeat and stale write fencing", (
        "tests.test_agent_background_job_ownership",
    )),
    ("F4", "real process tree and Room event contracts", (
        "tests.test_agent_execution_process_faults",
        "tests.test_agent_delegation_cancel_contention",
        "tests.test_agent_lifecycle_cancellation.AgentLifecycleCancellationTests.test_delegation_owner_aborts_matching_running_children_and_replays_receipt",
        "tests.test_agent_room_turn_registry.RuntimeTurnBindingTests.test_cancelled_turn_rejects_late_events_and_allows_next_turn",
        "tests.test_agent_room_turn_registry.RuntimeTurnBindingTests.test_cancelled_abort_terminal_can_be_claimed_exactly_once",
        "tests.test_agent_room_turn_registry.RuntimeTurnBindingTests.test_cancelled_root_cannot_begin_a_late_wake_turn",
    )),
    ("F5a", "native workspace sandbox", (
        "tests.test_agent_workspace.AgentWorkspaceHarnessTests.test_real_harness_runs_inside_workspace_and_denies_outside_read",
        "tests.test_agent_workspace.AgentWorkspaceHarnessTests.test_read_only_harness_runs_tests_but_only_writes_command_temp",
    )),
    ("F5b", "full-authority execution and Room/Trace policy contracts", (
        "tests.test_agent_workspace.AgentWorkspaceHarnessTests.test_unrestricted_shell_inherits_environment_and_normalizes_tool_path",
        "tests.test_agent_workspace.AgentWorkspaceHarnessTests.test_unrestricted_profiles_admit_full_disk_system_network_and_sensitive_commands",
        "tests.test_agent_execution_policy.AgentExecutionPolicyTests.test_confirmed_room_unrestricted_skips_per_tool_approval_within_fences",
        "tests.test_agent_tools.ControlToolGatewayTests.test_confirmed_room_unrestricted_executes_without_per_tool_prompt",
        "tests.test_trace_agent_diagnostics_skill",
    )),
)


class CaseResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cases = []
        self.started = 0.0

    def startTest(self, test):
        self.started = time.monotonic()
        super().startTest(test)

    def stopTest(self, test):
        failures = {getattr(case, "test_case", case).id() for case, _ in self.failures}
        errors = {getattr(case, "test_case", case).id() for case, _ in self.errors}
        skipped = dict((getattr(case, "test_case", case).id(), reason) for case, reason in self.skipped)
        identity = test.id()
        status = "failed" if identity in failures else "error" if identity in errors else "skipped" if identity in skipped else "passed"
        self.cases.append({
            "test": identity, "status": status,
            "elapsedSeconds": round(time.monotonic() - self.started, 3),
            **({"reason": skipped[identity]} if identity in skipped else {}),
        })
        super().stopTest(test)


def source_hashes():
    paths = {
        "rag_ime/agent_background_jobs.py", "rag_ime/agent_workspace.py",
        "rag_ime/agent_background_launch.py",
        "rag_ime/agent_background_ownership.py",
        "rag_ime/agent_tools.py", "rag_ime/agent_execution_policy.py",
        "rag_ime/agent_lab/trials.py", "rag_ime/agent_lab/trial_execution.py",
        "rag_ime/agent_delegation.py", "rag_ime/agent_context_runtime.py",
        "tests/test_agent_delegation.py",
        "rag_ime/rooms/turn_registry.py",
        "rag_ime/db/migrations/0192_background_job_request_identity.sql",
        "rag_ime/db/migrations/0193_background_job_owner_leases.sql",
        "tests/fixtures/agent_execution_fault_host.py",
        "tests/fixtures/agent_background_ownership_host.py",
        str(Path(__file__).resolve().relative_to(ROOT)),
    }
    for _fault, _boundary, names in GROUPS:
        paths.update("/".join(name.split(".")[:2]) + ".py" for name in names)
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in sorted(paths)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path)
    args = parser.parse_args()
    if args.output_root:
        output = args.output_root.expanduser().resolve()
        if output == ROOT or ROOT in output.parents:
            parser.error("write generated receipts outside the repository")
        output.mkdir(parents=True, mode=0o700, exist_ok=False)
    else:
        output = Path(tempfile.mkdtemp(prefix="paw-execution-fault-matrix-"))
    before = source_hashes()
    rows = []
    for index, (fault, boundary, names) in enumerate(GROUPS, 1):
        log = output / f"{index:02d}-tests.log"
        with log.open("w", encoding="utf-8") as stream:
            with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
                suite = unittest.defaultTestLoader.loadTestsFromNames(names)
                result = unittest.TextTestRunner(
                    stream=stream, verbosity=2, resultclass=CaseResult,
                ).run(suite)
        rows.append({"fault": fault, "boundary": boundary, "log": log.name, "cases": result.cases})
        print(f"{fault}: {result.testsRun} cases; failures={len(result.failures)} errors={len(result.errors)} skipped={len(result.skipped)}", flush=True)
    after = source_hashes()
    cases = [case for row in rows for case in row["cases"]]
    status_counts = {status: sum(case["status"] == status for case in cases) for status in ("passed", "failed", "error", "skipped")}
    report = {
        "schemaVersion": "paw.execution-fault-matrix.v1",
        "python": sys.version, "platform": platform.platform(),
        "sourceHashesBefore": before, "sourceHashesAfter": after,
        "sourceUnchangedDuringRun": before == after,
        "boundary": "isolated source tests; synthetic effects; no installed application or configured Provider acceptance",
        "groups": rows, "counts": status_counts,
        "unverified": [
            "cross-machine execution transport and storage; current leases use same-host SQLite and monotonic time",
            "supervisor pause while holding a SQLite transaction; not a heartbeat-only outage",
            "host failure before the launcher can persist a valid startup receipt",
            "automatic reconciliation of arbitrary external writes",
            "installed Gateway, Providers and foreground UI",
        ],
    }
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Receipt: {output / 'report.json'}")
    return 0 if before == after and status_counts["passed"] == len(cases) and cases else 1


if __name__ == "__main__":
    raise SystemExit(main())
