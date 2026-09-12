from __future__ import annotations

import io
import json
import os
import sqlite3
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, redirect_stderr
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from rag_ime.memory_lifecycle.cli import main, read_json, write_private
from rag_ime.memory_lifecycle.common import LifecycleError, canonical_json, digest, text_digest, transaction
from rag_ime.memory_lifecycle.daily import day_bounds, generate, snapshot
from rag_ime.memory_lifecycle.forget import forget_source, preview_source_forget
from rag_ime.memory_lifecycle.ingress import gate_input_event
from rag_ime.memory_lifecycle.portability import (export_project, import_bundle, object_id, records_bundle, validate_bundle)
from rag_ime.memory_lifecycle.privacy import (CapturePolicy, PrivacyInputError, assess_capture, redact_text, sanitize_json)
from rag_ime.memory_lifecycle.refresh import (
    LostLease,
    RETRY_DELAYS_MS,
    RefreshJobs,
    RefreshWorker,
    failure_code,
)

ROOT = Path(__file__).resolve().parents[1]
AT = 1789142400000  # 2026-09-11 16:00:00 UTC; assertions use day_bounds, not host TZ.


def seal(packet):
    packet.pop("sha256", None)
    packet["sha256"] = digest(packet)
    return packet


def bundle(text="完成检索索引联调", *, atom=True, namespace="test:work", rid="entry-1", at=AT):
    value = records_bundle(records=[{"id": rid, "text": text, "occurredAtMs": at}], namespace=namespace, project="PAW")
    if atom:
        origin = {"namespace": namespace, "id": "atom-" + rid}
        item = {"id": object_id("atom", origin), "origin": origin, "kind": "project_fact", "text": text,
                "contentSha256": text_digest(text), "status": "approved", "createdAtMs": at, "updatedAtMs": at,
                "validFromMs": 0, "validToMs": None, "claimState": "current", "redacted": False}
        value["atoms"].append(item)
        value["references"].append({"from": item["id"], "to": value["evidence"][0]["id"], "relation": "source"})
    return seal(value)


def test_admission(alias):
    # Unit-test dependency seam. Production calls PAW's owning canonical gate.
    return f"""{alias}.status='active' AND {alias}.admission_state='admitted'
        AND {alias}.evidence_domain='personal_memory' AND {alias}.scope_mode='authoritative'
        AND {alias}.owner_kind='user' AND {alias}.owner_id='default'
        AND EXISTS (SELECT 1 FROM memory_evidence_input_event_links l WHERE l.evidence_id={alias}.evidence_id AND l.relation='source')
        AND NOT EXISTS (SELECT 1 FROM memory_evidence_input_event_links l JOIN memory_state s ON s.event_id=l.input_event_id
            WHERE l.evidence_id={alias}.evidence_id AND s.deleted!=0)"""


def admit_fixture(conn):
    # Simulates a successful owner-controlled review, not an application API.
    conn.execute("UPDATE agent_memory_evidence SET admission_state='admitted'")
    conn.execute("UPDATE memory_atoms SET status='approved'")
    conn.commit()


def admission_fixture(conn, evidence_id, at):
    conn.execute("UPDATE agent_memory_evidence SET admission_state='forgotten',admission_revision=admission_revision+1,forgotten_at_ms=? WHERE evidence_id=?", (at, evidence_id))


def mutation_fixture(conn, kind, target, at):
    table, col = {"atom": ("memory_atoms", "id"), "item": ("memory_items", "memory_id"), "book": ("memory_books", "book_id")}[kind]
    conn.execute(f"UPDATE {table} SET status='tombstoned',updated_at_ms=? WHERE {col}=?", (at, target))


class DatabaseCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "memory.sqlite"
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript((Path(__file__).with_name("memory_lifecycle_fixture.sql")).read_text())
        self.conn.executescript((ROOT / "rag_ime/db/migrations/0201_memory_lifecycle.sql").read_text())
        self.conn.execute("UPDATE memory_portable_identity SET namespace='test:local' WHERE singleton=1")
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        self.temp.cleanup()

    def imported(self, packet=None, *, project="PAW"):
        return import_bundle(self.conn, packet or bundle(), target_project=project, dry_run=False)

    def table_count(self, table):
        return self.conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]

    def report(self, *, project="PAW", day="2026-09-11", timezone="UTC"):
        return generate(self.conn, project=project, day=day, timezone=timezone,
                        admission_predicate=test_admission, include_timeline=False)

    def forget(self, source_id="event:1", **kwargs):
        plan = preview_source_forget(self.conn, project="PAW", source_id=source_id)
        return forget_source(self.conn, project="PAW", source_id=source_id, expected_plan_digest=plan["planDigest"],
            admission=admission_fixture, mutation=mutation_fixture, rebuild=lambda conn: None, **kwargs)


