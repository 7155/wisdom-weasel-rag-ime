from __future__ import annotations

import unittest

from rag_ime.model_lane_scheduler import LatestWinsModelScheduler, ModelRequestToken


class ModelLaneSchedulerTests(unittest.TestCase):
    def test_new_generation_cancels_older_model_request(self) -> None:
        scheduler = LatestWinsModelScheduler()
        old = _token("old", 1)
        new = _token("new", 2)

        scheduler.begin(old)
        scheduler.begin(new)

        self.assertTrue(scheduler.is_cancelled("old"))
        self.assertFalse(scheduler.is_latest(old))
        self.assertTrue(scheduler.is_latest(new))

    def test_different_panel_sessions_do_not_cancel_each_other(self) -> None:
        scheduler = LatestWinsModelScheduler()
        one = _token("one", 1, panel="panel-a")
        two = _token("two", 2, panel="panel-b")

        scheduler.begin(one)
        scheduler.begin(two)

        self.assertFalse(scheduler.is_cancelled("one"))
        self.assertTrue(scheduler.is_latest(one))
        self.assertTrue(scheduler.is_latest(two))


def _token(request_id: str, generation: int, *, panel: str = "panel") -> ModelRequestToken:
    return ModelRequestToken(
        request_id=request_id,
        session_id="session",
        panel_session_id=panel,
        input_generation=generation,
        apply_anchor="ctx",
        query_anchor="query",
        profile_id="hot",
        created_at_ms=generation,
    )


if __name__ == "__main__":
    unittest.main()
