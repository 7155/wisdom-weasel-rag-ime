#!/usr/bin/env python3
"""Evaluate Luna Activity organization on one frozen approved Timeline.

The source database is opened with mode=ro&immutable=1. Private source/model
artifacts are written mode 0600 outside Git. The optional Markdown report is
raw-text-free and suitable for later interview review.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Mapping


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag_ime.activity_timeline_curation import (
    ACTIVITY_ORGANIZATION_CONTRACT_REPAIR_PROMPT_VERSION,
    ACTIVITY_ORGANIZATION_INPUT_VERSION,
    ACTIVITY_ORGANIZATION_OUTPUT_VERSION,
    ACTIVITY_ORGANIZATION_PROMPT_VERSION,
    ACTIVITY_ORGANIZATION_REPAIR_PROMPT_VERSION,
    ACTIVITY_ORGANIZATION_VERDICT_VERSION,
    ACTIVITY_ORGANIZATION_VERIFIER_PROMPT_VERSION,
    activity_organization_output_schema,
    activity_organization_verdict_schema,
    build_activity_organization_packet,
    build_activity_organization_prompt,
    build_activity_organization_repair_prompt,
    build_activity_organization_verifier_prompt,
    validate_activity_organization_output,
    validate_activity_organization_verdict,
)
from rag_ime.activity_timeline_evaluation import (
    REQUIRED_EVALUATION_MODEL,
    REQUIRED_EVALUATION_THINKING,
    baseline_activity_summary,
    evaluation_timezone,
    load_frozen_activity_timeline,
    load_luna_structured_run,
    redacted_organization_summary,
    run_luna_structured,
    validate_activity_candidate_with_one_contract_repair,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Replay one approved Activity Timeline through real Luna/max and an "
            "independent Luna/max semantic reviewer without modifying SQLite."
        )
    )
    parser.add_argument("--db-path", type=Path, required=True)
    parser.add_argument("--timeline-id", required=True)
    parser.add_argument(
        "--private-dir",
        type=Path,
        required=True,
        help="New directory outside Git for private packet, prompts, and model output",
    )
    parser.add_argument(
        "--public-report",
        type=Path,
        help="Optional raw-text-free Markdown report; must not already exist",
    )
    parser.add_argument("--codex-bin", default="codex")
    source_group = parser.add_mutually_exclusive_group()
    source_group.add_argument(
        "--repair-from",
        type=Path,
        help=(
            "Existing private evaluation directory whose validated candidate and "
            "independent review should receive one bounded repair pass"
        ),
    )
    source_group.add_argument(
        "--resume-candidate-from",
        type=Path,
        help=(
            "Completed private candidate directory to verify without rerunning its "
            "organizer or semantic repair"
        ),
    )
    parser.add_argument(
        "--timezone-fallback",
        default="Asia/Shanghai",
        help="IANA timezone used only when the stored Timeline has a legacy abbreviation",
    )
    parser.add_argument("--timeout-seconds", type=float, default=1_200.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    os.umask(0o077)
    parser = build_parser()
    args = parser.parse_args(argv)
    private_root = args.private_dir.expanduser().resolve()
    if private_root.exists():
        parser.error("--private-dir must not already exist")
    private_root.mkdir(parents=True, mode=0o700)
    private_root.chmod(0o700)

    db_path = args.db_path.expanduser().resolve(strict=True)
    db_stat_before = _file_stat(db_path)
    try:
        snapshot = load_frozen_activity_timeline(
            db_path,
            timeline_id=str(args.timeline_id),
        )
        packet_timezone = evaluation_timezone(
            snapshot.timezone,
            fallback=str(args.timezone_fallback),
        )
        packet = build_activity_organization_packet(
            snapshot.event_rows,
            timeline_id=snapshot.timeline_id,
            project=snapshot.project,
            timeline_date=snapshot.timeline_date,
            timezone_name=packet_timezone,
        )
        baseline = baseline_activity_summary(snapshot)
        parent_evaluation: dict[str, object] = {}
        resumed_candidate: dict[str, object] = {}
        if args.resume_candidate_from is not None:
            resume_source = args.resume_candidate_from.expanduser().resolve(strict=True)
            resume_membership = _private_evaluation_membership(resume_source)
            if resume_membership != packet.membership_sha256:
                raise ValueError("resumed candidate does not match frozen event membership")
            candidate_phase, candidate_dir, initial_candidate_prompt_version = (
                _private_candidate_location(resume_source)
            )
            candidate_run = load_luna_structured_run(
                candidate_dir,
                phase=candidate_phase,
            )
            candidate_output = candidate_run.output
            resumed_candidate = {
                "membershipSha256": resume_membership,
                "phase": candidate_phase,
                "promptVersion": initial_candidate_prompt_version,
                "outputSha256": candidate_run.output_sha256,
                "receiptValidated": True,
            }
            repair_parent_path = resume_source / "repair-parent.json"
            if repair_parent_path.is_file():
                parent_evaluation = _read_private_json(repair_parent_path)
        elif args.repair_from is None:
            candidate_run = run_luna_structured(
                prompt=build_activity_organization_prompt(packet),
                schema=activity_organization_output_schema(),
                artifact_dir=private_root / "organizer",
                phase="organizer",
                timeout_seconds=float(args.timeout_seconds),
                codex_bin=str(args.codex_bin),
            )
            candidate_output = candidate_run.output
            initial_candidate_prompt_version = ACTIVITY_ORGANIZATION_PROMPT_VERSION
        else:
            repair_source = args.repair_from.expanduser().resolve(strict=True)
            source_summary = _read_private_json(repair_source / "evaluation-summary.json")
            source_timeline = source_summary.get("timeline")
            if not isinstance(source_timeline, Mapping) or str(
                source_timeline.get("membershipSha256") or ""
            ) != packet.membership_sha256:
                raise ValueError("repair source does not match the frozen event membership")
            source_candidate_path = repair_source / "organizer" / "organizer-output.json"
            if not source_candidate_path.exists():
                source_candidate_path = repair_source / "repair" / "repair-output.json"
            source_verdict_path = repair_source / "verifier" / "verifier-output.json"
            source_candidate = _read_private_json(source_candidate_path)
            source_verdict = _read_private_json(source_verdict_path)
            validate_activity_organization_output(source_candidate, packet=packet)
            prior_verdict = validate_activity_organization_verdict(
                source_verdict,
                packet=packet,
            )
            if prior_verdict.verdict == "pass":
                raise ValueError("repair source already has a passing independent verdict")
            candidate_run = run_luna_structured(
                prompt=build_activity_organization_repair_prompt(
                    packet,
                    organizer_output=source_candidate,
                    verdict_output=source_verdict,
                ),
                schema=activity_organization_output_schema(),
                artifact_dir=private_root / "repair",
                phase="repair",
                timeout_seconds=float(args.timeout_seconds),
                codex_bin=str(args.codex_bin),
            )
            candidate_output = candidate_run.output
            initial_candidate_prompt_version = ACTIVITY_ORGANIZATION_REPAIR_PROMPT_VERSION
            parent_evaluation = {
                "membershipSha256": packet.membership_sha256,
                "candidateOutputSha256": _file_sha256(source_candidate_path),
                "verifierOutputSha256": _file_sha256(source_verdict_path),
                "verdict": prior_verdict.verdict,
                "scores": dict(prior_verdict.scores),
            }
            _write_private_json(private_root / "repair-parent.json", parent_evaluation)

        validated_candidate = validate_activity_candidate_with_one_contract_repair(
            packet=packet,
            initial_run=candidate_run,
            artifact_dir=private_root,
            timeout_seconds=float(args.timeout_seconds),
            codex_bin=str(args.codex_bin),
        )
        candidate_run = validated_candidate.run
        candidate_output = candidate_run.output
        organization = validated_candidate.result
        contract_repairs = list(validated_candidate.contract_repairs)
        candidate_prompt_version = (
            ACTIVITY_ORGANIZATION_CONTRACT_REPAIR_PROMPT_VERSION
            if contract_repairs
            else initial_candidate_prompt_version
        )
        normalized_organization = organization.payload()
        _write_private_json(
            private_root / "normalized-organization.json",
            normalized_organization,
        )
        _write_private_json(
            private_root / "candidate-checkpoint.json",
            {
                "membershipSha256": packet.membership_sha256,
                "candidatePromptVersion": candidate_prompt_version,
                "candidateRun": candidate_run.redacted_receipt(),
                "contractRepairs": contract_repairs,
            },
        )

        verifier_run = run_luna_structured(
            prompt=build_activity_organization_verifier_prompt(
                packet,
                organizer_output=candidate_output,
            ),
            schema=activity_organization_verdict_schema(),
            artifact_dir=private_root / "verifier",
            phase="verifier",
            timeout_seconds=float(args.timeout_seconds),
            codex_bin=str(args.codex_bin),
        )
        verdict = validate_activity_organization_verdict(
            verifier_run.output,
            packet=packet,
        )
        normalized_verdict = verdict.payload()
        _write_private_json(private_root / "normalized-verdict.json", normalized_verdict)
    except (OSError, RuntimeError, ValueError) as exc:
        parser.error(str(exc))

    db_stat_after = _file_stat(db_path)
    codex_version = _codex_version(str(args.codex_bin))
    packet_json = packet.json_text()
    public_summary = {
        "schemaVersion": "rag-ime.activity-luna-evaluation.v1",
        "generatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "timeline": {
            "timelineId": snapshot.timeline_id,
            "project": snapshot.project,
            "date": snapshot.timeline_date,
            "timezone": snapshot.timezone,
            "evaluationTimezone": packet_timezone,
            "status": snapshot.status,
            "sourceEventHash": snapshot.source_event_hash,
            "membershipSha256": packet.membership_sha256,
            "eventCount": len(packet.records),
        },
        "input": {
            "protocolVersion": ACTIVITY_ORGANIZATION_INPUT_VERSION,
            "promptVersion": ACTIVITY_ORGANIZATION_PROMPT_VERSION,
            "packetChars": len(packet_json),
            "packetUtf8Bytes": len(packet_json.encode("utf-8")),
            "currentTextChars": sum(len(record.current_text) for record in packet.records),
            "referenceContextChars": sum(
                len(record.reference_context) for record in packet.records
            ),
            "contextStatusCounts": dict(
                sorted(Counter(record.context_status for record in packet.records).items())
            ),
            "appCounts": dict(sorted(Counter(record.app for record in packet.records).items())),
            "sourceCounts": dict(
                sorted(Counter(record.source for record in packet.records).items())
            ),
        },
        "baseline": baseline,
        "luna": redacted_organization_summary(
            normalized_organization,
            run=candidate_run,
        ),
        "verifier": _redacted_verdict_summary(
            normalized_verdict,
            run_receipt=verifier_run.redacted_receipt(),
        ),
        "runtime": {
            "codexVersion": codex_version,
            "model": REQUIRED_EVALUATION_MODEL,
            "thinking": REQUIRED_EVALUATION_THINKING,
            "organizerOutputVersion": ACTIVITY_ORGANIZATION_OUTPUT_VERSION,
            "candidatePhase": candidate_run.phase,
            "initialCandidatePromptVersion": initial_candidate_prompt_version,
            "candidatePromptVersion": candidate_prompt_version,
            "contractRepairs": contract_repairs,
            "verifierOutputVersion": ACTIVITY_ORGANIZATION_VERDICT_VERSION,
            "verifierPromptVersion": ACTIVITY_ORGANIZATION_VERIFIER_PROMPT_VERSION,
            "parentEvaluation": parent_evaluation,
            "resumedCandidate": resumed_candidate,
        },
        "safety": {
            "sqliteMode": "mode=ro&immutable=1",
            "databaseStatBefore": db_stat_before,
            "databaseStatAfter": db_stat_after,
            "databaseStatUnchanged": db_stat_before == db_stat_after,
            "productionWritesByEvaluator": 0,
            "privateDirectoryMode": oct(stat.S_IMODE(private_root.stat().st_mode)),
            "privateArtifactsOutsideGit": not _is_relative_to(private_root, ROOT),
            "publicReportContainsRawSourceOrModelText": False,
        },
    }
    _write_private_json(private_root / "evaluation-summary.json", public_summary)

    if args.public_report is not None:
        report_path = args.public_report.expanduser().resolve()
        if report_path.exists():
            parser.error("--public-report must not already exist")
        report_path.parent.mkdir(parents=True, exist_ok=True)
        _write_private_text(report_path, _render_markdown(public_summary))

    console = {
        "ok": True,
        "timelineId": snapshot.timeline_id,
        "eventCount": len(packet.records),
        "membershipSha256": packet.membership_sha256,
        "baselineSegmentCount": baseline["segmentCount"],
        "lunaActivityCount": public_summary["luna"]["activityCount"],
        "unclassifiedCount": public_summary["luna"]["unclassifiedCount"],
        "verdict": public_summary["verifier"]["verdict"],
        "candidatePhase": candidate_run.phase,
        "scores": public_summary["verifier"]["scores"],
        "privateDir": str(private_root),
        "publicReport": str(args.public_report or ""),
        "databaseStatUnchanged": db_stat_before == db_stat_after,
    }
    print(json.dumps(console, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if str(public_summary["verifier"]["verdict"]) == "pass" else 4


def _redacted_verdict_summary(
    verdict: Mapping[str, object],
    *,
    run_receipt: Mapping[str, object],
) -> dict[str, object]:
    raw_issues = verdict.get("issues")
    issues = raw_issues if isinstance(raw_issues, list) else []
    issue_summaries: list[dict[str, object]] = []
    for item in issues:
        if not isinstance(item, Mapping):
            continue
        refs = item.get("eventRefs")
        event_refs = [str(value) for value in refs] if isinstance(refs, list) else []
        issue_summaries.append(
            {
                "severity": str(item.get("severity") or ""),
                "category": str(item.get("category") or ""),
                "eventRefCount": len(event_refs),
                "eventRefsSha256": _sha256(json.dumps(event_refs, separators=(",", ":"))),
                "findingSha256": _sha256(str(item.get("finding") or "")),
                "recommendationSha256": _sha256(str(item.get("recommendation") or "")),
            }
        )
    strengths = verdict.get("strengths")
    strength_values = strengths if isinstance(strengths, list) else []
    scores = verdict.get("scores")
    return {
        "verdict": str(verdict.get("verdict") or ""),
        "scores": dict(scores) if isinstance(scores, Mapping) else {},
        "issueCount": len(issue_summaries),
        "issues": issue_summaries,
        "strengthCount": len(strength_values),
        "strengthsSha256": [_sha256(str(value)) for value in strength_values],
        "run": dict(run_receipt),
    }


def _render_markdown(report: Mapping[str, object]) -> str:
    timeline = report["timeline"]
    input_summary = report["input"]
    baseline = report["baseline"]
    luna = report["luna"]
    verifier = report["verifier"]
    runtime = report["runtime"]
    safety = report["safety"]
    scores = verifier["scores"]
    score_lines = "\n".join(
        f"| {field} | {value}/5 |" for field, value in scores.items()
    )
    issue_lines = "\n".join(
        "| {severity} | {category} | {count} | `{digest}` |".format(
            severity=item["severity"],
            category=item["category"],
            count=item["eventRefCount"],
            digest=str(item["findingSha256"])[:12],
        )
        for item in verifier["issues"]
    ) or "| none | none | 0 | - |"
    parent_line = ""
    if runtime.get("parentEvaluation"):
        parent = runtime["parentEvaluation"]
        parent_line = (
            f"- Parent candidate: verdict `{parent['verdict']}`, output SHA-256 "
            f"`{parent['candidateOutputSha256']}`.\n"
        )
    contract_repair_lines = ""
    contract_repairs = runtime.get("contractRepairs")
    if isinstance(contract_repairs, list) and contract_repairs:
        repair = contract_repairs[-1]
        rejected = repair["rejectedRun"]
        repaired = repair["repairedRun"]
        contract_repair_lines = (
            f"- Contract repair: one bounded `{repair['promptVersion']}` pass; "
            f"rejected output SHA-256 `{rejected['outputSha256']}`, validation "
            f"error SHA-256 `{repair['contractErrorSha256']}`, repaired output "
            f"SHA-256 `{repaired['outputSha256']}`.\n"
        )
    resumed_candidate_line = ""
    resumed_candidate = runtime.get("resumedCandidate")
    if isinstance(resumed_candidate, Mapping) and resumed_candidate:
        resumed_candidate_line = (
            f"- Resumed candidate: phase `{resumed_candidate['phase']}`, receipt/hash "
            f"validated, output SHA-256 `{resumed_candidate['outputSha256']}`; organizer "
            "was not rerun.\n"
        )
    return f"""# Luna Activity Organization Evaluation — 2026-08-02