class PrivacyTests(unittest.TestCase):
    def test_private_flags_fail_closed_without_text(self):
        for key in ("privateWindow", "isIncognito", "privateCommunication", "sessionOnly", "onlyThisTime"):
            with self.subTest(key=key):
                decision = assess_capture(source="input", text="秘密原文", metadata={key: True})
                self.assertFalse(decision.allowed)
                self.assertEqual(decision.text, "")
                self.assertNotIn("秘密原文", canonical_json(decision.receipt()))

    def test_false_is_not_true(self):
        self.assertTrue(assess_capture(source="input", text="正常", metadata={"privateWindow": False}).allowed)
        self.assertFalse(assess_capture(source="input", text="正常", metadata={"privateWindow": "false"}).allowed)

    def test_nested_privacy(self):
        self.assertFalse(assess_capture(source="input", text="正常", metadata={"captureMetadata": {"privacy": {"sessionOnly": True}}}).allowed)

    def test_retention(self):
        for value in ("session_only", "only_this_time", "none", "invalid"):
            self.assertFalse(assess_capture(source="input", text="正常", metadata={"memoryRetention": value}).allowed)

    def test_tag_exclusion(self):
        self.assertFalse(assess_capture(source="input", text="正常", tags=("session-only",)).allowed)

    def test_source_exclusion(self):
        self.assertFalse(assess_capture(source="PASSWORD_MANAGER", text="normal").allowed)
        with patch.dict(os.environ, {"PAW_MEMORY_INGRESS_POLICY": '{"excludedSources":["test"]}'}):
            self.assertFalse(assess_capture(source="test", text="normal").allowed)

    def test_bad_configuration(self):
        for value in ("not-json", "[]", '{"redact":"true"}', '{"excludedSources":"x"}', '{"unknown":0}'):
            with patch.dict(os.environ, {"PAW_MEMORY_INGRESS_POLICY": value}):
                with self.assertRaises(PrivacyInputError):
                    assess_capture(source="x", text="normal")

    def test_disposition_never_widened(self):
        for value in ("private", "sensitive", "unknown", "bogus"):
            self.assertFalse(assess_capture(source="x", text="normal", disposition=value).allowed)

    def test_text_redaction(self):
        examples = ["password=abcXYZ", '"api_key":"s3cr3t"', "Bearer 123456.foo", "a@example.com",
                    "13812345678", "123-45-6789", "4111 1111 1111 1111", "sk-" + "abcdefghijklmnopqrstuvwxyz"]
        for value in examples:
            with self.subTest(value=value):
                self.assertNotIn(value, redact_text("测试 " + value + " 结束"))

    def test_private_key(self):
        value = "-----BEGIN PRIVATE KEY-----\nabcdef\n-----END PRIVATE KEY-----"
        self.assertEqual(redact_text(value), "[REDACTED]")

    def test_regular_text_and_number_preserved(self):
        self.assertEqual(redact_text("测试通过42项，latency=123ms"), "测试通过42项，latency=123ms")

    def test_recursive_metadata_redaction(self):
        metadata = {"account": {"apiKey": "secret-data", "user": "name@example.com"}, "urls": ["https://example.org/?access_token=abc123"]}
        value = canonical_json(sanitize_json(metadata))
        self.assertNotIn("secret-data", value)
        self.assertNotIn("name@example.com", value)
        self.assertNotIn("abc123", value)

    def test_redact_disabled_means_deny_not_store_raw(self):
        self.assertFalse(assess_capture(source="input", text="password=secret", policy=CapturePolicy(redact=False)).allowed)

    def test_limits(self):
        with self.assertRaises(PrivacyInputError):
            redact_text("a" * 64_001)
        with self.assertRaises(PrivacyInputError):
            sanitize_json({"x": float("nan")})
        value = {}
        for _ in range(15):
            value = {"x": value}
        with self.assertRaises(PrivacyInputError):
            sanitize_json(value)

    def test_protocol_metadata_is_not_a_secret_key(self):
        value = {"authorizationRevision": "policy-1", "tokenCount": 12, "maxTokens": 42, "apiKey": "abc"}
        safe = sanitize_json(value)
        self.assertEqual(safe["authorizationRevision"], "policy-1")
        self.assertEqual(safe["tokenCount"], 12)
        self.assertEqual(safe["apiKey"], "[REDACTED]")

    def test_malformed_retention_fails_closed(self):
        for value in ([], {}, 1, None):
            self.assertFalse(assess_capture(source="input", text="normal", metadata={"memoryRetention": value}).allowed)

    def test_sensitive_identity_requires_opaque_id(self):
        with self.assertRaisesRegex(LifecycleError, "opaque"):
            records_bundle(records=[{"id": "person@example.com", "text": "normal", "occurredAtMs": AT}], namespace="test", project="PAW")

    def test_generated_reports_cannot_loop_back(self):
        self.assertFalse(assess_capture(source="work_record", text="日报", metadata={"derivedArtifactType": "daily_memory_report"}).allowed)
        with self.assertRaises(LifecycleError):
            records_bundle(records=[{"id": "x", "text": "日报", "occurredAtMs": AT,
                "metadata": {"derivedArtifactType": "daily_memory_report"}}], namespace="n", project="PAW")


@dataclass(frozen=True)
class Event:
    committed_text: str = "正常文本"
    source: str = "test"
    recent_context: str = ""
    preedit: str = ""
    capture_metadata: dict = field(default_factory=dict)
    tags: tuple = ()
    privacy_disposition: str = "allowed"
    project: str = "PAW"
    app: str = "test"
    context_group_id: str = ""
    created_at_ms: int = AT


