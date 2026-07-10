from __future__ import annotations

import unittest

from rag_ime.management_events import ManagementEventHub


class ManagementEventTests(unittest.TestCase):
    def test_sse_subscription_is_event_driven(self) -> None:
        hub = ManagementEventHub()
        stream = hub.subscribe(heartbeat_seconds=0.01)

        self.assertEqual(next(stream), b": connected\n\n")
        hub.publish("runtime_health_changed", {"ok": True})
        event = next(stream)

        self.assertIn(b"event: runtime_health_changed", event)
        self.assertIn(b'"type":"runtime_health_changed"', event)
        stream.close()
        self.assertEqual(hub.subscriber_count, 0)


if __name__ == "__main__":
    unittest.main()
