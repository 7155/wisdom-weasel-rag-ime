from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
from pathlib import Path
from typing import Sequence

from .adapter import InputMethodAdapter, SuggestionRequest
from .agent_hook import build_first_run_injection
from .core_client import CoreMemory, FixtureCoreClient, JsonCommandCoreClient, default_fixture_memories
from .history_context import build_prediction_context
from .local_sqlite_core import LocalSqliteCoreClient
from .models import InputEvent, MemoryAction
from .payloads import action_response_payload, suggestions_response_payload
from .predictor import prediction_provider_from_env
from .renderer import render_agent_injection, render_terminal_panel
from .rime_sidecar import build_rime_sidecar_response
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
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-db", help="Initialize the local SQLite/FTS5 database")

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

    debug_server = subparsers.add_parser("debug-server", help="Run the browser debug page and local API")
    debug_server.add_argument("--host", default=os.environ.get("RAG_IME_DEBUG_HOST", "127.0.0.1"))
    debug_server.add_argument("--port", type=int, default=int(os.environ.get("RAG_IME_DEBUG_PORT", "8765")))
    debug_server.add_argument("--project", default="wisdom-weasel-rag-ime")
    debug_server.add_argument("--static-dir", default=os.environ.get("RAG_IME_DEBUG_STATIC_DIR", "debug"))
    debug_server.add_argument("--no-seed", action="store_true", help="Do not seed demo memories when DB is empty")

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
    return LocalSqliteCoreClient(args.db_path)


def _read_json_payload(payload_file: str) -> dict[str, object]:
    raw = sys.stdin.read() if payload_file == "-" else Path(payload_file).read_text(encoding="utf-8")
    if not raw.strip():
        return {}
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise SystemExit("JSON payload must be an object")
    return data


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
