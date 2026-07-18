from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from rag_ime.agent_memory_sources import AgentMemorySourceStore
from rag_ime.agent_sessions import AgentSessionStore
from rag_ime.historical_memory_curation import curate_historical_memory_database
from rag_ime.owner_memory_curation import OwnerMemoryCurator


PROJECT = "wisdom-weasel-rag-ime"


class _HistoricalOrganizer:
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
        del instruction
        inputs = [dict(item) for item in bundle.get("inputs") or []]
        self.calls.append(
            {
                "date": dict(bundle.get("activityContext") or {}).get("date"),
                "ownerKind": owner_kind,
                "ownerId": owner_id,
                "texts": [str(item.get("text") or "") for item in inputs],
            }
        )
        atoms = []
        for index, item in enumerate(inputs, start=1):
            atoms.append(
                {
                    "atomId": f"atom:history:{len(self.calls)}:{index}",
                    "claimKey": f"history:{len(self.calls)}:{index}",
                    "canonicalText": str(item["text"]),
                    "summary": "历史迁移中的稳定个人记忆",
                    "kind": "project_decision",
                    "sourceEventIds": list(item["sourceEventIds"]),
                    "confidence": 0.92,
                    "qualityScore": 0.9,
                    "directCandidateAllowed": False,
                }
            )
        return {
            "schemaVersion": "rag-ime.owner-memory-curation.v1",
            "provider": "fixture",
            "model": "fixture-history",
            "sourceDecisions": [
                {
                    "sourceRef": item["sourceRef"],
                    "disposition": "remember",
                    "reasonCode": "durable_historical_memory",
                    "confidence": 0.95,
                }
                for item in inputs
            ],
            "topicBooks": [
                {
                    "title": "个人长期记忆",
                    "summary": "保留经过证据审阅的历史项目决定。",
                    "sourceEventIds": [
                        int(event_id)
                        for item in inputs
                        for event_id in item["sourceEventIds"]
                    ],
                    "memoryAtomIds": [str(item["atomId"]) for item in atoms],
                    "confidence": 0.9,
                    "qualityScore": 0.88,
                }
            ],
            "memoryAtoms": atoms,
            "warnings": [],
        }


class HistoricalMemoryCurationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-history-curation-")
        self.db_path = Path(self.tmp.name) / "rag-ime.sqlite"
        self.sessions = AgentSessionStore(self.db_path)
        self.sessions.initialize()
        self.session = self.sessions.create(title="history", created_at_ms=1)
        self.sources = AgentMemorySourceStore(self.db_path, project=PROJECT)
        self.sources.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_full_history_resolves_old_draft_and_organizes_all_dates(self) -> None:
        transient = self.sources.checkpoint_user_message(
            session_id=str(self.session["id"]),
            pi_entry_id="entry:transient",
            turn_id="turn:transient",
            text="AI 辅助已暂停，普通 Rime 拼音仍可使用。",
            created_at_ms=self._ms(2026, 7, 14, 10),
        )
        old_curator = OwnerMemoryCurator(
            self.db_path,
            organizer=_HistoricalOrganizer(),
            project=PROJECT,
            initial_settle_ms=0,
        )
        old_curator.initialize()
        old = old_curator.run_due(
            manual=True,
            owner_kind="user",
            owner_id="default",
            current_ms=self._ms(2026, 7, 14, 11),
        )
        self.assertEqual(old["results"][0]["runStatus"], "waiting_review")

        self.sources.checkpoint_user_message(
            session_id=str(self.session["id"]),
            pi_entry_id="entry:model",
            turn_id="turn:model",
            text="输入法已经切换到 100M 自训练模型，旧 0.8B 模型不再作为热路径。",
            created_at_ms=self._ms(2026, 7, 15, 10),
        )
        self.sources.checkpoint_user_message(
            session_id=str(self.session["id"]),
            pi_entry_id="entry:memory",
            turn_id="turn:memory",
            text="个人记忆在 Session 开始时召回一次，后续由 Agent 按需使用工具检索。",
            created_at_ms=self._ms(2026, 7, 16, 10),
        )
        organizer = _HistoricalOrganizer()

        report = curate_historical_memory_database(
            self.db_path,
            organizer=organizer,
            project=PROJECT,
            timezone_name="Asia/Shanghai",
            max_batches=20,
        )

        self.assertTrue(report["ok"])
        self.assertEqual(report["ownerCuration"]["pendingSourceCount"], 0)
        self.assertEqual(report["after"]["draftOwnerRuns"], 0)
        self.assertEqual(report["timelines"]["dateCount"], 3)
        self.assertEqual(
            {item["status"] for item in report["timelines"]["items"]},
            {"approved"},
        )
        self.assertTrue(report["reviewedRuns"][0]["transientSourcesRejected"])
        self.assertEqual(
            self.sources.get(str(transient["source"]["sourceId"]))["disposition"],
            "not_for_memory",
        )
        self.assertEqual(len(organizer.calls), 2)
        with sqlite3.connect(self.db_path) as conn:
            current_atoms = [
                str(row[0])
                for row in conn.execute(
                    "SELECT canonical_text FROM memory_atoms WHERE status IN ('active', 'approved')"
                ).fetchall()
            ]
            approved_timelines = int(
                conn.execute(
                    "SELECT COUNT(*) FROM daily_activity_timelines WHERE status = 'approved'"
                ).fetchone()[0]
            )
        self.assertFalse(any("已暂停" in text for text in current_atoms))
        self.assertTrue(any("100M" in text for text in current_atoms))
        self.assertTrue(any("Session" in text for text in current_atoms))
        self.assertEqual(approved_timelines, 3)

    @staticmethod
    def _ms(year: int, month: int, day: int, hour: int) -> int:
        return int(
            datetime(
                year,
                month,
                day,
                hour,
                tzinfo=ZoneInfo("Asia/Shanghai"),
            ).timestamp()
            * 1000
        )


if __name__ == "__main__":
    unittest.main()