class IngressTests(DatabaseCase):
    def core(self):
        outer = self
        class Core:
            calls = []
            def initialize(self):
                pass
            @contextmanager
            def _connect(self):
                yield outer.conn
            def record_capture_outcome(self, **kwargs):
                self.calls.append(kwargs)
                return {"outcome": "no_store", "reason": kwargs["reason_code"]}
        return Core()

    def test_untyped_redaction_copies_not_mutates(self):
        original = Event(committed_text="password=secret", recent_context="x@example.com")
        event, _ = gate_input_event(self.core(), original, None)
        self.assertEqual(original.committed_text, "password=secret")
        self.assertNotIn("secret", event.committed_text)
        self.assertNotIn("example.com", event.recent_context)
        self.assertEqual(self.table_count("input_events"), 0)

    def test_typed_redaction_acks_original_without_content_write(self):
        core = self.core()
        receipts = []
        event, ref = gate_input_event(core, Event(committed_text="password=secret", capture_metadata={"captureId": "c-1"}), receipts)
        self.assertIsNone(event)
        self.assertEqual(len(receipts), 1)
        self.assertEqual(core.calls[-1]["text"], "password=secret")
        self.assertNotIn("secret", canonical_json(receipts))
        self.assertIn("no_store", ref)
        self.assertEqual(self.table_count("input_events"), 0)

    def test_private_event_has_no_content(self):
        event, _ = gate_input_event(self.core(), Event(capture_metadata={"privateWindow": True}), None)
        self.assertIsNone(event)

    def test_session_exclusion_is_project_scoped(self):
        self.conn.execute("INSERT INTO memory_capture_exclusions VALUES ('PAW','session','s1',?)", (AT,))
        self.conn.commit()
        event, _ = gate_input_event(self.core(), Event(context_group_id="agent-session:s1"), None)
        self.assertIsNone(event)
        event, _ = gate_input_event(self.core(), Event(project="Other", context_group_id="agent-session:s1"), None)
        self.assertIsNotNone(event)


