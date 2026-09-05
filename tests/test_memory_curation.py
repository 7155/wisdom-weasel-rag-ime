from __future__ import annotations

import json
import unittest

from rag_ime.deepseek_config import load_deepseek_config
from rag_ime.deepseek_memory_organizer import (
    DeepSeekMemoryOrganizer,
    DeepSeekMemoryOrganizerError,
)
from rag_ime.memory_curation import (
    MEMORY_CURATION_ARCHITECTURE,
    build_memory_curation_model_bundle,
    curation_decisions_to_compile_output,
)
from rag_ime.memory_book_compiler import (
    inspect_memory_book_plan,
    memory_book_plan_from_compile_output,
)


class MemoryCurationTests(unittest.TestCase):
    def test_model_and_verifier_snapshot_keep_tail_constraint_and_source_scope(self):
        from rag_ime.deepseek_memory_organizer import _semantic_curation_prompt_bundle

        text = "讨论现有实现及其调用关系。" * 70 + "最终决定：不要自动发布，只允许本地修改。"
        bundle = _source_bundle()
        bundle["recentEvents"] = [{
            "eventId": 901, "sourceEventIds": [901], "sourceRef": "source:901",
            "text": text, "createdAtMs": 2000, "sourceOccurredAtMs": 1000,
            "project": "paw", "app": "com.openai.codex", "sourceKind": "user_final",
        }]
        model_bundle = build_memory_curation_model_bundle(bundle)
        snapshot = _semantic_curation_prompt_bundle(model_bundle)
        evidence = snapshot["inputs"][0]
        self.assertEqual(evidence["text"], text)
        self.assertEqual(evidence["sourceOccurredAtMs"], 1000)
        self.assertEqual(evidence["project"], "paw")
        self.assertEqual(model_bundle["inputs"][0]["sourceRef"], "source:901")
        self.assertEqual(model_bundle["inputs"][0]["eventIds"], [901])


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
                    "canonicalText": "用户将该产品称为澄输入法。",
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
        self.assertEqual([item["text"] for item in result["phraseCandidates"]], ["澄输入法"])
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

    def test_explicit_forget_decision_projects_a_guarded_retraction(self) -> None:
        bundle = _source_bundle(include_feedback=False)
        bundle["recentEvents"] = [
            {
                "eventId": 201,
                "sourceEventIds": [201],
                "sourceRef": "S1",
                "createdAtMs": 1,
                "text": "忘记输入法碎片不能直接注入 Agent 上下文这条记忆。",
                "finalized": True,
                "memoryEligible": True,
            }
        ]

        result = curation_decisions_to_compile_output(
            {
                "retract": [
                    {
                        "e": "E1",
                        "p": "P1",
                        "confidence": 0.99,
                        "reason": "explicit_user_forget",
                    }
                ],
                "ignore": [],
            },
            source_bundle=bundle,
            project="ime",
        )

        self.assertEqual(result["curationOutcome"], "changes")
        self.assertEqual(
            result["memoryRetractions"],
            [
                {
                    "targetAtomId": "atom:no-fragment-context",
                    "reason": "explicit_user_forget",
                    "sourceEventIds": [201],
                    "confidence": 0.99,
                }
            ],
        )
        self.assertEqual(
            result["sourceDecisions"][0]["reasonCode"],
            "explicit_memory_forget",
        )
        self.assertEqual(
            result["sourceDecisions"][0]["disposition"],
            "not_for_memory",
        )
        self.assertEqual(result["curationDiagnostics"]["retractionCount"], 1)

    def test_independent_verifier_rejection_fails_the_frozen_batch(self) -> None:
        class RejectingExecutor:
            def complete(
                self,
                *,
                messages,
                max_tokens=None,
                phase="model-call",
                isolated=False,
            ):
                del max_tokens, isolated
                if phase == "atom-first-verifier":
                    packet = json.loads(messages[1]["content"])
                    return {
                        "choices": [
                            {
                                "message": {
                                    "content": json.dumps(
                                        {
                                            "v": 1,
                                            "ok": 0,
                                            "coveredEvidenceRefs": ["E1", "E2"],
                                            "checkedActionCount": packet[
                                                "expectedActionCount"
                                            ],
                                            "decisionDigest": packet["decisionDigest"],
                                            "findings": [
                                                {
                                                    "code": "unsupported_inference",
                                                    "actionType": "attach",
                                                    "actionIndex": 0,
                                                    "evidenceRefs": ["E1"],
                                                }
                                            ],
                                            "errors": ["unsupported_inference"],
                                        }
                                    )
                                }
                            }
                        ]
                    }
                return {
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
                                        "retract": [],
                                        "ignore": ["E2"],
                                        "tagMerges": [],
                                        "warnings": [],
                                    }
                                )
                            }
                        }
                    ]
                }

        organizer = DeepSeekMemoryOrganizer(
            load_deepseek_config(
                env={
                    "DEEPSEEK_API_KEY": "secret",
                    "RAG_IME_DEEPSEEK_MODEL": "deepseek-v4-flash",
                }
            ),
            completion_executor=RejectingExecutor(),
        )
        with self.assertRaisesRegex(
            DeepSeekMemoryOrganizerError,
            "independent memory curation verifier rejected",
        ):
            organizer.compile_memory_curation(
                bundle=_source_bundle(include_feedback=False),
                project="ime",
            )

    def test_one_evidence_can_create_independent_atoms_in_multiple_books(self) -> None:
        bundle = _source_bundle(include_feedback=False)
        bundle["recentEvents"] = [
            {
                "eventId": 201,
                "sourceEventIds": [201],
                "sourceRef": "S1",
                "createdAtMs": 1,
                "text": (
                    "Rime 候选不能被模型候选重排；切换应用后必须让旧模型候选失效。"
                ),
                "app": "com.openai.codex",
                "contextGroupId": "app:codex",
                "finalized": True,
                "memoryEligible": True,
            }
        ]

        result = curation_decisions_to_compile_output(
            {
                "create": [
                    {
                        "e": "E1",
                        "text": "Rime 候选不能被模型候选重排。",
                        "kind": "project_constraint",
                        "topicRefs": ["G1"],
                        "tags": ["new:Rime", "new:候选排序"],
                        "confidence": 0.98,
                    },
                    {
                        "e": "E1",
                        "text": "切换应用后必须让旧模型候选失效。",
                        "kind": "project_requirement",
                        "topicRefs": ["G1", "new:context-stability"],
                        "topicTitle": "上下文稳定性",
                        "tags": ["new:候选失效"],
                        "confidence": 0.97,
                    },
                ],
                "ignore": [],
                "warnings": [],
            },
            source_bundle=bundle,
            project="ime",
        )

        self.assertEqual(len(result["memoryAtoms"]), 2)
        self.assertEqual(
            {item["kind"] for item in result["memoryAtoms"]},
            {"project_constraint", "project_requirement"},
        )
        self.assertTrue(
            all(item["sourceEventIds"] == [201] for item in result["memoryAtoms"])
        )
        self.assertEqual(
            result["sourceDecisions"],
            [
                {
                    "sourceRef": "S1",
                    "evidenceRef": "E1",
                    "disposition": "remember",
                    "reasonCode": "atom_create",
                    "confidence": 0.98,
                }
            ],
        )
        books_by_title = {item["title"]: item for item in result["topicBooks"]}
        self.assertEqual(set(books_by_title), {"输入法", "上下文稳定性"})
        context_atom = next(
            item
            for item in result["memoryAtoms"]
            if "切换应用" in item["canonicalText"]
        )
        self.assertIn(
            context_atom["atomId"],
            books_by_title["输入法"]["memoryAtomIds"],
        )
        self.assertIn(
            context_atom["atomId"],
            books_by_title["上下文稳定性"]["memoryAtomIds"],
        )

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
        self.assertEqual(created["canonicalText"], "我会使用澄输入法")
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

    def test_global_catalog_bundle_is_complete_uncapped_and_order_stable(self) -> None:
        bundle = _global_catalog_bundle()
        bundle["existingMemoryAtoms"] = [
            {
                "atomId": f"atom:{index}",
                "kind": "project_fact",
                "canonicalText": f"catalog fact {index}",
                "claimKey": f"claim:{index}",
                "lineageId": f"lineage:{index}",
                "claimState": "current",
                "validFromMs": index,
                "validToMs": None,
                "supersedesId": "",
                "sourceEventIds": [index + 1],
                "sourceMemoryIds": [f"memory:{value}" for value in range(70)],
                "app": "com.openai.codex",
                "project": "ime",
                "tags": [f"tag-{value}" for value in range(20)],
                "semanticGroupIds": [f"group:{value}" for value in range(10)],
                "aliases": [f"alias-{value}" for value in range(60)],
                "surfaceHints": [f"surface-{value}" for value in range(40)],
                "queryExpansions": [f"query-{value}" for value in range(50)],
                "status": "active",
            }
            for index in range(501)
        ]
        bundle["existingSemanticGroups"] = [
            {
                "groupId": f"group:{index}",
                "title": f"Group {index}",
                "description": f"Group description {index}",
                "aliases": [],
                "tags": [],
            }
            for index in range(25)
        ]
        bundle["existingSemanticTags"] = [
            {
                "tagId": index + 1,
                "name": f"Tag {index}",
                "description": f"Tag description {index}",
                "aliases": [],
                "semanticGroupIds": [],
            }
            for index in range(161)
        ]
        bundle["existingTagEdges"] = [
            {
                "srcTagId": (index % 161) + 1,
                "dstTagId": ((index + 1) % 161) + 1,
                "edgeType": "related_to",
                "weight": 0.5,
                "evidenceCount": 1,
            }
            for index in range(241)
        ]
        bundle["existingMemoryBooks"] = [
            {
                "bookId": f"book:{index}",
                "title": f"Book {index}",
                "summary": f"Book summary {index}",
                "tags": [],
                "semanticGroupIds": [],
                "memoryAtomIds": [f"atom:{index}"],
                "status": "active",
            }
            for index in range(49)
        ]

        result = build_memory_curation_model_bundle(bundle)
        reordered = dict(bundle)
        for key in (
            "existingMemoryAtoms",
            "existingSemanticGroups",
            "existingSemanticTags",
            "existingTagEdges",
            "existingMemoryBooks",
        ):
            reordered[key] = list(reversed(bundle[key]))
        reordered_result = build_memory_curation_model_bundle(reordered)

        self.assertEqual(len(result["existingAtoms"]), 501)
        self.assertEqual(len(result["existingGroups"]), 25)
        self.assertEqual(len(result["existingTags"]), 161)
        self.assertEqual(len(result["existingTagEdges"]), 241)
        self.assertEqual(len(result["existingBooks"]), 49)
        self.assertEqual(len(result["existingAtoms"][0]["tags"]), 20)
        self.assertEqual(len(result["existingAtoms"][0]["sourceMemoryIds"]), 70)
        self.assertTrue(result["catalogComplete"])
        self.assertFalse(any(result["catalogTruncated"].values()))
        self.assertEqual(result["catalogDigest"], reordered_result["catalogDigest"])

    def test_global_catalog_digest_ignores_only_maintenance_timestamps(self) -> None:
        bundle = _global_catalog_bundle()
        for key in (
            "existingMemoryAtoms",
            "existingSemanticGroups",
            "existingSemanticTags",
            "existingTagEdges",
            "existingMemoryBooks",
        ):
            for item in bundle[key]:
                item["updatedAtMs"] = 10
                item["lastActiveAtMs"] = 11
        baseline = build_memory_curation_model_bundle(bundle)["catalogDigest"]
        timestamp_only = json.loads(json.dumps(bundle))
        for key in (
            "existingMemoryAtoms",
            "existingSemanticGroups",
            "existingSemanticTags",
            "existingTagEdges",
            "existingMemoryBooks",
        ):
            for item in timestamp_only[key]:
                item["updatedAtMs"] = 999
                item["lastActiveAtMs"] = 1_000
        self.assertEqual(
            build_memory_curation_model_bundle(timestamp_only)["catalogDigest"],
            baseline,
        )

        semantic_change = json.loads(json.dumps(timestamp_only))
        semantic_change["existingMemoryBooks"][0]["summary"] = "Changed meaning"
        self.assertNotEqual(
            build_memory_curation_model_bundle(semantic_change)["catalogDigest"],
            baseline,
        )

    def test_global_catalog_rejects_every_atom_authority_mismatch(self) -> None:
        authority_cases = {
            "ownerKind": ("user", "agent"),
            "ownerId": ("default", "other"),
            "privacyLevel": ("local", "private"),
            "knowledgeDomain": ("legacy", "personal_memory"),
            "scopeKind": ("project", "user"),
            "scopeId": ("ime", "default"),
            "visibility": ("shared", "private"),
            "authorizationRevision": ("auth:1", "auth:2"),
            "bindingId": ("binding:1", "binding:2"),
            "scopeMode": ("advisory", "authoritative"),
        }
        for field, (left, right) in authority_cases.items():
            with self.subTest(field=field):
                bundle = _global_catalog_bundle()
                bundle["existingMemoryAtoms"][0][field] = left
                bundle["existingMemoryAtoms"][1][field] = right
                rejected = curation_decisions_to_compile_output(
                    {"merge": [["P2", "P1"]]},
                    source_bundle=bundle,
                    project="ime",
                )
                self.assertEqual(rejected["supersedes"], [])
                self.assertTrue(
                    any(
                        warning.startswith(
                            "global_catalog_non_equivalent_atom_merge_ignored:"
                        )
                        for warning in rejected["warnings"]
                    )
                )


    def test_global_catalog_accepts_only_exact_atom_and_physical_tag_merges(self) -> None:
        bundle = _global_catalog_bundle()
        result = curation_decisions_to_compile_output(
            {
                "atomDecisions": [
                    {
                        "action": "merge",
                        "sourceRef": "P2",
                        "targetRef": "P1",
                        "reason": "exact duplicate",
                    },
                    {
                        "action": "create",
                        "canonicalText": "global audit must not create",
                    },
                ],
                "tagMerges": [
                    {
                        "source": "T2",
                        "target": "T1",
                        "reason": "normalized duplicate",
                    }
                ],
            },
            source_bundle=bundle,
            project="ime",
        )

        self.assertEqual(
            [(item["oldId"], item["newId"]) for item in result["supersedes"]],
            [("atom:duplicate:2", "atom:duplicate:1")],
        )
        self.assertEqual(
            result["tagMerges"],
            [
                {
                    "source": "Agent",
                    "target": "Agent",
                    "sourceTagId": 12,
                    "targetTagId": 11,
                    "reason": "normalized duplicate",
                    "evidenceEventIds": [],
                    "confidence": 0.8,
                }
            ],
        )
        self.assertIn(
            "catalog_audit_disallowed_fact_action_ignored",
            result["warnings"],
        )
        plan = memory_book_plan_from_compile_output(
            result,
            project="ime",
            provider="openai-codex",
            model="gpt-5.6-luna",
            source_bundle=bundle,
        )
        validation = inspect_memory_book_plan(plan)
        self.assertTrue(validation["ok"], validation)
        self.assertEqual(validation["counts"]["memoryAtoms"], 1)
        self.assertEqual(validation["counts"]["supersedes"], 1)
        self.assertEqual(validation["counts"]["tagMerges"], 1)
        planned_tag_merge = next(
            item
            for item in plan["diffs"]
            if item["op"] == "merge_semantic_tag"
        )
        self.assertEqual(planned_tag_merge["payload"]["sourceTagId"], 12)
        self.assertEqual(planned_tag_merge["payload"]["targetTagId"], 11)
        no_model_tag_merge = dict(result)
        no_model_tag_merge["tagMerges"] = []
        deterministic_plan = memory_book_plan_from_compile_output(
            no_model_tag_merge,
            project="ime",
            provider="openai-codex",
            model="gpt-5.6-luna",
            source_bundle=bundle,
        )
        deterministic_tag_merges = [
            item
            for item in deterministic_plan["diffs"]
            if item["op"] == "merge_semantic_tag"
        ]
        self.assertEqual(len(deterministic_tag_merges), 1)
        self.assertEqual(
            deterministic_tag_merges[0]["payload"]["sourceTagId"],
            12,
        )
        self.assertEqual(
            deterministic_tag_merges[0]["payload"]["targetTagId"],
            11,
        )

        mismatched = json.loads(json.dumps(bundle))
        mismatched["existingMemoryAtoms"][1]["project"] = "another-project"
        rejected = curation_decisions_to_compile_output(
            {
                "merge": [["P2", "P1"]],
            },
            source_bundle=mismatched,
            project="ime",
        )
        self.assertEqual(rejected["supersedes"], [])
        self.assertTrue(
            any(
                warning.startswith(
                    "global_catalog_non_equivalent_atom_merge_ignored:"
                )
                for warning in rejected["warnings"]
            )
        )

    def test_global_catalog_organizer_is_dedicated_merge_only_and_fail_closed(self) -> None:
        captured: list[dict[str, object]] = []

        class CatalogExecutor:
            def complete(
                self,
                *,
                messages,
                max_tokens=None,
                phase="model-call",
                isolated=False,
            ):
                del max_tokens
                captured.append(
                    {
                        "messages": messages,
                        "phase": phase,
                        "isolated": isolated,
                    }
                )
                if phase == "memory-catalog-consolidation-verifier":
                    packet = json.loads(messages[1]["content"])
                    return {
                        "choices": [
                            {
                                "message": {
                                    "content": json.dumps(
                                        {
                                            "v": 1,
                                            "ok": 1,
                                            "coveredEvidenceRefs": [],
                                            "checkedActionCount": packet[
                                                "expectedActionCount"
                                            ],
                                            "decisionDigest": packet[
                                                "decisionDigest"
                                            ],
                                            "findings": [],
                                            "errors": [],
                                        }
                                    )
                                }
                            }
                        ]
                    }
                return {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "atomDecisions": [
                                            {
                                                "action": "merge",
                                                "sourceRef": "P2",
                                                "targetRef": "P1",
                                            },
                                            {
                                                "action": "create",
                                                "canonicalText": "not allowed",
                                            },
                                        ],
                                        "create": [
                                            {
                                                "canonicalText": "also not allowed",
                                            }
                                        ],
                                        "tagMerges": [
                                            {
                                                "source": "T2",
                                                "target": "T1",
                                                "reason": "same normalized name",
                                            }
                                        ],
                                        "warnings": [],
                                    }
                                )
                            }
                        }
                    ]
                }

        organizer = DeepSeekMemoryOrganizer(
            load_deepseek_config(
                env={
                    "DEEPSEEK_API_KEY": "secret",
                    "RAG_IME_DEEPSEEK_MODEL": "deepseek-v4-flash",
                }
            ),
            completion_executor=CatalogExecutor(),
        )
        result = organizer.compile_memory_curation(
            bundle=_global_catalog_bundle(),
            project="ime",
        )

        self.assertEqual(
            [item["phase"] for item in captured],
            [
                "memory-catalog-consolidation",
                "memory-catalog-consolidation-verifier",
            ],
        )
        self.assertFalse(captured[0]["isolated"])
        self.assertTrue(captured[1]["isolated"])
        self.assertEqual(len(result["merge"]), 1)
        self.assertEqual(result["create"], [])
        self.assertIn(
            "global_catalog_direct_actions_discarded",
            result["warnings"],
        )
        snapshot = json.loads(captured[0]["messages"][1]["content"])["snapshot"]
        self.assertTrue(snapshot["catalogComplete"])
        self.assertTrue(snapshot["catalogDigest"])
        self.assertEqual(snapshot["existingTags"][0]["tagId"], 11)
        self.assertEqual(
            snapshot["existingAtoms"][0]["claimKey"],
            "claim:duplicate",
        )
        self.assertIn("normalized name", captured[0]["messages"][0]["content"])

        incomplete = _global_catalog_bundle()
        incomplete["catalogComplete"] = False
        calls_before = len(captured)
        with self.assertRaisesRegex(
            DeepSeekMemoryOrganizerError,
            "requires a complete catalog snapshot",
        ):
            organizer.compile_memory_curation(
                bundle=incomplete,
                project="ime",
            )
        self.assertEqual(len(captured), calls_before)

    def test_deepseek_curation_prompt_requests_only_compact_atom_decisions(self) -> None:
        config = load_deepseek_config(
            env={
                "DEEPSEEK_API_KEY": "secret",
                "RAG_IME_DEEPSEEK_BASE_URL": "https://api.deepseek.com",
                "RAG_IME_DEEPSEEK_MODEL": "deepseek-v4-flash",
            }
        )
        captured: list[dict[str, object]] = []

        class FakeResponse:
            def __init__(self, content: dict[str, object]):
                self.content = content

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
                                    "content": json.dumps(self.content, ensure_ascii=False)
                                }
                            }
                        ]
                    },
                    ensure_ascii=False,
                ).encode("utf-8")

        def fake_urlopen(request, timeout):
            del timeout
            request_payload = json.loads(request.data.decode("utf-8"))
            captured.append(request_payload)
            user_payload = json.loads(request_payload["messages"][1]["content"])
            if "decisionDigest" in user_payload:
                return FakeResponse(
                    {
                        "v": 1,
                        "ok": 1,
                        "coveredEvidenceRefs": ["E1", "E2"],
                        "checkedActionCount": user_payload["expectedActionCount"],
                        "decisionDigest": user_payload["decisionDigest"],
                        "findings": [],
                        "errors": [],
                    }
                )
            return FakeResponse(
                {
                    "attach": [["E1", "P1"]],
                    "create": [],
                    "update": [],
                    "supersede": [],
                    "merge": [],
                    "retract": [],
                    "ignore": ["E2"],
                    "tagMerges": [],
                    "warnings": [],
                }
            )

        result = DeepSeekMemoryOrganizer(config, urlopen=fake_urlopen).compile_memory_curation(
            bundle=_source_bundle(include_feedback=False),
            project="ime",
        )

        self.assertEqual(result["schemaVersion"], "rag-ime.memory-curation-decisions.v1")
        self.assertEqual(result["attach"], [["E1", "P1"]])
        self.assertEqual(result["ignore"], ["E2"])
        self.assertTrue(result["independentlyVerified"])
        self.assertEqual(len(captured), 2)
        request = captured[0]
        system_prompt = request["messages"][0]["content"]
        self.assertIn("Atom-first", system_prompt)
        self.assertIn("禁止输出 dailyBooks", system_prompt)
        self.assertIn("词库由 Rime", system_prompt)
        self.assertIn('attach: [["E1","P1"]]', system_prompt)
        user_payload = json.loads(request["messages"][1]["content"])
        self.assertEqual(user_payload["snapshot"]["existingAtoms"][0]["ref"], "P1")
        self.assertNotIn("rimeRankFeedback", user_payload["snapshot"])


