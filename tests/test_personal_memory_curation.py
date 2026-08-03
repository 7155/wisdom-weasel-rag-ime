from __future__ import annotations

import json
import unittest

from rag_ime.personal_memory_curation import (
    PERSONAL_CURATION_POLICY_REVISION,
    PersonalMemoryCurationError,
    build_personal_memory_packet,
    curate_personal_memory_v2,
)


class FakeExecutor:
    provider = "openai-codex"
    model_id = "gpt-5.6-luna"

    def __init__(self, outputs: list[dict[str, object]]) -> None:
        self.outputs = list(outputs)
        self.calls: list[dict[str, object]] = []

    def complete(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(dict(kwargs))
        payload = self.outputs.pop(0)
        ordinal = len(self.calls)
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": json.dumps(payload, ensure_ascii=False),
                    }
                }
            ],
            "requestId": f"request:{ordinal}",
            "turnId": f"turn:{ordinal}",
            "receipt": {
                "sessionId": f"session:{ordinal}",
                "inputSha256": str(ordinal) * 64,
                "inputChars": 100 + ordinal,
            },
        }


def _input(
    ordinal: int,
    text: str,
) -> dict[str, object]:
    return {
        "sourceRef": f"S{ordinal}",
        "sourceId": f"source:{ordinal}",
        "sourceIds": [f"source:{ordinal}"],
        "evidenceId": f"evidence:{ordinal}",
        "evidenceIds": [f"evidence:{ordinal}"],
        "sourceEventIds": [ordinal],
        "sourceKind": "user_final",
        "sourceChannel": "input_method",
        "boundaryKind": "host_return",
        "sourceOccurredAtMs": 1_000 + ordinal,
        "createdAtMs": 1_000 + ordinal,
        "app": "com.apple.TextEdit",
        "text": text,
    }


