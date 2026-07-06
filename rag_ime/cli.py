from __future__ import annotations

import argparse
import hashlib
import json
import os
import plistlib
import shutil
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import replace
from pathlib import Path
from typing import Any, Sequence

from .adapter import InputMethodAdapter, SuggestionRequest
from .agent_hook import build_first_run_injection
from .codex_history import (
    CodexEvalCase,
    eval_report,
    evaluate_suggestions,
    input_event_from_codex_record,
    load_codex_history_records,
    load_eval_cases,
)
from .core_client import CoreMemory, FixtureCoreClient, JsonCommandCoreClient, default_fixture_memories
from .embeddings import embedding_provider_from_env
from .history_context import build_prediction_context
from .local_sqlite_core import LocalSqliteCoreClient
from .memory_cleanup import cleanup_plan_from_payload, cleanup_plan_to_payload, inspect_cleanup_plan, load_cleanup_run_from_file
from .memory_compiler import (
    build_memory_compile_bundle,
    cleanup_plan_from_compiler_report,
    compiler_generator_from_env,
    memory_compile_report_payload,
)
from .memory_eval import run_memory_optimizer_eval
from .memory_models import ImeQueryContext
from .memory_optimizer import AntiEchoGovernor, MemoryOptimizerConfig
from .memory_optimizer_models import ContextFrame, RawRetrievalHit
from .memory_generator import (
    MemoryGenerationError,
    VcpRebuildMemoryGenerator,
    generated_lexicon_dedupe_tag,
    generated_memory_context,
    generated_memory_dedupe_tag,
)
from .models import InputEvent, InputSuggestion, MemoryAction, ModelPrediction
from .payloads import action_response_payload, suggestions_response_payload
from .predictor import (
    PredictionBenchmarkCase,
    benchmark_prediction_provider,
    benchmark_streaming_ttft_provider,
    doctor_prediction_provider,
    prediction_provider_from_env,
    prediction_provider_status,
)
from .renderer import render_agent_injection, render_terminal_panel
from .reranker import rerank_candidate_dicts
from .rime_sidecar import build_rime_sidecar_response, record_rime_side_candidate_selection
from .scenarios import SCENARIOS, get_scenario
from .text_utils import compact_whitespace, now_ms
from .trigger_policy import TypingState, should_refresh_rag


DEFAULT_DB_PATH = Path(os.environ.get("RAG_IME_DB_PATH", ".rag-ime-data/rag-ime.sqlite"))


