from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DelegatedRagBenchmarkAgentCanaryTests(unittest.TestCase):
    def test_canary_does_not_use_retired_room_skill_policy(self) -> None:
        source = (
            ROOT / "scripts" / "canary_delegated_rag_benchmark_agent.py"
        ).read_text(encoding="utf-8")

        self.assertNotIn("service.room_skill_policy", source)
        self.assertIn("governed_skills=None", source)
        self.assertNotIn("service.delegation.delegate(", source)
        self.assertIn('"tool": "agents"', source)
        self.assertIn("server.tool_gateway_url", source)

    def test_canary_accepts_an_explicit_verified_runtime_payload(self) -> None:
        source = (
            ROOT / "scripts" / "canary_delegated_rag_benchmark_agent.py"
        ).read_text(encoding="utf-8")

        self.assertIn('"--pi-runtime-payload"', source)
        self.assertIn("args.pi_runtime_payload.expanduser().resolve", source)
        self.assertIn("runtime_payload=runtime_payload", source)


if __name__ == "__main__":
    unittest.main()
