from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rag_ime.deepseek_config import load_deepseek_config
from rag_ime.deepseek_memory_organizer import DeepSeekMemoryOrganizer


class DeepSeekMemoryOrganizerTests(unittest.TestCase):
    def test_deepseek_config_reads_official_and_x1api_env_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / "deepseek.env"
            env_path.write_text(
                "\n".join(
                    [
                        "DEEPSEEK_API_KEY=secret",
                        "RAG_IME_DEEPSEEK_BASE_URL=https://api.deepseek.com",
                        "RAG_IME_DEEPSEEK_MODEL=deepseek-v4-flash",
                        "RAG_IME_DEEPSEEK_JSON=1",
                    ]
                ),
                encoding="utf-8",
            )

            config = load_deepseek_config(env_path)

        self.assertEqual(config.api_base_url, "https://api.deepseek.com/v1")
        self.assertEqual(config.api_key, "secret")
        self.assertEqual(config.model, "deepseek-v4-flash")
        self.assertTrue(config.json_mode)

    def test_memory_organizer_builds_json_chat_completion_request(self) -> None:
        config = load_deepseek_config(
            env={
                "DEEPSEEK_API_KEY": "secret",
                "RAG_IME_DEEPSEEK_BASE_URL": "https://api.deepseek.com",
                "RAG_IME_DEEPSEEK_MODEL": "deepseek-v4-flash",
            }
        )
        organizer = DeepSeekMemoryOrganizer(config)
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

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            payload = organizer.compile_memory_book(
                bundle={"recentEvents": [{"eventId": 1, "text": "RAG 输入法"}]},
                project="wisdom-weasel-rag-ime",
            )

        self.assertEqual(payload["schemaVersion"], "rag-ime.memory-book-compile.v1")
        self.assertEqual(payload["provider"], "deepseek")
        self.assertEqual(payload["model"], "deepseek-v4-flash")
        self.assertEqual(captured["url"], "https://api.deepseek.com/v1/chat/completions")
        self.assertEqual(captured["authorization"], "Bearer secret")
        self.assertEqual(captured["userAgent"], "rag-ime/1.0 curl-compatible")
        self.assertEqual(captured["payload"]["response_format"], {"type": "json_object"})
        self.assertFalse(captured["payload"]["stream"])


if __name__ == "__main__":
    unittest.main()
