from __future__ import annotations

import unittest

from rag_ime.activity_timeline_curation import (
    ACTIVITY_ORGANIZATION_INPUT_VERSION,
    ACTIVITY_ORGANIZATION_OUTPUT_VERSION,
    ACTIVITY_ORGANIZATION_CONTRACT_REPAIR_PROMPT_VERSION,
    ACTIVITY_ORGANIZATION_REPAIR_PROMPT_VERSION,
    ACTIVITY_ORGANIZATION_VERDICT_VERSION,
    ActivityOrganizationContractError,
    activity_organization_verdict_schema,
    activity_organization_output_schema,
    build_activity_organization_packet,
    build_activity_organization_contract_repair_prompt,
    build_activity_organization_prompt,
    build_activity_organization_repair_prompt,
    build_activity_organization_verifier_prompt,
    validate_activity_organization_output,
    validate_activity_organization_verdict,
)


class ActivityTimelineCurationTests(unittest.TestCase):
    def _row(
        self,
        event_id: int,
        text: str,
        *,
        context: str = "",
        app: str = "Ghostty",
        source: str = "squirrel_input_segment",
        created_at_ms: int | None = None,
        lane: str = "app:ghostty",
    ) -> dict[str, object]:
        return {
            "id": event_id,
            "created_at_ms": created_at_ms or 1_754_035_200_000 + event_id * 60_000,
            "source": source,
            "committed_text": text,
            "recent_context": context,
            "preedit": "",
            "app": app,
            "project": "wisdom-weasel-rag-ime",
            "context_group_id": lane,
            "context_group_level": "app",
        }

    def _packet(self):
        return build_activity_organization_packet(
            [
                self._row(
                    11,
                    "完成哪些方面",
                    context="当前这个岛用户还是看不出每个 Room 完成哪些方面",
                ),
                self._row(
                    12,
                    "修复时间线",
                    context="一段与当前输入完全无关的浏览器输出",
                    app="RagImeControl",
                    lane="session:timeline",
                ),
                self._row(
                    13,
                    "继续验证整理效果",
                    context="继续验证整理效果",
                    app="Zed",
                    lane="session:timeline",
                ),
            ],
            timeline_id="activity-timeline:test",
            project="wisdom-weasel-rag-ime",
            timeline_date="2026-08-01",
            timezone_name="Asia/Shanghai",
        )

    def test_packet_preserves_current_text_and_attaches_only_aligned_context(self) -> None:
        packet = self._packet()

        self.assertEqual(packet.payload["v"], ACTIVITY_ORGANIZATION_INPUT_VERSION)
        self.assertEqual(packet.event_refs, ("e1", "e2", "e3"))
        self.assertEqual(packet.ref_to_event_id, {"e1": 11, "e2": 12, "e3": 13})
        self.assertEqual(packet.records[0].current_text, "完成哪些方面")
        self.assertEqual(
            packet.records[0].reference_context,
            "当前这个岛用户还是看不出每个 Room 完成哪些方面",
        )
        self.assertEqual(packet.records[0].context_status, "aligned")
        self.assertEqual(packet.records[1].current_text, "修复时间线")
        self.assertEqual(packet.records[1].reference_context, "")
        self.assertEqual(packet.records[1].context_status, "unaligned")
        self.assertEqual(packet.records[2].reference_context, "")
        self.assertEqual(packet.records[2].context_status, "same")
        self.assertNotEqual(packet.records[0].current_text, packet.records[0].reference_context)

        columns = packet.payload["columns"]
        self.assertIn("currentText", columns)
        self.assertIn("referenceContext", columns)
        self.assertNotIn("goal", packet.json_text().casefold())
        self.assertNotIn("book", packet.json_text().casefold())
        self.assertNotIn("roomid", packet.json_text().casefold())

    def test_packet_is_deterministic_and_uses_content_independent_membership_hash(self) -> None:
        packet = self._packet()
        changed_text = build_activity_organization_packet(
            [
                self._row(11, "完全不同的文本"),
                self._row(12, "另一个文本", app="RagImeControl"),
                self._row(13, "第三个文本", app="Zed"),
            ],
            timeline_id="activity-timeline:test",
            project="wisdom-weasel-rag-ime",
            timeline_date="2026-08-01",
            timezone_name="Asia/Shanghai",
        )

        self.assertEqual(packet.membership_sha256, changed_text.membership_sha256)
        self.assertNotEqual(packet.private_payload_sha256, changed_text.private_payload_sha256)
        self.assertEqual(packet.json_text(), self._packet().json_text())

    def test_output_contract_accepts_natural_activity_count_and_abstention(self) -> None:
        packet = self._packet()
        result = validate_activity_organization_output(
            {
                "schemaVersion": ACTIVITY_ORGANIZATION_OUTPUT_VERSION,
                "activities": [
                    {
                        "title": "时间线整理验证",
                        "summary": "修复并验证活动时间线的整理效果。",
                        "eventRefs": ["e2", "e3"],
                        "confidence": 0.94,
                        "boundaryBasis": "两条输入都直接讨论时间线整理与验证。",
                    }
                ],
                "unclassified": [
                    {
                        "eventRef": "e1",
                        "reason": "只有局部指代，无法仅凭当前表达确认所属活动。",
                    }
                ],
            },
            packet=packet,
        )

        self.assertEqual(len(result.activities), 1)
        self.assertEqual(result.activities[0].event_refs, ("e2", "e3"))
        self.assertTrue(result.activities[0].activity_id.startswith("activity:"))
        self.assertEqual(result.unclassified[0].event_ref, "e1")

    def test_output_contract_rejects_missing_duplicate_and_unknown_refs(self) -> None:
        packet = self._packet()
        cases = {
            "missing": (["e1"], ["e2"]),
            "duplicate": (["e1", "e2"], ["e2", "e3"]),
            "unknown": (["e1", "e2"], ["e3", "e9"]),
        }
        for label, (activity_refs, unclassified_refs) in cases.items():
            with self.subTest(label=label):
                with self.assertRaises(ActivityOrganizationContractError):
                    validate_activity_organization_output(
                        {
                            "schemaVersion": ACTIVITY_ORGANIZATION_OUTPUT_VERSION,
                            "activities": [
                                {
                                    "title": "示例活动",
                                    "summary": "只用于验证引用守恒。",
                                    "eventRefs": activity_refs,
                                    "confidence": 0.8,
                                    "boundaryBasis": "示例边界。",
                                }
                            ],
                            "unclassified": [
                                {"eventRef": ref, "reason": "信息不足。"}
                                for ref in unclassified_refs
                            ],
                        },
                        packet=packet,
                    )

    def test_output_contract_rejects_goal_book_room_and_extra_fields(self) -> None:
        packet = self._packet()
        valid = {
            "schemaVersion": ACTIVITY_ORGANIZATION_OUTPUT_VERSION,
            "activities": [
                {
                    "title": "示例活动",
                    "summary": "覆盖三条测试输入。",
                    "eventRefs": ["e1", "e2", "e3"],
                    "confidence": 0.8,
                    "boundaryBasis": "示例边界。",
                }
            ],
            "unclassified": [],
        }
        for forbidden in ("goal", "book", "roomId"):
            with self.subTest(forbidden=forbidden):
                value = {**valid, forbidden: "not allowed"}
                with self.assertRaises(ActivityOrganizationContractError):
                    validate_activity_organization_output(value, packet=packet)

    def test_schema_and_prompt_encode_abstention_and_context_boundaries(self) -> None:
        packet = self._packet()
        schema = activity_organization_output_schema()
        prompt = build_activity_organization_prompt(packet)

        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(schema["properties"]["schemaVersion"]["const"], ACTIVITY_ORGANIZATION_OUTPUT_VERSION)
        self.assertNotIn("goal", str(schema).casefold())
        self.assertNotIn("book", str(schema).casefold())
        self.assertIn("currentText", prompt)
        self.assertIn("referenceContext", prompt)
        self.assertIn("unclassified", prompt)
        self.assertIn("exactly once", prompt)
        self.assertIn("one concrete work object", prompt)
        self.assertIn("one resumable work thread", prompt)
        self.assertIn("shared project or broad domain is not a semantic bond", prompt)
        self.assertIn("proposal", prompt)
        self.assertIn("one object and one intent", prompt)
        self.assertIn("final reference ledger", prompt)
        self.assertIn("remaining ref", prompt)
        self.assertIn(packet.private_payload_sha256, prompt)
        self.assertIn(
            f'"const":"{ACTIVITY_ORGANIZATION_OUTPUT_VERSION}"',
            prompt,
        )
        self.assertIn('"required":["schemaVersion","activities","unclassified"]', prompt)

        def all_keys(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    yield key
                    yield from all_keys(child)
            elif isinstance(value, list):
                for child in value:
                    yield from all_keys(child)

        self.assertNotIn("uniqueItems", set(all_keys(schema)))
        self.assertNotIn(
            "uniqueItems",
            set(all_keys(activity_organization_verdict_schema())),
        )

    def test_independent_verifier_contract_scores_semantics_and_checks_refs(self) -> None:
        packet = self._packet()
        organizer_output = {
            "schemaVersion": ACTIVITY_ORGANIZATION_OUTPUT_VERSION,
            "activities": [
                {
                    "title": "时间线整理验证",
                    "summary": "修复并验证活动时间线的整理效果。",
                    "eventRefs": ["e2", "e3"],
                    "confidence": 0.94,
                    "boundaryBasis": "两条输入都直接讨论时间线整理与验证。",
                }
            ],
            "unclassified": [
                {"eventRef": "e1", "reason": "信息不足。"}
            ],
        }
        verdict = validate_activity_organization_verdict(
            {
                "schemaVersion": ACTIVITY_ORGANIZATION_VERDICT_VERSION,
                "verdict": "iterate",
                "scores": {
                    "semanticCoherence": 4,
                    "boundaryPrecision": 3,
                    "titleSummaryFidelity": 4,
                    "contextDiscipline": 5,
                    "crossAppContinuity": 4,
                    "interleavingSeparation": 3,
                    "abstentionQuality": 4,
                    "unsupportedInference": 5,
                },
                "issues": [
                    {
                        "severity": "major",
                        "category": "boundaryPrecision",
                        "eventRefs": ["e1", "e2"],
                        "finding": "边界仍需复核。",
                        "recommendation": "检查相邻事件的语义转换。",
                    }
                ],
                "strengths": ["参考上下文没有覆盖当前输入。"],
            },
            packet=packet,
        )

        self.assertEqual(verdict.verdict, "iterate")
        self.assertEqual(verdict.scores["contextDiscipline"], 5)
        self.assertEqual(verdict.issues[0].event_refs, ("e1", "e2"))

        schema = activity_organization_verdict_schema()
        prompt = build_activity_organization_verifier_prompt(
            packet,
            organizer_output=organizer_output,
        )
        self.assertFalse(schema["additionalProperties"])
        self.assertIn("independent", prompt.casefold())
        self.assertIn("interleavingSeparation", prompt)
        self.assertIn(
            f'"const":"{ACTIVITY_ORGANIZATION_VERDICT_VERSION}"',
            prompt,
        )

        invalid = {
            "schemaVersion": ACTIVITY_ORGANIZATION_VERDICT_VERSION,
            "verdict": "pass",
            "scores": {key: 5 for key in verdict.scores},
            "issues": [
                {
                    "severity": "minor",
                    "category": "semanticCoherence",
                    "eventRefs": ["e99"],
                    "finding": "未知引用。",
                    "recommendation": "拒绝。",
                }
            ],
            "strengths": [],
        }
        with self.assertRaises(ActivityOrganizationContractError):
            validate_activity_organization_verdict(invalid, packet=packet)

    def test_repair_prompt_uses_isolated_review_without_weakening_coverage(self) -> None:
        packet = self._packet()
        organizer_output = {
            "schemaVersion": ACTIVITY_ORGANIZATION_OUTPUT_VERSION,
            "activities": [
                {
                    "title": "时间线整理验证",
                    "summary": "修复并验证活动时间线的整理效果。",
                    "eventRefs": ["e1", "e2", "e3"],
                    "confidence": 0.9,
                    "boundaryBasis": "三条输入属于一次整理验证。",
                }
            ],
            "unclassified": [],
        }
        verdict_output = {
            "schemaVersion": ACTIVITY_ORGANIZATION_VERDICT_VERSION,
            "verdict": "iterate",
            "scores": {
                "semanticCoherence": 4,
                "boundaryPrecision": 3,
                "titleSummaryFidelity": 3,
                "contextDiscipline": 5,
                "crossAppContinuity": 4,
                "interleavingSeparation": 4,
                "abstentionQuality": 4,
                "unsupportedInference": 3,
            },
            "issues": [
                {
                    "severity": "minor",
                    "category": "titleSummaryFidelity",
                    "eventRefs": ["e1"],
                    "finding": "标题把讨论写成了完成。",
                    "recommendation": "保留原始语气。",
                }
            ],
            "strengths": ["引用覆盖完整。"],
        }

        prompt = build_activity_organization_repair_prompt(
            packet,
            organizer_output=organizer_output,
            verdict_output=verdict_output,
        )

        self.assertIn(ACTIVITY_ORGANIZATION_REPAIR_PROMPT_VERSION, prompt)
        self.assertIn("bounded repair", prompt.casefold())
        self.assertIn("preserve", prompt.casefold())
        self.assertIn("final reference ledger", prompt)
        self.assertIn(packet.private_payload_sha256, prompt)
        self.assertIn(
            f'"const":"{ACTIVITY_ORGANIZATION_OUTPUT_VERSION}"',
            prompt,
        )

    def test_contract_repair_prompt_is_bounded_and_carries_exact_ref_ledger(self) -> None:
        packet = self._packet()
        rejected_output = {
            "schemaVersion": ACTIVITY_ORGANIZATION_OUTPUT_VERSION,
            "activities": [
                {
                    "title": "时间线整理验证",
                    "summary": "修复并验证活动时间线的整理效果。",
                    "eventRefs": ["e1", "e3"],
                    "confidence": 0.9,
                    "boundaryBasis": "两条输入被模型归为同一活动。",
                }
            ],
            "unclassified": [],
        }

        prompt = build_activity_organization_contract_repair_prompt(
            packet,
            organizer_output=rejected_output,
            contract_error=(
                "Activity event coverage mismatch: duplicates=[], "
                "missing=['e2'], unknown=[]"
            ),
        )

        self.assertIn(ACTIVITY_ORGANIZATION_CONTRACT_REPAIR_PROMPT_VERSION, prompt)
        self.assertIn("contract repair only", prompt.casefold())
        self.assertIn('"requiredRefLedger":["e1","e2","e3"]', prompt)
        self.assertIn("missing=['e2']", prompt)
        self.assertIn("Preserve", prompt)
        self.assertIn("one bounded", prompt)
        self.assertIn(packet.private_payload_sha256, prompt)
        self.assertIn(
            f'"const":"{ACTIVITY_ORGANIZATION_OUTPUT_VERSION}"',
            prompt,
        )


if __name__ == "__main__":
    unittest.main()