class PersonalMemoryCurationTests(unittest.TestCase):
    def test_three_pass_protocol_is_exact_compact_and_book_free(self) -> None:
        executor = FakeExecutor(
            [
                {
                    "v": 2,
                    "d": [
                        ["E1", "p", 0.97, "durable_preference"],
                        ["E2", "n", 0.99, "project_task"],
                    ],
                },
                {
                    "v": 2,
                    "o": [
                        [
                            "c",
                            "d",
                            "user:response-style",
                            "用户偏好简洁、自然的回答。",
                            ["E1"],
                            0.96,
                            ["沟通风格"],
                        ]
                    ],
                },
                {
                    "v": 2,
                    "ok": 1,
                    "r": [["E1", 1], ["E2", 1]],
                    "o": [[0, 1]],
                    "errors": [],
                },
            ]
        )
        bundle = {
            "inputs": [
                _input(1, "我长期偏好简洁、自然的回答。"),
                _input(2, "把当前项目的导航组件改完。"),
            ],
            "existingMemoryAtoms": [],
            "contextOnly": [
                {"occurredAtMs": 900, "channel": "input_method", "app": "TextEdit", "text": "上一句"}
            ],
        }

        result = curate_personal_memory_v2(executor, bundle=bundle)

        self.assertEqual([call["phase"] for call in executor.calls], [
            "evidence-adjudication",
            "atom-adjudication",
            "independent-verifier",
        ])
        self.assertFalse(executor.calls[0]["isolated"])
        self.assertTrue(executor.calls[2]["isolated"])
        self.assertIn(
            "a correct n (not-memory) decision still receives 1",
            executor.calls[2]["messages"][0]["content"],
        )
        self.assertEqual(result["topicBooks"], [])
        self.assertEqual(result["memoryAtoms"][0]["evidenceIds"], ["evidence:1"])
        self.assertEqual(result["memoryAtoms"][0]["knowledgeDomain"], "personal_memory")
        self.assertEqual(
            [decision["disposition"] for decision in result["sourceDecisions"]],
            ["remember", "not_for_memory"],
        )
        first_user_payload = json.loads(executor.calls[0]["messages"][1]["content"])
        self.assertIsInstance(first_user_payload, dict)
        self.assertNotIn("messages", first_user_payload)
        self.assertEqual(first_user_payload["p"]["x"][0][-1], "上一句")

    def test_prompt_contract_preserves_source_authority_and_claim_granularity(self) -> None:
        executor = FakeExecutor(
            [
                {"v": 2, "d": [["E1", "p", 0.97, "durable_preference"]]},
                {
                    "v": 2,
                    "o": [[
                        "c",
                        "d",
                        "user:communication:answer-style",
                        "用户在技术讨论中偏好简洁、自然且保留必要依据的回答。",
                        ["E1"],
                        0.97,
                        ["沟通风格"],
                    ]],
                },
                {
                    "v": 2,
                    "ok": 1,
                    "r": [["E1", 1]],
                    "o": [[0, 1]],
                    "errors": [],
                },
            ]
        )
        bundle = {
            "inputs": [
                _input(1, "我在技术讨论中长期偏好简洁、自然且保留必要依据的回答。")
            ],
            "existingMemoryAtoms": [],
            "contextOnly": [
                {
                    "occurredAtMs": 900,
                    "channel": "input_method",
                    "app": "com.mitchellh.ghostty",
                    "text": "把当前项目的提示词改好。",
                }
            ],
        }

        result = curate_personal_memory_v2(executor, bundle=bundle)

        evidence_prompt = str(executor.calls[0]["messages"][0]["content"])
        atom_prompt = str(executor.calls[1]["messages"][0]["content"])
        verifier_prompt = str(executor.calls[2]["messages"][0]["content"])
        self.assertEqual(PERSONAL_CURATION_POLICY_REVISION, "personal-curator-v8")
        self.assertIn(PERSONAL_CURATION_POLICY_REVISION, evidence_prompt)
        self.assertIn(
            "Upstream has already reconstructed cumulative IME snapshots",
            evidence_prompt,
        )
        self.assertIn("Do not denoise, merge, repair", evidence_prompt)
        self.assertIn("E-row text is the only claim-bearing source", evidence_prompt)
        self.assertIn("Context x and metadata may disambiguate", evidence_prompt)
        self.assertIn("cannot add missing", evidence_prompt)
        self.assertIn(
            "Judge that clause rather than the row's dominant project topic",
            evidence_prompt,
        )
        self.assertIn(
            "A mixed task row can therefore contain a personal-memory candidate",
            evidence_prompt,
        )
        self.assertIn(
            "Do not invent a 'current UI', 'current project', or 'current memory structure'",
            evidence_prompt,
        )
        self.assertIn(
            "rule for how the assistant should communicate",
            evidence_prompt,
        )
        self.assertIn(
            "an information-organization preference",
            evidence_prompt,
        )
        self.assertIn(
            "Mentioning a UI, memory structure, or project does not by itself make the preference one-off",
            evidence_prompt,
        )
        self.assertIn(
            "When implementation is unclear, ask me and use natural wording",
            evidence_prompt,
        )
        self.assertIn(
            "Use Luna for this batch; change this UI",
            evidence_prompt,
        )
        self.assertIn("Use n only after this clause scan", evidence_prompt)
        self.assertIn("one current user claim", atom_prompt)
        self.assertIn(
            "Preserve qualifiers, negation, modality, conditions, and scope",
            atom_prompt,
        )
        self.assertIn("Do not merge related but independent claims", atom_prompt)
        self.assertIn(
            "mixes one personal claim with project content",
            atom_prompt,
        )
        self.assertIn("false positive and false negative", verifier_prompt)
        self.assertIn("mixed project row", verifier_prompt)
        self.assertIn("current model/Provider/Skill/Tool choice", verifier_prompt)
        self.assertIn("assistant-behavior ambiguity", verifier_prompt)
        self.assertIn("over-generalization", verifier_prompt)
        self.assertIn("lost qualifier", verifier_prompt)
        self.assertIn("rubber-stamp", verifier_prompt)
        self.assertEqual(
            result["personalCurationV2"]["promptVersion"],
            PERSONAL_CURATION_POLICY_REVISION,
        )

    def test_missing_evidence_coverage_fails_closed_before_atom_pass(self) -> None:
        executor = FakeExecutor(
            [{"v": 2, "d": [["E1", "p", 0.97, "durable_preference"]]}]
        )
        bundle = {
            "inputs": [_input(1, "我偏好短回答。"), _input(2, "我每天复盘。")],
            "existingMemoryAtoms": [],
        }

        with self.assertRaisesRegex(PersonalMemoryCurationError, "cover every"):
            curate_personal_memory_v2(executor, bundle=bundle)

        self.assertEqual(len(executor.calls), 1)

    def test_supersession_requires_explicit_correction_language(self) -> None:
        executor = FakeExecutor(
            [
                {"v": 2, "d": [["E1", "c", 0.98, "correction"]]},
                {
                    "v": 2,
                    "o": [[
                        "s", "A1", "d", "user:answer-length", "用户偏好长回答。",
                        ["E1"], 0.98, ["沟通风格"],
                    ]],
                },
            ]
        )
        bundle = {
            "inputs": [_input(1, "用户偏好长回答。")],
            "existingMemoryAtoms": [
                {
                    "atomId": "atom:old",
                    "kind": "durable_preference",
                    "claimKey": "user:answer-length",
                    "canonicalText": "用户偏好短回答。",
                    "evidenceIds": ["evidence:old"],
                    "tags": ["沟通风格"],
                }
            ],
        }

        with self.assertRaisesRegex(PersonalMemoryCurationError, "explicit correction"):
            curate_personal_memory_v2(executor, bundle=bundle)

        self.assertEqual(len(executor.calls), 2)

    def test_packet_keeps_complete_current_atom_catalog(self) -> None:
        atoms = [
            {
                "atomId": f"atom:{index}",
                "kind": "personal_fact",
                "claimKey": f"user:fact:{index}",
                "canonicalText": f"用户长期事实 {index}。",
                "evidenceIds": [f"evidence:old:{index}"],
                "tags": ["长期事实"],
            }
            for index in range(40)
        ]

        packet, index = build_personal_memory_packet(
            {"inputs": [_input(1, "我有一个新的长期事实。")], "existingMemoryAtoms": atoms}
        )

        self.assertEqual(len(packet["a"]), 40)
        self.assertEqual(len(index["atomByRef"]), 40)


if __name__ == "__main__":
    unittest.main()
