from __future__ import annotations

import argparse
import copy
import hashlib
import inspect
import json
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any, Sequence

from .adapter import InputMethodAdapter
from .anti_echo import candidate_echoes_text, candidate_has_self_repetition
from .embeddings import embedding_provider_from_env
from .hybrid_rag_models import HybridRagQuery
from .hybrid_rag_retriever import retrieve_hybrid_rag_candidates
from .knowledge_workbench import KnowledgeWorkbenchRequest, build_knowledge_workbench_messages
from .local_sqlite_core import LocalSqliteCoreClient
from .memory_book_compiler import (
    apply_memory_book_plan,
    inspect_memory_book_plan,
    memory_book_plan_from_compile_output,
    rollback_memory_book_run,
)
from .memory_tag_graph import recompute_tag_graph
from .models import ModelPrediction, RimeContextSnapshot
from .prediction_first import merge_prediction_first_candidates
from .prediction_trigger import PredictionTrigger
from .retrieval_docs import rebuild_retrieval_docs
from .rime_rank_export import preview_rime_rank_export, record_rime_rank_feedback
from .text_utils import compact_whitespace


SCHEMA_VERSION = "rag-ime.ime-first-demo-report.v1"
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FIXTURE_PATH = REPO_ROOT / "dataset" / "ime_first_demo_pack.v1.json"
DEFAULT_DEMO_DB_PATH = REPO_ROOT / ".rag-ime-demo" / "ime-first-demo.sqlite"
DEMO_RUN_ID = "memory_book_ime_first_demo_v1"
LIVE_CONFIRMATION = "SEED_PUBLIC_IME_DEMO_PACK"


def load_demo_fixture(path: str | Path = DEFAULT_FIXTURE_PATH) -> dict[str, Any]:
    fixture_path = Path(path)
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("demo fixture must contain a JSON object")
    if payload.get("schemaVersion") != "rag-ime.ime-first-demo-pack.v1":
        raise ValueError("unsupported demo fixture schemaVersion")
    for key in ("fixtureId", "fixtureTag", "project"):
        if not compact_whitespace(str(payload.get(key) or "")):
            raise ValueError(f"demo fixture {key} must not be empty")
    events = payload.get("events")
    frames = payload.get("tabFrames")
    if not isinstance(events, list) or not events:
        raise ValueError("demo fixture events must not be empty")
    if not isinstance(frames, list) or len(frames) < 2:
        raise ValueError("demo fixture must contain a multi-step Tab chain")
    return payload


def assert_isolated_demo_db_path(
    path: str | Path,
    *,
    live: bool = False,
    confirmation: str = "",
) -> Path:
    db_path = Path(path).expanduser()
    real_data_path = any(part.lower() == ".rag-ime-data" for part in db_path.parts)
    if real_data_path and not live:
        raise ValueError("refusing to use the real .rag-ime-data directory for demo data")
    if live and confirmation != LIVE_CONFIRMATION:
        raise ValueError(f"live demo mode requires --confirm {LIVE_CONFIRMATION}")
    return db_path


