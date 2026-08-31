from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_PATH = (
    ROOT / "integrations" / "pi" / "skills" / "trace-agent-diagnostics" / "SKILL.md"
)


class TraceAgentDiagnosticsSkillTests(unittest.TestCase):
    def test_skill_contains_mandatory_exact_envelope_checklist(self) -> None:
        content = SKILL_PATH.read_text(encoding="utf-8")
        heading = "### Mandatory Exact-Envelope Checklist"
        self.assertEqual(1, content.count(heading))
        checklist = content.split(heading, 1)[1].split("\n### ", 1)[0]

        allowed = re.search(
            r"Allowed top-level keys \(complete allowlist\): `(\[[^`]+\])`",
            checklist,
        )
        required = re.search(
            r"Required top-level keys: `(\[[^`]+\])`",
            checklist,
        )
        self.assertIsNotNone(allowed)
        self.assertIsNotNone(required)
        self.assertEqual(
            [
                "schemaVersion",
                "summary",
                "hardGates",
                "judgeScores",
                "requirementAssessments",
                "causalLinks",
                "findings",
            ],
            json.loads(allowed.group(1)),
        )
        self.assertEqual(
            [
                "schemaVersion",
                "summary",
                "hardGates",
                "judgeScores",
                "findings",
            ],
            json.loads(required.group(1)),
        )
        self.assertIn("`additionalProperties=false`", checklist)
        self.assertIn(
            '`confidence` MUST be a JSON string: `"high"`, `"medium"`, '
            '`"low"`, or `"unknown"`.',
            checklist,
        )
        self.assertIn(
            "Numeric confidence values such as `1` or `0.95` are invalid",
            checklist,
        )
        self.assertIn('use `"evidenceIds": []`', checklist)
        self.assertIn('use `"confidence": "unknown"`', checklist)
        self.assertIn('use `"status": "unknown"`', checklist)
        self.assertIn('use `"score": null`', checklist)
        self.assertIn('use `"status": "unverified"`', checklist)
        self.assertIn(
            '`"hardGates": []`, `"judgeScores": []`, and `"findings": []`',
            checklist,
        )


if __name__ == "__main__":
    unittest.main()
