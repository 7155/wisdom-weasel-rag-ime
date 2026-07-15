from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Callable, Iterable, Protocol

from .anti_echo import candidate_echoes_text, candidate_has_self_repetition, repeat_norm
from .predictor import PREDICTION_REQUEST_IME_POST_COMMIT, PredictionProvider, predict_with_optional_request_context
from .text_utils import compact_whitespace


DATASET_SCHEMA_VERSION = "rag-ime.minimind-completion-dataset.v1"
AUDIT_SCHEMA_VERSION = "rag-ime.minimind-dataset-audit.v1"
QUALITY_SCHEMA_VERSION = "rag-ime.minimind-quality-gate.v1"
EXPORT_SCHEMA_VERSION = "rag-ime.minimind-training-export.v1"
RANKING_EXPORT_SCHEMA_VERSION = "rag-ime.minimind-ranking-export.v1"
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATASET_ROOT = REPO_ROOT / "dataset" / "minimind_completion_v3_public"
SPLITS = ("train", "val", "test")
PRODUCTION_CANDIDATE_STAGE = "production_candidate"
RAW_MODEL_OUTPUT_STAGE = "raw_model_output"
HUMAN_JUDGMENT_SCHEMA_VERSION = "rag-ime.minimind-human-judgments.v1"
PROMOTION_QUALITY_CHECK_NAMES = frozenset(
    {
        "semantic-scorer-configured",
        "semantic-judgment-coverage",
        "semantic-top1",
        "semantic-top3",
        "bare-completion",
        "boundary-valid",
        "anti-echo",
        "three-candidates",
        "hard-negative-avoidance",
        "candidate-diversity",
        "continuous-tab",
        "mean-reciprocal-rank",
        "latency-p95",
    }
)