def reset_demo_database(
    path: str | Path = DEFAULT_DEMO_DB_PATH,
    *,
    fixture_path: str | Path = DEFAULT_FIXTURE_PATH,
    live: bool = False,
    confirmation: str = "",
) -> dict[str, object]:
    db_path = assert_isolated_demo_db_path(path, live=live, confirmation=confirmation)
    fixture = load_demo_fixture(fixture_path)
    if not db_path.exists():
        return {
            "schemaVersion": SCHEMA_VERSION,
            "action": "reset",
            "ok": True,
            "dbPath": str(db_path),
            "mode": "live-opt-in" if live else "isolated",
            "removed": {},
        }

    core = LocalSqliteCoreClient(db_path)
    core.initialize()
    removed: dict[str, int] = {}
    with _connect(db_path) as conn:
        run_exists = conn.execute(
            "SELECT 1 FROM memory_cleanup_runs WHERE run_id = ?",
            (DEMO_RUN_ID,),
        ).fetchone()
        if run_exists is not None:
            rollback_memory_book_run(conn, run_id=DEMO_RUN_ID)

        demo_rows = conn.execute(
            """
            SELECT id, committed_text, project, app
            FROM input_events
            WHERE source = 'ime_demo_fixture'
              AND provider_name = 'demo-fixture'
              AND project = ?
              AND tags_json LIKE ?
            """,
            (str(fixture["project"]), f"%{fixture['fixtureTag']}%"),
        ).fetchall()
        event_ids = [int(row["id"]) for row in demo_rows]
        memory_item_ids: list[int] = []
        if event_ids:
            placeholders = ",".join("?" for _ in event_ids)
            memory_item_ids = [
                int(row["id"])
                for row in conn.execute(
                    f"SELECT id FROM memory_items WHERE source_event_id IN ({placeholders})",
                    event_ids,
                ).fetchall()
            ]
            if memory_item_ids:
                item_placeholders = ",".join("?" for _ in memory_item_ids)
                conn.execute(f"DELETE FROM memory_items_fts WHERE rowid IN ({item_placeholders})", memory_item_ids)
                conn.execute(f"DELETE FROM memory_items WHERE id IN ({item_placeholders})", memory_item_ids)
            conn.execute(f"DELETE FROM memory_fts WHERE rowid IN ({placeholders})", event_ids)
            conn.execute(f"DELETE FROM input_events WHERE id IN ({placeholders})", event_ids)
        removed["inputEvents"] = len(event_ids)
        removed["memoryItems"] = len(memory_item_ids)

        rime_cursor = conn.execute(
            """
            DELETE FROM rime_rank_feedback
            WHERE project = ?
              AND context_hash LIKE 'demo:yon:%'
              AND metadata_json LIKE ?
            """,
            (str(fixture["project"]), f"%{fixture['fixtureId']}%"),
        )
        removed["rimeRankFeedback"] = max(0, int(rime_cursor.rowcount))
        run_cursor = conn.execute("DELETE FROM memory_cleanup_runs WHERE run_id = ?", (DEMO_RUN_ID,))
        removed["memoryBookRuns"] = max(0, int(run_cursor.rowcount))
        _refresh_demo_phrase_stats(conn, demo_rows)
        tag_graph = recompute_tag_graph(conn, project="")
        _remove_orphan_demo_tags(conn, fixture=fixture)
        retrieval = rebuild_retrieval_docs(conn, project="")
    return {
        "schemaVersion": SCHEMA_VERSION,
        "action": "reset",
        "ok": True,
        "dbPath": str(db_path),
        "mode": "live-opt-in" if live else "isolated",
        "removed": removed,
        "tagGraph": tag_graph,
        "retrievalDocs": retrieval,
    }


