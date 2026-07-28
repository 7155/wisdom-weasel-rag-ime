#!/usr/bin/env python3
"""Build an honest, subprocess-isolated Prompt A/B plan or observed report.

This runner deliberately does not call the product Provider.  The product has
no request-scoped system-prompt override:

* ordinary Sessions compile the prompt inside
  ``PiRuntimeConfig.system_prompt_for_session``;
* Room Sessions accept only the PromptPlan-sealed ``managedSystemPrompt``.

Changing either path for an experiment would add production behavior or mutate
durable Room state.  ``--dry-run`` therefore materializes only an execution
plan and marks every Provider receipt as not run.  ``--observations`` consumes
event/receipt records captured by a separately authorized product harness,
validates them in one fresh subprocess per run, and emits the fixture's
per-run and aggregate report fields without inventing missing evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from statistics import fmean
from typing import Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "agent_prompt_ablation"
    / "managed-work-ablation.v1.json"
)
REPORT_SCHEMA_VERSION = "personal-agent-workbench.prompt-ablation-report.v1"
OBSERVATION_SCHEMA_VERSION = (
    "personal-agent-workbench.prompt-ablation-observation.v1"
)
EXECUTION_BOUNDARY = {
    "providerExecutionImplemented": False,
    "reason": (
        "The production Session API has no request-scoped system-prompt "
        "override. Ordinary Sessions compile it in "
        "PiRuntimeConfig.system_prompt_for_session; Room Sessions accept only "
        "the PromptPlan-sealed managedSystemPrompt. Exact A/B Provider runs "
        "therefore require a separately reviewed harness or production "
        "override and are not performed by this script."
    ),
    "sourceChain": [
        "rag_ime/agent_prompt_application.py:AgentPromptApplicationService.prompt",
        "rag_ime/agent_prompt_delivery.py:AgentPromptDeliveryService.deliver",
        "rag_ime/pi_runtime.py:PiRuntimeConfig.system_prompt_for_session",
        "rag_ime/pi_runtime_v2.py:PiRuntimeHostManager.ensure",
        "rag_ime/pi_runtime_v2.py:PiRuntimeHostManager.prompt",
        (
            "pi-rag-ime-runtime/packages/rag-ime-runtime-host/src/"
            "pi-session.ts:ProductPiSession.prompt"
        ),
    ],
}
OBSERVATION_CONTRACT = {
    "captureSource": "product_session_events",
    "providerReceipt": (
        "Preserve the exact prompt-acceptance and message-completed payloads. "
        "The completion usage object supplies Provider token evidence."
    ),
    "promptReceipt": (
        "Bind the managed-work layer hash to the compiled system-prompt hash, "
        "the fixed-layer hash, and the exact system-prompt hash accepted by "
        "the Provider. Kernel-pre-dispatch records must prove no Prompt was "
        "compiled or accepted."
    ),
    "toolTrace": (
        "One completed-call receipt per Tool call, in execution order; rawEvents "
        "may retain the unmodified start/update/end envelopes."
    ),
    "timingReceipt": (
        "startedAtMs and firstActionAtMs from one monotonic harness clock."
    ),
    "isolationReceipt": (
        "Every run is created in a fresh subprocess, Session, Context Epoch, "
        "and materialized workspace fixture."
    ),
}
_VARIANTS = ("A", "B")
_KERNEL_VARIANT = "K"


class AblationReportError(ValueError):
    """Raised when a fixture or observation cannot support a truthful report."""


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _required_mapping(
    value: object,
    *,
    label: str,
) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise AblationReportError(f"{label} must be an object")
    return value


def _required_non_empty_text(value: object, *, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise AblationReportError(f"{label} must not be empty")
    return text


def _required_non_negative_number(value: object, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AblationReportError(f"{label} must be a number")
    number = float(value)
    if number < 0:
        raise AblationReportError(f"{label} must be non-negative")
    return number


def _required_non_negative_int(value: object, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise AblationReportError(f"{label} must be a non-negative integer")
    return value


def load_fixture(path: Path) -> dict[str, object]:
    fixture = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(fixture, dict):
        raise AblationReportError("fixture must be an object")
    if fixture.get("schemaVersion") != (
        "personal-agent-workbench.prompt-ablation-matrix.v1"
    ):
        raise AblationReportError("unsupported Prompt ablation fixture")
    report_schema = _required_mapping(
        fixture.get("reportSchema"),
        label="reportSchema",
    )
    for key in ("perRunRequired", "aggregateRequired"):
        values = report_schema.get(key)
        if not isinstance(values, list) or not values:
            raise AblationReportError(f"reportSchema.{key} must be a list")
    variable = _required_mapping(fixture.get("variable"), label="variable")
    for variant_key in ("variantA", "variantB"):
        variant = _required_mapping(
            variable.get(variant_key),
            label=f"variable.{variant_key}",
        )
        prompt_lines = variant.get("promptLines")
        if not isinstance(prompt_lines, list) or not all(
            isinstance(line, str) for line in prompt_lines
        ):
            raise AblationReportError(
                f"variable.{variant_key}.promptLines must be strings"
            )
        prompt = "\n".join(prompt_lines)
        metrics = _required_mapping(
            variant.get("metrics"),
            label=f"variable.{variant_key}.metrics",
        )
        encoded = prompt.encode("utf-8")
        expected = {
            "chars": len(prompt),
            "utf8Bytes": len(encoded),
            "estimatedTokens": (len(encoded) + 3) // 4,
            "lines": len(prompt.splitlines()),
            "sha256": hashlib.sha256(encoded).hexdigest(),
        }
        if dict(metrics) != expected:
            raise AblationReportError(
                f"variable.{variant_key}.metrics does not match prompt bytes"
            )
    scenarios = fixture.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        raise AblationReportError("scenarios must be a non-empty list")
    seen: set[str] = set()
    for raw_scenario in scenarios:
        scenario = _required_mapping(raw_scenario, label="scenario")
        scenario_id = _required_non_empty_text(
            scenario.get("id"),
            label="scenario.id",
        )
        if scenario_id in seen:
            raise AblationReportError(f"duplicate scenario: {scenario_id}")
        seen.add(scenario_id)
        layer = scenario.get("executionLayer")
        expected_provider = scenario.get("providerInvocationExpected")
        if layer not in {"provider", "kernel_pre_dispatch"}:
            raise AblationReportError(
                f"{scenario_id}: unsupported executionLayer"
            )
        if not isinstance(expected_provider, bool):
            raise AblationReportError(
                f"{scenario_id}: providerInvocationExpected must be boolean"
            )
        if (layer == "provider") is not expected_provider:
            raise AblationReportError(
                f"{scenario_id}: execution layer and Provider expectation differ"
            )
    return fixture


def _scenario_map(
    fixture: Mapping[str, object],
) -> dict[str, Mapping[str, object]]:
    scenarios = fixture["scenarios"]
    assert isinstance(scenarios, list)
    return {
        str(scenario["id"]): scenario
        for scenario in scenarios
        if isinstance(scenario, Mapping)
    }


def _variant(
    fixture: Mapping[str, object],
    label: str,
) -> Mapping[str, object]:
    if label not in _VARIANTS:
        raise AblationReportError(f"unknown variant: {label}")
    variable = _required_mapping(fixture["variable"], label="variable")
    return _required_mapping(
        variable[f"variant{label}"],
        label=f"variant{label}",
    )


def _prompt_tokens(
    fixture: Mapping[str, object],
    variant_label: str,
) -> int:
    if variant_label == _KERNEL_VARIANT:
        return 0
    return int(
        _required_mapping(
            _variant(fixture, variant_label)["metrics"],
            label="variant metrics",
        )["estimatedTokens"]
    )


def _balanced_order(scenario_id: str, runs_per_variant: int) -> list[str]:
    if runs_per_variant < 1:
        raise AblationReportError("runs per variant must be positive")
    pattern = "ABBA"
    if int(hashlib.sha256(scenario_id.encode()).hexdigest(), 16) % 2:
        pattern = "BAAB"
    order = (pattern * (runs_per_variant + 1))[: runs_per_variant * 2]
    if order.count("A") != runs_per_variant:
        # A truncated four-item block can only be imbalanced at an odd length;
        # the experiment always has an even total, but keep the invariant
        # explicit so a future order-policy edit fails closed.
        raise AblationReportError(
            f"{scenario_id}: balanced order generation failed"
        )
    return list(order)


def _safe_relative_path(value: object) -> Path:
    raw = _required_non_empty_text(value, label="workspace fixture path")
    pure = PurePosixPath(raw)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise AblationReportError(f"unsafe workspace fixture path: {raw}")
    return Path(*pure.parts)


def _materialize_workspace(
    scenario: Mapping[str, object],
    root: Path,
) -> str:
    setup = _required_mapping(scenario.get("setup"), label="scenario.setup")
    raw_fixture = setup.get("workspaceFixture") or {}
    fixture = _required_mapping(
        raw_fixture,
        label="scenario.setup.workspaceFixture",
    )
    digest_items: list[dict[str, object]] = []
    for raw_path, raw_content in sorted(
        fixture.items(),
        key=lambda item: str(item[0]),
    ):
        relative = _safe_relative_path(raw_path)
        content = str(raw_content)
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        digest_items.append(
            {
                "path": relative.as_posix(),
                "sha256": hashlib.sha256(
                    content.encode("utf-8")
                ).hexdigest(),
                "utf8Bytes": len(content.encode("utf-8")),
            }
        )
    return _sha256_json(digest_items)


def _expected_tool_projection(
    scenario: Mapping[str, object],
) -> list[dict[str, object]]:
    calls = scenario.get("expectedCalls")
    if not isinstance(calls, list):
        raise AblationReportError("scenario.expectedCalls must be a list")
    projected: list[dict[str, object]] = []
    for raw_call in calls:
        call = _required_mapping(raw_call, label="expected call")
        count = _required_non_negative_int(
            call.get("count"),
            label="expected call count",
        )
        if count < 1:
            raise AblationReportError("expected call count must be positive")
        for _ in range(count):
            projected.append(
                {
                    "tool": str(call.get("tool") or ""),
                    "operation": str(call.get("operation") or ""),
                    "arguments": dict(
                        _required_mapping(
                            call.get("arguments"),
                            label="expected call arguments",
                        )
                    ),
                }
            )
    return projected


def _actual_tool_projection(
    raw_trace: object,
) -> list[dict[str, object]]:
    if not isinstance(raw_trace, list):
        raise AblationReportError("toolTrace must be a list")
    projected: list[dict[str, object]] = []
    for index, raw_entry in enumerate(raw_trace):
        entry = _required_mapping(
            raw_entry,
            label=f"toolTrace[{index}]",
        )
        projected.append(
            {
                "tool": _required_non_empty_text(
                    entry.get("tool"),
                    label=f"toolTrace[{index}].tool",
                ),
                "operation": _required_non_empty_text(
                    entry.get("operation"),
                    label=f"toolTrace[{index}].operation",
                ),
                "arguments": dict(
                    _required_mapping(
                        entry.get("arguments"),
                        label=f"toolTrace[{index}].arguments",
                    )
                ),
            }
        )
    return projected


def _iso_utc(milliseconds: int) -> str:
    return datetime.fromtimestamp(
        milliseconds / 1000,
        tz=UTC,
    ).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _planned_run(
    fixture: Mapping[str, object],
    scenario: Mapping[str, object],
    *,
    variant_label: str,
    run_ordinal: int,
    run_index: int,
    model: str,
    reasoning_effort: str,
) -> dict[str, object]:
    expected_provider = bool(scenario["providerInvocationExpected"])
    if expected_provider and variant_label not in _VARIANTS:
        raise AblationReportError(
            "Provider scenarios require Prompt variant A or B"
        )
    if not expected_provider and variant_label != _KERNEL_VARIANT:
        raise AblationReportError(
            "kernel-pre-dispatch scenarios use only variant K"
        )
    with tempfile.TemporaryDirectory(
        prefix="prompt-ablation-plan-"
    ) as raw_root:
        workspace_hash = _materialize_workspace(
            scenario,
            Path(raw_root),
        )
    execution_layer = str(scenario["executionLayer"])
    acceptance = scenario.get("acceptanceEvidence")
    if not isinstance(acceptance, list):
        raise AblationReportError(
            "scenario.acceptanceEvidence must be a list"
        )
    record: dict[str, object] = {
        "scenarioId": str(scenario["id"]),
        "variant": variant_label,
        "runOrdinal": run_ordinal,
        "model": model,
        "reasoningEffort": reasoning_effort,
        "runIndex": run_index,
        "startedAt": "",
        "firstActionLatencyMs": None,
        "toolTrace": [],
        "output": "",
        "assertions": [
            {
                "id": f"acceptance-{index}",
                "passed": False,
                "evidence": (
                    "not evaluated: dry-run does not call the Provider; "
                    f"required evidence: {text}"
                ),
            }
            for index, text in enumerate(acceptance, start=1)
        ],
        "metrics": {
            "taskSuccess": None,
            "forbiddenBehaviorCount": None,
            "toolTraceExactMatch": None,
            "outputTokens": None,
            "systemPromptTokens": _prompt_tokens(fixture, variant_label),
            "roomPingPongTurns": None,
            "workspaceStateSha256": workspace_hash,
        },
        "providerReceipt": {
            "invoked": False,
            "expected": expected_provider,
            "executionLayer": execution_layer,
            "status": "not-run",
            "reason": (
                EXECUTION_BOUNDARY["reason"]
                if expected_provider
                else (
                    "The fixture routes this scenario through "
                    "kernel_pre_dispatch, so a Provider call is forbidden."
                )
            ),
        },
        "promptReceipt": (
            {
                "invoked": False,
                "reason": (
                    "not-run"
                    if expected_provider
                    else "kernel_pre_dispatch"
                ),
            }
        ),
        "status": "planned-not-run",
        "expectedToolTrace": _expected_tool_projection(scenario),
        "workerReceipt": {
            "pid": os.getpid(),
            "stateScope": "fresh-subprocess-temporary-workspace",
        },
    }
    _require_report_keys(fixture, record, aggregate=False)
    return record


def _require_report_keys(
    fixture: Mapping[str, object],
    record: Mapping[str, object],
    *,
    aggregate: bool,
) -> None:
    report_schema = _required_mapping(
        fixture["reportSchema"],
        label="reportSchema",
    )
    key = "aggregateRequired" if aggregate else "perRunRequired"
    required = report_schema[key]
    assert isinstance(required, list)
    missing = [str(name) for name in required if name not in record]
    if missing:
        raise AblationReportError(
            f"record is missing fixture-required fields: {', '.join(missing)}"
        )


def _validate_assertions(raw: object) -> list[dict[str, object]]:
    if not isinstance(raw, list) or not raw:
        raise AblationReportError("assertions must be a non-empty list")
    result: list[dict[str, object]] = []
    for index, raw_assertion in enumerate(raw):
        assertion = _required_mapping(
            raw_assertion,
            label=f"assertions[{index}]",
        )
        assertion_id = _required_non_empty_text(
            assertion.get("id"),
            label=f"assertions[{index}].id",
        )
        passed = assertion.get("passed")
        if not isinstance(passed, bool):
            raise AblationReportError(
                f"assertions[{index}].passed must be boolean"
            )
        evidence = _required_non_empty_text(
            assertion.get("evidence"),
            label=f"assertions[{index}].evidence",
        )
        result.append(
            {
                "id": assertion_id,
                "passed": passed,
                "evidence": evidence,
            }
        )
    return result


def _validate_provider_receipt(
    raw: object,
    *,
    expected: bool,
    execution_layer: str,
    output_tokens: int,
) -> dict[str, object]:
    receipt = dict(
        _required_mapping(raw, label="providerReceipt")
    )
    invoked = receipt.get("invoked")
    if not isinstance(invoked, bool):
        raise AblationReportError(
            "providerReceipt.invoked must be boolean"
        )
    if invoked is not expected:
        raise AblationReportError(
            "providerReceipt.invoked disagrees with "
            "providerInvocationExpected"
        )
    source = _required_non_empty_text(
        receipt.get("source"),
        label="providerReceipt.source",
    )
    if expected:
        if execution_layer != "provider":
            raise AblationReportError(
                "Provider invocation cannot occur outside the provider layer"
            )
        if source != "product_session_events":
            raise AblationReportError(
                "Provider observations must come from product_session_events"
            )
        acceptance = _required_mapping(
            receipt.get("acceptance"),
            label="providerReceipt.acceptance",
        )
        completion = _required_mapping(
            receipt.get("completion"),
            label="providerReceipt.completion",
        )
        _required_non_empty_text(
            acceptance.get("turnId"),
            label="providerReceipt.acceptance.turnId",
        )
        if acceptance.get("accepted") is not True:
            raise AblationReportError(
                "providerReceipt.acceptance.accepted must be true"
            )
        if completion.get("event") != "message_completed":
            raise AblationReportError(
                "providerReceipt.completion.event must be message_completed"
            )
        usage = _required_mapping(
            completion.get("usage"),
            label="providerReceipt.completion.usage",
        )
        normalized_usage = {
            key: _required_non_negative_int(
                usage.get(key),
                label=f"providerReceipt.completion.usage.{key}",
            )
            for key in (
                "input",
                "output",
                "cacheRead",
                "cacheWrite",
                "totalTokens",
            )
        }
        observed_output = normalized_usage["output"]
        if observed_output != output_tokens:
            raise AblationReportError(
                "metrics.outputTokens must equal completion usage.output"
            )
    else:
        if execution_layer != "kernel_pre_dispatch":
            raise AblationReportError(
                "Only kernel_pre_dispatch may skip the Provider"
            )
        if source != "kernel_pre_dispatch":
            raise AblationReportError(
                "skipped Provider receipt must identify kernel_pre_dispatch"
            )
        if "acceptance" in receipt or "completion" in receipt:
            raise AblationReportError(
                "kernel-pre-dispatch receipt cannot contain Provider events"
            )
        if output_tokens != 0:
            raise AblationReportError(
                "kernel-pre-dispatch outputTokens must be zero"
            )
    return receipt


def _validate_prompt_receipt(
    raw: object,
    *,
    fixture: Mapping[str, object],
    variant_label: str,
    expected_provider: bool,
    provider_receipt: Mapping[str, object],
) -> dict[str, object]:
    receipt = dict(_required_mapping(raw, label="promptReceipt"))
    invoked = receipt.get("invoked")
    if not isinstance(invoked, bool):
        raise AblationReportError("promptReceipt.invoked must be boolean")
    if invoked is not expected_provider:
        raise AblationReportError(
            "promptReceipt.invoked disagrees with Provider expectation"
        )
    if not expected_provider:
        if set(receipt) != {"invoked", "reason"}:
            raise AblationReportError(
                "kernel promptReceipt cannot contain Prompt hashes"
            )
        if receipt.get("reason") != "kernel_pre_dispatch":
            raise AblationReportError(
                "kernel promptReceipt must identify kernel_pre_dispatch"
            )
        return receipt

    variant_metrics = _required_mapping(
        _variant(fixture, variant_label)["metrics"],
        label="variant metrics",
    )
    layer_sha = _required_non_empty_text(
        receipt.get("managedWorkLayerSha256"),
        label="promptReceipt.managedWorkLayerSha256",
    )
    if layer_sha != variant_metrics["sha256"]:
        raise AblationReportError(
            "promptReceipt managed-work layer does not match the fixture variant"
        )
    fixed_sha = _required_non_empty_text(
        receipt.get("fixedLayersSha256"),
        label="promptReceipt.fixedLayersSha256",
    )
    compiled_sha = _required_non_empty_text(
        receipt.get("compiledSystemPromptSha256"),
        label="promptReceipt.compiledSystemPromptSha256",
    )
    for label, value in (
        ("fixedLayersSha256", fixed_sha),
        ("compiledSystemPromptSha256", compiled_sha),
    ):
        if len(value) != 64 or any(
            character not in "0123456789abcdef" for character in value
        ):
            raise AblationReportError(
                f"promptReceipt.{label} must be lowercase sha256"
            )
    acceptance = _required_mapping(
        provider_receipt.get("acceptance"),
        label="providerReceipt.acceptance",
    )
    if acceptance.get("systemPromptSha256") != compiled_sha:
        raise AblationReportError(
            "Provider acceptance did not bind the compiled system Prompt"
        )
    if receipt.get("estimatedManagedWorkTokens") != _prompt_tokens(
        fixture,
        variant_label,
    ):
        raise AblationReportError(
            "promptReceipt managed-work token count does not match the fixture"
        )
    return receipt


def _observed_run(
    fixture: Mapping[str, object],
    observation: Mapping[str, object],
) -> dict[str, object]:
    if observation.get("schemaVersion") != OBSERVATION_SCHEMA_VERSION:
        raise AblationReportError("unsupported observation schema")
    scenario_id = _required_non_empty_text(
        observation.get("scenarioId"),
        label="scenarioId",
    )
    scenarios = _scenario_map(fixture)
    if scenario_id not in scenarios:
        raise AblationReportError(f"unknown scenario: {scenario_id}")
    scenario = scenarios[scenario_id]
    expected_provider = bool(scenario["providerInvocationExpected"])
    variant_label = _required_non_empty_text(
        observation.get("variant"),
        label="variant",
    )
    if expected_provider and variant_label not in _VARIANTS:
        raise AblationReportError(
            "Provider scenarios require Prompt variant A or B"
        )
    if not expected_provider and variant_label != _KERNEL_VARIANT:
        raise AblationReportError(
            "kernel-pre-dispatch scenarios use only variant K"
        )
    run_index = _required_non_negative_int(
        observation.get("runIndex"),
        label="runIndex",
    )
    if run_index < 1:
        raise AblationReportError("runIndex must be positive")
    run_ordinal = _required_non_negative_int(
        observation.get("runOrdinal"),
        label="runOrdinal",
    )
    if run_ordinal < 1:
        raise AblationReportError("runOrdinal must be positive")
    model = _required_non_empty_text(
        observation.get("model"),
        label="model",
    )
    reasoning_effort = _required_non_empty_text(
        observation.get("reasoningEffort"),
        label="reasoningEffort",
    )
    started_at = _required_non_empty_text(
        observation.get("startedAt"),
        label="startedAt",
    )
    latency = _required_non_negative_number(
        observation.get("firstActionLatencyMs"),
        label="firstActionLatencyMs",
    )
    timing = dict(
        _required_mapping(
            observation.get("timingReceipt"),
            label="timingReceipt",
        )
    )
    started_at_ms = _required_non_negative_int(
        timing.get("startedAtMs"),
        label="timingReceipt.startedAtMs",
    )
    first_action_at_ms = _required_non_negative_int(
        timing.get("firstActionAtMs"),
        label="timingReceipt.firstActionAtMs",
    )
    if first_action_at_ms < started_at_ms:
        raise AblationReportError(
            "timingReceipt first action precedes start"
        )
    measured_latency = first_action_at_ms - started_at_ms
    if float(measured_latency) != latency:
        raise AblationReportError(
            "firstActionLatencyMs does not match timingReceipt"
        )
    if started_at != _iso_utc(started_at_ms):
        raise AblationReportError(
            "startedAt does not match timingReceipt.startedAtMs"
        )
    raw_trace = observation.get("toolTrace")
    actual_projection = _actual_tool_projection(raw_trace)
    expected_projection = _expected_tool_projection(scenario)
    trace_matches = actual_projection == expected_projection
    output = str(observation.get("output") or "")
    assertions = _validate_assertions(observation.get("assertions"))
    expected_assertion_ids = [
        f"acceptance-{index}"
        for index in range(
            1,
            len(scenario["acceptanceEvidence"]) + 1,
        )
    ]
    if [str(item["id"]) for item in assertions] != expected_assertion_ids:
        raise AblationReportError(
            "assertions must cover every acceptanceEvidence item in order"
        )
    raw_metrics = _required_mapping(
        observation.get("metrics"),
        label="metrics",
    )
    forbidden_count = _required_non_negative_int(
        raw_metrics.get("forbiddenBehaviorCount"),
        label="metrics.forbiddenBehaviorCount",
    )
    output_tokens = _required_non_negative_int(
        raw_metrics.get("outputTokens"),
        label="metrics.outputTokens",
    )
    system_prompt_tokens = _required_non_negative_int(
        raw_metrics.get("systemPromptTokens"),
        label="metrics.systemPromptTokens",
    )
    expected_prompt_tokens = _prompt_tokens(fixture, variant_label)
    if system_prompt_tokens != expected_prompt_tokens:
        raise AblationReportError(
            "metrics.systemPromptTokens does not match fixture variant"
        )
    ping_pong_turns = _required_non_negative_int(
        raw_metrics.get("roomPingPongTurns"),
        label="metrics.roomPingPongTurns",
    )
    execution_layer = str(scenario["executionLayer"])
    provider_receipt = _validate_provider_receipt(
        observation.get("providerReceipt"),
        expected=expected_provider,
        execution_layer=execution_layer,
        output_tokens=output_tokens,
    )
    prompt_receipt = _validate_prompt_receipt(
        observation.get("promptReceipt"),
        fixture=fixture,
        variant_label=variant_label,
        expected_provider=expected_provider,
        provider_receipt=provider_receipt,
    )
    if not expected_provider and raw_trace:
        raise AblationReportError(
            "kernel-pre-dispatch scenario must have an empty toolTrace"
        )
    with tempfile.TemporaryDirectory(
        prefix="prompt-ablation-observation-"
    ) as raw_root:
        expected_workspace_hash = _materialize_workspace(
            scenario,
            Path(raw_root),
        )
    isolation_receipt = dict(
        _required_mapping(
            observation.get("isolationReceipt"),
            label="isolationReceipt",
        )
    )
    if isolation_receipt.get("stateScope") != (
        "fresh-subprocess-session-context-epoch"
    ):
        raise AblationReportError(
            "isolationReceipt.stateScope must prove a fresh subprocess"
        )
    process_id = _required_non_negative_int(
        isolation_receipt.get("processId"),
        label="isolationReceipt.processId",
    )
    if process_id < 1:
        raise AblationReportError(
            "isolationReceipt.processId must be positive"
        )
    if isolation_receipt.get("workspaceStateSha256") != (
        expected_workspace_hash
    ):
        raise AblationReportError(
            "isolationReceipt workspace hash does not match the fixture"
        )
    if expected_provider:
        _required_non_empty_text(
            isolation_receipt.get("sessionId"),
            label="isolationReceipt.sessionId",
        )
        context_epoch = _required_non_negative_int(
            isolation_receipt.get("contextEpoch"),
            label="isolationReceipt.contextEpoch",
        )
        if context_epoch < 1:
            raise AblationReportError(
                "isolationReceipt.contextEpoch must be positive"
            )
    task_success = (
        all(bool(assertion["passed"]) for assertion in assertions)
        and forbidden_count == 0
        and trace_matches
    )
    metrics = dict(raw_metrics)
    metrics.update(
        {
            "taskSuccess": task_success,
            "toolTraceExactMatch": trace_matches,
            "toolTraceSha256": _sha256_json(raw_trace),
            "systemPromptTokens": system_prompt_tokens,
            "outputTokens": output_tokens,
            "forbiddenBehaviorCount": forbidden_count,
            "roomPingPongTurns": ping_pong_turns,
        }
    )
    record: dict[str, object] = {
        "scenarioId": scenario_id,
        "variant": variant_label,
        "runOrdinal": run_ordinal,
        "model": model,
        "reasoningEffort": reasoning_effort,
        "runIndex": run_index,
        "startedAt": started_at,
        "firstActionLatencyMs": measured_latency,
        # Preserve every caller-supplied tool receipt and Provider event.
        "toolTrace": list(raw_trace) if isinstance(raw_trace, list) else [],
        "output": output,
        "assertions": assertions,
        "metrics": metrics,
        "providerReceipt": provider_receipt,
        "promptReceipt": prompt_receipt,
        "timingReceipt": timing,
        "isolationReceipt": isolation_receipt,
        "executionLayer": execution_layer,
        "providerInvocationExpected": expected_provider,
        "expectedWorkspaceStateSha256": expected_workspace_hash,
        "workerReceipt": {
            "pid": os.getpid(),
            "stateScope": "fresh-subprocess-temporary-workspace",
        },
    }
    _require_report_keys(fixture, record, aggregate=False)
    return record


def _worker(request: Mapping[str, object]) -> dict[str, object]:
    fixture_path = Path(
        _required_non_empty_text(
            request.get("fixturePath"),
            label="fixturePath",
        )
    )
    fixture = load_fixture(fixture_path)
    mode = request.get("mode")
    if mode == "plan":
        scenario_id = _required_non_empty_text(
            request.get("scenarioId"),
            label="scenarioId",
        )
        scenario = _scenario_map(fixture).get(scenario_id)
        if scenario is None:
            raise AblationReportError(
                f"unknown scenario: {scenario_id}"
            )
        return _planned_run(
            fixture,
            scenario,
            variant_label=_required_non_empty_text(
                request.get("variant"),
                label="variant",
            ),
            run_ordinal=_required_non_negative_int(
                request.get("runOrdinal"),
                label="runOrdinal",
            ),
            run_index=_required_non_negative_int(
                request.get("runIndex"),
                label="runIndex",
            ),
            model=_required_non_empty_text(
                request.get("model"),
                label="model",
            ),
            reasoning_effort=_required_non_empty_text(
                request.get("reasoningEffort"),
                label="reasoningEffort",
            ),
        )
    if mode == "observation":
        observation = _required_mapping(
            request.get("observation"),
            label="observation",
        )
        return _observed_run(fixture, observation)
    raise AblationReportError(f"unsupported worker mode: {mode}")


def _run_isolated_worker(
    request: Mapping[str, object],
    *,
    timeout_seconds: float = 20.0,
) -> dict[str, object]:
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--_worker",
    ]
    env = {
        key: value
        for key, value in os.environ.items()
        if key in {
            "LANG",
            "LC_ALL",
            "PATH",
            "PYTHONIOENCODING",
            "SYSTEMROOT",
        }
    }
    env["PYTHONIOENCODING"] = "utf-8"
    with tempfile.TemporaryDirectory(
        prefix="prompt-ablation-process-"
    ) as process_root:
        env["HOME"] = process_root
        env["TMPDIR"] = process_root
        completed = subprocess.run(
            command,
            input=json.dumps(request, ensure_ascii=False),
            capture_output=True,
            text=True,
            env=env,
            cwd=process_root,
            timeout=timeout_seconds,
            check=False,
        )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise AblationReportError(
            f"isolated worker failed ({completed.returncode}): {detail}"
        )
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise AblationReportError(
            "isolated worker returned invalid JSON"
        ) from exc
    if not isinstance(result, dict):
        raise AblationReportError(
            "isolated worker result must be an object"
        )
    return result


def _fixture_identity(
    path: Path,
    fixture: Mapping[str, object],
) -> dict[str, object]:
    return {
        "path": str(path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "schemaVersion": fixture["schemaVersion"],
        "status": fixture["status"],
    }


def _aggregate_template(
    fixture: Mapping[str, object],
    scenario_id: str,
    variant_label: str,
    *,
    planned_run_count: int,
) -> dict[str, object]:
    record: dict[str, object] = {
        "scenarioId": scenario_id,
        "variant": variant_label,
        "runCount": 0,
        "taskSuccessRate": None,
        "forbiddenBehaviorRate": None,
        "toolTraceExactMatchRate": None,
        "meanFirstActionLatencyMs": None,
        "meanOutputTokens": None,
        "meanSystemPromptTokens": _prompt_tokens(fixture, variant_label),
        "roomPingPongTurns": None,
        "plannedRunCount": planned_run_count,
        "status": "planned-not-run",
    }
    _require_report_keys(fixture, record, aggregate=True)
    return record


def build_dry_run_plan(
    fixture_path: Path = DEFAULT_FIXTURE,
    *,
    runs_per_variant: int | None = None,
    scenario_ids: Sequence[str] = (),
    model: str = "__RUNTIME_MODEL_NOT_RUN__",
    reasoning_effort: str = "__RUNTIME_REASONING_NOT_RUN__",
) -> dict[str, object]:
    fixture_path = fixture_path.resolve()
    fixture = load_fixture(fixture_path)
    scenarios = _scenario_map(fixture)
    selected = list(scenario_ids) if scenario_ids else list(scenarios)
    unknown = [scenario_id for scenario_id in selected if scenario_id not in scenarios]
    if unknown:
        raise AblationReportError(
            f"unknown scenarios: {', '.join(unknown)}"
        )
    if runs_per_variant is None:
        protocol = _required_mapping(
            fixture["runProtocol"],
            label="runProtocol",
        )
        provider_runs = int(protocol["pairedRunsPerProviderScenario"])
        kernel_runs = int(protocol["deterministicRunsPerKernelScenario"])
    else:
        provider_runs = kernel_runs = runs_per_variant
    planned_runs: list[dict[str, object]] = []
    aggregate_templates: list[dict[str, object]] = []
    for scenario_id in selected:
        scenario = scenarios[scenario_id]
        per_variant = (
            provider_runs
            if bool(scenario["providerInvocationExpected"])
            else kernel_runs
        )
        provider_expected = bool(scenario["providerInvocationExpected"])
        if provider_expected:
            run_order = _balanced_order(scenario_id, per_variant)
            seen = {"A": 0, "B": 0}
        else:
            run_order = [_KERNEL_VARIANT] * per_variant
            seen = {_KERNEL_VARIANT: 0}
        for variant_label in run_order:
            seen[variant_label] += 1
            run_ordinal = sum(seen.values())
            planned_runs.append(
                _run_isolated_worker(
                    {
                        "mode": "plan",
                        "fixturePath": str(fixture_path),
                        "scenarioId": scenario_id,
                        "variant": variant_label,
                        "runOrdinal": run_ordinal,
                        "runIndex": seen[variant_label],
                        "model": model,
                        "reasoningEffort": reasoning_effort,
                    }
                )
            )
        aggregate_variants = (
            _VARIANTS if provider_expected else (_KERNEL_VARIANT,)
        )
        for variant_label in aggregate_variants:
            aggregate_templates.append(
                _aggregate_template(
                    fixture,
                    scenario_id,
                    variant_label,
                    planned_run_count=per_variant,
                )
            )
    return {
        "schemaVersion": REPORT_SCHEMA_VERSION,
        "status": "designed-not-provider-run",
        "fixture": _fixture_identity(fixture_path, fixture),
        "executionBoundary": dict(EXECUTION_BOUNDARY),
        "observationContract": dict(OBSERVATION_CONTRACT),
        "orderPolicy": fixture["runProtocol"]["orderPolicy"],
        "plannedRuns": planned_runs,
        "aggregateTemplates": aggregate_templates,
        "perRun": [],
        "aggregate": [],
    }


def load_observations(path: Path) -> list[dict[str, object]]:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise AblationReportError("observation file is empty")
    if text.startswith("["):
        raw = json.loads(text)
    else:
        raw = [
            json.loads(line)
            for line in text.splitlines()
            if line.strip()
        ]
    if not isinstance(raw, list) or not all(
        isinstance(item, dict) for item in raw
    ):
        raise AblationReportError(
            "observations must be a JSON array or JSONL objects"
        )
    return list(raw)


def _aggregate_observed(
    fixture: Mapping[str, object],
    records: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    grouped: defaultdict[
        tuple[str, str],
        list[Mapping[str, object]],
    ] = defaultdict(list)
    for record in records:
        grouped[
            (str(record["scenarioId"]), str(record["variant"]))
        ].append(record)
    aggregates: list[dict[str, object]] = []
    for (scenario_id, variant_label), group in sorted(grouped.items()):
        task_successes = [
            bool(_required_mapping(item["metrics"], label="metrics")["taskSuccess"])
            for item in group
        ]
        forbidden = [
            int(
                _required_mapping(item["metrics"], label="metrics")[
                    "forbiddenBehaviorCount"
                ]
            )
            > 0
            for item in group
        ]
        trace_matches = [
            bool(
                _required_mapping(item["metrics"], label="metrics")[
                    "toolTraceExactMatch"
                ]
            )
            for item in group
        ]
        latencies = [float(item["firstActionLatencyMs"]) for item in group]
        output_tokens = [
            int(
                _required_mapping(item["metrics"], label="metrics")[
                    "outputTokens"
                ]
            )
            for item in group
        ]
        prompt_tokens = [
            int(
                _required_mapping(item["metrics"], label="metrics")[
                    "systemPromptTokens"
                ]
            )
            for item in group
        ]
        ping_pong = sum(
            int(
                _required_mapping(item["metrics"], label="metrics")[
                    "roomPingPongTurns"
                ]
            )
            for item in group
        )
        count = len(group)
        aggregate: dict[str, object] = {
            "scenarioId": scenario_id,
            "variant": variant_label,
            "runCount": count,
            "taskSuccessRate": sum(task_successes) / count,
            "forbiddenBehaviorRate": sum(forbidden) / count,
            "toolTraceExactMatchRate": sum(trace_matches) / count,
            "meanFirstActionLatencyMs": fmean(latencies),
            "meanOutputTokens": fmean(output_tokens),
            "meanSystemPromptTokens": fmean(prompt_tokens),
            "roomPingPongTurns": ping_pong,
        }
        _require_report_keys(fixture, aggregate, aggregate=True)
        aggregates.append(aggregate)
    return aggregates


def _require_complete_matrix(
    fixture: Mapping[str, object],
    records: Sequence[Mapping[str, object]],
) -> None:
    protocol = _required_mapping(
        fixture["runProtocol"],
        label="runProtocol",
    )
    counts: defaultdict[tuple[str, str], list[int]] = defaultdict(list)
    scenarios = _scenario_map(fixture)
    for record in records:
        counts[
            (str(record["scenarioId"]), str(record["variant"]))
        ].append(int(record["runIndex"]))
    for scenario_id, scenario in scenarios.items():
        expected_count = int(
            protocol[
                "pairedRunsPerProviderScenario"
                if bool(scenario["providerInvocationExpected"])
                else "deterministicRunsPerKernelScenario"
            ]
        )
        expected_indexes = list(range(1, expected_count + 1))
        variants = (
            _VARIANTS
            if bool(scenario["providerInvocationExpected"])
            else (_KERNEL_VARIANT,)
        )
        for variant_label in variants:
            actual = sorted(counts[(scenario_id, variant_label)])
            if actual != expected_indexes:
                raise AblationReportError(
                    f"{scenario_id}/{variant_label}: expected run indexes "
                    f"{expected_indexes}, got {actual}"
                )


def _require_observation_invariants(
    fixture: Mapping[str, object],
    records: Sequence[Mapping[str, object]],
    *,
    complete: bool,
) -> None:
    """Keep A/B order, fixed Provider settings, and run isolation auditable."""

    grouped: defaultdict[
        str,
        list[Mapping[str, object]],
    ] = defaultdict(list)
    seen_sessions: set[str] = set()
    seen_ordinals: set[tuple[str, int]] = set()
    for record in records:
        scenario_id = str(record["scenarioId"])
        grouped[scenario_id].append(record)
        ordinal_key = (scenario_id, int(record["runOrdinal"]))
        if ordinal_key in seen_ordinals:
            raise AblationReportError(
                f"{scenario_id}: duplicate runOrdinal {ordinal_key[1]}"
            )
        seen_ordinals.add(ordinal_key)
        if bool(record["providerInvocationExpected"]):
            isolation = _required_mapping(
                record["isolationReceipt"],
                label="isolationReceipt",
            )
            session_id = str(isolation["sessionId"])
            if session_id in seen_sessions:
                raise AblationReportError(
                    f"Provider Session was reused across runs: {session_id}"
                )
            seen_sessions.add(session_id)
    scenarios = _scenario_map(fixture)
    for scenario_id, group in grouped.items():
        scenario = scenarios[scenario_id]
        provider_expected = bool(scenario["providerInvocationExpected"])
        if provider_expected:
            models = {str(item["model"]) for item in group}
            efforts = {str(item["reasoningEffort"]) for item in group}
            fixed_layer_hashes = {
                str(
                    _required_mapping(
                        item["promptReceipt"],
                        label="promptReceipt",
                    )["fixedLayersSha256"]
                )
                for item in group
            }
            if len(models) != 1 or len(efforts) != 1:
                raise AblationReportError(
                    f"{scenario_id}: A/B model or reasoning effort changed"
                )
            if len(fixed_layer_hashes) != 1:
                raise AblationReportError(
                    f"{scenario_id}: fixed Prompt layers changed between A and B"
                )
        elif {str(item["variant"]) for item in group} != {
            _KERNEL_VARIANT
        }:
            raise AblationReportError(
                f"{scenario_id}: kernel observations must use variant K"
            )
        if complete:
            ordered = sorted(group, key=lambda item: int(item["runOrdinal"]))
            actual_order = [str(item["variant"]) for item in ordered]
            if provider_expected:
                expected_runs = len(ordered) // 2
                expected_order = _balanced_order(
                    scenario_id,
                    expected_runs,
                )
                if actual_order != expected_order:
                    raise AblationReportError(
                        f"{scenario_id}: run order does not match seeded ABBA"
                    )
            elif actual_order != [_KERNEL_VARIANT] * len(ordered):
                raise AblationReportError(
                    f"{scenario_id}: kernel run order must contain only K"
                )


def build_observed_report(
    observations: Sequence[Mapping[str, object]],
    fixture_path: Path = DEFAULT_FIXTURE,
    *,
    allow_partial: bool = False,
) -> dict[str, object]:
    fixture_path = fixture_path.resolve()
    fixture = load_fixture(fixture_path)
    records = [
        _run_isolated_worker(
            {
                "mode": "observation",
                "fixturePath": str(fixture_path),
                "observation": dict(observation),
            }
        )
        for observation in observations
    ]
    _require_observation_invariants(
        fixture,
        records,
        complete=not allow_partial,
    )
    if not allow_partial:
        _require_complete_matrix(fixture, records)
    return {
        "schemaVersion": REPORT_SCHEMA_VERSION,
        "status": "observed-partial" if allow_partial else "observed-complete",
        "fixture": _fixture_identity(fixture_path, fixture),
        "executionBoundary": dict(EXECUTION_BOUNDARY),
        "observationContract": dict(OBSERVATION_CONTRACT),
        "perRun": records,
        "aggregate": _aggregate_observed(fixture, records),
    }


def _write_report(
    report: Mapping[str, object],
    *,
    output_path: Path | None,
    pretty: bool,
) -> None:
    rendered = json.dumps(
        report,
        ensure_ascii=False,
        indent=2 if pretty else None,
        sort_keys=pretty,
    )
    if output_path is None:
        print(rendered)
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered + "\n", encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Plan isolated managed-work Prompt A/B runs or aggregate "
            "externally captured product observations."
        )
    )
    parser.add_argument(
        "--fixture",
        type=Path,
        default=DEFAULT_FIXTURE,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Materialize an isolated execution plan. This never invokes a "
            "Provider and marks every Provider receipt as not run."
        ),
    )
    parser.add_argument(
        "--observations",
        type=Path,
        help=(
            "JSON array or JSONL of separately captured product observations."
        ),
    )
    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help="Allow an incomplete observation matrix for focused validation.",
    )
    parser.add_argument(
        "--runs-per-variant",
        type=int,
        default=None,
        help="Dry-run override; fixture counts are used by default.",
    )
    parser.add_argument(
        "--scenario",
        action="append",
        default=[],
        help="Dry-run only: select one scenario ID; repeat as needed.",
    )
    parser.add_argument(
        "--model",
        default="__RUNTIME_MODEL_NOT_RUN__",
        help="Dry-run plan label only; no Provider is called.",
    )
    parser.add_argument(
        "--reasoning-effort",
        default="__RUNTIME_REASONING_NOT_RUN__",
        help="Dry-run plan label only; no Provider is called.",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--pretty", action="store_true")
    parser.add_argument(
        "--_worker",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args._worker:
            raw_request = json.loads(sys.stdin.read())
            request = _required_mapping(
                raw_request,
                label="worker request",
            )
            print(json.dumps(_worker(request), ensure_ascii=False))
            return 0
        if args.dry_run == (args.observations is not None):
            raise AblationReportError(
                "choose exactly one of --dry-run or --observations"
            )
        if args.dry_run:
            report = build_dry_run_plan(
                args.fixture,
                runs_per_variant=args.runs_per_variant,
                scenario_ids=args.scenario,
                model=args.model,
                reasoning_effort=args.reasoning_effort,
            )
        else:
            report = build_observed_report(
                load_observations(args.observations),
                args.fixture,
                allow_partial=args.allow_partial,
            )
        _write_report(
            report,
            output_path=args.output,
            pretty=args.pretty,
        )
    except (
        AblationReportError,
        json.JSONDecodeError,
        OSError,
        subprocess.SubprocessError,
    ) as exc:
        print(f"prompt ablation runner: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
