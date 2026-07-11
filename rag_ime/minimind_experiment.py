from __future__ import annotations

import hashlib
import json
from pathlib import Path

from rag_ime.authorized_blog_corpus import SCHEMA_VERSION as BLOG_CORPUS_SCHEMA_VERSION
from rag_ime.minimind_quality_gate import (
    audit_completion_dataset,
    export_minimind_ranking_pairs,
    export_minimind_training_pairs,
)


EXPERIMENT_SCHEMA_VERSION = "rag-ime.minimind-experiment.v1"


def prepare_minimind_experiment(
    *,
    causal_manifest_path: str | Path,
    completion_dataset_root: str | Path,
    output_root: str | Path,
    base_checkpoint: str,
    base_checkpoint_fingerprint: str,
    tokenizer_fingerprint: str,
    purpose: str = "demo",
    ranking_loss_weight: float = 0.1,
) -> dict[str, object]:
    """Prepare immutable A0/A1 inputs without pretending to run training.

    Causal blog text and single-user suffix supervision remain separate phases.
    The public completion seed may exercise the pipeline in demo mode, but it
    cannot produce a production promotion plan.
    """

    if purpose not in {"demo", "production"}:
        raise ValueError("purpose must be demo or production")
    if not base_checkpoint.strip():
        raise ValueError("base_checkpoint is required")
    for name, value in (
        ("base_checkpoint_fingerprint", base_checkpoint_fingerprint),
        ("tokenizer_fingerprint", tokenizer_fingerprint),
    ):
        if not _is_sha256(value):
            raise ValueError(f"{name} must be sha256:<64 lowercase hex>")
    if not 0.0 < ranking_loss_weight <= 1.0:
        raise ValueError("ranking_loss_weight must be in (0, 1]")

    causal_path = Path(causal_manifest_path).expanduser().resolve()
    causal = _load_object(causal_path)
    _validate_causal_manifest(causal)

    completion_root = Path(completion_dataset_root).expanduser().resolve()
    completion_manifest = _load_object(completion_root / "manifest.json")
    completion_audit = audit_completion_dataset(completion_root)
    if not completion_audit.get("ok"):
        raise ValueError("completion dataset audit failed")
    production_ready = bool(completion_manifest.get("productionTrainingReady", False))
    if purpose == "production" and not production_ready:
        raise ValueError("production experiment requires productionTrainingReady=true completion data")

    output = Path(output_root).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    sft = export_minimind_training_pairs(completion_root, output / "suffix-sft")
    ranking = export_minimind_ranking_pairs(completion_root, output / "suffix-ranking")

    plan = {
        "schemaVersion": EXPERIMENT_SCHEMA_VERSION,
        "purpose": purpose,
        "promotionEligible": purpose == "production" and production_ready,
        "baseCheckpoint": {
            "id": base_checkpoint.strip(),
            "fingerprint": base_checkpoint_fingerprint,
            "tokenizerFingerprint": tokenizer_fingerprint,
            "tokenizerFrozenAcrossAB": True,
        },
        "inputs": {
            "causalCorpus": {
                "manifest": str(causal_path),
                "manifestSha256": _sha256_file(causal_path),
                "corpusFingerprint": causal["corpusFingerprint"],
                "rowShape": {"text": "string"},
            },
            "completionDataset": {
                "root": str(completion_root),
                "datasetFingerprint": completion_audit["datasetFingerprint"],
                "productionTrainingReady": production_ready,
                "sftManifest": str(output / "suffix-sft" / "export-manifest.json"),
                "rankingManifest": str(output / "suffix-ranking" / "ranking-export-manifest.json"),
            },
        },
        "phases": [
            {
                "id": "a0-causal-adaptation",
                "initialization": "baseCheckpoint",
                "objective": "causal_language_modeling",
                "input": "inputs.causalCorpus",
                "forbiddenFields": ["prefix", "completion", "chosen", "rejected", "messages", "prompt"],
                "outputCheckpoint": "a0-causal",
            },
            {
                "id": "a0-suffix-sft",
                "initialization": "a0-causal",
                "objective": "suffix_only_causal_loss",
                "input": "inputs.completionDataset.sftManifest",
                "prefixLossMasked": True,
                "outputCheckpoint": "a0-sft",
            },
            {
                "id": "a1-ranking-ab",
                "initialization": "a0-sft",
                "control": "suffix_only_causal_loss",
                "treatment": "suffix_only_causal_loss_plus_length_normalized_pairwise_margin",
                "rankingInput": "inputs.completionDataset.rankingManifest",
                "rankingLossWeight": ranking_loss_weight,
                "outputCheckpoints": ["a1-control", "a1-ranking"],
            },
        ],
        "requiredEvaluation": [
            "raw_model_output",
            "production_candidate",
            "semantic_top1_top3",
            "continuous_tab",
            "anti_echo",
            "boundary_validity",
            "three_candidate_diversity",
            "complete_response_latency",
            "foreground_first_visible_latency",
        ],
        "trainingExecuted": False,
        "notes": [
            "This artifact prepares inputs only; it does not claim that training ran.",
            "Causal blog rows and suffix supervision must never be concatenated into one row schema.",
            "Demo plans are never promotion eligible.",
        ],
        "exportPairCounts": {"sft": sft["pairCounts"], "ranking": ranking["pairCounts"]},
    }
    plan_path = output / "experiment-plan.json"
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"ok": True, "plan": str(plan_path), **plan}


def _validate_causal_manifest(payload: dict[str, object]) -> None:
    if payload.get("schemaVersion") != BLOG_CORPUS_SCHEMA_VERSION:
        raise ValueError("causal manifest is not an authorized blog corpus manifest")
    contract = payload.get("trainingContract")
    if not isinstance(contract, dict) or contract.get("rowShape") != {"text": "string"}:
        raise ValueError("causal corpus must use text-only rows")
    if contract.get("chatFieldsAllowed") is not False:
        raise ValueError("causal corpus must forbid chat fields")
    if not str(payload.get("corpusFingerprint") or "").strip():
        raise ValueError("causal corpus fingerprint is required")


def _load_object(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _is_sha256(value: str) -> bool:
    prefix, separator, digest = value.partition(":")
    return separator == ":" and prefix == "sha256" and len(digest) == 64 and all(ch in "0123456789abcdef" for ch in digest)


def _sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
