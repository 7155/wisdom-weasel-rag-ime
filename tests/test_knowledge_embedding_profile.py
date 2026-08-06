from __future__ import annotations

import unittest

from rag_ime.knowledge_embedding_profile import (
    embedding_environment_from_settings,
    normalize_knowledge_embedding_profile,
    probe_knowledge_embedding_profile,
)


class KnowledgeEmbeddingProfileTests(unittest.TestCase):
    def test_explicit_profile_overrides_environment_and_probes_without_secrets(self) -> None:
        settings = {
            "knowledgeLibrary": {
                "embedding": {
                    "provider": "local-hash",
                    "model": "deterministic-term-vector-v1",
                    "dimensions": 48,
                    "baseUrl": "",
                    "secretReference": "",
                    "queryPrefix": "",
                    "documentPrefix": "",
                    "denseBackend": "sqlite-exact",
                }
            }
        }
        source_environment = {
            "RAG_IME_EMBEDDING_PROVIDER": "none",
            "RAG_IME_EMBEDDING_API_KEY": "must-not-leak",
            "RAG_IME_KNOWLEDGE_DENSE_BACKEND": "usearch",
        }

        profile = normalize_knowledge_embedding_profile(
            settings,
            environ=source_environment,
        )
        worker_environment = embedding_environment_from_settings(
            settings,
            environ=source_environment,
        )
        probe = probe_knowledge_embedding_profile(
            settings,
            environ=source_environment,
        )

        self.assertEqual("settings", profile["source"])
        self.assertEqual("local-hash", profile["provider"])
        self.assertEqual(48, profile["dimensions"])
        self.assertEqual("local-hash", worker_environment["RAG_IME_EMBEDDING_PROVIDER"])
        self.assertEqual("48", worker_environment["RAG_IME_EMBEDDING_DIMENSIONS"])
        self.assertEqual("sqlite-exact", worker_environment["RAG_IME_KNOWLEDGE_DENSE_BACKEND"])
        self.assertNotIn("RAG_IME_EMBEDDING_API_KEY", worker_environment)
        self.assertTrue(probe["ready"])
        self.assertEqual(48, probe["dimensions"])
        self.assertFalse(probe["secretsVisible"])
        self.assertNotIn("must-not-leak", str(profile))
        self.assertNotIn("must-not-leak", str(probe))

    def test_remote_profile_resolves_only_the_named_secret_at_worker_boundary(self) -> None:
        settings = {
            "knowledgeLibrary": {
                "embedding": {
                    "provider": "openai-compatible",
                    "model": "bge-small-zh",
                    "dimensions": 3,
                    "baseUrl": "https://embedding.example.test",
                    "secretReference": "PAW_EMBEDDING_API_KEY",
                    "queryPrefix": "query: ",
                    "documentPrefix": "passage: ",
                    "denseBackend": "sqlite-exact",
                }
            }
        }
        environment = {
            "PAW_EMBEDDING_API_KEY": "remote-secret",
            "UNRELATED_SECRET": "not-authorized",
        }

        public = normalize_knowledge_embedding_profile(settings, environ=environment)
        worker = embedding_environment_from_settings(settings, environ=environment)

        self.assertEqual("PAW_EMBEDDING_API_KEY", public["secretReference"])
        self.assertTrue(public["secretAvailable"])
        self.assertEqual("remote-secret", worker["RAG_IME_EMBEDDING_API_KEY"])
        self.assertNotIn("UNRELATED_SECRET", worker)
        self.assertNotIn("remote-secret", str(public))

    def test_environment_profile_remains_the_backward_compatible_default(self) -> None:
        environment = {
            "RAG_IME_EMBEDDING_PROVIDER": "local-hash",
            "RAG_IME_EMBEDDING_DIMENSIONS": "24",
            "RAG_IME_KNOWLEDGE_DENSE_BACKEND": "sqlite-exact",
        }

        profile = normalize_knowledge_embedding_profile({}, environ=environment)
        worker = embedding_environment_from_settings({}, environ=environment)

        self.assertEqual("environment", profile["source"])
        self.assertEqual("local-hash", profile["provider"])
        self.assertEqual(24, profile["dimensions"])
        self.assertEqual(environment, worker)

    def test_lexical_only_profile_has_a_probe_receipt_without_vectors(self) -> None:
        settings = {
            "knowledgeLibrary": {
                "embedding": {
                    "provider": "none",
                    "model": "",
                    "dimensions": 0,
                    "baseUrl": "",
                    "secretReference": "",
                    "queryPrefix": "",
                    "documentPrefix": "",
                    "denseBackend": "sqlite-exact",
                }
            }
        }

        probe = probe_knowledge_embedding_profile(settings, environ={})

        self.assertTrue(probe["ready"])
        self.assertEqual("none", probe["provider"])
        self.assertEqual(0, probe["dimensions"])
        self.assertFalse(probe["semantic"])
        self.assertFalse(probe["secretsVisible"])

    def test_dimensions_reject_non_scalar_values_as_a_public_validation_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "dimensions must be an integer"):
            normalize_knowledge_embedding_profile(
                {
                    "knowledgeLibrary": {
                        "embedding": {
                            "provider": "none",
                            "dimensions": [],
                        }
                    }
                },
                environ={},
            )


if __name__ == "__main__":
    unittest.main()
