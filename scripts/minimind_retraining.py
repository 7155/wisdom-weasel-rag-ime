#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag_ime.minimind_quality_gate import (
    DEFAULT_DATASET_ROOT,
    PRODUCTION_CANDIDATE_STAGE,
    RAW_MODEL_OUTPUT_STAGE,
    HumanJudgmentFixtureScorer,
    RawCompletionBatch,
    audit_completion_dataset,
    export_minimind_ranking_pairs,
    export_minimind_training_pairs,
    run_minimind_quality_gate,
    run_minimind_raw_output_gate,
    write_quality_report,
)
from rag_ime.minimind_experiment import prepare_minimind_experiment
from rag_ime.predictor import NullPredictionProvider, prediction_provider_from_env
from rag_ime.model_registry import fingerprint_model_artifact


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit, export, or evaluate prompt-free MiniMind IME completion data"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    audit_parser = subparsers.add_parser("audit", help="Validate split isolation and suffix-only data contracts")
    audit_parser.add_argument("--dataset", default=str(DEFAULT_DATASET_ROOT))
    audit_parser.add_argument("--report", default="")

    export_parser = subparsers.add_parser("export", help="Flatten three positive suffixes into prefix/completion pairs")
    export_parser.add_argument("--dataset", default=str(DEFAULT_DATASET_ROOT))
    export_parser.add_argument("--output", required=True)
    export_parser.add_argument("--report", default="")

    ranking_parser = subparsers.add_parser(
        "export-ranking",
        help="Export prompt-free chosen/rejected suffix pairs for an optional margin loss",
    )
    ranking_parser.add_argument("--dataset", default=str(DEFAULT_DATASET_ROOT))
    ranking_parser.add_argument("--output", required=True)
    ranking_parser.add_argument("--report", default="")

    experiment_parser = subparsers.add_parser(
        "prepare-experiment",
        help="Prepare hash-bound A0/A1 inputs without claiming that training ran",
    )
    experiment_parser.add_argument("--causal-manifest", required=True)
    experiment_parser.add_argument("--dataset", default=str(DEFAULT_DATASET_ROOT))
    experiment_parser.add_argument("--output", required=True)
    experiment_parser.add_argument("--base-checkpoint", required=True)
    experiment_parser.add_argument("--base-checkpoint-fingerprint", required=True)
    experiment_parser.add_argument("--tokenizer-fingerprint", required=True)
    experiment_parser.add_argument("--purpose", choices=("demo", "production"), default="demo")
    experiment_parser.add_argument("--ranking-loss-weight", type=float, default=0.1)
    experiment_parser.add_argument("--report", default="")

    evaluate_parser = subparsers.add_parser(
        "evaluate",
        help="Evaluate an already-running predictor; this command never starts a service or training job",
    )
    evaluate_parser.add_argument("--dataset", default=str(DEFAULT_DATASET_ROOT))
    evaluate_parser.add_argument("--split", choices=("train", "val", "test"), default="test")
    evaluate_parser.add_argument("--stage", choices=(PRODUCTION_CANDIDATE_STAGE, RAW_MODEL_OUTPUT_STAGE), default=PRODUCTION_CANDIDATE_STAGE)
    evaluate_parser.add_argument("--provider", choices=("env", "raw-jsonl"), required=True)
    evaluate_parser.add_argument("--raw-output-jsonl", default="")
    evaluate_parser.add_argument(
        "--raw-capture-report",
        default="",
        help="Capture report that binds the raw JSONL to the loaded checkpoint and dataset",
    )
    evaluate_parser.add_argument(
        "--semantic-judgments",
        default="",
        help="Versioned local human-judgment fixture; no network/model judge is called",
    )
    evaluate_parser.add_argument("--checkpoint", default="")
    evaluate_parser.add_argument(
        "--checkpoint-path",
        default="",
        help="Bind the report to the current local artifact fingerprint without activating it",
    )
    evaluate_parser.add_argument("--baseline-report", default="")
    evaluate_parser.add_argument("--report", required=True)

    args = parser.parse_args(argv)
    try:
        if args.command == "audit":
            payload = audit_completion_dataset(args.dataset)
        elif args.command == "export":
            payload = export_minimind_training_pairs(args.dataset, args.output)
        elif args.command == "export-ranking":
            payload = export_minimind_ranking_pairs(args.dataset, args.output)
        elif args.command == "prepare-experiment":
            payload = prepare_minimind_experiment(
                causal_manifest_path=args.causal_manifest,
                completion_dataset_root=args.dataset,
                output_root=args.output,
                base_checkpoint=args.base_checkpoint,
                base_checkpoint_fingerprint=args.base_checkpoint_fingerprint,
                tokenizer_fingerprint=args.tokenizer_fingerprint,
                purpose=args.purpose,
                ranking_loss_weight=args.ranking_loss_weight,
            )
        else:
            baseline = _read_json(args.baseline_report) if args.baseline_report else None
            semantic_scorer = (
                HumanJudgmentFixtureScorer.from_path(args.semantic_judgments)
                if args.semantic_judgments
                else None
            )
            if args.stage == PRODUCTION_CANDIDATE_STAGE:
                if args.provider != "env":
                    raise ValueError("production_candidate stage requires --provider env")
                provider = prediction_provider_from_env()
                if isinstance(provider, NullPredictionProvider):
                    raise RuntimeError(
                        "predictor is not configured; set a loopback provider, base URL, and model before evaluation"
                    )
                runtime_evidence = (
                    _verify_runtime_checkpoint(provider, args.checkpoint_path)
                    if args.checkpoint_path
                    else {}
                )
                payload = run_minimind_quality_gate(
                    provider,
                    dataset_root=args.dataset,
                    split=args.split,
                    checkpoint=args.checkpoint,
                    baseline_report=baseline,
                    semantic_scorer=semantic_scorer,
                )
            else:
                if args.provider != "raw-jsonl" or not args.raw_output_jsonl:
                    raise ValueError("raw_model_output stage requires --provider raw-jsonl and --raw-output-jsonl")
                raw_provider = _RawJsonlReplayProvider(args.raw_output_jsonl)
                payload = run_minimind_raw_output_gate(
                    raw_provider,
                    dataset_root=args.dataset,
                    split=args.split,
                    checkpoint=args.checkpoint,
                    baseline_report=baseline,
                    semantic_scorer=semantic_scorer,
                )
            if args.checkpoint_path:
                payload["checkpointFingerprint"] = fingerprint_model_artifact(args.checkpoint_path)
                payload["checkpointPath"] = str(Path(args.checkpoint_path).expanduser().resolve())
                if args.stage == PRODUCTION_CANDIDATE_STAGE:
                    payload["runtimeModelEvidence"] = {
                        **runtime_evidence,
                        "checkpoint": args.checkpoint,
                        "checkpointFingerprint": payload["checkpointFingerprint"],
                        "datasetFingerprint": payload.get("datasetFingerprint"),
                    }
                elif args.raw_capture_report:
                    payload["rawCaptureEvidence"] = _verify_raw_capture_evidence(
                        capture_report_path=args.raw_capture_report,
                        raw_output_path=args.raw_output_jsonl,
                        checkpoint=args.checkpoint,
                        checkpoint_path=args.checkpoint_path,
                        dataset_fingerprint=payload.get("datasetFingerprint"),
                    )
    except (FileNotFoundError, json.JSONDecodeError, RuntimeError, ValueError) as exc:
        payload = {"ok": False, "command": args.command, "error": str(exc)}

    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    report_path = str(getattr(args, "report", "") or "")
    if report_path:
        write_quality_report(payload, report_path)
    print(rendered)
    return 0 if bool(payload.get("ok", payload.get("gatePassed"))) else 1


