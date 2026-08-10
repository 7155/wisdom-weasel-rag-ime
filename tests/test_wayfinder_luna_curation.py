from __future__ import annotations

import json
import re
import sys
import unittest
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from curate_wayfinder_sources_luna import (  # noqa: E402
    CurationError,
    SCHEMA_VERSION,
    SKILL_IDS,
    validate_candidate,
)


AUDIT_PATH = (
    ROOT
    / "design-system/rag-ime-control-center/prototypes/room-navigation-wayfinder"
    / "reconciliation/wayfinder-luna-source-audit.v1.json"
)
SHA256 = re.compile(r"^[0-9a-f]{64}$")


class WayfinderLunaCurationTests(unittest.TestCase):
    def test_public_audit_is_complete_bounded_and_human_reviewed(self) -> None:
        audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
        inventory = audit["inventory"]
        receipt = audit["corpusReceipt"]
        serialized = json.dumps(audit, ensure_ascii=False, sort_keys=True)

        self.assertEqual("personal-agent.wayfinder-luna-source-audit.v1", audit["schemaVersion"])
        self.assertEqual("2026-08-04T23:59:59+08:00", audit["cutoff"])
        self.assertEqual("gpt-5.6-luna", audit["lunaRun"]["model"])
        self.assertEqual("max", audit["lunaRun"]["reasoningEffort"])
        self.assertTrue(audit["lunaRun"]["candidateSchemaValidated"])
        self.assertEqual("needs_human_resolution", audit["lunaRun"]["candidateVerdict"])

        self.assertEqual(receipt["historicalDocumentCount"], len(inventory["historicalDocuments"]))
        self.assertEqual(receipt["targetDraftCount"], len(inventory["targetDrafts"]))
        self.assertEqual(receipt["primarySessionCount"], len(inventory["primarySessions"]))
        self.assertEqual(receipt["gitCommitCount"], len(inventory["commits"]))
        self.assertEqual(
            receipt["sessionAliasRefCount"],
            sum(len(session["aliases"]) for session in inventory["primarySessions"]),
        )
        self.assertEqual(
            receipt["userMessageCount"],
            sum(session["userMessageCount"] for session in inventory["primarySessions"]),
        )

        for document in inventory["historicalDocuments"] + inventory["targetDrafts"]:
            self.assertRegex(document["sha256"], SHA256)
            self.assertGreater(document["byteCount"], 0)
        for session in inventory["primarySessions"]:
            self.assertRegex(session["userMessagesSha256"], SHA256)
            self.assertGreater(session["userMessageCount"], 0)
        for key in ("sourcePacketSha256",):
            self.assertRegex(receipt[key], SHA256)
        for key in ("promptSha256", "schemaSha256", "outputSha256"):
            self.assertRegex(audit["lunaRun"][key], SHA256)

        inventory_aliases = {
            session["id"]: session["aliases"]
            for session in inventory["primarySessions"]
            if session["aliases"]
        }
        reviewed_aliases = {
            group["canonicalSourceId"]: group["aliasRefs"]
            for group in audit["deduplication"]["exactAliasGroups"]
        }
        self.assertEqual(inventory_aliases, reviewed_aliases)
        self.assertIn("swapped", audit["deduplication"]["lunaCandidateCorrection"])
        self.assertEqual(
            [
                "Project 是长期空间",
                "Room 不是工单",
                "聚焦不离开项目",
                "导航只决定归属",
            ],
            audit["resultingCurrentRoom"]["decisionTitles"],
        )
        self.assertEqual(
            "implementation-execution",
            audit["resultingCurrentRoom"]["activeSkillStage"],
        )
        self.assertEqual(
            "not_verified",
            audit["humanReview"]["openQuestions"][0]["status"],
        )

        self.assertNotIn("/Users/", serialized)
        self.assertNotIn("/Volumes/", serialized)
        self.assertNotIn("/private/", serialized)
        self.assertNotIn('"boundedUserExcerpts":', serialized)
        self.assertNotIn('"userMessageLedger":', serialized)
        self.assertFalse(audit["privacy"]["rawChatIncluded"])
        self.assertFalse(audit["privacy"]["assistantReasoningIncluded"])

    def test_candidate_validation_rejects_reassigned_exact_alias(self) -> None:
        cutoff = "2026-08-04T23:59:59+08:00"
        alias = "agent-session:codex:019fc86c-1d2f-76b1-af75-bb4ac3708d52"
        candidate = {
            "schemaVersion": SCHEMA_VERSION,
            "cutoff": cutoff,
            "sourceAudit": {
                "includedSourceIds": ["session-canonical", "session-wrong"],
                "duplicateSessionGroups": [
                    {
                        "canonicalSourceId": "session-canonical",
                        "aliasRefs": [alias],
                        "reason": "exact source-packet alias",
                    }
                ],
                "sourceGaps": [],
            },
            "projectMap": {"rooms": [{"roomId": "project-field"}]},
            "currentRoomDocs": {
                "roomId": "project-field",
                "skillFlow": [{"id": skill_id} for skill_id in SKILL_IDS],
            },
        }
        kwargs = {
            "cutoff": cutoff,
            "room_ids": ["project-field"],
            "available_source_ids": {"session-canonical", "session-wrong"},
            "exact_session_aliases": {"session-canonical": [alias]},
        }

        validate_candidate(candidate, **kwargs)
        swapped = deepcopy(candidate)
        swapped["sourceAudit"]["duplicateSessionGroups"][0][
            "canonicalSourceId"
        ] = "session-wrong"
        with self.assertRaisesRegex(CurationError, "reassigned an exact alias"):
            validate_candidate(swapped, **kwargs)


if __name__ == "__main__":
    unittest.main()
