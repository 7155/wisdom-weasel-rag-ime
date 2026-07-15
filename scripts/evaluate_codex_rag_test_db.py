#!/usr/bin/env python3
"""Exercise Group, TagMemo, timeline, vector health, and optional DeepSeek."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rag_ime.active_rag_service import ActiveRagService, ActiveRagStartRequest
from rag_ime.deepseek_completion import DeepSeekV4FlashCompletionProvider
from rag_ime.deepseek_config import load_deepseek_config
from rag_ime.embeddings import embedding_provider_from_env
from rag_ime.hybrid_rag_models import HybridRagQuery
from rag_ime.hybrid_rag_retriever import retrieve_hybrid_rag_candidates
from rag_ime.local_sqlite_core import LocalSqliteCoreClient
from rag_ime.retrieval_docs import rebuild_retrieval_docs
from rag_ime.retrieval_vector_index import rebuild_retrieval_doc_vectors
from rag_ime.text_utils import stable_text_hash
from rag_ime.timeline_context import build_timeline_context_pack


PROJECT = "wisdom-weasel-rag-ime"
SCENARIOS = (
    ("retrieval", "embedding 和多路召回怎么接入 RAG", "retrieval"),
    ("group", "Context Group 如何防止跨项目污染", "group"),
    ("tag", "TagMemo 标签图如何增强召回", "tag"),
    ("deepseek", "DeepSeek 显式生成如何注入本地证据", "deepseek"),
    ("foreground", "Squirrel 前台候选 stale context 怎么丢弃", "foreground"),
    ("memory", "Memory Book 如何周期性整理和去重", "memory"),
    ("runtime", "sidecar timeout 和 doctor 怎么排查", "runtime"),
    ("privacy", "输入法敏感内容怎样禁止进入记忆", "privacy"),
)


def _wait(service: ActiveRagService, session_id: str, timeout_s: float) -> dict[str, object]:
    deadline = time.monotonic() + timeout_s
    result = service.status(session_id)
    while time.monotonic() < deadline:
        result = service.status(session_id)
        if result.get("status") in {"ready", "error", "cancelled", "stale_dropped"}:
            break
        time.sleep(0.05)
    return result


def evaluate(db_path: Path, *, run_deepseek: bool) -> dict[str, object]:
    provider = embedding_provider_from_env()
    core = LocalSqliteCoreClient(db_path, embedding_provider=provider)
    core.initialize()
    scenario_reports: list[dict[str, object]] = []
    with core._connect() as conn:  # type: ignore[attr-defined]
        rebuild = rebuild_retrieval_docs(conn, project=PROJECT)
        indexed = int(conn.execute(
            "SELECT COUNT(*) FROM memory_retrieval_doc_vectors WHERE provider_fingerprint = ?",
            (provider.fingerprint,),
        ).fetchone()[0])
        vector_rebuild = (
            {"providerFingerprint": provider.fingerprint, "documents": indexed, "reused": True}
            if indexed == int(rebuild.get("docCount") or indexed + 1)
            else rebuild_retrieval_doc_vectors(conn, provider, project=PROJECT)
        )
        for scenario_id, query_text, topic in SCENARIOS:
            started = time.perf_counter()
            payload = retrieve_hybrid_rag_candidates(
                conn,
                HybridRagQuery(
                    query_text=query_text,
                    raw_input=query_text,
                    committed_tail="用户正在 Codex 中连续讨论 RAG、Group、Tag 和 DeepSeek。",
                    rime_candidates=tuple(query_text.split()[:3]),
                    project=PROJECT,
                    app="dev.openai.codex",
                    top_k=8,
                    latency_budget_ms=800,
                    context_group_id=f"project:{PROJECT}/topic:{topic}",
                    context_group_level="project",
                ),
                provider,
            )
            elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
            candidates = [item for item in payload.get("candidates", []) if isinstance(item, dict)]
            hits = [item for item in payload.get("hits", []) if isinstance(item, dict)]
            exact_group_hits = sum(
                1
                for item in hits
                if str(dict(item.get("metadata") or {}).get("contextGroupId") or "")
                == f"project:{PROJECT}/topic:{topic}"
            )
            lanes = payload.get("lanes") if isinstance(payload.get("lanes"), dict) else {}
            scenario_reports.append(
                {
                    "id": scenario_id,
                    "query": query_text,
                    "elapsedMs": elapsed_ms,
                    "candidateCount": len(candidates),
                    "exactGroupHitCount": exact_group_hits,
                    "topCandidates": [str(item.get("text") or "")[:160] for item in candidates[:3]],
                    "laneCounts": {
                        name: int(value.get("count") or 0)
                        for name, value in lanes.items()
                        if isinstance(value, dict)
                    },
                    "vectorAvailable": bool(dict(lanes.get("vector_raw") or {}).get("available")),
                }
            )

    timeline = build_timeline_context_pack(core, project=PROJECT, app="dev.openai.codex")
    recent_input = str(timeline.get("recentInput") or "")
    deepseek_reports: list[dict[str, object]] = []
    if run_deepseek:
        os.environ.setdefault("RAG_IME_DEEPSEEK_ACTIVE_RAG", "1")
        service = ActiveRagService(
            core=core,
            completion_provider=DeepSeekV4FlashCompletionProvider(load_deepseek_config(), enforce_runtime_flags=True),
        )
        for index, selected_text in enumerate(
            (
                "根据我的历史说明 Group 和 Tag 应该怎样增强输入法 RAG。",
                "整理上午最近输入的内容，并给出下一步测试重点。",
                "结合本地记忆解释 DeepSeek 为什么必须显式触发。",
            ),
            start=1,
        ):
            request = ActiveRagStartRequest(
                selected_text=selected_text,
                selected_text_hash=stable_text_hash(selected_text),
                frontend_revision=index,
                selection_epoch=index,
                panel_session_id=f"codex-test-{index}",
                front_app_bundle_id="dev.openai.codex",
                surrounding_before=recent_input,
                context=recent_input,
                project=PROJECT,
                app="dev.openai.codex",
                max_candidates=1,
                max_chars=180,
                latency_budget_ms=20_000,
                remote_model_allowed=True,
                remote_model_gates={
                    "sceneEnabled": True,
                    "providerConfigured": True,
                    "explicitTrigger": True,
                    "allowRemoteModel": True,
                    "localOnlyDefaultDisabled": True,
                    "sensitiveFieldClear": True,
                },
            )
            started = time.perf_counter()
            initial = service.start(request)
            final = _wait(service, str(initial["sessionId"]), 22.0)
            diagnostics = dict(final.get("diagnostics") or {})
            retrieval = dict(diagnostics.get("retrieval") or {})
            deepseek_reports.append(
                {
                    "id": f"deepseek-{index}",
                    "status": final.get("status"),
                    "elapsedMs": round((time.perf_counter() - started) * 1000, 2),
                    "evidenceCount": int(retrieval.get("evidenceCount") or 0),
                    "candidateTexts": [
                        str(item.get("text") or "")
                        for item in final.get("candidates", [])
                        if isinstance(item, dict)
                    ],
                    "route": diagnostics.get("route"),
                }
            )
    return {
        "schemaVersion": "rag-ime.codex-test-evaluation.v1",
        "database": str(db_path),
        "embedding": {"fingerprint": provider.fingerprint, "vectorStats": core.vector_index_stats()},
        "retrievalDocs": rebuild,
        "retrievalVectors": vector_rebuild,
        "timeline": {
            "recentInputChars": len(recent_input),
            "recentInputSeparatorCount": recent_input.count(" / "),
            "evidenceCount": len(timeline.get("evidencePack") or []),
        },
        "scenarios": scenario_reports,
        "deepseek": deepseek_reports,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=Path(".rag-ime-data/codex-rag-deepseek-test.sqlite"))
    parser.add_argument("--output", type=Path, default=Path(".rag-ime-data/codex-rag-deepseek-test-report.json"))
    parser.add_argument("--deepseek", action="store_true")
    args = parser.parse_args()
    report = evaluate(args.db, run_deepseek=args.deepseek)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
