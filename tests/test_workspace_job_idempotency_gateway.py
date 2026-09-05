from __future__ import annotations

from pathlib import Path
import time
import unittest

from rag_ime.agent_background_jobs import AgentBackgroundJobService
from rag_ime.agent_tools import ControlToolGateway
from tests import test_agent_tools as tool_fixtures


class WorkspaceJobIdempotencyGatewayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = tool_fixtures.ControlToolGatewayTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.workspace = Path(self.fixture.tmp.name) / "idempotent-command"
        self.workspace.mkdir()
        self.session = self.fixture.store.create(
            title="job identity contract",
            mode="coordinator",
            tool_profile_version="control-center-auto-approve-v1",
            execution_mode="full_trust",
            workspace_roots=[str(self.workspace), "/"],
        )
        self.fixture._start_todo(str(self.session["id"]))
        self.jobs = AgentBackgroundJobService(
            Path(self.fixture.tmp.name) / "rag-ime.sqlite",
            events=lambda *args, **kwargs: None,
        )
        self.jobs.initialize()
        self.addCleanup(self.jobs.close)
        self.gateway = ControlToolGateway(
            sessions=self.fixture.store,
            management=self.fixture.management,
            core=tool_fixtures._Core(),
            project="personal-agent-workbench",
            facade=tool_fixtures._Facade(),
            workspace_harness=self.jobs.workspace_harness,
            background_jobs=self.jobs,
        )

    def _start(self):
        prepared = self.gateway._prepare_background_job_start(
            session_id=str(self.session["id"]),
            args={
                "command": "printf 'effect\\n' >> effect.txt",
                "cwd": str(self.workspace),
                "timeoutSeconds": 5,
                "idempotencyKey": "same-start-after-lost-reply",
            },
            risk_level="R2",
        )
        approval = prepared["approval"]
        self.assertEqual(
            approval["preview"]["actionPayload"].get("idempotencyKey"),
            "same-start-after-lost-reply",
        )
        decided = self.fixture.store.decide_approval(
            approval["approvalId"], approved=True, payload_sha256=approval["payloadSha256"]
        )
        return self.gateway.apply_approval(decided)

    def test_start_identity_survives_preview_and_replays_without_new_mutation(self) -> None:
        first = self._start()
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            job = self.jobs.status(str(self.session["id"]), first["job"]["jobId"])["job"]
            if job["status"] not in {"queued", "running", "cancelling"}:
                break
            time.sleep(0.02)
        self.assertEqual(job["status"], "completed")
        replay = self._start()
        self.assertEqual(first["job"]["jobId"], replay["job"]["jobId"])
        self.assertTrue(replay["replayed"])
        self.assertFalse(replay["mutationApplied"])
        self.assertEqual((self.workspace / "effect.txt").read_text().splitlines(), ["effect"])


if __name__ == "__main__":
    unittest.main()
