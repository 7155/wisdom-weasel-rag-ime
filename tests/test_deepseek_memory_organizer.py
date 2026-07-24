from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rag_ime.deepseek_config import load_deepseek_config
from rag_ime.deepseek_memory_organizer import (
    DEFAULT_MEMORY_ORGANIZATION_INSTRUCTION,
    DeepSeekMemoryOrganizer,
    _owner_memory_model_bundle,
)


class DeepSeekMemoryOrganizerTests(unittest.TestCase):
    def test_role_book_curation_is_review_only_and_preserves_allowed_ids(self) -> None:
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
                del exc_type, exc, tb
                return False

            def read(self):
                return json.dumps(
                    {
                        "choices": [
                            {
                                "message": {
                                    "content": json.dumps(
                                        {
                                            "traitProposals": [],
                                            "capabilityProposals": [],
                                            "lessonProposals": [],
                                            "commitmentProposals": [],
                                            "warnings": [],
                                        },
                                        ensure_ascii=False,
                                    )
                                }
                            }
                        ]
                    }
                ).encode("utf-8")

        def fake_urlopen(request, timeout):
            del timeout
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            return FakeResponse()

        bundle = {
            "schemaVersion": "rag-ime.role-book-curation-input.v2",
            "curationEvidence": [
                {
                    "evidenceId": "evidence:digest:1",
                    "sourceKind": "session_digest",
                    "text": "已完成并验证角色书维护边界",
                }
            ],
            "activityContext": {
                "corroborationOnly": True,
                "maySupportRoleProposals": False,
            },
            "policy": {
                "allowedEvidenceIds": ["evidence:digest:1"],
                "rawConversationMaySupplyEvidence": False,
                "autoActivation": False,
            },
        }
        result = DeepSeekMemoryOrganizer(
            config,
            urlopen=fake_urlopen,
        ).curate_role_book(
            bundle=bundle,
            project="rag-ime",
            role_id="architect",
            role_version="role-v1",
        )

        self.assertEqual(result["schemaVersion"], "rag-ime.role-book-curation.v1")
        self.assertEqual(result["provider"], "deepseek")
        request_payload = captured["payload"]
        system_prompt = request_payload["messages"][0]["content"]
        self.assertIn("review-only", system_prompt)
        self.assertIn("原始 user/assistant 消息", system_prompt)
        self.assertIn("不能单独", system_prompt)
        model_input = json.loads(request_payload["messages"][1]["content"])
        self.assertEqual(
            model_input["bundle"]["policy"]["allowedEvidenceIds"],
            ["evidence:digest:1"],
        )
        self.assertFalse(model_input["bundle"]["policy"]["autoActivation"])

    def test_owner_model_bundle_keeps_joint_context_without_evidence_ids(self) -> None:
        projected = _owner_memory_model_bundle(
            {
                "inputs": [
                    {
                        "sourceRef": "S1",
                        "sourceKind": "user_final",
                        "trustClass": "user_claim",
                        "createdAtMs": 1,
                        "sourceEventIds": [11],
                        "text": "继续整理个人记忆",
                        "recentContext": "前一轮正在讨论输入法历史记录",
                        "app": "com.openai.codex",
                        "contextGroupId": "app:codex",
                    }
                ],
                "activityContext": {
                    "available": True,
                    "date": "2026-07-17",
                    "status": "draft",
                    "summary": "当天主要在 TextEdit 实现时间线",
                    "sourceEventIds": [999],
                    "segments": [
                        {
                            "segmentId": "segment:1",
                            "app": "TextEdit",
                            "startMs": 2,
                            "endMs": 3,
                            "summary": "实现时间线联合上下文",
                            "sourceEventIds": [999],
                        }
                    ],
                },
                "agentConversationContext": {
                    "available": True,
                    "date": "2026-07-17",
                    "evidenceIds": ["evidence:secret"],
                    "messages": [
                        {
                            "role": "assistant",
                            "text": "已完成有界上下文审计",
                            "occurredAtMs": 4,
                            "evidenceId": "evidence:secret",
                        }
                    ],
                },
            }
        )

        self.assertIn("TextEdit", projected["activityContext"]["summary"])
        self.assertEqual(
            projected["agentConversationContext"]["messages"][0]["text"],
            "已完成有界上下文审计",
        )
        context_json = json.dumps(
            {
                "activity": projected["activityContext"],
                "conversation": projected["agentConversationContext"],
            },
            ensure_ascii=False,
        )
        self.assertNotIn("sourceEventIds", context_json)
        self.assertNotIn("evidenceId", context_json)
        self.assertTrue(projected["activityContext"]["corroborationOnly"])
        self.assertFalse(projected["activityContext"]["maySupportFacts"])
        self.assertEqual(
            projected["inputs"][0]["localContext"],
            "前一轮正在讨论输入法历史记录",
        )
        self.assertEqual(projected["inputs"][0]["app"], "com.openai.codex")

    def test_owner_bundle_samples_long_fragment_provenance_across_full_range(self) -> None:
        projected = _owner_memory_model_bundle(
            {
                "inputs": [
                    {
                        "sourceRef": "S1",
                        "sourceKind": "user_final",
                        "trustClass": "user_claim",
                        "createdAtMs": 1,
                        "sourceEventIds": list(range(1, 5_001)),
                        "text": "重建后的完整输入",
                    }
                ]
            }
        )

        source_ids = projected["inputs"][0]["sourceEventIds"]
        self.assertEqual(len(source_ids), 64)
        self.assertEqual(source_ids[0], 1)
        self.assertEqual(source_ids[-1], 5_000)
        self.assertTrue(all(left < right for left, right in zip(source_ids, source_ids[1:])))

    def test_external_owner_bundle_drops_unrelated_daily_context_and_caps_atoms(
        self,
    ) -> None:
        projected = _owner_memory_model_bundle(
            {
                "inputs": [
                    {
                        "sourceRef": "S1",
                        "sourceKind": "session_digest",
                        "trustClass": "session_summary",
                        "externalProvider": "codex",
                        "createdAtMs": 2,
                        "sourceOccurredAtMs": 1,
                        "sourceEventIds": [11],
                        "text": "Codex 已整理的 Session 摘要",
                    }
                ],
                "activityContext": {
                    "available": True,
                    "summary": "今天正在处理无关的前台窗口。",
                    "segments": [
                        {
                            "segmentId": "segment:1",
                            "app": "TextEdit",
                            "summary": "无关活动",
                        }
                    ],
                },
                "agentConversationContext": {
                    "available": True,
                    "messages": [
                        {
                            "role": "assistant",
                            "text": "无关对话尾窗",
                        }
                    ],
                },
                "existingMemoryAtoms": [
                    {
                        "atomId": f"atom:{index}",
                        "canonicalText": f"已有事实 {index}",
                    }
                    for index in range(40)
                ],
            }
        )

        self.assertFalse(projected["activityContext"]["available"])
        self.assertFalse(projected["agentConversationContext"]["available"])
        self.assertEqual(len(projected["existingMemoryAtoms"]), 20)

    def test_deepseek_config_reads_dedicated_env_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / "deepseek.env"
            env_path.write_text(
                "\n".join(
                    [
                        "DEEPSEEK_API_KEY=secret",
                        "RAG_IME_DEEPSEEK_BASE_URL=https://api.deepseek.com",
                        "RAG_IME_DEEPSEEK_MODEL=deepseek-v4-flash",
                        "RAG_IME_DEEPSEEK_JSON=1",
                        "RAG_IME_DEEPSEEK_ACTIVE_RAG_MAX_TOKENS=1280",
                        "RAG_IME_DEEPSEEK_MEMORY_BOOK_MAX_TOKENS=1536",
                    ]
                ),
                encoding="utf-8",
            )

            config = load_deepseek_config(env_path)

        self.assertEqual(config.api_base_url, "https://api.deepseek.com/v1")
        self.assertEqual(config.api_key, "secret")
        self.assertEqual(config.model, "deepseek-v4-flash")
        self.assertTrue(config.json_mode)
        self.assertEqual(config.thinking, "disabled")
        self.assertEqual(config.active_rag_max_tokens, 1280)
        self.assertEqual(config.memory_book_max_tokens, 1536)

    def test_deepseek_config_reads_process_environment_by_default(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "RAG_IME_DEEPSEEK_API_KEY": "env-secret",
                "RAG_IME_DEEPSEEK_BASE_URL": "https://api.kukuit.com",
                "RAG_IME_DEEPSEEK_MODEL": "deepseek-v4-flash",
            },
            clear=False,
        ):
            config = load_deepseek_config()

        self.assertEqual(config.api_base_url, "https://api.kukuit.com/v1")
        self.assertEqual(config.api_key, "env-secret")
        self.assertEqual(config.model, "deepseek-v4-flash")

    def test_deepseek_config_rejects_non_v4_model_for_high_intelligence_routes(self) -> None:
        with self.assertRaisesRegex(ValueError, "DeepSeek V4"):
            load_deepseek_config(
                env={
                    "DEEPSEEK_API_KEY": "secret",
                    "RAG_IME_DEEPSEEK_MODEL": "deepseek-chat",
                }
            )

    def test_deepseek_config_reads_default_env_file_pointer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / "deepseek.env"
            env_path.write_text(
                "\n".join(
                    [
                        "DEEPSEEK_API_KEY=file-secret",
                        "RAG_IME_DEEPSEEK_BASE_URL=https://api.kukuit.com",
                        "RAG_IME_DEEPSEEK_MODEL=deepseek-v4-flash",
                    ]
                ),
                encoding="utf-8",
            )
            with patch.dict("os.environ", {"RAG_IME_DEEPSEEK_ENV": str(env_path)}, clear=False):
                config = load_deepseek_config()

        self.assertEqual(config.api_base_url, "https://api.kukuit.com/v1")
        self.assertEqual(config.api_key, "file-secret")
        self.assertEqual(config.env_path, env_path)

    def test_memory_organizer_builds_json_chat_completion_request(self) -> None:
        config = load_deepseek_config(
            env={
                "DEEPSEEK_API_KEY": "secret",
                "RAG_IME_DEEPSEEK_BASE_URL": "https://api.deepseek.com",
                "RAG_IME_DEEPSEEK_MODEL": "deepseek-v4-flash",
            }
        )
        captured = {}

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                content = {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "schemaVersion": "rag-ime.memory-book-compile.v1",
                                        "dailyBooks": [],
                                        "topicBooks": [],
                                        "memoryAtoms": [],
                                        "tagEdges": [],
                                        "phraseCandidates": [],
                                        "warnings": [],
                                    },
                                    ensure_ascii=False,
                                )
                            }
                        }
                    ]
                }
                return json.dumps(content).encode("utf-8")

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["timeout"] = timeout
            captured["authorization"] = request.get_header("Authorization")
            captured["userAgent"] = request.get_header("User-agent")
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            return FakeResponse()

        organizer = DeepSeekMemoryOrganizer(config, urlopen=fake_urlopen)
        payload = organizer.compile_memory_book(
            bundle={"recentEvents": [{"eventId": 1, "text": "RAG 输入法"}]},
            project="wisdom-weasel-rag-ime",
            instruction="合并输入法分组，修正语音错字，标签不要太碎",
        )

        self.assertEqual(payload["schemaVersion"], "rag-ime.memory-book-compile.v1")
        self.assertEqual(payload["topicBooks"], [])
        self.assertEqual(payload["semanticGroups"], [])
        self.assertEqual(payload["semanticTags"], [])
        self.assertEqual(payload["provider"], "deepseek")
        self.assertEqual(payload["model"], "deepseek-v4-flash")
        self.assertEqual(payload["instruction"], "合并输入法分组，修正语音错字，标签不要太碎")
        self.assertEqual(captured["url"], "https://api.deepseek.com/v1/chat/completions")
        self.assertEqual(captured["authorization"], "Bearer secret")
        self.assertEqual(captured["userAgent"], "rag-ime/1.0 curl-compatible")
        self.assertEqual(captured["payload"]["response_format"], {"type": "json_object"})
        self.assertEqual(captured["payload"]["thinking"], {"type": "enabled"})
        self.assertEqual(captured["payload"]["reasoning_effort"], "low")
        self.assertEqual(captured["payload"]["max_tokens"], 3072)
        self.assertFalse(captured["payload"]["stream"])
        system_prompt = captured["payload"]["messages"][0]["content"]
        self.assertIn("topicBooks", system_prompt)
        self.assertIn('bookType="topic"', system_prompt)
        self.assertIn("更新摘要而不是按日期新建重复主题", system_prompt)
        self.assertIn("semanticGroups", system_prompt)
        self.assertIn("禁止照抄成语义标签", system_prompt)
        self.assertIn("rimeRankFeedback", system_prompt)
        self.assertIn("合并输入法分组，修正语音错字，标签不要太碎", captured["payload"]["messages"][1]["content"])

    def test_memory_organizer_uses_project_default_when_instruction_is_empty(self) -> None:
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
                body = {"choices": [{"message": {"content": '{"memoryAtoms": []}'}}]}
                return json.dumps(body).encode("utf-8")

        def fake_urlopen(request, timeout):
            request_payload = json.loads(request.data.decode("utf-8"))
            captured.setdefault("payloads", []).append(request_payload)
            captured.setdefault("payload", request_payload)
            return FakeResponse()

        payload = DeepSeekMemoryOrganizer(config, urlopen=fake_urlopen).compile_memory_book(
            bundle={"recentEvents": [{"eventId": 1, "text": "输入法记忆整理"}]},
            project="wisdom-weasel-rag-ime",
        )

        self.assertEqual(payload["instruction"], DEFAULT_MEMORY_ORGANIZATION_INSTRUCTION)
        request_payload = captured["payload"]
        self.assertIn(DEFAULT_MEMORY_ORGANIZATION_INSTRUCTION, request_payload["messages"][1]["content"])
        self.assertIn("不直接写入正式记忆", DEFAULT_MEMORY_ORGANIZATION_INSTRUCTION)

    def test_owner_curator_requires_source_coverage_and_defines_not_for_memory_examples(self) -> None:
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
                body = {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "sourceDecisions": [
                                            {
                                                "sourceRef": "S1",
                                                "disposition": "remember",
                                                "reasonCode": "durable_constraint",
                                                "confidence": 0.95,
                                            }
                                        ],
                                        "memoryAtoms": [],
                                        "phraseCandidates": [{"text": "不应写入词库"}],
                                    },
                                    ensure_ascii=False,
                                )
                            }
                        }
                    ]
                }
                return json.dumps(body, ensure_ascii=False).encode("utf-8")

        def fake_urlopen(request, timeout):
            request_payload = json.loads(request.data.decode("utf-8"))
            captured.setdefault("payloads", []).append(request_payload)
            captured.setdefault("payload", request_payload)
            return FakeResponse()

        payload = DeepSeekMemoryOrganizer(config, urlopen=fake_urlopen).curate_owner_memory(
            bundle={
                "inputs": [
                    {
                        "sourceRef": "S1",
                        "sourceKind": "user_final",
                        "trustClass": "user_claim",
                        "createdAtMs": 1,
                        "sourceEventIds": [11],
                        "text": "不要截图",
                    },
                    {
                        "sourceRef": "S2",
                        "sourceKind": "user_final",
                        "trustClass": "user_claim",
                        "createdAtMs": 2,
                        "sourceEventIds": [12],
                        "text": "嗯嗯那个这个",
                    },
                ]
            },
            project="wisdom-weasel-rag-ime",
            owner_kind="user",
            owner_id="default",
        )

        self.assertEqual(
            [(item["sourceRef"], item["disposition"]) for item in payload["sourceDecisions"]],
            [("S1", "remember"), ("S2", "needs_review")],
        )
        self.assertEqual(payload["phraseCandidates"], [])
        self.assertEqual(len(captured["payloads"]), 2)
        self.assertIn("retry", payload["modelDiagnostics"])
        request_payload = captured["payload"]
        system_prompt = request_payload["messages"][0]["content"]
        self.assertIn("not_for_memory", system_prompt)
        self.assertIn("输入法或语音噪声", system_prompt)
        self.assertIn("不要截图", system_prompt)
        self.assertIn("不应请求助手逐轮输出", system_prompt)
        self.assertIn("没有可复用事实的问题", system_prompt)
        self.assertIn("失败或被拒绝的工具回执", system_prompt)
        self.assertIn("重复问句", system_prompt)
        self.assertIn("禁止 project_question", system_prompt)
        self.assertIn("不能原封不动复制长输入", system_prompt)

    def test_owner_curator_recovers_truncated_output_with_compact_retry(self) -> None:
        config = load_deepseek_config(
            env={
                "DEEPSEEK_API_KEY": "secret",
                "RAG_IME_DEEPSEEK_BASE_URL": "https://api.deepseek.com",
                "RAG_IME_DEEPSEEK_MODEL": "deepseek-v4-flash",
            }
        )
        requests: list[dict[str, object]] = []
        responses = [
            {
                "choices": [
                    {
                        "finish_reason": "length",
                        "message": {
                            "content": json.dumps(
                                {
                                    "sourceDecisions": [
                                        {
                                            "sourceRef": "S1",
                                            "disposition": "remember",
                                            "reasonCode": "durable_preference",
                                            "confidence": 0.95,
                                        }
                                    ]
                                }
                            )
                        },
                    }
                ]
            },
            {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {
                                    "sourceDecisions": [
                                        {
                                            "sourceRef": "S1",
                                            "disposition": "remember",
                                            "reasonCode": "durable_preference",
                                            "confidence": 0.95,
                                        },
                                        {
                                            "sourceRef": "S2",
                                            "disposition": "not_for_memory",
                                            "reasonCode": "input_noise_filler",
                                            "confidence": 0.98,
                                        },
                                    ],
                                    "memoryAtoms": [
                                        {
                                            "canonicalText": "用户要求记忆按需召回。",
                                            "summary": "按需召回",
                                            "kind": "durable_preference",
                                            "sourceEventIds": [11],
                                        }
                                    ],
                                },
                                ensure_ascii=False,
                            )
                        },
                    }
                ]
            },
        ]

        class FakeResponse:
            def __init__(self, payload):
                self.payload = payload

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")

        def fake_urlopen(request, timeout):
            requests.append(json.loads(request.data.decode("utf-8")))
            return FakeResponse(responses[len(requests) - 1])

        result = DeepSeekMemoryOrganizer(
            config,
            urlopen=fake_urlopen,
        ).curate_owner_memory(
            bundle={
                "inputs": [
                    {
                        "sourceRef": "S1",
                        "sourceKind": "user_final",
                        "trustClass": "user_claim",
                        "createdAtMs": 1,
                        "sourceEventIds": [11],
                        "text": "记忆只按当前问题召回。",
                    },
                    {
                        "sourceRef": "S2",
                        "sourceKind": "user_final",
                        "trustClass": "user_claim",
                        "createdAtMs": 2,
                        "sourceEventIds": [12],
                        "text": "嗯嗯那个这个",
                    },
                ],
                "existingMemoryAtoms": [
                    {
                        "atomId": f"atom:{index}",
                        "canonicalText": f"已有事实 {index}",
                    }
                    for index in range(40)
                ],
            },
            project="wisdom-weasel-rag-ime",
            owner_kind="user",
            owner_id="default",
        )

        self.assertEqual(len(requests), 2)
        self.assertEqual(result["modelDiagnostics"]["finishReason"], "length")
        self.assertEqual(result["modelDiagnostics"]["retry"]["finishReason"], "stop")
        self.assertIn(
            "owner_curation_recovered_with_compact_retry",
            result["warnings"],
        )
        self.assertEqual(len(result["memoryAtoms"]), 1)
        retry_bundle = json.loads(requests[1]["messages"][1]["content"])["bundle"]
        self.assertLessEqual(len(retry_bundle["existingMemoryAtoms"]), 8)

    def test_memory_organizer_repairs_missing_phrase_pinyin_with_bounded_second_request(self) -> None:
        config = load_deepseek_config(
            env={
                "DEEPSEEK_API_KEY": "secret",
                "RAG_IME_DEEPSEEK_BASE_URL": "https://api.deepseek.com",
                "RAG_IME_DEEPSEEK_MODEL": "deepseek-v4-flash",
            }
        )
        response_payloads = [
            {
                "schemaVersion": "rag-ime.memory-book-compile.v1",
                "dailyBooks": [],
                "topicBooks": [],
                "memoryAtoms": [],
                "tagEdges": [],
                "phraseCandidates": [
                    {
                        "text": "表情包",
                        "pinyin": "",
                        "tags": ["词库"],
                        "weight": 0.8,
                        "sourceEventIds": [1, 2],
                    },
                    {
                        "text": "输入法",
                        "pinyin": "shu ru fa",
                        "tags": ["项目"],
                        "weight": 0.7,
                        "sourceEventIds": [2],
                    },
                ],
                "warnings": [],
            },
            {"items": [{"text": "表情包", "pinyin": "biao qing bao"}]},
        ]
        requests = []

        class FakeResponse:
            def __init__(self, payload):
                self.payload = payload

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                body = {
                    "choices": [
                        {"message": {"content": json.dumps(self.payload, ensure_ascii=False)}}
                    ]
                }
                return json.dumps(body, ensure_ascii=False).encode("utf-8")

        def fake_urlopen(request, timeout):
            requests.append(json.loads(request.data.decode("utf-8")))
            return FakeResponse(response_payloads[len(requests) - 1])

        organizer = DeepSeekMemoryOrganizer(config, urlopen=fake_urlopen)
        payload = organizer.compile_memory_book(
            bundle={"recentEvents": [{"eventId": 1, "text": "使用表情包"}]},
            project="wisdom-weasel-rag-ime",
        )

        self.assertEqual(len(requests), 2)
        self.assertEqual(requests[1]["max_tokens"], 512)
        self.assertEqual(requests[1]["messages"][1]["content"], '{"project": "wisdom-weasel-rag-ime", "texts": ["表情包"]}')
        self.assertEqual(payload["phraseCandidates"][0]["pinyin"], "biao qing bao")
        self.assertEqual(payload["phraseCandidates"][1]["pinyin"], "shu ru fa")
        self.assertIn("phrase_pinyin_repaired:1", payload["warnings"])

    def test_memory_organizer_keeps_unrepaired_phrase_out_of_dsv4_lexicon_contract(self) -> None:
        config = load_deepseek_config(
            env={
                "DEEPSEEK_API_KEY": "secret",
                "RAG_IME_DEEPSEEK_BASE_URL": "https://api.deepseek.com",
                "RAG_IME_DEEPSEEK_MODEL": "deepseek-v4-flash",
            }
        )
        response_payloads = [
            {"phraseCandidates": [{"text": "未知词", "sourceEventIds": [1]}]},
            {"items": []},
        ]

        class FakeResponse:
            def __init__(self, payload):
                self.payload = payload

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                body = {"choices": [{"message": {"content": json.dumps(self.payload, ensure_ascii=False)}}]}
                return json.dumps(body, ensure_ascii=False).encode("utf-8")

        calls = 0

        def fake_urlopen(request, timeout):
            nonlocal calls
            response = FakeResponse(response_payloads[calls])
            calls += 1
            return response

        payload = DeepSeekMemoryOrganizer(config, urlopen=fake_urlopen).compile_memory_book(
            bundle={"recentEvents": [{"eventId": 1, "text": "未知词"}]},
            project="wisdom-weasel-rag-ime",
        )

        self.assertEqual(calls, 2)
        self.assertNotIn("pinyin", payload["phraseCandidates"][0])
        self.assertIn("phrase_pinyin_missing:1", payload["warnings"])

    def test_empty_primary_response_recovers_with_compact_governed_retry(self) -> None:
        config = load_deepseek_config(
            env={
                "DEEPSEEK_API_KEY": "secret",
                "RAG_IME_DEEPSEEK_BASE_URL": "https://api.deepseek.com",
                "RAG_IME_DEEPSEEK_MODEL": "deepseek-v4-flash",
            }
        )
        payloads = [
            {"semanticGroups": [], "semanticTags": [], "memoryAtoms": []},
            {
                "semanticGroups": [
                    {
                        "groupId": "group:input-method",
                        "title": "输入法",
                        "description": "输入法与个人记忆",
                        "sourceEventIds": [1, 2],
                    }
                ],
                "semanticTags": [
                    {
                        "name": "记忆清洗",
                        "description": "模型清洗输入历史后再建立索引",
                        "semanticGroupIds": ["group:input-method"],
                        "sourceEventIds": [1, 2],
                    }
                ],
                "memoryAtoms": [
                    {
                        "canonicalText": "原始输入需经模型清洗后再索引。",
                        "sourceEventIds": [1, 2],
                        "semanticGroupIds": ["group:input-method"],
                    }
                ],
            },
        ]
        requests = []

        class FakeResponse:
            def __init__(self, payload):
                self.payload = payload

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return json.dumps(
                    {
                        "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(self.payload, ensure_ascii=False)}}],
                        "usage": {"prompt_tokens": 100, "completion_tokens": 80},
                    },
                    ensure_ascii=False,
                ).encode("utf-8")

        def fake_urlopen(request, timeout):
            requests.append(json.loads(request.data.decode("utf-8")))
            return FakeResponse(payloads[len(requests) - 1])

        result = DeepSeekMemoryOrganizer(config, urlopen=fake_urlopen).compile_memory_book(
            bundle={
                "project": "wisdom-weasel-rag-ime",
                "recentEvents": [
                    {"eventId": 1, "sourceEventIds": [1], "text": "输入法需要整理记忆"},
                    {"eventId": 2, "sourceEventIds": [2], "text": "历史要清洗后再索引"},
                ],
            },
            project="wisdom-weasel-rag-ime",
        )

        self.assertEqual(len(requests), 2)
        self.assertEqual(result["semanticGroups"][0]["groupId"], "group:input-method")
        self.assertIn("organizer_recovered_with_compact_retry", result["warnings"])
        self.assertEqual(result["modelDiagnostics"]["retry"]["finishReason"], "stop")
        self.assertLess(result["modelBundleStats"]["chars"], 2_000)


if __name__ == "__main__":
    unittest.main()