class PortabilityTests(DatabaseCase):
    def test_preview_rolls_back_everything(self):
        before = list(self.conn.iterdump())
        result = import_bundle(self.conn, bundle(), target_project="PAW")
        self.assertTrue(result["dryRun"])
        self.assertEqual(result["counts"]["atom"], 1)
        self.assertEqual(before, list(self.conn.iterdump()))

    def test_import_never_trusts_approval(self):
        result = self.imported()
        self.assertEqual(result["approvedAtomsCreated"], 0)
        self.assertEqual(self.conn.execute("SELECT status FROM memory_atoms").fetchone()[0], "draft")
        row = self.conn.execute("SELECT admission_state,owner_kind,owner_id,origin_kind FROM agent_memory_evidence").fetchone()
        self.assertEqual(tuple(row), ("needs_review", "user", "default", "explicit_user_memory"))

    def test_provenance_and_occurrence_preserved(self):
        self.imported()
        row = self.conn.execute("SELECT occurred_at_ms,recorded_at_ms,provenance_json FROM agent_memory_evidence").fetchone()
        self.assertEqual(row[0], AT)
        self.assertEqual(row[1], AT)
        self.assertEqual(json.loads(row[2])["portableOrigin"]["namespace"], "test:work")
        self.assertNotEqual(self.conn.execute("SELECT imported_at_ms FROM memory_portable_imports LIMIT 1").fetchone()[0], AT)

    def test_reference_closure_and_foreign_keys(self):
        self.imported()
        self.assertEqual(self.table_count("memory_lifecycle_atom_evidence_links"), 1)
        self.assertEqual(self.table_count("memory_evidence_input_event_links"), 1)
        self.assertEqual(self.conn.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_same_import_twice_is_idempotent(self):
        packet = bundle()
        a = self.imported(packet)
        b = self.imported(packet)
        self.assertEqual(a["idMap"], b["idMap"])
        self.assertEqual(b["counts"]["reused"], 3)
        self.assertEqual(self.table_count("input_events"), 1)

    def test_project_migration_is_copy_not_move(self):
        packet = bundle()
        self.imported(packet)
        moved = self.imported(packet, project="Other")
        self.assertEqual(self.table_count("memory_atoms"), 2)
        self.assertEqual(moved["counts"]["source"], 1)
        self.assertNotEqual(*[r[0] for r in self.conn.execute("SELECT id FROM memory_atoms")])

    def test_redacted_import_roundtrip_has_stable_identity(self):
        self.imported(bundle("password=secret-value"))
        self.assertNotIn("secret-value", "\n".join(self.conn.iterdump()))
        result = self.imported(export_project(self.conn, project="PAW"))
        self.assertEqual(result["counts"]["reused"], 3)

    def test_export_does_not_mix_projects(self):
        self.imported()
        self.imported(bundle("其他项目", rid="other"), project="Other")
        out = export_project(self.conn, project="PAW")
        self.assertEqual(len(out["atoms"]), 1)
        self.assertNotIn("其他项目", canonical_json(out))
        validate_bundle(out)

    def test_roundtrip_is_not_duplicate_evidence(self):
        self.imported()
        out = export_project(self.conn, project="PAW")
        result = self.imported(out)
        self.assertEqual(result["counts"]["reused"], 3)
        self.assertEqual(self.table_count("agent_memory_evidence"), 1)

    def test_export_private_class_is_not_incognito(self):
        self.imported()
        self.assertEqual(self.conn.execute("SELECT privacy_class FROM agent_memory_evidence").fetchone()[0], "private")
        self.assertEqual(len(export_project(self.conn, project="PAW")["evidence"]), 1)

    def test_private_input_omits_entire_proof(self):
        self.imported()
        self.conn.execute("UPDATE input_events SET capture_metadata_json=?", ('{"privateWindow":true}',))
        self.conn.commit()
        out = export_project(self.conn, project="PAW")
        self.assertEqual(out["evidence"], [])
        self.assertEqual(out["atoms"], [])
        self.assertEqual(out["omitted"], {"atoms": 1, "evidence": 1})

    def test_owner_isolation(self):
        self.imported()
        self.conn.execute("UPDATE agent_memory_evidence SET owner_kind='agent',owner_id='test'")
        self.conn.commit()
        self.assertEqual(export_project(self.conn, project="PAW")["atoms"], [])

    def test_local_source_policy_is_reapplied(self):
        packet = bundle()
        packet["sources"][0]["source"] = "password_manager"
        seal(packet)
        with self.assertRaises(LifecycleError):
            self.imported(packet)
        self.assertEqual(self.table_count("input_events"), 0)

    def test_content_identity_conflict_does_not_overwrite(self):
        self.imported()
        changed = bundle("修改了同一来源的内容")
        with self.assertRaisesRegex(LifecycleError, "conflict"):
            self.imported(changed)
        self.assertEqual(self.conn.execute("SELECT committed_text FROM input_events").fetchone()[0], "完成检索索引联调")

    def test_integrity_error_precedes_write(self):
        packet = bundle()
        packet["atoms"][0]["text"] = "tampered"
        with self.assertRaises(LifecycleError):
            self.imported(packet)
        self.assertEqual(self.table_count("input_events"), 0)

    def test_dangling_reference_rejected(self):
        packet = bundle()
        packet["references"][0]["to"] = "missing"
        seal(packet)
        with self.assertRaisesRegex(LifecycleError, "dangling"):
            self.imported(packet)
        self.assertEqual(self.table_count("agent_memory_evidence"), 0)

    def test_duplicate_reference_rejected(self):
        packet = bundle()
        packet["references"].append(packet["references"][0].copy())
        seal(packet)
        with self.assertRaisesRegex(LifecycleError, "duplicate_reference"):
            self.imported(packet)

    def test_duplicate_objects_rejected(self):
        packet = bundle()
        packet["sources"].append(packet["sources"][0].copy())
        seal(packet)
        with self.assertRaisesRegex(LifecycleError, "duplicate_or_invalid"):
            self.imported(packet)

    def test_invalid_reference_direction_rejected(self):
        packet = bundle()
        ref = packet["references"][0]
        ref["from"], ref["to"] = ref["to"], ref["from"]
        seal(packet)
        with self.assertRaisesRegex(LifecycleError, "direction"):
            self.imported(packet)

    def test_missing_evidence_rejected(self):
        packet = bundle()
        packet["references"] = []
        seal(packet)
        with self.assertRaisesRegex(LifecycleError, "missing_supporting"):
            self.imported(packet)

    def test_partial_failure_rolls_back_prior_sources(self):
        packet = bundle()
        packet["evidence"][0]["provenance"] = {"privateWindow": True}
        seal(packet)
        with self.assertRaises(LifecycleError):
            self.imported(packet)
        self.assertEqual(self.table_count("input_events"), 0)
        self.assertEqual(self.table_count("agent_memory_sources"), 0)

    def test_source_timestamp_is_required(self):
        packet = bundle()
        del packet["sources"][0]["occurredAtMs"]
        seal(packet)
        with self.assertRaisesRegex(LifecycleError, "timestamp"):
            self.imported(packet)

    def test_bool_is_not_a_timestamp(self):
        packet = bundle()
        packet["sources"][0]["occurredAtMs"] = True
        seal(packet)
        with self.assertRaisesRegex(LifecycleError, "timestamp"):
            self.imported(packet)

    def test_unsupported_owner_is_not_rebound_silently(self):
        packet = bundle()
        packet["owner"] = {"kind": "agent", "id": "other"}
        seal(packet)
        with self.assertRaisesRegex(LifecycleError, "owner"):
            self.imported(packet)

    def test_concurrent_import_deduplicates_in_database(self):
        packet = bundle()
        barrier = threading.Barrier(2)
        def write():
            conn = sqlite3.connect(self.path, timeout=10)
            conn.execute("PRAGMA foreign_keys=ON")
            try:
                barrier.wait()
                return import_bundle(conn, packet, target_project="PAW", dry_run=False)
            finally:
                conn.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: write(), range(2)))
        self.assertEqual(sorted(x["counts"]["reused"] for x in results), [0, 3])
        self.assertEqual(self.table_count("memory_atoms"), 1)


