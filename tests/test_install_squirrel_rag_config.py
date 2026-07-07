from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


class InstallSquirrelRagConfigScriptTests(unittest.TestCase):
    def test_config_script_preserves_existing_patch_and_replaces_managed_block(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-squirrel-config-") as tmp:
            tmp_path = Path(tmp)
            snippet = tmp_path / "rag-ime.squirrel.custom.yaml"
            config_path = tmp_path / "Rime" / "squirrel.custom.yaml"
            default_config_path = tmp_path / "Rime" / "default.custom.yaml"
            config_path.parent.mkdir()
            config_path.write_text(
                'patch:\n  "style/color_scheme": "native"\n',
                encoding="utf-8",
            )
            default_config_path.write_text(
                "patch:\n"
                "  schema_list:\n"
                "    - schema: luna_pinyin\n"
                '  "menu/page_size": 5\n',
                encoding="utf-8",
            )
            _write_snippet(snippet, sidecar_url="http://127.0.0.1:8766/api")

            subprocess.run(
                ["bash", str(root / "scripts" / "install_squirrel_rag_config.sh")],
                cwd=root,
                env={
                    **os.environ,
                    "RAG_IME_SQUIRREL_CONFIG_SNIPPET": str(snippet),
                    "RAG_IME_SQUIRREL_CUSTOM_CONFIG": str(config_path),
                },
                check=True,
                text=True,
                capture_output=True,
            )
            _write_snippet(snippet, sidecar_url="http://127.0.0.1:9999/api")
            subprocess.run(
                ["bash", str(root / "scripts" / "install_squirrel_rag_config.sh")],
                cwd=root,
                env={
                    **os.environ,
                    "RAG_IME_SQUIRREL_CONFIG_SNIPPET": str(snippet),
                    "RAG_IME_SQUIRREL_CUSTOM_CONFIG": str(config_path),
                },
                check=True,
                text=True,
                capture_output=True,
            )

            config = config_path.read_text(encoding="utf-8")
            default_config = default_config_path.read_text(encoding="utf-8")
        self.assertIn('"style/color_scheme": "native"', config)
        self.assertEqual(config.count("# >>> RAG-IME managed block"), 1)
        self.assertIn('"rag_ime/sidecar_url": "http://127.0.0.1:9999/api"', config)
        self.assertNotIn("http://127.0.0.1:8766/api", config)
        self.assertEqual(default_config.count("# >>> RAG-IME default managed block"), 1)
        self.assertIn('"menu/page_size": 8', default_config)
        self.assertIn("- schema: luna_pinyin_simp", default_config)
        self.assertNotIn('"menu/page_size": 5', default_config)


def _write_snippet(path: Path, *, sidecar_url: str) -> None:
    path.write_text(
        "\n".join(
            [
                "rag_ime:",
                "  enabled: true",
                f"  sidecar_url: {sidecar_url}",
                "  python: /usr/bin/python3",
                "  repo_root: /tmp/rag-ime",
                "  db_path: /tmp/rag-ime.sqlite",
                "  project: offline-test",
                "  max_visible_candidates: 8",
                "  max_side_candidates: 8",
                "  latency_budget_ms: 450",
                "  debounce_ms: 40",
                "  timeout_ms: 600",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    unittest.main()
