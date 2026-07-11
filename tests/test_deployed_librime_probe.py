from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "probe_deployed_librime_candidates.sh"
SOURCE = ROOT / "scripts" / "support" / "rime_candidate_probe.c"
INSTALLED_APP = Path.home() / "Library" / "Input Methods" / "Squirrel.app"
PREPARED_HEADERS = Path("/tmp/rag-ime-squirrel/librime/dist/include/rime_api.h")


class DeployedLibrimeProbeTests(unittest.TestCase):
    def test_probe_is_read_only_and_checks_real_librime_candidates(self) -> None:
        script = SCRIPT.read_text(encoding="utf-8")
        source = SOURCE.read_text(encoding="utf-8")

        self.assertIn("INPUTS=(yon yong)", script)
        self.assertIn("librime.1.dylib", script)
        self.assertIn("api->simulate_key_sequence", source)
        self.assertIn("api->get_context", source)
        self.assertNotIn("api->select_candidate", source)
        self.assertNotIn("api->commit_composition", source)

    @unittest.skipUnless(
        INSTALLED_APP.is_dir() and PREPARED_HEADERS.is_file(),
        "requires installed Squirrel and a prepared Squirrel workdir",
    )
    def test_deployed_yon_and_yong_have_expected_first_candidate(self) -> None:
        result = subprocess.run(
            [str(SCRIPT)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=20,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("yon\t用", result.stdout)
        self.assertIn("yong\t用", result.stdout)
        self.assertIn("[OK] deployed librime candidate probe passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
