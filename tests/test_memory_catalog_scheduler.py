from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from rag_ime.memory_catalog_scheduler import (
    CATALOG_CONSOLIDATION_LEASE_DURATION_MS,
    CATALOG_CONSOLIDATION_RETRY_BASE_MS,
    CATALOG_CONSOLIDATION_RETRY_MAX_MS,
    DEFAULT_CATALOG_CONSOLIDATION_CADENCE_DAYS,
    MemoryCatalogConsolidationScheduler,
)


class _Clock:
    def __init__(self, value: int = 1_000) -> None:
        self.value = value

    def __call__(self) -> int:
        return self.value


class MemoryCatalogConsolidationSchedulerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(
            prefix="rag-ime-memory-catalog-scheduler-"
        )
        self.db_path = Path(self.temporary.name) / "rag-ime.sqlite"
        self.clock = _Clock()
        self.scheduler = MemoryCatalogConsolidationScheduler(
            self.db_path,
            clock_ms=self.clock,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_first_run_is_due_and_admission_is_append_only(self) -> None:
        initial = self.scheduler.status("sample-project")

        self.assertEqual(initial["state"], "never")
        self.assertTrue(initial["due"])
        self.assertEqual(initial["dueReason"], "first_run")

        admitted = self._admit()
        self.assertEqual(admitted["reason"], "first_run")
        self.assertEqual(admitted["status"]["attemptCount"], 1)
        self.assertIsInstance(admitted["admissionToken"], str)
        self.assertTrue(admitted["admissionToken"])

        duplicate = self.scheduler.admit("sample-project")
        self.assertFalse(duplicate["admitted"])
        self.assertEqual(duplicate["reason"], "already_running")
        self.assertNotIn("admissionToken", duplicate)
        self.assertEqual(self._receipt_count("sample-project"), 1)

    def test_default_lease_covers_the_longest_managed_maintenance_timeout(self) -> None:
        self.assertEqual(
            CATALOG_CONSOLIDATION_LEASE_DURATION_MS,
            3 * 60 * 60 * 1_000,
        )
        admitted = self._admit()
        self.assertEqual(
            self.scheduler.status("sample-project")["leaseExpiresAtMs"],
            self.clock.value + 3 * 60 * 60 * 1_000,
        )
        self.assertTrue(admitted["admissionToken"])

    def test_restart_recovers_a_running_receipt_only_after_lease_expiry(self) -> None:
        admitted = self._admit()

        restarted = MemoryCatalogConsolidationScheduler(
            self.db_path,
            clock_ms=self.clock,
        )
        persisted = restarted.status("sample-project")

        self.assertEqual(persisted["state"], "running")
        self.assertFalse(persisted["due"])
        self.assertEqual(persisted["dueReason"], "running")
        self.assertEqual(persisted["attemptCount"], 1)

        blocked = restarted.admit("sample-project")
        self.assertFalse(blocked["admitted"])
        self.assertEqual(blocked["reason"], "already_running")

        self.clock.value += CATALOG_CONSOLIDATION_LEASE_DURATION_MS
        retry = restarted.admit("sample-project")
        self.assertTrue(retry["admitted"])
        self.assertEqual(retry["reason"], "lease_expired")
        self.assertEqual(retry["status"]["attemptCount"], 2)
        with self.assertRaises(RuntimeError):
            restarted.complete(
                "sample-project",
                catalog_digest="digest-v1",
                ok=True,
                admission_token=admitted["admissionToken"],
            )

    def test_completed_receipt_is_due_at_the_seven_day_boundary(self) -> None:
        admitted = self._admit()
        self.scheduler.record_digest(
            "sample-project",
            "digest-v1",
            admission_token=admitted["admissionToken"],
        )
        completed = self._complete(admitted, catalog_digest="digest-v1", ok=True, curation_run_id="memory-book-run-1", result={"ok": True, "mergeCount": 0})

        cadence_ms = DEFAULT_CATALOG_CONSOLIDATION_CADENCE_DAYS * 24 * 60 * 60 * 1_000
        self.assertEqual(completed["nextDueAtMs"], self.clock.value + cadence_ms)
        self.assertEqual(completed["lastSuccessfulCatalogDigest"], "digest-v1")
        self.assertEqual(completed["lastSuccessfulCatalogCommittedAtMs"], self.clock.value)
        self.clock.value += cadence_ms - 1
        before_boundary = self.scheduler.status("sample-project")
        self.assertFalse(before_boundary["due"])
        self.assertEqual(before_boundary["dueReason"], "not_due")

        self.clock.value += 1
        at_boundary = self.scheduler.status("sample-project")
        self.assertTrue(at_boundary["due"])
        self.assertEqual(at_boundary["dueReason"], "scheduled")
        self.assertEqual(at_boundary["catalogDigest"], "digest-v1")
        self.assertEqual(at_boundary["curationRunId"], "memory-book-run-1")


    def test_completed_admission_recomputes_due_when_cadence_shortens(self) -> None:
        admitted = self._admit()
        self._complete(
            admitted,
            catalog_digest="digest-v1",
            ok=True,
            cadence_days=7,
        )

        day_ms = 24 * 60 * 60 * 1_000
        self.clock.value += 2 * day_ms
        shortened = self.scheduler.admit(
            "sample-project",
            cadence_days=1,
        )

        self.assertTrue(shortened["admitted"])
        self.assertEqual(shortened["reason"], "scheduled")

    def test_completed_admission_recomputes_due_when_cadence_lengthens(self) -> None:
        admitted = self._admit()
        completed = self._complete(
            admitted,
            catalog_digest="digest-v1",
            ok=True,
            cadence_days=1,
        )

        day_ms = 24 * 60 * 60 * 1_000
        self.clock.value += 2 * day_ms
        lengthened = self.scheduler.admit(
            "sample-project",
            cadence_days=7,
        )

        self.assertFalse(lengthened["admitted"])
        self.assertFalse(lengthened["due"])
        self.assertEqual(lengthened["reason"], "not_due")
        self.assertEqual(
            lengthened["status"]["nextDueAtMs"],
            int(completed["lastSuccessfulCatalogCommittedAtMs"]) + 7 * day_ms,
        )

    def test_cadence_changes_do_not_override_a_live_lease(self) -> None:
        admitted = self._admit(cadence_days=7)

        blocked = self.scheduler.admit(
            "sample-project",
            cadence_days=1,
        )

        self.assertFalse(blocked["admitted"])
        self.assertFalse(blocked["due"])
        self.assertEqual(blocked["reason"], "already_running")
        self.assertEqual(blocked["status"]["state"], "running")
        self.assertNotIn("admissionToken", blocked)
        self.assertTrue(admitted["admissionToken"])

    def test_cadence_changes_do_not_override_failure_retry_deadline(self) -> None:
        admitted = self._admit()
        failed = self._complete(
            admitted,
            catalog_digest="digest-v1",
            ok=False,
            error="provider unavailable",
            cadence_days=7,
        )

        self.clock.value += 1
        blocked = self.scheduler.admit(
            "sample-project",
            cadence_days=1,
        )
        self.assertFalse(blocked["admitted"])
        self.assertFalse(blocked["due"])
        self.assertEqual(blocked["reason"], "not_due")
        self.assertEqual(
            blocked["status"]["nextDueAtMs"],
            failed["nextDueAtMs"],
        )

        self.clock.value = int(failed["nextDueAtMs"])
        retry = self.scheduler.admit(
            "sample-project",
            cadence_days=365,
        )
        self.assertTrue(retry["admitted"])
        self.assertEqual(retry["reason"], "retry_backoff")

    def test_failure_backoff_is_exponential_and_bounded(self) -> None:
        admitted = self._admit()
        first = self._complete(
            admitted,
            catalog_digest="digest-v1",
            result={"ok": False},
            ok=False,
            error="provider unavailable",
        )
        self.assertEqual(first["retryCount"], 1)
        self.assertEqual(
            first["nextDueAtMs"],
            self.clock.value + CATALOG_CONSOLIDATION_RETRY_BASE_MS,
        )

        self.clock.value = int(first["nextDueAtMs"])
        admitted = self._admit()
        second = self._complete(
            admitted,
            catalog_digest="digest-v1",
            result={"ok": False},
            ok=False,
            error="provider unavailable",
        )
        self.assertEqual(second["retryCount"], 2)
        self.assertEqual(
            second["nextDueAtMs"],
            self.clock.value + 2 * CATALOG_CONSOLIDATION_RETRY_BASE_MS,
        )

        for _ in range(3, 10):
            self.clock.value = int(self.scheduler.status("sample-project")["nextDueAtMs"])
            admitted = self._admit()
            self._complete(
                admitted,
                catalog_digest="digest-v1",
                result={"ok": False},
                ok=False,
                error="provider unavailable",
            )
        final = self.scheduler.status("sample-project")
        self.assertEqual(final["retryCount"], 9)
        self.assertLessEqual(
            int(final["nextDueAtMs"]) - self.clock.value,
            CATALOG_CONSOLIDATION_RETRY_MAX_MS,
        )
        self.assertEqual(final["error"], "provider unavailable")

    def test_disabled_scheduling_is_read_only_but_manual_force_bypasses_cadence(self) -> None:
        disabled = self.scheduler.admit(
            "sample-project",
            enabled=False,
            manual=True,
        )
        self.assertFalse(disabled["admitted"])
        self.assertTrue(disabled["skipped"])
        self.assertEqual(disabled["reason"], "catalog_consolidation_disabled")
        self.assertNotIn("admissionToken", disabled)
        self.assertEqual(self._receipt_count("sample-project"), 0)

        admitted = self._admit()
        self._complete(admitted, catalog_digest="digest-v1", result={"ok": True}, ok=True)
        self.clock.value += 1
        forced = self.scheduler.admit("sample-project", manual=True)
        self.assertTrue(forced["admitted"])
        self.assertEqual(forced["reason"], "manual")

    def test_completion_preserves_last_successful_digest_after_failed_attempt(self) -> None:
        admitted = self._admit()
        self._complete(admitted, catalog_digest="digest-v1", result={"ok": True}, ok=True)
        self.clock.value = int(self.scheduler.status("sample-project")["nextDueAtMs"])
        admitted = self._admit()
        self.scheduler.record_digest(
            "sample-project",
            "digest-v2",
            admission_token=admitted["admissionToken"],
        )
        failed = self._complete(
            admitted,
            catalog_digest="digest-v2",
            result={"ok": False},
            ok=False,
            error="catalog snapshot failed",
        )

        self.assertEqual(failed["state"], "failed")
        self.assertEqual(failed["catalogDigest"], "digest-v1")
        self.assertEqual(failed["lastSuccessfulCatalogDigest"], "digest-v1")
        self.assertEqual(failed["error"], "catalog snapshot failed")

    def test_wrong_or_stale_tokens_fail_closed_without_mutating_receipts(self) -> None:
        admitted = self._admit()
        token = admitted["admissionToken"]
        before = self._receipt_count("sample-project")
        with self.assertRaises(RuntimeError):
            self.scheduler.record_digest(
                "sample-project",
                "digest-v1",
                admission_token="wrong-token",
            )
        with self.assertRaises(RuntimeError):
            self.scheduler.complete(
                "sample-project",
                catalog_digest="digest-v1",
                ok=True,
                admission_token="wrong-token",
            )
        self.assertEqual(self._receipt_count("sample-project"), before)

        self.clock.value += CATALOG_CONSOLIDATION_LEASE_DURATION_MS
        replacement = self.scheduler.admit("sample-project")
        self.assertTrue(replacement["admitted"])
        with self.assertRaises(RuntimeError):
            self.scheduler.fail(
                "sample-project",
                admission_token=token,
                error="stale worker",
            )
        self.assertEqual(self.scheduler.status("sample-project")["state"], "running")

    def test_digest_and_curation_metadata_are_persisted_in_the_latest_receipt(self) -> None:
        admitted = self._admit()
        self.scheduler.record_digest(
            "sample-project",
            "digest-v2",
            admission_token=admitted["admissionToken"],
        )
        completed = self._complete(
            admitted,
            catalog_digest="digest-v2",
            curation_run_id="memory-book-run-2",
            result={"ok": True, "curation": {"storedRun": "memory-book-run-2"}},
            ok=True,
        )

        self.assertEqual(completed["catalogDigest"], "digest-v2")
        self.assertEqual(completed["curationRunId"], "memory-book-run-2")
        self.assertEqual(completed["result"]["ok"], True)
        self.assertEqual(self._receipt_count("sample-project"), 3)

    def _admit(
        self,
        project: str = "sample-project",
        *,
        cadence_days: int = DEFAULT_CATALOG_CONSOLIDATION_CADENCE_DAYS,
    ) -> dict[str, object]:
        admitted = self.scheduler.admit(project, cadence_days=cadence_days)
        self.assertTrue(admitted["admitted"], admitted)
        return admitted

    def _complete(
        self,
        admitted: dict[str, object],
        *,
        catalog_digest: str,
        ok: bool,
        result: dict[str, object] | None = None,
        curation_run_id: str = "",
        error: str = "",
        cadence_days: int = DEFAULT_CATALOG_CONSOLIDATION_CADENCE_DAYS,
    ) -> dict[str, object]:
        return self.scheduler.complete(
            "sample-project",
            catalog_digest=catalog_digest,
            curation_run_id=curation_run_id,
            result=result,
            ok=ok,
            error=error,
            cadence_days=cadence_days,
            admission_token=str(admitted["admissionToken"]),
        )

    def _receipt_count(self, project: str) -> int:
        with sqlite3.connect(self.db_path) as conn:
            return int(
                conn.execute(
                    "SELECT COUNT(*) FROM memory_catalog_consolidation_receipts WHERE project = ?",
                    (project,),
                ).fetchone()[0]
            )


if __name__ == "__main__":
    unittest.main()
