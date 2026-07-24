from __future__ import annotations

import json
import unittest

from rag_ime.deepseek_config import load_deepseek_config
from rag_ime.deepseek_memory_organizer import DeepSeekMemoryOrganizer
from rag_ime.memory_curation import (
    MEMORY_CURATION_ARCHITECTURE,
    build_memory_curation_model_bundle,
    curation_decisions_to_compile_output,
)


class MemoryCurationTests(unittest.TestCase):
    def test_model_bundle_uses_compact_refs_and_includes_existing_atoms(self) -> None:
        bundle = _source_bundle()

        result = build_memory_curation_model_bundle(bundle)

        self.assertEqual(result["inputs"][0]["ref"], "E1")
        self.assertEqual(result["inputs"][0]["localContext"], "前文正在排查上下文注入")
        self.assertEqual(result["existingAtoms"][0]["ref"], "P1")
        self.assertEqual(result["existingAtoms"][0]["atomId"], "atom:no-fragment-context")
        self.assertEqual(result["existingGroups"][0]["ref"], "G1")
        self.assertEqual(result["existingTags"][0]["ref"], "T1")
        self.assertNotIn("rimeRankFeedback", result)

    def test_atom_decisions_drive_all_semantic_projections_and_native_lexicon_lane(self) -> None:
        bundle = _source_bundle()
        decisions = {
            "schemaVersion": "rag-ime.memory-curation-decisions.v1",
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
            "decisions": [
                {
                    "action": "attach",
                    "evidenceRefs": ["E1"],
                    "targetRef": "P1",
                    "kind": "requirement",
                    "topicRef": "G1",
                    "tags": ["T1", "T2"],
                    "confidence": 0.94,
                },
                {
                    "action": "create",
                    "evidenceRefs": ["E2"],
                    "canonicalText": "用户将该产品称为智鼬输入法。",
                    "kind": "preference",
                    "topicRef": "G1",
                    "tags": ["T1", "new:产品命名"],
                    "confidence": 0.88,
                },
            ],
            # A model-generated phrase field must be ignored. The native Rime
            # feedback lane below is the sole source of lexicon proposals.
            "phraseCandidates": [{"text": "模型乱造词", "pinyin": "mo xing"}],
            "warnings": [],
        }

        result = curation_decisions_to_compile_output(
            decisions,
            source_bundle=bundle,
            project="ime",
        )

        self.assertEqual(result["curationArchitecture"], MEMORY_CURATION_ARCHITECTURE)
        self.assertEqual(result["curationOutcome"], "changes")
        self.assertEqual(len(result["memoryAtoms"]), 2)
        attached = next(item for item in result["memoryAtoms"] if item["atomId"] == "atom:no-fragment-context")
        self.assertEqual(attached["sourceEventIds"], [1, 101])
        self.assertEqual(attached["app"], "com.openai.codex")
        self.assertEqual(attached["surfaceHints"], [])
        self.assertEqual(result["topicBooks"][0]["bookId"], "book:topic:input-method")
        self.assertIn("atom:no-fragment-context", result["topicBooks"][0]["memoryAtomIds"])
        self.assertTrue(result["tagEdges"])
        self.assertEqual([item["text"] for item in result["phraseCandidates"]], ["智鼬输入法"])
        self.assertEqual(result["phraseCandidates"][0]["pinyin"], "zhi you shu ru fa")
        self.assertNotIn("模型乱造词", str(result))
        self.assertFalse(result["lexiconDiagnostics"]["modelGenerated"])

    def test_ignore_only_batch_is_a_valid_no_change_curation_outcome(self) -> None:
        result = curation_decisions_to_compile_output(
            {
                "decisions": [
                    {
                        "action": "ignore",
                        "evidenceRefs": ["E1", "E2"],
                        "reason": "temporary question",
                    }
                ]
            },
            source_bundle=_source_bundle(include_feedback=False),
            project="ime",
        )

        self.assertEqual(result["curationOutcome"], "no_changes")
        self.assertEqual(result["memoryAtoms"], [])
        self.assertEqual(result["topicBooks"], [])
        self.assertEqual(result["curationDiagnostics"]["ignoredDecisionCount"], 1)

    def test_compact_reference_protocol_expands_without_model_repeating_rows(self) -> None:
        result = curation_decisions_to_compile_output(
            {
                "attach": [["E1", "P1"]],
                "create": ["E2"],
                "merge": [["P2", "P1"]],
                "ignore": [],
                "tagMerges": [],
            },
            source_bundle=_source_bundle(include_feedback=False),
            project="ime",
        )

        self.assertEqual(result["curationDiagnostics"]["decisionCount"], 3)
        self.assertEqual(result["curationDiagnostics"]["mergedAtomCount"], 1)
        canonical = next(
            item
            for item in result["memoryAtoms"]
            if item["atomId"] == "atom:no-fragment-context"
        )
        self.assertEqual(canonical["sourceEventIds"], [1, 2, 101])
        created = next(
            item
            for item in result["memoryAtoms"]
            if item["atomId"] != "atom:no-fragment-context"
        )
        self.assertEqual(created["canonicalText"], "我会使用智鼬输入法")
        self.assertEqual(created["sourceEventIds"], [102])

    def test_merge_keeps_canonical_atom_and_unions_existing_provenance(self) -> None:
        result = curation_decisions_to_compile_output(
            {
                "decisions": [
                    {
                        "action": "merge",
                        "sourceRef": "P2",
                        "targetRef": "P1",
                        "reason": "语义等价，保留约束更明确的表述",
                        "confidence": 0.96,
                    }
                ]
            },
            source_bundle=_source_bundle(include_feedback=False),
            project="ime",
        )

        self.assertEqual(len(result["memoryAtoms"]), 1)
        canonical = result["memoryAtoms"][0]
        self.assertEqual(canonical["atomId"], "atom:no-fragment-context")
        self.assertEqual(canonical["sourceEventIds"], [1, 2])
        self.assertIn("输入法零散词不能作为 Agent 记忆。", canonical["aliases"])
        self.assertEqual(
            result["supersedes"],
            [
                {
                    "oldId": "atom:fragment-memory",
                    "newId": "atom:no-fragment-context",
                    "sourceEventIds": [1, 2],
                    "reason": "语义等价，保留约束更明确的表述",
                }
            ],
        )
        self.assertEqual(result["curationDiagnostics"]["mergedAtomCount"], 1)

    def test_multiple_attaches_to_one_atom_keep_every_new_evidence(self) -> None:
        result = curation_decisions_to_compile_output(
            {
                "decisions": [
                    {
                        "action": "attach",
                        "evidenceRefs": ["E1"],
                        "targetRef": "P1",
                        "topicRef": "G1",
                        "tags": ["T1"],
                    },
                    {
                        "action": "attach",
                        "evidenceRefs": ["E2"],
                        "targetRef": "P1",
                        "topicRef": "G1",
                        "tags": ["T2"],
                    },
                ]
            },
            source_bundle=_source_bundle(include_feedback=False),
            project="ime",
        )

        self.assertEqual(len(result["memoryAtoms"]), 1)
        self.assertEqual(result["memoryAtoms"][0]["sourceEventIds"], [1, 101, 102])
        self.assertEqual(
            set(result["memoryAtoms"][0]["tags"]),
            {"输入法", "上下文治理"},
        )

    def test_deepseek_curation_prompt_requests_only_compact_atom_decisions(self) -> None:
        config = load_deepseek_config(
            env={
                "DEEPSEEK_API_KEY": "secret",
                "RAG_IME_DEEPSEEK_BASE_URL": "https://api.deepseek.com",
                "RAG_IME_DEEPSEEK_MODEL": "deepseek-v4-flash",
            }
        )
        captured: dict[str, object] = {}

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return json.dumps(
                    {
                        "choices": [
                            {
                                "message": {
                                    "content": json.dumps(
                                        {
                                            "attach": [["E1", "P1"]],
                                            "create": [],
                                            "update": [],
                                            "supersede": [],
                                            "merge": [],
                                            "ignore": ["E2"],
                                            "tagMerges": [],
                                            "warnings": [],
                                        },
                                        ensure_ascii=False,
                                    )
                                }
                            }
                        ]
                    },
                    ensure_ascii=False,
                ).encode("utf-8")

        def fake_urlopen(request, timeout):
            del timeout
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            return FakeResponse()

        result = DeepSeekMemoryOrganizer(config, urlopen=fake_urlopen).compile_memory_curation(
            bundle=_source_bundle(include_feedback=False),
            project="ime",
        )

        self.assertEqual(result["schemaVersion"], "rag-ime.memory-curation-decisions.v1")
        self.assertEqual(result["attach"], [["E1", "P1"]])
        self.assertEqual(result["ignore"], ["E2"])
        request = captured["payload"]
        system_prompt = request["messages"][0]["content"]
        self.assertIn("Atom-first", system_prompt)
        self.assertIn("禁止输出 dailyBooks", system_prompt)
        self.assertIn("词库由 Rime", system_prompt)
        self.assertIn('attach: [["E1","P1"]]', system_prompt)
        user_payload = json.loads(request["messages"][1]["content"])
        self.assertEqual(user_payload["snapshot"]["existingAtoms"][0]["ref"], "P1")
        self.assertNotIn("rimeRankFeedback", user_payload["snapshot"])


