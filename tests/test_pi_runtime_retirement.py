from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rag_ime.agent_events import AgentEventHub
from rag_ime.agent_runtime_driver import AgentRuntimeDriver, RuntimeDriverContext
from rag_ime.agent_sessions import AgentSessionStore
from rag_ime.pi.config import PiRuntimeConfig
from rag_ime.pi.factory import PiRuntimeDriverFactory
from rag_ime.pi.protocols import normalize_protocol_version
from rag_ime.pi.runtime import PiRuntimeHostManager


class PiRuntimeRetirementTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def config(self, **changes):
        return PiRuntimeConfig(
            enabled=False,
            executable=None,
            agent_dir=self.root / "config",
            session_dir=self.root / "sessions",
            logs_dir=self.root / "logs",
            idle_timeout_seconds=0,
            **changes,
        )

    def test_default_config_and_factory_use_only_the_host_protocol(self) -> None:
        config = self.config()
        self.assertEqual(config.protocol_version, "2")
        context = RuntimeDriverContext(
            sessions=AgentSessionStore(self.root / "sessions.sqlite"),
            events=AgentEventHub(),
            tool_gateway_token="test-token",
        )
        for purpose in ("interactive", "delegated"):
            with self.subTest(purpose=purpose):
                runtime = PiRuntimeDriverFactory(config).create(
                    context, purpose=purpose
                )
                self.addCleanup(runtime.stop)
                self.assertIsInstance(runtime, PiRuntimeHostManager)
                self.assertIsInstance(runtime, AgentRuntimeDriver)
                self.assertIs(runtime.sessions, context.sessions)
                self.assertIs(runtime.events, context.events)

    def test_complete_driver_retains_runtime_checkable_property_constraints(self) -> None:
        # The full contract has properties as well as methods. Splitting its
        # consumer interfaces must retain instance checks and reject subclass
        # checks, as the original runtime_checkable Protocol did.
        with self.assertRaisesRegex(TypeError, "non-method members"):
            issubclass(PiRuntimeHostManager, AgentRuntimeDriver)

    def test_retired_protocol_is_rejected_instead_of_selecting_an_executor(
        self,
    ) -> None:
        with self.assertRaisesRegex(ValueError, "retired"):
            normalize_protocol_version("1")
        with self.assertRaisesRegex(ValueError, "retired"):
            self.config(protocol_version="1")

    def test_unknown_protocol_is_not_silently_treated_as_host(self) -> None:
        for value in ("", "0", "3", "v2"):
            with (
                self.subTest(value=value),
                self.assertRaisesRegex(ValueError, "unsupported"),
            ):
                normalize_protocol_version(value)


if __name__ == "__main__":
    unittest.main()
