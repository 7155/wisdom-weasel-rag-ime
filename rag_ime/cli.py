from __future__ import annotations

import argparse
import json
import os
import shutil
import shlex
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Sequence

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
from .models import InputEvent, InputSuggestion, MemoryAction, ModelPrediction
from .payloads import action_response_payload, suggestions_response_payload
from .predictor import (
    PredictionBenchmarkCase,
    benchmark_prediction_provider,
    doctor_prediction_provider,
    prediction_provider_from_env,
    prediction_provider_status,
)
from .renderer import render_agent_injection, render_terminal_panel
from .rime_sidecar import build_rime_sidecar_response, record_rime_side_candidate_selection
from .scenarios import SCENARIOS, get_scenario
from .text_utils import now_ms
from .trigger_policy import TypingState, should_refresh_rag


DEFAULT_DB_PATH = Path(os.environ.get("RAG_IME_DB_PATH", ".rag-ime-data/rag-ime.sqlite"))


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

    rebuild_vector = subparsers.add_parser("rebuild-vector-index", help="Backfill optional local-core vector side index")
    rebuild_vector.add_argument("--project", default="")
    rebuild_vector.add_argument("--limit", type=int, default=0)

    seed = subparsers.add_parser("seed-demo", help="Seed local DB with deterministic demo memories")
    seed.add_argument("--reset", action="store_true", help="Reset local DB before seeding")

    commit = subparsers.add_parser("commit", help="Record one committed input event")
    commit.add_argument("text")
    commit.add_argument("--recent-context", default="")
    commit.add_argument("--project", default="wisdom-weasel-rag-ime")
    commit.add_argument("--preedit", default="")
    commit.add_argument("--source", default="manual_commit")
    commit.add_argument("--tag", action="append", default=[])
    commit.add_argument("--sensitive", action="store_true", help="Do not record this input")
    commit.add_argument("--recording-disabled", action="store_true", help="Skip recording for this commit")

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
    import_codex.add_argument("--sample-size", type=int, default=3)
    import_codex.add_argument("--dry-run", action="store_true", help="Parse and summarize without writing memory")
    import_codex.add_argument("--allow-duplicates", action="store_true", help="Import records even if their stable record tag already exists")

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
    eval_rime_sidecar.add_argument("--rime-cache-ttl-ms", type=int, default=int(os.environ.get("RAG_IME_RIME_CACHE_TTL_MS", "400")))
    eval_rime_sidecar.add_argument("--force-side-candidates", action="store_true")

    predict_benchmark = subparsers.add_parser("predict-benchmark", help="Measure local model prediction latency")
    predict_benchmark.add_argument("--case", action="append", default=[], help="Input case to predict. Can be repeated.")
    predict_benchmark.add_argument("--recent-context", default="")
    predict_benchmark.add_argument("--project", default="wisdom-weasel-rag-ime")
    predict_benchmark.add_argument("--max-candidates", type=int, default=3)
    predict_benchmark.add_argument("--latency-budget-ms", type=int, default=150)

    subparsers.add_parser("predictor-status", help="Show local model prediction configuration without calling the model")

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

    eval_model_matrix = subparsers.add_parser(
        "eval-model-matrix",
        help="Evaluate multiple local model ids on the same prediction cases",
    )
    eval_model_matrix.add_argument("--cases-file", required=True, help="JSONL cases with query and expectedTerms")
    eval_model_matrix.add_argument("--project", default="wisdom-weasel-rag-ime")
    eval_model_matrix.add_argument(
        "--base-url",
        default=os.environ.get("RAG_IME_PREDICTOR_BASE_URL", "http://127.0.0.1:11434/v1"),
        help="OpenAI-compatible base URL shared by all model ids. Defaults to Ollama /v1.",
    )
    eval_model_matrix.add_argument(
        "--models",
        default="qwen3.5:0.8b,qwen3.5:2b,qwen3.5:4b",
        help="Comma-separated model ids. Defaults to small Ollama qwen3.5 tags.",
    )
    eval_model_matrix.add_argument("--profile", default=os.environ.get("RAG_IME_PREDICTOR_PROFILE", "instant"))
    eval_model_matrix.add_argument("--provider", default=os.environ.get("RAG_IME_PREDICTOR_PROVIDER", "openai-compatible"))
    eval_model_matrix.add_argument("--max-candidates", type=int, default=3)
    eval_model_matrix.add_argument("--match", choices=("any", "all"), default="any")
    eval_model_matrix.add_argument("--repeat", type=int, default=1)
    eval_model_matrix.add_argument("--latency-budget-ms", type=int, default=150)
    eval_model_matrix.add_argument(
        "--failure-cooldown-ms",
        type=int,
        default=0,
        help="Prediction failure cooldown during matrix eval. Defaults to 0 so latency is measured per case.",
    )
    eval_model_matrix.add_argument(
        "--include-cases",
        action="store_true",
        help="Include full per-case evaluation details for every model.",
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

    subparsers.add_parser("acceptance", help="Run deterministic adapter acceptance scenarios")

    args = parser.parse_args(argv)
    core = _build_core(args)
    adapter = InputMethodAdapter(core, project="wisdom-weasel-rag-ime")
    predictor = prediction_provider_from_env()

    if args.command == "init-db":
        if not isinstance(core, LocalSqliteCoreClient):
            raise SystemExit("init-db requires --core-mode local")
        core.initialize()
        print(json.dumps({"db_path": str(core.db_path), "initialized": True}, ensure_ascii=False, indent=2))
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
        records = load_codex_history_records(
            Path(args.path),
            limit=max(0, args.limit),
            min_chars=max(1, args.min_chars),
            max_chars=max(16, args.max_chars),
            path_order=args.path_order,
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

    if args.command == "eval-codex-history":
        cases = load_eval_cases(Path(args.cases_file))
        repeat_count = max(1, args.repeat)
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
                        project=eval_case.project or args.project,
                        top_k=args.top_k,
                    )
                )
                elapsed_ms_by_case[eval_case.case_id] = int((time.perf_counter() - started) * 1000)
                results.append(evaluate_suggestions(eval_case, suggestions, match=args.match))
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
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    if args.command == "eval-rime-sidecar":
        from .debug_server import DebugImeService, DebugServerConfig

        cases = load_eval_cases(Path(args.cases_file))
        repeat_count = max(1, args.repeat)
        max_visible_candidates = max(1, min(10, args.max_visible_candidates))
        max_side_candidates = max(0, min(6, args.max_side_candidates))
        service = DebugImeService(
            DebugServerConfig(
                db_path=Path(args.db_path),
                project=args.project,
                core=core,
                predictor=predictor,
                seed_if_empty=False,
                rime_cache_ttl_ms=max(0, args.rime_cache_ttl_ms),
            )
        )
        results = []
        elapsed_ms_by_case: dict[str, int] = {}
        side_counts: list[int] = []
        model_counts: list[int] = []
        rag_counts: list[int] = []
        trigger_refresh_count = 0
        for repeat_index in range(1, repeat_count + 1):
            for case_index, case in enumerate(cases, start=1):
                eval_case = _case_for_eval_repeat(case, repeat_index=repeat_index, repeat_count=repeat_count)
                payload = _rime_eval_payload(
                    eval_case,
                    request_seq=(repeat_index - 1) * len(cases) + case_index,
                    project=eval_case.project or args.project,
                    max_visible_candidates=max_visible_candidates,
                    max_side_candidates=max_side_candidates,
                    force_side_candidates=bool(args.force_side_candidates),
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
                results.append(evaluate_suggestions(eval_case, side_suggestions, match=args.match))
        report = eval_report(results)
        report["schemaVersion"] = "rag-ime.rime-sidecar-eval.v1"
        report["casesFile"] = str(Path(args.cases_file))
        report["project"] = args.project
        report["match"] = args.match
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
            "forceSideCandidates": bool(args.force_side_candidates),
            "triggerRefreshCount": trigger_refresh_count,
            "totalSideCandidates": sum(side_counts),
            "totalModelCandidates": sum(model_counts),
            "totalRagCandidates": sum(rag_counts),
            "hasSideCandidates": any(count > 0 for count in side_counts),
            "rimeSuggestCache": health.get("rimeSuggestCache"),
            "suggestionCache": health.get("suggestionCache"),
            "predictor": health.get("predictor"),
        }
        _attach_vector_stats(report, core)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

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
        print(json.dumps(prediction_provider_status(predictor), ensure_ascii=False, indent=2))
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

    if args.command == "eval-model-matrix":
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
    adapter.pin(before[-1], query=action_scenario.current_input)
    adapter.delete(before[0], query=action_scenario.current_input)
    after = adapter.suggest(request)
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
            "deleted_removed": before[0].surface_text not in [item.surface_text for item in after],
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


