from __future__ import annotations

import json
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from rag_ime.agent_lab_trials import AgentLabTrialConflict, AgentLabTrialStore
from rag_ime.agent_service import AgentService
from rag_ime.control_api import ControlAccessContext, ControlApiError, ControlRequest, default_route_policy
from rag_ime.control_api.route_table import find_route
from rag_ime.debug_server import DebugRequestHandler
from rag_ime.pi_runtime import PiRuntimeConfig


class Adapter:
    def __init__(self):
        self.prepared = 0
        self.executed = 0
        self.entered = threading.Event()
        self.abort_called = threading.Event()
        self.release = threading.Event()

    def prepare(self, spec, job_id):
        self.prepared += 1
        return {"publicSpec": {"model": spec["model"]},
                "privateInput": {"jobId": job_id, "secret": "private-sentinel"}}

    def execute(self, private_input, observer, cancelled):
        self.executed += 1
        observer.bind_session("actual-session", "actual-turn", cancel=self.abort_called.set)
        self.entered.set()
        if not self.release.wait(5):
            raise TimeoutError("Test did not release the execution")
        return {"qualityVerdict": "reject", "score": 0.5}


def handler(agent):
    value = DebugRequestHandler.__new__(DebugRequestHandler)
    value.service = SimpleNamespace(agent=agent)
    value._authorize_gateway_request = lambda *_args: True
    value._serve_isolated_html_preview = lambda _path: False
    value._serve_gateway_static = lambda _path: False
    value._management_post_security_error = lambda *_args, **_kwargs: None
    written = []
    value._write_json = lambda status, body: written.append((int(status), body))
    return value, written


class TrialServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.adapter = Adapter()
        self.addCleanup(self.adapter.release.set)

    def service(self, *, owner=True, recovery=False, adapters=True):
        kwargs = {"eval_lab_trial_adapters": {"scene": self.adapter}} if adapters else {}
        service = AgentService(
            db_path=self.root / "paw.sqlite",
            runtime_config=PiRuntimeConfig(enabled=False, executable=None,
                agent_dir=self.root / "config", session_dir=self.root / "sessions", logs_dir=self.root / "logs"),
            background_job_execution_owner=owner, startup_recovery_enabled=recovery, **kwargs,
        )
        return service

    def request(self):
        return {"clientRequestId": "click-1", "sceneId": "scene", "spec": {"model": "test"}}

    def test_read_and_replica_close_preserve_queued_work_without_constructing_application(self):
        service = self.service(owner=False, recovery=True)
        try:
            store = AgentLabTrialStore(self.root / "paw.sqlite")
            job_id = store.admit("persisted", "scene", {"model": "test"}, self.adapter.prepare)["job"]["jobId"]
            for _ in range(3):
                response = service.eval_lab_trials({"jobId": job_id})
                self.assertEqual(response["job"]["state"], "queued")
                self.assertNotIn("private-sentinel", json.dumps(response))
            listing = service.eval_lab_trials()
            self.assertEqual(listing["registeredSceneIds"], ["scene"])
            self.assertNotIn("privateInput", json.dumps(listing))
            self.assertIsNone(service._eval_lab_trial_application)
            self.assertEqual(self.adapter.executed, 0)
        finally:
            service.close()
        self.assertEqual(store.read(job_id)["job"]["state"], "queued")

    def test_execution_owner_recovers_at_startup_without_creating_an_application(self):
        store = AgentLabTrialStore(self.root / "paw.sqlite")
        job_id = store.admit("persisted", "scene", {"model": "test"}, self.adapter.prepare)["job"]["jobId"]
        store.claim(job_id)
        store.bind_session(job_id, "original-session", "original-turn")
        service = self.service(recovery=True)
        try:
            job = service.eval_lab_trials({"jobId": job_id})["job"]
            self.assertEqual(job["state"], "interrupted")
            self.assertEqual(job["sessions"], [{"sessionId": "original-session", "turnId": "original-turn"}])
            self.assertIsNone(service._eval_lab_trial_application)
            self.assertEqual(self.adapter.executed, 0)
        finally:
            service.close()

    def test_replica_rejects_start_and_cancel_without_mutating_owner_jobs(self):
        service = self.service(owner=False)
        try:
            store = AgentLabTrialStore(self.root / "paw.sqlite")
            job_id = store.admit("persisted", "scene", {"model": "test"}, self.adapter.prepare)["job"]["jobId"]
            for operation, body in ((service.eval_lab_trial_start, self.request()),
                                    (service.eval_lab_trial_cancel, {"jobId": job_id})):
                with self.assertRaises(Exception) as error:
                    operation(body)
                self.assertEqual(getattr(error.exception, "http_status", None), 503)
            self.assertEqual(store.read(job_id)["job"]["state"], "queued")
            self.assertIsNone(service._eval_lab_trial_application)
        finally:
            service.close()

    def test_service_uses_injected_adapter_once_and_cancellation_waits_for_settlement(self):
        service = self.service()
        try:
            original = service.eval_lab_trial_start(self.request())
            job_id = original["job"]["jobId"]
            self.assertTrue(self.adapter.entered.wait(3))
            replay = service.eval_lab_trial_start(self.request())
            self.assertTrue(replay["replayed"])
            self.assertEqual(replay["job"]["jobId"], job_id)
            with self.assertRaises(AgentLabTrialConflict):
                service.eval_lab_trial_start({**self.request(), "spec": {"model": "changed"}})
            with self.assertRaises(AgentLabTrialConflict):
                service.eval_lab_trial_start({**self.request(), "sceneId": "another-scene"})
            stopping = service.eval_lab_trial_cancel({"jobId": job_id})
            self.assertTrue(self.adapter.abort_called.is_set())
            self.assertEqual(stopping["job"]["state"], "cancelling")
            self.assertNotIn("private-sentinel", json.dumps([original, replay, stopping]))
            self.adapter.release.set()
            deadline = time.monotonic() + 3
            while service.eval_lab_trials({"jobId": job_id})["job"]["state"] == "cancelling" and time.monotonic() < deadline:
                time.sleep(0.01)
            final = service.eval_lab_trials({"jobId": job_id})["job"]
            self.assertEqual(final["state"], "cancelled")
            self.assertIsNone(final["result"])
            self.assertEqual(final["sessions"], [{"sessionId": "actual-session", "turnId": "actual-turn"}])
            self.assertEqual((self.adapter.prepared, self.adapter.executed), (1, 1))
        finally:
            self.adapter.release.set()
            service.close()

    def test_shutdown_settles_trial_before_stopping_runtime(self):
        service = self.service()
        service.runtime.stop = Mock(wraps=service.runtime.stop)
        try:
            job_id = service.eval_lab_trial_start(self.request())["job"]["jobId"]
            self.assertTrue(self.adapter.entered.wait(3))
            closer = threading.Thread(target=service.close)
            closer.start()
            self.assertTrue(self.adapter.abort_called.wait(3))
            self.assertTrue(closer.is_alive())
            service.runtime.stop.assert_not_called()
        finally:
            self.adapter.release.set()
            if "closer" in locals():
                closer.join(5)
            else:
                service.close()
        self.assertFalse(closer.is_alive())
        service.runtime.stop.assert_called_once()
        self.assertEqual(AgentLabTrialStore(self.root / "paw.sqlite").read(job_id)["job"]["state"], "interrupted")
        with self.assertRaises(Exception) as error:
            service.eval_lab_trial_start({**self.request(), "clientRequestId": "after-close"})
        self.assertEqual(getattr(error.exception, "http_status", None), 503)

    def test_transient_terminal_write_failure_retries_receipt_without_reexecuting(self):
        service = self.service()
        settled = threading.Event()
        try:
            application = service._trial_application()
            finish = application.store.finish
            attempts = []
            def persist(*args, **kwargs):
                attempts.append((args, kwargs))
                if len(attempts) == 1:
                    raise sqlite3.OperationalError("database is locked: private-sentinel")
                response = finish(*args, **kwargs)
                settled.set()
                return response
            with patch.object(application.store, "finish", side_effect=persist):
                job_id = service.eval_lab_trial_start(self.request())["job"]["jobId"]
                self.assertTrue(self.adapter.entered.wait(3))
                self.adapter.release.set()
                self.assertTrue(settled.wait(3), "A transient final write error left the settled trial running")
                job = service.eval_lab_trials({"jobId": job_id})["job"]
            self.assertEqual(job["state"], "completed")
            self.assertEqual(job["result"]["qualityVerdict"], "reject")
            self.assertEqual(self.adapter.executed, 1)
            self.assertEqual(len(attempts), 2)
            self.assertEqual(attempts[0], attempts[1])
            self.assertNotIn("private-sentinel", json.dumps(job))
        finally:
            self.adapter.release.set()
            service.close()

    def test_default_memory_registry_and_invalid_request_do_not_admit_or_create_workers(self):
        service = self.service(adapters=False)
        try:
            invalid = [None, [], {}, {**self.request(), "privateInput": {}},
                       {**self.request(), "sceneId": []}, {**self.request(), "spec": []}]
            for body in invalid:
                with self.subTest(body=body), self.assertRaises(ValueError):
                    service.eval_lab_trial_start(body)
            self.assertIsNone(service._eval_lab_trial_application)
            with self.assertRaises(ValueError):
                service.eval_lab_trial_start(self.request())
            listing = service.eval_lab_trials()
            self.assertEqual(listing["jobs"], [])
            self.assertEqual(listing["registeredSceneIds"], ["knowledge-resource", "memory"])
        finally:
            service.close()

    def test_default_memory_registration_and_reads_do_not_construct_pi_or_create_artifacts(self):
        from rag_ime.agent_lab_memory_trial import AgentLabMemoryTrialAdapter
        with patch("rag_ime.agent_lab_golden_pi.AgentLabGoldenPiExecutor") as executor:
            service = self.service(adapters=False)
            try:
                adapter = service._eval_lab_trial_adapters.get("memory")
                self.assertIsInstance(adapter, AgentLabMemoryTrialAdapter)
                for _ in range(3):
                    listing = service.eval_lab_trials()
                    self.assertEqual(listing["registeredSceneIds"], ["knowledge-resource", "memory"])
                    self.assertEqual(listing["jobs"], [])
                prepared = adapter.prepare({}, "lab-trial:admission-only")
                self.assertEqual(prepared["publicSpec"]["evaluationMode"], "synthetic-fixture")
                self.assertFalse(prepared["publicSpec"]["personalMemoryQualityMeasured"])
                self.assertFalse(adapter.artifact_root.exists())
                self.assertNotIn(str(self.root), json.dumps(listing))
                self.assertIsNone(service._eval_lab_trial_application)
                executor.assert_not_called()
            finally:
                service.close()

    def test_explicit_empty_registry_disables_default_memory(self):
        service = AgentService(
            db_path=self.root / "paw.sqlite", eval_lab_trial_adapters={},
            runtime_config=PiRuntimeConfig(enabled=False, executable=None,
                agent_dir=self.root / "config", session_dir=self.root / "sessions", logs_dir=self.root / "logs"),
            startup_recovery_enabled=False,
        )
        try:
            self.assertEqual(service.eval_lab_trials()["registeredSceneIds"], [])
        finally:
            service.close()

    def test_default_memory_trial_uses_resident_runtime_and_replays_without_second_execution(self):
        from tests.test_agent_lab_memory_trial import FixtureRuntime
        runtime = FixtureRuntime()
        service = self.service(adapters=False)
        try:
            with patch.object(service, "runtime", runtime):
                request = {"clientRequestId": "default-memory", "sceneId": "memory", "spec": {}}
                admitted = service.eval_lab_trial_start(request)
                job_id = admitted["job"]["jobId"]
                deadline = time.monotonic() + 20
                while True:
                    job = service.eval_lab_trials({"jobId": job_id})["job"]
                    if job["state"] not in {"queued", "running", "cancelling"} or time.monotonic() >= deadline:
                        break
                    time.sleep(0.02)
                self.assertEqual(job["state"], "completed")
                self.assertEqual(job["result"]["qualityVerdict"], "reject")
                self.assertTrue(job["result"]["signals"]["syntheticFixture"])
                self.assertFalse(job["result"]["signals"]["personalMemoryQualityMeasured"])
                self.assertTrue(job["sessions"])
                self.assertTrue(all(service.sessions.get(item["sessionId"])["ownerAppId"] == "extension:agent-lab" for item in job["sessions"]))
                calls = len(runtime.calls)
                self.assertGreater(calls, 0)
                replay = service.eval_lab_trial_start(request)
                self.assertTrue(replay["replayed"])
                self.assertEqual(replay["job"], job)
                self.assertEqual(len(runtime.calls), calls)
                self.assertNotIn(str(self.root), json.dumps(job))
                self.assertFalse(list(service._eval_lab_trial_adapters["memory"].artifact_root.rglob("work")))
        finally:
            service.close()

    def test_host_factories_forward_explicit_adapter_registry_without_preparation(self):
        from rag_ime.agent_service import agent_service_from_environment, agent_service_from_settings
        config = PiRuntimeConfig(enabled=False, executable=None,
            agent_dir=self.root / "config", session_dir=self.root / "sessions", logs_dir=self.root / "logs")
        registry = {"scene": self.adapter}
        with patch("rag_ime.agent_service.AgentService") as create_service:
            with patch("rag_ime.agent_service.PiRuntimeConfig.from_environment", return_value=config):
                agent_service_from_environment(self.root / "paw.sqlite", eval_lab_trial_adapters=registry)
            self.assertIs(create_service.call_args.kwargs["eval_lab_trial_adapters"], registry)
            with patch("rag_ime.agent_service.pi_runtime_config_from_settings", return_value=config):
                agent_service_from_settings(self.root / "paw.sqlite", {}, eval_lab_trial_adapters=registry)
            self.assertIs(create_service.call_args.kwargs["eval_lab_trial_adapters"], registry)
        self.assertEqual(self.adapter.prepared, 0)
        self.assertEqual(self.adapter.executed, 0)


