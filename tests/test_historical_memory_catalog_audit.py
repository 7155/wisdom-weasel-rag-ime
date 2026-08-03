from __future__ import annotations

import unittest

from rag_ime.historical_memory_catalog_audit import (
    HistoricalMemoryCatalogAuditError,
    _representative_evidence_rows,
    catalog_audit_digest,
    validate_historical_catalog_audit,
)


class HistoricalMemoryCatalogAuditTests(unittest.TestCase):
    def test_representative_evidence_removes_cumulative_short_fragments(self) -> None:
        rows = _representative_evidence_rows(
            [
                {"key": "1", "text": "记忆", "occurredAtMs": 1},
                {"key": "2", "text": "记忆整理", "occurredAtMs": 2},
                {"key": "3", "text": "记忆整理需要证据", "occurredAtMs": 3},
            ]
        )

        self.assertEqual([row["key"] for row in rows], ["3"])

    def test_validator_requires_exact_atom_and_book_coverage(self) -> None:
        packet = {
            "schemaVersion": "rag-ime.historical-memory-catalog-audit.v1",
            "project": "ime",
            "atoms": [{"ref": "P1", "kind": "project_requirement", "text": "要求", "evidenceRefs": ["E1"]}],
            "evidence": [{"ref": "E1", "text": "要求", "origin": "capture_v2_input", "boundary": "enter", "admission": "admitted"}],
            "books": [{"ref": "B1", "title": "输入法", "summary": "要求", "atomRefs": ["P1"], "missingAtomCount": 0}],
        }
        packet["catalogDigest"] = catalog_audit_digest(packet)
        valid = {
            "v": 1,
            "ok": 1,
            "catalogDigest": packet["catalogDigest"],
            "checkedAtomRefs": ["P1"],
            "checkedBookRefs": ["B1"],
            "findings": [],
            "errors": [],
        }

        self.assertTrue(validate_historical_catalog_audit(valid, packet=packet)["passed"])
        with self.assertRaises(HistoricalMemoryCatalogAuditError):
            validate_historical_catalog_audit(
                {**valid, "checkedAtomRefs": []},
                packet=packet,
            )

    def test_validator_rejects_inconsistent_ok_flag(self) -> None:
        packet = {
            "schemaVersion": "rag-ime.historical-memory-catalog-audit.v1",
            "project": "ime",
            "atoms": [{"ref": "P1"}],
            "evidence": [],
            "books": [],
        }
        packet["catalogDigest"] = catalog_audit_digest(packet)
        with self.assertRaises(HistoricalMemoryCatalogAuditError):
            validate_historical_catalog_audit(
                {
                    "v": 1,
                    "ok": 1,
                    "catalogDigest": packet["catalogDigest"],
                    "checkedAtomRefs": ["P1"],
                    "checkedBookRefs": [],
                    "findings": [
                        {
                            "entity": "atom",
                            "ref": "P1",
                            "code": "unsupported",
                            "relatedRefs": [],
                        }
                    ],
                    "errors": [],
                },
                packet=packet,
            )


if __name__ == "__main__":
    unittest.main()
