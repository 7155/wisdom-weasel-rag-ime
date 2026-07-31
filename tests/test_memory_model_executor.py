from __future__ import annotations

import unittest

from rag_ime.memory_model_executor import (
    GovernedMemoryModelExecutor,
    MemoryModelUnavailable,
)


class FakeMemoryRuntime:
    def __init__(self, models: list[dict[str, object]]) -> None:
        self.models = models
        self.requests: list[dict[str, object]] = []

    def available_models(self) -> list[dict[str, object]]:
        return [dict(model) for model in self.models]

    def complete_once(self, **kwargs: object) -> dict[str, object]:
        self.requests.append(dict(kwargs))
        return {
            "text": '{"decisions": []}',
            "modelId": kwargs["model_id"],
            "thinkingLevel": kwargs["thinking_level"],
            "elapsedMs": 12,
        }


class GovernedMemoryModelExecutorTests(unittest.TestCase):
    def test_selected_model_and_thinking_reach_managed_completion(self) -> None:
        runtime = FakeMemoryRuntime(
            [
                {
                    "provider": "gpt",
                    "id": "gpt-5.6-luna",
                    "thinkingLevels": ["off", "high", "max"],
                }
            ]
        )
        executor = GovernedMemoryModelExecutor(
            runtime,
            "gpt",
            "gpt-5.6-luna",
            "max",
        )

        response = executor.complete(
            messages=[{"role": "user", "content": "organize"}],
            max_tokens=256,
        )

        self.assertEqual(runtime.requests[0]["provider"], "gpt")
        self.assertEqual(runtime.requests[0]["model_id"], "gpt-5.6-luna")
        self.assertEqual(runtime.requests[0]["thinking_level"], "max")
        self.assertIn('"messages"', str(runtime.requests[0]["message"]))
        self.assertEqual(response["model"], "gpt-5.6-luna")
        self.assertEqual(response["thinkingLevel"], "max")

    def test_unavailable_model_fails_closed_without_a_request(self) -> None:
        runtime = FakeMemoryRuntime(
            [
                {
                    "provider": "gpt",
                    "id": "gpt-5.6-sol",
                    "thinkingLevels": ["max"],
                }
            ]
        )

        with self.assertRaisesRegex(MemoryModelUnavailable, "gpt/gpt-5.6-luna"):
            GovernedMemoryModelExecutor(
                runtime,
                "gpt",
                "gpt-5.6-luna",
                "max",
            )

        self.assertEqual(runtime.requests, [])


if __name__ == "__main__":
    unittest.main()
