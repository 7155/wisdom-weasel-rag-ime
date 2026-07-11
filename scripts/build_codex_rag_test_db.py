#!/usr/bin/env python3
"""Build a private RAG/DeepSeek test database from local Codex history."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rag_ime.codex_history import load_codex_history_records
from rag_ime.local_sqlite_core import LocalSqliteCoreClient
from rag_ime.memory_book_compiler import apply_memory_book_plan, inspect_memory_book_plan, memory_book_plan_from_compile_output
from rag_ime.memory_ingest import normalize_text, upsert_memory_item
from rag_ime.models import InputEvent
from rag_ime.retrieval_docs import rebuild_retrieval_docs
from rag_ime.text_utils import compact_whitespace, now_ms, truncate_text


PROJECT = "wisdom-weasel-rag-ime"
TOPICS: dict[str, tuple[str, ...]] = {
    "foreground": ("squirrel", "前台", "候选窗", "input source", "backspace", "delete", "stale"),
    "retrieval": ("rag", "检索", "embedding", "向量", "bm25", "召回"),
    "deepseek": ("deepseek", "active rag", "生成", "reasoning", "显式触发"),
    "memory": ("memory book", "memory atom", "记忆", "去重", "compiler", "整理"),
    "group": ("context group", "group", "上下文组", "跨项目", "短期记忆"),
    "tag": ("tagmemo", "tag", "标签", "tag edge", "标签图"),
    "privacy": ("privacy", "隐私", "敏感", "密码", "secure"),
    "model": ("minimind", "mlx", "qwen", "模型", "completion", "补全"),
    "runtime": ("sidecar", "launchagent", "timeout", "延迟", "doctor", "runtime"),
    "notion": ("notion", "worker", "custom agent", "知识库"),
}
SENSITIVE_RE = re.compile(
    r"(sk-[A-Za-z0-9]{8,}|bearer\s+[A-Za-z0-9._-]{10,}|api[_ -]?key\s*[=:：]\s*\S+)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SourceRecord:
    text: str
    source: str
    created_at_ms: int
    topic: str
    tags: tuple[str, ...]
    context_group_id: str
    stable: bool


def _topic(text: str) -> str:
    lowered = text.lower()
    scored = [(sum(1 for term in terms if term in lowered), name) for name, terms in TOPICS.items()]
    score, name = max(scored)
    return name if score else "general"


def _tags(text: str, topic: str) -> tuple[str, ...]:
    lowered = text.lower()
    values = {"codex", "test-corpus", topic}
    for name, terms in TOPICS.items():
        if any(term in lowered for term in terms):
            values.add(name)
    return tuple(sorted(values))


def _safe_text(value: str, *, max_chars: int = 700) -> str:
    text = compact_whitespace(value)
    if SENSITIVE_RE.search(text):
        return ""
    if text.startswith("<environment_context>") or text.startswith("<permissions"):
        return ""
    if "rollout_summaries/" in text or "cwd=" in text or "rollout_path=" in text:
        return ""
    return truncate_text(text, max_chars)


def _markdown_records(paths: list[Path], *, limit: int) -> list[SourceRecord]:
    records: list[SourceRecord] = []
    for path in paths:
        if not path.exists():
            continue
        heading = ""
        for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
            stripped = raw.strip()
            if stripped.startswith("#"):
                heading = compact_whitespace(stripped.lstrip("#"))
                continue
            if not stripped.startswith(("- ", "* ")):
                continue
            text = _safe_text(stripped[2:])
            if len(text) < 24:
                continue
            topic = _topic(f"{heading} {text}")
            records.append(
                SourceRecord(
                    text=text,
                    source=f"markdown:{path.name}",
                    created_at_ms=int(path.stat().st_mtime * 1000),
                    topic=topic,
                    tags=_tags(f"{heading} {text}", topic),
                    context_group_id=f"project:{PROJECT}/topic:{topic}",
                    stable=True,
                )
            )
            if len(records) >= limit:
                return records
    return records


def _session_records(path: Path, *, limit: int) -> list[SourceRecord]:
    records: list[SourceRecord] = []
    for item in load_codex_history_records(
        path,
        limit=limit,
        min_chars=24,
        max_chars=700,
        path_order="mtime-desc",
        roles=("user",),
    ):
        text = _safe_text(item.text)
        if not text:
            continue
        topic = _topic(text)
        records.append(
            SourceRecord(
                text=text,
                source=f"codex-session:{Path(item.source_path).name}",
                created_at_ms=item.created_at_ms or now_ms(),
                topic=topic,
                tags=_tags(text, topic) + ("raw-chat",),
                context_group_id=f"project:{PROJECT}/topic:{topic}",
                stable=False,
            )
        )
    return records


def _dedupe(records: list[SourceRecord]) -> list[SourceRecord]:
    seen: set[str] = set()
    result: list[SourceRecord] = []
    for record in records:
        key = normalize_text(record.text)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(record)
    return result


def _memory_id(record: SourceRecord) -> str:
    digest = hashlib.sha256(f"{record.source}\n{record.text}".encode("utf-8")).hexdigest()[:20]
    return f"codex-test:{record.topic}:{digest}"


def build_database(*, output: Path, records: list[SourceRecord]) -> dict[str, object]:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)
    core = LocalSqliteCoreClient(output)
    core.initialize()
    event_ids: dict[str, list[int]] = {}
    stable_records: list[tuple[SourceRecord, int]] = []
    for index, record in enumerate(records, start=1):
        ref = core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=record.created_at_ms + index,
                source=record.source,
                committed_text=record.text,
                privacy_disposition="allowed",
                recent_context=f"Codex private test corpus topic={record.topic}",
                schema_id="codex_test_corpus",
                app="dev.openai.codex",
                project=PROJECT,
                provider_name="codex-test-db-builder",
                tags=record.tags,
                context_group_id=record.context_group_id,
                context_group_level="project",
            )
        )
        event_id = int(str(ref).split(":")[-1])
        event_ids.setdefault(record.topic, []).append(event_id)
        if record.stable:
            stable_records.append((record, event_id))

    with core._connect() as conn:  # type: ignore[attr-defined]
        for record, event_id in stable_records:
            upsert_memory_item(
                conn,
                memory_id=_memory_id(record),
                kind="stable_memory",
                text=record.text,
                normalized_text=normalize_text(record.text),
                summary=truncate_text(record.text, 180),
                source_event_id=event_id,
                project=PROJECT,
                app="",
                confidence=0.88,
                quality_score=0.84,
                status="approved",
                privacy_class="local",
                created_at_ms=record.created_at_ms,
                updated_at_ms=record.created_at_ms,
                metadata={
                    "source": record.source,
                    "contextGroupId": record.context_group_id,
                    "shortTerm": False,
                    "direct_candidate_allowed": False,
                },
                tags=record.tags,
                embedding_provider=None,
            )

        compile_output = _compile_output(stable_records=stable_records, event_ids=event_ids)
        plan = memory_book_plan_from_compile_output(
            compile_output,
            project=PROJECT,
            provider="codex-test-db-builder",
            model="deterministic-local",
        )
        validation = inspect_memory_book_plan(plan)
        if not validation.get("ok"):
            raise ValueError(json.dumps(validation, ensure_ascii=False, indent=2))
        applied = apply_memory_book_plan(conn, plan)
        retrieval = rebuild_retrieval_docs(conn, project=PROJECT)
        counts = {
            table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in (
                "input_events",
                "memory_items",
                "memory_books",
                "memory_atoms",
                "memory_tags",
                "memory_tag_edges",
                "memory_retrieval_docs",
            )
        }
        groups = [
            {"contextGroupId": str(row[0]), "count": int(row[1])}
            for row in conn.execute(
                "SELECT context_group_id, COUNT(*) FROM input_events GROUP BY context_group_id ORDER BY COUNT(*) DESC"
            ).fetchall()
        ]
    return {
        "schemaVersion": "rag-ime.codex-private-test-db.v1",
        "output": str(output),
        "recordCount": len(records),
        "stableRecordCount": len(stable_records),
        "counts": counts,
        "groups": groups,
        "memoryBookApply": {
            "runId": applied.get("runId"),
            "status": applied.get("status"),
            "summary": applied.get("summary"),
        },
        "retrievalDocs": retrieval,
    }


def _compile_output(*, stable_records: list[tuple[SourceRecord, int]], event_ids: dict[str, list[int]]) -> dict[str, object]:
    daily_books: list[dict[str, object]] = []
    atoms: list[dict[str, object]] = []
    phrases: list[dict[str, object]] = []
    by_topic: dict[str, list[tuple[SourceRecord, int]]] = {}
    for item in stable_records:
        by_topic.setdefault(item[0].topic, []).append(item)
    for topic, items in sorted(by_topic.items()):
        sources = [event_id for _, event_id in items[:20]]
        topic_terms = list(TOPICS.get(topic, (topic,)))
        hints = [truncate_text(term, 24) for term in topic_terms[:4]]
        topic_summary = f"Codex 记忆中整理出 {len(items)} 条 {topic} 主题记录，用于 RAG 分组、标签和生成测试。"
        daily_books.append(
            {
                "bookId": f"codex-test-book:{topic}",
                "bookType": "topic",
                "bookKey": topic,
                "title": f"Codex {topic} test memory",
                "summary": topic_summary,
                "tags": [topic, "codex", "test-corpus"],
                "surfaceHints": hints,
                "queryExpansions": list(TOPICS.get(topic, (topic,))),
                "sourceEventIds": sources,
                "confidence": 0.88,
                "metadata": {"contextGroupId": f"project:{PROJECT}/topic:{topic}"},
            }
        )
        atoms.append(
            {
                "id": f"codex-test-atom:{topic}",
                "kind": "topic_summary",
                "text": topic_summary,
                "canonicalText": topic_summary,
                "tags": [topic, "codex", "test-corpus"],
                "aliases": topic_terms,
                "surfaceHints": hints,
                "queryExpansions": [topic, *topic_terms],
                "confidence": 0.9,
                "qualityScore": 0.86,
                "scopeProject": PROJECT,
                "scopeApp": "",
                "sourceEventIds": sources[:8],
                "metadata": {"contextGroupId": f"project:{PROJECT}/topic:{topic}", "source": "codex-test-db-builder"},
            }
        )
        if hints:
            phrases.append(
                {
                    "text": hints[0],
                    "tags": [topic, "codex"],
                    "project": PROJECT,
                    "app": "",
                    "sourceEventIds": sources[:1],
                    "metadata": {"contextGroupId": f"project:{PROJECT}/topic:{topic}", "source": "codex-test-db-builder"},
                }
            )
    edges = []
    for topic in sorted(by_topic):
        for related in _related_topics(topic):
            if related not in by_topic:
                continue
            edges.append(
                {
                    "src": topic,
                    "dst": related,
                    "weight": 0.72,
                    "evidenceEventIds": event_ids.get(topic, [])[:2],
                }
            )
    return {
        "schemaVersion": "rag-ime.memory-book-compile.v1",
        "dailyBooks": daily_books,
        "memoryAtoms": atoms,
        "tagEdges": edges,
        "phraseCandidates": phrases,
        "warnings": [],
    }


def _related_topics(topic: str) -> tuple[str, ...]:
    return {
        "foreground": ("runtime", "retrieval"),
        "retrieval": ("tag", "group", "deepseek"),
        "deepseek": ("retrieval", "memory"),
        "memory": ("tag", "group", "deepseek"),
        "group": ("retrieval", "memory"),
        "tag": ("retrieval", "memory"),
        "model": ("runtime", "foreground"),
        "runtime": ("foreground", "model"),
        "privacy": ("foreground", "deepseek"),
        "notion": ("memory", "deepseek"),
    }.get(topic, ())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path(".rag-ime-data/codex-rag-deepseek-test.sqlite"))
    parser.add_argument("--manifest", type=Path, default=Path(".rag-ime-data/codex-rag-deepseek-test-manifest.json"))
    parser.add_argument("--sessions", type=Path, default=Path.home() / ".codex" / "sessions")
    parser.add_argument("--max-session-records", type=int, default=240)
    parser.add_argument("--max-markdown-records", type=int, default=260)
    args = parser.parse_args()
    memory_root = Path.home() / ".codex" / "memories"
    markdown_paths = [
        memory_root / "MEMORY.md",
        *sorted((memory_root / "rollout_summaries").glob("*.md"), key=lambda path: path.stat().st_mtime, reverse=True)[:40],
        Path("docs/agent/chat-summary.md"),
        Path("docs/agent/notes.md"),
    ]
    records = _dedupe(
        _markdown_records(markdown_paths, limit=max(1, args.max_markdown_records))
        + _session_records(args.sessions, limit=max(1, args.max_session_records))
    )
    report = build_database(output=args.output, records=records)
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
