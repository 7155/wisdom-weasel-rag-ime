from __future__ import annotations

import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path

from rag_ime.knowledge_search_use_eval import KnowledgeEvalError, KnowledgeSearchUseEvalStore


class KnowledgeSearchUseEvalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="knowledge-eval-")
        self.db = Path(self.tmp.name) / "eval.sqlite"
        self.store = KnowledgeSearchUseEvalStore(self.db, signer_secrets={"fixture-signer": b"fixture-secret"}, evaluator_secrets={"eval-runner": b"eval-secret"})
        self.assertEqual(self.store.initialize(), 90)
        self._seed_binding_and_receipts()
        self.dataset = self.store.sign_dataset(dataset_id="dataset:1", dataset_version=1, signer_id="fixture-signer", fixtures=self._fixtures(), thresholds=self._thresholds(), created_at_ms=1, expires_at_ms=1000, signer_secret=b"fixture-secret")
        self.store.register_dataset(self.dataset)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_signed_stratified_eval_reports_pass_without_activation_side_effect(self) -> None:
        report, created = self.store.record_eval(eval_run_id="knowledge-eval:pass", dataset_id="dataset:1", room_binding_id="binding:eval", traces=self._traces(), evaluator_id="eval-runner", evaluator_secret=b"eval-secret", created_at_ms=10)
        self.assertTrue(created); self.assertEqual(report["status"], "passed"); self.assertTrue(report["reportOnly"])
        self.assertEqual(report["metrics"]["authorizationLeakageCount"], 0)
        self.assertEqual(report["metrics"]["usedCitationRate"], 1.0)
        self.assertEqual(set(key.split(":", 1)[0] for key in report["strataMetrics"]), {"owner", "room", "session"})
        with sqlite3.connect(self.db) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM room_v2_guard_active_pointers").fetchone()[0], 0)

    def test_failed_metrics_are_signed_report_only_and_cannot_hide_leakage(self) -> None:
        traces = self._traces(); traces[0] = {**traces[0], "retrievedRefs": ["claim:0", "forbidden:0", "secret:0"], "readRefs": [], "usedCitationRefs": []}
        report, _ = self.store.record_eval(eval_run_id="knowledge-eval:failed", dataset_id="dataset:1", room_binding_id="binding:eval", traces=traces, evaluator_id="eval-runner", evaluator_secret=b"eval-secret", created_at_ms=10)
        self.assertEqual(report["status"], "failed")
        self.assertIn("authorization_leakage", report["failureReasons"])
        self.assertIn("citation_use_gap", report["failureReasons"])
        self.assertIn("secret_quarantine_gap", report["failureReasons"])
        self.assertTrue(report["reportOnly"])

    def test_duplicate_query_gaming_tamper_expiry_and_no_room_fail_closed(self) -> None:
        fixtures = self._fixtures(); fixtures[1] = {**fixtures[1], "query": fixtures[0]["query"]}
        duplicate = self.store.sign_dataset(dataset_id="dataset:duplicate", dataset_version=1, signer_id="fixture-signer", fixtures=fixtures, thresholds=self._thresholds(), created_at_ms=1, expires_at_ms=100, signer_secret=b"fixture-secret")
        with self.assertRaisesRegex(KnowledgeEvalError, "duplicate"):
            self.store.register_dataset(duplicate)
        tampered = {**self.dataset, "expiresAtMs": 2000}
        with self.assertRaisesRegex(KnowledgeEvalError, "signature"):
            self.store.register_dataset(tampered)
        with self.assertRaisesRegex(KnowledgeEvalError, "expired"):
            self.store.record_eval(eval_run_id="knowledge-eval:expired", dataset_id="dataset:1", room_binding_id="binding:eval", traces=self._traces(), evaluator_id="eval-runner", evaluator_secret=b"eval-secret", created_at_ms=1001)
        before = self._run_count()
        result, created = self.store.record_eval(eval_run_id="ordinary", dataset_id="dataset:1", room_binding_id=None, traces=[], evaluator_id="eval-runner", evaluator_secret=b"eval-secret", created_at_ms=10)
        self.assertIsNone(result); self.assertFalse(created); self.assertEqual(self._run_count(), before)
        with sqlite3.connect(self.db) as conn, self.assertRaisesRegex(sqlite3.IntegrityError, "immutable"):
            conn.execute("UPDATE room_v2_knowledge_eval_fixture_datasets SET expires_at_ms=2000 WHERE dataset_id='dataset:1'")

    def test_missing_or_replayed_fixture_trace_and_foreign_receipt_are_rejected(self) -> None:
        with self.assertRaisesRegex(KnowledgeEvalError, "missing, duplicated"):
            self.store.record_eval(eval_run_id="missing", dataset_id="dataset:1", room_binding_id="binding:eval", traces=self._traces()[:-1], evaluator_id="eval-runner", evaluator_secret=b"eval-secret", created_at_ms=10)
        traces = self._traces(); traces[1] = {**traces[1], "fixtureId": traces[0]["fixtureId"]}
        with self.assertRaisesRegex(KnowledgeEvalError, "missing, duplicated"):
            self.store.record_eval(eval_run_id="duplicate", dataset_id="dataset:1", room_binding_id="binding:eval", traces=traces, evaluator_id="eval-runner", evaluator_secret=b"eval-secret", created_at_ms=10)
        traces = self._traces(); traces[0] = {**traces[0], "retrievalReceiptId": "receipt:foreign"}
        with self.assertRaisesRegex(KnowledgeEvalError, "foreign"):
            self.store.record_eval(eval_run_id="foreign", dataset_id="dataset:1", room_binding_id="binding:eval", traces=traces, evaluator_id="eval-runner", evaluator_secret=b"eval-secret", created_at_ms=10)

    def _seed_binding_and_receipts(self) -> None:
        h = "a" * 64
        with sqlite3.connect(self.db) as conn:
            conn.execute("PRAGMA foreign_keys=OFF")
            conn.execute("INSERT INTO room_v2_capability_manifests VALUES ('manifest:eval','binding:eval','room:1','root:1','task','dispatch',0,'1',1,?,'{}',1)", (h,))
            for index in range(5):
                conn.execute("INSERT INTO room_v2_knowledge_retrieval_receipts VALUES (?,?,?,?,?,?,?,1)", (f"retrieval:{index}", "binding:eval", "auth:1", h, '{}', '[]', '{}'))
            conn.execute("INSERT INTO room_v2_knowledge_retrieval_receipts VALUES ('receipt:foreign','other-binding','auth:1',?,'{}','[]','{}',1)", (h,))

    @staticmethod
    def _fixtures():
        fixtures = []
        strata = (("owner", "owner:a"), ("owner", "owner:b"), ("room", "room:a"), ("room", "room:b"), ("session", "session:a"), ("session", "session:b"))
        for index, (kind, identity) in enumerate(strata):
            abstain = index == 5
            fixtures.append({"fixtureId": f"fixture:{index}", "query": f"unique query {index}", "stratumKind": kind, "stratumId": identity, "expectedRetrievalRefs": [] if abstain else [f"claim:{index}"], "expectedReadRefs": [] if abstain else [f"claim:{index}"], "expectedUsedCitationRefs": [] if abstain else [f"claim:{index}"], "forbiddenRefs": [f"forbidden:{index}"], "expectAbstain": abstain, "expectedContradictionRefs": ["contradiction:0"] if index == 0 else [], "requireFreshness": not abstain, "secretRefs": ["secret:0"] if index == 0 else []})
        return fixtures

    def _traces(self):
        traces = []
        for index, fixture in enumerate(self._fixtures()):
            abstain = fixture["expectAbstain"]; claim = [] if abstain else [f"claim:{index}"]
            traces.append({"fixtureId": fixture["fixtureId"], "queryHash": hashlib.sha256(fixture["query"].encode()).hexdigest(), "retrievalReceiptId": "" if abstain else f"retrieval:{index}", "retrievedRefs": claim, "readRefs": claim, "usedCitationRefs": claim, "abstained": abstain, "surfacedContradictionRefs": fixture["expectedContradictionRefs"], "freshnessPassed": not abstain, "quarantinedSecretRefs": fixture["secretRefs"], "latencyMs": 50 + index, "bytesRead": 100})
        return traces

    @staticmethod
    def _thresholds():
        return {"maxAuthorizationLeakageCount": 0, "minExpectedRetrievalRate": 1, "minExpectedReadRate": 1, "minReadAfterRetrievalRate": 1, "minUsedCitationRate": 1, "minAbstentionAccuracy": 1, "minContradictionSurfacingRate": 1, "minFreshnessPassRate": 1, "minSecretQuarantineRate": 1, "maxP95LatencyMs": 100, "maxTotalBytes": 1000}

    def _run_count(self):
        with sqlite3.connect(self.db) as conn:
            return conn.execute("SELECT COUNT(*) FROM room_v2_knowledge_search_use_eval_runs").fetchone()[0]


if __name__ == "__main__": unittest.main()
