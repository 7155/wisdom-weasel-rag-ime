from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


class BootstrapSquirrelUserDataScriptTests(unittest.TestCase):
    def test_bootstrap_copies_shared_support_plum_output_and_builds_user_data(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-squirrel-bootstrap-") as tmp:
            tmp_path = Path(tmp)
            app = _fake_squirrel_app(tmp_path)
            workdir = tmp_path / "squirrel-workdir"
            plum = workdir / "plum" / "output"
            plum.mkdir(parents=True)
            (plum / "quick5.schema.yaml").write_text("schema:\n  schema_id: quick5\n", encoding="utf-8")
            (plum / "quick5.dict.yaml").write_text("---\nname: quick5\n...\n", encoding="utf-8")
            rime_dir = tmp_path / "Rime"

            result = subprocess.run(
                ["bash", str(root / "scripts" / "bootstrap_squirrel_user_data.sh")],
                cwd=root,
                env={
                    **os.environ,
                    "RAG_IME_SQUIRREL_APP": str(app),
                    "RAG_IME_SQUIRREL_WORKDIR": str(workdir),
                    "RAG_IME_RIME_USER_DIR": str(rime_dir),
                    "RAG_IME_SQUIRREL_BOOTSTRAP_BACKUP": "0",
                },
                check=True,
                text=True,
                capture_output=True,
            )

            self.assertIn("[OK] bootstrapped Squirrel user Rime data", result.stdout)
            self.assertTrue((rime_dir / "default.yaml").is_file())
            self.assertTrue((rime_dir / "luna_pinyin.schema.yaml").is_file())
            self.assertTrue((rime_dir / "quick5.schema.yaml").is_file())
            self.assertTrue((rime_dir / "build" / "default.yaml").is_file())
            self.assertTrue((rime_dir / "build" / "luna_pinyin.schema.yaml").is_file())
            self.assertTrue((rime_dir / "build" / "luna_pinyin.table.bin").is_file())

    def test_bootstrap_fails_on_squirrel_build_error_text_even_when_exit_code_is_zero(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-squirrel-bootstrap-") as tmp:
            tmp_path = Path(tmp)
            app = _fake_squirrel_app(tmp_path, build_output="missing input schema: quick5")
            rime_dir = tmp_path / "Rime"

            result = subprocess.run(
                ["bash", str(root / "scripts" / "bootstrap_squirrel_user_data.sh")],
                cwd=root,
                env={
                    **os.environ,
                    "RAG_IME_SQUIRREL_APP": str(app),
                    "RAG_IME_RIME_USER_DIR": str(rime_dir),
                    "RAG_IME_SQUIRREL_BOOTSTRAP_BACKUP": "0",
                },
                text=True,
                capture_output=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Squirrel user data build reported errors", result.stderr)
            self.assertIn("missing input schema: quick5", result.stderr)


def _fake_squirrel_app(tmp_path: Path, build_output: str = "") -> Path:
    app = tmp_path / "Squirrel.app"
    shared_support = app / "Contents" / "SharedSupport"
    shared_support.mkdir(parents=True)
    (shared_support / "default.yaml").write_text("schema_list:\n  - schema: luna_pinyin\n", encoding="utf-8")
    (shared_support / "luna_pinyin.schema.yaml").write_text("schema:\n  schema_id: luna_pinyin\n", encoding="utf-8")
    (shared_support / "luna_pinyin.dict.yaml").write_text("---\nname: luna_pinyin\n...\n", encoding="utf-8")

    executable = app / "Contents" / "MacOS" / "Squirrel"
    executable.parent.mkdir(parents=True)
    executable.write_text(
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "set -euo pipefail",
                "if [[ \"${1:-}\" == \"--build\" ]]; then",
                f"  printf '%s\\n' {build_output!r}",
                "  mkdir -p build",
                "  printf 'default\\n' > build/default.yaml",
                "  printf 'schema\\n' > build/luna_pinyin.schema.yaml",
                "  printf 'table\\n' > build/luna_pinyin.table.bin",
                "  exit 0",
                "fi",
                "if [[ \"${1:-}\" == \"--reload\" ]]; then",
                "  exit 0",
                "fi",
                "exit 0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    return app


if __name__ == "__main__":
    unittest.main()
