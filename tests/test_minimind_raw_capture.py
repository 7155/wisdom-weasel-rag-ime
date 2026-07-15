from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

from rag_ime.minimind_quality_gate import DEFAULT_DATASET_ROOT
from rag_ime.minimind_raw_capture import (
    LoopbackMlxRawClient,
    capture_raw_completion_dataset,
    extract_pre_parser_branches,
    write_raw_capture,
)


class MiniMindRawCaptureTests(unittest.TestCase):
    def test_extract_pre_parser_branches_preserves_text_before_rerank_cleanup(self) -> None:
        payload = {
            "rawText": "面再根据坏例继续调整\n不要增加太多上下文\n实实变化",
            "candidates": ["不要增加太多上下文", "面再根据坏例继续调整", "实变化"],
            "timing": {"branches": [{}, {}, {}]},
        }

        branches = extract_pre_parser_branches(payload, max_candidates=3)

        self.assertEqual(branches[0], "面再根据坏例继续调整")
        self.assertEqual(branches[2], "实实变化")
        self.assertNotEqual(branches, tuple(payload["candidates"]))

    def test_extract_rejects_ambiguous_raw_response(self) -> None:
        with self.assertRaisesRegex(ValueError, "ambiguous raw branch"):
            extract_pre_parser_branches(
                {"rawText": "first\nsecond", "timing": {"branches": [{}, {}, {}]}},
                max_candidates=3,
            )

    def test_capture_includes_canonical_cases_and_adaptive_raw_tab_prefixes(self) -> None:
        seen: list[str] = []

        def predict(prefix: str):
            seen.append(prefix)
            suffix = f"续{len(seen)}"
            return {
                "ok": True,
                "model": "fake-minimind",
                "rawText": f"{suffix}\n备选甲\n备选乙",
                "candidates": [suffix, "备选甲", "备选乙"],
                "candidateMode": "base-completion-branches",
                "totalMs": 12,
                "timing": {"branches": [{}, {}, {}]},
            }

        rows, report = capture_raw_completion_dataset(
            predict,
            dataset_root=DEFAULT_DATASET_ROOT,
            split="test",
            checkpoint="fake-minimind",
        )

        self.assertTrue(report["ok"])
        self.assertEqual(report["evaluationStage"], "raw_model_output")
        self.assertEqual(report["datasetRoot"], "dataset/minimind_completion_v3_public")
        self.assertGreater(len(rows), report["caseCount"])
        self.assertTrue(any(not turn["teacherPrefixMatched"] for chain in report["chainRollouts"] for turn in chain["turns"][1:]))
        self.assertTrue(all(row["candidates"] for row in rows))
        self.assertTrue(all(row["model"] == "fake-minimind" for row in rows))

        with tempfile.TemporaryDirectory(prefix="raw-capture-") as tmp:
            output = Path(tmp) / "raw.jsonl"
            report_path = Path(tmp) / "report.json"
            write_raw_capture(rows, report, output_path=output, report_path=report_path)
            self.assertEqual(len(output.read_text(encoding="utf-8").splitlines()), len(rows))
            self.assertTrue(report_path.is_file())
            self.assertTrue(report["rawOutputSha256"].startswith("sha256:"))

    def test_loopback_client_verifies_loaded_artifact_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory(prefix="raw-capture-model-") as tmp:
            model = Path(tmp) / "candidate"
            model.mkdir()
            (model / "config.json").write_text("{}", encoding="utf-8")
            (model / "model.safetensors").write_bytes(b"candidate")
            client = LoopbackMlxRawClient("http://127.0.0.1:8767", model=str(model))

            class _Opener:
                def open(self, _request, timeout):
                    _ = timeout
                    return io.BytesIO(
                        json.dumps({"ok": True, "modelLoaded": True, "model": str(model)}).encode("utf-8")
                    )

            client._opener = _Opener()
            evidence = client.verify_loaded_model(model)

        self.assertTrue(evidence["verified"])
        self.assertTrue(evidence["checkpointFingerprint"].startswith("sha256:"))

    def test_loopback_client_rejects_remote_or_missing_model(self) -> None:
        with self.assertRaisesRegex(ValueError, "loopback"):
            LoopbackMlxRawClient("https://example.com", model="demo")
        with self.assertRaisesRegex(ValueError, "model"):
            LoopbackMlxRawClient("http://127.0.0.1:8767", model="")


if __name__ == "__main__":
    unittest.main()
