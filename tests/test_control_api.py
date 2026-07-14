from __future__ import annotations

import unittest

from rag_ime.control_api import ControlApiFacade, control_route_catalog
from rag_ime.control_api.route_policy import control_route


class _Agent:
    def configuration(self):
        return {
            "ok": True,
            "configuration": {
                "schemaVersion": "rag-ime.agent-configuration.v1",
                "revision": 3,
                "revisionToken": "agent-config:3",
                "configuration": {
                    "runtime": {"enabled": True, "startup": "lazy", "idleTimeoutSeconds": 900},
                    "sessionDefaults": {
                        "resumeLastSession": True,
                        "roleId": "zhiyou-v1",
                        "roleVersion": "1",
                        "modelProfile": "deepseek/deepseek-chat",
                        "toolProfileVersion": "control-center-v1",
                    },
                    "coordination": {"enabled": False},
                },
                "sync": {"state": "synchronized", "appliedRevision": 3, "error": ""},
                "updatedAtMs": 1,
                "updatedBy": "test",
                "lastEventId": "agent-control:2",
            },
        }

    def runtime_status(self):
        return {
            "schemaVersion": "rag-ime.agent-runtime.v1",
            "enabled": True,
            "managed": True,
            "status": "ready",
            "driverId": "managed-pi",
            "runtimeKind": "pi_rpc",
            "runtimeVersion": "0.80.2",
            "piVersion": "0.80.2",
            "idleTimeoutSeconds": 900,
            "activeSessionId": None,
            "lastError": "/private/path/must-not-cross-bootstrap",
            "capabilities": {"rpc": True},
            "configurationRevision": 3,
            "configurationSyncState": "synchronized",
        }


class _Capabilities:
    def manifests(self):
        return {
            "items": [
                {
                    "schemaVersion": "rag-ime.control-tool-manifest.v1",
                    "id": "ime_memory",
                    "availability": "online",
                }
            ]
        }

    def execute(self, _payload):
        raise AssertionError("bootstrap must never execute a capability")


class ControlApiTests(unittest.TestCase):
    def test_bootstrap_is_frontend_neutral_and_redacts_runtime_errors(self) -> None:
        facade = ControlApiFacade(
            agent=_Agent(),
            capabilities=_Capabilities(),
            platform_capabilities=lambda: {"transport": "mock", "filePicker": False},
        )
        payload = facade.bootstrap()

        self.assertEqual(payload["apiVersion"], "control-api.v1")
        self.assertEqual(payload["configuration"]["revision"], 3)
        self.assertEqual(payload["runtime"]["driverId"], "managed-pi")
        self.assertNotIn("lastError", payload["runtime"])
        self.assertEqual(payload["capabilities"]["items"][0]["id"], "ime_memory")
        self.assertIn("agent.configuration.get", {item["pathId"] for item in payload["routes"]})

    def test_route_catalog_is_unique_and_internal_tool_execution_is_not_remote(self) -> None:
        routes = control_route_catalog()
        ids = [str(item["pathId"]) for item in routes]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(control_route("agent.session.events", remote=True).streaming)
        self.assertEqual(
            control_route("agent.artifact.get", remote=True).capability,
            "agent.artifacts.read",
        )
        self.assertEqual(
            control_route("agent.session.intercom.send").method,
            "POST",
        )
        with self.assertRaisesRegex(ValueError, "not available remotely"):
            control_route("agent.tool.execute", remote=True)
        with self.assertRaisesRegex(ValueError, "unknown control pathId"):
            control_route("debug.anything")


if __name__ == "__main__":
    unittest.main()