class DailyTests(DatabaseCase):
    def test_unreviewed_import_not_in_daily_report(self):
        self.imported()
        self.assertNotIn("完成检索索引联调", self.report()["markdown"])

    def test_reviewed_evidence_and_atom_are_consumed(self):
        self.imported()
        admit_fixture(self.conn)
        result = self.report()
        self.assertIn("完成检索索引联调", result["markdown"])
        self.assertFalse(result["metadata"]["writesBackToMemory"])
        self.assertGreater(len(result["references"]), 0)

    def test_report_is_read_only(self):
        self.imported()
        admit_fixture(self.conn)
        before = list(self.conn.iterdump())
        queries = []
        self.conn.set_trace_callback(queries.append)
        self.report()
        self.conn.set_trace_callback(None)
        self.assertEqual(before, list(self.conn.iterdump()))
        self.assertFalse(any(q.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "REPLACE")) for q in queries))

    def test_occurrence_time_not_import_time(self):
        self.imported(bundle(at=AT - 86_400_000))
        admit_fixture(self.conn)
        self.assertNotIn("完成检索索引联调", self.report()["markdown"])
        self.assertIn("完成检索索引联调", self.report(day="2026-09-10")["markdown"])

    def test_day_range_is_half_open(self):
        start, end = day_bounds("2026-09-11", "UTC")
        self.imported(bundle("今天开始", rid="start", at=start))
        self.imported(bundle("明天开始", rid="end", at=end))
        admit_fixture(self.conn)
        text = self.report()["markdown"]
        self.assertIn("今天开始", text)
        self.assertNotIn("明天开始", text)

    def test_dst_spring_day(self):
        start, end = day_bounds("2026-03-08", "America/Los_Angeles")
        self.assertEqual(end - start, 23 * 3_600_000)

    def test_dst_fall_day(self):
        start, end = day_bounds("2026-11-01", "America/Los_Angeles")
        self.assertEqual(end - start, 25 * 3_600_000)

    def test_invalid_timezone_and_date(self):
        for day, tz in (("2026-02-30", "UTC"), ("2026-09-11", "Mars/Test"), ("20260911", "UTC")):
            with self.assertRaises(LifecycleError):
                day_bounds(day, tz)

    def test_digest_stable_without_source_changes(self):
        self.imported()
        admit_fixture(self.conn)
        self.assertEqual(self.report()["inputDigest"], self.report()["inputDigest"])

    def test_admission_revision_changes_digest(self):
        self.imported()
        admit_fixture(self.conn)
        before = self.report()["inputDigest"]
        self.conn.execute("UPDATE agent_memory_evidence SET admission_revision=admission_revision+1")
        self.conn.commit()
        self.assertNotEqual(before, self.report()["inputDigest"])

    def test_forget_retracts_future_reports(self):
        self.imported()
        admit_fixture(self.conn)
        before = self.report()
        self.forget()
        after = self.report()
        self.assertNotIn("完成检索索引联调", after["markdown"])
        self.assertNotEqual(before["inputDigest"], after["inputDigest"])

    def test_markdown_is_escaped_not_executable(self):
        self.imported(bundle("![track](https://example.org/track) <script>bad</script>"))
        admit_fixture(self.conn)
        text = self.report()["markdown"]
        self.assertNotIn("![track]", text)
        self.assertNotIn("<script>", text)

    def test_other_project_excluded(self):
        self.imported(bundle("别的项目工作"), project="Other")
        admit_fixture(self.conn)
        self.assertNotIn("别的项目工作", self.report()["markdown"])


