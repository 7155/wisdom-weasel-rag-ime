from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import urlopen

from rag_ime.activity_timeline import DailyActivityTimelineStore
from rag_ime.agent_role_book import AgentRoleBookStore
from rag_ime.contracts.json_schema import validate_contract
from rag_ime.debug_server import DebugImeService, DebugRequestHandler, DebugServerConfig
from rag_ime.local_sqlite_core import LocalSqliteCoreClient
from rag_ime.management_service import page_request
from rag_ime.models import InputEvent


class MemoryReferenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="rag-ime-memory-ref-")
        self.db_path = Path(self.temporary.name) / "rag-ime.sqlite"
        self.project = "wisdom-weasel-rag-ime"
        self.core = LocalSqliteCoreClient(self.db_path)
        self.core.initialize()
        self.safe_event_id = self._record_event(
            "CAS 在 Ghostty 切换 Codex 账号并完成验证",
            created_at_ms=1_784_250_000_000,
            app="com.mitchellh.ghostty",
            recent_context="准备切换工作账号",
            preedit="cas codex",
        )
        self.sensitive_event_id = self._record_event(
            "token=super-secret-value",
            created_at_ms=1_784_250_060_000,
            app="com.openai.codex",
        )
        self.source_id = "source:cas-user-final"
        self.evidence_id = "evidence:cas-agent"
        self.atom_id = "atom:cas-current-account"
        self.book_id = "book:cas-account-workflow"
        self._seed_reference_graph()
        timeline = DailyActivityTimelineStore(
            self.db_path,
            project=self.project,
            timezone_name="Asia/Shanghai",
        ).build_draft(
            "2026-07-17",
            generated_at_ms=1_784_250_120_000,
        )["timeline"]
        self.timeline_id = str(timeline["timelineId"])
        role_book = AgentRoleBookStore(self.db_path)
        seeded = role_book.ensure_seeded(
            "architect",
            "role-v1",
            display_name="架构师",
            mission="维护个人上下文",
            created_at_ms=1_784_250_180_000,
        )
        self.role_revision_id = str(seeded["revisionId"])
        self.service = DebugImeService(
            DebugServerConfig(
                db_path=self.db_path,
                project=self.project,
                seed_if_empty=False,
            )
        )

    def tearDown(self) -> None:
        self.service.close()
        self.temporary.cleanup()

    def test_evidence_page_unifies_both_catalogs_with_canonical_references(self) -> None:
        result = self.service.management.memory_page(
            "evidence",
            page_request({"project": self.project, "limit": 20}),
        )

        by_id = {str(item["id"]): item for item in result["items"]}
        self.assertIn(self.source_id, by_id)
        self.assertIn(self.evidence_id, by_id)
        self.assertEqual(
            by_id[self.source_id]["catalogSource"],
            "agent_memory_sources",
        )
        self.assertEqual(
            by_id[self.evidence_id]["catalogSource"],
            "agent_memory_evidence",
        )
        self.assertEqual(by_id[self.source_id]["ref"]["kind"], "evidence")
        self.assertEqual(
            by_id[self.source_id]["evidenceRefs"][0]["id"],
            str(self.safe_event_id),
        )
        self.assertEqual(
            by_id[self.evidence_id]["evidenceRefs"][0]["id"],
            str(self.safe_event_id),
        )

    def test_atom_book_and_timeline_pages_expose_resolvable_reference_chains(self) -> None:
        atom = self.service.management.memory_page(
            "atoms",
            page_request({"project": self.project, "limit": 20}),
        )["items"][0]
        book = self.service.management.memory_page(
            "books",
            page_request({"project": self.project, "limit": 20}),
        )["items"][0]
        timeline = self.service.management.memory_page(
            "timelines",
            page_request({"project": self.project, "limit": 20}),
        )["items"][0]

        self.assertEqual(atom["ref"]["kind"], "atom")
        self.assertEqual(
            {(ref["kind"], ref["id"]) for ref in atom["evidenceRefs"]},
            {
                ("event", str(self.safe_event_id)),
                ("evidence", self.evidence_id),
            },
        )
        self.assertEqual(book["ref"]["kind"], "book")
        self.assertEqual(
            {(ref["kind"], ref["id"]) for ref in book["evidenceRefs"]},
            {
                ("event", str(self.safe_event_id)),
                ("atom", self.atom_id),
            },
        )
        self.assertEqual(timeline["ref"]["kind"], "timeline")
        self.assertTrue(timeline["segments"])
        self.assertTrue(
            all(
                ref["kind"] == "event"
                for segment in timeline["segments"]
                for ref in segment["evidenceRefs"]
            )
        )
        self.assertNotIn(
            "super-secret-value",
            json.dumps(timeline, ensure_ascii=False),
        )

    def test_timeline_visibility_checks_all_sources_beyond_reference_preview_cap(self) -> None:
        event_ids = [self.safe_event_id]
        with sqlite3.connect(self.db_path) as conn, conn:
            conn.executemany(
                """
                INSERT INTO input_events(
                    created_at_ms, source, committed_text, app, project
                ) VALUES (?, 'manual', ?, 'com.openai.codex', ?)
                """,
                [
                    (
                        1_784_250_240_000 + index,
                        f"可见时间线来源 {index}",
                        self.project,
                    )
                    for index in range(81)
                ],
            )
            event_ids.extend(
                int(row[0])
                for row in conn.execute(
                    """
                    SELECT id FROM input_events
                    WHERE created_at_ms BETWEEN ? AND ?
                    ORDER BY id
                    """,
                    (1_784_250_240_000, 1_784_250_240_080),
                )
            )
            source_json = json.dumps(event_ids, separators=(",", ":"))
            conn.execute(
                """
                UPDATE daily_activity_timelines
                SET source_event_ids_json = ?,
                    source_event_hash = ?,
                    event_count = ?
                WHERE timeline_id = ?
                """,
                (
                    source_json,
                    hashlib.sha256(source_json.encode("utf-8")).hexdigest(),
                    len(event_ids),
                    self.timeline_id,
                ),
            )

        timelines = self.service.management.memory_page(
            "timelines",
            page_request({"project": self.project, "status": "draft", "limit": 20}),
        )["items"]

        timeline = next(item for item in timelines if item["id"] == self.timeline_id)
        self.assertEqual(timeline["eventCount"], len(event_ids))
        self.assertEqual(len(timeline["evidenceRefs"]), 80)

    def test_reference_resolvers_preserve_provenance_and_redact_sensitive_text(self) -> None:
        for event_reference in (
            str(self.safe_event_id),
            f"event:{self.safe_event_id}",
            f"input-memory:{self.safe_event_id}",
        ):
            event = self.service.management.memory_reference(
                "event",
                event_reference,
            )
            validate_contract(event, "memory-reference.v1.json")
            self.assertEqual(event["ref"]["id"], str(self.safe_event_id))

            self.assertTrue(event["item"]["sourceContextAvailable"])
            self.assertEqual(
                event["item"]["sourceContext"]["recentContext"],
                "准备切换工作账号",
            )
            self.assertEqual(
                event["item"]["sourceContext"]["preedit"],
                "cas codex",
            )
            self.assertEqual(
                event["item"]["sourceContext"]["usedFor"],
                ["source_fingerprint", "semantic_grouping"],
            )
        evidence = self.service.management.memory_reference(
            "evidence",
            self.evidence_id,
        )
        atom = self.service.management.memory_reference("atom", self.atom_id)
        book = self.service.management.memory_reference("book", self.book_id)
        timeline = self.service.management.memory_reference(
            "timeline",
            self.timeline_id,
        )
        role = self.service.management.memory_reference(
            "role_book_revision",
            self.role_revision_id,
        )
        for payload in (evidence, atom, book, timeline, role):
            validate_contract(payload, "memory-reference.v1.json")

        self.assertEqual(evidence["evidenceRefs"][0]["id"], str(self.safe_event_id))
        self.assertIn(
            ("evidence", self.evidence_id),
            {(ref["kind"], ref["id"]) for ref in atom["evidenceRefs"]},
        )
        self.assertIn(
            ("atom", self.atom_id),
            {(ref["kind"], ref["id"]) for ref in book["evidenceRefs"]},
        )
        self.assertIn(
            ("event", str(self.safe_event_id)),
            {(ref["kind"], ref["id"]) for ref in timeline["evidenceRefs"]},
        )
        self.assertEqual(timeline["item"]["ordinaryActivityCount"], 1)
        self.assertEqual(timeline["item"]["consolidatedActivityCount"], 0)
        self.assertEqual(
            timeline["item"]["spanSemantics"],
            "first_to_last_source_event",
        )
        self.assertTrue(
            all(
                "preview" not in reference
                for segment in timeline["item"]["segments"]
                for reference in segment["evidenceRefs"]
            )
        )
        self.assertEqual(role["ref"]["kind"], "role_book_revision")

        sensitive = self.service.management.memory_reference(
            "event",
            str(self.sensitive_event_id),
        )
        serialized = json.dumps(sensitive, ensure_ascii=False)
        self.assertTrue(sensitive["item"]["sensitive"])
        self.assertEqual(sensitive["item"]["text"], "")
        self.assertNotIn("super-secret-value", serialized)
        self.assertTrue(sensitive["item"]["sourceContext"]["redacted"])
        self.assertEqual(sensitive["item"]["sourceContext"]["recentContext"], "")
        self.assertEqual(sensitive["item"]["sourceContext"]["preedit"], "")

        unscoped_service = DebugImeService(
            DebugServerConfig(
                db_path=self.db_path,
                project="",
                seed_if_empty=False,
            )
        )
        try:
            unscoped = unscoped_service.management.memory_reference(
                "event",
                str(self.safe_event_id),
            )
            self.assertFalse(unscoped["item"]["sourceContextAvailable"])
            self.assertNotIn("sourceContext", unscoped["item"])
        finally:
            unscoped_service.close()

    def test_forgotten_tombstoned_and_unknown_references_fail_closed(self) -> None:
        with sqlite3.connect(self.db_path) as conn, conn:
            conn.execute(
                """
                UPDATE agent_memory_sources
                SET disposition = 'not_for_memory',
                    disposition_reason = 'user_forgotten'
                WHERE source_id = ?
                """,
                (self.source_id,),
            )
            conn.execute(
                "UPDATE agent_memory_evidence SET status = 'tombstoned' WHERE evidence_id = ?",
                (self.evidence_id,),
            )
            conn.execute(
                """
                INSERT INTO memory_tombstones(
                    created_at_ms, target_type, target_value, reason,
                    active, metadata_json
                ) VALUES (?, 'memory_id', ?, 'test-forget', 1, '{}')
                """,
                (1_784_250_240_000, f"event:{self.safe_event_id}"),
            )

        for kind, reference_id in (
            ("event", str(self.safe_event_id)),
            ("evidence", self.source_id),
            ("evidence", self.evidence_id),
            ("atom", "atom:missing"),
        ):
            with self.assertRaisesRegex(ValueError, "not found"):
                self.service.management.memory_reference(kind, reference_id)
        with self.assertRaisesRegex(ValueError, "unsupported"):
            self.service.management.memory_reference("segment", "segment:1")

    def test_event_tombstone_shapes_fail_closed_across_source_open_paths(self) -> None:
        tombstone_shapes = (
            ("source_event_id", str(self.safe_event_id)),
            ("memory_id", f"event:{self.safe_event_id}"),
        )
        for target_type, target_value in tombstone_shapes:
            with self.subTest(target_type=target_type):
                with sqlite3.connect(self.db_path) as conn, conn:
                    cursor = conn.execute(
                        """
                        INSERT INTO memory_tombstones(
                            created_at_ms, target_type, target_value, reason,
                            active, metadata_json
                        ) VALUES (?, ?, ?, 'test-forget-source', 1, '{}')
                        """,
                        (1_784_250_250_000, target_type, target_value),
                    )
                    tombstone_id = int(cursor.lastrowid)

                for kind, reference_id in (
                    ("event", str(self.safe_event_id)),
                    ("evidence", self.source_id),
                    ("evidence", self.evidence_id),
                    ("timeline", self.timeline_id),
                ):
                    with self.assertRaisesRegex(ValueError, "not found"):
                        self.service.management.memory_reference(kind, reference_id)

                history = self.service.management.history_page(
                    page_request({"limit": 20})
                )
                self.assertNotIn(
                    self.safe_event_id,
                    {int(item["id"]) for item in history["items"]},
                )
                detail = self.service.management.history_detail(self.safe_event_id)
                self.assertFalse(detail["ok"])
                self.assertEqual(detail["errorCode"], "not_found")

                evidence = self.service.management.memory_page(
                    "evidence",
                    page_request({"project": self.project, "limit": 20}),
                )
                evidence_ids = {str(item["id"]) for item in evidence["items"]}
                self.assertNotIn(self.source_id, evidence_ids)
                self.assertNotIn(self.evidence_id, evidence_ids)
                timelines = self.service.management.memory_page(
                    "timelines",
                    page_request({"project": self.project, "limit": 20}),
                )
                self.assertNotIn(
                    self.timeline_id,
                    {str(item["id"]) for item in timelines["items"]},
                )

                with sqlite3.connect(self.db_path) as conn, conn:
                    conn.execute(
                        "UPDATE memory_tombstones SET active = 0 WHERE id = ?",
                        (tombstone_id,),
                    )
                restored = self.service.management.memory_reference(
                    "event",
                    str(self.safe_event_id),
                )
                self.assertTrue(restored["ok"])
                self.assertTrue(
                    self.service.management.memory_reference(
                        "evidence",
                        self.source_id,
                    )["ok"]
                )
                self.assertTrue(
                    self.service.management.memory_reference(
                        "evidence",
                        self.evidence_id,
                    )["ok"]
                )
                self.assertTrue(
                    self.service.management.memory_reference(
                        "timeline",
                        self.timeline_id,
                    )["ok"]
                )

    def test_http_reference_route_accepts_url_encoded_event_id(self) -> None:
        class Handler(DebugRequestHandler):
            pass

        Handler.service = self.service
        Handler.static_dir = Path(".")
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            encoded = quote(f"event:{self.safe_event_id}", safe="")
            with urlopen(
                f"http://127.0.0.1:{server.server_port}/api/memory/references/event/{encoded}",
                timeout=5,
            ) as response:
                payload = json.load(response)
            self.assertEqual(payload["kind"], "event")
            self.assertEqual(payload["ref"]["id"], str(self.safe_event_id))
            with self.assertRaises(HTTPError) as raised:
                urlopen(
                    f"http://127.0.0.1:{server.server_port}/api/memory/references/atom/atom%3Amissing",
                    timeout=5,
                )
            self.assertEqual(raised.exception.code, 400)
            error = json.loads(raised.exception.read().decode("utf-8"))
            raised.exception.close()
            self.assertEqual(error["errorCode"], "invalid_request")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def _record_event(
        self,
        text: str,
        *,
        created_at_ms: int,
        app: str,
        recent_context: str = "",
        preedit: str = "",
    ) -> int:
        self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=created_at_ms,
                source="squirrel_input_segment",
                committed_text=text,
                recent_context=recent_context,
                preedit=preedit,
                privacy_disposition="allowed",
                app=app,
                project=self.project,
                tags=("input-segment", "finalized", "complete-input"),
                context_group_id=f"app:{app}",
                context_group_level="app",
            )
        )
        with sqlite3.connect(self.db_path) as conn:
            return int(conn.execute("SELECT MAX(id) FROM input_events").fetchone()[0])

    def _seed_reference_graph(self) -> None:
        source_text = "CAS 在 Ghostty 切换 Codex 账号并完成验证"
        digest = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
        with sqlite3.connect(self.db_path) as conn, conn:
            conn.execute(
                """
                INSERT INTO agent_memory_sources(
                    source_id, session_id, pi_entry_id, input_event_id,
                    source_role, canonical_text_sha256, created_at_ms,
                    source_kind, trust_class, disposition, metadata_json
                ) VALUES (?, 'session:cas', 'entry:cas', ?, 'user', ?, ?,
                          'user_final', 'user_claim', 'remember', '{}')
                """,
                (
                    self.source_id,
                    self.safe_event_id,
                    digest,
                    1_784_250_000_000,
                ),
            )
            conn.execute(
                """
                INSERT INTO agent_memory_evidence(
                    evidence_id, project, role_id, session_id, source_kind,
                    source_id, idempotency_key, content_text, content_sha256,
                    provenance_json, metadata_json, privacy_class, status,
                    occurred_at_ms, recorded_at_ms
                ) VALUES (?, ?, 'architect', 'session:cas', 'user_message',
                          'entry:cas', 'cas-evidence-v1', ?, ?, ?, '{}',
                          'local', 'active', ?, ?)
                """,
                (
                    self.evidence_id,
                    self.project,
                    source_text,
                    digest,
                    json.dumps({"inputEventId": self.safe_event_id}),
                    1_784_250_000_000,
                    1_784_250_000_000,
                ),
            )
            conn.execute(
                """
                INSERT INTO memory_atoms(
                    id, kind, text, canonical_text, source_event_ids_json,
                    source_memory_ids_json, scope_project, privacy_level,
                    status, created_at_ms, updated_at_ms
                ) VALUES (?, 'fact', ?, ?, ?, '[]', ?, 'local', 'active', ?, ?)
                """,
                (
                    self.atom_id,
                    "CAS 用于在终端切换 Codex 账号",
                    "CAS 用于在终端切换 Codex 账号",
                    json.dumps([self.safe_event_id]),
                    self.project,
                    1_784_250_000_000,
                    1_784_250_000_000,
                ),
            )
            conn.execute(
                """
                INSERT INTO memory_atom_evidence_links(
                    memory_atom_id, evidence_id, proposal_id, relation,
                    content_sha256, provenance_json, created_at_ms
                ) VALUES (?, ?, 'proposal:cas', 'supports', ?, '{}', ?)
                """,
                (
                    self.atom_id,
                    self.evidence_id,
                    digest,
                    1_784_250_000_000,
                ),
            )
            conn.execute(
                """
                INSERT INTO memory_books(
                    book_id, book_type, book_key, title, summary, project,
                    source_event_ids_json, memory_atom_ids_json, status,
                    created_at_ms, updated_at_ms
                ) VALUES (?, 'topic', 'cas-account', 'CAS 账号工作流',
                          '记录终端切换与 Codex 验证步骤', ?, ?, ?, 'active', ?, ?)
                """,
                (
                    self.book_id,
                    self.project,
                    json.dumps([self.safe_event_id]),
                    json.dumps([self.atom_id]),
                    1_784_250_000_000,
                    1_784_250_000_000,
                ),
            )


if __name__ == "__main__":
    unittest.main()
