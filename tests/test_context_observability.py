from __future__ import annotations

import json
import unittest

from rag_ime.contracts.context_observability import build_context_injection_trace, text_fingerprint


class ContextObservabilityTests(unittest.TestCase):
    def test_context_injection_trace_proves_injection_without_raw_text(self) -> None:
        context = "这是真实光标上下文，不应默认出现在诊断响应里"
        selected = "真实选区"
        evidence = ({"sourceType": "memory", "sourceLane": "timeline_daily_book", "summary": "私密证据"},)
        packet = {"packetId": "pkt-private", "notebook": {"items": [{"summary": "私密证据"}]}}
        messages = (
            {"role": "system", "content": "system"},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "currentContext": context,
                        "selectedText": selected,
                        "contextPacket": packet,
                        "evidenceHints": ["私密证据"],
                    },
                    ensure_ascii=False,
                ),
            },
        )

        trace = build_context_injection_trace(
            current_context=context,
            selected_text=selected,
            evidence_pack=evidence,
            context_packet=packet,
            messages=messages,
        )
        blob = json.dumps(trace, ensure_ascii=False)

        self.assertTrue(trace["injection"]["success"])
        self.assertTrue(trace["injection"]["contextPacketIncluded"])
        self.assertEqual(trace["capturedContext"]["currentContext"]["chars"], len(context))
        self.assertTrue(str(trace["capturedContext"]["currentContext"]["hash"]).startswith("sha256:"))
        self.assertEqual(trace["evidence"]["sourceLaneCounts"], {"timeline_daily_book": 1})
        self.assertNotIn(context, blob)
        self.assertNotIn(selected, blob)
        self.assertNotIn("私密证据", blob)

    def test_text_fingerprint_can_include_text_only_when_explicit(self) -> None:
        self.assertNotIn("text", text_fingerprint("内容"))
        self.assertEqual(text_fingerprint("内容", include_text=True)["text"], "内容")


if __name__ == "__main__":
    unittest.main()
