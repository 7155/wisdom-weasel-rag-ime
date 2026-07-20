from __future__ import annotations

import hashlib
import hmac
import json
import math
import sqlite3
from collections import defaultdict
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path

from .contracts.json_schema import validate_contract
from .db import apply_database_migrations


class KnowledgeEvalError(RuntimeError):
    pass


class KnowledgeSearchUseEvalStore:
    """Signed, stratified search-to-read-to-citation evaluation; report-only by design."""

    def __init__(self, db_path: str | Path, *, signer_secrets: Mapping[str, bytes | str] | None = None, evaluator_secrets: Mapping[str, bytes | str] | None = None) -> None:
        self.db_path = Path(db_path)
        self._signers = _secrets(signer_secrets)
        self._evaluators = _secrets(evaluator_secrets)

    def initialize(self) -> int:
        with self._connect() as conn:
            return apply_database_migrations(conn).current_version

    def sign_dataset(self, *, dataset_id: str, dataset_version: int, signer_id: str, fixtures: Sequence[Mapping[str, object]], thresholds: Mapping[str, object], created_at_ms: int, expires_at_ms: int, signer_secret: bytes | str) -> dict[str, object]:
        normalized = [_fixture(value) for value in fixtures]
        material = {"datasetId": dataset_id, "datasetVersion": dataset_version, "signerId": signer_id, "fixtures": normalized, "thresholds": _thresholds(thresholds), "createdAtMs": created_at_ms, "expiresAtMs": expires_at_ms}
        content_hash = _hash_json(material); secret = signer_secret if isinstance(signer_secret, bytes) else signer_secret.encode()
        return {**material, "contentHash": content_hash, "signerSignature": hmac.new(secret, content_hash.encode(), hashlib.sha256).hexdigest()}

    def register_dataset(self, payload: Mapping[str, object]) -> None:
        dataset = dict(payload); fixtures = [_fixture(value) for value in dataset.get("fixtures") or []]; thresholds = _thresholds(dataset.get("thresholds") or {})
        if len(fixtures) < 6 or int(dataset.get("expiresAtMs", 0)) <= int(dataset.get("createdAtMs", 0)):
            raise KnowledgeEvalError("fixture dataset is undersized or expired at creation")
        fixture_ids = [item["fixtureId"] for item in fixtures]; query_hashes = [item["queryHash"] for item in fixtures]
        if len(set(fixture_ids)) != len(fixtures) or len(set(query_hashes)) != len(fixtures):
            raise KnowledgeEvalError("fixture dataset contains duplicate fixtures or queries")
        strata = defaultdict(int)
        for item in fixtures: strata[item["stratumKind"]] += 1
        if any(strata[kind] < 2 for kind in ("owner", "room", "session")):
            raise KnowledgeEvalError("fixture dataset must stratify owner, room, and session")
        material = {"datasetId": str(dataset.get("datasetId") or ""), "datasetVersion": int(dataset.get("datasetVersion", 0)), "signerId": str(dataset.get("signerId") or ""), "fixtures": fixtures, "thresholds": thresholds, "createdAtMs": int(dataset.get("createdAtMs", 0)), "expiresAtMs": int(dataset.get("expiresAtMs", 0))}
        content_hash = _hash_json(material); secret = self._signers.get(material["signerId"])
        signature = str(dataset.get("signerSignature") or "")
        if not material["datasetId"] or material["datasetVersion"] < 1 or secret is None or content_hash != dataset.get("contentHash") or not hmac.compare_digest(signature, hmac.new(secret, content_hash.encode(), hashlib.sha256).hexdigest()):
            raise KnowledgeEvalError("fixture dataset signature/content hash is invalid")
        with self._connect(immediate=True) as conn:
            conn.execute("INSERT INTO room_v2_knowledge_eval_fixture_datasets VALUES (?,?,?,?,?,?,?,?,?,?)", (material["datasetId"], material["datasetVersion"], material["signerId"], len(fixtures), _json(fixtures), _json(thresholds), content_hash, signature, material["createdAtMs"], material["expiresAtMs"]))

    def record_eval(self, *, eval_run_id: str, dataset_id: str, room_binding_id: str | None, traces: Sequence[Mapping[str, object]], evaluator_id: str, evaluator_secret: bytes | str, created_at_ms: int) -> tuple[dict[str, object] | None, bool]:
        if not room_binding_id:
            return None, False
        configured = self._evaluators.get(evaluator_id); supplied = evaluator_secret if isinstance(evaluator_secret, bytes) else evaluator_secret.encode()
        if configured is None or not hmac.compare_digest(configured, supplied): raise KnowledgeEvalError("evaluator identity is not trusted")
        with self._connect(immediate=True) as conn:
            binding = conn.execute("SELECT 1 FROM room_v2_capability_manifests WHERE binding_id=?", (room_binding_id,)).fetchone()
            if binding is None: return None, False
            dataset = conn.execute("SELECT * FROM room_v2_knowledge_eval_fixture_datasets WHERE dataset_id=?", (dataset_id,)).fetchone()
            if dataset is None: raise KeyError(dataset_id)
            if created_at_ms > int(dataset["expires_at_ms"]): raise KnowledgeEvalError("fixture dataset evidence is expired")
            fixtures = json.loads(str(dataset["fixtures_json"])); thresholds = json.loads(str(dataset["thresholds_json"]))
            dataset_material = {"datasetId": dataset["dataset_id"], "datasetVersion": dataset["dataset_version"], "signerId": dataset["signer_id"], "fixtures": fixtures, "thresholds": thresholds, "createdAtMs": dataset["created_at_ms"], "expiresAtMs": dataset["expires_at_ms"]}
            signer_secret = self._signers.get(str(dataset["signer_id"])); expected_hash = _hash_json(dataset_material)
            if signer_secret is None or expected_hash != dataset["content_hash"] or not hmac.compare_digest(str(dataset["signer_signature"]), hmac.new(signer_secret, expected_hash.encode(), hashlib.sha256).hexdigest()): raise KnowledgeEvalError("stored fixture dataset was tampered")
            normalized_traces = [_trace(value) for value in traces]
            by_fixture = {item["fixtureId"]: item for item in normalized_traces}
            if len(by_fixture) != len(normalized_traces) or set(by_fixture) != {item["fixtureId"] for item in fixtures}:
                raise KnowledgeEvalError("eval traces are missing, duplicated, or contain unknown fixtures")
            aggregate = _Accumulator()
            strata: dict[str, _Accumulator] = defaultdict(_Accumulator)
            for fixture in fixtures:
                trace = by_fixture[fixture["fixtureId"]]
                if trace["queryHash"] != fixture["queryHash"]: raise KnowledgeEvalError("eval query hash differs from signed fixture")
                if trace["retrievalReceiptId"]:
                    receipt = conn.execute("SELECT binding_id FROM room_v2_knowledge_retrieval_receipts WHERE retrieval_receipt_id=?", (trace["retrievalReceiptId"],)).fetchone()
                    if receipt is None or str(receipt[0]) != room_binding_id: raise KnowledgeEvalError("eval retrieval receipt is missing or foreign")
                elif not fixture["expectAbstain"]:
                    raise KnowledgeEvalError("non-abstention fixture lacks retrieval receipt")
                aggregate.add(fixture, trace); strata[f"{fixture['stratumKind']}:{fixture['stratumId']}"].add(fixture, trace)
            metrics = aggregate.metrics(); strata_metrics = {key: value.metrics() for key, value in sorted(strata.items())}
            reasons = _failures(metrics, thresholds); status = "failed" if reasons else "passed"
            material = {"evalRunId": eval_run_id, "datasetId": dataset_id, "datasetContentHash": dataset["content_hash"], "roomBindingId": room_binding_id, "traceCount": len(normalized_traces), "metrics": metrics, "strataMetrics": strata_metrics, "status": status, "failureReasons": reasons, "reportOnly": True, "evaluatorId": evaluator_id, "createdAtMs": created_at_ms}
            content_hash = _hash_json(material); signature = hmac.new(configured, content_hash.encode(), hashlib.sha256).hexdigest()
            conn.execute("INSERT INTO room_v2_knowledge_search_use_eval_runs VALUES (?,?,?,?,?,?,?,?,?,1,?,?,?,?)", (eval_run_id, dataset_id, dataset["content_hash"], room_binding_id, len(normalized_traces), _json(metrics), _json(strata_metrics), status, _json(reasons), evaluator_id, content_hash, signature, created_at_ms))
        payload = {"schemaVersion": "wisdom-weasel.knowledge-search-use-eval-run.v1", **material, "contentHash": content_hash, "evaluatorSignature": signature}
        validate_contract(payload, "knowledge-search-use-eval-run.v1.json")
        return payload, True

    @contextmanager
    def _connect(self, *, immediate: bool = False):
        conn = sqlite3.connect(self.db_path); conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            if immediate: conn.execute("BEGIN IMMEDIATE")
            yield conn; conn.commit()
        except BaseException:
            conn.rollback(); raise
        finally: conn.close()


