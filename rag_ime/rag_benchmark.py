from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import urlparse


DATASET_MANIFEST_SCHEMA_VERSION = "rag-ime.rag-benchmark-dataset.v1"
BENCHMARK_SYSTEMS = frozenset({"memory", "knowledge"})
BENCHMARK_SPLITS = ("train", "validation", "held_out")
METRIC_NAMESPACES = frozenset({"memory", "knowledge", "agent"})
ABLATION_LANES = ("baseline", "skill", "tuned", "agentic")
_LANE_FEATURES = {
    "baseline": {"skill": False, "offlineTuned": False, "agentic": False},
    "skill": {"skill": True, "offlineTuned": False, "agentic": False},
    "tuned": {"skill": True, "offlineTuned": True, "agentic": False},
    "agentic": {"skill": True, "offlineTuned": True, "agentic": True},
}
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_SHA256 = re.compile(r"^[a-fA-F0-9]{64}$")


def validate_dataset_manifest(value: Mapping[str, object]) -> dict[str, Any]:
    """Validate and normalize public benchmark provenance without corpus data."""

    if not isinstance(value, Mapping):
        raise ValueError("benchmark dataset manifest must be an object")
    schema_version = str(value.get("schemaVersion") or "").strip()
    if schema_version != DATASET_MANIFEST_SCHEMA_VERSION:
        raise ValueError(
            f"schemaVersion must be {DATASET_MANIFEST_SCHEMA_VERSION}"
        )
    benchmark_id = _identifier(value.get("benchmarkId"), "benchmarkId")
    system = str(value.get("system") or "").strip().lower()
    if system not in BENCHMARK_SYSTEMS:
        raise ValueError("system must be memory or knowledge")
    tool = str(value.get("tool") or "").strip().lower()
    if tool != system:
        raise ValueError(f"{system} benchmark must use the {system} Tool")
    source_url = _public_url(value.get("sourceUrl"), "sourceUrl")
    version = _text(value.get("version"), "version", maximum=200)
    source_sha256 = str(value.get("sourceSha256") or "").strip().lower()
    if not _SHA256.fullmatch(source_sha256):
        raise ValueError("sourceSha256 must be a 64-character hexadecimal digest")
    license_reference = _text(
        value.get("licenseReference"), "licenseReference", maximum=2_000
    )
    if value.get("corpusIncluded") is not False:
        raise ValueError("corpusIncluded must be false for a public-safe manifest")

    raw_splits = value.get("splits")
    if not isinstance(raw_splits, Mapping):
        raise ValueError("splits must be an object")
    if set(raw_splits) != set(BENCHMARK_SPLITS):
        raise ValueError("splits must contain only train, validation, and held_out")
    splits: dict[str, list[str]] = {}
    owners: dict[str, str] = {}
    for split_name in BENCHMARK_SPLITS:
        raw_ids = raw_splits.get(split_name)
        if not isinstance(raw_ids, list):
            raise ValueError(f"splits.{split_name} must be an array")
        identifiers = sorted(
            _identifier(item, f"splits.{split_name} item") for item in raw_ids
        )
        if len(identifiers) != len(set(identifiers)):
            raise ValueError(f"splits.{split_name} contains duplicate item IDs")
        if split_name in {"validation", "held_out"} and not identifiers:
            raise ValueError(f"splits.{split_name} must not be empty")
        for item_id in identifiers:
            owner = owners.get(item_id)
            if owner is not None:
                raise ValueError(
                    f"split leakage: item {item_id!r} appears in {owner} and {split_name}"
                )
            owners[item_id] = split_name
        splits[split_name] = identifiers

    split_hashes = {
        name: hashlib.sha256(
            json.dumps(
                identifiers,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        for name, identifiers in splits.items()
    }
    return {
        "schemaVersion": DATASET_MANIFEST_SCHEMA_VERSION,
        "benchmarkId": benchmark_id,
        "system": system,
        "tool": tool,
        "sourceUrl": source_url,
        "version": version,
        "sourceSha256": source_sha256,
        "licenseReference": license_reference,
        "corpusIncluded": False,
        "splits": splits,
        "splitCounts": {name: len(identifiers) for name, identifiers in splits.items()},
        "splitHashes": split_hashes,
    }


def compute_retrieval_metrics(
    cases: list[Mapping[str, object]],
    *,
    k_values: tuple[int, ...] = (1, 3, 5, 10),
) -> dict[str, Any]:
    """Compute macro Recall@K, MRR, and graded nDCG@K from qrels."""

    if not isinstance(cases, list) or not cases:
        raise ValueError("retrieval cases must be a non-empty array")
    normalized_k = tuple(sorted(set(k_values)))
    if not normalized_k or any(
        isinstance(value, bool) or not isinstance(value, int) or value < 1 or value > 1_000
        for value in normalized_k
    ):
        raise ValueError("k_values must contain positive integers up to 1000")

    seen_queries: set[str] = set()
    per_query: list[dict[str, Any]] = []
    for raw_case in cases:
        if not isinstance(raw_case, Mapping):
            raise ValueError("each retrieval case must be an object")
        query_id = _identifier(raw_case.get("queryId"), "queryId")
        if query_id in seen_queries:
            raise ValueError(f"duplicate queryId: {query_id}")
        seen_queries.add(query_id)
        raw_relevant = raw_case.get("relevant")
        if not isinstance(raw_relevant, Mapping) or not raw_relevant:
            raise ValueError(f"query {query_id} relevant qrels must be non-empty")
        relevant: dict[str, float] = {}
        for raw_item_id, raw_gain in raw_relevant.items():
            item_id = _identifier(raw_item_id, f"query {query_id} relevant item")
            if (
                isinstance(raw_gain, bool)
                or not isinstance(raw_gain, (int, float))
                or not math.isfinite(float(raw_gain))
                or float(raw_gain) <= 0
            ):
                raise ValueError(f"query {query_id} relevance gains must be positive")
            relevant[item_id] = float(raw_gain)
        raw_retrieved = raw_case.get("retrieved")
        if not isinstance(raw_retrieved, list):
            raise ValueError(f"query {query_id} retrieved must be an array")
        retrieved = [
            _identifier(item, f"query {query_id} retrieved item")
            for item in raw_retrieved
        ]
        if len(retrieved) != len(set(retrieved)):
            raise ValueError(f"query {query_id} contains duplicate retrieved IDs")

        first_relevant_rank = next(
            (rank for rank, item_id in enumerate(retrieved, start=1) if item_id in relevant),
            None,
        )
        recalls: dict[str, float] = {}
        ndcg: dict[str, float] = {}
        for k in normalized_k:
            top_ids = retrieved[:k]
            recalls[str(k)] = len(set(top_ids) & set(relevant)) / len(relevant)
            actual = sum(
                _discounted_gain(relevant.get(item_id, 0.0), rank)
                for rank, item_id in enumerate(top_ids, start=1)
            )
            ideal = sum(
                _discounted_gain(gain, rank)
                for rank, gain in enumerate(
                    sorted(relevant.values(), reverse=True)[:k],
                    start=1,
                )
            )
            ndcg[str(k)] = actual / ideal if ideal > 0 else 0.0
        per_query.append(
            {
                "queryId": query_id,
                "relevantCount": len(relevant),
                "retrievedCount": len(retrieved),
                "firstRelevantRank": first_relevant_rank,
                "reciprocalRank": 1.0 / first_relevant_rank if first_relevant_rank else 0.0,
                "recallAtK": recalls,
                "ndcgAtK": ndcg,
            }
        )

    denominator = len(per_query)
    return {
        "schemaVersion": "rag-ime.rag-retrieval-metrics.v1",
        "queryCount": denominator,
        "kValues": list(normalized_k),
        "metrics": {
            "recallAtK": {
                str(k): sum(item["recallAtK"][str(k)] for item in per_query)
                / denominator
                for k in normalized_k
            },
            "mrr": sum(item["reciprocalRank"] for item in per_query) / denominator,
            "ndcgAtK": {
                str(k): sum(item["ndcgAtK"][str(k)] for item in per_query)
                / denominator
                for k in normalized_k
            },
        },
        "perQuery": per_query,
    }


def select_validation_config(
    *,
    manifest: Mapping[str, object],
    validation_cases: list[Mapping[str, object]],
    candidate_configs: list[Mapping[str, object]],
    retrieve: Callable[[dict[str, object], dict[str, Any]], list[str]],
    objective: str = "ndcgAtK.10",
    k_values: tuple[int, ...] = (1, 3, 5, 10),
) -> dict[str, Any]:
    """Select and freeze a retrieval config using validation qrels only.

    The retrieval callback receives a deliberately narrow query payload. It
    never receives qrels, answer text, split labels, or held-out cases.
    """

    normalized_manifest = validate_dataset_manifest(manifest)
    if not isinstance(validation_cases, list) or not validation_cases:
        raise ValueError("validation_cases must be a non-empty array")
    normalized_k = tuple(sorted(set(k_values)))
    if not normalized_k or any(
        isinstance(value, bool) or not isinstance(value, int) or value < 1 or value > 1_000
        for value in normalized_k
    ):
        raise ValueError("k_values must contain positive integers up to 1000")
    objective_name = _validation_objective(objective, normalized_k)

    metric_cases: list[dict[str, object]] = []
    query_payloads: list[dict[str, object]] = []
    observed_ids: set[str] = set()
    for raw_case in validation_cases:
        if not isinstance(raw_case, Mapping):
            raise ValueError("validation cases must be objects")
        if str(raw_case.get("split") or "").strip() != "validation":
            raise ValueError("tuning accepts validation cases only")
        system = str(raw_case.get("system") or "").strip().lower()
        if system != normalized_manifest["system"]:
            raise ValueError("validation case system must match the dataset manifest")
        query_id = _identifier(raw_case.get("queryId"), "validation queryId")
        if query_id in observed_ids:
            raise ValueError(f"duplicate validation queryId: {query_id}")
        observed_ids.add(query_id)
        query_text = _text(
            raw_case.get("query") or raw_case.get("question"),
            f"validation query {query_id}",
            maximum=100_000,
        )
        relevant = raw_case.get("relevant")
        if not isinstance(relevant, Mapping):
            raise ValueError(f"validation query {query_id} relevant must be an object")
        slice_name = str(
            raw_case.get("slice") or raw_case.get("questionType") or "unknown"
        ).strip()[:120] or "unknown"
        metric_cases.append(
            {
                "queryId": query_id,
                "relevant": dict(relevant),
                "slice": slice_name,
            }
        )
        query_payloads.append(
            {
                "queryId": query_id,
                "system": system,
                "text": query_text,
            }
        )
    expected_ids = set(normalized_manifest["splits"]["validation"])
    if observed_ids != expected_ids:
        missing = sorted(expected_ids - observed_ids)
        unexpected = sorted(observed_ids - expected_ids)
        raise ValueError(
            "validation cases must exactly match the manifest split"
            f"; missing={missing}; unexpected={unexpected}"
        )

    if not isinstance(candidate_configs, list) or not candidate_configs:
        raise ValueError("candidate_configs must be a non-empty array")
    normalized_candidates: list[tuple[str, dict[str, Any]]] = []
    seen_config_hashes: set[str] = set()
    for index, raw_config in enumerate(candidate_configs):
        config = _json_object(raw_config, f"candidate_configs[{index}]")
        _reject_secret_fields(config, f"candidate_configs[{index}]")
        config_sha256 = _sha256_json(config)
        if config_sha256 in seen_config_hashes:
            raise ValueError("candidate_configs contains duplicate configurations")
        seen_config_hashes.add(config_sha256)
        normalized_candidates.append((config_sha256, config))
    normalized_candidates.sort(key=lambda item: item[0])

    candidate_reports: list[dict[str, Any]] = []
    winner_sort_key: tuple[float, float, float, float] | None = None
    winner: dict[str, Any] | None = None
    for config_sha256, config in normalized_candidates:
        scored_cases: list[dict[str, object]] = []
        for query_payload, metric_case in zip(
            query_payloads, metric_cases, strict=True
        ):
            retrieved = retrieve(
                json.loads(_canonical_json(query_payload)),
                json.loads(_canonical_json(config)),
            )
            scored_cases.append({**metric_case, "retrieved": retrieved})
        full_metrics = compute_retrieval_metrics(scored_cases, k_values=normalized_k)
        aggregate = {
            "queryCount": full_metrics["queryCount"],
            "kValues": full_metrics["kValues"],
            "metrics": full_metrics["metrics"],
            "perSlice": {
                slice_name: {
                    "queryCount": slice_metrics["queryCount"],
                    "metrics": slice_metrics["metrics"],
                }
                for slice_name in sorted(
                    {str(item.get("slice") or "unknown") for item in scored_cases}
                )
                for slice_metrics in [
                    compute_retrieval_metrics(
                        [
                            item
                            for item in scored_cases
                            if str(item.get("slice") or "unknown") == slice_name
                        ],
                        k_values=normalized_k,
                    )
                ]
            },
        }
        candidate_report = {
            "config": config,
            "configSha256": config_sha256,
            "validation": aggregate,
        }
        candidate_reports.append(candidate_report)
        metrics = aggregate["metrics"]
        max_k = str(normalized_k[-1])
        sort_key = (
            _objective_metric(metrics, objective_name),
            float(metrics["mrr"]),
            float(metrics["ndcgAtK"][max_k]),
            float(metrics["recallAtK"][max_k]),
        )
        if winner_sort_key is None or sort_key > winner_sort_key:
            winner_sort_key = sort_key
            winner = candidate_report
    if winner is None:
        raise ValueError("candidate selection did not produce a winner")

    report: dict[str, Any] = {
        "schemaVersion": "rag-ime.rag-validation-selection.v1",
        "benchmarkId": normalized_manifest["benchmarkId"],
        "system": normalized_manifest["system"],
        "selectionSplit": "validation",
        "validationSplitSha256": normalized_manifest["splitHashes"]["validation"],
        "validationQueryCount": len(query_payloads),
        "heldOutLabelsObserved": False,
        "objective": objective_name,
        "candidateCount": len(candidate_reports),
        "candidates": candidate_reports,
        "winner": winner,
        "frozenConfigSha256": winner["configSha256"],
    }
    report["selectionReceiptSha256"] = _sha256_json(report)
    return report


def build_ablation_report(
    *,
    metric_namespace: str,
    lanes: list[Mapping[str, object]],
    required_hard_gates: tuple[str, ...],
) -> dict[str, Any]:
    """Build a deterministic, hard-gated four-lane comparison report."""

    namespace = str(metric_namespace or "").strip().lower()
    if namespace not in METRIC_NAMESPACES:
        raise ValueError("metric_namespace must be memory, knowledge, or agent")
    if not isinstance(lanes, list) or len(lanes) != len(ABLATION_LANES):
        raise ValueError("ablation must contain exactly four lanes")
    required_gates = tuple(_identifier(name, "hard gate") for name in required_hard_gates)
    if not required_gates or len(required_gates) != len(set(required_gates)):
        raise ValueError("required_hard_gates must be unique and non-empty")

    by_name: dict[str, dict[str, Any]] = {}
    for raw_lane in lanes:
        if not isinstance(raw_lane, Mapping):
            raise ValueError("each ablation lane must be an object")
        lane_name = str(raw_lane.get("lane") or "").strip().lower()
        if lane_name not in ABLATION_LANES or lane_name in by_name:
            raise ValueError("ablation lane names must be baseline, skill, tuned, and agentic")
        features = _json_object(raw_lane.get("features"), f"{lane_name}.features")
        for key, expected in _LANE_FEATURES[lane_name].items():
            if features.get(key) is not expected:
                raise ValueError(f"{lane_name} lane has invalid {key} feature state")
        conditions = _conditions(raw_lane.get("conditions"), lane_name)
        config_sha256 = _digest(
            raw_lane.get("retrievalConfigSha256"),
            f"{lane_name}.retrievalConfigSha256",
        )
        metrics = _numeric_map(raw_lane.get("metrics"), f"{lane_name}.metrics")
        forbidden_metrics = {
            key
            for key in metrics
            if key.casefold() in {"combinedscore", "overallscore", "headlinescore"}
        }
        if forbidden_metrics:
            raise ValueError("combined headline scores are not allowed")
        costs = _numeric_map(raw_lane.get("costs"), f"{lane_name}.costs")
        hard_gates = _boolean_map(raw_lane.get("hardGates"), f"{lane_name}.hardGates")
        missing = set(required_gates) - set(hard_gates)
        if missing:
            raise ValueError(
                f"{lane_name} is missing hard gates: {', '.join(sorted(missing))}"
            )
        by_name[lane_name] = {
            "lane": lane_name,
            "features": features,
            "conditions": conditions,
            "retrievalConfigSha256": config_sha256,
            "metrics": metrics,
            "costs": costs,
            "hardGates": hard_gates,
        }

    ordered = [by_name[name] for name in ABLATION_LANES]
    condition_materials = {_canonical_json(item["conditions"]) for item in ordered}
    if len(condition_materials) != 1:
        raise ValueError(
            "all lanes must use the same model, data, permissions, and denominator"
        )
    metric_keys = {tuple(item["metrics"]) for item in ordered}
    cost_keys = {tuple(item["costs"]) for item in ordered}
    gate_keys = {tuple(item["hardGates"]) for item in ordered}
    if len(metric_keys) != 1 or len(cost_keys) != 1 or len(gate_keys) != 1:
        raise ValueError("all lanes must report identical metric, cost, and hard-gate keys")
    if ordered[0]["retrievalConfigSha256"] != ordered[1]["retrievalConfigSha256"]:
        raise ValueError("baseline and skill lanes must share the default retrieval config")
    if ordered[2]["retrievalConfigSha256"] != ordered[3]["retrievalConfigSha256"]:
        raise ValueError("tuned and agentic lanes must share the frozen retrieval config")

    failed_hard_gates = [
        f"{item['lane']}:{gate}"
        for item in ordered
        for gate, passed in item["hardGates"].items()
        if not passed
    ]
    comparison = {
        "fromLane": "baseline",
        "toLane": "agentic",
        "metrics": _delta_map(ordered[0]["metrics"], ordered[3]["metrics"]),
        "costs": _delta_map(ordered[0]["costs"], ordered[3]["costs"]),
    }
    report: dict[str, Any] = {
        "schemaVersion": "rag-ime.rag-ablation-report.v1",
        "metricNamespace": namespace,
        "conditions": ordered[0]["conditions"],
        "conditionsSha256": _sha256_json(ordered[0]["conditions"]),
        "requiredHardGates": list(required_gates),
        "failedHardGates": failed_hard_gates,
        "accepted": not failed_hard_gates,
        "lanes": ordered,
        "comparison": comparison,
    }
    report_sha256 = _sha256_json(report)
    report["reportSha256"] = report_sha256
    report["acceptanceReceipt"] = {
        "schemaVersion": "rag-ime.rag-ablation-acceptance.v1",
        "status": "accepted" if report["accepted"] else "rejected",
        "metricNamespace": namespace,
        "reportSha256": report_sha256,
        "conditionsSha256": report["conditionsSha256"],
        "frozenRetrievalConfigSha256": ordered[3]["retrievalConfigSha256"],
        "failedHardGates": failed_hard_gates,
    }
    return report


def _discounted_gain(gain: float, rank: int) -> float:
    return (2.0**gain - 1.0) / math.log2(rank + 1.0)


def _validation_objective(value: object, k_values: tuple[int, ...]) -> str:
    objective = str(value or "").strip()
    if objective == "mrr":
        return objective
    parts = objective.split(".")
    if (
        len(parts) == 2
        and parts[0] in {"recallAtK", "ndcgAtK"}
        and parts[1].isdigit()
        and int(parts[1]) in k_values
    ):
        return objective
    raise ValueError("objective must be mrr or a requested recallAtK/ndcgAtK value")


def _objective_metric(metrics: Mapping[str, object], objective: str) -> float:
    if objective == "mrr":
        return float(metrics["mrr"])
    family, k = objective.split(".", maxsplit=1)
    values = metrics[family]
    if not isinstance(values, Mapping):
        raise ValueError(f"metric family {family} is invalid")
    return float(values[k])


def _reject_secret_fields(value: object, field: str) -> None:
    if isinstance(value, Mapping):
        for raw_key, child in value.items():
            key = str(raw_key)
            compact_key = re.sub(r"[^a-z0-9]", "", key.casefold())
            if any(
                marker in compact_key
                for marker in ("apikey", "password", "secret", "credential", "accesstoken")
            ):
                raise ValueError(f"{field} must not contain credential field {key!r}")
            _reject_secret_fields(child, f"{field}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_secret_fields(child, f"{field}[{index}]")


def _conditions(value: object, lane_name: str) -> dict[str, Any]:
    conditions = _json_object(value, f"{lane_name}.conditions")
    model = str(conditions.get("model") or "").strip()
    thinking = str(conditions.get("thinking") or "").strip()
    if not model or not thinking:
        raise ValueError(f"{lane_name}.conditions must identify model and thinking")
    dataset_hash = _digest(
        conditions.get("datasetSplitSha256"),
        f"{lane_name}.conditions.datasetSplitSha256",
    )
    permission_hash = _digest(
        conditions.get("permissionSha256"),
        f"{lane_name}.conditions.permissionSha256",
    )
    denominator = conditions.get("denominator")
    if isinstance(denominator, bool) or not isinstance(denominator, int) or denominator < 1:
        raise ValueError(f"{lane_name}.conditions.denominator must be positive")
    return {
        **conditions,
        "model": model,
        "thinking": thinking,
        "datasetSplitSha256": dataset_hash,
        "permissionSha256": permission_hash,
        "denominator": denominator,
    }


def _json_object(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    try:
        normalized = json.loads(_canonical_json(dict(value)))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must contain JSON-safe values") from exc
    if not isinstance(normalized, dict):
        raise ValueError(f"{field} must be an object")
    return normalized


def _numeric_map(value: object, field: str) -> dict[str, float]:
    if not isinstance(value, Mapping) or not value:
        raise ValueError(f"{field} must be a non-empty object")
    result: dict[str, float] = {}
    for raw_name, raw_value in value.items():
        name = _identifier(raw_name, f"{field} key")
        if (
            isinstance(raw_value, bool)
            or not isinstance(raw_value, (int, float))
            or not math.isfinite(float(raw_value))
        ):
            raise ValueError(f"{field}.{name} must be a finite number")
        result[name] = float(raw_value)
    return {name: result[name] for name in sorted(result)}


def _boolean_map(value: object, field: str) -> dict[str, bool]:
    if not isinstance(value, Mapping) or not value:
        raise ValueError(f"{field} must be a non-empty object")
    result: dict[str, bool] = {}
    for raw_name, raw_value in value.items():
        name = _identifier(raw_name, f"{field} key")
        if not isinstance(raw_value, bool):
            raise ValueError(f"{field}.{name} must be a boolean")
        result[name] = raw_value
    return {name: result[name] for name in sorted(result)}


def _delta_map(
    baseline: Mapping[str, float], optimized: Mapping[str, float]
) -> dict[str, dict[str, float | None]]:
    result: dict[str, dict[str, float | None]] = {}
    for name in baseline:
        before = float(baseline[name])
        after = float(optimized[name])
        absolute = after - before
        result[name] = {
            "baseline": before,
            "optimized": after,
            "absoluteDelta": absolute,
            "relativeDelta": absolute / before if before != 0 else None,
        }
    return result


def _digest(value: object, field: str) -> str:
    text = str(value or "").strip().lower()
    if not _SHA256.fullmatch(text):
        raise ValueError(f"{field} must be a SHA-256 digest")
    return text


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _identifier(value: object, field: str) -> str:
    text = str(value or "").strip()
    if not _IDENTIFIER.fullmatch(text):
        raise ValueError(f"{field} must be a stable identifier")
    return text


def _text(value: object, field: str, *, maximum: int) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} must not be empty")
    if len(text) > maximum:
        raise ValueError(f"{field} is too long")
    return text


def _public_url(value: object, field: str) -> str:
    text = _text(value, field, maximum=2_000)
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{field} must be an http(s) URL")
    return text
