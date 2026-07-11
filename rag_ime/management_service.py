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

from .memory_actions import execute_memory_action
from .management_events import ManagementEventHub
from .management_models import MANAGEMENT_SCHEMA_VERSION, ManagementRevision, PageRequest, RuntimeJob
from .runtime_config import RuntimeConfigSnapshot
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
        runtime_config_provider: Callable[[], RuntimeConfigSnapshot],
        last_prediction_provider: Callable[[], Mapping[str, object]] | None = None,
        cache_invalidator: Callable[[], object] | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.project = project
        self.repo_root = Path(repo_root)
        self.settings_store = settings_store
        self.health_provider = health_provider
        self.input_source_provider = input_source_provider
        self.predictor_provider = predictor_provider
        self.runtime_config_provider = runtime_config_provider
        self.last_prediction_provider = last_prediction_provider or (lambda: {})
        self.cache_invalidator = cache_invalidator
        self.events = ManagementEventHub()
        self._jobs: dict[str, RuntimeJob] = {}
        self._jobs_lock = threading.RLock()
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="rag-ime-management")

    def close(self) -> None:
        # A closed management service must not keep audit/database work alive.
        # Otherwise callers can observe a terminal job and remove its runtime
        # directory while the worker is still persisting the final audit row.
        self._executor.shutdown(wait=True, cancel_futures=True)

    def revision(
        self,
        *,
        audit_id: int | None = None,
        snapshot: RuntimeConfigSnapshot | None = None,
    ) -> ManagementRevision:
        current = snapshot or self.runtime_config_provider()
        return ManagementRevision(current.settings_revision, current.runtime_revision, audit_id)

    def runtime_config(self) -> dict[str, object]:
        snapshot = self.runtime_config_provider()
        return {
            **self.revision(snapshot=snapshot).payload(),
            "ok": True,
            "runtimeConfig": snapshot.payload(),
        }

    def settings_changed(
        self,
        *,
        audit_id: int,
        changed_keys: list[str],
        snapshot: RuntimeConfigSnapshot | None = None,
    ) -> dict[str, object]:
        snapshot = snapshot or self.runtime_config_provider()
        revision = self.revision(audit_id=audit_id, snapshot=snapshot)
        self.events.publish(
            "settings_changed",
            {**revision.payload(), "changedKeys": changed_keys, "runtimeConfig": snapshot.payload()},
        )
        return {**revision.payload(), "runtimeConfig": snapshot.payload()}

    def overview(self) -> dict[str, object]:
        health = _safe_mapping(self.health_provider)
        input_source = _safe_mapping(self.input_source_provider)
        predictor = _safe_mapping(self.predictor_provider)
        last_prediction = _safe_mapping(self.last_prediction_provider)
        snapshot = self.runtime_config_provider()
        counts = self._summary_counts()
        user_bundle = Path.home() / "Library/Input Methods/Squirrel.app"
        system_bundle = Path("/Library/Input Methods/Squirrel.app")
        components = self._components(
            health=health,
            input_source=input_source,
            predictor=predictor,
            runtime_config=snapshot,
            last_prediction=last_prediction,
        )
        return {
            **self.revision(snapshot=snapshot).payload(),
            "ok": True,
            "project": self.project,
            "profile": snapshot.profile,
            "aiPaused": not snapshot.post_commit.enabled,
            "runtimeConfig": snapshot.payload(),
            "components": components,
            "canonicalSquirrel": {
                "ok": user_bundle.exists(),
                "path": str(user_bundle),
                "duplicateSystemBundle": system_bundle.exists(),
            },
            "memory": counts,
            "lastPrediction": last_prediction,
        }

    def runtime_status(self) -> dict[str, object]:
        health = _safe_mapping(self.health_provider)
        input_source = _safe_mapping(self.input_source_provider)
        predictor = _safe_mapping(self.predictor_provider)
        last_prediction = _safe_mapping(self.last_prediction_provider)
        snapshot = self.runtime_config_provider()
        return {
            **self.revision(snapshot=snapshot).payload(),
            "ok": True,
            "components": self._components(
                health=health,
                input_source=input_source,
                predictor=predictor,
                runtime_config=snapshot,
                last_prediction=last_prediction,
            ),
            "eventSubscribers": self.events.subscriber_count,
            "runtimeConfig": snapshot.payload(),
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
        if action in _EXTERNAL_SUPERVISOR_ACTIONS:
            self._mark_external_supervisor_required(job)
            return {
                **self.revision(audit_id=audit_id).payload(),
                "ok": True,
                "job": job.payload(),
                "jobId": job.job_id,
            }
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
        mutation = execute_memory_action(
            connection_factory=self._connect,
            payload=payload,
            cache_invalidator=self.cache_invalidator,
            event_publisher=self.events.publish,
        )
        item_id = str(mutation["memoryId"])
        item_type = str(mutation["targetType"])
        action = str(mutation["action"])
        audit_id = self._audit(
            f"memory_{action}",
            item_type,
            item_id,
            dict(payload),
            mutation,
        )
        self._bump_runtime_revision()
        revision = self.revision(audit_id=int(audit_id))
        return {
            **mutation,
            "mutationSchemaVersion": mutation["schemaVersion"],
            **revision.payload(),
            "ok": True,
            "id": item_id,
            "itemId": item_id,
            "memoryId": item_id,
        }

    def _components(
        self,
        *,
        health: Mapping[str, object],
        input_source: Mapping[str, object],
        predictor: Mapping[str, object],
        runtime_config: RuntimeConfigSnapshot,
        last_prediction: Mapping[str, object],
    ) -> dict[str, dict[str, object]]:
        sidecar_ok = bool(health.get("ok"))
        predictor_payload = predictor.get("predictor") if isinstance(predictor.get("predictor"), Mapping) else predictor
        configured = predictor_payload.get("configured") is True
        capability_probe = _mapping(predictor_payload.get("capabilityProbe"))
        probe_ok = capability_probe.get("ok") is True
        predictor_ok = configured and probe_ok
        predictor_detail = _predictor_detail(configured=configured, probe=capability_probe)
        expected_input_source = _string_value(
            input_source.get("expectedInputSourceId")
            or input_source.get("inputSourceId")
            or input_source.get("id")
            or os.environ.get("RAG_IME_SQUIRREL_INPUT_SOURCE_ID")
        )
        current_input_source = _string_value(input_source.get("currentInputSourceId") or input_source.get("current"))
        selected = bool(expected_input_source and current_input_source == expected_input_source)
        input_source_metadata = dict(input_source)
        input_source_metadata.update(
            {
                "expectedInputSourceId": expected_input_source,
                "currentInputSourceId": current_input_source,
                "idMatchesExpected": selected,
            }
        )
        foreground = _foreground_context_component(sidecar_ok=sidecar_ok, last_prediction=last_prediction)
        compiler = self._compiler_component()
        return {
            "inputMethod": _component(
                "inputMethod",
                selected,
                "已选择" if selected else "当前输入源不匹配",
                input_source_metadata,
            ),
            "sidecar": _component("sidecar", sidecar_ok, "运行中" if sidecar_ok else "不可用", health),
            "predictor": _component("predictor", predictor_ok, predictor_detail, predictor_payload),
            "foregroundContext": foreground,
            "hybridRag": _component(
                "hybridRag",
                runtime_config.hybrid_rag.enabled,
                "已启用" if runtime_config.hybrid_rag.enabled else "未启用",
                {},
            ),
            "memoryCompiler": compiler,
            "sqlite": _component("sqlite", self.db_path.exists(), "正常" if self.db_path.exists() else "缺失", {"path": str(self.db_path)}),
        }

    def _compiler_component(self) -> dict[str, object]:
        metadata: dict[str, object] = {"project": self.project}
        try:
            with self._connect() as conn:
                tables = {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if "memory_compile_state" not in tables:
                    return _component("memoryCompiler", False, "编译状态表不存在", metadata)
                row = conn.execute(
                    "SELECT last_compiled_event_id, last_run_ms, pending_event_count, last_bundle_hash "
                    "FROM memory_compile_state WHERE project = ?",
                    (self.project,),
                ).fetchone()
                if row is None:
                    return _component("memoryCompiler", False, "尚无成功编译记录", metadata)
                last_event_id = int(row["last_compiled_event_id"] or 0)
                pending = int(row["pending_event_count"] or 0)
                if "input_events" in tables:
                    pending = int(
                        conn.execute(
                            "SELECT COUNT(*) FROM input_events WHERE id > ? AND (project = ? OR project = '')",
                            (last_event_id, self.project),
                        ).fetchone()[0]
                    )
                last_run_ms = int(row["last_run_ms"] or 0)
                bundle_hash = str(row["last_bundle_hash"] or "")
        except Exception as exc:
            return _component("memoryCompiler", False, "读取编译状态失败", {**metadata, "error": str(exc)})
        metadata.update(
            {
                "lastCompiledEventId": last_event_id,
                "lastRunMs": last_run_ms,
                "lastRunAgeMs": max(0, _now_ms() - last_run_ms) if last_run_ms else None,
                "pendingEventCount": pending,
                "lastBundleHash": bundle_hash,
            }
        )
        ok = bool(last_run_ms and bundle_hash)
        detail = f"待整理 {pending} 条" if ok else "编译记录不完整"
        return _component("memoryCompiler", ok, detail, metadata)

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
        limit = request.limit
        cursor = _cursor_int(request.cursor)
        like = f"%{request.query}%"
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    mi.id AS row_cursor,
                    mi.memory_id,
                    mi.text,
                    mi.normalized_text,
                    mi.project,
                    mi.app,
                    mi.status,
                    mi.confidence,
                    mi.quality_score,
                    mi.updated_at_ms,
                    COALESCE(ps.input_frequency, 0) AS use_count,
                    COALESCE(ps.first_seen_ms, mi.created_at_ms) AS first_seen_ms,
                    COALESCE(ps.last_seen_ms, mi.updated_at_ms) AS last_seen_ms
                FROM memory_items mi
                LEFT JOIN phrase_stats ps ON ps.committed_text = mi.text
                WHERE mi.kind = 'phrase'
                  AND mi.privacy_class != 'sensitive'
                  AND (? = 0 OR mi.id < ?)
                  AND (? = '' OR mi.text LIKE ? OR mi.normalized_text LIKE ? OR mi.project LIKE ? OR mi.app LIKE ?)
                  AND (? = '' OR mi.status = ?)
                ORDER BY mi.id DESC
                LIMIT ?
                """,
                (
                    cursor,
                    cursor,
                    request.query,
                    like,
                    like,
                    like,
                    like,
                    request.status,
                    request.status,
                    limit + 1,
                ),
            ).fetchall()
        has_more = len(rows) > limit
        rows = rows[:limit]
        items: list[dict[str, object]] = []
        for row in rows:
            memory_id = str(row["memory_id"])
            text = str(row["text"] or "")
            text_hash = _text_hash(text)
            items.append(
                {
                    "id": memory_id,
                    "itemId": memory_id,
                    "memoryId": memory_id,
                    "type": "phrase",
                    "normalizedText": str(row["normalized_text"] or ""),
                    "textHash": text_hash,
                    "originalTextHash": text_hash,
                    "textChars": len(text),
                    "textPreview": _redacted_preview(text),
                    "project": str(row["project"] or ""),
                    "app": str(row["app"] or ""),
                    "status": str(row["status"]),
                    "confidence": float(row["confidence"]),
                    "qualityScore": float(row["quality_score"]),
                    "useCount": int(row["use_count"]),
                    "firstSeenMs": int(row["first_seen_ms"]),
                    "lastSeenMs": int(row["last_seen_ms"]),
                    "updatedAtMs": int(row["updated_at_ms"]),
                }
            )
        next_cursor = str(rows[-1]["row_cursor"]) if has_more and rows else ""
        return items, next_cursor

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
        terminal_status = "succeeded"
        result: dict[str, Any] = {}
        error = ""
        try:
            if job.action in _AI_TOGGLE_ACTIONS:
                result = self._apply_ai_toggle(job.action)
            else:
                command = self._command_for_action(job.action)
                completed = subprocess.run(
                    command,
                    cwd=self._source_root() or self.repo_root,
                    text=True,
                    capture_output=True,
                    timeout=90,
                    check=False,
                )
                result = {
                    "exitCode": completed.returncode,
                    "stdout": (completed.stdout or "").strip()[-1000:],
                    "stderr": (completed.stderr or "").strip()[-1000:],
                    "command": command,
                }
                if completed.returncode != 0:
                    raise RuntimeError((completed.stderr or completed.stdout or f"exit {completed.returncode}").strip()[-1000:])
                self._bump_runtime_revision()
        except subprocess.TimeoutExpired as exc:
            terminal_status = "timed_out"
            result = {
                "exitCode": None,
                "stdout": _tail_text(exc.stdout),
                "stderr": _tail_text(exc.stderr),
                "command": list(exc.cmd) if isinstance(exc.cmd, (list, tuple)) else [str(exc.cmd)],
            }
            error = "runtime action timed out after 90 seconds"
        except Exception as exc:
            terminal_status = "failed"
            error = str(exc)

        finished_at_ms = _now_ms()
        with self._jobs_lock:
            job.result = result
            job.error = error
            audit_payload = {
                **job.payload(),
                "status": terminal_status,
                "finishedAtMs": finished_at_ms,
            }

        # Persist the final audit before publishing the terminal state. A
        # terminal job therefore means all worker-owned durable writes are
        # complete, not merely that the child process has exited.
        try:
            self._audit("runtime_action_finished", "runtime", job.action, {"jobId": job_id}, audit_payload)
        except Exception as exc:
            terminal_status = "failed"
            audit_error = f"runtime audit persistence failed: {exc}"
            error = f"{error}; {audit_error}" if error else audit_error

        with self._jobs_lock:
            job.status = terminal_status
            job.result = result
            job.error = error
            job.finished_at_ms = finished_at_ms
            terminal_payload = job.payload()
        self.events.publish(
            "runtime_job_changed",
            {"jobId": job_id, "status": terminal_status, "action": job.action, "error": error},
        )
        self.events.publish("runtime_health_changed", {**self.revision().payload(), "job": terminal_payload})

    def _command_for_action(self, action: str) -> list[str]:
        if action in _EXTERNAL_SUPERVISOR_ACTIONS:
            raise RuntimeError(f"{action} requires an external supervisor")
        if action in _AI_TOGGLE_ACTIONS:
            raise RuntimeError(f"{action} is a live setting action and does not execute a process")
        uid = str(os.getuid())
        squirrel = str(Path.home() / "Library/Input Methods/Squirrel.app/Contents/MacOS/Squirrel")
        commands = {
            "restart_predictor": ["launchctl", "kickstart", "-k", f"gui/{uid}/com.rag-ime.mlx-predictor"],
            "redeploy_rime": ["/bin/bash", str(self._helper_path("install_squirrel_rag_config.sh"))],
            "register_input_source": [squirrel, "--register-input-source"],
            "open_accessibility_settings": ["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"],
        }
        return commands[action]

    def _apply_ai_toggle(self, action: str) -> dict[str, object]:
        enabled = action == "resume_ai"
        update = self.settings_store.update_settings(
            {"interaction.postCommit.enabled": enabled},
            updated_by="runtime-control",
        )
        snapshot = self.runtime_config_provider()
        revision = self.settings_changed(
            audit_id=update.audit_id,
            changed_keys=list(update.changed_keys),
            snapshot=snapshot,
        )
        return {
            "exitCode": 0,
            "aiPaused": not enabled,
            "changedKeys": list(update.changed_keys),
            "settingsRevision": revision["settingsRevision"],
            "runtimeRevision": revision["runtimeRevision"],
        }

    def _mark_external_supervisor_required(self, job: RuntimeJob) -> None:
        now = _now_ms()
        helper: list[str]
        if job.action == "restart_sidecar":
            helper = ["launchctl", "kickstart", "-k", f"gui/{os.getuid()}/com.rag-ime.sidecar"]
        else:
            helper_path = self._helper_path("repair_rag_ime_launch_agents.sh", required=False)
            helper = ["/bin/bash", str(helper_path)] if helper_path is not None else []
        with self._jobs_lock:
            job.status = "external-supervisor-required"
            job.started_at_ms = now
            job.finished_at_ms = now
            job.result = {
                "code": "external-supervisor-required",
                "externalCommand": helper,
            }
            job.error = (
                "This action would terminate the Sidecar that owns this in-memory job; "
                "the Sidecar refuses it until a separate external supervisor executes the command."
            )
        self._audit("runtime_action_finished", "runtime", job.action, {"jobId": job.job_id}, job.payload())
        self.events.publish(
            "runtime_job_changed",
            {"jobId": job.job_id, "status": job.status, "action": job.action, "error": job.error},
        )

    def _source_root(self) -> Path | None:
        candidates = [
            Path(value).expanduser()
            for value in (os.environ.get("RAG_IME_SOURCE_ROOT"), os.environ.get("RAG_IME_REPO_ROOT"))
            if value
        ]
        candidates.append(self.repo_root)
        for candidate in candidates:
            if candidate.is_dir():
                return candidate
        return None

    def _helper_path(self, name: str, *, required: bool = True) -> Path | None:
        source_root = self._source_root()
        candidate = source_root / "scripts" / name if source_root is not None else None
        if candidate is not None and candidate.is_file():
            return candidate
        if required:
            root_hint = str(source_root) if source_root is not None else "<unset>"
            raise RuntimeError(
                f"runtime helper is unavailable: {name}; set RAG_IME_SOURCE_ROOT to a source checkout (resolved root: {root_hint})"
            )
        return None

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

    def _bump_runtime_revision(self) -> int:
        # Resolve once so the persistent row contains the current snapshot hash.
        self.runtime_config_provider()
        return self.settings_store.bump_runtime_config_revision()

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

_AI_TOGGLE_ACTIONS = {"stop_ai", "resume_ai"}
_EXTERNAL_SUPERVISOR_ACTIONS = {"restart_sidecar", "repair_launch_agents"}


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


def _predictor_detail(*, configured: bool, probe: Mapping[str, object]) -> str:
    if not configured:
        return "未配置"
    if not probe:
        return "已配置，但没有可用性探测证据"
    if probe.get("ok") is not True:
        error = _string_value(probe.get("error"))
        return f"探测失败：{error}" if error else "探测失败"
    model = Path(_string_value(probe.get("model"))).name
    fingerprint = _string_value(probe.get("modelFingerprint"))
    parts = ["已配置且探测通过"]
    if model:
        parts.append(model)
    if fingerprint.startswith("sha256:"):
        parts.append(fingerprint.removeprefix("sha256:")[:12])
    return " · ".join(parts)


def _foreground_context_component(
    *,
    sidecar_ok: bool,
    last_prediction: Mapping[str, object],
) -> dict[str, object]:
    nested = _mapping(last_prediction.get("foregroundContext"))
    injection = _mapping(last_prediction.get("contextInjection") or last_prediction.get("injection"))
    evidence = {**dict(last_prediction), **nested}
    source = _string_value(
        evidence.get("source") or evidence.get("contextSource") or evidence.get("foregroundContextSource")
    )
    created_at_ms = _integer_value(
        evidence.get("capturedAtMs") or evidence.get("createdAtMs") or evidence.get("foregroundCapturedAtMs")
    )
    reported_freshness = _integer_value(evidence.get("freshnessMs") or evidence.get("captureAgeMs"), default=-1)
    freshness_ms = reported_freshness if reported_freshness >= 0 else (
        max(0, _now_ms() - created_at_ms) if created_at_ms > 0 else -1
    )
    freshness_limit_ms = max(
        1_000,
        _integer_value(os.environ.get("RAG_IME_MANAGEMENT_FOREGROUND_FRESH_MS"), default=30_000),
    )
    applied = _first_bool(
        evidence.get("applied"),
        evidence.get("foregroundContextApplied"),
        injection.get("success"),
    )
    commit_text_matched = _first_bool(
        evidence.get("commitTextMatched"),
        evidence.get("commit_text_matched"),
    )
    failure = _string_value(
        evidence.get("captureFailureReason")
        or evidence.get("foregroundReason")
        or evidence.get("error")
        or injection.get("error")
    )
    metadata = {
        "source": source,
        "capturedAtMs": created_at_ms,
        "freshnessMs": freshness_ms,
        "freshnessLimitMs": freshness_limit_ms,
        "applied": applied,
        "commitTextMatched": commit_text_matched,
        "failureReason": failure,
        "requestId": _string_value(last_prediction.get("requestId")),
    }
    if not sidecar_ok:
        return _component("foregroundContext", False, "Sidecar 不可用", metadata)
    if failure:
        return _component("foregroundContext", False, f"上下文采集失败：{failure}", metadata)
    if source not in {"accessibility", "text_input_client"}:
        return _component("foregroundContext", False, "尚无可信前台上下文来源证据", metadata)
    if freshness_ms < 0 or freshness_ms > freshness_limit_ms:
        return _component("foregroundContext", False, "前台上下文证据已过期或缺少时间戳", metadata)
    if applied is not True:
        return _component("foregroundContext", False, "尚无上下文成功注入证据", metadata)
    if commit_text_matched is not True:
        return _component("foregroundContext", False, "尚无提交文本匹配证据", metadata)
    return _component("foregroundContext", True, "最近前台上下文已采集并注入", metadata)


def _safe_mapping(provider: Callable[[], Mapping[str, object]]) -> dict[str, object]:
    try:
        return dict(provider())
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _mapping(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, Mapping) else {}


def _string_value(value: object) -> str:
    return str(value or "").strip()


def _integer_value(value: object, *, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _first_bool(*values: object) -> bool | None:
    for value in values:
        if isinstance(value, bool):
            return value
    return None


def _tail_text(value: object) -> str:
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    return str(value or "").strip()[-1000:]


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