_ALLOWED_CASE_FIELDS = {
    "id",
    "chainId",
    "turn",
    "domain",
    "prefix",
    "completions",
    "hardNegatives",
    "forbiddenCandidatePrefixes",
    "forbiddenJoinedFragments",
    "maxCandidateChars",
}
_PROMPT_FIELDS = {"prompt", "system", "user", "assistant", "messages", "roles", "chatTemplate"}
_ASSISTANT_STYLE_RE = re.compile(
    r"(?:^|[：:，,。.!！?？])(assistant|system|user)(?:$|[：:，,。.!！?？])|"
    r"^(?:作为(?:AI|模型|助手)|请回答|请解释|候选如下|下面给出|以下是)",
    re.IGNORECASE,
)
_SENSITIVE_RE = re.compile(
    r"(?:sk-[A-Za-z0-9]{8,}|bearer\s+[A-Za-z0-9._-]+|api[_ -]?key|access[_ -]?token|secret[_ -]?key|"
    r"身份证|银行卡|验证码|手机号)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CompletionQualityCase:
    case_id: str
    split: str
    chain_id: str
    turn: int
    domain: str
    prefix: str
    completions: tuple[str, ...]
    hard_negatives: tuple[str, ...]
    forbidden_candidate_prefixes: tuple[str, ...]
    forbidden_joined_fragments: tuple[str, ...]
    max_candidate_chars: int = 24
    raw_fields: frozenset[str] = frozenset()


@dataclass(frozen=True)
class CompletionQualityThresholds:
    min_semantic_top1_rate: float = 0.80
    min_semantic_top3_rate: float = 1.00
    min_semantic_judgment_coverage_rate: float = 1.00
    min_bare_completion_rate: float = 1.00
    min_boundary_valid_rate: float = 1.00
    min_anti_echo_rate: float = 1.00
    min_three_candidate_rate: float = 1.00
    min_hard_negative_avoidance_rate: float = 1.00
    min_diversity_rate: float = 0.90
    min_tab_chain_pass_rate: float = 1.00
    min_mean_reciprocal_rank: float = 0.80
    max_p95_latency_ms: int = 500
    lexical_reference_score_floor: float = 0.42
    lexical_reference_margin_floor: float = 0.08


@dataclass(frozen=True)
class RawCompletionBatch:
    """Unparsed decode branches emitted directly by a checkpoint/runtime."""

    candidates: tuple[str, ...]
    raw_response: str = ""
    latency_ms: int = 0
    provider_name: str = "raw-completion"


class RawCompletionProvider(Protocol):
    """Checkpoint-facing interface that must not apply production candidate parsing."""

    def complete_raw(self, *, prefix: str, max_candidates: int = 3) -> RawCompletionBatch:
        ...


@dataclass(frozen=True)
class _ObservedCandidate:
    text: str
    provider_name: str
    latency_ms: int


@dataclass(frozen=True)
class _ObservedBatch:
    candidates: tuple[_ObservedCandidate, ...]
    latency_ms: int
    raw_response: str


@dataclass(frozen=True)
class SemanticJudgment:
    accepted: bool
    source: str
    note: str = ""


class SemanticScorer(Protocol):
    """Explicit, deterministic semantic judgment source; never an implicit network judge."""

    dataset_fingerprint: str
    scorer_id: str

    def judge(self, *, case_id: str, candidate: str) -> SemanticJudgment | None:
        ...


class HumanJudgmentFixtureScorer:
    """Exact candidate judgments loaded from a versioned local JSON fixture."""

    def __init__(
        self,
        *,
        dataset_fingerprint: str,
        judgments: dict[tuple[str, str], SemanticJudgment],
        scorer_id: str = "human-fixture",
    ) -> None:
        self.dataset_fingerprint = dataset_fingerprint
        self.scorer_id = scorer_id
        self._judgments = dict(judgments)

    @classmethod
    def from_path(cls, path: str | Path) -> "HumanJudgmentFixtureScorer":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("schemaVersion") != HUMAN_JUDGMENT_SCHEMA_VERSION:
            raise ValueError("unsupported MiniMind human-judgment fixture")
        fingerprint = str(payload.get("datasetFingerprint") or "")
        if not fingerprint:
            raise ValueError("human-judgment fixture requires datasetFingerprint")
        rows = payload.get("judgments")
        if not isinstance(rows, list):
            raise ValueError("human-judgment fixture judgments must be an array")
        judgments: dict[tuple[str, str], SemanticJudgment] = {}
        for index, row in enumerate(rows, start=1):
            if not isinstance(row, dict):
                raise ValueError(f"human-judgment fixture row {index} must be an object")
            case_id = compact_whitespace(str(row.get("caseId") or ""))
            candidate = str(row.get("candidate") or "")
            accepted = row.get("accepted")
            if not case_id or not candidate or not isinstance(accepted, bool):
                raise ValueError(f"human-judgment fixture row {index} is incomplete")
            key = (case_id, _quality_norm(candidate))
            judgment = SemanticJudgment(
                accepted=accepted,
                source=str(payload.get("scorerId") or "human-fixture"),
                note=compact_whitespace(str(row.get("note") or "")),
            )
            previous = judgments.get(key)
            if previous is not None and previous.accepted != judgment.accepted:
                raise ValueError(f"conflicting human judgments for {case_id}: {candidate}")
            judgments[key] = judgment
        return cls(
            dataset_fingerprint=fingerprint,
            judgments=judgments,
            scorer_id=str(payload.get("scorerId") or "human-fixture"),
        )

    def judge(self, *, case_id: str, candidate: str) -> SemanticJudgment | None:
        return self._judgments.get((case_id, _quality_norm(candidate)))


def load_completion_dataset(root: str | Path = DEFAULT_DATASET_ROOT) -> dict[str, list[CompletionQualityCase]]:
    dataset_root = Path(root)
    manifest = _load_manifest(dataset_root)
    split_files = manifest.get("splits")
    if not isinstance(split_files, dict):
        raise ValueError("dataset manifest splits must be an object")
    result: dict[str, list[CompletionQualityCase]] = {}
    for split in SPLITS:
        relative = str(split_files.get(split) or f"{split}.jsonl")
        path = dataset_root / relative
        cases: list[CompletionQualityCase] = []
        for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not raw_line.strip() or raw_line.lstrip().startswith("#"):
                continue
            payload = json.loads(raw_line)
            if not isinstance(payload, dict):
                raise ValueError(f"{path}:{line_number} must contain a JSON object")
            cases.append(_case_from_payload(payload, split=split, source=f"{path}:{line_number}"))
        result[split] = cases
    return result


def audit_completion_dataset(root: str | Path = DEFAULT_DATASET_ROOT) -> dict[str, object]:
    dataset_root = Path(root)
    errors: list[dict[str, object]] = []
    warnings: list[dict[str, object]] = []
    try:
        manifest = _load_manifest(dataset_root)
        dataset = load_completion_dataset(dataset_root)
    except (FileNotFoundError, json.JSONDecodeError, ValueError) as exc:
        return {
            "schemaVersion": AUDIT_SCHEMA_VERSION,
            "ok": False,
            "datasetRoot": _portable_dataset_path(dataset_root),
            "datasetFingerprint": "",
            "errors": [{"code": "dataset_load_failed", "detail": str(exc)}],
            "warnings": [],
        }

    prefix_owner: dict[str, tuple[str, str]] = {}
    target_owner: dict[str, tuple[str, str]] = {}
    chain_owner: dict[str, str] = {}
    all_case_ids: set[str] = set()
    domain_counts: dict[str, int] = {}

    for split, cases in dataset.items():
        for case in cases:
            domain_counts[case.domain] = domain_counts.get(case.domain, 0) + 1
            if case.case_id in all_case_ids:
                _add_issue(errors, "duplicate_case_id", case, detail=case.case_id)
            all_case_ids.add(case.case_id)
            # raw_fields is captured while parsing each JSONL row.  Auditing therefore
            # stays O(n) instead of reopening and scanning the split for every case.
            unexpected_fields = set(case.raw_fields) - _ALLOWED_CASE_FIELDS
            for field in sorted(unexpected_fields & _PROMPT_FIELDS):
                _add_issue(errors, "prompt_field_forbidden", case, detail=field)
            if unexpected_fields - _PROMPT_FIELDS:
                _add_issue(errors, "unknown_case_fields", case, detail=", ".join(sorted(unexpected_fields - _PROMPT_FIELDS)))
            if not case.prefix:
                _add_issue(errors, "empty_prefix", case)
            if _SENSITIVE_RE.search(case.prefix):
                _add_issue(errors, "public_safe_violation", case, detail="prefix")
            if len(case.completions) != 3:
                _add_issue(errors, "three_positive_completions_required", case, detail=str(len(case.completions)))
            if len({_quality_norm(value) for value in case.completions}) != len(case.completions):
                _add_issue(errors, "duplicate_positive_completion", case)
            for completion in case.completions:
                if not _bare_completion_valid(case, completion):
                    _add_issue(errors, "invalid_bare_completion", case, detail=completion)
                if not _anti_echo_valid(case.prefix, completion):
                    _add_issue(errors, "positive_echoes_prefix", case, detail=completion)
                if not _boundary_valid(case, completion):
                    _add_issue(errors, "positive_boundary_invalid", case, detail=completion)
                if _SENSITIVE_RE.search(completion):
                    _add_issue(errors, "public_safe_violation", case, detail="completion")
            if not case.hard_negatives:
                _add_issue(errors, "hard_negatives_required", case)
            elif len(case.hard_negatives) != len(case.completions):
                _add_issue(
                    errors,
                    "hard_negative_count_must_match_completions",
                    case,
                    detail=f"{len(case.hard_negatives)} != {len(case.completions)}",
                )
            positive_norms = {_quality_norm(value) for value in case.completions}
            for hard_negative in case.hard_negatives:
                normalized = _quality_norm(hard_negative)
                if normalized in positive_norms:
                    _add_issue(errors, "hard_negative_equals_positive", case, detail=hard_negative)
                if _SENSITIVE_RE.search(hard_negative):
                    _add_issue(errors, "public_safe_violation", case, detail="hardNegative")

            prefix_key = _quality_norm(case.prefix)
            previous_prefix = prefix_owner.get(prefix_key)
            if previous_prefix and previous_prefix[0] != split:
                _add_issue(
                    errors,
                    "prefix_cross_split_leakage",
                    case,
                    detail=f"also in {previous_prefix[0]}:{previous_prefix[1]}",
                )
            prefix_owner.setdefault(prefix_key, (split, case.case_id))
            for completion in case.completions:
                target_key = _quality_norm(case.prefix + completion)
                previous_target = target_owner.get(target_key)
                if previous_target and previous_target[0] != split:
                    _add_issue(
                        errors,
                        "target_cross_split_leakage",
                        case,
                        detail=f"also in {previous_target[0]}:{previous_target[1]}",
                    )
                target_owner.setdefault(target_key, (split, case.case_id))
            previous_chain_split = chain_owner.get(case.chain_id)
            if previous_chain_split and previous_chain_split != split:
                _add_issue(errors, "chain_cross_split_leakage", case, detail=previous_chain_split)
            chain_owner.setdefault(case.chain_id, split)

    chain_reports: list[dict[str, object]] = []
    for split, cases in dataset.items():
        for chain_id, chain_cases in _chains(cases).items():
            ordered = sorted(chain_cases, key=lambda item: item.turn)
            turns_contiguous = [item.turn for item in ordered] == list(range(1, len(ordered) + 1))
            transitions_valid = all(
                ordered[index + 1].prefix == ordered[index].prefix + ordered[index].completions[0]
                for index in range(len(ordered) - 1)
            )
            if not turns_contiguous:
                _add_issue(errors, "chain_turns_not_contiguous", ordered[0], detail=chain_id)
            if len(ordered) > 1 and not transitions_valid:
                _add_issue(errors, "chain_gold_transition_invalid", ordered[0], detail=chain_id)
            chain_reports.append(
                {
                    "split": split,
                    "chainId": chain_id,
                    "turnCount": len(ordered),
                    "multiTurn": len(ordered) > 1,
                    "turnsContiguous": turns_contiguous,
                    "goldTransitionsValid": transitions_valid,
                }
            )

    case_count = sum(len(cases) for cases in dataset.values())
    if domain_counts.get("technical", 0) == 0 or domain_counts.get("daily", 0) == 0:
        warnings.append({"code": "domain_coverage_incomplete", "domainCounts": domain_counts})
    fingerprint = dataset_fingerprint(dataset)
    reviewed_baselines = _audit_reviewed_baselines(
        dataset_root,
        manifest=manifest,
        dataset_fingerprint_value=fingerprint,
        errors=errors,
    )
    return {
        "schemaVersion": AUDIT_SCHEMA_VERSION,
        "ok": not errors,
        "datasetRoot": _portable_dataset_path(dataset_root),
        "datasetId": manifest.get("datasetId"),
        "datasetFingerprint": fingerprint,
        "splitCounts": {split: len(dataset[split]) for split in SPLITS},
        "caseCount": case_count,
        "positivePairCount": case_count * 3,
        "hardNegativeCount": sum(len(case.hard_negatives) for cases in dataset.values() for case in cases),
        "domainCounts": domain_counts,
        "multiTurnChainCount": sum(1 for item in chain_reports if item["multiTurn"]),
        "chains": chain_reports,
        "reviewedBaselines": reviewed_baselines,
        "errors": errors,
        "warnings": warnings,
    }


def export_minimind_training_pairs(
    dataset_root: str | Path,
    output_root: str | Path,
) -> dict[str, object]:
    audit = audit_completion_dataset(dataset_root)
    if not audit.get("ok"):
        raise ValueError("MiniMind dataset audit failed; refusing to export training pairs")
    dataset = load_completion_dataset(dataset_root)
    destination = Path(output_root)
    destination.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    files: dict[str, str] = {}
    for split in SPLITS:
        path = destination / f"{split}.jsonl"
        rows = [
            {"prefix": case.prefix, "completion": completion}
            for case in dataset[split]
            for completion in case.completions
        ]
        path.write_text(
            "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
            encoding="utf-8",
        )
        counts[split] = len(rows)
        files[split] = str(path)
    report = {
        "schemaVersion": EXPORT_SCHEMA_VERSION,
        "ok": True,
        "sourceDataset": _portable_dataset_path(dataset_root),
        "datasetFingerprint": audit["datasetFingerprint"],
        "outputRoot": str(destination),
        "files": files,
        "pairCounts": counts,
        "recordKeys": ["completion", "prefix"],
        "promptFree": True,
        "prefixLossMasked": True,
        "hardNegativesExportedAsTargets": False,
    }
    (destination / "export-manifest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def export_minimind_ranking_pairs(
    dataset_root: str | Path,
    output_root: str | Path,
) -> dict[str, object]:
    """Export prompt-free chosen/rejected suffix pairs for an optional ranking loss."""

    audit = audit_completion_dataset(dataset_root)
    if not audit.get("ok"):
        raise ValueError("MiniMind dataset audit failed; refusing to export ranking pairs")
    dataset = load_completion_dataset(dataset_root)
    destination = Path(output_root)
    destination.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    files: dict[str, str] = {}
    for split in SPLITS:
        path = destination / f"{split}.jsonl"
        rows = [
            {"prefix": case.prefix, "chosen": chosen, "rejected": rejected}
            for case in dataset[split]
            for chosen, rejected in zip(case.completions, case.hard_negatives, strict=True)
        ]
        path.write_text(
            "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
            encoding="utf-8",
        )
        counts[split] = len(rows)
        files[split] = str(path)
    report = {
        "schemaVersion": RANKING_EXPORT_SCHEMA_VERSION,
        "ok": True,
        "sourceDataset": _portable_dataset_path(dataset_root),
        "datasetFingerprint": audit["datasetFingerprint"],
        "outputRoot": str(destination),
        "files": files,
        "pairCounts": counts,
        "recordKeys": ["chosen", "prefix", "rejected"],
        "promptFree": True,
        "recommendedObjective": "length-normalized chosen suffix log-likelihood > rejected suffix log-likelihood + margin",
        "useAsCausalPositiveTargets": False,
    }
    (destination / "ranking-export-manifest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def run_minimind_quality_gate(
    provider: PredictionProvider,
    *,
    dataset_root: str | Path = DEFAULT_DATASET_ROOT,
    split: str = "test",
    thresholds: CompletionQualityThresholds | None = None,
    checkpoint: str = "",
    baseline_report: dict[str, object] | None = None,
    semantic_scorer: SemanticScorer | None = None,
) -> dict[str, object]:
    """Evaluate candidates after the production provider has parsed/filtered them.

    This function deliberately does not claim to inspect raw checkpoint output.
    Use ``run_minimind_raw_output_gate`` with a RawCompletionProvider for that.
    """

    def observe(prefix: str) -> _ObservedBatch:
        started = time.perf_counter()
        predictions = predict_with_optional_request_context(
            provider,
            current_input="",
            recent_context=prefix,
            max_candidates=3,
            request_type=PREDICTION_REQUEST_IME_POST_COMMIT,
            rime_candidates=(),
        )
        wall_ms = int((time.perf_counter() - started) * 1000)
        latency_ms = max(wall_ms, max((int(item.latency_ms) for item in predictions), default=0))
        return _ObservedBatch(
            candidates=tuple(
                _ObservedCandidate(
                    text=item.text,
                    provider_name=item.provider_name,
                    latency_ms=int(item.latency_ms),
                )
                for item in predictions[:3]
            ),
            latency_ms=latency_ms,
            raw_response="",
        )

    return _run_minimind_quality_gate(
        observe,
        dataset_root=dataset_root,
        split=split,
        thresholds=thresholds,
        checkpoint=checkpoint or _provider_checkpoint(provider),
        provider_name=provider.__class__.__name__,
        evaluation_stage=PRODUCTION_CANDIDATE_STAGE,
        baseline_report=baseline_report,
        semantic_scorer=semantic_scorer,
    )


def run_minimind_raw_output_gate(
    provider: RawCompletionProvider,
    *,
    dataset_root: str | Path = DEFAULT_DATASET_ROOT,
    split: str = "test",
    thresholds: CompletionQualityThresholds | None = None,
    checkpoint: str = "",
    baseline_report: dict[str, object] | None = None,
    semantic_scorer: SemanticScorer | None = None,
) -> dict[str, object]:
    """Evaluate unparsed decode branches supplied by an explicit raw provider."""

    def observe(prefix: str) -> _ObservedBatch:
        started = time.perf_counter()
        batch = provider.complete_raw(prefix=prefix, max_candidates=3)
        wall_ms = int((time.perf_counter() - started) * 1000)
        return _ObservedBatch(
            candidates=tuple(
                _ObservedCandidate(text=text, provider_name=batch.provider_name, latency_ms=int(batch.latency_ms))
                for text in batch.candidates[:3]
            ),
            latency_ms=max(wall_ms, int(batch.latency_ms)),
            raw_response=batch.raw_response,
        )

    return _run_minimind_quality_gate(
        observe,
        dataset_root=dataset_root,
        split=split,
        thresholds=thresholds,
        checkpoint=checkpoint or provider.__class__.__name__,
        provider_name=provider.__class__.__name__,
        evaluation_stage=RAW_MODEL_OUTPUT_STAGE,
        baseline_report=baseline_report,
        semantic_scorer=semantic_scorer,
    )


def _run_minimind_quality_gate(
    observe: Callable[[str], _ObservedBatch],
    *,
    dataset_root: str | Path,
    split: str,
    thresholds: CompletionQualityThresholds | None,
    checkpoint: str,
    provider_name: str,
    evaluation_stage: str,
    baseline_report: dict[str, object] | None,
    semantic_scorer: SemanticScorer | None,
) -> dict[str, object]:
    if split not in SPLITS:
        raise ValueError(f"split must be one of: {', '.join(SPLITS)}")
    effective_thresholds = thresholds or CompletionQualityThresholds()
    audit = audit_completion_dataset(dataset_root)
    if not audit.get("ok"):
        return {
            "schemaVersion": QUALITY_SCHEMA_VERSION,
            "gatePassed": False,
            "promotionEligible": False,
            "checkpoint": checkpoint,
            "evaluationStage": evaluation_stage,
            "split": split,
            "datasetAudit": audit,
            "summary": {},
            "checks": [{"name": "dataset-audit", "passed": False}],
            "cases": [],
            "tabChains": [],
        }
    dataset_fingerprint_value = str(audit.get("datasetFingerprint") or "")
    if semantic_scorer is not None and semantic_scorer.dataset_fingerprint != dataset_fingerprint_value:
        return {
            "schemaVersion": QUALITY_SCHEMA_VERSION,
            "gatePassed": False,
            "promotionEligible": False,
            "checkpoint": checkpoint,
            "provider": provider_name,
            "evaluationStage": evaluation_stage,
            "split": split,
            "datasetId": audit.get("datasetId"),
            "datasetFingerprint": dataset_fingerprint_value,
            "datasetAudit": audit,
            "summary": {},
            "checks": [{"name": "semantic-fixture-fingerprint", "passed": False}],
            "semanticScorer": {
                "configured": True,
                "scorerId": semantic_scorer.scorer_id,
                "datasetFingerprint": semantic_scorer.dataset_fingerprint,
                "error": "dataset_fingerprint_mismatch",
            },
            "cases": [],
            "tabChains": [],
        }
    dataset = load_completion_dataset(dataset_root)
    cases = dataset[split]
    case_reports = [
        _evaluate_case(observe, case, thresholds=effective_thresholds, semantic_scorer=semantic_scorer)
        for case in cases
    ]
    tab_chains = _evaluate_tab_chains(
        observe,
        cases,
        thresholds=effective_thresholds,
        semantic_scorer=semantic_scorer,
    )
    summary = _quality_summary(case_reports, tab_chains=tab_chains)
    checks = _quality_checks(summary, thresholds=effective_thresholds, semantic_scorer_configured=semantic_scorer is not None)
    gate_passed = all(bool(item["passed"]) for item in checks)
    report: dict[str, object] = {
        "schemaVersion": QUALITY_SCHEMA_VERSION,
        "gatePassed": gate_passed,
        "promotionEligible": gate_passed and semantic_scorer is not None,
        "checkpoint": checkpoint,
        "provider": provider_name,
        "evaluationStage": evaluation_stage,
        "candidateSourceContract": (
            "unparsed decode branches from RawCompletionProvider"
            if evaluation_stage == RAW_MODEL_OUTPUT_STAGE
            else "production PredictionProvider candidates after provider-defined parsing/filtering"
        ),
        "split": split,
        "datasetId": audit.get("datasetId"),
        "datasetFingerprint": audit.get("datasetFingerprint"),
        "datasetAudit": audit,
        "scoringContract": {
            "lexicalReference": "character-sequence and bigram overlap against positive and negative references",
            "semantic": "explicit local human-judgment fixture only; no implicit network or model judge",
            "boundary": "case-annotated forbidden starts and joined fragments",
            "antiEcho": "candidate must be a new suffix and must not repeat the prefix",
            "gateMutatesCandidateOutput": False,
            "productionProviderMayParseOrFilter": evaluation_stage == PRODUCTION_CANDIDATE_STAGE,
        },
        "semanticScorer": {
            "configured": semantic_scorer is not None,
            "scorerId": semantic_scorer.scorer_id if semantic_scorer is not None else "",
            "datasetFingerprint": semantic_scorer.dataset_fingerprint if semantic_scorer is not None else "",
            "implicitNetworkJudge": False,
        },
        "summary": summary,
        "thresholds": _threshold_payload(effective_thresholds),
        "checks": checks,
        "cases": case_reports,
        "tabChains": tab_chains,
    }
    if baseline_report:
        report["comparison"] = compare_quality_reports(report, baseline_report)
    return report


def compare_quality_reports(current: dict[str, object], baseline: dict[str, object]) -> dict[str, object]:
    same_fingerprint = bool(current.get("datasetFingerprint")) and (
        current.get("datasetFingerprint") == baseline.get("datasetFingerprint")
    )
    if not same_fingerprint:
        return {
            "schemaVersion": "rag-ime.minimind-quality-comparison.v1",
            "comparable": False,
            "sameDatasetFingerprint": False,
            "baselineCheckpoint": baseline.get("checkpoint"),
            "currentCheckpoint": current.get("checkpoint"),
            "rejectionReason": "dataset_fingerprint_mismatch",
        }
    if current.get("evaluationStage") != baseline.get("evaluationStage"):
        return {
            "schemaVersion": "rag-ime.minimind-quality-comparison.v1",
            "comparable": False,
            "sameDatasetFingerprint": True,
            "baselineCheckpoint": baseline.get("checkpoint"),
            "currentCheckpoint": current.get("checkpoint"),
            "rejectionReason": "evaluation_stage_mismatch",
        }
    current_summary = current.get("summary") if isinstance(current.get("summary"), dict) else {}
    baseline_summary = baseline.get("summary") if isinstance(baseline.get("summary"), dict) else {}
    quality_metrics = (
        "semanticTop1Rate",
        "semanticTop3Rate",
        "semanticJudgmentCoverageRate",
        "lexicalReferenceTop1Rate",
        "lexicalReferenceTop3Rate",
        "bareCompletionRate",
        "boundaryValidRate",
        "antiEchoRate",
        "threeCandidateRate",
        "hardNegativeAvoidanceRate",
        "diversityRate",
        "tabChainPassRate",
        "meanReciprocalRank",
        "meanLexicalReferenceMargin",
    )
    deltas = {
        metric: round(float(current_summary.get(metric) or 0.0) - float(baseline_summary.get(metric) or 0.0), 6)
        for metric in quality_metrics
    }
    deltas["p95LatencyMs"] = round(
        float(current_summary.get("p95LatencyMs") or 0.0) - float(baseline_summary.get("p95LatencyMs") or 0.0),
        3,
    )
    regressions = [metric for metric in quality_metrics if deltas[metric] < 0]
    if deltas["p95LatencyMs"] > 0:
        regressions.append("p95LatencyMs")
    return {
        "schemaVersion": "rag-ime.minimind-quality-comparison.v1",
        "comparable": True,
        "baselineCheckpoint": baseline.get("checkpoint"),
        "currentCheckpoint": current.get("checkpoint"),
        "sameDatasetFingerprint": True,
        "deltas": deltas,
        "regressions": regressions,
        "improvedQualityMetricCount": sum(1 for metric in quality_metrics if deltas[metric] > 0),
    }


def write_quality_report(report: dict[str, object], path: str | Path) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def dataset_fingerprint(dataset: dict[str, list[CompletionQualityCase]]) -> str:
    rows = [
        {
            "split": split,
            "id": case.case_id,
            "chainId": case.chain_id,
            "turn": case.turn,
            "domain": case.domain,
            "prefix": case.prefix,
            "completions": list(case.completions),
            "hardNegatives": list(case.hard_negatives),
            "forbiddenCandidatePrefixes": list(case.forbidden_candidate_prefixes),
            "forbiddenJoinedFragments": list(case.forbidden_joined_fragments),
            "maxCandidateChars": case.max_candidate_chars,
        }
        for split in SPLITS
        for case in dataset[split]
    ]
    encoded = json.dumps(rows, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _evaluate_case(
    observe: Callable[[str], _ObservedBatch],
    case: CompletionQualityCase,
    *,
    thresholds: CompletionQualityThresholds,
    semantic_scorer: SemanticScorer | None,
    prefix_override: str | None = None,
) -> dict[str, object]:
    prefix = case.prefix if prefix_override is None else prefix_override
    observed = observe(prefix)
    candidate_reports = [
        _evaluate_candidate(
            case,
            item,
            prefix=prefix,
            rank=index,
            thresholds=thresholds,
            semantic_scorer=semantic_scorer,
        )
        for index, item in enumerate(observed.candidates[:3], start=1)
    ]
    semantic_ranks = [int(item["rank"]) for item in candidate_reports if item["semanticAccepted"] is True]
    lexical_ranks = [int(item["rank"]) for item in candidate_reports if item["lexicalReferenceAccepted"]]
    semantic_top1 = bool(candidate_reports and candidate_reports[0]["semanticAccepted"] is True)
    semantic_top3 = bool(semantic_ranks)
    lexical_top1 = bool(candidate_reports and candidate_reports[0]["lexicalReferenceAccepted"])
    lexical_top3 = bool(lexical_ranks)
    three_candidates = len(candidate_reports) == 3
    bare_valid = three_candidates and all(bool(item["bareCompletionValid"]) for item in candidate_reports)
    boundary_valid = three_candidates and all(bool(item["boundaryValid"]) for item in candidate_reports)
    anti_echo_valid = three_candidates and all(bool(item["antiEchoValid"]) for item in candidate_reports)
    hard_negative_avoided = three_candidates and all(bool(item["hardNegativeAvoided"]) for item in candidate_reports)
    diversity = _candidate_diversity([str(item["text"]) for item in candidate_reports]) if three_candidates else False
    reciprocal_rank = 0.0 if not semantic_ranks else round(1.0 / min(semantic_ranks), 6)
    structural_passed = (
        three_candidates
        and bare_valid
        and boundary_valid
        and anti_echo_valid
        and hard_negative_avoided
        and diversity
    )
    return {
        "caseId": case.case_id,
        "chainId": case.chain_id,
        "turn": case.turn,
        "domain": case.domain,
        "prefix": prefix,
        "teacherPrefix": case.prefix,
        "prefixMatchesTeacher": prefix == case.prefix,
        "latencyMs": observed.latency_ms,
        "rawResponse": observed.raw_response,
        "candidateCount": len(candidate_reports),
        "threeCandidates": three_candidates,
        "semanticTop1": semantic_top1,
        "semanticTop3": semantic_top3,
        "semanticTop1Judged": bool(candidate_reports and candidate_reports[0]["semanticAccepted"] is not None),
        "semanticJudgmentCount": sum(1 for item in candidate_reports if item["semanticAccepted"] is not None),
        "lexicalReferenceTop1": lexical_top1,
        "lexicalReferenceTop3": lexical_top3,
        "bareCompletionValid": bare_valid,
        "boundaryValid": boundary_valid,
        "antiEchoValid": anti_echo_valid,
        "hardNegativeAvoided": hard_negative_avoided,
        "diverse": diversity,
        "reciprocalRank": reciprocal_rank,
        "structuralPassed": structural_passed,
        "passed": semantic_top1 and structural_passed,
        "candidates": candidate_reports,
    }


def _evaluate_candidate(
    case: CompletionQualityCase,
    prediction: _ObservedCandidate,
    *,
    prefix: str,
    rank: int,
    thresholds: CompletionQualityThresholds,
    semantic_scorer: SemanticScorer | None,
) -> dict[str, object]:
    # Preserve exact provider output in reports. Validators normalize only their
    # local comparison views and never rewrite the candidate returned to callers.
    text = prediction.text
    positive_scores = [_lexical_reference_similarity(text, reference) for reference in case.completions]
    hard_scores = [_lexical_reference_similarity(text, reference) for reference in case.hard_negatives]
    positive_score = max(positive_scores, default=0.0)
    hard_score = max(hard_scores, default=0.0)
    positive_index = positive_scores.index(positive_score) + 1 if positive_scores else 0
    margin = positive_score - hard_score
    exact_hard_negative = _quality_norm(text) in {_quality_norm(value) for value in case.hard_negatives}
    hard_negative_avoided = not exact_hard_negative and hard_score < 0.92
    lexical_reference_accepted = (
        positive_score >= thresholds.lexical_reference_score_floor
        and margin >= thresholds.lexical_reference_margin_floor
        and hard_negative_avoided
    )
    judgment = semantic_scorer.judge(case_id=case.case_id, candidate=text) if semantic_scorer is not None else None
    return {
        "rank": rank,
        "text": text,
        "provider": prediction.provider_name,
        "latencyMs": int(prediction.latency_ms),
        "bestPositiveIndex": positive_index,
        "lexicalPositiveReferenceScore": round(positive_score, 6),
        "lexicalHardNegativeReferenceScore": round(hard_score, 6),
        "lexicalReferenceMargin": round(margin, 6),
        "lexicalReferenceAccepted": lexical_reference_accepted,
        "semanticAccepted": judgment.accepted if judgment is not None else None,
        "semanticJudgment": (
            {"accepted": judgment.accepted, "source": judgment.source, "note": judgment.note}
            if judgment is not None
            else None
        ),
        "bareCompletionValid": _bare_completion_valid(case, text),
        "boundaryValid": _boundary_valid(case, text, prefix=prefix),
        "antiEchoValid": _anti_echo_valid(prefix, text),
        "hardNegativeAvoided": hard_negative_avoided,
    }


def _evaluate_tab_chains(
    observe: Callable[[str], _ObservedBatch],
    cases: list[CompletionQualityCase],
    *,
    thresholds: CompletionQualityThresholds,
    semantic_scorer: SemanticScorer | None,
) -> list[dict[str, object]]:
    reports: list[dict[str, object]] = []
    for chain_id, chain_cases in _chains(cases).items():
        ordered = sorted(chain_cases, key=lambda item: item.turn)
        if len(ordered) < 2:
            continue
        rolling_prefix = ordered[0].prefix
        turns: list[dict[str, object]] = []
        chain_passed = True
        for index, case in enumerate(ordered):
            evaluated = _evaluate_case(
                observe,
                case,
                thresholds=thresholds,
                semantic_scorer=semantic_scorer,
                prefix_override=rolling_prefix,
            )
            candidates = evaluated.get("candidates") if isinstance(evaluated.get("candidates"), list) else []
            top_text = str(candidates[0].get("text") or "") if candidates and isinstance(candidates[0], dict) else ""
            next_prefix = rolling_prefix + top_text
            expected_next_prefix = ordered[index + 1].prefix if index + 1 < len(ordered) else ""
            transition_matches = not expected_next_prefix or next_prefix == expected_next_prefix
            turn_passed = bool(evaluated.get("passed")) and bool(evaluated.get("prefixMatchesTeacher")) and transition_matches
            chain_passed = chain_passed and turn_passed
            turns.append(
                {
                    "turn": case.turn,
                    "caseId": case.case_id,
                    "prefixMatchesTeacher": evaluated.get("prefixMatchesTeacher"),
                    "acceptedTop1": top_text,
                    "nextPrefix": next_prefix,
                    "expectedNextPrefix": expected_next_prefix,
                    "transitionMatchesPreferredPath": transition_matches,
                    "semanticTop1": evaluated.get("semanticTop1"),
                    "passed": turn_passed,
                }
            )
            rolling_prefix = next_prefix
        reports.append(
            {
                "chainId": chain_id,
                "turnCount": len(ordered),
                "preferredPathRollout": True,
                "passed": chain_passed,
                "turns": turns,
            }
        )
    return reports


def _quality_summary(case_reports: list[dict[str, object]], *, tab_chains: list[dict[str, object]]) -> dict[str, object]:
    count = max(1, len(case_reports))
    chain_count = max(1, len(tab_chains))
    latencies = sorted(int(item.get("latencyMs") or 0) for item in case_reports)
    margins = [
        float(candidates[0].get("lexicalReferenceMargin") or 0.0)
        for item in case_reports
        for candidates in [item.get("candidates") if isinstance(item.get("candidates"), list) else []]
        if candidates and isinstance(candidates[0], dict)
    ]
    return {
        "caseCount": len(case_reports),
        "passedCaseRate": _rate(case_reports, "passed", count),
        "semanticTop1Rate": _rate(case_reports, "semanticTop1", count),
        "semanticTop3Rate": _rate(case_reports, "semanticTop3", count),
        "semanticJudgmentCoverageRate": round(
            sum(int(item.get("semanticJudgmentCount") or 0) for item in case_reports) / max(1, len(case_reports) * 3),
            6,
        ),
        "lexicalReferenceTop1Rate": _rate(case_reports, "lexicalReferenceTop1", count),
        "lexicalReferenceTop3Rate": _rate(case_reports, "lexicalReferenceTop3", count),
        "bareCompletionRate": _rate(case_reports, "bareCompletionValid", count),
        "boundaryValidRate": _rate(case_reports, "boundaryValid", count),
        "antiEchoRate": _rate(case_reports, "antiEchoValid", count),
        "threeCandidateRate": _rate(case_reports, "threeCandidates", count),
        "hardNegativeAvoidanceRate": _rate(case_reports, "hardNegativeAvoided", count),
        "diversityRate": _rate(case_reports, "diverse", count),
        "meanReciprocalRank": round(sum(float(item.get("reciprocalRank") or 0.0) for item in case_reports) / count, 6),
        "meanLexicalReferenceMargin": round(sum(margins) / max(1, len(margins)), 6),
        "tabChainCount": len(tab_chains),
        "tabChainPassRate": round(sum(1 for item in tab_chains if item.get("passed")) / chain_count, 6),
        "p50LatencyMs": _percentile(latencies, 0.50),
        "p95LatencyMs": _percentile(latencies, 0.95),
    }


def _quality_checks(
    summary: dict[str, object],
    *,
    thresholds: CompletionQualityThresholds,
    semantic_scorer_configured: bool,
) -> list[dict[str, object]]:
    checks = (
        (
            "semantic-scorer-configured",
            "semanticScorerConfigured",
            1.0,
            ">=",
            1.0 if semantic_scorer_configured else 0.0,
        ),
        (
            "semantic-judgment-coverage",
            "semanticJudgmentCoverageRate",
            thresholds.min_semantic_judgment_coverage_rate,
            ">=",
            None,
        ),
        ("semantic-top1", "semanticTop1Rate", thresholds.min_semantic_top1_rate, ">=", None),
        ("semantic-top3", "semanticTop3Rate", thresholds.min_semantic_top3_rate, ">=", None),
        ("bare-completion", "bareCompletionRate", thresholds.min_bare_completion_rate, ">=", None),
        ("boundary-valid", "boundaryValidRate", thresholds.min_boundary_valid_rate, ">=", None),
        ("anti-echo", "antiEchoRate", thresholds.min_anti_echo_rate, ">=", None),
        ("three-candidates", "threeCandidateRate", thresholds.min_three_candidate_rate, ">=", None),
        ("hard-negative-avoidance", "hardNegativeAvoidanceRate", thresholds.min_hard_negative_avoidance_rate, ">=", None),
        ("candidate-diversity", "diversityRate", thresholds.min_diversity_rate, ">=", None),
        ("continuous-tab", "tabChainPassRate", thresholds.min_tab_chain_pass_rate, ">=", None),
        ("mean-reciprocal-rank", "meanReciprocalRank", thresholds.min_mean_reciprocal_rank, ">=", None),
        ("latency-p95", "p95LatencyMs", float(thresholds.max_p95_latency_ms), "<=", None),
    )
    return [
        {
            "name": name,
            "metric": metric,
            "actual": float(actual_override if actual_override is not None else summary.get(metric) or 0.0),
            "expected": float(expected),
            "operator": operator,
            "passed": (
                float(actual_override if actual_override is not None else summary.get(metric) or 0.0) >= float(expected)
                if operator == ">="
                else float(actual_override if actual_override is not None else summary.get(metric) or 0.0) <= float(expected)
            ),
        }
        for name, metric, expected, operator, actual_override in checks
    ]


def _case_from_payload(payload: dict[str, object], *, split: str, source: str) -> CompletionQualityCase:
    case_id = compact_whitespace(str(payload.get("id") or ""))
    prefix = str(payload.get("prefix") or "")
    completions = _strings(payload.get("completions"))
    if not case_id:
        raise ValueError(f"{source} id must not be empty")
    return CompletionQualityCase(
        case_id=case_id,
        split=split,
        chain_id=compact_whitespace(str(payload.get("chainId") or case_id)) or case_id,
        turn=max(1, int(payload.get("turn") or 1)),
        domain=compact_whitespace(str(payload.get("domain") or "unknown")) or "unknown",
        prefix=prefix,
        completions=tuple(completions),
        hard_negatives=tuple(_strings(payload.get("hardNegatives"))),
        forbidden_candidate_prefixes=tuple(_strings(payload.get("forbiddenCandidatePrefixes"))),
        forbidden_joined_fragments=tuple(_strings(payload.get("forbiddenJoinedFragments"))),
        max_candidate_chars=max(4, min(48, int(payload.get("maxCandidateChars") or 24))),
        raw_fields=frozenset(str(key) for key in payload),
    )


def _bare_completion_valid(case: CompletionQualityCase, candidate: str) -> bool:
    text = candidate.strip()
    if not text or len(text) > case.max_candidate_chars or "\n" in text or "\r" in text:
        return False
    if _ASSISTANT_STYLE_RE.search(text) or re.match(r"^\s*[1-9][.)、]", text):
        return False
    if text.startswith(("{", "[", "```")) or _SENSITIVE_RE.search(text):
        return False
    return True


def _anti_echo_valid(prefix: str, candidate: str) -> bool:
    if not candidate or candidate_has_self_repetition(candidate):
        return False
    if candidate_echoes_text(
        candidate,
        prefix,
        reject_tail=True,
        reject_single_occurrence=True,
        min_candidate_chars=2,
    ):
        return False
    candidate_norm = _quality_norm(candidate)
    prefix_norm = _quality_norm(prefix)
    if not candidate_norm or not prefix_norm:
        return False
    max_overlap = min(12, len(candidate_norm), len(prefix_norm))
    return not any(prefix_norm.endswith(candidate_norm[:size]) for size in range(4, max_overlap + 1))


def _boundary_valid(case: CompletionQualityCase, candidate: str, *, prefix: str | None = None) -> bool:
    text = compact_whitespace(candidate)
    normalized = _quality_norm(text)
    if not normalized:
        return False
    for forbidden_prefix in case.forbidden_candidate_prefixes:
        if normalized.startswith(_quality_norm(forbidden_prefix)):
            return False
    joined = _quality_norm((case.prefix if prefix is None else prefix) + text)
    for fragment in case.forbidden_joined_fragments:
        if _quality_norm(fragment) in joined:
            return False
    boundary = repeat_norm((case.prefix if prefix is None else prefix)[-4:] + text[:4])
    return re.search(r"([再先在给把要可很就让还都也并])\1", boundary) is None


def _candidate_diversity(candidates: list[str]) -> bool:
    normalized = [_quality_norm(value) for value in candidates]
    if len(normalized) != 3 or len(set(normalized)) != 3:
        return False
    return all(
        _lexical_reference_similarity(left, right) < 0.92
        for index, left in enumerate(candidates)
        for right in candidates[index + 1 :]
    )


def _lexical_reference_similarity(left: str, right: str) -> float:
    """Character-overlap diagnostic; this is intentionally not called semantic."""
    left_norm = _quality_norm(left)
    right_norm = _quality_norm(right)
    if not left_norm or not right_norm:
        return 0.0
    if left_norm == right_norm:
        return 1.0
    sequence = SequenceMatcher(None, left_norm, right_norm).ratio()
    left_grams = _char_ngrams(left_norm)
    right_grams = _char_ngrams(right_norm)
    overlap = len(left_grams & right_grams)
    gram_f1 = 0.0 if not overlap else 2.0 * overlap / (len(left_grams) + len(right_grams))
    return round(sequence * 0.65 + gram_f1 * 0.35, 6)


def _char_ngrams(text: str) -> set[str]:
    if len(text) < 2:
        return {text}
    return {text[index : index + 2] for index in range(len(text) - 1)}


def _quality_norm(value: str) -> str:
    return re.sub(r"[\s\W_]+", "", compact_whitespace(value), flags=re.UNICODE).lower()


def _chains(cases: Iterable[CompletionQualityCase]) -> dict[str, list[CompletionQualityCase]]:
    result: dict[str, list[CompletionQualityCase]] = {}
    for case in cases:
        result.setdefault(case.chain_id, []).append(case)
    return result


def _load_manifest(dataset_root: Path) -> dict[str, object]:
    payload = json.loads((dataset_root / "manifest.json").read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schemaVersion") != DATASET_SCHEMA_VERSION:
        raise ValueError("unsupported MiniMind completion dataset manifest")
    return payload


def _audit_reviewed_baselines(
    dataset_root: Path,
    *,
    manifest: dict[str, object],
    dataset_fingerprint_value: str,
    errors: list[dict[str, object]],
) -> list[dict[str, object]]:
    raw_entries = manifest.get("reviewedBaselines", [])
    if not isinstance(raw_entries, list):
        errors.append({"code": "reviewed_baselines_must_be_array"})
        return []
    reports: list[dict[str, object]] = []
    allowed_stages = {PRODUCTION_CANDIDATE_STAGE, RAW_MODEL_OUTPUT_STAGE}
    for index, entry in enumerate(raw_entries):
        if not isinstance(entry, dict):
            errors.append({"code": "reviewed_baseline_invalid", "index": index})
            continue
        stage = str(entry.get("evaluationStage") or "")
        checkpoint = str(entry.get("checkpoint") or "")
        report: dict[str, object] = {"index": index, "checkpoint": checkpoint, "evaluationStage": stage, "files": {}}
        if not checkpoint:
            errors.append({"code": "reviewed_baseline_checkpoint_missing", "index": index})
        if stage not in allowed_stages:
            errors.append({"code": "reviewed_baseline_stage_invalid", "index": index, "detail": stage})
        file_reports: dict[str, object] = {}
        for field in ("rawCapture", "captureReport", "humanJudgments", "qualityReport"):
            value = entry.get(field)
            if value is None:
                continue
            relative = str(value or "")
            path = Path(relative)
            if not relative or path.is_absolute() or ".." in path.parts:
                errors.append({"code": "reviewed_baseline_path_invalid", "index": index, "field": field})
                continue
            target = dataset_root / path
            exists = target.is_file()
            file_reports[field] = {"path": relative, "exists": exists}
            if not exists:
                errors.append(
                    {"code": "reviewed_baseline_file_missing", "index": index, "field": field, "detail": relative}
                )
                continue
            try:
                if field == "rawCapture":
                    for line_number, line in enumerate(target.read_text(encoding="utf-8").splitlines(), start=1):
                        if not line.strip():
                            continue
                        row = json.loads(line)
                        if not isinstance(row, dict) or not isinstance(row.get("prefix"), str) or not isinstance(row.get("candidates"), list):
                            raise ValueError(f"invalid row {line_number}")
                else:
                    payload = json.loads(target.read_text(encoding="utf-8"))
                    if not isinstance(payload, dict):
                        raise ValueError("not an object")
                    fingerprint = payload.get("datasetFingerprint")
                    if fingerprint is not None and fingerprint != dataset_fingerprint_value:
                        errors.append(
                            {
                                "code": "reviewed_baseline_fingerprint_mismatch",
                                "index": index,
                                "field": field,
                            }
                        )
                    payload_stage = payload.get("evaluationStage")
                    if payload_stage is not None and payload_stage != stage:
                        errors.append(
                            {"code": "reviewed_baseline_stage_mismatch", "index": index, "field": field}
                        )
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                errors.append(
                    {
                        "code": "reviewed_baseline_file_invalid",
                        "index": index,
                        "field": field,
                        "detail": type(exc).__name__,
                    }
                )
        report["files"] = file_reports
        reports.append(report)
    return reports


def _portable_dataset_path(path: str | Path) -> str:
    resolved = Path(path).expanduser().resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(resolved)


def _provider_checkpoint(provider: PredictionProvider) -> str:
    config = getattr(provider, "config", None)
    if config is None:
        delegate = getattr(provider, "delegate", None)
        config = getattr(delegate, "config", None)
    return str(getattr(config, "model", "") or provider.__class__.__name__)


def _threshold_payload(thresholds: CompletionQualityThresholds) -> dict[str, object]:
    return {
        "minSemanticTop1Rate": thresholds.min_semantic_top1_rate,
        "minSemanticTop3Rate": thresholds.min_semantic_top3_rate,
        "minSemanticJudgmentCoverageRate": thresholds.min_semantic_judgment_coverage_rate,
        "minBareCompletionRate": thresholds.min_bare_completion_rate,
        "minBoundaryValidRate": thresholds.min_boundary_valid_rate,
        "minAntiEchoRate": thresholds.min_anti_echo_rate,
        "minThreeCandidateRate": thresholds.min_three_candidate_rate,
        "minHardNegativeAvoidanceRate": thresholds.min_hard_negative_avoidance_rate,
        "minDiversityRate": thresholds.min_diversity_rate,
        "minTabChainPassRate": thresholds.min_tab_chain_pass_rate,
        "minMeanReciprocalRank": thresholds.min_mean_reciprocal_rank,
        "maxP95LatencyMs": thresholds.max_p95_latency_ms,
        "lexicalReferenceScoreFloor": thresholds.lexical_reference_score_floor,
        "lexicalReferenceMarginFloor": thresholds.lexical_reference_margin_floor,
    }


def _strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _add_issue(
    issues: list[dict[str, object]],
    code: str,
    case: CompletionQualityCase,
    *,
    detail: str = "",
) -> None:
    payload: dict[str, object] = {"code": code, "split": case.split, "caseId": case.case_id}
    if detail:
        payload["detail"] = detail
    issues.append(payload)


def _rate(rows: list[dict[str, object]], key: str, denominator: int) -> float:
    return round(sum(1 for item in rows if item.get(key)) / max(1, denominator), 6)


def _percentile(values: list[int], fraction: float) -> int:
    filtered = sorted(value for value in values if value >= 0)
    if not filtered:
        return 0
    index = max(0, min(len(filtered) - 1, int(round((len(filtered) - 1) * fraction))))
    return int(filtered[index])
