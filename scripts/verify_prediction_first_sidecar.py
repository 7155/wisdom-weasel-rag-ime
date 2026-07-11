#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from typing import Any


LOW_VALUE = {"根据", "基于", "和", "测试", "分析", "假设", "或者", "生成", "现在", "目前", "当前", "然后"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify live Prediction-first RAG-IME sidecar behavior.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8766")
    parser.add_argument("--latency-budget-ms", type=int, default=350)
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    cases = [
        prediction_first_payload(args.latency_budget_ms),
        post_commit_payload(args.latency_budget_ms),
        weak_context_payload(args.latency_budget_ms),
        raw_command_payload(args.latency_budget_ms),
        raw_code_identifier_payload(args.latency_budget_ms),
        raw_path_payload(args.latency_budget_ms),
        rime_fallback_payload(args.latency_budget_ms),
    ]
    report: dict[str, Any] = {
        "schemaVersion": "rag-ime.prediction-first-sidecar-verify.v1",
        "baseUrl": base_url,
        "latencyBudgetMs": args.latency_budget_ms,
        "cases": [],
    }
    failures: list[str] = []
    for case in cases:
        started = time.perf_counter()
        try:
            response = post_json(f"{base_url}/rime-suggest", case["payload"])
            response = retry_post_commit_model_if_needed(
                base_url=base_url,
                case=case,
                response=response,
                latency_budget_ms=args.latency_budget_ms,
            )
        except Exception as exc:
            failures.append(f"{case['caseId']}: request failed: {exc}")
            report["cases"].append({"caseId": case["caseId"], "ok": False, "error": str(exc)})
            continue
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        case_report, case_failures = check_case(case, response, elapsed_ms=elapsed_ms)
        report["cases"].append(case_report)
        failures.extend(case_failures)

    report["ok"] = not failures
    report["failures"] = failures
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


def post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=10) as response:
        parsed = json.loads(response.read().decode("utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("sidecar response must be a JSON object")
    return parsed


def retry_post_commit_model_if_needed(
    *,
    base_url: str,
    case: dict[str, Any],
    response: dict[str, Any],
    latency_budget_ms: int,
) -> dict[str, Any]:
    if case.get("caseId") != "post-commit-model-memory-panel":
        return response
    if _has_model_candidate(response):
        return response
    model_lane = response.get("modelLane") if isinstance(response.get("modelLane"), dict) else {}
    skipped_reason = str(model_lane.get("skippedReason") or "")
    if skipped_reason not in {"model lane already running", "model lane exceeded latency budget"}:
        return response
    payload = dict(case["payload"])
    payload["sessionId"] = "verify-post-commit-model-retry"
    payload["requestSeq"] = int(payload.get("requestSeq") or 1) + 100
    payload["latencyBudgetMs"] = max(latency_budget_ms, 2000)
    for attempt in range(2):
        time.sleep(0.18 * (attempt + 1))
        retry_payload = dict(payload)
        retry_payload["requestSeq"] = int(payload["requestSeq"]) + attempt
        retried = post_json(f"{base_url}/rime-suggest", retry_payload)
        if _has_model_candidate(retried):
            retried["verifyRetry"] = {
                "reason": skipped_reason,
                "attempt": attempt + 1,
                "latencyBudgetMs": retry_payload["latencyBudgetMs"],
            }
            return retried
    response["verifyRetry"] = {
        "reason": skipped_reason,
        "attempt": 2,
        "latencyBudgetMs": payload["latencyBudgetMs"],
        "modelStillMissing": True,
    }
    return response


def _has_model_candidate(response: dict[str, Any]) -> bool:
    display = response.get("displayCandidates")
    if isinstance(display, list) and any(isinstance(item, dict) and item.get("sourceType") == "model" for item in display):
        return True
    predictions = response.get("modelPredictions")
    return isinstance(predictions, list) and any(isinstance(item, dict) for item in predictions)


def patched_frontend_base(case_id: str, latency_budget_ms: int) -> dict[str, Any]:
    return {
        "sessionId": f"verify-{case_id}",
        "requestSeq": 1,
        "privacyDisposition": "allowed",
        "frontendBuild": "rag-ime.foreground-trace.v2",
        "schemaVersion": "rag-ime.squirrel-frontend-trace.v1",
        "forceSideCandidates": True,
        "latencyBudgetMs": latency_budget_ms,
        "maxVisibleCandidates": 8,
        "maxSideCandidates": 8,
    }


def prediction_first_payload(latency_budget_ms: int) -> dict[str, Any]:
    payload = patched_frontend_base("prediction-first", latency_budget_ms)
    payload.update(
        {
            "rawInput": "sj",
            "preedit": "sj",
            "committedContext": "我想设计一个候选展示方式，做一个预测优先的 RAG 输入法，先把输入法流程跑通，再接入本地记忆和 LLM 候选",
            "rimeContext": {
                "candidates": [
                    {"label": "1", "text": "设计", "comment": "wanxiang", "index": 0},
                    {"label": "2", "text": "时间", "comment": "wanxiang", "index": 1},
                    {"label": "3", "text": "世界", "comment": "wanxiang", "index": 2},
                    {"label": "4", "text": "手机", "comment": "wanxiang", "index": 3},
                ]
            },
        }
    )
    return {"caseId": "prediction-first-model-memory", "payload": payload}


def weak_context_payload(latency_budget_ms: int) -> dict[str, Any]:
    payload = patched_frontend_base("weak-context", latency_budget_ms)
    payload.update(
        {
            "rawInput": "ceshi",
            "preedit": "ceshi",
            "committedContext": "阿斯顿和2根根据2和1根据测试",
            "rimeContext": {
                "candidates": [
                    {"label": "1", "text": "根据", "comment": "wanxiang", "index": 0},
                    {"label": "2", "text": "基于", "comment": "wanxiang", "index": 1},
                    {"label": "3", "text": "和", "comment": "wanxiang", "index": 2},
                    {"label": "4", "text": "测试", "comment": "wanxiang", "index": 3},
                ]
            },
        }
    )
    return {"caseId": "weak-context-no-low-value-model", "payload": payload}


def post_commit_payload(latency_budget_ms: int) -> dict[str, Any]:
    payload = patched_frontend_base("post-commit", latency_budget_ms)
    payload.update(
        {
            "rawInput": "",
            "preedit": "",
            "commitTextPreview": "",
            "idleMs": 80,
            "forceSideCandidates": False,
            "committedContext": "我想设计一个候选展示方式，做一个预测优先的 RAG 输入法",
            "rimeContext": {"candidates": []},
        }
    )
    return {"caseId": "post-commit-model-memory-panel", "payload": payload}


def raw_command_payload(latency_budget_ms: int) -> dict[str, Any]:
    payload = patched_frontend_base("raw-command", latency_budget_ms)
    payload.update(
        {
            "rawInput": "git status",
            "preedit": "git status",
            "committedContext": "正在调试 Prediction-first RAG 输入法",
            "rimeContext": {"candidates": [{"label": "1", "text": "给他", "comment": "wanxiang", "index": 0}]},
        }
    )
    return {"caseId": "raw-command-keeps-english-first", "payload": payload}


def raw_code_identifier_payload(latency_budget_ms: int) -> dict[str, Any]:
    payload = patched_frontend_base("raw-code", latency_budget_ms)
    payload.update(
        {
            "rawInput": "model_prediction",
            "preedit": "model_prediction",
            "committedContext": "正在调试输入法英文和代码输入保护",
            "rimeContext": {"candidates": [{"label": "1", "text": "模型", "comment": "wanxiang", "index": 0}]},
        }
    )
    return {"caseId": "raw-code-identifier-keeps-english-first", "payload": payload}


def raw_path_payload(latency_budget_ms: int) -> dict[str, Any]:
    payload = patched_frontend_base("raw-path", latency_budget_ms)
    payload.update(
        {
            "rawInput": "/workspace/example-project",
            "preedit": "/workspace/example-project",
            "committedContext": "正在调试 Codex 项目路径输入保护",
            "rimeContext": {"candidates": [{"label": "1", "text": "路径", "comment": "wanxiang", "index": 0}]},
        }
    )
    return {"caseId": "raw-path-keeps-english-first", "payload": payload}


def rime_fallback_payload(latency_budget_ms: int) -> dict[str, Any]:
    payload = patched_frontend_base("rime-fallback", latency_budget_ms)
    payload.update(
        {
            "rawInput": "ni",
            "preedit": "ni",
            "committedContext": "",
            "forceSideCandidates": False,
            "rimeContext": {
                "candidates": [
                    {"label": "1", "text": "你", "comment": "wanxiang", "index": 0},
                    {"label": "2", "text": "呢", "comment": "wanxiang", "index": 1},
                ]
            },
        }
    )
    return {"caseId": "rime-fallback-when-no-context", "payload": payload}


def check_case(case: dict[str, Any], response: dict[str, Any], *, elapsed_ms: int) -> tuple[dict[str, Any], list[str]]:
    case_id = str(case["caseId"])
    display = response.get("displayCandidates")
    if not isinstance(display, list):
        display = []
    texts = [str(item.get("text") or "") for item in display if isinstance(item, dict)]
    source_types = [str(item.get("sourceType") or "") for item in display if isinstance(item, dict)]
    lanes = [str(item.get("displayLane") or "") for item in display if isinstance(item, dict)]
    prediction_first = response.get("predictionFirst") if isinstance(response.get("predictionFirst"), dict) else {}
    policy = prediction_first.get("policy") if isinstance(prediction_first, dict) and isinstance(prediction_first.get("policy"), dict) else {}
    report = {
        "caseId": case_id,
        "elapsedMs": elapsed_ms,
        "predictionFirst": {
            "enabled": bool(prediction_first.get("enabled")) if isinstance(prediction_first, dict) else False,
            "mode": prediction_first.get("mode") if isinstance(prediction_first, dict) else "",
            "policy": policy,
        },
        "modelLane": response.get("modelLane"),
        "ragLane": response.get("ragLane"),
        "texts": texts,
        "sourceTypes": source_types,
        "displayLanes": lanes,
    }
    failures: list[str] = []
    if case_id == "prediction-first-model-memory":
        require(prediction_first.get("enabled") is True, case_id, "prediction-first must be enabled", failures)
        prefix_matched_side = int(policy.get("prefixMatchedSideInserted") or 0)
        wanxiang_fallback_count = int(policy.get("wanxiangFallbackCount") or 0)
        if prefix_matched_side > 0:
            require(source_types and source_types[0] != "rime", case_id, "side candidate must stay before Rime", failures)
            require(
                any(source in {"model", "memory", "rag"} for source in source_types),
                case_id,
                "must show model/memory/RAG candidates",
                failures,
            )
            require("rime" not in source_types, case_id, "must not show Rime while side candidates exist", failures)
            require(wanxiang_fallback_count == 0, case_id, "wanxiang fallback count must be 0", failures)
        else:
            require(source_types and all(source == "rime" for source in source_types), case_id, "unmatched prefix must fall back to Rime", failures)
            require(wanxiang_fallback_count > 0, case_id, "unmatched prefix must report Rime fallback count", failures)
            require(policy.get("predictionPanelVisible") is False, case_id, "unmatched prefix must hide prediction panel", failures)
            require(policy.get("shouldClearPredictionPanel") is True, case_id, "unmatched prefix must clear stale prediction panel", failures)
        require(not (LOW_VALUE & set(texts)), case_id, "low-value words must be filtered", failures)
    elif case_id == "post-commit-model-memory-panel":
        require(prediction_first.get("enabled") is True, case_id, "prediction-first must be enabled", failures)
        require(prediction_first.get("mode") == "post_commit_predicting", case_id, "must enter post-commit mode", failures)
        require("model" in source_types, case_id, "must show model continuation", failures)
        require(any(source in {"memory", "rag"} for source in source_types), case_id, "must show memory/RAG continuation", failures)
        require("rime" not in source_types, case_id, "post-commit panel must not show Rime fallback", failures)
        require(int(policy.get("sideInserted") or 0) > 0, case_id, "must insert side candidates", failures)
        require(policy.get("rimeCompositionOwnedByRime") is False, case_id, "post-commit panel is not Rime composition", failures)
    elif case_id == "weak-context-no-low-value-model":
        require(prediction_first.get("enabled") is True, case_id, "prediction-first must be enabled", failures)
        require(not (LOW_VALUE & set(texts)), case_id, "weak context must not surface low-value words", failures)
        if any(source != "rime" for source in source_types):
            require("rime" not in source_types, case_id, "Rime must not mix in when side candidates exist", failures)
    elif case_id == "raw-command-keeps-english-first":
        first = display[0] if display and isinstance(display[0], dict) else {}
        require(first.get("sourceType") == "raw_english", case_id, "raw command must stay first", failures)
        require(first.get("insertText") == "git status", case_id, "raw command insert text mismatch", failures)
        require(len(display) == 1, case_id, "raw command must not mix model/RAG/Rime candidates", failures)
    elif case_id == "raw-code-identifier-keeps-english-first":
        first = display[0] if display and isinstance(display[0], dict) else {}
        require(first.get("sourceType") == "raw_english", case_id, "raw code identifier must stay first", failures)
        require(first.get("insertText") == "model_prediction", case_id, "raw code identifier insert text mismatch", failures)
        require(len(display) == 1, case_id, "raw code identifier must not mix model/RAG/Rime candidates", failures)
    elif case_id == "raw-path-keeps-english-first":
        first = display[0] if display and isinstance(display[0], dict) else {}
        require(first.get("sourceType") == "raw_english", case_id, "raw path must stay first", failures)
        require(first.get("insertText") == "/workspace/example-project", case_id, "raw path insert text mismatch", failures)
        require(len(display) == 1, case_id, "raw path must not mix model/RAG/Rime candidates", failures)
    elif case_id == "rime-fallback-when-no-context":
        require(source_types[:2] == ["rime", "rime"], case_id, "plain anchor should keep Rime fallback", failures)
    return report, failures


def require(condition: bool, case_id: str, message: str, failures: list[str]) -> None:
    if not condition:
        failures.append(f"{case_id}: {message}")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except urllib.error.URLError as exc:
        print(f"FAIL: sidecar request failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