def seed_demo_database(
    path: str | Path = DEFAULT_DEMO_DB_PATH,
    *,
    fixture_path: str | Path = DEFAULT_FIXTURE_PATH,
    reset: bool = False,
    live: bool = False,
    confirmation: str = "",
) -> dict[str, object]:
    db_path = assert_isolated_demo_db_path(path, live=live, confirmation=confirmation)
    fixture = load_demo_fixture(fixture_path)
    if reset:
        reset_demo_database(
            db_path,
            fixture_path=fixture_path,
            live=live,
            confirmation=confirmation,
        )

    core = LocalSqliteCoreClient(db_path)
    core.initialize()
    total_events = _table_count(db_path, "input_events")
    demo_events = _demo_event_count(
        db_path,
        project=str(fixture["project"]),
        fixture_tag=str(fixture["fixtureTag"]),
    )
    if demo_events > 0 or (total_events > 0 and not live):
        raise ValueError("demo rows already exist or isolated DB is not empty; run reset or seed --reset")
    adapter = InputMethodAdapter(core, project=str(fixture["project"]))
    event_ids: dict[str, int] = {}
    for raw in fixture["events"]:
        event = _object(raw, "event")
        event_ref = compact_whitespace(str(event.get("id") or ""))
        if not event_ref or event_ref in event_ids:
            raise ValueError("demo event ids must be non-empty and unique")
        stored = adapter.commit_text(
            str(event.get("text") or ""),
            recent_context=str(event.get("recentContext") or ""),
            preedit=str(event.get("preedit") or ""),
            schema_id=str(event.get("schemaId") or "luna_pinyin"),
            app=str(event.get("app") or "demo.textedit"),
            project=str(fixture["project"]),
            source=str(event.get("source") or "ime_demo_fixture"),
            provider_name=str(event.get("providerName") or "demo-fixture"),
            tags=tuple(
                dict.fromkeys(
                    [
                        *(str(value) for value in event.get("tags", []) if str(value).strip()),
                        str(fixture["fixtureTag"]),
                    ]
                )
            ),
            context_group_id=str(event.get("contextGroupId") or "demo:input-method"),
            context_group_level=str(event.get("contextGroupLevel") or "document"),
            privacy_disposition="allowed",
        )
        if not stored.startswith("event:"):
            raise RuntimeError(f"demo event was not stored: {event_ref} -> {stored}")
        event_ids[event_ref] = int(stored.split(":", 1)[1])

    for index, raw in enumerate(fixture.get("rimeFeedback", []), start=1):
        feedback = _object(raw, "rime feedback")
        kwargs: dict[str, object] = {
            "preedit": str(feedback.get("preedit") or ""),
            "accepted_text": str(feedback.get("acceptedText") or ""),
            "rejected_text": str(feedback.get("rejectedText") or ""),
            "action": str(feedback.get("action") or "accepted"),
            "project": str(fixture["project"]),
            "app": "demo.textedit",
            "candidate_rank": int(feedback.get("candidateRank") or 1),
            "context_hash": str(feedback.get("contextHash") or f"demo:rime:{index}"),
            "metadata": {
                "candidateSource": "rime",
                "fixtureId": fixture["fixtureId"],
                "privacyDisposition": "allowed",
            },
        }
        if "privacy_disposition" in inspect.signature(record_rime_rank_feedback).parameters:
            kwargs["privacy_disposition"] = "allowed"
        record_rime_rank_feedback(db_path, **kwargs)

    compile_output = _resolved_memory_book(fixture, event_ids=event_ids)
    plan = memory_book_plan_from_compile_output(
        compile_output,
        project=str(fixture["project"]),
        provider="deterministic-demo-fixture",
        model="none",
    )
    plan["runId"] = DEMO_RUN_ID
    validation = inspect_memory_book_plan(plan)
    if not validation["ok"]:
        raise ValueError(f"demo Memory Book failed validation: {validation['errors']}")
    with _connect(db_path) as conn:
        apply_memory_book_plan(conn, plan)
        retrieval_report = rebuild_retrieval_docs(conn, project=str(fixture["project"]))

    counts = _demo_counts(db_path)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "action": "seed",
        "ok": True,
        "fixtureId": fixture["fixtureId"],
        "fixtureTag": fixture["fixtureTag"],
        "fixtureSha256": _fixture_sha256(fixture_path),
        "dbPath": str(db_path),
        "mode": "live-opt-in" if live else "isolated",
        "project": fixture["project"],
        "sceneOrder": list(fixture.get("sceneOrder") or []),
        "eventIds": event_ids,
        "counts": counts,
        "memoryBookValidation": validation,
        "retrievalDocs": retrieval_report,
    }


def verify_demo_database(
    path: str | Path = DEFAULT_DEMO_DB_PATH,
    *,
    fixture_path: str | Path = DEFAULT_FIXTURE_PATH,
    live: bool = False,
    confirmation: str = "",
) -> dict[str, object]:
    db_path = assert_isolated_demo_db_path(path, live=live, confirmation=confirmation)
    fixture = load_demo_fixture(fixture_path)
    if not db_path.exists():
        raise FileNotFoundError(f"demo database not found: {db_path}; run seed --reset first")

    ordinary_pinyin = _verify_ordinary_pinyin(db_path, fixture=fixture)
    tab_chain = _verify_tab_chain(fixture)
    rag_memory = _verify_rag_memory(db_path, fixture=fixture)
    workbench = _verify_knowledge_workbench(fixture, rag_memory=rag_memory)
    no_store = _verify_no_store(db_path, fixture=fixture)
    checks = {
        "ordinaryPinyin": ordinary_pinyin,
        "continuousTab": tab_chain,
        "ragMemory": rag_memory,
        "knowledgeWorkbench": workbench,
        "noStoreBaseline": no_store,
    }
    ok = all(bool(item.get("ok")) for item in checks.values())
    return {
        "schemaVersion": SCHEMA_VERSION,
        "action": "verify",
        "ok": ok,
        "fixtureId": fixture["fixtureId"],
        "fixtureTag": fixture["fixtureTag"],
        "fixtureSha256": _fixture_sha256(fixture_path),
        "dbPath": str(db_path),
        "mode": "live-opt-in" if live else "isolated",
        "project": fixture["project"],
        "sceneOrder": list(fixture.get("sceneOrder") or []),
        "counts": _demo_counts(db_path),
        "checks": checks,
    }