Status: **{verifier['verdict']}** from an isolated second Luna/max review. This is
evaluation evidence, not production integration or installed foreground acceptance.

## Frozen sample

| Field | Value |
| --- | --- |
| Timeline | `{timeline['timelineId']}` |
| Project/date | `{timeline['project']}` / `{timeline['date']}` |
| Events | {timeline['eventCount']} |
| Membership SHA-256 | `{timeline['membershipSha256']}` |
| Existing source hash | `{timeline['sourceEventHash']}` |
| Packet | {input_summary['packetChars']} chars / {input_summary['packetUtf8Bytes']} UTF-8 bytes |
| Current text / reference context | {input_summary['currentTextChars']} / {input_summary['referenceContextChars']} chars |
| Context states | `{json.dumps(input_summary['contextStatusCounts'], ensure_ascii=False, sort_keys=True)}` |

The same frozen event membership was used for the existing deterministic baseline and
the Luna organizer. Source SQLite was opened with `mode=ro&immutable=1`.

## Baseline versus Luna

| Measure | Existing `semantic_task_v5` | Luna `{runtime['model']}` |
| --- | ---: | ---: |
| Activity count | {baseline['segmentCount']} | {luna['activityCount']} |
| Events per Activity | `{baseline['eventCounts']}` | `{luna['activityEventCounts']}` |
| Unclassified | 0 (forced membership) | {luna['unclassifiedCount']} |
| Exact ref coverage | {str(baseline['exactEventCoverage']).lower()} | true (strict local validator) |
| Mean model confidence | n/a | {luna['confidenceMean']} |

