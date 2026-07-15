from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "install_mineru_launch_agent.sh"


class MinerULaunchAgentScriptTests(unittest.TestCase):
    def test_installs_an_isolated_loopback_only_service(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")

        self.assertIn('HOST="127.0.0.1"', source)
        self.assertIn('PORT="${RAG_IME_MINERU_PORT:-30001}"', source)
        self.assertIn('PACKAGE_SPEC="${RAG_IME_MINERU_PACKAGE_SPEC:-mineru[all]>=3.4,<3.5}"', source)
        self.assertIn('MINERU_API_MAX_CONCURRENT_REQUESTS', source)
        self.assertIn('MINERU_PROCESSING_WINDOW_SIZE', source)
        self.assertIn('HF_HOME', source)
        self.assertIn('MODELSCOPE_CACHE', source)
        self.assertIn('MINERU_MODEL_SOURCE', source)
        self.assertIn('"mineru.cli.fast_api"', source)
        self.assertNotIn("0.0.0.0", source)

    def test_health_check_does_not_use_a_proxy_or_cloud_endpoint(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")

        self.assertIn('urllib.request.ProxyHandler({})', source)
        self.assertIn('http://127.0.0.1:{sys.argv[1]}/health', source)
        self.assertNotIn("mineru.net", source)


if __name__ == "__main__":
    unittest.main()
