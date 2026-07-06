from __future__ import annotations

import unittest

from rag_ime.side_lane_scheduler import LaneRequestToken, LatestWinsLaneScheduler


class LatestWinsLaneSchedulerTests(unittest.TestCase):
    def test_new_generation_supersedes_older_token_for_same_panel(self) -> None:
        scheduler = LatestWinsLaneScheduler()
        first = scheduler.begin(_token(input_generation=1, apply_anchor="apply-a"))
        second = scheduler.begin(_token(input_generation=2, apply_anchor="apply-b"))

        self.assertFalse(scheduler.is_latest(first))
        self.assertTrue(scheduler.is_latest(second))
        self.assertNotEqual(first.serial, second.serial)

    def test_follow_up_with_same_context_reuses_active_token(self) -> None:
        scheduler = LatestWinsLaneScheduler()
        first = scheduler.begin(_token(input_generation=1, apply_anchor="apply-a"))
        follow_up = scheduler.begin(_token(input_generation=2, apply_anchor="apply-a"))

        self.assertEqual(first, follow_up)
        self.assertTrue(scheduler.is_latest(first))
        self.assertTrue(scheduler.is_latest(follow_up))

    def test_other_panel_does_not_supersede_current_panel(self) -> None:
        scheduler = LatestWinsLaneScheduler()
        first = scheduler.begin(_token(panel_session_id="panel-a", input_generation=1))
        second = scheduler.begin(_token(panel_session_id="panel-b", input_generation=2))

        self.assertTrue(scheduler.is_latest(first))
        self.assertTrue(scheduler.is_latest(second))

    def test_cancel_older_removes_latest_for_panel(self) -> None:
        scheduler = LatestWinsLaneScheduler()
        token = scheduler.begin(_token())

        self.assertEqual(scheduler.cancel_older("session", "panel"), 1)
        self.assertFalse(scheduler.is_latest(token))


def _token(
    *,
    panel_session_id: str = "panel",
    input_generation: int = 1,
    apply_anchor: str = "apply",
) -> LaneRequestToken:
    return LaneRequestToken(
        session_id="session",
        panel_session_id=panel_session_id,
        frontend_revision=1,
        input_generation=input_generation,
        apply_anchor=apply_anchor,
        query_anchor="query",
        created_at_ms=1000,
    )


if __name__ == "__main__":
    unittest.main()
