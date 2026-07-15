from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from rag_ime.daily_planner import (
    detect_task_completion,
    local_date_string,
    planning_assistant_reply,
    planning_context,
    planning_dashboard,
    save_daily_plan,
    save_goal,
    save_task,
    undo_task_event,
)
from rag_ime.db import apply_database_migrations
from rag_ime.local_sqlite_core import LocalSqliteCoreClient
from rag_ime.models import InputEvent
from rag_ime.text_utils import now_ms


class DailyPlannerTests(unittest.TestCase):
    def test_daily_plan_tasks_goals_and_assistant_form_one_dashboard(self) -> None:
        with self._connection() as conn, conn:
            save_daily_plan(
                conn,
                {
                    "date": "2026-07-13",
                    "intention": "完成输入法上下文优化",
                    "notes": "先修短输入组装，再跑前台验收。",
                },
            )
            goal = save_goal(
                conn,
                {
                    "title": "把输入法做成稳定的个人工作台",
                    "detail": "持续优化 Rime、RAG、记忆与语音输入。",
                    "priority": 3,
                },
            )["goal"]
            save_task(
                conn,
                {
                    "date": "2026-07-13",
                    "title": "完成上下文测试",
                    "priority": 2,
                    "goalId": goal["id"],
                },
            )

            context = planning_context(conn, plan_date="2026-07-13")
            reply = planning_assistant_reply(
                conn,
                message="今天还有什么任务？",
                plan_date="2026-07-13",
            )
            dashboard = planning_dashboard(conn, plan_date="2026-07-13")

        self.assertEqual(context["intention"], "完成输入法上下文优化")
        self.assertEqual(context["openTasks"][0]["title"], "完成上下文测试")
        self.assertEqual(context["longTermGoals"][0]["id"], goal["id"])
        self.assertIn("今天还剩 1 项", reply["reply"])
        self.assertEqual([item["role"] for item in dashboard["conversation"]], ["user", "assistant"])

    def test_unambiguous_completion_is_automatic_and_undoable(self) -> None:
        with self._connection() as conn, conn:
            task = save_task(
                conn,
                {"date": "2026-07-13", "title": "书法界面优化", "priority": 2},
            )["task"]

            completion = detect_task_completion(
                conn,
                text="书法界面优化已经完成了",
                source_event_id=41,
                current_date="2026-07-13",
            )
            dashboard = planning_dashboard(conn, plan_date="2026-07-13")

            self.assertEqual(completion["status"], "completed")
            self.assertEqual(completion["task"]["id"], task["id"])
            self.assertEqual(dashboard["recentDetectedCompletion"]["eventId"], completion["taskEventId"])
            self.assertIn("书法界面优化", dashboard["recentDetectedCompletion"]["message"])

            undone = undo_task_event(conn, event_id=completion["taskEventId"])
            refreshed = planning_dashboard(conn, plan_date="2026-07-13")

        self.assertEqual(undone["task"]["status"], "todo")
        self.assertIsNone(refreshed["recentDetectedCompletion"])

    def test_ambiguous_completion_waits_for_user_confirmation(self) -> None:
        with self._connection() as conn, conn:
            first = save_task(
                conn,
                {"date": "2026-07-13", "title": "优化输入法界面"},
            )["task"]
            second = save_task(
                conn,
                {"date": "2026-07-13", "title": "优化输入法模型"},
            )["task"]

            result = detect_task_completion(
                conn,
                text="优化输入法已经完成了",
                source_event_id=52,
                current_date="2026-07-13",
            )
            dashboard = planning_dashboard(conn, plan_date="2026-07-13")

        self.assertEqual(result["status"], "confirmation_required")
        self.assertEqual(set(result["candidateTaskIds"]), {first["id"], second["id"]})
        self.assertEqual(len(dashboard["pendingCompletionSuggestions"]), 1)
        self.assertTrue(all(item["status"] == "todo" for item in dashboard["tasks"]))

    def test_final_voice_event_closes_task_through_real_input_ledger(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-planning-ledger-") as temporary:
            core = LocalSqliteCoreClient(Path(temporary) / "rag-ime.sqlite")
            core.initialize()
            today = local_date_string()
            with core._connect() as conn:
                save_task(
                    conn,
                    {"date": today, "title": "完成语音输入测试"},
                )
            core.record_event(
                InputEvent(
                    event_id=None,
                    created_at_ms=now_ms(),
                    source="voice_final",
                    committed_text="完成语音输入测试已经完成了",
                    privacy_disposition="allowed",
                )
            )
            with core._connect() as conn:
                dashboard = planning_dashboard(conn, plan_date=today)

        self.assertEqual(dashboard["tasks"][0]["status"], "done")
        self.assertIsNotNone(dashboard["recentDetectedCompletion"])

    @staticmethod
    def _connection():
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        apply_database_migrations(conn)
        return closing(conn)


if __name__ == "__main__":
    unittest.main()
