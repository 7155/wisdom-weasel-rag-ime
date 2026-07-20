from __future__ import annotations

import json
import unittest
from pathlib import Path

from rag_ime.context_inspection import inspect_context_sequence, replay_context_jsonl


FIXTURE = Path(__file__).parent / "fixtures" / "room_context_inspection" / "replay.jsonl"
REAL_CANARY = FIXTURE.parent / "real-provider-canary-failed.v1.json"


def snapshot(
    session_id: str,
    tail: str,
    *,
    root_id: str = "root-alpha",
    generation: int = 2,
    role: str = "A",
    transition: str = "turn",
    usage: dict[str, int] | None = None,
) -> dict[str, object]:
    return {
        "sessionId": session_id,
        "rootId": root_id,
        "generation": generation,
        "role": role,
        "transition": transition,
        "layers": [
            {"name": "system", "content": "stable-system-v2"},
            {"name": "persona", "content": f"stable-persona:{role}"},
            {"name": "tools-skills", "content": "read,skill_load"},
            {"name": "sealed-room", "content": f"sealed:{root_id}:{role}"},
            {"name": "dynamic-tail", "content": tail},
        ],
        "sealedContributionRefs": [f"sealed:{root_id}:{role}"],
        "roomContributionRefs": [f"room:{root_id}:post"],
        "privateSessionRefs": [f"private:{session_id}"],
        "providerBody": f"Work on the current bounded objective for {role}.",
        "usage": usage or {"input": 20, "output": 4, "cacheRead": 10, "cacheWrite": 2},
    }


class ContextInspectionTests(unittest.TestCase):
    def test_synthetic_contract_shapes_keep_five_layer_prefixes_and_room_isolation(self) -> None:
        snapshots = [
            snapshot("ordinary-agent", "u1\n", root_id="", role="ordinary"),
            snapshot("ordinary-agent", "u1\na1\nu2\n", root_id="", role="ordinary"),
            snapshot("subagent", "sub-u1\n", root_id="", role="subagent"),
            snapshot("room-a", "post-1\n", role="A"),
            snapshot("room-a", "post-1\na-result\npost-2\n", role="A"),
            snapshot("room-b", "handoff-a-b\n", role="B"),
            snapshot("room-a", "post-1\na-result\npost-2\nhandoff-b-a\n", role="A"),
            snapshot("room-reviewer", "review-request\n", role="reviewer"),
            snapshot("room-a", "recovery-packet\n", role="A", transition="compaction"),
            snapshot("room-a", "recovery-packet\nnew-tail\n", role="A", transition="recovery"),
            snapshot("room-new", "new-root-post\n", root_id="root-beta", role="A"),
        ]

        report = inspect_context_sequence(snapshots)

        self.assertTrue(report["safe"], report["violations"])
        self.assertEqual(report["snapshotCount"], 11)
        self.assertTrue(all(row["prefixSha256"] for row in report["deltas"]))
        self.assertTrue(any(row["cacheReadTokens"] == 10 for row in report["cacheEvidence"]))
        self.assertTrue(all(row["capability"] == "reported" for row in report["cacheEvidence"]))

    def test_cache_capability_is_unsupported_when_provider_omits_fields(self) -> None:
        item = snapshot("ordinary", "u1\n", root_id="", role="ordinary", usage={"input": 8, "output": 2})

        report = inspect_context_sequence([item])

        self.assertEqual(report["cacheEvidence"][0]["capability"], "unsupported")
        self.assertEqual(report["cacheEvidence"][0]["cacheReadTokens"], 0)

    def test_internal_projection_noise_and_cross_root_leak_fail_closed(self) -> None:
        item = snapshot("room-new", "new\n", root_id="root-beta", role="A")
        item["providerBody"] = '{"score":0.9,"rootId":"root-alpha"}'

        report = inspect_context_sequence([snapshot("room-a", "old\n"), item])

        self.assertFalse(report["safe"])
        self.assertIn("provider_body_internal_noise", {row["code"] for row in report["violations"]})
        self.assertIn("old_root_leaked", {row["code"] for row in report["violations"]})

    def test_jsonl_replay_ignores_duplicates_old_generation_and_truncated_crash_tail(self) -> None:
        replay = replay_context_jsonl(FIXTURE.read_text(encoding="utf-8").splitlines())

        self.assertEqual(replay["activeGeneration"], {"root-alpha": 2})
        self.assertIn("old-generation", replay["ignoredEventIds"])
        self.assertIn("post-2", replay["ignoredEventIds"])
        self.assertTrue(replay["recoveredFromTruncatedTail"])

    def test_real_provider_failure_fixture_never_claims_cache_support_or_hit(self) -> None:
        evidence = json.loads(REAL_CANARY.read_text(encoding="utf-8"))

        self.assertTrue(evidence["providerContextAvailable"])
        self.assertGreater(evidence["systemPromptBytes"], 8_000)
        self.assertEqual(evidence["assistantStopReason"], "error")
        self.assertFalse(evidence["providerUsageReported"])
        self.assertFalse(evidence["providerCacheFieldsReported"])
        self.assertFalse(evidence["stableHitProven"])
        self.assertEqual(evidence["verdict"], "inconclusive_provider_unreachable")


if __name__ == "__main__":
    unittest.main()
