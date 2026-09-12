"""A read-only daily-report consumer. No Atom, Evidence or model writes."""
from __future__ import annotations

import html
import sqlite3
from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .common import LifecycleError, digest, identifier, load_json, now_ms, require_schema, row_dicts, transaction
from .portability import _export_snapshot, _origin, object_id
from .privacy import assess_capture, sanitize_json

AdmissionPredicate = Callable[[str], str]


def day_bounds(day: str, timezone: str) -> tuple[int, int]:
    try:
        parsed = date.fromisoformat(day)
        if parsed.isoformat() != day:
            raise ValueError
        zone = ZoneInfo(timezone)
        start = datetime.combine(parsed, time.min, zone)
        end = datetime.combine(parsed + timedelta(days=1), time.min, zone)
    except (ValueError, TypeError, OverflowError, ZoneInfoNotFoundError):
        raise LifecycleError("invalid_report_date_or_timezone") from None
    # Calendar midnights, not start + 24h: DST days can be 23 or 25 hours.
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)


def _canonical_admission(alias: str) -> str:
    # Keep the owning module as the single authority; do not clone its predicate.
    from ..memory_evidence_admission import admitted_personal_evidence_sql
    return admitted_personal_evidence_sql(alias)


def snapshot(conn: sqlite3.Connection, *, project: str, day: str, timezone: str,
             admission_predicate: AdmissionPredicate | None = None,
             include_timeline: bool = True) -> dict[str, Any]:
    """Freeze admitted evidence and confirmed atoms from ONE database snapshot.

    admission_predicate is an in-process test seam, never a request parameter.
    Imported timestamps do not move yesterday's work into today's report.
    """
    project = identifier(project, field="project", allow_empty=True)
    start, end = day_bounds(day, timezone)
    require_schema(conn)
    predicate = admission_predicate or _canonical_admission
    with transaction(conn, write=False):
        namespace_row = conn.execute("SELECT namespace FROM memory_portable_identity WHERE singleton=1").fetchone()
        namespace = str(namespace_row[0]) if namespace_row else "paw:local-readonly"
        packet = _export_snapshot(conn, project=project, namespace=namespace, policy=None)
        admitted = row_dicts(conn.execute(f"""SELECT e.evidence_id,e.occurred_at_ms,e.admission_revision
            FROM agent_memory_evidence e WHERE e.project=? AND {predicate('e')}""", (project,)))
        allowed = {object_id("evidence", _origin(conn, namespace, "evidence", row["evidence_id"], project)): row for row in admitted}
        evidence = [row for row in packet["evidence"] if row["id"] in allowed and start <= row["occurredAtMs"] < end]
        daily_ids = {row["id"] for row in evidence}
        refs_by_atom: dict[str, set[str]] = {}
        for ref in packet["references"]:
            if ref["from"].startswith("atom:") and ref["relation"] == "source":
                refs_by_atom.setdefault(ref["from"], set()).add(ref["to"])
        memory = [row for row in packet["atoms"] if row["status"] in {"approved", "active"}
            and row["claimState"] == "current" and row["validFromMs"] < end
            and (row["validToMs"] is None or row["validToMs"] > start)
            and refs_by_atom.get(row["id"], set()) <= allowed.keys()
            and refs_by_atom.get(row["id"], set()).intersection(daily_ids)]
        # Include older supporting Evidence for a mixed-date Atom as context,
        # clearly separated from observations that actually occurred today.
        supporting_ids = set().union(*(refs_by_atom.get(row["id"], set()) for row in memory)) if memory else set()
        context_evidence = [row for row in packet["evidence"] if row["id"] in supporting_ids - daily_ids]
        kept = daily_ids | supporting_ids | {row["id"] for row in memory}
        refs = [r for r in packet["references"] if r["from"] in kept]
        source_ids = {r["to"] for r in refs if r["to"].startswith("source:")}
        sources = [s for s in packet["sources"] if s["id"] in source_ids]
        timeline: dict[str, Any] = {}
        if include_timeline:
            from ..personal_context import load_activity_timeline_context, local_day_bounds_ms
            # The existing timeline uses the host calendar. Never silently label
            # that interval with another timezone or include a blocked legacy event.
            same_calendar = tuple(local_day_bounds_ms(day)) == (start, end)
            blocked = False
            if same_calendar:
                for event in row_dicts(conn.execute("""SELECT e.source,e.committed_text,e.tags_json,e.capture_metadata_json
                    FROM input_events e LEFT JOIN memory_state s ON s.event_id=e.id
                    WHERE e.project=? AND e.created_at_ms>=? AND e.created_at_ms<? AND COALESCE(s.deleted,0)=0""", (project, start, end))):
                    if not assess_capture(source=event["source"], text=event["committed_text"],
                        tags=tuple(load_json(event["tags_json"], list)), metadata=load_json(event["capture_metadata_json"])).allowed:
                        blocked = True
                        break
            if same_calendar and not blocked:
                timeline = sanitize_json(load_activity_timeline_context(conn, project=project, timeline_date=day))
            else:
                timeline = {"available": False, "reason": "timeline_privacy_or_timezone_boundary", "corroborationOnly": True}
        # Revisions participate even if the text and max timestamp are unchanged.
        revisions = {key: allowed[key]["admission_revision"] for key in sorted((daily_ids | supporting_ids))}
        result = {"schemaVersion": "paw.memory-daily-snapshot.v1", "project": project, "date": day,
            "timezone": timezone, "startMs": start, "endMs": end,
            "evidence": evidence, "memory": memory, "contextEvidence": context_evidence,
            "sources": sources, "references": refs, "admissionRevisions": revisions,
            "timeline": timeline, "omitted": packet["omitted"]}
        result["inputDigest"] = digest(result)
        result["sourceCursor"] = {"evidenceCount": len(evidence), "atomCount": len(memory),
            "lastOccurredAtMs": max((e["occurredAtMs"] for e in evidence), default=start),
            "lastEvidenceId": max(((e["occurredAtMs"], e["id"]) for e in evidence), default=(start, ""))[1]}
        return result