Titles, summaries, boundary explanations, source text, and unclassified reasons are
deliberately absent from this report. They remain in mode-0600 private artifacts; this
report records only counts, contract results, and hashes.

## Independent semantic review

| Dimension | Score |
| --- | ---: |
{score_lines}

| Severity | Category | Affected refs | Finding hash |
| --- | --- | ---: | --- |
{issue_lines}

Verifier protocol: `{runtime['verifierPromptVersion']}`. The verifier ran in a separate
ephemeral Codex invocation and received no organizer transcript. This reduces shared
context bias but is still model-based review, not a human-labeled gold set.

## Reproduction receipts

- Codex: `{runtime['codexVersion']}`.
- Candidate phase: `{runtime['candidatePhase']}`, `{runtime['model']}`, thinking
  `{runtime['thinking']}`, prompt `{runtime['candidatePromptVersion']}`, output
  `{runtime['organizerOutputVersion']}`.
- Initial semantic candidate prompt: `{runtime['initialCandidatePromptVersion']}`.
- Verifier: `{runtime['model']}`, thinking `{runtime['thinking']}`, prompt
  `{runtime['verifierPromptVersion']}`, output `{runtime['verifierOutputVersion']}`.
{parent_line}{resumed_candidate_line}{contract_repair_lines}- Candidate prompt SHA-256: `{luna['run']['promptSha256']}`.
- Candidate output SHA-256: `{luna['run']['outputSha256']}`.
- Verifier prompt SHA-256: `{verifier['run']['promptSha256']}`.
- Verifier output SHA-256: `{verifier['run']['outputSha256']}`.
- App counts: `{json.dumps(input_summary['appCounts'], ensure_ascii=False, sort_keys=True)}`.
- Source counts: `{json.dumps(input_summary['sourceCounts'], ensure_ascii=False, sort_keys=True)}`.

