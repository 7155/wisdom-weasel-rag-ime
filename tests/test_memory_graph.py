from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

from rag_ime.memory_graph import MemoryGraphPrincipal, MemoryGraphStore


PROJECT = "wisdom-weasel-rag-ime"


class MemoryGraphTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-memory-graph-")
        self.db_path = Path(self.tmp.name) / "memory.sqlite3"
        self.store = MemoryGraphStore(self.db_path)
        self.store.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _event(self, text: str, *, source: str = "manual") -> int:
        with closing(self._connect()) as conn, conn:
            row = conn.execute(
                """
                INSERT INTO input_events(
                    created_at_ms, source, committed_text, recent_context, preedit,
                    schema_id, app, project, provider_name, tags_json,
                    context_group_id, context_group_level
                ) VALUES (1000, ?, ?, '', '', 'default', 'test', ?, 'local', '[]', '', 'app')
                """,
                (source, text, PROJECT),
            )
            event_id = int(row.lastrowid)
            conn.execute("INSERT INTO memory_state(event_id, updated_at_ms) VALUES (?, 1000)", (event_id,))
            return event_id

    def _session(self, session_id: str, role_id: str) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                """
                INSERT INTO agent_sessions(
                    id, agent_id, title, session_mode, role_id, role_version, model_profile,
                    tool_profile_version, created_at_ms, updated_at_ms, last_opened_at_ms, status
                ) VALUES (?, ?, ?, 'assistant', ?, 'v1', 'test', 'v1', 1, 1, 1, 'active')
                """,
                (session_id, role_id, session_id, role_id),
            )

    def _agent_source(self, event_id: int, *, session_id: str, source_role: str) -> str:
        source_id = f"agent-memory:{session_id}:{event_id}"
        with closing(self._connect()) as conn, conn:
            text = str(conn.execute("SELECT committed_text FROM input_events WHERE id = ?", (event_id,)).fetchone()[0])
            conn.execute(
                """
                INSERT INTO agent_memory_sources(
                    source_id, session_id, pi_entry_id, input_event_id, source_role,
                    source_revision, canonical_text_sha256, status, created_at_ms
                ) VALUES (?, ?, ?, ?, ?, 1, ?, 'active', 1000)
                """,
                (source_id, session_id, f"entry:{event_id}", event_id, source_role, hashlib.sha256(text.encode()).hexdigest()),
            )
        return source_id

    def _entity(self, entity_id: str, name: str, *, owner_kind: str = "user", owner_id: str = "local-user") -> None:
        self.store.upsert_entity(
            entity_id=entity_id,
            entity_type="concept",
            name=name,
            owner_kind=owner_kind,
            owner_id=owner_id,
            project=PROJECT,
            updated_at_ms=1000,
        )

    def test_source_anchor_expand_and_rehydrate_use_one_canonical_graph(self) -> None:
        event_id = self._event("八月考试让我压力很大，最近睡不好")
        self._entity("entity:exam", "考试")
        self._entity("entity:stress", "压力")
        self._entity("entity:sleep", "睡眠")
        first = self.store.upsert_relation(
            relation_id="relation:exam-stress",
            source_entity_id="entity:exam",
            target_entity_id="entity:stress",
            relation_type="causes",
            fact="考试准备使用户感到压力",
            idempotency_key="exam-stress-v1",
            sources=[
                {
                    "sourceType": "input_event",
                    "sourceId": str(event_id),
                    "evidenceText": "不应进入 expand 的自由文本",
                    "evidence": {"observedAtMs": 1000, "prompt": "也不应投影"},
                }
            ],
            project=PROJECT,
            valid_from_ms=1000,
            updated_at_ms=1000,
        )
        self.store.upsert_relation(
            relation_id="relation:stress-sleep",
            source_entity_id="entity:stress",
            target_entity_id="entity:sleep",
            relation_type="affects",
            fact="压力影响睡眠",
            idempotency_key="stress-sleep-v1",
            sources=[{"sourceType": "input_event", "sourceId": str(event_id)}],
            project=PROJECT,
            valid_from_ms=1000,
            updated_at_ms=1001,
        )
        principal = MemoryGraphPrincipal(project=PROJECT, session_id="reader", agent_id="reader")

        anchors = self.store.find_anchors(
            principal,
            source_refs=[{"sourceType": "input_event", "sourceId": str(event_id)}],
            query_text="完全无关的名称不会新增锚点",
        )
        self.assertEqual({item["entityId"] for item in anchors["anchors"]}, {"entity:exam", "entity:stress", "entity:sleep"})
        self.assertTrue(all(item["matchedBy"] == ["source"] for item in anchors["anchors"]))

        expanded = self.store.expand(principal, anchor_ids=["entity:exam"], max_depth=2, as_of_ms=2000)
        self.assertEqual([item["relationId"] for item in expanded["relations"]], ["relation:exam-stress", "relation:stress-sleep"])
        self.assertEqual(
            set(expanded["relations"][0]["sources"][0]),
            {"sourceType", "sourceId", "sourceRevision"},
        )
        sources = self.store.get_sources(principal, relation_ids=[str(first["relation"]["relationId"])])
        self.assertEqual(sources["count"], 1)
        self.assertIn("八月考试", sources["sources"][0]["text"])

    def test_browser_entity_type_filter_applies_to_relation_endpoints(self) -> None:
        event_id = self._event("输入法项目包含模型推理")
        for entity_id, entity_type, name in (
            ("entity:ime", "topic", "输入法"),
            ("entity:model", "topic", "模型"),
            ("entity:latency", "metric", "延迟"),
        ):
            self.store.upsert_entity(
                entity_id=entity_id,
                entity_type=entity_type,
                name=name,
                project=PROJECT,
                updated_at_ms=1000,
            )
        for relation_id, target_id, key in (
            ("relation:ime-model", "entity:model", "ime-model"),
            ("relation:ime-latency", "entity:latency", "ime-latency"),
        ):
            self.store.upsert_relation(
                relation_id=relation_id,
                source_entity_id="entity:ime",
                target_entity_id=target_id,
                relation_type="related_to",
                fact=f"输入法关联{target_id.rsplit(':', 1)[-1]}",
                idempotency_key=key,
                sources=[{"sourceType": "input_event", "sourceId": str(event_id)}],
                project=PROJECT,
                valid_from_ms=1000,
                updated_at_ms=1000,
            )

        payload = self.store.browse(
            MemoryGraphPrincipal(project=PROJECT, local_admin=True),
            entity_types=("topic",),
            as_of_ms=2000,
        )

        self.assertEqual({item["entityType"] for item in payload["entities"]}, {"topic"})
        self.assertEqual(
            {item["relationId"] for item in payload["relations"]},
            {"relation:ime-model"},
        )

    def test_relation_is_idempotent_and_relation_id_cannot_change_identity(self) -> None:
        event_id = self._event("考试带来压力")
        self._entity("entity:a", "考试")
        self._entity("entity:b", "压力")
        kwargs = dict(
            relation_id="relation:a-b",
            source_entity_id="entity:a",
            target_entity_id="entity:b",
            relation_type="causes",
            fact="考试带来压力",
            idempotency_key="identity:a-b",
            sources=[{"sourceType": "input_event", "sourceId": str(event_id)}],
            project=PROJECT,
            valid_from_ms=1000,
            updated_at_ms=1000,
        )
        first = self.store.upsert_relation(**kwargs)
        second = self.store.upsert_relation(**kwargs)
        self.assertEqual(first["operation"], "created")
        self.assertEqual(second["operation"], "unchanged")
        with self.assertRaisesRegex(ValueError, "idempotency key"):
            self.store.upsert_relation(**{**kwargs, "idempotency_key": "different-identity"})
        with closing(self._connect()) as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM memory_projection_outbox WHERE aggregate_id = 'relation:a-b'"
            ).fetchone()[0]
        self.assertEqual(count, 1)

    def test_tool_receipt_is_private_but_user_prompt_is_shared_user_memory(self) -> None:
        self._session("session:a", "agent:a")
        self._session("session:b", "agent:b")
        tool_event = self._event("工具完成了 Agent A 的私有操作", source="pi_agent_tool_receipt")
        user_event = self._event("我八月要考试", source="pi_agent_user")
        self._agent_source(tool_event, session_id="session:a", source_role="tool_receipt")
        self._agent_source(user_event, session_id="session:a", source_role="user")
        self._entity("entity:private-a", "Agent A 操作", owner_kind="session", owner_id="session:a")
        self._entity("entity:private-b", "私有结果", owner_kind="session", owner_id="session:a")
        private_relation = self.store.upsert_relation(
            relation_id="relation:private",
            source_entity_id="entity:private-a",
            target_entity_id="entity:private-b",
            relation_type="produced",
            fact="Agent A 完成了私有操作",
            idempotency_key="private-v1",
            sources=[{"sourceType": "input_event", "sourceId": str(tool_event)}],
            owner_kind="session",
            owner_id="session:a",
            project=PROJECT,
            valid_from_ms=1000,
        )
        with self.assertRaises(PermissionError):
            self.store.upsert_relation(
                source_entity_id="entity:private-a",
                target_entity_id="entity:private-b",
                relation_type="leaks",
                fact="错误提升为公共事实",
                idempotency_key="leak-v1",
                sources=[{"sourceType": "input_event", "sourceId": str(tool_event)}],
                owner_kind="user",
                owner_id="local-user",
                project=PROJECT,
                valid_from_ms=1000,
            )
        with self.assertRaises(ValueError):
            self.store.upsert_relation(
                source_entity_id="entity:private-a",
                target_entity_id="entity:private-b",
                relation_type="fake",
                fact="伪造来源",
                idempotency_key="fake-v1",
                sources=[{"sourceType": "input_event", "sourceId": "999999"}],
                owner_kind="session",
                owner_id="session:a",
                project=PROJECT,
            )

        principal_b = MemoryGraphPrincipal(project=PROJECT, session_id="session:b", agent_id="agent:b")
        self.assertEqual(self.store.expand(principal_b, anchor_ids=["entity:private-a"])["count"], 0)
        self.assertEqual(
            self.store.get_sources(principal_b, relation_ids=[str(private_relation["relation"]["relationId"])])["count"],
            0,
        )

        self._entity("entity:user", "用户")
        self._entity("entity:exam", "八月考试")
        public_relation = self.store.upsert_relation(
            relation_id="relation:user-exam",
            source_entity_id="entity:user",
            target_entity_id="entity:exam",
            relation_type="plans",
            fact="用户八月参加考试",
            idempotency_key="user-exam-v1",
            sources=[{"sourceType": "input_event", "sourceId": str(user_event)}],
            project=PROJECT,
            valid_from_ms=1000,
        )
        public_sources = self.store.get_sources(
            principal_b,
            relation_ids=[str(public_relation["relation"]["relationId"])],
        )
        self.assertEqual(public_sources["count"], 1)
        self.assertIn("八月", public_sources["sources"][0]["text"])

    def test_source_rehydration_requires_relation_and_rechecks_sensitive_text(self) -> None:
        event_id = self._event("这是可回源的普通内容")
        self._entity("entity:one", "一")
        self._entity("entity:two", "二")
        relation = self.store.upsert_relation(
            relation_id="relation:sensitive-guard",
            source_entity_id="entity:one",
            target_entity_id="entity:two",
            relation_type="related_to",
            fact="普通内容形成关系",
            idempotency_key="sensitive-guard-v1",
            sources=[{"sourceType": "input_event", "sourceId": str(event_id)}],
            project=PROJECT,
            valid_from_ms=1000,
        )
        principal = MemoryGraphPrincipal(project=PROJECT, session_id="reader", agent_id="reader")
        with self.assertRaisesRegex(ValueError, "relation_ids"):
            self.store.get_sources(
                principal,
                source_refs=[{"sourceType": "input_event", "sourceId": str(event_id)}],
            )
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "UPDATE input_events SET committed_text = 'password=super-secret-value' WHERE id = ?",
                (event_id,),
            )
        guarded = self.store.get_sources(principal, relation_ids=[str(relation["relation"]["relationId"])])
        self.assertEqual(guarded["count"], 0)

    def test_agent_source_deletion_sensitivity_and_lifecycle_fail_closed(self) -> None:
        self._session("session:a", "agent:a")
        self._session("session:b", "agent:b")
        event_id = self._event("Agent A 可回源的普通结果", source="pi_agent_tool_receipt")
        source_id = self._agent_source(event_id, session_id="session:a", source_role="tool_receipt")
        self._entity("entity:agent-a", "Agent A", owner_kind="session", owner_id="session:a")
        self._entity("entity:result", "执行结果", owner_kind="session", owner_id="session:a")
        relation = self.store.upsert_relation(
            relation_id="relation:agent-source-guard",
            source_entity_id="entity:agent-a",
            target_entity_id="entity:result",
            relation_type="produced",
            fact="Agent A 产生了执行结果",
            idempotency_key="agent-source-guard-v1",
            sources=[{"sourceType": "agent_memory_source", "sourceId": source_id}],
            owner_kind="session",
            owner_id="session:a",
            project=PROJECT,
            valid_from_ms=1000,
        )
        principal_a = MemoryGraphPrincipal(project=PROJECT, session_id="session:a", agent_id="agent:a")
        self.assertEqual(
            self.store.get_sources(principal_a, relation_ids=[str(relation["relation"]["relationId"])])["count"],
            1,
        )

        with closing(self._connect()) as conn, conn:
            conn.execute("UPDATE memory_state SET deleted = 1 WHERE event_id = ?", (event_id,))
        self.assertEqual(
            self.store.find_anchors(
                principal_a,
                source_refs=[{"sourceType": "agent_memory_source", "sourceId": source_id}],
                query_text="Agent A 执行结果",
            )["count"],
            0,
        )
        self.assertEqual(
            self.store.expand(principal_a, anchor_ids=["entity:agent-a"])["count"],
            0,
        )
        self.assertEqual(
            self.store.get_sources(principal_a, relation_ids=[str(relation["relation"]["relationId"])])["count"],
            0,
        )
        with closing(self._connect()) as conn:
            relation_state = conn.execute(
                "SELECT status, revision FROM memory_relations WHERE relation_id = ?",
                (str(relation["relation"]["relationId"]),),
            ).fetchone()
            delete_outbox = conn.execute(
                """
                SELECT COUNT(*) FROM memory_projection_outbox
                WHERE aggregate_type = 'relation' AND aggregate_id = ? AND operation = 'delete'
                """,
                (str(relation["relation"]["relationId"]),),
            ).fetchone()[0]
        self.assertEqual(str(relation_state["status"]), "tombstoned")
        self.assertEqual(int(relation_state["revision"]), 2)
        self.assertEqual(int(delete_outbox), 1)

        sensitive_event = self._event("password=super-secret", source="pi_agent_tool_receipt")
        sensitive_source = self._agent_source(
            sensitive_event,
            session_id="session:a",
            source_role="tool_receipt",
        )
        with self.assertRaises(PermissionError):
            self.store.upsert_relation(
                source_entity_id="entity:agent-a",
                target_entity_id="entity:result",
                relation_type="produced",
                fact="敏感结果",
                idempotency_key="sensitive-agent-source",
                sources=[{"sourceType": "agent_memory_source", "sourceId": sensitive_source}],
                owner_kind="session",
                owner_id="session:a",
                project=PROJECT,
            )

        archived_event = self._event("归档后的私有工具结果", source="pi_agent_tool_receipt")
        archived_source = self._agent_source(
            archived_event,
            session_id="session:a",
            source_role="tool_receipt",
        )
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "UPDATE agent_memory_sources SET status = 'archived' WHERE source_id = ?",
                (archived_source,),
            )
        with self.assertRaises(PermissionError):
            self.store.upsert_relation(
                source_entity_id="entity:agent-a",
                target_entity_id="entity:result",
                relation_type="produced",
                fact="归档结果不能重新入图",
                idempotency_key="archived-agent-source",
                sources=[{"sourceType": "input_event", "sourceId": str(archived_event)}],
                owner_kind="session",
                owner_id="session:a",
                project=PROJECT,
            )

    def test_entity_source_deletion_blocks_name_fallback_and_emits_delete(self) -> None:
        event_id = self._event("用户最近在准备八月考试")
        created = self.store.upsert_entity(
            entity_id="entity:provenanced-exam",
            entity_type="topic",
            name="八月考试",
            sources=[{"sourceType": "input_event", "sourceId": str(event_id)}],
            project=PROJECT,
            updated_at_ms=1000,
        )
        principal = MemoryGraphPrincipal(project=PROJECT)
        self.assertEqual(
            self.store.find_anchors(
                principal,
                source_refs=[{"sourceType": "input_event", "sourceId": str(event_id)}],
            )["count"],
            1,
        )
        self.assertEqual(
            self.store.find_anchors(principal, query_text="八月考试")["count"],
            1,
        )

        with closing(self._connect()) as conn, conn:
            conn.execute("UPDATE memory_state SET deleted = 1 WHERE event_id = ?", (event_id,))
        self.assertEqual(
            self.store.find_anchors(principal, query_text="八月考试")["count"],
            0,
        )
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT status, revision FROM memory_entities WHERE entity_id = 'entity:provenanced-exam'"
            ).fetchone()
            outbox = conn.execute(
                """
                SELECT operation, revision FROM memory_projection_outbox
                WHERE aggregate_type = 'entity' AND aggregate_id = 'entity:provenanced-exam'
                ORDER BY revision
                """
            ).fetchall()
        self.assertEqual(created["entity"]["sources"][0]["sourceId"], str(event_id))
        self.assertEqual(tuple(row), ("tombstoned", 2))
        self.assertEqual([tuple(item) for item in outbox], [("upsert", 1), ("delete", 2)])

    def test_dirty_source_drain_is_bounded_and_leaves_unrelated_graph_active(self) -> None:
        deleted_event = self._event("考试导致压力")
        live_event = self._event("散步改善心情")
        for entity_id, name, event_id in (
            ("entity:exam-dirty", "考试", deleted_event),
            ("entity:stress-dirty", "压力", deleted_event),
            ("entity:walk-live", "散步", live_event),
            ("entity:mood-live", "心情", live_event),
        ):
            self.store.upsert_entity(
                entity_id=entity_id,
                entity_type="concept",
                name=name,
                sources=[{"sourceType": "input_event", "sourceId": str(event_id)}],
                project=PROJECT,
            )
        self.store.upsert_relation(
            relation_id="relation:dirty",
            source_entity_id="entity:exam-dirty",
            target_entity_id="entity:stress-dirty",
            relation_type="causes",
            fact="考试导致压力",
            idempotency_key="dirty-source",
            sources=[{"sourceType": "input_event", "sourceId": str(deleted_event)}],
            project=PROJECT,
        )
        self.store.upsert_relation(
            relation_id="relation:unrelated-live",
            source_entity_id="entity:walk-live",
            target_entity_id="entity:mood-live",
            relation_type="improves",
            fact="散步改善心情",
            idempotency_key="unrelated-live",
            sources=[{"sourceType": "input_event", "sourceId": str(live_event)}],
            project=PROJECT,
        )

        with closing(self._connect()) as conn, conn:
            conn.execute(
                "UPDATE memory_state SET deleted = 1 WHERE event_id = ?",
                (deleted_event,),
            )
            dirty_before = conn.execute(
                "SELECT source_type, source_id FROM memory_graph_source_dirty"
            ).fetchall()
        self.assertEqual(
            [tuple(row) for row in dirty_before],
            [("input_event", str(deleted_event))],
        )

        report = self.store.drain_dirty_sources(limit=1)

        self.assertEqual(report, {"sources": 1, "relations": 1, "entities": 2})
        with closing(self._connect()) as conn:
            dirty_after = conn.execute(
                "SELECT COUNT(*) FROM memory_graph_source_dirty"
            ).fetchone()[0]
            statuses = dict(
                conn.execute(
                    "SELECT relation_id, status FROM memory_relations ORDER BY relation_id"
                ).fetchall()
            )
        self.assertEqual(dirty_after, 0)
        self.assertEqual(statuses["relation:dirty"], "tombstoned")
        self.assertEqual(statuses["relation:unrelated-live"], "active")

    def test_dirty_source_removes_only_changed_provenance_and_projects_new_revision(self) -> None:
        changed_event = self._event("考试带来压力")
        supporting_event = self._event("复习压力仍然存在")
        self.store.upsert_entity(
            entity_id="entity:multi-exam",
            entity_type="concept",
            name="考试",
            sources=[
                {"sourceType": "input_event", "sourceId": str(changed_event)},
                {"sourceType": "input_event", "sourceId": str(supporting_event)},
            ],
            project=PROJECT,
            updated_at_ms=1000,
        )
        self._entity("entity:multi-stress", "压力")
        self.store.upsert_relation(
            relation_id="relation:multi-source",
            source_entity_id="entity:multi-exam",
            target_entity_id="entity:multi-stress",
            relation_type="causes",
            fact="备考会带来压力",
            idempotency_key="multi-source",
            sources=[
                {"sourceType": "input_event", "sourceId": str(changed_event)},
                {"sourceType": "input_event", "sourceId": str(supporting_event)},
            ],
            project=PROJECT,
            updated_at_ms=1000,
        )
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "UPDATE input_events SET committed_text = '这段证据已经改成别的话题' WHERE id = ?",
                (changed_event,),
            )

        report = self.store.drain_dirty_sources(limit=1)

        self.assertEqual(report, {"sources": 1, "relations": 1, "entities": 1})
        with closing(self._connect()) as conn:
            relation = conn.execute(
                "SELECT status, revision FROM memory_relations WHERE relation_id = 'relation:multi-source'"
            ).fetchone()
            sources = conn.execute(
                """
                SELECT source_id FROM memory_relation_sources
                WHERE relation_id = 'relation:multi-source'
                ORDER BY source_id
                """
            ).fetchall()
            projected = conn.execute(
                """
                SELECT operation, revision, payload_json
                FROM memory_projection_outbox
                WHERE aggregate_type = 'relation' AND aggregate_id = 'relation:multi-source'
                ORDER BY revision
                """
            ).fetchall()
            entity = conn.execute(
                "SELECT status, revision FROM memory_entities WHERE entity_id = 'entity:multi-exam'"
            ).fetchone()
            entity_sources = conn.execute(
                """
                SELECT source_id FROM memory_entity_sources
                WHERE entity_id = 'entity:multi-exam'
                ORDER BY source_id
                """
            ).fetchall()
        self.assertEqual(tuple(relation), ("active", 2))
        self.assertEqual(tuple(entity), ("active", 2))
        self.assertEqual([str(row["source_id"]) for row in sources], [str(supporting_event)])
        self.assertEqual([str(row["source_id"]) for row in entity_sources], [str(supporting_event)])
        self.assertEqual([(row["operation"], row["revision"]) for row in projected], [("upsert", 1), ("upsert", 2)])
        revision_two = json.loads(str(projected[1]["payload_json"]))
        self.assertEqual(
            revision_two["sources"],
            [{"sourceId": str(supporting_event), "sourceRevision": 1, "sourceType": "input_event"}],
        )

    def test_dirty_drain_preserves_provenance_rederived_at_new_source_generation(self) -> None:
        event_id = self._event("旧证据：考试带来压力")
        self._entity("entity:generation-exam", "考试")
        self._entity("entity:generation-stress", "压力")
        self.store.upsert_relation(
            relation_id="relation:generation-aware",
            source_entity_id="entity:generation-exam",
            target_entity_id="entity:generation-stress",
            relation_type="causes",
            fact="旧结论",
            idempotency_key="generation-aware",
            sources=[{"sourceType": "input_event", "sourceId": str(event_id)}],
            project=PROJECT,
            updated_at_ms=1000,
        )
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "UPDATE input_events SET committed_text = '新证据：复习进度落后带来压力' WHERE id = ?",
                (event_id,),
            )
            generation = conn.execute(
                """
                SELECT generation FROM memory_source_generations
                WHERE source_type = 'input_event' AND source_id = ?
                """,
                (str(event_id),),
            ).fetchone()[0]
        self.assertEqual(int(generation), 2)

        corrected = self.store.upsert_relation(
            relation_id="relation:generation-aware",
            source_entity_id="entity:generation-exam",
            target_entity_id="entity:generation-stress",
            relation_type="causes",
            fact="复习进度落后带来压力",
            idempotency_key="generation-aware",
            sources=[{"sourceType": "input_event", "sourceId": str(event_id)}],
            project=PROJECT,
        )
        report = self.store.drain_dirty_sources(limit=1)

        self.assertEqual(report["relations"], 1)
        with closing(self._connect()) as conn:
            relation = conn.execute(
                "SELECT status, revision, fact FROM memory_relations WHERE relation_id = 'relation:generation-aware'"
            ).fetchone()
            source_rows = conn.execute(
                """
                SELECT source_id, source_revision FROM memory_relation_sources
                WHERE relation_id = 'relation:generation-aware'
                ORDER BY source_revision
                """
            ).fetchall()
            delete_count = conn.execute(
                """
                SELECT COUNT(*) FROM memory_projection_outbox
                WHERE aggregate_type = 'relation'
                  AND aggregate_id = 'relation:generation-aware'
                  AND operation = 'delete'
                """
            ).fetchone()[0]
        self.assertEqual(corrected["relation"]["revision"], 2)
        self.assertEqual(tuple(relation), ("active", 3, "复习进度落后带来压力"))
        self.assertEqual([tuple(row) for row in source_rows], [(str(event_id), 2)])
        self.assertEqual(delete_count, 0)

    def test_entity_revision_compare_and_swap_allows_only_one_writer(self) -> None:
        self.store.upsert_entity(
            entity_id="entity:cas",
            entity_type="concept",
            name="初始实体",
            project=PROJECT,
            updated_at_ms=1000,
        )

        def update(name: str) -> str:
            try:
                result = self.store.upsert_entity(
                    entity_id="entity:cas",
                    entity_type="concept",
                    name=name,
                    project=PROJECT,
                    expected_revision=1,
                )
                return str(result["operation"])
            except ValueError as exc:
                return str(exc)

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(update, ("并发写入甲", "并发写入乙")))
        self.assertEqual(sum(item == "updated" for item in outcomes), 1)
        self.assertEqual(sum("revision conflict" in item for item in outcomes), 1)
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT revision FROM memory_entities WHERE entity_id = 'entity:cas'"
            ).fetchone()
            revisions = conn.execute(
                """
                SELECT revision FROM memory_projection_outbox
                WHERE aggregate_type = 'entity' AND aggregate_id = 'entity:cas'
                ORDER BY revision
                """
            ).fetchall()
        self.assertEqual(int(row["revision"]), 2)
        self.assertEqual([int(item["revision"]) for item in revisions], [1, 2])

    def test_rollback_uses_compensating_revision_instead_of_destructive_delete(self) -> None:
        created = self.store.upsert_entity(
            entity_id="entity:rollback",
            entity_type="concept",
            name="临时实体",
            project=PROJECT,
            updated_at_ms=1000,
        )
        restored = self.store.restore_entity(
            entity_id="entity:rollback",
            snapshot=created["previous"],
        )
        self.assertEqual(restored["operation"], "tombstoned")
        self.assertEqual(restored["entity"]["revision"], 2)
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT status, revision FROM memory_entities WHERE entity_id = 'entity:rollback'"
            ).fetchone()
            outbox = conn.execute(
                "SELECT operation, revision FROM memory_projection_outbox WHERE aggregate_id = 'entity:rollback' ORDER BY revision"
            ).fetchall()
        self.assertEqual(tuple(row), ("tombstoned", 2))
        self.assertEqual([tuple(item) for item in outbox], [("upsert", 1), ("delete", 2)])

    def test_acl_is_applied_before_query_limits(self) -> None:
        event_id = self._event("共享锚点证据")
        self._entity("entity:shared-start", "共享起点")
        for index in range(20):
            hidden_id = f"entity:hidden:{index}"
            self._entity(hidden_id, f"隐藏节点 {index}", owner_kind="session", owner_id="session:other")
            self.store.upsert_relation(
                relation_id=f"relation:hidden:{index}",
                source_entity_id="entity:shared-start",
                target_entity_id=hidden_id,
                relation_type="private_link",
                fact=f"不可见关系 {index}",
                idempotency_key=f"hidden:{index}",
                sources=[{"sourceType": "input_event", "sourceId": str(event_id)}],
                owner_kind="session",
                owner_id="session:other",
                project=PROJECT,
                confidence=1.0,
                valid_from_ms=1000,
            )
        self._entity("entity:visible", "可见节点")
        self.store.upsert_relation(
            relation_id="relation:visible-after-hidden",
            source_entity_id="entity:shared-start",
            target_entity_id="entity:visible",
            relation_type="public_link",
            fact="低排序但可见的关系",
            idempotency_key="visible-after-hidden",
            sources=[{"sourceType": "input_event", "sourceId": str(event_id)}],
            project=PROJECT,
            confidence=0.1,
            valid_from_ms=1000,
        )
        principal = MemoryGraphPrincipal(project=PROJECT, session_id="session:reader", agent_id="agent:reader")

        anchors = self.store.find_anchors(
            principal,
            source_refs=[{"sourceType": "input_event", "sourceId": str(event_id)}],
            limit=1,
        )
        self.assertEqual(anchors["anchors"][0]["entityId"], "entity:shared-start")
        expanded = self.store.expand(principal, anchor_ids=["entity:shared-start"], limit=1)
        self.assertEqual(expanded["relations"][0]["relationId"], "relation:visible-after-hidden")


if __name__ == "__main__":
    unittest.main()
