from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from rag_ime.cli import main


class CliForegroundPrivacyTests(unittest.TestCase):
    def _run(self, db_path: Path, *arguments: str) -> dict[str, object]:
        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(["--db-path", str(db_path), *arguments]), 0)
        return json.loads(output.getvalue())

    def test_commit_requires_explicit_allowed_disposition(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-cli-privacy-") as temp_dir:
            db_path = Path(temp_dir) / "privacy.sqlite"

            unknown = self._run(db_path, "commit", "不应落库")
            allowed = self._run(
                db_path,
                "commit",
                "明确允许落库",
                "--privacy-disposition",
                "allowed",
            )

            self.assertFalse(unknown["recorded"])
            self.assertEqual(unknown["event_id"], "skipped:privacy_unknown")
            self.assertTrue(allowed["recorded"])

    def test_action_without_disposition_is_a_no_store_receipt(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-cli-action-privacy-") as temp_dir:
            payload = self._run(
                Path(temp_dir) / "privacy.sqlite",
                "action-json",
                "accepted",
                "--memory-id",
                "memory:test",
            )

            self.assertTrue(payload["noStore"])
            self.assertFalse(payload["stored"])
            self.assertEqual(payload["storageReceipt"]["privacyDisposition"], "unknown")


if __name__ == "__main__":
    unittest.main()
