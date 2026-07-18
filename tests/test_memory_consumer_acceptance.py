from __future__ import annotations

import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from rag_ime.agent_context_runtime import RUNTIME_PROMPT_ENVELOPE_PREFIX
from rag_ime.agent_service import AgentService
from rag_ime.agent_tools import ControlToolGateway
from rag_ime.embeddings import HashingEmbeddingProvider
from rag_ime.generation_memory import (
    generation_memory_evidence_pack,
    retrieve_generation_memory_hits,
)
from rag_ime.local_sqlite_core import LocalSqliteCoreClient
from rag_ime.memory_projectors import ImeMemoryProjector
from rag_ime.pi_runtime import PiRuntimeConfig
from rag_ime.retrieval_docs import rebuild_retrieval_docs


PROJECT = "wisdom-weasel-rag-ime"
OLD_ATOM_ID = "atom:model-choice"
OLD_FACT = "当前输入法仍使用千问 0.8B 模型"
NEW_ATOM_ID = "atom:model-choice-100m"
NEW_FACT = "当前输入法使用 100M 自训练模型并通过验收"
BOOK_ID = "book:ime-model-context"
BOOK_TITLE = "输入法模型上下文书"
BOOK_SUMMARY = "记录输入法模型架构与切换决策，验收标记为模型工具书"
ROLE_MARKER = "已经验证个人记忆的三条消费路径"


class MemoryConsumerAcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(
            prefix="rag-ime-memory-consumer-acceptance-"
        )
        self.root = Path(self.temporary.name)
        self.db_path = self.root / "rag-ime.sqlite"
        self.service = AgentService(
            db_path=self.db_path,
            project=PROJECT,
            runtime_config=PiRuntimeConfig(
                enabled=False,
                executable=None,
                agent_dir=self.root / "agent-config",
                session_dir=self.root / "sessions",
                logs_dir=self.root / "logs",
            ),
        )
        self.core = LocalSqliteCoreClient(
            self.db_path,
            embedding_provider=HashingEmbeddingProvider(dimensions=16),
        )
        self.core.initialize()
        self.gateway = ControlToolGateway(
            sessions=self.service.sessions,
            management=object(),
            core=self.core,
            project=PROJECT,
            role_books=self.service.role_books,
        )
        self.active_role_revision = self._activate_role_book_marker()

    def tearDown(self) -> None:
        self.service.close()
        self.temporary.cleanup()

    def test_generation_retrieves_current_atom_and_book_without_ime_body_leak(
        self,
    ) -> None:
        self._seed_superseded_model_pair()
        self._seed_model_book(memory_atom_id=NEW_ATOM_ID)
        self._rebuild_retrieval_docs()

        hits = retrieve_generation_memory_hits(
            self.core,
            current_context="请根据输入法模型版本和模型架构继续生成",
            project=PROJECT,
            top_k=8,
        )
        evidence = generation_memory_evidence_pack(hits, max_items=8)
        evidence_blob = json.dumps(evidence, ensure_ascii=False, sort_keys=True)

        self.assertIn(NEW_ATOM_ID, evidence_blob)
        self.assertIn(NEW_FACT, evidence_blob)
        self.assertIn(BOOK_ID, evidence_blob)
        self.assertIn(BOOK_SUMMARY, evidence_blob)
        recalled_atom_ids = {
            str(atom_id)
            for item in evidence
            for atom_id in item.get("atomIds", [])
        }
        self.assertNotIn(OLD_ATOM_ID, recalled_atom_ids)
        self.assertNotIn(OLD_FACT, evidence_blob)

        # Generation consumes evidence. IME insertion remains a stricter
        # projection and must not expose Atom/Book bodies without surface hints.
        ime_candidates = ImeMemoryProjector().project(
            list(hits),
            query_text="输入法模型版本",
            top_k=8,
        )
        ime_blob = json.dumps(
            [candidate.__dict__ for candidate in ime_candidates],
            ensure_ascii=False,
            sort_keys=True,
        )
        self.assertNotIn(NEW_FACT, ime_blob)
        self.assertNotIn(BOOK_SUMMARY, ime_blob)

    def test_session_bootstrap_retrieves_relevant_atom_and_book_for_the_session(
        self,
    ) -> None:
        self._seed_superseded_model_pair()
        self._seed_model_book(memory_atom_id=NEW_ATOM_ID)
        self._rebuild_retrieval_docs()
        created = self.service.create_session({"title": "记忆首次注入验收"})
        session = created["session"]
        session_id = str(session["id"])

        accepted = [
            {
                "accepted": True,
                "turnId": "turn:memory-acceptance:1",
                "piEntryId": "entry:memory-acceptance:1",
                "response": {"success": True},
            },
            {
                "accepted": True,
                "turnId": "turn:memory-acceptance:2",
                "piEntryId": "entry:memory-acceptance:2",
                "response": {"success": True},
            },
        ]
        with patch.object(
            self.service.runtime,
            "prompt",
            side_effect=accepted,
        ) as runtime_prompt:
            first = self.service.prompt(session_id, {"message": "输入法模型架构现在是什么？"})
            second = self.service.prompt(session_id, {"message": "继续展开测试"})

        first_runtime_message = runtime_prompt.call_args_list[0].args[1]
        self.assertTrue(first_runtime_message.startswith(RUNTIME_PROMPT_ENVELOPE_PREFIX))
        first_envelope = json.loads(
            first_runtime_message.removeprefix(RUNTIME_PROMPT_ENVELOPE_PREFIX)
        )
        transient_context = str(first_envelope["transientContext"])
        second_runtime_message = runtime_prompt.call_args_list[1].args[1]

        self.assertEqual(first["contextItemsDelivered"], 1)
        self.assertEqual(second["contextItemsDelivered"], 0)
        self.assertEqual(first_envelope["message"], "输入法模型架构现在是什么？")
        self.assertIn("## 新 Session 个人记忆召回", transient_context)
        self.assertIn(NEW_ATOM_ID, transient_context)
        self.assertIn(NEW_FACT, transient_context)
        self.assertIn(BOOK_ID, transient_context)
        self.assertIn(BOOK_SUMMARY, transient_context)
        self.assertNotIn(f"来源: `{OLD_ATOM_ID}`", transient_context)
        self.assertNotIn(OLD_FACT, transient_context)
        self.assertEqual(second_runtime_message, "继续展开测试")
        self.assertEqual(
            len(self.service.context_runtime.list_items(session_id, status="consumed")),
            1,
        )

        self.assertEqual(
            session["roleBookRevisionId"],
            self.active_role_revision["revisionId"],
        )
        system_prompt = self.service.runtime_factory.config.system_prompt_for_session(
            session
        )
        self.assertIn("<agent-role-book>", system_prompt)
        self.assertIn(ROLE_MARKER, system_prompt)
        self.assertNotIn(NEW_ATOM_ID, system_prompt)
        self.assertNotIn(BOOK_ID, system_prompt)

    def test_governed_correction_converges_tools_projection_and_new_session(
        self,
    ) -> None:
        self._seed_old_current_model_fact()
        self._seed_model_book(memory_atom_id=OLD_ATOM_ID)
        governed_session = self.service.create_session({"title": "受治理记忆更正"})[
            "session"
        ]
        governed_session_id = str(governed_session["id"])
        evidence = self.service.memory_evidence.record_user_message(
            session_id=governed_session_id,
            pi_entry_id="message:memory-correction-acceptance",
            turn_id="turn:memory-correction-acceptance",
            role_id=str(governed_session["roleId"]),
            text="用户明确确认当前输入法使用 100M 自训练模型",
            occurred_at_ms=int(time.time() * 1_000),
        )["evidence"]

        before_atoms = self._table_count("memory_atoms")
        before_outbox = self._table_count("memory_projection_outbox")
        preview = self._execute_tool(
            governed_session_id,
            "ime_memory",
            "correct_preview",
            targetId=OLD_ATOM_ID,
            text=NEW_FACT,
            memoryKind="fact",
            reason="旧模型事实已被用户明确更新",
            evidenceIds=[evidence["evidenceId"]],
        )["result"]

        self.assertFalse(preview["mutationApplied"])
        self.assertEqual(self._table_count("memory_atoms"), before_atoms)
        self.assertEqual(self._table_count("memory_projection_outbox"), before_outbox)
        self.assertEqual(self._atom_state(OLD_ATOM_ID), ("active", "current"))

        prepared = self._execute_tool(
            governed_session_id,
            "ime_memory",
            "correct_apply",
            proposalId=preview["proposalId"],
        )["result"]
        self.assertTrue(prepared["approvalRequired"])
        decided = self.service.sessions.decide_approval(
            str(prepared["approvalId"]),
            approved=True,
            payload_sha256=str(prepared["approval"]["payloadSha256"]),
        )
        receipt = self.gateway.apply_approval(decided)
        new_atom_id = str(receipt["memoryId"])

        self.assertEqual(self._atom_state(OLD_ATOM_ID), ("superseded", "superseded"))
        self.assertEqual(self._atom_state(new_atom_id), ("approved", "current"))
        current = self._execute_tool(
            governed_session_id,
            "ime_memory",
            "search",
        )["result"]
        current_ids = {str(item["memoryId"]) for item in current["items"]}
        self.assertIn(new_atom_id, current_ids)
        self.assertNotIn(OLD_ATOM_ID, current_ids)

        projection = self.core.process_memory_projection_outbox(max_events=32)
        with sqlite3.connect(self.db_path) as conn:
            outbox_state = conn.execute(
                "SELECT state FROM memory_projection_outbox WHERE outbox_id = ?",
                (receipt["projectionOutboxId"],),
            ).fetchone()[0]
            atom_doc_ids = {
                str(row[0])
                for row in conn.execute(
                    "SELECT source_id FROM memory_retrieval_docs WHERE doc_type = 'atom'"
                ).fetchall()
            }
        self.assertEqual(outbox_state, "applied")
        self.assertIn(int(receipt["projectionOutboxId"]), projection["applied"])
        self.assertTrue(projection["freshness"]["fresh"])
        self.assertIn(new_atom_id, atom_doc_ids)
        self.assertNotIn(OLD_ATOM_ID, atom_doc_ids)

        active_role_revision_id = str(
            self.service.role_books.active("zhiyou-v1", "1")["revisionId"]
        )
        role_proposal = self._execute_tool(
            governed_session_id,
            "agent_role_book",
            "propose_revision",
            updates={
                "recentWork": [
                    {
                        "itemId": "recent:governed-correction",
                        "text": "完成受治理记忆更正的组合验收",
                        "provenance": {
                            "sourceType": "agent-session",
                            "sourceId": governed_session_id,
                            "observedAtMs": int(time.time() * 1_000),
                        },
                        "evidenceIds": [str(evidence["evidenceId"])],
                    }
                ]
            },
            changeSummary="记录受治理记忆更正验收",
        )["result"]
        draft = role_proposal["result"]["draft"]
        self.assertEqual(draft["status"], "draft")
        self.assertTrue(role_proposal["result"]["reviewRequired"])
        self.assertFalse(role_proposal["result"]["activationAvailableInTool"])
        self.assertEqual(
            self.service.role_books.active("zhiyou-v1", "1")["revisionId"],
            active_role_revision_id,
        )

        new_session = self.service.create_session({"title": "更正后的新会话"})["session"]
        new_session_id = str(new_session["id"])
        with patch.object(
            self.service.runtime,
            "prompt",
            return_value={
                "accepted": True,
                "turnId": "turn:corrected-bootstrap",
                "piEntryId": "entry:corrected-bootstrap",
                "response": {"success": True},
            },
        ) as runtime_prompt:
            result = self.service.prompt(
                new_session_id,
                {"message": "当前输入法使用哪个模型？"},
            )

        runtime_message = runtime_prompt.call_args.args[1]
        envelope = json.loads(
            runtime_message.removeprefix(RUNTIME_PROMPT_ENVELOPE_PREFIX)
        )
        transient_context = str(envelope["transientContext"])
        self.assertEqual(result["contextItemsDelivered"], 1)
        self.assertIn(new_atom_id, transient_context)
        self.assertIn(NEW_FACT, transient_context)
        self.assertNotIn(f"来源: `{OLD_ATOM_ID}`", transient_context)
        self.assertNotIn(OLD_FACT, transient_context)

    def _activate_role_book_marker(self) -> dict[str, object]:
        role = self.service.personas.resolve("zhiyou-v1", "1")
        self.service.role_books.ensure_seeded(
            role.role_id,
            role.version,
            role.display_name,
            role.summary,
            role.version,
            created_at_ms=1,
        )
        draft = self.service.role_books.propose_revision(
            role.role_id,
            role.version,
            {
                "recentWork": [
                    {
                        "itemId": "recent:memory-consumer-acceptance",
                        "text": ROLE_MARKER,
                        "provenance": {
                            "sourceType": "acceptance-test",
                            "sourceId": "memory-consumer-acceptance",
                            "observedAtMs": 2,
                        },
                        "evidenceIds": ["acceptance:memory-consumer"],
                    }
                ]
            },
            proposed_by="acceptance-test",
            change_summary="Seed a visible Role Book acceptance marker",
            created_at_ms=2,
        )
        return self.service.role_books.activate_revision(
            draft["revisionId"],
            activated_by="acceptance-test",
            reason="Prepare the pinned Role Book acceptance fixture",
            activated_at_ms=3,
        )

    def _seed_old_current_model_fact(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO memory_atoms(
                    id, kind, text, canonical_text, source_event_ids_json,
                    source_memory_ids_json, scope_app, scope_project, language,
                    confidence, quality_score, echo_risk, privacy_level, status,
                    created_at_ms, updated_at_ms, last_used_at_ms, claim_key,
                    lineage_id, claim_state, valid_from_ms, valid_to_ms,
                    supersedes_id
                ) VALUES (?, 'fact', ?, ?, '[]', '[]', NULL, ?, 'zh',
                          1.0, 1.0, 0.0, 'local', 'active', 10, 10, NULL,
                          'input-model-choice', 'lineage:input-model-choice',
                          'current', 10, NULL, NULL)
                """,
                (OLD_ATOM_ID, OLD_FACT, OLD_FACT, PROJECT),
            )

    def _seed_superseded_model_pair(self) -> None:
        self._seed_old_current_model_fact()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE memory_atoms
                SET status = 'superseded', claim_state = 'superseded',
                    valid_to_ms = 20, updated_at_ms = 20
                WHERE id = ?
                """,
                (OLD_ATOM_ID,),
            )
            conn.execute(
                """
                INSERT INTO memory_atoms(
                    id, kind, text, canonical_text, source_event_ids_json,
                    source_memory_ids_json, scope_app, scope_project, language,
                    confidence, quality_score, echo_risk, privacy_level, status,
                    created_at_ms, updated_at_ms, last_used_at_ms, claim_key,
                    lineage_id, claim_state, valid_from_ms, valid_to_ms,
                    supersedes_id
                ) VALUES (?, 'fact', ?, ?, '[]', ?, NULL, ?, 'zh',
                          1.0, 1.0, 0.0, 'local', 'active', 20, 20, NULL,
                          'input-model-choice', 'lineage:input-model-choice',
                          'current', 20, NULL, ?)
                """,
                (
                    NEW_ATOM_ID,
                    NEW_FACT,
                    NEW_FACT,
                    json.dumps([OLD_ATOM_ID], ensure_ascii=False),
                    PROJECT,
                    OLD_ATOM_ID,
                ),
            )

    def _seed_model_book(self, *, memory_atom_id: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO memory_books(
                    book_id, book_type, book_key, title, summary, normalized_text,
                    project, app, tags_json, surface_hints_json,
                    query_expansions_json, source_event_ids_json,
                    memory_atom_ids_json, status, confidence, quality_score,
                    created_at_ms, updated_at_ms, metadata_json
                ) VALUES (?, 'topic', 'ime-model-context', ?, ?, ?, ?, '', ?,
                          '[]', '[]', '[]', ?, 'active', 1.0, 1.0, 20, 20, '{}')
                """,
                (
                    BOOK_ID,
                    BOOK_TITLE,
                    BOOK_SUMMARY,
                    f"{BOOK_TITLE} {BOOK_SUMMARY} 输入法 模型 架构 切换",
                    PROJECT,
                    json.dumps(["输入法", "模型", "架构"], ensure_ascii=False),
                    json.dumps([memory_atom_id], ensure_ascii=False),
                ),
            )

    def _rebuild_retrieval_docs(self) -> None:
        with self.core._connect() as conn:  # type: ignore[attr-defined]
            rebuild_retrieval_docs(conn, project=PROJECT)

    def _execute_tool(
        self,
        session_id: str,
        tool: str,
        operation: str,
        **args: object,
    ) -> dict[str, object]:
        return self.gateway.execute(
            {
                "schemaVersion": "rag-ime.agent-tool-call.v1",
                "sessionId": session_id,
                "tool": tool,
                "toolCallId": f"acceptance:{tool}:{operation}",
                "args": {"op": operation, **args},
            }
        )

    def _table_count(self, table: str) -> int:
        with sqlite3.connect(self.db_path) as conn:
            return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

    def _atom_state(self, atom_id: str) -> tuple[str, str]:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT status, claim_state FROM memory_atoms WHERE id = ?",
                (atom_id,),
            ).fetchone()
        if row is None:
            self.fail(f"memory atom is missing: {atom_id}")
        return str(row[0]), str(row[1])


if __name__ == "__main__":
    unittest.main()