class _Accumulator:
    def __init__(self) -> None:
        self.count = self.leaks = self.retrieved = self.read_after = self.expected_retrieval = self.matched_retrieval = self.expected_read = self.matched_read = self.citation_expected = self.citation_used = 0
        self.abstention_correct = self.contradiction_expected = self.contradiction_seen = 0
        self.freshness_expected = self.freshness_passed = self.secret_expected = self.secret_quarantined = 0
        self.latencies: list[int] = []; self.bytes_read = 0; self.trace_errors = 0

    def add(self, fixture: Mapping[str, object], trace: Mapping[str, object]) -> None:
        self.count += 1; retrieved = set(trace["retrievedRefs"]); read = set(trace["readRefs"]); used = set(trace["usedCitationRefs"])
        secret_refs = set(fixture["secretRefs"])
        exposed_refs = retrieved | read | used
        forbidden = set(fixture["forbiddenRefs"]) | secret_refs
        self.leaks += len(exposed_refs & forbidden)
        if retrieved: self.retrieved += 1
        if retrieved and read: self.read_after += 1
        expected_retrieval = set(fixture["expectedRetrievalRefs"]); self.expected_retrieval += len(expected_retrieval); self.matched_retrieval += len(expected_retrieval & retrieved)
        expected_read = set(fixture["expectedReadRefs"]); self.expected_read += len(expected_read); self.matched_read += len(expected_read & read)
        expected_used = set(fixture["expectedUsedCitationRefs"]); self.citation_expected += len(expected_used); self.citation_used += len(expected_used & used)
        if not read <= retrieved or not used <= read:
            self.trace_errors += 1
        self.abstention_correct += int(bool(trace["abstained"]) == bool(fixture["expectAbstain"]))
        expected_contradictions = set(fixture["expectedContradictionRefs"]); self.contradiction_expected += len(expected_contradictions); self.contradiction_seen += len(expected_contradictions & set(trace["surfacedContradictionRefs"]))
        self.freshness_expected += int(bool(fixture["requireFreshness"])); self.freshness_passed += int(bool(fixture["requireFreshness"]) and bool(trace["freshnessPassed"]))
        self.secret_expected += len(secret_refs)
        self.secret_quarantined += len(
            secret_refs & set(trace["quarantinedSecretRefs"]) - exposed_refs
        )
        self.latencies.append(int(trace["latencyMs"])); self.bytes_read += int(trace["bytesRead"])

    def metrics(self) -> dict[str, object]:
        ordered = sorted(self.latencies); p95 = ordered[max(0, math.ceil(len(ordered) * .95) - 1)] if ordered else 0
        return {"fixtureCount": self.count, "authorizationLeakageCount": self.leaks, "expectedRetrievalRate": _ratio(self.matched_retrieval, self.expected_retrieval), "expectedReadRate": _ratio(self.matched_read, self.expected_read), "readAfterRetrievalRate": _ratio(self.read_after, self.retrieved), "usedCitationRate": _ratio(self.citation_used, self.citation_expected), "abstentionAccuracy": _ratio(self.abstention_correct, self.count), "contradictionSurfacingRate": _ratio(self.contradiction_seen, self.contradiction_expected), "freshnessPassRate": _ratio(self.freshness_passed, self.freshness_expected), "secretQuarantineRate": _ratio(self.secret_quarantined, self.secret_expected), "p95LatencyMs": p95, "totalBytes": self.bytes_read, "traceConsistencyErrors": self.trace_errors}


