from __future__ import annotations

import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from rag_ime.temporal_query import parse_temporal_query


TZ = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 7, 13, 16, 30, tzinfo=TZ)  # Monday.


class TemporalQueryTests(unittest.TestCase):
    def test_calendar_relative_ranges(self) -> None:
        cases = {
            "今天做了什么": ("2026-07-13", "2026-07-14"),
            "昨天做了什么": ("2026-07-12", "2026-07-13"),
            "前天做了什么": ("2026-07-11", "2026-07-12"),
            "上周做了什么": ("2026-07-06", "2026-07-13"),
            "本周做了什么": ("2026-07-13", "2026-07-20"),
            "上个月做了什么": ("2026-06-01", "2026-07-01"),
        }
        for query, (start, end) in cases.items():
            with self.subTest(query=query):
                parsed = parse_temporal_query(query, now=NOW)
                self.assertEqual(len(parsed.ranges), 1)
                self.assertEqual(datetime.fromtimestamp(parsed.ranges[0].start_ms / 1000, TZ).date().isoformat(), start)
                self.assertEqual(datetime.fromtimestamp(parsed.ranges[0].end_ms / 1000, TZ).date().isoformat(), end)

    def test_recent_and_dynamic_ranges(self) -> None:
        recent = parse_temporal_query("最近干了什么", now=NOW)
        three_days = parse_temporal_query("最近三天改了什么", now=NOW)
        two_weeks_ago = parse_temporal_query("两周前做过什么", now=NOW)
        last_friday = parse_temporal_query("上周五处理了什么", now=NOW)

        self.assertEqual(recent.ranges[0].label, "2026-07-09 至 2026-07-13")
        self.assertEqual(three_days.ranges[0].label, "2026-07-11 至 2026-07-13")
        self.assertEqual(two_weeks_ago.ranges[0].label, "2026-06-29 至 2026-07-05")
        self.assertEqual(last_friday.ranges[0].label, "2026-07-10")
        self.assertEqual(three_days.cleaned_query, "改了什么")

    def test_multiple_time_expressions_are_deduplicated(self) -> None:
        parsed = parse_temporal_query("比较昨天和上周五的输入法工作", now=NOW)

        self.assertEqual([item.label for item in parsed.ranges], ["2026-07-10", "2026-07-12"])
        self.assertEqual(parsed.cleaned_query, "比较 和 的输入法工作")


if __name__ == "__main__":
    unittest.main()
