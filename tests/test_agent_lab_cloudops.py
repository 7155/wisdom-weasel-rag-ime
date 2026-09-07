from __future__ import annotations

import json
import tempfile
import threading
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock, patch

from rag_ime.agent_lab.cloudops import CloudOpsTrialAdapter, CloudOpsTrialAssets
from rag_ime.agent_lab.trial_execution import AgentLabTrialApplication
from rag_ime.agent_lab.trials import AgentLabTrialStore
from rag_ime.eval_run_store import EvalRunStore
from rag_ime.sandbox_run_store import SandboxRunStore
from rag_ime.trace_store import TraceStore
from tests.test_cloudops_benchmark_agent import _write_fixture
from tests.test_run_cloudops_agent_eval import _FakeAgentService


class _Observer:
    def __init__(self):
        self.bindings, self.messages = [], []

    def progress(self, message):
        self.messages.append(message)

    def bind_session(self, session_id, turn_id="", cancel=None):
        self.bindings.append((session_id, turn_id, cancel))


class CloudOpsTrialAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="lab-cloudops-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cases = [f"demo/runtime/{index}" for index in range(1, 13)]
        _write_fixture(self.root, self.cases)
        self.gold = self.root / "gold.json"
        self.gold.write_text("HOST GOLD SECRET")
        self.scorer = self.root / "score.py"
        self.scorer.write_text("# configured host scorer")
        self.assets = CloudOpsTrialAssets(
            blind_root=self.root / "blind", gold=self.gold, scorer=self.scorer,
            runtime_candidate=self.root, source_agent_config=self.root,
            private_root=self.root / "trials", pricing_config=None,
        )
        self.services, self.closed = [], []

        @contextmanager
        def environment(assets, run_root, spec, suite, gateway):
            service = _FakeAgentService(gateway)
            service.trace_store = TraceStore(run_root / "observability.sqlite")
            service.eval_runs = EvalRunStore(run_root / "observability.sqlite")
            service.sandbox_runs = SandboxRunStore(run_root / "observability.sqlite")
            service.prompt = Mock(wraps=service.prompt)
            service.abort = Mock()
            self.services.append(service)
            try:
                yield service, {"provider": "openai-codex", "model": "gpt-5.6-sol"}
            finally:
                self.closed.append(service)

        self.adapter = CloudOpsTrialAdapter(self.assets, environment_factory=environment)
        self.scoring = patch("scripts.run_cloudops_agent_eval.invoke_host_scorer", side_effect=self.score).start()
        self.addCleanup(patch.stopall)

    def score(self, scorer, gold, answers):
        self.assertEqual(self.gold.resolve(), gold)
        self.assertEqual(12, len(answers))
        self.assertEqual(3, len(self.services[0].created))
        return {
            "aggregate": {"cases": 12, "answered": 12, "AnswerCoverage": 1., "CA": 1., "FA": 1., "JRA": 1., "Top3JRA": 1.},
            "perCase": [{"case_id": case_id, "JRA": 1.} for case_id in self.cases],
        }

    def test_runtime_composition_requires_an_explicit_application_owner(self):
        with self.assertRaisesRegex(ValueError, "application owner"):
            CloudOpsTrialAdapter(self.assets)

    def test_injected_service_factory_closes_service_and_transport(self):
        service = Mock()
        service_factory = Mock(return_value=service)
        adapter = CloudOpsTrialAdapter(self.assets, service_factory=service_factory)
        with patch("rag_ime.rag_benchmark_agent.RagBenchmarkAgentSpoolGateway") as transport_type:
            transport = transport_type.return_value
            with patch("scripts.run_cloudops_agent_eval._candidate_runtime_config", return_value=("config", {"model": "test"})):
                with adapter._environment(self.assets, self.root / "run", {"provider": "test", "model": "test"}, None, Mock()) as result:
                    self.assertIs(result[0], service)
                    self.assertEqual(service_factory.call_args.kwargs["runtime_config"], "config")
                    self.assertFalse(service_factory.call_args.kwargs["background_job_execution_owner"])
                service.close.assert_called_once_with()
                transport.close.assert_called_once_with()

    def test_prepare_is_read_only_and_does_not_accept_host_paths(self):
        prepared = self.adapter.prepare({"candidatePromptText": "Check competing evidence."}, "lab-trial:one")
        self.assertEqual([], self.services)
        self.assertFalse(self.assets.private_root.exists())
        self.assertEqual(12, prepared["publicSpec"]["caseCount"])
        self.assertNotIn(str(self.root), json.dumps(prepared["publicSpec"]))
        self.assertNotIn("Check competing", json.dumps(prepared["publicSpec"]))
        for key in ("gold", "scorer", "runtimeCandidate", "privateRoot", "candidatePromptFile"):
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.adapter.prepare({key: str(self.gold)}, "lab-trial:bad")

    def test_actual_runner_binds_three_turns_scores_and_closes_before_result(self):
        prepared = self.adapter.prepare({"candidatePromptText": "Check competing evidence."}, "lab-trial:one")
        observer = _Observer()
        report = self.adapter.execute(prepared["privateInput"], observer, lambda: False)
        self.assertEqual(self.services, self.closed)
        self.assertEqual("completed", report["status"])
        self.assertEqual(1., report["metrics"]["JRA"])
        self.assertEqual(12, report["caseCount"])
        self.assertEqual(3, len([entry for entry in observer.bindings if entry[1]]))
        self.assertEqual(3, len([entry for entry in observer.bindings if entry[2] is not None]))
        self.assertFalse(report["cost"]["available"])
        self.assertNotIn(str(self.root), json.dumps(report))
        self.assertNotIn("HOST GOLD", json.dumps(report))
        for call in self.services[0].prompt.call_args_list:
            self.assertIn("Check competing evidence.", call.args[1]["message"])
            self.assertNotIn("HOST GOLD", json.dumps(call.args))
        self.assertEqual(1, self.scoring.call_count)
        self.assertTrue(list(self.assets.private_root.glob("*/report.json")))

    def test_application_replay_cannot_launch_a_second_evaluation(self):
        app = AgentLabTrialApplication(AgentLabTrialStore(self.root / "jobs.sqlite"), {"cloudops": self.adapter}, start_workers=False)
        self.addCleanup(app.close)
        first = app.start("click-once", "cloudops", {})
        app.run_job(first["job"]["jobId"])
        again = app.start("click-once", "cloudops", {})
        app.run_job(again["job"]["jobId"])
        self.assertTrue(again["replayed"])
        self.assertEqual("completed", again["job"]["state"])
        self.assertEqual(1, len(self.services))

    def test_cancel_after_first_turn_prevents_next_batch_and_retains_failure(self):
        stopped = threading.Event()
        prepared = self.adapter.prepare({}, "lab-trial:stop")
        observer = _Observer()
        original = observer.bind_session

        def bind(session_id, turn_id="", cancel=None):
            original(session_id, turn_id, cancel)
            if turn_id:
                stopped.set()

        observer.bind_session = bind
        with self.assertRaisesRegex(RuntimeError, "cancelled"):
            self.adapter.execute(prepared["privateInput"], observer, stopped.is_set)
        self.assertEqual(1, len(self.services[0].created))
        self.assertEqual(self.services, self.closed)
        self.assertEqual(0, self.scoring.call_count)
        self.assertTrue(list(self.assets.private_root.glob("*/failure.json")))

    def test_changed_host_assets_fail_before_runtime_or_paid_admission(self):
        prepared = self.adapter.prepare({}, "lab-trial:drift")
        self.gold.write_text("changed labels")
        with self.assertRaisesRegex(ValueError, "changed"):
            self.adapter.execute(prepared["privateInput"], _Observer(), lambda: False)
        self.assertEqual([], self.services)


if __name__ == "__main__":
    unittest.main()