def _fixture(value: Mapping[str, object]) -> dict[str, object]:
    query = str(value.get("query") or "").strip(); kind = str(value.get("stratumKind") or "")
    if not query or not str(value.get("fixtureId") or "").strip() or not str(value.get("stratumId") or "").strip() or kind not in {"owner", "room", "session"}: raise KnowledgeEvalError("fixture query/stratum is invalid")
    return {"fixtureId": str(value.get("fixtureId") or ""), "query": query, "queryHash": hashlib.sha256(query.encode()).hexdigest(), "stratumKind": kind, "stratumId": str(value.get("stratumId") or ""), "expectedRetrievalRefs": _refs(value.get("expectedRetrievalRefs") or []), "expectedReadRefs": _refs(value.get("expectedReadRefs") or []), "expectedUsedCitationRefs": _refs(value.get("expectedUsedCitationRefs") or []), "forbiddenRefs": _refs(value.get("forbiddenRefs") or []), "expectAbstain": bool(value.get("expectAbstain")), "expectedContradictionRefs": _refs(value.get("expectedContradictionRefs") or []), "requireFreshness": bool(value.get("requireFreshness")), "secretRefs": _refs(value.get("secretRefs") or [])}


def _trace(value: Mapping[str, object]) -> dict[str, object]:
    return {"fixtureId": str(value.get("fixtureId") or ""), "queryHash": str(value.get("queryHash") or ""), "retrievalReceiptId": str(value.get("retrievalReceiptId") or ""), "retrievedRefs": _refs(value.get("retrievedRefs") or []), "readRefs": _refs(value.get("readRefs") or []), "usedCitationRefs": _refs(value.get("usedCitationRefs") or []), "abstained": bool(value.get("abstained")), "surfacedContradictionRefs": _refs(value.get("surfacedContradictionRefs") or []), "freshnessPassed": bool(value.get("freshnessPassed")), "quarantinedSecretRefs": _refs(value.get("quarantinedSecretRefs") or []), "latencyMs": max(0, int(value.get("latencyMs", 0))), "bytesRead": max(0, int(value.get("bytesRead", 0)))}