class ForgetTests(DatabaseCase):
    def test_preview_does_not_modify_state(self):
        self.imported()
        before = list(self.conn.iterdump())
        plan = preview_source_forget(self.conn, project="PAW", source_id="event:1")
        self.assertEqual(len(plan["atomIds"]), 1)
        self.assertEqual(before, list(self.conn.iterdump()))

    def test_closure_and_unrelated_source(self):
        self.imported()
        self.imported(bundle("保留的工作", rid="keep"))
        self.forget()
        rows = self.conn.execute("SELECT content_text,admission_state FROM agent_memory_evidence ORDER BY content_text").fetchall()
        states = dict(rows)
        self.assertEqual(states["完成检索索引联调"], "forgotten")
        self.assertEqual(states["保留的工作"], "needs_review")
        self.assertEqual(self.conn.execute("SELECT count(*) FROM memory_atoms WHERE status='tombstoned'").fetchone()[0], 1)
        self.assertEqual(self.conn.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_old_export_cannot_resurrect_forgotten_source(self):
        packet = bundle()
        self.imported(packet)
        self.forget()
        with self.assertRaisesRegex(LifecycleError, "forgotten"):
            self.imported(packet)
        with self.assertRaisesRegex(LifecycleError, "forgotten"):
            self.imported(packet, project="Other")

    def test_stale_preview_is_rejected(self):
        self.imported()
        plan = preview_source_forget(self.conn, project="PAW", source_id="event:1")
        self.conn.execute("UPDATE memory_atoms SET updated_at_ms=updated_at_ms+1")
        self.conn.commit()
        with self.assertRaisesRegex(LifecycleError, "stale"):
            forget_source(self.conn, project="PAW", source_id="event:1", expected_plan_digest=plan["planDigest"],
                          admission=admission_fixture, mutation=mutation_fixture, rebuild=lambda conn: None)
        self.assertEqual(self.conn.execute("SELECT admission_state FROM agent_memory_evidence").fetchone()[0], "needs_review")

    def test_failure_rolls_back_cascade(self):
        self.imported()
        plan = preview_source_forget(self.conn, project="PAW", source_id="event:1")
        def fail(*args):
            raise RuntimeError("simulated index failure")
        before = list(self.conn.iterdump())
        with self.assertRaises(RuntimeError):
            forget_source(self.conn, project="PAW", source_id="event:1", expected_plan_digest=plan["planDigest"],
                          admission=admission_fixture, mutation=mutation_fixture, rebuild=fail)
        self.assertEqual(before, list(self.conn.iterdump()))

    def test_observer_failure_does_not_undo_commit(self):
        self.imported()
        def fail():
            raise RuntimeError("observer failed")
        result = self.forget(cache_invalidator=fail)
        self.assertTrue(result["ok"])
        self.assertTrue(result["processCacheInvalidationRequired"])
        self.assertEqual(self.conn.execute("SELECT admission_state FROM agent_memory_evidence").fetchone()[0], "forgotten")

    def test_successful_cache_invalidation(self):
        self.imported()
        calls = []
        self.assertTrue(self.forget(cache_invalidator=lambda: calls.append(True))["cacheInvalidated"])
        self.assertEqual(calls, [True])

    def test_forgetting_is_not_forensic_wiping(self):
        self.imported()
        self.forget()
        self.assertEqual(self.conn.execute("SELECT committed_text FROM input_events").fetchone()[0], "完成检索索引联调")
        self.assertTrue(self.conn.execute("SELECT deleted FROM memory_state").fetchone()[0])

    def test_wrong_project_does_not_resolve_source(self):
        self.imported()
        with self.assertRaisesRegex(LifecycleError, "not_found"):
            preview_source_forget(self.conn, project="Other", source_id="event:1")

    def test_shared_evidence_does_not_erase_independent_source_b(self):
        self.imported()
        self.imported(bundle("独立来源B", rid="b"))
        # Attach B as an additional supporting source to A's Evidence.
        a = self.conn.execute("SELECT evidence_id FROM agent_memory_evidence WHERE content_text='完成检索索引联调'").fetchone()[0]
        b_hash = self.conn.execute("SELECT canonical_text_sha256 FROM agent_memory_sources WHERE input_event_id=2").fetchone()[0]
        self.conn.execute("INSERT INTO memory_evidence_input_event_links VALUES (?,?,1,'source',?,?)", (a, 2, b_hash, AT))
        self.conn.commit()
        result = self.forget()
        self.assertEqual(result["plan"]["eventIds"], [1])
        self.assertEqual(self.conn.execute("SELECT deleted FROM memory_state WHERE event_id=2").fetchone()[0], 0)
        self.assertEqual(self.conn.execute("SELECT admission_state FROM agent_memory_evidence WHERE content_text='独立来源B'").fetchone()[0], "needs_review")

    def test_transitive_atom_and_book(self):
        self.imported()
        atom = self.conn.execute("SELECT id FROM memory_atoms").fetchone()[0]
        self.conn.execute("INSERT INTO memory_atoms(id,kind,text,canonical_text,source_memory_ids_json,created_at_ms,updated_at_ms,scope_project) VALUES ('derived','fact','derived','derived',?,?,?,'PAW')", (canonical_json([atom]), AT, AT))
        self.conn.execute("INSERT INTO memory_books(book_id,memory_atom_ids_json) VALUES ('book',?)", (canonical_json(["derived"]),))
        self.conn.commit()
        plan = self.forget()["plan"]
        self.assertIn("derived", plan["atomIds"])
        self.assertIn("book", plan["bookIds"])
        self.assertEqual(self.conn.execute("SELECT status FROM memory_books").fetchone()[0], "tombstoned")


class RefreshTests(DatabaseCase):
    def setUp(self):
        super().setUp()
        self.now = 1000
    def build(self, conn, request):
        rev = conn.execute("SELECT revision FROM refresh_test_inputs").fetchone()[0]
        return {"inputDigest": digest(rev), "sourceCursor": {"revision": rev}}
    def effect(self, conn, request):
        conn.execute("UPDATE refresh_test_effects SET counter=counter+1")
        return {"ok": True, "reportReady": True, "privateText": "DO NOT JOURNAL"}
    def jobs(self, **kwargs):
        return RefreshJobs(self.path, clock=lambda: self.now, build_input=self.build,
                           execute=kwargs.pop("execute", self.effect), lease_ms=1000, **kwargs)
    def submit(self, jobs):
        return jobs.submit(operation="daily_report", project="PAW", day="2026-09-11")
    def effect_count(self):
        return self.conn.execute("SELECT counter FROM refresh_test_effects").fetchone()[0]

    def test_job_idempotency_and_no_duplicate_effect(self):
        jobs = self.jobs()
        first = self.submit(jobs)
        second = self.submit(jobs)
        self.assertEqual(first["batchId"], second["batchId"])
        self.assertTrue(second["reused"])
        self.assertEqual(jobs.run_one()["state"], "completed")
        self.assertIsNone(jobs.run_one())
        self.assertEqual(self.effect_count(), 1)
        self.assertTrue(self.submit(jobs)["reused"])

    def test_process_worker_consumes_queued_job_and_can_stop(self):
        jobs = self.jobs()
        submitted = self.submit(jobs)
        worker = RefreshWorker(jobs, poll_interval_s=0.05)
        worker.start()
        try:
            deadline = time.monotonic() + 2
            status = jobs.status(submitted["jobId"])
            while status["state"] not in {"completed", "failed", "paused", "stale"} and time.monotonic() < deadline:
                time.sleep(0.01)
                status = jobs.status(submitted["jobId"])
            self.assertEqual(status["state"], "completed")
            self.assertEqual(self.effect_count(), 1)
        finally:
            worker.stop()
        self.assertFalse(worker.running)

    def test_success_is_content_free(self):
        jobs = self.jobs()
        self.submit(jobs)
        result = jobs.run_one()
        self.assertNotIn("DO NOT JOURNAL", canonical_json(result))
        self.assertNotIn("privateText", self.conn.execute("SELECT result_json FROM memory_maintenance_jobs").fetchone()[0])

    def test_backoff_then_pause(self):
        def fail(conn, request):
            raise TimeoutError("secret password=never-log")
        jobs = self.jobs(execute=fail)
        submitted = self.submit(jobs)
        first = jobs.run_one()
        self.assertEqual(first["nextAttemptAtMs"], self.now + RETRY_DELAYS_MS[0])
        self.assertIsNone(jobs.run_one())
        self.now = first["nextAttemptAtMs"]
        second = jobs.run_one()
        self.assertEqual(second["nextAttemptAtMs"], self.now + RETRY_DELAYS_MS[1])
        self.now = second["nextAttemptAtMs"]
        third = jobs.run_one()
        self.assertEqual(third["state"], "paused")
        self.assertEqual(third["attemptCount"], 3)
        self.assertEqual(third["inputDigest"], submitted["inputDigest"])
        self.assertNotIn("never-log", canonical_json(third))
        self.assertIsNone(jobs.run_one())

    def test_permanent_error_does_not_retry(self):
        def fail(conn, request):
            raise PermissionError("secret")
        jobs = self.jobs(execute=fail)
        self.submit(jobs)
        result = jobs.run_one()
        self.assertEqual(result["state"], "paused")
        self.assertEqual(result["lastErrorCode"], "permission_denied")

    def test_failed_effect_is_rolled_back(self):
        def fail(conn, request):
            conn.execute("UPDATE refresh_test_effects SET counter=counter+1")
            raise TimeoutError()
        jobs = self.jobs(execute=fail)
        self.submit(jobs)
        jobs.run_one()
        self.assertEqual(self.effect_count(), 0)

    def test_continue_keeps_frozen_batch(self):
        def fail(conn, request):
            raise PermissionError()
        jobs = self.jobs(execute=fail)
        original = self.submit(jobs)
        jobs.run_one()
        resumed = jobs.continue_job(original["jobId"])
        self.assertEqual(resumed["batchId"], original["batchId"])
        self.assertEqual(resumed["sourceCursor"], original["sourceCursor"])
        self.assertEqual(resumed["attemptCount"], 1)
        self.assertEqual(resumed["consecutiveFailures"], 0)

    def test_changed_inputs_require_refresh_not_continue(self):
        def fail(conn, request):
            raise PermissionError()
        jobs = self.jobs(execute=fail)
        original = self.submit(jobs)
        jobs.run_one()
        self.conn.execute("UPDATE refresh_test_inputs SET revision=2")
        self.conn.commit()
        with self.assertRaisesRegex(LifecycleError, "refresh_required"):
            jobs.continue_job(original["jobId"])
        self.assertNotEqual(self.submit(jobs)["batchId"], original["batchId"])

    def test_stale_batch_never_executes(self):
        jobs = self.jobs()
        self.submit(jobs)
        self.conn.execute("UPDATE refresh_test_inputs SET revision=2")
        self.conn.commit()
        self.assertEqual(jobs.run_one()["state"], "stale")
        self.assertEqual(self.effect_count(), 0)

    def test_two_process_connections_only_one_claim(self):
        jobs = self.jobs()
        self.submit(jobs)
        barrier = threading.Barrier(2)
        def claim():
            barrier.wait()
            return self.jobs().claim()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: claim(), range(2)))
        self.assertEqual(sum(r is not None for r in results), 1)

    def test_crash_recovery_and_fencing(self):
        jobs = self.jobs()
        original = self.submit(jobs)
        old = jobs.claim()
        self.now += 1001
        self.assertIsNone(self.jobs().claim())  # Interrupted attempt observes backoff.
        state = jobs.status(original["jobId"])
        self.assertEqual(state["lastErrorCode"], "worker_interrupted")
        self.now = state["nextAttemptAtMs"]
        new = self.jobs().claim()
        self.assertNotEqual(new["leaseToken"], old["leaseToken"])
        with self.assertRaises(LostLease):
            jobs.run_claim(old)
        self.assertEqual(self.jobs().run_claim(new)["state"], "completed")
        self.assertEqual(self.effect_count(), 1)

    def test_request_and_digest_from_claim_cannot_replace_durable_inputs(self):
        jobs = self.jobs()
        original = self.submit(jobs)
        claim = jobs.claim()
        claim["request"] = {"operation": "unsafe_apply"}
        claim["inputDigest"] = "forged"
        self.assertEqual(jobs.run_claim(claim)["inputDigest"], original["inputDigest"])

    def test_daily_schedule_is_once_per_calendar_key(self):
        jobs = self.jobs()
        a = jobs.submit(operation="daily_report", project="PAW", day="2026-09-11", scheduled=True)
        self.conn.execute("UPDATE refresh_test_inputs SET revision=2")
        self.conn.commit()
        b = jobs.submit(operation="daily_report", project="PAW", day="2026-09-11", scheduled=True)
        self.assertEqual(a["jobId"], b["jobId"])
        self.assertTrue(b["reused"])
        self.assertNotEqual(a["jobId"], self.submit(jobs)["jobId"])

    def test_completed_receipt_reports_stale_inputs(self):
        jobs = self.jobs()
        original = self.submit(jobs)
        jobs.run_one()
        self.conn.execute("UPDATE refresh_test_inputs SET revision=2")
        self.conn.commit()
        status = jobs.status(original["jobId"])
        self.assertEqual(status["state"], "completed")
        self.assertTrue(status["requiresRefresh"])
        self.assertTrue(status["freshness"]["sourceChanged"])

    def test_expired_lease_cannot_start_even_before_takeover(self):
        jobs = self.jobs()
        self.submit(jobs)
        claim = jobs.claim()
        self.now += 1001
        with self.assertRaises(LostLease):
            jobs.run_claim(claim)
        self.assertEqual(self.effect_count(), 0)

    def test_projection_fingerprint_includes_memory_items(self):
        jobs = RefreshJobs(self.path, clock=lambda: self.now, execute=self.effect)
        original = jobs.submit(operation="retrieval_projection", project="PAW")
        self.conn.execute("INSERT INTO memory_items(memory_id,text) VALUES ('test-item','new phrase')")
        self.conn.commit()
        self.assertEqual(jobs.run_one()["state"], "stale")
        self.assertTrue(jobs.status(original["jobId"])["requiresRefresh"])
        self.assertEqual(self.effect_count(), 0)

    def test_operation_allowlist(self):
        with self.assertRaisesRegex(LifecycleError, "unsupported"):
            self.jobs().submit(operation="governance_apply", project="PAW")

    def test_error_classification(self):
        self.assertTrue(failure_code(HTTPError("https://test", 429, "secret", None, None))[1])
        self.assertFalse(failure_code(HTTPError("https://test", 401, "secret", None, None))[1])
        self.assertTrue(failure_code(sqlite3.OperationalError("database is locked"))[1])
        self.assertFalse(failure_code(ValueError("secret"))[1])


