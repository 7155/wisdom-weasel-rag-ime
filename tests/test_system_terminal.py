from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import call, patch

from rag_ime.system_terminal import SCHEMA_VERSION, SystemTerminalError, SystemTerminalService


class SystemTerminalServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="paw-system-terminal-")
        self.root = Path(self.temporary.name)
        self.service = SystemTerminalService(default_cwd=self.root)

    def tearDown(self) -> None:
        self.service.close()
        self.temporary.cleanup()

    def test_failed_spawn_closes_each_pty_descriptor_once(self) -> None:
        with (
            patch(
                "rag_ime.system_terminal.os.openpty",
                return_value=(70, 71),
            ),
            patch.object(
                self.service,
                "_set_size",
            ),
            patch(
                "rag_ime.system_terminal.subprocess.Popen",
                side_effect=OSError("simulated spawn failure"),
            ),
            patch(
                "rag_ime.system_terminal.os.close",
            ) as close_descriptor,
        ):
            with self.assertRaisesRegex(
                OSError,
                "simulated spawn failure",
            ):
                self.service.create({"shell": "/bin/sh"})

        self.assertEqual(
            close_descriptor.call_args_list,
            [call(70), call(71)],
        )

    def test_failed_pty_configuration_closes_each_descriptor(self) -> None:
        with (
            patch(
                "rag_ime.system_terminal.os.openpty",
                return_value=(80, 81),
            ),
            patch.object(
                self.service,
                "_set_size",
                side_effect=OSError("simulated pty configuration failure"),
            ),
            patch(
                "rag_ime.system_terminal.os.close",
            ) as close_descriptor,
        ):
            with self.assertRaisesRegex(
                OSError,
                "simulated pty configuration failure",
            ):
                self.service.create({"shell": "/bin/sh"})

        self.assertEqual(
            close_descriptor.call_args_list,
            [call(80), call(81)],
        )

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