Command shape (private prompt is supplied on stdin, never argv):

```bash
codex exec --ephemeral --ignore-user-config --ignore-rules \\
  --model gpt-5.6-luna --config 'model_reasoning_effort="max"' \\
  --sandbox read-only --output-schema <private-schema> \\
  --output-last-message <private-output> -
```

Focused contract regression at this checkpoint:

```bash
.venv/bin/python -m unittest \\
  tests.test_activity_timeline_curation \\
  tests.test_activity_timeline_evaluation
```

## Safety and interpretation

- Production writes by this evaluator: **{safety['productionWritesByEvaluator']}**.
- Database stat unchanged during the run: **{str(safety['databaseStatUnchanged']).lower()}**.
- Private directory mode: `{safety['privateDirectoryMode']}`; individual artifacts are
  mode `0600` and live outside Git.
- The report contains no raw source or model text.
- A verifier pass establishes one replay result, not production scheduling,
  provisional/day-end versioning, UI rollback, or installed behavior.
- Before using this as an interview case, add a human-reviewed, public-safe explanation
  of the most important boundary improvement and one real failure/iteration. Do not turn
  model self-review into a claimed product metric.
"""


def _file_stat(path: Path) -> dict[str, int]:
    value = path.stat()
    return {
        "size": int(value.st_size),
        "mtimeNs": int(value.st_mtime_ns),
        "mode": stat.S_IMODE(value.st_mode),
    }


def _private_evaluation_membership(root: Path) -> str:
    checkpoint_path = root / "candidate-checkpoint.json"
    if checkpoint_path.is_file():
        checkpoint = _read_private_json(checkpoint_path)
        value = str(checkpoint.get("membershipSha256") or "")
        if value:
            return value

    summary_path = root / "evaluation-summary.json"
    if summary_path.is_file():
        summary = _read_private_json(summary_path)
        timeline = summary.get("timeline")
        if isinstance(timeline, Mapping):
            value = str(timeline.get("membershipSha256") or "")
            if value:
                return value

    repair_parent_path = root / "repair-parent.json"
    if repair_parent_path.is_file():
        repair_parent = _read_private_json(repair_parent_path)
        value = str(repair_parent.get("membershipSha256") or "")
        if value:
            return value
    raise ValueError("resumed candidate has no frozen-membership receipt")


def _private_candidate_location(root: Path) -> tuple[str, Path, str]:
    candidates = (
        (
            "contract-repair",
            root / "contract-repair",
            ACTIVITY_ORGANIZATION_CONTRACT_REPAIR_PROMPT_VERSION,
        ),
        ("repair", root / "repair", ACTIVITY_ORGANIZATION_REPAIR_PROMPT_VERSION),
        ("organizer", root / "organizer", ACTIVITY_ORGANIZATION_PROMPT_VERSION),
    )
    for phase, directory, prompt_version in candidates:
        if (
            (directory / f"{phase}-output.json").is_file()
            and (directory / f"{phase}-receipt.json").is_file()
        ):
            return phase, directory, prompt_version
    raise ValueError("resumed candidate has no completed private Luna output and receipt")


def _codex_version(binary: str) -> str:
    completed = subprocess.run(
        [binary, "--version"],
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0:
        return "unknown"
    return str(completed.stdout or "").strip()


def _write_private_json(path: Path, value: Mapping[str, object]) -> None:
    _write_private_text(
        path,
        json.dumps(dict(value), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


def _read_private_json(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise ValueError(f"private evaluation artifact is missing: {path.name}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"private evaluation artifact is invalid JSON: {path.name}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"private evaluation artifact must be an object: {path.name}")
    return dict(value)


def _write_private_text(path: Path, value: str) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(value)
    path.chmod(0o600)


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
