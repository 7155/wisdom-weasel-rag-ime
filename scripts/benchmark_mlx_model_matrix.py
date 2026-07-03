#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL_ROOT = REPO_ROOT.parent / "models" / "mlx"
DEFAULT_MODELS = (
    "Qwen3-0.6B-4bit",
    "Qwen3-1.7B-4bit",
)
DEFAULT_PYTHON = REPO_ROOT / ".venv-mlx314sys" / "bin" / "python"
BAD_RAW_MARKERS = ("<think>", "</think>", "\ufffd", "/no_think")
LOW_VALUE_CANDIDATES = {
    "补后端测试",
    "模型相关表达",
    "调试流程",
    "继续预测",
    "预测流程",
}


@dataclass(frozen=True)
class MatrixCase:
    case_id: str
    current_input: str
    recent_context: str
    request_type: str
    rime_candidates: tuple[str, ...] = ()

    def to_payload(self, *, max_candidates: int, max_tokens: int, temperature: float, top_p: float) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "currentInput": self.current_input,
            "recentContext": self.recent_context,
            "requestType": self.request_type,
            "maxCandidates": max_candidates,
            "maxTokens": max_tokens,
            "temperature": temperature,
            "topP": top_p,
        }
        if self.rime_candidates:
            payload["rimeCandidates"] = list(self.rime_candidates)
        return payload