def _add_model_matrix_eval_parser(subparsers: argparse._SubParsersAction, name: str) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        name,
        help="Evaluate multiple local model ids on the same prediction cases",
    )
    parser.add_argument("--cases-file", required=True, help="JSONL cases with query and expectedTerms")
    parser.add_argument("--project", default="wisdom-weasel-rag-ime")
    parser.add_argument(
        "--base-url",
        default=os.environ.get("RAG_IME_PREDICTOR_BASE_URL", "http://127.0.0.1:11434/v1"),
        help="Base URL shared by all model ids. Defaults to Ollama /v1; --provider ollama normalizes it to native /api endpoints.",
    )
    parser.add_argument(
        "--models",
        default="qwen3.5:0.8b,qwen3.5:2b,qwen3.5:4b",
        help="Comma-separated model ids. Defaults to small Ollama qwen3.5 tags.",
    )
    parser.add_argument("--profile", default=os.environ.get("RAG_IME_PREDICTOR_PROFILE", "instant"))
    parser.add_argument("--provider", default=os.environ.get("RAG_IME_PREDICTOR_PROVIDER", "openai-compatible"))
    parser.add_argument("--max-candidates", type=int, default=3)
    parser.add_argument("--match", choices=("any", "all"), default="any")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--latency-budget-ms", type=int, default=150)
    parser.add_argument(
        "--failure-cooldown-ms",
        type=int,
        default=0,
        help="Prediction failure cooldown during matrix eval. Defaults to 0 so latency is measured per case.",
    )
    parser.add_argument(
        "--include-cases",
        action="store_true",
        help="Include full per-case evaluation details for every model.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rag-ime", description="Wisdom-Weasel RAG IME adapter prototype")
    parser.add_argument(
        "--core-mode",
        choices=("local", "fixture", "json"),
        default=os.environ.get("RAG_IME_CORE_MODE", "local"),
        help="Core backend. Defaults to local SQLite/FTS5.",
    )
    parser.add_argument(
        "--db-path",
        default=str(DEFAULT_DB_PATH),
        help="SQLite DB path for --core-mode local.",
    )
    parser.add_argument(
        "--core-command",
        default=os.environ.get("RAG_MEMORY_CORE_COMMAND", ""),
        help="JSON core command when --core-mode json.",
    )
    parser.add_argument(
        "--suggestion-cache-size",
        type=int,
        default=int(os.environ.get("RAG_IME_SUGGESTION_CACHE_SIZE", "128")),
        help="Process-local local-core suggestion cache size. Use 0 to disable.",
    )
    parser.add_argument(
        "--embedding-provider",
        choices=("none", "local-hash", "openai-compatible", "openai"),
        default=os.environ.get("RAG_IME_EMBEDDING_PROVIDER", "none"),
        help="Optional local-core vector provider. Defaults to none.",
    )
    parser.add_argument(
        "--embedding-vector-candidates",
        type=int,
        default=int(os.environ.get("RAG_IME_VECTOR_CANDIDATES", "80")),
        help="Maximum vector side-index candidates merged into retrieval.",
    )
    parser.add_argument(
        "--embedding-vector-weight",
        type=float,
        default=float(os.environ.get("RAG_IME_VECTOR_WEIGHT", "1.4")),
        help="Score multiplier for vector side-index similarity.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-db", help="Initialize the local SQLite/FTS5 database")

    memory_inspect = subparsers.add_parser("memory-inspect", help="Inspect v2 memory items")
    memory_inspect.add_argument("--project", default="")
    memory_inspect.add_argument("--kind", default="")
    memory_inspect.add_argument("--status", default="")
    memory_inspect.add_argument("--limit", type=int, default=20)

    memory_optimizer_trace = subparsers.add_parser("memory-optimizer-trace", help="Inspect one stored optimizer trace")
    memory_optimizer_trace.add_argument("trace_id")

    memory_candidate_explain = subparsers.add_parser("memory-candidate-explain", help="Explain one memory/optimizer candidate")
    memory_candidate_explain.add_argument("candidate_id")
    memory_candidate_explain.add_argument("--context-hash", default="")

    memory_governance = subparsers.add_parser("memory-governance", help="Inspect suppressions and tombstones")
    memory_governance.add_argument("--limit", type=int, default=20)
    memory_governance.add_argument("--include-inactive", action="store_true")

    governance_report = subparsers.add_parser("governance-report", help="Alias of memory-governance for PR-5 review")
    governance_report.add_argument("--limit", type=int, default=20)
    governance_report.add_argument("--include-inactive", action="store_true")

    tombstone = subparsers.add_parser("tombstone", help="Create one manual tombstone entry")
    tombstone.add_argument("target_value")
    tombstone.add_argument(
        "--target-type",
        choices=("memory_id", "normalized_text", "phrase", "source_event_id"),
        default="memory_id",
    )
    tombstone.add_argument("--reason", default="manual")
    tombstone.add_argument("--metadata-json", default="")
    tombstone.add_argument("--inactive", action="store_true")

    memory_cleanup_runs = subparsers.add_parser("memory-cleanup-runs", help="Inspect stored cleanup runs and diffs")
    memory_cleanup_runs.add_argument("--limit", type=int, default=20)
    memory_cleanup_runs.add_argument("--run-id", default="")
    memory_cleanup_runs.add_argument("--status", default="")

    cleanup_review = subparsers.add_parser("memory-cleanup-review", help="Approve or reject stored cleanup diffs")
    cleanup_review.add_argument("--run-id", required=True)
    cleanup_review.add_argument("--status", choices=("pending", "approved", "rejected"), required=True)
    cleanup_review.add_argument("--diff-id", action="append", type=int, default=[])
    cleanup_review.add_argument("--diff-index", action="append", type=int, default=[])

    compile_review = subparsers.add_parser("memory-compile-review", help="Alias of memory-cleanup-review for compiler-generated runs")
    compile_review.add_argument("--run-id", required=True)
    compile_review.add_argument("--status", choices=("pending", "approved", "rejected"), required=True)
    compile_review.add_argument("--diff-id", action="append", type=int, default=[])
    compile_review.add_argument("--diff-index", action="append", type=int, default=[])

    recompute_tags = subparsers.add_parser("memory-recompute-tags", help="Recompute v2 tag graph edges")
    recompute_tags.add_argument("--project", default="")

    retrieve_v2 = subparsers.add_parser("retrieve-candidates-v2", help="Run the v2 retrieval mixer")
    retrieve_v2.add_argument("current_input")
    retrieve_v2.add_argument("--recent-context", default="")
    retrieve_v2.add_argument("--committed-context", default="")
    retrieve_v2.add_argument("--project", default="wisdom-weasel-rag-ime")
    retrieve_v2.add_argument("--app", default="")
    retrieve_v2.add_argument("--top-k", type=int, default=5)
    retrieve_v2.add_argument("--allow-raw-event-candidates", action="store_true")

    anti_echo_demo = subparsers.add_parser("anti-echo-demo", help="Run the PR-5 anti-echo governor on ad-hoc candidates")
    anti_echo_demo.add_argument("candidate_text", nargs="+")
    anti_echo_demo.add_argument("--candidate-source", choices=("rag", "memory", "phrase", "cold_knowledge"), default="rag")
    anti_echo_demo.add_argument(
        "--hit-source",
        choices=("fts", "stable_memory", "phrase", "tag_graph", "rime_feedback", "vector", "cold_knowledge"),
        default="fts",
    )
    anti_echo_demo.add_argument("--committed-tail", default="")
    anti_echo_demo.add_argument("--raw-input", default="")
    anti_echo_demo.add_argument("--preedit", default="")
    anti_echo_demo.add_argument("--semantic-query", default="")
    anti_echo_demo.add_argument(
        "--semantic-query-source",
        choices=("rime_candidate", "commit_preview", "preedit", "raw_input", "none"),
        default="none",
    )
    anti_echo_demo.add_argument("--context-hash", default="ctx:anti-echo-demo")
    anti_echo_demo.add_argument("--session-id", default="anti-echo-demo")
    anti_echo_demo.add_argument("--request-seq", type=int, default=1)
    anti_echo_demo.add_argument("--front-app-bundle-id", default="manual.cli")
    anti_echo_demo.add_argument(
        "--input-mode",
        choices=("pinyin_composition", "post_commit_continuation", "english", "code", "path", "number", "punctuation", "unknown"),
        default="post_commit_continuation",
    )
    anti_echo_demo.add_argument("--project", default="wisdom-weasel-rag-ime")
    anti_echo_demo.add_argument("--source-tag", action="append", default=[])
    anti_echo_demo.add_argument("--governance-json", default="")

    cleanup_plan = subparsers.add_parser("memory-cleanup-plan", help="Build a dry-run cleanup diff plan")
    cleanup_plan.add_argument("--project", default="")
    cleanup_plan.add_argument("--since-days", type=int, default=90)
    cleanup_plan.add_argument("--provider", default="")
    cleanup_plan.add_argument("--model", default="")
    cleanup_plan.add_argument("--out", default="")

    cleanup_apply = subparsers.add_parser("memory-cleanup-apply", help="Apply a stored cleanup diff plan")
    cleanup_apply.add_argument("--run", default="", help="JSON cleanup plan file")
    cleanup_apply.add_argument("--run-id", default="", help="Stored cleanup run id")
    cleanup_apply.add_argument("--only-approved", action="store_true")

    cleanup_rollback = subparsers.add_parser("memory-cleanup-rollback", help="Rollback an applied cleanup diff plan")
    cleanup_rollback.add_argument("--run-id", required=True)

    cleanup_preview = subparsers.add_parser("cleanup-preview", help="Build an offline cleanup diff preview without modifying the DB")
    cleanup_preview.add_argument("--provider", choices=("local-rule", "x1api", "x1top", "openai-compatible", "model-api"), default="local-rule")
    cleanup_preview.add_argument("--project", default="wisdom-weasel-rag-ime")
    cleanup_preview.add_argument("--since-days", type=int, default=90)
    cleanup_preview.add_argument("--recent-limit", type=int, default=80)
    cleanup_preview.add_argument("--phrase-limit", type=int, default=60)
    cleanup_preview.add_argument("--memory-limit", type=int, default=120)
    cleanup_preview.add_argument("--governance-limit", type=int, default=40)
    cleanup_preview.add_argument("--max-memories", type=int, default=4)
    cleanup_preview.add_argument("--max-lexicon-phrases", type=int, default=8)
    cleanup_preview.add_argument("--max-hide-suggestions", type=int, default=12)
    cleanup_preview.add_argument("--model", default="")
    cleanup_preview.add_argument(
        "--model-env-path",
        default=os.environ.get("RAG_IME_MODEL_ENV", "")
        or os.environ.get("RAG_IME_X1API_ENV", "")
        or os.environ.get("RAG_IME_VCP_REBUILD_ENV", ""),
    )
    cleanup_preview.add_argument("--allow-private-paths", action="store_true")
    cleanup_preview.add_argument("--output", default="")

    cleanup_validate = subparsers.add_parser("cleanup-validate", help="Validate a cleanup diff plan before apply")
    cleanup_validate.add_argument("--run-id", default="")
    cleanup_validate.add_argument("--run", default="", help="JSON cleanup plan file")

    cleanup_apply = subparsers.add_parser("cleanup-apply", help="Apply a cleanup diff plan after explicit confirmation")
    cleanup_apply.add_argument("--run-id", default="")
    cleanup_apply.add_argument("--run", default="", help="JSON cleanup plan file")
    cleanup_apply.add_argument("--only-approved", action="store_true")
    cleanup_apply.add_argument("--apply", action="store_true", help="Required to actually modify the DB")

    cleanup_rollback_v2 = subparsers.add_parser("cleanup-rollback", help="Rollback an applied cleanup run")
    cleanup_rollback_v2.add_argument("--run-id", required=True)

    memory_compile = subparsers.add_parser(
        "memory-compile",
        help="Export a sanitized local bundle and build a dry-run cleanup diff with an explicitly configured model",
    )
    memory_compile.add_argument("--project", default="wisdom-weasel-rag-ime")
    memory_compile.add_argument("--since-days", type=int, default=14)
    memory_compile.add_argument("--recent-limit", type=int, default=80)
    memory_compile.add_argument("--phrase-limit", type=int, default=60)
    memory_compile.add_argument("--memory-limit", type=int, default=120)
    memory_compile.add_argument("--governance-limit", type=int, default=40)
    memory_compile.add_argument("--max-memories", type=int, default=4)
    memory_compile.add_argument("--max-lexicon-phrases", type=int, default=8)
    memory_compile.add_argument("--max-hide-suggestions", type=int, default=12)
    memory_compile.add_argument("--provider", default="")
    memory_compile.add_argument("--model", default="")
    memory_compile.add_argument(
        "--model-env-path",
        default=os.environ.get("RAG_IME_MODEL_ENV", "")
        or os.environ.get("RAG_IME_X1API_ENV", "")
        or os.environ.get("RAG_IME_VCP_REBUILD_ENV", ""),
    )
    memory_compile.add_argument("--output", default="", help="Optional JSON path. When set, writes the dry-run diff plan.")
    memory_compile.add_argument("--allow-private-paths", action="store_true")
    memory_compile.add_argument("--dry-run", action="store_true", help="Accepted for compatibility; memory-compile is always dry-run.")
    memory_compile.add_argument(
        "--save-draft",
        action="store_true",
        help="Store the generated diff as a reviewable draft run. Default memory-compile does not modify the DB.",
    )

    memory_compile_apply = subparsers.add_parser("memory-compile-apply", help="Apply a reviewed diff emitted by memory-compile")
    memory_compile_apply.add_argument("--diff", default="")
    memory_compile_apply.add_argument("--run-id", default="")
    memory_compile_apply.add_argument("--only-approved", action="store_true")

    memory_compile_rollback = subparsers.add_parser("memory-compile-rollback", help="Rollback an applied memory-compile run")
    memory_compile_rollback.add_argument("--run-id", required=True)

    rebuild_vector = subparsers.add_parser("rebuild-vector-index", help="Backfill optional local-core vector side index")
    rebuild_vector.add_argument("--project", default="")
    rebuild_vector.add_argument("--limit", type=int, default=0)

    seed = subparsers.add_parser("seed-demo", help="Seed local DB with deterministic demo memories")
    seed.add_argument("--reset", action="store_true", help="Reset local DB before seeding")

    seed_eval_cases = subparsers.add_parser(
        "seed-eval-cases",
        help="Seed local DB with deterministic memories derived from eval cases",
    )
    seed_eval_cases.add_argument("--cases-file", required=True, help="JSONL cases with query and expectedTerms")
    seed_eval_cases.add_argument("--project", default="wisdom-weasel-rag-ime")

    commit = subparsers.add_parser("commit", help="Record one committed input event")
    commit.add_argument("text")
    commit.add_argument("--recent-context", default="")
    commit.add_argument("--project", default="wisdom-weasel-rag-ime")
    commit.add_argument("--preedit", default="")
    commit.add_argument("--source", default="manual_commit")
    commit.add_argument("--tag", action="append", default=[])
    commit.add_argument("--sensitive", action="store_true", help="Do not record this input")
    commit.add_argument("--recording-disabled", action="store_true", help="Skip recording for this commit")

    generate_memory = subparsers.add_parser(
        "generate-memory",
        help="Distill stable long-term memory from text through x1top/x1api-compatible config",
    )
    generate_memory.add_argument("text")
    generate_memory.add_argument("--recent-context", default="")
    generate_memory.add_argument("--project", default="wisdom-weasel-rag-ime")
    generate_memory.add_argument("--app", default="manual")
    generate_memory.add_argument("--max-items", type=int, default=3)
    generate_memory.add_argument("--dry-run", action="store_true")
    generate_memory.add_argument("--allow-duplicates", action="store_true")
    generate_memory.add_argument(
        "--model-env-path",
        default=os.environ.get("RAG_IME_MODEL_ENV", "")
        or os.environ.get("RAG_IME_X1API_ENV", "")
        or os.environ.get("RAG_IME_VCP_REBUILD_ENV", ""),
        help="x1top/x1api-compatible env file. Prefer this over the legacy --vcp-env-path.",
    )
    generate_memory.add_argument("--vcp-env-path", default="", help=argparse.SUPPRESS)

    optimize_core = subparsers.add_parser(
        "optimize-core",
        help="Use x1top/x1api-compatible config to optimize RAG memory and lexicon phrases from local history",
    )
    optimize_core.add_argument("--project", default="wisdom-weasel-rag-ime")
    optimize_core.add_argument("--app", default="manual")
    optimize_core.add_argument("--recent-limit", type=int, default=80)
    optimize_core.add_argument("--phrase-limit", type=int, default=60)
    optimize_core.add_argument("--max-memories", type=int, default=4)
    optimize_core.add_argument("--max-lexicon-phrases", type=int, default=8)
    optimize_core.add_argument("--max-hide-suggestions", type=int, default=12)
    optimize_core.add_argument("--dry-run", action="store_true")
    optimize_core.add_argument("--allow-duplicates", action="store_true")
    optimize_core.add_argument(
        "--model-env-path",
        default=os.environ.get("RAG_IME_MODEL_ENV", "")
        or os.environ.get("RAG_IME_X1API_ENV", "")
        or os.environ.get("RAG_IME_VCP_REBUILD_ENV", ""),
    )

    suggest = subparsers.add_parser("suggest", help="Render suggestions for one input")
    suggest.add_argument("current_input")
    suggest.add_argument("--recent-context", default="")
    suggest.add_argument("--project", default="wisdom-weasel-rag-ime")
    suggest.add_argument("--top-k", type=int, default=5)

    suggest_json = subparsers.add_parser("suggest-json", help="Return structured suggestions for native frontends")
    suggest_json.add_argument("current_input")
    suggest_json.add_argument("--recent-context", default="")
    suggest_json.add_argument("--project", default="wisdom-weasel-rag-ime")
    suggest_json.add_argument("--top-k", type=int, default=5)

    rime_suggest_json = subparsers.add_parser(
        "rime-suggest-json",
        help="Return merged Rime + RAG/model side candidates for Squirrel/Rime frontends",
    )
    rime_suggest_json.add_argument(
        "--payload-file",
        default="-",
        help="JSON request file. Use '-' to read stdin.",
    )

    rime_select_json = subparsers.add_parser(
        "rime-select-json",
        help="Record an accepted Rime side candidate selection and return structured JSON",
    )
    rime_select_json.add_argument(
        "--payload-file",
        default="-",
        help="JSON request file. Use '-' to read stdin.",
    )

    action_json = subparsers.add_parser("action-json", help="Apply one memory action and return structured JSON")
    action_json.add_argument("action_type", choices=("accepted", "accept", "skipped", "skip", "pin", "unpin", "downrank", "delete", "hide", "restore"))
    action_json.add_argument("--memory-id", required=True)
    action_json.add_argument("--suggestion-id", default="")
    action_json.add_argument("--source-event-id", type=int, default=0)
    action_json.add_argument("--query", default="")
    action_json.add_argument("--surface-text", default="")

    demo = subparsers.add_parser("demo", help="Render one or all UI scenarios")
    demo.add_argument("--scenario", choices=[item.scenario_id for item in SCENARIOS], default="")
    demo.add_argument("--top-k", type=int, default=5)

    subparsers.add_parser("action-demo", help="Show pin/downrank/delete effects against fixture core")

    trigger = subparsers.add_parser("trigger-demo", help="Show RAG refresh trigger decisions")
    trigger.add_argument("current_input")
    trigger.add_argument("--idle-ms", type=int, default=0)
    trigger.add_argument("--app-kind", default="editor")
    trigger.add_argument("--explicit", action="store_true")
    trigger.add_argument("--sensitive", action="store_true")

    hook = subparsers.add_parser("agent-hook", help="Build PROJECT_MEMORY_BLOCK")
    hook.add_argument("--project", default="wisdom-weasel-rag-ime")
    hook.add_argument("--query", default="当前项目背景 用户偏好 最近决策 禁止事项 推荐下一步")
    hook.add_argument("--top-k", type=int, default=5)

    import_codex = subparsers.add_parser("import-codex-history", help="Import Codex JSONL history into local memory")
    import_codex.add_argument("--path", required=True, help="Codex JSONL file or directory containing *.jsonl files")
    import_codex.add_argument("--project", default="wisdom-weasel-rag-ime")
    import_codex.add_argument("--limit", type=int, default=200)
    import_codex.add_argument("--min-chars", type=int, default=12)
    import_codex.add_argument("--max-chars", type=int, default=1600)
    import_codex.add_argument(
        "--path-order",
        choices=("mtime-desc", "mtime-asc", "path"),
        default="mtime-desc",
        help="Order JSONL files when --path is a directory. Defaults to newest modified sessions first.",
    )
    import_codex.add_argument(
        "--roles",
        default="user",
        help="Comma-separated Codex roles to import. Defaults to user; use 'any' to keep all parsed roles.",
    )
    import_codex.add_argument("--sample-size", type=int, default=3)
    import_codex.add_argument("--dry-run", action="store_true", help="Parse and summarize without writing memory")
    import_codex.add_argument("--allow-duplicates", action="store_true", help="Import records even if their stable record tag already exists")

    prune_codex = subparsers.add_parser(
        "prune-codex-history-noise",
        help="Hide imported Codex history rows that are not useful user-memory candidates",
    )
    prune_codex.add_argument("--project", default="wisdom-weasel-rag-ime")
    prune_codex.add_argument(
        "--keep-roles",
        default="user",
        help="Comma-separated Codex roles to keep active. Defaults to user.",
    )
    prune_codex.add_argument("--dry-run", action="store_true", help="Report rows that would be hidden without changing the database")

    organize_rag = subparsers.add_parser(
        "organize-rag-db",
        help="Hide noisy local RAG rows such as one-off generated side candidates and IME complaint/debug feedback",
    )
    organize_rag.add_argument("--project", default="wisdom-weasel-rag-ime")
    organize_rag.add_argument("--dry-run", action="store_true", help="Report rows that would be hidden without changing the database")
    organize_rag.add_argument(
        "--min-generated-accepts",
        type=int,
        default=3,
        help="Generated model/RAG side candidates need this many accepts/frequency before they survive cleanup.",
    )
    organize_rag.add_argument("--sample-size", type=int, default=12)

    eval_codex = subparsers.add_parser("eval-codex-history", help="Evaluate retrieval against explicit JSONL cases")
    eval_codex.add_argument("--cases-file", required=True, help="JSONL cases with query and expectedTerms")
    eval_codex.add_argument("--project", default="wisdom-weasel-rag-ime")
    eval_codex.add_argument("--top-k", type=int, default=5)
    eval_codex.add_argument("--match", choices=("any", "all"), default="any")
    eval_codex.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="Repeat all cases to measure warm-cache latency and hit behavior.",
    )

    eval_rime_sidecar = subparsers.add_parser(
        "eval-rime-sidecar",
        help="Evaluate Rime sidecar side candidates against explicit JSONL cases",
    )
    eval_rime_sidecar.add_argument("--cases-file", required=True, help="JSONL cases with query and expectedTerms")
    eval_rime_sidecar.add_argument("--project", default="wisdom-weasel-rag-ime")
    eval_rime_sidecar.add_argument("--match", choices=("any", "all"), default="any")
    eval_rime_sidecar.add_argument("--repeat", type=int, default=1)
    eval_rime_sidecar.add_argument("--max-visible-candidates", type=int, default=6)
    eval_rime_sidecar.add_argument("--max-side-candidates", type=int, default=3)
    eval_rime_sidecar.add_argument("--sidecar-latency-budget-ms", type=int, default=300)
    eval_rime_sidecar.add_argument("--rime-cache-ttl-ms", type=int, default=int(os.environ.get("RAG_IME_RIME_CACHE_TTL_MS", "400")))
    eval_rime_sidecar.add_argument("--force-side-candidates", action="store_true")

    eval_memory_optimizer = subparsers.add_parser(
        "eval-memory-optimizer",
        help="Run sidecar + memory optimizer regression cases against a local temporary core",
    )
    eval_memory_optimizer.add_argument("cases_file", help="JSONL cases for memory optimizer gates")
    eval_memory_optimizer.add_argument("--project", default="wisdom-weasel-rag-ime")
    eval_memory_optimizer.add_argument("--repeat", type=int, default=1)
    eval_memory_optimizer.add_argument("--max-visible-candidates", type=int, default=4)
    eval_memory_optimizer.add_argument("--max-side-candidates", type=int, default=2)
    eval_memory_optimizer.add_argument("--latency-budget-ms", type=int, default=150)
    eval_memory_optimizer.add_argument(
        "--optimizer-max-ms",
        type=int,
        default=int(os.environ.get("RAG_IME_MEMORY_OPTIMIZER_MAX_MS", "15")),
    )

    predict_benchmark = subparsers.add_parser("predict-benchmark", help="Measure local model prediction latency")
    predict_benchmark.add_argument("--case", action="append", default=[], help="Input case to predict. Can be repeated.")
    predict_benchmark.add_argument("--recent-context", default="")
    predict_benchmark.add_argument("--project", default="wisdom-weasel-rag-ime")
    predict_benchmark.add_argument("--max-candidates", type=int, default=3)
    predict_benchmark.add_argument("--latency-budget-ms", type=int, default=150)

    predictor_ttft = subparsers.add_parser(
        "predictor-ttft",
        help="Measure streaming first-chunk latency for the local model lane",
    )
    predictor_ttft.add_argument("--case", action="append", default=[], help="Input case to predict. Can be repeated.")
    predictor_ttft.add_argument("--recent-context", default="")
    predictor_ttft.add_argument("--project", default="wisdom-weasel-rag-ime")
    predictor_ttft.add_argument("--max-candidates", type=int, default=3)
    predictor_ttft.add_argument("--repeat", type=int, default=3)
    predictor_ttft.add_argument("--latency-budget-ms", type=int, default=200)

    bench_ime_ttfc = subparsers.add_parser(
        "bench-ime-ttfc",
        help="Run a multi-case streaming TTFC benchmark for IME model candidates",
    )
    bench_ime_ttfc.add_argument("--cases-file", default="", help="JSONL cases with query/currentInput fields")
    bench_ime_ttfc.add_argument("--case", action="append", default=[], help="Inline current input case. Can be repeated.")
    bench_ime_ttfc.add_argument("--recent-context", default="")
    bench_ime_ttfc.add_argument("--project", default="wisdom-weasel-rag-ime")
    bench_ime_ttfc.add_argument(
        "--base-url",
        default=os.environ.get("RAG_IME_PREDICTOR_BASE_URL", "http://127.0.0.1:11434"),
        help="Base URL shared by all model ids. Ollama uses the native /api endpoint.",
    )
    bench_ime_ttfc.add_argument(
        "--models",
        default=os.environ.get("RAG_IME_PREDICTOR_MODEL", "qwen3.5:0.8b-mlx"),
        help="Comma-separated model ids to measure.",
    )
    bench_ime_ttfc.add_argument("--profile", default=os.environ.get("RAG_IME_PREDICTOR_PROFILE", "instant"))
    bench_ime_ttfc.add_argument("--provider", default=os.environ.get("RAG_IME_PREDICTOR_PROVIDER", "ollama"))
    bench_ime_ttfc.add_argument("--max-candidates", type=int, default=3)
    bench_ime_ttfc.add_argument("--repeat", type=int, default=20)
    bench_ime_ttfc.add_argument(
        "--warmup-runs",
        type=int,
        default=0,
        help="Run and discard this many full case passes before scoring TTFC. Use this to separate cold load from resident IME latency.",
    )
    bench_ime_ttfc.add_argument("--latency-budget-ms", type=int, default=200)
    bench_ime_ttfc.add_argument(
        "--failure-cooldown-ms",
        type=int,
        default=0,
        help="Prediction failure cooldown during TTFC benchmark. Defaults to 0 so every sample is measured.",
    )
    bench_ime_ttfc.add_argument(
        "--include-cases",
        action="store_true",
        help="Include full per-sample streaming measurements for every model.",
    )

    predictor_status = subparsers.add_parser("predictor-status", help="Show local model prediction configuration")
    predictor_status.add_argument(
        "--probe-capabilities",
        action="store_true",
        help="Probe provider health endpoints for runtime capability claims such as MLX prompt-cache use",
    )

    predictor_doctor = subparsers.add_parser("predictor-doctor", help="Probe local model endpoint and one short prediction")
    predictor_doctor.add_argument("--case", default="RAG 输入法")
    predictor_doctor.add_argument("--recent-context", default="")
    predictor_doctor.add_argument("--max-candidates", type=int, default=3)
    predictor_doctor.add_argument("--latency-budget-ms", type=int, default=150)

    eval_prediction = subparsers.add_parser(
        "eval-prediction",
        help="Evaluate the local model prediction lane against explicit JSONL cases",
    )
    eval_prediction.add_argument("--cases-file", required=True, help="JSONL cases with query and expectedTerms")
    eval_prediction.add_argument("--project", default="wisdom-weasel-rag-ime")
    eval_prediction.add_argument("--max-candidates", type=int, default=3)
    eval_prediction.add_argument("--match", choices=("any", "all"), default="any")
    eval_prediction.add_argument("--repeat", type=int, default=1)
    eval_prediction.add_argument("--latency-budget-ms", type=int, default=150)

    eval_model_matrix = _add_model_matrix_eval_parser(subparsers, "eval-model-matrix")
    _add_model_matrix_eval_parser(subparsers, "model-matrix-eval")

    rerank_demo = subparsers.add_parser(
        "rerank-demo",
        help="Run the PR-9 source-aware reranker on ad-hoc mixed candidates",
    )
    rerank_demo.add_argument("--query", default="")
    rerank_demo.add_argument("--recent-context", default="")
    rerank_demo.add_argument("--max-candidates", type=int, default=10)
    rerank_demo.add_argument(
        "--candidate",
        action="append",
        default=[],
        help="Candidate as source:text or source|text. Repeat for Rime/model/RAG/memory inputs.",
    )
    rerank_demo.add_argument(
        "--candidate-json",
        action="append",
        default=[],
        help="Candidate JSON object. Can be repeated for confidence, feedback, and pinned metadata.",
    )

    eval_comparison = subparsers.add_parser(
        "eval-comparison",
        help="Evaluate RAG suggestions and local model predictions on the same JSONL cases",
    )
    eval_comparison.add_argument("--cases-file", required=True, help="JSONL cases with query and expectedTerms")
    eval_comparison.add_argument("--project", default="wisdom-weasel-rag-ime")
    eval_comparison.add_argument("--top-k", type=int, default=5)
    eval_comparison.add_argument("--max-candidates", type=int, default=3)
    eval_comparison.add_argument("--match", choices=("any", "all"), default="any")
    eval_comparison.add_argument("--repeat", type=int, default=1)
    eval_comparison.add_argument("--latency-budget-ms", type=int, default=150)

    cache_probe = subparsers.add_parser(
        "cache-probe",
        help="Probe warm cache hits for repeated suggest and Rime sidecar requests",
    )
    cache_probe.add_argument("current_input", nargs="?", default="RAG 输入法")
    cache_probe.add_argument("--recent-context", default="")
    cache_probe.add_argument("--project", default="wisdom-weasel-rag-ime")
    cache_probe.add_argument("--top-k", type=int, default=5)
    cache_probe.add_argument("--repeat", type=int, default=3)
    cache_probe.add_argument(
        "--rime-candidate",
        action="append",
        default=[],
        help="Structured Rime candidate text used for semantic cache probing. Can be repeated.",
    )
    cache_probe.add_argument("--force-side-candidates", action="store_true")
    cache_probe.add_argument("--rime-cache-ttl-ms", type=int, default=int(os.environ.get("RAG_IME_RIME_CACHE_TTL_MS", "400")))

    quality_gate = subparsers.add_parser(
        "quality-gate",
        help="Run the local acceptance, RAG eval, Rime sidecar eval, and cache-hit gates",
    )
    quality_gate.add_argument("--cases-file", default="docs/eval/codex-history-cases.example.jsonl")
    quality_gate.add_argument("--project", default="wisdom-weasel-rag-ime")
    quality_gate.add_argument("--top-k", type=int, default=5)
    quality_gate.add_argument("--match", choices=("any", "all"), default="any")
    quality_gate.add_argument("--repeat", type=int, default=1)
    quality_gate.add_argument("--min-rag-pass-rate", type=float, default=0.1)
    quality_gate.add_argument("--min-sidecar-pass-rate", type=float, default=0.1)
    quality_gate.add_argument("--min-rag-top1-accuracy", type=float, default=0.0)
    quality_gate.add_argument("--min-sidecar-top1-accuracy", type=float, default=0.0)
    quality_gate.add_argument("--min-rag-mrr", type=float, default=0.0)
    quality_gate.add_argument("--min-sidecar-mrr", type=float, default=0.0)
    quality_gate.add_argument("--max-rag-noise-rate", type=float, default=1.0)
    quality_gate.add_argument("--max-sidecar-noise-rate", type=float, default=1.0)
    quality_gate.add_argument("--max-sidecar-rag-timeout-rate", type=float, default=1.0)
    quality_gate.add_argument("--max-sidecar-model-timeout-rate", type=float, default=1.0)
    quality_gate.add_argument("--max-old-input-echo-rate", type=float, default=1.0)
    quality_gate.add_argument("--require-model-ttfc", action="store_true")
    quality_gate.add_argument("--model-ttfc-cases-file", default="docs/eval/ime-ttfc-cases.example.jsonl")
    quality_gate.add_argument(
        "--model-ttfc-provider",
        default=os.environ.get("RAG_IME_PREDICTOR_PROVIDER", "ollama"),
        help="Provider used for the optional first-candidate model gate.",
    )
    quality_gate.add_argument(
        "--model-ttfc-base-url",
        default=os.environ.get("RAG_IME_PREDICTOR_BASE_URL", "http://127.0.0.1:11434"),
        help="Base URL used for the optional first-candidate model gate.",
    )
    quality_gate.add_argument(
        "--model-ttfc-models",
        default=os.environ.get("RAG_IME_PREDICTOR_MODEL", "qwen3.5:0.8b-mlx"),
        help="Comma-separated model ids for the optional first-candidate model gate.",
    )
    quality_gate.add_argument("--model-ttfc-profile", default=os.environ.get("RAG_IME_PREDICTOR_PROFILE", "instant"))
    quality_gate.add_argument("--model-ttfc-repeat", type=int, default=3)
    quality_gate.add_argument(
        "--model-ttfc-warmup-runs",
        type=int,
        default=0,
        help="Warm the model with this many TTFC case passes before scoring the optional model gate.",
    )
    quality_gate.add_argument("--model-ttfc-latency-budget-ms", type=int, default=200)
    quality_gate.add_argument("--max-model-ttfc-p95-ms", type=int, default=200)
    quality_gate.add_argument("--max-model-ttfc-over-budget-rate", type=float, default=0.0)
    quality_gate.add_argument("--cache-repeat", type=int, default=3)
    quality_gate.add_argument("--cache-current-input", default="RAG 输入法")
    quality_gate.add_argument("--cache-recent-context", default="quality gate cache probe")
    quality_gate.add_argument("--rime-candidate", action="append", default=[])
    quality_gate.add_argument("--max-visible-candidates", type=int, default=6)
    quality_gate.add_argument("--max-side-candidates", type=int, default=3)
    quality_gate.add_argument("--sidecar-latency-budget-ms", type=int, default=300)
    quality_gate.add_argument("--rime-cache-ttl-ms", type=int, default=int(os.environ.get("RAG_IME_RIME_CACHE_TTL_MS", "400")))
    quality_gate.add_argument("--force-side-candidates", action="store_true")
    quality_gate.add_argument("--require-suggestion-cache", action="store_true")
    quality_gate.add_argument("--skip-acceptance-check", action="store_true")
    quality_gate.add_argument(
        "--require-input-source-ready",
        action="store_true",
        help="Require the macOS Squirrel input source to be installed, enabled, and currently selected.",
    )
    quality_gate.add_argument(
        "--input-source-id",
        default=os.environ.get("RAG_IME_SQUIRREL_INPUT_SOURCE_ID", "im.rime.inputmethod.Squirrel.Hans"),
        help="macOS input source id checked by --require-input-source-ready.",
    )
    quality_gate.add_argument(
        "--input-source-check-script",
        default=os.environ.get("RAG_IME_INPUT_SOURCE_CHECK_SCRIPT", ""),
        help="Override scripts/check_macos_input_source.sh for input-source readiness checks.",
    )
    quality_gate.add_argument(
        "--require-predictor-capability",
        action="append",
        default=[],
        choices=("streaming", "residentModel", "promptCache", "seededPromptReplay", "kvFork", "sequenceFork", "batchCandidates", "logitsTopK", "serverTiming"),
        help="Require a local model provider capability. Repeat for Wisdom-Weasel-style gates.",
    )
    quality_gate.add_argument("--include-cases", action="store_true", help="Include full per-case eval details in the quality-gate JSON")

    squirrel_tryout_gate = subparsers.add_parser(
        "squirrel-tryout-gate",
        help="Run the real macOS Squirrel tryout readiness gate and quality gate",
    )
    squirrel_tryout_gate.add_argument("--cases-file", default="docs/eval/codex-history-cases.example.jsonl")
    squirrel_tryout_gate.add_argument("--project", default="wisdom-weasel-rag-ime")
    squirrel_tryout_gate.add_argument("--top-k", type=int, default=5)
    squirrel_tryout_gate.add_argument("--match", choices=("any", "all"), default="any")
    squirrel_tryout_gate.add_argument("--repeat", type=int, default=1)
    squirrel_tryout_gate.add_argument("--min-rag-pass-rate", type=float, default=0.1)
    squirrel_tryout_gate.add_argument("--min-sidecar-pass-rate", type=float, default=0.1)
    squirrel_tryout_gate.add_argument("--min-rag-top1-accuracy", type=float, default=0.0)
    squirrel_tryout_gate.add_argument("--min-sidecar-top1-accuracy", type=float, default=0.0)
    squirrel_tryout_gate.add_argument("--min-rag-mrr", type=float, default=0.0)
    squirrel_tryout_gate.add_argument("--min-sidecar-mrr", type=float, default=0.0)
    squirrel_tryout_gate.add_argument("--max-rag-noise-rate", type=float, default=1.0)
    squirrel_tryout_gate.add_argument("--max-sidecar-noise-rate", type=float, default=1.0)
    squirrel_tryout_gate.add_argument("--max-sidecar-rag-timeout-rate", type=float, default=1.0)
    squirrel_tryout_gate.add_argument("--max-sidecar-model-timeout-rate", type=float, default=1.0)
    squirrel_tryout_gate.add_argument("--max-old-input-echo-rate", type=float, default=1.0)
    squirrel_tryout_gate.add_argument("--cache-repeat", type=int, default=3)
    squirrel_tryout_gate.add_argument("--cache-current-input", default="RAG 输入法")
    squirrel_tryout_gate.add_argument("--cache-recent-context", default="squirrel tryout cache probe")
    squirrel_tryout_gate.add_argument("--rime-candidate", action="append", default=[])
    squirrel_tryout_gate.add_argument("--max-visible-candidates", type=int, default=6)
    squirrel_tryout_gate.add_argument("--max-side-candidates", type=int, default=3)
    squirrel_tryout_gate.add_argument("--sidecar-latency-budget-ms", type=int, default=300)
    squirrel_tryout_gate.add_argument("--rime-cache-ttl-ms", type=int, default=int(os.environ.get("RAG_IME_RIME_CACHE_TTL_MS", "400")))
    squirrel_tryout_gate.add_argument(
        "--no-force-side-candidates",
        action="store_true",
        help="Do not force side-candidate refreshes during the quality-gate portion.",
    )
    squirrel_tryout_gate.add_argument(
        "--no-require-suggestion-cache",
        action="store_true",
        help="Do not require warm local-core suggestion-cache hits.",
    )
    squirrel_tryout_gate.add_argument("--skip-acceptance-check", action="store_true")
    squirrel_tryout_gate.add_argument(
        "--input-source-id",
        default=os.environ.get("RAG_IME_SQUIRREL_INPUT_SOURCE_ID", "im.rime.inputmethod.Squirrel.Hans"),
    )
    squirrel_tryout_gate.add_argument(
        "--input-source-check-script",
        default=os.environ.get("RAG_IME_INPUT_SOURCE_CHECK_SCRIPT", ""),
    )
    squirrel_tryout_gate.add_argument(
        "--include-input-source-audit",
        action="store_true",
        help="Attach the read-only Squirrel input-source audit report to the tryout JSON.",
    )
    squirrel_tryout_gate.add_argument("--squirrel-app", default=os.environ.get("RAG_IME_SQUIRREL_APP", ""))
    squirrel_tryout_gate.add_argument(
        "--squirrel-config-path",
        default=os.environ.get(
            "RAG_IME_SQUIRREL_CUSTOM_CONFIG",
            str(Path.home() / "Library" / "Rime" / "squirrel.custom.yaml"),
        ),
    )
    squirrel_tryout_gate.add_argument(
        "--expected-rime-primary-schema",
        default=os.environ.get("RAG_IME_RIME_PRIMARY_SCHEMA", "luna_pinyin_simp"),
    )
    squirrel_tryout_gate.add_argument(
        "--expected-rime-page-size",
        type=int,
        default=int(os.environ.get("RAG_IME_RIME_PAGE_SIZE", "8")),
    )
    squirrel_tryout_gate.add_argument("--sidecar-url", default=os.environ.get("RAG_IME_SIDECAR_URL", "http://127.0.0.1:8766"))
    squirrel_tryout_gate.add_argument(
        "--launch-agent-label",
        default=os.environ.get("RAG_IME_LAUNCH_AGENT_LABEL", "com.rag-ime.sidecar"),
    )
    squirrel_tryout_gate.add_argument("--skip-launch-agent", action="store_true")
    squirrel_tryout_gate.add_argument("--skip-sidecar-health", action="store_true")
    squirrel_tryout_gate.add_argument("--require-model-ttfc", action="store_true")
    squirrel_tryout_gate.add_argument("--model-ttfc-cases-file", default="docs/eval/ime-ttfc-cases.example.jsonl")
    squirrel_tryout_gate.add_argument("--model-ttfc-provider", default=os.environ.get("RAG_IME_PREDICTOR_PROVIDER", "ollama"))
    squirrel_tryout_gate.add_argument("--model-ttfc-base-url", default=os.environ.get("RAG_IME_PREDICTOR_BASE_URL", "http://127.0.0.1:11434"))
    squirrel_tryout_gate.add_argument("--model-ttfc-models", default=os.environ.get("RAG_IME_PREDICTOR_MODEL", "qwen3.5:0.8b-mlx"))
    squirrel_tryout_gate.add_argument("--model-ttfc-profile", default=os.environ.get("RAG_IME_PREDICTOR_PROFILE", "instant"))
    squirrel_tryout_gate.add_argument("--model-ttfc-repeat", type=int, default=3)
    squirrel_tryout_gate.add_argument("--model-ttfc-warmup-runs", type=int, default=0)
    squirrel_tryout_gate.add_argument("--model-ttfc-latency-budget-ms", type=int, default=200)
    squirrel_tryout_gate.add_argument("--max-model-ttfc-p95-ms", type=int, default=200)
    squirrel_tryout_gate.add_argument("--max-model-ttfc-over-budget-rate", type=float, default=0.0)
    squirrel_tryout_gate.add_argument(
        "--require-predictor-capability",
        action="append",
        default=[],
        choices=("streaming", "residentModel", "promptCache", "seededPromptReplay", "kvFork", "sequenceFork", "batchCandidates", "logitsTopK", "serverTiming"),
    )
    squirrel_tryout_gate.add_argument("--include-cases", action="store_true")
    squirrel_tryout_gate.add_argument("--report-path", default="")

    debug_server = subparsers.add_parser("debug-server", help="Run the browser debug page and local API")
    debug_server.add_argument("--host", default=os.environ.get("RAG_IME_DEBUG_HOST", "127.0.0.1"))
    debug_server.add_argument("--port", type=int, default=int(os.environ.get("RAG_IME_DEBUG_PORT", "8765")))
    debug_server.add_argument("--project", default="wisdom-weasel-rag-ime")
    debug_server.add_argument("--static-dir", default=os.environ.get("RAG_IME_DEBUG_STATIC_DIR", "debug"))
    debug_server.add_argument("--no-seed", action="store_true", help="Do not seed demo memories when DB is empty")
    debug_server.add_argument(
        "--rime-cache-ttl-ms",
        type=int,
        default=int(os.environ.get("RAG_IME_RIME_CACHE_TTL_MS", "400")),
        help="Short TTL cache for repeated /rime-suggest payloads. Use 0 to disable.",
    )
    debug_server.add_argument(
        "--vector-auto-rebuild-limit",
        type=int,
        default=int(os.environ.get("RAG_IME_VECTOR_AUTO_REBUILD_LIMIT", "0")),
        help="Backfill this many recent vectors at startup when an embedding provider is enabled and no active vectors exist.",
    )

    sidecar_server = subparsers.add_parser("sidecar-server", help="Run the local HTTP sidecar for Squirrel/Rime")
    sidecar_server.add_argument("--host", default=os.environ.get("RAG_IME_SIDECAR_HOST", "127.0.0.1"))
    sidecar_server.add_argument("--port", type=int, default=int(os.environ.get("RAG_IME_SIDECAR_PORT", "8766")))
    sidecar_server.add_argument("--project", default="wisdom-weasel-rag-ime")
    sidecar_server.add_argument("--no-seed", action="store_true", help="Do not seed demo memories when DB is empty")
    sidecar_server.add_argument(
        "--rime-cache-ttl-ms",
        type=int,
        default=int(os.environ.get("RAG_IME_RIME_CACHE_TTL_MS", "400")),
        help="Short TTL cache for repeated /rime-suggest payloads. Use 0 to disable.",
    )
    sidecar_server.add_argument(
        "--vector-auto-rebuild-limit",
        type=int,
        default=int(os.environ.get("RAG_IME_VECTOR_AUTO_REBUILD_LIMIT", "0")),
        help="Backfill this many recent vectors at startup when an embedding provider is enabled and no active vectors exist.",
    )

    mlx_predictor_server = subparsers.add_parser(
        "mlx-predictor-server",
        help="Run the resident MLX-LM prediction service for the IME model lane",
    )
    mlx_predictor_server.add_argument("--host", default=os.environ.get("RAG_IME_MLX_HOST", "127.0.0.1"))
    mlx_predictor_server.add_argument("--port", type=int, default=int(os.environ.get("RAG_IME_MLX_PORT", "8767")))
    mlx_predictor_server.add_argument("--model", default=os.environ.get("RAG_IME_MLX_MODEL", ""))
    mlx_predictor_server.add_argument("--max-tokens", type=int, default=int(os.environ.get("RAG_IME_MLX_MAX_TOKENS", "8")))
    mlx_predictor_server.add_argument("--temperature", type=float, default=float(os.environ.get("RAG_IME_MLX_TEMPERATURE", "0.15")))
    mlx_predictor_server.add_argument("--top-p", type=float, default=float(os.environ.get("RAG_IME_MLX_TOP_P", "0.85")))
    mlx_predictor_server.add_argument(
        "--prompt-cache",
        action="store_true",
        default=os.environ.get("RAG_IME_MLX_PROMPT_CACHE", "").strip().lower() in {"1", "true", "yes", "on"},
        help="Prepare the stable system-prompt cache at startup",
    )
    mlx_predictor_server.add_argument(
        "--prompt-cache-max-kv-size",
        type=int,
        default=int(os.environ.get("RAG_IME_MLX_PROMPT_CACHE_MAX_KV_SIZE", "0")),
    )

    subparsers.add_parser("acceptance", help="Run deterministic adapter acceptance scenarios")

    args = parser.parse_args(argv)
    if args.command == "mlx-predictor-server":
        if not args.model:
            raise SystemExit("mlx-predictor-server requires --model or RAG_IME_MLX_MODEL")
        from .mlx_predictor_server import MlxPredictorServerConfig, serve_mlx_predictor

        serve_mlx_predictor(
            MlxPredictorServerConfig(
                host=args.host,
                port=args.port,
                model=args.model,
                max_tokens=args.max_tokens,
                temperature=args.temperature,
                top_p=args.top_p,
                prompt_cache=args.prompt_cache,
                prompt_cache_max_kv_size=args.prompt_cache_max_kv_size,
            )
        )
        return 0

    core = _build_core(args)
    adapter = InputMethodAdapter(core, project="wisdom-weasel-rag-ime")
    predictor = prediction_provider_from_env()

    if args.command == "init-db":
        if not isinstance(core, LocalSqliteCoreClient):
            raise SystemExit("init-db requires --core-mode local")
        core.initialize()
        print(json.dumps({"db_path": str(core.db_path), "initialized": True}, ensure_ascii=False, indent=2))
        return 0

    if args.command == "memory-inspect":
        if not isinstance(core, LocalSqliteCoreClient):
            raise SystemExit("memory-inspect requires --core-mode local")
        print(
            json.dumps(
                core.inspect_memory_v2(
                    project=args.project,
                    limit=max(1, int(args.limit)),
                    kind=args.kind,
                    status=args.status,
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.command == "memory-optimizer-trace":
        if not isinstance(core, LocalSqliteCoreClient):
            raise SystemExit("memory-optimizer-trace requires --core-mode local")
        payload = core.get_memory_optimizer_trace(args.trace_id)
        if payload is None:
            raise SystemExit(f"unknown optimizer trace: {args.trace_id}")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.command == "memory-candidate-explain":
        if not isinstance(core, LocalSqliteCoreClient):
            raise SystemExit("memory-candidate-explain requires --core-mode local")
        payload = core.explain_memory_candidate(args.candidate_id, context_hash=args.context_hash or None)
        if payload is None:
            raise SystemExit(f"unknown memory candidate: {args.candidate_id}")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.command in {"memory-governance", "governance-report"}:
        if not isinstance(core, LocalSqliteCoreClient):
            raise SystemExit(f"{args.command} requires --core-mode local")
        print(
            json.dumps(
                core.inspect_memory_governance(
                    limit=max(1, int(args.limit)),
                    include_inactive=bool(args.include_inactive),
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.command == "tombstone":
        if not isinstance(core, LocalSqliteCoreClient):
            raise SystemExit("tombstone requires --core-mode local")
        metadata = _json_object_arg(args.metadata_json, flag="--metadata-json")
        payload = core.add_memory_tombstone(
            target_type=args.target_type,
            target_value=args.target_value,
            reason=args.reason,
            metadata=metadata,
            active=not bool(args.inactive),
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.command == "memory-cleanup-runs":
        if not isinstance(core, LocalSqliteCoreClient):
            raise SystemExit("memory-cleanup-runs requires --core-mode local")
        print(
            json.dumps(
                core.list_memory_cleanup_runs(
                    limit=max(1, int(args.limit)),
                    run_id=args.run_id,
                    status=args.status,
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.command in {"memory-cleanup-review", "memory-compile-review"}:
        if not isinstance(core, LocalSqliteCoreClient):
            raise SystemExit(f"{args.command} requires --core-mode local")
        payload = core.review_memory_cleanup_plan(
            run_id=args.run_id,
            status=args.status,
            diff_ids=list(args.diff_id),
            diff_indexes=list(args.diff_index),
        )
        print(
            json.dumps(
                {
                    "schemaVersion": "rag-ime.memory-cleanup-review.v1",
                    "run": payload,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.command == "memory-recompute-tags":
        if not isinstance(core, LocalSqliteCoreClient):
            raise SystemExit("memory-recompute-tags requires --core-mode local")
        print(json.dumps(core.recompute_memory_tags(project=args.project), ensure_ascii=False, indent=2))
        return 0

    if args.command == "retrieve-candidates-v2":
        if not isinstance(core, LocalSqliteCoreClient):
            raise SystemExit("retrieve-candidates-v2 requires --core-mode local")
        context = ImeQueryContext(
            current_input=args.current_input,
            recent_context=args.recent_context,
            committed_context=args.committed_context,
            project=args.project,
            app=args.app,
            top_k=max(1, int(args.top_k)),
            allow_raw_event_candidates=bool(args.allow_raw_event_candidates),
        )
        print(json.dumps(core.retrieve_candidates_v2(context=context), ensure_ascii=False, indent=2))
        return 0

    if args.command == "anti-echo-demo":
        governance = _json_object_arg(args.governance_json, flag="--governance-json")
        governor = AntiEchoGovernor(MemoryOptimizerConfig(enabled=True))
        context = ContextFrame(
            session_id=args.session_id,
            request_seq=max(1, int(args.request_seq)),
            front_app_bundle_id=args.front_app_bundle_id or None,
            input_mode=args.input_mode,
            raw_input=args.raw_input,
            preedit=args.preedit,
            committed_tail=args.committed_tail,
            selected_rime_candidates=[],
            semantic_query=args.semantic_query,
            semantic_query_source=args.semantic_query_source,
            composition_hash="",
            context_hash=args.context_hash,
            active_tags=[],
            project_scope=args.project or None,
            timestamp_ms=now_ms(),
        )
        source_tags = [compact_whitespace(tag) for tag in args.source_tag if compact_whitespace(tag)]
        decisions: list[dict[str, object]] = []
        for index, text in enumerate(args.candidate_text, start=1):
            hit = RawRetrievalHit(
                id=f"demo:{index}",
                text=text,
                source=args.hit_source,
                score=max(0.1, 1.0 - (index - 1) * 0.05),
                memory_atom_id=None,
                evidence="anti-echo-demo",
                metadata={
                    "tags": source_tags,
                    "source_type": args.candidate_source,
                },
            )
            blocked = governor.should_block(hit=hit, context=context, governance=governance)
            decisions.append(
                {
                    "id": hit.id,
                    "text": hit.text,
                    "blocked": blocked is not None,
                    "reason": blocked.reason if blocked is not None else "",
                    "source": hit.source,
                    "sourceType": args.candidate_source,
                }
            )
        print(
            json.dumps(
                {
                    "schemaVersion": "rag-ime.anti-echo-demo.v1",
                    "context": {
                        "committedTail": context.committed_tail,
                        "rawInput": context.raw_input,
                        "semanticQuery": context.semantic_query,
                        "inputMode": context.input_mode,
                        "contextHash": context.context_hash,
                    },
                    "governance": governance,
                    "decisions": decisions,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.command == "cleanup-preview":
        if not isinstance(core, LocalSqliteCoreClient):
            raise SystemExit("cleanup-preview requires --core-mode local")
        payload = _cleanup_preview_payload(core=core, args=args)
        if args.output:
            Path(args.output).write_text(json.dumps(payload["run"], ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.command == "cleanup-validate":
        if not isinstance(core, LocalSqliteCoreClient):
            raise SystemExit("cleanup-validate requires --core-mode local")
        try:
            plan = _cleanup_plan_from_cli_args(core=core, run_id=args.run_id, run_path=args.run)
        except ValueError as exc:
            print(
                json.dumps(
                    {"schemaVersion": "rag-ime.cleanup-validate.v1", "ok": False, "error": str(exc)},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 2
        report = inspect_cleanup_plan(plan)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report.get("ok") else 1

    if args.command == "cleanup-apply":
        if not isinstance(core, LocalSqliteCoreClient):
            raise SystemExit("cleanup-apply requires --core-mode local")
        if not bool(args.apply):
            print(
                json.dumps(
                    {
                        "schemaVersion": "rag-ime.cleanup-apply.v1",
                        "ok": False,
                        "error": "cleanup-apply requires --apply to modify the DB",
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 2
        try:
            plan = _cleanup_plan_from_cli_args(core=core, run_id=args.run_id, run_path=args.run)
        except ValueError as exc:
            print(
                json.dumps(
                    {"schemaVersion": "rag-ime.cleanup-apply.v1", "ok": False, "error": str(exc)},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 2
        validation = inspect_cleanup_plan(plan)
        if not validation.get("ok"):
            print(
                json.dumps(
                    {
                        "schemaVersion": "rag-ime.cleanup-apply.v1",
                        "ok": False,
                        "error": "cleanup plan failed validation",
                        "validation": validation,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 1
        payload = core.apply_memory_cleanup_plan(
            run_path=args.run,
            run_id=args.run_id,
            only_approved=bool(args.only_approved),
        )
        print(
            json.dumps(
                {
                    "schemaVersion": "rag-ime.cleanup-apply.v1",
                    "ok": True,
                    "validation": validation,
                    "run": payload,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.command == "cleanup-rollback":
        if not isinstance(core, LocalSqliteCoreClient):
            raise SystemExit("cleanup-rollback requires --core-mode local")
        payload = core.rollback_memory_cleanup_plan(run_id=args.run_id)
        print(
            json.dumps(
                {
                    "schemaVersion": "rag-ime.cleanup-rollback.v1",
                    "ok": True,
                    "run": payload,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.command == "memory-cleanup-plan":
        if not isinstance(core, LocalSqliteCoreClient):
            raise SystemExit("memory-cleanup-plan requires --core-mode local")
        payload = core.build_memory_cleanup_plan(
            project=args.project,
            since_days=max(1, int(args.since_days)),
            provider=args.provider,
            model=args.model,
        )
        if args.out:
            Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.command == "memory-cleanup-apply":
        if not isinstance(core, LocalSqliteCoreClient):
            raise SystemExit("memory-cleanup-apply requires --core-mode local")
        payload = core.apply_memory_cleanup_plan(
            run_path=args.run,
            run_id=args.run_id,
            only_approved=bool(args.only_approved),
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.command == "memory-cleanup-rollback":
        if not isinstance(core, LocalSqliteCoreClient):
            raise SystemExit("memory-cleanup-rollback requires --core-mode local")
        payload = core.rollback_memory_cleanup_plan(run_id=args.run_id)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.command == "memory-compile":
        if not isinstance(core, LocalSqliteCoreClient):
            raise SystemExit("memory-compile requires --core-mode local")
        try:
            generator = compiler_generator_from_env(
                env_path=args.model_env_path or None,
                provider=args.provider,
                model=args.model,
            )
            bundle = build_memory_compile_bundle(
                core,
                project=args.project,
                recent_limit=max(1, int(args.recent_limit)),
                phrase_limit=max(1, int(args.phrase_limit)),
                memory_limit=max(1, int(args.memory_limit)),
                governance_limit=max(1, int(args.governance_limit)),
                allow_private_paths=bool(args.allow_private_paths),
            )
            if isinstance(bundle.get("source"), dict):
                bundle["source"]["sinceDays"] = max(1, int(args.since_days))
            report = generator.optimize_core(
                snapshot=bundle,
                project=args.project,
                max_memories=max(1, int(args.max_memories)),
                max_lexicon_phrases=max(1, int(args.max_lexicon_phrases)),
                max_hide_suggestions=max(0, int(args.max_hide_suggestions)),
            )
            plan = cleanup_plan_from_compiler_report(project=args.project, bundle=bundle, report=report)
            stored_run = core.store_memory_cleanup_plan(plan) if bool(args.save_draft) else None
        except MemoryGenerationError as exc:
            print(
                json.dumps(
                    {"schemaVersion": "rag-ime.memory-compile.v1", "ok": False, "error": str(exc)},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 2
        if args.output:
            Path(args.output).parent.mkdir(parents=True, exist_ok=True)
            Path(args.output).write_text(json.dumps(cleanup_plan_to_payload(plan), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        payload = memory_compile_report_payload(
            project=args.project,
            bundle=bundle,
            report=report,
            plan=plan,
            output_path=str(args.output or ""),
        )
        payload["storedDraft"] = stored_run is not None
        if stored_run is not None:
            payload["run"] = stored_run
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.command == "memory-compile-apply":
        if not isinstance(core, LocalSqliteCoreClient):
            raise SystemExit("memory-compile-apply requires --core-mode local")
        if not args.diff and not args.run_id:
            raise SystemExit("memory-compile-apply requires --diff or --run-id")
        payload = core.apply_memory_cleanup_plan(
            run_path=args.diff,
            run_id=args.run_id,
            only_approved=bool(args.only_approved),
        )
        print(
            json.dumps(
                {
                    "schemaVersion": "rag-ime.memory-compile-apply.v1",
                    "ok": True,
                    "run": payload,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.command == "memory-compile-rollback":
        if not isinstance(core, LocalSqliteCoreClient):
            raise SystemExit("memory-compile-rollback requires --core-mode local")
        payload = core.rollback_memory_cleanup_plan(run_id=args.run_id)
        print(
            json.dumps(
                {
                    "schemaVersion": "rag-ime.memory-compile-rollback.v1",
                    "ok": True,
                    "run": payload,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.command == "seed-demo":
        if not isinstance(core, LocalSqliteCoreClient):
            raise SystemExit("seed-demo requires --core-mode local")
        if args.reset:
            core.reset()
        seed_demo_memories(adapter, default_fixture_memories())
        print(
            json.dumps(
                {"db_path": str(core.db_path), "event_count": core.event_count(), "seeded": True},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.command == "seed-eval-cases":
        if not isinstance(core, LocalSqliteCoreClient):
            raise SystemExit("seed-eval-cases requires --core-mode local")
        cases = load_eval_cases(Path(args.cases_file))
        event_ids = seed_eval_case_memories(adapter, cases, project=args.project)
        print(
            json.dumps(
                {
                    "db_path": str(core.db_path),
                    "cases_file": str(Path(args.cases_file)),
                    "project": args.project,
                    "event_count": core.event_count(),
                    "seeded_eval_cases": len(event_ids),
                    "seeded": True,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.command == "rebuild-vector-index":
        if not isinstance(core, LocalSqliteCoreClient):
            raise SystemExit("rebuild-vector-index requires --core-mode local")
        print(
            json.dumps(
                core.rebuild_vector_index(project=args.project, limit=max(0, args.limit)),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.command == "commit":
        event_id = adapter.commit_text(
            args.text,
            recent_context=args.recent_context,
            preedit=args.preedit,
            project=args.project,
            source=args.source,
            tags=tuple(args.tag),
            recording_enabled=not args.recording_disabled,
            field_is_sensitive=args.sensitive,
        )
        print(
            json.dumps(
                {"event_id": event_id, "recorded": not event_id.startswith("skipped:")},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.command == "generate-memory":
        try:
            generator = VcpRebuildMemoryGenerator.from_env_path(args.model_env_path or args.vcp_env_path or None)
            report = generator.generate(
                text=args.text,
                recent_context=args.recent_context,
                project=args.project,
                max_items=max(1, args.max_items),
            )
        except MemoryGenerationError as exc:
            print(
                json.dumps(
                    {"schemaVersion": "rag-ime.generated-memory.v1", "ok": False, "error": str(exc)},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 2
        recorded: list[dict[str, object]] = []
        duplicate_skipped = 0
        provider_tag = report.provider
        for item in report.items:
            dedupe_tag = generated_memory_dedupe_tag(item.text)
            if not args.allow_duplicates and _core_has_event_tag(core, dedupe_tag):
                duplicate_skipped += 1
                continue
            tags = tuple(
                dict.fromkeys(
                    (
                        "generated-memory",
                        provider_tag,
                        "aimemo",
                        dedupe_tag,
                        *item.tags,
                    )
                )
            )
            event_id = ""
            if not args.dry_run:
                event_id = adapter.commit_text(
                    item.text,
                    recent_context=generated_memory_context(args.text, args.recent_context, item.reason),
                    project=args.project,
                    app=args.app,
                    source="api_memory_generator",
                    provider_name=f"{report.provider}:{report.model}",
                    tags=tags,
                )
            recorded.append(
                {
                    "eventId": event_id,
                    "text": item.text,
                    "tags": list(tags),
                    "importance": item.importance,
                    "reason": item.reason,
                }
            )
        print(
            json.dumps(
                {
                    "schemaVersion": "rag-ime.generated-memory.v1",
                    "ok": True,
                    "dryRun": bool(args.dry_run),
                    "provider": report.provider,
                    "model": report.model,
                    "elapsedMs": report.elapsed_ms,
                    "generated": len(report.items),
                    "recorded": 0 if args.dry_run else len(recorded),
                    "duplicateSkipped": duplicate_skipped,
                    "items": recorded,
                    "metadata": report.metadata,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.command == "optimize-core":
        snapshot_builder = getattr(core, "core_optimization_snapshot", None)
        if not callable(snapshot_builder):
            print(
                json.dumps(
                    {"schemaVersion": "rag-ime.core-optimization.v1", "ok": False, "error": "core does not support optimization snapshots"},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 2
        snapshot = snapshot_builder(
            project=args.project,
            recent_limit=max(1, int(args.recent_limit)),
            phrase_limit=max(1, int(args.phrase_limit)),
        )
        try:
            generator = VcpRebuildMemoryGenerator.from_env_path(args.model_env_path or None)
            report = generator.optimize_core(
                snapshot=snapshot,
                project=args.project,
                max_memories=max(1, args.max_memories),
                max_lexicon_phrases=max(1, args.max_lexicon_phrases),
                max_hide_suggestions=max(0, args.max_hide_suggestions),
            )
        except MemoryGenerationError as exc:
            print(
                json.dumps(
                    {"schemaVersion": "rag-ime.core-optimization.v1", "ok": False, "error": str(exc)},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 2
        recorded_memories: list[dict[str, object]] = []
        recorded_lexicon: list[dict[str, object]] = []
        duplicate_skipped = 0
        provider_tag = report.provider
        for item in report.memories:
            dedupe_tag = generated_memory_dedupe_tag(item.text)
            if not args.allow_duplicates and _core_has_event_tag(core, dedupe_tag):
                duplicate_skipped += 1
                continue
            tags = tuple(
                dict.fromkeys(
                    (
                        "generated-memory",
                        "api-core-optimized",
                        provider_tag,
                        "aimemo",
                        dedupe_tag,
                        *item.tags,
                    )
                )
            )
            event_id = ""
            if not args.dry_run:
                event_id = adapter.commit_text(
                    item.text,
                    recent_context=generated_memory_context("core optimization snapshot", "", item.reason),
                    project=args.project,
                    app=args.app,
                    source="api_core_optimizer",
                    provider_name=f"{report.provider}:{report.model}",
                    tags=tags,
                )
            recorded_memories.append(
                {
                    "eventId": event_id,
                    "text": item.text,
                    "tags": list(tags),
                    "importance": item.importance,
                    "reason": item.reason,
                }
            )
        for phrase in report.lexicon_phrases:
            dedupe_tag = generated_lexicon_dedupe_tag(phrase.text)
            if not args.allow_duplicates and _core_has_event_tag(core, dedupe_tag):
                duplicate_skipped += 1
                continue
            tags = tuple(
                dict.fromkeys(
                    (
                        "lexicon-phrase",
                        "api-lexicon",
                        "api-core-optimized",
                        dedupe_tag,
                        *phrase.tags,
                    )
                )
            )
            event_id = ""
            if not args.dry_run:
                event_id = adapter.commit_text(
                    phrase.text,
                    recent_context=f"API lexicon optimization | reason: {compact_whitespace(phrase.reason)}",
                    project=args.project,
                    app=args.app,
                    source="api_lexicon_optimizer",
                    provider_name=f"{report.provider}:{report.model}",
                    tags=tags,
                )
            recorded_lexicon.append(
                {
                    "eventId": event_id,
                    "text": phrase.text,
                    "tags": list(tags),
                    "weight": phrase.weight,
                    "reason": phrase.reason,
                }
            )
        print(
            json.dumps(
                {
                    "schemaVersion": "rag-ime.core-optimization.v1",
                    "ok": True,
                    "dryRun": bool(args.dry_run),
                    "provider": report.provider,
                    "model": report.model,
                    "elapsedMs": report.elapsed_ms,
                    "snapshotTotals": snapshot.get("totals"),
                    "recordedMemories": 0 if args.dry_run else len(recorded_memories),
                    "recordedLexiconPhrases": 0 if args.dry_run else len(recorded_lexicon),
                    "duplicateSkipped": duplicate_skipped,
                    "memories": recorded_memories,
                    "lexiconPhrases": recorded_lexicon,
                    "hideEventSuggestions": [
                        {"eventId": item.event_id, "reason": item.reason}
                        for item in report.hide_events
                    ],
                    "metadata": report.metadata,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.command == "suggest":
        suggestions = adapter.suggest(
            SuggestionRequest(
                current_input=args.current_input,
                recent_context=args.recent_context,
                project=args.project,
                top_k=args.top_k,
            )
        )
        print(
            render_terminal_panel(
                title="manual suggest",
                current_input=args.current_input,
                recent_context=args.recent_context,
                suggestions=suggestions,
            )
        )
        return 0

    if args.command == "suggest-json":
        prediction_context = build_prediction_context(
            core,
            explicit_recent_context=args.recent_context,
            project=args.project,
        )
        model_predictions = predictor.predict(
            current_input=args.current_input,
            recent_context=prediction_context,
            max_candidates=5,
        )
        suggestions = adapter.suggest(
            SuggestionRequest(
                current_input=args.current_input,
                recent_context=prediction_context,
                project=args.project,
                top_k=args.top_k,
            )
        )
        print(
            json.dumps(
                suggestions_response_payload(
                    current_input=args.current_input,
                    recent_context=args.recent_context,
                    project=args.project,
                    history_context=prediction_context,
                    model_predictions=model_predictions,
                    suggestions=suggestions,
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.command == "rime-suggest-json":
        payload = _read_json_payload(args.payload_file)
        print(
            json.dumps(
                build_rime_sidecar_response(
                    payload=payload,
                    adapter=adapter,
                    core=core,
                    predictor=predictor,
                    default_project="wisdom-weasel-rag-ime",
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.command == "rime-select-json":
        payload = _read_json_payload(args.payload_file)
        print(
            json.dumps(
                record_rime_side_candidate_selection(
                    payload=payload,
                    adapter=adapter,
                    core=core,
                    default_project="wisdom-weasel-rag-ime",
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.command == "action-json":
        action = core.apply_action(
            MemoryAction(
                action_id=None,
                created_at_ms=now_ms(),
                memory_id=args.memory_id,
                action_type=args.action_type,
                query=args.query,
                suggestion_id=args.suggestion_id,
                source_event_id=args.source_event_id or None,
                metadata={"surface_text": args.surface_text} if args.surface_text else {},
            )
        )
        print(json.dumps(action_response_payload(action), ensure_ascii=False, indent=2))
        return 0

    if args.command == "demo":
        scenarios = [get_scenario(args.scenario)] if args.scenario else list(SCENARIOS)
        for index, scenario in enumerate(scenarios):
            if index:
                print("\n" + "=" * 80 + "\n")
            suggestions = adapter.suggest(
                SuggestionRequest(
                    current_input=scenario.current_input,
                    recent_context=scenario.recent_context,
                    project=scenario.project,
                    top_k=args.top_k,
                )
            )
            print(
                render_terminal_panel(
                    title=scenario.title,
                    current_input=scenario.current_input,
                    recent_context=scenario.recent_context,
                    suggestions=suggestions,
                )
            )
        return 0

    if args.command == "action-demo":
        scenario = get_scenario("technical-plan")
        request = SuggestionRequest(
            current_input=scenario.current_input,
            recent_context=scenario.recent_context,
            project=scenario.project,
            top_k=3,
        )
        before = adapter.suggest(request)
        pinned = before[-1]
        adapter.pin(pinned, query=scenario.current_input)
        downranked = before[0]
        adapter.downrank(downranked, query=scenario.current_input)
        after = adapter.suggest(request)
        print(
            json.dumps(
                {
                    "before": [item.surface_text for item in before],
                    "pinned": pinned.surface_text,
                    "downranked": downranked.surface_text,
                    "after": [item.surface_text for item in after],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.command == "trigger-demo":
        decision = should_refresh_rag(
            TypingState(
                current_input=args.current_input,
                idle_ms=args.idle_ms,
                app_kind=args.app_kind,
                explicit_request=args.explicit,
                field_is_sensitive=args.sensitive,
            )
        )
        print(
            json.dumps(
                {"should_refresh": decision.should_refresh, "reason": decision.reason},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.command == "agent-hook":
        injection = build_first_run_injection(adapter, project=args.project, query=args.query, top_k=args.top_k)
        print(render_agent_injection(injection))
        return 0

    if args.command == "import-codex-history":
        role_filter = _parse_codex_role_filter(args.roles)
        records = load_codex_history_records(
            Path(args.path),
            limit=max(0, args.limit),
            min_chars=max(1, args.min_chars),
            max_chars=max(16, args.max_chars),
            path_order=args.path_order,
            roles=role_filter,
        )
        event_ids: list[str] = []
        duplicate_skipped = 0
        if not args.dry_run:
            for record in records:
                record_tag = f"record:{record.record_id[:12]}"
                if not args.allow_duplicates and _core_has_event_tag(core, record_tag):
                    duplicate_skipped += 1
                    continue
                event_ids.append(core.record_event(input_event_from_codex_record(record, project=args.project)))
        print(
            json.dumps(
                {
                    "schemaVersion": "rag-ime.codex-history-import.v1",
                    "path": str(Path(args.path)),
                    "project": args.project,
                    "dryRun": args.dry_run,
                    "roles": "any" if role_filter is None else list(role_filter),
                    "records": len(records),
                    "imported": 0 if args.dry_run else len(event_ids),
                    "duplicateSkipped": duplicate_skipped,
                    "eventIds": [] if args.dry_run else event_ids[:10],
                    "samples": [
                        {
                            "recordId": record.record_id,
                            "sourcePath": record.source_path,
                            "lineNumber": record.line_number,
                            "role": record.role,
                            "text": record.text[:160],
                        }
                        for record in records[: max(0, args.sample_size)]
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.command == "prune-codex-history-noise":
        pruner = getattr(core, "hide_codex_history_noise", None)
        if not callable(pruner):
            print(json.dumps({"ok": False, "error": "core does not support Codex history pruning"}, ensure_ascii=False, indent=2))
            return 2
        keep_roles = _parse_codex_role_filter(args.keep_roles)
        if keep_roles is None:
            keep_roles = ("user",)
        report = pruner(project=args.project, keep_roles=keep_roles, dry_run=bool(args.dry_run))
        print(json.dumps({"schemaVersion": "rag-ime.codex-history-prune.v1", **report}, ensure_ascii=False, indent=2))
        return 0

    if args.command == "organize-rag-db":
        organizer = getattr(core, "organize_rag_database", None)
        if not callable(organizer):
            print(json.dumps({"ok": False, "error": "core does not support RAG database organization"}, ensure_ascii=False, indent=2))
            return 2
        report = organizer(
            project=args.project,
            dry_run=bool(args.dry_run),
            min_generated_accepts=max(1, int(args.min_generated_accepts)),
            sample_size=max(0, int(args.sample_size)),
        )
        print(json.dumps({"schemaVersion": "rag-ime.rag-db-organize.v1", **report}, ensure_ascii=False, indent=2))
        return 0

    if args.command == "eval-codex-history":
        report = run_codex_history_eval(
            adapter,
            core,
            cases_file=Path(args.cases_file),
            project=args.project,
            top_k=max(1, args.top_k),
            match=args.match,
            repeat=max(1, args.repeat),
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    if args.command == "eval-rime-sidecar":
        report = run_rime_sidecar_eval(
            core,
            predictor,
            db_path=Path(args.db_path),
            cases_file=Path(args.cases_file),
            project=args.project,
            match=args.match,
            repeat=max(1, args.repeat),
            max_visible_candidates=max(1, min(10, args.max_visible_candidates)),
            max_side_candidates=max(0, min(10, args.max_side_candidates)),
            sidecar_latency_budget_ms=max(30, args.sidecar_latency_budget_ms),
            rime_cache_ttl_ms=max(0, args.rime_cache_ttl_ms),
            force_side_candidates=bool(args.force_side_candidates),
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    if args.command == "eval-memory-optimizer":
        report = run_memory_optimizer_eval(
            cases_file=Path(args.cases_file),
            project=args.project,
            repeat=max(1, args.repeat),
            max_visible_candidates=max(1, min(10, args.max_visible_candidates)),
            max_side_candidates=max(0, min(10, args.max_side_candidates)),
            latency_budget_ms=max(30, args.latency_budget_ms),
            optimizer_max_ms=max(1, args.optimizer_max_ms),
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if bool(report.get("gatePassed")) else 1

    if args.command == "predict-benchmark":
        prediction_context = build_prediction_context(
            core,
            explicit_recent_context=args.recent_context,
            project=args.project,
        )
        raw_cases = args.case or [
            "RAG 输入法",
            "Squirrel 候选",
            "PROJECT_MEMORY_BLOCK",
        ]
        cases = [PredictionBenchmarkCase(current_input=item, recent_context=prediction_context) for item in raw_cases]
        print(
            json.dumps(
                benchmark_prediction_provider(
                    predictor,
                    cases,
                    max_candidates=max(1, args.max_candidates),
                    latency_budget_ms=max(1, args.latency_budget_ms),
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.command == "predictor-status":
        print(
            json.dumps(
                prediction_provider_status(predictor, probe_capabilities=bool(args.probe_capabilities)),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.command == "predictor-ttft":
        prediction_context = build_prediction_context(
            core,
            explicit_recent_context=args.recent_context,
            project=args.project,
        )
        raw_cases = args.case or [
            "RAG 输入法",
            "Squirrel 候选",
            "PROJECT_MEMORY_BLOCK",
        ]
        cases = [PredictionBenchmarkCase(current_input=item, recent_context=prediction_context) for item in raw_cases]
        print(
            json.dumps(
                benchmark_streaming_ttft_provider(
                    predictor,
                    cases,
                    max_candidates=max(1, args.max_candidates),
                    repeat=max(1, args.repeat),
                    latency_budget_ms=max(1, args.latency_budget_ms),
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.command == "bench-ime-ttfc":
        report = run_ime_ttfc_benchmark(
            core=core,
            cases_file=args.cases_file,
            inline_cases=list(args.case),
            recent_context=args.recent_context,
            project=args.project,
            provider=args.provider,
            base_url=args.base_url,
            models=args.models,
            profile=args.profile,
            max_candidates=max(1, min(10, args.max_candidates)),
            repeat=max(1, args.repeat),
            warmup_runs=max(0, args.warmup_runs),
            latency_budget_ms=max(1, args.latency_budget_ms),
            failure_cooldown_ms=max(0, args.failure_cooldown_ms),
            include_cases=bool(args.include_cases),
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    if args.command == "predictor-doctor":
        report = doctor_prediction_provider(
            predictor,
            sample_input=args.case,
            recent_context=args.recent_context,
            max_candidates=max(1, args.max_candidates),
            latency_budget_ms=max(1, args.latency_budget_ms),
        )
        report["localRunners"] = _local_model_runner_status()
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    if args.command == "eval-prediction":
        cases = load_eval_cases(Path(args.cases_file))
        repeat_count = max(1, args.repeat)
        max_candidates = max(1, min(10, args.max_candidates))
        results = []
        elapsed_ms_by_case: dict[str, int] = {}
        candidate_counts: list[int] = []
        over_budget_count = 0
        provider_name = _prediction_provider_name(predictor)
        provider_configured = not _is_null_prediction_provider(predictor)
        for repeat_index in range(1, repeat_count + 1):
            for case in cases:
                eval_case = _case_for_eval_repeat(case, repeat_index=repeat_index, repeat_count=repeat_count)
                prediction_context = build_prediction_context(
                    core,
                    explicit_recent_context=eval_case.recent_context,
                    project=eval_case.project or args.project,
                )
                started = time.perf_counter()
                predictions = predictor.predict(
                    current_input=eval_case.query,
                    recent_context=prediction_context,
                    max_candidates=max_candidates,
                )
                elapsed_ms = int((time.perf_counter() - started) * 1000)
                elapsed_ms_by_case[eval_case.case_id] = elapsed_ms
                if predictions:
                    provider_name = predictions[0].provider_name
                candidate_counts.append(len(predictions))
                if elapsed_ms > args.latency_budget_ms:
                    over_budget_count += 1
                results.append(
                    evaluate_suggestions(
                        eval_case,
                        _predictions_as_eval_suggestions(predictions),
                        match=args.match,
                    )
                )
        report = eval_report(results)
        report["repeat"] = {
            "requested": repeat_count,
            "baseCaseCount": len(cases),
            "effectiveCaseCount": len(results),
        }
        _attach_eval_latency(report, elapsed_ms_by_case)
        report["prediction"] = {
            "providerName": provider_name,
            "providerProfile": _prediction_provider_profile(predictor),
            "providerConfigured": provider_configured,
            "maxCandidates": max_candidates,
            "latencyBudgetMs": args.latency_budget_ms,
            "overBudgetCount": over_budget_count,
            "totalCandidates": sum(candidate_counts),
            "hasCandidates": any(count > 0 for count in candidate_counts),
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    if args.command in {"eval-model-matrix", "model-matrix-eval"}:
        cases = load_eval_cases(Path(args.cases_file))
        models = _parse_model_matrix_models(args.models)
        reports = []
        for model in models:
            matrix_provider = _prediction_provider_for_model_matrix(args=args, model=model)
            model_report = _eval_prediction_provider_on_cases(
                provider=matrix_provider,
                core=core,
                cases=cases,
                project=args.project,
                max_candidates=max(1, min(10, args.max_candidates)),
                match=args.match,
                repeat=max(1, args.repeat),
                latency_budget_ms=max(1, args.latency_budget_ms),
            )
            model_report["model"] = model
            if not args.include_cases:
                model_report["failedCaseIds"] = [
                    str(item.get("caseId"))
                    for item in model_report.get("cases", [])
                    if isinstance(item, dict) and not item.get("passed")
                ]
                model_report.pop("cases", None)
            reports.append(model_report)
        report = {
            "schemaVersion": "rag-ime.model-matrix-eval.v1",
            "casesFile": str(Path(args.cases_file)),
            "project": args.project,
            "provider": str(args.provider),
            "baseUrl": args.base_url,
            "profile": args.profile,
            "match": args.match,
            "repeat": {
                "requested": max(1, args.repeat),
                "baseCaseCount": len(cases),
                "effectiveCaseCount": len(cases) * max(1, args.repeat),
            },
            "maxCandidates": max(1, min(10, args.max_candidates)),
            "latencyBudgetMs": max(1, args.latency_budget_ms),
            "failureCooldownMs": max(0, args.failure_cooldown_ms),
            "localRunners": _local_model_runner_status(),
            "models": reports,
            "winner": _model_matrix_winner(reports),
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    if args.command == "rerank-demo":
        candidates = _parse_rerank_demo_candidates(args.candidate, args.candidate_json)
        ranked = rerank_candidate_dicts(
            candidates,
            query=args.query,
            recent_context=args.recent_context,
            max_candidates=max(1, min(20, args.max_candidates)),
        )
        report = {
            "schemaVersion": "rag-ime.rerank-demo.v1",
            "query": args.query,
            "recentContextHash": _stable_eval_hash(args.recent_context),
            "inputCount": len(candidates),
            "maxCandidates": max(1, min(20, args.max_candidates)),
            "candidates": ranked,
            "sourceCounts": _source_counts(ranked),
            "rimeFallbackPreserved": any(item.get("source") == "rime" for item in ranked),
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    if args.command == "eval-comparison":
        cases = load_eval_cases(Path(args.cases_file))
        repeat_count = max(1, args.repeat)
        max_candidates = max(1, min(10, args.max_candidates))
        rag_results = []
        model_results = []
        rag_elapsed_ms_by_case: dict[str, int] = {}
        model_elapsed_ms_by_case: dict[str, int] = {}
        candidate_counts: list[int] = []
        over_budget_count = 0
        provider_name = _prediction_provider_name(predictor)
        provider_configured = not _is_null_prediction_provider(predictor)

        for repeat_index in range(1, repeat_count + 1):
            for case in cases:
                eval_case = _case_for_eval_repeat(case, repeat_index=repeat_index, repeat_count=repeat_count)
                project = eval_case.project or args.project

                rag_started = time.perf_counter()
                suggestions = adapter.suggest(
                    SuggestionRequest(
                        current_input=eval_case.query,
                        recent_context=eval_case.recent_context,
                        project=project,
                        top_k=args.top_k,
                    )
                )
                rag_elapsed_ms_by_case[eval_case.case_id] = int((time.perf_counter() - rag_started) * 1000)
                rag_results.append(evaluate_suggestions(eval_case, suggestions, match=args.match))

                prediction_context = build_prediction_context(
                    core,
                    explicit_recent_context=eval_case.recent_context,
                    project=project,
                )
                model_started = time.perf_counter()
                predictions = predictor.predict(
                    current_input=eval_case.query,
                    recent_context=prediction_context,
                    max_candidates=max_candidates,
                )
                model_elapsed_ms = int((time.perf_counter() - model_started) * 1000)
                model_elapsed_ms_by_case[eval_case.case_id] = model_elapsed_ms
                if predictions:
                    provider_name = predictions[0].provider_name
                candidate_counts.append(len(predictions))
                if model_elapsed_ms > args.latency_budget_ms:
                    over_budget_count += 1
                model_results.append(
                    evaluate_suggestions(
                        eval_case,
                        _predictions_as_eval_suggestions(predictions),
                        match=args.match,
                    )
                )

        rag_report = eval_report(rag_results)
        model_report = eval_report(model_results)
        repeat_payload = {
            "requested": repeat_count,
            "baseCaseCount": len(cases),
            "effectiveCaseCount": len(rag_results),
        }
        rag_report["repeat"] = repeat_payload
        model_report["repeat"] = dict(repeat_payload)
        _attach_eval_latency(rag_report, rag_elapsed_ms_by_case)
        _attach_eval_latency(model_report, model_elapsed_ms_by_case)
        cache_stats = getattr(core, "suggestion_cache_stats", None)
        if callable(cache_stats):
            rag_report["cacheStats"] = cache_stats()
        _attach_vector_stats(rag_report, core)
        model_report["prediction"] = {
            "providerName": provider_name,
            "providerProfile": _prediction_provider_profile(predictor),
            "providerConfigured": provider_configured,
            "maxCandidates": max_candidates,
            "latencyBudgetMs": args.latency_budget_ms,
            "overBudgetCount": over_budget_count,
            "totalCandidates": sum(candidate_counts),
            "hasCandidates": any(count > 0 for count in candidate_counts),
        }
        report = {
            "schemaVersion": "rag-ime.eval-comparison.v1",
            "casesFile": str(Path(args.cases_file)),
            "project": args.project,
            "match": args.match,
            "repeat": repeat_payload,
            "rag": rag_report,
            "model": model_report,
            "comparison": _comparison_summary(
                rag_results=rag_results,
                model_results=model_results,
                rag_elapsed_ms_by_case=rag_elapsed_ms_by_case,
                model_elapsed_ms_by_case=model_elapsed_ms_by_case,
            ),
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    if args.command == "cache-probe":
        report = run_cache_probe(
            core,
            predictor,
            db_path=Path(args.db_path),
            project=args.project,
            current_input=args.current_input,
            recent_context=args.recent_context,
            top_k=max(1, args.top_k),
            repeat=max(1, args.repeat),
            rime_candidates=list(args.rime_candidate) or ["RAG 输入法"],
            rime_cache_ttl_ms=max(0, args.rime_cache_ttl_ms),
            force_side_candidates=bool(args.force_side_candidates),
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    if args.command == "quality-gate":
        report = run_quality_gate(
            adapter,
            core,
            predictor,
            db_path=Path(args.db_path),
            cases_file=Path(args.cases_file),
            project=args.project,
            top_k=max(1, args.top_k),
            match=args.match,
            repeat=max(1, args.repeat),
            min_rag_pass_rate=max(0.0, min(1.0, args.min_rag_pass_rate)),
            min_sidecar_pass_rate=max(0.0, min(1.0, args.min_sidecar_pass_rate)),
            min_rag_top1_accuracy=max(0.0, min(1.0, args.min_rag_top1_accuracy)),
            min_sidecar_top1_accuracy=max(0.0, min(1.0, args.min_sidecar_top1_accuracy)),
            min_rag_mrr=max(0.0, min(1.0, args.min_rag_mrr)),
            min_sidecar_mrr=max(0.0, min(1.0, args.min_sidecar_mrr)),
            max_rag_noise_rate=max(0.0, min(1.0, args.max_rag_noise_rate)),
            max_sidecar_noise_rate=max(0.0, min(1.0, args.max_sidecar_noise_rate)),
            max_sidecar_rag_timeout_rate=max(0.0, min(1.0, args.max_sidecar_rag_timeout_rate)),
            max_sidecar_model_timeout_rate=max(0.0, min(1.0, args.max_sidecar_model_timeout_rate)),
            max_old_input_echo_rate=max(0.0, min(1.0, args.max_old_input_echo_rate)),
            require_model_ttfc=bool(args.require_model_ttfc),
            model_ttfc_cases_file=Path(args.model_ttfc_cases_file),
            model_ttfc_provider=args.model_ttfc_provider,
            model_ttfc_base_url=args.model_ttfc_base_url,
            model_ttfc_models=args.model_ttfc_models,
            model_ttfc_profile=args.model_ttfc_profile,
            model_ttfc_repeat=max(1, args.model_ttfc_repeat),
            model_ttfc_warmup_runs=max(0, args.model_ttfc_warmup_runs),
            model_ttfc_latency_budget_ms=max(1, args.model_ttfc_latency_budget_ms),
            max_model_ttfc_p95_ms=max(1, args.max_model_ttfc_p95_ms),
            max_model_ttfc_over_budget_rate=max(0.0, min(1.0, args.max_model_ttfc_over_budget_rate)),
            cache_current_input=args.cache_current_input,
            cache_recent_context=args.cache_recent_context,
            cache_repeat=max(1, args.cache_repeat),
            rime_candidates=list(args.rime_candidate),
            max_visible_candidates=max(1, min(10, args.max_visible_candidates)),
            max_side_candidates=max(0, min(10, args.max_side_candidates)),
            sidecar_latency_budget_ms=max(30, args.sidecar_latency_budget_ms),
            rime_cache_ttl_ms=max(0, args.rime_cache_ttl_ms),
            force_side_candidates=bool(args.force_side_candidates),
            require_suggestion_cache=bool(args.require_suggestion_cache),
            require_acceptance_check=not bool(args.skip_acceptance_check),
            require_input_source_ready=bool(args.require_input_source_ready),
            input_source_id=args.input_source_id,
            input_source_check_script=Path(args.input_source_check_script) if args.input_source_check_script else None,
            required_predictor_capabilities=tuple(args.require_predictor_capability),
            include_cases=bool(args.include_cases),
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if bool(report.get("passed")) else 1

    if args.command == "squirrel-tryout-gate":
        report = run_squirrel_tryout_gate(
            adapter,
            core,
            predictor,
            db_path=Path(args.db_path),
            cases_file=Path(args.cases_file),
            project=args.project,
            top_k=max(1, args.top_k),
            match=args.match,
            repeat=max(1, args.repeat),
            min_rag_pass_rate=max(0.0, min(1.0, args.min_rag_pass_rate)),
            min_sidecar_pass_rate=max(0.0, min(1.0, args.min_sidecar_pass_rate)),
            min_rag_top1_accuracy=max(0.0, min(1.0, args.min_rag_top1_accuracy)),
            min_sidecar_top1_accuracy=max(0.0, min(1.0, args.min_sidecar_top1_accuracy)),
            min_rag_mrr=max(0.0, min(1.0, args.min_rag_mrr)),
            min_sidecar_mrr=max(0.0, min(1.0, args.min_sidecar_mrr)),
            max_rag_noise_rate=max(0.0, min(1.0, args.max_rag_noise_rate)),
            max_sidecar_noise_rate=max(0.0, min(1.0, args.max_sidecar_noise_rate)),
            max_sidecar_rag_timeout_rate=max(0.0, min(1.0, args.max_sidecar_rag_timeout_rate)),
            max_sidecar_model_timeout_rate=max(0.0, min(1.0, args.max_sidecar_model_timeout_rate)),
            max_old_input_echo_rate=max(0.0, min(1.0, args.max_old_input_echo_rate)),
            require_model_ttfc=bool(args.require_model_ttfc),
            model_ttfc_cases_file=Path(args.model_ttfc_cases_file),
            model_ttfc_provider=args.model_ttfc_provider,
            model_ttfc_base_url=args.model_ttfc_base_url,
            model_ttfc_models=args.model_ttfc_models,
            model_ttfc_profile=args.model_ttfc_profile,
            model_ttfc_repeat=max(1, args.model_ttfc_repeat),
            model_ttfc_warmup_runs=max(0, args.model_ttfc_warmup_runs),
            model_ttfc_latency_budget_ms=max(1, args.model_ttfc_latency_budget_ms),
            max_model_ttfc_p95_ms=max(1, args.max_model_ttfc_p95_ms),
            max_model_ttfc_over_budget_rate=max(0.0, min(1.0, args.max_model_ttfc_over_budget_rate)),
            cache_current_input=args.cache_current_input,
            cache_recent_context=args.cache_recent_context,
            cache_repeat=max(1, args.cache_repeat),
            rime_candidates=list(args.rime_candidate),
            max_visible_candidates=max(1, min(10, args.max_visible_candidates)),
            max_side_candidates=max(0, min(10, args.max_side_candidates)),
            sidecar_latency_budget_ms=max(30, args.sidecar_latency_budget_ms),
            rime_cache_ttl_ms=max(0, args.rime_cache_ttl_ms),
            force_side_candidates=not bool(args.no_force_side_candidates),
            require_suggestion_cache=not bool(args.no_require_suggestion_cache),
            require_acceptance_check=not bool(args.skip_acceptance_check),
            input_source_id=args.input_source_id,
            input_source_check_script=Path(args.input_source_check_script) if args.input_source_check_script else None,
            include_input_source_audit=bool(args.include_input_source_audit),
            squirrel_app=Path(args.squirrel_app) if args.squirrel_app else None,
            squirrel_config_path=Path(args.squirrel_config_path),
            expected_rime_primary_schema=args.expected_rime_primary_schema,
            expected_rime_page_size=max(1, min(10, args.expected_rime_page_size)),
            sidecar_url=args.sidecar_url,
            launch_agent_label=args.launch_agent_label,
            skip_launch_agent=bool(args.skip_launch_agent),
            skip_sidecar_health=bool(args.skip_sidecar_health),
            required_predictor_capabilities=tuple(args.require_predictor_capability),
            include_cases=bool(args.include_cases),
        )
        if args.report_path:
            report_path = Path(args.report_path)
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if bool(report.get("passed")) else 1

    if args.command == "debug-server":
        from .debug_server import DebugServerConfig, run_debug_server

        run_debug_server(
            DebugServerConfig(
                host=args.host,
                port=args.port,
                db_path=Path(args.db_path),
                project=args.project,
                static_dir=Path(args.static_dir),
                seed_if_empty=not args.no_seed,
                core=core,
                rime_cache_ttl_ms=args.rime_cache_ttl_ms,
                vector_auto_rebuild_limit=args.vector_auto_rebuild_limit,
            )
        )
        return 0

    if args.command == "sidecar-server":
        from .debug_server import DebugServerConfig, run_debug_server

        run_debug_server(
            DebugServerConfig(
                host=args.host,
                port=args.port,
                db_path=Path(args.db_path),
                project=args.project,
                static_dir=Path("debug"),
                seed_if_empty=not args.no_seed,
                core=core,
                server_name="sidecar server",
                rime_cache_ttl_ms=args.rime_cache_ttl_ms,
                vector_auto_rebuild_limit=args.vector_auto_rebuild_limit,
            )
        )
        return 0

    if args.command == "acceptance":
        report = run_acceptance(adapter)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    parser.error(f"unknown command: {args.command}")
    return 2


def seed_demo_memories(adapter: InputMethodAdapter, memories: list[CoreMemory]) -> list[str]:
    event_ids: list[str] = []
    created_at = now_ms()
    for index, memory in enumerate(memories):
        event_ids.append(
            adapter.core.record_event(
                InputEvent(
                    event_id=None,
                    created_at_ms=created_at + index,
                    source="demo_seed",
                    committed_text=memory.text,
                    recent_context=memory.evidence_preview,
                    preedit="",
                    schema_id="demo",
                    app="cli",
                    project=memory.project or adapter.project,
                    provider_name="demo-fixture",
                    tags=memory.tags,
                )
            )
        )
    return event_ids


def seed_eval_case_memories(adapter: InputMethodAdapter, cases: list[CodexEvalCase], *, project: str) -> list[str]:
    event_ids: list[str] = []
    created_at = now_ms()
    for index, case in enumerate(cases):
        expected = " ".join(case.expected_terms)
        committed_text = compact_whitespace(f"{expected} {case.query}" if expected else case.query)
        if not committed_text:
            continue
        event_id = adapter.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=created_at + index,
                source="eval_case_seed",
                committed_text=committed_text,
                recent_context=compact_whitespace(f"eval_case:{case.case_id} expected:{expected}"),
                preedit="",
                schema_id="eval_case",
                app="product-readiness-gate",
                project=case.project or project or adapter.project,
                provider_name="eval-case-fixture",
                tags=("eval-case", "curated", f"case:{case.case_id}"),
            )
        )
        event_ids.append(event_id)
        recorder = getattr(adapter.core, "record_memory_feedback", None)
        source_event_id = _event_id_from_memory_id_for_seed(event_id)
        if callable(recorder) and source_event_id is not None:
            recorder(
                {
                    "event": "accepted",
                    "candidateId": event_id,
                    "candidateText": committed_text,
                    "sourceType": "memory",
                    "contextHash": f"eval-case:{case.case_id}",
                    "timestampMs": created_at + index,
                    "project": case.project or project or adapter.project,
                    "sourceEventId": source_event_id,
                    "query": case.query,
                }
            )
    return event_ids


def _event_id_from_memory_id_for_seed(memory_id: str) -> int | None:
    if not memory_id.startswith("event:"):
        return None
    try:
        return int(memory_id.split(":", 1)[1])
    except ValueError:
        return None


def run_codex_history_eval(
    adapter: InputMethodAdapter,
    core,
    *,
    cases_file: Path,
    project: str,
    top_k: int,
    match: str,
    repeat: int,
) -> dict[str, object]:
    cases = load_eval_cases(cases_file)
    repeat_count = max(1, repeat)
    results = []
    elapsed_ms_by_case: dict[str, int] = {}
    for repeat_index in range(1, repeat_count + 1):
        for case in cases:
            eval_case = _case_for_eval_repeat(case, repeat_index=repeat_index, repeat_count=repeat_count)
            started = time.perf_counter()
            suggestions = adapter.suggest(
                SuggestionRequest(
                    current_input=eval_case.query,
                    recent_context=eval_case.recent_context,
                    project=eval_case.project or project,
                    top_k=top_k,
                )
            )
            elapsed_ms_by_case[eval_case.case_id] = int((time.perf_counter() - started) * 1000)
            results.append(evaluate_suggestions(eval_case, suggestions, match=match))
    report = eval_report(results)
    report["repeat"] = {
        "requested": repeat_count,
        "baseCaseCount": len(cases),
        "effectiveCaseCount": len(results),
    }
    _attach_eval_latency(report, elapsed_ms_by_case)
    cache_stats = getattr(core, "suggestion_cache_stats", None)
    if callable(cache_stats):
        report["cacheStats"] = cache_stats()
    _attach_vector_stats(report, core)
    return report


def run_rime_sidecar_eval(
    core,
    predictor,
    *,
    db_path: Path,
    cases_file: Path,
    project: str,
    match: str,
    repeat: int,
    max_visible_candidates: int,
    max_side_candidates: int,
    sidecar_latency_budget_ms: int,
    rime_cache_ttl_ms: int,
    force_side_candidates: bool,
) -> dict[str, object]:
    from .debug_server import DebugImeService, DebugServerConfig

    cases = load_eval_cases(cases_file)
    repeat_count = max(1, repeat)
    service = DebugImeService(
        DebugServerConfig(
            db_path=db_path,
            project=project,
            core=core,
            predictor=predictor,
            seed_if_empty=False,
            rime_cache_ttl_ms=max(0, rime_cache_ttl_ms),
        )
    )
    results = []
    elapsed_ms_by_case: dict[str, int] = {}
    side_counts: list[int] = []
    model_counts: list[int] = []
    rag_counts: list[int] = []
    trigger_refresh_count = 0
    rag_lane_called_count = 0
    rag_lane_timeout_count = 0
    model_lane_called_count = 0
    model_lane_timeout_count = 0
    for repeat_index in range(1, repeat_count + 1):
        for case_index, case in enumerate(cases, start=1):
            eval_case = _case_for_eval_repeat(case, repeat_index=repeat_index, repeat_count=repeat_count)
            payload = _rime_eval_payload(
                eval_case,
                request_seq=(repeat_index - 1) * len(cases) + case_index,
                project=eval_case.project or project,
                max_visible_candidates=max_visible_candidates,
                max_side_candidates=max_side_candidates,
                latency_budget_ms=sidecar_latency_budget_ms,
                force_side_candidates=force_side_candidates,
            )
            started = time.perf_counter()
            response = service.rime_suggest(payload)
            elapsed_ms_by_case[eval_case.case_id] = int((time.perf_counter() - started) * 1000)
            display_candidates = response.get("displayCandidates") if isinstance(response, dict) else []
            side_suggestions = _rime_display_side_candidates_as_eval_suggestions(display_candidates)
            side_counts.append(len(side_suggestions))
            model_counts.append(sum(1 for item in side_suggestions if item.suggestion_type == "model_prediction"))
            rag_counts.append(sum(1 for item in side_suggestions if item.suggestion_type == "rag_candidate"))
            trigger = response.get("triggerDecision") if isinstance(response, dict) else {}
            if isinstance(trigger, dict) and trigger.get("shouldRefresh"):
                trigger_refresh_count += 1
            rag_lane = response.get("ragLane") if isinstance(response, dict) else {}
            if isinstance(rag_lane, dict):
                if bool(rag_lane.get("called")):
                    rag_lane_called_count += 1
                if bool(rag_lane.get("timedOut")):
                    rag_lane_timeout_count += 1
            model_lane = response.get("modelLane") if isinstance(response, dict) else {}
            if isinstance(model_lane, dict):
                if bool(model_lane.get("called")):
                    model_lane_called_count += 1
                if bool(model_lane.get("timedOut")):
                    model_lane_timeout_count += 1
            results.append(evaluate_suggestions(eval_case, side_suggestions, match=match))
    report = eval_report(results)
    report["schemaVersion"] = "rag-ime.rime-sidecar-eval.v1"
    report["casesFile"] = str(cases_file)
    report["project"] = project
    report["match"] = match
    report["repeat"] = {
        "requested": repeat_count,
        "baseCaseCount": len(cases),
        "effectiveCaseCount": len(results),
    }
    _attach_eval_latency(report, elapsed_ms_by_case)
    health = service.health()
    report["sidecar"] = {
        "maxVisibleCandidates": max_visible_candidates,
        "maxSideCandidates": max_side_candidates,
        "latencyBudgetMs": max(30, int(sidecar_latency_budget_ms)),
        "forceSideCandidates": force_side_candidates,
        "triggerRefreshCount": trigger_refresh_count,
        "totalSideCandidates": sum(side_counts),
        "totalModelCandidates": sum(model_counts),
        "totalRagCandidates": sum(rag_counts),
        "hasSideCandidates": any(count > 0 for count in side_counts),
        "ragLaneCalledCount": rag_lane_called_count,
        "ragLaneTimeoutCount": rag_lane_timeout_count,
        "ragLaneTimeoutRate": _rate(rag_lane_timeout_count, len(results)),
        "modelLaneCalledCount": model_lane_called_count,
        "modelLaneTimeoutCount": model_lane_timeout_count,
        "modelLaneTimeoutRate": _rate(model_lane_timeout_count, len(results)),
        "rimeSuggestCache": health.get("rimeSuggestCache"),
        "suggestionCache": health.get("suggestionCache"),
        "predictor": health.get("predictor"),
    }
    _attach_vector_stats(report, core)
    return report


def run_cache_probe(
    core,
    predictor,
    *,
    db_path: Path,
    project: str,
    current_input: str,
    recent_context: str,
    top_k: int,
    repeat: int,
    rime_candidates: list[str],
    rime_cache_ttl_ms: int,
    force_side_candidates: bool,
) -> dict[str, object]:
    from .debug_server import DebugImeService, DebugServerConfig

    service = DebugImeService(
        DebugServerConfig(
            db_path=db_path,
            project=project,
            seed_if_empty=False,
            core=core,
            predictor=predictor,
            rime_cache_ttl_ms=rime_cache_ttl_ms,
        )
    )
    return service.cache_probe(
        {
            "currentInput": current_input,
            "recentContext": recent_context,
            "project": project,
            "topK": top_k,
            "repeat": repeat,
            "rimeCandidates": rime_candidates,
            "forceSideCandidates": force_side_candidates,
        }
    )


def run_squirrel_tryout_gate(
    adapter: InputMethodAdapter,
    core,
    predictor,
    *,
    db_path: Path,
    cases_file: Path,
    project: str,
    top_k: int,
    match: str,
    repeat: int,
    min_rag_pass_rate: float,
    min_sidecar_pass_rate: float,
    min_rag_top1_accuracy: float,
    min_sidecar_top1_accuracy: float,
    min_rag_mrr: float,
    min_sidecar_mrr: float,
    max_rag_noise_rate: float,
    max_sidecar_noise_rate: float,
    max_sidecar_rag_timeout_rate: float,
    max_sidecar_model_timeout_rate: float,
    max_old_input_echo_rate: float,
    require_model_ttfc: bool,
    model_ttfc_cases_file: Path,
    model_ttfc_provider: str,
    model_ttfc_base_url: str,
    model_ttfc_models: str,
    model_ttfc_profile: str,
    model_ttfc_repeat: int,
    model_ttfc_warmup_runs: int,
    model_ttfc_latency_budget_ms: int,
    max_model_ttfc_p95_ms: int,
    max_model_ttfc_over_budget_rate: float,
    cache_current_input: str,
    cache_recent_context: str,
    cache_repeat: int,
    rime_candidates: list[str],
    max_visible_candidates: int,
    max_side_candidates: int,
    sidecar_latency_budget_ms: int,
    rime_cache_ttl_ms: int,
    force_side_candidates: bool,
    require_suggestion_cache: bool,
    require_acceptance_check: bool,
    input_source_id: str,
    input_source_check_script: Path | None,
    include_input_source_audit: bool,
    squirrel_app: Path | None,
    squirrel_config_path: Path,
    expected_rime_primary_schema: str,
    expected_rime_page_size: int,
    sidecar_url: str,
    launch_agent_label: str,
    skip_launch_agent: bool,
    skip_sidecar_health: bool,
    required_predictor_capabilities: tuple[str, ...],
    include_cases: bool,
) -> dict[str, object]:
    from .debug_server import DebugImeService, DebugServerConfig

    bundle_report = _tryout_installed_bundle(squirrel_app)
    config_report = _tryout_installed_rime_config(
        squirrel_config_path,
        expected_db_path=db_path,
        expected_project=project,
        expected_sidecar_url=sidecar_url,
    )
    defaults_report = _tryout_installed_rime_defaults(
        squirrel_config_path,
        expected_primary_schema=expected_rime_primary_schema,
        expected_page_size=expected_rime_page_size,
    )
    build_report = _tryout_installed_rime_build(squirrel_config_path)
    input_source_report = DebugImeService(
        DebugServerConfig(
            db_path=db_path,
            project=project,
            seed_if_empty=False,
            core=core,
            predictor=predictor,
            input_source_id=input_source_id,
            input_source_check_script=input_source_check_script,
            input_source_require_hitoolbox=True,
        )
    ).input_source_status()
    input_source_audit = (
        _tryout_input_source_audit(input_source_id=input_source_id, input_source_check_script=input_source_check_script)
        if include_input_source_audit
        else None
    )
    input_ready = bool(input_source_report.get("typingReady"))
    launch_agent_report = (
        {"schemaVersion": "rag-ime.tryout-launch-agent.v1", "skipped": True, "ok": True, "label": launch_agent_label}
        if skip_launch_agent
        else _tryout_launch_agent_status(launch_agent_label)
    )
    sidecar_report = (
        {"schemaVersion": "rag-ime.tryout-sidecar-health.v1", "skipped": True, "ok": True}
        if skip_sidecar_health
        else _tryout_sidecar_health(sidecar_url)
    )
    bundle_ok = bool(bundle_report.get("ok"))
    config_ok = bool(config_report.get("ok"))
    defaults_ok = bool(defaults_report.get("ok"))
    build_ok = bool(build_report.get("ok"))
    launch_agent_ok = bool(launch_agent_report.get("ok"))
    sidecar_ok = bool(sidecar_report.get("ok"))
    quality_report: dict[str, object] | None = None
    if bundle_ok and config_ok and defaults_ok and build_ok and launch_agent_ok and input_ready and sidecar_ok:
        quality_report = run_quality_gate(
            adapter,
            core,
            predictor,
            db_path=db_path,
            cases_file=cases_file,
            project=project,
            top_k=top_k,
            match=match,
            repeat=repeat,
            min_rag_pass_rate=min_rag_pass_rate,
            min_sidecar_pass_rate=min_sidecar_pass_rate,
            min_rag_top1_accuracy=min_rag_top1_accuracy,
            min_sidecar_top1_accuracy=min_sidecar_top1_accuracy,
            min_rag_mrr=min_rag_mrr,
            min_sidecar_mrr=min_sidecar_mrr,
            max_rag_noise_rate=max_rag_noise_rate,
            max_sidecar_noise_rate=max_sidecar_noise_rate,
            max_sidecar_rag_timeout_rate=max_sidecar_rag_timeout_rate,
            max_sidecar_model_timeout_rate=max_sidecar_model_timeout_rate,
            max_old_input_echo_rate=max_old_input_echo_rate,
            require_model_ttfc=require_model_ttfc,
            model_ttfc_cases_file=model_ttfc_cases_file,
            model_ttfc_provider=model_ttfc_provider,
            model_ttfc_base_url=model_ttfc_base_url,
            model_ttfc_models=model_ttfc_models,
            model_ttfc_profile=model_ttfc_profile,
            model_ttfc_repeat=model_ttfc_repeat,
            model_ttfc_warmup_runs=model_ttfc_warmup_runs,
            model_ttfc_latency_budget_ms=model_ttfc_latency_budget_ms,
            max_model_ttfc_p95_ms=max_model_ttfc_p95_ms,
            max_model_ttfc_over_budget_rate=max_model_ttfc_over_budget_rate,
            cache_current_input=cache_current_input,
            cache_recent_context=cache_recent_context,
            cache_repeat=cache_repeat,
            rime_candidates=rime_candidates,
            max_visible_candidates=max_visible_candidates,
            max_side_candidates=max_side_candidates,
            sidecar_latency_budget_ms=sidecar_latency_budget_ms,
            rime_cache_ttl_ms=rime_cache_ttl_ms,
            force_side_candidates=force_side_candidates,
            require_suggestion_cache=require_suggestion_cache,
            require_acceptance_check=require_acceptance_check,
            require_input_source_ready=True,
            input_source_id=input_source_id,
            input_source_check_script=input_source_check_script,
            required_predictor_capabilities=required_predictor_capabilities,
            include_cases=include_cases,
        )
    duplicate_apps_check = _tryout_duplicate_squirrel_apps_check(input_source_audit)
    checks = [
        {
            "name": "installed-bundle",
            "passed": bundle_ok,
            "appPath": bundle_report.get("appPath"),
            "bundleIdentifier": bundle_report.get("bundleIdentifier"),
        },
        {
            "name": "installed-rime-config",
            "passed": config_ok,
            "configPath": config_report.get("configPath"),
            "enabled": config_report.get("enabled"),
            "sidecarUrlMatches": config_report.get("sidecarUrlMatches"),
            "dbPathMatches": config_report.get("dbPathMatches"),
            "projectMatches": config_report.get("projectMatches"),
        },
        {
            "name": "installed-rime-defaults",
            "passed": defaults_ok,
            "defaultConfigPath": defaults_report.get("defaultConfigPath"),
            "buildDefaultPath": defaults_report.get("buildDefaultPath"),
            "primarySchema": defaults_report.get("primarySchema"),
            "expectedPrimarySchema": defaults_report.get("expectedPrimarySchema"),
            "primarySchemaMatches": defaults_report.get("primarySchemaMatches"),
            "pageSize": defaults_report.get("pageSize"),
            "expectedPageSize": defaults_report.get("expectedPageSize"),
            "pageSizeMatches": defaults_report.get("pageSizeMatches"),
        },
        {
            "name": "installed-rime-build",
            "passed": build_ok,
            "rimeDir": build_report.get("rimeDir"),
            "missingFiles": build_report.get("missingFiles"),
        },
        duplicate_apps_check,
        {
            "name": "input-source-ready",
            "passed": input_ready,
            "readinessState": input_source_report.get("readinessState"),
            "current": input_source_report.get("current"),
            "nextAction": input_source_report.get("nextAction"),
        },
        {
            "name": "launch-agent",
            "passed": launch_agent_ok,
            "skipped": bool(launch_agent_report.get("skipped")),
            "label": launch_agent_label,
            "state": launch_agent_report.get("state"),
            "pid": launch_agent_report.get("pid"),
        },
        {
            "name": "sidecar-health",
            "passed": sidecar_ok,
            "skipped": bool(sidecar_report.get("skipped")),
            "url": sidecar_url,
        },
        {
            "name": "quality-gate",
            "passed": bool(quality_report and quality_report.get("passed")),
            "skipped": quality_report is None,
        },
    ]
    manual_required = _squirrel_tryout_manual_required(
        input_source_report=input_source_report,
        duplicate_apps_check=duplicate_apps_check,
    )
    return {
        "schemaVersion": "rag-ime.squirrel-tryout-gate.v1",
        "passed": all(bool(item.get("passed")) for item in checks),
        "project": project,
        "dbPath": str(db_path),
        "casesFile": str(cases_file),
        "checks": checks,
        "manualRequired": manual_required,
        "installedBundle": bundle_report,
        "installedRimeConfig": config_report,
        "installedRimeDefaults": defaults_report,
        "installedRimeBuild": build_report,
        "inputSource": input_source_report,
        "inputSourceAudit": input_source_audit,
        "launchAgent": launch_agent_report,
        "sidecar": sidecar_report,
        "qualityGate": quality_report,
    }


def _squirrel_tryout_manual_required(
    *,
    input_source_report: dict[str, object],
    duplicate_apps_check: dict[str, object],
) -> list[str]:
    items = [
        "foreground editor typing verification",
        "real Squirrel candidate panel visual check",
        "side candidate number-key commit verification",
    ]
    if not bool(duplicate_apps_check.get("passed")):
        next_action = str(duplicate_apps_check.get("nextAction") or "").strip()
        if next_action:
            items.append(next_action)
        duplicate_paths = duplicate_apps_check.get("duplicatePaths")
        if isinstance(duplicate_paths, list):
            for path in duplicate_paths[:5]:
                if path:
                    items.append(f"move duplicate Squirrel.app backup out of LaunchServices-visible folders: {path}")
        cleanup_commands = duplicate_apps_check.get("cleanupCommands")
        if isinstance(cleanup_commands, list):
            for command in cleanup_commands:
                if command:
                    items.append(str(command))
    if not bool(input_source_report.get("typingReady")):
        manual_action = str(input_source_report.get("manualAction") or "").strip()
        helper_command = str(input_source_report.get("helperCommand") or "").strip()
        verification_command = str(input_source_report.get("verificationCommand") or "").strip()
        next_action = str(input_source_report.get("nextAction") or "").strip()
        if manual_action:
            items.append(manual_action)
        elif next_action:
            items.append(next_action)
        if helper_command:
            items.append(helper_command)
        if verification_command:
            items.append(verification_command)
    return items


def _tryout_duplicate_squirrel_apps_check(input_source_audit: dict[str, object] | None) -> dict[str, object]:
    name = "duplicate-squirrel-app-registrations"
    if not isinstance(input_source_audit, dict):
        return {
            "name": name,
            "passed": True,
            "skipped": True,
            "reason": "input source audit not requested",
        }
    launch_services = input_source_audit.get("launchServices")
    if not isinstance(launch_services, dict) or not launch_services.get("available", True):
        return {
            "name": name,
            "passed": True,
            "skipped": True,
            "reason": "LaunchServices audit unavailable",
        }
    duplicate_count = _safe_int(launch_services.get("duplicatePathCount"))
    records = launch_services.get("matchingRecords") if isinstance(launch_services.get("matchingRecords"), list) else []
    paths = [str(item.get("path")) for item in records if isinstance(item, dict) and item.get("path")]
    duplicate_paths = paths[1:] if duplicate_count > 0 and len(paths) > 1 else []
    cleanup_commands = _tryout_duplicate_squirrel_cleanup_commands(duplicate_paths) if duplicate_count > 0 else []
    return {
        "name": name,
        "passed": duplicate_count == 0,
        "skipped": False,
        "duplicatePathCount": duplicate_count,
        "paths": paths,
        "duplicatePaths": duplicate_paths,
        "cleanupCommands": cleanup_commands,
        "nextAction": (
            "move old Squirrel.app backups out of LaunchServices-visible folders, then rerun audit"
            if duplicate_count > 0
            else ""
        ),
    }


def _tryout_duplicate_squirrel_cleanup_commands(duplicate_paths: Sequence[str]) -> list[str]:
    if not duplicate_paths:
        return []
    quarantine_root = Path.home() / "Library" / "Application Support" / "RagIme" / "disabled-input-method-backups"
    commands = [f"sudo mkdir -p {shlex.quote(str(quarantine_root))}"]
    for path in duplicate_paths[:5]:
        if not path:
            continue
        target_prefix = f"{quarantine_root}/{Path(path).name}.disabled-bundle-"
        commands.append(f"sudo mv {shlex.quote(str(path))} {shlex.quote(target_prefix)}$(date +%Y%m%d-%H%M%S)")
    commands.append("RAG_IME_QUARANTINE_STALE_SQUIRREL_APPS=1 scripts/refresh_squirrel_input_source_registration.sh")
    commands.append("python3 scripts/audit_squirrel_input_source.py")
    return commands


def _tryout_input_source_audit(*, input_source_id: str, input_source_check_script: Path | None) -> dict[str, object]:
    script = Path(__file__).resolve().parents[1] / "scripts" / "audit_squirrel_input_source.py"
    payload: dict[str, object] = {
        "schemaVersion": "rag-ime.macos-input-source-audit.v1",
        "available": script.exists(),
        "exitCode": None,
        "error": "",
    }
    if not script.exists():
        return {**payload, "error": "audit script is missing"}
    cmd = [sys.executable, str(script), "--input-source-id", input_source_id]
    if input_source_check_script is not None:
        cmd.extend(["--check-script", str(input_source_check_script)])
    try:
        completed = subprocess.run(cmd, check=False, text=True, capture_output=True, timeout=15)
    except Exception as exc:
        return {**payload, "error": str(exc)}
    try:
        report = json.loads(completed.stdout)
    except Exception as exc:
        return {
            **payload,
            "exitCode": completed.returncode,
            "error": f"cannot parse audit JSON: {exc}",
            "rawOutput": "\n".join(part for part in (completed.stdout.strip(), completed.stderr.strip()) if part),
        }
    if isinstance(report, dict):
        report.setdefault("available", True)
        report["exitCode"] = completed.returncode
        return report
    return {**payload, "exitCode": completed.returncode, "error": "audit JSON root is not an object"}


def _tryout_installed_bundle(squirrel_app: Path | None) -> dict[str, object]:
    app_path = _resolve_squirrel_app_path(squirrel_app)
    executable = app_path / "Contents" / "MacOS" / "Squirrel"
    info_plist = app_path / "Contents" / "Info.plist"
    bundle_identifier = ""
    if info_plist.exists():
        try:
            with info_plist.open("rb") as fh:
                info = plistlib.load(fh)
            bundle_identifier = str(info.get("CFBundleIdentifier") or "")
        except Exception:
            bundle_identifier = ""
    executable_exists = executable.exists() and os.access(executable, os.X_OK)
    return {
        "schemaVersion": "rag-ime.tryout-installed-bundle.v1",
        "ok": app_path.is_dir() and executable_exists,
        "appPath": str(app_path),
        "bundleExists": app_path.is_dir(),
        "executablePath": str(executable),
        "executableExists": executable_exists,
        "bundleIdentifier": bundle_identifier,
    }


def _resolve_squirrel_app_path(squirrel_app: Path | None) -> Path:
    if squirrel_app is not None:
        return squirrel_app.expanduser()
    candidates = [
        Path.home() / "Library" / "Input Methods" / "Squirrel.app",
        Path("/Library/Input Methods/Squirrel.app"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _tryout_installed_rime_config(
    config_path: Path,
    *,
    expected_db_path: Path,
    expected_project: str,
    expected_sidecar_url: str,
) -> dict[str, object]:
    expanded_config_path = config_path.expanduser()
    payload: dict[str, object] = {
        "schemaVersion": "rag-ime.tryout-installed-rime-config.v1",
        "configPath": str(expanded_config_path),
        "exists": expanded_config_path.exists(),
        "ok": False,
    }
    if not expanded_config_path.exists():
        return {**payload, "error": "Squirrel custom config is missing"}
    values = _parse_rag_ime_managed_config(expanded_config_path.read_text(encoding="utf-8"))
    required_keys = ("enabled", "sidecar_url", "db_path", "project")
    missing = [key for key in required_keys if key not in values]
    enabled = _config_bool(values.get("enabled"))
    sidecar_url = str(values.get("sidecar_url") or "")
    db_path = str(values.get("db_path") or "")
    project = str(values.get("project") or "")
    sidecar_matches = _same_sidecar_base(sidecar_url, expected_sidecar_url)
    db_matches = _same_path_text(db_path, str(expected_db_path))
    project_matches = project == expected_project
    ok = not missing and enabled and sidecar_matches and db_matches and project_matches
    return {
        **payload,
        "ok": ok,
        "values": values,
        "missingKeys": missing,
        "enabled": enabled,
        "sidecarUrl": sidecar_url,
        "expectedSidecarUrl": expected_sidecar_url,
        "sidecarUrlMatches": sidecar_matches,
        "dbPath": db_path,
        "expectedDbPath": str(expected_db_path),
        "dbPathMatches": db_matches,
        "project": project,
        "expectedProject": expected_project,
        "projectMatches": project_matches,
    }


def _tryout_installed_rime_defaults(
    config_path: Path,
    *,
    expected_primary_schema: str,
    expected_page_size: int,
) -> dict[str, object]:
    rime_dir = config_path.expanduser().parent
    default_config_path = rime_dir / "default.custom.yaml"
    build_default_path = rime_dir / "build" / "default.yaml"
    expected_primary_schema = expected_primary_schema.strip() or "luna_pinyin_simp"
    expected_page_size = max(1, min(10, int(expected_page_size)))
    default_custom = _parse_rime_default_settings(default_config_path.read_text(encoding="utf-8")) if default_config_path.exists() else {}
    build_default = _parse_rime_default_settings(build_default_path.read_text(encoding="utf-8")) if build_default_path.exists() else {}
    primary_schema = str(build_default.get("primarySchema") or "")
    page_size = build_default.get("pageSize")
    default_custom_primary_matches = default_custom.get("primarySchema") == expected_primary_schema
    default_custom_page_matches = default_custom.get("pageSize") == expected_page_size
    primary_matches = primary_schema == expected_primary_schema
    page_matches = page_size == expected_page_size
    ok = (
        default_config_path.exists()
        and build_default_path.exists()
        and default_custom_primary_matches
        and default_custom_page_matches
        and primary_matches
        and page_matches
    )
    missing = []
    if not default_config_path.exists():
        missing.append("default.custom.yaml")
    if not build_default_path.exists():
        missing.append("build/default.yaml")
    return {
        "schemaVersion": "rag-ime.tryout-installed-rime-defaults.v1",
        "ok": ok,
        "rimeDir": str(rime_dir),
        "defaultConfigPath": str(default_config_path),
        "defaultConfigExists": default_config_path.exists(),
        "buildDefaultPath": str(build_default_path),
        "buildDefaultExists": build_default_path.exists(),
        "missingFiles": missing,
        "expectedPrimarySchema": expected_primary_schema,
        "expectedPageSize": expected_page_size,
        "defaultCustom": default_custom,
        "defaultCustomPrimarySchemaMatches": default_custom_primary_matches,
        "defaultCustomPageSizeMatches": default_custom_page_matches,
        "buildDefault": build_default,
        "primarySchema": primary_schema,
        "primarySchemaMatches": primary_matches,
        "pageSize": page_size,
        "pageSizeMatches": page_matches,
    }


def _tryout_installed_rime_build(config_path: Path) -> dict[str, object]:
    rime_dir = config_path.expanduser().parent
    expected_files = (
        "build/default.yaml",
        "build/luna_pinyin.schema.yaml",
        "build/luna_pinyin.table.bin",
    )
    files = [
        {
            "path": str(rime_dir / relative_path),
            "relativePath": relative_path,
            "exists": (rime_dir / relative_path).is_file(),
        }
        for relative_path in expected_files
    ]
    missing = [item["relativePath"] for item in files if not item["exists"]]
    return {
        "schemaVersion": "rag-ime.tryout-installed-rime-build.v1",
        "ok": not missing,
        "rimeDir": str(rime_dir),
        "expectedFiles": files,
        "missingFiles": missing,
    }


def _parse_rime_default_settings(text: str) -> dict[str, object]:
    primary_schema = ""
    page_size: int | None = None
    in_schema_list = False
    schema_indent = 0
    in_menu = False
    menu_indent = 0

    for raw_line in text.splitlines():
        line_without_comment = raw_line.split("#", 1)[0].rstrip()
        stripped = line_without_comment.strip()
        if not stripped:
            continue
        indent = len(line_without_comment) - len(line_without_comment.lstrip(" "))

        if stripped == "schema_list:":
            in_schema_list = True
            schema_indent = indent
            continue
        if in_schema_list:
            if indent <= schema_indent and not stripped.startswith("-"):
                in_schema_list = False
            elif "schema:" in stripped and not primary_schema:
                value = stripped.split("schema:", 1)[1].strip().strip("'\"")
                if value:
                    primary_schema = value

        if stripped == "menu:":
            in_menu = True
            menu_indent = indent
            continue
        if in_menu:
            if indent <= menu_indent:
                in_menu = False
            elif stripped.startswith("page_size:"):
                page_size = _parse_int_config_value(stripped.split(":", 1)[1])

        if stripped.startswith('"menu/page_size":') or stripped.startswith("menu/page_size:"):
            page_size = _parse_int_config_value(stripped.split(":", 1)[1])

    return {
        "primarySchema": primary_schema,
        "pageSize": page_size,
    }


def _parse_int_config_value(value_text: str) -> int | None:
    value = value_text.strip().strip("'\"")
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _parse_rag_ime_managed_config(text: str) -> dict[str, object]:
    start = "# >>> RAG-IME managed block"
    end = "# <<< RAG-IME managed block"
    if start not in text or end not in text:
        return {}
    managed = text.split(start, 1)[1].split(end, 1)[0]
    values: dict[str, object] = {}
    for raw_line in managed.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, raw_value = line.partition(":")
        if not sep:
            continue
        key = key.strip().strip('"')
        if not key.startswith("rag_ime/"):
            continue
        value_text = raw_value.strip()
        try:
            value: object = json.loads(value_text)
        except json.JSONDecodeError:
            value = value_text.strip('"')
        values[key.removeprefix("rag_ime/")] = value
    return values


def _config_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _same_sidecar_base(left: str, right: str) -> bool:
    def normalize(value: str) -> str:
        text = value.strip().rstrip("/")
        if text.endswith("/api"):
            text = text[:-4]
        return text.rstrip("/")

    return bool(left and right) and normalize(left) == normalize(right)


def _same_path_text(left: str, right: str) -> bool:
    if not left or not right:
        return False
    return os.path.abspath(os.path.expanduser(left)) == os.path.abspath(os.path.expanduser(right))


def _tryout_launch_agent_status(label: str) -> dict[str, object]:
    command = ["launchctl", "print", f"gui/{os.getuid()}/{label}"]
    try:
        completed = subprocess.run(command, check=False, text=True, capture_output=True, timeout=3.0)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "schemaVersion": "rag-ime.tryout-launch-agent.v1",
            "ok": False,
            "label": label,
            "error": str(exc),
        }
    output = "\n".join(part for part in (completed.stdout.strip(), completed.stderr.strip()) if part)
    state = _launchctl_field(output, "state")
    report: dict[str, object] = {
        "schemaVersion": "rag-ime.tryout-launch-agent.v1",
        "ok": completed.returncode == 0 and state == "running",
        "label": label,
        "exitCode": completed.returncode,
        "state": state,
        "pid": _launchctl_field(output, "pid"),
        "path": _launchctl_field(output, "path"),
        "program": _launchctl_field(output, "program"),
    }
    if not report["ok"]:
        report["rawOutput"] = output[-4000:]
    return report


def _launchctl_field(output: str, key: str) -> str:
    prefix = f"{key} = "
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith(prefix):
            return stripped[len(prefix) :].strip()
    return ""


def _tryout_sidecar_health(sidecar_url: str) -> dict[str, object]:
    base = sidecar_url.rstrip("/")
    try:
        with urllib.request.urlopen(f"{base}/health", timeout=2.0) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return {
            "schemaVersion": "rag-ime.tryout-sidecar-health.v1",
            "ok": False,
            "url": base,
            "error": str(exc),
        }
    predictor = payload.get("predictor") if isinstance(payload.get("predictor"), dict) else {}
    rime_probe = _tryout_sidecar_rime_suggest(base)
    health_ok = bool(payload.get("ok"))
    return {
        "schemaVersion": "rag-ime.tryout-sidecar-health.v1",
        "ok": health_ok and bool(rime_probe.get("ok")),
        "healthOk": health_ok,
        "url": base,
        "eventCount": payload.get("eventCount"),
        "predictor": {
            "providerName": predictor.get("providerName"),
            "model": predictor.get("model"),
            "streamFirstCandidate": predictor.get("streamFirstCandidate"),
            "configured": predictor.get("configured"),
        },
        "rimeSuggest": rime_probe,
    }


def _tryout_sidecar_rime_suggest(base_url: str) -> dict[str, object]:
    request_payload = {
        "sessionId": "tryout-gate",
        "requestSeq": 1,
        "rawInput": "bendi",
        "preedit": "bendi",
        "committedContext": "Squirrel tryout gate",
        "maxVisibleCandidates": 3,
        "maxSideCandidates": 1,
        "idleMs": 0,
        "rimeContext": {
            "candidates": [
                {
                    "label": "1",
                    "text": "本地记忆",
                    "comment": "tryout",
                    "index": 0,
                }
            ],
            "highlightedIndex": 0,
            "page": 0,
            "isLastPage": True,
        },
    }
    try:
        request = urllib.request.Request(
            f"{base_url}/rime-suggest",
            data=json.dumps(request_payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=3.0) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return {
            "ok": False,
            "error": str(exc),
        }
    display_candidates = payload.get("displayCandidates") if isinstance(payload.get("displayCandidates"), list) else []
    return {
        "ok": payload.get("schemaVersion") == "rag-ime.rime-sidecar.v1" and bool(display_candidates),
        "schemaVersion": payload.get("schemaVersion"),
        "displayCandidateCount": len(display_candidates),
        "queryBasis": payload.get("queryBasis"),
        "cache": payload.get("cache") if isinstance(payload.get("cache"), dict) else None,
    }


def run_quality_gate(
    adapter: InputMethodAdapter,
    core,
    predictor,
    *,
    db_path: Path,
    cases_file: Path,
    project: str,
    top_k: int,
    match: str,
    repeat: int,
    min_rag_pass_rate: float,
    min_sidecar_pass_rate: float,
    min_rag_top1_accuracy: float,
    min_sidecar_top1_accuracy: float,
    min_rag_mrr: float,
    min_sidecar_mrr: float,
    max_rag_noise_rate: float,
    max_sidecar_noise_rate: float,
    max_sidecar_rag_timeout_rate: float,
    max_sidecar_model_timeout_rate: float,
    require_model_ttfc: bool,
    model_ttfc_cases_file: Path,
    model_ttfc_provider: str,
    model_ttfc_base_url: str,
    model_ttfc_models: str,
    model_ttfc_profile: str,
    model_ttfc_repeat: int,
    model_ttfc_warmup_runs: int,
    model_ttfc_latency_budget_ms: int,
    max_model_ttfc_p95_ms: int,
    max_model_ttfc_over_budget_rate: float,
    cache_current_input: str,
    cache_recent_context: str,
    cache_repeat: int,
    rime_candidates: list[str],
    max_visible_candidates: int,
    max_side_candidates: int,
    sidecar_latency_budget_ms: int,
    rime_cache_ttl_ms: int,
    force_side_candidates: bool,
    require_suggestion_cache: bool,
    require_acceptance_check: bool,
    require_input_source_ready: bool,
    input_source_id: str,
    input_source_check_script: Path | None,
    required_predictor_capabilities: tuple[str, ...],
    include_cases: bool,
    max_old_input_echo_rate: float = 1.0,
) -> dict[str, object]:
    from .debug_server import DebugImeService, DebugServerConfig

    rag_report = run_codex_history_eval(
        adapter,
        core,
        cases_file=cases_file,
        project=project,
        top_k=top_k,
        match=match,
        repeat=repeat,
    )
    rime_report = run_rime_sidecar_eval(
        core,
        predictor,
        db_path=db_path,
        cases_file=cases_file,
        project=project,
        match=match,
        repeat=repeat,
        max_visible_candidates=max_visible_candidates,
        max_side_candidates=max_side_candidates,
        sidecar_latency_budget_ms=sidecar_latency_budget_ms,
        rime_cache_ttl_ms=rime_cache_ttl_ms,
        force_side_candidates=force_side_candidates,
    )
    cache_report = run_cache_probe(
        core,
        predictor,
        db_path=db_path,
        project=project,
        current_input=cache_current_input,
        recent_context=cache_recent_context,
        top_k=top_k,
        repeat=cache_repeat,
        rime_candidates=rime_candidates,
        rime_cache_ttl_ms=rime_cache_ttl_ms,
        force_side_candidates=force_side_candidates,
    )
    acceptance_report = (
        run_acceptance(adapter)
        if require_acceptance_check
        else {"schemaVersion": "rag-ime.acceptance.v1", "skipped": True, "passed": True}
    )
    input_source_report: dict[str, object] | None = None
    if require_input_source_ready:
        input_source_report = DebugImeService(
            DebugServerConfig(
                db_path=db_path,
                project=project,
                seed_if_empty=False,
                core=core,
                predictor=predictor,
                input_source_id=input_source_id,
                input_source_check_script=input_source_check_script,
                input_source_require_hitoolbox=True,
            )
        ).input_source_status()
    predictor_status = prediction_provider_status(
        predictor,
        probe_capabilities=bool(required_predictor_capabilities),
    )
    model_ttfc_report: dict[str, object] | None = None
    if require_model_ttfc:
        model_ttfc_report = run_ime_ttfc_benchmark(
            core=core,
            cases_file=str(model_ttfc_cases_file),
            inline_cases=[],
            recent_context="",
            project=project,
            provider=model_ttfc_provider,
            base_url=model_ttfc_base_url,
            models=model_ttfc_models,
            profile=model_ttfc_profile,
            max_candidates=3,
            repeat=max(1, model_ttfc_repeat),
            warmup_runs=max(0, model_ttfc_warmup_runs),
            latency_budget_ms=max(1, model_ttfc_latency_budget_ms),
            failure_cooldown_ms=0,
            include_cases=False,
        )
    checks = _quality_gate_checks(
        acceptance_report=acceptance_report,
        rag_report=rag_report,
        rime_report=rime_report,
        cache_report=cache_report,
        predictor_status=predictor_status,
        model_ttfc_report=model_ttfc_report,
        input_source_report=input_source_report,
        min_rag_pass_rate=min_rag_pass_rate,
        min_sidecar_pass_rate=min_sidecar_pass_rate,
        min_rag_top1_accuracy=min_rag_top1_accuracy,
        min_sidecar_top1_accuracy=min_sidecar_top1_accuracy,
        min_rag_mrr=min_rag_mrr,
        min_sidecar_mrr=min_sidecar_mrr,
        max_rag_noise_rate=max_rag_noise_rate,
        max_sidecar_noise_rate=max_sidecar_noise_rate,
        max_sidecar_rag_timeout_rate=max_sidecar_rag_timeout_rate,
        max_sidecar_model_timeout_rate=max_sidecar_model_timeout_rate,
        max_old_input_echo_rate=max_old_input_echo_rate,
        require_model_ttfc=require_model_ttfc,
        max_model_ttfc_p95_ms=max_model_ttfc_p95_ms,
        max_model_ttfc_over_budget_rate=max_model_ttfc_over_budget_rate,
        require_suggestion_cache=require_suggestion_cache,
        require_acceptance_check=require_acceptance_check,
        require_input_source_ready=require_input_source_ready,
        required_predictor_capabilities=required_predictor_capabilities,
    )
    rag_payload = rag_report if include_cases else _compact_eval_report(rag_report)
    rime_payload = rime_report if include_cases else _compact_eval_report(rime_report)
    return {
        "schemaVersion": "rag-ime.quality-gate.v1",
        "passed": all(bool(item["passed"]) for item in checks),
        "casesFile": str(cases_file),
        "project": project,
        "thresholds": {
            "minRagPassRate": min_rag_pass_rate,
            "minSidecarPassRate": min_sidecar_pass_rate,
            "minRagTop1Accuracy": min_rag_top1_accuracy,
            "minSidecarTop1Accuracy": min_sidecar_top1_accuracy,
            "minRagMeanReciprocalRank": min_rag_mrr,
            "minSidecarMeanReciprocalRank": min_sidecar_mrr,
            "maxRagNoiseRate": max_rag_noise_rate,
            "maxSidecarNoiseRate": max_sidecar_noise_rate,
            "maxSidecarRagTimeoutRate": max_sidecar_rag_timeout_rate,
            "maxSidecarModelTimeoutRate": max_sidecar_model_timeout_rate,
            "sidecarLatencyBudgetMs": max(30, int(sidecar_latency_budget_ms)),
            "maxOldInputEchoRate": max_old_input_echo_rate,
            "requireModelTtfc": require_model_ttfc,
            "modelTtfcProvider": model_ttfc_provider,
            "modelTtfcBaseUrl": model_ttfc_base_url,
            "modelTtfcModels": model_ttfc_models,
            "modelTtfcCasesFile": str(model_ttfc_cases_file),
            "modelTtfcRepeat": max(1, model_ttfc_repeat),
            "modelTtfcWarmupRuns": max(0, model_ttfc_warmup_runs),
            "modelTtfcLatencyBudgetMs": max(1, model_ttfc_latency_budget_ms),
            "maxModelTtfcP95Ms": max_model_ttfc_p95_ms,
            "maxModelTtfcOverBudgetRate": max_model_ttfc_over_budget_rate,
            "requireSuggestionCache": require_suggestion_cache,
            "requireAcceptanceCheck": require_acceptance_check,
            "requireInputSourceReady": require_input_source_ready,
            "inputSourceId": input_source_id,
            "requiredPredictorCapabilities": list(required_predictor_capabilities),
            "probePredictorCapabilities": bool(required_predictor_capabilities),
            "cacheRepeat": cache_repeat,
        },
        "checks": checks,
        "predictor": predictor_status,
        "acceptance": acceptance_report,
        "rag": rag_payload,
        "rimeSidecar": rime_payload,
        "modelTtfc": model_ttfc_report,
        "inputSource": input_source_report,
        "cacheProbe": cache_report,
    }


def _compact_eval_report(report: dict[str, object]) -> dict[str, object]:
    compact: dict[str, object] = {
        "schemaVersion": report.get("schemaVersion"),
        "total": report.get("total"),
        "passed": report.get("passed"),
        "failed": report.get("failed"),
        "passRate": report.get("passRate"),
        "metrics": report.get("metrics"),
        "repeat": report.get("repeat"),
        "latency": report.get("latency"),
    }
    for key in ("cacheStats", "vectorStats", "sidecar", "prediction", "comparison"):
        if key in report:
            compact[key] = report.get(key)
    failed_cases = []
    cases = report.get("cases")
    if isinstance(cases, list):
        for item in cases:
            if isinstance(item, dict) and not bool(item.get("passed")):
                failed_cases.append(
                    {
                        "caseId": item.get("caseId"),
                        "query": item.get("query"),
                        "expectedTerms": item.get("expectedTerms"),
                        "topSurfaces": item.get("topSurfaces"),
                    }
                )
    compact["failedCasesPreview"] = failed_cases[:8]
    compact["failedCasesPreviewCount"] = len(failed_cases)
    return compact


def _quality_gate_checks(
    *,
    acceptance_report: dict[str, object],
    rag_report: dict[str, object],
    rime_report: dict[str, object],
    cache_report: dict[str, object],
    predictor_status: dict[str, object],
    model_ttfc_report: dict[str, object] | None,
    input_source_report: dict[str, object] | None,
    min_rag_pass_rate: float,
    min_sidecar_pass_rate: float,
    min_rag_top1_accuracy: float,
    min_sidecar_top1_accuracy: float,
    min_rag_mrr: float,
    min_sidecar_mrr: float,
    max_rag_noise_rate: float,
    max_sidecar_noise_rate: float,
    max_sidecar_rag_timeout_rate: float,
    max_sidecar_model_timeout_rate: float,
    max_old_input_echo_rate: float,
    require_model_ttfc: bool,
    max_model_ttfc_p95_ms: int,
    max_model_ttfc_over_budget_rate: float,
    require_suggestion_cache: bool,
    require_acceptance_check: bool,
    require_input_source_ready: bool,
    required_predictor_capabilities: tuple[str, ...],
) -> list[dict[str, object]]:
    cache_summary = cache_report.get("summary") if isinstance(cache_report.get("summary"), dict) else {}
    sidecar = rime_report.get("sidecar") if isinstance(rime_report.get("sidecar"), dict) else {}
    suggestion_cache_pass = cache_summary.get("suggestionCachePassed")
    suggestion_cache_required = require_suggestion_cache or suggestion_cache_pass is not None
    checks = [
        {
            "name": "acceptance",
            "passed": (not require_acceptance_check) or _acceptance_report_passed(acceptance_report),
            "required": require_acceptance_check,
            "skipped": not require_acceptance_check,
        },
        {
            "name": "rag-pass-rate",
            "passed": float(rag_report.get("passRate") or 0.0) >= min_rag_pass_rate,
            "actual": float(rag_report.get("passRate") or 0.0),
            "expectedAtLeast": min_rag_pass_rate,
        },
        {
            "name": "rime-sidecar-pass-rate",
            "passed": float(rime_report.get("passRate") or 0.0) >= min_sidecar_pass_rate,
            "actual": float(rime_report.get("passRate") or 0.0),
            "expectedAtLeast": min_sidecar_pass_rate,
        },
        *_quality_metric_checks(
            "rag",
            rag_report,
            min_top1_accuracy=min_rag_top1_accuracy,
            min_mrr=min_rag_mrr,
            max_noise_rate=max_rag_noise_rate,
        ),
        *_quality_metric_checks(
            "rime-sidecar",
            rime_report,
            min_top1_accuracy=min_sidecar_top1_accuracy,
            min_mrr=min_sidecar_mrr,
            max_noise_rate=max_sidecar_noise_rate,
        ),
        *_sidecar_lane_timeout_checks(
            rime_report,
            max_rag_timeout_rate=max_sidecar_rag_timeout_rate,
            max_model_timeout_rate=max_sidecar_model_timeout_rate,
        ),
        *_old_input_echo_rate_checks(
            "rag",
            rag_report,
            max_old_input_echo_rate=max_old_input_echo_rate,
        ),
        *_old_input_echo_rate_checks(
            "rime-sidecar",
            rime_report,
            max_old_input_echo_rate=max_old_input_echo_rate,
        ),
        {
            "name": "rime-sidecar-has-side-candidates",
            "passed": bool(sidecar.get("hasSideCandidates")),
        },
        {
            "name": "suggestion-cache-warm-hit",
            "passed": (not suggestion_cache_required) or suggestion_cache_pass is True,
            "required": suggestion_cache_required,
            "actual": suggestion_cache_pass,
        },
        {
            "name": "rime-cache-warm-hit",
            "passed": cache_summary.get("rimeCachePassed") is True,
            "actual": cache_summary.get("rimeCachePassed"),
        },
    ]
    if require_model_ttfc:
        checks.extend(
            _model_ttfc_checks(
                model_ttfc_report or {},
                max_p95_first_candidate_ms=max_model_ttfc_p95_ms,
                max_over_budget_rate=max_model_ttfc_over_budget_rate,
            )
        )
    if require_input_source_ready:
        checks.extend(_input_source_ready_checks(input_source_report or {}))
    checks.extend(_predictor_capability_checks(predictor_status, required_predictor_capabilities))
    return checks


def _input_source_ready_checks(report: dict[str, object]) -> list[dict[str, object]]:
    return [
        {
            "name": "input-source-installed",
            "passed": bool(report.get("ok")),
            "inputSourceId": report.get("inputSourceId") or report.get("id"),
            "enabled": report.get("enabled"),
            "selectable": report.get("selectable"),
            "hitoolboxEnabled": report.get("hitoolboxEnabled"),
            "thirdPartyEnabled": report.get("thirdPartyEnabled"),
            "current": report.get("current"),
            "exitCode": report.get("exitCode"),
        },
        {
            "name": "input-source-selected",
            "passed": bool(report.get("typingReady")),
            "inputSourceId": report.get("inputSourceId") or report.get("id"),
            "selected": report.get("selected"),
            "current": report.get("current"),
        },
    ]


def _quality_metric_checks(
    prefix: str,
    report: dict[str, object],
    *,
    min_top1_accuracy: float,
    min_mrr: float,
    max_noise_rate: float,
) -> list[dict[str, object]]:
    metrics = report.get("metrics") if isinstance(report.get("metrics"), dict) else {}
    top1 = float(metrics.get("top1Accuracy") or 0.0)
    mrr = float(metrics.get("meanReciprocalRank") or 0.0)
    noise = float(metrics.get("noiseRate") or 0.0)
    return [
        {
            "name": f"{prefix}-top1-accuracy",
            "passed": top1 >= min_top1_accuracy,
            "actual": top1,
            "expectedAtLeast": min_top1_accuracy,
        },
        {
            "name": f"{prefix}-mean-reciprocal-rank",
            "passed": mrr >= min_mrr,
            "actual": mrr,
            "expectedAtLeast": min_mrr,
        },
        {
            "name": f"{prefix}-noise-rate",
            "passed": noise <= max_noise_rate,
            "actual": noise,
            "expectedAtMost": max_noise_rate,
        },
    ]


def _sidecar_lane_timeout_checks(
    report: dict[str, object],
    *,
    max_rag_timeout_rate: float,
    max_model_timeout_rate: float,
) -> list[dict[str, object]]:
    sidecar = report.get("sidecar") if isinstance(report.get("sidecar"), dict) else {}
    rag_timeout_rate = float(sidecar.get("ragLaneTimeoutRate") or 0.0)
    model_timeout_rate = float(sidecar.get("modelLaneTimeoutRate") or 0.0)
    return [
        {
            "name": "rime-sidecar-rag-timeout-rate",
            "passed": rag_timeout_rate <= max_rag_timeout_rate,
            "actual": rag_timeout_rate,
            "expectedAtMost": max_rag_timeout_rate,
            "timeoutCount": int(sidecar.get("ragLaneTimeoutCount") or 0),
            "calledCount": int(sidecar.get("ragLaneCalledCount") or 0),
        },
        {
            "name": "rime-sidecar-model-timeout-rate",
            "passed": model_timeout_rate <= max_model_timeout_rate,
            "actual": model_timeout_rate,
            "expectedAtMost": max_model_timeout_rate,
            "timeoutCount": int(sidecar.get("modelLaneTimeoutCount") or 0),
            "calledCount": int(sidecar.get("modelLaneCalledCount") or 0),
        },
    ]


def _old_input_echo_rate_checks(
    prefix: str,
    report: dict[str, object],
    *,
    max_old_input_echo_rate: float,
) -> list[dict[str, object]]:
    metrics = report.get("metrics") if isinstance(report.get("metrics"), dict) else {}
    product_metrics = report.get("productMetrics") if isinstance(report.get("productMetrics"), dict) else {}
    old_input_echo_rate = float(
        product_metrics.get("oldInputEchoRate")
        if product_metrics.get("oldInputEchoRate") is not None
        else metrics.get("oldInputEchoRate") or 0.0
    )
    return [
        {
            "name": f"{prefix}-old-input-echo-rate",
            "passed": old_input_echo_rate <= max_old_input_echo_rate,
            "actual": old_input_echo_rate,
            "expectedAtMost": max_old_input_echo_rate,
        }
    ]


def _model_ttfc_checks(
    report: dict[str, object],
    *,
    max_p95_first_candidate_ms: int,
    max_over_budget_rate: float,
) -> list[dict[str, object]]:
    winner_report = _ttfc_winner_model_report(report)
    summary = winner_report.get("summary") if isinstance(winner_report.get("summary"), dict) else {}
    sample_count = int(summary.get("sampleCount") or 0)
    over_budget_count = int(summary.get("overBudgetCount") or 0)
    over_budget_rate = _rate(over_budget_count, sample_count)
    p95_first_candidate_ms = int(summary.get("p95FirstCandidateMs") or 0)
    first_candidate_missing_count = int(summary.get("firstCandidateMissingCount") or 0)
    failure_count = int(summary.get("failureCount") or 0)
    winner = report.get("winner") if isinstance(report.get("winner"), dict) else {}
    winner_model = str(winner.get("model") or winner_report.get("model") or "")
    supported = bool(winner_report.get("supported"))
    has_first_candidate = bool(summary.get("hasFirstCandidate"))
    return [
        {
            "name": "model-ttfc-supported",
            "passed": bool(winner_model) and supported,
            "model": winner_model,
            "reason": winner.get("reason") or winner_report.get("reason"),
        },
        {
            "name": "model-ttfc-first-candidate",
            "passed": has_first_candidate and first_candidate_missing_count == 0 and failure_count == 0,
            "model": winner_model,
            "hasFirstCandidate": has_first_candidate,
            "firstCandidateMissingCount": first_candidate_missing_count,
            "failureCount": failure_count,
        },
        {
            "name": "model-ttfc-p95-first-candidate",
            "passed": has_first_candidate and p95_first_candidate_ms <= max_p95_first_candidate_ms,
            "model": winner_model,
            "actual": p95_first_candidate_ms,
            "expectedAtMost": max_p95_first_candidate_ms,
        },
        {
            "name": "model-ttfc-over-budget-rate",
            "passed": sample_count > 0 and over_budget_rate <= max_over_budget_rate,
            "model": winner_model,
            "actual": over_budget_rate,
            "expectedAtMost": max_over_budget_rate,
            "overBudgetCount": over_budget_count,
            "sampleCount": sample_count,
        },
    ]


def _ttfc_winner_model_report(report: dict[str, object]) -> dict[str, object]:
    winner = report.get("winner") if isinstance(report.get("winner"), dict) else {}
    winner_model = str(winner.get("model") or "")
    models = report.get("models") if isinstance(report.get("models"), list) else []
    for item in models:
        if isinstance(item, dict) and str(item.get("model") or "") == winner_model:
            return item
    return {}


def _rate(count: int, total: int) -> float:
    return float(count) / total if total > 0 else 0.0


def _predictor_capability_checks(
    predictor_status: dict[str, object],
    required_predictor_capabilities: tuple[str, ...],
) -> list[dict[str, object]]:
    capabilities = predictor_status.get("capabilities") if isinstance(predictor_status.get("capabilities"), dict) else {}
    checks = []
    for name in required_predictor_capabilities:
        checks.append(
            {
                "name": f"predictor-capability:{name}",
                "passed": capabilities.get(name) is True,
                "required": True,
                "actual": capabilities.get(name),
                "providerName": predictor_status.get("providerName"),
                "providerProfile": predictor_status.get("providerProfile"),
            }
        )
    return checks


def _acceptance_report_passed(report: dict[str, object]) -> bool:
    scenarios = report.get("scenario_results")
    if not isinstance(scenarios, list) or not scenarios:
        return False
    scenario_ok = all(
        isinstance(item, dict)
        and int(item.get("candidate_count") or 0) > 0
        and bool(item.get("has_evidence_preview"))
        and bool(item.get("has_actions"))
        for item in scenarios
    )
    action = report.get("action_result") if isinstance(report.get("action_result"), dict) else {}
    agent_hook = report.get("agent_hook") if isinstance(report.get("agent_hook"), dict) else {}
    trigger = report.get("trigger_policy") if isinstance(report.get("trigger_policy"), dict) else {}
    return (
        bool(report.get("local_first"))
        and not bool(report.get("cloud_default"))
        and not bool(report.get("fine_tuning"))
        and scenario_ok
        and bool(action.get("deleted_removed"))
        and bool(agent_hook.get("has_project_memory_block"))
        and trigger.get("single_char") is False
        and trigger.get("idle_semantic") is True
        and trigger.get("sensitive") is False
    )


def run_acceptance(adapter: InputMethodAdapter) -> dict[str, object]:
    scenario_results = []
    for scenario in SCENARIOS:
        suggestions = adapter.suggest(
            SuggestionRequest(
                current_input=scenario.current_input,
                recent_context=scenario.recent_context,
                project=scenario.project,
                top_k=5,
            )
        )
        scenario_results.append(
            {
                "scenario_id": scenario.scenario_id,
                "title": scenario.title,
                "candidate_count": len(suggestions),
                "top_candidate": suggestions[0].surface_text if suggestions else "",
                "has_evidence_preview": bool(suggestions and suggestions[0].evidence_preview),
                "has_actions": bool(suggestions and {"commit", "expand", "pin", "downrank", "delete"}.issubset(set(suggestions[0].actions))),
            }
        )

    action_scenario = get_scenario("technical-plan")
    request = SuggestionRequest(
        current_input=action_scenario.current_input,
        recent_context=action_scenario.recent_context,
        project=action_scenario.project,
        top_k=3,
    )
    before = adapter.suggest(request)
    if before:
        adapter.pin(before[-1], query=action_scenario.current_input)
        adapter.delete(before[0], query=action_scenario.current_input)
        after = adapter.suggest(request)
        deleted_removed = before[0].surface_text not in [item.surface_text for item in after]
    else:
        after = []
        deleted_removed = False
    injection = build_first_run_injection(adapter, project="wisdom-weasel-rag-ime", top_k=3)
    trigger_cases = {
        "single_char": should_refresh_rag(TypingState(current_input="项", idle_ms=500)).should_refresh,
        "idle_semantic": should_refresh_rag(TypingState(current_input="这个项目", idle_ms=300)).should_refresh,
        "sensitive": should_refresh_rag(
            TypingState(current_input="银行卡密码", idle_ms=800, field_is_sensitive=True)
        ).should_refresh,
    }
    return {
        "local_first": True,
        "cloud_default": False,
        "fine_tuning": False,
        "scenario_results": scenario_results,
        "action_result": {
            "before": [item.surface_text for item in before],
            "after": [item.surface_text for item in after],
            "deleted_removed": deleted_removed,
        },
        "agent_hook": {
            "has_project_memory_block": "PROJECT_MEMORY_BLOCK" in injection.block,
            "source_count": len(injection.source_event_ids),
        },
        "trigger_policy": trigger_cases,
    }


def _build_core(args):
    if args.core_mode == "fixture":
        return FixtureCoreClient()
    if args.core_mode == "json":
        if not args.core_command:
            raise SystemExit("--core-command is required when --core-mode json")
        return JsonCommandCoreClient(shlex.split(args.core_command))
    return LocalSqliteCoreClient(
        args.db_path,
        suggestion_cache_size=args.suggestion_cache_size,
        embedding_provider=_embedding_provider_from_args(args),
        vector_candidate_limit=args.embedding_vector_candidates,
        vector_weight=args.embedding_vector_weight,
    )


def _embedding_provider_from_args(args):
    env = dict(os.environ)
    env["RAG_IME_EMBEDDING_PROVIDER"] = args.embedding_provider
    return embedding_provider_from_env(env)


def _case_for_eval_repeat(case: CodexEvalCase, *, repeat_index: int, repeat_count: int) -> CodexEvalCase:
    if repeat_count <= 1:
        return case
    return replace(case, case_id=f"{case.case_id}#r{repeat_index}")


def _predictions_as_eval_suggestions(predictions: list[ModelPrediction]) -> list[InputSuggestion]:
    return [
        InputSuggestion(
            suggestion_id=f"prediction:{prediction.rank}",
            surface_text=prediction.text,
            suggestion_type="model_prediction",
            source_event_id=0,
            evidence_preview=prediction.provider_name,
            confidence=prediction.confidence,
            metadata={
                "provider_name": prediction.provider_name,
                "latency_ms": prediction.latency_ms,
                **dict(prediction.metadata),
            },
        )
        for prediction in predictions
    ]


def _parse_rerank_demo_candidates(raw_candidates: list[str], raw_json_candidates: list[str]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for raw in raw_candidates:
        parsed = _parse_rerank_demo_candidate(raw)
        if parsed:
            candidates.append(parsed)
    for raw in raw_json_candidates:
        try:
            item = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"invalid --candidate-json: {exc}") from exc
        if not isinstance(item, dict):
            raise SystemExit("--candidate-json must be a JSON object")
        text = compact_whitespace(str(item.get("text") or item.get("surface") or ""))
        if text:
            candidate = dict(item)
            candidate["text"] = text
            candidates.append(candidate)
    if not candidates:
        candidates = [
            {"source": "rime", "text": "输入法", "confidence": 0.8},
            {"source": "model", "text": "继续预测", "confidence": 0.74},
            {"source": "rag", "text": "输入法", "confidence": 0.6},
            {"source": "memory", "text": "长期记忆候选", "acceptedCount": 3},
        ]
    return candidates


def _parse_rerank_demo_candidate(raw: str) -> dict[str, Any] | None:
    value = compact_whitespace(str(raw))
    if not value:
        return None
    if value.startswith("{"):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"invalid --candidate JSON object: {exc}") from exc
        if not isinstance(parsed, dict):
            raise SystemExit("--candidate JSON form must be an object")
        return parsed
    if "|" in value:
        source, text = value.split("|", 1)
    elif ":" in value:
        source, text = value.split(":", 1)
    else:
        source, text = "unknown", value
    text = compact_whitespace(text)
    if not text:
        return None
    return {"source": compact_whitespace(source) or "unknown", "text": text}


def _source_counts(candidates: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in candidates:
        source = str(item.get("source") or "unknown")
        counts[source] = counts.get(source, 0) + 1
    return counts


def _stable_eval_hash(text: str) -> str:
    compact = compact_whitespace(text)
    if not compact:
        return ""
    return "sha256:" + hashlib.sha256(compact.encode("utf-8")).hexdigest()[:16]


def _rime_eval_payload(
    case: CodexEvalCase,
    *,
    request_seq: int,
    project: str,
    max_visible_candidates: int,
    max_side_candidates: int,
    latency_budget_ms: int,
    force_side_candidates: bool,
) -> dict[str, object]:
    return {
        "sessionId": f"eval-rime-sidecar:{case.case_id}",
        "requestSeq": request_seq,
        "rawInput": "",
        "preedit": "",
        "committedContext": case.recent_context,
        "project": project,
        "maxVisibleCandidates": max_visible_candidates,
        "maxSideCandidates": max_side_candidates,
        "latencyBudgetMs": max(30, int(latency_budget_ms)),
        "forceSideCandidates": force_side_candidates,
        "rimeContext": {
            "candidates": [
                {
                    "label": "1",
                    "text": case.query,
                    "comment": "eval-rime",
                }
            ],
            "highlightedIndex": 0,
            "page": 0,
            "isLastPage": True,
        },
    }


def _rime_display_side_candidates_as_eval_suggestions(display_candidates: object) -> list[InputSuggestion]:
    if not isinstance(display_candidates, list):
        return []
    suggestions: list[InputSuggestion] = []
    for index, item in enumerate(display_candidates, start=1):
        if not isinstance(item, dict):
            continue
        source_type = str(item.get("sourceType") or "")
        if source_type == "rime":
            continue
        surface_text = str(item.get("text") or item.get("insertText") or "")
        insert_text = str(item.get("insertText") or surface_text)
        if not surface_text and not insert_text:
            continue
        suggestion_type = "model_prediction" if source_type == "model" else "rag_candidate"
        source_event_id = item.get("sourceEventId")
        source_event_id = source_event_id if isinstance(source_event_id, int) else 0
        metadata = dict(item)
        metadata["insert_text"] = insert_text
        suggestions.append(
            InputSuggestion(
                suggestion_id=str(item.get("suggestionId") or f"rime-side:{index}"),
                surface_text=surface_text or insert_text,
                suggestion_type=suggestion_type,
                source_event_id=source_event_id,
                evidence_preview=str(item.get("evidencePreview") or item.get("comment") or source_type),
                confidence=_safe_float(metadata.get("confidence")),
                expanded_evidence=insert_text,
                metadata=metadata,
            )
        )
    return suggestions


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _prediction_provider_name(predictor) -> str:
    config = getattr(predictor, "config", None)
    provider_name = getattr(config, "provider_name", "")
    return provider_name if isinstance(provider_name, str) and provider_name else predictor.__class__.__name__


def _prediction_provider_profile(predictor) -> str:
    config = getattr(predictor, "config", None)
    profile = getattr(config, "profile", "")
    return profile if isinstance(profile, str) and profile else "none"


def _is_null_prediction_provider(predictor) -> bool:
    return predictor.__class__.__name__ == "NullPredictionProvider"


def run_ime_ttfc_benchmark(
    *,
    core,
    cases_file: str,
    inline_cases: list[str],
    recent_context: str,
    project: str,
    provider: str,
    base_url: str,
    models: str,
    profile: str,
    max_candidates: int,
    repeat: int,
    warmup_runs: int,
    latency_budget_ms: int,
    failure_cooldown_ms: int,
    include_cases: bool,
) -> dict[str, object]:
    args = argparse.Namespace(
        cases_file=cases_file,
        case=inline_cases,
        recent_context=recent_context,
        project=project,
        provider=provider,
        base_url=base_url,
        models=models,
        profile=profile,
        max_candidates=max_candidates,
        repeat=repeat,
        warmup_runs=warmup_runs,
        latency_budget_ms=latency_budget_ms,
        failure_cooldown_ms=failure_cooldown_ms,
        include_cases=include_cases,
    )
    cases = _load_ime_ttfc_benchmark_cases(args=args, core=core)
    model_ids = _parse_model_matrix_models(models)
    reports = []
    for model in model_ids:
        matrix_provider = _prediction_provider_for_model_matrix(args=args, model=model)
        model_report = benchmark_streaming_ttft_provider(
            matrix_provider,
            cases,
            max_candidates=max(1, min(10, max_candidates)),
            repeat=max(1, repeat),
            warmup_runs=max(0, warmup_runs),
            latency_budget_ms=max(1, latency_budget_ms),
        )
        model_report["model"] = model
        if not include_cases:
            model_report.pop("cases", None)
        reports.append(model_report)
    return {
        "schemaVersion": "rag-ime.ime-ttfc-benchmark.v1",
        "casesFile": str(Path(cases_file)) if cases_file else "",
        "project": project,
        "provider": str(provider),
        "baseUrl": base_url,
        "profile": profile,
        "repeat": {
            "requested": max(1, repeat),
            "baseCaseCount": len(cases),
            "effectiveCaseCount": len(cases) * max(1, repeat),
        },
        "warmupRuns": max(0, warmup_runs),
        "maxCandidates": max(1, min(10, max_candidates)),
        "latencyBudgetMs": max(1, latency_budget_ms),
        "failureCooldownMs": max(0, failure_cooldown_ms),
        "localRunners": _local_model_runner_status(),
        "models": reports,
        "winner": _ttfc_matrix_winner(reports),
    }


def _load_ime_ttfc_benchmark_cases(*, args, core) -> list[PredictionBenchmarkCase]:
    if args.cases_file:
        cases: list[PredictionBenchmarkCase] = []
        path = Path(args.cases_file)
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SystemExit(f"invalid JSONL in {path}:{line_number}: {exc}") from exc
            if not isinstance(obj, dict):
                continue
            current_input = compact_whitespace(
                str(obj.get("query") or obj.get("currentInput") or obj.get("current_input") or obj.get("input") or "")
            )
            if not current_input:
                continue
            project = compact_whitespace(str(obj.get("project") or "")) or args.project
            recent_context = compact_whitespace(str(obj.get("recentContext") or obj.get("recent_context") or ""))
            prediction_context = build_prediction_context(
                core,
                explicit_recent_context=recent_context,
                project=project,
            )
            case_id = compact_whitespace(str(obj.get("id") or obj.get("caseId") or f"case-{line_number}"))
            cases.append(
                PredictionBenchmarkCase(
                    current_input=current_input,
                    recent_context=prediction_context,
                    case_id=case_id,
                )
            )
        if not cases:
            raise SystemExit(f"no TTFC benchmark cases found in {path}")
        return cases

    prediction_context = build_prediction_context(
        core,
        explicit_recent_context=args.recent_context,
        project=args.project,
    )
    raw_cases = args.case or [
        "RAG 输入法",
        "Squirrel 候选",
        "PROJECT_MEMORY_BLOCK",
    ]
    cases = []
    for index, item in enumerate(raw_cases, start=1):
        current_input = compact_whitespace(str(item))
        if current_input:
            cases.append(
                PredictionBenchmarkCase(
                    current_input=current_input,
                    recent_context=prediction_context,
                    case_id=f"inline-{index}",
                )
            )
    if not cases:
        raise SystemExit("bench-ime-ttfc needs at least one non-empty --case or --cases-file entry")
    return cases


def _parse_model_matrix_models(raw: str) -> list[str]:
    models: list[str] = []
    seen: set[str] = set()
    for item in (raw or "").replace("\n", ",").split(","):
        model = item.strip()
        if not model or model in seen:
            continue
        seen.add(model)
        models.append(model)
    if not models:
        raise SystemExit("--models must contain at least one model id")
    return models


def _prediction_provider_for_model_matrix(*, args, model: str):
    env = dict(os.environ)
    env["RAG_IME_PREDICTOR_PROVIDER"] = str(args.provider)
    env["RAG_IME_PREDICTOR_BASE_URL"] = str(args.base_url)
    env["RAG_IME_PREDICTOR_MODEL"] = model
    env["RAG_IME_PREDICTOR_PROFILE"] = str(args.profile)
    env["RAG_IME_PREDICTOR_FAILURE_COOLDOWN_MS"] = str(max(0, int(args.failure_cooldown_ms)))
    return prediction_provider_from_env(env)


def _eval_prediction_provider_on_cases(
    *,
    provider,
    core,
    cases: list[CodexEvalCase],
    project: str,
    max_candidates: int,
    match: str,
    repeat: int,
    latency_budget_ms: int,
) -> dict[str, object]:
    results = []
    elapsed_ms_by_case: dict[str, int] = {}
    candidate_counts: list[int] = []
    product_samples: list[dict[str, Any]] = []
    over_budget_count = 0
    provider_name = _prediction_provider_name(provider)
    provider_configured = not _is_null_prediction_provider(provider)

    for repeat_index in range(1, repeat + 1):
        for case in cases:
            eval_case = _case_for_eval_repeat(case, repeat_index=repeat_index, repeat_count=repeat)
            prediction_context = build_prediction_context(
                core,
                explicit_recent_context=eval_case.recent_context,
                project=eval_case.project or project,
            )
            started = time.perf_counter()
            predictions = provider.predict(
                current_input=eval_case.query,
                recent_context=prediction_context,
                max_candidates=max_candidates,
            )
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            elapsed_ms_by_case[eval_case.case_id] = elapsed_ms
            if predictions:
                provider_name = predictions[0].provider_name
            candidate_counts.append(len(predictions))
            product_samples.append(
                _model_matrix_product_sample(
                    case=eval_case,
                    predictions=predictions,
                    elapsed_ms=elapsed_ms,
                    max_candidates=max_candidates,
                )
            )
            if elapsed_ms > latency_budget_ms:
                over_budget_count += 1
            results.append(
                evaluate_suggestions(
                    eval_case,
                    _predictions_as_eval_suggestions(predictions),
                    match=match,
                )
            )

    report = eval_report(results)
    report["productMetrics"] = _model_matrix_product_metrics(results=results, samples=product_samples)
    report["repeat"] = {
        "requested": repeat,
        "baseCaseCount": len(cases),
        "effectiveCaseCount": len(results),
    }
    _attach_eval_latency(report, elapsed_ms_by_case)
    status = prediction_provider_status(provider)
    report["prediction"] = {
        "providerName": provider_name,
        "providerProfile": _prediction_provider_profile(provider),
        "providerConfigured": provider_configured,
        "status": status,
        "maxCandidates": max_candidates,
        "latencyBudgetMs": latency_budget_ms,
        "overBudgetCount": over_budget_count,
        "allWithinBudget": over_budget_count == 0,
        "totalCandidates": sum(candidate_counts),
        "hasCandidates": any(count > 0 for count in candidate_counts),
    }
    return report


def _model_matrix_product_sample(
    *,
    case: CodexEvalCase,
    predictions: list[ModelPrediction],
    elapsed_ms: int,
    max_candidates: int,
) -> dict[str, Any]:
    surfaces = [compact_whitespace(item.text) for item in predictions if compact_whitespace(item.text)]
    first_candidate_ms = _first_candidate_ms(predictions, fallback_ms=elapsed_ms if surfaces else 0)
    return {
        "caseId": case.case_id,
        "query": case.query,
        "recentContext": case.recent_context,
        "surfaces": surfaces,
        "candidateCount": len(surfaces),
        "elapsedMs": elapsed_ms,
        "firstCandidateMs": first_candidate_ms,
        "threeCandidatesMs": elapsed_ms if len(surfaces) >= min(3, max_candidates) else 0,
        "chainReady": len(surfaces) >= min(2, max_candidates),
    }


def _model_matrix_product_metrics(
    *,
    results: list,
    samples: list[dict[str, Any]],
) -> dict[str, object]:
    total = len(results)
    surfaces_by_sample = [list(item.get("surfaces") or []) for item in samples]
    all_surfaces = [surface for surfaces in surfaces_by_sample for surface in surfaces]
    duplicate_count = sum(_duplicate_count(surfaces) for surfaces in surfaces_by_sample)
    echo_count = sum(
        1
        for sample in samples
        if any(
            _candidate_echoes_old_input(
                surface,
                query=str(sample.get("query") or ""),
                recent_context=str(sample.get("recentContext") or ""),
            )
            for surface in list(sample.get("surfaces") or [])
        )
    )
    first_candidate_ms_values = [int(item.get("firstCandidateMs") or 0) for item in samples if int(item.get("firstCandidateMs") or 0) > 0]
    three_candidate_ms_values = [int(item.get("threeCandidatesMs") or 0) for item in samples if int(item.get("threeCandidatesMs") or 0) > 0]
    top3_hits = sum(1 for item in results if item.first_match_rank is not None and int(item.first_match_rank) <= 3)
    forbidden_count = sum(1 for item in results if item.forbidden_matched_terms)
    return {
        "top1Acceptability": (sum(1 for item in results if item.top1_passed) / total) if total else 0.0,
        "top3Coverage": (top3_hits / total) if total else 0.0,
        "MRR": (sum(float(item.reciprocal_rank) for item in results) / total) if total else 0.0,
        "noiseRate": (forbidden_count / total) if total else 0.0,
        "forbiddenRate": (forbidden_count / total) if total else 0.0,
        "oldInputEchoRate": (echo_count / total) if total else 0.0,
        "duplicateRate": (duplicate_count / len(all_surfaces)) if all_surfaces else 0.0,
        "avgCandidateChars": (sum(len(surface) for surface in all_surfaces) / len(all_surfaces)) if all_surfaces else 0.0,
        "firstCandidateMs": _latency_percentiles(first_candidate_ms_values),
        "threeCandidatesMs": _latency_percentiles(three_candidate_ms_values),
        "chainSuccessRate": (
            sum(1 for item in samples if bool(item.get("chainReady"))) / len(samples)
        )
        if samples
        else 0.0,
    }


def _first_candidate_ms(predictions: list[ModelPrediction], *, fallback_ms: int) -> int:
    values = [
        _safe_int(item.metadata.get("first_candidate_ms"))
        for item in predictions
        if isinstance(item.metadata, dict) and _safe_int(item.metadata.get("first_candidate_ms")) > 0
    ]
    return min(values) if values else fallback_ms


def _candidate_echoes_old_input(surface: str, *, query: str, recent_context: str) -> bool:
    text = compact_whitespace(surface).casefold()
    query_norm = compact_whitespace(query).casefold()
    context_norm = compact_whitespace(recent_context).casefold()
    if not text:
        return False
    if query_norm and text == query_norm:
        return True
    return bool(context_norm and len(text) >= 4 and text in context_norm[-120:])


def _duplicate_count(surfaces: list[str]) -> int:
    seen: set[str] = set()
    duplicates = 0
    for surface in surfaces:
        key = compact_whitespace(surface).casefold()
        if not key:
            continue
        if key in seen:
            duplicates += 1
        else:
            seen.add(key)
    return duplicates


def _latency_percentiles(values: list[int]) -> dict[str, int]:
    sorted_values = sorted(values)
    count = len(sorted_values)
    return {
        "count": count,
        "p50Ms": sorted_values[count // 2] if sorted_values else 0,
        "p95Ms": sorted_values[min(count - 1, int(count * 0.95))] if sorted_values else 0,
    }


def _safe_int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _model_matrix_winner(reports: list[dict[str, object]]) -> dict[str, object]:
    eligible = [
        item
        for item in reports
        if isinstance(item.get("prediction"), dict) and bool(item["prediction"].get("hasCandidates"))
    ]
    if not eligible:
        return {
            "model": "",
            "reason": "no_model_returned_candidates",
        }

    def sort_key(item: dict[str, object]) -> tuple[float, float, float, float, float, int]:
        metrics = item.get("metrics") if isinstance(item.get("metrics"), dict) else {}
        product_metrics = item.get("productMetrics") if isinstance(item.get("productMetrics"), dict) else {}
        first_candidate_ms = product_metrics.get("firstCandidateMs") if isinstance(product_metrics.get("firstCandidateMs"), dict) else {}
        latency = item.get("latency") if isinstance(item.get("latency"), dict) else {}
        return (
            float(item.get("passRate") or 0.0),
            float(product_metrics.get("top3Coverage") or metrics.get("hitRate") or 0.0),
            float(product_metrics.get("top1Acceptability") or metrics.get("top1Accuracy") or 0.0),
            float(product_metrics.get("MRR") or metrics.get("meanReciprocalRank") or 0.0),
            -float(product_metrics.get("duplicateRate") or 0.0),
            -int(first_candidate_ms.get("p95Ms") or latency.get("p95Ms") or 0),
        )

    best = max(eligible, key=sort_key)
    metrics = best.get("metrics") if isinstance(best.get("metrics"), dict) else {}
    product_metrics = best.get("productMetrics") if isinstance(best.get("productMetrics"), dict) else {}
    latency = best.get("latency") if isinstance(best.get("latency"), dict) else {}
    return {
        "model": str(best.get("model") or ""),
        "passRate": float(best.get("passRate") or 0.0),
        "top1Accuracy": float(metrics.get("top1Accuracy") or 0.0),
        "meanReciprocalRank": float(metrics.get("meanReciprocalRank") or 0.0),
        "top1Acceptability": float(product_metrics.get("top1Acceptability") or metrics.get("top1Accuracy") or 0.0),
        "top3Coverage": float(product_metrics.get("top3Coverage") or metrics.get("hitRate") or 0.0),
        "MRR": float(product_metrics.get("MRR") or metrics.get("meanReciprocalRank") or 0.0),
        "duplicateRate": float(product_metrics.get("duplicateRate") or 0.0),
        "oldInputEchoRate": float(product_metrics.get("oldInputEchoRate") or 0.0),
        "p95Ms": int(latency.get("p95Ms") or 0),
        "reason": "highest_pass_rate_top3_top1_mrr_then_lowest_duplicate_and_latency",
    }


def _ttfc_matrix_winner(reports: list[dict[str, object]]) -> dict[str, object]:
    eligible = []
    for item in reports:
        summary = item.get("summary") if isinstance(item.get("summary"), dict) else {}
        if bool(item.get("supported")) and bool(summary.get("hasFirstCandidate")):
            eligible.append(item)
    if not eligible:
        return {
            "model": "",
            "reason": "no_supported_model_returned_first_candidate",
        }

    def sort_key(item: dict[str, object]) -> tuple[int, int, int, int, str]:
        summary = item.get("summary") if isinstance(item.get("summary"), dict) else {}
        return (
            int(summary.get("overBudgetCount") or 0),
            int(summary.get("p95FirstCandidateMs") or 0),
            int(summary.get("p50FirstCandidateMs") or 0),
            int(summary.get("failureCount") or 0),
            str(item.get("model") or ""),
        )

    best = min(eligible, key=sort_key)
    summary = best.get("summary") if isinstance(best.get("summary"), dict) else {}
    return {
        "model": str(best.get("model") or ""),
        "p50FirstCandidateMs": int(summary.get("p50FirstCandidateMs") or 0),
        "p95FirstCandidateMs": int(summary.get("p95FirstCandidateMs") or 0),
        "overBudgetCount": int(summary.get("overBudgetCount") or 0),
        "failureCount": int(summary.get("failureCount") or 0),
        "reason": "lowest_over_budget_then_p95_ttfc_then_p50_ttfc",
    }


def _comparison_summary(
    *,
    rag_results,
    model_results,
    rag_elapsed_ms_by_case: dict[str, int],
    model_elapsed_ms_by_case: dict[str, int],
) -> dict[str, object]:
    total = min(len(rag_results), len(model_results))
    rag_passed = sum(1 for item in rag_results if item.passed)
    model_passed = sum(1 for item in model_results if item.passed)
    rag_top1 = sum(1 for item in rag_results if item.top1_passed)
    model_top1 = sum(1 for item in model_results if item.top1_passed)
    rag_mrr = (sum(item.reciprocal_rank for item in rag_results) / len(rag_results)) if rag_results else 0.0
    model_mrr = (sum(item.reciprocal_rank for item in model_results) / len(model_results)) if model_results else 0.0

    both = 0
    rag_only = 0
    model_only = 0
    neither = 0
    cases = []
    for rag_item, model_item in zip(rag_results, model_results):
        if rag_item.passed and model_item.passed:
            both += 1
        elif rag_item.passed:
            rag_only += 1
        elif model_item.passed:
            model_only += 1
        else:
            neither += 1
        cases.append(
            {
                "caseId": rag_item.case_id,
                "query": rag_item.query,
                "ragPassed": rag_item.passed,
                "modelPassed": model_item.passed,
                "ragFirstMatchRank": rag_item.first_match_rank,
                "modelFirstMatchRank": model_item.first_match_rank,
                "ragTop1Passed": rag_item.top1_passed,
                "modelTop1Passed": model_item.top1_passed,
                "ragElapsedMs": rag_elapsed_ms_by_case.get(rag_item.case_id, 0),
                "modelElapsedMs": model_elapsed_ms_by_case.get(model_item.case_id, 0),
                "ragTopSurfaces": list(rag_item.top_surfaces),
                "modelTopSurfaces": list(model_item.top_surfaces),
            }
        )

    return {
        "total": total,
        "bothPassed": both,
        "ragOnlyPassed": rag_only,
        "modelOnlyPassed": model_only,
        "neitherPassed": neither,
        "winnerByPassRate": _metric_winner(rag_passed, model_passed),
        "winnerByTop1Accuracy": _metric_winner(rag_top1, model_top1),
        "winnerByMeanReciprocalRank": _metric_winner(rag_mrr, model_mrr),
        "ragPassRate": (rag_passed / len(rag_results)) if rag_results else 0.0,
        "modelPassRate": (model_passed / len(model_results)) if model_results else 0.0,
        "ragTop1Accuracy": (rag_top1 / len(rag_results)) if rag_results else 0.0,
        "modelTop1Accuracy": (model_top1 / len(model_results)) if model_results else 0.0,
        "ragMeanReciprocalRank": rag_mrr,
        "modelMeanReciprocalRank": model_mrr,
        "cases": cases,
    }


def _metric_winner(rag_value: float | int, model_value: float | int) -> str:
    if rag_value > model_value:
        return "rag"
    if model_value > rag_value:
        return "model"
    return "tie"


def _read_json_payload(payload_file: str) -> dict[str, object]:
    raw = sys.stdin.read() if payload_file == "-" else Path(payload_file).read_text(encoding="utf-8")
    if not raw.strip():
        return {}
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise SystemExit("JSON payload must be an object")
    return data


def _json_object_arg(raw: str, *, flag: str) -> dict[str, object]:
    value = compact_whitespace(raw)
    if not value:
        return {}
    try:
        data = json.loads(value)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{flag} must be valid JSON object: {exc}") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"{flag} must be a JSON object")
    return dict(data)


def _cleanup_provider_alias(provider: str) -> str:
    normalized = compact_whitespace(provider).lower()
    if normalized in {"", "local-rule"}:
        return "local-rule"
    if normalized in {"openai-compatible"}:
        return "openai-compatible"
    if normalized in {"model-api"}:
        return "model-api"
    if normalized in {"x1api", "x1top", "x2app"}:
        return "x1api"
    return normalized


def _cleanup_counts_payload(run_payload: dict[str, object]) -> dict[str, int]:
    counts = {"addStableMemory": 0, "addPhrase": 0, "tombstone": 0}
    for item in run_payload.get("diffs", []) if isinstance(run_payload.get("diffs"), list) else []:
        if not isinstance(item, dict):
            continue
        op = str(item.get("op") or "")
        if op == "add_stable_memory":
            counts["addStableMemory"] += 1
        elif op == "add_phrase":
            counts["addPhrase"] += 1
        elif op == "tombstone":
            counts["tombstone"] += 1
    return counts


def _cleanup_plan_from_cli_args(*, core: LocalSqliteCoreClient, run_id: str, run_path: str) -> object:
    if compact_whitespace(run_path):
        return load_cleanup_run_from_file(run_path)
    normalized_run_id = compact_whitespace(run_id)
    if not normalized_run_id:
        raise ValueError("run_id or run file is required")
    runs = core.list_memory_cleanup_runs(run_id=normalized_run_id, limit=1).get("items", [])
    if not runs:
        raise ValueError(f"cleanup run not found: {normalized_run_id}")
    payload = runs[0]
    if not isinstance(payload, dict):
        raise ValueError(f"cleanup run payload invalid: {normalized_run_id}")
    return cleanup_plan_from_payload(payload)


def _cleanup_preview_payload(*, core: LocalSqliteCoreClient, args) -> dict[str, object]:
    provider = _cleanup_provider_alias(str(args.provider))
    if provider == "local-rule":
        run_payload = core.preview_memory_cleanup_plan(
            project=args.project,
            since_days=max(1, int(args.since_days)),
            provider="local-rule",
            model="local-rule",
        )
        validation = inspect_cleanup_plan(cleanup_plan_from_payload(run_payload))
        return {
            "schemaVersion": "rag-ime.cleanup-preview.v1",
            "ok": True,
            "dryRun": True,
            "provider": "local-rule",
            "model": "local-rule",
            "reviewRequired": True,
            "sourceStats": {
                "strategy": "local-rule",
                "sinceDays": max(1, int(args.since_days)),
                "diffCounts": _cleanup_counts_payload(run_payload),
            },
            "validation": validation,
            "run": run_payload,
        }
    generator = compiler_generator_from_env(
        env_path=args.model_env_path or None,
        provider="" if provider == "openai-compatible" else provider,
        model=args.model,
    )
    bundle = build_memory_compile_bundle(
        core,
        project=args.project,
        recent_limit=max(1, int(args.recent_limit)),
        phrase_limit=max(1, int(args.phrase_limit)),
        memory_limit=max(1, int(args.memory_limit)),
        governance_limit=max(1, int(args.governance_limit)),
        allow_private_paths=bool(args.allow_private_paths),
    )
    if isinstance(bundle.get("source"), dict):
        bundle["source"]["sinceDays"] = max(1, int(args.since_days))
    report = generator.optimize_core(
        snapshot=bundle,
        project=args.project,
        max_memories=max(1, int(args.max_memories)),
        max_lexicon_phrases=max(1, int(args.max_lexicon_phrases)),
        max_hide_suggestions=max(0, int(args.max_hide_suggestions)),
    )
    plan = cleanup_plan_from_compiler_report(project=args.project, bundle=bundle, report=report)
    run_payload = cleanup_plan_to_payload(plan)
    validation = inspect_cleanup_plan(plan)
    return {
        "schemaVersion": "rag-ime.cleanup-preview.v1",
        "ok": True,
        "dryRun": True,
        "provider": report.provider,
        "model": report.model,
        "reviewRequired": True,
        "sourceStats": {
            "strategy": report.provider,
            "bundleTotals": dict(bundle.get("totals") or {}),
            "redactionStats": dict(bundle.get("redactionStats") or {}),
            "generatorMetadata": dict(report.metadata or {}),
            "diffCounts": _cleanup_counts_payload(run_payload),
        },
        "validation": validation,
        "run": run_payload,
        "rawPreview": memory_compile_report_payload(
            project=args.project,
            bundle=bundle,
            report=report,
            plan=plan,
        ).get("rawPreview", ""),
    }


def _attach_eval_latency(report: dict[str, object], elapsed_ms_by_case: dict[str, int]) -> None:
    cases = report.get("cases")
    if isinstance(cases, list):
        for item in cases:
            if not isinstance(item, dict):
                continue
            case_id = item.get("caseId")
            if isinstance(case_id, str):
                item["elapsedMs"] = elapsed_ms_by_case.get(case_id, 0)
    elapsed_values = list(elapsed_ms_by_case.values())
    sorted_values = sorted(elapsed_values)
    count = len(sorted_values)
    p50 = sorted_values[count // 2] if sorted_values else 0
    p95 = sorted_values[min(count - 1, int(count * 0.95))] if sorted_values else 0
    report["latency"] = {
        "caseCount": count,
        "totalMs": sum(elapsed_values),
        "avgMs": (sum(elapsed_values) / count) if count else 0.0,
        "p50Ms": p50,
        "p95Ms": p95,
        "maxMs": max(elapsed_values) if elapsed_values else 0,
    }


def _attach_vector_stats(report: dict[str, object], core) -> None:
    vector_stats = getattr(core, "vector_index_stats", None)
    if callable(vector_stats):
        report["vectorStats"] = vector_stats()


def _core_has_event_tag(core, tag: str) -> bool:
    checker = getattr(core, "has_event_tag", None)
    if not callable(checker):
        return False
    return bool(checker(tag))


def _parse_codex_role_filter(value: str) -> tuple[str, ...] | None:
    raw = compact_whitespace(value or "")
    if not raw or raw.lower() in {"any", "all", "*"}:
        return None
    roles = tuple(
        dict.fromkeys(
            item.strip().lower()
            for item in raw.replace(";", ",").split(",")
            if item.strip()
        )
    )
    return roles or None


def _local_model_runner_status() -> dict[str, object]:
    runners = {
        "ollama": shutil.which("ollama"),
        "llama-server": shutil.which("llama-server"),
        "lmstudio": shutil.which("lmstudio"),
        "mlx_lm.server": shutil.which("mlx_lm.server"),
    }
    return {
        "available": {name: path for name, path in runners.items() if path},
        "missing": [name for name, path in runners.items() if not path],
    }


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
