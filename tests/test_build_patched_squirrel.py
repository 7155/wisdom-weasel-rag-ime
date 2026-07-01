from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class BuildPatchedSquirrelScriptTests(unittest.TestCase):
    def test_squirrel_patch_contains_side_first_mixed_layout_hooks(self) -> None:
        root = Path(__file__).resolve().parents[1]
        patch_text = (root / "squirrel-patches" / "0001-add-rag-ime-sidecar.patch").read_text(encoding="utf-8")

        self.assertIn("fallback: 8, range: 0...10", patch_text)
        self.assertIn("let displayLayout: String?", patch_text)
        self.assertIn("let displayLane: String?", patch_text)
        self.assertIn("func candidateSeparator(before index: Int) -> String", patch_text)
        self.assertIn('currentLayout == "inline", previousLayout == "inline"', patch_text)
        self.assertIn("private var ragImePanelUsesDisplayCandidates: Bool = false", patch_text)
        self.assertIn("func ragImePanelForcesHorizontalLayout() -> Bool", patch_text)
        self.assertIn("var ragImePanelLinear: Bool", patch_text)
        self.assertIn("view.textView.setLayoutOrientation(ragImePanelVertical ? .vertical : .horizontal)", patch_text)
        self.assertIn("private let ragImeDisplayHoldoverDuration: TimeInterval = 1.2", patch_text)
        self.assertIn("func canUseRagImeDisplayHoldover(", patch_text)
        self.assertIn('ragImeDisplayQueryBasis == "committedContext"', patch_text)
        self.assertIn("committedContext: ragImeCommittedContext", patch_text)
        self.assertIn("guard response.committedContext == request.committedContext else { return }", patch_text)
        self.assertIn("guard ragImeCommittedContext == request.committedContext else { return }", patch_text)
        self.assertIn(
            "+    committedContext: String,\n"
            "+    page: Int,\n"
            "+    highlighted: Int,\n"
            "+    candidates: [RagImeRimeCandidatePayload]\n"
            "+  ) -> String {\n"
            "+    return [\n"
            "+      rawInput,\n"
            "+      preedit,\n"
            "+      commitTextPreview,\n"
            "+      committedContext,",
            patch_text,
        )
        self.assertIn(
            "+  func selectRagImeSideCandidate(forKey key: String) -> Bool {\n"
            "+    guard ragImePanelUsesDisplayCandidates else {\n"
            "+      return false\n"
            "+    }\n"
            "+    guard let index = ragImeDisplayCandidates.firstIndex(where: { ragImeSelectionKey(for: $0) == key }) else {\n"
            "+      return false\n"
            "+    }\n"
            "+    return selectCandidate(index)\n"
            "+  }",
            patch_text,
        )

    def test_build_script_dry_run_reports_resolved_commands(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-squirrel-build-") as tmp:
            workdir = Path(tmp) / "squirrel"
            result = subprocess.run(
                ["bash", str(root / "scripts" / "build_patched_squirrel.sh"), "build"],
                cwd=root,
                env={
                    **os.environ,
                    "RAG_IME_SQUIRREL_BUILD_DRY_RUN": "1",
                    "RAG_IME_SQUIRREL_WORKDIR": str(workdir),
                    "RAG_IME_SQUIRREL_SCHEME": "SquirrelTest",
                    "RAG_IME_SQUIRREL_CONFIGURATION": "Debug",
                },
                check=True,
                text=True,
                capture_output=True,
            )
        self.assertIn(f"workdir={workdir}", result.stdout)
        self.assertIn("scheme=SquirrelTest", result.stdout)
        self.assertIn("configuration=Debug", result.stdout)
        self.assertIn("list_command=", result.stdout)
        self.assertIn("build_command=", result.stdout)
        self.assertIn("CODE_SIGNING_ALLOWED=NO build", result.stdout)

    def test_build_script_uses_xcodebuild_list_and_build(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-squirrel-build-") as tmp:
            tmp_path = Path(tmp)
            workdir = _fake_patched_squirrel_workdir(tmp_path)
            fake_bin = tmp_path / "bin"
            fake_bin.mkdir()
            fake_log = tmp_path / "xcodebuild.log"
            fake_xcodebuild = fake_bin / "xcodebuild"
            fake_xcodebuild.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env bash",
                        "printf '%s\\n' \"$*\" >> \"$FAKE_XCODEBUILD_LOG\"",
                        "if [[ \"$1\" == \"-version\" ]]; then",
                        "  echo 'Xcode 16.0'",
                        "  echo 'Build version 16A000'",
                        "  exit 0",
                        "fi",
                        "if [[ \"$1\" == \"-project\" && \"$3\" == \"-list\" ]]; then",
                        "  echo 'Targets:'",
                        "  echo '  Squirrel'",
                        "  exit 0",
                        "fi",
                        "if [[ \"$1\" == \"-project\" && \"$*\" == *' CODE_SIGNING_ALLOWED=NO build'* ]]; then",
                        "  echo 'Build succeeded'",
                        "  exit 0",
                        "fi",
                        "exit 1",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            fake_xcodebuild.chmod(0o755)

            result = subprocess.run(
                ["bash", str(root / "scripts" / "build_patched_squirrel.sh")],
                cwd=root,
                env={
                    **os.environ,
                    "PATH": f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}",
                    "FAKE_XCODEBUILD_LOG": str(fake_log),
                    "RAG_IME_SQUIRREL_WORKDIR": str(workdir),
                    "RAG_IME_SQUIRREL_DERIVED_DATA": str(tmp_path / "derived-data"),
                },
                check=True,
                text=True,
                capture_output=True,
            )

            xcodebuild_log = fake_log.read_text(encoding="utf-8")
        self.assertIn("[OK] xcodebuild can inspect patched Squirrel project", result.stdout)
        self.assertIn("[OK] xcodebuild build succeeded", result.stdout)
        self.assertIn("-list", xcodebuild_log)
        self.assertIn("-scheme Squirrel", xcodebuild_log)
        self.assertIn("CODE_SIGNING_ALLOWED=NO build", xcodebuild_log)

    def test_install_action_copies_app_and_installs_rag_config(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-squirrel-install-") as tmp:
            tmp_path = Path(tmp)
            workdir = _fake_patched_squirrel_workdir(tmp_path)
            fake_bin = tmp_path / "bin"
            fake_bin.mkdir()
            fake_xcodebuild = fake_bin / "xcodebuild"
            fake_xcodebuild.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env bash",
                        "if [[ \"$1\" == \"-version\" ]]; then",
                        "  echo 'Xcode 16.0'",
                        "  echo 'Build version 16A000'",
                        "  exit 0",
                        "fi",
                        "if [[ \"$1\" == \"-project\" && \"$3\" == \"-list\" ]]; then",
                        "  echo 'Targets:'",
                        "  echo '  Squirrel'",
                        "  exit 0",
                        "fi",
                        "derived=''",
                        "previous=''",
                        "for arg in \"$@\"; do",
                        "  if [[ \"$previous\" == \"-derivedDataPath\" ]]; then derived=\"$arg\"; fi",
                        "  previous=\"$arg\"",
                        "done",
                        "if [[ \"$*\" == *' CODE_SIGNING_ALLOWED=NO build'* ]]; then",
                        "  mkdir -p \"$derived/Build/Products/Release/Squirrel.app/Contents/MacOS\"",
                        "  mkdir -p \"$derived/Build/Products/Release/Squirrel.app/Contents/SharedSupport\"",
                        "  printf 'schema_list:\\n  - schema: luna_pinyin\\n' > \"$derived/Build/Products/Release/Squirrel.app/Contents/SharedSupport/default.yaml\"",
                        "  printf 'schema:\\n  schema_id: luna_pinyin\\n' > \"$derived/Build/Products/Release/Squirrel.app/Contents/SharedSupport/luna_pinyin.schema.yaml\"",
                        "  printf -- '---\\nname: luna_pinyin\\n...\\n' > \"$derived/Build/Products/Release/Squirrel.app/Contents/SharedSupport/luna_pinyin.dict.yaml\"",
                        "  cat > \"$derived/Build/Products/Release/Squirrel.app/Contents/MacOS/Squirrel\" <<'SH'",
                        "#!/usr/bin/env bash",
                        "set -euo pipefail",
                        "if [[ \"${1:-}\" == \"--build\" ]]; then",
                        "  mkdir -p build",
                        "  printf 'default\\n' > build/default.yaml",
                        "  printf 'schema\\n' > build/luna_pinyin.schema.yaml",
                        "  printf 'table\\n' > build/luna_pinyin.table.bin",
                        "  exit 0",
                        "fi",
                        "if [[ \"${1:-}\" == \"--reload\" ]]; then exit 0; fi",
                        "exit 0",
                        "SH",
                        "  chmod +x \"$derived/Build/Products/Release/Squirrel.app/Contents/MacOS/Squirrel\"",
                        "  exit 0",
                        "fi",
                        "exit 1",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            fake_xcodebuild.chmod(0o755)
            install_dir = tmp_path / "Input Methods"
            rime_dir = tmp_path / "Rime"
            result = subprocess.run(
                ["bash", str(root / "scripts" / "build_patched_squirrel.sh"), "install"],
                cwd=root,
                env={
                    **os.environ,
                    "PATH": f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}",
                    "RAG_IME_SQUIRREL_WORKDIR": str(workdir),
                    "RAG_IME_SQUIRREL_DERIVED_DATA": str(tmp_path / "derived-data"),
                    "RAG_IME_SQUIRREL_INSTALL_DIR": str(install_dir),
                    "RAG_IME_RIME_USER_DIR": str(rime_dir),
                    "RAG_IME_SQUIRREL_SKIP_CODESIGN": "1",
                    "RAG_IME_SQUIRREL_SKIP_POSTINSTALL": "1",
                },
                check=True,
                text=True,
                capture_output=True,
            )

            self.assertIn("[OK] installed patched Squirrel.app", result.stdout)
            self.assertTrue((install_dir / "Squirrel.app" / "Contents" / "MacOS" / "Squirrel").is_file())
            config = (rime_dir / "squirrel.custom.yaml").read_text(encoding="utf-8")
            self.assertIn('"rag_ime/enabled": true', config)
            self.assertIn('"rag_ime/sidecar_url": "http://127.0.0.1:19866/api"', config)
            self.assertTrue((rime_dir / "build" / "luna_pinyin.table.bin").is_file())

    def test_build_script_fails_clearly_when_workdir_is_missing(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-squirrel-build-") as tmp:
            result = subprocess.run(
                ["bash", str(root / "scripts" / "build_patched_squirrel.sh")],
                cwd=root,
                env={
                    **os.environ,
                    "RAG_IME_XCODEBUILD": sys.executable,
                    "RAG_IME_SQUIRREL_WORKDIR": str(Path(tmp) / "missing-squirrel"),
                },
                text=True,
                capture_output=True,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Squirrel workdir not prepared", result.stderr)
        self.assertIn("Run scripts/prepare_squirrel_workspace.sh first", result.stderr)


def _fake_patched_squirrel_workdir(tmp_path: Path) -> Path:
    workdir = tmp_path / "squirrel"
    workdir.mkdir()
    subprocess.run(["git", "init"], cwd=workdir, check=True, capture_output=True, text=True)
    (workdir / "sources").mkdir()
    (workdir / "sources" / "RagImeSidecarModels.swift").write_text("// models\n", encoding="utf-8")
    (workdir / "sources" / "RagImeSidecarClient.swift").write_text("// client\n", encoding="utf-8")
    (workdir / "sources" / "SquirrelInputController.swift").write_text(
        "final class SquirrelInputController { func ragImePanelForcesHorizontalLayout() -> Bool { false } }\n",
        encoding="utf-8",
    )
    (workdir / "sources" / "SquirrelPanel.swift").write_text(
        "final class SquirrelPanel { var ragImePanelLinear: Bool { true }; func candidateSeparator(before index: Int) -> String { \" \" } }\n",
        encoding="utf-8",
    )
    (workdir / "Squirrel.xcodeproj").mkdir()
    (workdir / "Squirrel.xcodeproj" / "project.pbxproj").write_text("// pbxproj\n", encoding="utf-8")
    (workdir / "rag-ime.squirrel.custom.yaml").write_text(
        "\n".join(
            [
                "rag_ime:",
                "  enabled: true",
                "  sidecar_url: http://127.0.0.1:19866/api",
                "  python: /usr/bin/python3",
                f"  repo_root: {tmp_path}",
                f"  db_path: {tmp_path / 'rag-ime.sqlite'}",
                "  project: offline-test",
                "  max_visible_candidates: 8",
                "  max_side_candidates: 8",
                "  latency_budget_ms: 180",
                "  debounce_ms: 40",
                "  timeout_ms: 1200",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return workdir


if __name__ == "__main__":
    unittest.main()
