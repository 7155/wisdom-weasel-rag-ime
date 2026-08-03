from __future__ import annotations

import json
import os
import plistlib
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from importlib.util import module_from_spec, spec_from_file_location
from io import StringIO
from pathlib import Path
from unittest.mock import patch


class _FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._raw = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._raw


class _FakeOpener:
    def __init__(self) -> None:
        self.requests: list[object] = []

    def open(self, request: object, *, timeout: float) -> _FakeResponse:
        del timeout
        self.requests.append(request)
        if len(self.requests) == 1:
            return _FakeResponse(
                {
                    "schemaVersion": "rag-ime.gateway-memory-maintenance-job.v1",
                    "ok": True,
                    "jobId": "memory-maintenance:test",
                    "state": "queued",
                    "result": {},
                }
            )
        return _FakeResponse(
            {
                "schemaVersion": "rag-ime.gateway-memory-maintenance-job.v1",
                "ok": True,
                "jobId": "memory-maintenance:test",
                "state": "completed",
                "result": {"ok": True, "ranScopeCount": 1},
            }
        )


def _load_wrapper(root: Path):
    path = root / "scripts/memory_book_maintenance_launch.py"
    spec = spec_from_file_location("memory_book_maintenance_launch_test", path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MemoryMaintenanceGatewayClientTests(unittest.TestCase):
    def test_app_local_wrapper_only_triggers_and_polls_gateway(self) -> None:
        root = Path(__file__).resolve().parents[1]
        wrapper = _load_wrapper(root)
        opener = _FakeOpener()
        output = StringIO()
        with (
            patch.object(wrapper, "build_opener", return_value=opener),
            patch.object(wrapper.time, "sleep", return_value=None),
            patch.dict(
                os.environ,
                {
                    "RAG_IME_AGENT_GATEWAY_URL": "http://127.0.0.1:18768",
                    "RAG_IME_MEMORY_MAINTENANCE_POLL_SECONDS": "0.05",
                    "RAG_IME_PROJECT": "sample-project",
                },
                clear=False,
            ),
            redirect_stdout(output),
        ):
            exit_code = wrapper.main()

        self.assertEqual(exit_code, 0)
        report = json.loads(output.getvalue())
        self.assertEqual(report["state"], "completed")
        self.assertEqual(
            [item.get_method() for item in opener.requests],
            ["POST", "GET"],
        )
        self.assertEqual(
            json.loads(opener.requests[0].data.decode("utf-8")),
            {"project": "sample-project", "manual": False},
        )
        self.assertIn(
            "jobId=memory-maintenance%3Atest",
            opener.requests[1].full_url,
        )

    def test_wrapper_rejects_non_loopback_gateway(self) -> None:
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [sys.executable, str(root / "scripts/memory_book_maintenance_launch.py")],
            cwd=root,
            env={
                **os.environ,
                "RAG_IME_AGENT_GATEWAY_URL": "https://example.invalid",
            },
            check=False,
            text=True,
            capture_output=True,
        )

        self.assertEqual(result.returncode, 1)
        report = json.loads(result.stdout)
        self.assertEqual(report["state"], "failed")
        self.assertIn("loopback HTTP origin", report["error"])


@unittest.skipUnless(sys.platform == "darwin", "requires macOS LaunchAgent tools")
class MemoryBookMaintenanceScriptTests(unittest.TestCase):
    def test_install_packages_only_a_gateway_trigger(self) -> None:
        root = Path(__file__).resolve().parents[1]
        installer = (
            root / "scripts" / "install_memory_book_maintenance_launch_agent.sh"
        ).read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory(prefix="rag-ime-memory-book-agent-") as tmp:
            home = Path(tmp) / "home"
            model_env = Path(tmp) / "source-deepseek.env"
            model_env.write_text("DEEPSEEK_API_KEY=fake\n", encoding="utf-8")
            result = subprocess.run(
                ["bash", str(root / "scripts/install_memory_book_maintenance_launch_agent.sh")],
                cwd=root,
                env={
                    **os.environ,
                    "HOME": str(home),
                    "RAG_IME_LAUNCH_AGENT_DRY_RUN": "1",
                    "RAG_IME_DEEPSEEK_ENV": str(model_env),
                    "RAG_IME_DB_PATH": str(Path(tmp) / "must-not-be-packaged.sqlite"),
                    "RAG_IME_MEMORY_BOOK_MAINTENANCE_INTERVAL_SECONDS": "900",
                },
                check=True,
                text=True,
                capture_output=True,
            )

            plist_path = home / "Library" / "LaunchAgents" / "com.rag-ime.memory-book-maintenance.plist"
            payload = plistlib.loads(plist_path.read_bytes())
            app_dir = (
                home
                / "Library"
                / "Application Support"
                / "RagIme"
                / "components"
                / "memory-book-maintenance"
            )
            installed_files = {
                "wrapper": (app_dir / "memory_book_maintenance_launch.py").is_file(),
                "runner": (app_dir / "scripts" / "run_memory_book_maintenance_once.sh").is_file(),
                "package": (app_dir / "rag_ime" / "cli.py").is_file(),
                "marker": (app_dir / "rag-ime-install-marker.json").is_file(),
            }

        self.assertIn(str(plist_path), result.stdout)
        self.assertEqual(payload["Label"], "com.rag-ime.memory-book-maintenance")
        self.assertEqual(payload["StartInterval"], 900)
        self.assertFalse(payload["RunAtLoad"])
        self.assertFalse(payload["KeepAlive"])
        self.assertTrue(payload["ProgramArguments"][-1].endswith("memory_book_maintenance_launch.py"))
        self.assertEqual(payload["WorkingDirectory"], str(app_dir))
        self.assertTrue(installed_files["wrapper"])
        self.assertFalse(installed_files["runner"])
        self.assertFalse(installed_files["package"])
        self.assertTrue(installed_files["marker"])
        env_vars = payload["EnvironmentVariables"]
        self.assertEqual(
            env_vars["RAG_IME_AGENT_GATEWAY_URL"],
            "http://127.0.0.1:8768",
        )
        self.assertEqual(
            env_vars["RAG_IME_MEMORY_BOOK_MAINTENANCE_TRIGGER"],
            "scheduled",
        )
        self.assertNotIn("RAG_IME_ROOT", env_vars)
        self.assertNotIn("RAG_IME_DB_PATH", env_vars)
        self.assertFalse(any("DEEPSEEK" in key or "MODEL" in key for key in env_vars))
        self.assertNotIn("cp -R \"$ROOT/rag_ime\"", installer)
        self.assertLess(
            installer.rindex("launchctl enable"),
            installer.rindex("launchctl bootstrap"),
        )

    def test_source_runner_is_only_a_gateway_trigger(self) -> None:
        root = Path(__file__).resolve().parents[1]
        source = (root / "scripts" / "run_memory_book_maintenance_once.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn("memory_book_maintenance_launch.py", source)
        self.assertNotIn("rag_ime.owner_memory_maintenance", source)
        self.assertNotIn("sqlite", source.lower())
        self.assertNotIn("deepseek", source.lower())
        self.assertNotIn("memory_book_compiler", source)


if __name__ == "__main__":
    unittest.main()