def _verify_ordinary_pinyin(db_path: Path, *, fixture: dict[str, Any]) -> dict[str, object]:
    preview = preview_rime_rank_export(db_path, project=str(fixture["project"]))
    matching = [
        item
        for item in preview.get("entries", [])
        if isinstance(item, dict) and item.get("text") == "用" and item.get("pinyin") == "yong"
    ]
    return {
        "ok": len(matching) == 1,
        "inputs": ["yon", "yo n", "yong"],
        "expected": "用",
        "canonicalPinyin": "yong",
        "dictionaryEntry": matching[0] if matching else None,
    }


def _verify_tab_chain(fixture: dict[str, Any]) -> dict[str, object]:
    frames = [_object(value, "Tab frame") for value in fixture["tabFrames"]]
    rendered_frames: list[dict[str, object]] = []
    chain_ok = True
    clock = {"now": 0}
    trigger = PredictionTrigger(clock_ms=lambda: clock["now"])
    for index, frame in enumerate(frames):
        context = str(frame.get("context") or "")
        candidates = [str(value) for value in frame.get("candidates", [])]
        predictions = [
            ModelPrediction(
                text=text,
                rank=rank,
                provider_name="deterministic-demo",
                latency_ms=1,
                confidence=round(0.96 - rank * 0.05, 2),
                metadata={"fixtureFrame": frame.get("id"), "bareCompletion": True},
            )
            for rank, text in enumerate(candidates, start=1)
        ]
        merged = merge_prediction_first_candidates(
            snapshot=RimeContextSnapshot(
                session_id="ime-first-demo",
                request_seq=index + 1,
                committed_context=context,
                project=str(fixture["project"]),
                app="demo.textedit",
                max_visible_candidates=3,
                max_side_candidates=3,
            ),
            model_predictions=predictions,
            suggestions=[],
        )
        display = list(merged.display_candidates)
        frame_ok = (
            len(candidates) == 3
            and [item.insert_text for item in display] == candidates
            and all(item.source_type == "model" and item.selection_action == "commit_side_candidate" for item in display)
            and all(not candidate_echoes_text(text, context, reject_single_occurrence=True) for text in candidates)
            and all(not candidate_has_self_repetition(text) for text in candidates)
        )
        next_context = context + (candidates[0] if candidates else "")
        if index + 1 < len(frames):
            frame_ok = frame_ok and next_context == str(frames[index + 1].get("context") or "")
        clock["now"] = (index + 1) * 100
        trigger.record_commit(
            group_id="demo:tab-chain",
            text=candidates[0] if candidates else "",
            context_hash=f"demo:tab:{index + 1}",
            reliable=True,
            accepted_candidate=True,
            now=clock["now"],
        )
        continuation = trigger.poll("demo:tab-chain", now=clock["now"])
        frame_ok = frame_ok and continuation.should_call_predictor
        if continuation.should_call_predictor:
            trigger.complete(continuation, result_count=3, now=clock["now"])
        chain_ok = chain_ok and frame_ok
        rendered_frames.append(
            {
                "id": frame.get("id"),
                "context": context,
                "candidates": [item.insert_text for item in display],
                "topCandidateNextContext": next_context,
                "tabAction": "accept_top_prediction",
                "continuationTriggered": continuation.should_call_predictor,
                "ok": frame_ok,
            }
        )

    quiet_clock = {"now": 0}
    quiet_trigger = PredictionTrigger(clock_ms=lambda: quiet_clock["now"])
    quiet_trigger.record_commit(
        group_id="demo:quiet",
        text="短",
        context_hash="demo:quiet:1",
        reliable=True,
        now=0,
    )
    quiet_clock["now"] = 500
    quiet = quiet_trigger.poll("demo:quiet", now=500)
    quiet_ok = not quiet.should_call_predictor and quiet.reason == "minimum_delta_not_reached"
    return {
        "ok": chain_ok and quiet_ok,
        "frames": rendered_frames,
        "notEveryCommit": {
            "ok": quiet_ok,
            "shortCommit": "短",
            "decision": quiet.action,
            "reason": quiet.reason,
        },
    }