def _source_bundle(*, include_feedback: bool = True) -> dict[str, object]:
    return {
        "schemaVersion": "rag-ime.memory-book-source-bundle.v1",
        "project": "ime",
        "bundleHash": "sha256:bundle",
        "cursor": {"fromEventId": 0, "toEventId": 102, "pendingEventCount": 2},
        "recentEvents": [
            {
                "eventId": 101,
                "sourceEventIds": [101],
                "createdAtMs": 1,
                "text": "输入法的单词碎片不能直接注入 Agent 上下文",
                "recentContext": "前文正在排查上下文注入",
                "app": "com.openai.codex",
                "contextGroupId": "app:codex",
                "finalized": True,
                "memoryEligible": True,
            },
            {
                "eventId": 102,
                "sourceEventIds": [102],
                "createdAtMs": 2,
                "text": "我会使用智鼬输入法",
                "app": "com.apple.Notes",
                "contextGroupId": "app:notes",
                "finalized": True,
                "memoryEligible": True,
            },
        ],
        "existingMemoryAtoms": [
            {
                "atomId": "atom:no-fragment-context",
                "kind": "project_requirement",
                "canonicalText": "禁止把输入法碎片注入普通 Agent 上下文。",
                "sourceEventIds": [1],
                "sourceMemoryIds": [],
                "app": "com.openai.codex",
                "project": "ime",
                "tags": ["输入法", "上下文治理"],
                "semanticGroupIds": ["group:input-method"],
                "aliases": [],
                "queryExpansions": [],
                "status": "active",
            },
            {
                "atomId": "atom:fragment-memory",
                "kind": "project_requirement",
                "canonicalText": "输入法零散词不能作为 Agent 记忆。",
                "sourceEventIds": [2],
                "sourceMemoryIds": [],
                "app": "com.openai.codex",
                "project": "ime",
                "tags": ["输入法"],
                "semanticGroupIds": ["group:input-method"],
                "aliases": ["禁止保存逐词输入"],
                "queryExpansions": [],
                "status": "active",
            },
        ],
        "existingSemanticGroups": [
            {
                "groupId": "group:input-method",
                "title": "输入法",
                "description": "输入法、候选与个人记忆。",
                "aliases": ["RAG-IME"],
                "tags": ["输入法"],
                "sourceEventIds": [1],
            }
        ],
        "existingSemanticTags": [
            {
                "tagId": 1,
                "name": "输入法",
                "description": "输入系统",
                "aliases": ["IME"],
                "semanticGroupIds": ["group:input-method"],
                "sourceEventIds": [1],
            },
            {
                "tagId": 2,
                "name": "上下文治理",
                "description": "控制可注入的上下文",
                "aliases": [],
                "semanticGroupIds": ["group:input-method"],
                "sourceEventIds": [1],
            },
        ],
        "existingTagEdges": [],
        "existingMemoryBooks": [
            {
                "bookId": "book:topic:input-method",
                "bookType": "topic",
                "bookKey": "input-method",
                "title": "输入法",
                "summary": "输入法只召回经过治理的长期记忆。",
                "tags": ["输入法"],
                "sourceEventIds": [1],
                "memoryAtomIds": ["atom:no-fragment-context"],
                "semanticGroupIds": ["group:input-method"],
            }
        ],
        "feedback": [],
        "rimeRankFeedback": (
            [
                {
                    "action": "accepted",
                    "preedit": "zhi you shu ru fa",
                    "acceptedText": "智鼬输入法",
                    "rejectedText": "",
                    "candidateRank": 2,
                    "app": "com.apple.Notes",
                }
            ]
            if include_feedback
            else []
        ),
    }


if __name__ == "__main__":
    unittest.main()