def _global_catalog_bundle() -> dict[str, object]:
    bundle = _source_bundle(include_feedback=False)
    common_atom = {
        "kind": "project_fact",
        "canonicalText": "The catalog keeps one exact duplicate.",
        "claimKey": "claim:duplicate",
        "lineageId": "lineage:duplicate",
        "claimState": "current",
        "validFromMs": 10,
        "validToMs": None,
        "supersedesId": "",
        "app": "com.openai.codex",
        "project": "ime",
        "tags": ["Agent"],
        "semanticGroupIds": ["group:input-method"],
        "aliases": [],
        "surfaceHints": [],
        "queryExpansions": [],
        "sourceMemoryIds": [],
        "status": "active",
        "confidence": 0.9,
        "qualityScore": 0.9,
    }
    bundle.update(
        {
            "curationScope": "global",
            "catalogAudit": True,
            "catalogOnly": True,
            "catalogComplete": True,
            "catalogTruncated": {},
            "recentEvents": [],
            "existingMemoryAtoms": [
                {
                    **common_atom,
                    "atomId": "atom:duplicate:1",
                    "sourceEventIds": [1],
                },
                {
                    **common_atom,
                    "atomId": "atom:duplicate:2",
                    "sourceEventIds": [2],
                },
            ],
            "existingSemanticTags": [
                {
                    "tagId": 11,
                    "name": "Agent",
                    "description": "Agent concept",
                    "aliases": [],
                    "semanticGroupIds": ["group:input-method"],
                    "sourceEventIds": [1],
                    "qualityScore": 0.9,
                },
                {
                    "tagId": 12,
                    "name": "Agent",
                    "description": "Duplicate Agent concept",
                    "aliases": [],
                    "semanticGroupIds": ["group:input-method"],
                    "sourceEventIds": [2],
                    "qualityScore": 0.8,
                },
            ],
            "existingTagEdges": [
                {
                    "srcTagId": 11,
                    "dstTagId": 12,
                    "edgeType": "related_to",
                    "weight": 0.5,
                    "evidenceCount": 1,
                }
            ],
            "existingMemoryBooks": [
                {
                    "bookId": "book:topic:catalog",
                    "title": "Catalog",
                    "summary": "Derived view over exact duplicate atoms.",
                    "tags": ["Agent"],
                    "sourceEventIds": [1, 2],
                    "memoryAtomIds": [
                        "atom:duplicate:1",
                        "atom:duplicate:2",
                    ],
                    "semanticGroupIds": ["group:input-method"],
                    "status": "active",
                }
            ],
        }
    )
    return bundle


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
                "text": "我会使用澄输入法",
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
                    "acceptedText": "澄输入法",
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