def _verify_rag_memory(db_path: Path, *, fixture: dict[str, Any]) -> dict[str, object]:
    query_config = _object(fixture["ragQuery"], "RAG query")
    embedding_provider = embedding_provider_from_env()
    with _connect(db_path) as conn:
        payload = retrieve_hybrid_rag_candidates(
            conn,
            HybridRagQuery(
                query_text=str(query_config["text"]),
                project=str(fixture["project"]),
                app="demo.textedit",
                top_k=int(query_config.get("topK") or 5),
                latency_budget_ms=1000,
            ),
            embedding_provider=embedding_provider,
        )
    candidates = [dict(item) for item in payload.get("candidates", []) if isinstance(item, dict)]
    traceable = [
        item
        for item in candidates
        if item.get("evidence_event_ids")
        and (item.get("book_ids") or item.get("atom_ids") or item.get("memory_ids"))
        and item.get("evidence_preview")
    ]
    expected_source_ids = [str(value) for value in query_config.get("expectedSourceIds", [])]
    visible_source_ids = sorted(
        {
            str(value)
            for item in candidates
            for key in ("book_ids", "atom_ids", "memory_ids")
            for value in item.get(key, [])
            if str(value)
        }
    )
    expected_sources_visible = all(value in visible_source_ids for value in expected_source_ids)
    return {
        "ok": bool(candidates and traceable and expected_sources_visible),
        "query": payload.get("query"),
        "lanes": payload.get("lanes"),
        "embeddingProvider": embedding_provider.fingerprint,
        "vectorIndexDocuments": int(payload.get("vectorIndexDocuments") or 0),
        "elapsedMs": int(payload.get("elapsedMs") or 0),
        "overBudget": bool(payload.get("overBudget")),
        "candidateCount": len(candidates),
        "candidates": candidates,
        "traceableCandidateCount": len(traceable),
        "expectedSourceIds": expected_source_ids,
        "visibleSourceIds": visible_source_ids,
        "expectedSourcesVisible": expected_sources_visible,
    }


def _verify_knowledge_workbench(fixture: dict[str, Any], *, rag_memory: dict[str, object]) -> dict[str, object]:
    config = _object(fixture["knowledgeWorkbench"], "knowledge workbench")
    evidence: list[dict[str, object]] = []
    for index, raw in enumerate(rag_memory.get("candidates", []), start=1):
        item = dict(raw) if isinstance(raw, dict) else {}
        source_ids = [
            *list(item.get("book_ids") or []),
            *list(item.get("atom_ids") or []),
            *list(item.get("memory_ids") or []),
        ]
        if not source_ids:
            continue
        evidence.append(
            {
                "sourceId": str(source_ids[0]),
                "sourceLane": str(item.get("source_lane") or "local"),
                "title": str(item.get("text") or f"本地来源 {index}"),
                "text": str(item.get("evidence_preview") or ""),
                "tags": list(item.get("tags") or []),
                "score": float(item.get("score") or 0.0),
            }
        )
    request = KnowledgeWorkbenchRequest(
        question=str(config["question"]),
        mode=str(config["mode"]),
        context=str(config["context"]),
        project=str(fixture["project"]),
        app="com.rag-ime.control.demo",
        include_notion=False,
        max_chars=int(config.get("maxChars") or 2400),
    )
    messages = build_knowledge_workbench_messages(request, evidence=tuple(evidence))
    injected = json.loads(messages[1]["content"])
    local_evidence = list(injected.get("localEvidence") or [])
    ok = (
        request.mode == "long_form"
        and injected.get("context") == request.context
        and bool(local_evidence)
        and all(str(item.get("id") or "") for item in local_evidence)
        and "高质量长文" in messages[0]["content"]
    )
    return {
        "ok": ok,
        "mode": request.mode,
        "question": request.question,
        "contextChars": len(request.context),
        "contextInjected": injected.get("context") == request.context,
        "localEvidenceCount": len(local_evidence),
        "sourceIds": [str(item.get("id") or "") for item in local_evidence],
        "networkCalled": False,
    }


