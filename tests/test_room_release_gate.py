from __future__ import annotations

import json
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path

from rag_ime.db import apply_database_migrations
from rag_ime.room_release_gate import stage_room_v2_canary


class RoomReleaseGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="room-release-gate-")
        self.root = Path(self.tmp.name)
        self.product = self.root / "product"; self.pi = self.root / "pi"
        for repo in (self.product, self.pi):
            repo.mkdir(); subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
        contracts = self.product / "rag_ime/contracts/json"; contracts.mkdir(parents=True)
        for index in range(138):
            (contracts / f"contract-{index:03}.json").write_text("{}\n", encoding="utf-8")
        for relative in ("rag_ime/agent_knowledge_promotion.py", "rag_ime/collaboration_profile_control.py", "rag_ime/agent_governance_projection.py", "rag_ime/runtime_prompt.py"):
            path = self.product / relative; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(relative + "\n", encoding="utf-8")
        routes = self.product / "control-center-web/src/platform/routes.ts"; routes.parent.mkdir(parents=True); routes.write_text("export const routes = {};\n", encoding="utf-8")
        self.frontend = self.root / "frontend"; self.frontend.mkdir(); (self.frontend / "index.js").write_text("ready\n", encoding="utf-8")
        (self.pi / "README.md").write_text("fixture\n", encoding="utf-8")
        for repo in (self.product, self.pi):
            subprocess.run(["git", "add", "."], cwd=repo, check=True); subprocess.run(["git", "commit", "-qm", "fixture"], cwd=repo, check=True)
        self.pi_build = self.root / "pi-build"; self.pi_build.mkdir()
        (self.pi_build / "manifest.json").write_text(
            json.dumps(
                {
                    "schemaVersion": "rag-ime.pi-runtime-manifest.v1",
                    "runtimeProtocolVersion": "2",
                    "runtimeMethods": ["room.dispatch", "room.cancel"],
                    "source": {
                        "commit": subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.pi, check=True, text=True, stdout=subprocess.PIPE).stdout.strip(),
                        "productCommit": subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.product, check=True, text=True, stdout=subprocess.PIPE).stdout.strip(),
                    },
                },
                sort_keys=True,
            ) + "\n",
            encoding="utf-8",
        )
        self.db = self.root / "source.sqlite"
        with sqlite3.connect(self.db) as conn:
            apply_database_migrations(conn, applied_at_ms=0)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_staging_is_reproducible_and_never_modifies_source_or_claims_canary_ready(self) -> None:
        before = self.db.read_bytes()
        reports = [stage_room_v2_canary(product_root=self.product, pi_root=self.pi, source_db=self.db,
            frontend_dist=self.frontend, output_dir=self.root / name, pi_build=self.pi_build) for name in ("out-a", "out-b")]
        self.assertEqual(before, self.db.read_bytes())
        self.assertEqual(reports[0]["receiptHash"], reports[1]["receiptHash"])
        self.assertEqual(reports[0]["checks"]["migrationVersion"], 101)
        self.assertEqual(reports[0]["checks"]["schemaCount"], 138)
        self.assertTrue(reports[0]["checks"]["piBuildManifestValid"])
        self.assertTrue(reports[0]["checks"]["piBuildProductCommitMatches"])
        self.assertTrue(reports[0]["checks"]["piBuildSourceCommitMatches"])
        self.assertNotIn("local_provenance_or_dry_run", reports[0]["remainingGates"])
        self.assertFalse(reports[0]["productionCanaryEligible"])
        self.assertIn("loopback_worker_control_e2e", reports[0]["remainingGates"])
        self.assertFalse(reports[0]["installedAppsModified"])


if __name__ == "__main__":
    unittest.main()
