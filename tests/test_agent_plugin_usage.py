from __future__ import annotations

import json
import sqlite3
import unittest

from rag_ime.agent_plugin_usage import AgentPluginUsageStore
from rag_ime.contracts.json_schema import validate_contract


class AgentPluginUsageStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database_uri = f"file:plugin-usage-{id(self)}?mode=memory&cache=shared"
        self.anchor = sqlite3.connect(self.database_uri, uri=True)
        self.store = AgentPluginUsageStore(
            "unused.sqlite",
            connection_factory=lambda: sqlite3.connect(self.database_uri, uri=True),
        )
        self.store.initialize()

    def tearDown(self) -> None:
        self.anchor.close()

    @staticmethod
    def event(
        *,
        event_id: str,
        resource_kind: str = "tool",
        resource_id: str = "memory",
        activity: str = "loaded",
        invocation_id: str | None = None,
        outcome: str | None = None,
        duration_ms: int | None = None,
        occurred_at_ms: int = 100,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "schemaVersion": "paw.plugin-usage.v1",
            "eventId": event_id,
            "occurredAtMs": occurred_at_ms,
            "sessionId": "agent:test-session",
            "packageId": "@paw/test-package",
            "packageVersion": "1.2.3",
            "resourceKind": resource_kind,
            "resourceId": resource_id,
            "activity": activity,
        }
        if invocation_id is not None:
            payload["invocationId"] = invocation_id
        if outcome is not None:
            payload["outcome"] = outcome
        if duration_ms is not None:
            payload["durationMs"] = duration_ms
        return payload

    def test_records_loaded_invoked_and_terminal_aggregates_without_conflation(self) -> None:
        self.store.record(self.event(event_id="usage:load", activity="loaded"))
        self.store.record(
            self.event(
                event_id="usage:start",
                activity="invoked",
                invocation_id="invoke:1",
                occurred_at_ms=110,
            )
        )
        self.store.record(
            self.event(
                event_id="usage:end",
                activity="finished",
                invocation_id="invoke:1",
                outcome="succeeded",
                duration_ms=37,
                occurred_at_ms=147,
            )
        )

        snapshot = self.store.query(package_id="@paw/test-package")
        validate_contract(snapshot, "paw.plugin-usage-query.v1.json")

        self.assertEqual([item["activity"] for item in snapshot["events"]], ["finished", "invoked", "loaded"])
        self.assertEqual(
            snapshot["aggregates"],
            [{
                "packageId": "@paw/test-package",
                "packageVersion": "1.2.3",
                "resourceKind": "tool",
                "resourceId": "memory",
                "loadedCount": 1,
                "invocationCount": 1,
                "terminalCount": 1,
                "succeededCount": 1,
                "failedCount": 0,
                "cancelledCount": 0,
                "averageDurationMs": 37,
                "lastLoadedAtMs": 100,
                "lastInvokedAtMs": 110,
            }],
        )
        self.assertEqual(
            self.store.package_summary("@paw/test-package", package_version="1.2.3"),
            {
                "loadedSessionCount": 1,
                "lastLoadedAtMs": 100,
                "invocationCount": 1,
                "succeededCount": 1,
                "failedCount": 0,
                "cancelledCount": 0,
                "averageDurationMs": 37,
                "lastInvocation": {
                    "resourceKind": "tool",
                    "resourceName": "memory",
                    "sessionId": "agent:test-session",
                    "startedAtMs": 110,
                    "completedAtMs": 147,
                    "durationMs": 37,
                    "status": "succeeded",
                },
            },
        )
        self.assertEqual(
            self.store.package_summary("@paw/not-installed"),
            {
                "loadedSessionCount": 0,
                "lastLoadedAtMs": None,
                "invocationCount": 0,
                "succeededCount": 0,
                "failedCount": 0,
                "cancelledCount": 0,
                "averageDurationMs": None,
                "lastInvocation": None,
            },
        )

    def test_failure_and_cancel_are_distinct_terminal_outcomes(self) -> None:
        for index, (outcome, duration) in enumerate((("failed", 11), ("cancelled", 7)), start=1):
            invocation_id = f"invoke:{index}"
            self.store.record(self.event(event_id=f"usage:start:{index}", activity="invoked", invocation_id=invocation_id, occurred_at_ms=200 + index))
            self.store.record(self.event(event_id=f"usage:end:{index}", activity="finished", invocation_id=invocation_id, outcome=outcome, duration_ms=duration, occurred_at_ms=220 + index))

        aggregate = self.store.query()["aggregates"][0]
        self.assertEqual(aggregate["invocationCount"], 2)
        self.assertEqual(aggregate["failedCount"], 1)
        self.assertEqual(aggregate["cancelledCount"], 1)
        self.assertEqual(aggregate["averageDurationMs"], 9)

    def test_all_resource_kinds_allow_loaded_but_unsupported_activation_claims_are_rejected(self) -> None:
        for resource_kind in ("extension", "tool", "command", "skill", "prompt", "theme"):
            self.store.record(self.event(event_id=f"usage:{resource_kind}", resource_kind=resource_kind, resource_id=f"resource-{resource_kind}"))
        for resource_kind in ("extension", "theme"):
            with self.assertRaisesRegex(ValueError, f"{resource_kind}.*loaded"):
                self.store.record(self.event(event_id=f"usage:{resource_kind}-invoke", resource_kind=resource_kind, activity="invoked", invocation_id=f"invoke:{resource_kind}"))
        self.store.record(self.event(event_id="usage:prompt-invoke", resource_kind="prompt", activity="invoked", invocation_id="invoke:prompt"))
        with self.assertRaisesRegex(ValueError, "prompt.*terminal"):
            self.store.record(self.event(event_id="usage:prompt-end", resource_kind="prompt", activity="finished", invocation_id="invoke:prompt", outcome="succeeded", duration_ms=1))

        self.assertEqual(len(self.store.query()["events"]), 7)

    def test_rejects_forbidden_or_unknown_fields_before_sqlite_and_never_serializes_secrets(self) -> None:
        forbidden_values = [
            "SECRET_ARGUMENT_TOKEN",
            "SECRET_RESULT_TOKEN",
            "SECRET_PROMPT_TOKEN",
            "/Users/private/secret-file.txt",
            "SECRET_PAGE_CONTENT",
            "SECRET_CREDENTIAL",
        ]
        forbidden_fields = ("parameters", "result", "prompt", "filePath", "pageContent", "credential")
        for index, (field, value) in enumerate(zip(forbidden_fields, forbidden_values, strict=True)):
            payload = self.event(event_id=f"usage:forbidden:{index}")
            payload[field] = value
            with self.assertRaisesRegex(ValueError, "unsupported fields"):
                self.store.record(payload)
            with self.assertRaises(ValueError):
                validate_contract(payload, "paw.plugin-usage.v1.json")

        safe = self.event(event_id="usage:safe")
        self.store.record(safe)
        serialized = json.dumps(self.store.query(), ensure_ascii=False)
        with sqlite3.connect(self.database_uri, uri=True) as conn:
            stored = "\n".join(
                str(value)
                for row in conn.execute("SELECT * FROM agent_plugin_usage_events")
                for value in row
                if value is not None
            )
        for secret in forbidden_values:
            self.assertNotIn(secret, serialized)
            self.assertNotIn(secret, stored)

    def test_duplicate_is_idempotent_but_conflicting_event_id_is_rejected(self) -> None:
        payload = self.event(event_id="usage:duplicate")
        first = self.store.record(payload)
        second = self.store.record(payload)
        self.assertEqual(first, second)

        conflicting = dict(payload)
        conflicting["resourceId"] = "different-resource"
        with self.assertRaisesRegex(ValueError, "different event"):
            self.store.record(conflicting)
        self.assertEqual(len(self.store.query()["events"]), 1)

    def test_terminal_requires_matching_invocation_and_non_negative_duration(self) -> None:
        with self.assertRaisesRegex(ValueError, "matching invoked event"):
            self.store.record(self.event(event_id="usage:orphan", activity="finished", invocation_id="invoke:missing", outcome="failed", duration_ms=1))
        with self.assertRaisesRegex(ValueError, "durationMs"):
            self.store.record(self.event(event_id="usage:negative", activity="finished", invocation_id="invoke:negative", outcome="failed", duration_ms=-1))

if __name__ == "__main__":
    unittest.main()
