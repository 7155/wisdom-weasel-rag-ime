from __future__ import annotations

import hashlib
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from rag_ime.agent_memory_query import AgentMemoryQueryService
from rag_ime.agent_rooms import AgentRoomStore
from rag_ime.agent_sessions import AgentSessionStore


class _GraphStore:
    def __init__(self) -> None:
        self.initialized = False
        self.calls: list[tuple[str, object, dict[str, object]]] = []

    def initialize(self) -> None:
        self.initialized = True

    def find_anchors(self, principal, **kwargs):
        self.calls.append(("find_anchors", principal, dict(kwargs)))
        return {
            "anchors": [
                {
                    "entityId": "entity:memory",
                    "name": "输入法记忆",
                    "entityType": "topic",
                }
            ]
        }

    def expand(self, principal, **kwargs):
        self.calls.append(("expand", principal, dict(kwargs)))
        return {
            "relations": [
                {
                    "relationId": "relation:1",
                    "fact": "输入法记忆属于当前项目",
                }
            ]
        }

    def get_sources(self, principal, **kwargs):
        self.calls.append(("get_sources", principal, dict(kwargs)))
        return {
            "sources": [
                {
                    "sourceType": "atom",
                    "sourceId": "atom:1",
                    "text": "统一使用增强后的混合检索",
                }
            ]
        }


class AgentMemoryQueryServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-agent-memory-query-")
        self.db_path = Path(self.tmp.name) / "rag-ime.sqlite"
        sessions = AgentSessionStore(self.db_path)
        sessions.initialize()
        self.session = sessions.create(
            title="memory query",
            role_id="memory-researcher-v1",
            created_at_ms=10,
        )
        peer = sessions.create(title="peer", role_id="reviewer-v1", created_at_ms=11)
        self.peer = peer
        self.room = AgentRoomStore(self.db_path).create(
            title="memory room",
            routing_policy="manual_mentions",
            participants=(
                {
                    "sessionId": self.session["id"],
                    "roleId": "memory-researcher-v1",
                    "roleVersion": "1",
                    "displayName": "研究员",
                },
                {
                    "sessionId": peer["id"],
                    "roleId": "reviewer-v1",
                    "roleVersion": "1",
                    "displayName": "复核员",
                },
            ),
            created_at_ms=12,
        )
        self.graph = _GraphStore()
        self.service = AgentMemoryQueryService(
            self.db_path,
            project="wisdom-weasel-rag-ime",
            graph_store=self.graph,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_search_reuses_hybrid_retrieval_then_rrf_deduplicates_sources(self) -> None:
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            source_event_ids: list[int] = []
            for text in ("统一使用增强后的混合检索", "补充检索证据"):
                row = conn.execute(
                    """
                    INSERT INTO input_events(
                        created_at_ms, source, committed_text, recent_context, preedit,
                        schema_id, app, project, provider_name, tags_json,
                        context_group_id, context_group_level
                    ) VALUES (20, 'ime', ?, '', '', 'test', 'RagImeControl', ?, 'test', '[]', '', 'session')
                    """,
                    (text, "wisdom-weasel-rag-ime"),
                )
                event_id = int(row.lastrowid)
                source_event_ids.append(event_id)
                conn.execute(
                    "INSERT INTO memory_state(event_id, updated_at_ms) VALUES (?, 20)",
                    (event_id,),
                )
        retrieval = {
            "hits": [
                {
                    "doc_id": "doc:atom:1",
                    "doc_type": "atom",
                    "source_id": "atom:1",
                    "text": "统一使用增强后的混合检索",
                    "tags": ("RAG",),
                    "source_lane": "bm25_raw",
                    "rank": 1,
                    "raw_score": -7.5,
                    "metadata": {
                        "bookId": "book:ime",
                        "sourceEventIds": source_event_ids,
                    },
                },
                {
                    "doc_id": "doc:atom:2",
                    "doc_type": "atom",
                    "source_id": "atom:2",
                    "text": "另一个只有词法命中的来源",
                    "tags": (),
                    "source_lane": "bm25_raw",
                    "rank": 2,
                    "raw_score": -3.0,
                    "metadata": {},
                },
                {
                    "doc_id": "doc:atom:1",
                    "doc_type": "atom",
                    "source_id": "atom:1",
                    "text": "统一使用增强后的混合检索",
                    "tags": ("RAG",),
                    "source_lane": "vector_tag_boost",
                    "rank": 3,
                    "raw_score": 0.82,
                    "metadata": {"bookId": "book:ime"},
                },
            ],
            "lanes": {
                "bm25_raw": {"weight": 1.0, "count": 2},
                "vector_tag_boost": {"weight": 1.05, "count": 1},
            },
            "elapsedMs": 17,
            "parallelExecution": True,
            "overBudget": False,
            "vectorIndexDocuments": 8,
            # Agent evidence must not be built from completion candidates.
            "candidates": [{"text": "不应进入 evidence"}],
        }

        with patch(
            "rag_ime.agent_memory_query.retrieve_hybrid_rag_candidates",
            return_value=retrieval,
        ) as retrieve:
            result = self.service.search(
                str(self.session["id"]),
                query_text="输入法 RAG",
                limit=8,
            )

        self.assertTrue(self.graph.initialized)
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["items"][0]["sourceId"], "atom:1")
        self.assertEqual(
            result["items"][0]["sourceLanes"],
            ["bm25_raw", "vector_tag_boost"],
        )
        self.assertEqual(result["items"][0]["rawScores"]["bm25_raw"], -7.5)
        self.assertGreater(result["items"][0]["score"], result["items"][1]["score"])
        self.assertNotIn("不应进入 evidence", str(result))
        query = retrieve.call_args.args[1]
        self.assertEqual(query.project, "wisdom-weasel-rag-ime")
        self.assertEqual(query.latency_budget_ms, 500)
        self.assertEqual(query.top_k, 8)

        name, principal, kwargs = self.graph.calls[0]
        self.assertEqual(name, "find_anchors")
        self.assertEqual(principal.agent_id, self.session["agentId"])
        self.assertEqual(principal.room_ids, (self.room["id"],))
        self.assertEqual(kwargs["source_refs"][0]["sourceId"], "atom:1")
        self.assertIn(
            {
                "sourceType": "input_event",
                "sourceId": str(source_event_ids[0]),
                "sourceRevision": 1,
            },
            kwargs["source_refs"],
        )
        self.assertEqual(result["anchors"][0]["entityId"], "entity:memory")
        self.assertEqual(result["lanes"]["bm25_raw"]["weight"], 1.0)
        self.assertEqual(result["lanes"]["bm25_raw"]["docIds"], ["doc:atom:1", "doc:atom:2"])
        self.assertEqual(result["lanes"]["vector_tag_boost"]["docIds"], ["doc:atom:1"])
        self.assertEqual(result["diagnostics"]["rawHitCount"], 3)

    def test_search_filters_other_agent_tool_receipts_but_keeps_user_prompts(self) -> None:
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            event_ids: dict[str, int] = {}
            for role, text in (("tool_receipt", "peer private tool result"), ("user", "user shared prompt")):
                event = conn.execute(
                    """
                    INSERT INTO input_events(
                        created_at_ms, source, committed_text, recent_context, preedit,
                        schema_id, app, project, provider_name, tags_json,
                        context_group_id, context_group_level
                    ) VALUES (20, ?, ?, '', '', 'agent-session', 'RagImeControl', ?, 'pi-rpc', '[]', '', 'session')
                    """,
                    (f"pi_agent_{role}", text, "wisdom-weasel-rag-ime"),
                )
                event_id = int(event.lastrowid)
                event_ids[role] = event_id
                conn.execute("INSERT INTO memory_state(event_id, updated_at_ms) VALUES (?, 20)", (event_id,))
                conn.execute(
                    """
                    INSERT INTO agent_memory_sources(
                        source_id, session_id, pi_entry_id, input_event_id, source_role,
                        source_revision, canonical_text_sha256, status, created_at_ms
                    ) VALUES (?, ?, ?, ?, ?, 1, ?, 'active', 20)
                    """,
                    (
                        f"source:{role}",
                        str(self.peer["id"]),
                        f"entry:{role}",
                        event_id,
                        role,
                        hashlib.sha256(text.encode()).hexdigest(),
                    ),
                )
        retrieval = {
            "hits": [
                {
                    "doc_id": f"item:private-{event_ids['tool_receipt']}",
                    "doc_type": "item",
                    "source_id": "private-item",
                    "text": "peer private tool result",
                    "source_lane": "bm25_raw",
                    "rank": 1,
                    "raw_score": 1,
                    "metadata": {"sourceEventId": event_ids["tool_receipt"]},
                },
                {
                    "doc_id": f"item:public-{event_ids['user']}",
                    "doc_type": "item",
                    "source_id": "public-item",
                    "text": "user shared prompt",
                    "source_lane": "bm25_raw",
                    "rank": 2,
                    "raw_score": 1,
                    "metadata": {"sourceEventId": event_ids["user"]},
                },
            ],
            "lanes": {"bm25_raw": {"weight": 1.0}},
        }
        with patch("rag_ime.agent_memory_query.retrieve_hybrid_rag_candidates", return_value=retrieval):
            result = self.service.search(str(self.session["id"]), query_text="agent memory")

        self.assertEqual([item["sourceId"] for item in result["items"]], ["public-item"])
        self.assertEqual(result["diagnostics"]["aclFilteredHitCount"], 1)

    def test_room_owned_tool_receipt_is_visible_only_to_active_room_members(self) -> None:
        outsider = AgentSessionStore(self.db_path).create(
            title="outsider",
            role_id="outsider-v1",
            created_at_ms=13,
        )
        text = "房间内共享的工具结论"
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            event = conn.execute(
                """
                INSERT INTO input_events(
                    created_at_ms, source, committed_text, recent_context, preedit,
                    schema_id, app, project, provider_name, tags_json,
                    context_group_id, context_group_level
                ) VALUES (20, 'pi_agent_tool_receipt', ?, '', '', 'agent-session',
                          'RagImeControl', 'wisdom-weasel-rag-ime', 'pi-rpc', '[]', '', 'session')
                """,
                (text,),
            )
            event_id = int(event.lastrowid)
            conn.execute("INSERT INTO memory_state(event_id, updated_at_ms) VALUES (?, 20)", (event_id,))
            conn.execute(
                """
                INSERT INTO agent_memory_sources(
                    source_id, session_id, pi_entry_id, input_event_id, source_role,
                    source_revision, canonical_text_sha256, status, created_at_ms
                ) VALUES ('source:room', ?, 'entry:room', ?, 'tool_receipt', 1, ?, 'active', 20)
                """,
                (str(self.peer["id"]), event_id, hashlib.sha256(text.encode()).hexdigest()),
            )
        retrieval = {
            "hits": [
                {
                    "doc_id": "item:room",
                    "doc_type": "item",
                    "source_id": "room-item",
                    "text": text,
                    "source_lane": "bm25_raw",
                    "rank": 1,
                    "raw_score": 1,
                    "metadata": {
                        "sourceEventId": event_id,
                        "ownerKind": "room",
                        "ownerId": self.room["id"],
                    },
                }
            ],
            "lanes": {"bm25_raw": {"weight": 1.0}},
        }
        with patch("rag_ime.agent_memory_query.retrieve_hybrid_rag_candidates", return_value=retrieval):
            member_view = self.service.search(str(self.session["id"]), query_text="共享结论")
            outsider_view = self.service.search(str(outsider["id"]), query_text="共享结论")

        self.assertEqual(member_view["count"], 1)
        self.assertEqual(outsider_view["count"], 0)

        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute("UPDATE agent_memory_sources SET status = 'archived' WHERE source_id = 'source:room'")
        with patch("rag_ime.agent_memory_query.retrieve_hybrid_rag_candidates", return_value=retrieval):
            archived_view = self.service.search(str(self.session["id"]), query_text="共享结论")
        self.assertEqual(archived_view["count"], 0)
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute("DELETE FROM agent_memory_sources WHERE source_id = 'source:room'")
        with patch("rag_ime.agent_memory_query.retrieve_hybrid_rag_candidates", return_value=retrieval):
            orphaned_view = self.service.search(str(self.session["id"]), query_text="共享结论")
        self.assertEqual(orphaned_view["count"], 0)

    def test_expand_and_get_sources_keep_graph_access_bounded(self) -> None:
        expanded = self.service.expand(
            str(self.session["id"]),
            anchor_ids=("entity:1", "entity:1", "entity:2"),
            max_depth=9,
            limit=99,
            as_of_ms=1234,
        )
        sources = self.service.get_sources(
            str(self.session["id"]),
            relation_ids=("relation:1", "relation:1"),
            source_refs=(
                {"sourceType": "atom", "sourceId": "atom:1"},
                {"sourceType": "atom", "sourceId": "atom:1"},
                {"sourceType": "", "sourceId": "ignored"},
            ),
            limit=99,
        )

        self.assertEqual(expanded["count"], 1)
        self.assertEqual(sources["count"], 1)
        expand_call = self.graph.calls[0]
        self.assertEqual(expand_call[2]["anchor_ids"], ["entity:1", "entity:2"])
        self.assertEqual(expand_call[2]["max_depth"], 3)
        self.assertEqual(expand_call[2]["limit"], 50)
        self.assertEqual(expand_call[2]["as_of_ms"], 1234)
        source_call = self.graph.calls[1]
        self.assertEqual(source_call[2]["relation_ids"], ["relation:1"])
        self.assertEqual(
            source_call[2]["source_refs"],
            [{"sourceType": "atom", "sourceId": "atom:1"}],
        )
        self.assertEqual(source_call[2]["limit"], 50)

    def test_cross_project_and_unanchored_requests_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "cross-project"):
            self.service.search(
                str(self.session["id"]),
                query_text="secret",
                project="another-project",
            )
        with self.assertRaisesRegex(ValueError, "anchorIds"):
            self.service.expand(str(self.session["id"]), anchor_ids=())
        with self.assertRaisesRegex(ValueError, "relationIds is required"):
            self.service.get_sources(str(self.session["id"]))
        with self.assertRaisesRegex(ValueError, "asOfMs"):
            self.service.expand(
                str(self.session["id"]),
                anchor_ids=("entity:1",),
                as_of_ms=-1,
            )


if __name__ == "__main__":
    unittest.main()