def _quote(text: str) -> str:
    # Do not let imported markup create images, tracking requests or fake headings.
    safe = html.escape(text, quote=False)
    for char in "\\`*_{}[]()#!|":
        safe = safe.replace(char, "\\" + char)
    return "\n".join("> " + line for line in safe.splitlines())


def render(snapshot_value: dict[str, Any]) -> dict[str, Any]:
    """Deterministic report; text is quoted evidence, not invented achievements."""
    lines = [f"# {snapshot_value['date']} 日报", "",
        f"时区：{snapshot_value['timezone']}。", _quote("项目：" + snapshot_value["project"]), "",
        "## 当日来源陈述", "这些是已获准用于 Memory 的来源陈述，不等同于执行成功的独立证明。", ""]
    for item in snapshot_value["evidence"]:
        lines.extend([_quote(item["text"]), f"来源引用：`{item['id']}`；发生时间：`{item['occurredAtMs']}`。", ""])
    if not snapshot_value["evidence"]:
        lines.extend(["这一天没有可用的已准入个人 Evidence；不据此推断当天没有工作。", ""])
    lines.extend(["## 相关已确认记忆", ""])
    for item in snapshot_value["memory"]:
        refs = [r["to"] for r in snapshot_value["references"] if r["from"] == item["id"] and r["relation"] == "source"]
        lines.extend([_quote(item["text"]), "证据：" + "、".join(f"`{ref}`" for ref in refs), ""])
    if not snapshot_value["memory"]:
        lines.extend(["没有与当日证据相连的已确认 Atom。", ""])
    timeline = snapshot_value["timeline"]
    if timeline.get("available"):
        lines.extend(["## 活动时间线（仅供佐证）", "", _quote(str(timeline.get("summary", ""))), ""])
    return {"schemaVersion": "paw.memory-daily-report.v1", "metadata": {"derivedArtifactType": "daily_memory_report",
        "memoryRetention": "none", "writesBackToMemory": False},
        "project": snapshot_value["project"], "date": snapshot_value["date"], "timezone": snapshot_value["timezone"],
        "generatedAtMs": now_ms(), "inputDigest": snapshot_value["inputDigest"],
        "sourceCursor": snapshot_value["sourceCursor"], "references": snapshot_value["references"],
        "evidence": snapshot_value["evidence"], "contextEvidence": snapshot_value["contextEvidence"],
        "memory": snapshot_value["memory"], "sources": snapshot_value["sources"],
        "markdown": "\n".join(lines), "omitted": snapshot_value["omitted"]}


def generate(conn: sqlite3.Connection, *, project: str, day: str, timezone: str,
             admission_predicate: AdmissionPredicate | None = None,
             include_timeline: bool = True) -> dict[str, Any]:
    return render(snapshot(conn, project=project, day=day, timezone=timezone,
                           admission_predicate=admission_predicate, include_timeline=include_timeline))
