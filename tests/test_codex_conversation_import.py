from __future__ import annotations

import importlib.util
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from rag_ime.agent_events import AgentEventHub
from rag_ime.agent_sessions import AgentSessionStore
from rag_ime.codex_conversation_import import (
    CodexConversationIncomplete,
    discover_codex_conversation_sources,
    import_codex_conversation,
    parse_codex_conversation,
)
from rag_ime.pi_runtime_public import pi_message_is_public
from rag_ime.pi_runtime import PiRuntimeConfig
from rag_ime.pi_runtime_v2 import PiRuntimeHostManager
from rag_ime.pi_runtime_transcript import durable_branch_messages


class CodexConversationImportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="paw-codex-conversation-")
        self.root = Path(self.tmp.name)
        self.source = self.root / "rollout-codex-source.jsonl"
        self.session_dir = self.root / "Agent" / "sessions"
        self.store = AgentSessionStore(self.root / "rag-ime.sqlite")
        self.store.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write_source(self, *, complete: bool = True) -> None:
        rows: list[dict[str, object]] = [
            {
                "timestamp": "2026-08-25T00:47:28.475Z",
                "type": "session_meta",
                "payload": {
                    "id": "01a03662-e4a8-7ca2-bfc1-931c3f98bc55",
                    "cwd": "/Volumes/undo 4t/git/personal-agent-workbench",
                },
            },
            {
                "timestamp": "2026-08-25T00:47:29.000Z",
                "type": "turn_context",
                "payload": {
                    "cwd": "/Volumes/undo 4t/git/personal-agent-workbench",
                    "model": "gpt-5.6-sol",
                },
            },
            {
                "timestamp": "2026-08-25T00:47:29.100Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "developer",
                    "content": [{"type": "input_text", "text": "private bootstrap"}],
                },
            },
            {
                "timestamp": "2026-08-25T00:47:29.200Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "id": "user-wrapper",
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": "<recommended_plugins>internal catalog</recommended_plugins>",
                        }
                    ],
                },
            },
            {
                "timestamp": "2026-08-25T00:47:29.536Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "id": "user-visible",
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": "把 ion-dist 打成 ZIP",
                        }
                    ],
                },
            },
            {
                "timestamp": "2026-08-25T00:47:30.000Z",
                "type": "response_item",
                "payload": {"type": "reasoning", "summary": []},
            },
            {
                "timestamp": "2026-08-25T00:47:41.997Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "id": "assistant-commentary",
                    "role": "assistant",
                    "phase": "commentary",
                    "content": [
                        {"type": "output_text", "text": "我先核对源目录。"}
                    ],
                },
            },
            {
                "timestamp": "2026-08-25T00:47:43.000Z",
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call",
                    "name": "exec",
                    "input": "private command",
                },
            },
            {
                "timestamp": "2026-08-25T00:47:44.000Z",
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call_output",
                    "output": "private output",
                },
            },
            {
                "timestamp": "2026-08-25T00:48:08.766Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "id": "assistant-final",
                    "role": "assistant",
                    "phase": "final_answer",
                    "content": [
                        {"type": "output_text", "text": "已打包并校验通过。"}
                    ],
                },
            },
        ]
        if complete:
            rows.append(
                {
                    "timestamp": "2026-08-25T00:48:08.822Z",
                    "type": "event_msg",
                    "payload": {"type": "task_complete"},
                }
            )
        self.source.write_text(
            "".join(f"{json.dumps(row, ensure_ascii=False)}\n" for row in rows),
            encoding="utf-8",
        )

    def test_parse_keeps_only_visible_conversation_messages(self) -> None:
        self._write_source()

        conversation = parse_codex_conversation(self.source)

        self.assertTrue(conversation.complete)
        self.assertEqual(
            conversation.source_session_id,
            "01a03662-e4a8-7ca2-bfc1-931c3f98bc55",
        )
        self.assertEqual(conversation.model, "gpt-5.6-sol")
        self.assertEqual(
            [(message.role, message.text, message.phase) for message in conversation.messages],
            [
                ("user", "把 ion-dist 打成 ZIP", ""),
                ("assistant", "我先核对源目录。", "commentary"),
                ("assistant", "已打包并校验通过。", "final_answer"),
            ],
        )
        self.assertEqual(
            conversation.omitted_kinds,
            ("developer", "reasoning", "runtime-context", "tool-call", "tool-output"),
        )

    def test_parse_keeps_the_rollout_identity_when_history_has_session_metadata(self) -> None:
        self._write_source()
        rows = [
            json.loads(line)
            for line in self.source.read_text(encoding="utf-8").splitlines()
        ]
        rows.insert(
            1,
            {
                "timestamp": "2026-08-25T00:47:28.500Z",
                "type": "session_meta",
                "payload": {
                    "id": "01999999-9999-7999-8999-999999999999",
                    "cwd": "/older/resumed/history",
                    "source": "cli",
                },
            },
        )
        self.source.write_text(
            "".join(f"{json.dumps(row)}\n" for row in rows),
            encoding="utf-8",
        )

        conversation = parse_codex_conversation(self.source)

        self.assertEqual(
            conversation.source_session_id,
            "01a03662-e4a8-7ca2-bfc1-931c3f98bc55",
        )

    def test_import_registers_one_idempotent_paw_conversation(self) -> None:
        self._write_source()

        imported = import_codex_conversation(
            self.source,
            sessions=self.store,
            session_dir=self.session_dir,
            title="ion-dist 压缩",
        )

        self.assertEqual(imported["status"], "imported")
        self.assertEqual(imported["messageCount"], 3)
        session = imported["session"]
        self.assertEqual(session["title"], "ion-dist 压缩")
        self.assertEqual(session["status"], "idle")
        self.assertEqual(session["messageCount"], 3)
        self.assertEqual(session["modelProfile"], "openai-codex/gpt-5.6-sol")
        self.assertEqual(session["createdAtMs"], 1787618848475)
        self.assertEqual(session["updatedAtMs"], 1787618888766)

        binding = self.store.runtime_binding(str(session["id"]))
        self.assertIsNotNone(binding)
        assert binding is not None
        self.assertEqual(binding["state"], "prepared")
        self.assertEqual(
            binding["externalSessionId"],
            "codex-01a03662-e4a8-7ca2-bfc1-931c3f98bc55",
        )
        self.assertEqual(binding["metadata"]["externalProvider"], "codex")
        self.assertEqual(binding["metadata"]["importFidelity"], "conversation-text")
        self.assertNotIn("sourcePath", binding["metadata"])

        transcript = Path(str(binding["transcriptRef"]))
        self.assertTrue(transcript.is_file())
        self.assertEqual(transcript.stat().st_mode & 0o777, 0o600)
        rows = [
            json.loads(line)
            for line in transcript.read_text(encoding="utf-8").splitlines()
            if line
        ]
        self.assertEqual(rows[0]["type"], "session")
        self.assertEqual(rows[0]["version"], 3)
        self.assertEqual(rows[1]["customType"], "paw.external-conversation.v1")
        messages, _entries = durable_branch_messages(
            rows,
            leaf_id=str(rows[-1]["id"]),
        )
        self.assertEqual(len(messages), 3)
        self.assertTrue(all(pi_message_is_public(message) for message in messages))

        runtime = PiRuntimeHostManager(
            config=PiRuntimeConfig(
                enabled=False,
                executable=None,
                agent_dir=self.root / "Agent" / "config",
                session_dir=self.session_dir,
                logs_dir=self.root / "Agent" / "logs",
            ),
            sessions=self.store,
            events=AgentEventHub(),
        )
        snapshot = runtime.session_snapshot(str(session["id"]))
        self.assertEqual(
            [message["role"] for message in snapshot["messages"]],
            ["user", "assistant", "assistant"],
        )

        # Opening a prepared imported Session lets the Runtime refresh its
        # protocol metadata. Import identity must survive that refresh because
        # the external Pi session id and transcript provenance remain stable.
        self.store.bind_runtime_session(
            str(session["id"]),
            driver_id="managed-pi",
            runtime_kind="pi_rpc",
            external_session_id=str(binding["externalSessionId"]),
            transcript_ref=str(binding["transcriptRef"]),
            branch_anchor=str(binding["branchAnchor"]),
            binding_state="active",
            metadata={"protocolVersion": "2"},
        )

        repeated = import_codex_conversation(
            self.source,
            sessions=self.store,
            session_dir=self.session_dir,
            title="ignored on repeat",
        )
        self.assertEqual(repeated["status"], "already_imported")
        self.assertEqual(repeated["session"]["id"], session["id"])
        self.assertEqual(len(self.store.list()), 1)
        self.assertEqual(len(list(self.session_dir.glob("*.jsonl"))), 1)

    def test_incomplete_codex_session_is_rejected_by_default(self) -> None:
        self._write_source(complete=False)

        with self.assertRaisesRegex(
            CodexConversationIncomplete,
            "has no task_complete marker",
        ):
            import_codex_conversation(
                self.source,
                sessions=self.store,
                session_dir=self.session_dir,
            )

        self.assertEqual(self.store.list(), [])
        self.assertFalse(self.session_dir.exists())

    def test_discovery_deduplicates_by_embedded_session_identity(self) -> None:
        local_root = self.root / "codex-local"
        external_root = self.root / "codex-external"
        local_root.mkdir()
        external_root.mkdir()

        def write_rollout(path: Path, session_id: str, *, padding: str = "") -> None:
            rows = [
                {
                    "timestamp": "2026-08-25T00:47:28.475Z",
                    "type": "session_meta",
                    "payload": {"id": session_id, "cwd": self.root.as_posix()},
                },
                {
                    "timestamp": "2026-08-25T00:47:29.000Z",
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": f"hello {padding}"}],
                    },
                },
            ]
            path.write_text(
                "".join(f"{json.dumps(row)}\n" for row in rows),
                encoding="utf-8",
            )

        session_a = "01a00000-0000-7000-8000-00000000000a"
        session_b = "01a00000-0000-7000-8000-00000000000b"
        session_c = "01a00000-0000-7000-8000-00000000000c"
        rollout_b = local_root / "rollout-b.jsonl"
        rollout_a_old = external_root / "rollout-a-old.jsonl"
        rollout_a_new = external_root / "rollout-a-new.jsonl"
        rollout_c = external_root / "rollout-c.jsonl"
        write_rollout(rollout_b, session_b)
        write_rollout(rollout_a_old, session_a)
        write_rollout(rollout_a_new, session_a, padding="newer-and-longer")
        write_rollout(rollout_c, session_c)
        (external_root / "not-a-session.jsonl").write_text("{}\n", encoding="utf-8")

        state_db = self.root / "state.sqlite"
        with sqlite3.connect(state_db) as connection:
            connection.execute(
                "CREATE TABLE threads(id TEXT PRIMARY KEY, rollout_path TEXT NOT NULL, title TEXT NOT NULL)"
            )
            # Historical state can contain a stale alias: A points at B's
            # physical rollout. Embedded session_meta.id remains authoritative.
            connection.executemany(
                "INSERT INTO threads(id, rollout_path, title) VALUES (?, ?, ?)",
                [
                    (session_a, rollout_b.as_posix(), "Title A"),
                    (session_b, rollout_b.as_posix(), "Title B"),
                ],
            )

        discovery = discover_codex_conversation_sources(
            source_roots=[local_root, external_root],
            state_db=state_db,
        )

        self.assertEqual(
            [source.source_session_id for source in discovery.sources],
            [session_a, session_b, session_c],
        )
        sources = {source.source_session_id: source for source in discovery.sources}
        self.assertEqual(sources[session_a].path, rollout_a_new.resolve())
        self.assertEqual(sources[session_a].title, "Title A")
        self.assertEqual(sources[session_a].candidate_count, 2)
        self.assertTrue(sources[session_a].indexed)
        self.assertFalse(sources[session_c].indexed)
        self.assertEqual(discovery.state_path_mismatches, 1)
        self.assertEqual(discovery.files_without_session_meta, 1)

    def test_bulk_cli_imports_multiple_roots_and_can_be_rerun(self) -> None:
        local_root = self.root / "bulk-local"
        external_root = self.root / "bulk-external"
        local_root.mkdir()
        external_root.mkdir()

        def write_rollout(path: Path, session_id: str, *, complete: bool) -> None:
            rows: list[dict[str, object]] = [
                {
                    "timestamp": "2026-08-25T00:47:28.475Z",
                    "type": "session_meta",
                    "payload": {"id": session_id, "cwd": self.root.as_posix()},
                },
                {
                    "timestamp": "2026-08-25T00:47:29.000Z",
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": session_id}],
                    },
                },
                {
                    "timestamp": "2026-08-25T00:47:30.000Z",
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "assistant",
                        "phase": "final_answer",
                        "content": [{"type": "output_text", "text": "done"}],
                    },
                },
            ]
            if complete:
                rows.append(
                    {
                        "timestamp": "2026-08-25T00:47:31.000Z",
                        "type": "event_msg",
                        "payload": {"type": "task_complete"},
                    }
                )
            path.write_text(
                "".join(f"{json.dumps(row)}\n" for row in rows),
                encoding="utf-8",
            )

        first_id = "01a00000-0000-7000-8000-000000000101"
        second_id = "01a00000-0000-7000-8000-000000000102"
        first = local_root / "first.jsonl"
        second = external_root / "second.jsonl"
        write_rollout(first, first_id, complete=True)
        write_rollout(second, second_id, complete=False)
        state_db = self.root / "bulk-state.sqlite"
        with sqlite3.connect(state_db) as connection:
            connection.execute(
                "CREATE TABLE threads(id TEXT PRIMARY KEY, rollout_path TEXT NOT NULL, title TEXT NOT NULL)"
            )
            connection.executemany(
                "INSERT INTO threads(id, rollout_path, title) VALUES (?, ?, ?)",
                [
                    (first_id, first.as_posix(), "First title"),
                    (second_id, second.as_posix(), "Second title"),
                ],
            )

        script = Path(__file__).resolve().parents[1] / "scripts" / "import_codex_conversations.py"
        batch_sessions = self.root / "bulk-sessions"
        command = [
            sys.executable,
            script.as_posix(),
            "--paw-python-root",
            Path(__file__).resolve().parents[1].as_posix(),
            "--state-db",
            state_db.as_posix(),
            "--db",
            self.store.db_path.as_posix(),
            "--session-dir",
            batch_sessions.as_posix(),
            "--source-root",
            local_root.as_posix(),
            "--source-root",
            external_root.as_posix(),
            "--allow-incomplete",
            "--write",
        ]
        first_run = subprocess.run(
            [*command, "--receipt", (self.root / "receipt-1.json").as_posix()],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(first_run.returncode, 0, first_run.stderr)
        first_summary = json.loads(first_run.stdout)
        self.assertEqual(first_summary["counts"]["imported"], 2)
        self.assertEqual(first_summary["counts"]["incompleteImported"], 1)
        self.assertEqual(first_summary["counts"]["failed"], 0)

        second_run = subprocess.run(
            [*command, "--receipt", (self.root / "receipt-2.json").as_posix()],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(second_run.returncode, 0, second_run.stderr)
        second_summary = json.loads(second_run.stdout)
        self.assertEqual(second_summary["counts"]["imported"], 0)
        self.assertEqual(second_summary["counts"]["alreadyImported"], 2)
        self.assertEqual(len(self.store.list()), 2)

    def test_bulk_cli_finds_codex_processes_by_full_executable_path(self) -> None:
        script = Path(__file__).resolve().parents[1] / "scripts" / "import_codex_conversations.py"
        spec = importlib.util.spec_from_file_location("paw_bulk_import_test", script)
        self.assertIsNotNone(spec)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        process_ids = module._codex_process_ids(
            """
             7152 /opt/homebrew/lib/node_modules/@openai/codex/bin/codex
            90136 /opt/homebrew/lib/node_modules/@openai/codex/vendor/bin/codex
            40974 /Applications/ChatGPT.app/Contents/Resources/codex
             1234 /usr/bin/python3
            """
        )

        self.assertEqual(process_ids, ["7152", "90136", "40974"])


if __name__ == "__main__":
    unittest.main()
