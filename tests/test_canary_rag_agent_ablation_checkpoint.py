from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.canary_rag_agent_ablation_checkpoint import main


class CanaryRagAgentAblationCheckpointTests(unittest.TestCase):
    def test_validation_checkpoint_resume_canary_is_deterministic_and_public(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            first_path = root / "first.json"
            second_path = root / "second.json"

            self.assertEqual(0, main(["--output", str(first_path)]))
            self.assertEqual(0, main(["--output", str(second_path)]))

            first_bytes = first_path.read_bytes()
            second_bytes = second_path.read_bytes()
            receipt = json.loads(first_bytes)

        self.assertEqual(first_bytes, second_bytes)
        self.assertEqual(
            "rag-ime.rag-agent-ablation-checkpoint-canary.v1",
            receipt["schemaVersion"],
        )
        self.assertTrue(receipt["passed"])
        self.assertFalse(receipt["scoreEligible"])
        self.assertFalse(receipt["formalAcceptanceEligible"])
        self.assertFalse(receipt["formalAcceptancePassed"])
        self.assertEqual("validation", receipt["evaluation"]["split"])
        self.assertFalse(receipt["evaluation"]["heldOutAccessed"])
        self.assertFalse(receipt["evaluation"]["heldOutConsumed"])
        self.assertEqual(
            ["baseline", "skill"],
            receipt["canary"]["reusedAfterExplicitResume"],
        )
        self.assertEqual(
            ["baseline", "skill", "tuned", "agentic"],
            receipt["canary"]["finalReusableLanes"],
        )
        self.assertEqual(6, receipt["checkpoint"]["attemptCount"])
        self.assertEqual(6, receipt["checkpoint"]["startedReceiptCount"])
        self.assertEqual(12, receipt["checkpoint"]["bindingReceiptCount"])
        self.assertEqual(
            1, receipt["checkpoint"]["orphanRecoveryReceiptCount"]
        )
        self.assertEqual(1, receipt["checkpoint"]["recoveredOrphanCount"])
        self.assertEqual(0, receipt["checkpoint"]["blockedOrphanCount"])
        self.assertFalse(receipt["checkpoint"]["recoveryFailClosed"])
        self.assertEqual(5, receipt["checkpoint"]["terminalReceiptCount"])
        self.assertEqual(1, receipt["checkpoint"]["interruptedAttemptCount"])
        self.assertEqual(4, receipt["checkpoint"]["completedLaneCount"])
        self.assertEqual(2, receipt["checkpoint"]["reusedLaneCount"])
        self.assertEqual(2, receipt["checkpoint"]["freshLaneCount"])
        self.assertEqual(2, receipt["checkpoint"]["retriedLaneCount"])
        terminals = [
            (
                item["lane"],
                item["attempt"],
                item["terminalEvent"],
                item["runtimeFailureCategory"],
                item["lifecycleState"],
            )
            for item in receipt["checkpoint"]["attemptHistory"]
        ]
        self.assertEqual(
            [
                ("baseline", 1, "turn_completed", "", "terminal"),
                ("skill", 1, "turn_completed", "", "terminal"),
                (
                    "tuned",
                    1,
                    "turn_failed",
                    "provider_transient_after_tool",
                    "terminal",
                ),
                ("agentic", 1, "", "interrupted", "interrupted"),
                ("tuned", 2, "turn_completed", "", "terminal"),
                ("agentic", 2, "turn_completed", "", "terminal"),
            ],
            terminals,
        )
        self.assertTrue(
            all(item["startReceiptSha256"] for item in receipt["checkpoint"]["attemptHistory"])
        )
        tuned_attempts = [
            item
            for item in receipt["checkpoint"]["attemptHistory"]
            if item["lane"] == "tuned"
        ]
        self.assertNotEqual(
            tuned_attempts[0]["sessionSha256"],
            tuned_attempts[1]["sessionSha256"],
        )
        agentic_attempts = [
            item
            for item in receipt["checkpoint"]["attemptHistory"]
            if item["lane"] == "agentic"
        ]
        self.assertTrue(agentic_attempts[0]["sessionSha256"])
        self.assertTrue(agentic_attempts[0]["turnSha256"])
        self.assertTrue(agentic_attempts[1]["sessionSha256"])
        self.assertNotEqual(
            agentic_attempts[0]["sessionSha256"],
            agentic_attempts[1]["sessionSha256"],
        )
        recovery = receipt["checkpoint"]["orphanRecoveryHistory"][0]
        self.assertEqual("agentic", recovery["lane"])
        self.assertEqual(1, recovery["attempt"])
        self.assertEqual("recovered", recovery["status"])
        self.assertEqual("recovered", recovery["sessionRecovery"]["status"])
        self.assertEqual("recovered", recovery["sandboxRecovery"]["status"])
        self.assertTrue(receipt["canary"]["recoveryCallbacksSimulated"])
        self.assertFalse(receipt["canary"]["liveSessionCancellationVerified"])
        serialized = json.dumps(receipt, ensure_ascii=False, sort_keys=True)
        self.assertNotIn("agent:canary", serialized)
        self.assertNotIn("turn:canary", serialized)
        self.assertNotIn("private assistant", serialized)
        self.assertNotIn("/Volumes/", serialized)
        self.assertNotIn("/private/tmp/rag-checkpoint-canary", serialized)


if __name__ == "__main__":
    unittest.main()
