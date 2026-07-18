from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from rag_ime.local_mlx_memory_organizer import LocalMlxMemoryOrganizer


class LocalMlxMemoryOrganizerTests(unittest.TestCase):
    def test_normalizes_local_json_without_loading_mlx_or_using_network(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-local-organizer-") as tmp:
            captured: list[list[dict[str, str]]] = []

            def complete(messages):
                captured.append([dict(message) for message in messages])
                return "```json\n" + json.dumps(
                    {
                        "sourceDecisions": [
                            {
                                "sourceRef": "input:1",
                                "disposition": "remember",
                                "reasonCode": "durable_project_decision",
                                "confidence": 0.96,
                            }
                        ],
                        "memoryAtoms": [
                            {
                                "atomId": "atom:local:1",
                                "claimKey": "ime:model:hot-path",
                                "canonicalText": "输入法热路径使用 100M 自训练模型。",
                                "summary": "输入法模型决定",
                                "kind": "project_decision",
                                "tags": ["输入法", "模型"],
                                "sourceEventIds": [1],
                                "confidence": 0.95,
                                "qualityScore": 0.91,
                                "directCandidateAllowed": False,
                            }
                        ],
                        "topicBooks": [],
                    },
                    ensure_ascii=False,
                ) + "\n```"

            organizer = LocalMlxMemoryOrganizer(
                Path(tmp) / "fixture-model",
                completion=complete,
            )
            result = organizer.curate_owner_memory(
                bundle={
                    "inputs": [
                        {
                            "sourceRef": "input:1",
                            "sourceKind": "user_final",
                            "trustClass": "user_direct",
                            "createdAtMs": 1,
                            "sourceEventIds": [1],
                            "text": "输入法热路径使用 100M 自训练模型。",
                        }
                    ]
                },
                project="wisdom-weasel-rag-ime",
                owner_kind="user",
                owner_id="default",
            )

        self.assertEqual(result["provider"], "local-mlx")
        self.assertEqual(result["sourceDecisions"][0]["disposition"], "remember")
        self.assertEqual(result["memoryAtoms"][0]["sourceEventIds"], [1])
        self.assertTrue(result["modelDiagnostics"]["localOnly"])
        self.assertEqual(result["modelDiagnostics"]["externalRequestCount"], 0)
        self.assertIn("只输出一个 JSON 对象", captured[0][0]["content"])

    def test_repairs_a_remember_decision_that_omitted_its_atom(self) -> None:
        calls = 0

        def complete(_messages):
            nonlocal calls
            calls += 1
            if calls == 1:
                return json.dumps(
                    {
                        "sourceDecisions": [
                            {
                                "sourceRef": "input:9",
                                "disposition": "remember",
                                "reasonCode": "durable_project_decision",
                                "confidence": 0.9,
                            }
                        ],
                        "memoryAtoms": [],
                    }
                )
            return json.dumps(
                {
                    "sourceDecisions": [
                        {
                            "sourceRef": "input:9",
                            "disposition": "remember",
                            "reasonCode": "durable_project_decision",
                            "confidence": 0.94,
                        }
                    ],
                    "memoryAtoms": [
                        {
                            "canonicalText": "Session 开始时只召回一次记忆。",
                            "summary": "Session 记忆策略",
                            "kind": "project_decision",
                            "sourceEventIds": [9],
                            "confidence": 0.93,
                            "qualityScore": 0.9,
                            "directCandidateAllowed": False,
                        }
                    ],
                }
            )

        organizer = LocalMlxMemoryOrganizer("/missing", completion=complete)
        result = organizer.curate_owner_memory(
            bundle={
                "inputs": [
                    {
                        "sourceRef": "input:9",
                        "sourceKind": "user_final",
                        "trustClass": "user_direct",
                        "createdAtMs": 9,
                        "sourceEventIds": [9],
                        "text": "Session 开始时只召回一次记忆。",
                    }
                ]
            },
            project="wisdom-weasel-rag-ime",
            owner_kind="user",
            owner_id="default",
        )

        self.assertEqual(calls, 2)
        self.assertEqual(result["modelDiagnostics"]["repairCount"], 1)
        self.assertEqual(result["memoryAtoms"][0]["sourceEventIds"], [9])

    def test_isolates_a_source_when_the_batch_repair_still_omits_it(self) -> None:
        calls = 0

        def complete(_messages):
            nonlocal calls
            calls += 1
            if calls < 3:
                return json.dumps(
                    {
                        "sourceDecisions": [
                            {
                                "sourceRef": "input:17",
                                "disposition": "remember",
                                "reasonCode": "durable_requirement",
                                "confidence": 0.9,
                            }
                        ],
                        "memoryAtoms": [],
                    }
                )
            return json.dumps(
                {
                    "sourceDecisions": [
                        {
                            "sourceRef": "input:17",
                            "disposition": "remember",
                            "reasonCode": "durable_requirement",
                            "confidence": 0.95,
                        }
                    ],
                    "memoryAtoms": [
                        {
                            "canonicalText": "历史记忆整理必须只在本机运行。",
                            "summary": "本地隐私约束",
                            "kind": "project_requirement",
                            "sourceEventIds": [17],
                            "confidence": 0.95,
                            "qualityScore": 0.92,
                            "directCandidateAllowed": False,
                        }
                    ],
                }
            )

        organizer = LocalMlxMemoryOrganizer("/missing", completion=complete)
        result = organizer.curate_owner_memory(
            bundle={
                "inputs": [
                    {
                        "sourceRef": "input:17",
                        "sourceKind": "user_final",
                        "trustClass": "user_direct",
                        "createdAtMs": 17,
                        "sourceEventIds": [17],
                        "text": "历史记忆整理必须只在本机运行。",
                    }
                ]
            },
            project="wisdom-weasel-rag-ime",
            owner_kind="user",
            owner_id="default",
        )

        self.assertEqual(calls, 3)
        self.assertEqual(result["modelDiagnostics"]["repairCount"], 2)
        self.assertEqual(result["memoryAtoms"][0]["sourceEventIds"], [17])


if __name__ == "__main__":
    unittest.main()