DEFAULT_CASES = (
    MatrixCase(
        case_id="post-commit-rag-ime",
        current_input="",
        recent_context="我想把这个输入法流程跑通，接入本地记忆和 RAG，优化 MLX 小模型候选。",
        request_type="no_input_prediction",
    ),
    MatrixCase(
        case_id="pinyin-constrain-design",
        current_input="sj",
        recent_context="我想",
        request_type="pinyin_constrained_prediction",
        rime_candidates=("设计", "世界", "手机", "时间"),
    ),
    MatrixCase(
        case_id="rime-reorder-debug",
        current_input="diao shi",
        recent_context="现在输入法候选需要根据上下文预测，优先辅助我排查不能输入的问题。",
        request_type="rime_reorder",
        rime_candidates=("调试", "吊饰", "雕饰", "掉事"),
    ),
    MatrixCase(
        case_id="english-vibecode",
        current_input="model",
        recent_context="这个输入法主要服务 vibe coding，经常需要中英文混输和技术词。",
        request_type="pinyin_constrained_prediction",
        rime_candidates=("model", "module", "memory", "mlx"),
    ),
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="benchmark_mlx_model_matrix.py",
        description="Start temporary MLX predictor servers and compare IME candidate latency/quality.",
    )
    parser.add_argument(
        "--models",
        default=",".join(str(DEFAULT_MODEL_ROOT / name) for name in DEFAULT_MODELS),
        help="Comma-separated local MLX model directories. Defaults to Qwen3 0.6B and 1.7B under ../models/mlx.",
    )
    parser.add_argument("--python", default=os.environ.get("RAG_IME_MLX_PYTHON") or _default_python())
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--base-port", type=int, default=8781)
    parser.add_argument("--max-candidates", type=int, default=4)
    parser.add_argument("--max-tokens", type=int, default=32)
    parser.add_argument("--temperature", type=float, default=0.15)
    parser.add_argument("--top-p", type=float, default=0.85)
    parser.add_argument("--startup-timeout", type=float, default=90.0)
    parser.add_argument("--case", action="append", default=[], help="Inline case as id|requestType|currentInput|recentContext|rime1,rime2")
    parser.add_argument("--cases-file", default="", help="Optional JSONL cases file.")
    parser.add_argument("--keep-cases", action="store_true", help="Keep per-case raw summaries in output.")
    parser.add_argument("--pretty", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Print planned model/server/case matrix without loading MLX.")
    args = parser.parse_args(argv)

    models = parse_models(args.models)
    cases = load_cases(args)
    plan = {
        "schemaVersion": "rag-ime.mlx-model-matrix-plan.v1",
        "python": args.python,
        "host": args.host,
        "basePort": args.base_port,
        "models": [{"model": model, "port": args.base_port + index} for index, model in enumerate(models)],
        "caseIds": [case.case_id for case in cases],
        "maxCandidates": args.max_candidates,
        "maxTokens": args.max_tokens,
    }
    if args.dry_run:
        print_json(plan, pretty=args.pretty)
        return 0

    started_at = time.time()
    reports = []
    for index, model in enumerate(models):
        port = args.base_port + index
        reports.append(run_one_model(model=model, port=port, cases=cases, args=args))
    report = {
        "schemaVersion": "rag-ime.mlx-model-matrix.v1",
        "generatedAt": int(started_at),
        "python": args.python,
        "host": args.host,
        "maxCandidates": args.max_candidates,
        "maxTokens": args.max_tokens,
        "temperature": args.temperature,
        "topP": args.top_p,
        "models": reports,
        "winner": choose_winner(reports),
    }
    print_json(report, pretty=args.pretty)
    return 0


def _default_python() -> str:
    if DEFAULT_PYTHON.exists():
        return str(DEFAULT_PYTHON)
    return sys.executable


def parse_models(raw: str) -> list[str]:
    models: list[str] = []
    seen: set[str] = set()
    for item in (raw or "").replace("\n", ",").split(","):
        model = item.strip()
        if not model:
            continue
        if model not in seen:
            models.append(model)
            seen.add(model)
    if not models:
        raise SystemExit("at least one --models entry is required")
    return models


def load_cases(args: argparse.Namespace) -> list[MatrixCase]:
    cases: list[MatrixCase] = list(DEFAULT_CASES)
    if args.cases_file:
        cases = []
        path = Path(args.cases_file)
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            obj = json.loads(line)
            if not isinstance(obj, dict):
                raise SystemExit(f"{path}:{line_number}: case must be a JSON object")
            cases.append(
                MatrixCase(
                    case_id=str(obj.get("id") or obj.get("caseId") or f"case-{line_number}"),
                    current_input=str(obj.get("currentInput") or obj.get("current_input") or ""),
                    recent_context=str(obj.get("recentContext") or obj.get("recent_context") or ""),
                    request_type=str(obj.get("requestType") or obj.get("request_type") or "generic"),
                    rime_candidates=tuple(str(item) for item in obj.get("rimeCandidates", []) if str(item).strip()),
                )
            )
    for raw_case in args.case:
        cases.append(parse_inline_case(raw_case))
    if not cases:
        raise SystemExit("no benchmark cases configured")
    return cases


def parse_inline_case(raw: str) -> MatrixCase:
    parts = raw.split("|", 4)
    if len(parts) < 4:
        raise SystemExit("--case must be id|requestType|currentInput|recentContext|rime1,rime2")
    case_id, request_type, current_input, recent_context = (part.strip() for part in parts[:4])
    rime_candidates: tuple[str, ...] = ()
    if len(parts) == 5 and parts[4].strip():
        rime_candidates = tuple(item.strip() for item in parts[4].split(",") if item.strip())
    return MatrixCase(
        case_id=case_id or f"inline-{int(time.time())}",
        current_input=current_input,
        recent_context=recent_context,
        request_type=request_type or "generic",
        rime_candidates=rime_candidates,
    )


def run_one_model(*, model: str, port: int, cases: list[MatrixCase], args: argparse.Namespace) -> dict[str, Any]:
    if not Path(model).expanduser().exists():
        return {
            "model": model,
            "port": port,
            "ok": False,
            "error": "model_path_not_found",
        }
    if not _port_available(args.host, port):
        return {
            "model": model,
            "port": port,
            "ok": False,
            "error": "port_unavailable",
        }

    process = start_server(model=model, port=port, args=args)
    try:
        health = wait_health(host=args.host, port=port, timeout=args.startup_timeout, process=process)
        case_reports = [
            run_case(host=args.host, port=port, case=case, args=args)
            for case in cases
        ]
        summary = summarize_cases(case_reports)
        report: dict[str, Any] = {
            "model": model,
            "port": port,
            "ok": True,
            "health": {
                "model": health.get("model"),
                "promptMode": health.get("promptMode"),
                "capabilities": health.get("capabilities", {}),
                "modelInfo": health.get("modelInfo", {}),
                "promptCache": health.get("promptCache", {}),
            },
            "summary": summary,
        }
        if args.keep_cases:
            report["cases"] = case_reports
        return report
    except Exception as exc:  # noqa: BLE001 - CLI report should contain the failure.
        stop_process(process)
        return {
            "model": model,
            "port": port,
            "ok": False,
            "error": f"{exc.__class__.__name__}: {exc}",
            "stderrTail": read_stderr_tail(process),
        }
    finally:
        stop_process(process)


def start_server(*, model: str, port: int, args: argparse.Namespace) -> subprocess.Popen[str]:
    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")
    cmd = [
        args.python,
        "-m",
        "rag_ime.cli",
        "mlx-predictor-server",
        "--host",
        args.host,
        "--port",
        str(port),
        "--model",
        model,
        "--max-tokens",
        str(args.max_tokens),
        "--temperature",
        str(args.temperature),
        "--top-p",
        str(args.top_p),
        "--prompt-cache",
    ]
    return subprocess.Popen(
        cmd,
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )


def wait_health(*, host: str, port: int, timeout: float, process: subprocess.Popen[str]) -> dict[str, Any]:
    deadline = time.time() + timeout
    last_error: Exception | None = None
    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"server exited before health check: {read_stderr_tail(process)}")
        try:
            return http_json("GET", f"http://{host}:{port}/health")
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            last_error = exc
            time.sleep(0.4)
    raise TimeoutError(f"server did not become healthy on port {port}: {last_error}")


