from __future__ import annotations

import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from rag_ime.control_api import ControlAccessContext, ControlRequest, default_route_policy
from rag_ime.debug_server import DebugRequestHandler
from rag_ime.agent_service import AgentService
from rag_ime.pi.config import PiRuntimeConfig


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


class GoldenRouteTests(unittest.TestCase):
    def test_real_service_freezes_routed_model_defaults_on_new_suite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            service = AgentService(
                db_path=root / "paw.sqlite",
                runtime_config=PiRuntimeConfig(enabled=False, executable=None, agent_dir=root / "config", session_dir=root / "sessions", logs_dir=root / "logs"),
                background_job_execution_owner=False, startup_recovery_enabled=False,
            )
            try:
                self.assertEqual(service.eval_lab_golden()["items"], [])
                response = service.eval_lab_golden_command({"action": "create", "expectedRevision": 0, "clientRequestId": "create-service", "input": {
                    "title": "Service acceptance", "scenario": "context_qa", "targetCount": 2,
                    "sources": [{"sourceId": "doc", "title": "Document", "kind": "document", "uri": "fixture:doc", "text": "Pi owns Sessions."}],
                }})
                primary = service.configuration_store.snapshot()["configuration"]["modelRouting"]["primary"]
                model = response["suite"]["judgeConfig"]
                self.assertEqual(f'{model["provider"]}/{model["model"]}', primary["modelProfile"])
                self.assertEqual(model["thinkingLevel"], primary["thinkingLevel"])
                self.assertEqual(service.eval_lab_golden()["items"][0]["suiteId"], response["suite"]["suiteId"])
                settings = service.configuration_store.snapshot()
                next_profile = "openai-codex/gpt-6-astra"
                service.configuration_store.update(
                    {"modelRouting.primary": {"modelProfile": next_profile,
                                              "thinkingLevel": "low"}},
                    expected_revision=settings["revision"], updated_by="golden-test",
                )
                next_request = {"action": "create", "expectedRevision": 0,
                                "clientRequestId": "create-after-settings", "input": {
                                    "title": "Updated settings", "scenario": "context_qa", "targetCount": 2,
                                    "sources": response["suite"]["sources"],
                                }}
                updated = service.eval_lab_golden_command(next_request)
                self.assertEqual(updated["suite"]["judgeConfig"]["model"], "gpt-6-astra")
                self.assertEqual(updated["suite"]["judgeConfig"]["thinkingLevel"], "low")
                original = service.eval_lab_golden({"suiteId": response["suite"]["suiteId"]})
                self.assertEqual(original["suite"]["judgeConfig"], model)
            finally:
                service.close()

    def test_command_route_accepts_a_concrete_command_without_confirmation(self):
        policy = default_route_policy()
        body = {"action": "create", "expectedRevision": 0, "clientRequestId": "new-1", "input": {"title": "Support"}}
        route = policy.resolve("agent.eval-lab.golden.command")
        self.assertEqual(route.local_8766_path, "/api/agent/eval-lab/golden/command")
        policy.authorize(ControlRequest(request_id="http-1", path_id="agent.eval-lab.golden.command", body=body), ControlAccessContext.native())

    def test_get_forwards_optional_suite_identity(self):
        read = Mock(return_value={"ok": True, "items": [], "suite": None})
        value, written = handler(SimpleNamespace(eval_lab_golden=read))
        value.path = "/api/agent/eval-lab/golden?suiteId=suite-1"
        value.do_GET()
        read.assert_called_once_with({"suiteId": "suite-1"})
        self.assertEqual(written[0][0], 200)

    def test_post_preserves_command_identity_and_returns_real_receipt(self):
        receipt = {"ok": True, "suite": {"suiteId": "suite-1"}, "clientRequestId": "review-1", "replayed": False, "job": None}
        command = Mock(return_value=receipt)
        value, written = handler(SimpleNamespace(eval_lab_golden_command=command))
        value.path = "/api/agent/eval-lab/golden/command"
        body = {"action": "review_case", "suiteId": "suite-1", "expectedRevision": 2, "clientRequestId": "review-1", "input": {"caseId": "case-1", "verdict": "approved"}}
        value._read_json = lambda: body
        value.do_POST()
        command.assert_called_once_with(body)
        self.assertEqual(written, [(200, receipt)])

    def test_temporary_read_failure_is_safe_and_distinct_from_empty_suite(self):
        read = Mock(side_effect=OSError("secret /private/local.sqlite"))
        value, written = handler(SimpleNamespace(eval_lab_golden=read))
        value.path = "/api/agent/eval-lab/golden"
        value.do_GET()
        self.assertEqual(written[0][0], 503)
        self.assertFalse(written[0][1]["ok"])
        self.assertNotIn("/private", str(written))


if __name__ == "__main__":
    unittest.main()
