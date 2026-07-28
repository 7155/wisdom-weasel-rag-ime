from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "render_agent_prompt_system_audit.py"
SPEC = importlib.util.spec_from_file_location(
    "render_agent_prompt_system_audit",
    SCRIPT,
)
assert SPEC is not None and SPEC.loader is not None
AUDIT = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = AUDIT
SPEC.loader.exec_module(AUDIT)


def _records_by_id(audit: dict[str, object]) -> dict[str, dict[str, object]]:
    return {
        str(item["prompt_id"]): item
        for item in audit["promptRecords"]
        if isinstance(item, dict)
    }


class RenderAgentPromptSystemAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.audit = AUDIT.build_audit()
        cls.records = _records_by_id(cls.audit)

    def test_every_prompt_producer_is_classified(self) -> None:
        inventory = self.audit["promptSymbolInventory"]

        self.assertEqual(inventory["unclassified"], [])
        self.assertEqual(
            set(inventory["discovered"]),
            set(inventory["classification"]),
        )

    def test_ordinary_agent_prompt_has_no_room_duty(self) -> None:
        prompt = self.records["agent.composed.assistant-example"]["content"]
        coordinator = self.records["agent.composed.coordinator-example"]["content"]

        self.assertNotIn("<room-work>", prompt)
        self.assertNotIn("room_commit", prompt)
        self.assertNotIn("<room-context>", prompt)
        self.assertNotIn("<managed-work>", prompt)
        self.assertIn("<durable-memory-policy>", prompt)
        self.assertIn("<capability-policy>", prompt)
        self.assertIn('<session-mode kind="coordinator">', coordinator)
        self.assertIn("不是 Room", coordinator)
        self.assertNotIn("<room-work>", coordinator)
        self.assertIn("<managed-work>", coordinator)

    def test_conditional_agent_prompt_branches_are_explicit(self) -> None:
        self.assertEqual(
            self.records["agent.session.assistant-zero"]["content"],
            "",
        )
        self.assertEqual(
            self.records["agent.session.template-selected-zero"]["content"],
            "",
        )
        self.assertIn(
            "工作区范围尚未确认",
            self.records["agent.execution.workspace_managed"]["content"],
        )
        self.assertIn(
            "已批准工作区内",
            self.records["agent.execution.workspace_managed.granted"]["content"],
        )
        self.assertIn(
            "工作区边界尚未确认",
            self.records["agent.execution.full_trust"]["content"],
        )
        self.assertIn(
            "当前工作区内符合策略的动作可以直接完成",
            self.records["agent.execution.full_trust.granted"]["content"],
        )
        for prompt_id in (
            "agent.execution.workspace_managed",
            "agent.execution.workspace_managed.granted",
            "agent.execution.full_trust",
            "agent.execution.full_trust.granted",
        ):
            with self.subTest(prompt=prompt_id):
                content = self.records[prompt_id]["content"]
                self.assertNotIn("workspaceScopeSha256", content)
                self.assertNotIn("/workspace/project", content)

    def test_room_prompt_has_fixed_layer_order_and_one_rule_owner(self) -> None:
        prompt = self.records["room.composed.stable-prefix-example"]["content"]

        positions = [
            prompt.index(f'<layer order="{order}" name="{name}">')
            for order, name, _producer, _optional in AUDIT.PROMPT_LAYER_SPECS[:4]
        ]
        self.assertEqual(positions, sorted(positions))
        self.assertNotIn('name="room_profile_overlay"', prompt)
        self.assertEqual(prompt.count("<durable-memory-policy>"), 1)
        self.assertEqual(prompt.count("<room-work>"), 1)
        self.assertEqual(prompt.count("<capability-policy>"), 1)

    def test_room_intercom_and_guard_branches_are_reviewable(self) -> None:
        self.assertIn(
            "这是需要答复的问题",
            self.records["room.dynamic.intercom-question"]["content"],
        )
        self.assertIn(
            "这是对先前问题的答复",
            self.records["room.dynamic.intercom-reply"]["content"],
        )
        self.assertIn(
            "消息本身不是验收 evidenceRef",
            self.records["room.dynamic.intercom-reply"]["content"],
        )
        self.assertIn(
            "不必机械复述",
            self.records["room.dynamic.intercom-notice"]["content"],
        )
        guard = self.records["room.profile.guard-example"]["content"]
        self.assertIn("已审核的 Room Guard", guard)
        self.assertIn('"requireGate":"peer-review-required"', guard)
        self.assertIn("只能进一步收紧", self.records["room.profile.guard-example"]["notes"])

    def test_role_book_absence_is_zero_bytes(self) -> None:
        absent = self.records["agent.role-book.unpinned"]
        pinned = self.records["agent.role-book.pinned-example"]

        self.assertEqual(absent["content"], "")
        self.assertEqual(absent["utf8Bytes"], 0)
        self.assertNotIn("revision_not_pinned", pinned["content"])
        self.assertIn("稳定工作画像", pinned["content"])

    def test_memory_prompts_are_agent_first_and_lexicon_is_separate(self) -> None:
        memory_records = [
            item
            for item in self.audit["promptRecords"]
            if item["category"] == "memory-governance"
        ]

        for record in memory_records:
            with self.subTest(prompt=record["prompt_id"]):
                self.assertNotIn("你是 RAG 输入法", record["content"])
                self.assertNotIn("你是一个输入法", record["content"])
        self.assertIn(
            "三条路径不能互相冒充",
            self.records["memory.legacy-core-optimization"]["content"],
        )
        self.assertIn(
            "输入法词库新增",
            self.records["memory.default-instruction"]["content"],
        )

    def test_auxiliary_ime_prompts_are_explicitly_isolated(self) -> None:
        auxiliary = [
            item
            for item in self.audit["promptRecords"]
            if item["category"] == "auxiliary-surface"
        ]

        self.assertTrue(auxiliary)
        self.assertTrue(
            all(
                record["runtime_scope"] == "auxiliary-surface"
                for record in auxiliary
            )
        )
        stable = [
            item
            for item in self.audit["promptRecords"]
            if item["category"]
            in {
                "ordinary-agent",
                "persona",
                "agent-template",
                "room-stable",
            }
        ]
        for record in stable:
            with self.subTest(prompt=record["prompt_id"]):
                self.assertNotIn("你是 RAG 输入法", record["content"])
                self.assertNotIn("你是一个输入法", record["content"])

    def test_deep_search_transport_is_agent_first_and_hides_internal_context(self) -> None:
        prompt = self.records["surface.deep-search-example"]["content"]

        self.assertIn("<agent-deep-search-context>", prompt)
        self.assertIn("<agent-user-query>", prompt)
        self.assertIn("当前连续 Agent Session", prompt)
        self.assertIn("本轮已召回的证据线索", prompt)
        self.assertNotIn("输入法深度查找任务", prompt)
        self.assertNotIn("<rag-ime-user-query>", prompt)

    def test_knowledge_workbench_prompt_is_agent_first_and_bounded(self) -> None:
        system = self.records["surface.knowledge-workbench.system"]["content"]
        payload = json.loads(
            self.records["surface.knowledge-workbench.user-example"]["content"]
        )

        self.assertIn("Agent 记忆系统的显式知识工作台", system)
        self.assertNotIn("你是 RAG-IME", system)
        self.assertNotIn("普通数字键必须透传", system)
        self.assertIn("runtimeContract", payload)
        self.assertIn("agentMemory", payload["runtimeContract"])
        self.assertNotIn("inputSurface", payload["runtimeContract"])

    def test_current_minimind_hot_route_is_prompt_free(self) -> None:
        self.assertNotIn(
            "surface.predictor.minimind-system-zero",
            self.records,
        )
        self.assertNotIn(
            "surface.predictor.minimind-context-example",
            self.records,
        )
        for prompt_id in (
            "surface.predictor.system_prompt",
            "surface.predictor.stream_first_system_prompt",
            "surface.predictor.space_list_system_prompt",
            "surface.predictor.logits_system_prompt",
            "surface.predictor.mlx-generic-example",
            "surface.predictor.mlx-no-input-example",
        ):
            with self.subTest(prompt=prompt_id):
                self.assertEqual(self.records[prompt_id]["status"], "compatibility")
                self.assertEqual(
                    self.records[prompt_id]["reachability"],
                    "compatibility",
                )

    def test_every_model_request_route_has_source_and_prompt_ledger_entries(
        self,
    ) -> None:
        routes = {
            item["id"]: item
            for item in self.audit["modelRequestRoutes"]
        }

        self.assertEqual(set(routes), {str(item["id"]) for item in AUDIT.MODEL_REQUEST_ROUTE_SPECS})
        self.assertTrue(all(item["sourceExists"] for item in routes.values()))
        self.assertTrue(all(item["missingPromptIds"] == [] for item in routes.values()))
        self.assertEqual(routes["minimind-hot"]["systemInstruction"], "none")
        self.assertEqual(routes["minimind-hot"]["reachability"], "production-current")
        self.assertEqual(routes["minimind-hot"]["promptIds"], [])
        self.assertEqual(
            routes["minimind-hot"]["requestExample"],
            "Agent Prompt 已进入逐段复核继续检查上下文",
        )
        self.assertIn(
            "当前模型没有 Prompt",
            routes["minimind-hot"]["notes"],
        )
        self.assertEqual(routes["active-rag-pi"]["systemInstruction"], "none")
        self.assertEqual(
            routes["active-rag-pi"]["promptIds"],
            ["surface.ime-continuation.request-example"],
        )
        self.assertIn(
            "接受完整思考等级",
            routes["active-rag-pi"]["thinking"],
        )
        self.assertIn(
            "user message",
            routes["active-rag-pi"]["transport"],
        )
        self.assertEqual(
            routes["agent-deep-search"]["reachability"],
            "production-conditional",
        )
        self.assertIn(
            "记忆检索",
            routes["agent-deep-search"]["notes"],
        )
        self.assertIn(
            "surface.deep-search-example",
            routes["agent-deep-search"]["promptIds"],
        )
        self.assertEqual(
            self.records["surface.ime-continuation"]["status"],
            "compatibility",
        )
        self.assertIn(
            "complete production model input",
            self.records["surface.ime-continuation.request-example"]["notes"],
        )
        self.assertEqual(
            routes["deepseek-post-commit"]["reachability"],
            "production-conditional",
        )
        self.assertEqual(
            routes["direct-active-rag-preview"]["reachability"],
            "debug-compatibility",
        )

    def test_direct_deepseek_post_commit_prompt_is_not_mislabeled_as_preview(
        self,
    ) -> None:
        system = self.records["surface.deepseek-post-commit.system"]
        user = self.records["surface.deepseek-post-commit.user-example"]

        self.assertEqual(system["display_group"], "auxiliary-production")
        self.assertEqual(system["reachability"], "conditional")
        self.assertIn("Smart RAG 候选生成器", system["content"])
        self.assertIn('"scene": "post_commit"', user["content"])
        self.assertIn("Rime post-commit side lane", system["owner"])
        self.assertEqual(
            self.records["surface.deepseek-active-rag.system"]["status"],
            "compatibility",
        )

    def test_room_recovery_packet_contains_each_required_field_once(self) -> None:
        raw = self.records["room.compaction.recovery-example"]["content"]
        packet = json.loads(raw)

        self.assertEqual(
            set(packet),
            {
                "originalRequirements",
                "requirementDirectory",
                "currentTask",
                "acceptance",
                "blockers",
                "handoff",
                "skillReceipt",
                "toolReceipt",
            },
        )
        self.assertEqual(raw.count('"originalRequirements"'), 1)
        self.assertEqual(raw.count('"skillReceipt"'), 1)
        self.assertEqual(raw.count('"toolReceipt"'), 1)
        self.assertEqual(
            [item["alias"] for item in packet["acceptance"]],
            ["AC-1", "AC-2"],
        )
        self.assertNotIn("criterion-a", raw)
        self.assertNotIn("criterion-b", raw)

    def test_tool_inventory_has_one_public_memory_capture_projection(self) -> None:
        tools = self.audit["tools"]
        product = {
            item["name"]: item
            for item in tools["productTools"]
        }
        room = {
            item["name"]: item
            for item in tools["roomTools"]
        }

        self.assertEqual(
            product["ime_memory"]["runtimeProjections"],
            [{"name": "memory_capture", "operation": "capture"}],
        )
        self.assertEqual(
            tools["modelVisibleMemoryCapture"]["projectionTarget"],
            {"name": "ime_memory", "operation": "capture"},
        )
        self.assertTrue(room["room_state"]["bootstrap"])
        self.assertTrue(room["room_post"]["bootstrap"])
        self.assertTrue(room["room_commit"]["bootstrap"])
        self.assertTrue(room["room_collaborate"]["deferred"])

    def test_skill_inventory_and_references_are_complete(self) -> None:
        skill_names = {
            item["name"]
            for item in self.audit["skills"]["skills"]
        }
        reference_rows = self.audit["references"]["references"]

        self.assertIn("requirement-alignment", skill_names)
        self.assertIn("managed-task-execution", skill_names)
        self.assertIn("quality-gate", skill_names)
        self.assertIn("grill-me", skill_names)
        self.assertTrue(all(item["exists"] for item in reference_rows))

        comparisons = {
            item["id"]: item
            for item in self.audit["references"]["comparisonCases"]
        }
        snapshots = {
            item["id"]: item
            for item in self.audit["references"]["sourceSnapshots"]
        }
        self.assertEqual(
            set(comparisons),
            {
                "identity-and-rails",
                "prompt-layering",
                "requirement-alignment",
                "progressive-disclosure",
                "durable-memory",
                "review-separation",
                "task-settlement",
                "collaboration-handoff",
                "compaction-recovery",
            },
        )
        self.assertIn("工具未暴露时", snapshots["cafe.tool-index"]["content"])
        self.assertIn(
            "同一件事写同一个日记",
            snapshots["vcp.agent-memory"]["content"],
        )
        self.assertIn(
            "DELEGATION_MAX_ROUNDS",
            snapshots["vcp.delegation-loop"]["content"],
        )
        self.assertIn(
            "绝不回写已有 systemPrompt 字节",
            comparisons["progressive-disclosure"]["decision"],
        )
        self.assertIn(
            "每个新 context epoch 只注入一份结构化恢复包",
            comparisons["compaction-recovery"]["decision"],
        )
        for comparison in comparisons.values():
            with self.subTest(comparison=comparison["id"]):
                self.assertTrue(
                    set(comparison["localSkillNames"]).issubset(skill_names)
                )

    def test_pi_runtime_prompt_producers_and_epoch_evidence_are_reviewable(
        self,
    ) -> None:
        producer_inventory = self.audit["piRuntimePromptProducerInventory"]

        self.assertEqual(
            set(producer_inventory),
            set(AUDIT.PI_RUNTIME_PROMPT_PRODUCERS),
        )
        self.assertTrue(
            all(item["exists"] for item in producer_inventory.values())
        )

        runtime_records = {
            prompt_id: record
            for prompt_id, record in self.records.items()
            if prompt_id.startswith("pi.runtime.")
        }
        if not runtime_records:
            return
        loaded = runtime_records[
            "pi.runtime.skill-load.tool-result.agent-example"
        ]
        restored = runtime_records[
            "pi.runtime.skill-load.compaction-restore.agent-example"
        ]
        self.assertEqual(loaded["content"], restored["content"])
        self.assertEqual(loaded["utf8Bytes"], restored["utf8Bytes"])
        self.assertEqual(loaded["sha256"], restored["sha256"])
        self.assertIn(
            "<skill_capability_families",
            runtime_records[
                "pi.runtime.skill-catalog.agent-example"
            ]["content"],
        )
        self.assertIn(
            '<rag-ime-context type="room_context">',
            runtime_records[
                "pi.runtime.room-context.room-example"
            ]["content"],
        )

    def test_rendered_bundle_contains_human_and_machine_readable_ledgers(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            output = Path(raw) / "audit"
            AUDIT.render_audit(self.audit, output)

            self.assertEqual(
                {path.name for path in output.iterdir()},
                {
                    "README.md",
                    "index.html",
                    "manifest.json",
                    "prompts.md",
                    "reference-comparison.md",
                    "review.md",
                    "skills.md",
                    "tools.json",
                },
            )
            manifest = json.loads(
                (output / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                manifest["schemaVersion"],
                "wisdom-weasel.agent-prompt-system-audit.v1",
            )
            self.assertIn(
                "agent.core.durable-memory",
                (output / "prompts.md").read_text(encoding="utf-8"),
            )
            review = (output / "review.md").read_text(encoding="utf-8")
            self.assertIn("普通 Agent", review)
            self.assertIn("三成员 Room", review)
            self.assertIn("真实 Provider 证明", review)
            self.assertIn("Root 原始需求", review)
            html = (output / "index.html").read_text(encoding="utf-8")
            self.assertIn("<title>Agent Prompt 与上下文复核台</title>", html)
            self.assertIn('id="audit-data"', html)
            self.assertIn('id="scope-filter"', html)
            self.assertIn("Agent / Room / 记忆（默认）", html)
            self.assertIn("模型路由", html)
            self.assertIn('"systemInstruction":"none"', html)
            self.assertIn("真正 Owner", html)
            self.assertIn("思考要求", html)
            self.assertIn("Provider 上下文", html)
            self.assertIn("审定状态", html)
            self.assertIn("为什么这样取", html)
            self.assertIn("剩余验证", html)
            self.assertIn("productSkillRecords", html)
            self.assertIn("skill_load 后完整生效", html)
            self.assertIn("本项目 Skill", html)
            self.assertNotIn("__AGENT_PROMPT_AUDIT_DATA__", html)


class SiblingRepositoryRootTests(unittest.TestCase):
    """Sibling repositories resolve through Git's common directory.

    `ROOT.parent` is only the sibling root when ROOT is the canonical
    checkout; in a physical worktree it pointed into `.worktrees/`, which
    made every default sibling path nonexistent and failed three audit
    assertions. The resolver must locate the canonical repository from Git
    and fall back to the historical `ROOT.parent` when Git cannot answer.
    """

    def _init_repository(self, repository: Path) -> None:
        for command in (
            ["git", "init", "--quiet", str(repository)],
            [
                "git", "-C", str(repository),
                "-c", "user.email=audit@test", "-c", "user.name=audit",
                "commit", "--allow-empty", "--quiet", "-m", "seed",
            ],
        ):
            completed = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_normal_checkout_resolves_the_repository_parent(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            siblings = Path(raw)
            repository = siblings / "repo"
            self._init_repository(repository)
            self.assertEqual(
                AUDIT._sibling_repository_root(repository).resolve(),
                siblings.resolve(),
            )

    def test_worktree_resolves_through_the_common_git_directory(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            siblings = Path(raw)
            repository = siblings / "repo"
            self._init_repository(repository)
            worktree = repository / ".worktrees" / "lane"
            completed = subprocess.run(
                ["git", "-C", str(repository), "worktree", "add",
                 "--quiet", str(worktree)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            # ROOT.parent would be repo/.worktrees -- the defect. The
            # resolver must come back to the sibling root instead.
            self.assertEqual(
                AUDIT._sibling_repository_root(worktree).resolve(),
                siblings.resolve(),
            )

    def test_git_unavailable_preserves_the_root_parent_fallback(self) -> None:
        somewhere = Path("/definitely/not/a/repository/checkout")
        with unittest.mock.patch.object(
            AUDIT.subprocess,
            "run",
            side_effect=FileNotFoundError("git not installed"),
        ):
            self.assertEqual(
                AUDIT._sibling_repository_root(somewhere),
                somewhere.parent,
            )

    def test_git_error_preserves_the_root_parent_fallback(self) -> None:
        somewhere = Path("/definitely/not/a/repository/checkout")
        failed = subprocess.CompletedProcess(
            args=["git"], returncode=128, stdout="", stderr="fatal: not a git repository",
        )
        with unittest.mock.patch.object(
            AUDIT.subprocess, "run", return_value=failed
        ):
            self.assertEqual(
                AUDIT._sibling_repository_root(somewhere),
                somewhere.parent,
            )

    def test_evidence_prefers_a_local_capture(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            siblings = Path(raw)
            repository = siblings / "repo"
            self._init_repository(repository)
            relative = Path("docs/agent/audits/agent-prompt-system-current")
            (repository / relative).mkdir(parents=True)
            self.assertEqual(
                AUDIT._deterministic_evidence_root(repository).resolve(),
                (repository / relative).resolve(),
            )

    def test_evidence_falls_back_to_the_canonical_checkout(self) -> None:
        """A worktree has no gitignored evidence of its own; the canonical
        checkout's capture must be found, and with no capture anywhere the
        historical local path is still reported."""

        with tempfile.TemporaryDirectory() as raw:
            siblings = Path(raw)
            repository = siblings / "repo"
            self._init_repository(repository)
            worktree = repository / ".worktrees" / "lane"
            completed = subprocess.run(
                ["git", "-C", str(repository), "worktree", "add",
                 "--quiet", str(worktree)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            relative = Path("docs/agent/audits/agent-prompt-system-current")

            self.assertEqual(
                AUDIT._deterministic_evidence_root(worktree).resolve(),
                (worktree / relative).resolve(),
                "with no capture anywhere, the local path is still reported",
            )
            (repository / relative).mkdir(parents=True)
            self.assertEqual(
                AUDIT._deterministic_evidence_root(worktree).resolve(),
                (repository / relative).resolve(),
            )

    def test_explicit_pi_root_remains_authoritative(self) -> None:
        """An explicit --pi-root value must win over the resolved default.

        `main()` passes the argparse values straight into `build_audit`, so
        proving `build_audit` honours an explicit (nonexistent) root proves
        the override path end to end: the inventory must report that root's
        files as missing even though the resolved default exists.
        """

        with tempfile.TemporaryDirectory() as raw:
            bogus = Path(raw) / "nowhere"
            audit = AUDIT.build_audit(pi_root=bogus)
        inventory = audit["piRuntimePromptProducerInventory"]
        self.assertTrue(inventory)
        self.assertFalse(any(item["exists"] for item in inventory.values()))


if __name__ == "__main__":
    unittest.main()
