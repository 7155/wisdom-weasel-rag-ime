from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from typing import Any, Callable, Mapping

from .agent_memory_sources import AgentMemorySourceStore
from .config_portability import (
    apply_user_configuration,
    export_portable_backup,
    provider_metadata,
    preview_portable_restore,
    preview_user_configuration,
    restore_portable_backup,
)
from .daily_planner import (
    planning_assistant_reply,
    planning_dashboard,
    resolve_completion_suggestion,
    save_daily_plan,
    save_goal,
    save_task,
    task_action,
    undo_task_event,
)
from .memory_actions import execute_memory_action
from .memory_book_lifecycle import archive_inactive_memory_books, set_memory_book_archive_status
from .memory_graph_read import read_memory_entity, read_memory_graph
from .memory_ingest import looks_sensitive, normalize_text
from .memory_ownership import normalize_memory_owner, sql_memory_owner_predicate
from .management_events import ManagementEventHub
from .management_models import MANAGEMENT_SCHEMA_VERSION, ManagementRevision, PageRequest, RuntimeJob
from .management_work_contract import (
    ManagementWorkContract,
    ManagementWorkError,
    StoredReceipt,
    WorkExecution,
    canonical_payload_sha256,
)
from .retrieval_docs import rebuild_retrieval_docs
from .runtime_config import RuntimeConfigSnapshot
from .settings_store import ManagementSettingsStore, record_management_audit
from .text_utils import compact_whitespace
from .voice_control import read_voice_control_status, resolve_voice_support_directory