def _thresholds(value: Mapping[str, object]) -> dict[str, object]:
    result = {"maxAuthorizationLeakageCount": int(value.get("maxAuthorizationLeakageCount", -1)), "minExpectedRetrievalRate": float(value.get("minExpectedRetrievalRate", -1)), "minExpectedReadRate": float(value.get("minExpectedReadRate", -1)), "minReadAfterRetrievalRate": float(value.get("minReadAfterRetrievalRate", -1)), "minUsedCitationRate": float(value.get("minUsedCitationRate", -1)), "minAbstentionAccuracy": float(value.get("minAbstentionAccuracy", -1)), "minContradictionSurfacingRate": float(value.get("minContradictionSurfacingRate", -1)), "minFreshnessPassRate": float(value.get("minFreshnessPassRate", -1)), "minSecretQuarantineRate": float(value.get("minSecretQuarantineRate", -1)), "maxP95LatencyMs": int(value.get("maxP95LatencyMs", -1)), "maxTotalBytes": int(value.get("maxTotalBytes", -1))}
    if set(value) != set(result) or result["maxAuthorizationLeakageCount"] != 0 or any(not 0 <= result[key] <= 1 for key in result if key.startswith("min")) or result["maxP95LatencyMs"] < 1 or result["maxTotalBytes"] < 1: raise KnowledgeEvalError("knowledge eval thresholds are invalid")
    return result


def _failures(metrics: Mapping[str, object], thresholds: Mapping[str, object]) -> list[str]:
    checks = (("authorization_leakage", metrics["authorizationLeakageCount"] <= thresholds["maxAuthorizationLeakageCount"]), ("expected_retrieval_gap", metrics["expectedRetrievalRate"] >= thresholds["minExpectedRetrievalRate"]), ("expected_read_gap", metrics["expectedReadRate"] >= thresholds["minExpectedReadRate"]), ("retrieval_read_gap", metrics["readAfterRetrievalRate"] >= thresholds["minReadAfterRetrievalRate"]), ("citation_use_gap", metrics["usedCitationRate"] >= thresholds["minUsedCitationRate"]), ("abstention_gap", metrics["abstentionAccuracy"] >= thresholds["minAbstentionAccuracy"]), ("contradiction_gap", metrics["contradictionSurfacingRate"] >= thresholds["minContradictionSurfacingRate"]), ("freshness_gap", metrics["freshnessPassRate"] >= thresholds["minFreshnessPassRate"]), ("secret_quarantine_gap", metrics["secretQuarantineRate"] >= thresholds["minSecretQuarantineRate"]), ("latency_budget", metrics["p95LatencyMs"] <= thresholds["maxP95LatencyMs"]), ("bytes_budget", metrics["totalBytes"] <= thresholds["maxTotalBytes"]), ("trace_consistency", metrics["traceConsistencyErrors"] == 0))
    return [code for code, passed in checks if not passed]


def _ratio(value: int, total: int) -> float:
    return 1.0 if total == 0 else round(value / total, 6)


def _refs(values: Sequence[object]) -> list[str]:
    return list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))


def _secrets(values: Mapping[str, bytes | str] | None) -> dict[str, bytes]:
    return {str(key): value if isinstance(value, bytes) else str(value).encode() for key, value in (values or {}).items()}


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash_json(value: object) -> str:
    return hashlib.sha256(_json(value).encode()).hexdigest()