def _verify_no_store(db_path: Path, *, fixture: dict[str, Any]) -> dict[str, object]:
    before = _table_count(db_path, "input_events")
    adapter = InputMethodAdapter(LocalSqliteCoreClient(db_path), project=str(fixture["project"]))
    unknown = adapter.commit_text(
        "demo account field placeholder",
        privacy_disposition="unknown",
        app="demo.account-form",
    )
    sensitive = adapter.commit_text(
        "demo credential field placeholder",
        privacy_disposition="sensitive",
        app="demo.account-form",
    )
    after = _table_count(db_path, "input_events")
    return {
        "ok": before == after and unknown == "skipped:privacy_unknown" and sensitive == "skipped:privacy_sensitive",
        "rowCountBefore": before,
        "rowCountAfter": after,
        "unknownResult": unknown,
        "sensitiveResult": sensitive,
    }


def _resolved_memory_book(fixture: dict[str, Any], *, event_ids: dict[str, int]) -> dict[str, object]:
    compile_output = copy.deepcopy(_object(fixture["memoryBook"], "Memory Book"))
    for section in ("dailyBooks", "memoryAtoms", "phraseCandidates"):
        for raw in compile_output.get(section, []):
            item = _object(raw, section)
            item["sourceEventIds"] = _resolve_refs(item.pop("sourceRefs", []), event_ids=event_ids)
    for raw in compile_output.get("tagEdges", []):
        item = _object(raw, "tag edge")
        item["evidenceEventIds"] = _resolve_refs(item.pop("evidenceRefs", []), event_ids=event_ids)
    return compile_output


def _resolve_refs(values: object, *, event_ids: dict[str, int]) -> list[int]:
    if not isinstance(values, list) or not values:
        raise ValueError("Memory Book fixture source refs must not be empty")
    result: list[int] = []
    for raw in values:
        ref = str(raw)
        if ref not in event_ids:
            raise ValueError(f"unknown demo source ref: {ref}")
        event_id = event_ids[ref]
        if event_id not in result:
            result.append(event_id)
    return result


def _demo_counts(db_path: Path) -> dict[str, int]:
    tables = (
        "input_events",
        "memory_books",
        "memory_atoms",
        "memory_retrieval_docs",
        "rime_rank_feedback",
    )
    return {table: _table_count(db_path, table) for table in tables}


def _demo_event_count(db_path: Path, *, project: str, fixture_tag: str) -> int:
    with closing(sqlite3.connect(db_path)) as conn:
        return int(
            conn.execute(
                """
                SELECT COUNT(*) FROM input_events
                WHERE source = 'ime_demo_fixture'
                  AND provider_name = 'demo-fixture'
                  AND project = ?
                  AND tags_json LIKE ?
                """,
                (project, f"%{fixture_tag}%"),
            ).fetchone()[0]
        )


def _refresh_demo_phrase_stats(conn: sqlite3.Connection, rows: list[sqlite3.Row]) -> None:
    keys = {(str(row["committed_text"]), str(row["project"]), str(row["app"])) for row in rows}
    for text, project, app in keys:
        conn.execute("DELETE FROM phrase_stats WHERE committed_text = ?", (text,))
        conn.execute(
            """
            INSERT INTO phrase_stats(committed_text, input_frequency, first_seen_ms, last_seen_ms)
            SELECT e.committed_text, COUNT(*), MIN(e.created_at_ms), MAX(e.created_at_ms)
            FROM input_events e JOIN memory_state s ON s.event_id = e.id
            WHERE s.deleted = 0 AND e.committed_text = ?
            GROUP BY e.committed_text
            """,
            (text,),
        )
        conn.execute(
            "DELETE FROM phrase_project_stats WHERE committed_text = ? AND project = ?",
            (text, project),
        )
        conn.execute(
            """
            INSERT INTO phrase_project_stats(committed_text, project, input_frequency, first_seen_ms, last_seen_ms)
            SELECT e.committed_text, e.project, COUNT(*), MIN(e.created_at_ms), MAX(e.created_at_ms)
            FROM input_events e JOIN memory_state s ON s.event_id = e.id
            WHERE s.deleted = 0 AND e.committed_text = ? AND e.project = ?
            GROUP BY e.committed_text, e.project
            """,
            (text, project),
        )
        conn.execute(
            "DELETE FROM phrase_app_stats WHERE committed_text = ? AND app = ?",
            (text, app),
        )
        conn.execute(
            """
            INSERT INTO phrase_app_stats(committed_text, app, input_frequency, first_seen_ms, last_seen_ms)
            SELECT e.committed_text, e.app, COUNT(*), MIN(e.created_at_ms), MAX(e.created_at_ms)
            FROM input_events e JOIN memory_state s ON s.event_id = e.id
            WHERE s.deleted = 0 AND e.committed_text = ? AND e.app = ?
            GROUP BY e.committed_text, e.app
            """,
            (text, app),
        )


