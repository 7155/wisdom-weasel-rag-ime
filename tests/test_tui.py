import os
import json
import unittest
from pathlib import Path
from unittest.mock import patch
import urllib.request

from rag_ime.tui import (
    GatewayRuntimeFacade,
    build_app,
    _command_help,
    _command_source,
    _inspector_text,
    _project_transcript,
    _render_messages,
    _render_command_result,
    _session_heading,
    _detail_text,
    _render_room,
    _render_session,
    _room_member_count,
    default_db_path,
    default_gateway_url,
    main,
    snapshot,
)


class FakeService:
    def __init__(self):
        self.session_payload = None
        self.room_payload = None
        self.created_payloads = []
        self.abort_calls = []

    def list_sessions(self, payload=None):
        self.session_payload = payload
        return {
            "items": [
                {"id": "s1", "title": "Build", "status": "active", "phase": "running", "roomParticipant": "r1"},
            ],
            "activeSessionId": "s1",
        }

    def messages(self, session_id):
        return {"messages": [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi"}]}

    def create_session(self, payload):
        self.created_payloads.append(dict(payload))
        return {
            "ok": True,
            "session": {
                "id": "s-created",
                "title": str(payload.get("title") or "New"),
                "status": "idle",
                "workspaceRoots": list(payload.get("workspaceRoots") or []),
            },
        }

    def prompt(self, session_id, payload):
        self.prompt_call = (session_id, payload)
        return {"ok": True}

    def abort(self, session_id):
        self.abort_calls.append(session_id)
        return {"ok": True, "status": "cancellation_pending"}

    def command_catalog(self, session_id):
        return {
            "items": [
                {"name": "paw-status", "source": "extension"},
                {"name": "skill:paw-review", "source": "skill"},
            ]
        }

    def invoke_command(self, session_id, payload):
        self.command_call = (session_id, payload)
        return {
            "name": "paw-status",
            "result": {"message": "Goal [active]: Ship the TUI"},
        }

    def list_rooms(self, payload=None):
        self.room_payload = payload
        return {
            "items": [
                {
                    "id": "r1",
                    "title": "Review",
                    "routingPolicy": "single_leader",
                    "participants": [{"id": "p1"}, {"id": "p2"}],
                },
            ]
        }


class TuiProjectionTests(unittest.TestCase):
    def test_snapshot_reads_session_and_room_projections(self):
        service = FakeService()
        self.assertEqual(
            snapshot(service),
            {
                "sessions": [
                    {
                        "id": "s1",
                        "title": "Build",
                        "status": "active",
                        "phase": "running",
                        "roomParticipant": "r1",
                    }
                ],
                "rooms": [
                    {
                        "id": "r1",
                        "title": "Review",
                        "routingPolicy": "single_leader",
                        "participants": [{"id": "p1"}, {"id": "p2"}],
                    }
                ],
                "activeSessionId": "s1",
            },
        )
        self.assertEqual(service.session_payload, {"limit": 500})
        self.assertEqual(service.room_payload, {"limit": 200})

    def test_messages_and_delivery_payload(self):
        service = FakeService()
        rendered = _render_messages(service, "s1")
        self.assertIn("user: hello", rendered)
        service.prompt("s1", {"message": "change", "delivery": "steer"})
        self.assertEqual(service.prompt_call, ("s1", {"message": "change", "delivery": "steer"}))

    def test_messages_render_structured_public_blocks(self):
        service = FakeService()
        service.messages = lambda _session_id: {
            "messages": [
                {
                    "role": "assistant",
                    "blocks": [{"type": "text", "data": {"text": "done"}}],
                }
            ]
        }
        self.assertEqual(_render_messages(service, "s1"), "assistant: done")

    def test_transcript_projects_runtime_rows_without_retry_or_terminal_duplicates(self):
        payload = {
            "items": [
                {
                    "id": "message:user:1",
                    "clientMessageId": "client:1",
                    "turnId": "turn:1",
                    "role": "user",
                    "content": "大家好",
                },
                {
                    "id": "message:user:1",
                    "clientMessageId": "client:1",
                    "turnId": "turn:1",
                    "role": "user",
                    "content": "大家好",
                },
                {
                    "id": "message:assistant:1",
                    "turnId": "turn:1",
                    "role": "assistant",
                    "status": "failed",
                    "blocks": [
                        {
                            "type": "error",
                            "data": {"message": "模型服务未能生成最终回复"},
                        }
                    ],
                },
            ],
            "liveEvents": [
                {
                    "eventId": "event:tool:1",
                    "turnId": "turn:1",
                    "eventType": "tool_started",
                    "payload": {
                        "toolId": "knowledge",
                        "operation": "search",
                        "summary": "正在检索实现证据",
                    },
                },
                {
                    "eventId": "event:failed:1",
                    "turnId": "turn:1",
                    "eventType": "turn_failed",
                    "payload": {"error": "模型服务未能生成最终回复"},
                },
            ],
        }
        entries = _project_transcript(payload, "s1")
        self.assertEqual(
            [entry.body for entry in entries].count("大家好"),
            1,
        )
        self.assertEqual(
            [entry.body for entry in entries].count("模型服务未能生成最终回复"),
            1,
        )
        self.assertTrue(
            any(entry.kind == "tool" and "knowledge" in entry.title for entry in entries)
        )

    def test_session_heading_and_inspector_project_owned_runtime_facts(self):
        heading = _session_heading(
            {
                "id": "s1",
                "title": "Build",
                "modelProfile": "openai-codex/gpt-5.4",
                "workspaceRoots": ["/workspace"],
            },
            {"status": "busy"},
        )
        self.assertIn("Build  ·  busy", heading)
        self.assertIn("openai-codex/gpt-5.4  ·  /workspace", heading)
        inspector = _inspector_text(
            {
                "goal": {"text": "完成 TUI"},
                "todo": {
                    "items": [
                        {"status": "completed"},
                        {"status": "active"},
                    ]
                },
                "messageQueue": {"steering": [{"id": "q1"}], "followUp": []},
            },
            {"items": [{"name": "workflow", "source": "extension"}]},
        )
        self.assertIn("/workflow", inspector)
        self.assertIn("Goal: 完成 TUI", inspector)
        self.assertIn("Todo: 1/2", inspector)
        self.assertIn("等待投递: 1", inspector)

    def test_command_help_only_projects_enabled_extension_commands(self):
        self.assertEqual(
            _command_help(FakeService(), "s1"),
            "已启用 Pi Package 命令（在输入框直接执行）: /paw-status",
        )

    def test_command_source_uses_live_pi_catalog(self):
        service = FakeService()
        self.assertEqual(_command_source(service, "s1", "/paw-status"), "extension")
        self.assertEqual(
            _command_source(service, "s1", "/skill:paw-review"),
            "skill",
        )
        self.assertIsNone(_command_source(service, "s1", "/goal"))

    def test_command_result_is_visible_without_a_model_turn(self):
        service = FakeService()
        receipt = service.invoke_command("s1", {"command": "/paw-status"})
        self.assertEqual(
            _render_command_result(receipt),
            "/paw-status: Goal [active]: Ship the TUI",
        )
        self.assertEqual(service.command_call, ("s1", {"command": "/paw-status"}))

    def test_render_session_marks_active_and_status(self):
        rendered = _render_session({"id": "s1", "title": "Build", "status": "active"}, "s1")
        self.assertIn("active", rendered)
        self.assertIn("Build", rendered)
        self.assertIn("s1", rendered)

    def test_render_room_includes_routing_policy_and_members(self):
        rendered = _render_room({
            "id": "r1",
            "title": "Review",
            "routingPolicy": "single_leader",
            "participants": [{"id": "p1"}, {"id": "p2"}],
        })
        self.assertIn("Review", rendered)
        self.assertIn("single_leader", rendered)
        self.assertIn("2", rendered)

    def test_room_member_count_from_participants_and_count(self):
        self.assertEqual(
            _room_member_count(
                {"participants": [{"id": "p1"}, {"id": "p2"}], "participantCount": 1}
            ),
            2,
        )
        self.assertEqual(_room_member_count({"participantCount": "3"}), 3)

    def test_detail_text(self):
        text = _detail_text({"id": "s1", "title": "Build", "status": "active"}, "session", active_session_id="s1")
        self.assertIn("Session*", text)
        self.assertIn("ID: s1", text)
        room_bound = _detail_text(
            {
                "id": "s1",
                "title": "Build",
                "status": "active",
                "roomParticipant": {"roomId": "room-1", "participantId": "participant-1"},
            },
            "session",
        )
        self.assertIn("Room: room-1", room_bound)

    def test_detail_text_projects_room_participants_and_tasks(self):
        text = _detail_text({"id": "r1", "title": "Review", "participants": [{"title": "Alice", "status": "active"}], "tasks": [{"title": "Inspect", "status": "running"}]}, "room")
        self.assertIn("Participants: Alice (active)", text)
        self.assertIn("Tasks: Inspect (running)", text)

    def test_detail_text_projects_tool_and_subagent_states(self):
        text = _detail_text({"id": "s1", "title": "Build", "status": "active", "tools": [{"title": "pytest", "status": "completed"}], "subAgents": [{"title": "Reviewer", "phase": "running"}]}, "session")
        self.assertIn("Tools: pytest (completed)", text)
        self.assertIn("SubAgents: Reviewer (running)", text)

    def test_detail_text_omits_absent_runtime_state(self):
        text = _detail_text({"id": "s1", "title": "Build"}, "session")
        self.assertNotIn("Tools:", text)
        self.assertNotIn("SubAgents:", text)

    def test_default_db_path_uses_env_when_present(self):
        home = str(Path.home())
        os.environ["RAG_IME_DB_PATH"] = str(Path(home) / "tmp" / "agent.sqlite")
        try:
            self.assertTrue(str(default_db_path()).endswith("tmp/agent.sqlite"))
        finally:
            os.environ.pop("RAG_IME_DB_PATH", None)

    def test_default_db_path_uses_installed_product_database(self):
        previous = os.environ.pop("RAG_IME_DB_PATH", None)
        try:
            self.assertEqual(
                default_db_path(),
                Path.home()
                / "Library"
                / "Application Support"
                / "RagIme"
                / "rag-ime.sqlite",
            )
        finally:
            if previous is not None:
                os.environ["RAG_IME_DB_PATH"] = previous

    def test_default_gateway_url_uses_dedicated_runtime_owner(self):
        previous = os.environ.pop("RAG_IME_AGENT_GATEWAY_URL", None)
        try:
            self.assertEqual(default_gateway_url(), "http://127.0.0.1:8768")
        finally:
            if previous is not None:
                os.environ["RAG_IME_AGENT_GATEWAY_URL"] = previous

    def test_gateway_facade_projects_and_mutates_through_http(self):
        requests = []

        class Response:
            def __init__(self, payload):
                self.payload = payload

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return json.dumps(self.payload).encode("utf-8")

        def urlopen(request, *, timeout):
            self.assertIsInstance(request, urllib.request.Request)
            requests.append((request.full_url, request.get_method(), request.data, timeout))
            if request.get_method() == "POST":
                return Response({"ok": True, "name": "paw-status", "result": {"message": "ready"}})
            return Response({"ok": True, "items": []})

        service = GatewayRuntimeFacade(
            "http://127.0.0.1:8768",
            timeout_seconds=7,
            urlopen=urlopen,
        )
        service.list_sessions({"limit": 5})
        service.list_rooms({"limit": 3})
        service.create_session(
            {
                "title": "New",
                "workspaceRoots": ["/workspace"],
                "executionMode": "per_action",
            }
        )
        service.messages("agent:one/two")
        service.prompt("agent:one/two", {"message": "hello", "delivery": "prompt"})
        service.abort("agent:one/two")
        service.command_catalog("agent:one/two")
        service.invoke_command("agent:one/two", {"command": "/paw-status"})

        self.assertEqual(requests[0][0], "http://127.0.0.1:8768/api/agent/sessions?limit=5")
        self.assertEqual(requests[1][0], "http://127.0.0.1:8768/api/agent/rooms?limit=3")
        self.assertEqual(requests[2][0], "http://127.0.0.1:8768/api/agent/sessions")
        self.assertEqual(requests[2][1], "POST")
        self.assertIn("agent%3Aone%2Ftwo/messages", requests[3][0])
        self.assertEqual(requests[4][1], "POST")
        self.assertEqual(
            json.loads(requests[4][2].decode("utf-8")),
            {"message": "hello", "delivery": "prompt"},
        )
        self.assertEqual(requests[4][3], 300.0)
        self.assertIn("agent%3Aone%2Ftwo/abort", requests[5][0])
        self.assertEqual(json.loads(requests[5][2].decode("utf-8")), {})
        self.assertEqual(requests[-1][3], 7.0)

    def test_gateway_facade_turn_timeout_is_a_recoverable_runtime_error(self):
        def urlopen(_request, *, timeout):
            self.assertEqual(timeout, 12.0)
            raise TimeoutError("provider stalled")

        service = GatewayRuntimeFacade(
            "http://127.0.0.1:8768",
            timeout_seconds=3,
            turn_timeout_seconds=12,
            urlopen=urlopen,
        )
        with self.assertRaisesRegex(
            RuntimeError,
            "Pi turn may still be running",
        ):
            service.prompt("s1", {"message": "hello"})

    def test_gateway_facade_rejects_non_loopback_runtime_owner(self):
        with self.assertRaisesRegex(ValueError, "loopback"):
            GatewayRuntimeFacade("https://example.com")

    def test_main_no_runtime_owner_uses_gateway_not_local_service(self):
        class App:
            def run(self):
                return None

        gateway_service = FakeService()
        with (
            patch("rag_ime.tui.build_gateway_service", return_value=gateway_service) as gateway,
            patch("rag_ime.tui.build_agent_service") as local,
            patch("rag_ime.tui.build_app", return_value=App()) as build,
        ):
            self.assertEqual(
                main(argv=["--no-runtime-owner", "--gateway-url", "http://127.0.0.1:18768"]),
                0,
            )
        gateway.assert_called_once_with(gateway_url="http://127.0.0.1:18768")
        local.assert_not_called()
        build.assert_called_once_with(gateway_service, session_page_size=20, room_page_size=20)


class InteractiveFakeService(FakeService):
    def __init__(self):
        super().__init__()
        self.prompt_calls = []
        self.sessions = [
            {
                "id": "s1",
                "title": "First",
                "status": "idle",
                "modelProfile": "pi/default",
                "workspaceRoots": ["/workspace/first"],
            },
            {
                "id": "s2",
                "title": "Second",
                "status": "idle",
                "modelProfile": "pi/default",
                "workspaceRoots": ["/workspace/second"],
            },
        ]
        self.message_payloads = {
            "s1": [{"role": "assistant", "content": "first"}],
            "s2": [{"role": "assistant", "content": "second"}],
        }

    def list_sessions(self, payload=None):
        self.session_payload = payload
        return {
            "items": list(self.sessions),
            "activeSessionId": "s1",
        }

    def messages(self, session_id):
        return {"messages": list(self.message_payloads[session_id])}

    def prompt(self, session_id, payload):
        self.prompt_calls.append((session_id, dict(payload)))
        self.message_payloads[session_id].append(
            {"role": "user", "content": str(payload.get("message") or "")}
        )
        return {"ok": True}

    def command_catalog(self, session_id):
        return {"items": [{"name": "paw-status", "source": "extension"}]}

    def create_session(self, payload):
        self.created_payloads.append(dict(payload))
        session = {
            "id": "s-created",
            "title": str(payload.get("title") or "New"),
            "status": "idle",
            "modelProfile": "pi/default",
            "workspaceRoots": list(payload.get("workspaceRoots") or []),
        }
        self.sessions.insert(0, session)
        self.message_payloads["s-created"] = []
        return {"ok": True, "session": session}


class TuiInteractionTests(unittest.IsolatedAsyncioTestCase):
    async def test_selection_drives_detail_and_enter_sends_to_selected_session(self):
        from textual.widgets import ListView, Static, TextArea

        service = InteractiveFakeService()
        app = build_app(service)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(0.05)
            for _ in range(40):
                sessions = app.query_one("#sessions", ListView)
                if len(sessions) == 2:
                    break
                await pilot.pause(0.05)
            self.assertEqual(len(sessions), 2)

            sessions.focus()
            sessions.index = 1
            await pilot.pause(0.1)
            heading = str(app.query_one("#session-header", Static).renderable)
            self.assertIn("Second", heading)
            self.assertIn("/workspace/second", heading)

            app.action_focus_input()
            field = app.query_one("#prompt-input", TextArea)
            field.text = "hello\nfrom tui"
            await pilot.press("enter")
            for _ in range(40):
                if service.prompt_calls:
                    break
                await pilot.pause(0.05)

            self.assertEqual(service.prompt_calls[0][0], "s2")
            payload = service.prompt_calls[0][1]
            self.assertEqual(payload["message"], "hello\nfrom tui")
            self.assertEqual(payload["delivery"], "prompt")
            self.assertTrue(str(payload["clientMessageId"]).startswith("tui:"))

            for _ in range(40):
                if not app._prompt_in_flight:
                    break
                await pilot.pause(0.05)
            field.text = "steer from tui"
            await pilot.press("ctrl+s")
            for _ in range(40):
                if len(service.prompt_calls) == 2:
                    break
                await pilot.pause(0.05)
            self.assertEqual(service.prompt_calls[1][0], "s2")
            self.assertEqual(service.prompt_calls[1][1]["message"], "steer from tui")
            self.assertEqual(service.prompt_calls[1][1]["delivery"], "steer")

    async def test_shift_enter_keeps_multiline_draft_without_sending(self):
        from textual.widgets import TextArea

        service = InteractiveFakeService()
        app = build_app(service)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(0.05)
            for _ in range(40):
                field = app.query_one("#prompt-input", TextArea)
                if not field.disabled:
                    break
                await pilot.pause(0.05)
            app.action_focus_input()
            field.text = "first line"
            field.move_cursor((0, len(field.text)))
            await pilot.press("shift+enter")
            await pilot.pause(0.05)
            self.assertEqual(field.text, "first line\n")
            self.assertEqual(service.prompt_calls, [])

    async def test_context_refresh_preserves_focused_draft_and_stop_targets_session(self):
        from textual.widgets import TextArea

        service = InteractiveFakeService()
        app = build_app(service)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(0.05)
            for _ in range(40):
                field = app.query_one("#prompt-input", TextArea)
                if not field.disabled:
                    break
                await pilot.pause(0.05)
            app.action_focus_input()
            field.text = "do not lose this draft"
            app._apply_context(
                "s1",
                {
                    "items": [{"id": "m1", "role": "assistant", "content": "working"}],
                    "status": "busy",
                    "liveEvents": [
                        {
                            "eventId": "e1",
                            "eventType": "tool_started",
                            "payload": {"toolId": "read", "summary": "reading source"},
                        }
                    ],
                },
                {"items": []},
            )
            await pilot.pause(0.05)
            self.assertEqual(field.text, "do not lose this draft")
            self.assertTrue(field.has_focus)
            self.assertTrue(any(entry.kind == "tool" for entry in app._transcript_entries))

            app.action_abort()
            for _ in range(40):
                if service.abort_calls:
                    break
                await pilot.pause(0.05)
            self.assertEqual(service.abort_calls, ["s1"])

    async def test_new_session_form_shows_workspace_and_never_grants_full_trust(self):
        from textual.widgets import Input, Select, TextArea

        service = InteractiveFakeService()
        app = build_app(service)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(0.1)
            app.action_new_session()
            await pilot.pause(0.1)
            title = app.screen.query_one("#new-session-title", Input)
            workspace = app.screen.query_one("#new-session-workspace", Input)
            execution = app.screen.query_one("#new-session-execution", Select)
            self.assertTrue(workspace.value)
            title.value = "TUI development"
            workspace.value = "/workspace/new"
            execution.value = "workspace_managed"
            await pilot.click("#new-session-submit")
            for _ in range(40):
                if service.created_payloads:
                    break
                await pilot.pause(0.05)
            payload = service.created_payloads[0]
            self.assertEqual(payload["title"], "TUI development")
            self.assertEqual(payload["workspaceRoots"], ["/workspace/new"])
            self.assertEqual(payload["executionMode"], "workspace_managed")
            self.assertEqual(
                payload["workspaceScopeConfirmation"],
                "APPROVE_WORKSPACE_SCOPE",
            )
            self.assertNotIn("dangerousModeConfirmation", payload)
            self.assertIsInstance(
                app.query_one("#prompt-input", TextArea),
                TextArea,
            )

    async def test_room_projection_disables_session_input(self):
        from textual.widgets import TextArea

        app = build_app(InteractiveFakeService())
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(0.05)
            for _ in range(40):
                if not app.query_one("#prompt-input", TextArea).disabled:
                    break
                await pilot.pause(0.05)
            app.action_focus_rooms()
            await pilot.pause(0.1)
            self.assertTrue(app.query_one("#prompt-input", TextArea).disabled)


if __name__ == "__main__":
    unittest.main()
