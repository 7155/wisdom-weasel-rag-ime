from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .minimind_quality_gate import DEFAULT_DATASET_ROOT, audit_completion_dataset, load_completion_dataset
from .model_registry import fingerprint_model_artifact, is_loopback_endpoint


CAPTURE_SCHEMA_VERSION = "rag-ime.minimind-raw-capture.v1"
CAPTURE_ROW_SCHEMA_VERSION = "rag-ime.minimind-raw-capture-row.v1"
REPO_ROOT = Path(__file__).resolve().parent.parent


def extract_pre_parser_branches(payload: dict[str, Any], *, max_candidates: int = 3) -> tuple[str, ...]:
    """Return decoded branch text before the production candidate parser/reranker."""

    raw_text = payload.get("rawText")
    timing = payload.get("timing")
    branches = timing.get("branches") if isinstance(timing, dict) else None
    if not isinstance(raw_text, str) or not isinstance(branches, list):
        raise ValueError("predictor response does not expose branch rawText/timing")
    raw_lines = tuple(line for line in raw_text.splitlines() if line)
    expected_count = len(branches)
    if expected_count <= 0 or len(raw_lines) != expected_count:
        raise ValueError(
            f"ambiguous raw branch response: raw lines={len(raw_lines)}, branch records={expected_count}"
        )
    return raw_lines[: max(1, int(max_candidates))]


class LoopbackMlxRawClient:
    def __init__(
        self,
        endpoint: str,
        *,
        model: str,
        max_candidates: int = 3,
        max_tokens: int = 8,
        temperature: float = 0.15,
        top_p: float = 0.85,
        timeout_s: float = 5.0,
    ) -> None:
        normalized = str(endpoint or "").strip().rstrip("/")
        if not is_loopback_endpoint(normalized):
            raise ValueError("raw capture endpoint must be an HTTP(S) loopback URL")
        parsed = urllib.parse.urlsplit(normalized)
        path = parsed.path.rstrip("/")
        if not path.endswith("/predict"):
            path = f"{path}/predict" if path else "/predict"
        self.url = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))
        health_path = path[: -len("/predict")] + "/health"
        self.health_url = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, health_path, "", ""))
        self.model = str(model or "").strip()
        if not self.model:
            raise ValueError("raw capture model must not be empty")
        self.max_candidates = max(1, min(3, int(max_candidates)))
        self.max_tokens = max(1, min(64, int(max_tokens)))
        self.temperature = max(0.0, float(temperature))
        self.top_p = max(0.0, min(1.0, float(top_p)))
        self.timeout_s = max(0.1, float(timeout_s))
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def verify_loaded_model(self, expected_model_path: str | Path) -> dict[str, object]:
        expected = Path(expected_model_path).expanduser().resolve()
        if not expected.is_dir():
            raise ValueError("expected checkpoint path must be a model directory")
        request = urllib.request.Request(self.health_url, method="GET")
        try:
            with self._opener.open(request, timeout=min(self.timeout_s, 1.0)) as response:
                payload = json.load(response)
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"raw capture health check failed: {type(exc).__name__}") from exc
        if not isinstance(payload, dict) or payload.get("ok") is not True or payload.get("modelLoaded") is not True:
            raise RuntimeError("raw capture predictor is not healthy with a loaded model")
        runtime_model = Path(str(payload.get("model") or "")).expanduser().resolve()
        if not runtime_model.is_dir():
            raise RuntimeError("raw capture predictor did not expose a readable local model path")
        expected_fingerprint = fingerprint_model_artifact(expected)
        runtime_fingerprint = fingerprint_model_artifact(runtime_model)
        if runtime_fingerprint != expected_fingerprint:
            raise RuntimeError("raw capture predictor is loaded with a different model artifact")
        return {
            "verified": True,
            "runtimeModel": str(runtime_model),
            "checkpointPath": str(expected),
            "checkpointFingerprint": expected_fingerprint,
        }

    def predict(self, prefix: str) -> dict[str, Any]:
        body = {
            "model": self.model,
            "currentInput": "",
            "recentContext": str(prefix),
            "maxCandidates": self.max_candidates,
            "maxTokens": self.max_tokens,
            "temperature": self.temperature,
            "topP": self.top_p,
            "requestType": "ime_post_commit",
            "streamFirstCandidate": False,
            "requestId": f"raw-capture-{uuid.uuid4().hex}",
        }
        request = urllib.request.Request(
            self.url,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with self._opener.open(request, timeout=self.timeout_s) as response:
                payload = json.load(response)
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"raw capture request failed: {type(exc).__name__}") from exc
        if not isinstance(payload, dict) or payload.get("ok") is False:
            raise RuntimeError("raw capture predictor returned an invalid/error response")
        return payload


