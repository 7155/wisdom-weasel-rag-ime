from __future__ import annotations

import unittest

from rag_ime.context_frame import build_current_input_frame, context_frame_trace_payload
from rag_ime.models import FrontendTransaction, RimeCandidate, RimeContextSnapshot


class ContextFrameTests(unittest.TestCase):
    def test_build_frame_from_rime_snapshot(self) -> None:
        snapshot = RimeContextSnapshot(
            session_id="s1",
            request_seq=7,
            raw_input="chuxian",
            preedit="chuxian",
            committed_context="前面已经输入过一些内容",
            candidates=(RimeCandidate(text="出现", label="1"),),
            frontend_transaction=FrontendTransaction(
                frontend_revision=3,
                selection_epoch=4,
                input_generation=5,
                panel_session_id="panel-a",
                input_source_id="im.rag-ime.inputmethod.RagIme.Hans",
            ),
        )

        frame = build_current_input_frame(
            snapshot,
            ui_mode="composition_rime",
            semantic_query="出现",
            query_basis="rimeCandidates",
        )

        self.assertEqual(frame.schema_version, "rag-ime.context-frame.v1")
        self.assertEqual(frame.session.input_generation, 5)
        self.assertEqual(frame.ui.ui_mode, "composition_rime")
        self.assertEqual(frame.composition.rime_candidates[0].text, "出现")
        self.assertEqual(frame.foreground_text.source, "rime_composition")
        self.assertEqual(frame.foreground_text.confidence, 1.0)
        self.assertTrue(frame.anchors.apply_anchor.startswith("sha256:"))

    def test_frame_trace_redacts_raw_text_by_default(self) -> None:
        snapshot = RimeContextSnapshot(
            session_id="s1",
            request_seq=8,
            commit_text_preview="秘密项目名称",
            committed_context="这里包含秘密项目名称和更长的上下文",
            frontend_transaction=FrontendTransaction(input_generation=9, panel_session_id="panel-a"),
        )
        frame = build_current_input_frame(snapshot, ui_mode="post_commit_prediction")

        payload = context_frame_trace_payload(frame)
        serialized = repr(payload)

        self.assertNotIn("秘密项目名称", serialized)
        self.assertEqual(payload["foregroundText"]["source"], "ime_commit_ledger")
        self.assertIn("committedContextHash", payload["committed"])
        self.assertGreater(payload["committed"]["committedTailChars"], 0)

    def test_foreground_text_payload_records_provenance_without_requiring_clipboard(self) -> None:
        snapshot = RimeContextSnapshot(session_id="s1", request_seq=9)
        frame = build_current_input_frame(
            snapshot,
            ui_mode="active_rag_assist",
            foreground_text_payload={
                "available": True,
                "source": "accessibility",
                "confidence": 0.7,
                "selectedTextPreview": "用户主动选中的文本",
                "canReplaceSelection": True,
                "captureEpoch": 12,
            },
        )

        payload = context_frame_trace_payload(frame)
        self.assertEqual(frame.foreground_text.source, "accessibility")
        self.assertTrue(frame.foreground_text.selected_text_hash.startswith("sha256:"))
        self.assertNotIn("用户主动选中的文本", repr(payload))
        self.assertEqual(payload["foregroundText"]["selectedTextChars"], 9)


if __name__ == "__main__":
    unittest.main()

