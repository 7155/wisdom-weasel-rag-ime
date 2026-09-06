from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.check_pawos_requirement_status import (
    extract_status_payload,
    validate_requirement_status,
)


def status_document(payload: dict[str, object]) -> str:
    return (
        "# Status\n\n"
        "<!-- PAWOS_REQUIREMENT_STATUS_JSON_BEGIN -->\n"
        "```json\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}\n"
        "```\n"
        "<!-- PAWOS_REQUIREMENT_STATUS_JSON_END -->\n"
    )


class PawosRequirementStatusTests(unittest.TestCase):
    def test_repository_split_ledger_covers_ur_001_through_ur_297_with_scoped_closeouts(self) -> None:
        root = Path(__file__).resolve().parents[1]
        requirements_path = root / "control-center-web/docs/pawos/PAWOS_REQUIREMENTS.md"
        status_path = root / "control-center-web/docs/pawos/PAWOS_REQUIREMENT_STATUS.md"

        report = validate_requirement_status(requirements_path, status_path)

        self.assertEqual(report["errors"], [])
        self.assertEqual(report["requirementCount"], 297)
        self.assertEqual(report["firstRequirementId"], "UR-001")
        self.assertEqual(report["lastRequirementId"], "UR-297")
        self.assertEqual(report["assessmentCounts"], {"complete": 7, "in_progress": 29, "unassessed": 261})
        self.assertTrue(report["splitLedger"])
        self.assertEqual(report["completeCount"], 7)
        self.assertEqual(report["receiptCount"], 26)

    def test_current_or_checked_source_text_does_not_imply_complete(self) -> None:
        requirements = (
            "### UR-001 — one\n"
            "- **状态 / 优先级：** `current / P0`\n"
            "- [x] implementation-looking prose\n"
        )
        payload = self._payload(requirements, {"UR-001": {}})

        report = self._validate(requirements, payload)

        self.assertEqual(report["errors"], [])
        self.assertEqual(report["assessmentCounts"], {"unassessed": 1})
        self.assertEqual(report["completeCount"], 0)

    def test_complete_requires_both_verdicts_and_a_valid_receipt(self) -> None:
        requirements = "### UR-001 — one\n"
        payload = self._payload(
            requirements,
            {
                "UR-001": {
                    "assessment": "complete",
                    "runsVerdict": "passed",
                    "requirementVerdict": "unverified",
                    "evidenceRefs": [],
                    "requiredEvidenceLevels": ["E6"],
                }
            },
        )

        report = self._validate(requirements, payload)

        self.assertIn(
            "UR-001: complete requires requirementVerdict=satisfied",
            report["errors"],
        )
        self.assertIn("UR-001: complete requires at least one evidence receipt", report["errors"])

    def test_complete_with_both_verdicts_and_a_scoped_receipt_is_valid(self) -> None:
        requirements = "### UR-001 — one\n"
        payload = self._payload(
            requirements,
            {
                "UR-001": {
                    "assessment": "complete",
                    "runsVerdict": "passed",
                    "requirementVerdict": "satisfied",
                    "evidenceRefs": ["RCP-001"],
                    "requiredEvidenceLevels": ["E2"],
                    "owner": "test owner",
                    "updatedAt": "2026-08-26T17:30:00+08:00",
                    "note": "The bounded requirement was observed.",
                }
            },
        )
        payload["receipts"] = {
            "RCP-001": {
                "level": "E2",
                "recordedAt": "2026-08-26T17:30:00+08:00",
                "owner": "test owner",
                "claim": "One focused check passed.",
                "artifactRefs": ["python3 -m unittest example"],
                "sha256": "sha256:" + ("a" * 64),
            }
        }

        report = self._validate(requirements, payload)

        self.assertEqual(report["errors"], [])
        self.assertEqual(report["completeCount"], 1)
        self.assertEqual(report["receiptCount"], 1)

    def test_gap_and_stale_source_hash_are_rejected(self) -> None:
        requirements = "### UR-001 — one\n### UR-003 — three\n"
        payload = self._payload(requirements, {"UR-001": {}, "UR-003": {}})
        payload["sourceReceipt"]["sha256"] = "sha256:" + ("0" * 64)

        report = self._validate(requirements, payload)

        self.assertIn("requirements headings are not continuous: expected UR-002, found UR-003", report["errors"])
        self.assertTrue(any("sourceReceipt.sha256 does not match" in error for error in report["errors"]))

    def test_repository_machine_block_is_parseable_json(self) -> None:
        root = Path(__file__).resolve().parents[1]
        text = (root / "control-center-web/docs/pawos/PAWOS_REQUIREMENT_STATUS.md").read_text(
            encoding="utf-8"
        )

        payload = extract_status_payload(text)

        self.assertEqual(payload["schemaVersion"], "pawos.requirement-status.v1")

    @staticmethod
    def _payload(requirements: str, entries: dict[str, object]) -> dict[str, object]:
        return {
            "schemaVersion": "pawos.requirement-status.v1",
            "sourceReceipt": {
                "path": "PAWOS_REQUIREMENTS.md",
                "sha256": "sha256:" + hashlib.sha256(requirements.encode("utf-8")).hexdigest(),
            },
            "evidenceLevelLabels": {
                "E1": "Source",
                "E2": "Test",
                "E3": "Build",
                "E4": "Install",
                "E5": "Runtime",
                "E6": "Foreground",
            },
            "defaults": {
                "assessment": "unassessed",
                "runsVerdict": "unverified",
                "requirementVerdict": "unverified",
                "evidenceRefs": [],
            },
            "receipts": {},
            "requirements": entries,
        }

    def _validate(self, requirements: str, payload: dict[str, object]) -> dict[str, object]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            requirements_path = root / "PAWOS_REQUIREMENTS.md"
            status_path = root / "PAWOS_REQUIREMENT_STATUS.md"
            requirements_path.write_text(requirements, encoding="utf-8")
            status_path.write_text(status_document(payload), encoding="utf-8")
            return validate_requirement_status(requirements_path, status_path)


if __name__ == "__main__":
    unittest.main()
