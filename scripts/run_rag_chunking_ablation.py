#!/usr/bin/env python3
"""Select a Knowledge chunk profile on validation, then open held-out once."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "run_rag_retrieval_experiment.py"

DEFAULT_PROFILES: tuple[dict[str, object], ...] = (
    {
        "id": "general-600-80",
        "strategy": "general",
        "size": 600,
        "overlap": 80,
    },
    {
        "id": "general-900-120",
        "strategy": "general",
        "size": 900,
        "overlap": 120,
    },
    {
        "id": "general-1200-160",
        "strategy": "general",
        "size": 1_200,
        "overlap": 160,
    },
    {
        "id": "general-1600-200",
        "strategy": "general",
        "size": 1_600,
        "overlap": 200,
    },
    {
        "id": "markdown-900-120",
        "strategy": "markdown",
        "size": 900,
        "overlap": 120,
    },
    {
        "id": "fixed-900-120",
        "strategy": "fixed",
        "size": 900,
        "overlap": 120,
    },
)


def main(argv: list[str] | None = None) -> int:
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--work-root",
        type=Path,
        default=ROOT / ".rag-ime-data" / "runs" / "chunking-ablation",
    )
    parser.add_argument("--profiles-json", type=Path)
    parser.add_argument("--baseline-profile-id", default="general-1200-160")
    parser.add_argument("--seed", default="paw-chunking-ablation-v1")
    parser.add_argument("--max-cases-per-split", type=int, default=0)
    parser.add_argument("--distractor-limit", type=int, default=0)
    parser.add_argument(
        "--embedding-provider",
        choices=("local-hash", "mlx-bert", "sentence-transformers", "openai-compatible"),
        default="local-hash",
    )
    parser.add_argument("--embedding-model", default="")
    parser.add_argument("--embedding-dimensions", type=int, default=96)
    parser.add_argument("--embedding-query-prefix", default="")
    parser.add_argument("--embedding-document-prefix", default="")
    parser.add_argument("--embedding-bits", type=int, default=8)
    parser.add_argument("--embedding-group-size", type=int, default=32)
    parser.add_argument(
        "--dense-backend",
        choices=("sqlite-exact", "usearch"),
        default="usearch",
    )
    args = parser.parse_args(argv)

    prepared = args.prepared.expanduser().resolve(strict=True)
    output = args.output.expanduser().resolve(strict=False)
    work_root = args.work_root.expanduser().resolve(strict=False)
    work_root.mkdir(parents=True, exist_ok=True)
    profiles = _load_profiles(args.profiles_json)
    profile_ids = {str(profile["id"]) for profile in profiles}
    if args.baseline_profile_id not in profile_ids:
        raise SystemExit("--baseline-profile-id must name one of the chunk profiles")

    started_at_ms = int(time.time() * 1_000)
    candidate_rows: list[dict[str, Any]] = []
    for profile in profiles:
        profile_id = str(profile["id"])
        report_path = work_root / f"validation-{profile_id}.json"
        log_path = work_root / f"validation-{profile_id}.log"
        command = _runner_command(
            args,
            prepared=prepared,
            output=report_path,
            sandbox_root=work_root / f"sandbox-{profile_id}",
            profile=profile,
            evaluation_scope="validation-only",
        )
        _progress("candidate_started", profile=profile)
        _run(command, log_path=log_path)
        report = _read_report(report_path)
        row = _candidate_row(profile, report, report_path=report_path, log_path=log_path)
        if report.get("heldOut") is not None or report.get("comparison") is not None:
            raise RuntimeError(f"validation candidate {profile_id} exposed held-out metrics")
        if not bool(
            (report.get("hardGates") or {}).get(
                "heldOutMetricsSuppressedDuringChunkSelection"
            )
        ):
            raise RuntimeError(f"validation candidate {profile_id} failed leakage gate")
        candidate_rows.append(row)
        _progress(
            "candidate_completed",
            profileId=profile_id,
            metrics=row["validationMetrics"],
            reportSha256=row["reportSha256"],
        )

    winner = _select_winner(candidate_rows)
    baseline = next(
        row for row in candidate_rows if row["profile"]["id"] == args.baseline_profile_id
    )
    acceptance_path = output.with_name(f"{output.stem}-heldout-winner.json")
    acceptance_log = work_root / "heldout-winner.log"
    acceptance_command = _runner_command(
        args,
        prepared=prepared,
        output=acceptance_path,
        sandbox_root=work_root / "sandbox-heldout-winner",
        profile=dict(winner["profile"]),
        evaluation_scope="full",
    )
    _progress("heldout_started", winner=winner["profile"])
    _run(acceptance_command, log_path=acceptance_log)
    acceptance = _read_report(acceptance_path)
    acceptance_chunking = acceptance.get("chunking")
    if not isinstance(acceptance_chunking, Mapping):
        raise RuntimeError("held-out winner report is missing chunking")
    winner_matches = _profile_matches_chunking(
        dict(winner["profile"]),
        acceptance_chunking,
    )
    selection_config_matches = (
        str((acceptance.get("validationSelection") or {}).get("frozenConfigSha256") or "")
        == str(winner["retrievalConfigSha256"])
    )
    split_hash_matches = all(
        row["validationSplitSha256"] == winner["validationSplitSha256"]
        for row in candidate_rows
    )
    corpus_hash_matches = all(
        row["datasetSha256"] == winner["datasetSha256"]
        for row in candidate_rows
    )
    completed_at_ms = int(time.time() * 1_000)
    summary = {
        "schemaVersion": "rag-ime.rag-chunking-ablation.v1",
        "status": "completed",
        "localOnly": True,
        "uploaded": False,
        "startedAtMs": started_at_ms,
        "completedAtMs": completed_at_ms,
        "elapsedMs": completed_at_ms - started_at_ms,
        "selectionSplit": "validation",
        "acceptanceSplit": "held_out",
        "selectionObjective": "ndcgAtK.10",
        "selectionBudget": {
            "maxCasesPerSplit": int(args.max_cases_per_split),
            "distractorLimit": int(args.distractor_limit),
            "seed": str(args.seed),
        },
        "baselineProfileId": str(args.baseline_profile_id),
        "candidates": candidate_rows,
        "winner": winner,
        "validationComparisonToDefault": _metric_deltas(
            dict(baseline["validationMetrics"]),
            dict(winner["validationMetrics"]),
        ),
        "heldOutAcceptance": {
            "report": str(acceptance_path),
            "reportSha256": str(acceptance.get("reportSha256") or ""),
            "log": str(acceptance_log),
            "winnerProfileMatches": winner_matches,
            "retrievalConfigMatchesSelection": selection_config_matches,
            "metrics": _held_out_metrics(acceptance),
            "comparison": acceptance.get("comparison"),
        },
        "hardGates": {
            "allCandidatesValidationOnly": all(
                row["evaluationScope"] == "validation-only"
                for row in candidate_rows
            ),
            "heldOutSuppressedForEveryCandidate": all(
                row["heldOutSuppressed"] for row in candidate_rows
            ),
            "sameValidationSplit": split_hash_matches,
            "sameDatasetAndCorpus": corpus_hash_matches,
            "heldOutRunUsesFrozenWinnerProfile": winner_matches,
            "heldOutRunReproducesFrozenRetrievalConfig": selection_config_matches,
        },
        "scopeWarnings": [
            "Chunk profile and retrieval config are selected together on validation only.",
            "Only the frozen winner opens held-out metrics.",
            "This local product run is not an official leaderboard submission.",
        ],
    }
    summary["passed"] = all(bool(value) for value in summary["hardGates"].values())
    summary["reportSha256"] = _sha256_json(summary)
    _write_json(output, summary)
    _progress(
        "completed",
        output=str(output),
        passed=summary["passed"],
        winner=winner["profile"],
        validationComparison=summary["validationComparisonToDefault"],
        heldOutMetrics=summary["heldOutAcceptance"]["metrics"],
        reportSha256=summary["reportSha256"],
    )
    return 0 if summary["passed"] else 2


def _load_profiles(path: Path | None) -> list[dict[str, object]]:
    raw: object = list(DEFAULT_PROFILES)
    if path is not None:
        try:
            raw = json.loads(path.expanduser().resolve(strict=True).read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SystemExit("--profiles-json must be readable UTF-8 JSON") from exc
    if not isinstance(raw, list) or len(raw) < 2:
        raise SystemExit("chunking ablation requires at least two profiles")
    result: list[dict[str, object]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, Mapping):
            raise SystemExit("each chunk profile must be an object")
        profile_id = str(item.get("id") or "").strip()
        strategy = str(item.get("strategy") or "").strip()
        if not profile_id or profile_id in seen:
            raise SystemExit("chunk profile IDs must be unique and non-empty")
        if strategy not in {"general", "markdown", "book", "qa", "laws", "separator", "fixed"}:
            raise SystemExit(f"unsupported chunk strategy for {profile_id}")
        size = int(item.get("size") or 0)
        overlap = int(item.get("overlap") or 0)
        if not 200 <= size <= 8_000 or not 0 <= overlap < size or overlap > 2_000:
            raise SystemExit(f"invalid size/overlap for {profile_id}")
        separator = str(item.get("separator") or "")
        if strategy == "separator" and not separator:
            raise SystemExit(f"separator profile {profile_id} requires separator")
        seen.add(profile_id)
        result.append(
            {
                "id": profile_id,
                "strategy": strategy,
                "size": size,
                "overlap": overlap,
                "separator": separator,
                "respectHeadings": bool(item.get("respectHeadings", True)),
                "respectPageBoundaries": bool(item.get("respectPageBoundaries", True)),
            }
        )
    return result


def _runner_command(
    args: argparse.Namespace,
    *,
    prepared: Path,
    output: Path,
    sandbox_root: Path,
    profile: Mapping[str, object],
    evaluation_scope: str,
) -> list[str]:
    command = [
        sys.executable,
        str(RUNNER),
        "--prepared",
        str(prepared),
        "--sandbox-root",
        str(sandbox_root),
        "--output",
        str(output),
        "--evaluation-scope",
        evaluation_scope,
        "--seed",
        str(args.seed),
        "--max-cases-per-split",
        str(args.max_cases_per_split),
        "--distractor-limit",
        str(args.distractor_limit),
        "--chunk-strategy",
        str(profile["strategy"]),
        "--chunk-size",
        str(profile["size"]),
        "--chunk-overlap",
        str(profile["overlap"]),
        "--chunk-separator",
        str(profile.get("separator") or ""),
        "--embedding-provider",
        str(args.embedding_provider),
        "--embedding-dimensions",
        str(args.embedding_dimensions),
        "--embedding-bits",
        str(args.embedding_bits),
        "--embedding-group-size",
        str(args.embedding_group_size),
        "--dense-backend",
        str(args.dense_backend),
    ]
    command.append(
        "--respect-headings"
        if bool(profile.get("respectHeadings", True))
        else "--no-respect-headings"
    )
    command.append(
        "--respect-page-boundaries"
        if bool(profile.get("respectPageBoundaries", True))
        else "--no-respect-page-boundaries"
    )
    optional = (
        ("--embedding-model", args.embedding_model),
        ("--embedding-query-prefix", args.embedding_query_prefix),
        ("--embedding-document-prefix", args.embedding_document_prefix),
    )
    for flag, value in optional:
        if value:
            command.extend((flag, str(value)))
    return command


def _run(command: list[str], *, log_path: Path) -> None:
    completed = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(
        completed.stdout + ("\n[stderr]\n" + completed.stderr if completed.stderr else ""),
        encoding="utf-8",
    )
    log_path.chmod(0o600)
    if completed.returncode != 0:
        raise RuntimeError(
            f"retrieval runner failed with exit {completed.returncode}; see {log_path}"
        )


def _read_report(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid retrieval report: {path}") from exc
    if not isinstance(value, dict) or value.get("status") != "completed":
        raise RuntimeError(f"incomplete retrieval report: {path}")
    return value


def _candidate_row(
    profile: Mapping[str, object],
    report: Mapping[str, object],
    *,
    report_path: Path,
    log_path: Path,
) -> dict[str, Any]:
    selection = report.get("validationSelection")
    if not isinstance(selection, Mapping):
        raise RuntimeError("validation report is missing selection")
    winner = selection.get("winner")
    validation = winner.get("validation") if isinstance(winner, Mapping) else None
    metrics = validation.get("metrics") if isinstance(validation, Mapping) else None
    if not isinstance(metrics, Mapping):
        raise RuntimeError("validation report is missing winner metrics")
    dataset = report.get("dataset")
    split_hashes = dataset.get("splitHashes") if isinstance(dataset, Mapping) else None
    return {
        "profile": dict(profile),
        "profileSha256": _sha256_json(profile),
        "evaluationScope": str(report.get("evaluationScope") or ""),
        "heldOutSuppressed": report.get("heldOut") is None and report.get("comparison") is None,
        "validationMetrics": {
            "ndcgAt10": float((metrics.get("ndcgAtK") or {}).get("10") or 0.0),
            "mrr": float(metrics.get("mrr") or 0.0),
            "recallAt10": float((metrics.get("recallAtK") or {}).get("10") or 0.0),
            "recallAt1": float((metrics.get("recallAtK") or {}).get("1") or 0.0),
        },
        "retrievalConfig": dict(winner.get("config") or {}),
        "retrievalConfigSha256": str(selection.get("frozenConfigSha256") or ""),
        "validationSplitSha256": str(
            (split_hashes or {}).get("validation") if isinstance(split_hashes, Mapping) else ""
        ),
        "datasetSha256": _sha256_json(dataset),
        "elapsedMs": int(report.get("elapsedMs") or 0),
        "chunkCount": int(
            ((report.get("embedding") or {}).get("acceptance") or {}).get("chunkCount")
            or 0
        ),
        "report": str(report_path),
        "log": str(log_path),
        "reportSha256": str(report.get("reportSha256") or ""),
    }


def _select_winner(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        raise ValueError("chunk candidate rows must not be empty")
    return max(
        rows,
        key=lambda row: (
            float(row["validationMetrics"]["ndcgAt10"]),
            float(row["validationMetrics"]["mrr"]),
            float(row["validationMetrics"]["recallAt10"]),
            float(row["validationMetrics"]["recallAt1"]),
            -int(row["chunkCount"]),
            -int(row["elapsedMs"]),
            str(row["profile"]["id"]),
        ),
    )


def _profile_matches_chunking(
    profile: Mapping[str, object],
    chunking: Mapping[str, object],
) -> bool:
    return all(
        (
            str(chunking.get(field) or "") == str(profile.get(field) or "")
            if field in {"strategy", "separator"}
            else chunking.get(field) == profile.get(field)
        )
        for field in (
            "strategy",
            "size",
            "overlap",
            "separator",
            "respectHeadings",
            "respectPageBoundaries",
        )
    )


def _held_out_metrics(report: Mapping[str, object]) -> dict[str, float]:
    held_out = report.get("heldOut")
    tuned = held_out.get("tuned") if isinstance(held_out, Mapping) else None
    outer = tuned.get("metrics") if isinstance(tuned, Mapping) else None
    metrics = outer.get("metrics") if isinstance(outer, Mapping) else None
    if not isinstance(metrics, Mapping):
        raise RuntimeError("held-out winner report is missing tuned metrics")
    return {
        "ndcgAt10": float((metrics.get("ndcgAtK") or {}).get("10") or 0.0),
        "mrr": float(metrics.get("mrr") or 0.0),
        "recallAt10": float((metrics.get("recallAtK") or {}).get("10") or 0.0),
        "recallAt1": float((metrics.get("recallAtK") or {}).get("1") or 0.0),
    }


def _metric_deltas(
    baseline: Mapping[str, object],
    optimized: Mapping[str, object],
) -> dict[str, dict[str, float | None]]:
    return {
        key: {
            "baseline": float(baseline[key]),
            "optimized": float(optimized[key]),
            "absoluteDelta": float(optimized[key]) - float(baseline[key]),
            "relativeDelta": (
                (float(optimized[key]) - float(baseline[key])) / float(baseline[key])
                if float(baseline[key]) != 0.0
                else None
            ),
        }
        for key in baseline
    }


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.chmod(0o600)
    temporary.replace(path)


def _sha256_json(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _progress(event: str, **payload: object) -> None:
    print(
        json.dumps({"event": event, **payload}, ensure_ascii=False, sort_keys=True),
        flush=True,
    )


if __name__ == "__main__":
    raise SystemExit(main())
