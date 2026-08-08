from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from scripts.run_swe_bench_agent_eval import (
    _DeferredToolGateway,
    _case_prompt,
    _public_model_state,
    main,
)


class RunSweBenchAgentEvalTests(unittest.TestCase):
    def test_prompt_uses_only_agent_case_and_preserves_hidden_verifier_boundary(self) -> None:
        prompt = _case_prompt(
            {
                "instanceId": "example__demo-1",
                "repo": "example/demo",
                "baseCommit": "a" * 40,
                "difficulty": "<15 min fix",
                "problemStatement": "Fix answer().",
                "hintsText": "Inspect demo.py.",
            },
            1,
        )

        self.assertIn("at most 1 read-only subagent", prompt)
        self.assertIn("no .git metadata", prompt)
        self.assertIn("Never create, edit, rename, or delete tests", prompt)
        self.assertNotIn("FAIL_TO_PASS", prompt)
        self.assertNotIn("goldPatch", prompt)

    def test_public_model_state_requires_provider_qualified_luna_identity(self) -> None:
        state = _public_model_state(
            {
                "state": {
                    "model": {"provider": "openai-codex", "id": "gpt-5.6-luna"},
                    "thinkingLevel": "max",
                    "protocolVersion": "2",
                }
            }
        )

        self.assertEqual(state["reference"], "openai-codex/gpt-5.6-luna")
        self.assertEqual(state["thinkingLevel"], "max")

    def test_deferred_gateway_fails_closed_until_bound(self) -> None:
        gateway = _DeferredToolGateway()
        with self.assertRaisesRegex(RuntimeError, "not bound"):
            gateway.execute({})

        class Target:
            @staticmethod
            def execute(payload):
                return {"ok": True, "value": payload["value"]}

        gateway.target = Target()  # type: ignore[assignment]
        self.assertEqual(gateway.execute({"value": 3})["value"], 3)

    def test_verifier_command_is_printed_without_executing_docker(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            predictions = Path(temporary) / "predictions.jsonl"
            stream = io.StringIO()
            with redirect_stdout(stream):
                exit_code = main(
                    [
                        "verifier-command",
                        "--predictions",
                        str(predictions),
                        "--instance-id",
                        "example__demo-1",
                        "--run-id",
                        "local-test",
                    ]
                )
        payload = json.loads(stream.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertIn("swebench.harness.run_evaluation", payload["argv"])
        self.assertNotIn("docker run", payload["shell"])


if __name__ == "__main__":
    unittest.main()
