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
)


class DeepSeekMemoryOrganizerTests(unittest.TestCase):
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
        self.assertEqual(captured["payload"]["thinking"], {"type": "disabled"})
        self.assertNotIn("reasoning_effort", captured["payload"])
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
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            return FakeResponse()

        payload = DeepSeekMemoryOrganizer(config, urlopen=fake_urlopen).compile_memory_book(
            bundle={"recentEvents": [{"eventId": 1, "text": "输入法记忆整理"}]},
            project="wisdom-weasel-rag-ime",
        )

        self.assertEqual(payload["instruction"], DEFAULT_MEMORY_ORGANIZATION_INSTRUCTION)
        request_payload = captured["payload"]
        self.assertIn(DEFAULT_MEMORY_ORGANIZATION_INSTRUCTION, request_payload["messages"][1]["content"])
        self.assertIn("不直接写入正式记忆", DEFAULT_MEMORY_ORGANIZATION_INSTRUCTION)

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
