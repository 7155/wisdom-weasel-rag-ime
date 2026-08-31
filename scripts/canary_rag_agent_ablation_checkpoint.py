#!/usr/bin/env python3
"""Run a deterministic Validation-only checkpoint/resume control-plane canary."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import run_rag_agent_ablation as ablation  # noqa: E402


SCHEMA_VERSION = "rag-ime.rag-agent-ablation-checkpoint-canary.v1"
_FIXED_TIME_SECONDS = 1_788_180_000.0
_FIXED_TIME_NANOSECONDS = 1_788_180_000_000_000_000


def _stable_hash(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _fingerprint() -> dict[str, object]:
    return ablation._lane_checkpoint_fingerprint(
        source_prepared_sha256=_stable_hash("prepared-validation-v1"),
        source_answer_cases_sha256=_stable_hash("answer-cases-validation-v1"),
        source_retrieval_report_sha256=_stable_hash("retrieval-report-validation-v1"),
        evaluation_mode="answer-only",
        evaluation_split="validation",
        case_ids_sha256=_stable_hash("validation-case-ids-v1"),
        case_set_sha256=_stable_hash("validation-case-set-v1"),
        answer_case_manifest_sha256=_stable_hash("answer-manifest-validation-v1"),
        prompt_config_sha256=_stable_hash("frozen-prompt-config-v1"),
        lane_prompt_sha256_by_lane={
            lane: _stable_hash(f"{lane}-validation-prompt-v1")
            for lane in ablation.LANES
        },
        skill_sha256=_stable_hash("rag-retrieval-optimization-skill-v1"),
        runtime_contract_sha256=_stable_hash("runtime-contract-v1"),
        default_retrieval_config_sha256=_stable_hash("default-retrieval-config-v1"),
        tuned_retrieval_config_sha256=_stable_hash("tuned-retrieval-config-v1"),
        model_route_identity_sha256=_stable_hash("openai-codex-gpt-5.6-sol-max"),
        pi_runtime_identity_sha256=_stable_hash("pinned-pi-runtime-v1"),
        maximum_attempts_per_lane=2,
    )


def _lane_record(
    lane: str,
    attempt: int,
    *,
    terminal_event: str,
    runtime_failure_category: str = "",
) -> dict[str, object]:
    return {
        "lane": lane,
        "promptSha256": _stable_hash(f"{lane}-validation-prompt-v1"),
        "terminalEvent": terminal_event,
        "runtimeFailureCategory": runtime_failure_category,
        "error": "",
        "toolContract": True,
        "scopeBoundary": True,
        "bindingCleanup": True,
        "binding": {"sessionId": f"agent:canary:{lane}:{attempt}"},
        "gatewayLedger": {"itemCount": 5, "failedItemCount": 0},
        "score": {
            "protocolErrors": [],
            "failedToolItemCount": 0,
            "hardEvidence": {
                "parameterBounded": True,
                "agenticLoopObserved": lane == "agentic",
            },
            "agentMetrics": {"outputProtocolRate": 1.0},
            "answerCases": [],
        },
        "_assistantText": f"private assistant output for {lane} attempt {attempt}",
        "_checkpointSessionId": f"agent:canary:{lane}:{attempt}",
        "_checkpointTurnId": f"turn:canary:{lane}:{attempt}",
    }


def _recovery_locator(
    lane: str,
    attempt: int,
    *,
    turn_id: str,
) -> dict[str, object]:
    session_id = f"agent:canary:{lane}:{attempt}"
    run_root = Path(f"/private/tmp/rag-checkpoint-canary/{lane}-{attempt}")
    return {
        "schemaVersion": "rag-ime.rag-agent-orphan-locator.v1",
        "runRoot": str(run_root),
        "agentDbPath": str(run_root / "agent.sqlite"),
        "sessionId": session_id,
        "turnId": turn_id,
        "sandboxRoot": str(run_root / "knowledge-runs"),
        "sandboxOwnerId": "ablation:canary-owner",
        "sandboxRunId": _stable_hash(f"sandbox:{lane}:{attempt}")[:32],
    }


def _run_canary() -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="rag-checkpoint-canary-") as temporary:
        checkpoint_path = Path(temporary) / "validation.checkpoint.json"
        with (
            patch.object(ablation.time, "time", return_value=_FIXED_TIME_SECONDS),
            patch.object(
                ablation.time,
                "time_ns",
                return_value=_FIXED_TIME_NANOSECONDS,
            ),
        ):
            fingerprint = _fingerprint()
            checkpoint = ablation._open_lane_checkpoint(
                checkpoint_path,
                fingerprint=fingerprint,
                resume=False,
            )
            initial_records = (
                _lane_record("baseline", 1, terminal_event="turn_completed"),
                _lane_record("skill", 1, terminal_event="turn_completed"),
                _lane_record(
                    "tuned",
                    1,
                    terminal_event="turn_failed",
                    runtime_failure_category="provider_transient_after_tool",
                ),
                _lane_record("agentic", 1, terminal_event=""),
            )
            for lane_record in initial_records:
                lane = str(lane_record["lane"])
                checkpoint = ablation._append_lane_checkpoint_attempt_started(
                    checkpoint_path,
                    checkpoint=checkpoint,
                    lane=lane,
                    attempt=1,
                )
                checkpoint = ablation._append_lane_checkpoint_attempt_binding(
                    checkpoint_path,
                    checkpoint=checkpoint,
                    lane=lane,
                    attempt=1,
                    session_id=f"agent:canary:{lane}:1",
                    turn_id="",
                    recovery_locator=_recovery_locator(
                        lane,
                        1,
                        turn_id="",
                    ),
                )
                checkpoint = ablation._append_lane_checkpoint_attempt_binding(
                    checkpoint_path,
                    checkpoint=checkpoint,
                    lane=lane,
                    attempt=1,
                    session_id=f"agent:canary:{lane}:1",
                    turn_id=f"turn:canary:{lane}:1",
                    recovery_locator=_recovery_locator(
                        lane,
                        1,
                        turn_id=f"turn:canary:{lane}:1",
                    ),
                )
                if lane == "agentic":
                    continue
                checkpoint = ablation._append_lane_checkpoint_attempt(
                    checkpoint_path,
                    checkpoint=checkpoint,
                    lane=lane,
                    attempt=1,
                    lane_record=lane_record,
                )

            initial_attempt_count = len(
                ablation._lane_checkpoint_attempt_records(checkpoint)
            )
            checkpoint = ablation._open_lane_checkpoint(
                checkpoint_path,
                fingerprint=fingerprint,
                resume=True,
            )
            checkpoint, recovery_summary = (
                ablation._recover_lane_checkpoint_orphans(
                    checkpoint_path,
                    checkpoint=checkpoint,
                    session_recover=lambda locator: {
                        "recovered": True,
                        "terminal": True,
                        "sessionSha256": _stable_hash(
                            str(locator["sessionId"])
                        ),
                        "turnSha256": (
                            _stable_hash(str(locator["turnId"]))
                            if locator["turnId"]
                            else ""
                        ),
                    },
                    sandbox_cleanup=lambda locator: {
                        "deleted": True,
                        "runId": str(locator["sandboxRunId"]),
                    },
                )
            )
            if recovery_summary["failClosed"] is True:
                raise RuntimeError("canary orphan recovery unexpectedly blocked")
            reusable_after_resume = ablation._lane_checkpoint_reusable_records(
                checkpoint
            )
            for lane in ("tuned", "agentic"):
                checkpoint = ablation._append_lane_checkpoint_attempt_started(
                    checkpoint_path,
                    checkpoint=checkpoint,
                    lane=lane,
                    attempt=2,
                )
                checkpoint = ablation._append_lane_checkpoint_attempt_binding(
                    checkpoint_path,
                    checkpoint=checkpoint,
                    lane=lane,
                    attempt=2,
                    session_id=f"agent:canary:{lane}:2",
                    turn_id="",
                    recovery_locator=_recovery_locator(
                        lane,
                        2,
                        turn_id="",
                    ),
                )
                checkpoint = ablation._append_lane_checkpoint_attempt_binding(
                    checkpoint_path,
                    checkpoint=checkpoint,
                    lane=lane,
                    attempt=2,
                    session_id=f"agent:canary:{lane}:2",
                    turn_id=f"turn:canary:{lane}:2",
                    recovery_locator=_recovery_locator(
                        lane,
                        2,
                        turn_id=f"turn:canary:{lane}:2",
                    ),
                )
                checkpoint = ablation._append_lane_checkpoint_attempt(
                    checkpoint_path,
                    checkpoint=checkpoint,
                    lane=lane,
                    attempt=2,
                    lane_record=_lane_record(
                        lane,
                        2,
                        terminal_event="turn_completed",
                    ),
                )
            final_reusable = ablation._lane_checkpoint_reusable_records(checkpoint)
            checkpoint_projection = ablation._lane_checkpoint_report_projection(
                checkpoint,
                resume_requested=True,
                initial_attempt_count=initial_attempt_count,
                reused_lanes=set(reusable_after_resume),
                fresh_lanes={"tuned", "agentic"},
            )

    expected_reused = ["baseline", "skill"]
    expected_final = list(ablation.LANES)
    passed = (
        [lane for lane in ablation.LANES if lane in reusable_after_resume]
        == expected_reused
        and [lane for lane in ablation.LANES if lane in final_reusable]
        == expected_final
        and checkpoint_projection["attemptCount"] == 6
        and checkpoint_projection["completedLaneCount"] == 4
        and checkpoint_projection["retriedLaneCount"] == 2
    )
    receipt = ablation._finalize_public_report(
        {
            "schemaVersion": SCHEMA_VERSION,
            "passed": passed,
            "scoreEligible": False,
            "formalAcceptanceEligible": False,
            "formalAcceptancePassed": False,
            "localOnly": True,
            "uploaded": False,
            "evaluation": {
                "mode": "checkpoint-resume-control-plane-canary",
                "split": "validation",
                "caseCount": 0,
                "caseIds": [],
                "heldOutAccessed": False,
                "heldOutConsumed": False,
            },
            "canary": {
                "scenario": (
                    "baseline-skill-complete_tuned-provider-failed_"
                    "agentic-nonterminal_then-explicit-resume"
                ),
                "modelInvoked": False,
                "metalRequired": False,
                "retrievalInvoked": False,
                "recoveryCallbacksSimulated": True,
                "liveSessionCancellationVerified": False,
                "reusedAfterExplicitResume": expected_reused,
                "finalReusableLanes": expected_final,
            },
        },
        checkpoint=checkpoint_projection,
    )
    if receipt.get("passed") is not True:
        raise RuntimeError("Validation checkpoint/resume control-plane canary failed")
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    output = args.output.expanduser().resolve(strict=False)
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    receipt = _run_canary()
    ablation._write_json(output, receipt)
    print(
        json.dumps(
            {
                "event": "completed",
                "passed": receipt["passed"],
                "output": str(output),
                "reportSha256": receipt["reportSha256"],
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
