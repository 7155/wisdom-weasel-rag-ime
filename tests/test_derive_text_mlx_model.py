from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class DeriveTextMlxModelScriptTests(unittest.TestCase):
    def test_dry_run_reports_text_only_target_without_importing_mlx(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-derive-text-model-") as tmp:
            source = Path(tmp) / "source"
            target = Path(tmp) / "target"
            source.mkdir()
            (source / "model.safetensors").write_bytes(b"fake")
            (source / "tokenizer.json").write_text("{}", encoding="utf-8")
            (source / "config.json").write_text(
                json.dumps(
                    {
                        "model_type": "qwen3_5",
                        "architectures": ["Qwen3_5ForConditionalGeneration"],
                        "text_config": {
                            "model_type": "qwen3_5_text",
                            "vocab_size": 248320,
                            "hidden_size": 1024,
                            "num_hidden_layers": 24,
                        },
                        "vision_config": {"hidden_size": 768},
                        "quantization": {"bits": 4, "group_size": 64},
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(root / "scripts" / "derive_text_mlx_model.py"),
                    "--source-dir",
                    str(source),
                    "--target-dir",
                    str(target),
                    "--dry-run",
                ],
                cwd=root,
                check=True,
                text=True,
                capture_output=True,
            )

        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["dryRun"])
        self.assertIn("tokenizer.json", payload["copiedFiles"])
        self.assertFalse(payload["config"]["hasVisionConfig"])
        self.assertEqual(payload["config"]["textModelType"], "qwen3_5_text")
        self.assertEqual(payload["config"]["vocabSize"], 248320)


if __name__ == "__main__":
    unittest.main()
