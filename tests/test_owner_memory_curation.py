from __future__ import annotations

import json
import re
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from rag_ime.activity_timeline import DailyActivityTimelineStore
from rag_ime.agent_memory_sources import AgentMemorySourceStore
from rag_ime.agent_sessions import AgentSessionStore
from rag_ime.local_sqlite_core import LocalSqliteCoreClient
from rag_ime.memory_book_lifecycle import set_memory_book_archive_status
from rag_ime.memory_book_compiler import (
    apply_stored_memory_book_run,
    rollback_memory_book_run,
    update_stored_memory_book_diff,
)
from rag_ime.models import InputEvent
from rag_ime.owner_memory_curation import OwnerMemoryCurator
from rag_ime.personal_context import (
    AgentMemoryEvidenceStore,
    local_date_for_timestamp,
)


class _FakeOrganizer:
    provider_name = "fixture"

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[dict[str, object]] = []

    def curate_owner_memory(
        self,
        *,
        bundle: dict[str, object],
        project: str,
        owner_kind: str,
        owner_id: str,
        instruction: str = "",
    ) -> dict[str, object]:
        if self.fail:
            raise RuntimeError("fixture organizer unavailable")
        self.calls.append(
            {
                "ownerKind": owner_kind,
                "ownerId": owner_id,
                "inputs": list(bundle.get("inputs") or []),
                "recentEvents": list(bundle.get("recentEvents") or []),
            }
        )
        inputs = [dict(item) for item in bundle.get("inputs") or []]
        event_ids = [
            int(event_id)
            for item in inputs
            for event_id in item.get("sourceEventIds") or []
        ]
        return {
            "schemaVersion": "rag-ime.owner-memory-curation.v1",
            "provider": "fixture",
            "model": "fixture-memory",
            "sourceDecisions": [
                {
                    "sourceRef": item["sourceRef"],
                    "disposition": "remember",
                    "reasonCode": "durable_user_intent",
                    "confidence": 0.96,
                }
                for item in inputs
            ],
            "topicBooks": [
                {
                    "title": "长期工作方式",
                    "summary": "保留这一批跨会话仍然有效的决定和约束。",
                    "sourceEventIds": event_ids,
                    "confidence": 0.9,
                    "qualityScore": 0.9,
                }
            ],
            "memoryAtoms": [
                {
                    "canonicalText": str(item["text"]),
                    "summary": "长期有效的记忆证据",
                    "kind": "project_decision",
                    "sourceEventIds": list(item["sourceEventIds"]),
                    "confidence": 0.9,
                    "qualityScore": 0.9,
                    "directCandidateAllowed": False,
                }
                for item in inputs
            ],
            "warnings": [],
        }


class _MultiTopicOrganizer(_FakeOrganizer):
    def curate_owner_memory(
        self,
        *,
        bundle: dict[str, object],
        project: str,
        owner_kind: str,
        owner_id: str,
        instruction: str = "",
    ) -> dict[str, object]:
        result = super().curate_owner_memory(
            bundle=bundle,
            project=project,
            owner_kind=owner_kind,
            owner_id=owner_id,
            instruction=instruction,
        )
        inputs = [dict(item) for item in bundle.get("inputs") or []]
        result["memoryAtoms"] = [
            {
                "canonicalText": str(item["text"]),
                "summary": "主题内稳定事实",
                "kind": "project_requirement",
                "sourceEventIds": list(item["sourceEventIds"]),
                "confidence": 0.95,
                "qualityScore": 0.9,
                "directCandidateAllowed": False,
            }
            for item in inputs
        ]
        result["topicBooks"] = [
            {
                "title": "RAG IME 记忆架构",
                "summary": "Atom、Topic Book 和 Timeline 必须保持独立。",
                "sourceEventIds": list(inputs[0]["sourceEventIds"]),
                "tags": ["RAG IME", "记忆架构"],
                "confidence": 0.95,
                "qualityScore": 0.9,
            },
            {
                "title": "本地模型配置",
                "summary": "记忆整理使用低成本模型并按固定频率运行。",
                "sourceEventIds": list(inputs[1]["sourceEventIds"]),
                "tags": ["模型配置"],
                "confidence": 0.95,
                "qualityScore": 0.9,
            },
        ]
        return result


class _DecisionOnlyOrganizer:
    provider_name = "fixture"

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def curate_owner_memory(
        self,
        *,
        bundle: dict[str, object],
        project: str,
        owner_kind: str,
        owner_id: str,
        instruction: str = "",
    ) -> dict[str, object]:
        del project, owner_kind, owner_id, instruction
        inputs = [dict(item) for item in bundle.get("inputs") or []]
        self.calls.append([str(item["text"]) for item in inputs])
        return {
            "schemaVersion": "rag-ime.owner-memory-curation.v1",
            "provider": "fixture",
            "model": "fixture-memory",
            "sourceDecisions": [
                {
                    "sourceRef": item["sourceRef"],
                    "disposition": (
                        "needs_review"
                        if "指代不清" in str(item["text"])
                        else "not_for_memory"
                    ),
                    "reasonCode": (
                        "ambiguous_reference"
                        if "指代不清" in str(item["text"])
                        else "one_batch_test_input"
                    ),
                    "confidence": 0.95,
                }
                for item in inputs
            ],
            "topicBooks": [],
            "memoryAtoms": [],
        }


class _AtomOnlyOrganizer(_FakeOrganizer):
    def curate_owner_memory(
        self,
        *,
        bundle: dict[str, object],
        project: str,
        owner_kind: str,
        owner_id: str,
        instruction: str = "",
    ) -> dict[str, object]:
        result = super().curate_owner_memory(
            bundle=bundle,
            project=project,
            owner_kind=owner_kind,
            owner_id=owner_id,
            instruction=instruction,
        )
        result["topicBooks"] = []
        return result


class _OmittingOrganizer:
    provider_name = "fixture"

    def curate_owner_memory(
        self,
        *,
        bundle: dict[str, object],
        project: str,
        owner_kind: str,
        owner_id: str,
        instruction: str = "",
    ) -> dict[str, object]:
        del project, owner_kind, owner_id, instruction
        first = dict((bundle.get("inputs") or [])[0])
        return {
            "schemaVersion": "rag-ime.owner-memory-curation.v1",
            "provider": "fixture",
            "model": "fixture-memory",
            "sourceDecisions": [
                {
                    "sourceRef": first["sourceRef"],
                    "disposition": "remember",
                    "reasonCode": "durable_user_intent",
                    "confidence": 0.95,
                }
            ],
            "topicBooks": [],
            "memoryAtoms": [
                {
                    "canonicalText": str(first["text"]),
                    "summary": "模型已覆盖的稳定证据",
                    "kind": "project_requirement",
                    "sourceEventIds": list(first["sourceEventIds"]),
                    "confidence": 0.9,
                    "qualityScore": 0.9,
                    "directCandidateAllowed": False,
                }
            ],
        }


class _AtomDecisionOmittingOrganizer(_OmittingOrganizer):
    def curate_owner_memory(
        self,
        *,
        bundle: dict[str, object],
        project: str,
        owner_kind: str,
        owner_id: str,
        instruction: str = "",
    ) -> dict[str, object]:
        result = super().curate_owner_memory(
            bundle=bundle,
            project=project,
            owner_kind=owner_kind,
            owner_id=owner_id,
            instruction=instruction,
        )
        result["sourceDecisions"] = []
        return result


class _TimelineOnlyFactOrganizer:
    provider_name = "fixture"

    def __init__(self, timeline_event_id: int) -> None:
        self.timeline_event_id = timeline_event_id
        self.calls: list[dict[str, object]] = []

    def curate_owner_memory(
        self,
        *,
        bundle: dict[str, object],
        project: str,
        owner_kind: str,
        owner_id: str,
        instruction: str = "",
    ) -> dict[str, object]:
        del project, owner_kind, owner_id, instruction
        self.calls.append(bundle)
        inputs = [dict(item) for item in bundle.get("inputs") or []]
        return {
            "schemaVersion": "rag-ime.owner-memory-curation.v1",
            "provider": "fixture",
            "model": "fixture-memory",
            "sourceDecisions": [
                {
                    "sourceRef": item["sourceRef"],
                    "disposition": "remember",
                    "reasonCode": "durable_user_intent",
                    "confidence": 0.9,
                }
                for item in inputs
            ],
            "topicBooks": [],
            "memoryAtoms": [
                {
                    "canonicalText": "仅由活动时间线猜测出的完成事实",
                    "summary": "不应通过治理",
                    "kind": "project_fact",
                    "sourceEventIds": [self.timeline_event_id],
                    "confidence": 0.9,
                    "qualityScore": 0.9,
                    "directCandidateAllowed": False,
                }
            ],
        }


class _ConversationCapturingOrganizer:
    provider_name = "fixture"

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def curate_owner_memory(
        self,
        *,
        bundle: dict[str, object],
        project: str,
        owner_kind: str,
        owner_id: str,
        instruction: str = "",
    ) -> dict[str, object]:
        del project, owner_kind, owner_id, instruction
        self.calls.append(bundle)
        inputs = [dict(item) for item in bundle.get("inputs") or []]
        return {
            "schemaVersion": "rag-ime.owner-memory-curation.v1",
            "provider": "fixture",
            "model": "fixture-memory",
            "sourceDecisions": [
                {
                    "sourceRef": item["sourceRef"],
                    "disposition": "not_for_memory",
                    "reasonCode": "conversation_context_budget_test",
                    "confidence": 0.99,
                }
                for item in inputs
            ],
            "topicBooks": [],
            "memoryAtoms": [],
        }


class _ClaimAwareOrganizer:
    provider_name = "fixture"

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def curate_owner_memory(
        self,
        *,
        bundle: dict[str, object],
        project: str,
        owner_kind: str,
        owner_id: str,
        instruction: str = "",
    ) -> dict[str, object]:
        del project, owner_kind, owner_id, instruction
        self.calls.append(bundle)
        source = dict((bundle.get("inputs") or [])[0])
        existing = [
            dict(item)
            for item in bundle.get("existingMemoryAtoms") or []
            if isinstance(item, dict)
        ]
        claim_key = (
            str(existing[0].get("claimKey") or "")
            if existing
            else "project:memory.maintenance-cadence"
        )
        return {
            "schemaVersion": "rag-ime.owner-memory-curation.v1",
            "provider": "fixture",
            "model": "fixture-memory",
            "sourceDecisions": [
                {
                    "sourceRef": source["sourceRef"],
                    "disposition": "remember",
                    "reasonCode": "durable_preference",
                    "confidence": 0.99,
                }
            ],
            "memoryAtoms": [
                {
                    "canonicalText": str(source["text"]),
                    "summary": "记忆维护频率",
                    "kind": "durable_preference",
                    "claimKey": claim_key,
                    "sourceEventIds": list(source["sourceEventIds"]),
                    "confidence": 0.99,
                    "qualityScore": 0.95,
                    "directCandidateAllowed": False,
                }
            ],
            "topicBooks": (
                []
                if existing
                else [
                    {
                        "title": "记忆维护策略",
                        "summary": "记忆维护使用明确的周期配置。",
                        "sourceEventIds": list(source["sourceEventIds"]),
                        "confidence": 0.95,
                        "qualityScore": 0.9,
                    }
                ]
            ),
        }


class _BundleCaptureOrganizer:
    provider_name = "fixture"

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def curate_owner_memory(
        self,
        *,
        bundle: dict[str, object],
        project: str,
        owner_kind: str,
        owner_id: str,
        instruction: str = "",
    ) -> dict[str, object]:
        del project, owner_kind, owner_id, instruction
        self.calls.append(bundle)
        return {
            "schemaVersion": "rag-ime.owner-memory-curation.v1",
            "provider": "fixture",
            "model": "fixture-memory",
            "sourceDecisions": [
                {
                    "sourceRef": item["sourceRef"],
                    "disposition": "not_for_memory",
                    "reasonCode": "test_capture_only",
                    "confidence": 0.99,
                }
                for item in bundle.get("inputs") or []
                if isinstance(item, dict)
            ],
            "memoryAtoms": [],
            "topicBooks": [],
        }


class _StressUpdateOrganizer:
    provider_name = "fixture-stress"
    _UPDATE_RE = re.compile(
        r"输入法部署槽\s+(model-slot-\d{3})\s+当前版本更新为\s+v(\d+)"
    )

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.missing_claim_keys: list[str] = []

    def curate_owner_memory(
        self,
        *,
        bundle: dict[str, object],
        project: str,
        owner_kind: str,
        owner_id: str,
        instruction: str = "",
    ) -> dict[str, object]:
        del project, owner_kind, owner_id, instruction
        self.calls.append(bundle)
        existing_by_claim = {
            str(item.get("claimKey") or ""): dict(item)
            for item in bundle.get("existingMemoryAtoms") or []
            if isinstance(item, dict) and item.get("claimKey")
        }
        decisions: list[dict[str, object]] = []
        atoms: list[dict[str, object]] = []
        for raw in bundle.get("inputs") or []:
            if not isinstance(raw, dict):
                continue
            match = self._UPDATE_RE.search(str(raw.get("text") or ""))
            if match is None:
                decisions.append(
                    {
                        "sourceRef": raw["sourceRef"],
                        "disposition": "not_for_memory",
                        "reasonCode": "stress_non_fact",
                        "confidence": 0.99,
                    }
                )
                continue
            slot, version = match.groups()
            claim_key = f"ime:{slot}:current-version"
            if claim_key not in existing_by_claim:
                self.missing_claim_keys.append(claim_key)
                decisions.append(
                    {
                        "sourceRef": raw["sourceRef"],
                        "disposition": "needs_review",
                        "reasonCode": "stress_missing_previous_claim",
                        "confidence": 0.99,
                    }
                )
                continue
            decisions.append(
                {
                    "sourceRef": raw["sourceRef"],
                    "disposition": "remember",
                    "reasonCode": "stress_version_update",
                    "confidence": 0.99,
                }
            )
            atoms.append(
                {
                    "canonicalText": f"输入法部署槽 {slot} 当前版本为 v{version}。",
                    "summary": f"{slot} 当前版本",
                    "kind": "project_fact",
                    "claimKey": claim_key,
                    "sourceEventIds": list(raw.get("sourceEventIds") or []),
                    "confidence": 0.99,
                    "qualityScore": 0.99,
                    "directCandidateAllowed": False,
                }
            )
        return {
            "schemaVersion": "rag-ime.owner-memory-curation.v1",
            "provider": self.provider_name,
            "model": "deterministic-stress",
            "sourceDecisions": decisions,
            "memoryAtoms": atoms,
            "topicBooks": [],
            # Intentionally omit supersedes: the write gate must close the old
            # current version from the reused claimKey atomically.
            "supersedes": [],
        }


