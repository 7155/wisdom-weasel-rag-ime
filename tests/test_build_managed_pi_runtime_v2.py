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
    REQUIRED_PI_RUNTIME_BASE_COMMIT,
    REQUIRED_RUNTIME_METHODS,
    SESSION_RUNTIME_CONTRACT,
    _SESSION_RUNTIME_SOURCE_KEYS,
    _copy_bundled_pi_packages,
    _copy_product_skills,
    _compact_card_length,
    _default_pi_worktree,
    _default_node,
    _product_skill_dirs,
    _resolve_skill_source_collisions,
    _runtime_host_banner,
    _skill_routing_projection,
    _smoke_oauth_runtime_modules,
    _validated_skill_routing_catalog,
    _verified_session_runtime_contract,
)
from rag_ime.managed_pi_runtime import ManagedPiRuntimeError


SESSION_FLOW_SKILLS = {
    "alignment-and-decision",
    "facilitate-room",
    "implementation-planning",
    "independent-review",
    "orchestrate-session",
    "organize-work-documents",
    "systematic-debugging",
    "test-driven-implementation",
}


class ManagedPiRuntimeV2BuildTests(unittest.TestCase):
    def test_control_extension_keeps_full_desktop_receipt_out_of_model_context(self) -> None:
        source = (ROOT / "integrations" / "pi" / "rag-ime-control.ts").read_text(
            encoding="utf-8"
        )

        self.assertIn('key !== "auditReceipt"', source)
        self.assertIn("boundedToolResult(toolCallId", source)

    def test_session_runtime_source_contract_pins_required_session_surfaces(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(
            prefix="rag-ime-session-host-contract-"
        ) as temporary:
            root = Path(temporary)
            relative_sources = {
                "protocol": Path("integrations/rag-ime-runtime-host/src/protocol.ts"),
                "runtimeHost": Path("integrations/rag-ime-runtime-host/src/runtime-host.ts"),
                "contextInspection": Path("integrations/rag-ime-runtime-host/src/debug-context.ts"),
                "toolBridge": Path("integrations/rag-ime-runtime-host/src/tool-bridge.ts"),
                "toolResults": Path("integrations/rag-ime-runtime-host/src/tool-artifact-buffer.ts"),
                "session": Path("integrations/rag-ime-runtime-host/src/pi-session.ts"),
                "pluginManager": Path("integrations/rag-ime-runtime-host/src/plugin-manager.ts"),
                "packageCatalog": Path("integrations/rag-ime-runtime-host/src/bundled-package-catalog.ts"),
                "packageManager": Path("integrations/rag-ime-runtime-host/src/native-package-manager.ts"),
            }
            self.assertEqual(
                set(relative_sources),
                set(_SESSION_RUNTIME_SOURCE_KEYS),
            )
            methods = list(REQUIRED_RUNTIME_METHODS)
            markers = {
                key: [f"marker:{key}"]
                for key in _SESSION_RUNTIME_SOURCE_KEYS
            }
            for key, relative in relative_sources.items():
                source = root / relative
                source.parent.mkdir(parents=True, exist_ok=True)
                extra = ""
                if key == "protocol":
                    extra = (
                        "export type RuntimeMethod = "
                        + " ".join(f'| "{method}"' for method in methods)
                        + ";\n"
                    )
                elif key == "runtimeHost":
                    extra = (
                        "switch (method) { "
                        + " ".join(
                            f'case "{method}": break;'
                            for method in methods
                        )
                        + " }\n"
                    )
                source.write_text(
                    f"// marker:{key}\n{extra}",
                    encoding="utf-8",
                )
            contract_path = root / "session-runtime-host-contract.json"
            contract_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": (
                            "rag-ime.pi-session-runtime-host-contract.v1"
                        ),
                        "sourceRepository": (
                            "https://github.com/7155/pi.git"
                        ),
                        "sourcePackage": (
                            "@earendil-works/pi-rag-ime-runtime-host"
                        ),
                        "protocolVersion": "2",
                        "minimumHandlersCommit": "a" * 40,
                        "requiredMethods": methods,
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
            with (
                patch(
                    "scripts.build_managed_pi_runtime_v2."
                    "SESSION_RUNTIME_CONTRACT",
                    contract_path,
                ),
                patch(
                    "scripts.build_managed_pi_runtime_v2."
                    "REQUIRED_PI_RUNTIME_BASE_COMMIT",
                    "a" * 40,
                ),
            ):
                contract, digest = (
                    _verified_session_runtime_contract(root)
                )
                (root / relative_sources["session"]).write_text(
                    "// marker removed\n",
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(
                    RuntimeError,
                    "source marker is missing: session",
                ):
                    _verified_session_runtime_contract(root)

        self.assertEqual(
            contract["minimumHandlersCommit"],
            "a" * 40,
        )
        self.assertEqual(len(digest), 64)

    def test_public_pi_pin_uses_session_runtime_contract(self) -> None:
        contract = json.loads(
            SESSION_RUNTIME_CONTRACT.read_text(encoding="utf-8")
        )
        self.assertEqual(
            contract["minimumHandlersCommit"],
            REQUIRED_PI_RUNTIME_BASE_COMMIT,
        )
        self.assertEqual(
            contract["requiredMethods"],
            list(REQUIRED_RUNTIME_METHODS),
        )
        serialized = json.dumps(contract, sort_keys=True)
        self.assertIn("room.dispatch", contract["requiredMethods"])
        self.assertIn("room.cancel", contract["requiredMethods"])
        self.assertIn("session.await_settled", contract["requiredMethods"])
        self.assertIn("plugins.create", contract["requiredMethods"])
        self.assertIn("plugins.validate", contract["requiredMethods"])
        self.assertIn("session.command.invoke", serialized)
        self.assertIn("plugins.catalog", serialized)
        self.assertIn("plugins.package.prepare", serialized)
        self.assertIn("plugins.uninstall", serialized)
        self.assertEqual(
            contract["handlerSources"],
            {
                "protocol": "integrations/rag-ime-runtime-host/src/protocol.ts",
                "runtimeHost": "integrations/rag-ime-runtime-host/src/runtime-host.ts",
                "contextInspection": "integrations/rag-ime-runtime-host/src/debug-context.ts",
                "toolBridge": "integrations/rag-ime-runtime-host/src/tool-bridge.ts",
                "toolResults": "integrations/rag-ime-runtime-host/src/tool-artifact-buffer.ts",
                "session": "integrations/rag-ime-runtime-host/src/pi-session.ts",
                "pluginManager": "integrations/rag-ime-runtime-host/src/plugin-manager.ts",
                "packageCatalog": "integrations/rag-ime-runtime-host/src/bundled-package-catalog.ts",
                "packageManager": "integrations/rag-ime-runtime-host/src/native-package-manager.ts",
            },
        )

    def test_public_pi_pin_matches_reviewed_runtime_protocol_order(self) -> None:
        self.assertEqual(
            list(REQUIRED_RUNTIME_METHODS),
            [
                "hello",
                "health",
                "models.list",
                "completion.once",
                "completion.cancel",
                "tools.list",
                "tools.sync",
                "session.open",
                "session.control_state",
                "session.settlement.get",
                "session.await_settled",
                "session.snapshot",
                "session.debug.context",
                "session.commands",
                "session.command.invoke",
                "session.fork.candidates",
                "session.fork",
                "session.rewind",
                "session.prompt",
                "session.steer",
                "session.follow_up",
                "session.abort",
                "session.compact",
                "session.model.set",
                "session.thinking.set",
                "session.close",
                "room.dispatch",
                "room.cancel",
                "approval.resolve",
                "review.resolve",
                "ui.resolve",
                "plugins.catalog",
                "plugins.list",
                "plugins.create",
                "plugins.package.create",
                "plugins.package.prepare",
                "plugins.validate",
                "plugins.install.preview",
                "plugins.install",
                "plugins.enable",
                "plugins.disable",
                "plugins.uninstall",
                "plugins.rollback",
            ],
        )
        self.assertEqual(
            REQUIRED_PI_RUNTIME_BASE_COMMIT,
            "59a71b235dadb4ad0d67557a8abb0aaa093e68b4",
        )

    def test_default_pi_worktree_prefers_canonical_main_checkout(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-pi-worktree-") as temporary:
            workspace = Path(temporary)
            canonical = workspace / "pi"
            legacy = workspace / "pi-rag-ime-runtime"
            (canonical / "integrations" / "rag-ime-runtime-host").mkdir(parents=True)
            (legacy / "packages" / "rag-ime-runtime-host").mkdir(parents=True)

            self.assertEqual(_default_pi_worktree(workspace), canonical)

            (canonical / "integrations" / "rag-ime-runtime-host").rmdir()
            (canonical / "integrations").rmdir()
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
        contract = SESSION_RUNTIME_CONTRACT.read_text(encoding="utf-8")

        self.assertIn('product_commit.encode("ascii")', script)
        self.assertIn('"productCommit": product_commit', script)
        self.assertIn('manifest["createdAtMs"] = product_commit_ms', script)
        self.assertIn("_verified_session_runtime_contract", script)
        self.assertIn("_copy_bundled_pi_packages", script)
        self.assertIn('package_root / "pi-packages"', script)
        self.assertIn('bundled_pi_cli = runtime_dir / "pi-cli.mjs"', script)
        self.assertIn('packages" / "coding-agent" / "src" / "cli.ts"', script)
        self.assertIn('bundled_pi_theme_dir = runtime_dir / "dist" / "modes" / "interactive" / "theme"', script)
        self.assertIn(
            "source_contract_sha256=session_runtime_contract_sha256",
            script,
        )
        for method in REQUIRED_RUNTIME_METHODS:
            self.assertIn(f'"{method}"', contract)

    def test_bundled_pi_packages_are_copied_next_to_the_runtime_host(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-pi-packages-") as temporary:
            root = Path(temporary)
            source = root / "pi-packages"
            package = source / "example"
            package.mkdir(parents=True)
            (source / "catalog.json").write_text(
                '{"schemaVersion":1,"packages":[]}',
                encoding="utf-8",
            )
            (package / "package.json").write_text(
                '{"name":"@paw/example","version":"1.0.0"}',
                encoding="utf-8",
            )
            (package / "index.ts").write_text("export {};\n", encoding="utf-8")
            destination = root / "payload" / "pi-packages"

            _copy_bundled_pi_packages(source, destination)

            self.assertEqual(
                (destination / "catalog.json").read_text(encoding="utf-8"),
                '{"schemaVersion":1,"packages":[]}',
            )
            self.assertTrue((destination / "example" / "package.json").is_file())
            self.assertTrue((destination / "example" / "index.ts").is_file())

    def test_staged_smoke_uses_session_lifecycle_contract(self) -> None:
        script = (ROOT / "scripts" / "smoke_pi_session_staged_runtime.py").read_text(
            encoding="utf-8"
        )

        for method in (
            "session.open",
            "session.prompt",
            "session.steer",
            "session.debug.context",
            "session.abort",
            "session.snapshot",
        ):
            self.assertIn(f'"{method}"', script)
        self.assertNotIn('"room.dispatch"', script)
        self.assertNotIn('"room.cancel"', script)

    def test_staged_package_smoke_proves_native_resource_projection(self) -> None:
        script = (
            ROOT / "scripts" / "smoke_pi_packages_staged_runtime.py"
        ).read_text(encoding="utf-8")

        for method in (
            "plugins.catalog",
            "plugins.package.prepare",
            "plugins.install.preview",
            "plugins.install",
            "plugins.enable",
            "plugins.disable",
            "plugins.uninstall",
            "session.commands",
            "tools.list",
        ):
            self.assertIn(f'"{method}"', script)
        self.assertIn("disabledResourcesAbsent", script)
        self.assertIn("independentCapabilityRemoval", script)

    def test_staged_resilience_smoke_covers_compaction_and_tool_failure_stop(self) -> None:
        script = (
            ROOT / "scripts" / "smoke_pi_resilience_staged_runtime.py"
        ).read_text(encoding="utf-8")

        self.assertIn("threshold-continuation", script)
        self.assertIn("THRESHOLD-COMPACTION-CONTINUED-OK", script)
        self.assertIn("tool_loop_no_progress", script)
        self.assertIn("repeated_failure_signature", script)
        self.assertIn('"session.snapshot"', script)

    def test_staged_room_smoke_uses_the_typed_participant_steer_contract(self) -> None:
        script = (ROOT / "scripts" / "smoke_pi_room_composition.py").read_text(
            encoding="utf-8"
        )

        self.assertIn('"action": "steer_participant"', script)
        self.assertNotIn('"action": "steer",', script)
        self.assertIn('"authorityKind": "room_work_item"', script)
        self.assertIn('"partnerWorkDocumentRevision"', script)
        self.assertIn('"partnerWorkItemState"', script)
        self.assertIn('"op": "wait"', script)
        self.assertIn('"op": "accept"', script)
        self.assertIn('"operabilityVerdict": "passed"', script)
        self.assertIn('"requirementVerdict": "satisfied"', script)
        self.assertIn("synced_document['documentId']", script)
        self.assertNotIn('child_result.get("status") != "completed"', script)

    def test_product_owns_all_managed_skills(self) -> None:
        skills_root = ROOT / "integrations" / "pi" / "skills"
        skill_dirs = _product_skill_dirs(skills_root)
        skill_names = [item.name for item in skill_dirs]

        self.assertEqual(
            skill_names,
            sorted({
                "alignment-and-decision",
                "bootstrap-project-context",
                "ego-browser",
                "facilitate-room",
                "implementation-planning",
                "improve-codebase-architecture",
                "independent-review",
                "rag-retrieval-optimization",
                "memory-curation",
                "orchestrate-session",
                "organize-work-documents",
                "pawos-system",
                "plugin-creator",
                "project-maintainer",
                "systematic-debugging",
                "test-driven-implementation",
                "trace-agent-diagnostics",
            }),
        )
        for name in skill_names:
            content = (skills_root / name / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn(f"name: {name}", content)
            self.assertIn("\ndescription: ", content)
            if name in SESSION_FLOW_SKILLS:
                frontmatter = yaml.safe_load(content.split("---", 2)[1])
                self.assertEqual(set(frontmatter), {"name", "description"})
                description = frontmatter["description"]
                self.assertIn("Use when", description)
                self.assertIn("Do not use", description)
                self.assertIn("e.g.,", description)
                self.assertLessEqual(len(description), 600)
                self.assertIn("\n## Not For\n", content)
                self.assertIn("\nExample:", content)
                agent_metadata = yaml.safe_load(
                    (skills_root / name / "agents" / "openai.yaml").read_text(
                        encoding="utf-8"
                    )
                )
                self.assertIn(
                    f"${name}",
                    agent_metadata["interface"]["default_prompt"],
                )

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
        self.assertNotIn("structured-result-presentation", {card["name"] for card in cards})
        for card in cards:
            self.assertTrue(card["when"])
            self.assertTrue(card["does"])
            compact = json.dumps(card, ensure_ascii=False, separators=(",", ":"))
            self.assertLessEqual(
                _compact_card_length(card),
                MAX_ROUTING_CARD_CHARS,
                card["name"],
            )
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
                _skill_routing_projection(frontmatter, skill_name=name),
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
            _skill_routing_projection(
                bundled_frontmatter,
                skill_name="memory-curation",
            ),
        )

    def test_project_routing_card_drift_is_rejected(self) -> None:
        skills_root = ROOT / "integrations" / "pi" / "skills"
        catalog = json.loads(SKILL_ROUTING_CARDS.read_text(encoding="utf-8"))
        project_card = next(
            card for card in catalog["cards"] if card["name"] == "memory-curation"
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
                "project routing card drift for 'memory-curation'",
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

    def test_managed_payload_copies_session_skills_and_memory_contract(self) -> None:
        source_root = ROOT / "integrations" / "pi" / "skills"
        with tempfile.TemporaryDirectory(prefix="rag-ime-runtime-skill-copy-") as temporary:
            runtime_root = Path(temporary) / "runtime-host" / "skills"
            copied = _copy_product_skills(source_root, runtime_root)
            skill_root = runtime_root / "memory-curation"
            skill = (skill_root / "SKILL.md").read_text(encoding="utf-8")
            alignment = (runtime_root / "alignment-and-decision" / "SKILL.md").read_text(
                encoding="utf-8"
            )
            orchestration = (
                runtime_root / "orchestrate-session" / "SKILL.md"
            ).read_text(encoding="utf-8")
            facilitation = (
                runtime_root / "facilitate-room" / "SKILL.md"
            ).read_text(encoding="utf-8")
            bootstrap = (
                runtime_root / "bootstrap-project-context" / "SKILL.md"
            ).read_text(encoding="utf-8")
            organization = (
                runtime_root / "organize-work-documents" / "SKILL.md"
            ).read_text(encoding="utf-8")
            ego_browser = (
                runtime_root / "ego-browser" / "SKILL.md"
            ).read_text(encoding="utf-8")
            independent_review = (
                runtime_root / "independent-review" / "SKILL.md"
            ).read_text(encoding="utf-8")
            agent_prompt = (skill_root / "agents" / "openai.yaml").read_text(
                encoding="utf-8"
            )
            orchestration_prompt = (
                runtime_root / "orchestrate-session" / "agents" / "openai.yaml"
            ).read_text(encoding="utf-8")

        self.assertIn("memory-curation", copied)
        self.assertIn("alignment-and-decision", copied)
        self.assertIn("orchestrate-session", copied)
        self.assertIn("facilitate-room", copied)
        self.assertIn("bootstrap-project-context", copied)
        self.assertIn("organize-work-documents", copied)
        for retired in (
            "implementation-execution",
            "quality-gate",
            "review-feedback-resolution",
            "structured-handoff",
            "work-document-archive",
        ):
            self.assertNotIn(retired, copied)
        self.assertIn("name: alignment-and-decision", alignment)
        self.assertIn("material user-owned choices", alignment)
        self.assertIn("Session's native subagent capability", orchestration)
        self.assertIn("does not define another event bus", orchestration)
        self.assertIn("Batch dispatch", orchestration)
        self.assertIn("fresh/new", orchestration)
        self.assertIn("does not rank either mode", orchestration)
        self.assertIn("A pass on only one axis is not closure", orchestration)
        self.assertIn("AGENTS.md", bootstrap)
        self.assertIn("write's `workDocument` field", bootstrap)
        self.assertIn("live", bootstrap)
        self.assertIn("authorityRevision", bootstrap)
        self.assertIn("never emit `clear`/`passed` for unverified work", independent_review)
        self.assertIn("rewrite unverified work as `clear`/`passed`", independent_review)
        self.assertIn("Never fall through to standalone Google", ego_browser)
        self.assertIn("not permission to drive desktop Chrome or Edge", ego_browser)
        self.assertIn("Partners remain ordinary Sessions", facilitation)
        self.assertIn(
            "Partner assignment exists only after a real delegated dispatch",
            facilitation,
        )
        self.assertIn("prerequisites for submission, not acceptance", facilitation)
        self.assertIn("one `delegate_batch` call", facilitation)
        self.assertIn("never describe consecutive `delegate` calls as parallel", facilitation)
        self.assertIn("emit the best evidence-backed partial or blocked final", facilitation)
        self.assertIn("unfinished, failed, orphaned, partial, and unclosed", facilitation)
        self.assertIn("does not prove requirement satisfaction", facilitation)
        self.assertIn("returns an immediate durable dispatch receipt", facilitation)
        self.assertIn("durable wake", facilitation)
        self.assertIn("`room_partner collect` or `wait`", facilitation)
        self.assertIn("A `wait` timeout never cancels", facilitation)
        self.assertIn("explicitly call `accept` or `return`", facilitation)
        self.assertIn("Do not pause a live Room Goal to wait", facilitation)
        self.assertIn("pause a live Room Goal as a wait", facilitation)
        self.assertIn("If a reviewer reported `unverified`", facilitation)
        self.assertIn("live `authorityRevision`", facilitation)
        self.assertIn("product `browser` tool", facilitation)
        self.assertIn("Before any requirements, business-code, configuration, or test write", facilitation)
        self.assertIn("`agent_goal confirm_setup`", facilitation)
        self.assertIn('workDocument={authorityKind:"session_goal"', facilitation)
        self.assertIn("successful `workDocumentRegistration`", facilitation)
        self.assertIn("do not create an unbound requirements file", facilitation)
        self.assertIn("A plain `docs/agent/requirements.md`, Todo, or Room post is not that binding", facilitation)
        self.assertNotIn("automatically accepted", facilitation)
        self.assertIn("document gardener", organization)
        self.assertIn("both verification axes", organization)
        self.assertIn("$orchestrate-session", orchestration_prompt)
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
