from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from rag_ime.agent_composition import build_room_stores, build_session_applications
from rag_ime.agent_configuration import AgentConfigurationStore
from rag_ime.agent_command_receipts import AgentCommandReceiptStore
from rag_ime.agent_delegation import AgentDelegationCoordinator
from rag_ime.agent_events import AgentEventHub
from rag_ime.agent_media import AgentMediaStore
from rag_ime.rooms.store import AgentRoomStore
from rag_ime.agent_runtime_driver import RuntimeDriverFactory
from rag_ime.agent_sessions import AgentSessionStore


class AgentCompositionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="paw-composition-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.db = self.root / "test.sqlite"

    def test_session_list_constructs_without_runtime_provider_or_worker_start(self):
        stores = build_room_stores(self.db, session_root=self.root / "sessions")
        self.addCleanup(stores.rooms.close)
        sessions = AgentSessionStore(self.db)
        sessions.initialize()
        created = sessions.create(title="offline source")
        events = AgentEventHub()
        self.addCleanup(events.close)
        runtime = Mock(side_effect=AssertionError("list must not initialize a Runtime"))
        apps = build_session_applications(
            sessions=sessions, rooms=stores.rooms, runtime_provider=runtime,
            runtime_factory=Mock(spec=RuntimeDriverFactory),
            configuration_store=AgentConfigurationStore(self.db),
            delegation=Mock(spec=AgentDelegationCoordinator), media=AgentMediaStore(self.db),
            events=events, command_receipts=AgentCommandReceiptStore(self.db),
            runtime_status=lambda: {"activeSessionId": ""}, pending_memory_bootstrap=lambda _: {},
            probe_memory_maintenance=lambda *_args, **_kwargs: {},
            prompt_with_checkpoint=lambda **_kwargs: {},
        )
        listing = apps.application.list_sessions()
        self.assertEqual([item["id"] for item in listing["items"]], [created["id"]])
        self.assertIs(apps.policy.sessions, sessions)
        self.assertIs(apps.branching.sessions, sessions)
        self.assertFalse(runtime.called)
        self.assertFalse(apps.application.delegation.mock_calls)

    def test_room_group_closes_connection_on_partial_initialization_failure(self):
        original_close = AgentRoomStore.close
        closed = []
        def close(store):
            closed.append(store)
            original_close(store)
        with (
            patch("rag_ime.agent_composition.AgentRoomWorkStore.initialize", side_effect=RuntimeError("schema initialization failed")),
            patch.object(AgentRoomStore, "close", side_effect=close, autospec=True),
            self.assertRaisesRegex(RuntimeError, "schema initialization failed"),
        ):
            build_room_stores(self.db, session_root=self.root / "sessions")
        self.assertEqual(len(closed), 1)
        # A fresh construction can use the same durable DB; no rows/schema were reset.
        stores = build_room_stores(self.db, session_root=self.root / "sessions")
        self.addCleanup(stores.rooms.close)
        self.assertEqual(stores.rooms.list(), [])
