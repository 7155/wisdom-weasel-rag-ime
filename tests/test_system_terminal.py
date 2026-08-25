from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from rag_ime.system_terminal import SCHEMA_VERSION, SystemTerminalError, SystemTerminalService


class SystemTerminalServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="paw-system-terminal-")
        self.root = Path(self.temporary.name)
        self.service = SystemTerminalService(default_cwd=self.root)

    def tearDown(self) -> None:
        self.service.close()
        self.temporary.cleanup()

    def test_real_pty_runs_command_and_returns_cursor_stream(self) -> None:
        created = self.service.create({"shell": "/bin/sh", "cols": 90, "rows": 24})
        terminal = created["terminal"]
        terminal_id = str(terminal["terminalId"])

        self.service.write({"terminalId": terminal_id, "text": "printf 'PAW_PTY_OK\\n'\n"})
        output = ""
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and "PAW_PTY_OK" not in output:
            receipt = self.service.read({"terminalId": terminal_id, "cursor": 0})
            output = str(receipt["text"])
            time.sleep(0.02)

        self.assertEqual(created["schemaVersion"], SCHEMA_VERSION)
        self.assertIn("PAW_PTY_OK", output)
        self.assertEqual(
            Path(str(self.service.list()["items"][0]["cwd"])).resolve(),
            self.root.resolve(),
        )
        resized = self.service.resize({"terminalId": terminal_id, "cols": 120, "rows": 40})
        self.assertEqual((resized["terminal"]["cols"], resized["terminal"]["rows"]), (120, 40))

        closed = self.service.close_terminal({"terminalId": terminal_id})
        self.assertEqual(closed["terminal"]["status"], "closed")
        self.assertEqual(self.service.list()["items"], [])

    def test_unknown_terminal_is_rejected(self) -> None:
        with self.assertRaisesRegex(SystemTerminalError, "not found"):
            self.service.read({"terminalId": "term_missing"})


if __name__ == "__main__":
    unittest.main()
