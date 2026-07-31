from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rag_ime.lexicon_organization import (
    MAX_CANDIDATES_PER_RUN,
    lexicon_organization_status,
    run_due_lexicon_organization,
)
from rag_ime.settings_store import ManagementSettingsStore


class LexiconOrganizationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="rag-ime-lexicon-organization-")
        self.db_path = Path(self.temporary.name) / "rag-ime.sqlite"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_cadence_and_receipt_survive_a_new_status_reader(self) -> None:
        observed: list[dict[str, object]] = []

        def review(*_args: object, **kwargs: object) -> dict[str, object]:
            observed.append(dict(kwargs))
            return {
                "ok": True,
                "entryCount": 3,
                "filteredEntryCount": 2,
                "reviewToken": "local-review-token",
            }

        report = run_due_lexicon_organization(
            self.db_path,
            project="project-a",
            current_ms=1_000_000,
            review=review,
        )
        restored = lexicon_organization_status(
            self.db_path,
            project="project-a",
            current_ms=1_000_001,
        )

        self.assertTrue(report["ok"])
        self.assertEqual(observed[0]["limit"], MAX_CANDIDATES_PER_RUN)
        self.assertIsNone(observed[0]["rime_user_dir"])
        self.assertEqual(restored["owner"], "maintenance_poll")
        self.assertEqual(restored["decoderOwner"], "rime")
        self.assertEqual(restored["lastRun"]["candidateCount"], 3)
        self.assertGreater(restored["nextRunAtMs"], restored["lastRunAtMs"])
        self.assertEqual(restored["runsPerDay"], 2)
        self.assertEqual(restored["intervalMs"], 43_200_000)
        self.assertEqual(
            restored["nextRunAtMs"],
            restored["lastRunAtMs"] + restored["intervalMs"],
        )
        self.assertNotIn("local-review-token", str(restored))
        self.assertFalse(restored["privacy"]["storesRawCandidateText"])

    def test_persisted_settings_disable_and_change_the_single_cadence(self) -> None:
        store = ManagementSettingsStore(self.db_path)
        store.update_settings(
            {
                "lexiconOrganization.enabled": False,
                "lexiconOrganization.runsPerDay": 4,
            }
        )

        disabled = run_due_lexicon_organization(
            self.db_path,
            project="project-a",
            current_ms=2_000_000,
            review=lambda *_args, **_kwargs: self.fail("disabled cadence must not read candidates"),
        )

        self.assertFalse(disabled["enabled"])
        self.assertEqual(disabled["runsPerDay"], 4)
        self.assertEqual(disabled["intervalMs"], 21_600_000)
        self.assertIsNone(disabled["nextRunAtMs"])
        self.assertEqual(disabled["skipReason"], "disabled")

    def test_real_failure_is_persisted_with_private_paths_and_secrets_redacted(self) -> None:
        def fail(*_args: object, **_kwargs: object) -> dict[str, object]:
            raise OSError("/Users/private/Documents failed api_key=top-secret")

        report = run_due_lexicon_organization(
            self.db_path,
            project="project-a",
            current_ms=3_000_000,
            review=fail,
        )
        restored = lexicon_organization_status(
            self.db_path,
            project="project-a",
            current_ms=3_000_001,
        )

        self.assertFalse(report["ok"])
        self.assertEqual(restored["lastRun"]["status"], "failed")
        self.assertEqual(restored["lastRun"]["errorCode"], "o_s_error")
        self.assertIn("[LOCAL_PATH]", restored["lastRun"]["error"])
        self.assertIn("[REDACTED_SECRET]", restored["lastRun"]["error"])
        self.assertNotIn("top-secret", str(restored))


if __name__ == "__main__":
    unittest.main()
