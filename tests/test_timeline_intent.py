from __future__ import annotations

import unittest
from datetime import datetime

from rag_ime.timeline_intent import classify_timeline_intent, timeline_date_bounds


class TimelineIntentTests(unittest.TestCase):
    def test_explicit_relative_and_date_intents_are_observable(self) -> None:
        recent = classify_timeline_intent("最近几天我在做什么？")
        yesterday = classify_timeline_intent("昨天 RAG IME 做到哪里了？")
        exact = classify_timeline_intent("2026-07-18 改了什么？")
        explicit = classify_timeline_intent("打开工作记录")

        self.assertEqual(
            recent.as_dict(),
            {
                "requested": True,
                "reason": "relative_time",
                "matched": ["最近几天"],
                "range": "recent_days",
            },
        )
        self.assertEqual(yesterday.reason, "relative_time")
        self.assertEqual(yesterday.range, "yesterday")
        self.assertEqual(exact.reason, "exact_date")
        self.assertEqual(exact.range, "2026-07-18")
        self.assertEqual(explicit.reason, "explicit_timeline")

    def test_vague_history_and_continuation_do_not_unlock_timeline(self) -> None:
        for query in (
            "输入法本地模型怎么配置？",
            "之前那个模型怎么优化？",
            "继续做 RAG",
            "接着处理这个问题",
        ):
            with self.subTest(query=query):
                self.assertFalse(classify_timeline_intent(query).requested)

    def test_timeline_architecture_question_does_not_unlock_activity_records(self) -> None:
        for query in (
            "时间线为什么不放主题书？",
            "记忆系统的时间线索引如何实现？",
        ):
            with self.subTest(query=query):
                self.assertEqual(
                    classify_timeline_intent(query).as_dict(),
                    {
                        "requested": False,
                        "reason": "none",
                        "matched": [],
                        "range": "",
                    },
                )

        today = classify_timeline_intent("为什么今天的时间线没有记录？")
        self.assertTrue(today.requested)
        self.assertEqual(today.reason, "relative_time")
        self.assertEqual(today.range, "today")

    def test_stale_relative_word_in_raw_history_does_not_unlock_timeline(self) -> None:
        intent = classify_timeline_intent(
            "输入法本地模型怎么配置？",
            raw_input="昨天我修了别的模块",
        )
        explicit = classify_timeline_intent(
            "帮我看一下",
            raw_input="请按活动记录定位昨天的问题",
        )

        self.assertFalse(intent.requested)
        self.assertTrue(explicit.requested)
        self.assertEqual(explicit.reason, "explicit_timeline")

    def test_settings_can_fail_closed(self) -> None:
        intent = classify_timeline_intent("昨天做了什么", enabled=False)

        self.assertEqual(intent.reason, "disabled")
        self.assertFalse(intent.requested)

    def test_relative_ranges_resolve_to_inclusive_local_dates(self) -> None:
        now = datetime.fromisoformat("2026-07-19T11:00:00+08:00")

        self.assertEqual(
            timeline_date_bounds(
                classify_timeline_intent("昨天做了什么"),
                now=now,
            ),
            ("2026-07-18", "2026-07-18"),
        )
        self.assertEqual(
            timeline_date_bounds(
                classify_timeline_intent("过去3天改了什么"),
                now=now,
            ),
            ("2026-07-17", "2026-07-19"),
        )
        self.assertEqual(
            timeline_date_bounds(
                classify_timeline_intent("2026-07-11 改了什么"),
                now=now,
            ),
            ("2026-07-11", "2026-07-11"),
        )
        self.assertIsNone(
            timeline_date_bounds(
                classify_timeline_intent("打开工作记录"),
                now=now,
            )
        )


if __name__ == "__main__":
    unittest.main()
