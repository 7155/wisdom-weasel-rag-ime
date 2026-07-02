from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


class ReplaceSystemSquirrelAppScriptTests(unittest.TestCase):
    def test_replace_script_preflight_reports_stale_target_without_replacing(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-replace-squirrel-") as tmp:
            tmp_path = Path(tmp)
            source_app = _write_fake_squirrel_app(tmp_path / "User Squirrel.app", patched=True)
            target_app = _write_fake_squirrel_app(tmp_path / "System Squirrel.app", patched=False)
            fake_bin = _write_fake_system_tools(tmp_path)
            check_script = _write_logger_script(tmp_path / "check.sh", "check")
            calls_log = tmp_path / "calls.log"

            result = subprocess.run(
                ["bash", str(root / "scripts" / "replace_system_squirrel_app.sh"), "--preflight"],
                cwd=root,
                env={
                    **os.environ,
                    "PATH": f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}",
                    "RAG_IME_SQUIRREL_SOURCE_APP": str(source_app),
                    "RAG_IME_SQUIRREL_SYSTEM_APP": str(target_app),
                    "RAG_IME_CHECK_INPUT_SOURCE_SCRIPT": str(check_script),
                    "RAG_IME_TEST_CALLS_LOG": str(calls_log),
                },
                check=True,
                text=True,
                capture_output=True,
            )

            target_text = (target_app / "Contents" / "MacOS" / "Squirrel").read_text(encoding="utf-8")
            calls = calls_log.read_text(encoding="utf-8")

        self.assertIn("mode=preflight", result.stdout)
        self.assertIn("source_patch=true", result.stdout)
        self.assertIn("target_exists=true", result.stdout)
        self.assertIn("target_patch=false", result.stdout)
        self.assertIn("replacement_required=true", result.stdout)
        self.assertIn("next_command=scripts/replace_system_squirrel_app.sh", result.stdout)
        self.assertIn("check im.rime.inputmethod.Squirrel.Hans", calls)
        self.assertNotIn("rag-ime.squirrel-frontend-trace.v1", target_text)

    def test_replace_script_copies_patched_app_and_runs_post_doctor(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-replace-squirrel-") as tmp:
            tmp_path = Path(tmp)
            source_app = _write_fake_squirrel_app(tmp_path / "User Squirrel.app", patched=True)
            target_app = _write_fake_squirrel_app(tmp_path / "System Squirrel.app", patched=False)
            fake_bin = _write_fake_system_tools(tmp_path)
            select_script = _write_logger_script(tmp_path / "select.sh", "select")
            check_script = _write_logger_script(tmp_path / "check.sh", "check")
            doctor_script = _write_logger_script(tmp_path / "doctor.sh", "doctor")
            calls_log = tmp_path / "calls.log"

            result = subprocess.run(
                ["bash", str(root / "scripts" / "replace_system_squirrel_app.sh")],
                cwd=root,
                env={
                    **os.environ,
                    "PATH": f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}",
                    "RAG_IME_SQUIRREL_SOURCE_APP": str(source_app),
                    "RAG_IME_SQUIRREL_SYSTEM_APP": str(target_app),
                    "RAG_IME_SQUIRREL_BACKUP_SUFFIX": "test-backup",
                    "RAG_IME_SELECT_INPUT_SOURCE_SCRIPT": str(select_script),
                    "RAG_IME_CHECK_INPUT_SOURCE_SCRIPT": str(check_script),
                    "RAG_IME_DOCTOR_SCRIPT": str(doctor_script),
                    "RAG_IME_TEST_CALLS_LOG": str(calls_log),
                },
                check=True,
                text=True,
                capture_output=True,
            )

            target_executable = target_app / "Contents" / "MacOS" / "Squirrel"
            target_text = target_executable.read_text(encoding="utf-8")
            calls = calls_log.read_text(encoding="utf-8")

        self.assertIn("installed patched system Squirrel.app", result.stdout)
        self.assertIn("backing up existing system Squirrel.app", result.stdout)
        self.assertIn("rag-ime.squirrel-frontend-trace.v1", target_text)
        self.assertIn("panel_text_layout", target_text)
        self.assertIn("sidecar_request_scheduled", target_text)
        self.assertIn("sidecar_empty_response_cleared", target_text)
        self.assertIn("select im.rime.inputmethod.Squirrel.Hans", calls)
        self.assertIn("check --require-selected im.rime.inputmethod.Squirrel.Hans", calls)
        self.assertIn("doctor", calls)
        self.assertIn(f"doctor_app={target_app}", calls)
        self.assertIn(f"doctor_duplicates={source_app}:{target_app}", calls)
        self.assertIn("doctor_tryout=1", calls)
        self.assertIn("doctor_frontend_trace=0", calls)

    def test_replace_script_fails_if_copied_target_lacks_patch_marker(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-replace-squirrel-") as tmp:
            tmp_path = Path(tmp)
            source_app = _write_fake_squirrel_app(tmp_path / "User Squirrel.app", patched=True)
            target_app = tmp_path / "System Squirrel.app"
            fake_bin = _write_fake_system_tools(tmp_path, strip_patch_on_ditto=True)

            result = subprocess.run(
                ["bash", str(root / "scripts" / "replace_system_squirrel_app.sh")],
                cwd=root,
                env={
                    **os.environ,
                    "PATH": f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}",
                    "RAG_IME_SQUIRREL_SOURCE_APP": str(source_app),
                    "RAG_IME_SQUIRREL_SYSTEM_APP": str(target_app),
                    "RAG_IME_SELECT_INPUT_SOURCE_SCRIPT": str(tmp_path / "missing-select.sh"),
                    "RAG_IME_CHECK_INPUT_SOURCE_SCRIPT": str(tmp_path / "missing-check.sh"),
                    "RAG_IME_DOCTOR_SCRIPT": str(tmp_path / "missing-doctor.sh"),
                },
                text=True,
                capture_output=True,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("target Squirrel.app does not contain the current RAG-IME frontend patch", result.stderr)


def _write_fake_squirrel_app(path: Path, *, patched: bool) -> Path:
    executable = path / "Contents" / "MacOS" / "Squirrel"
    executable.parent.mkdir(parents=True)
    lines = ["#!/usr/bin/env bash"]
    if patched:
        lines.extend(
            [
                "# rag-ime.squirrel-frontend-trace.v1",
                "# rag-ime.foreground-trace.v2",
                "# panel_text_layout",
                "# sidecar_request_scheduled",
                "# sidecar_empty_response_cleared",
            ]
        )
    lines.extend(
        [
            "if [[ \"${RAG_IME_TEST_CALLS_LOG:-}\" != \"\" ]]; then",
            "  printf 'squirrel %s\\n' \"$*\" >> \"$RAG_IME_TEST_CALLS_LOG\"",
            "fi",
            "exit 0",
        ]
    )
    executable.write_text("\n".join(lines) + "\n", encoding="utf-8")
    executable.chmod(0o755)
    return path


def _write_fake_system_tools(tmp_path: Path, *, strip_patch_on_ditto: bool = False) -> Path:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "sudo").write_text(
        "#!/usr/bin/env bash\n"
        "if [[ \"${1:-}\" == \"-n\" ]]; then exit 1; fi\n"
        "if [[ \"${1:-}\" == \"chown\" ]]; then exit 0; fi\n"
        "exec \"$@\"\n",
        encoding="utf-8",
    )
    (fake_bin / "sudo").chmod(0o755)
    ditto_body = [
        "#!/usr/bin/env bash",
        "rm -rf \"$2\"",
        "cp -R \"$1\" \"$2\"",
    ]
    if strip_patch_on_ditto:
        ditto_body.extend(
            [
                "exe=\"$2/Contents/MacOS/Squirrel\"",
                "python3 - \"$exe\" <<'PY'",
                "from pathlib import Path",
                "import sys",
                "path = Path(sys.argv[1])",
                "text = path.read_text(encoding='utf-8')",
                "text = text.replace('# rag-ime.squirrel-frontend-trace.v1\\n', '')",
                "text = text.replace('# rag-ime.foreground-trace.v2\\n', '')",
                "text = text.replace('# panel_text_layout\\n', '')",
                "text = text.replace('# sidecar_request_scheduled\\n', '')",
                "text = text.replace('# sidecar_empty_response_cleared\\n', '')",
                "path.write_text(text, encoding='utf-8')",
                "PY",
            ]
        )
    ditto_body.append("exit 0")
    (fake_bin / "ditto").write_text("\n".join(ditto_body) + "\n", encoding="utf-8")
    (fake_bin / "ditto").chmod(0o755)
    (fake_bin / "codesign").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    (fake_bin / "codesign").chmod(0o755)
    (fake_bin / "pkill").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    (fake_bin / "pkill").chmod(0o755)
    return fake_bin


def _write_logger_script(path: Path, prefix: str) -> Path:
    path.write_text(
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "set -euo pipefail",
                "printf '%s %s\\n' '" + prefix + "' \"$*\" >> \"$RAG_IME_TEST_CALLS_LOG\"",
                "if [[ '" + prefix + "' == 'doctor' ]]; then",
                "  printf 'doctor_app=%s\\n' \"${RAG_IME_SQUIRREL_APP:-}\" >> \"$RAG_IME_TEST_CALLS_LOG\"",
                "  printf 'doctor_duplicates=%s\\n' \"${RAG_IME_SQUIRREL_DUPLICATE_APP_CANDIDATES:-}\" >> \"$RAG_IME_TEST_CALLS_LOG\"",
                "  printf 'doctor_tryout=%s\\n' \"${RAG_IME_DOCTOR_REQUIRE_TRYOUT:-}\" >> \"$RAG_IME_TEST_CALLS_LOG\"",
                "  printf 'doctor_frontend_trace=%s\\n' \"${RAG_IME_DOCTOR_REQUIRE_FRONTEND_TRACE:-}\" >> \"$RAG_IME_TEST_CALLS_LOG\"",
                "fi",
                "exit 0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


if __name__ == "__main__":
    unittest.main()
