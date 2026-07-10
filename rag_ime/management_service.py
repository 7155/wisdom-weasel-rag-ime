from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Mapping

from .management_events import ManagementEventHub
from .management_models import MANAGEMENT_SCHEMA_VERSION, ManagementRevision, PageRequest, RuntimeJob
from .settings_schema import stable_settings_hash
from .settings_store import ManagementSettingsStore, record_management_audit


class ManagementService:
    """Control-plane facade. It is never used by the `/rime-suggest` path."""

    def __init__(
        self,
        *,
        db_path: str | Path,
        project: str,
        repo_root: str | Path,
        settings_store: ManagementSettingsStore,
        health_provider: Callable[[], Mapping[str, object]],
        input_source_provider: Callable[[], Mapping[str, object]],
        predictor_provider: Callable[[], Mapping[str, object]],
        last_prediction_provider: Callable[[], Mapping[str, object]] | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.project = project
        self.repo_root = Path(repo_root)
        self.settings_store = settings_store
        self.health_provider = health_provider
        self.input_source_provider = input_source_provider
        self.predictor_provider = predictor_provider
        self.last_prediction_provider = last_prediction_provider or (lambda: {})
        self.events = ManagementEventHub()
        self._runtime_revision = 1
        self._revision_lock = threading.RLock()
        self._jobs: dict[str, RuntimeJob] = {}
        self._jobs_lock = threading.RLock()
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="rag-ime-management")

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    def revision(self, *, audit_id: int | None = None) -> ManagementRevision:
        settings = self.settings_store.get_settings()
        with self._revision_lock:
            runtime_revision = self._runtime_revision
        return ManagementRevision(stable_settings_hash(settings), runtime_revision, audit_id)

    def settings_changed(self, *, audit_id: int, changed_keys: list[str]) -> dict[str, object]:
        with self._revision_lock:
            self._runtime_revision += 1
        revision = self.revision(audit_id=audit_id)
        self.events.publish(
            "settings_changed",
            {**revision.payload(), "changedKeys": changed_keys},
        )
        return revision.payload()

    def overview(self) -> dict[str, object]:
        health = _safe_mapping(self.health_provider)
        input_source = _safe_mapping(self.input_source_provider)
        predictor = _safe_mapping(self.predictor_provider)
        settings = self.settings_store.get_settings()
        counts = self._summary_counts()
        user_bundle = Path.home() / "Library/Input Methods/Squirrel.app"
        system_bundle = Path("/Library/Input Methods/Squirrel.app")
        components = self._components(health=health, input_source=input_source, predictor=predictor)
        return {
            **self.revision().payload(),
            "ok": True,
            "project": self.project,
            "profile": _profile_name(settings),
            "aiPaused": not bool(_nested(settings, "interaction.postCommit.enabled", True)),
            "components": components,
            "canonicalSquirrel": {
                "ok": user_bundle.exists(),
                "path": str(user_bundle),
                "duplicateSystemBundle": system_bundle.exists(),
            },
            "memory": counts,
            "lastPrediction": dict(self.last_prediction_provider() or {}),
        }

    def runtime_status(self) -> dict[str, object]:
        health = _safe_mapping(self.health_provider)
        input_source = _safe_mapping(self.input_source_provider)
        predictor = _safe_mapping(self.predictor_provider)
        return {
            **self.revision().payload(),
            "ok": True,
            "components": self._components(health=health, input_source=input_source, predictor=predictor),
            "eventSubscribers": self.events.subscriber_count,
        }

    def runtime_components(self) -> dict[str, object]:
        status = self.runtime_status()
        return {**status, "items": list(status["components"].values())}

    def start_runtime_action(self, payload: Mapping[str, object]) -> dict[str, object]:
        action = str(payload.get("action") or "").strip()
        if action not in _RUNTIME_ACTIONS:
            raise ValueError(f"unsupported runtime action: {action}")
        job = RuntimeJob(job_id=str(uuid.uuid4()), action=action, created_at_ms=_now_ms())
        with self._jobs_lock:
            self._jobs[job.job_id] = job
        audit_id = self._audit("runtime_action_queued", "runtime", action, dict(payload), {"jobId": job.job_id})
        self._executor.submit(self._run_runtime_action, job.job_id)
        return {
            **self.revision(audit_id=audit_id).payload(),
            "ok": True,
            "job": job.payload(),
            "jobId": job.job_id,
        }

    def runtime_job(self, job_id: str) -> dict[str, object]:
        with self._jobs_lock:
            job = self._jobs.get(job_id)
        if job is None:
            return {**self.revision().payload(), "ok": False, "error": "job not found", "jobId": job_id}
        return {**self.revision().payload(), "ok": True, "job": job.payload()}

    def memory_summary(self) -> dict[str, object]:
        return {**self.revision().payload(), "ok": True, **self._summary_counts()}

    def memory_page(self, kind: str, request: PageRequest) -> dict[str, object]:
        handlers = {
            "books": self._memory_books,
            "atoms": self._memory_atoms,
            "phrases": self._memory_phrases,
            "groups": self._memory_groups,
            "negative": self._negative_memory,
        }
        handler = handlers.get(kind)
        if handler is None:
            raise ValueError(f"unsupported memory page: {kind}")
        items, next_cursor = handler(request)
        return {
            **self.revision().payload(),
            "ok": True,
            "kind": kind,
            "items": items,
            "nextCursor": next_cursor,
            "limit": request.limit,
            "rawTextVisible": False,
        }

    def history_page(self, request: PageRequest) -> dict[str, object]:
        cursor = _cursor_int(request.cursor)
        query = f"%{request.query}%"
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, created_at_ms, source, committed_text, recent_context, app,
                       project, provider_name, context_group_id, context_group_level
                FROM input_events
                WHERE (? = 0 OR id < ?)
                  AND (? = '' OR source = ?)
                  AND (? = '' OR committed_text LIKE ? OR app LIKE ? OR project LIKE ?)
                ORDER BY id DESC LIMIT ?
                """,
                (cursor, cursor, request.status, request.status, request.query, query, query, query, request.limit + 1),
            ).fetchall()
        has_more = len(rows) > request.limit
        rows = rows[: request.limit]
        items = [
            {
                "id": int(row["id"]),
                "createdAtMs": int(row["created_at_ms"]),
                "source": str(row["source"]),
                "app": str(row["app"]),
                "project": str(row["project"]),
                "provider": str(row["provider_name"]),
                "groupId": str(row["context_group_id"]),
                "groupLevel": str(row["context_group_level"]),
                "textHash": _text_hash(str(row["committed_text"])),
                "textChars": len(str(row["committed_text"])),
                "textPreview": _redacted_preview(str(row["committed_text"])),
                "contextHash": _text_hash(str(row["recent_context"])),
            }
            for row in rows
        ]
        next_cursor = str(rows[-1]["id"]) if has_more and rows else ""
        return {
            **self.revision().payload(),
            "ok": True,
            "items": items,
            "nextCursor": next_cursor,
            "limit": request.limit,
            "rawTextVisible": False,
        }

    def memory_action(self, payload: Mapping[str, object]) -> dict[str, object]:
        item_id = str(payload.get("id") or payload.get("itemId") or "").strip()
        item_type = str(payload.get("type") or payload.get("itemType") or "").strip()
        action = str(payload.get("action") or "").strip()
        if not item_id or action not in {"pin", "enable", "disable", "suppress", "tombstone", "forget", "update_phrase", "rebuild_retrieval_doc"}:
            raise ValueError("valid item id and memory action are required")
        status = "active" if action in {"pin", "enable", "update_phrase", "rebuild_retrieval_doc"} else "disabled"
        with self._connect() as conn:
            if item_type == "book":
                conn.execute("UPDATE memory_books SET status = ?, updated_at_ms = ? WHERE book_id = ?", (status, _now_ms(), item_id))
            elif item_type == "atom":
                conn.execute("UPDATE memory_atoms SET status = ?, updated_at_ms = ? WHERE id = ?", (status, _now_ms(), item_id))
            else:
                conn.execute(
                    "INSERT INTO memory_tombstones(created_at_ms, target_type, target_value, reason, active, metadata_json) VALUES (?, ?, ?, ?, 1, '{}')",
                    (_now_ms(), item_type or "phrase", item_id, action),
                )
            audit_id = record_management_audit(
                conn,
                action=f"memory_{action}",
                target_type=item_type or "memory",
                target_id=item_id,
                payload=dict(payload),
                result={"status": status},
            )
        with self._revision_lock:
            self._runtime_revision += 1
        revision = self.revision(audit_id=int(audit_id))
        self.events.publish("memory_changed", {**revision.payload(), "itemId": item_id, "action": action})
        return {**revision.payload(), "ok": True, "itemId": item_id, "status": status}

    def _components(
        self,
        *,
        health: Mapping[str, object],
        input_source: Mapping[str, object],
        predictor: Mapping[str, object],
    ) -> dict[str, dict[str, object]]:
        sidecar_ok = bool(health.get("ok"))
        predictor_payload = predictor.get("predictor") if isinstance(predictor.get("predictor"), Mapping) else predictor
        predictor_ok = bool(predictor.get("ok", predictor_payload.get("ok", False)))
        selected = bool(input_source.get("selected") or input_source.get("current"))
        counts = self._summary_counts()
        return {
            "inputMethod": _component("inputMethod", selected, "已选择" if selected else "未选择", input_source),
            "sidecar": _component("sidecar", sidecar_ok, "运行中" if sidecar_ok else "不可用", health),
            "predictor": _component("predictor", predictor_ok, "已加载" if predictor_ok else "不可用", predictor_payload),
            "foregroundContext": _component("foregroundContext", sidecar_ok, "等待输入" if sidecar_ok else "不可用", {}),
            "hybridRag": _component("hybridRag", bool(_nested(self.settings_store.get_settings(), "rag.hybrid.enabled", False)), "已启用", {}),
            "memoryCompiler": _component("memoryCompiler", True, f"待整理 {counts['pendingCompileEvents']} 条", counts),
            "sqlite": _component("sqlite", self.db_path.exists(), "正常" if self.db_path.exists() else "缺失", {"path": str(self.db_path)}),
        }

    def _summary_counts(self) -> dict[str, int]:
        names = {
            "eventCount": "input_events",
            "memoryItemCount": "memory_items",
            "memoryBookCount": "memory_books",
            "memoryAtomCount": "memory_atoms",
            "retrievalDocCount": "memory_retrieval_docs",
        }
        result: dict[str, int] = {}
        with self._connect() as conn:
            tables = {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
            for key, table in names.items():
                result[key] = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]) if table in tables else 0
            if "memory_compile_state" in tables:
                result["pendingCompileEvents"] = int(conn.execute("SELECT COALESCE(SUM(pending_event_count), 0) FROM memory_compile_state").fetchone()[0])
            else:
                result["pendingCompileEvents"] = 0
        return result

    def _memory_books(self, request: PageRequest) -> tuple[list[dict[str, object]], str]:
        return self._rowid_page(
            "memory_books",
            request,
            columns="book_id AS id, title, book_type AS type, project, app, status, confidence, quality_score, updated_at_ms",
            search_columns=("title", "project", "app", "book_type"),
        )

    def _memory_atoms(self, request: PageRequest) -> tuple[list[dict[str, object]], str]:
        items, cursor = self._rowid_page(
            "memory_atoms",
            request,
            columns="id, kind AS type, text, scope_project AS project, scope_app AS app, status, confidence, quality_score, updated_at_ms",
            search_columns=("text", "kind", "scope_project", "scope_app"),
        )
        for item in items:
            text = str(item.pop("text", ""))
            item["textHash"] = _text_hash(text)
            item["textChars"] = len(text)
            item["textPreview"] = _redacted_preview(text)
        return items, cursor

    def _memory_phrases(self, request: PageRequest) -> tuple[list[dict[str, object]], str]:
        items, cursor = self._rowid_page(
            "phrase_stats",
            request,
            columns="committed_text AS text, input_frequency AS useCount, first_seen_ms, last_seen_ms",
            search_columns=("committed_text",),
        )
        for item in items:
            text = str(item.pop("text", ""))
            item["id"] = _text_hash(text)
            item["textHash"] = _text_hash(text)
            item["textPreview"] = _redacted_preview(text)
        return items, cursor

    def _memory_groups(self, request: PageRequest) -> tuple[list[dict[str, object]], str]:
        limit = request.limit
        cursor = _cursor_int(request.cursor)
        query = f"%{request.query}%"
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT MAX(id) AS row_cursor, context_group_id AS id, context_group_level AS level,
                       project, app, COUNT(*) AS event_count, MAX(created_at_ms) AS updated_at_ms
                FROM input_events
                WHERE context_group_id != '' AND (? = '' OR context_group_id LIKE ? OR project LIKE ? OR app LIKE ?)
                GROUP BY context_group_id, context_group_level, project, app
                HAVING (? = 0 OR MAX(id) < ?)
                ORDER BY row_cursor DESC LIMIT ?
                """,
                (request.query, query, query, query, cursor, cursor, limit + 1),
            ).fetchall()
        has_more = len(rows) > limit
        rows = rows[:limit]
        return [dict(row) for row in rows], str(rows[-1]["row_cursor"]) if has_more and rows else ""

    def _negative_memory(self, request: PageRequest) -> tuple[list[dict[str, object]], str]:
        return self._rowid_page(
            "memory_tombstones",
            request,
            columns="id, target_type AS type, target_value AS value, reason, active, created_at_ms",
            search_columns=("target_value", "reason", "target_type"),
        )

    def _rowid_page(
        self,
        table: str,
        request: PageRequest,
        *,
        columns: str,
        search_columns: tuple[str, ...],
    ) -> tuple[list[dict[str, object]], str]:
        limit = request.limit
        cursor = _cursor_int(request.cursor)
        like = f"%{request.query}%"
        search_sql = " OR ".join(f"{column} LIKE ?" for column in search_columns)
        params: list[object] = [cursor, cursor, request.query, *([like] * len(search_columns))]
        status_sql = ""
        if request.status and table not in {"phrase_stats"}:
            status_column = "active" if table == "memory_tombstones" else "status"
            status_sql = f" AND {status_column} = ?"
            params.append(int(request.status == "active") if status_column == "active" else request.status)
        params.append(limit + 1)
        with self._connect() as conn:
            tables = {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if table not in tables:
                return [], ""
            rows = conn.execute(
                f"SELECT rowid AS row_cursor, {columns} FROM {table} "
                f"WHERE (? = 0 OR rowid < ?) AND (? = '' OR {search_sql}){status_sql} "
                "ORDER BY rowid DESC LIMIT ?",
                params,
            ).fetchall()
        has_more = len(rows) > limit
        rows = rows[:limit]
        items = [{key: row[key] for key in row.keys() if key != "row_cursor"} for row in rows]
        return items, str(rows[-1]["row_cursor"]) if has_more and rows else ""

    def _run_runtime_action(self, job_id: str) -> None:
        with self._jobs_lock:
            job = self._jobs[job_id]
            job.status = "running"
            job.started_at_ms = _now_ms()
        self.events.publish("runtime_job_changed", {"jobId": job_id, "status": "running", "action": job.action})
        try:
            command = self._command_for_action(job.action)
            completed = subprocess.run(command, cwd=self.repo_root, text=True, capture_output=True, timeout=90, check=False)
            if completed.returncode != 0:
                raise RuntimeError((completed.stderr or completed.stdout or f"exit {completed.returncode}").strip()[-1000:])
            result = {"exitCode": completed.returncode, "output": (completed.stdout or "").strip()[-1000:]}
            with self._revision_lock:
                self._runtime_revision += 1
            with self._jobs_lock:
                job.status = "succeeded"
                job.result = result
                job.finished_at_ms = _now_ms()
        except Exception as exc:
            with self._jobs_lock:
                job.status = "failed"
                job.error = str(exc)
                job.finished_at_ms = _now_ms()
        self._audit("runtime_action_finished", "runtime", job.action, {"jobId": job_id}, job.payload())
        self.events.publish("runtime_health_changed", {**self.revision().payload(), "job": job.payload()})

    def _command_for_action(self, action: str) -> list[str]:
        uid = str(os.getuid())
        squirrel = str(Path.home() / "Library/Input Methods/Squirrel.app/Contents/MacOS/Squirrel")
        commands = {
            "restart_sidecar": ["launchctl", "kickstart", "-k", f"gui/{uid}/com.rag-ime.sidecar"],
            "restart_predictor": ["launchctl", "kickstart", "-k", f"gui/{uid}/com.rag-ime.mlx-predictor"],
            "redeploy_rime": [str(self.repo_root / "scripts/install_squirrel_rag_config.sh")],
            "register_input_source": [squirrel, "--register-input-source"],
            "repair_launch_agents": [str(self.repo_root / "scripts/restart_rag_ime_runtime.sh")],
            "open_accessibility_settings": ["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"],
            "stop_ai": [str(self.repo_root / "scripts/stop_rag_ime_runtime.sh")],
            "resume_ai": [str(self.repo_root / "scripts/restart_rag_ime_runtime.sh")],
        }
        return commands[action]

    def _audit(
        self,
        action: str,
        target_type: str,
        target_id: str,
        payload: Mapping[str, object],
        result: Mapping[str, object],
    ) -> int:
        with self._connect() as conn:
            return int(record_management_audit(conn, action=action, target_type=target_type, target_id=target_id, payload=payload, result=result))

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return _ConnectionContext(conn)


class _ConnectionContext:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def __enter__(self) -> sqlite3.Connection:
        return self.conn

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if exc_type is None:
            self.conn.commit()
        else:
            self.conn.rollback()
        self.conn.close()


_RUNTIME_ACTIONS = {
    "restart_sidecar",
    "restart_predictor",
    "redeploy_rime",
    "register_input_source",
    "repair_launch_agents",
    "open_accessibility_settings",
    "stop_ai",
    "resume_ai",
}


def page_request(payload: Mapping[str, object]) -> PageRequest:
    try:
        limit = int(payload.get("limit") or 50)
    except (TypeError, ValueError):
        limit = 50
    return PageRequest(
        limit=max(1, min(limit, 100)),
        cursor=str(payload.get("cursor") or ""),
        query=str(payload.get("query") or "").strip(),
        status=str(payload.get("status") or payload.get("filter") or "").strip(),
        kind=str(payload.get("kind") or "").strip(),
    )


def _component(component_id: str, ok: bool, detail: str, metadata: Mapping[str, object]) -> dict[str, object]:
    return {
        "id": component_id,
        "ok": ok,
        "status": "healthy" if ok else "unavailable",
        "detail": detail,
        "metadata": dict(metadata),
    }


def _safe_mapping(provider: Callable[[], Mapping[str, object]]) -> dict[str, object]:
    try:
        return dict(provider())
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _nested(settings: Mapping[str, object], key: str, default: object = None) -> object:
    cursor: object = settings
    for part in key.split("."):
        if not isinstance(cursor, Mapping) or part not in cursor:
            return default
        cursor = cursor[part]
    return cursor


def _profile_name(settings: Mapping[str, object]) -> str:
    if not bool(_nested(settings, "interaction.postCommit.enabled", True)):
        return "安全模式"
    if bool(_nested(settings, "rag.lanes.tagMemo", False)) and bool(_nested(settings, "rag.lanes.timeDailyBook", False)):
        return "记忆增强"
    return "标准模式"


def _cursor_int(value: str) -> int:
    try:
        return max(0, int(value or 0))
    except ValueError:
        return 0


def _text_hash(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _redacted_preview(value: str) -> str:
    compact = " ".join(value.split())
    if not compact:
        return ""
    return f"{compact[:8]}...（{len(compact)} 字）" if len(compact) > 8 else f"{len(compact)} 字内容"


def _now_ms() -> int:
    return int(time.time() * 1000)