class TrialRouteTests(unittest.TestCase):
    def test_policy_and_descriptor_have_one_authority_and_exact_fields(self):
        policy = default_route_policy()
        for action, method, suffix, body, query in (
            ("get", "GET", "", None, {"jobId": "trial"}),
            ("start", "POST", "/start", {"clientRequestId": "click", "sceneId": "scene", "spec": {}}, {}),
            ("cancel", "POST", "/cancel", {"jobId": "trial"}, {}),
        ):
            path_id = f"agent.eval-lab.trials.{action}"
            path = "/api/agent/eval-lab/trials" + suffix
            route = policy.resolve(path_id)
            self.assertEqual(route.local_8766_path, path)
            self.assertFalse(route.remote_safe)
            self.assertIsNotNone(find_route(method, path))
            policy.authorize(ControlRequest(request_id="http", path_id=path_id, body=body or {}, query=query), ControlAccessContext.native())
            if body is not None:
                with self.assertRaises(ControlApiError):
                    policy.authorize(ControlRequest(request_id="extra", path_id=path_id, body={**body, "privateInput": {}}), ControlAccessContext.native())

    def test_get_passes_identity_and_post_preserves_explicit_admission(self):
        read = Mock(return_value={"jobs": []})
        value, written = handler(SimpleNamespace(eval_lab_trials=read))
        value.path = "/api/agent/eval-lab/trials?jobId=trial-1"
        value.do_GET()
        read.assert_called_once_with({"jobId": "trial-1"})
        self.assertEqual(written, [(200, {"jobs": []})])
        for action, status, method in (("start", 202, "eval_lab_trial_start"), ("cancel", 200, "eval_lab_trial_cancel")):
            body = {"jobId": "trial-1"} if action == "cancel" else {"clientRequestId": "click", "sceneId": "scene", "spec": {}}
            receipt = {"job": {"jobId": "trial-1", "state": "queued"}}
            command = Mock(return_value=receipt)
            value, written = handler(SimpleNamespace(**{method: command}))
            value.path = "/api/agent/eval-lab/trials/" + action
            value._read_json = lambda body=body: body
            value.do_POST()
            command.assert_called_once_with(body)
            self.assertEqual(written, [(status, receipt)])

    def test_read_failure_and_mutation_errors_never_leak_private_details(self):
        from rag_ime.agent_lab_trials import AgentLabTrialNotFound
        for method, path, attribute in (
            ("GET", "/api/agent/eval-lab/trials", "eval_lab_trials"),
            ("POST", "/api/agent/eval-lab/trials/start", "eval_lab_trial_start"),
        ):
            for error, status in ((AgentLabTrialConflict(), 409), (AgentLabTrialNotFound(), 404),
                                  (ValueError("private-sentinel"), 422), (TypeError("private-sentinel"), 422),
                                  (OSError("private-sentinel"), 503), (RuntimeError("private-sentinel"), 500)):
                with self.subTest(method=method, error=type(error).__name__):
                    value, written = handler(SimpleNamespace(**{attribute: Mock(side_effect=error)}))
                    value.path = path
                    value._read_json = lambda: {}
                    getattr(value, "do_" + method)()
                    self.assertEqual(written[0][0], status)
                    self.assertFalse(written[0][1]["ok"])
                    self.assertNotIn("private-sentinel", json.dumps(written))


if __name__ == "__main__":
    unittest.main()
