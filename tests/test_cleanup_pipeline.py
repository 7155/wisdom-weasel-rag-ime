from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from rag_ime.cli import main
from rag_ime.local_sqlite_core import LocalSqliteCoreClient
from rag_ime.memory_generator import (
    CoreOptimizationReport,
    GeneratedLexiconPhrase,
    GeneratedMemoryItem,
    VcpRebuildConfig,
)
from rag_ime.models import InputEvent, MemoryAction
import rag_ime.memory_compiler as memory_compiler_module


class FakeCleanupCompilerGenerator:
    calls: list[dict[str, object]] = []

    def __init__(self, config: VcpRebuildConfig):
        self.config = config

    @property
    def provider_name(self) -> str:
        return "x1api"

    @classmethod
    def from_env_path(cls, env_path=None):
        cls.calls.append({"envPath": str(env_path or "")})
        return cls(
            VcpRebuildConfig(
                api_base_url="https://x1api.top/v1",
                api_key="fake-key",
                model="fake-gpt",
            )
        )

    def optimize_core(
        self,
        *,
        snapshot: dict[str, object],
        project: str = "wisdom-weasel-rag-ime",
        max_memories: int = 4,
        max_lexicon_phrases: int = 8,
        max_hide_suggestions: int = 12,
    ) -> CoreOptimizationReport:
        self.__class__.calls.append(
            {
                "project": project,
                "snapshot": snapshot,
                "maxMemories": max_memories,
                "maxLexiconPhrases": max_lexicon_phrases,
                "maxHideSuggestions": max_hide_suggestions,
                "model": self.config.model,
            }
        )
        return CoreOptimizationReport(
            provider="x1api",
            model=self.config.model,
            elapsed_ms=19,
            memories=(
                GeneratedMemoryItem(
                    text="本地检索优先",
                    tags=("memory",),
                    importance=0.9,
                    reason="归纳项目偏好",
                    source="cleanup-preview",
                ),
            ),
            lexicon_phrases=(
                GeneratedLexiconPhrase(
                    text="连续预测",
                    tags=("continuation",),
                    weight=0.8,
                    reason="高频短语",
                ),
            ),
            raw_text='{"ok":true}',
            metadata={"wireApi": "chat_completions"},
        )


class CleanupPipelineCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-cleanup-pipeline-")
        self.db_path = Path(self.tmp.name) / "rag-ime.sqlite"
        self.core = LocalSqliteCoreClient(self.db_path)
        self.core.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _run_cli_json(self, *args: str) -> tuple[int, dict[str, object]]:
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            code = main(["--db-path", str(self.db_path), *args])
        return code, json.loads(stdout.getvalue())

    def test_cleanup_preview_local_rule_is_dry_run_and_apply_requires_flag(self) -> None:
        self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=1_900_000_100_001,
                source="manual",
                committed_text="连续预测",
                recent_context="RAG 输入法",
                project="wisdom-weasel-rag-ime",
                tags=("phrase-memory",),
            )
        )
        self.core.apply_action(
            MemoryAction(
                action_id=None,
                created_at_ms=1_900_000_100_002,
                memory_id="event:1",
                action_type="accepted",
                query="连续",
                metadata={"project": "wisdom-weasel-rag-ime"},
            )
        )
        self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=1_900_000_100_003,
                source="manual",
                committed_text="这是一条很长且没有被接受过的历史输入，应该进入 cleanup tombstone",
                recent_context="old raw event",
                project="wisdom-weasel-rag-ime",
                tags=("user-input",),
            )
        )
        plan_path = Path(self.tmp.name) / "cleanup-preview.json"

        code, preview = self._run_cli_json(
            "cleanup-preview",
            "--provider",
            "local-rule",
            "--project",
            "wisdom-weasel-rag-ime",
            "--output",
            str(plan_path),
        )

        self.assertEqual(code, 0)
        self.assertTrue(preview["dryRun"])
        self.assertEqual(preview["provider"], "local-rule")
        self.assertTrue(preview["validation"]["ok"])
        self.assertTrue(plan_path.exists())
        self.assertEqual(self.core.list_memory_cleanup_runs(limit=10)["items"], [])

        code, validate = self._run_cli_json("cleanup-validate", "--run", str(plan_path))
        self.assertEqual(code, 0)
        self.assertTrue(validate["ok"])

        code, apply_missing = self._run_cli_json("cleanup-apply", "--run", str(plan_path))
        self.assertEqual(code, 2)
        self.assertFalse(apply_missing["ok"])
        inspect_before = self.core.inspect_memory_v2(project="wisdom-weasel-rag-ime", limit=20)
        self.assertNotIn("stable:连续预测", {item["memoryId"] for item in inspect_before["items"]})

        code, applied = self._run_cli_json("cleanup-apply", "--run", str(plan_path), "--apply")
        self.assertEqual(code, 0)
        self.assertTrue(applied["ok"])
        self.assertEqual(applied["run"]["status"], "applied")
        inspect_after = self.core.inspect_memory_v2(project="wisdom-weasel-rag-ime", limit=20)
        self.assertIn("stable:连续预测", {item["memoryId"] for item in inspect_after["items"]})

        code, rolled_back = self._run_cli_json("cleanup-rollback", "--run-id", preview["run"]["runId"])
        self.assertEqual(code, 0)
        self.assertTrue(rolled_back["ok"])
        inspect_final = self.core.inspect_memory_v2(project="wisdom-weasel-rag-ime", limit=20)
        self.assertNotIn("stable:连续预测", {item["memoryId"] for item in inspect_final["items"]})

    def test_cleanup_validate_rejects_stable_memory_without_evidence(self) -> None:
        plan_path = Path(self.tmp.name) / "invalid-cleanup.json"
        plan_path.write_text(
            json.dumps(
                {
                    "runId": "cleanup_invalid",
                    "provider": "x1api",
                    "model": "fake-gpt",
                    "summary": "stable=1",
                    "diffs": [
                        {
                            "op": "add_stable_memory",
                            "targetMemoryId": "stable:本地检索优先",
                            "payload": {
                                "memoryId": "stable:本地检索优先",
                                "text": "本地检索优先",
                                "project": "wisdom-weasel-rag-ime",
                                "confidence": 0.9,
                                "evidenceEventIds": [],
                            },
                            "status": "pending",
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        code, payload = self._run_cli_json("cleanup-validate", "--run", str(plan_path))

        self.assertEqual(code, 1)
        self.assertFalse(payload["ok"])
        self.assertTrue(any(item["code"] == "missing_evidence_event_ids" for item in payload["errors"]))

    def test_cleanup_preview_x1api_is_dry_run_and_surfaces_validation(self) -> None:
        original = memory_compiler_module.VcpRebuildMemoryGenerator
        FakeCleanupCompilerGenerator.calls = []
        memory_compiler_module.VcpRebuildMemoryGenerator = FakeCleanupCompilerGenerator
        try:
            self.core.record_event(
                InputEvent(
                    event_id=None,
                    created_at_ms=1_900_000_100_010,
                    source="manual",
                    committed_text="本地检索优先",
                    recent_context="这是项目里长期稳定的输入法偏好",
                    project="wisdom-weasel-rag-ime",
                    tags=("memory",),
                )
            )
            fake_env = Path(self.tmp.name) / "fake.env"
            fake_env.write_text("X1API_API_KEY=fake-key\nX1API_MODEL=fake-gpt\n", encoding="utf-8")
            output_path = Path(self.tmp.name) / "cleanup-x1api.json"

            code, payload = self._run_cli_json(
                "cleanup-preview",
                "--provider",
                "x1api",
                "--project",
                "wisdom-weasel-rag-ime",
                "--model-env-path",
                str(fake_env),
                "--output",
                str(output_path),
            )
        finally:
            memory_compiler_module.VcpRebuildMemoryGenerator = original

        self.assertEqual(code, 0)
        self.assertTrue(payload["dryRun"])
        self.assertEqual(payload["provider"], "x1api")
        self.assertTrue(output_path.exists())
        self.assertEqual(self.core.list_memory_cleanup_runs(limit=10)["items"], [])
        self.assertTrue(payload["validation"]["ok"])
        stable_diff = next(item for item in payload["run"]["diffs"] if item["op"] == "add_stable_memory")
        self.assertEqual(stable_diff["payload"]["evidenceEventIds"], [1])
