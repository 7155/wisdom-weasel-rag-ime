from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from rag_ime.pi_provider_config import load_pi_provider_config


class PiProviderConfigTest(unittest.TestCase):
    def test_imported_openai_gateway_disables_unverified_native_tool_search(self) -> None:
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

        provider = bundle.providers["gpt"]
        self.assertEqual(provider["modelCatalogProvider"], "openai")
        self.assertEqual(provider["models"], [{"id": "gpt-test"}])
        self.assertNotIn("api", provider)
        self.assertEqual(provider["compat"], {"supportsToolSearch": False})


if __name__ == "__main__":
    unittest.main()
