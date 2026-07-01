from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class PrepareSquirrelWorkspaceScriptTests(unittest.TestCase):
    def test_prepare_squirrel_workspace_dry_run_reports_paths(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-squirrel-prepare-") as tmp:
            workdir = Path(tmp) / "squirrel"
            env = {
                **os.environ,
                "RAG_IME_SQUIRREL_DRY_RUN": "1",
                "RAG_IME_SQUIRREL_WORKDIR": str(workdir),
                "RAG_IME_SIDECAR_PORT": "18766",
            }
            result = subprocess.run(
                ["bash", str(root / "scripts" / "prepare_squirrel_workspace.sh")],
                cwd=root,
                env=env,
                check=True,
                text=True,
                capture_output=True,
            )
        self.assertIn(f"workdir={workdir}", result.stdout)
        self.assertIn("base_ref=2158538", result.stdout)
        self.assertIn("sidecar_url=http://127.0.0.1:18766/api", result.stdout)
        self.assertIn(f"repo_root={root}", result.stdout)

    def test_prepare_squirrel_workspace_applies_patch_and_writes_config_offline(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-squirrel-prepare-") as tmp:
            tmp_path = Path(tmp)
            upstream = tmp_path / "upstream-squirrel"
            workdir = tmp_path / "patched-squirrel"
            patch_file = tmp_path / "rag-ime-sidecar.patch"
            upstream.mkdir()
            (upstream / "sources").mkdir()
            subprocess.run(["git", "init"], cwd=upstream, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=upstream, check=True)
            subprocess.run(["git", "config", "user.name", "RAG IME Test"], cwd=upstream, check=True)
            (upstream / "README.md").write_text("fake squirrel\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=upstream, check=True)
            subprocess.run(["git", "commit", "-m", "base"], cwd=upstream, check=True, capture_output=True, text=True)

            (upstream / "sources" / "RagImeSidecarModels.swift").write_text(
                "import Foundation\nstruct RagImeSidecarRequest: Codable {}\n",
                encoding="utf-8",
            )
            (upstream / "sources" / "RagImeSidecarClient.swift").write_text(
                "\n".join(
                    [
                        "import Foundation",
                        "struct RagImeSidecarClient {",
                        "  init?(config: SquirrelConfig?) {}",
                        "  func call() {",
                        '    _ = "rime-suggest"',
                        '    _ = "rime-select"',
                        "  }",
                        "}",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (upstream / "sources" / "SquirrelInputController.swift").write_text(
                "\n".join(
                    [
                        "final class SquirrelInputController {",
                        "  func selectRagImeSideCandidate() {}",
                        "  func ragImeRequestFingerprint() {}",
                        "  func mergedRagImePanelCandidates() {}",
                        "}",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            subprocess.run(["git", "add", "sources"], cwd=upstream, check=True)
            patch = subprocess.run(
                ["git", "diff", "--cached", "--binary"],
                cwd=upstream,
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            patch_file.write_text(patch, encoding="utf-8")
            subprocess.run(["git", "reset", "--hard", "HEAD"], cwd=upstream, check=True, capture_output=True, text=True)

            env = {
                **os.environ,
                "RAG_IME_SQUIRREL_REPO_URL": str(upstream),
                "RAG_IME_SQUIRREL_BASE_REF": "HEAD",
                "RAG_IME_SQUIRREL_WORKDIR": str(workdir),
                "RAG_IME_SQUIRREL_PATCH": str(patch_file),
                "RAG_IME_PYTHON": sys.executable,
                "RAG_IME_DB_PATH": str(tmp_path / "rag-ime.sqlite"),
                "RAG_IME_PROJECT": "offline-test",
                "RAG_IME_SIDECAR_PORT": "19866",
            }
            result = subprocess.run(
                ["bash", str(root / "scripts" / "prepare_squirrel_workspace.sh")],
                cwd=root,
                env=env,
                check=True,
                text=True,
                capture_output=True,
            )

            self.assertIn("Prepared patched Squirrel workdir", result.stdout)
            self.assertTrue((workdir / "sources" / "RagImeSidecarModels.swift").is_file())
            self.assertTrue((workdir / "sources" / "RagImeSidecarClient.swift").is_file())
            self.assertTrue((workdir / "sources" / "SquirrelInputController.swift").is_file())
            config = (workdir / "rag-ime.squirrel.custom.yaml").read_text(encoding="utf-8")
            self.assertIn("sidecar_url: http://127.0.0.1:19866/api", config)
            self.assertIn("project: offline-test", config)


if __name__ == "__main__":
    unittest.main()
