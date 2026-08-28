from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from rag_ime.agent_service import AgentService
from rag_ime.trace_runtime import TraceContractError, build_trace_envelope, make_span
from rag_ime.trace_store import TraceConflict, TraceStore


def _trace(trace_id: str = "trace:durable:1", *, now_ms: int = 20):
    return build_trace_envelope(
        trace_id=trace_id,
        source_kind="vertical_agent",
        input_text="private query is represented by a hash only",
        binding={"runId": "run:durable:1"},
        spans=(
            make_span(
                span_id=f"span:{trace_id}:run",
                name="agent.run",
                started_at_ms=now_ms,
                ended_at_ms=now_ms + 2,
            ),
        ),
        status="completed",
        now_ms=now_ms + 2,
    )


class TraceStoreTests(unittest.TestCase):
    def test_persists_exact_validated_envelope_across_store_reopen(self) -> None:
        with tempfile.TemporaryDirectory(prefix="trace-store-") as tmp:
            path = Path(tmp) / "runtime.sqlite"
            trace = _trace()

            first = TraceStore(path)
            self.assertEqual(first.persist(trace), trace.to_dict())
            self.assertEqual(first.get(trace.trace_id), trace.to_dict())

            # A new store models a process restart.  The canonical Trace must
            # no longer depend on the temporary vertical-agent workspace.
            second = TraceStore(path)
            self.assertEqual(second.get(trace.trace_id), trace.to_dict())
            self.assertEqual(second.list(), [trace.to_dict()])

    def test_same_canonical_identity_is_idempotent_and_rebinding_conflicts(self) -> None:
        with tempfile.TemporaryDirectory(prefix="trace-store-") as tmp:
            store = TraceStore(Path(tmp) / "runtime.sqlite")
            trace = _trace()

            self.assertEqual(store.persist(trace), store.persist(trace.to_dict()))
            self.assertEqual(len(store.list()), 1)

            changed = _trace(now_ms=21)
            with self.assertRaises(TraceConflict):
                store.persist(changed)
            self.assertEqual(store.get(trace.trace_id), trace.to_dict())

    def test_canonical_json_hash_is_stable_and_invalid_payload_never_writes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="trace-store-") as tmp:
            path = Path(tmp) / "runtime.sqlite"
            store = TraceStore(path)
            payload = _trace().to_dict()
            reordered = {
                "updatedAtMs": payload["updatedAtMs"],
                "createdAtMs": payload["createdAtMs"],
                "artifacts": payload["artifacts"],
                "evidence": payload["evidence"],
                "spans": payload["spans"],
                "input": payload["input"],
                "binding": payload["binding"],
                "status": payload["status"],
                "sourceKind": payload["sourceKind"],
                "traceId": payload["traceId"],
                "schemaVersion": payload["schemaVersion"],
            }
            store.persist(reordered)
            with sqlite3.connect(path) as conn:
                row = conn.execute(
                    "SELECT payload_hash, payload_json FROM trace_envelopes WHERE trace_id = ?",
                    (payload["traceId"],),
                ).fetchone()
            assert row is not None
            self.assertEqual(
                row[0],
                hashlib.sha256(str(row[1]).encode("utf-8")).hexdigest(),
            )
            self.assertEqual(json.loads(str(row[1])), payload)

            invalid = dict(payload)
            invalid["status"] = "not-a-trace-status"
            with self.assertRaises(TraceContractError):
                store.persist(invalid)
            building = dict(payload)
            building["status"] = "building"
            with self.assertRaisesRegex(TraceContractError, "terminal"):
                store.persist(building)
            self.assertEqual(len(store.list()), 1)

    def test_rows_are_immutable_and_eval_refs_have_no_trace_foreign_key(self) -> None:
        with tempfile.TemporaryDirectory(prefix="trace-store-") as tmp:
            path = Path(tmp) / "runtime.sqlite"
            store = TraceStore(path)
            trace = _trace()
            store.persist(trace)

            with sqlite3.connect(path) as conn:
                with self.assertRaisesRegex(sqlite3.IntegrityError, "immutable"):
                    conn.execute(
                        "UPDATE trace_envelopes SET payload_json = '{}' WHERE trace_id = ?",
                        (trace.trace_id,),
                    )
                with self.assertRaisesRegex(sqlite3.IntegrityError, "permanent"):
                    conn.execute(
                        "DELETE FROM trace_envelopes WHERE trace_id = ?",
                        (trace.trace_id,),
                    )
                foreign_keys = conn.execute(
                    "PRAGMA foreign_key_list(eval_run_trace_refs)"
                ).fetchall()
            self.assertNotIn("trace_envelopes", {row[2] for row in foreign_keys})

    def test_replace_cannot_bypass_append_only_trace_identity_guard(self) -> None:
        with tempfile.TemporaryDirectory(prefix="trace-store-") as tmp:
            path = Path(tmp) / "runtime.sqlite"
            store = TraceStore(path)
            trace = _trace()
            store.persist(trace)
            original = trace.to_dict()
            original_json = json.dumps(
                original,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )

            replacement = (
                trace.trace_id,
                "attacker",
                "completed",
                original["createdAtMs"],
                original["updatedAtMs"],
                "0" * 64,
                "{}",
            )
            for statement in ("INSERT OR REPLACE", "REPLACE"):
                with self.subTest(statement=statement):
                    with sqlite3.connect(path) as conn:
                        with self.assertRaisesRegex(
                            sqlite3.IntegrityError,
                            "immutable",
                        ):
                            conn.execute(
                                f"{statement} INTO trace_envelopes("
                                "trace_id, source_kind, status, created_at_ms, "
                                "updated_at_ms, payload_hash, payload_json) "
                                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                                replacement,
                            )

                    self.assertEqual(store.get(trace.trace_id), original)
                    with sqlite3.connect(path) as conn:
                        self.assertEqual(
                            conn.execute(
                                "SELECT source_kind, payload_json FROM trace_envelopes "
                                "WHERE trace_id = ?",
                                (trace.trace_id,),
                            ).fetchone(),
                            ("vertical_agent", original_json),
                        )

    def test_reads_fail_closed_when_row_metadata_disagrees_with_canonical_payload(self) -> None:
        """A direct SQL insert must not make TraceStore return a false authority."""

        cases = (
            ("status", "completed", "building"),
            ("source_kind", "tampered_source", "vertical_agent"),
            ("created_at_ms", 21, 20),
            ("updated_at_ms", 23, 22),
        )
        with tempfile.TemporaryDirectory(prefix="trace-store-inconsistent-") as tmp:
            for index, (column, row_value, payload_value) in enumerate(cases, start=1):
                path = Path(tmp) / f"runtime-{index}.sqlite"
                store = TraceStore(path)
                store.initialize()
                trace = _trace(trace_id=f"trace:inconsistent:{index}", now_ms=20)
                payload = trace.to_dict()
                payload_key = {
                    "status": "status",
                    "source_kind": "sourceKind",
                    "created_at_ms": "createdAtMs",
                    "updated_at_ms": "updatedAtMs",
                }[column]
                payload[payload_key] = payload_value
                canonical = json.dumps(
                    payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                payload_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
                row = (
                    payload["traceId"],
                    row_value if column == "source_kind" else payload["sourceKind"],
                    row_value if column == "status" else "completed",
                    row_value if column == "created_at_ms" else payload["createdAtMs"],
                    row_value if column == "updated_at_ms" else payload["updatedAtMs"],
                    payload_hash,
                    canonical,
                )
                with sqlite3.connect(path) as conn:
                    conn.execute(
                        "INSERT INTO trace_envelopes("
                        "trace_id, source_kind, status, created_at_ms, updated_at_ms, "
                        "payload_hash, payload_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        row,
                    )

                with self.subTest(column=column):
                    with self.assertRaisesRegex(
                        TraceContractError,
                        "persisted trace row metadata|terminal",
                    ):
                        store.get(str(payload["traceId"]))
                    with self.assertRaisesRegex(
                        TraceContractError,
                        "persisted trace row metadata|terminal",
                    ):
                        store.list()

    def test_agent_service_prefers_durable_trace_over_journal_without_requiring_the_attribute(self) -> None:
        with tempfile.TemporaryDirectory(prefix="trace-store-") as tmp:
            path = Path(tmp) / "runtime.sqlite"
            trace = _trace()
            store = TraceStore(path)
            store.persist(trace)
            journal = SimpleNamespace(
                snapshot=lambda _payload: {
                    "items": [],
                    "truncated": False,
                    "firstSequence": 0,
                    "lastSequence": 0,
                    "resumeToken": "observation:0",
                }
            )
            service = AgentService.__new__(AgentService)
            service.trace_store = store
            service.observations = journal

            result = service.observation_trace({"traceId": trace.trace_id})

            self.assertEqual(result["projectionSource"], "trace_store")
            self.assertEqual(result["trace"], trace.to_dict())
            self.assertEqual(
                result["observationWindow"]["resumeToken"],
                f"trace-store:{trace.trace_id}",
            )

            # The legacy __new__ facade remains valid when no durable store is
            # present, and falls through to the journal projection.
            legacy = AgentService.__new__(AgentService)
            legacy.observations = journal
            with self.assertRaises(KeyError):
                legacy.observation_trace({"traceId": trace.trace_id})


if __name__ == "__main__":
    unittest.main()
