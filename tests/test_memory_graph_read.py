from __future__ import annotations

import json
import sqlite3
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import urlopen

from rag_ime.contracts.json_schema import validate_contract
from rag_ime.debug_server import DebugImeService, DebugRequestHandler, DebugServerConfig
from rag_ime.local_sqlite_core import LocalSqliteCoreClient


PROJECT = "wisdom-weasel-rag-ime"
OTHER_PROJECT = "other-project"


class MemoryGraphReadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-memory-graph-")
        self.db_path = Path(self.tmp.name) / "rag-ime.sqlite"
        LocalSqliteCoreClient(self.db_path).initialize()
        self.service = DebugImeService(
            DebugServerConfig(db_path=self.db_path, project=PROJECT, seed_if_empty=False)
        )
        self.ids = self._seed_graph()

    def tearDown(self) -> None:
        self.service.agent.close()
        self.service.management.close()
        self.tmp.cleanup()

    def _seed_graph(self) -> dict[str, str]:
        with sqlite3.connect(self.db_path) as conn:
            tag_ids: dict[str, str] = {}
            for index, (name, quality) in enumerate(
                (("输入法", 0.98), ("Agent", 0.9), ("外部项目", 0.8), ("RAG", 0.85)),
                start=1,
            ):
                tag_ids[name] = str(
                    conn.execute(
                        """
                        INSERT INTO memory_tags(
                            tag, normalized_tag, tag_type, quality_score,
                            created_at_ms, updated_at_ms, description, source, status
                        ) VALUES (?, ?, 'concept', ?, ?, ?, ?, 'dsv4', 'active')
                        """,
                        (name, name.lower(), quality, index, index, f"{name} 的语义标签"),
                    ).lastrowid
                )
            conn.execute(
                "INSERT INTO memory_tag_profiles(tag_id, color_token, aliases_json, updated_at_ms) VALUES (?, 'teal', '[\"IME\"]', 10)",
                (int(tag_ids["输入法"]),),
            )

            atoms = (
                ("atom:visible", "候选栏与前台输入", PROJECT, "local", 0.95),
                ("atom:shared", "Agent 与输入法共享上下文", PROJECT, "local", 0.9),
                ("atom:sensitive", "绝不能出现在图里的敏感正文", PROJECT, "sensitive", 0.99),
                ("atom:other", "其他项目的记忆", OTHER_PROJECT, "local", 0.8),
            )
            for index, (atom_id, text, project, privacy, quality) in enumerate(atoms, start=20):
                conn.execute(
                    """
                    INSERT INTO memory_atoms(
                        id, kind, text, canonical_text, source_event_ids_json,
                        source_memory_ids_json, scope_project, privacy_level,
                        status, quality_score, created_at_ms, updated_at_ms
                    ) VALUES (?, 'fact', ?, ?, '[]', '[]', ?, ?, 'active', ?, ?, ?)
                    """,
                    (atom_id, text, text, project, privacy, quality, index, index),
                )
            for atom_id, tag_name, weight in (
                ("atom:visible", "输入法", 0.95),
                ("atom:shared", "Agent", 0.9),
                ("atom:sensitive", "输入法", 1.0),
                ("atom:other", "外部项目", 0.9),
                ("atom:shared", "RAG", 0.8),
            ):
                conn.execute(
                    "INSERT INTO memory_atom_tags(memory_atom_id, tag_id, weight, source) VALUES (?, ?, ?, 'dsv4')",
                    (atom_id, tag_ids[tag_name], weight),
                )

            phrase_row_id = conn.execute(
                """
                INSERT INTO memory_items(
                    memory_id, kind, text, normalized_text, summary, project,
                    confidence, quality_score, status, privacy_class,
                    created_at_ms, updated_at_ms
                ) VALUES (
                    'phrase:continue', 'phrase', '继续完善候选栏', '继续完善候选栏',
                    '用户确认过的短语', ?, 0.9, 0.9, 'approved', 'local', 40, 40
                )
                """,
                (PROJECT,),
            ).lastrowid
            conn.execute(
                "INSERT INTO memory_item_tags(memory_item_id, tag_id, weight, position, evidence) VALUES (?, ?, 0.85, 0, 'fixture')",
                (phrase_row_id, int(tag_ids["输入法"])),
            )

            for src, dst, edge_type, weight, evidence in (
                ("输入法", "Agent", "related", 0.95, 4),
                ("输入法", "RAG", "part_of", 0.9, 3),
                ("Agent", "外部项目", "related", 0.7, 2),
            ):
                conn.execute(
                    """
                    INSERT INTO memory_tag_edges(
                        src_tag_id, dst_tag_id, edge_type, weight,
                        direction_bias, evidence_count, updated_at_ms, metadata_json
                    ) VALUES (?, ?, ?, ?, 0.25, ?, 50, '{"source":"dsv4"}')
                    """,
                    (int(tag_ids[src]), int(tag_ids[dst]), edge_type, weight, evidence),
                )

            groups = (
                ("group:input", "输入法时间线", "输入与候选", PROJECT, 0.98),
                ("group:agent", "Agent 时间线", "Agent 运行记录", PROJECT, 0.9),
                ("group:other", "外部时间线", "其他项目", OTHER_PROJECT, 0.8),
            )
            for index, (group_id, title, description, project, quality) in enumerate(groups, start=60):
                conn.execute(
                    """
                    INSERT INTO memory_semantic_groups(
                        group_id, title, description, project, aliases_json, tags_json,
                        source_event_ids_json, status, confidence, quality_score,
                        created_at_ms, updated_at_ms
                    ) VALUES (?, ?, ?, ?, '[]', '[]', '[]', 'active', 0.9, ?, ?, ?)
                    """,
                    (group_id, title, description, project, quality, index, index),
                )
            conn.execute(
                "INSERT INTO memory_books(book_id, book_type, book_key, title, summary, project, tags_json, memory_atom_ids_json, status, quality_score, created_at_ms, updated_at_ms) "
                "VALUES ('book:input', 'topic', 'input', '输入法知识册', '候选与上下文', ?, '[\"输入法\",\"候选\"]', '[\"atom:visible\",\"atom:sensitive\"]', 'active', 0.9, 70, 70)",
                (PROJECT,),
            )
            memberships = (
                ("group:input", "atom", "atom:visible", 0.95),
                ("group:input", "atom", "atom:shared", 0.9),
                ("group:input", "atom", "atom:sensitive", 1.0),
                ("group:input", "tag", tag_ids["输入法"], 0.85),
                ("group:input", "phrase", "phrase:continue", 0.8),
                ("group:agent", "atom", "atom:shared", 0.9),
                ("group:agent", "book", "book:input", 0.75),
                ("group:other", "atom", "atom:other", 0.9),
            )
            for index, (group_id, member_type, member_id, weight) in enumerate(memberships, start=80):
                conn.execute(
                    """
                    INSERT INTO memory_semantic_group_members(
                        group_id, member_type, member_id, weight, source, updated_at_ms
                    ) VALUES (?, ?, ?, ?, 'dsv4', ?)
                    """,
                    (group_id, member_type, member_id, weight, index),
                )
        return {
            "inputTag": tag_ids["输入法"],
            "agentTag": tag_ids["Agent"],
            "otherTag": tag_ids["外部项目"],
            "ragTag": tag_ids["RAG"],
        }

    def test_tag_graph_is_typed_deterministic_and_project_scoped(self) -> None:
        request = {
            "plane": "tags",
            "project": PROJECT,
            "status": "active",
            "depth": 2,
            "nodeLimit": 20,
            "edgeLimit": 20,
            "minWeight": 0.0,
        }
        first = self.service.management.memory_graph(request)
        second = self.service.management.memory_graph(request)

        validate_contract(first, "memory-graph.v1.json")
        self.assertEqual(first["graphRevision"], second["graphRevision"])
        self.assertRegex(first["graphRevision"], r"^sha256:[0-9a-f]{64}$")
        entity_ids = {node["entityId"] for node in first["nodes"]}
        self.assertIn(self.ids["inputTag"], entity_ids)
        self.assertIn(self.ids["agentTag"], entity_ids)
        self.assertIn(self.ids["ragTag"], entity_ids)
        self.assertNotIn(self.ids["otherTag"], entity_ids)
        self.assertTrue(all(node["kind"] == "tag" for node in first["nodes"]))
        self.assertTrue(all(edge["kind"] == "tagRelation" for edge in first["edges"]))
        self.assertNotIn("rawTextVisible", first)
        self.assertNotIn("绝不能出现在图里的敏感正文", json.dumps(first, ensure_ascii=False))

        alias_match = self.service.management.memory_graph(
            {
                "plane": "tags",
                "project": PROJECT,
                "query": "IME",
                "depth": 0,
                "nodeLimit": 10,
                "edgeLimit": 10,
            }
        )
        self.assertEqual(
            [node["entityId"] for node in alias_match["nodes"]],
            [self.ids["inputTag"]],
        )

        edge_bounded = self.service.management.memory_graph(
            {
                "plane": "tags",
                "project": PROJECT,
                "focusId": self.ids["inputTag"],
                "depth": 1,
                "nodeLimit": 20,
                "edgeLimit": 1,
            }
        )
        self.assertEqual(len(edge_bounded["edges"]), 1)
        self.assertTrue(edge_bounded["truncated"]["edges"])

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE memory_tag_edges
                SET weight = 0.88, updated_at_ms = 99
                WHERE src_tag_id = ? AND dst_tag_id = ? AND edge_type = 'related'
                """,
                (int(self.ids["inputTag"]), int(self.ids["agentTag"])),
            )
        changed = self.service.management.memory_graph(request)
        self.assertNotEqual(first["graphRevision"], changed["graphRevision"])

    def test_group_graph_has_typed_members_excludes_sensitive_atoms_and_truncates(self) -> None:
        graph = self.service.management.memory_graph(
            {
                "plane": "groups",
                "project": PROJECT,
                "focusId": "group:input",
                "depth": 2,
                "nodeLimit": 20,
                "edgeLimit": 20,
            }
        )

        validate_contract(graph, "memory-graph.v1.json")
        entity_ids = {node["entityId"] for node in graph["nodes"]}
        self.assertIn("group:input", entity_ids)
        self.assertIn("group:agent", entity_ids)
        self.assertIn("atom:visible", entity_ids)
        self.assertIn("atom:shared", entity_ids)
        self.assertNotIn("atom:sensitive", entity_ids)
        self.assertNotIn("group:other", entity_ids)
        self.assertTrue(all(edge["kind"] == "groupMember" for edge in graph["edges"]))
        self.assertNotIn("绝不能出现在图里的敏感正文", json.dumps(graph, ensure_ascii=False))

        bounded = self.service.management.memory_graph(
            {
                "plane": "groups",
                "project": PROJECT,
                "focusId": "group:input",
                "depth": 1,
                "nodeLimit": 1,
                "edgeLimit": 1,
            }
        )
        self.assertEqual(len(bounded["nodes"]), 1)
        self.assertTrue(bounded["truncated"]["nodes"])

    def test_entity_pages_connections_and_members_independently(self) -> None:
        first = self.service.management.memory_entity(
            "tag",
            self.ids["inputTag"],
            {
                "project": PROJECT,
                "connectionsLimit": 1,
                "membersLimit": 1,
            },
        )

        validate_contract(first, "memory-entity.v1.json")
        self.assertTrue(first["connections"]["hasMore"])
        self.assertTrue(first["members"]["hasMore"])
        self.assertEqual(len(first["connections"]["items"]), 1)
        self.assertEqual(len(first["members"]["items"]), 1)
        self.assertEqual(first["attributes"]["type"], "concept")
        self.assertIn("IME", first["attributes"]["aliases"])
        self.assertNotIn("atom:sensitive", json.dumps(first, ensure_ascii=False))

        next_members = self.service.management.memory_entity(
            "tag",
            self.ids["inputTag"],
            {
                "project": PROJECT,
                "connectionsLimit": 1,
                "membersLimit": 1,
                "membersCursor": first["members"]["nextCursor"],
            },
        )
        first_member = first["members"]["items"][0]["node"]["id"]
        second_member = next_members["members"]["items"][0]["node"]["id"]
        self.assertNotEqual(first_member, second_member)

        group = self.service.management.memory_entity(
            "group",
            "group:input",
            {"project": PROJECT, "connectionsLimit": 5, "membersLimit": 2},
        )
        validate_contract(group, "memory-entity.v1.json")
        self.assertEqual(group["connections"]["items"], [])
        self.assertTrue(group["members"]["hasMore"])
        self.assertNotIn("atom:sensitive", json.dumps(group, ensure_ascii=False))

        book = self.service.management.memory_entity(
            "book",
            "book:input",
            {"project": PROJECT, "connectionsLimit": 5, "membersLimit": 5},
        )
        validate_contract(book, "memory-entity.v1.json")
        self.assertEqual(book["entity"]["memberCount"], 2)
        self.assertEqual(book["attributes"]["type"], "topic")
        self.assertEqual(book["attributes"]["tags"], ["输入法", "候选"])
        self.assertEqual(
            [item["node"]["entityId"] for item in book["connections"]["items"]],
            ["group:agent"],
        )
        self.assertEqual(book["members"]["items"], [])
        serialized_book = json.dumps(book, ensure_ascii=False)
        self.assertNotIn("atom:visible", serialized_book)
        self.assertNotIn("atom:sensitive", serialized_book)
        self.assertNotIn("绝不能出现在图里的敏感正文", serialized_book)
        self.assertNotIn("memory_atom_ids_json", serialized_book)

    def test_read_queries_reject_ambiguous_or_unsafe_shapes(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            before = (
                conn.execute("SELECT COUNT(*) FROM memory_tags").fetchone()[0],
                conn.execute("SELECT COUNT(*) FROM memory_semantic_group_members").fetchone()[0],
                conn.execute("SELECT COUNT(*) FROM management_audit_log").fetchone()[0],
                conn.execute(
                    "SELECT runtime_revision FROM runtime_config_state WHERE singleton_id = 1"
                ).fetchone()[0],
            )
        self.service.management.memory_graph({"plane": "tags", "project": PROJECT})
        self.service.management.memory_entity(
            "group", "group:input", {"project": PROJECT}
        )
        with sqlite3.connect(self.db_path) as conn:
            after = (
                conn.execute("SELECT COUNT(*) FROM memory_tags").fetchone()[0],
                conn.execute("SELECT COUNT(*) FROM memory_semantic_group_members").fetchone()[0],
                conn.execute("SELECT COUNT(*) FROM management_audit_log").fetchone()[0],
                conn.execute(
                    "SELECT runtime_revision FROM runtime_config_state WHERE singleton_id = 1"
                ).fetchone()[0],
            )
        self.assertEqual(before, after)

        with self.assertRaisesRegex(ValueError, "plane"):
            self.service.management.memory_graph({"plane": "timeline"})
        with self.assertRaisesRegex(ValueError, "nodeLimit"):
            self.service.management.memory_graph({"plane": "tags", "nodeLimit": 201})
        with self.assertRaisesRegex(ValueError, "unsupported query field"):
            self.service.management.memory_graph({"plane": "tags", "sql": "SELECT *"})
        with self.assertRaisesRegex(ValueError, "invalid memory tag id"):
            self.service.management.memory_entity("tag", "1 OR 1=1", {})
        with self.assertRaisesRegex(ValueError, "kind"):
            self.service.management.memory_entity("atoms", "atom:visible", {})

    def test_debug_get_handlers_validate_contracts_and_query_allowlists(self) -> None:
        class Handler(DebugRequestHandler):
            pass

        Handler.service = self.service
        Handler.static_dir = Path(self.tmp.name)
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            graph_query = urlencode(
                {
                    "plane": "tags",
                    "project": PROJECT,
                    "focusId": self.ids["inputTag"],
                    "depth": 1,
                    "nodeLimit": 20,
                    "edgeLimit": 20,
                }
            )
            with urlopen(
                f"http://127.0.0.1:{server.server_port}/api/memory/graph?{graph_query}",
                timeout=5,
            ) as response:
                graph = json.loads(response.read().decode("utf-8"))
            validate_contract(graph, "memory-graph.v1.json")

            group_id = quote("group:input", safe="")
            with urlopen(
                f"http://127.0.0.1:{server.server_port}/api/memory/entities/group/{group_id}?membersLimit=2",
                timeout=5,
            ) as response:
                entity = json.loads(response.read().decode("utf-8"))
            validate_contract(entity, "memory-entity.v1.json")

            with self.assertRaises(HTTPError) as caught:
                urlopen(
                    f"http://127.0.0.1:{server.server_port}/api/memory/graph?plane=tags&unexpected=1",
                    timeout=5,
                )
            error_response = caught.exception
            self.assertEqual(error_response.code, 400)
            try:
                error = json.loads(error_response.read().decode("utf-8"))
            finally:
                error_response.close()
            validate_contract(error, "memory-read-error.v1.json")
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()


if __name__ == "__main__":
    unittest.main()
