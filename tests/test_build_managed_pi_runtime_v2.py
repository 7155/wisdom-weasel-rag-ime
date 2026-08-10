from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from scripts.build_managed_pi_runtime_v2 import (
    BUNDLED_SKILL_SUPPORT_DIRS,
    MAX_ROUTING_CARD_CHARS,
    PROJECT_ROUTING_SKILLS,
    ROUTING_CARD_FIELDS,
    SKILL_ROUTING_CARDS,
    _OAUTH_RUNTIME_MODULES,
    ROOT,
    REQUIRED_GOAL_RUNTIME_SOURCE_MARKERS,
    REQUIRED_PI_RUNTIME_BASE_COMMIT,
    _ROOM_RUNTIME_SOURCE_KEYS,
    _copy_product_skills,
    _default_pi_worktree,
    _default_node,
    _product_skill_dirs,
    _resolve_skill_source_collisions,
    _runtime_host_banner,
    _smoke_oauth_runtime_modules,
    _validated_skill_routing_catalog,
    _verified_room_runtime_contract,
)
from rag_ime.managed_pi_runtime import ManagedPiRuntimeError


class ManagedPiRuntimeV2BuildTests(unittest.TestCase):
    def test_room_runtime_source_contract_pins_all_required_runtime_surfaces(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-room-host-contract-") as temporary:
            root = Path(temporary)
            relative_sources = {
                "protocol": Path("packages/rag-ime-runtime-host/src/protocol.ts"),
                "runtimeHost": Path("packages/rag-ime-runtime-host/src/runtime-host.ts"),
                "providerContextHook": Path("packages/coding-agent/src/core/sdk.ts"),
                "agentLoop": Path("packages/agent/src/agent-loop.ts"),
                "agentCore": Path("packages/agent/src/agent.ts"),
                "agentTypes": Path("packages/agent/src/types.ts"),
                "agentSession": Path("packages/coding-agent/src/core/agent-session.ts"),
                "contextInspection": Path("packages/rag-ime-runtime-host/src/debug-context.ts"),
                "skills": Path("packages/coding-agent/src/core/skills.ts"),
                "discoveryTools": Path("packages/rag-ime-runtime-host/src/discovery-tools.ts"),
                "memoryCapture": Path(
                    "packages/rag-ime-runtime-host/src/memory-capture-tool.ts"
                ),
                "roomToolBootstrap": Path(
                    "packages/rag-ime-runtime-host/src/room-tool-bootstrap.ts"
                ),
                "runtimeToolNames": Path(
                    "packages/rag-ime-runtime-host/src/runtime-tool-names.ts"
                ),
                "ask": Path("packages/rag-ime-runtime-host/src/ask.ts"),
                "toolBridge": Path("packages/rag-ime-runtime-host/src/tool-bridge.ts"),
                "toolArtifacts": Path("packages/rag-ime-runtime-host/src/tool-artifact-buffer.ts"),
                "providerContextJournal": Path(
                    "packages/rag-ime-runtime-host/src/provider-context-journal.ts"
                ),
                "sessionContextRefresh": Path(
                    "packages/rag-ime-runtime-host/src/session-context-refresh.ts"
                ),
                "summarizationCompletion": Path(
                    "packages/coding-agent/src/core/compaction/summarization-completion.ts"
                ),
                "cancellationReceipts": Path(
                    "packages/rag-ime-runtime-host/src/cancellation-receipts.ts"
                ),
                "roomSettleLifecycle": Path(
                    "packages/rag-ime-runtime-host/src/room-settle-lifecycle.ts"
                ),
                "workflowControl": Path(
                    "packages/rag-ime-runtime-host/src/workflow-control.ts"
                ),
                "lifecycleHooks": Path(
                    "packages/rag-ime-runtime-host/src/lifecycle-hooks.ts"
                ),
                "deterministicTestAdapter": Path(
                    "packages/rag-ime-runtime-host/src/deterministic-test-adapter.ts"
                ),
                "session": Path("packages/rag-ime-runtime-host/src/pi-session.ts"),
            }
            self.assertEqual(set(relative_sources), set(_ROOM_RUNTIME_SOURCE_KEYS))
            markers = {key: [f"marker:{key}"] for key in _ROOM_RUNTIME_SOURCE_KEYS}
            for key, relative in relative_sources.items():
                source = root / relative
                source.parent.mkdir(parents=True, exist_ok=True)
                extra = ""
                if key == "protocol":
                    extra = (
                        'export type RuntimeMethod = | "session.control_state" '
                        '| "room.dispatch" | "room.cancel";\n'
                    )
                elif key == "runtimeHost":
                    extra = (
                        'switch (method) { case "session.control_state": break; '
                        'case "room.dispatch": break; '
                        'case "room.cancel": break; }\n'
                    )
                source.write_text(f"// marker:{key}\n{extra}", encoding="utf-8")
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=Room Test",
                    "-c",
                    "user.email=room@example.invalid",
                    "commit",
                    "-qm",
                    "room handlers",
                ],
                cwd=root,
                check=True,
            )
            commit = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=root,
                check=True,
                text=True,
                stdout=subprocess.PIPE,
            ).stdout.strip()
            contract_path = root / "room-runtime-host-contract.json"
            adapter_path = root / "room-runtime-host.ts"
            contract_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": "rag-ime.pi-room-runtime-host-contract.v1",
                        "sourceRepository": "https://github.com/7155/pi.git",
                        "sourcePackage": "@earendil-works/pi-rag-ime-runtime-host",
                        "protocolVersion": "2",
                        "minimumHandlersCommit": commit,
                        "requiredMethods": [
                            "session.control_state",
                            "room.dispatch",
                            "room.cancel",
                        ],
                        "handlerSources": {
                            key: relative.as_posix()
                            for key, relative in relative_sources.items()
                        },
                        "requiredSourceMarkers": markers,
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            adapter_path.write_text(
                (
                    'export const methods = ["session.control_state", '
                    '"room.dispatch", "room.cancel"] as const;\n'
                ),
                encoding="utf-8",
            )
            with (
                patch("scripts.build_managed_pi_runtime_v2.ROOM_RUNTIME_CONTRACT", contract_path),
                patch("scripts.build_managed_pi_runtime_v2.ROOM_RUNTIME_ADAPTER", adapter_path),
                patch(
                    "scripts.build_managed_pi_runtime_v2.REQUIRED_PI_RUNTIME_BASE_COMMIT",
                    commit,
                ),
                patch(
                    "scripts.build_managed_pi_runtime_v2.REQUIRED_GOAL_RUNTIME_SOURCE_MARKERS",
                    {
                        key: (f"marker:{key}",)
                        for key in ("providerContextJournal", "workflowControl", "session")
                    },
                ),
            ):
                contract, digest = _verified_room_runtime_contract(root)
                (root / relative_sources["skills"]).write_text(
                    "// required marker removed\n",
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(
                    RuntimeError,
                    "source marker is missing: skills",
                ):
                    _verified_room_runtime_contract(root)

        self.assertEqual(contract["minimumHandlersCommit"], commit)
        self.assertEqual(len(digest), 64)

    def test_public_pi_pin_requires_goal_settle_and_memory_refresh_hooks(self) -> None:
        contract_path = ROOT / "integrations" / "pi" / "room-runtime-host-contract.json"
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        release_guide = (ROOT / "release" / "README.md").read_text(encoding="utf-8")
        product_status = json.loads(
            (ROOT / "release" / "product-status.json").read_text(encoding="utf-8")
        )

        self.assertEqual(
            contract["minimumHandlersCommit"],
            REQUIRED_PI_RUNTIME_BASE_COMMIT,
        )
        self.assertIn(f"git checkout {REQUIRED_PI_RUNTIME_BASE_COMMIT}", release_guide)
        declared_markers = contract["requiredSourceMarkers"]
        for key, required in REQUIRED_GOAL_RUNTIME_SOURCE_MARKERS.items():
            with self.subTest(source=key):
                self.assertTrue(set(required).issubset(declared_markers[key]))

        blockers = {item["id"] for item in product_status["blockers"]}
        self.assertIn("managed_pi_0fd0564_runtime_acceptance_pending", blockers)
        source_contract = next(
            item
            for item in product_status["resolvedBlockers"]
            if item["id"] == "managed_pi_v2_source_contract"
        )
        self.assertIn(REQUIRED_PI_RUNTIME_BASE_COMMIT, source_contract["evidence"])
        self.assertIn("not runtime acceptance evidence", source_contract["evidence"])

    def test_default_pi_worktree_prefers_canonical_main_checkout(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-pi-worktree-") as temporary:
            workspace = Path(temporary)
            canonical = workspace / "pi"
            legacy = workspace / "pi-rag-ime-runtime"
            (canonical / "packages" / "rag-ime-runtime-host").mkdir(parents=True)
            (legacy / "packages" / "rag-ime-runtime-host").mkdir(parents=True)

            self.assertEqual(_default_pi_worktree(workspace), canonical)

            (canonical / "packages" / "rag-ime-runtime-host").rmdir()
            self.assertEqual(_default_pi_worktree(workspace), legacy)

    def test_oauth_runtime_smoke_loads_every_lazy_module_and_derives_codex_auth(
        self,
    ) -> None:
        node = Path(_default_node())
        if not node.is_file():
            self.skipTest("Node runtime is unavailable")
        with tempfile.TemporaryDirectory(prefix="rag-ime-oauth-runtime-") as temporary:
            runtime_dir = Path(temporary)
            for output_name, (_source, export_name) in _OAUTH_RUNTIME_MODULES.items():
                if export_name == "openaiCodexOAuth":
                    body = (
                        "export const openaiCodexOAuth = {"
                        "async toAuth(credential) { return {apiKey: credential.access}; }"
                        "};\n"
                    )
                elif export_name == "createRadiusOAuth":
                    body = "export function createRadiusOAuth() { return {}; }\n"
                else:
                    body = f"export const {export_name} = {{}};\n"
                (runtime_dir / output_name).write_text(body, encoding="utf-8")

            result = _smoke_oauth_runtime_modules(node, runtime_dir)

        self.assertEqual(
            result,
            {"ok": True, "moduleCount": len(_OAUTH_RUNTIME_MODULES)},
        )
        self.assertEqual(
            set(_OAUTH_RUNTIME_MODULES),
            {
                "anthropic.ts",
                "github-copilot.ts",
                "openai-codex.ts",
                "radius.ts",
            },
        )

    def test_payload_version_and_manifest_are_bound_to_the_product_commit(self) -> None:
        script = (ROOT / "scripts" / "build_managed_pi_runtime_v2.py").read_text(
            encoding="utf-8"
        )
        adapter = (ROOT / "integrations" / "pi" / "room-runtime-host.ts").read_text(
            encoding="utf-8"
        )

        self.assertIn('product_commit.encode("ascii")', script)
        self.assertIn('"productCommit": product_commit', script)
        self.assertIn('manifest["createdAtMs"] = product_commit_ms', script)
        self.assertIn("_verified_room_runtime_contract", script)
        self.assertIn("source_contract_sha256=room_runtime_contract_sha256", script)
        for method in ("session.control_state", "room.dispatch", "room.cancel"):
            self.assertIn(f'"{method}"', adapter)

    def test_staged_smoke_uses_current_dispatch_and_continuation_contract(self) -> None:
        script = (ROOT / "scripts" / "smoke_room_v2_staged_runtime.py").read_text(
            encoding="utf-8"
        )

        self.assertEqual(script.count('"capabilityEpoch": 1,'), 4)
        self.assertEqual(script.count('"dispatchId": "dispatch:a"'), 3)
        self.assertEqual(script.count('"dispatchAttempt": 0,'), 2)
        self.assertIn('"idempotencyKey": "root:staged-e2e/continuation-b"', script)
        self.assertIn('"roomContext": room_context', script)
        self.assertIn('"roomRecoveryContext": room_context', script)
        self.assertIn('"manifestSha256": manifest_sha256', script)
        self.assertIn('"stage": "implementation"', script)
        self.assertIn('"workspace_read",', script)
        self.assertIn('"modelVisible": False', script)
        self.assertIn('"nativeCodingToolSchemas": sorted(native_schema_names)', script)
        self.assertIn('forbidden_native_schema_names = {"edit", "write"}', script)
        self.assertIn("active_schema_names & forbidden_native_schema_names", script)
        self.assertNotIn('"name": "room_post"', script)
        for method in (
            "session.open",
            "room.dispatch",
            "session.debug.context",
            "room.cancel",
        ):
            self.assertIn(f'"{method}"', script)

    def test_product_owns_all_managed_skills(self) -> None:
        skills_root = ROOT / "integrations" / "pi" / "skills"
        skill_dirs = _product_skill_dirs(skills_root)
        skill_names = [item.name for item in skill_dirs]

        room_policy = json.loads(
            (ROOT / "integrations" / "pi" / "room-skill-policy.json").read_text(
                encoding="utf-8"
            )
        )
        room_skill_names = sorted(entry["skillId"] for entry in room_policy["skills"])
        self.assertEqual(
            skill_names,
            sorted({
                "implementation-execution",
                "improve-codebase-architecture",
                "quality-gate",
                "rag-retrieval-optimization",
                "memory-curation",
                "plugin-creator",
                "work-document-archive",
                "review-feedback-resolution",
                *room_skill_names,
            }),
        )
        for name in skill_names:
            content = (skills_root / name / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn(f"name: {name}", content)
            self.assertIn("\ndescription: ", content)
            if name != "rag-retrieval-optimization":
                self.assertIn("\nwhen:\n", content)
                self.assertIn("\ndoes: ", content)
                self.assertIn("\nnotFor:\n", content)

        routing_catalog = _validated_skill_routing_catalog(
            SKILL_ROUTING_CARDS,
            skills_root,
        )
        self.assertEqual(
            routing_catalog["schemaVersion"],
            "rag-ime.skill-routing-card-catalog.v1",
        )
        self.assertEqual(
            routing_catalog["collisionPolicy"],
            {
                "default": "reject",
                "bundledWins": {
                    "configured": [],
                    "pi-installed": sorted(skill_names),
                },
            },
        )
        self.assertEqual(
            routing_catalog["scope"],
            {
                "bundledSkillEntries": len(skill_dirs),
                "projectedBundledCards": len(PROJECT_ROUTING_SKILLS),
                "canonicalCards": len(routing_catalog["cards"]),
            },
        )
        cards = routing_catalog["cards"]
        self.assertEqual(len(cards), 40)
        self.assertEqual(len({card["name"] for card in cards}), len(cards))
        self.assertTrue(set(room_skill_names).isdisjoint({card["name"] for card in cards}))
        self.assertNotIn("structured-result-presentation", {card["name"] for card in cards})
        for card in cards:
            self.assertTrue(card["when"])
            self.assertTrue(card["does"])
            compact = json.dumps(card, ensure_ascii=False, separators=(",", ":"))
            self.assertLessEqual(len(compact), MAX_ROUTING_CARD_CHARS, card["name"])
            self.assertNotIn("file://", compact)
            self.assertNotIn(str(ROOT), compact)

        cards_by_name = {card["name"]: card for card in cards}
        for name in PROJECT_ROUTING_SKILLS:
            frontmatter = yaml.safe_load(
                (skills_root / name / "SKILL.md")
                .read_text(encoding="utf-8")
                .split("---", 2)[1]
            )
            self.assertEqual(
                cards_by_name[name],
                {field: frontmatter[field] for field in ROUTING_CARD_FIELDS},
            )

        first = json.dumps(routing_catalog, ensure_ascii=False, separators=(",", ":"))
        second = json.dumps(
            _validated_skill_routing_catalog(SKILL_ROUTING_CARDS, skills_root),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        self.assertEqual(first, second)

    def test_orphan_bundled_skill_directories_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-orphan-skill-") as temporary:
            skills_root = Path(temporary) / "skills"
            (skills_root / "valid").mkdir(parents=True)
            (skills_root / "valid" / "SKILL.md").write_text(
                "---\nname: valid\n---\n",
                encoding="utf-8",
            )
            (skills_root / "orphan").mkdir()

            with self.assertRaisesRegex(
                ManagedPiRuntimeError,
                r"bundled Skill discovery failed: .*orphan.*missing SKILL\.md",
            ):
                _product_skill_dirs(skills_root)

            self.assertEqual(BUNDLED_SKILL_SUPPORT_DIRS, frozenset())
            self.assertEqual(
                [item.name for item in _product_skill_dirs(
                    skills_root,
                    allowed_support_dirs=frozenset({"orphan"}),
                )],
                ["valid"],
            )

    def test_unresolved_skill_name_collisions_report_each_source(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-skill-collision-") as temporary:
            root = Path(temporary)
            roots: dict[str, Path] = {}
            for source in ("bundled", "configured", "pi-installed"):
                skill_root = root / source / "shared-name"
                skill_root.mkdir(parents=True)
                (skill_root / "SKILL.md").write_text(
                    f"---\nname: shared-name\ndescription: {source}\n---\n{source}\n",
                    encoding="utf-8",
                )
                roots[source] = skill_root

            with self.assertRaises(ManagedPiRuntimeError) as raised:
                _resolve_skill_source_collisions(
                    bundled=(roots["bundled"],),
                    configured=(roots["configured"],),
                    pi_installed=(roots["pi-installed"],),
                    collision_policy={
                        "default": "reject",
                        "bundledWins": {"configured": [], "pi-installed": []},
                    },
                )

        diagnostic = str(raised.exception)
        self.assertIn("unresolved Skill name collision for 'shared-name'", diagnostic)
        self.assertIn("bundled=", diagnostic)
        self.assertIn("configured=", diagnostic)
        self.assertIn("pi-installed=", diagnostic)
        self.assertIn("collisionPolicy.default=reject", diagnostic)

    def test_bundled_skill_wins_only_with_explicit_source_policy(self) -> None:
        skills_root = ROOT / "integrations" / "pi" / "skills"
        bundled_skill = skills_root / "memory-curation"
        with tempfile.TemporaryDirectory(prefix="rag-ime-explicit-skill-winner-") as temporary:
            root = Path(temporary)
            external: dict[str, Path] = {}
            for source in ("configured", "pi-installed"):
                skill_root = root / source / "memory-curation"
                skill_root.mkdir(parents=True)
                (skill_root / "SKILL.md").write_text(
                    f"---\nname: memory-curation\ndescription: {source}\n---\n{source}\n",
                    encoding="utf-8",
                )
                external[source] = skill_root

            resolved = _resolve_skill_source_collisions(
                bundled=(bundled_skill,),
                configured=(external["configured"],),
                pi_installed=(external["pi-installed"],),
                collision_policy={
                    "default": "reject",
                    "bundledWins": {
                        "configured": ["memory-curation"],
                        "pi-installed": ["memory-curation"],
                    },
                },
            )

        winner = resolved["memory-curation"]
        self.assertEqual(winner["source"], "bundled")
        self.assertEqual(Path(winner["path"]), bundled_skill / "SKILL.md")
        self.assertIn(
            "authorized Evidence",
            Path(winner["path"]).read_text(encoding="utf-8"),
        )
        catalog = _validated_skill_routing_catalog(SKILL_ROUTING_CARDS, skills_root)
        bundled_frontmatter = yaml.safe_load(
            (bundled_skill / "SKILL.md").read_text(encoding="utf-8").split("---", 2)[1]
        )
        card = next(
            item for item in catalog["cards"] if item["name"] == "memory-curation"
        )
        self.assertEqual(
            card,
            {field: bundled_frontmatter[field] for field in ROUTING_CARD_FIELDS},
        )

    def test_project_routing_card_drift_is_rejected(self) -> None:
        skills_root = ROOT / "integrations" / "pi" / "skills"
        catalog = json.loads(SKILL_ROUTING_CARDS.read_text(encoding="utf-8"))
        project_card = next(
            card for card in catalog["cards"] if card["name"] == "work-document-archive"
        )
        project_card["does"] = "drifted duplicate truth"
        with tempfile.TemporaryDirectory(prefix="rag-ime-routing-card-drift-") as temporary:
            cards_path = Path(temporary) / "skill-routing-cards.json"
            cards_path.write_text(
                json.dumps(catalog, ensure_ascii=False),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                ManagedPiRuntimeError,
                "project routing card drift for 'work-document-archive'",
            ):
                _validated_skill_routing_catalog(cards_path, skills_root)

    def test_runtime_banner_loads_all_product_skills_without_enabling_global_discovery(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-runtime-skills-") as temporary:
            root = Path(temporary)
            for name in ("memory-curation", "plugin-creator"):
                skill_root = root / name
                skill_root.mkdir()
                (skill_root / "SKILL.md").write_text(
                    f"---\nname: {name}\ndescription: test\n---\n",
                    encoding="utf-8",
                )

            banner = _runtime_host_banner(root)

        self.assertIn('"memory-curation"', banner)
        self.assertIn('"plugin-creator"', banner)
        self.assertIn('process.env.RAG_IME_PI_SKILL_PATHS', banner)
        self.assertIn('process.env.RAG_IME_PI_SKILL_ROUTING_CARDS', banner)
        self.assertIn('skill-routing-cards.json', banner)
        self.assertIn('__join(__ragImeRuntimeDir, "skills", name)', banner)
        self.assertIn("RAG_IME_PI_USER_SKILL_PATHS", banner)
        self.assertIn("Unresolved Skill name collision", banner)
        self.assertIn("collisionPolicy.default=reject", banner)
        self.assertIn("explicitBundledWinner", banner)
        self.assertNotIn("--no-skills", banner)

    def test_managed_payload_copies_memory_curation_governance_contract(self) -> None:
        source_root = ROOT / "integrations" / "pi" / "skills"
        with tempfile.TemporaryDirectory(prefix="rag-ime-runtime-skill-copy-") as temporary:
            runtime_root = Path(temporary) / "runtime-host" / "skills"
            copied = _copy_product_skills(source_root, runtime_root)
            skill_root = runtime_root / "memory-curation"
            skill = (skill_root / "SKILL.md").read_text(encoding="utf-8")
            alignment = (runtime_root / "alignment-and-decision" / "SKILL.md").read_text(
                encoding="utf-8"
            )
            implementation_execution = (
                runtime_root / "implementation-execution" / "SKILL.md"
            ).read_text(encoding="utf-8")
            continuity_contract = (
                runtime_root
                / "implementation-execution"
                / "references"
                / "execution-continuity-contract.md"
            ).read_text(encoding="utf-8")
            agent_prompt = (skill_root / "agents" / "openai.yaml").read_text(
                encoding="utf-8"
            )
            execution_prompt = (
                runtime_root / "implementation-execution" / "agents" / "openai.yaml"
            ).read_text(encoding="utf-8")

        self.assertIn("memory-curation", copied)
        self.assertIn("alignment-and-decision", copied)
        self.assertIn("implementation-execution", copied)
        self.assertIn("name: alignment-and-decision", alignment)
        self.assertIn("the decision, not the user", alignment)
        self.assertIn("Write a glossary, ADR, or decision record only", alignment)
        self.assertIn("one continuous suite", implementation_execution)
        self.assertIn("docs/agent/chat-summary.md", implementation_execution)
        self.assertIn("one conditional inner", implementation_execution)
        self.assertIn("implementation-continuity:start", continuity_contract)
        self.assertIn(
            "One Small Project Index",
            continuity_contract,
        )
        self.assertIn(
            "One Work Item, One WorkDocument",
            continuity_contract,
        )
        self.assertIn("Original User Request", continuity_contract)
        self.assertIn("Original User Vision", continuity_contract)
        self.assertIn("no automatic expiry or deletion", continuity_contract)
        self.assertIn("preserve the original request and vision", execution_prompt)
        for required in (
            "authorized Evidence -> one Current Atom",
            "Task Timeline for continuity only",
            "legitimate trigger",
            "durable-information gate",
            "correction",
            "duplicate",
            "conflict",
            "native review boundary",
            "One Atom holds one current claim",
            "Background curation remains bounded",
            "Do not read or write SQLite directly",
            "memory capture and memory curation",
        ):
            self.assertIn(required, skill)
        self.assertIn("durable personal memory", agent_prompt)
        self.assertIn("Preserve provenance", agent_prompt)
        self.assertIn("background auto-apply", agent_prompt)


if __name__ == "__main__":
    unittest.main()
