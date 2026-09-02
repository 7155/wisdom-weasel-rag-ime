from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_PATH = (
    ROOT / "integrations" / "pi" / "skills" / "trace-agent-diagnostics" / "SKILL.md"
)
REPAIR_VERIFICATION_PATH = (
    SKILL_PATH.parent / "references" / "repair-verification.md"
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
                "presentation",
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
                "presentation",
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
        self.assertIn("`presentation` is the bounded plain-language scan layer", checklist)
        self.assertIn("`recordedStageReceiptEvidenceIds`", checklist)
        self.assertIn("`expectedStageCount: 0`", checklist)
        self.assertIn("no stage was expected", checklist)
        self.assertIn("`failureAttribution` is required for every new result", checklist)
        self.assertIn("five entries in order `tool`, `skill`, `template`, `workflow`, `model`", checklist)
        self.assertIn("Mark Tool `healthy` when a receipt proves the Tool effect worked", checklist)
        self.assertIn(
            "Do not blame the model until input, Skill, template/prompt, workflow, "
            "and Tool evidence is adequate",
            " ".join(checklist.split()),
        )
        self.assertIn('`workspaceRoots: ["/"]`', content)
        self.assertIn('`writeAuthority: "auto_approved_full_trust"`', content)
        self.assertNotIn("Luna Max", content)
        self.assertNotIn("workspace-fenced", content)

    def test_repair_verification_uses_direct_full_auto_authority(self) -> None:
        content = REPAIR_VERIFICATION_PATH.read_text(encoding="utf-8")
        self.assertIn('`toolProfileVersion: "control-center-auto-approve-v1"`', content)
        self.assertIn('`executionMode: "full_trust"`', content)
        self.assertIn('`workspaceRoots: ["/"]`', content)
        self.assertIn('`writeAuthority: "auto_approved_full_trust"`', content)
        self.assertNotIn("Pending operations are arbitrated", content)
        self.assertNotIn("model-arbitrated", content)
        self.assertNotIn("exact authorized workspace roots", content)


if __name__ == "__main__":
    unittest.main()
