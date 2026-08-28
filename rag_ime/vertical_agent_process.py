"""Run an external vertical Agent and close its Trace/Eval receipt chain.

This is the small bridge for a custom vertical application.  The Agent is a
real child process launched by the default :class:`WorkspaceHarness`; its
stdout must contain exactly one canonical Trace JSON envelope.  The parent
then owns verification and durable Trace/Eval persistence.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from .agent_workspace import WorkspaceHarness
from .eval_run_store import EvalRunStore
from .trace_store import TraceStore
from .vertical_agent_harness import VerticalHarnessError
from .vertical_agent_suite import evaluate_vertical_agent_case_trace


class VerticalAgentProcessError(VerticalHarnessError):
    """The external vertical Agent did not produce a usable Trace receipt."""


def run_external_vertical_agent_process(
    manifest: Mapping[str, object],
    *,
    session: Mapping[str, object],
    source_session_id: str,
    command: str,
    cwd: str | Path,
    eval_store: EvalRunStore,
    trace_store: TraceStore,
    workspace_harness: WorkspaceHarness | None = None,
    fixture_id: str | None = None,
    timeout_seconds: int = 120,
    allow_network: bool = False,
    now_ms: int | None = None,
) -> dict[str, object]:
    """Execute one custom Agent and persist its verified Trace and EvalRun.

    When no harness is supplied, ``WorkspaceHarness()`` is constructed with
    its defaults so the production lane uses macOS ``sandbox-exec``.  The
    subprocess protocol is deliberately narrow: stdout is one JSON Trace and
    stderr is not a second channel because the harness merges it into the
    receipt.
    """

    harness = workspace_harness or WorkspaceHarness()
    prepared = harness.prepare_command(
        session,
        {
            "command": command,
            "cwd": str(cwd),
            "timeoutSeconds": timeout_seconds,
            "allowNetwork": allow_network,
        },
    )
    receipt = harness.execute(prepared)
    if (
        receipt.get("exitCode") != 0
        or receipt.get("timedOut") is True
        or receipt.get("outputLimited") is True
    ):
        raise VerticalAgentProcessError(
            "vertical Agent process did not complete successfully"
        )

    output = receipt.get("output")
    if not isinstance(output, str) or not output.strip():
        raise VerticalAgentProcessError(
            "vertical Agent process must emit one Trace JSON object"
        )
    try:
        trace = json.loads(output)
    except json.JSONDecodeError as exc:
        raise VerticalAgentProcessError(
            "vertical Agent stdout is not canonical Trace JSON"
        ) from exc
    if not isinstance(trace, Mapping):
        raise VerticalAgentProcessError(
            "vertical Agent stdout must be one Trace JSON object"
        )

    binding = trace.get("binding")
    if not isinstance(binding, Mapping):
        raise VerticalAgentProcessError(
            "vertical Agent Trace binding must be an object"
        )
    bound_trace = dict(trace)
    bound_trace["binding"] = {
        **binding,
        "sessionId": source_session_id,
    }

    evaluated = evaluate_vertical_agent_case_trace(
        manifest,
        bound_trace,
        eval_store=eval_store,
        trace_store=trace_store,
        fixture_id=fixture_id,
        now_ms=now_ms,
    )
    return {"processReceipt": dict(receipt), **evaluated}
