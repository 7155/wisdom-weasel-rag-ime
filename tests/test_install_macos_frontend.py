from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


class InstallMacosFrontendScriptTests(unittest.TestCase):
    def test_dry_run_reports_native_input_source_and_skips_check(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-install-macos-") as tmp:
            app = _write_fake_app(Path(tmp))
            result = subprocess.run(
                [
                    "bash",
                    str(root / "scripts" / "install_macos_frontend.sh"),
                    "--no-check",
                ],
                cwd=root,
                env={
                    **os.environ,
                    "HOME": str(Path(tmp) / "home"),
                    "RAG_IME_MACOS_APP": str(app),
                    "RAG_IME_MACOS_INSTALL_DRY_RUN": "1",
                },
                check=True,
                text=True,
                capture_output=True,
            )

        self.assertIn("dry-run: would install", result.stdout)
        self.assertIn("input_source_id=dev.local.inputmethod.RagImeMac", result.stdout)
        self.assertIn("RagImeMac.app", result.stdout)

    def test_installs_app_and_user_bridge_config_under_home(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-install-macos-") as tmp:
            tmp_path = Path(tmp)
            home = tmp_path / "home"
            app = _write_fake_app(tmp_path)
            result = subprocess.run(
                [
                    "bash",
                    str(root / "scripts" / "install_macos_frontend.sh"),
                    "--no-check",
                ],
                cwd=root,
                env={
                    **os.environ,
                    "HOME": str(home),
                    "RAG_IME_MACOS_APP": str(app),
                },
                check=True,
                text=True,
                capture_output=True,
            )
            target_app = home / "Library" / "Input Methods" / "RagImeMac.app"
            user_config = home / "Library" / "Application Support" / "RagImeMac" / "bridge-config.json"

            self.assertTrue(target_app.is_dir())
            self.assertTrue(user_config.is_file())
            config = json.loads(user_config.read_text(encoding="utf-8"))

        self.assertIn(str(target_app), result.stdout)
        self.assertIn(str(user_config), result.stdout)
        self.assertEqual(config["project"], "wisdom-weasel-rag-ime")
        self.assertEqual(config["sidecarBaseUrl"], "http://127.0.0.1:8766")

    def test_install_updates_existing_bundle_without_removing_input_source_path_by_default(self) -> None:
        root = Path(__file__).resolve().parents[1]
        source = (root / "scripts" / "install_macos_frontend.sh").read_text(encoding="utf-8")

        self.assertIn("/usr/bin/ditto \"$APP_DIR\" \"$TARGET_APP\"", source)
        self.assertIn("CLEAN_INSTALL", source)
        self.assertIn("rm -rf \"$TARGET_APP\"", source)


def _write_fake_app(tmp_path: Path) -> Path:
    app = tmp_path / "RagImeMac.app"
    resources = app / "Contents" / "Resources"
    resources.mkdir(parents=True)
    (resources / "bridge-config.json").write_text(
        json.dumps(
            {
                "repoRoot": str(tmp_path),
                "dbPath": str(tmp_path / "rag-ime.sqlite"),
                "pythonExecutable": "/usr/bin/python3",
                "project": "wisdom-weasel-rag-ime",
                "sidecarBaseUrl": "http://127.0.0.1:8766",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return app


if __name__ == "__main__":
    unittest.main()