def _remove_orphan_demo_tags(conn: sqlite3.Connection, *, fixture: dict[str, Any]) -> None:
    tags = {
        str(tag)
        for event in fixture.get("events", [])
        if isinstance(event, dict)
        for tag in event.get("tags", [])
    }
    memory_book = fixture.get("memoryBook") if isinstance(fixture.get("memoryBook"), dict) else {}
    for section in ("dailyBooks", "memoryAtoms", "phraseCandidates"):
        for item in memory_book.get(section, []):
            if isinstance(item, dict):
                tags.update(str(tag) for tag in item.get("tags", []))
    tags.discard("")
    tags.add(str(fixture["fixtureTag"]))
    for tag in sorted(tags):
        row = conn.execute("SELECT id FROM memory_tags WHERE tag = ?", (tag,)).fetchone()
        if row is None:
            continue
        tag_id = int(row["id"])
        references = int(
            conn.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM memory_item_tags WHERE tag_id = ?) +
                    (SELECT COUNT(*) FROM memory_atom_tags WHERE CAST(tag_id AS TEXT) = CAST(? AS TEXT))
                """,
                (tag_id, tag_id),
            ).fetchone()[0]
        )
        if references == 0:
            conn.execute("DELETE FROM memory_tag_edges WHERE src_tag_id = ? OR dst_tag_id = ?", (tag_id, tag_id))
            conn.execute("DELETE FROM memory_tags WHERE id = ?", (tag_id,))


def _table_count(db_path: Path, table: str) -> int:
    with closing(sqlite3.connect(db_path)) as conn:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        if exists is None:
            return 0
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


@contextmanager
def _connect(db_path: Path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _fixture_sha256(path: str | Path) -> str:
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed and verify the isolated input-method-first demo database")
    parser.add_argument("command", choices=("seed", "reset", "verify"))
    parser.add_argument("--db-path", default=str(DEFAULT_DEMO_DB_PATH))
    parser.add_argument("--fixture", default=str(DEFAULT_FIXTURE_PATH))
    parser.add_argument("--reset", action="store_true", help="Reset the isolated demo DB before seeding")
    parser.add_argument("--live", action="store_true", help="Explicitly allow a real product DB; never enabled by default")
    parser.add_argument("--confirm", default="", help=f"Live mode requires the exact value {LIVE_CONFIRMATION}")
    parser.add_argument("--report", default="", help="Optional path for the machine-readable JSON result")
    args = parser.parse_args(argv)
    try:
        if args.command == "seed":
            payload = seed_demo_database(
                args.db_path,
                fixture_path=args.fixture,
                reset=args.reset,
                live=args.live,
                confirmation=args.confirm,
            )
        elif args.command == "reset":
            payload = reset_demo_database(
                args.db_path,
                fixture_path=args.fixture,
                live=args.live,
                confirmation=args.confirm,
            )
        else:
            payload = verify_demo_database(
                args.db_path,
                fixture_path=args.fixture,
                live=args.live,
                confirmation=args.confirm,
            )
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        payload = {"schemaVersion": SCHEMA_VERSION, "action": args.command, "ok": False, "error": str(exc)}
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if bool(payload.get("ok")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
