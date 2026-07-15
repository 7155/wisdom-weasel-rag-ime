from __future__ import annotations

import subprocess
import unittest
from unittest.mock import patch

from rag_ime.keychain_secrets import read_keychain_secret


class KeychainSecretsTests(unittest.TestCase):
    @patch("rag_ime.keychain_secrets.subprocess.run")
    @patch("rag_ime.keychain_secrets.shutil.which", return_value="/usr/bin/security")
    def test_read_timeout_is_treated_as_not_configured(self, _which, run) -> None:
        run.side_effect = subprocess.TimeoutExpired(cmd=["security"], timeout=5)

        self.assertEqual(read_keychain_secret("service", "account"), "")


if __name__ == "__main__":
    unittest.main()