def _provider_configuration_hash(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


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
        deployment_provider: Callable[[], Mapping[str, object]] | None = None,
        cache_invalidator: Callable[[], object] | None = None,
        voice_support_directory: str | Path | None = None,
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
        self.deployment_provider = deployment_provider
        self.cache_invalidator = cache_invalidator
        self.voice_support_directory = (
            Path(voice_support_directory).expanduser()
            if voice_support_directory is not None
            else resolve_voice_support_directory(self.db_path)
        )
        self.events = ManagementEventHub()
        self.work_contract = ManagementWorkContract(db_path=self.db_path)
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

    def management_work_revision(
        self,
        conn: sqlite3.Connection,
        *,
        subject_revision: str,
    ) -> dict[str, object]:
        row = conn.execute(
            "SELECT runtime_revision FROM runtime_config_state WHERE singleton_id = 1"
        ).fetchone()
        runtime_revision = self.revision().runtime_revision if row is None else int(row[0])
        return {
            "runtimeRevision": runtime_revision,
            "subjectRevision": subject_revision,
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

    def configuration_import_preview(self, payload: Mapping[str, object]) -> dict[str, object]:
        _require_exact_keys(payload, required={"path"}, optional=set())
        return {
            **self.revision().payload(),
            **preview_user_configuration(payload, settings_store=self.settings_store),
        }

    def configuration_import_apply(self, payload: Mapping[str, object]) -> dict[str, object]:
        _require_exact_keys(
            payload,
            required={
                "path",
                "expectedRuntimeRevision",
                "previewToken",
                "confirmText",
            },
            optional={"confirmRemoteModel"},
        )
        current_revision = self.revision().runtime_revision
        expected_revision = _strict_nonnegative_int(
            payload.get("expectedRuntimeRevision"),
            field="expectedRuntimeRevision",
        )
        if expected_revision != current_revision:
            raise ValueError("configuration changed after preview; preview it again")
        current_preview = preview_user_configuration(
            {"path": payload.get("path")},
            settings_store=self.settings_store,
        )
        if not _constant_time_text_equal(
            payload.get("previewToken"),
            current_preview.get("configurationHash"),
        ):
            raise ValueError("configuration file changed after preview; preview it again")
        if not _constant_time_text_equal(
            payload.get("confirmText"),
            current_preview.get("requiresConfirmation"),
        ):
            raise ValueError("configuration import requires explicit confirmation")
        result = apply_user_configuration(payload, settings_store=self.settings_store)
        audit_id = int(result.get("auditId") or 0)
        changed_keys = [str(item) for item in result.get("changedKeys", [])]
        snapshot = self.runtime_config_provider()
        if changed_keys:
            self.settings_changed(audit_id=audit_id, changed_keys=changed_keys, snapshot=snapshot)
        self.events.publish("configuration_imported", {"changedKeys": changed_keys})
        return {**self.revision(audit_id=audit_id or None, snapshot=snapshot).payload(), **result}

    def provider_configuration(self) -> dict[str, object]:
        providers = provider_metadata(support_directory=self._provider_support_directory())
        return {
            "schemaVersion": "rag-ime.provider-configuration.v1",
            "ok": True,
            **self.revision().payload(),
            "configurationHash": _provider_configuration_hash(providers),
            "providers": providers,
        }

    def provider_configuration_apply(self, payload: Mapping[str, object]) -> dict[str, object]:
        slot = compact_whitespace(str(payload.get("slot") or ""))
        if slot not in {"instant", "knowledge", "voice"}:
            raise ValueError("provider slot must be instant, knowledge, or voice")
        if any(key in payload for key in ("apiKey", "accessToken", "headers")):
            raise ValueError("provider secrets and custom headers are not accepted by this operation")

        expected_hash = compact_whitespace(str(payload.get("expectedConfigurationHash") or ""))
        current = self.provider_configuration()
        if not expected_hash or expected_hash != current["configurationHash"]:
            raise ValueError("provider configuration changed after the approval preview was created")

        desired: dict[str, object] = {}
        profile_keys = ("provider",) if slot == "voice" else ("provider", "endpoint", "model")
        for key in profile_keys:
            if key in payload:
                desired[key] = compact_whitespace(str(payload.get(key) or ""))
        if not desired:
            raise ValueError("provider configuration did not include any changes")

        config = {
            "schemaVersion": "rag-ime.user-config.v1",
            "providers": {slot: desired},
        }
        preview = preview_user_configuration({"config": config}, settings_store=self.settings_store)
        if preview.get("valid") is not True:
            errors = preview.get("errors") if isinstance(preview.get("errors"), list) else []
            raise ValueError("; ".join(str(item) for item in errors) or "provider configuration is invalid")

        before_providers = current.get("providers") if isinstance(current.get("providers"), Mapping) else {}
        before = dict(before_providers.get(slot) or {}) if isinstance(before_providers.get(slot), Mapping) else {}
        result = apply_user_configuration(
            {"config": config},
            settings_store=self.settings_store,
            support_directory=self._provider_support_directory(),
        )
        after_status = self.provider_configuration()
        after_providers = (
            after_status.get("providers")
            if isinstance(after_status.get("providers"), Mapping)
            else {}
        )
        after = dict(after_providers.get(slot) or {}) if isinstance(after_providers.get(slot), Mapping) else {}
        audit_result = {
            "slot": slot,
            "before": before,
            "after": after,
            "secretsEchoed": False,
            "existingSecretPreserved": True,
        }
        audit_id = self._audit(
            "provider_configuration_apply",
            "provider_slot",
            slot,
            {
                "slot": slot,
                "provider": desired.get("provider", ""),
                "endpoint": desired.get("endpoint", ""),
                "model": desired.get("model", ""),
                "expectedConfigurationHash": expected_hash,
            },
            audit_result,
        )
        self._bump_runtime_revision()
        snapshot = self.runtime_config_provider()
        final_status = self.provider_configuration()
        self.events.publish(
            "provider_configuration_changed",
            {"slot": slot, "requiresRestart": True, "auditId": audit_id},
        )
        return {
            "schemaVersion": "rag-ime.provider-configuration-apply.v1",
            "ok": True,
            **self.revision(audit_id=audit_id, snapshot=snapshot).payload(),
            "slot": slot,
            "before": before,
            "after": after,
            "configurationHash": final_status["configurationHash"],
            "requiresRestart": True,
            "restartComponent": {
                "instant": "predictor",
                "knowledge": "sidecar",
                "voice": "voice",
            }[slot],
            "secretsEchoed": False,
            "existingSecretPreserved": True,
            "providerResultConfigured": bool(result.get("providers")),
        }

    def portable_backup_export(self, payload: Mapping[str, object]) -> dict[str, object]:
        _require_exact_keys(payload, required={"destination"}, optional=set())
        destination = compact_whitespace(str(payload.get("destination") or ""))
        if not destination:
            raise ValueError("backup destination is required")
        selected_destination = Path(destination).expanduser()
        if selected_destination.is_dir():
            destination = str(selected_destination / "rag-ime-backup.ragime-backup")
        result = export_portable_backup(
            db_path=self.db_path,
            settings_store=self.settings_store,
            destination=destination,
        )
        audit_id = self._audit("portable_backup_export", "backup", str(result.get("path") or ""), payload, result)
        return {**self.revision(audit_id=audit_id).payload(), **result}

    @staticmethod
    def _provider_support_directory() -> Path:
        configured = compact_whitespace(os.environ.get("RAG_IME_APP_SUPPORT_DIR", ""))
        if configured:
            return Path(configured).expanduser()
        return Path.home() / "Library" / "Application Support" / "RagIme"

    def portable_restore_preview(self, payload: Mapping[str, object]) -> dict[str, object]:
        _require_exact_keys(payload, required={"path"}, optional=set())
        source = compact_whitespace(str(payload.get("path") or ""))
        if not source:
            raise ValueError("backup path is required")
        return {**self.revision().payload(), **preview_portable_restore(archive_path=source)}

    def portable_restore_apply(self, payload: Mapping[str, object]) -> dict[str, object]:
        _require_exact_keys(
            payload,
            required={
                "path",
                "restoreToken",
                "confirmText",
                "expectedRuntimeRevision",
            },
            optional=set(),
        )
        source = compact_whitespace(str(payload.get("path") or ""))
        if not source:
            raise ValueError("backup path is required")
        current_revision = self.revision().runtime_revision
        expected_revision = _strict_nonnegative_int(
            payload.get("expectedRuntimeRevision"),
            field="expectedRuntimeRevision",
        )
        if expected_revision != current_revision:
            raise ValueError("local data changed after restore preview; preview it again")
        result = restore_portable_backup(
            archive_path=source,
            db_path=self.db_path,
            settings_store=self.settings_store,
            restore_token=compact_whitespace(str(payload.get("restoreToken") or "")),
            confirm_text=compact_whitespace(str(payload.get("confirmText") or "")),
        )
        if self.cache_invalidator is not None:
            self.cache_invalidator()
        snapshot = self.runtime_config_provider()
        audit_id = self._audit("portable_restore_apply", "backup", source, payload, result)
        self.events.publish("portable_restore_applied", {"path": source, "requiresRestart": True})
        return {**self.revision(audit_id=audit_id, snapshot=snapshot).payload(), **result}

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

    def runtime_action_preview(self, payload: Mapping[str, object]) -> dict[str, object]:
        current = {"runtimeRevision": self.revision().runtime_revision}
        try:
            _require_exact_keys(
                payload,
                required={"action", "expectedRuntimeRevision"},
                optional=set(),
            )
            action = compact_whitespace(str(payload.get("action") or ""))
            if action not in _DIAGNOSTICS_RUNTIME_ACTIONS:
                raise ManagementWorkError("invalid_request", f"unsupported diagnostics action: {action}")
            expected_runtime_revision = _strict_nonnegative_int(
                payload.get("expectedRuntimeRevision"),
                field="expectedRuntimeRevision",
            )
            if expected_runtime_revision != current["runtimeRevision"]:
                raise ManagementWorkError(
                    "revision_mismatch",
                    "The diagnostics runtime snapshot is stale.",
                    current_revision=current,
                )
            command_sha256 = _runtime_action_command_sha256(action)
            domain = {"action": action, "commandSha256": command_sha256}
            preview = self.work_contract.create_preview(
                path_id="diagnostics.action.start",
                payload=domain,
                expected_revision=current,
                required_confirm="apply",
                summary=_runtime_action_preview_summary(action),
            )
            return {
                **preview,
                "action": action,
                "commandSha256": command_sha256,
                "externalSupervisorRequired": action in _DIAGNOSTICS_EXTERNAL_ACTIONS,
            }
        except Exception as exc:
            return self.work_contract.error_payload(exc, current_revision=current)

    def runtime_action_start(self, payload: Mapping[str, object]) -> dict[str, object]:
        current = {"runtimeRevision": self.revision().runtime_revision}
        try:
            _require_exact_keys(
                payload,
                required={
                    "action",
                    "expectedRuntimeRevision",
                    "previewToken",
                    "payloadSha256",
                    "commandSha256",
                    "confirmText",
                },
                optional=set(),
            )
            action = compact_whitespace(str(payload.get("action") or ""))
            if action not in _DIAGNOSTICS_RUNTIME_ACTIONS:
                raise ManagementWorkError("invalid_request", f"unsupported diagnostics action: {action}")
            expected_runtime_revision = _strict_nonnegative_int(
                payload.get("expectedRuntimeRevision"),
                field="expectedRuntimeRevision",
            )
            if expected_runtime_revision != current["runtimeRevision"]:
                raise ManagementWorkError(
                    "revision_mismatch",
                    "The diagnostics action request revision is stale.",
                    current_revision=current,
                )
            command_sha256 = _runtime_action_command_sha256(action)
            if not _constant_time_text_equal(payload.get("commandSha256"), command_sha256):
                raise ManagementWorkError(
                    "command_hash_mismatch",
                    "The approved diagnostics command no longer matches the allowlisted action.",
                )
            domain = {"action": action, "commandSha256": command_sha256}
            job_id = str(uuid.uuid4())

            def current_revision(_conn: sqlite3.Connection) -> Mapping[str, object]:
                return {"runtimeRevision": self.revision().runtime_revision}

            def execute(_conn: sqlite3.Connection) -> WorkExecution:
                job = RuntimeJob(job_id=job_id, action=action, created_at_ms=_now_ms())
                with self._jobs_lock:
                    self._jobs[job_id] = job
                return WorkExecution(
                    result={
                        "schemaVersion": "rag-ime.diagnostics-runtime-job.v1",
                        "ok": True,
                        "jobId": job_id,
                        "action": action,
                        "commandSha256": command_sha256,
                        "externalSupervisorRequired": action in _DIAGNOSTICS_EXTERNAL_ACTIONS,
                    },
                    audit_action="runtime_action_queued",
                    target_type="runtime",
                    target_id=action,
                )

            response = self.work_contract.execute_apply(
                path_id="diagnostics.action.start",
                payload=domain,
                preview_token=str(payload.get("previewToken") or ""),
                payload_sha256=str(payload.get("payloadSha256") or ""),
                confirm_text=str(payload.get("confirmText") or ""),
                current_revision=current_revision,
                executor=execute,
            )
            with self._jobs_lock:
                job = self._jobs[job_id]
            if action in _DIAGNOSTICS_EXTERNAL_ACTIONS:
                self._mark_diagnostics_external_supervisor_required(
                    job,
                    payload_sha256=str(response.get("payloadSha256") or ""),
                    command_sha256=command_sha256,
                )
            else:
                self._executor.submit(self._run_runtime_action, job_id)
            return response
        except Exception as exc:
            return self.work_contract.error_payload(exc, current_revision=current)

    def runtime_job(self, job_id: str) -> dict[str, object]:
        with self._jobs_lock:
            job = self._jobs.get(job_id)
        if job is None:
            return {**self.revision().payload(), "ok": False, "error": "job not found", "jobId": job_id}
        return {**self.revision().payload(), "ok": True, "job": job.payload()}

    def memory_summary(self) -> dict[str, object]:
        return {**self.revision().payload(), "ok": True, **self._summary_counts()}

    def memory_graph(self, payload: Mapping[str, object]) -> dict[str, object]:
        with self._connect() as conn:
            conn.execute("BEGIN")
            graph = read_memory_graph(conn, payload, default_project=self.project)
        return {**self.revision().payload(), **graph}

    def memory_entity(
        self,
        kind: str,
        entity_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        with self._connect() as conn:
            conn.execute("BEGIN")
            entity = read_memory_entity(
                conn,
                kind,
                entity_id,
                payload,
                default_project=self.project,
            )
        return {**self.revision().payload(), **entity}

    def memory_page(self, kind: str, request: PageRequest) -> dict[str, object]:
        handlers = {
            "books": self._memory_books,
            "atoms": self._memory_atoms,
            "tags": self._memory_tags,
            "phrases": self._memory_phrases,
            "evidence": self._memory_evidence,
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
            "rawTextVisible": kind
            in {
                "books",
                "atoms",
                "phrases",
                "evidence",
                "tags",
                "groups",
                "negative",
            },
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
                  AND NOT EXISTS (
                    SELECT 1
                    FROM memory_tombstones tombstone
                    WHERE tombstone.target_type = 'memory_id'
                      AND tombstone.target_value = ('event:' || input_events.id)
                      AND tombstone.active = 1
                  )
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

    def history_detail(self, event_id: object) -> dict[str, object]:
        parsed_event_id = _strict_bounded_int(
            event_id,
            field="eventId",
            minimum=1,
            maximum=9_223_372_036_854_775_807,
        )
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT event.id, event.created_at_ms, event.source, event.committed_text,
                       event.app, event.project, event.candidate_rank,
                       event.provider_name, event.context_group_id,
                       event.context_group_level, state.accepted_count,
                       state.skipped_count, state.pinned, state.downranked,
                       state.deleted, state.updated_at_ms,
                       EXISTS (
                           SELECT 1
                           FROM memory_tombstones tombstone
                           WHERE tombstone.target_type = 'memory_id'
                             AND tombstone.target_value = ('event:' || event.id)
                             AND tombstone.active = 1
                       ) AS hidden
                FROM input_events event
                LEFT JOIN memory_state state ON state.event_id = event.id
                WHERE event.id = ?
                LIMIT 1
                """,
                (parsed_event_id,),
            ).fetchone()
            latest_action = conn.execute(
                """
                SELECT action_type, created_at_ms
                FROM memory_actions
                WHERE event_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (parsed_event_id,),
            ).fetchone()
        if row is None:
            return {
                **self.revision().payload(),
                "ok": False,
                "errorCode": "not_found",
                "error": "History record not found.",
            }

        feedback_available = row["accepted_count"] is not None
        feedback: dict[str, object] = {"available": feedback_available}
        if feedback_available:
            feedback.update(
                {
                    "acceptedCount": int(row["accepted_count"]),
                    "skippedCount": int(row["skipped_count"]),
                    "pinned": bool(row["pinned"]),
                    "downranked": bool(row["downranked"]),
                    "deleted": bool(row["deleted"]),
                    "updatedAtMs": int(row["updated_at_ms"]),
                }
            )
        if latest_action is not None:
            feedback["latestAction"] = str(latest_action["action_type"])
            feedback["latestActionAtMs"] = int(latest_action["created_at_ms"])

        return {
            **self.revision().payload(),
            "ok": True,
            "item": {
                "id": int(row["id"]),
                "createdAtMs": int(row["created_at_ms"]),
                "source": str(row["source"]),
                "text": str(row["committed_text"]),
                "textChars": len(str(row["committed_text"])),
                "app": str(row["app"]),
                "project": str(row["project"]),
                "provider": str(row["provider_name"]),
                "candidateRank": (
                    int(row["candidate_rank"])
                    if row["candidate_rank"] is not None
                    else None
                ),
                "groupId": str(row["context_group_id"]),
                "groupLevel": str(row["context_group_level"]),
                "status": (
                    "hidden"
                    if bool(row["hidden"]) or bool(row["deleted"])
                    else "active"
                ),
                "feedback": feedback,
            },
            "rawTextVisible": True,
        }

    def history_tombstone_preview(self, payload: Mapping[str, object]) -> dict[str, object]:
        current = {"runtimeRevision": self.revision().runtime_revision}
        try:
            _require_exact_keys(
                payload,
                required={"eventId", "expectedRuntimeRevision"},
                optional={"reason"},
            )
            event_id = _strict_bounded_int(
                payload.get("eventId"),
                field="eventId",
                minimum=1,
                maximum=9_223_372_036_854_775_807,
            )
            expected_runtime_revision = _strict_nonnegative_int(
                payload.get("expectedRuntimeRevision"),
                field="expectedRuntimeRevision",
            )
            if expected_runtime_revision != current["runtimeRevision"]:
                raise ManagementWorkError(
                    "revision_mismatch",
                    "The history snapshot revision is stale.",
                    current_revision=current,
                )
            reason = compact_whitespace(str(payload.get("reason") or "control-center-history"))
            if len(reason) > 256:
                raise ManagementWorkError("invalid_request", "reason must not exceed 256 characters.")
            domain = {"eventId": event_id, "reason": reason}
            with self._connect() as conn:
                snapshot = _history_subject_snapshot(conn, event_id)
                if snapshot["activeTombstoneIds"]:
                    raise ManagementWorkError(
                        "domain_conflict",
                        "This history record is already hidden.",
                        current_revision=self.management_work_revision(
                            conn,
                            subject_revision=_snapshot_revision(snapshot),
                        ),
                    )
                expected_revision = self.management_work_revision(
                    conn,
                    subject_revision=_snapshot_revision(snapshot),
                )
            return self.work_contract.create_preview(
                path_id="history.tombstone.apply",
                payload=domain,
                expected_revision=expected_revision,
                required_confirm="apply",
                summary={
                    "title": "隐藏输入历史记录",
                    "items": [
                        f"记录 ID: {event_id}",
                        "停止参与后续历史列表与记忆召回。",
                        "保留原始审计记录，并允许使用本次收据回滚。",
                    ],
                    "risk": "R2",
                },
            )
        except Exception as exc:
            return self.work_contract.error_payload(exc, current_revision=current)

    def history_tombstone_apply(self, payload: Mapping[str, object]) -> dict[str, object]:
        current = {"runtimeRevision": self.revision().runtime_revision}
        try:
            _require_exact_keys(
                payload,
                required={
                    "eventId",
                    "reason",
                    "expectedRuntimeRevision",
                    "previewToken",
                    "payloadSha256",
                    "confirmText",
                },
                optional=set(),
            )
            event_id = _strict_bounded_int(
                payload.get("eventId"),
                field="eventId",
                minimum=1,
                maximum=9_223_372_036_854_775_807,
            )
            expected_runtime_revision = _strict_nonnegative_int(
                payload.get("expectedRuntimeRevision"),
                field="expectedRuntimeRevision",
            )
            if expected_runtime_revision != current["runtimeRevision"]:
                raise ManagementWorkError(
                    "revision_mismatch",
                    "The history apply request revision is stale.",
                    current_revision=current,
                )
            reason = compact_whitespace(str(payload.get("reason") or ""))
            if not reason or len(reason) > 256:
                raise ManagementWorkError("invalid_request", "reason must contain 1 to 256 characters.")
            domain = {"eventId": event_id, "reason": reason}

            def current_revision(conn: sqlite3.Connection) -> Mapping[str, object]:
                return self.management_work_revision(
                    conn,
                    subject_revision=_snapshot_revision(_history_subject_snapshot(conn, event_id)),
                )

            def execute(conn: sqlite3.Connection) -> WorkExecution:
                before = _history_subject_snapshot(conn, event_id)
                if before["activeTombstoneIds"]:
                    raise ManagementWorkError("domain_conflict", "This history record is already hidden.")
                created_at_ms = _now_ms()
                cursor = conn.execute(
                    """
                    INSERT INTO memory_tombstones(
                        created_at_ms, target_type, target_value, reason, active, metadata_json
                    ) VALUES (?, 'memory_id', ?, ?, 1, ?)
                    """,
                    (
                        created_at_ms,
                        f"event:{event_id}",
                        reason,
                        json.dumps(
                            {"source": "control-center-web", "eventId": event_id},
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                    ),
                )
                tombstone_id = int(cursor.lastrowid)
                after = _history_subject_snapshot(conn, event_id)
                result = {
                    "schemaVersion": "rag-ime.history-tombstone.v1",
                    "ok": True,
                    "eventId": event_id,
                    "tombstoneId": tombstone_id,
                    "hidden": True,
                }
                return WorkExecution(
                    result=result,
                    audit_action="history_tombstone",
                    target_type="history",
                    target_id=str(event_id),
                    rollback_available=True,
                    rollback_path_id="history.tombstone.rollback",
                    rollback_confirm="rollback",
                    rollback_authority={"eventId": event_id, "tombstoneId": tombstone_id},
                    rollback_data={"afterRevision": _snapshot_revision(after)},
                )

            response = self.work_contract.execute_apply(
                path_id="history.tombstone.apply",
                payload=domain,
                preview_token=str(payload.get("previewToken") or ""),
                payload_sha256=str(payload.get("payloadSha256") or ""),
                confirm_text=str(payload.get("confirmText") or ""),
                current_revision=current_revision,
                executor=execute,
            )
            if self.cache_invalidator is not None:
                self.cache_invalidator()
            self.events.publish("history_changed", {"eventId": event_id, "action": "tombstone"})
            return response
        except Exception as exc:
            return self.work_contract.error_payload(exc, current_revision=current)

    def history_tombstone_rollback(self, payload: Mapping[str, object]) -> dict[str, object]:
        current = {"runtimeRevision": self.revision().runtime_revision}
        try:
            _require_exact_keys(
                payload,
                required={"receiptId", "rollbackToken", "payloadSha256", "confirmText"},
                optional=set(),
            )

            def execute(conn: sqlite3.Connection, receipt: StoredReceipt) -> WorkExecution:
                authority = dict(receipt.rollback_authority)
                event_id = _strict_bounded_int(
                    authority.get("eventId"),
                    field="eventId",
                    minimum=1,
                    maximum=9_223_372_036_854_775_807,
                )
                tombstone_id = _strict_bounded_int(
                    authority.get("tombstoneId"),
                    field="tombstoneId",
                    minimum=1,
                    maximum=9_223_372_036_854_775_807,
                )
                snapshot = _history_subject_snapshot(conn, event_id)
                if _snapshot_revision(snapshot) != receipt.rollback_data.get("afterRevision"):
                    raise ManagementWorkError(
                        "rollback_state_changed",
                        "The history record changed after the apply receipt was issued.",
                        current_revision=self.management_work_revision(
                            conn,
                            subject_revision=_snapshot_revision(snapshot),
                        ),
                    )
                updated = conn.execute(
                    """
                    UPDATE memory_tombstones
                    SET active = 0
                    WHERE id = ? AND target_type = 'memory_id'
                      AND target_value = ? AND active = 1
                    """,
                    (tombstone_id, f"event:{event_id}"),
                )
                if updated.rowcount != 1:
                    raise ManagementWorkError(
                        "rollback_state_changed",
                        "The managed tombstone is no longer active.",
                    )
                return WorkExecution(
                    result={
                        "schemaVersion": "rag-ime.history-tombstone.v1",
                        "ok": True,
                        "eventId": event_id,
                        "tombstoneId": tombstone_id,
                        "hidden": False,
                    },
                    audit_action="history_tombstone_rollback",
                    target_type="history",
                    target_id=str(event_id),
                )

            response = self.work_contract.execute_rollback(
                path_id="history.tombstone.rollback",
                receipt_id=str(payload.get("receiptId") or ""),
                rollback_token=str(payload.get("rollbackToken") or ""),
                payload_sha256=str(payload.get("payloadSha256") or ""),
                confirm_text=str(payload.get("confirmText") or ""),
                expected_apply_path_id="history.tombstone.apply",
                executor=execute,
            )
            if self.cache_invalidator is not None:
                self.cache_invalidator()
            authority = response.get("rollbackAuthority")
            self.events.publish(
                "history_changed",
                {
                    "eventId": authority.get("eventId") if isinstance(authority, Mapping) else 0,
                    "action": "rollback",
                },
            )
            return response
        except Exception as exc:
            return self.work_contract.error_payload(exc, current_revision=current)

    def planning_dashboard(self, *, plan_date: str = "", project: str = "") -> dict[str, object]:
        with self._connect() as conn:
            payload = planning_dashboard(
                conn,
                plan_date=plan_date,
                project=compact_whitespace(project) or self.project,
            )
        return {**self.revision().payload(), **payload}

    def planning_save_plan(self, payload: Mapping[str, object]) -> dict[str, object]:
        project = compact_whitespace(str(payload.get("project") or self.project))
        with self._connect() as conn:
            result = save_daily_plan(conn, payload, project=project)
        audit_id = self._audit("planning_plan_save", "daily_plan", str(result.get("date") or ""), payload, result)
        self.events.publish("planning_changed", {"kind": "daily_plan", "date": result.get("date")})
        return {**self.revision(audit_id=audit_id).payload(), **result}

    def planning_save_goal(self, payload: Mapping[str, object]) -> dict[str, object]:
        project = compact_whitespace(str(payload.get("project") or self.project))
        with self._connect() as conn:
            result = save_goal(conn, payload, project=project)
        goal = result.get("goal") if isinstance(result.get("goal"), dict) else {}
        audit_id = self._audit("planning_goal_save", "goal", str(goal.get("id") or ""), payload, result)
        self.events.publish("planning_changed", {"kind": "goal", "id": goal.get("id")})
        return {**self.revision(audit_id=audit_id).payload(), **result}

    def planning_save_task(self, payload: Mapping[str, object]) -> dict[str, object]:
        project = compact_whitespace(str(payload.get("project") or self.project))
        with self._connect() as conn:
            result = save_task(conn, payload, project=project)
        task = result.get("task") if isinstance(result.get("task"), dict) else {}
        audit_id = self._audit("planning_task_save", "task", str(task.get("id") or ""), payload, result)
        self.events.publish("planning_changed", {"kind": "task", "id": task.get("id")})
        return {**self.revision(audit_id=audit_id).payload(), **result}

    def planning_mutation_preview(self, payload: Mapping[str, object]) -> dict[str, object]:
        current_revision = {"runtimeRevision": self.revision().runtime_revision}
        try:
            kind = compact_whitespace(str(payload.get("kind") or ""))
            if kind not in {"task.save", "task.action", "goal.save"}:
                raise ManagementWorkError(
                    "unsupported_mutation",
                    "Planning preview supports only task.save, task.action, and goal.save.",
                    current_revision=current_revision,
                )
            expected_runtime_revision = _strict_nonnegative_int(
                payload.get("expectedRuntimeRevision"),
                field="expectedRuntimeRevision",
            )
            if expected_runtime_revision != current_revision["runtimeRevision"]:
                raise ManagementWorkError(
                    "revision_mismatch",
                    "The planning dashboard revision is stale.",
                    current_revision=current_revision,
                )
            raw_domain = payload.get("payload")
            if not isinstance(raw_domain, Mapping):
                raise ManagementWorkError("invalid_request", "payload must be an object.")
            if kind == "task.save":
                _require_exact_keys(
                    raw_domain,
                    required={"date", "title"},
                    optional=_PLANNING_TASK_SAVE_FIELDS - {"date", "title"},
                )
            elif kind == "task.action":
                _require_exact_keys(
                    raw_domain,
                    required=_PLANNING_TASK_ACTION_FIELDS,
                    optional=set(),
                )
            else:
                _require_exact_keys(
                    raw_domain,
                    required={"title"},
                    optional=_PLANNING_GOAL_SAVE_FIELDS - {"title"},
                )
            domain = _normalize_planning_work_payload(kind, raw_domain, project=self.project)
            path_id = {
                "task.save": "planning.task.save",
                "task.action": "planning.task.action",
                "goal.save": "planning.goal.save",
            }[kind]
            with self._connect() as conn:
                subject_revision = _planning_subject_revision(conn, kind=kind, payload=domain)
            expected_revision = {
                "runtimeRevision": expected_runtime_revision,
                "subjectRevision": subject_revision,
            }
            title = {
                "task.save": "保存规划任务",
                "task.action": "更新规划任务状态",
                "goal.save": "保存规划目标",
            }[kind]
            summary = {
                "title": title,
                "items": _planning_preview_items(kind, domain),
                "risk": "R1",
            }
            return self.work_contract.create_preview(
                path_id=path_id,
                payload=domain,
                expected_revision=expected_revision,
                required_confirm="apply",
                summary=summary,
            )
        except Exception as exc:
            return self.work_contract.error_payload(exc, current_revision=current_revision)

    def planning_apply_task_save(self, payload: Mapping[str, object]) -> dict[str, object]:
        return self._planning_apply_contract("task.save", payload)

    def planning_apply_task_action(self, payload: Mapping[str, object]) -> dict[str, object]:
        return self._planning_apply_contract("task.action", payload)

    def planning_apply_goal_save(self, payload: Mapping[str, object]) -> dict[str, object]:
        return self._planning_apply_contract("goal.save", payload)

    def _planning_apply_contract(
        self,
        kind: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        current = {"runtimeRevision": self.revision().runtime_revision}
        try:
            _reject_unknown_work_fields(payload, kind=kind)
            expected_runtime_revision = _strict_nonnegative_int(
                payload.get("expectedRuntimeRevision"),
                field="expectedRuntimeRevision",
            )
            if expected_runtime_revision != current["runtimeRevision"]:
                raise ManagementWorkError(
                    "revision_mismatch",
                    "The apply request revision is stale.",
                    current_revision=current,
                )
            domain = _normalize_planning_work_payload(kind, payload, project=self.project)
            path_id = {
                "task.save": "planning.task.save",
                "task.action": "planning.task.action",
                "goal.save": "planning.goal.save",
            }[kind]

            def current_revision(conn: sqlite3.Connection) -> Mapping[str, object]:
                return self.management_work_revision(
                    conn,
                    subject_revision=_planning_subject_revision(conn, kind=kind, payload=domain),
                )

            def execute(conn: sqlite3.Connection) -> WorkExecution:
                if kind == "goal.save":
                    goal_id = compact_whitespace(str(domain.get("goalId") or ""))
                    before = _planning_goal_snapshot(conn, goal_id) if goal_id else None
                    result = save_goal(conn, domain, project=self.project)
                    goal = result.get("goal") if isinstance(result.get("goal"), dict) else {}
                    applied_goal_id = compact_whitespace(str(goal.get("id") or ""))
                    after = _planning_goal_snapshot(conn, applied_goal_id)
                    return WorkExecution(
                        result=result,
                        audit_action="planning_goal_save",
                        target_type="goal",
                        target_id=applied_goal_id,
                        rollback_available=True,
                        rollback_path_id="planning.mutation.rollback",
                        rollback_confirm="rollback",
                        rollback_authority={"goalId": applied_goal_id},
                        rollback_data={
                            "kind": kind,
                            "goalId": applied_goal_id,
                            "beforeGoal": before,
                            "afterRevision": _snapshot_revision(after),
                        },
                    )
                if kind == "task.save":
                    task_id = compact_whitespace(str(domain.get("taskId") or ""))
                    before = _planning_task_snapshot(conn, task_id) if task_id else None
                    result = save_task(conn, domain, project=self.project)
                    task = result.get("task") if isinstance(result.get("task"), dict) else {}
                    applied_task_id = compact_whitespace(str(task.get("id") or ""))
                    after = _planning_task_snapshot(conn, applied_task_id)
                    return WorkExecution(
                        result=result,
                        audit_action="planning_task_save",
                        target_type="task",
                        target_id=applied_task_id,
                        rollback_available=True,
                        rollback_path_id="planning.mutation.rollback",
                        rollback_confirm="rollback",
                        rollback_authority={"taskId": applied_task_id},
                        rollback_data={
                            "kind": kind,
                            "taskId": applied_task_id,
                            "beforeTask": before,
                            "afterRevision": _snapshot_revision(after),
                        },
                    )
                task_id = compact_whitespace(str(domain.get("taskId") or ""))
                result = task_action(
                    conn,
                    task_id=task_id,
                    action=compact_whitespace(str(domain.get("action") or "")),
                    metadata={"source": "control-center-web"},
                )
                event_id = compact_whitespace(str(result.get("eventId") or ""))
                after = _planning_task_snapshot(conn, task_id)
                return WorkExecution(
                    result=result,
                    audit_action=f"planning_task_{domain['action']}",
                    target_type="task",
                    target_id=task_id,
                    rollback_available=bool(result.get("undoAvailable")),
                    rollback_path_id="planning.taskEvent.undo",
                    rollback_confirm="undo",
                    rollback_authority={"eventId": event_id, "taskId": task_id},
                    rollback_data={
                        "kind": kind,
                        "eventId": event_id,
                        "taskId": task_id,
                        "afterRevision": _snapshot_revision(after),
                    },
                )

            response = self.work_contract.execute_apply(
                path_id=path_id,
                payload=domain,
                preview_token=str(payload.get("previewToken") or ""),
                payload_sha256=str(payload.get("payloadSha256") or ""),
                confirm_text=str(payload.get("confirmText") or ""),
                current_revision=current_revision,
                executor=execute,
            )
            subject_key = "goal" if kind == "goal.save" else "task"
            subject = response.get(subject_key) if isinstance(response.get(subject_key), dict) else {}
            self.events.publish(
                "planning_changed",
                {
                    "kind": subject_key,
                    "id": subject.get("id"),
                    "action": domain.get("action") or "save",
                },
            )
            return response
        except Exception as exc:
            return self.work_contract.error_payload(exc, current_revision=current)

    def planning_undo_task_event_contract(self, payload: Mapping[str, object]) -> dict[str, object]:
        current = {"runtimeRevision": self.revision().runtime_revision}
        try:
            _require_exact_keys(
                payload,
                required={"eventId", "receiptId", "rollbackToken", "payloadSha256", "confirmText"},
                optional=set(),
            )
            event_id = compact_whitespace(str(payload.get("eventId") or ""))
            if not event_id:
                raise ManagementWorkError("invalid_request", "eventId is required.")

            def execute(conn: sqlite3.Connection, receipt: StoredReceipt) -> WorkExecution:
                authority = dict(receipt.rollback_authority)
                if authority.get("eventId") != event_id:
                    raise ManagementWorkError(
                        "rollback_authority_mismatch",
                        "The task event is not owned by this receipt.",
                    )
                rollback_data = dict(receipt.rollback_data)
                task_id = compact_whitespace(str(rollback_data.get("taskId") or ""))
                current_task = _planning_task_snapshot(conn, task_id)
                if _snapshot_revision(current_task) != rollback_data.get("afterRevision"):
                    raise ManagementWorkError(
                        "rollback_state_changed",
                        "The task changed after the receipt was issued.",
                        current_revision={
                            **current,
                            "subjectRevision": _snapshot_revision(current_task),
                        },
                    )
                result = undo_task_event(conn, event_id=event_id)
                return WorkExecution(
                    result=result,
                    audit_action="planning_task_event_undo",
                    target_type="task",
                    target_id=task_id,
                )

            response = self.work_contract.execute_rollback(
                path_id="planning.taskEvent.undo",
                receipt_id=str(payload.get("receiptId") or ""),
                rollback_token=str(payload.get("rollbackToken") or ""),
                payload_sha256=str(payload.get("payloadSha256") or ""),
                confirm_text=str(payload.get("confirmText") or ""),
                expected_apply_path_id="planning.task.action",
                executor=execute,
            )
            task = response.get("task") if isinstance(response.get("task"), dict) else {}
            self.events.publish(
                "planning_changed",
                {"kind": "task", "id": task.get("id"), "action": "undo"},
            )
            return response
        except Exception as exc:
            return self.work_contract.error_payload(exc, current_revision=current)

    def planning_mutation_rollback(self, payload: Mapping[str, object]) -> dict[str, object]:
        current = {"runtimeRevision": self.revision().runtime_revision}
        try:
            _require_exact_keys(
                payload,
                required={"receiptId", "rollbackToken", "payloadSha256", "confirmText"},
                optional=set(),
            )

            def execute(conn: sqlite3.Connection, receipt: StoredReceipt) -> WorkExecution:
                rollback_data = dict(receipt.rollback_data)
                kind = compact_whitespace(str(rollback_data.get("kind") or ""))
                if kind not in {"task.save", "goal.save"}:
                    raise ManagementWorkError(
                        "rollback_authority_mismatch",
                        "This receipt is not a planning save receipt.",
                    )
                subject_id_key = "goalId" if kind == "goal.save" else "taskId"
                before_key = "beforeGoal" if kind == "goal.save" else "beforeTask"
                subject_id = compact_whitespace(str(rollback_data.get(subject_id_key) or ""))
                current_subject = (
                    _planning_goal_snapshot(conn, subject_id)
                    if kind == "goal.save"
                    else _planning_task_snapshot(conn, subject_id)
                )
                if _snapshot_revision(current_subject) != rollback_data.get("afterRevision"):
                    raise ManagementWorkError(
                        "rollback_state_changed",
                        "The planning item changed after the receipt was issued.",
                        current_revision={
                            **current,
                            "subjectRevision": _snapshot_revision(current_subject),
                        },
                    )
                before = rollback_data.get(before_key)
                if before is None:
                    if kind == "goal.save":
                        conn.execute("DELETE FROM planning_goals WHERE goal_id = ?", (subject_id,))
                    else:
                        conn.execute("DELETE FROM planning_tasks WHERE task_id = ?", (subject_id,))
                    result: dict[str, object] = {
                        "schemaVersion": "rag-ime.planning.v1",
                        "ok": True,
                        subject_id_key: subject_id,
                        "deleted": True,
                    }
                elif isinstance(before, Mapping):
                    if kind == "goal.save":
                        _restore_planning_goal(conn, before)
                    else:
                        _restore_planning_task(conn, before)
                    result = {
                        "schemaVersion": "rag-ime.planning.v1",
                        "ok": True,
                        subject_id_key: subject_id,
                        "restored": True,
                    }
                else:
                    raise ManagementWorkError(
                        "stored_contract_invalid",
                        "The planning rollback snapshot is invalid.",
                    )
                return WorkExecution(
                    result=result,
                    audit_action=f"planning_{'goal' if kind == 'goal.save' else 'task'}_save_rollback",
                    target_type="goal" if kind == "goal.save" else "task",
                    target_id=subject_id,
                )

            response = self.work_contract.execute_rollback(
                path_id="planning.mutation.rollback",
                receipt_id=str(payload.get("receiptId") or ""),
                rollback_token=str(payload.get("rollbackToken") or ""),
                payload_sha256=str(payload.get("payloadSha256") or ""),
                confirm_text=str(payload.get("confirmText") or ""),
                expected_apply_path_id=("planning.task.save", "planning.goal.save"),
                executor=execute,
            )
            authority = response.get("rollbackAuthority")
            authority_payload = authority if isinstance(authority, Mapping) else {}
            subject_kind = "goal" if authority_payload.get("goalId") else "task"
            self.events.publish(
                "planning_changed",
                {
                    "kind": subject_kind,
                    "id": authority_payload.get(f"{subject_kind}Id"),
                    "action": "rollback",
                },
            )
            return response
        except Exception as exc:
            return self.work_contract.error_payload(exc, current_revision=current)

    def planning_task_action(self, payload: Mapping[str, object]) -> dict[str, object]:
        task_id = compact_whitespace(str(payload.get("taskId") or payload.get("id") or ""))
        if not task_id:
            raise ValueError("taskId is required")
        action = compact_whitespace(str(payload.get("action") or ""))
        with self._connect() as conn:
            result = task_action(
                conn,
                task_id=task_id,
                action=action,
                metadata={"source": "native-control-center"},
            )
        audit_id = self._audit(f"planning_task_{action}", "task", task_id, payload, result)
        self.events.publish("planning_changed", {"kind": "task", "id": task_id, "action": action})
        return {**self.revision(audit_id=audit_id).payload(), **result}

    def planning_undo_task_event(self, payload: Mapping[str, object]) -> dict[str, object]:
        event_id = compact_whitespace(str(payload.get("eventId") or ""))
        if not event_id:
            raise ValueError("eventId is required")
        with self._connect() as conn:
            result = undo_task_event(conn, event_id=event_id)
        task = result.get("task") if isinstance(result.get("task"), dict) else {}
        audit_id = self._audit("planning_task_event_undo", "task", str(task.get("id") or ""), payload, result)
        self.events.publish("planning_changed", {"kind": "task", "id": task.get("id"), "action": "undo"})
        return {**self.revision(audit_id=audit_id).payload(), **result}

    def planning_resolve_completion(self, payload: Mapping[str, object]) -> dict[str, object]:
        suggestion_id = compact_whitespace(str(payload.get("suggestionId") or ""))
        if not suggestion_id:
            raise ValueError("suggestionId is required")
        with self._connect() as conn:
            result = resolve_completion_suggestion(
                conn,
                suggestion_id=suggestion_id,
                task_id=compact_whitespace(str(payload.get("taskId") or "")),
                dismiss=bool(payload.get("dismiss")),
            )
        audit_id = self._audit("planning_completion_resolve", "completion_suggestion", suggestion_id, payload, result)
        self.events.publish("planning_changed", {"kind": "completion_suggestion", "id": suggestion_id})
        return {**self.revision(audit_id=audit_id).payload(), **result}

    def planning_assistant(self, payload: Mapping[str, object]) -> dict[str, object]:
        message = compact_whitespace(str(payload.get("message") or payload.get("text") or ""))
        project = compact_whitespace(str(payload.get("project") or self.project))
        with self._connect() as conn:
            result = planning_assistant_reply(
                conn,
                message=message,
                project=project,
                plan_date=compact_whitespace(str(payload.get("date") or "")),
            )
        audit_id = self._audit("planning_assistant_message", "daily_plan", str(result.get("date") or ""), {"messageChars": len(message)}, {"ok": True})
        self.events.publish("planning_changed", {"kind": "assistant", "date": result.get("date")})
        return {**self.revision(audit_id=audit_id).payload(), **result}

    def memory_book_archive_status(self, payload: Mapping[str, object]) -> dict[str, object]:
        book_id = compact_whitespace(str(payload.get("bookId") or payload.get("id") or ""))
        if not book_id:
            raise ValueError("bookId is required")
        archived = bool(payload.get("archived", True))
        with self._connect() as conn:
            result = set_memory_book_archive_status(
                conn,
                book_id=book_id,
                archived=archived,
                reason=compact_whitespace(str(payload.get("reason") or "")),
                actor=compact_whitespace(str(payload.get("updatedBy") or "native-control-center")),
            )
            retrieval = rebuild_retrieval_docs(conn, project="")
        result["retrievalDocs"] = retrieval
        audit_id = self._audit(
            "memory_book_archive" if archived else "memory_book_restore",
            "memory_book",
            book_id,
            payload,
            result,
        )
        if self.cache_invalidator is not None:
            self.cache_invalidator()
        self.events.publish(
            "memory_changed",
            {"kind": "book", "id": book_id, "action": "archive" if archived else "restore"},
        )
        return {**self.revision(audit_id=audit_id).payload(), **result}

    def memory_book_archive_preview(self, payload: Mapping[str, object]) -> dict[str, object]:
        current = {"runtimeRevision": self.revision().runtime_revision}
        try:
            _require_exact_keys(
                payload,
                required={"bookId", "archived", "expectedRuntimeRevision"},
                optional={"reason"},
            )
            book_id = compact_whitespace(str(payload.get("bookId") or ""))
            if not book_id or len(book_id) > 512:
                raise ManagementWorkError("invalid_request", "bookId must contain 1 to 512 characters.")
            if not isinstance(payload.get("archived"), bool):
                raise ManagementWorkError("invalid_request", "archived must be a boolean.")
            archived = bool(payload["archived"])
            expected_runtime_revision = _strict_nonnegative_int(
                payload.get("expectedRuntimeRevision"),
                field="expectedRuntimeRevision",
            )
            if expected_runtime_revision != current["runtimeRevision"]:
                raise ManagementWorkError(
                    "revision_mismatch",
                    "The memory snapshot revision is stale.",
                    current_revision=current,
                )
            reason = compact_whitespace(
                str(payload.get("reason") or ("control_center_archive" if archived else "control_center_restore"))
            )
            if not reason or len(reason) > 256:
                raise ManagementWorkError("invalid_request", "reason must contain 1 to 256 characters.")
            domain = {"bookId": book_id, "archived": archived, "reason": reason}
            with self._connect() as conn:
                snapshot = _memory_book_subject_snapshot(conn, book_id)
                current_archived = str(snapshot["status"]) == "archived"
                if current_archived == archived:
                    raise ManagementWorkError(
                        "domain_conflict",
                        "This memory book already has the requested archive state.",
                        current_revision=self.management_work_revision(
                            conn,
                            subject_revision=_snapshot_revision(snapshot),
                        ),
                    )
                if archived and str(snapshot["book_type"]) != "topic":
                    raise ManagementWorkError(
                        "domain_rejected",
                        "Only topic memory books can be archived manually.",
                    )
                expected_revision = self.management_work_revision(
                    conn,
                    subject_revision=_snapshot_revision(snapshot),
                )
            action_label = "归档" if archived else "恢复"
            return self.work_contract.create_preview(
                path_id="memory.book.archive.apply",
                payload=domain,
                expected_revision=expected_revision,
                required_confirm="apply",
                summary={
                    "title": f"{action_label}主题记忆",
                    "items": [
                        f"主题：{snapshot['title']}",
                        "归档后退出日常自动召回；明确回顾旧主题时仍可恢复。" if archived else "恢复后重新参与日常记忆召回。",
                        "原始内容与关系仍会保留，本次变更可使用收据回滚。",
                    ],
                    "risk": "R2",
                },
            )
        except Exception as exc:
            return self.work_contract.error_payload(exc, current_revision=current)

    def memory_book_archive_apply(self, payload: Mapping[str, object]) -> dict[str, object]:
        current = {"runtimeRevision": self.revision().runtime_revision}
        try:
            _require_exact_keys(
                payload,
                required={
                    "bookId",
                    "archived",
                    "reason",
                    "expectedRuntimeRevision",
                    "previewToken",
                    "payloadSha256",
                    "confirmText",
                },
                optional=set(),
            )
            book_id = compact_whitespace(str(payload.get("bookId") or ""))
            if not book_id or len(book_id) > 512:
                raise ManagementWorkError("invalid_request", "bookId must contain 1 to 512 characters.")
            if not isinstance(payload.get("archived"), bool):
                raise ManagementWorkError("invalid_request", "archived must be a boolean.")
            archived = bool(payload["archived"])
            reason = compact_whitespace(str(payload.get("reason") or ""))
            if not reason or len(reason) > 256:
                raise ManagementWorkError("invalid_request", "reason must contain 1 to 256 characters.")
            expected_runtime_revision = _strict_nonnegative_int(
                payload.get("expectedRuntimeRevision"),
                field="expectedRuntimeRevision",
            )
            if expected_runtime_revision != current["runtimeRevision"]:
                raise ManagementWorkError(
                    "revision_mismatch",
                    "The memory apply request revision is stale.",
                    current_revision=current,
                )
            domain = {"bookId": book_id, "archived": archived, "reason": reason}

            def current_revision(conn: sqlite3.Connection) -> Mapping[str, object]:
                return self.management_work_revision(
                    conn,
                    subject_revision=_snapshot_revision(_memory_book_subject_snapshot(conn, book_id)),
                )

            def execute(conn: sqlite3.Connection) -> WorkExecution:
                before = _memory_book_subject_snapshot(conn, book_id)
                if (str(before["status"]) == "archived") == archived:
                    raise ManagementWorkError(
                        "domain_conflict",
                        "This memory book already has the requested archive state.",
                    )
                result = set_memory_book_archive_status(
                    conn,
                    book_id=book_id,
                    archived=archived,
                    reason=reason,
                    actor="control-center-web",
                )
                result["retrievalDocs"] = rebuild_retrieval_docs(conn, project="")
                after = _memory_book_subject_snapshot(conn, book_id)
                return WorkExecution(
                    result=result,
                    audit_action="memory_book_archive" if archived else "memory_book_restore",
                    target_type="memory_book",
                    target_id=book_id,
                    rollback_available=True,
                    rollback_path_id="memory.book.archive.rollback",
                    rollback_confirm="rollback",
                    rollback_authority={"bookId": book_id},
                    rollback_data={
                        "beforeSnapshot": before,
                        "afterRevision": _snapshot_revision(after),
                    },
                )

            response = self.work_contract.execute_apply(
                path_id="memory.book.archive.apply",
                payload=domain,
                preview_token=str(payload.get("previewToken") or ""),
                payload_sha256=str(payload.get("payloadSha256") or ""),
                confirm_text=str(payload.get("confirmText") or ""),
                current_revision=current_revision,
                executor=execute,
            )
            if self.cache_invalidator is not None:
                self.cache_invalidator()
            self.events.publish(
                "memory_changed",
                {"kind": "book", "id": book_id, "action": "archive" if archived else "restore"},
            )
            return response
        except Exception as exc:
            return self.work_contract.error_payload(exc, current_revision=current)

    def memory_book_archive_rollback(self, payload: Mapping[str, object]) -> dict[str, object]:
        current = {"runtimeRevision": self.revision().runtime_revision}
        try:
            _require_exact_keys(
                payload,
                required={"receiptId", "rollbackToken", "payloadSha256", "confirmText"},
                optional=set(),
            )

            def execute(conn: sqlite3.Connection, receipt: StoredReceipt) -> WorkExecution:
                book_id = compact_whitespace(str(receipt.rollback_authority.get("bookId") or ""))
                if not book_id:
                    raise ManagementWorkError(
                        "stored_contract_invalid",
                        "The archive receipt does not identify a memory book.",
                    )
                current_snapshot = _memory_book_subject_snapshot(conn, book_id)
                if _snapshot_revision(current_snapshot) != receipt.rollback_data.get("afterRevision"):
                    raise ManagementWorkError(
                        "rollback_state_changed",
                        "The memory book changed after the apply receipt was issued.",
                        current_revision=self.management_work_revision(
                            conn,
                            subject_revision=_snapshot_revision(current_snapshot),
                        ),
                    )
                before = receipt.rollback_data.get("beforeSnapshot")
                if not isinstance(before, Mapping):
                    raise ManagementWorkError(
                        "stored_contract_invalid",
                        "The archive receipt does not contain a restorable memory snapshot.",
                    )
                _restore_memory_book_snapshot(conn, before)
                retrieval = rebuild_retrieval_docs(conn, project="")
                return WorkExecution(
                    result={
                        "schemaVersion": "rag-ime.memory-book-lifecycle.v1",
                        "ok": True,
                        "bookId": book_id,
                        "status": str(before["status"]),
                        "retrievalDocs": retrieval,
                    },
                    audit_action="memory_book_archive_rollback",
                    target_type="memory_book",
                    target_id=book_id,
                )

            response = self.work_contract.execute_rollback(
                path_id="memory.book.archive.rollback",
                receipt_id=str(payload.get("receiptId") or ""),
                rollback_token=str(payload.get("rollbackToken") or ""),
                payload_sha256=str(payload.get("payloadSha256") or ""),
                confirm_text=str(payload.get("confirmText") or ""),
                expected_apply_path_id="memory.book.archive.apply",
                executor=execute,
            )
            if self.cache_invalidator is not None:
                self.cache_invalidator()
            authority = response.get("rollbackAuthority")
            self.events.publish(
                "memory_changed",
                {
                    "kind": "book",
                    "id": authority.get("bookId") if isinstance(authority, Mapping) else "",
                    "action": "rollback",
                },
            )
            return response
        except Exception as exc:
            return self.work_contract.error_payload(exc, current_revision=current)

    def memory_book_archive_maintenance(self, payload: Mapping[str, object]) -> dict[str, object]:
        apply_changes = bool(payload.get("apply", False))
        inactive_days = _bounded_int(payload.get("inactiveDays"), default=60, minimum=7, maximum=3650)
        project = compact_whitespace(str(payload.get("project") or self.project))
        with self._connect() as conn:
            result = archive_inactive_memory_books(
                conn,
                project=project,
                inactive_days=inactive_days,
                dry_run=not apply_changes,
            )
            if apply_changes:
                result["retrievalDocs"] = rebuild_retrieval_docs(conn, project="")
        audit_id = self._audit(
            "memory_book_archive_maintenance_apply" if apply_changes else "memory_book_archive_maintenance_preview",
            "memory_book",
            project or "global",
            payload,
            result,
        )
        if apply_changes and self.cache_invalidator is not None:
            self.cache_invalidator()
        if apply_changes:
            self.events.publish("memory_changed", {"kind": "book", "action": "archive_maintenance"})
        return {**self.revision(audit_id=audit_id).payload(), **result}

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

    def memory_source_disposition(
        self,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        source_id = compact_whitespace(str(payload.get("sourceId") or ""))
        disposition = compact_whitespace(
            str(payload.get("disposition") or "")
        ).lower()
        if not source_id:
            raise ValueError("memory source id is required")
        if disposition not in {"pending", "not_for_memory"}:
            raise ValueError(
                "memory source disposition must be pending or not_for_memory"
            )
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT event.project, event.committed_text,
                       source.disposition, source.disposition_reason
                FROM agent_memory_sources AS source
                JOIN input_events AS event ON event.id = source.input_event_id
                WHERE source.source_id = ?
                """,
                (source_id,),
            ).fetchone()
        if row is None:
            raise ValueError(f"memory source not found: {source_id}")
        event_project = compact_whitespace(str(row["project"] or ""))
        if (
            self.project
            and event_project
            and event_project != self.project
        ):
            raise ValueError("memory source belongs to another project")
        previous_disposition = compact_whitespace(
            str(row["disposition"] or "")
        )
        sensitive = (
            str(row["disposition_reason"] or "") == "sensitive_input"
            or looks_sensitive(str(row["committed_text"] or ""))
        )
        if disposition == "pending":
            if sensitive:
                raise ValueError(
                    "sensitive memory evidence cannot be restored"
                )
            allowed_previous = {"pending", "not_for_memory", "expired"}
        else:
            allowed_previous = {
                "pending",
                "remember",
                "needs_review",
                "not_for_memory",
            }
        if previous_disposition not in allowed_previous:
            raise ValueError(
                "memory source disposition transition is not allowed"
            )

        action = "restore" if disposition == "pending" else "forget"
        store = AgentMemorySourceStore(
            self.db_path,
            project=self.project,
        )
        if previous_disposition == disposition:
            result = {
                "schemaVersion": "rag-ime.agent-memory-disposition.v1",
                "ok": True,
                "changed": False,
                "source": store.get(source_id),
            }
        else:
            result = store.set_disposition(
                source_id,
                disposition=disposition,
                reason_code=(
                    "user_restored"
                    if disposition == "pending"
                    else "user_forgotten"
                ),
                actor_kind="user",
                metadata={"surface": "control_center", "action": action},
            )
        audit_id = self._audit(
            f"memory_source_{action}",
            "memory_source",
            source_id,
            dict(payload),
            result,
        )
        self._bump_runtime_revision()
        if self.cache_invalidator is not None:
            self.cache_invalidator()
        self.events.publish(
            "memory_changed",
            {
                "kind": "evidence",
                "action": action,
                "sourceId": source_id,
            },
        )
        return {
            **self.revision(audit_id=int(audit_id)).payload(),
            **result,
            "ok": True,
            "action": action,
        }

    def memory_edit(self, payload: Mapping[str, object]) -> dict[str, object]:
        kind = str(payload.get("kind") or payload.get("itemType") or "").strip().lower()
        item_id = str(payload.get("id") or payload.get("memoryId") or "").strip()
        merge_into_id = str(payload.get("mergeIntoId") or "").strip()
        if not kind or not item_id:
            raise ValueError("kind and id are required")
        if kind in {"phrase", "phrases"}:
            return self.memory_action(
                {
                    "memoryId": item_id,
                    "itemType": "phrase",
                    "action": "update_phrase",
                    "newPhrase": str(payload.get("text") or payload.get("title") or ""),
                    "reason": "native_control_center_edit",
                    "updatedBy": "native-control-center",
                }
            )

        timestamp = _now_ms()
        changes: dict[str, object] = {}
        with self._connect() as conn:
            if kind in {"book", "books"}:
                title = " ".join(str(payload.get("title") or "").split())
                summary = " ".join(str(payload.get("summary") or "").split())
                tags = _string_list_value(payload.get("tags"))
                if not title:
                    raise ValueError("book title is required")
                cursor = conn.execute(
                    "UPDATE memory_books SET title = ?, summary = ?, tags_json = ?, updated_at_ms = ? WHERE book_id = ?",
                    (title, summary, json.dumps(tags, ensure_ascii=False), timestamp, item_id),
                )
                if cursor.rowcount != 1:
                    raise ValueError(f"memory book not found: {item_id}")
                changes = {"title": title, "summary": summary, "tags": tags}
            elif kind in {"atom", "atoms"}:
                if merge_into_id:
                    changes = _merge_memory_atoms(
                        conn,
                        source_id=item_id,
                        target_id=merge_into_id,
                        changed_at_ms=timestamp,
                    )
                else:
                    text = " ".join(str(payload.get("text") or payload.get("summary") or "").split())
                    tags = _string_list_value(payload.get("tags"))
                    if not text:
                        raise ValueError("memory atom text is required")
                    row = conn.execute(
                        "SELECT privacy_level FROM memory_atoms WHERE id = ?",
                        (item_id,),
                    ).fetchone()
                    if row is None:
                        raise ValueError(f"memory atom not found: {item_id}")
                    if str(row[0] or "") == "sensitive":
                        raise ValueError("sensitive memory cannot be edited in the control center")
                    conn.execute(
                        "UPDATE memory_atoms SET text = ?, canonical_text = ?, updated_at_ms = ? WHERE id = ?",
                        (text, text, timestamp, item_id),
                    )
                    conn.execute("DELETE FROM memory_atom_tags WHERE memory_atom_id = ?", (item_id,))
                    for position, tag in enumerate(tags):
                        row = conn.execute("SELECT id FROM memory_tags WHERE tag = ?", (tag,)).fetchone()
                        if row is None:
                            cursor = conn.execute(
                                """
                                INSERT INTO memory_tags(
                                    tag, normalized_tag, tag_type, quality_score,
                                    created_at_ms, updated_at_ms, description,
                                    source, status, metadata_json
                                ) VALUES (?, ?, 'concept', 0.9, ?, ?, '', 'user', 'active', '{}')
                                """,
                                (tag, normalize_text(tag), timestamp, timestamp),
                            )
                            tag_id = int(cursor.lastrowid)
                        else:
                            tag_id = int(row[0])
                        conn.execute(
                            "INSERT INTO memory_atom_tags(memory_atom_id, tag_id, weight, source) VALUES (?, ?, ?, 'user_edit')",
                            (item_id, str(tag_id), max(0.5, 1.0 - position * 0.05)),
                        )
                    changes = {"text": text, "tags": tags}
            elif kind in {"tag", "tags"}:
                tag = " ".join(str(payload.get("title") or payload.get("tag") or "").split())
                description = " ".join(
                    str(payload.get("description") or payload.get("summary") or payload.get("note") or "").split()
                )
                tag_type = " ".join(str(payload.get("type") or "concept").split()) or "concept"
                aliases = _string_list_value(payload.get("aliases"))
                color = str(payload.get("color") or "blue").strip().lower()
                if color not in {"blue", "teal", "green", "orange", "pink", "purple", "gray"}:
                    color = "blue"
                if merge_into_id:
                    changes = _merge_memory_tags(
                        conn,
                        source_id=item_id,
                        target_id=merge_into_id,
                        aliases=aliases,
                        color=color,
                        changed_at_ms=timestamp,
                    )
                else:
                    if not tag:
                        raise ValueError("tag name is required")
                    duplicate = conn.execute(
                        "SELECT id FROM memory_tags WHERE tag = ? AND CAST(id AS TEXT) != ?",
                        (tag, item_id),
                    ).fetchone()
                    if duplicate is not None:
                        raise ValueError("tag already exists; use merge instead of rename")
                    cursor = conn.execute(
                        """
                        UPDATE memory_tags
                        SET tag = ?, normalized_tag = ?, tag_type = ?, description = ?,
                            source = 'user', status = 'active', updated_at_ms = ?
                        WHERE CAST(id AS TEXT) = ?
                        """,
                        (tag, normalize_text(tag), tag_type, description, timestamp, item_id),
                    )
                    if cursor.rowcount != 1:
                        raise ValueError(f"memory tag not found: {item_id}")
                    conn.execute(
                        """
                        INSERT INTO memory_tag_profiles(tag_id, color_token, aliases_json, updated_at_ms)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(tag_id) DO UPDATE SET
                            color_token = excluded.color_token,
                            aliases_json = excluded.aliases_json,
                            updated_at_ms = excluded.updated_at_ms
                        """,
                        (int(item_id), color, json.dumps(aliases, ensure_ascii=False), timestamp),
                    )
                    changes = {
                        "tag": tag,
                        "description": description,
                        "type": tag_type,
                        "aliases": aliases,
                        "color": color,
                    }
            elif kind in {"group", "groups"}:
                title = " ".join(str(payload.get("title") or "").split())
                note = " ".join(str(payload.get("note") or payload.get("summary") or "").split())
                color = str(payload.get("color") or "blue").strip().lower()
                if color not in {"blue", "teal", "green", "orange", "pink", "purple", "gray"}:
                    color = "blue"
                if merge_into_id:
                    changes = _merge_semantic_groups(
                        conn,
                        source_id=item_id,
                        target_id=merge_into_id,
                        changed_at_ms=timestamp,
                    )
                else:
                    if conn.execute(
                        "SELECT 1 FROM memory_semantic_groups WHERE group_id = ?",
                        (item_id,),
                    ).fetchone() is None:
                        raise ValueError(f"semantic group not found: {item_id}")
                    conn.execute(
                        """
                        INSERT INTO memory_group_overrides(context_group_id, title, note, color_token, updated_at_ms)
                        VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(context_group_id) DO UPDATE SET
                            title = excluded.title,
                            note = excluded.note,
                            color_token = excluded.color_token,
                            updated_at_ms = excluded.updated_at_ms
                        """,
                        (item_id, title, note, color, timestamp),
                    )
                    changes = {"title": title, "note": note, "color": color}
            elif kind in {"negative", "tombstone"}:
                reason = " ".join(str(payload.get("reason") or "user_edit").split())
                active = 1 if bool(payload.get("active", True)) else 0
                cursor = conn.execute(
                    "UPDATE memory_tombstones SET reason = ?, active = ? WHERE CAST(id AS TEXT) = ?",
                    (reason, active, item_id),
                )
                if cursor.rowcount != 1:
                    raise ValueError(f"negative memory not found: {item_id}")
                changes = {"reason": reason, "active": bool(active)}
            else:
                raise ValueError(f"unsupported memory edit kind: {kind}")
            retrieval_report = rebuild_retrieval_docs(conn, project="")

        return self._finish_memory_edit(
            kind=kind,
            item_id=item_id,
            payload=payload,
            changes=changes,
            retrieval_report=retrieval_report,
        )

    def _finish_memory_edit(
        self,
        *,
        kind: str,
        item_id: str,
        payload: Mapping[str, object],
        changes: Mapping[str, object],
        retrieval_report: Mapping[str, object],
    ) -> dict[str, object]:
        if self.cache_invalidator is not None:
            self.cache_invalidator()
        result = {
            "schemaVersion": "rag-ime.memory-edit.v1",
            "ok": True,
            "kind": kind,
            "id": item_id,
            "changes": changes,
            "retrievalDocs": retrieval_report,
        }
        audit_id = self._audit("memory_edit", kind, item_id, dict(payload), result)
        self._bump_runtime_revision()
        self.events.publish("memory_changed", {"kind": kind, "id": item_id, "changes": changes})
        return {**result, **self.revision(audit_id=audit_id).payload()}

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
        deployment = _safe_mapping(self.deployment_provider) if self.deployment_provider else {}
        voice = read_voice_control_status(self.voice_support_directory)
        voice_agent = _mapping(voice.get("agent"))
        recognition = _mapping(voice.get("recognition"))
        deployed_recognition = _mapping(recognition.get("deployed"))
        last_voice_session = _mapping(recognition.get("lastSession"))
        voice_running = voice_agent.get("running") is True
        microphone_allowed = voice_agent.get("microphoneAuthorization") == "authorized"
        accessibility_allowed = voice_agent.get("accessibilityTrusted") is True
        recognition_state = _string_value(deployed_recognition.get("state"))
        recognition_ready = bool(
            recognition_state == "ready"
            and deployed_recognition.get("secondPass") is True
            and deployed_recognition.get("semanticSmoothing") is True
            and deployed_recognition.get("fullResultReplacement") is True
        )
        recognition_detail = {
            "ready": "语音代理已启用二遍识别请求和完整结果替换；真实修订效果以最近一次定稿为准",
            "restart_required": "语音代理安装已更新，需要重启后确认完整定稿能力",
            "outdated": "语音代理安装版本过旧，缺少完整定稿能力",
            "missing": "未找到语音代理安装包",
            "unreadable": "语音代理安装包存在，但能力标记无法读取",
            "unsupported": "运行中的语音代理未报告完整定稿能力",
        }.get(recognition_state, "尚未取得语音代理的完整定稿能力状态")
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
            **(
                {
                    "deployment": _component(
                        "deployment",
                        deployment.get("ok") is True,
                        _string_value(deployment.get("summary")) or "尚未完成安装一致性审计",
                        deployment,
                    )
                }
                if deployment
                else {}
            ),
            "voiceAgent": _component(
                "voiceAgent",
                voice_running,
                "运行中" if voice_running else "未运行或状态已失效",
                voice_agent,
            ),
            "voiceMicrophone": _component(
                "voiceMicrophone",
                microphone_allowed,
                "已授权" if microphone_allowed else "未授权",
                {"authorization": voice_agent.get("microphoneAuthorization", "unknown")},
            ),
            "voiceAccessibility": _component(
                "voiceAccessibility",
                accessibility_allowed,
                "已授权" if accessibility_allowed else "未授权",
                {},
            ),
            "voiceRecognition": _component(
                "voiceRecognition",
                recognition_ready,
                recognition_detail,
                {
                    "deployed": deployed_recognition,
                    "lastSession": last_voice_session,
                },
            ),
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

    def _summary_counts(self) -> dict[str, object]:
        names = {
            "eventCount": "input_events",
            "memoryItemCount": "memory_items",
            "memoryBookCount": "memory_books",
            "memoryAtomCount": "memory_atoms",
            "retrievalDocCount": "memory_retrieval_docs",
        }
        result: dict[str, object] = {}
        with self._connect() as conn:
            tables = {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
            for key, table in names.items():
                result[key] = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]) if table in tables else 0
            if "memory_compile_state" in tables:
                result["pendingCompileEvents"] = int(conn.execute("SELECT COALESCE(SUM(pending_event_count), 0) FROM memory_compile_state").fetchone()[0])
            else:
                result["pendingCompileEvents"] = 0
            if "agent_memory_sources" in tables:
                source_counts = conn.execute(
                    """
                    SELECT
                        COUNT(*) AS evidence_count,
                        SUM(CASE WHEN disposition = 'not_for_memory' THEN 1 ELSE 0 END)
                            AS forgotten_count,
                        SUM(CASE WHEN disposition = 'needs_review' THEN 1 ELSE 0 END)
                            AS needs_review_count
                    FROM agent_memory_sources
                    WHERE status = 'active'
                    """
                ).fetchone()
                result["evidenceSourceCount"] = int(
                    source_counts["evidence_count"] or 0
                )
                result["forgottenSourceCount"] = int(
                    source_counts["forgotten_count"] or 0
                )
                result["needsReviewSourceCount"] = int(
                    source_counts["needs_review_count"] or 0
                )
            else:
                result["evidenceSourceCount"] = 0
                result["forgottenSourceCount"] = 0
                result["needsReviewSourceCount"] = 0
            if {
                "memory_items",
                "memory_atoms",
                "memory_books",
                "agent_memory_sources",
            }.issubset(tables):
                owner_rows = conn.execute(
                    """
                    WITH owner_records AS (
                        SELECT owner_kind, owner_id FROM memory_items
                        UNION ALL
                        SELECT owner_kind, owner_id FROM memory_atoms
                        UNION ALL
                        SELECT owner_kind, owner_id FROM memory_books
                        UNION ALL
                        SELECT owner_kind, owner_id FROM agent_memory_sources
                        WHERE status = 'active'
                    )
                    SELECT owner_kind, owner_id, COUNT(*) AS item_count
                    FROM owner_records
                    GROUP BY owner_kind, owner_id
                    ORDER BY
                        CASE owner_kind
                            WHEN 'user' THEN 0
                            WHEN 'shared' THEN 1
                            WHEN 'agent' THEN 2
                            WHEN 'session' THEN 3
                            ELSE 4
                        END,
                        owner_id
                    """
                ).fetchall()
                result["owners"] = [
                    {
                        "ownerKind": str(row["owner_kind"]),
                        "ownerId": str(row["owner_id"]),
                        "itemCount": int(row["item_count"] or 0),
                    }
                    for row in owner_rows
                ]
            else:
                result["owners"] = []
        return result

    def _memory_books(self, request: PageRequest) -> tuple[list[dict[str, object]], str]:
        limit = request.limit
        cursor = _cursor_int(request.cursor)
        like = f"%{request.query}%"
        event_ranges: dict[str, tuple[int, int]] = {}
        atoms_by_book: dict[str, list[dict[str, object]]] = {}
        owner_clause, owner_params = _page_owner_filter(request, table_alias="memory_books")
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT rowid AS row_cursor, book_id AS id, title, summary,
                       book_type AS type, project, app, tags_json,
                       source_event_ids_json, memory_atom_ids_json,
                       owner_kind, owner_id,
                       status, confidence, quality_score, created_at_ms, updated_at_ms,
                       archived_at_ms, last_active_at_ms, archive_reason
                FROM memory_books
                WHERE (? = 0 OR rowid < ?)
                  AND (? = '' OR title LIKE ? OR summary LIKE ? OR project LIKE ? OR app LIKE ? OR book_type LIKE ?)
                  AND (? = '' OR status = ?)
                  AND {owner_clause}
                ORDER BY rowid DESC LIMIT ?
                """,
                (
                    cursor, cursor, request.query, like, like, like, like, like,
                    request.status, request.status, *owner_params, limit + 1,
                ),
            ).fetchall()
            for row in rows:
                event_ids = [int(value) for value in _json_list(row["source_event_ids_json"]) if str(value).isdigit()]
                if event_ids:
                    placeholders = ",".join("?" for _ in event_ids)
                    range_row = conn.execute(
                        f"SELECT MIN(created_at_ms), MAX(created_at_ms) FROM input_events WHERE id IN ({placeholders})",
                        event_ids,
                    ).fetchone()
                    if range_row is not None and range_row[0] is not None:
                        event_ranges[str(row["id"])] = (int(range_row[0]), int(range_row[1]))
                atom_ids = [str(value) for value in _json_list(row["memory_atom_ids_json"]) if str(value)]
                if atom_ids:
                    atom_placeholders = ",".join("?" for _ in atom_ids)
                    atom_rows = conn.execute(
                        f"""
                        SELECT id, kind AS type, COALESCE(NULLIF(canonical_text, ''), text) AS text,
                               status, confidence, updated_at_ms AS updatedAtMs
                        FROM memory_atoms
                        WHERE id IN ({atom_placeholders}) AND privacy_level != 'sensitive'
                          AND owner_kind = ? AND owner_id = ?
                        ORDER BY updated_at_ms DESC
                        """,
                        (*atom_ids, str(row["owner_kind"]), str(row["owner_id"])),
                    ).fetchall()
                    atoms_by_book[str(row["id"])] = [dict(atom) for atom in atom_rows]
        has_more = len(rows) > limit
        rows = rows[:limit]
        items: list[dict[str, object]] = []
        for row in rows:
            item = dict(row)
            item.pop("row_cursor", None)
            item["ownerKind"] = str(item.pop("owner_kind", "user") or "user")
            item["ownerId"] = str(item.pop("owner_id", "default") or "default")
            item["tags"] = _json_list(item.pop("tags_json", "[]"))
            item["sourceEventCount"] = len(_json_list(item.pop("source_event_ids_json", "[]")))
            item["atomCount"] = len(_json_list(item.pop("memory_atom_ids_json", "[]")))
            item["memories"] = atoms_by_book.get(str(item["id"]), [])
            source_range = event_ranges.get(str(item["id"]))
            item["sourceStartMs"] = source_range[0] if source_range else 0
            item["sourceEndMs"] = source_range[1] if source_range else 0
            item["archivedAtMs"] = int(item.pop("archived_at_ms", 0) or 0)
            item["lastActiveAtMs"] = int(item.pop("last_active_at_ms", 0) or 0)
            item["archiveReason"] = str(item.pop("archive_reason", "") or "")
            items.append(item)
        next_cursor = str(rows[-1]["row_cursor"]) if has_more and rows else ""
        return items, next_cursor

    def _memory_atoms(self, request: PageRequest) -> tuple[list[dict[str, object]], str]:
        limit = request.limit
        cursor = _cursor_int(request.cursor)
        like = f"%{request.query}%"
        owner_clause, owner_params = _page_owner_filter(request, table_alias="memory_atoms")
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT rowid AS row_cursor, id, kind AS type,
                       COALESCE(NULLIF(canonical_text, ''), text) AS text,
                       source_event_ids_json, scope_project AS project,
                       scope_app AS app, owner_kind, owner_id,
                       status, confidence, quality_score,
                       created_at_ms, last_used_at_ms, updated_at_ms
                FROM memory_atoms
                WHERE privacy_level != 'sensitive'
                  AND (? = 0 OR rowid < ?)
                  AND (? = '' OR text LIKE ? OR canonical_text LIKE ? OR kind LIKE ? OR scope_project LIKE ? OR scope_app LIKE ?)
                  AND (? = '' OR status = ?)
                  AND {owner_clause}
                ORDER BY rowid DESC LIMIT ?
                """,
                (
                    cursor, cursor, request.query, like, like, like, like, like,
                    request.status, request.status, *owner_params, limit + 1,
                ),
            ).fetchall()
            tag_rows = conn.execute(
                """
                SELECT mat.memory_atom_id, mt.tag
                FROM memory_atom_tags mat
                JOIN memory_tags mt ON CAST(mt.id AS TEXT) = CAST(mat.tag_id AS TEXT)
                WHERE mt.status = 'active' AND mt.source IN ('dsv4', 'user')
                """
            ).fetchall()
        tags_by_atom: dict[str, list[str]] = {}
        for atom_id, tag in tag_rows:
            tags_by_atom.setdefault(str(atom_id), []).append(str(tag))
        has_more = len(rows) > limit
        rows = rows[:limit]
        items: list[dict[str, object]] = []
        for row in rows:
            item = dict(row)
            item.pop("row_cursor", None)
            item["ownerKind"] = str(item.pop("owner_kind", "user") or "user")
            item["ownerId"] = str(item.pop("owner_id", "default") or "default")
            text = str(item.get("text") or "")
            item["textHash"] = _text_hash(text)
            item["textChars"] = len(text)
            item["textPreview"] = text
            item["sourceEventCount"] = len(_json_list(item.pop("source_event_ids_json", "[]")))
            item["tags"] = tags_by_atom.get(str(item["id"]), [])
            items.append(item)
        next_cursor = str(rows[-1]["row_cursor"]) if has_more and rows else ""
        return items, next_cursor

    def _memory_tags(self, request: PageRequest) -> tuple[list[dict[str, object]], str]:
        limit = request.limit
        cursor = _cursor_int(request.cursor)
        like = f"%{request.query}%"
        memories_by_tag: dict[str, list[dict[str, object]]] = {}
        connections_by_tag: dict[str, list[dict[str, object]]] = {}
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT mt.id AS row_cursor, CAST(mt.id AS TEXT) AS id, mt.tag,
                       mt.tag_type AS type, mt.description, mt.source, mt.status,
                       mt.quality_score, mt.updated_at_ms,
                       COALESCE(mtp.color_token, 'blue') AS color_token,
                       COALESCE(mtp.aliases_json, '[]') AS aliases_json,
                       (SELECT COUNT(*) FROM memory_item_tags mit WHERE mit.tag_id = mt.id)
                         + (SELECT COUNT(*) FROM memory_atom_tags mat WHERE CAST(mat.tag_id AS TEXT) = CAST(mt.id AS TEXT))
                         AS item_count,
                       (SELECT COUNT(*) FROM memory_tag_edges e WHERE e.src_tag_id = mt.id OR e.dst_tag_id = mt.id) AS edge_count
                FROM memory_tags mt
                LEFT JOIN memory_tag_profiles mtp ON mtp.tag_id = mt.id
                WHERE (? = 0 OR mt.id < ?)
                  AND mt.status = 'active'
                  AND mt.source IN ('dsv4', 'user')
                  AND (? = '' OR mt.tag LIKE ? OR mt.tag_type LIKE ?)
                ORDER BY mt.quality_score DESC, mt.id DESC LIMIT ?
                """,
                (cursor, cursor, request.query, like, like, limit + 1),
            ).fetchall()
            for row in rows:
                tag_id = str(row["id"])
                atom_rows = conn.execute(
                    """
                    SELECT ma.id, ma.kind AS type,
                           COALESCE(NULLIF(ma.canonical_text, ''), ma.text) AS text,
                           ma.status, ma.confidence, ma.updated_at_ms AS updatedAtMs
                    FROM memory_atom_tags mat
                    JOIN memory_atoms ma ON ma.id = mat.memory_atom_id
                    WHERE CAST(mat.tag_id AS TEXT) = ? AND ma.privacy_level != 'sensitive'
                    ORDER BY mat.weight DESC, ma.updated_at_ms DESC
                    LIMIT 30
                    """,
                    (tag_id,),
                ).fetchall()
                memories_by_tag[tag_id] = [dict(atom) for atom in atom_rows]
                edge_rows = conn.execute(
                    """
                    SELECT CAST(other.id AS TEXT) AS id, other.tag,
                           e.edge_type AS type, e.weight, e.evidence_count AS evidenceCount
                    FROM memory_tag_edges e
                    JOIN memory_tags other
                      ON other.id = CASE WHEN CAST(e.src_tag_id AS TEXT) = ? THEN e.dst_tag_id ELSE e.src_tag_id END
                    WHERE CAST(e.src_tag_id AS TEXT) = ? OR CAST(e.dst_tag_id AS TEXT) = ?
                    ORDER BY e.weight DESC, e.evidence_count DESC
                    LIMIT 20
                    """,
                    (tag_id, tag_id, tag_id),
                ).fetchall()
                connections_by_tag[tag_id] = [dict(edge) for edge in edge_rows]
        has_more = len(rows) > limit
        rows = rows[:limit]
        items = []
        for row in rows:
            item = dict(row)
            item.pop("row_cursor", None)
            item["aliases"] = _json_list(item.pop("aliases_json", "[]"))
            item["memories"] = memories_by_tag.get(str(item["id"]), [])
            item["connections"] = connections_by_tag.get(str(item["id"]), [])
            items.append(item)
        next_cursor = str(rows[-1]["row_cursor"]) if has_more and rows else ""
        return items, next_cursor

    def _memory_phrases(self, request: PageRequest) -> tuple[list[dict[str, object]], str]:
        limit = request.limit
        cursor = _cursor_int(request.cursor)
        like = f"%{request.query}%"
        owner_clause, owner_params = _page_owner_filter(request, table_alias="mi")
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT
                    mi.id AS row_cursor,
                    mi.memory_id,
                    mi.text,
                    mi.normalized_text,
                    mi.project,
                    mi.app,
                    mi.owner_kind,
                    mi.owner_id,
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
                  AND {owner_clause}
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
                    *owner_params,
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
                    "textPreview": text,
                    "text": text,
                    "project": str(row["project"] or ""),
                    "app": str(row["app"] or ""),
                    "ownerKind": str(row["owner_kind"] or "user"),
                    "ownerId": str(row["owner_id"] or "default"),
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

    def _memory_evidence(
        self,
        request: PageRequest,
    ) -> tuple[list[dict[str, object]], str]:
        limit = request.limit
        cursor = _cursor_int(request.cursor)
        like = f"%{request.query}%"
        owner_clause, owner_params = _page_owner_filter(
            request,
            table_alias="source",
        )
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT
                    event.id AS row_cursor,
                    source.source_id,
                    source.source_kind,
                    source.trust_class,
                    source.disposition,
                    source.disposition_reason,
                    source.owner_kind,
                    source.owner_id,
                    source.curation_run_id,
                    source.created_at_ms,
                    source.disposition_updated_at_ms,
                    source.metadata_json,
                    event.source AS transport_source,
                    event.committed_text,
                    event.project,
                    event.app
                FROM agent_memory_sources AS source
                JOIN input_events AS event ON event.id = source.input_event_id
                WHERE source.status = 'active'
                  AND (? = 0 OR event.id < ?)
                  AND (
                      ? = ''
                      OR event.committed_text LIKE ?
                      OR source.source_kind LIKE ?
                      OR source.disposition_reason LIKE ?
                      OR event.project LIKE ?
                      OR event.app LIKE ?
                  )
                  AND (? = '' OR source.disposition = ?)
                  AND {owner_clause}
                ORDER BY event.id DESC
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
                    like,
                    request.status,
                    request.status,
                    *owner_params,
                    limit + 1,
                ),
            ).fetchall()
        has_more = len(rows) > limit
        rows = rows[:limit]
        items: list[dict[str, object]] = []
        for row in rows:
            raw_text = compact_whitespace(str(row["committed_text"] or ""))
            sensitive = (
                str(row["disposition_reason"] or "") == "sensitive_input"
                or looks_sensitive(raw_text)
            )
            display_text = "敏感输入已排除，正文不显示" if sensitive else raw_text
            disposition = str(row["disposition"] or "pending")
            items.append(
                {
                    "id": str(row["source_id"]),
                    "itemId": str(row["source_id"]),
                    "type": str(row["source_kind"] or "user_final"),
                    "source": str(row["transport_source"] or ""),
                    "title": display_text[:160] or "空输入证据",
                    "detail": str(row["disposition_reason"] or "")
                    or _memory_disposition_label(disposition),
                    "text": "" if sensitive else raw_text,
                    "textPreview": display_text,
                    "textHash": _text_hash(raw_text),
                    "textChars": len(raw_text),
                    "sensitive": sensitive,
                    "project": str(row["project"] or ""),
                    "app": str(row["app"] or ""),
                    "ownerKind": str(row["owner_kind"] or "user"),
                    "ownerId": str(row["owner_id"] or "default"),
                    "status": disposition,
                    "disposition": disposition,
                    "dispositionReason": str(
                        row["disposition_reason"] or ""
                    ),
                    "trustClass": str(row["trust_class"] or ""),
                    "curationRunId": str(row["curation_run_id"] or ""),
                    "metadata": _json_mapping(row["metadata_json"]),
                    "createdAtMs": int(row["created_at_ms"] or 0),
                    "updatedAtMs": int(
                        row["disposition_updated_at_ms"]
                        or row["created_at_ms"]
                        or 0
                    ),
                    "canForget": disposition
                    in {"pending", "remember", "needs_review"},
                    "canRestore": (
                        disposition in {"not_for_memory", "expired"}
                        and not sensitive
                    ),
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
                SELECT msg.rowid AS row_cursor, msg.group_id AS id,
                       'semantic' AS level, msg.project, '' AS app,
                       COUNT(msgm.member_id) AS event_count, msg.updated_at_ms,
                       COALESCE(NULLIF(mgo.title, ''), msg.title) AS title,
                       COALESCE(NULLIF(mgo.note, ''), msg.description) AS note,
                       COALESCE(mgo.color_token, 'blue') AS color_token,
                       msg.aliases_json, msg.tags_json, msg.confidence, msg.quality_score
                FROM memory_semantic_groups msg
                LEFT JOIN memory_semantic_group_members msgm ON msgm.group_id = msg.group_id
                LEFT JOIN memory_group_overrides mgo ON mgo.context_group_id = msg.group_id
                WHERE msg.status = 'active'
                  AND (? = 0 OR msg.rowid < ?)
                  AND (? = '' OR msg.group_id LIKE ? OR msg.title LIKE ? OR msg.description LIKE ? OR msg.project LIKE ?)
                GROUP BY msg.group_id, msg.rowid, msg.project, msg.updated_at_ms,
                         msg.title, msg.description, mgo.title, mgo.note, mgo.color_token
                ORDER BY msg.quality_score DESC, row_cursor DESC LIMIT ?
                """,
                (cursor, cursor, request.query, query, query, query, query, limit + 1),
            ).fetchall()
        has_more = len(rows) > limit
        rows = rows[:limit]
        items: list[dict[str, object]] = []
        for row in rows:
            item = dict(row)
            item.pop("row_cursor", None)
            item["aliases"] = _json_list(item.pop("aliases_json", "[]"))
            item["tags"] = _json_list(item.pop("tags_json", "[]"))
            item["ruleDescription"] = f"内容主题 · {int(item.get('event_count') or 0)} 条知识"
            item["latestAtMs"] = int(item.get("updated_at_ms") or 0)
            items.append(item)
        return items, str(rows[-1]["row_cursor"]) if has_more and rows else ""

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
        if action == "register_input_source":
            return ["/bin/bash", str(self._helper_path("refresh_squirrel_input_source_registration.sh"))]
        uid = str(os.getuid())
        commands = {
            "restart_predictor": ["launchctl", "kickstart", "-k", f"gui/{uid}/com.rag-ime.mlx-predictor"],
            "redeploy_rime": ["/bin/bash", str(self._helper_path("install_squirrel_rag_config.sh"))],
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

    def _mark_diagnostics_external_supervisor_required(
        self,
        job: RuntimeJob,
        *,
        payload_sha256: str,
        command_sha256: str,
    ) -> None:
        now = _now_ms()
        with self._jobs_lock:
            job.status = "external-supervisor-required"
            job.started_at_ms = now
            job.finished_at_ms = now
            job.result = {
                "code": "external-supervisor-required",
                "externalAction": {
                    "action": job.action,
                    "receiptId": job.job_id,
                    "payloadSha256": payload_sha256,
                    "commandSha256": command_sha256,
                },
            }
            job.error = ""
            terminal_payload = job.payload()
        self._audit(
            "runtime_action_external_supervisor_required",
            "runtime",
            job.action,
            {"jobId": job.job_id},
            terminal_payload,
        )
        self.events.publish(
            "runtime_job_changed",
            {"jobId": job.job_id, "status": job.status, "action": job.action, "error": ""},
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


_PLANNING_TASK_SAVE_FIELDS = {
    "taskId",
    "date",
    "title",
    "detail",
    "priority",
    "status",
    "dueAtMs",
    "goalId",
    "project",
}
_PLANNING_TASK_ACTION_FIELDS = {"taskId", "action"}
_PLANNING_GOAL_SAVE_FIELDS = {
    "goalId",
    "title",
    "detail",
    "horizon",
    "status",
    "priority",
    "targetDate",
    "project",
}
_WORK_APPLY_FIELDS = {
    "expectedRuntimeRevision",
    "previewToken",
    "payloadSha256",
    "confirmText",
}
_PLANNING_TASK_COLUMNS = (
    "task_id",
    "plan_date",
    "title",
    "detail",
    "status",
    "priority",
    "due_at_ms",
    "project",
    "goal_id",
    "source",
    "confidence",
    "created_at_ms",
    "updated_at_ms",
    "completed_at_ms",
    "metadata_json",
)
_PLANNING_GOAL_COLUMNS = (
    "goal_id",
    "title",
    "detail",
    "horizon",
    "status",
    "priority",
    "target_date",
    "project",
    "created_at_ms",
    "updated_at_ms",
    "completed_at_ms",
    "metadata_json",
)


def _normalize_planning_work_payload(
    kind: str,
    payload: Mapping[str, object],
    *,
    project: str,
) -> dict[str, object]:
    if kind == "task.action":
        task_id = compact_whitespace(str(payload.get("taskId") or ""))
        action = compact_whitespace(str(payload.get("action") or "")).lower()
        if not task_id:
            raise ManagementWorkError("invalid_request", "taskId is required.")
        if action not in {"start", "complete", "reopen", "cancel"}:
            raise ManagementWorkError("invalid_request", "Unsupported planning task action.")
        return {"taskId": task_id, "action": action}
    if kind == "goal.save":
        title = compact_whitespace(str(payload.get("title") or ""))
        if not title:
            raise ManagementWorkError("invalid_request", "Goal title is required.")
        status = compact_whitespace(str(payload.get("status") or "active")).lower()
        if status not in {"active", "completed", "archived"}:
            raise ManagementWorkError("invalid_request", "Unsupported planning goal status.")
        target_date = compact_whitespace(str(payload.get("targetDate") or ""))
        if target_date:
            try:
                target_date = date.fromisoformat(target_date).isoformat()
            except ValueError as exc:
                raise ManagementWorkError(
                    "invalid_request",
                    "Goal target date must use YYYY-MM-DD.",
                ) from exc
        normalized_goal: dict[str, object] = {
            "title": title,
            "detail": compact_whitespace(str(payload.get("detail") or "")),
            "horizon": compact_whitespace(str(payload.get("horizon") or "long_term")) or "long_term",
            "status": status,
            "priority": _strict_bounded_int(payload.get("priority", 1), field="priority", minimum=0, maximum=3),
            "targetDate": target_date,
            "project": compact_whitespace(str(payload.get("project") or project)),
        }
        goal_id = compact_whitespace(str(payload.get("goalId") or ""))
        if goal_id:
            normalized_goal["goalId"] = goal_id
        return normalized_goal
    if kind != "task.save":
        raise ManagementWorkError("unsupported_mutation", "Unsupported planning mutation.")
    title = compact_whitespace(str(payload.get("title") or ""))
    day = compact_whitespace(str(payload.get("date") or ""))
    if not title:
        raise ManagementWorkError("invalid_request", "Task title is required.")
    if not day:
        raise ManagementWorkError("invalid_request", "Task date is required.")
    try:
        date.fromisoformat(day)
    except ValueError as exc:
        raise ManagementWorkError("invalid_request", "Task date must use YYYY-MM-DD.") from exc
    status = compact_whitespace(str(payload.get("status") or "todo")).lower()
    if status not in {"todo", "in_progress", "done", "cancelled"}:
        raise ManagementWorkError("invalid_request", "Unsupported planning task status.")
    priority = _strict_bounded_int(payload.get("priority", 1), field="priority", minimum=0, maximum=3)
    normalized: dict[str, object] = {
        "date": day,
        "title": title,
        "detail": compact_whitespace(str(payload.get("detail") or "")),
        "priority": priority,
        "status": status,
        "goalId": compact_whitespace(str(payload.get("goalId") or "")),
        "project": compact_whitespace(str(payload.get("project") or project)),
    }
    task_id = compact_whitespace(str(payload.get("taskId") or ""))
    if task_id:
        normalized["taskId"] = task_id
    if payload.get("dueAtMs") is not None:
        normalized["dueAtMs"] = _strict_nonnegative_int(payload.get("dueAtMs"), field="dueAtMs")
    return normalized


def _reject_unknown_work_fields(payload: Mapping[str, object], *, kind: str) -> None:
    allowed_domain = {
        "task.save": _PLANNING_TASK_SAVE_FIELDS,
        "task.action": _PLANNING_TASK_ACTION_FIELDS,
        "goal.save": _PLANNING_GOAL_SAVE_FIELDS,
    }.get(kind)
    if allowed_domain is None:
        raise ManagementWorkError("unsupported_mutation", "Unsupported planning mutation.")
    _require_exact_keys(payload, required=_WORK_APPLY_FIELDS, optional=allowed_domain)


def _require_exact_keys(
    payload: Mapping[str, object],
    *,
    required: set[str],
    optional: set[str],
) -> None:
    keys = {str(key) for key in payload}
    missing = sorted(required - keys)
    if missing:
        raise ManagementWorkError("invalid_request", f"Missing required fields: {', '.join(missing)}.")
    unknown = sorted(keys - required - optional)
    if unknown:
        raise ManagementWorkError("invalid_request", f"Unsupported fields: {', '.join(unknown)}.")


def _planning_subject_revision(
    conn: sqlite3.Connection,
    *,
    kind: str,
    payload: Mapping[str, object],
) -> str:
    if kind == "goal.save":
        goal_id = compact_whitespace(str(payload.get("goalId") or ""))
        if not goal_id:
            return "new"
        return _snapshot_revision(_planning_goal_snapshot(conn, goal_id))
    task_id = compact_whitespace(str(payload.get("taskId") or ""))
    if not task_id:
        return "new"
    snapshot = _planning_task_snapshot(conn, task_id)
    if kind == "task.action" and snapshot is None:
        raise ManagementWorkError("domain_not_found", "The planning task was not found.")
    return _snapshot_revision(snapshot)


def _planning_task_snapshot(conn: sqlite3.Connection, task_id: str) -> dict[str, object] | None:
    if not task_id:
        return None
    row = conn.execute(
        "SELECT * FROM planning_tasks WHERE task_id = ?",
        (task_id,),
    ).fetchone()
    if row is None:
        return None
    return {column: row[column] for column in _PLANNING_TASK_COLUMNS}


def _planning_goal_snapshot(conn: sqlite3.Connection, goal_id: str) -> dict[str, object] | None:
    if not goal_id:
        return None
    row = conn.execute(
        "SELECT * FROM planning_goals WHERE goal_id = ?",
        (goal_id,),
    ).fetchone()
    if row is None:
        return None
    return {column: row[column] for column in _PLANNING_GOAL_COLUMNS}


def _snapshot_revision(snapshot: Mapping[str, object] | None) -> str:
    if snapshot is None:
        return "missing"
    return canonical_payload_sha256(snapshot)


def _history_subject_snapshot(conn: sqlite3.Connection, event_id: int) -> dict[str, object]:
    row = conn.execute(
        """
        SELECT id, created_at_ms, source, app, project
        FROM input_events
        WHERE id = ?
        LIMIT 1
        """,
        (event_id,),
    ).fetchone()
    if row is None:
        raise ManagementWorkError("domain_not_found", "The history record was not found.")
    tombstones = conn.execute(
        """
        SELECT id
        FROM memory_tombstones
        WHERE target_type = 'memory_id' AND target_value = ? AND active = 1
        ORDER BY id
        """,
        (f"event:{event_id}",),
    ).fetchall()
    return {
        "event": {
            "id": int(row["id"]),
            "createdAtMs": int(row["created_at_ms"]),
            "source": str(row["source"]),
            "app": str(row["app"]),
            "project": str(row["project"]),
        },
        "activeTombstoneIds": [int(item["id"]) for item in tombstones],
    }


_MEMORY_BOOK_ARCHIVE_COLUMNS = (
    "book_id",
    "book_type",
    "book_key",
    "title",
    "status",
    "archived_at_ms",
    "last_active_at_ms",
    "archive_reason",
    "updated_at_ms",
    "metadata_json",
)


def _memory_book_subject_snapshot(conn: sqlite3.Connection, book_id: str) -> dict[str, object]:
    row = conn.execute(
        f"SELECT {', '.join(_MEMORY_BOOK_ARCHIVE_COLUMNS)} FROM memory_books WHERE book_id = ? LIMIT 1",
        (book_id,),
    ).fetchone()
    if row is None:
        raise ManagementWorkError("domain_not_found", "The memory book was not found.")
    return {column: row[column] for column in _MEMORY_BOOK_ARCHIVE_COLUMNS}


def _restore_memory_book_snapshot(conn: sqlite3.Connection, snapshot: Mapping[str, object]) -> None:
    missing = [column for column in _MEMORY_BOOK_ARCHIVE_COLUMNS if column not in snapshot]
    if missing:
        raise ManagementWorkError(
            "stored_contract_invalid",
            "The stored memory book snapshot is incomplete.",
        )
    book_id = compact_whitespace(str(snapshot["book_id"] or ""))
    if not book_id:
        raise ManagementWorkError(
            "stored_contract_invalid",
            "The stored memory book snapshot has no book id.",
        )
    updated = conn.execute(
        """
        UPDATE memory_books
        SET book_type = ?, book_key = ?, title = ?, status = ?,
            archived_at_ms = ?, last_active_at_ms = ?, archive_reason = ?,
            updated_at_ms = ?, metadata_json = ?
        WHERE book_id = ?
        """,
        (
            snapshot["book_type"],
            snapshot["book_key"],
            snapshot["title"],
            snapshot["status"],
            snapshot["archived_at_ms"],
            snapshot["last_active_at_ms"],
            snapshot["archive_reason"],
            snapshot["updated_at_ms"],
            snapshot["metadata_json"],
            book_id,
        ),
    )
    if updated.rowcount != 1:
        raise ManagementWorkError(
            "rollback_state_changed",
            "The memory book no longer exists.",
        )


def _planning_preview_items(kind: str, payload: Mapping[str, object]) -> list[str]:
    if kind == "task.action":
        return [
            f"任务: {payload.get('taskId', '')}",
            f"动作: {payload.get('action', '')}",
        ]
    if kind == "goal.save":
        horizon_label = {
            "today": "今天",
            "short_term": "近期",
            "medium_term": "阶段目标",
            "long_term": "长期目标",
        }.get(str(payload.get("horizon") or ""), "自定义周期")
        status_label = {
            "active": "进行中",
            "completed": "已完成",
            "archived": "已归档",
        }.get(str(payload.get("status") or ""), "待处理")
        return [
            f"目标: {payload.get('title', '')}",
            f"时间范围: {horizon_label}",
            f"状态: {status_label}",
        ]
    return [
        f"日期: {payload.get('date', '')}",
        f"任务: {payload.get('title', '')}",
        f"状态: {payload.get('status', '')}",
    ]


def _restore_planning_task(conn: sqlite3.Connection, snapshot: Mapping[str, object]) -> None:
    missing = [column for column in _PLANNING_TASK_COLUMNS if column not in snapshot]
    if missing:
        raise ManagementWorkError("stored_contract_invalid", "The stored task snapshot is incomplete.")
    placeholders = ", ".join("?" for _ in _PLANNING_TASK_COLUMNS)
    columns = ", ".join(_PLANNING_TASK_COLUMNS)
    conn.execute(
        f"INSERT OR REPLACE INTO planning_tasks({columns}) VALUES ({placeholders})",
        tuple(snapshot[column] for column in _PLANNING_TASK_COLUMNS),
    )


def _restore_planning_goal(conn: sqlite3.Connection, snapshot: Mapping[str, object]) -> None:
    missing = [column for column in _PLANNING_GOAL_COLUMNS if column not in snapshot]
    if missing:
        raise ManagementWorkError("stored_contract_invalid", "The stored goal snapshot is incomplete.")
    placeholders = ", ".join("?" for _ in _PLANNING_GOAL_COLUMNS)
    columns = ", ".join(_PLANNING_GOAL_COLUMNS)
    conn.execute(
        f"INSERT OR REPLACE INTO planning_goals({columns}) VALUES ({placeholders})",
        tuple(snapshot[column] for column in _PLANNING_GOAL_COLUMNS),
    )


def _strict_nonnegative_int(value: object, *, field: str) -> int:
    return _strict_bounded_int(value, field=field, minimum=0, maximum=9_223_372_036_854_775_807)


def _strict_bounded_int(value: object, *, field: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        raise ManagementWorkError("invalid_request", f"{field} must be an integer.")
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ManagementWorkError("invalid_request", f"{field} must be an integer.") from exc
    if parsed < minimum or parsed > maximum:
        raise ManagementWorkError(
            "invalid_request",
            f"{field} must be between {minimum} and {maximum}.",
        )
    return parsed


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

_DIAGNOSTICS_RUNTIME_ACTIONS = {
    "register_input_source",
    "restart_sidecar",
    "restart_predictor",
    "redeploy_rime",
    "open_accessibility_settings",
    "stop_ai",
    "resume_ai",
}
_DIAGNOSTICS_EXTERNAL_ACTIONS = _DIAGNOSTICS_RUNTIME_ACTIONS - _AI_TOGGLE_ACTIONS
_RUNTIME_ACTION_PREVIEWS: dict[str, dict[str, object]] = {
    "register_input_source": {
        "title": "重新注册输入法",
        "items": ["刷新当前用户的 Squirrel 输入源注册。", "不会删除用户词典或输入历史。"],
        "risk": "R2",
    },
    "restart_sidecar": {
        "title": "重启后台服务",
        "items": ["重新启动当前用户的 RAG-IME Sidecar。", "正在进行的本机请求可能需要重试。"],
        "risk": "R2",
    },
    "restart_predictor": {
        "title": "重启本机模型",
        "items": ["重新启动当前用户的 MLX 预测服务。", "模型重新载入期间会暂时没有智能候选。"],
        "risk": "R2",
    },
    "redeploy_rime": {
        "title": "重新部署 Rime 配置",
        "items": ["运行受信任的 Rime 配置部署脚本。", "用户词典和输入历史不会被清空。"],
        "risk": "R3",
    },
    "open_accessibility_settings": {
        "title": "打开辅助功能设置",
        "items": ["打开 macOS 隐私与安全性中的辅助功能页面。", "不会自动授予或撤销任何权限。"],
        "risk": "R1",
    },
    "stop_ai": {
        "title": "暂停智能候选",
        "items": ["暂停提交后的智能候选调度。", "基础 Rime 输入和用户数据保持不变。"],
        "risk": "R1",
    },
    "resume_ai": {
        "title": "恢复智能候选",
        "items": ["恢复提交后的智能候选调度。", "基础 Rime 输入和用户数据保持不变。"],
        "risk": "R1",
    },
}


def _runtime_action_command_sha256(action: str) -> str:
    descriptor = f"rag-ime.runtime-action.v1:{action}".encode("utf-8")
    return "sha256:" + hashlib.sha256(descriptor).hexdigest()


def _runtime_action_preview_summary(action: str) -> dict[str, object]:
    summary = _RUNTIME_ACTION_PREVIEWS.get(action)
    if summary is None:
        raise ManagementWorkError("invalid_request", f"unsupported diagnostics action: {action}")
    return {**summary, "items": list(summary["items"])}


def _constant_time_text_equal(value: object, expected: str) -> bool:
    return hmac.compare_digest(str(value or "").strip(), expected)


def page_request(payload: Mapping[str, object]) -> PageRequest:
    try:
        limit = int(payload.get("limit") or 50)
    except (TypeError, ValueError):
        limit = 50
    visible_owners: list[tuple[str, str]] = []
    raw_owners = payload.get("visibleOwners")
    if isinstance(raw_owners, (list, tuple)):
        for value in raw_owners:
            try:
                if isinstance(value, Mapping):
                    owner = normalize_memory_owner(value.get("ownerKind"), value.get("ownerId"))
                elif isinstance(value, (list, tuple)) and len(value) == 2:
                    owner = normalize_memory_owner(value[0], value[1])
                else:
                    continue
            except ValueError:
                continue
            if owner not in visible_owners:
                visible_owners.append(owner)
    if payload.get("ownerKind") or payload.get("ownerId"):
        owner = normalize_memory_owner(
            payload.get("ownerKind"),
            payload.get("ownerId"),
        )
        if owner not in visible_owners:
            visible_owners.append(owner)
    return PageRequest(
        limit=max(1, min(limit, 100)),
        cursor=str(payload.get("cursor") or ""),
        query=str(payload.get("query") or "").strip(),
        status=str(payload.get("status") or payload.get("filter") or "").strip(),
        kind=str(payload.get("kind") or "").strip(),
        visible_owners=tuple(visible_owners),
    )


def _page_owner_filter(
    request: PageRequest,
    *,
    table_alias: str,
) -> tuple[str, tuple[str, ...]]:
    if not request.visible_owners:
        return "1 = 1", ()
    return sql_memory_owner_predicate(request.visible_owners, table_alias=table_alias)


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
    selected_chars = _integer_value(evidence.get("selectedTextChars"), default=0)
    before_chars = _integer_value(evidence.get("surroundingBeforeChars"), default=0)
    after_chars = _integer_value(evidence.get("surroundingAfterChars"), default=0)
    captured_chars = max(selected_chars, before_chars + after_chars)
    char_counts_reported = any(key in evidence for key in ("selectedTextChars", "surroundingBeforeChars", "surroundingAfterChars"))
    metadata = {
        "source": source,
        "capturedAtMs": created_at_ms,
        "freshnessMs": freshness_ms,
        "freshnessLimitMs": freshness_limit_ms,
        "applied": applied,
        "commitTextMatched": commit_text_matched,
        "failureReason": failure,
        "requestId": _string_value(last_prediction.get("requestId")),
        "selectedTextChars": selected_chars,
        "surroundingBeforeChars": before_chars,
        "surroundingAfterChars": after_chars,
        "capturedContextChars": captured_chars,
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
    if char_counts_reported and captured_chars < 8:
        component = _component(
            "foregroundContext",
            True,
            f"仅采集 {captured_chars} 字；生成仍只使用当前前台内容",
            metadata,
        )
        component["status"] = "degraded"
        return component
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


def _json_list(value: object) -> list[object]:
    if isinstance(value, list):
        return list(value)
    try:
        parsed = json.loads(str(value or "[]"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    return list(parsed) if isinstance(parsed, list) else []


def _json_mapping(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return dict(value)
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _memory_disposition_label(value: str) -> str:
    return {
        "pending": "等待每日整理",
        "remember": "已判定值得保留",
        "not_for_memory": "已从长期记忆排除",
        "needs_review": "需要再次判断",
        "consolidated": "已整理进长期记忆",
        "expired": "已过期",
    }.get(value, value)


def _string_list_value(value: object) -> list[str]:
    if isinstance(value, str):
        raw = value.replace("，", ",").split(",")
    elif isinstance(value, (list, tuple)):
        raw = list(value)
    else:
        raw = []
    result: list[str] = []
    for item in raw:
        text = " ".join(str(item or "").split())[:48]
        if text and text not in result:
            result.append(text)
    return result[:24]


def _merge_memory_atoms(
    conn: sqlite3.Connection,
    *,
    source_id: str,
    target_id: str,
    changed_at_ms: int,
) -> dict[str, object]:
    if source_id == target_id:
        raise ValueError("memory atom cannot merge into itself")
    rows = conn.execute(
        """
        SELECT id, text, source_event_ids_json, source_memory_ids_json,
               privacy_level, confidence, quality_score
        FROM memory_atoms WHERE id IN (?, ?)
        """,
        (source_id, target_id),
    ).fetchall()
    by_id = {str(row["id"]): row for row in rows}
    source = by_id.get(source_id)
    target = by_id.get(target_id)
    if source is None or target is None:
        raise ValueError("source or target memory atom was not found")
    if "sensitive" in {str(source["privacy_level"] or ""), str(target["privacy_level"] or "")}:
        raise ValueError("sensitive memory cannot be merged in the control center")

    source_events = _deduplicated_values(
        [*_json_list(target["source_event_ids_json"]), *_json_list(source["source_event_ids_json"])]
    )
    source_memories = _deduplicated_values(
        [
            *_json_list(target["source_memory_ids_json"]),
            *_json_list(source["source_memory_ids_json"]),
            source_id,
        ]
    )
    conn.execute(
        """
        UPDATE memory_atoms
        SET source_event_ids_json = ?, source_memory_ids_json = ?,
            confidence = MAX(confidence, ?), quality_score = MAX(quality_score, ?),
            updated_at_ms = ?
        WHERE id = ?
        """,
        (
            json.dumps(source_events, ensure_ascii=False),
            json.dumps(source_memories, ensure_ascii=False),
            float(source["confidence"] or 0),
            float(source["quality_score"] or 0),
            changed_at_ms,
            target_id,
        ),
    )
    for tag_id, weight, tag_source in conn.execute(
        "SELECT tag_id, weight, source FROM memory_atom_tags WHERE memory_atom_id = ?",
        (source_id,),
    ).fetchall():
        existing = conn.execute(
            "SELECT weight FROM memory_atom_tags WHERE memory_atom_id = ? AND tag_id = ?",
            (target_id, tag_id),
        ).fetchone()
        if existing is None:
            conn.execute(
                "INSERT INTO memory_atom_tags(memory_atom_id, tag_id, weight, source) VALUES (?, ?, ?, ?)",
                (target_id, tag_id, weight, tag_source),
            )
        else:
            conn.execute(
                "UPDATE memory_atom_tags SET weight = MAX(weight, ?), source = 'user_merge' "
                "WHERE memory_atom_id = ? AND tag_id = ?",
                (weight, target_id, tag_id),
            )
    conn.execute("DELETE FROM memory_atom_tags WHERE memory_atom_id = ?", (source_id,))
    conn.execute("UPDATE memory_aliases SET memory_atom_id = ? WHERE memory_atom_id = ?", (target_id, source_id))

    for book_id, raw_ids in conn.execute("SELECT book_id, memory_atom_ids_json FROM memory_books").fetchall():
        atom_ids = [str(value) for value in _json_list(raw_ids)]
        if source_id not in atom_ids:
            continue
        replaced = _deduplicated_values(target_id if value == source_id else value for value in atom_ids)
        conn.execute(
            "UPDATE memory_books SET memory_atom_ids_json = ?, updated_at_ms = ? WHERE book_id = ?",
            (json.dumps(replaced, ensure_ascii=False), changed_at_ms, book_id),
        )

    conn.execute(
        "UPDATE memory_atoms SET status = 'tombstoned', updated_at_ms = ? WHERE id = ?",
        (changed_at_ms, source_id),
    )
    conn.execute(
        """
        INSERT INTO memory_tombstones(
            created_at_ms, target_type, target_value, reason, active, metadata_json
        ) VALUES (?, 'memory_id', ?, ?, 1, ?)
        """,
        (
            changed_at_ms,
            source_id,
            f"merged_into:{target_id}",
            json.dumps({"source": "native_control_center_merge", "targetId": target_id}, sort_keys=True),
        ),
    )
    return {
        "merged": True,
        "mergedIntoId": target_id,
        "sourceStatus": "tombstoned",
        "sourceEventCount": len(source_events),
    }


def _merge_memory_tags(
    conn: sqlite3.Connection,
    *,
    source_id: str,
    target_id: str,
    aliases: list[str],
    color: str,
    changed_at_ms: int,
) -> dict[str, object]:
    if source_id == target_id:
        raise ValueError("memory tag cannot merge into itself")
    rows = conn.execute(
        "SELECT id, tag FROM memory_tags WHERE CAST(id AS TEXT) IN (?, ?)",
        (source_id, target_id),
    ).fetchall()
    by_id = {str(row["id"]): row for row in rows}
    source = by_id.get(source_id)
    target = by_id.get(target_id)
    if source is None or target is None:
        raise ValueError("source or target memory tag was not found")
    source_numeric = int(source_id)
    target_numeric = int(target_id)

    for memory_item_id, weight, position, evidence in conn.execute(
        "SELECT memory_item_id, weight, position, evidence FROM memory_item_tags WHERE tag_id = ?",
        (source_numeric,),
    ).fetchall():
        existing = conn.execute(
            "SELECT weight, position, evidence FROM memory_item_tags WHERE memory_item_id = ? AND tag_id = ?",
            (memory_item_id, target_numeric),
        ).fetchone()
        if existing is None:
            conn.execute(
                "INSERT INTO memory_item_tags(memory_item_id, tag_id, weight, position, evidence) VALUES (?, ?, ?, ?, ?)",
                (memory_item_id, target_numeric, weight, position, evidence),
            )
        else:
            conn.execute(
                "UPDATE memory_item_tags SET weight = MAX(weight, ?), position = MIN(position, ?), evidence = ? "
                "WHERE memory_item_id = ? AND tag_id = ?",
                (weight, position, str(existing[2] or evidence or ""), memory_item_id, target_numeric),
            )
    conn.execute("DELETE FROM memory_item_tags WHERE tag_id = ?", (source_numeric,))

    for atom_id, weight, tag_source in conn.execute(
        "SELECT memory_atom_id, weight, source FROM memory_atom_tags WHERE CAST(tag_id AS TEXT) = ?",
        (source_id,),
    ).fetchall():
        existing = conn.execute(
            "SELECT weight FROM memory_atom_tags WHERE memory_atom_id = ? AND CAST(tag_id AS TEXT) = ?",
            (atom_id, target_id),
        ).fetchone()
        if existing is None:
            conn.execute(
                "INSERT INTO memory_atom_tags(memory_atom_id, tag_id, weight, source) VALUES (?, ?, ?, ?)",
                (atom_id, target_id, weight, tag_source),
            )
        else:
            conn.execute(
                "UPDATE memory_atom_tags SET weight = MAX(weight, ?), source = 'user_merge' "
                "WHERE memory_atom_id = ? AND CAST(tag_id AS TEXT) = ?",
                (weight, atom_id, target_id),
            )
    conn.execute("DELETE FROM memory_atom_tags WHERE CAST(tag_id AS TEXT) = ?", (source_id,))

    edge_rows = conn.execute(
        """
        SELECT src_tag_id, dst_tag_id, edge_type, weight, direction_bias,
               evidence_count, metadata_json
        FROM memory_tag_edges WHERE src_tag_id = ? OR dst_tag_id = ?
        """,
        (source_numeric, source_numeric),
    ).fetchall()
    for edge in edge_rows:
        src = target_numeric if int(edge[0]) == source_numeric else int(edge[0])
        dst = target_numeric if int(edge[1]) == source_numeric else int(edge[1])
        if src == dst:
            continue
        existing = conn.execute(
            "SELECT weight, evidence_count FROM memory_tag_edges WHERE src_tag_id = ? AND dst_tag_id = ? AND edge_type = ?",
            (src, dst, edge[2]),
        ).fetchone()
        if existing is None:
            conn.execute(
                """
                INSERT INTO memory_tag_edges(
                    src_tag_id, dst_tag_id, edge_type, weight, direction_bias,
                    evidence_count, updated_at_ms, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (src, dst, edge[2], edge[3], edge[4], edge[5], changed_at_ms, edge[6]),
            )
        else:
            conn.execute(
                """
                UPDATE memory_tag_edges
                SET weight = MAX(weight, ?), evidence_count = evidence_count + ?, updated_at_ms = ?
                WHERE src_tag_id = ? AND dst_tag_id = ? AND edge_type = ?
                """,
                (edge[3], edge[5], changed_at_ms, src, dst, edge[2]),
            )
    conn.execute("DELETE FROM memory_tag_edges WHERE src_tag_id = ? OR dst_tag_id = ?", (source_numeric, source_numeric))

    profile_rows = conn.execute(
        "SELECT tag_id, color_token, aliases_json FROM memory_tag_profiles WHERE tag_id IN (?, ?)",
        (source_numeric, target_numeric),
    ).fetchall()
    profiles = {int(row[0]): row for row in profile_rows}
    target_profile = profiles.get(target_numeric)
    source_profile = profiles.get(source_numeric)
    merged_aliases = _string_list_value(
        [
            *(_json_list(target_profile[2]) if target_profile is not None else []),
            str(source["tag"]),
            *(_json_list(source_profile[2]) if source_profile is not None else []),
            *aliases,
        ]
    )
    resolved_color = color
    if resolved_color == "blue" and target_profile is not None and str(target_profile[1] or ""):
        resolved_color = str(target_profile[1])
    conn.execute(
        """
        INSERT INTO memory_tag_profiles(tag_id, color_token, aliases_json, updated_at_ms)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(tag_id) DO UPDATE SET
            color_token = excluded.color_token,
            aliases_json = excluded.aliases_json,
            updated_at_ms = excluded.updated_at_ms
        """,
        (target_numeric, resolved_color, json.dumps(merged_aliases, ensure_ascii=False), changed_at_ms),
    )
    conn.execute("DELETE FROM memory_tag_profiles WHERE tag_id = ?", (source_numeric,))

    source_label = str(source["tag"])
    target_label = str(target["tag"])
    for book_id, tags_json in conn.execute("SELECT book_id, tags_json FROM memory_books").fetchall():
        tags = [str(value) for value in _json_list(tags_json)]
        if source_label not in tags:
            continue
        replaced = _deduplicated_values(target_label if value == source_label else value for value in tags)
        conn.execute(
            "UPDATE memory_books SET tags_json = ?, updated_at_ms = ? WHERE book_id = ?",
            (json.dumps(replaced, ensure_ascii=False), changed_at_ms, book_id),
        )
    conn.execute("DELETE FROM memory_tags WHERE id = ?", (source_numeric,))
    return {
        "merged": True,
        "mergedIntoId": target_id,
        "mergedIntoTag": target_label,
        "aliases": merged_aliases,
        "color": resolved_color,
    }


def _merge_semantic_groups(
    conn: sqlite3.Connection,
    *,
    source_id: str,
    target_id: str,
    changed_at_ms: int,
) -> dict[str, object]:
    if source_id == target_id:
        raise ValueError("semantic group cannot merge into itself")
    rows = conn.execute(
        "SELECT * FROM memory_semantic_groups WHERE group_id IN (?, ?)",
        (source_id, target_id),
    ).fetchall()
    by_id = {str(row["group_id"]): row for row in rows}
    source = by_id.get(source_id)
    target = by_id.get(target_id)
    if source is None or target is None:
        raise ValueError("source or target semantic group was not found")

    aliases = _string_list_value(
        [
            *_json_list(target["aliases_json"]),
            str(source["title"] or ""),
            *_json_list(source["aliases_json"]),
        ]
    )
    tags = _string_list_value([*_json_list(target["tags_json"]), *_json_list(source["tags_json"])])
    source_event_ids = _deduplicated_values(
        [*_json_list(target["source_event_ids_json"]), *_json_list(source["source_event_ids_json"])]
    )
    description = str(target["description"] or source["description"] or "")
    conn.execute(
        """
        UPDATE memory_semantic_groups
        SET description = ?, aliases_json = ?, tags_json = ?, source_event_ids_json = ?,
            confidence = MAX(confidence, ?), quality_score = MAX(quality_score, ?),
            updated_at_ms = ?
        WHERE group_id = ?
        """,
        (
            description,
            json.dumps(aliases, ensure_ascii=False),
            json.dumps(tags, ensure_ascii=False),
            json.dumps(source_event_ids, ensure_ascii=False),
            float(source["confidence"] or 0.0),
            float(source["quality_score"] or 0.0),
            changed_at_ms,
            target_id,
        ),
    )

    for member in conn.execute(
        """
        SELECT member_type, member_id, weight
        FROM memory_semantic_group_members
        WHERE group_id = ?
        """,
        (source_id,),
    ).fetchall():
        conn.execute(
            """
            INSERT INTO memory_semantic_group_members(
                group_id, member_type, member_id, weight, source, updated_at_ms
            ) VALUES (?, ?, ?, ?, 'user_merge', ?)
            ON CONFLICT(group_id, member_type, member_id) DO UPDATE SET
                weight = MAX(memory_semantic_group_members.weight, excluded.weight),
                source = 'user_merge',
                updated_at_ms = excluded.updated_at_ms
            """,
            (target_id, str(member[0]), str(member[1]), float(member[2] or 0.8), changed_at_ms),
        )
    conn.execute("DELETE FROM memory_semantic_group_members WHERE group_id = ?", (source_id,))
    conn.execute(
        "UPDATE memory_semantic_groups SET status = 'merged', updated_at_ms = ? WHERE group_id = ?",
        (changed_at_ms, source_id),
    )
    conn.execute("DELETE FROM memory_group_overrides WHERE context_group_id = ?", (source_id,))
    return {
        "merged": True,
        "mergedIntoId": target_id,
        "mergedIntoTitle": str(target["title"] or target_id),
        "movedMemberCount": int(
            conn.execute(
                "SELECT COUNT(*) FROM memory_semantic_group_members WHERE group_id = ?",
                (target_id,),
            ).fetchone()[0]
        ),
    }


def _deduplicated_values(values: object) -> list[object]:
    result: list[object] = []
    for value in values:  # type: ignore[union-attr]
        if value in (None, "") or value in result:
            continue
        result.append(value)
    return result


def _bounded_int(value: object, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _now_ms() -> int:
    return int(time.time() * 1000)
