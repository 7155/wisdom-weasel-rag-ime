from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.build_managed_pi_runtime_v2 import (
    ROOT,
    _copy_product_skills,
    _runtime_host_banner,
)


class ManagedPiRuntimeV2BuildTests(unittest.TestCase):
    def test_payload_version_and_manifest_are_bound_to_the_product_commit(self) -> None:
        script = (ROOT / "scripts" / "build_managed_pi_runtime_v2.py").read_text(
            encoding="utf-8"
        )

        self.assertIn('product_commit.encode("ascii")', script)
        self.assertIn('"productCommit": product_commit', script)
        self.assertIn('manifest["createdAtMs"] = product_commit_ms', script)

    def test_input_method_project_owns_all_managed_skills(self) -> None:
        skills_root = ROOT / "integrations" / "pi" / "skills"
        skill_names = sorted(item.name for item in skills_root.iterdir() if item.is_dir())

        self.assertEqual(skill_names, ["rag-ime-memory-curator", "rag-ime-plugin-creator"])
        for name in skill_names:
            content = (skills_root / name / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn(f"name: {name}", content)
            self.assertIn("\nwhen:\n", content)
            self.assertIn("\ndoes: ", content)
            self.assertIn("\nnotFor:\n", content)

        routing_catalog = json.loads(
            (ROOT / "integrations" / "pi" / "skill-routing-cards.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            routing_catalog["schemaVersion"],
            "rag-ime.skill-routing-card-catalog.v1",
        )
        cards = routing_catalog["cards"]
        self.assertEqual(len(cards), 40)
        self.assertEqual(len({card["name"] for card in cards}), len(cards))
        for card in cards:
            self.assertTrue(card["when"])
            self.assertTrue(card["does"])
            compact = json.dumps(card, ensure_ascii=False, separators=(",", ":"))
            self.assertLessEqual(len(compact), 200, card["name"])

    def test_runtime_banner_loads_all_product_skills_without_enabling_global_discovery(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-runtime-skills-") as temporary:
            root = Path(temporary)
            (root / "rag-ime-memory-curator").mkdir()
            (root / "rag-ime-plugin-creator").mkdir()

            banner = _runtime_host_banner(root)

        self.assertIn('"rag-ime-memory-curator"', banner)
        self.assertIn('"rag-ime-plugin-creator"', banner)
        self.assertIn('process.env.RAG_IME_PI_SKILL_PATHS', banner)
        self.assertIn('process.env.RAG_IME_PI_SKILL_ROUTING_CARDS', banner)
        self.assertIn('skill-routing-cards.json', banner)
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
            "Question with no asserted durable information",
            "Failed, rejected, timed-out",
            "Curation protocol/status",
            "Repeated question or duplicate message",
            "verbatim",
            "fails closed",
            "agent_role_book",
            "propose_revision",
            "session is pinned",
            "cannot activate",
            "Do not run memory curation merely because the Agent is chatting",
            "task_completion",
            "explicit_request",
            "idle_batch",
            "do not call a memory",
        ):
            self.assertIn(required, skill)
        self.assertIn("native approval", agent_prompt)
        self.assertIn("fact-free questions", agent_prompt)
        self.assertIn("failed receipts", agent_prompt)
        self.assertIn("workflow noise", agent_prompt)
        self.assertIn("duplicate questions", agent_prompt)
        self.assertIn("Do not curate ordinary zhiyou-v1 chat turns", agent_prompt)
        self.assertIn("trigger=task_completion", agent_prompt)
        self.assertIn("never activate it", agent_prompt)


if __name__ == "__main__":
    unittest.main()