def _read_json(path: str | Path) -> dict[str, object]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("baseline report must contain a JSON object")
    return payload


def _verify_runtime_checkpoint(provider: object, checkpoint_path: str | Path) -> dict[str, object]:
    expected_path = Path(checkpoint_path).expanduser().resolve()
    expected_fingerprint = fingerprint_model_artifact(expected_path)
    config = getattr(provider, "config", None)
    configured_model = Path(str(getattr(config, "model", "") or "")).expanduser().resolve()
    if not configured_model.is_dir() or fingerprint_model_artifact(configured_model) != expected_fingerprint:
        raise RuntimeError("configured production provider does not reference the candidate artifact")
    capability_probe = getattr(provider, "capability_probe", None)
    if not callable(capability_probe):
        raise RuntimeError("production provider cannot prove its loaded model identity")
    health = capability_probe()
    if not isinstance(health, dict) or health.get("ok") is not True or health.get("modelLoaded") is not True:
        raise RuntimeError("production predictor health did not prove a loaded model")
    health_model = Path(str(health.get("model") or "")).expanduser().resolve()
    if not health_model.is_dir() or fingerprint_model_artifact(health_model) != expected_fingerprint:
        raise RuntimeError("production predictor is loaded with a different model artifact")
    return {
        "verified": True,
        "configuredModel": str(configured_model),
        "runtimeModel": str(health_model),
        "runtimeProvider": str(health.get("providerName") or health.get("provider") or ""),
    }


