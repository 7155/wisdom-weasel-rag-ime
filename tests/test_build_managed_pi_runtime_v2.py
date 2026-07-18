from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.build_managed_pi_runtime_v2 import (
    _copy_product_skills,
    _runtime_host_banner,
)


ROOT = Path(__file__).resolve().parents[1]


class ManagedPiRuntimeV2BuildTests(unittest.TestCase):
    def test_payload_version_and_manifest_are_bound_to_the_product_commit(self) -> None:
        script = (ROOT / "scripts" / "build_managed_pi_runtime_v2.py").read_text(
            encoding="utf-8"
        )

        self.assertIn('product_commit.encode("ascii")', script)
        self.assertIn('"productCommit": product_commit', script)
        self.assertIn('manifest["createdAtMs"] = product_commit_ms', script)

    def test_runtime_banner_loads_all_product_skills_without_enabling_global_discovery(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-runtime-skills-") as temporary:
            root = Path(temporary)
            (root / "rag-ime-memory-curator").mkdir()
            (root / "rag-ime-plugin-creator").mkdir()

            banner = _runtime_host_banner(root)

        self.assertIn('"rag-ime-memory-curator"', banner)
        self.assertIn('"rag-ime-plugin-creator"', banner)
        self.assertIn('process.env.RAG_IME_PI_SKILL_PATHS', banner)
        self.assertIn('__join(__ragImeRuntimeDir, "skills", name)', banner)
        self.assertNotIn("--no-skills", banner)

    def test_managed_payload_copies_memory_curator_governance_contract(self) -> None:
        source_root = ROOT / "integrations" / "pi" / "skills"
        with tempfile.TemporaryDirectory(prefix="rag-ime-runtime-skill-copy-") as temporary:
            runtime_root = Path(temporary) / "runtime-host" / "skills"
            copied = _copy_product_skills(source_root, runtime_root)
            skill_root = runtime_root / "rag-ime-memory-curator"
            skill = (skill_root / "SKILL.md").read_text(encoding="utf-8")
            agent_prompt = (skill_root / "agents" / "openai.yaml").read_text(
                encoding="utf-8"
            )

        self.assertIn("rag-ime-memory-curator", copied)
        for required in (
            "Evidence -> Current Atom -> Topic Book",
            "cross-App Task Timeline",
            "remember_preview",
            "remember_apply",
            "correct_preview",
            "correct_apply",
            "forget_preview",
            "forget_apply",
            "governance_rollback",
            "lineageId",
            "memory_supersessions",
            "not_for_memory",
            "fails closed",
            "agent_role_book",
            "propose_revision",
            "session is pinned",
            "cannot activate",
        ):
            self.assertIn(required, skill)
        self.assertIn("native approval", agent_prompt)
        self.assertIn("never activate it", agent_prompt)


if __name__ == "__main__":
    unittest.main()
