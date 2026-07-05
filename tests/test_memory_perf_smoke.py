from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class MemoryPerfProbeSmokeTests(unittest.TestCase):
    def test_memory_perf_probe_reports_cached_and_uncached_latency(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "memory_perf_probe.py"
        with tempfile.TemporaryDirectory(prefix="rag-ime-memory-perf-") as tmp:
            db_path = Path(tmp) / "perf.sqlite"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(script_path),
                    "--db",
                    str(db_path),
                    "--items",
                    "120",
                    "--repeat",
                    "2",
                    "--top-k",
                    "4",
                ],
                cwd=repo_root,
                check=True,
                capture_output=True,
                text=True,
            )
        payload = json.loads(completed.stdout)

        self.assertEqual(payload["schemaVersion"], "rag-ime.memory-perf-probe.v1")
        self.assertEqual(payload["seeded"], 120)
        self.assertEqual(payload["itemCount"], 120)
        self.assertEqual(payload["vector"]["enabled"], False)
        self.assertGreater(payload["latency"]["uncached"]["queryCount"], 0)
        self.assertGreater(payload["latency"]["cached"]["queryCount"], 0)
        self.assertGreaterEqual(payload["latency"]["uncached"]["p95Ms"], 0.0)
        self.assertGreaterEqual(payload["latency"]["cached"]["p95Ms"], 0.0)
        self.assertGreater(payload["latency"]["cached"]["cacheStats"]["hits"], 0)