def _rime_eval_payload(
    case: CodexEvalCase,
    *,
    request_seq: int,
    project: str,
    max_visible_candidates: int,
    max_side_candidates: int,
    force_side_candidates: bool,
) -> dict[str, object]:
    return {
        "sessionId": f"eval-rime-sidecar:{case.case_id}",
        "requestSeq": request_seq,
        "rawInput": case.query,
        "preedit": case.query,
        "committedContext": case.recent_context,
        "project": project,
        "maxVisibleCandidates": max_visible_candidates,
        "maxSideCandidates": max_side_candidates,
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

    def sort_key(item: dict[str, object]) -> tuple[float, float, float, int]:
        metrics = item.get("metrics") if isinstance(item.get("metrics"), dict) else {}
        latency = item.get("latency") if isinstance(item.get("latency"), dict) else {}
        return (
            float(item.get("passRate") or 0.0),
            float(metrics.get("top1Accuracy") or 0.0),
            float(metrics.get("meanReciprocalRank") or 0.0),
            -int(latency.get("p95Ms") or 0),
        )

    best = max(eligible, key=sort_key)
    metrics = best.get("metrics") if isinstance(best.get("metrics"), dict) else {}
    latency = best.get("latency") if isinstance(best.get("latency"), dict) else {}
    return {
        "model": str(best.get("model") or ""),
        "passRate": float(best.get("passRate") or 0.0),
        "top1Accuracy": float(metrics.get("top1Accuracy") or 0.0),
        "meanReciprocalRank": float(metrics.get("meanReciprocalRank") or 0.0),
        "p95Ms": int(latency.get("p95Ms") or 0),
        "reason": "highest_pass_rate_top1_mrr_then_lowest_p95",
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
