from __future__ import annotations

import io
import json
import os
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from rag_ime.cli import _model_matrix_winner, main


class _MatrixProductMetricsHandler(BaseHTTPRequestHandler):
    seen_models: list[str] = []

    def do_POST(self) -> None:  # noqa: N802 - stdlib API
        length = int(self.headers.get("Content-Length") or "0")
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        model = str(payload.get("model") or "")
        _MatrixProductMetricsHandler.seen_models.append(model)
        content = '["候选一号","候选二号","候选三号"]' if model == "qwen3.5:0.8b" else '["无关候选"]'
        body = json.dumps({"choices": [{"message": {"content": content}}]}, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:
        return


class ModelMatrixEvalTests(unittest.TestCase):
    def test_model_matrix_eval_alias_reports_product_metrics(self) -> None:
        _MatrixProductMetricsHandler.seen_models = []
        server = ThreadingHTTPServer(("127.0.0.1", 0), _MatrixProductMetricsHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory(prefix="rag-ime-product-matrix-") as tmp:
                cases_file = f"{tmp}/cases.jsonl"
                with open(cases_file, "w", encoding="utf-8") as handle:
                    handle.write(
                        json.dumps(
                            {
                                "id": "multi-candidate-quality",
                                "query": "RAG 输入法",
                                "recentContext": "用户刚刚写过 候选一号",
                                "expectedTerms": ["候选一号"],
                                "forbiddenTerms": ["禁止词"],
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
                stdout = io.StringIO()
                with patch.dict(os.environ, {"RAG_IME_PREDICTOR_TIMEOUT_MS": "1000"}, clear=False):
                    with redirect_stdout(stdout):
                        code = main(
                            [
                                "--db-path",
                                f"{tmp}/matrix.sqlite",
                                "model-matrix-eval",
                                "--cases-file",
                                cases_file,
                                "--base-url",
                                f"http://127.0.0.1:{server.server_port}",
                                "--models",
                                "qwen3.5:0.8b,qwen3.5:2b",
                                "--max-candidates",
                                "3",
                                "--latency-budget-ms",
                                "1000",
                            ]
                        )
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()

        report = json.loads(stdout.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(report["schemaVersion"], "rag-ime.model-matrix-eval.v1")
        self.assertEqual(_MatrixProductMetricsHandler.seen_models, ["qwen3.5:0.8b", "qwen3.5:2b"])
        good = report["models"][0]
        self.assertNotIn("cases", good)
        self.assertEqual(good["productMetrics"]["top1Acceptability"], 1.0)
        self.assertEqual(good["productMetrics"]["top3Coverage"], 1.0)
        self.assertIn("duplicateRate", good["productMetrics"])
        self.assertGreater(good["productMetrics"]["oldInputEchoRate"], 0.0)
        self.assertEqual(good["productMetrics"]["chainSuccessRate"], 1.0)
        self.assertIn("firstCandidateMs", good["productMetrics"])
        self.assertIn("threeCandidatesMs", good["productMetrics"])
        self.assertEqual(report["winner"]["model"], "qwen3.5:0.8b")
        self.assertEqual(report["winner"]["top3Coverage"], 1.0)

    def test_model_matrix_winner_penalizes_echo_noise_and_forbidden_rates(self) -> None:
        noisy = {
            "model": "echo-heavy",
            "passRate": 1.0,
            "prediction": {"hasCandidates": True},
            "metrics": {"top1Accuracy": 1.0, "meanReciprocalRank": 1.0, "noiseRate": 0.0},
            "productMetrics": {
                "top1Acceptability": 1.0,
                "top3Coverage": 1.0,
                "MRR": 1.0,
                "noiseRate": 0.1,
                "forbiddenRate": 0.1,
                "oldInputEchoRate": 0.5,
                "duplicateRate": 0.0,
                "firstCandidateMs": {"p95Ms": 10},
            },
            "latency": {"p95Ms": 10},
        }
        clean = {
            **noisy,
            "model": "clean-branching",
            "productMetrics": {
                **noisy["productMetrics"],
                "noiseRate": 0.0,
                "forbiddenRate": 0.0,
                "oldInputEchoRate": 0.0,
                "firstCandidateMs": {"p95Ms": 20},
            },
            "latency": {"p95Ms": 20},
        }

        winner = _model_matrix_winner([noisy, clean])

        self.assertEqual(winner["model"], "clean-branching")
        self.assertEqual(winner["oldInputEchoRate"], 0.0)
        self.assertEqual(winner["forbiddenRate"], 0.0)
        self.assertEqual(winner["noiseRate"], 0.0)
        self.assertEqual(winner["reason"], "highest_pass_rate_top3_top1_mrr_then_lowest_noise_echo_duplicate_latency")


if __name__ == "__main__":
    unittest.main()
