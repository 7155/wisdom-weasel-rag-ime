from __future__ import annotations

import json
import os
import plistlib
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
                    "RAG_IME_ALLOW_NATIVE_HARNESS_INSTALL": "1",
                },
                check=True,
                text=True,
                capture_output=True,
            )

        self.assertIn("dry-run: would install", result.stdout)
        self.assertIn("input_source_id=dev.local.inputmethod.RagImeMac.Hans", result.stdout)
        self.assertIn("RagImeMac.app", result.stdout)

    def test_native_install_is_blocked_unless_harness_mode_is_explicit(self) -> None:
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
                text=True,
                capture_output=True,
            )

        self.assertEqual(result.returncode, 2)
        self.assertIn("RagImeMac is a debug harness", result.stderr)
        self.assertIn("Rime/Squirrel candidate-layer integration", result.stderr)

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
                    "RAG_IME_ALLOW_NATIVE_HARNESS_INSTALL": "1",
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

    def test_build_writes_sidecar_base_url_into_bridge_config(self) -> None:
        root = Path(__file__).resolve().parents[1]
        source = (root / "scripts" / "build_macos_frontend.sh").read_text(encoding="utf-8")

        self.assertIn("RAG_IME_SIDECAR_URL_VALUE", source)
        self.assertIn('"sidecarBaseUrl": os.environ["RAG_IME_SIDECAR_URL_VALUE"]', source)

    def test_build_writes_rime_dict_dir_into_bridge_config(self) -> None:
        root = Path(__file__).resolve().parents[1]
        source = (root / "scripts" / "build_macos_frontend.sh").read_text(encoding="utf-8")

        self.assertIn("RAG_IME_RIME_DICT_DIR_VALUE", source)
        self.assertIn("wisdom-weasel-felix/third_party/rime_wanxiang", source)
        self.assertIn('"rimeDictDir": os.environ["RAG_IME_RIME_DICT_DIR_VALUE"]', source)

    def test_build_precompiles_rime_candidate_index_resource(self) -> None:
        root = Path(__file__).resolve().parents[1]
        source = (root / "scripts" / "build_macos_frontend.sh").read_text(encoding="utf-8")

        self.assertIn("build_rime_candidate_index.py", source)
        self.assertIn("rime-candidate-index.tsv", source)
        self.assertIn("--max-entries 35000", source)
        self.assertIn("wanxiang_english.dict.yaml", source)
        self.assertIn("--max-english-entries 0", source)
        self.assertIn('"rimeCandidateIndexPath": os.environ["RAG_IME_RIME_INDEX_PATH_VALUE"]', source)

    def test_install_updates_existing_bundle_without_removing_input_source_path_by_default(self) -> None:
        root = Path(__file__).resolve().parents[1]
        source = (root / "scripts" / "install_macos_frontend.sh").read_text(encoding="utf-8")

        self.assertIn("/usr/bin/ditto \"$APP_DIR\" \"$TARGET_APP\"", source)
        self.assertIn("CLEAN_INSTALL", source)
        self.assertIn("rm -rf \"$TARGET_APP\"", source)

    def test_system_install_uses_canonical_system_app_permissions(self) -> None:
        root = Path(__file__).resolve().parents[1]
        source = (root / "scripts" / "install_system_macos_frontend.sh").read_text(encoding="utf-8")

        self.assertIn("/Library/Input Methods", source)
        self.assertIn("RAG_IME_MACOS_PRUNE_USER_DUPLICATE", source)
        self.assertIn("RAG_IME_ALLOW_NATIVE_HARNESS_INSTALL", source)
        self.assertIn("debug harness, not the product input-method route", source)
        self.assertIn("/usr/sbin/chown -R root:wheel", source)
        self.assertIn("/bin/chmod -R u+rwX,go+rX", source)
        self.assertIn("lsregister -f -R", source)

    def test_readme_keeps_native_app_as_debug_harness_not_product_route(self) -> None:
        root = Path(__file__).resolve().parents[1]
        readme = (root / "README.md").read_text(encoding="utf-8")

        self.assertIn("macOS Rime/Squirrel candidate-layer adapter", readme)
        self.assertIn("native InputMethodKit debug harness", readme)
        self.assertIn("The product route is not the independent native `RagImeMac` app", readme)
        self.assertNotIn("The current implementation direction is the independent native `RagImeMac`", readme)

    def test_refresh_script_only_unregisters_rag_ime_app_paths(self) -> None:
        root = Path(__file__).resolve().parents[1]
        source = (root / "scripts" / "refresh_macos_input_sources.sh").read_text(encoding="utf-8")

        self.assertIn('current_path.endswith("/RagImeMac.app")', source)
        self.assertNotIn("identifier:                 {bundle_id}", source)
        self.assertIn("lsregister-before.txt", source)

    def test_native_info_plist_declares_visible_hans_input_mode_and_icon(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with (root / "macos" / "RagImeMac" / "Info.plist").open("rb") as handle:
            info = plistlib.load(handle)

        self.assertEqual(info["CFBundleIdentifier"], "dev.local.inputmethod.RagImeMac")
        self.assertEqual(info["CFBundleVersion"], "2")
        self.assertEqual(info["CFBundleIconFile"], "RagImeIcon")
        self.assertEqual(info["CFBundleIconName"], "RagImeIcon")
        self.assertIn("MacOSX", info["CFBundleSupportedPlatforms"])
        modes = info["ComponentInputModeDict"]["tsInputModeListKey"]
        self.assertIn("dev.local.inputmethod.RagImeMac.Hans", modes)
        self.assertEqual(
            modes["dev.local.inputmethod.RagImeMac.Hans"]["TISIntendedLanguage"],
            "zh-Hans",
        )
        self.assertEqual(
            info["ComponentInputModeDict"]["tsVisibleInputModeOrderedArrayKey"],
            ["dev.local.inputmethod.RagImeMac.Hans"],
        )


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
