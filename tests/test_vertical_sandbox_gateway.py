from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rag_ime.agent_sessions import AgentSessionStore
from rag_ime.agent_tools import ControlToolGateway


class _SandboxConnector:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, object]]] = []

    def execute(
        self,
        session_id: str,
        operation: str,
        args: dict[str, object],
    ) -> dict[str, object]:
        self.calls.append((session_id, operation, dict(args)))
        return {
            "summary": "SGG 沙箱执行完成",
            "sandboxRunId": "sandbox:sgg:demo",
            "traceId": "trace:sgg:demo",
            "evalRunId": "eval:sgg:demo",
        }


class VerticalSandboxGatewayTests(unittest.TestCase):
    def test_routes_plugin_tool_to_host_owned_connector(self) -> None:
        with tempfile.TemporaryDirectory(prefix="paw-sandbox-gateway-") as temporary:
            sessions = AgentSessionStore(Path(temporary) / "agent.sqlite")
            sessions.initialize()
            session = sessions.create(title="sandbox plugin", created_at_ms=1)
            connector = _SandboxConnector()
            gateway = ControlToolGateway(
                sessions=sessions,
                management=object(),
                core=object(),
                project="sandbox-test",
                sandbox_connector=connector,
            )

            response = gateway.execute(
                {
                    "schemaVersion": "rag-ime.agent-tool-call.v1",
                    "sessionId": str(session["id"]),
                    "tool": "sandbox",
                    "toolCallId": "tool:sandbox:1",
                    "args": {"op": "run", "suiteId": "sgg"},
                }
            )

        self.assertTrue(response["ok"])
        self.assertEqual(response["tool"], "sandbox")
        self.assertEqual(response["result"]["traceId"], "trace:sgg:demo")
        self.assertEqual(connector.calls[0][0], str(session["id"]))
        self.assertEqual(connector.calls[0][1], "run")
        self.assertEqual(connector.calls[0][2]["suiteId"], "sgg")
        self.assertNotIn("dbPath", response["result"])


if __name__ == "__main__":
    unittest.main()