def _verify_raw_capture_evidence(
    *,
    capture_report_path: str | Path,
    raw_output_path: str | Path,
    checkpoint: str,
    checkpoint_path: str | Path,
    dataset_fingerprint: object,
) -> dict[str, object]:
    report_path = Path(capture_report_path).expanduser().resolve()
    raw_path = Path(raw_output_path).expanduser().resolve()
    report = _read_json(report_path)
    expected_fingerprint = fingerprint_model_artifact(checkpoint_path)
    raw_sha256 = _sha256_file(raw_path)
    expected = {
        "checkpoint": checkpoint,
        "checkpointFingerprint": expected_fingerprint,
        "datasetFingerprint": dataset_fingerprint,
        "rawOutputSha256": raw_sha256,
        "verified": True,
    }
    mismatches = [field for field, value in expected.items() if report.get(field) != value]
    if mismatches:
        raise RuntimeError("raw capture evidence mismatch: " + ", ".join(mismatches))
    return {
        "verified": True,
        "checkpoint": checkpoint,
        "checkpointFingerprint": expected_fingerprint,
        "datasetFingerprint": dataset_fingerprint,
        "runtimeModel": report.get("runtimeModel"),
        "rawOutputSha256": raw_sha256,
        "captureReportSha256": _sha256_file(report_path),
    }


def _sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


class _RawJsonlReplayProvider:
    """Deterministic replay of raw branch outputs captured by a training runtime."""

    def __init__(self, path: str | Path) -> None:
        self._by_prefix: dict[str, RawCompletionBatch] = {}
        for line_number, raw_line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
            if not raw_line.strip() or raw_line.lstrip().startswith("#"):
                continue
            row = json.loads(raw_line)
            if not isinstance(row, dict):
                raise ValueError(f"raw output row {line_number} must be an object")
            prefix = str(row.get("prefix") or "")
            candidates = row.get("candidates")
            if not prefix or not isinstance(candidates, list) or not all(isinstance(item, str) for item in candidates):
                raise ValueError(f"raw output row {line_number} requires prefix and string candidates")
            if prefix in self._by_prefix:
                raise ValueError(f"duplicate raw output prefix at row {line_number}")
            self._by_prefix[prefix] = RawCompletionBatch(
                candidates=tuple(candidates),
                raw_response=str(row.get("rawResponse") or ""),
                latency_ms=max(0, int(row.get("latencyMs") or 0)),
                provider_name=str(row.get("provider") or "raw-jsonl-replay"),
            )

    def complete_raw(self, *, prefix: str, max_candidates: int = 3) -> RawCompletionBatch:
        batch = self._by_prefix.get(prefix)
        if batch is None:
            return RawCompletionBatch(candidates=(), provider_name="raw-jsonl-replay")
        return RawCompletionBatch(
            candidates=batch.candidates[:max_candidates],
            raw_response=batch.raw_response,
            latency_ms=batch.latency_ms,
            provider_name=batch.provider_name,
        )


if __name__ == "__main__":
    raise SystemExit(main())