def run_case(*, host: str, port: int, case: MatrixCase, args: argparse.Namespace) -> dict[str, Any]:
    started = time.perf_counter()
    payload = case.to_payload(
        max_candidates=args.max_candidates,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
        top_p=args.top_p,
    )
    response = http_json("POST", f"http://{host}:{port}/predict", payload=payload)
    wall_ms = int((time.perf_counter() - started) * 1000)
    candidates = [str(item) for item in response.get("candidates", []) if str(item).strip()]
    raw_text = str(response.get("rawText") or "")
    return {
        "caseId": case.case_id,
        "requestType": case.request_type,
        "currentInput": case.current_input,
        "candidateMode": response.get("candidateMode"),
        "totalMs": response.get("totalMs", wall_ms),
        "wallMs": wall_ms,
        "candidateCount": len(candidates),
        "rawPreview": raw_text[:240],
        "badRawMarkers": [marker for marker in BAD_RAW_MARKERS if marker in raw_text],
        "lowValueCandidates": [item for item in candidates if item in LOW_VALUE_CANDIDATES],
        "candidates": candidates,
        "timing": response.get("timing", {}),
        "promptCache": response.get("promptCache", {}),
    }


def summarize_cases(cases: list[dict[str, Any]]) -> dict[str, Any]:
    latencies = [int(item["totalMs"]) for item in cases if isinstance(item.get("totalMs"), int)]
    candidate_counts = [int(item["candidateCount"]) for item in cases]
    bad_marker_count = sum(len(item.get("badRawMarkers", [])) for item in cases)
    low_value_count = sum(len(item.get("lowValueCandidates", [])) for item in cases)
    return {
        "caseCount": len(cases),
        "totalCandidates": sum(candidate_counts),
        "emptyCases": sum(1 for count in candidate_counts if count == 0),
        "badRawMarkerCount": bad_marker_count,
        "lowValueCandidateCount": low_value_count,
        "p50TotalMs": percentile(latencies, 0.50),
        "p95TotalMs": percentile(latencies, 0.95),
        "maxTotalMs": max(latencies) if latencies else 0,
        "candidateModes": sorted({str(item.get("candidateMode") or "") for item in cases if item.get("candidateMode")}),
        "qualityScore": quality_score(cases),
    }


def quality_score(cases: list[dict[str, Any]]) -> int:
    score = 100
    for item in cases:
        if int(item.get("candidateCount") or 0) == 0:
            score -= 25
        score -= 15 * len(item.get("badRawMarkers", []))
        score -= 8 * len(item.get("lowValueCandidates", []))
    return max(0, min(100, score))


def choose_winner(reports: list[dict[str, Any]]) -> dict[str, Any]:
    ok_reports = [item for item in reports if item.get("ok") and isinstance(item.get("summary"), dict)]
    if not ok_reports:
        return {"model": "", "reason": "no_successful_model"}
    ranked = sorted(
        ok_reports,
        key=lambda item: (
            -int(item["summary"].get("qualityScore") or 0),
            int(item["summary"].get("p50TotalMs") or 0),
            int(item["summary"].get("lowValueCandidateCount") or 0),
        ),
    )
    best = ranked[0]
    return {
        "model": best["model"],
        "qualityScore": best["summary"].get("qualityScore"),
        "p50TotalMs": best["summary"].get("p50TotalMs"),
        "reason": "highest_quality_then_lowest_p50_latency",
    }


def percentile(values: list[int], fraction: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = int(round((len(ordered) - 1) * fraction))
    return ordered[max(0, min(len(ordered) - 1, index))]


def http_json(method: str, url: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=8) as response:
        body = response.read().decode("utf-8")
    parsed = json.loads(body)
    return parsed if isinstance(parsed, dict) else {}


def _port_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) != 0


def stop_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=4)


def read_stderr_tail(process: subprocess.Popen[str]) -> str:
    if process.stderr is None:
        return ""
    try:
        return process.stderr.read()[-4000:]
    except Exception:  # noqa: BLE001 - best-effort diagnostic for CLI report.
        return ""


def print_json(payload: dict[str, Any], *, pretty: bool) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2 if pretty else None))


if __name__ == "__main__":
    raise SystemExit(main())