def capture_raw_completion_dataset(
    predict: Callable[[str], dict[str, Any]],
    *,
    dataset_root: str | Path = DEFAULT_DATASET_ROOT,
    split: str = "test",
    max_candidates: int = 3,
    checkpoint: str = "",
) -> tuple[list[dict[str, object]], dict[str, object]]:
    audit = audit_completion_dataset(dataset_root)
    if not audit.get("ok"):
        raise ValueError("MiniMind dataset audit failed; refusing raw capture")
    dataset = load_completion_dataset(dataset_root)
    if split not in dataset:
        raise ValueError(f"unknown dataset split: {split}")

    rows_by_prefix: dict[str, dict[str, object]] = {}
    capture_order: list[str] = []

    def capture(prefix: str, reason: str) -> tuple[str, ...]:
        existing = rows_by_prefix.get(prefix)
        if existing is not None:
            reasons = existing["captureReasons"]
            if isinstance(reasons, list) and reason not in reasons:
                reasons.append(reason)
            return tuple(str(item) for item in existing["candidates"])
        started = time.perf_counter()
        payload = predict(prefix)
        wall_ms = int((time.perf_counter() - started) * 1000)
        raw_candidates = extract_pre_parser_branches(payload, max_candidates=max_candidates)
        production_candidates = payload.get("candidates") if isinstance(payload.get("candidates"), list) else []
        payload_model = str(payload.get("model") or "")
        portable_model = checkpoint or Path(payload_model).name
        row = {
            "schemaVersion": CAPTURE_ROW_SCHEMA_VERSION,
            "prefix": prefix,
            "candidates": list(raw_candidates),
            "rawResponse": str(payload.get("rawText") or ""),
            "latencyMs": max(wall_ms, int(payload.get("totalMs") or 0)),
            "provider": "local-mlx-raw-branch",
            "model": portable_model,
            "candidateMode": str(payload.get("candidateMode") or ""),
            "branchCount": len(
                payload.get("timing", {}).get("branches", [])
                if isinstance(payload.get("timing"), dict)
                and isinstance(payload.get("timing", {}).get("branches"), list)
                else []
            ),
            "productionCandidates": [str(item) for item in production_candidates],
            "captureReasons": [reason],
            "prefixSha256": "sha256:" + hashlib.sha256(prefix.encode("utf-8")).hexdigest(),
        }
        rows_by_prefix[prefix] = row
        capture_order.append(prefix)
        return raw_candidates

    cases = dataset[split]
    for case in cases:
        capture(case.prefix, f"case:{case.case_id}")

    chains: dict[str, list[Any]] = {}
    for case in cases:
        chains.setdefault(case.chain_id, []).append(case)
    chain_reports: list[dict[str, object]] = []
    for chain_id, chain_cases in sorted(chains.items()):
        ordered = sorted(chain_cases, key=lambda item: item.turn)
        if len(ordered) <= 1:
            continue
        prefix = ordered[0].prefix
        turns: list[dict[str, object]] = []
        for case in ordered:
            raw_candidates = capture(prefix, f"raw-rollout:{chain_id}:turn-{case.turn}")
            accepted = raw_candidates[0] if raw_candidates else ""
            next_prefix = prefix + accepted
            turns.append(
                {
                    "caseId": case.case_id,
                    "turn": case.turn,
                    "prefix": prefix,
                    "acceptedTop1": accepted,
                    "nextPrefix": next_prefix,
                    "teacherPrefixMatched": prefix == case.prefix,
                }
            )
            prefix = next_prefix
        chain_reports.append({"chainId": chain_id, "turnCount": len(turns), "turns": turns})

    rows = [rows_by_prefix[prefix] for prefix in capture_order]
    report = {
        "schemaVersion": CAPTURE_SCHEMA_VERSION,
        "ok": True,
        "evaluationStage": "raw_model_output",
        "rawOutputContract": "decoded seed branches from predictor rawText before candidate parsing/reranking",
        "datasetRoot": _portable_path(dataset_root),
        "datasetId": audit.get("datasetId"),
        "datasetFingerprint": audit.get("datasetFingerprint"),
        "split": split,
        "checkpoint": checkpoint,
        "rowCount": len(rows),
        "caseCount": len(cases),
        "maxCandidates": max(1, int(max_candidates)),
        "chainRollouts": chain_reports,
    }
    return rows, report


def write_raw_capture(
    rows: list[dict[str, object]],
    report: dict[str, object],
    *,
    output_path: str | Path,
    report_path: str | Path,
) -> None:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows)
    output.write_text(body, encoding="utf-8")
    report["rawOutputSha256"] = "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()
    report_output = Path(report_path)
    report_output.parent.mkdir(parents=True, exist_ok=True)
    report_output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _portable_path(path: str | Path) -> str:
    resolved = Path(path).expanduser().resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(resolved)
