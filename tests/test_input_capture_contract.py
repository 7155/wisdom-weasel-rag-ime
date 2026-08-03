from __future__ import annotations

import hashlib
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from rag_ime.input_capture_contract import (
    CAPTURE_RECEIPT_SCHEMA_VERSION,
    InputCaptureContractError,
    InputCaptureIdentityConflict,
    parse_input_capture_contract,
)
from rag_ime.local_sqlite_core import LocalSqliteCoreClient
from rag_ime.models import InputEvent
from rag_ime.text_utils import compact_whitespace


APP = "com.apple.TextEdit"
TEXT = "这是一次已确认的最终输入"


def capture_metadata(
    *,
    text: str = TEXT,
    capture_id: str = "capture:controller-3:focus-8:1",
    transaction_id: str = "transaction:controller-3:focus-8",
    sequence: int = 1,
    channel: str = "input_method",
    boundary_kind: str = "host_return",
    boundary_confidence: str = "strong",
    native_composition_before: bool = False,
    rime_handled: bool = False,
    host_forwarded: bool = True,
    modified_return: bool = False,
    final_committed: bool = True,
) -> dict[str, object]:
    return {
        "schemaVersion": "rag-ime.input-capture.v2",
        "captureId": capture_id,
        "transactionId": transaction_id,
        "sequence": sequence,
        "channel": channel,
        "boundaryKind": boundary_kind,
        "boundaryConfidence": boundary_confidence,
        "nativeCompositionBefore": native_composition_before,
        "rimeHandled": rime_handled,
        "hostForwarded": host_forwarded,
        "modifiedReturn": modified_return,
        "finalCommitted": final_committed,
        "controllerEpoch": 3,
        "focusEpoch": 8,
        "appBundleId": APP,
        "fieldIdentitySha256": hashlib.sha256(b"field:editor").hexdigest(),
        "privacyRevision": "foreground-privacy.v1",
        "occurredStartMs": 100,
        "occurredEndMs": 140,
        "contentSha256": hashlib.sha256(
            compact_whitespace(text).encode("utf-8")
        ).hexdigest(),
        "captureSource": "text_input_client" if channel == "input_method" else "voice_insertion",
        "fallbackReason": "",
        "fieldContextChars": len(text),
        "imeBufferChars": len(text),
        "selectionRule": "final_committed_segment",
    }


def input_event(metadata: dict[str, object], *, text: str = TEXT) -> InputEvent:
    return InputEvent(
        event_id=None,
        created_at_ms=1_000,
        source="squirrel_input_segment",
        committed_text=text,
        privacy_disposition="allowed",
        app=APP,
        project="personal-agent-workbench",
        provider_name="squirrel",
        capture_metadata=metadata,
    )


class InputCaptureContractTests(unittest.TestCase):
    def test_unmodified_host_return_is_a_strong_final_boundary(self) -> None:
        contract = parse_input_capture_contract(
            capture_metadata(),
            text=TEXT,
            source="squirrel_input_segment",
            app=APP,
        )

        self.assertTrue(contract.is_strong_final)
        self.assertEqual(contract.boundary_kind, "host_return")
        self.assertEqual(contract.content_sha256, hashlib.sha256(TEXT.encode()).hexdigest())

    def test_candidate_selection_return_cannot_claim_a_strong_final_boundary(self) -> None:
        metadata = capture_metadata(
            native_composition_before=True,
            rime_handled=True,
            host_forwarded=False,
        )

        with self.assertRaisesRegex(InputCaptureContractError, "prior composition"):
            parse_input_capture_contract(
                metadata,
                text=TEXT,
                source="squirrel_input_segment",
                app=APP,
            )

    def test_modified_return_cannot_claim_a_strong_final_boundary(self) -> None:
        with self.assertRaisesRegex(InputCaptureContractError, "modified"):
            parse_input_capture_contract(
                capture_metadata(modified_return=True),
                text=TEXT,
                source="squirrel_input_segment",
                app=APP,
            )

    def test_focus_change_is_weak_audit_only(self) -> None:
        contract = parse_input_capture_contract(
            capture_metadata(
                boundary_kind="focus_change",
                boundary_confidence="weak",
                host_forwarded=False,
                final_committed=False,
            ),
            text=TEXT,
            source="squirrel_input_segment",
            app=APP,
        )

        self.assertFalse(contract.is_strong_final)

    def test_only_a_committed_voice_final_is_strong(self) -> None:
        metadata = capture_metadata(
            channel="voice",
            boundary_kind="voice_final",
            host_forwarded=True,
        )
        contract = parse_input_capture_contract(
            metadata,
            text=TEXT,
            source="voice_final",
            app=APP,
        )
        self.assertTrue(contract.is_strong_final)

        with self.assertRaises(InputCaptureContractError):
            parse_input_capture_contract(
                {**metadata, "finalCommitted": False},
                text=TEXT,
                source="voice_final",
                app=APP,
            )

        for invalid_field, invalid_value in (
            ("hostForwarded", False),
            ("nativeCompositionBefore", True),
            ("rimeHandled", True),
            ("modifiedReturn", True),
        ):
            with self.subTest(invalid_field=invalid_field):
                with self.assertRaisesRegex(
                    InputCaptureContractError,
                    "successfully inserted",
                ):
                    parse_input_capture_contract(
                        {**metadata, invalid_field: invalid_value},
                        text=TEXT,
                        source="voice_final",
                        app=APP,
                    )

    def test_capture_source_must_match_channel(self) -> None:
        with self.assertRaisesRegex(InputCaptureContractError, "voice_insertion"):
            parse_input_capture_contract(
                {**capture_metadata(), "captureSource": "voice_insertion"},
                text=TEXT,
                source="squirrel_input_segment",
                app=APP,
            )


class InputCaptureReceiptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="rag-ime-input-capture-")
        self.db_path = Path(self.temporary.name) / "rag-ime.sqlite"
        self.core = LocalSqliteCoreClient(self.db_path)
        self.core.initialize()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_exact_retry_returns_original_event_without_duplicate_write(self) -> None:
        event = input_event(capture_metadata())

        first = self.core.record_event(event)
        second = self.core.record_event(event)
        receipt = self.core.capture_receipt("capture:controller-3:focus-8:1")

        self.assertEqual(second, first)
        self.assertEqual(self.core.event_count(), 1)
        self.assertIsNotNone(receipt)
        assert receipt is not None
        self.assertEqual(receipt["schemaVersion"], CAPTURE_RECEIPT_SCHEMA_VERSION)
        self.assertEqual(receipt["eventId"], first)
        self.assertEqual(receipt["evidenceState"], "candidate")
        self.assertTrue(str(receipt["evidenceId"]).startswith("evidence:input:"))
        self.assertTrue(receipt["duplicate"])

        with sqlite3.connect(self.db_path) as conn:
            evidence = conn.execute(
                """
                SELECT evidence_domain, origin_kind, admission_state, project
                FROM agent_memory_evidence
                WHERE evidence_id = ?
                """,
                (receipt["evidenceId"],),
            ).fetchone()
        self.assertEqual(
            evidence,
            (
                "personal_memory",
                "capture_v2_input",
                "candidate",
                "personal-agent-workbench",
            ),
        )

    def test_concurrent_retry_converges_on_one_event_and_one_receipt(self) -> None:
        event = input_event(capture_metadata(capture_id="capture:concurrent:1"))

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _index: self.core.record_event(event), range(2)))

        self.assertEqual(results[0], results[1])
        self.assertEqual(self.core.event_count(), 1)
        with sqlite3.connect(self.db_path) as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM input_capture_receipts WHERE capture_id = ?",
                    ("capture:concurrent:1",),
                ).fetchone()[0],
                1,
            )

    def test_capture_id_replay_with_different_content_fails_closed(self) -> None:
        self.core.record_event(input_event(capture_metadata()))
        changed_text = "这是另一次不同的最终输入"
        changed = input_event(capture_metadata(text=changed_text), text=changed_text)

        with self.assertRaises(InputCaptureIdentityConflict):
            self.core.record_event(changed)
        self.assertEqual(self.core.event_count(), 1)

    def test_transaction_sequence_cannot_be_reused_by_another_capture(self) -> None:
        self.core.record_event(input_event(capture_metadata()))
        changed = capture_metadata(capture_id="capture:another-id")

        with self.assertRaises(InputCaptureIdentityConflict):
            self.core.record_event(input_event(changed))
        self.assertEqual(self.core.event_count(), 1)

    def test_weak_boundary_gets_text_free_quarantine_receipt(self) -> None:
        metadata = capture_metadata(
            boundary_kind="app_change",
            boundary_confidence="weak",
            host_forwarded=False,
            final_committed=False,
        )

        receipt = self.core.record_capture_outcome(
            text=TEXT,
            source="squirrel_input_segment",
            app=APP,
            capture_metadata=metadata,
            outcome="quarantined",
            reason_code="weak_boundary_not_final",
            created_at_ms=1_000,
        )

        self.assertEqual(receipt["outcome"], "quarantined")
        self.assertEqual(receipt["eventId"], "")
        self.assertNotIn(TEXT, str(receipt))
        self.assertEqual(self.core.event_count(), 0)

    def test_receipt_foreign_key_prevents_event_deletion(self) -> None:
        event_ref = self.core.record_event(input_event(capture_metadata()))
        event_id = int(event_ref.removeprefix("event:"))
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("DELETE FROM input_events WHERE id = ?", (event_id,))


if __name__ == "__main__":
    unittest.main()