class _OverCapacityOrganizer:
    provider_name = "fixture-over-capacity"

    def curate_owner_memory(
        self,
        *,
        bundle: dict[str, object],
        project: str,
        owner_kind: str,
        owner_id: str,
        instruction: str = "",
    ) -> dict[str, object]:
        del project, owner_kind, owner_id, instruction
        source = dict(bundle["inputs"][0])
        source_event_ids = list(source.get("sourceEventIds") or [])
        return {
            "schemaVersion": "rag-ime.owner-memory-curation.v1",
            "provider": self.provider_name,
            "model": "deterministic-over-capacity",
            "sourceDecisions": [
                {
                    "sourceRef": source["sourceRef"],
                    "disposition": "remember",
                    "reasonCode": "dense_fact_batch",
                    "confidence": 0.99,
                }
            ],
            "memoryAtoms": [
                {
                    "canonicalText": f"密集输入中的长期事实 {index}。",
                    "summary": f"事实 {index}",
                    "kind": "project_fact",
                    "claimKey": f"dense:fact:{index}",
                    "sourceEventIds": source_event_ids,
                    "confidence": 0.99,
                    "qualityScore": 0.99,
                    "directCandidateAllowed": False,
                }
                for index in range(7)
            ],
            "topicBooks": [],
            "supersedes": [],
        }


class _ExplicitForgetOrganizer:
    provider_name = "fixture"

    def curate_owner_memory(
        self,
        *,
        bundle: dict[str, object],
        project: str,
        owner_kind: str,
        owner_id: str,
        instruction: str = "",
    ) -> dict[str, object]:
        del project, owner_kind, owner_id, instruction
        source = dict((bundle.get("inputs") or [])[0])
        target = dict((bundle.get("existingMemoryAtoms") or [])[0])
        return {
            "schemaVersion": "rag-ime.owner-memory-curation.v1",
            "provider": "fixture",
            "model": "fixture-memory",
            "sourceDecisions": [
                {
                    "sourceRef": source["sourceRef"],
                    "disposition": "not_for_memory",
                    "reasonCode": "explicit_memory_forget",
                    "confidence": 0.99,
                }
            ],
            "memoryAtoms": [],
            "topicBooks": [],
            "memoryRetractions": [
                {
                    "targetAtomId": target["atomId"],
                    "reason": "用户明确要求忘记该偏好",
                    "sourceEventIds": list(source["sourceEventIds"]),
                    "confidence": 0.99,
                }
            ],
        }


class OwnerMemoryCuratorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-owner-curation-")
        self.db_path = Path(self.tmp.name) / "rag-ime.sqlite"
        self.sessions = AgentSessionStore(self.db_path)
        self.sessions.initialize()
        self.user_session = self.sessions.create(
            title="知游",
            role_id="companion-present-v1",
            role_version="1",
            created_at_ms=1,
        )
        self.other_session = self.sessions.create(
            title="另一个角色",
            role_id="librarian-v1",
            role_version="1",
            created_at_ms=2,
        )
        self.sources = AgentMemorySourceStore(
            self.db_path,
            project="wisdom-weasel-rag-ime",
        )
        self.sources.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_rime_fragments_are_curated_as_one_input_without_crossing_projects(self) -> None:
        core = LocalSqliteCoreClient(self.db_path)
        core.initialize()
        project_a_ids: list[int] = []
        for offset, committed, context in (
            (100, "BM", "目前BM"),
            (200, "25", "目前BM25"),
            (300, "这些", "目前BM25这些"),
            (400, "真实", "目前BM25这些真实实现"),
        ):
            event = core.record_event(
                InputEvent(
                    event_id=None,
                    created_at_ms=offset,
                    source="squirrel_rime_commit_burst",
                    committed_text=committed,
                    recent_context=context,
                    privacy_disposition="allowed",
                    app="com.openai.codex",
                    project="project-a",
                    context_group_id="app:codex",
                )
            )
            project_a_ids.append(int(event.split(":", 1)[1]))
        core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=500,
                source="manual_commit",
                committed_text="项目 B 的私有决定",
                privacy_disposition="allowed",
                project="project-b",
            )
        )
        organizer = _FakeOrganizer()
        curator = OwnerMemoryCurator(
            self.db_path,
            organizer=organizer,
            project="project-a",
            clock_ms=lambda: 1_000,
            initial_settle_ms=0,
        )
        curator.initialize()

        report = curator.run_due(current_ms=1_000)

        self.assertTrue(report["ok"])
        self.assertEqual(report["ranScopeCount"], 1)
        self.assertEqual(len(organizer.calls), 1)
        inputs = organizer.calls[0]["inputs"]
        self.assertEqual(len(inputs), 1)
        self.assertEqual(inputs[0]["text"], "目前BM25这些真实实现")
        self.assertEqual(inputs[0]["sourceEventIds"], project_a_ids)
        self.assertEqual(len(inputs[0]["sourceIds"]), 4)
        recent_events = organizer.calls[0]["recentEvents"]
        self.assertEqual(recent_events[0]["sourceEventIds"], project_a_ids)
        self.assertEqual(recent_events[0]["sourceIds"], inputs[0]["sourceIds"])
        self.assertEqual(recent_events[0]["source"], "reconstructed_user_input")
        self.assertEqual(recent_events[0]["app"], "com.openai.codex")
        self.assertEqual(recent_events[0]["contextGroupId"], "app:codex")
        self.assertEqual(report["results"][0]["sourceCount"], 4)
        self.assertEqual(report["results"][0]["logicalInputCount"], 1)
        with closing(sqlite3.connect(self.db_path)) as conn:
            rows = conn.execute(
                """
                SELECT e.project, s.disposition
                FROM agent_memory_sources AS s
                JOIN input_events AS e ON e.id = s.input_event_id
                ORDER BY e.id
                """
            ).fetchall()
            metadata_row = conn.execute(
                """
                SELECT metadata_json
                FROM memory_cleanup_runs
                WHERE run_id = ?
                """,
                (report["results"][0]["runId"],),
            ).fetchone()
            conn.row_factory = sqlite3.Row
            apply_stored_memory_book_run(
                conn,
                run_id=report["results"][0]["runId"],
            )
            atom_row = conn.execute(
                """
                SELECT source_event_ids_json
                FROM memory_atoms
                WHERE status = 'active'
                LIMIT 1
                """
            ).fetchone()
        self.assertEqual(
            rows,
            [
                ("project-a", "remember"),
                ("project-a", "remember"),
                ("project-a", "remember"),
                ("project-a", "remember"),
                ("project-b", "pending"),
            ],
        )
        metadata = json.loads(metadata_row[0])
        source_ref = metadata["sourceInputRefs"][0]
        self.assertEqual(source_ref["sourceEventIds"], project_a_ids)
        self.assertEqual(source_ref["sourceIds"], inputs[0]["sourceIds"])
        self.assertEqual(source_ref["app"], "com.openai.codex")
        self.assertEqual(source_ref["contextGroupId"], "app:codex")
        self.assertEqual(json.loads(atom_row[0]), project_a_ids)

    def test_owner_curation_builds_independent_thematic_topic_books(self) -> None:
        for index, text in enumerate(
            (
                "RAG IME 的 Atom、Topic Book 和 Timeline 必须独立存储。",
                "记忆整理模型固定使用 deepseek-v4-flash，每天运行两次。",
            ),
            start=1,
        ):
            self.sources.checkpoint_user_message(
                session_id=str(self.user_session["id"]),
                pi_entry_id=f"entry:topic-{index}",
                turn_id=f"turn:topic-{index}",
                text=text,
                created_at_ms=index * 100,
            )
        curator = OwnerMemoryCurator(
            self.db_path,
            organizer=_MultiTopicOrganizer(),
            project="wisdom-weasel-rag-ime",
            initial_settle_ms=0,
            auto_apply=True,
        )

        report = curator.run_due(current_ms=1_000)

        self.assertTrue(report["ok"], report)
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            books = conn.execute(
                """
                SELECT book_id, title, memory_atom_ids_json
                FROM memory_books
                WHERE status = 'active'
                ORDER BY title
                """
            ).fetchall()
            atoms = conn.execute(
                """
                SELECT id, canonical_text
                FROM memory_atoms
                WHERE status = 'active' AND claim_state = 'current'
                ORDER BY canonical_text
                """
            ).fetchall()
        self.assertEqual(
            {str(row["title"]) for row in books},
            {"RAG IME 记忆架构", "本地模型配置"},
        )
        self.assertNotIn("个人长期记忆", {str(row["title"]) for row in books})
        member_sets = [
            set(json.loads(str(row["memory_atom_ids_json"]))) for row in books
        ]
        self.assertEqual([len(member_ids) for member_ids in member_sets], [1, 1])
        self.assertTrue(member_sets[0].isdisjoint(member_sets[1]))
        self.assertEqual(
            set.union(*member_sets),
            {str(row["id"]) for row in atoms},
        )

    def test_initial_settle_window_tracks_the_latest_source(self) -> None:
        self.sources.checkpoint_user_message(
            session_id=str(self.user_session["id"]),
            pi_entry_id="entry:first-settle",
            turn_id="turn:first-settle",
            text="项目长期使用本地 SQLite。",
            created_at_ms=100,
        )
        last_source_ms = 1_199_900
        self.sources.checkpoint_user_message(
            session_id=str(self.user_session["id"]),
            pi_entry_id="entry:latest-settle",
            turn_id="turn:latest-settle",
            text="刚刚补充的分钟级上下文。",
            created_at_ms=last_source_ms,
        )
        settle_ms = 20 * 60 * 1_000
        curator = OwnerMemoryCurator(
            self.db_path,
            organizer=_FakeOrganizer(),
            project="wisdom-weasel-rag-ime",
            initial_settle_ms=settle_ms,
        )
        curator.initialize()

        status = curator.status(current_ms=settle_ms + 100)
        scope = status["scopes"][0]

        self.assertFalse(scope["due"])
        self.assertEqual(scope["nextDueAtMs"], last_source_ms + settle_ms)
        self.assertEqual(scope["dueReason"], "not_due")


    def test_minute_scale_compaction_cannot_become_durable_memory(self) -> None:
        compaction = self.sources.checkpoint_compaction(
            session_id=str(self.other_session["id"]),
            result={
                "summary": "刚刚检查了页面，当前操作已经结束。",
                "firstKeptEntryId": "entry:kept",
            },
            trigger="automatic",
            created_at_ms=1_000,
        )
        curator = OwnerMemoryCurator(
            self.db_path,
            organizer=_FakeOrganizer(),
            project="wisdom-weasel-rag-ime",
            initial_settle_ms=0,
            auto_apply=True,
        )
        curator.initialize()

        report = curator.run_due(
            owner_kind="agent",
            owner_id="librarian-v1",
            current_ms=2_000,
        )

        self.assertEqual(
            self.sources.get(str(compaction["source"]["sourceId"]))[
                "disposition"
            ],
            "not_for_memory",
        )
        with closing(sqlite3.connect(self.db_path)) as conn:
            atom_count = int(
                conn.execute("SELECT COUNT(*) FROM memory_atoms").fetchone()[0]
            )
        self.assertEqual(atom_count, 0)


    def test_daily_run_separates_user_and_role_books_and_forgets_noise_reversibly(self) -> None:
        noise = self.sources.checkpoint_user_message(
            session_id=str(self.user_session["id"]),
            pi_entry_id="entry:noise",
            turn_id="turn:noise",
            text="嗯嗯那个这个",
            created_at_ms=100,
        )
        durable = self.sources.checkpoint_user_message(
            session_id=str(self.user_session["id"]),
            pi_entry_id="entry:decision",
            turn_id="turn:decision",
            text="不要截图，桌面上下文默认读取 Accessibility Tree。",
            created_at_ms=200,
        )
        compaction = self.sources.checkpoint_compaction(
            session_id=str(self.other_session["id"]),
            result={
                "summary": "用户要求这个角色每天整理自己的主题书，但不读取助手逐轮输出。",
                "firstKeptEntryId": "entry:kept",
            },
            trigger="automatic",
            created_at_ms=300,
        )
        organizer = _FakeOrganizer()
        curator = OwnerMemoryCurator(
            self.db_path,
            organizer=organizer,
            project="wisdom-weasel-rag-ime",
            clock_ms=lambda: 1_000,
            initial_settle_ms=0,
        )
        curator.initialize()

        report = curator.run_due(current_ms=1_000)

        self.assertTrue(report["ok"])
        self.assertEqual(report["ranScopeCount"], 2)
        self.assertEqual(
            {(call["ownerKind"], call["ownerId"]) for call in organizer.calls},
            {("user", "default"), ("agent", "librarian-v1")},
        )
        self.assertEqual(
            self.sources.get(str(noise["source"]["sourceId"]))["disposition"],
            "not_for_memory",
        )
        self.assertEqual(
            self.sources.get(str(durable["source"]["sourceId"]))["disposition"],
            "remember",
        )
        self.assertEqual(
            self.sources.get(str(compaction["source"]["sourceId"]))["disposition"],
            "remember",
        )
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            runs = conn.execute(
                """
                SELECT run_id, owner_kind, owner_id, run_kind, status
                FROM memory_cleanup_runs
                WHERE run_kind = 'daily_curation'
                ORDER BY owner_kind, owner_id
                """
            ).fetchall()
            self.assertEqual(
                [(row["owner_kind"], row["owner_id"], row["status"]) for row in runs],
                [
                    ("agent", "librarian-v1", "draft"),
                    ("user", "default", "draft"),
                ],
            )
            agent_run_id = next(
                str(row["run_id"])
                for row in runs
                if row["owner_kind"] == "agent"
            )
            for row in runs:
                apply_stored_memory_book_run(conn, run_id=str(row["run_id"]))
            books = conn.execute(
                """
                SELECT owner_kind, owner_id, title
                FROM memory_books
                ORDER BY owner_kind, owner_id
                """
            ).fetchall()
            atoms = conn.execute(
                """
                SELECT owner_kind, owner_id, canonical_text
                FROM memory_atoms
                ORDER BY owner_kind, owner_id
                """
            ).fetchall()
        self.assertEqual(
            [(row["owner_kind"], row["owner_id"]) for row in books],
            [("agent", "librarian-v1"), ("user", "default")],
        )
        self.assertEqual(
            [(row["owner_kind"], row["owner_id"]) for row in atoms],
            [("agent", "librarian-v1"), ("user", "default")],
        )
        self.assertEqual(
            self.sources.get(str(durable["source"]["sourceId"]))["disposition"],
            "consolidated",
        )
        self.assertEqual(
            self.sources.get(str(compaction["source"]["sourceId"]))["disposition"],
            "consolidated",
        )

        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            rollback_memory_book_run(conn, run_id=agent_run_id)
            conn.commit()
        self.assertEqual(
            self.sources.get(str(compaction["source"]["sourceId"]))["disposition"],
            "remember",
        )
        role_scope = curator.status(
            owner_kind="agent",
            owner_id="librarian-v1",
            current_ms=1_200,
        )["scopes"][0]
        self.assertTrue(role_scope["due"])
        self.assertEqual(role_scope["status"], "idle")

        restored = self.sources.set_disposition(
            str(noise["source"]["sourceId"]),
            disposition="pending",
            reason_code="user_restored",
            actor_kind="rollback",
            created_at_ms=1_100,
        )
        self.assertEqual(restored["source"]["disposition"], "pending")

    def test_twice_daily_auto_apply_needs_no_user_review(self) -> None:
        durable = self.sources.checkpoint_user_message(
            session_id=str(self.user_session["id"]),
            pi_entry_id="entry:auto-apply",
            turn_id="turn:auto-apply",
            text="记忆整理每天运行两次，并在治理校验后自动应用。",
            created_at_ms=100,
        )
        curator = OwnerMemoryCurator(
            self.db_path,
            organizer=_FakeOrganizer(),
            project="wisdom-weasel-rag-ime",
            clock_ms=lambda: 1_000,
            initial_settle_ms=0,
            daily_interval_ms=12 * 60 * 60 * 1_000,
            auto_apply=True,
        )
        curator.initialize()

        report = curator.run_due(current_ms=1_000)

        self.assertTrue(report["ok"])
        self.assertEqual(report["ranScopeCount"], 1)
        result = report["results"][0]
        self.assertEqual(result["runStatus"], "applied")
        self.assertTrue(result["autoApplied"])
        self.assertFalse(result["reviewRequired"])
        self.assertEqual(report["status"]["policy"]["cadence"], "twice_daily")
        self.assertTrue(
            report["status"]["policy"]["autoApplyGovernedWrites"]
        )
        with closing(sqlite3.connect(self.db_path)) as conn:
            run_status = str(
                conn.execute(
                    "SELECT status FROM memory_cleanup_runs WHERE run_id = ?",
                    (result["runId"],),
                ).fetchone()[0]
            )
            atom_count = int(
                conn.execute("SELECT COUNT(*) FROM memory_atoms").fetchone()[0]
            )
            book_count = int(
                conn.execute("SELECT COUNT(*) FROM memory_books").fetchone()[0]
            )
            cursor_status, next_due_at_ms = conn.execute(
                """
                SELECT status, next_due_at_ms
                FROM memory_curation_cursors
                WHERE owner_kind = 'user' AND owner_id = 'default'
                """
            ).fetchone()
        self.assertEqual(run_status, "applied")
        self.assertEqual(atom_count, 1)
        self.assertEqual(book_count, 1)
        self.assertEqual(cursor_status, "idle")
        self.assertEqual(next_due_at_ms, 1_000 + 12 * 60 * 60 * 1_000)
        self.assertEqual(
            self.sources.get(str(durable["source"]["sourceId"]))["disposition"],
            "consolidated",
        )

    def test_daily_model_sees_dialogue_and_timeline_but_timeline_cannot_prove_fact(
        self,
    ) -> None:
        timestamp = 1_784_318_400_000
        checkpoint = self.sources.checkpoint_user_message(
            session_id=str(self.user_session["id"]),
            pi_entry_id="entry:joint-context",
            turn_id="turn:joint-context",
            text="输入法个人记忆需要按可追溯证据整理。",
            created_at_ms=timestamp,
        )
        evidence = AgentMemoryEvidenceStore(
            self.db_path,
            project="wisdom-weasel-rag-ime",
        )
        evidence.record_user_message(
            session_id=str(self.user_session["id"]),
            pi_entry_id="evidence:user:joint-context",
            turn_id="turn:joint-context",
            role_id="companion-present-v1",
            text="继续整理输入法个人记忆",
            occurred_at_ms=timestamp,
        )
        evidence.record_assistant_message(
            session_id=str(self.user_session["id"]),
            pi_entry_id="evidence:assistant:joint-context",
            turn_id="turn:joint-context",
            role_id="companion-present-v1",
            text="我会先验证联合上下文，再生成待审草案。",
            occurred_at_ms=timestamp + 1_000,
        )
        core = LocalSqliteCoreClient(self.db_path)
        timeline_event_id = int(
            core.record_event(
                InputEvent(
                    event_id=None,
                    created_at_ms=timestamp + 2_000,
                    source="squirrel_commit",
                    committed_text="在 TextEdit 实现时间线过滤",
                    privacy_disposition="allowed",
                    app="com.apple.TextEdit",
                    project="wisdom-weasel-rag-ime",
                )
            ).split(":", 1)[1]
        )
        timeline_date = local_date_for_timestamp(timestamp)
        DailyActivityTimelineStore(
            self.db_path,
            project="wisdom-weasel-rag-ime",
        ).build_draft(timeline_date, generated_at_ms=timestamp + 3_000)
        organizer = _TimelineOnlyFactOrganizer(timeline_event_id)
        curator = OwnerMemoryCurator(
            self.db_path,
            organizer=organizer,
            project="wisdom-weasel-rag-ime",
            clock_ms=lambda: timestamp + 10_000,
            initial_settle_ms=0,
        )

        result = curator.run_due(current_ms=timestamp + 10_000)

        self.assertTrue(result["ok"])
        self.assertEqual(result["ranScopeCount"], 1)
        self.assertEqual(result["results"][0]["runStatus"], "idle")
        self.assertEqual(result["results"][0]["diffCount"], 0)
        bundle = organizer.calls[0]
        self.assertIn("在 TextEdit 实现时间线过滤", bundle["activityContext"]["summary"])
        messages = bundle["agentConversationContext"]["messages"]
        self.assertEqual([item["role"] for item in messages], ["user"])
        self.assertNotIn(
            "待审草案",
            json.dumps(messages, ensure_ascii=False),
        )
        serialized_activity = json.dumps(bundle["activityContext"], ensure_ascii=False)
        serialized_conversation = json.dumps(
            bundle["agentConversationContext"], ensure_ascii=False
        )
        self.assertNotIn("sourceEventIds", serialized_activity)
        self.assertNotIn("evidenceId", serialized_conversation)
        legal_ids = bundle["legalSourceEventIds"]
        self.assertEqual(
            legal_ids,
            [int(checkpoint["source"]["inputEventId"])],
        )
        self.assertNotIn(timeline_event_id, legal_ids)
        with closing(sqlite3.connect(self.db_path)) as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM memory_cleanup_diffs"
                ).fetchone()[0],
                0,
            )

    def test_daily_model_reads_latest_digest_plus_small_post_digest_tail(self) -> None:
        timestamp = 1_784_318_400_000
        session_id = str(self.user_session["id"])
        self.sources.checkpoint_user_message(
            session_id=session_id,
            pi_entry_id="entry:digest-budget",
            turn_id="turn:digest-budget",
            text="对话整理需要使用摘要加少量新尾部。",
            created_at_ms=timestamp,
        )
        evidence = AgentMemoryEvidenceStore(
            self.db_path,
            project="wisdom-weasel-rag-ime",
        )
        evidence.record_user_message(
            session_id=session_id,
            pi_entry_id="evidence:user:before-digest",
            turn_id="turn:before-digest",
            role_id="companion-present-v1",
            text="摘要前的原始用户对话不应重复发送",
            occurred_at_ms=timestamp + 1_000,
        )
        evidence.record_assistant_message(
            session_id=session_id,
            pi_entry_id="evidence:assistant:before-digest",
            turn_id="turn:before-digest",
            role_id="companion-present-v1",
            text="摘要前的原始助手回答不应重复发送",
            occurred_at_ms=timestamp + 2_000,
        )
        evidence.record_session_digest(
            session_id=session_id,
            digest_id="digest:old",
            role_id="companion-present-v1",
            text="已经过期的旧摘要",
            occurred_at_ms=timestamp + 3_000,
        )
        evidence.record_session_digest(
            session_id=session_id,
            digest_id="digest:latest",
            role_id="companion-present-v1",
            text="最新压缩摘要：用户要求对话整理省 token，并保留可追溯索引。",
            occurred_at_ms=timestamp + 4_000,
        )
        evidence.record_user_message(
            session_id=session_id,
            pi_entry_id="evidence:user:after-digest",
            turn_id="turn:after-digest",
            role_id="companion-present-v1",
            text="摘要之后新增的用户要求",
            occurred_at_ms=timestamp + 5_000,
        )
        evidence.record_user_message(
            session_id=session_id,
            pi_entry_id="evidence:user:workflow-noise",
            turn_id="turn:workflow-noise",
            role_id="companion-present-v1",
            text="请调用 memory 的 curation_prepare 并返回 runId。",
            occurred_at_ms=timestamp + 5_500,
        )
        evidence.record_assistant_message(
            session_id=session_id,
            pi_entry_id="evidence:assistant:after-digest",
            turn_id="turn:after-digest",
            role_id="companion-present-v1",
            text="摘要之后新增的助手回答" * 80,
            occurred_at_ms=timestamp + 6_000,
        )
        organizer = _ConversationCapturingOrganizer()
        curator = OwnerMemoryCurator(
            self.db_path,
            organizer=organizer,
            project="wisdom-weasel-rag-ime",
            clock_ms=lambda: timestamp + 10_000,
            initial_settle_ms=0,
        )

        report = curator.run_due(current_ms=timestamp + 10_000)

        self.assertTrue(report["ok"])
        context = organizer.calls[0]["agentConversationContext"]
        messages = context["messages"]
        self.assertEqual(
            [item["sourceKind"] for item in messages],
            ["session_digest", "user_message", "assistant_message"],
        )
        serialized = json.dumps(context, ensure_ascii=False)
        self.assertIn("最新压缩摘要", serialized)
        self.assertIn("摘要之后新增的用户要求", serialized)
        self.assertNotIn("curation_prepare", serialized)
        self.assertNotIn("摘要前的原始用户对话", serialized)
        self.assertNotIn("摘要前的原始助手回答", serialized)
        self.assertNotIn("已经过期的旧摘要", serialized)
        self.assertLessEqual(sum(len(item["text"]) for item in messages), 2_000)
        self.assertLessEqual(len(messages[-1]["text"]), 320)
        self.assertTrue(context["corroborationOnly"])
        self.assertFalse(context["maySupportFacts"])

    def test_needs_review_source_stays_ahead_of_cursor_for_next_daily_pass(self) -> None:
        first = self.sources.checkpoint_user_message(
            session_id=str(self.user_session["id"]),
            pi_entry_id="entry:stable",
            turn_id="turn:stable",
            text="每天整理一次长期记忆。",
            created_at_ms=100,
        )
        second = self.sources.checkpoint_user_message(
            session_id=str(self.user_session["id"]),
            pi_entry_id="entry:ambiguous",
            turn_id="turn:ambiguous",
            text="这个以后照旧，但当前指代不清。",
            created_at_ms=200,
        )
        organizer = _DecisionOnlyOrganizer()
        curator = OwnerMemoryCurator(
            self.db_path,
            organizer=organizer,
            project="wisdom-weasel-rag-ime",
            clock_ms=lambda: 1_000,
            initial_settle_ms=0,
            daily_interval_ms=60_000,
        )
        curator.initialize()

        first_report = curator.run_due(current_ms=1_000)
        first_status = curator.status(current_ms=1_000)
        second_report = curator.run_due(current_ms=61_001)

        self.assertTrue(first_report["ok"], first_report)
        self.assertEqual(
            first_status["scopes"][0]["lastSourceCursor"]["sourceId"],
            str(first["source"]["sourceId"]),
        )
        self.assertEqual(first_status["needsReviewSourceCount"], 1)
        self.assertEqual(
            self.sources.get(str(second["source"]["sourceId"]))["disposition"],
            "needs_review",
        )
        self.assertTrue(second_report["ok"])
        self.assertEqual(
            organizer.calls,
            [
                ["每天整理一次长期记忆。", "这个以后照旧，但当前指代不清。"],
                ["这个以后照旧，但当前指代不清。"],
            ],
        )

    def test_organizer_omission_fails_closed_and_does_not_advance_past_source(self) -> None:
        first = self.sources.checkpoint_user_message(
            session_id=str(self.user_session["id"]),
            pi_entry_id="entry:covered",
            turn_id="turn:covered",
            text="每天整理一次长期记忆。",
            created_at_ms=100,
        )
        omitted = self.sources.checkpoint_user_message(
            session_id=str(self.user_session["id"]),
            pi_entry_id="entry:omitted",
            turn_id="turn:omitted",
            text="这条证据不能因为模型漏项而消失。",
            created_at_ms=200,
        )
        curator = OwnerMemoryCurator(
            self.db_path,
            organizer=_OmittingOrganizer(),
            project="wisdom-weasel-rag-ime",
            initial_settle_ms=0,
        )
        curator.initialize()

        report = curator.run_due(current_ms=1_000)
        status = report["status"]["scopes"][0]

        self.assertTrue(report["ok"], report)
        self.assertEqual(
            self.sources.get(str(first["source"]["sourceId"]))["disposition"],
            "remember",
        )
        omitted_source = self.sources.get(str(omitted["source"]["sourceId"]))
        self.assertEqual(omitted_source["disposition"], "needs_review")
        self.assertEqual(
            omitted_source["dispositionReason"],
            "model_decision_missing",
        )
        self.assertEqual(
            status["lastSourceCursor"]["sourceId"],
            str(first["source"]["sourceId"]),
        )
        self.assertEqual(status["needsReviewSourceCount"], 1)

    def test_auto_apply_closes_omitted_sources_from_atom_first_output(self) -> None:
        durable = self.sources.checkpoint_user_message(
            session_id=str(self.user_session["id"]),
            pi_entry_id="entry:auto-durable",
            turn_id="turn:auto-durable",
            text="时间线保持独立索引，按时间意图召回。",
            created_at_ms=100,
        )
        noise = self.sources.checkpoint_user_message(
            session_id=str(self.user_session["id"]),
            pi_entry_id="entry:auto-noise",
            turn_id="turn:auto-noise",
            text="你好呀",
            created_at_ms=200,
        )
        curator = OwnerMemoryCurator(
            self.db_path,
            organizer=_AtomDecisionOmittingOrganizer(),
            project="wisdom-weasel-rag-ime",
            initial_settle_ms=0,
            auto_apply=True,
        )
        curator.initialize()

        report = curator.run_due(current_ms=1_000)

        self.assertTrue(report["ok"], report)
        self.assertEqual(
            self.sources.get(str(durable["source"]["sourceId"]))["disposition"],
            "consolidated",
        )
        forgotten = self.sources.get(str(noise["source"]["sourceId"]))
        self.assertEqual(forgotten["disposition"], "not_for_memory")
        self.assertEqual(
            forgotten["dispositionReason"],
            "model_omitted_no_durable_atom",
        )
        scope = report["status"]["scopes"][0]
        self.assertEqual(scope["needsReviewSourceCount"], 0)
        self.assertEqual(
            scope["lastSourceCursor"]["sourceId"],
            str(noise["source"]["sourceId"]),
        )

    def test_draft_blocks_repeated_model_calls(self) -> None:
        self.sources.checkpoint_user_message(
            session_id=str(self.user_session["id"]),
            pi_entry_id="entry:preference",
            turn_id="turn:preference",
            text="每天只整理一次角色记忆。",
            created_at_ms=100,
        )
        organizer = _FakeOrganizer()
        curator = OwnerMemoryCurator(
            self.db_path,
            organizer=organizer,
            project="wisdom-weasel-rag-ime",
            initial_settle_ms=0,
        )
        curator.initialize()

        first = curator.run_due(current_ms=1_000)
        second = curator.run_due(current_ms=100_000_000)

        self.assertEqual(first["ranScopeCount"], 1)
        self.assertEqual(second["ranScopeCount"], 0)
        self.assertEqual(len(organizer.calls), 1)
        scope = second["status"]["scopes"][0]
        self.assertEqual(scope["dueReason"], "draft_pending_review")

    def test_transient_tool_receipts_are_not_promoted_to_long_term_memory(self) -> None:
        source = self.sources.checkpoint_tool_receipt(
            {
                "approvalId": "approval:pause-ai",
                "sessionId": str(self.user_session["id"]),
                "state": "applied",
                "receipt": {
                    "mutationApplied": True,
                    "summary": "AI 辅助已暂停，普通 Rime 拼音仍可使用。",
                },
            },
            created_at_ms=100,
        )
        organizer = _FakeOrganizer()
        curator = OwnerMemoryCurator(
            self.db_path,
            organizer=organizer,
            project="wisdom-weasel-rag-ime",
            initial_settle_ms=0,
        )
        curator.initialize()

        report = curator.run_due(
            manual=True,
            owner_kind="shared",
            owner_id="wisdom-weasel-rag-ime",
            current_ms=1_000,
        )

        self.assertTrue(report["ok"])
        self.assertEqual(organizer.calls, [])
        result = report["results"][0]
        self.assertEqual(result["modelSourceCount"], 0)
        self.assertEqual(
            result["deterministicDecisions"][0]["reasonCode"],
            "transient_runtime_receipt",
        )
        stored = self.sources.get(str(source["source"]["sourceId"]))
        self.assertEqual(stored["disposition"], "not_for_memory")

    def test_fact_free_questions_workflow_noise_duplicates_and_commands_are_filtered(self) -> None:
        texts = [
            "Pi Runtime 的新 Session 个人记忆应该如何注入？",
            "Pi Runtime 的新 Session 个人记忆应该如何注入？",
            "请调用 memory Tool 的 curation_prepare，只生成草案并返回 runId。",
            "合并分支并记录改动",
        ]
        sources = [
            self.sources.checkpoint_user_message(
                session_id=str(self.user_session["id"]),
                pi_entry_id=f"entry:noise:{index}",
                turn_id=f"turn:noise:{index}",
                text=text,
                created_at_ms=100 + index,
            )
            for index, text in enumerate(texts)
        ]
        organizer = _FakeOrganizer()
        curator = OwnerMemoryCurator(
            self.db_path,
            organizer=organizer,
            project="wisdom-weasel-rag-ime",
            initial_settle_ms=0,
        )
        curator.initialize()

        report = curator.run_due(current_ms=1_000)

        self.assertTrue(report["ok"])
        self.assertEqual(organizer.calls, [])
        self.assertEqual(
            sources[2]["status"],
            "skipped_memory_workflow_instruction",
        )
        reasons = [
            self.sources.get(str(sources[index]["source"]["sourceId"]))[
                "dispositionReason"
            ]
            for index in (0, 1, 3)
        ]
        self.assertEqual(
            reasons,
            [
                "duplicate_repeated_input",
                "standalone_question_no_durable_claim",
                "transient_user_instruction",
            ],
        )
        self.assertTrue(
            all(
                self.sources.get(
                    str(sources[index]["source"]["sourceId"])
                )["disposition"]
                == "not_for_memory"
                for index in (0, 1, 3)
            )
        )

    def test_explicitly_transient_non_durable_context_is_filtered_before_model(self) -> None:
        texts = [
            "这轮演示先隐藏侧栏，产品默认布局没有变化。",
            "今天试用了一个配色草稿，但没有决定采用它。",
            "当前只为排查问题打开详细日志，排查结束后不保留这个选择。",
            "本轮只是检查接口返回格式，没有产生新的项目事实。",
        ]
        sources = [
            self.sources.checkpoint_user_message(
                session_id=str(self.user_session["id"]),
                pi_entry_id=f"entry:transient-context:{index}",
                turn_id=f"turn:transient-context:{index}",
                text=text,
                created_at_ms=100 + index,
            )
            for index, text in enumerate(texts)
        ]
        organizer = _FakeOrganizer()
        curator = OwnerMemoryCurator(
            self.db_path,
            organizer=organizer,
            project="wisdom-weasel-rag-ime",
            initial_settle_ms=0,
        )
        curator.initialize()

        report = curator.run_due(current_ms=1_000)

        self.assertTrue(report["ok"])
        self.assertEqual(organizer.calls, [])
        result = report["results"][0]
        self.assertEqual(result["modelSourceCount"], 0)
        self.assertEqual(
            [item["reasonCode"] for item in result["deterministicDecisions"]],
            ["explicit_non_durable_context"] * len(texts),
        )
        self.assertTrue(
            all(
                self.sources.get(str(source["source"]["sourceId"]))["disposition"]
                == "not_for_memory"
                for source in sources
            )
        )

    def test_failed_tool_receipt_is_audit_only(self) -> None:
        source = self.sources.checkpoint_tool_receipt(
            {
                "approvalId": "approval:failed-memory-draft",
                "sessionId": str(self.user_session["id"]),
                # Simulate a legacy/malformed row that passed the old receipt
                # checkpoint despite carrying a failed outcome in its text.
                "state": "applied",
                "receipt": {
                    "mutationApplied": True,
                    "summary": "草案生成被网关校验拒绝，尚未生成 runId。",
                },
            },
            created_at_ms=100,
        )
        organizer = _FakeOrganizer()
        curator = OwnerMemoryCurator(
            self.db_path,
            organizer=organizer,
            project="wisdom-weasel-rag-ime",
            initial_settle_ms=0,
        )
        curator.initialize()

        report = curator.run_due(
            manual=True,
            owner_kind="shared",
            owner_id="wisdom-weasel-rag-ime",
            current_ms=1_000,
        )

        self.assertTrue(report["ok"])
        self.assertEqual(organizer.calls, [])
        stored = self.sources.get(str(source["source"]["sourceId"]))
        self.assertEqual(stored["disposition"], "not_for_memory")
        self.assertEqual(stored["dispositionReason"], "failed_tool_receipt")

    def test_verbatim_long_source_cannot_become_atom_or_book(self) -> None:
        source = self.sources.checkpoint_user_message(
            session_id=str(self.user_session["id"]),
            pi_entry_id="entry:verbatim-long",
            turn_id="turn:verbatim-long",
            text=(
                "输入法记忆整理需要先核对每条证据，再生成事实原子和主题书，"
                "同时不得把这段长输入原封不动复制进长期记忆正文。"
            ),
            created_at_ms=100,
        )
        curator = OwnerMemoryCurator(
            self.db_path,
            organizer=_FakeOrganizer(),
            project="wisdom-weasel-rag-ime",
            initial_settle_ms=0,
        )
        curator.initialize()

        report = curator.run_due(current_ms=1_000)

        self.assertTrue(report["ok"])
        result = report["results"][0]
        self.assertEqual(result["runStatus"], "idle")
        self.assertEqual(result["diffCount"], 0)
        stored = self.sources.get(str(source["source"]["sourceId"]))
        self.assertEqual(stored["disposition"], "needs_review")
        self.assertEqual(
            stored["dispositionReason"],
            "remember_without_durable_atom",
        )

    def test_verbatim_atomic_update_can_reuse_existing_claim(self) -> None:
        old_atom_id = "atom:existing-context-policy"
        claim_key = "desktop:context:source-priority"
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute(
                """
                INSERT INTO memory_atoms(
                    id, kind, text, canonical_text, scope_project,
                    confidence, quality_score, status, created_at_ms,
                    updated_at_ms, owner_kind, owner_id, claim_key,
                    lineage_id, claim_state, valid_from_ms
                ) VALUES (?, 'project_decision', ?, ?, ?, 0.99, 0.99,
                          'active', 10, 10, 'user', 'default', ?, ?,
                          'current', 10)
                """,
                (
                    old_atom_id,
                    "输入原文只取输入法自身记录的 committed text。",
                    "输入原文只取输入法自身记录的 committed text。",
                    "wisdom-weasel-rag-ime",
                    claim_key,
                    f"lineage:{claim_key}",
                ),
            )
            conn.commit()

        update_text = (
            "按回车时优先读取输入框最终全文；AX 不可用或内容更短时回退到输入法提交记录，"
            "密码框和 Secure Input 必须拒绝采集。"
        )
        source = self.sources.checkpoint_user_message(
            session_id=str(self.user_session["id"]),
            pi_entry_id="entry:verbatim-existing-update",
            turn_id="turn:verbatim-existing-update",
            text=update_text,
            created_at_ms=100,
        )

        class _ExistingClaimVerbatimOrganizer:
            provider_name = "fixture"

            def curate_owner_memory(self, *, bundle, **_kwargs):
                item = dict(bundle["inputs"][0])
                return {
                    "provider": "fixture",
                    "model": "fixture-memory",
                    "sourceDecisions": [
                        {
                            "sourceRef": item["sourceRef"],
                            "disposition": "remember",
                            "reasonCode": "stable_policy_update",
                            "confidence": 0.99,
                        }
                    ],
                    "memoryAtoms": [
                        {
                            "canonicalText": update_text,
                            # Deliberately change kind as a model can do; the
                            # existing claim owns its stable category/lineage.
                            "kind": "project_constraint",
                            "claimKey": claim_key,
                            "sourceEventIds": list(item["sourceEventIds"]),
                            "confidence": 0.99,
                            "qualityScore": 0.99,
                            "directCandidateAllowed": False,
                        }
                    ],
                    "topicBooks": [],
                }

        curator = OwnerMemoryCurator(
            self.db_path,
            organizer=_ExistingClaimVerbatimOrganizer(),
            project="wisdom-weasel-rag-ime",
            initial_settle_ms=0,
            auto_apply=True,
        )
        report = curator.run_due(current_ms=1_000)

        self.assertTrue(report["ok"], report)
        self.assertEqual(report["results"][0]["runStatus"], "applied")
        self.assertEqual(
            self.sources.get(str(source["source"]["sourceId"]))["disposition"],
            "consolidated",
        )
        with closing(sqlite3.connect(self.db_path)) as conn:
            rows = conn.execute(
                """
                SELECT kind, canonical_text, status, claim_state, lineage_id
                FROM memory_atoms
                WHERE claim_key = ?
                ORDER BY valid_from_ms
                """,
                (claim_key,),
            ).fetchall()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0][2:4], ("superseded", "superseded"))
        self.assertEqual(rows[1][0], "project_decision")
        self.assertEqual(rows[1][1], update_text)
        self.assertEqual(rows[1][2:4], ("active", "current"))
        self.assertEqual(rows[0][4], rows[1][4])

    def test_high_confidence_recalled_slot_repairs_model_claim_key_split(self) -> None:
        old_claim_key = "agent:capability:catalog-policy"
        model_claim_key = "agent:context:resident-policy"
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.executemany(
                """
                INSERT INTO memory_atoms(
                    id, kind, text, canonical_text, scope_project,
                    confidence, quality_score, status, created_at_ms,
                    updated_at_ms, owner_kind, owner_id, claim_key,
                    lineage_id, claim_state, valid_from_ms
                ) VALUES (?, 'project_decision', ?, ?, ?, 0.99, 0.99,
                          'active', 10, 10, 'user', 'default', ?, ?,
                          'current', 10)
                """,
                (
                    (
                        "atom:catalog-policy:v1",
                        "Agent 启动时加载所有 Skill 正文和全部工具 Schema。",
                        "Agent 启动时加载所有 Skill 正文和全部工具 Schema。",
                        "wisdom-weasel-rag-ime",
                        old_claim_key,
                        f"lineage:{old_claim_key}",
                    ),
                    (
                        "atom:session-memory:v1",
                        "个人记忆只在 Session 首轮自动召回。",
                        "个人记忆只在 Session 首轮自动召回。",
                        "wisdom-weasel-rag-ime",
                        "agent:session:memory-injection",
                        "lineage:agent:session:memory-injection",
                    ),
                ),
            )
            conn.commit()

        update_text = (
            "Agent 常驻上下文只保留 Skill 路由卡和工具 name/does，"
            "需要时再加载正文或 Schema。"
        )
        source = self.sources.checkpoint_user_message(
            session_id=str(self.user_session["id"]),
            pi_entry_id="entry:model-claim-split",
            turn_id="turn:model-claim-split",
            text=update_text,
            created_at_ms=100,
        )

        class _ClaimSplitOrganizer:
            provider_name = "fixture"

            def curate_owner_memory(self, *, bundle, **_kwargs):
                item = dict(bundle["inputs"][0])
                return {
                    "provider": "fixture",
                    "model": "fixture-memory",
                    "sourceDecisions": [
                        {
                            "sourceRef": item["sourceRef"],
                            "disposition": "remember",
                            "reasonCode": "stable_policy_update",
                            "confidence": 0.99,
                        }
                    ],
                    "memoryAtoms": [
                        {
                            "canonicalText": update_text,
                            "kind": "project_constraint",
                            # This reproduces the real model error: it saw the
                            # old Atom but renamed the same semantic slot.
                            "claimKey": model_claim_key,
                            "sourceEventIds": list(item["sourceEventIds"]),
                            "confidence": 0.99,
                            "qualityScore": 0.99,
                            "directCandidateAllowed": False,
                        }
                    ],
                    "topicBooks": [],
                }

        report = OwnerMemoryCurator(
            self.db_path,
            organizer=_ClaimSplitOrganizer(),
            project="wisdom-weasel-rag-ime",
            initial_settle_ms=0,
            auto_apply=True,
        ).run_due(current_ms=1_000)

        result = report["results"][0]
        self.assertTrue(report["ok"], report)
        self.assertEqual(result["runStatus"], "applied")
        self.assertEqual(result["claimKeyReconciliationCount"], 1)
        self.assertEqual(
            result["claimKeyReconciliations"][0]["toClaimKey"],
            old_claim_key,
        )
        self.assertEqual(
            self.sources.get(str(source["source"]["sourceId"]))["disposition"],
            "consolidated",
        )
        with closing(sqlite3.connect(self.db_path)) as conn:
            original_rows = conn.execute(
                """
                SELECT kind, status, claim_state, canonical_text
                FROM memory_atoms
                WHERE claim_key = ?
                ORDER BY valid_from_ms
                """,
                (old_claim_key,),
            ).fetchall()
            split_count = int(
                conn.execute(
                    "SELECT COUNT(*) FROM memory_atoms WHERE claim_key = ?",
                    (model_claim_key,),
                ).fetchone()[0]
            )
            distractor = conn.execute(
                """
                SELECT status, claim_state
                FROM memory_atoms
                WHERE claim_key = 'agent:session:memory-injection'
                """
            ).fetchone()
        self.assertEqual(len(original_rows), 2)
        self.assertEqual(original_rows[0][1:3], ("superseded", "superseded"))
        self.assertEqual(original_rows[1], ("project_decision", "active", "current", update_text))
        self.assertEqual(split_count, 0)
        self.assertEqual(distractor, ("active", "current"))

    def test_mismatched_existing_claim_key_is_reassigned_by_source_semantics(self) -> None:
        storage_claim = "memory:storage:atom-first"
        external_claim = "memory:external-agent:ingestion-policy"
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.executemany(
                """
                INSERT INTO memory_atoms(
                    id, kind, text, canonical_text, scope_project,
                    confidence, quality_score, status, created_at_ms,
                    updated_at_ms, owner_kind, owner_id, claim_key,
                    lineage_id, claim_state, valid_from_ms
                ) VALUES (?, 'project_constraint', ?, ?, ?, 0.99, 0.99,
                          'active', 10, 10, 'user', 'default', ?, ?,
                          'current', 10)
                """,
                (
                    (
                        "atom:storage-policy:v1",
                        "历史输入片段可以直接进入 Agent 长期上下文。",
                        "历史输入片段可以直接进入 Agent 长期上下文。",
                        "wisdom-weasel-rag-ime",
                        storage_claim,
                        f"lineage:{storage_claim}",
                    ),
                    (
                        "atom:external-policy:v1",
                        "Codex 的全部历史会话原文会直接导入长期记忆。",
                        "Codex 的全部历史会话原文会直接导入长期记忆。",
                        "wisdom-weasel-rag-ime",
                        external_claim,
                        f"lineage:{external_claim}",
                    ),
                ),
            )
            conn.commit()

        updates = (
            (
                "长期记忆已经改为 Atom-first；原始片段只作为可追溯证据，"
                "不能直接进入 Agent 上下文。"
            ),
            (
                "不再直接导入 Codex 原始会话，只接收近几个月由 Agent 汇总的"
                "高密度 Session 摘要。"
            ),
        )
        sources = [
            self.sources.checkpoint_user_message(
                session_id=str(self.user_session["id"]),
                pi_entry_id=f"entry:mismatched-existing-claim:{index}",
                turn_id=f"turn:mismatched-existing-claim:{index}",
                text=text,
                created_at_ms=100 + index,
            )
            for index, text in enumerate(updates)
        ]

        class _MismatchedExistingClaimOrganizer:
            provider_name = "fixture"

            def curate_owner_memory(self, *, bundle, **_kwargs):
                inputs = [dict(item) for item in bundle["inputs"]]
                return {
                    "provider": "fixture",
                    "model": "fixture-memory",
                    "sourceDecisions": [
                        {
                            "sourceRef": item["sourceRef"],
                            "disposition": "remember",
                            "reasonCode": "stable_policy_update",
                            "confidence": 0.99,
                        }
                        for item in inputs
                    ],
                    "memoryAtoms": [
                        {
                            "canonicalText": updates[0],
                            "kind": "project_fact",
                            # Reproduce the live model bug: both unrelated
                            # updates were assigned to the external-agent slot.
                            "claimKey": external_claim,
                            "sourceEventIds": list(inputs[0]["sourceEventIds"]),
                            "confidence": 0.99,
                            "qualityScore": 0.99,
                            "directCandidateAllowed": False,
                        },
                        {
                            "canonicalText": updates[1],
                            "kind": "project_constraint",
                            "claimKey": external_claim,
                            "sourceEventIds": list(inputs[1]["sourceEventIds"]),
                            "confidence": 0.99,
                            "qualityScore": 0.99,
                            "directCandidateAllowed": False,
                        },
                    ],
                    "topicBooks": [],
                }

        report = OwnerMemoryCurator(
            self.db_path,
            organizer=_MismatchedExistingClaimOrganizer(),
            project="wisdom-weasel-rag-ime",
            initial_settle_ms=0,
            auto_apply=True,
        ).run_due(current_ms=1_000)

        self.assertTrue(report["ok"], report)
        result = report["results"][0]
        self.assertEqual(result["claimKeyReconciliationCount"], 1)
        self.assertEqual(
            result["claimKeyReconciliations"][0]["toClaimKey"],
            storage_claim,
        )
        self.assertTrue(
            all(
                self.sources.get(str(source["source"]["sourceId"]))["disposition"]
                == "consolidated"
                for source in sources
            )
        )
        with closing(sqlite3.connect(self.db_path)) as conn:
            rows = conn.execute(
                """
                SELECT claim_key, canonical_text, claim_state
                FROM memory_atoms
                ORDER BY claim_key, valid_from_ms
                """
            ).fetchall()
        history = {
            claim_key: [
                (text, state)
                for row_claim, text, state in rows
                if row_claim == claim_key
            ]
            for claim_key in (storage_claim, external_claim)
        }
        self.assertEqual(len(history[storage_claim]), 2)
        self.assertEqual(len(history[external_claim]), 2)
        self.assertEqual(history[storage_claim][-1], (updates[0], "current"))
        self.assertEqual(history[external_claim][-1], (updates[1], "current"))

    def test_unique_existing_claim_key_is_not_overridden_by_related_wording(self) -> None:
        screenshot_claim = "security:desktop:screenshot-policy"
        context_claim = "desktop:context:source-priority"
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.executemany(
                """
                INSERT INTO memory_atoms(
                    id, kind, text, canonical_text, scope_project,
                    confidence, quality_score, status, created_at_ms,
                    updated_at_ms, owner_kind, owner_id, claim_key,
                    lineage_id, claim_state, valid_from_ms
                ) VALUES (?, 'project_decision', ?, ?, ?, 0.99, 0.99,
                          'active', 10, 10, 'user', 'default', ?, ?,
                          'current', 10)
                """,
                (
                    (
                        "atom:screenshot-policy:v1",
                        "桌面 Agent 默认每一步都截图。",
                        "桌面 Agent 默认每一步都截图。",
                        "wisdom-weasel-rag-ime",
                        screenshot_claim,
                        f"lineage:{screenshot_claim}",
                    ),
                    (
                        "atom:context-priority:v1",
                        "按回车时优先读取输入框最终全文；AX 不可用时回退到输入法记录。",
                        "按回车时优先读取输入框最终全文；AX 不可用时回退到输入法记录。",
                        "wisdom-weasel-rag-ime",
                        context_claim,
                        f"lineage:{context_claim}",
                    ),
                ),
            )
            conn.commit()

        update_text = (
            "桌面 Agent 默认不截图，优先读取 Accessibility Tree，"
            "必要时才回退截图。"
        )
        self.sources.checkpoint_user_message(
            session_id=str(self.user_session["id"]),
            pi_entry_id="entry:unique-existing-claim",
            turn_id="turn:unique-existing-claim",
            text=update_text,
            created_at_ms=100,
        )

        class _CorrectExistingClaimOrganizer:
            provider_name = "fixture"

            def curate_owner_memory(self, *, bundle, **_kwargs):
                item = dict(bundle["inputs"][0])
                return {
                    "provider": "fixture",
                    "model": "fixture-memory",
                    "sourceDecisions": [
                        {
                            "sourceRef": item["sourceRef"],
                            "disposition": "remember",
                            "reasonCode": "stable_policy_update",
                            "confidence": 0.99,
                        }
                    ],
                    "memoryAtoms": [
                        {
                            "canonicalText": update_text,
                            "kind": "security_constraint",
                            "claimKey": screenshot_claim,
                            "sourceEventIds": list(item["sourceEventIds"]),
                            "confidence": 0.99,
                            "qualityScore": 0.99,
                            "directCandidateAllowed": False,
                        }
                    ],
                    "topicBooks": [],
                }

        report = OwnerMemoryCurator(
            self.db_path,
            organizer=_CorrectExistingClaimOrganizer(),
            project="wisdom-weasel-rag-ime",
            initial_settle_ms=0,
            auto_apply=True,
        ).run_due(current_ms=1_000)

        self.assertTrue(report["ok"], report)
        self.assertEqual(report["results"][0]["claimKeyReconciliationCount"], 0)
        with closing(sqlite3.connect(self.db_path)) as conn:
            current_rows = dict(
                conn.execute(
                    """
                    SELECT claim_key, canonical_text
                    FROM memory_atoms
                    WHERE status = 'active' AND claim_state = 'current'
                    """
                ).fetchall()
            )
        self.assertEqual(current_rows[screenshot_claim], update_text)
        self.assertIn("输入框", current_rows[context_claim])

    def test_low_compatibility_same_source_fragment_merges_into_claim_anchor(self) -> None:
        role_claim = "memory:role-book:write-policy"
        external_claim = "memory:external-agent:ingestion-policy"
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.executemany(
                """
                INSERT INTO memory_atoms(
                    id, kind, text, canonical_text, scope_project,
                    confidence, quality_score, status, created_at_ms,
                    updated_at_ms, owner_kind, owner_id, claim_key,
                    lineage_id, claim_state, valid_from_ms
                ) VALUES (?, 'project_decision', ?, ?, ?, 0.99, 0.99,
                          'active', 10, 10, 'user', 'default', ?, ?,
                          'current', 10)
                """,
                (
                    (
                        "atom:role-policy:v1",
                        "角色书只在 Agent 完成功能或项目里程碑时调用工具写入。",
                        "角色书只在 Agent 完成功能或项目里程碑时调用工具写入。",
                        "wisdom-weasel-rag-ime",
                        role_claim,
                        f"lineage:{role_claim}",
                    ),
                    (
                        "atom:external-ingestion:v1",
                        "Codex 原始会话不直接导入，只接收高密度 Session 摘要。",
                        "Codex 原始会话不直接导入，只接收高密度 Session 摘要。",
                        "wisdom-weasel-rag-ime",
                        external_claim,
                        f"lineage:{external_claim}",
                    ),
                ),
            )
            conn.commit()

        source_text = (
            "角色书继续采用里程碑触发；空闲整理只处理高密度摘要，"
            "不读取逐轮聊天。"
        )
        source = self.sources.checkpoint_user_message(
            session_id=str(self.user_session["id"]),
            pi_entry_id="entry:same-source-fragment",
            turn_id="turn:same-source-fragment",
            text=source_text,
            created_at_ms=100,
        )

        class _SplitSameSourceOrganizer:
            provider_name = "fixture"

            def curate_owner_memory(self, *, bundle, **_kwargs):
                item = dict(bundle["inputs"][0])
                event_ids = list(item["sourceEventIds"])
                return {
                    "provider": "fixture",
                    "model": "fixture-memory",
                    "sourceDecisions": [
                        {
                            "sourceRef": item["sourceRef"],
                            "disposition": "remember",
                            "reasonCode": "stable_policy_update",
                            "confidence": 0.99,
                        }
                    ],
                    "memoryAtoms": [
                        {
                            "canonicalText": "角色书继续采用里程碑触发写入。",
                            "kind": "project_decision",
                            "claimKey": role_claim,
                            "sourceEventIds": event_ids,
                            "confidence": 0.99,
                            "qualityScore": 0.99,
                            "directCandidateAllowed": False,
                        },
                        {
                            "canonicalText": "空闲整理只处理高密度摘要，不读取逐轮聊天。",
                            "kind": "project_decision",
                            # Live model incorrectly attached this continuation
                            # to an unrelated external-ingestion claim.
                            "claimKey": external_claim,
                            "sourceEventIds": event_ids,
                            "confidence": 0.99,
                            "qualityScore": 0.99,
                            "directCandidateAllowed": False,
                        },
                    ],
                    "topicBooks": [],
                }

        report = OwnerMemoryCurator(
            self.db_path,
            organizer=_SplitSameSourceOrganizer(),
            project="wisdom-weasel-rag-ime",
            initial_settle_ms=0,
            auto_apply=True,
        ).run_due(current_ms=1_000)

        self.assertTrue(report["ok"], report)
        result = report["results"][0]
        self.assertEqual(result["claimKeyReconciliationCount"], 1)
        self.assertEqual(
            result["claimKeyReconciliations"][0]["reason"],
            "same_source_low_compatibility_merged_into_anchor",
        )
        self.assertEqual(
            self.sources.get(str(source["source"]["sourceId"]))["disposition"],
            "consolidated",
        )
        with closing(sqlite3.connect(self.db_path)) as conn:
            current_rows = dict(
                conn.execute(
                    """
                    SELECT claim_key, canonical_text
                    FROM memory_atoms
                    WHERE status = 'active' AND claim_state = 'current'
                    """
                ).fetchall()
            )
            external_depth = int(
                conn.execute(
                    "SELECT COUNT(*) FROM memory_atoms WHERE claim_key = ?",
                    (external_claim,),
                ).fetchone()[0]
            )
        self.assertIn("里程碑", current_rows[role_claim])
        self.assertIn("高密度摘要", current_rows[role_claim])
        self.assertEqual(external_depth, 1)

    def test_concise_existing_claim_update_restores_dropped_source_clause(self) -> None:
        claim_key = "browser:observation:protocol"
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute(
                """
                INSERT INTO memory_atoms(
                    id, kind, text, canonical_text, scope_project,
                    confidence, quality_score, status, created_at_ms,
                    updated_at_ms, owner_kind, owner_id, claim_key,
                    lineage_id, claim_state, valid_from_ms
                ) VALUES (
                    'atom:browser-protocol:v1', 'project_decision', ?, ?, ?,
                    0.99, 0.99, 'active', 10, 10, 'user', 'default', ?, ?,
                    'current', 10
                )
                """,
                (
                    "浏览器插件使用增量 DOM 状态和批量命令。",
                    "浏览器插件使用增量 DOM 状态和批量命令。",
                    "wisdom-weasel-rag-ime",
                    claim_key,
                    f"lineage:{claim_key}",
                ),
            )
            conn.commit()

        source_text = (
            "浏览器观察协议已从增量 DOM 状态改为紧凑快照桥接；"
            "批量执行动作，失败后才回退截图。"
        )
        source = self.sources.checkpoint_user_message(
            session_id=str(self.user_session["id"]),
            pi_entry_id="entry:dropped-source-clause",
            turn_id="turn:dropped-source-clause",
            text=source_text,
            created_at_ms=100,
        )

        class _ClauseDroppingOrganizer:
            provider_name = "fixture"

            def curate_owner_memory(self, *, bundle, **_kwargs):
                item = dict(bundle["inputs"][0])
                return {
                    "provider": "fixture",
                    "model": "fixture-memory",
                    "sourceDecisions": [
                        {
                            "sourceRef": item["sourceRef"],
                            "disposition": "remember",
                            "reasonCode": "stable_protocol_update",
                            "confidence": 0.99,
                        }
                    ],
                    "memoryAtoms": [
                        {
                            "canonicalText": (
                                "浏览器观察协议从增量 DOM 状态改为紧凑快照桥接。"
                            ),
                            "kind": "project_decision",
                            "claimKey": claim_key,
                            "sourceEventIds": list(item["sourceEventIds"]),
                            "confidence": 0.99,
                            "qualityScore": 0.99,
                            "directCandidateAllowed": False,
                        }
                    ],
                    "topicBooks": [],
                }

        report = OwnerMemoryCurator(
            self.db_path,
            organizer=_ClauseDroppingOrganizer(),
            project="wisdom-weasel-rag-ime",
            initial_settle_ms=0,
            auto_apply=True,
        ).run_due(current_ms=1_000)

        self.assertTrue(report["ok"], report)
        result = report["results"][0]
        self.assertEqual(result["memoryAtomRepairCount"], 1)
        self.assertEqual(
            result["memoryAtomRepairs"][0]["reason"],
            "concise_existing_claim_source_clause_restored",
        )
        self.assertEqual(
            self.sources.get(str(source["source"]["sourceId"]))["disposition"],
            "consolidated",
        )
        with closing(sqlite3.connect(self.db_path)) as conn:
            current_text = str(
                conn.execute(
                    """
                    SELECT canonical_text FROM memory_atoms
                    WHERE claim_key = ? AND status = 'active'
                      AND claim_state = 'current'
                    """,
                    (claim_key,),
                ).fetchone()[0]
            )
        self.assertEqual(current_text, source_text)

    def test_related_new_claim_is_not_forced_into_recalled_slot(self) -> None:
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute(
                """
                INSERT INTO memory_atoms(
                    id, kind, text, canonical_text, scope_project,
                    confidence, quality_score, status, created_at_ms,
                    updated_at_ms, owner_kind, owner_id, claim_key,
                    lineage_id, claim_state, valid_from_ms
                ) VALUES (
                    'atom:catalog-policy:v1', 'project_decision',
                    'Agent 启动时加载所有 Skill 正文和全部工具 Schema。',
                    'Agent 启动时加载所有 Skill 正文和全部工具 Schema。',
                    'wisdom-weasel-rag-ime', 0.99, 0.99, 'active', 10, 10,
                    'user', 'default', 'agent:capability:catalog-policy',
                    'lineage:agent:capability:catalog-policy', 'current', 10
                )
                """
            )
            conn.commit()

        new_text = "Agent 当前并发执行上限更新为 4 个子任务。"
        self.sources.checkpoint_user_message(
            session_id=str(self.user_session["id"]),
            pi_entry_id="entry:new-agent-limit",
            turn_id="turn:new-agent-limit",
            text=new_text,
            created_at_ms=100,
        )

        class _DistinctClaimOrganizer:
            provider_name = "fixture"

            def curate_owner_memory(self, *, bundle, **_kwargs):
                item = dict(bundle["inputs"][0])
                return {
                    "provider": "fixture",
                    "model": "fixture-memory",
                    "sourceDecisions": [
                        {
                            "sourceRef": item["sourceRef"],
                            "disposition": "remember",
                            "reasonCode": "stable_runtime_limit",
                            "confidence": 0.99,
                        }
                    ],
                    "memoryAtoms": [
                        {
                            "canonicalText": new_text,
                            "kind": "project_constraint",
                            "claimKey": "agent:runtime:concurrency-limit",
                            "sourceEventIds": list(item["sourceEventIds"]),
                            "confidence": 0.99,
                            "qualityScore": 0.99,
                            "directCandidateAllowed": False,
                        }
                    ],
                    "topicBooks": [],
                }

        report = OwnerMemoryCurator(
            self.db_path,
            organizer=_DistinctClaimOrganizer(),
            project="wisdom-weasel-rag-ime",
            initial_settle_ms=0,
            auto_apply=True,
        ).run_due(current_ms=1_000)

        self.assertTrue(report["ok"], report)
        self.assertEqual(report["results"][0]["claimKeyReconciliationCount"], 0)
        with closing(sqlite3.connect(self.db_path)) as conn:
            current_claims = {
                str(row[0])
                for row in conn.execute(
                    """
                    SELECT claim_key FROM memory_atoms
                    WHERE status = 'active' AND claim_state = 'current'
                    """
                ).fetchall()
            }
        self.assertEqual(
            current_claims,
            {
                "agent:capability:catalog-policy",
                "agent:runtime:concurrency-limit",
            },
        )

    def test_rejecting_every_semantic_write_resolves_review_without_forgetting_evidence(
        self,
    ) -> None:
        source = self.sources.checkpoint_user_message(
            session_id=str(self.user_session["id"]),
            pi_entry_id="entry:reject-synthesis",
            turn_id="turn:reject-synthesis",
            text="保留原始证据，但这次模型生成的整理内容不准确。",
            created_at_ms=100,
        )
        curator = OwnerMemoryCurator(
            self.db_path,
            organizer=_FakeOrganizer(),
            project="wisdom-weasel-rag-ime",
            initial_settle_ms=0,
            daily_interval_ms=60_000,
        )
        curator.initialize()

        generated = curator.run_due(current_ms=1_000)
        run_id = str(generated["results"][0]["runId"])
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            diff_ids = [
                int(row["id"])
                for row in conn.execute(
                    "SELECT id FROM memory_cleanup_diffs WHERE run_id = ? ORDER BY id",
                    (run_id,),
                ).fetchall()
            ]
            for diff_id in diff_ids:
                update_stored_memory_book_diff(
                    conn,
                    run_id=run_id,
                    diff_id=diff_id,
                    selected=False,
                )
            resolved = apply_stored_memory_book_run(conn, run_id=run_id)
            cursor = conn.execute(
                """
                SELECT status
                FROM memory_curation_cursors
                WHERE owner_kind = 'user' AND owner_id = 'default'
                  AND project = 'wisdom-weasel-rag-ime' AND lane = 'daily'
                """
            ).fetchone()

        self.assertEqual(resolved["status"], "empty")
        self.assertEqual(
            resolved["metadata"]["curationOutcome"],
            "review_rejected_all_writes",
        )
        self.assertEqual(cursor["status"], "idle")
        self.assertEqual(
            self.sources.get(str(source["source"]["sourceId"]))["disposition"],
            "remember",
        )
        status = curator.status(current_ms=61_001)["scopes"][0]
        self.assertEqual(status["dueReason"], "no_sources")
        self.assertFalse(status["due"])

    def test_daily_curation_does_not_reactivate_an_archived_owner_book(self) -> None:
        self.sources.checkpoint_user_message(
            session_id=str(self.user_session["id"]),
            pi_entry_id="entry:first-book",
            turn_id="turn:first-book",
            text="桌面上下文默认读取 Accessibility Tree。",
            created_at_ms=100,
        )
        curator = OwnerMemoryCurator(
            self.db_path,
            organizer=_FakeOrganizer(),
            project="wisdom-weasel-rag-ime",
            initial_settle_ms=0,
            daily_interval_ms=60_000,
        )
        curator.initialize()
        first = curator.run_due(current_ms=1_000)
        first_run_id = str(first["results"][0]["runId"])
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            applied = apply_stored_memory_book_run(conn, run_id=first_run_id)
            book_id = str(
                next(
                    diff["payload"]["bookId"]
                    for diff in applied["diffs"]
                    if diff["op"] == "upsert_memory_book"
                )
            )
            set_memory_book_archive_status(
                conn,
                book_id=book_id,
                archived=True,
                reason="user_archive",
                current_ms=2_000,
            )
            conn.commit()

        self.sources.checkpoint_user_message(
            session_id=str(self.user_session["id"]),
            pi_entry_id="entry:after-archive",
            turn_id="turn:after-archive",
            text="每日整理仍可保留新原子，但不能偷偷恢复归档书。",
            created_at_ms=70_000,
        )
        second = curator.run_due(current_ms=70_001)
        second_run_id = str(second["results"][0]["runId"])
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            second_diffs = conn.execute(
                "SELECT op FROM memory_cleanup_diffs WHERE run_id = ?",
                (second_run_id,),
            ).fetchall()
            apply_stored_memory_book_run(conn, run_id=second_run_id)
            book = conn.execute(
                """
                SELECT status, archived_at_ms, archive_reason
                FROM memory_books
                WHERE book_id = ?
                """,
                (book_id,),
            ).fetchone()

        self.assertNotIn("upsert_memory_book", {str(row["op"]) for row in second_diffs})
        self.assertEqual(
            tuple(book),
            ("archived", 2_000, "user_archive"),
        )

    def test_atom_only_model_output_does_not_force_atom_into_unrelated_book(self) -> None:
        first_text = "每天整理一次角色自己的长期记忆。"
        second_text = "浏览器工具默认使用隔离配置目录。"
        self.sources.checkpoint_user_message(
            session_id=str(self.user_session["id"]),
            pi_entry_id="entry:first-organic-book",
            turn_id="turn:first-organic-book",
            text=first_text,
            created_at_ms=100,
        )
        first_curator = OwnerMemoryCurator(
            self.db_path,
            organizer=_FakeOrganizer(),
            project="wisdom-weasel-rag-ime",
            initial_settle_ms=0,
            daily_interval_ms=60_000,
        )
        first_curator.initialize()
        first = first_curator.run_due(current_ms=1_000)
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            apply_stored_memory_book_run(
                conn,
                run_id=str(first["results"][0]["runId"]),
            )

        self.sources.checkpoint_user_message(
            session_id=str(self.user_session["id"]),
            pi_entry_id="entry:second-organic-book",
            turn_id="turn:second-organic-book",
            text=second_text,
            created_at_ms=70_000,
        )
        second_curator = OwnerMemoryCurator(
            self.db_path,
            organizer=_AtomOnlyOrganizer(),
            project="wisdom-weasel-rag-ime",
            initial_settle_ms=0,
            daily_interval_ms=60_000,
        )
        second = second_curator.run_due(current_ms=70_001)
        second_run_id = str(second["results"][0]["runId"])
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            book_drafts = conn.execute(
                """
                SELECT payload_json
                FROM memory_cleanup_diffs
                WHERE run_id = ? AND op = 'upsert_memory_book'
                """,
                (second_run_id,),
            ).fetchall()
            apply_stored_memory_book_run(conn, run_id=second_run_id)
            book = conn.execute(
                "SELECT summary, memory_atom_ids_json FROM memory_books"
            ).fetchone()
            atoms = conn.execute(
                """
                SELECT canonical_text
                FROM memory_atoms
                WHERE status = 'active' AND claim_state = 'current'
                ORDER BY canonical_text
                """
            ).fetchall()

        self.assertEqual(book_drafts, [])
        self.assertNotIn(second_text, str(book["summary"]))
        self.assertEqual(len(json.loads(book["memory_atom_ids_json"])), 1)
        self.assertEqual(
            {str(row["canonical_text"]) for row in atoms},
            {first_text, second_text},
        )

    def test_existing_claim_metadata_drives_automatic_fact_replacement(self) -> None:
        organizer = _ClaimAwareOrganizer()
        curator = OwnerMemoryCurator(
            self.db_path,
            organizer=organizer,
            project="wisdom-weasel-rag-ime",
            initial_settle_ms=0,
            daily_interval_ms=60_000,
            auto_apply=True,
        )
        self.sources.checkpoint_user_message(
            session_id=str(self.user_session["id"]),
            pi_entry_id="entry:cadence-old",
            turn_id="turn:cadence-old",
            text="记忆整理每天运行一次。",
            created_at_ms=100,
        )
        curator.initialize()
        first = curator.run_due(current_ms=1_000)
        self.assertTrue(first["ok"], first)

        self.sources.checkpoint_user_message(
            session_id=str(self.user_session["id"]),
            pi_entry_id="entry:cadence-new",
            turn_id="turn:cadence-new",
            text="记忆整理改成每天运行两次。",
            created_at_ms=70_000,
        )
        second = curator.run_due(current_ms=70_001)

        self.assertTrue(second["ok"], second)
        existing = organizer.calls[1]["existingMemoryAtoms"][0]
        self.assertEqual(
            existing["claimKey"],
            "project:memory.maintenance-cadence",
        )
        self.assertEqual(existing["claimState"], "current")
        self.assertTrue(existing["lineageId"])
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT id, canonical_text, status, claim_state, supersedes_id
                FROM memory_atoms
                WHERE claim_key = 'project:memory.maintenance-cadence'
                ORDER BY valid_from_ms, id
                """
            ).fetchall()
            book = conn.execute(
                """
                SELECT summary, memory_atom_ids_json
                FROM memory_books
                WHERE status = 'active'
                """
            ).fetchone()
        self.assertEqual(len(rows), 2)
        current = next(row for row in rows if row["claim_state"] == "current")
        historical = next(
            row for row in rows if row["claim_state"] == "superseded"
        )
        self.assertIn("每天运行两次", current["canonical_text"])
        self.assertEqual(current["supersedes_id"], historical["id"])
        self.assertEqual(historical["status"], "superseded")
        self.assertIn("每天运行两次", str(book["summary"]))
        self.assertNotIn("每天运行一次", str(book["summary"]))
        self.assertEqual(
            json.loads(str(book["memory_atom_ids_json"])),
            [str(current["id"])],
        )

    def test_each_new_fact_recalls_related_atoms_and_expands_topic_book_graph(self) -> None:
        atoms = (
            ("atom:qwen-primary", "输入法当前使用 Qwen 0.8B", "ime:primary-model"),
            ("atom:hot-path", "100M 模型用于输入法热路径", "ime:hot-path-model"),
            ("atom:fallback", "0.8B 模型作为离线回退", "ime:fallback-model"),
            ("atom:cadence", "记忆整理每天运行一次", "memory:curation-cadence"),
            ("atom:dark-ui", "用户长期偏好深色界面", "ui:theme"),
        )
        with closing(sqlite3.connect(self.db_path)) as conn:
            for atom_id, text, claim_key in atoms:
                conn.execute(
                    """
                    INSERT INTO memory_atoms(
                        id, kind, text, canonical_text, scope_project,
                        confidence, quality_score, status, created_at_ms,
                        updated_at_ms, owner_kind, owner_id, claim_key,
                        lineage_id, claim_state, valid_from_ms
                    ) VALUES (?, 'project_fact', ?, ?, ?, 0.95, 0.95,
                              'active', 10, 10, 'user', 'default', ?, ?,
                              'current', 10)
                    """,
                    (
                        atom_id,
                        text,
                        text,
                        "wisdom-weasel-rag-ime",
                        claim_key,
                        f"lineage:{claim_key}",
                    ),
                )
            conn.execute(
                """
                INSERT INTO memory_books(
                    book_id, book_type, book_key, title, summary,
                    normalized_text, project, tags_json,
                    query_expansions_json, memory_atom_ids_json, status,
                    confidence, quality_score, created_at_ms, updated_at_ms,
                    owner_kind, owner_id
                ) VALUES (
                    'book:ime-deployment', 'topic', 'ime-deployment',
                    '输入法模型部署方案', '输入法在线模型、热路径和离线回退。',
                    '输入法模型部署方案', ?, '["输入法","模型部署"]',
                    '["100M","Qwen","离线回退"]',
                    '["atom:qwen-primary","atom:hot-path","atom:fallback"]',
                    'active', 0.95, 0.95, 10, 10, 'user', 'default'
                )
                """,
                ("wisdom-weasel-rag-ime",),
            )
            conn.execute(
                """
                INSERT INTO memory_books(
                    book_id, book_type, book_key, title, summary,
                    normalized_text, project, memory_atom_ids_json, status,
                    confidence, quality_score, created_at_ms, updated_at_ms,
                    owner_kind, owner_id
                ) VALUES (
                    'book:memory-maintenance', 'topic', 'memory-maintenance',
                    '记忆整理策略', '记忆整理周期和治理策略。',
                    '记忆整理策略', ?, '["atom:cadence"]', 'active',
                    0.95, 0.95, 10, 10, 'user', 'default'
                )
                """,
                ("wisdom-weasel-rag-ime",),
            )
            conn.commit()

        self.sources.checkpoint_user_message(
            session_id=str(self.user_session["id"]),
            pi_entry_id="entry:multi-fact-recall",
            turn_id="turn:multi-fact-recall",
            text="输入法已经切换到 100M 自训练模型。记忆整理改为每天运行两次。",
            created_at_ms=100,
        )
        organizer = _BundleCaptureOrganizer()
        report = OwnerMemoryCurator(
            self.db_path,
            organizer=organizer,
            project="wisdom-weasel-rag-ime",
            initial_settle_ms=0,
            daily_interval_ms=60_000,
        ).run_due(current_ms=1_000)

        self.assertTrue(report["ok"], report)
        bundle = organizer.calls[0]
        recalled_atoms = {
            str(item["atomId"])
            for item in bundle["existingMemoryAtoms"]
            if isinstance(item, dict)
        }
        self.assertTrue(
            {
                "atom:qwen-primary",
                "atom:hot-path",
                "atom:fallback",
                "atom:cadence",
            }.issubset(recalled_atoms)
        )
        self.assertNotIn("atom:dark-ui", recalled_atoms)
        self.assertEqual(
            {
                str(item["bookId"])
                for item in bundle["existingMemoryBooks"]
                if isinstance(item, dict)
            },
            {"book:ime-deployment", "book:memory-maintenance"},
        )
        self.assertEqual(bundle["existingMemoryRecall"]["probeCount"], 2)
        self.assertEqual(
            bundle["existingMemoryRecall"]["strategy"],
            "per_fact_hybrid_union_with_book_graph",
        )

    def test_capture_hint_and_versioned_purpose_reach_owner_organizer(self) -> None:
        source = self.sources.checkpoint_user_message(
            session_id=str(self.user_session["id"]),
            pi_entry_id="entry:capture-purpose",
            turn_id="turn:capture-purpose",
            text="以后测试报告默认只展示聚合数据。",
            created_at_ms=100,
        )["source"]
        self.sources.capture_hint(
            session_id=str(self.user_session["id"]),
            source_id=str(source["sourceId"]),
            kind="preference",
            claim="用户偏好测试报告只展示聚合数据。",
            scope="user",
            basis="explicit_user_statement",
            future_use="这会改变未来报告默认输出。",
            created_at_ms=101,
        )
        organizer = _BundleCaptureOrganizer()

        report = OwnerMemoryCurator(
            self.db_path,
            organizer=organizer,
            project="wisdom-weasel-rag-ime",
            initial_settle_ms=0,
            daily_interval_ms=60_000,
            auto_apply=True,
        ).run_due(current_ms=1_000)

        self.assertTrue(report["ok"], report)
        bundle = organizer.calls[0]
        self.assertEqual(
            bundle["purposeProfile"]["profileRef"],
            "personal_current_state@1",
        )
        self.assertFalse(bundle["inputs"][0]["captureHints"][0]["authoritative"])
        with closing(sqlite3.connect(self.db_path)) as conn:
            metadata = json.loads(
                conn.execute(
                    "SELECT metadata_json FROM memory_cleanup_runs ORDER BY created_at_ms DESC LIMIT 1"
                ).fetchone()[0]
            )
        self.assertEqual(metadata["purpose_profile_id"], "personal_current_state")
        self.assertEqual(metadata["purpose_revision"], 1)
        self.assertEqual(
            metadata["schema_revision"],
            "rag-ime.owner-memory-curation.v1",
        )

    def test_large_mixed_batches_recall_and_replace_every_target_claim(self) -> None:
        total_slots = 500
        target_slots = 120
        members_by_book: dict[int, list[str]] = {}
        with closing(sqlite3.connect(self.db_path)) as conn:
            for slot_index in range(total_slots):
                slot = f"model-slot-{slot_index:03d}"
                atom_id = f"atom:stress:{slot}:v1"
                book_index = slot_index // 10
                members_by_book.setdefault(book_index, []).append(atom_id)
                conn.execute(
                    """
                    INSERT INTO memory_atoms(
                        id, kind, text, canonical_text, scope_project,
                        confidence, quality_score, status, created_at_ms,
                        updated_at_ms, owner_kind, owner_id, claim_key,
                        lineage_id, claim_state, valid_from_ms
                    ) VALUES (?, 'project_fact', ?, ?, ?, 0.99, 0.99,
                              'active', 10, 10, 'user', 'default', ?, ?,
                              'current', 10)
                    """,
                    (
                        atom_id,
                        f"输入法部署槽 {slot} 当前版本为 v1。",
                        f"输入法部署槽 {slot} 当前版本为 v1。",
                        "wisdom-weasel-rag-ime",
                        f"ime:{slot}:current-version",
                        f"lineage:ime:{slot}:current-version",
                    ),
                )
            for book_index, member_ids in members_by_book.items():
                conn.execute(
                    """
                    INSERT INTO memory_books(
                        book_id, book_type, book_key, title, summary,
                        normalized_text, project, tags_json,
                        query_expansions_json, memory_atom_ids_json, status,
                        confidence, quality_score, created_at_ms, updated_at_ms,
                        owner_kind, owner_id
                    ) VALUES (?, 'topic', ?, ?, ?, ?, ?, ?, ?, ?, 'active',
                              0.99, 0.99, 10, 10, 'user', 'default')
                    """,
                    (
                        f"book:stress:{book_index:02d}",
                        f"stress-model-deployment-{book_index:02d}",
                        f"输入法模型部署分组 {book_index:02d}",
                        f"管理第 {book_index:02d} 组输入法部署槽。",
                        f"输入法模型部署分组 {book_index:02d}",
                        "wisdom-weasel-rag-ime",
                        json.dumps(
                            ["输入法", "模型部署", f"group-{book_index:02d}"],
                            ensure_ascii=False,
                        ),
                        json.dumps(
                            [f"model-slot-{book_index * 10:03d}", "当前版本"],
                            ensure_ascii=False,
                        ),
                        json.dumps(member_ids, ensure_ascii=False),
                    ),
                )
            conn.commit()

        organizer = _StressUpdateOrganizer()
        curator = OwnerMemoryCurator(
            self.db_path,
            organizer=organizer,
            project="wisdom-weasel-rag-ime",
            initial_settle_ms=0,
            auto_apply=True,
            max_sources=64,
        )
        v2_order = [(index * 37) % target_slots for index in range(target_slots)]
        v3_order = [(index * 17) % 60 for index in range(60)]
        updates = [
            (slot_index, 2) for slot_index in v2_order
        ] + [
            (slot_index, 3) for slot_index in v3_order
        ]
        batches = [updates[index : index + 6] for index in range(0, len(updates), 6)]
        created_at_ms = 100
        expected_noise_count = 0
        for batch_index, batch in enumerate(batches):
            # These unique protocol lines must be discarded before they can
            # consume the bounded per-fact recall probe budget.
            for noise_index in range(4):
                self.sources.checkpoint_user_message(
                    session_id=str(self.user_session["id"]),
                    pi_entry_id=f"entry:stress-noise:{batch_index}:{noise_index}",
                    turn_id=f"turn:stress-noise:{batch_index}:{noise_index}",
                    text=(
                        f"curation_prepare runId stress-{batch_index:02d}-"
                        f"{noise_index:02d}，等待原生审阅。"
                    ),
                    created_at_ms=created_at_ms,
                )
                created_at_ms += 1
                expected_noise_count += 1
            for slot_index, version in batch:
                slot = f"model-slot-{slot_index:03d}"
                self.sources.checkpoint_user_message(
                    session_id=str(self.user_session["id"]),
                    pi_entry_id=f"entry:stress:{slot}:v{version}",
                    turn_id=f"turn:stress:{slot}:v{version}",
                    text=f"输入法部署槽 {slot} 当前版本更新为 v{version}。",
                    created_at_ms=created_at_ms,
                )
                created_at_ms += 1

        # Drain one large backlog through the real six-Atom transactional
        # boundary. No caller-side batching is allowed to hide cursor bugs.
        deferred_counts: list[int] = []
        for batch_index, batch in enumerate(batches):
            report = curator.run_due(
                manual=True,
                owner_kind="user",
                owner_id="default",
                current_ms=1_000_000 + batch_index,
            )
            self.assertTrue(report["ok"], report)
            self.assertEqual(report["results"][0]["runStatus"], "applied")
            self.assertEqual(report["results"][0]["modelSourceCount"], len(batch))
            deferred_counts.append(
                int(report["results"][0]["deferredModelInputCount"])
            )
            recall = organizer.calls[-1]["existingMemoryRecall"]
            self.assertEqual(recall["probeCount"], len(batch))
            self.assertLessEqual(recall["recalledAtomCount"], 20)

        self.assertEqual(len(updates), 180)
        self.assertEqual(expected_noise_count, 120)
        self.assertEqual(len(organizer.calls), 30)
        self.assertGreater(deferred_counts[0], 0)
        self.assertEqual(deferred_counts[-1], 0)
        self.assertEqual(organizer.missing_claim_keys, [])
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            current_rows = conn.execute(
                """
                SELECT id, claim_key, canonical_text
                FROM memory_atoms
                WHERE claim_state = 'current' AND status = 'active'
                """
            ).fetchall()
            superseded_count = int(
                conn.execute(
                    "SELECT COUNT(*) FROM memory_atoms WHERE claim_state = 'superseded'"
                ).fetchone()[0]
            )
            duplicate_current_count = int(
                conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM (
                        SELECT owner_kind, owner_id, claim_key, COUNT(*) AS n
                        FROM memory_atoms
                        WHERE claim_state = 'current' AND status = 'active'
                        GROUP BY owner_kind, owner_id, claim_key
                        HAVING n != 1
                    )
                    """
                ).fetchone()[0]
            )
            noise_count = int(
                conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM agent_memory_sources
                    WHERE disposition = 'not_for_memory'
                      AND disposition_reason = 'memory_workflow_instruction'
                    """
                ).fetchone()[0]
            )
            supersession_count = int(
                conn.execute("SELECT COUNT(*) FROM memory_supersessions").fetchone()[0]
            )
            invalid_interval_count = int(
                conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM memory_atoms AS newer
                    JOIN memory_atoms AS older ON older.id = newer.supersedes_id
                    WHERE older.claim_state != 'superseded'
                       OR older.valid_to_ms IS NULL
                       OR older.valid_to_ms != newer.valid_from_ms
                       OR older.claim_key != newer.claim_key
                    """
                ).fetchone()[0]
            )
            source_dispositions = {
                str(row["disposition"]): int(row["n"])
                for row in conn.execute(
                    """
                    SELECT disposition, COUNT(*) AS n
                    FROM agent_memory_sources
                    GROUP BY disposition
                    """
                ).fetchall()
            }
            book_members = [
                member_id
                for row in conn.execute(
                    """
                    SELECT memory_atom_ids_json
                    FROM memory_books
                    WHERE book_type = 'topic' AND status = 'active'
                    """
                ).fetchall()
                for member_id in json.loads(row["memory_atom_ids_json"] or "[]")
            ]

        current_by_claim = {
            str(row["claim_key"]): str(row["canonical_text"])
            for row in current_rows
        }
        self.assertEqual(len(current_by_claim), total_slots)
        self.assertEqual(superseded_count, len(updates))
        self.assertEqual(supersession_count, len(updates))
        self.assertEqual(invalid_interval_count, 0)
        self.assertEqual(duplicate_current_count, 0)
        self.assertEqual(noise_count, 0)
        self.assertEqual(
            source_dispositions,
            {"consolidated": len(updates)},
        )
        self.assertEqual(len(book_members), total_slots)
        self.assertEqual(
            set(book_members),
            {str(row["id"]) for row in current_rows},
        )
        for slot_index in range(total_slots):
            slot = f"model-slot-{slot_index:03d}"
            expected_version = 3 if slot_index < 60 else 2 if slot_index < 120 else 1
            self.assertEqual(
                current_by_claim[f"ime:{slot}:current-version"],
                f"输入法部署槽 {slot} 当前版本为 v{expected_version}。",
            )

    def test_compound_fact_source_reduces_batch_before_atom_capacity_gate(self) -> None:
        texts = [
            "主模型已更新为100M；延迟目标已更新为50ms；整理频率已更新为每天两次。",
            "角色书已更新为里程碑触发。",
            "会话记忆已更新为首轮注入。",
            "Room预算已更新为最近8条。",
            "浏览器观察已更新为紧凑快照。",
        ]
        sources = [
            self.sources.checkpoint_user_message(
                session_id=str(self.user_session["id"]),
                pi_entry_id=f"entry:compound-capacity:{index}",
                turn_id=f"turn:compound-capacity:{index}",
                text=text,
                created_at_ms=100 + index,
            )
            for index, text in enumerate(texts)
        ]

        class _CompoundFactOrganizer:
            provider_name = "fixture"

            def __init__(self) -> None:
                self.calls: list[list[str]] = []

            def curate_owner_memory(self, *, bundle, **_kwargs):
                inputs = [dict(item) for item in bundle["inputs"]]
                self.calls.append([str(item["text"]) for item in inputs])
                atoms = []
                for item in inputs:
                    clauses = [
                        part.strip().rstrip("。")
                        for part in re.split(r"[；;]", str(item["text"]))
                        if part.strip().rstrip("。")
                    ]
                    for clause_index, clause in enumerate(clauses):
                        event_id = int(item["sourceEventIds"][0])
                        atoms.append(
                            {
                                "canonicalText": clause,
                                "kind": "project_decision",
                                "claimKey": f"eval:{event_id}:{clause_index}",
                                "sourceEventIds": list(item["sourceEventIds"]),
                                "confidence": 0.99,
                                "qualityScore": 0.99,
                                "directCandidateAllowed": False,
                            }
                        )
                return {
                    "provider": "fixture",
                    "model": "fixture-memory",
                    "sourceDecisions": [
                        {
                            "sourceRef": item["sourceRef"],
                            "disposition": "remember",
                            "reasonCode": "stable_update",
                            "confidence": 0.99,
                        }
                        for item in inputs
                    ],
                    "memoryAtoms": atoms,
                    "topicBooks": [],
                }

        organizer = _CompoundFactOrganizer()
        curator = OwnerMemoryCurator(
            self.db_path,
            organizer=organizer,
            project="wisdom-weasel-rag-ime",
            initial_settle_ms=0,
            auto_apply=True,
        )
        first = curator.run_due(
            manual=True,
            owner_kind="user",
            owner_id="default",
            current_ms=1_000,
        )
        second = curator.run_due(
            manual=True,
            owner_kind="user",
            owner_id="default",
            current_ms=2_000,
        )

        self.assertTrue(first["ok"], first)
        self.assertTrue(second["ok"], second)
        first_result = first["results"][0]
        second_result = second["results"][0]
        self.assertEqual(first_result["modelSourceCount"], 4)
        self.assertEqual(first_result["modelFactProbeCount"], 6)
        self.assertEqual(first_result["deferredModelInputCount"], 1)
        self.assertEqual(second_result["modelSourceCount"], 1)
        self.assertEqual(second_result["modelFactProbeCount"], 1)
        self.assertEqual(second_result["deferredModelInputCount"], 0)
        self.assertEqual([len(call) for call in organizer.calls], [4, 1])
        self.assertTrue(
            all(
                self.sources.get(str(source["source"]["sourceId"]))["disposition"]
                == "consolidated"
                for source in sources
            )
        )
        with closing(sqlite3.connect(self.db_path)) as conn:
            atom_count = int(
                conn.execute("SELECT COUNT(*) FROM memory_atoms").fetchone()[0]
            )
        self.assertEqual(atom_count, 7)

    def test_dense_source_over_atom_capacity_fails_closed_without_partial_write(self) -> None:
        source = self.sources.checkpoint_user_message(
            session_id=str(self.user_session["id"]),
            pi_entry_id="entry:dense-memory-source",
            turn_id="turn:dense-memory-source",
            text="。".join(f"需要长期保留的事实 {index}" for index in range(7)),
            created_at_ms=100,
        )
        report = OwnerMemoryCurator(
            self.db_path,
            organizer=_OverCapacityOrganizer(),
            project="wisdom-weasel-rag-ime",
            initial_settle_ms=0,
            auto_apply=True,
        ).run_due(
            manual=True,
            owner_kind="user",
            owner_id="default",
            current_ms=1_000,
        )

        self.assertTrue(report["ok"], report)
        decision = report["results"][0]["modelDecisions"][0]
        self.assertEqual(decision["disposition"], "needs_review")
        self.assertEqual(decision["reasonCode"], "atom_batch_capacity_exceeded")
        with closing(sqlite3.connect(self.db_path)) as conn:
            atom_count = int(
                conn.execute("SELECT COUNT(*) FROM memory_atoms").fetchone()[0]
            )
            stored_source = conn.execute(
                """
                SELECT disposition, disposition_reason
                FROM agent_memory_sources
                WHERE source_id = ?
                """,
                (str(source["source"]["sourceId"]),),
            ).fetchone()
        self.assertEqual(atom_count, 0)
        self.assertEqual(stored_source[0], "needs_review")
        self.assertEqual(stored_source[1], "atom_batch_capacity_exceeded")

    def test_explicit_forget_auto_retracts_and_rollback_restores_atom(self) -> None:
        seed = self.sources.checkpoint_user_message(
            session_id=str(self.user_session["id"]),
            pi_entry_id="entry:dark-preference",
            turn_id="turn:dark-preference",
            text="我长期偏好深色界面。",
            created_at_ms=100,
        )
        seed_curator = OwnerMemoryCurator(
            self.db_path,
            organizer=_FakeOrganizer(),
            project="wisdom-weasel-rag-ime",
            initial_settle_ms=0,
            daily_interval_ms=60_000,
            auto_apply=True,
        )
        seed_curator.initialize()
        seeded = seed_curator.run_due(current_ms=1_000)
        self.assertTrue(seeded["ok"], seeded)
        self.assertEqual(
            self.sources.get(str(seed["source"]["sourceId"]))["disposition"],
            "consolidated",
        )

        self.sources.checkpoint_user_message(
            session_id=str(self.user_session["id"]),
            pi_entry_id="entry:forget-dark",
            turn_id="turn:forget-dark",
            text="忘记我长期偏好深色界面这条记忆。",
            created_at_ms=70_000,
        )
        curator = OwnerMemoryCurator(
            self.db_path,
            organizer=_ExplicitForgetOrganizer(),
            project="wisdom-weasel-rag-ime",
            initial_settle_ms=0,
            daily_interval_ms=60_000,
            auto_apply=True,
        )
        forgotten = curator.run_due(current_ms=70_001)

        self.assertTrue(forgotten["ok"], forgotten)
        result = forgotten["results"][0]
        self.assertEqual(result["runStatus"], "applied")
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            atom = conn.execute(
                "SELECT id, status, claim_state FROM memory_atoms"
            ).fetchone()
            tombstone = conn.execute(
                """
                SELECT id, active
                FROM memory_tombstones
                WHERE target_type = 'memory_id' AND target_value = ?
                ORDER BY id DESC LIMIT 1
                """,
                (str(atom["id"]),),
            ).fetchone()
            book = conn.execute(
                "SELECT status, memory_atom_ids_json FROM memory_books"
            ).fetchone()
            self.assertEqual((atom["status"], atom["claim_state"]), ("tombstoned", "retracted"))
            self.assertEqual(int(tombstone["active"]), 1)
            self.assertEqual(book["status"], "archived")
            self.assertEqual(json.loads(book["memory_atom_ids_json"]), [])
            conn.execute("PRAGMA foreign_keys = ON")
            rollback_memory_book_run(conn, run_id=str(result["runId"]))
            restored = conn.execute(
                "SELECT status, claim_state FROM memory_atoms WHERE id = ?",
                (str(atom["id"]),),
            ).fetchone()
            inactive = conn.execute(
                "SELECT active FROM memory_tombstones WHERE id = ?",
                (int(tombstone["id"]),),
            ).fetchone()
        self.assertEqual(tuple(restored), ("active", "current"))
        self.assertEqual(int(inactive["active"]), 0)

    def test_failure_keeps_cursor_and_enters_backoff(self) -> None:
        self.sources.checkpoint_user_message(
            session_id=str(self.user_session["id"]),
            pi_entry_id="entry:failure",
            turn_id="turn:failure",
            text="这条重要决定不能因为模型失败而丢失。",
            created_at_ms=100,
        )
        curator = OwnerMemoryCurator(
            self.db_path,
            organizer=_FakeOrganizer(fail=True),
            project="wisdom-weasel-rag-ime",
            initial_settle_ms=0,
        )
        curator.initialize()

        report = curator.run_due(current_ms=1_000)

        self.assertFalse(report["ok"])
        scope = report["status"]["scopes"][0]
        self.assertEqual(scope["status"], "backoff")
        self.assertEqual(scope["pendingSourceCount"], 1)
        self.assertEqual(scope["lastSourceCursor"]["createdAtMs"], 0)
        self.assertGreater(scope["nextDueAtMs"], 1_000)


if __name__ == "__main__":
    unittest.main()
