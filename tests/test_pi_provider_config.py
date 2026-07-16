from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from rag_ime.pi_provider_config import load_pi_provider_config


class PiProviderConfigTest(unittest.TestCase):
    def test_imported_openai_gateway_declares_cache_key_and_affinity_capabilities(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "providers.json"
            path.write_text(
                json.dumps(
                    {
                        "provider": {
                            "openai": {
                                "options": {
                                    "baseURL": "https://gateway.example/v1",
                                    "apiKey": "fixture-secret",
                                },
                                "models": {"gpt-test": {"name": "GPT Test"}},
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            bundle = load_pi_provider_config(path)

        compat = bundle.providers["gpt"]["compat"]
        self.assertTrue(compat["supportsPromptCacheKey"])
        self.assertTrue(compat["sendSessionAffinityHeaders"])
        self.assertEqual(compat["sessionAffinityFormat"], "openai-nosession")


if __name__ == "__main__":
    unittest.main()