class FileAndCliTests(DatabaseCase):
    def test_private_atomic_output_and_no_overwrite(self):
        dest = Path(self.temp.name) / "bundle.json"
        write_private(str(dest), "one")
        self.assertEqual(dest.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(FileExistsError):
            write_private(str(dest), "two")
        self.assertEqual(dest.read_text(), "one")
        write_private(str(dest), "two", overwrite=True)
        self.assertEqual(dest.read_text(), "two")

    def test_duplicate_json_keys_rejected(self):
        dest = Path(self.temp.name) / "bad.json"
        dest.write_text('{"x":1,"x":2}')
        with self.assertRaisesRegex(LifecycleError, "duplicate"):
            read_json(str(dest))

    def test_nan_json_rejected(self):
        dest = Path(self.temp.name) / "bad.json"
        dest.write_text('{"x":NaN}')
        with self.assertRaises(LifecycleError):
            read_json(str(dest))

    def test_offline_erasure_requires_explicit_acknowledgement(self):
        self.imported()
        errors = io.StringIO()
        with redirect_stderr(errors):
            code = main(["--db", str(self.path), "forget-source", "--project", "PAW", "--source-id", "event:1", "--commit"])
        self.assertEqual(code, 2)
        self.assertIn("stopped_gateway", errors.getvalue())
        self.assertEqual(self.conn.execute("SELECT deleted FROM memory_state").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()


class FinalReportBoundaryTests(DatabaseCase):
    def test_report_json_includes_resolvable_reference_objects(self):
        self.imported()
        admit_fixture(self.conn)
        report = self.report()
        ids = {obj["id"] for field in ("sources", "evidence", "contextEvidence", "memory") for obj in report[field]}
        self.assertTrue(report["references"])
        for ref in report["references"]:
            self.assertIn(ref["from"], ids)
            self.assertIn(ref["to"], ids)

    def test_legacy_private_provenance_is_excluded_on_export(self):
        self.imported()
        self.conn.execute("UPDATE agent_memory_evidence SET provenance_json=?", ('{"privateWindow":true}',))
        self.conn.commit()
        packet = export_project(self.conn, project="PAW")
        self.assertEqual(packet["evidence"], [])
        self.assertEqual(packet["atoms"], [])

    def test_timeline_owner_receives_date_string_not_date_object(self):
        import sys
        import types
        calls = []
        def bounds(day):
            self.assertIsInstance(day, str)
            calls.append(day)
            return day_bounds(day, "UTC")
        owner = types.ModuleType("rag_ime.personal_context")
        owner.local_day_bounds_ms = bounds
        owner.load_activity_timeline_context = lambda *a, **k: {"available": False}
        with patch.dict(sys.modules, {"rag_ime.personal_context": owner}):
            value = generate(self.conn, project="PAW", day="2026-09-11", timezone="UTC", admission_predicate=test_admission)
        self.assertEqual(calls, ["2026-09-11"])
        self.assertFalse(value["metadata"]["writesBackToMemory"])
