from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class RagImeFrontendToggleScriptTests(unittest.TestCase):
    def test_toggle_disables_existing_rag_ime_frontend_key(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-frontend-toggle-") as tmp:
            config = Path(tmp) / "squirrel.custom.yaml"
            config.write_text(
                "\n".join(
                    [
                        "patch:",
                        '  "rag_ime/enabled": true',
                        '  "rag_ime/timeout_ms": 600',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(root / "scripts" / "set_rag_ime_frontend_enabled.py"),
                    "false",
                    "--config",
                    str(config),
                ],
                check=True,
                text=True,
                capture_output=True,
            )

            updated = config.read_text(encoding="utf-8")
            backups = list(Path(tmp).glob("squirrel.custom.yaml.rag-ime-toggle-*.bak"))

        self.assertIn("frontend disabled", result.stdout)
        self.assertIn('"rag_ime/enabled": false', updated)
        self.assertEqual(len(backups), 1)

    def test_disable_missing_config_is_safe_noop(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-frontend-toggle-") as tmp:
            config = Path(tmp) / "missing.custom.yaml"
            result = subprocess.run(
                [
                    sys.executable,
                    str(root / "scripts" / "set_rag_ime_frontend_enabled.py"),
                    "false",
                    "--config",
                    str(config),
                ],
                check=True,
                text=True,
                capture_output=True,
            )

        self.assertIn("already disabled", result.stdout)


if __name__ == "__main__":
    unittest.main()
