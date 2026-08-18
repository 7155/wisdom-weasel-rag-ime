import unittest

from rag_ime.tui import snapshot


class FakeService:
    def list_sessions(self, payload=None):
        return {"items": [{"id": "s1", "title": "Build"}]}

    def list_rooms(self, payload=None):
        return {"items": [{"id": "r1", "title": "Review"}]}


class TuiProjectionTests(unittest.TestCase):
    def test_snapshot_reads_session_and_room_projections(self):
        self.assertEqual(snapshot(FakeService()), {"sessions": [{"id": "s1", "title": "Build"}], "rooms": [{"id": "r1", "title": "Review"}]})


if __name__ == "__main__":
    unittest.main()
