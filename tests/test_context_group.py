from __future__ import annotations

import unittest

from rag_ime.context_group import (
    GroupShortBuffer,
    context_group_compatibility,
    resolve_context_group,
)


class ContextGroupTest(unittest.TestCase):
    def test_document_url_is_stable_and_does_not_depend_on_text(self) -> None:
        first = resolve_context_group(
            app_bundle_id="com.apple.TextEdit",
            document_url="file:///tmp/interview.txt",
            project="wisdom-weasel-rag-ime",
        )
        second = resolve_context_group(
            app_bundle_id="com.apple.TextEdit",
            document_url="file:///tmp/interview.txt",
            project="wisdom-weasel-rag-ime",
        )
        self.assertEqual(first.context_group_id, second.context_group_id)
        self.assertEqual(first.context_group_level, "document")
        self.assertIn(first.project_group_id, first.parent_group_ids)

    def test_window_title_then_app_fallback(self) -> None:
        window = resolve_context_group(app_bundle_id="com.apple.TextEdit", window_title="Untitled 2")
        app = resolve_context_group(app_bundle_id="com.apple.TextEdit")
        self.assertEqual(window.context_group_level, "document")
        self.assertEqual(window.confidence, 0.85)
        self.assertEqual(app.context_group_level, "app")

    def test_group_compatibility_uses_soft_long_term_and_hard_short_term_isolation(self) -> None:
        current = resolve_context_group(
            app_bundle_id="com.apple.TextEdit",
            document_url="file:///tmp/a.txt",
            project="ime",
        )
        self.assertEqual(context_group_compatibility(current, candidate_group_id=current.context_group_id), 1.0)
        self.assertEqual(context_group_compatibility(current, candidate_project="ime"), 0.75)
        self.assertEqual(context_group_compatibility(current, candidate_app="com.apple.TextEdit"), 0.5)
        self.assertEqual(context_group_compatibility(current, candidate_group_id="global"), 0.2)
        self.assertEqual(context_group_compatibility(current, candidate_app="com.other.App"), 0.05)
        self.assertEqual(
            context_group_compatibility(current, candidate_group_id="doc:other", short_term=True),
            0.0,
        )

    def test_short_buffer_is_group_scoped_bounded_and_expires(self) -> None:
        current = 1_000
        buffer = GroupShortBuffer(max_events_per_group=2, ttl_ms=100, clock_ms=lambda: current)
        buffer.append("doc:a", "第一条", event_id=1)
        buffer.append("doc:a", "第二条", event_id=2)
        buffer.append("doc:a", "第三条", event_id=3)
        buffer.append("doc:b", "其他文档", event_id=4)
        self.assertEqual([item.text for item in buffer.recent("doc:a")], ["第二条", "第三条"])
        self.assertNotIn("其他文档", [item.text for item in buffer.recent("doc:a")])
        self.assertTrue(buffer.mark("doc:a", event_id=3, deleted=True))
        self.assertEqual([item.text for item in buffer.recent("doc:a")], ["第二条"])
        current = 1_101
        self.assertEqual(buffer.recent("doc:a"), ())


if __name__ == "__main__":
    unittest.main()
