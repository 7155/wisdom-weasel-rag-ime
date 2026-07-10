from __future__ import annotations

import copy
import hashlib
import ipaddress
import json
import mimetypes
import os
import re
import subprocess
import time
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Event, RLock
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from .active_rag_service import ACTIVE_RAG_DEFAULT_MAX_CHARS, ActiveRagService, ActiveRagStartRequest
from .adapter import InputMethodAdapter, SuggestionRequest
from .cli import seed_demo_memories
from .core_client import CoreClient, default_fixture_memories
from .deepseek_completion import DeepSeekCompletionRequest, DeepSeekV4FlashCompletionProvider, build_deepseek_completion_messages
from .deepseek_config import load_deepseek_config
from .history_context import build_prediction_context
from .hybrid_rag_models import HybridRagQuery
from .hybrid_rag_retriever import retrieve_hybrid_rag_candidates
from .local_sqlite_core import LocalSqliteCoreClient
from .management_service import ManagementService, page_request
from .memory_book_compiler import build_memory_book_source_bundle
from .memory_generator import (
    MemoryGenerationError,
    VcpRebuildMemoryGenerator,
    generated_memory_context,
    generated_memory_dedupe_tag,
)
from .models import MemoryAction
from .payloads import action_response_payload, suggestions_response_payload
from .prediction_anchors import build_prediction_anchors_from_snapshot
from .predictor import (
    PredictionBenchmarkCase,
    PredictionProvider,
    benchmark_streaming_ttft_provider,
    prediction_provider_from_env,
    prediction_provider_status,
)
from .predictor_benchmark import benchmark_predictor_latency, load_predictor_latency_cases
from .predictor_latency import latency_log_path_from_env, latency_report
from .rime_sidecar import (
    build_rime_sidecar_response,
    choose_semantic_query,
    decide_side_candidate_refresh,
    frontend_transaction_to_payload,
    parse_rime_context_payload,
    prediction_first_merge_enabled,
    record_rime_side_candidate_selection,
    rime_context_to_payload,
    semantic_signal_length,
)
from .retrieval_docs import rebuild_retrieval_docs
from .runtime_flags import assert_deepseek_scene_allowed
from .settings_models import UserProfile, UserVocabularyItem
from .settings_store import ManagementSettingsStore, settings_response
from .text_utils import compact_whitespace, now_ms, stable_text_hash


def _host_is_loopback(host: str) -> bool:
    normalized = (host or "").strip().lower().removeprefix("[").removesuffix("]")
    if normalized in {"localhost", "localhost.", "::1"}:
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _origin_matches_host(origin: str, host_header: str) -> bool:
    parsed = urlparse(origin)
    origin_host = parsed.netloc.lower()
    request_host = (host_header or "").lower()
    return bool(origin_host and request_host and origin_host == request_host)


@dataclass(frozen=True)
class DebugServerConfig:
    host: str = "127.0.0.1"
    port: int = 8765
    db_path: Path = Path(".rag-ime-data/rag-ime.sqlite")
    project: str = "wisdom-weasel-rag-ime"
    static_dir: Path = Path("debug")
    seed_if_empty: bool = True
    core: CoreClient | None = None
    predictor: PredictionProvider | None = None
    server_name: str = "debug server"
    rime_cache_ttl_ms: int = 400
    input_source_id: str = "im.rime.inputmethod.Squirrel.Hans"
    input_source_check_script: Path | None = None
    input_source_require_hitoolbox: bool = True
    vector_auto_rebuild_limit: int = 0
    include_raw_text: bool = False


@dataclass
class _RimeSuggestCacheEntry:
    expires_at: float
    response: dict[str, object]


@dataclass
class _RimeSuggestInflightEntry:
    event: Event
    response: dict[str, object] | None = None
    error: BaseException | None = None
    waiters: int = 0


@dataclass
class _PredictorStatusCacheEntry:
    fingerprint: str
    expires_at: float
    status: dict[str, object]


class DebugImeService:
    """Small local HTTP facade for browser-based IME debugging."""

    def __init__(self, config: DebugServerConfig):
        self.config = config
        self.core = config.core or LocalSqliteCoreClient(config.db_path)
        self.predictor = config.predictor or prediction_provider_from_env()
        self.adapter = InputMethodAdapter(self.core, project=config.project)
        self.deepseek_completion_provider = DeepSeekV4FlashCompletionProvider(
            load_deepseek_config(),
            enforce_runtime_flags=True,
        )
        self.active_rag = ActiveRagService(
            core=self.core if isinstance(self.core, LocalSqliteCoreClient) else None,
            completion_provider=self.deepseek_completion_provider,
        )
        self.settings_store = ManagementSettingsStore(config.db_path)
        self._rime_cache: dict[str, _RimeSuggestCacheEntry] = {}
        self._rime_inflight: dict[str, _RimeSuggestInflightEntry] = {}
        self._rime_cache_lock = RLock()
        self._rime_cache_hits = 0
        self._rime_cache_misses = 0
        self._rime_inflight_hits = 0
        self._rime_inflight_errors = 0
        self._prediction_live_trace: list[dict[str, object]] = []
        self._predictor_status_cache: dict[bool, _PredictorStatusCacheEntry] = {}
        self._predictor_status_lock = RLock()
        if isinstance(self.core, LocalSqliteCoreClient):
            self.core.initialize()
        self.settings_store.initialize()
        self.management = ManagementService(
            db_path=config.db_path,
            project=config.project,
            repo_root=Path(__file__).resolve().parents[1],
            settings_store=self.settings_store,
            health_provider=self.health,
            input_source_provider=self.input_source_status,
            predictor_provider=self.predictor_status,
            last_prediction_provider=self._last_management_prediction,
        )
        _apply_pinyin_settings_to_process_env(self.settings_store.get_settings(include_sensitive=True))
        if config.seed_if_empty and self._event_count() == 0:
            seed_demo_memories(self.adapter, default_fixture_memories())
        self._vector_auto_rebuild_report = self._maybe_auto_rebuild_vector_index()

    def health(self) -> dict[str, object]:
        settings = self.settings_store.get_settings()
        return {
            "ok": True,
            "project": self.config.project,
            "coreMode": "local" if isinstance(self.core, LocalSqliteCoreClient) else "json",
            "dbPath": str(self.config.db_path),
            "management": {
                "schemaVersion": "rag-ime.debug-management.v1",
                "localhostOnly": _host_is_loopback(self.config.host),
                "rawTextVisible": self._include_raw_text(),
                "settings": settings,
            },
            "pinyinRuntime": _pinyin_runtime_status(settings),
            "eventCount": self._event_count(),
            "actionCount": self._action_count(),
            "rimeSuggestCache": {
                "ttlMs": self._cache_ttl_ms(),
                "size": self._rime_cache_size(),
                "hits": self._rime_cache_hits,
                "misses": self._rime_cache_misses,
                "inFlight": self._rime_inflight_size(),
                "inFlightHits": self._rime_inflight_hits,
                "inFlightErrors": self._rime_inflight_errors,
            },
            "predictor": self._predictor_status(probe_capabilities=False),
            "suggestionCache": self._suggestion_cache_stats(),
            "vectorStats": self._vector_index_stats(),
            "vectorAutoRebuild": self._vector_auto_rebuild_status(),
        }

    def predictor_status(self) -> dict[str, object]:
        return {
            "schemaVersion": "rag-ime.predictor-status.v1",
            "ok": True,
            "predictor": self._predictor_status(probe_capabilities=True),
        }

    def settings(self) -> dict[str, object]:
        return settings_response(self.settings_store.get_settings())

    def management_security_settings(self) -> dict[str, object]:
        settings = self.settings_store.get_settings(include_sensitive=True)
        security = settings.get("managementSecurity") if isinstance(settings.get("managementSecurity"), dict) else {}
        return dict(security)

    def settings_schema(self) -> dict[str, object]:
        return {"ok": True, **self.settings_store.schema_payload()}

    def settings_update(self, payload: dict[str, Any]) -> dict[str, object]:
        result = self.settings_store.update_settings(
            payload,
            updated_by=_string(payload.get("updatedBy")) or "local-console",
            confirm_text=_string(payload.get("confirmText")),
        )
        _apply_pinyin_settings_to_process_env(result.settings)
        self._clear_rime_cache()
        return {
            **settings_response(result.settings),
            "auditId": result.audit_id,
            "changedKeys": list(result.changed_keys),
            **self.management.settings_changed(audit_id=result.audit_id, changed_keys=list(result.changed_keys)),
        }

    def settings_reset_section(self, payload: dict[str, Any]) -> dict[str, object]:
        section = _string(payload.get("section"))
        result = self.settings_store.reset_section(section, updated_by=_string(payload.get("updatedBy")) or "local-console")
        _apply_pinyin_settings_to_process_env(result.settings)
        self._clear_rime_cache()
        return {
            **settings_response(result.settings),
            "auditId": result.audit_id,
            "changedKeys": list(result.changed_keys),
            "section": section,
            **self.management.settings_changed(audit_id=result.audit_id, changed_keys=list(result.changed_keys)),
        }

    def _last_management_prediction(self) -> dict[str, object]:
        if not self._prediction_live_trace:
            return {}
        item = self._prediction_live_trace[-1]
        return {
            "requestId": item.get("requestId", ""),
            "triggerReason": item.get("triggerReason", item.get("reason", "")),
            "contextSource": item.get("foregroundContextSource", ""),
            "sourceTypes": item.get("sourceTypes", []),
            "visibleCandidate": item.get("visibleCandidate", ""),
            "totalLatencyMs": item.get("totalLatencyMs", item.get("elapsedMs", 0)),
            "providerCallCount": item.get("providerCallCount", 0),
            "createdAtMs": item.get("createdAtMs", 0),
        }

    def profiles(self, payload: dict[str, Any]) -> dict[str, object]:
        return self.settings_store.list_profiles(kind=_string(payload.get("kind")))

    def management_audit(self, payload: dict[str, Any]) -> dict[str, object]:
        if not isinstance(self.core, LocalSqliteCoreClient):
            return {"schemaVersion": "rag-ime.management-audit.v3", "ok": False, "items": [], "error": "local SQLite core required"}
        limit = _bounded_int(payload.get("limit"), default=50, minimum=1, maximum=200)
        action = _string(payload.get("action"))
        with self.core._connect() as conn:  # type: ignore[attr-defined]
            _ensure_management_audit_schema(conn)
            rows = conn.execute(
                """
                SELECT id, created_at_ms, action, target_type, target_id, payload_json, result_json
                FROM management_audit_log
                WHERE (? = '' OR action = ?)
                ORDER BY id DESC
                LIMIT ?
                """,
                (action, action, limit),
            ).fetchall()
        return {
            "schemaVersion": "rag-ime.management-audit.v3",
            "ok": True,
            "items": [
                {
                    "auditId": int(row["id"]),
                    "createdAtMs": int(row["created_at_ms"]),
                    "action": str(row["action"]),
                    "targetType": str(row["target_type"]),
                    "targetId": str(row["target_id"]),
                    "payload": _redact_mapping(_json_loads_dict(row["payload_json"]), include_text=self._include_raw_text()),
                    "result": _redact_mapping(_json_loads_dict(row["result_json"]), include_text=self._include_raw_text()),
                }
                for row in rows
            ],
        }

    def profile_save(self, payload: dict[str, Any]) -> dict[str, object]:
        profile = UserProfile(
            profile_id=_string(payload.get("id") or payload.get("profileId")),
            profile_kind=_string(payload.get("kind") or payload.get("profileKind")) or "interaction_profile",
            label=_string(payload.get("label")) or _string(payload.get("id") or payload.get("profileId")),
            description=_string(payload.get("description")),
            settings=dict(payload.get("settings") or {}) if isinstance(payload.get("settings"), dict) else {},
            enabled=_bool(payload.get("enabled"), default=True),
        )
        return self.settings_store.save_profile(profile)

    def profile_activate_dry_run(self, payload: dict[str, Any]) -> dict[str, object]:
        return self.settings_store.activate_profile_dry_run(_string(payload.get("id") or payload.get("profileId")))

    def vocabulary_items(self, payload: dict[str, Any]) -> dict[str, object]:
        return self.settings_store.list_vocabulary(status=_string(payload.get("status")), query=_string(payload.get("query")))

    def vocabulary_item_save(self, payload: dict[str, Any], *, action: str) -> dict[str, object]:
        item = UserVocabularyItem(
            vocab_id=_string(payload.get("id") or payload.get("vocabId")),
            surface=_string(payload.get("surface")),
            aliases=tuple(_string_list(payload.get("aliases"))),
            pinyin=_string(payload.get("pinyin")),
            tags=tuple(_string_list(payload.get("tags"))),
            scope=_string(payload.get("scope")) or "global",
            priority=_bounded_int(payload.get("priority"), default=0, minimum=0, maximum=1000),
            status=_string(payload.get("status")) or "active",
        )
        if not item.surface:
            return {"schemaVersion": "rag-ime.user-vocabulary-save.v3", "ok": False, "error": "surface is required"}
        return self.settings_store.save_vocabulary_item(item, action=action)

    def vocabulary_item_delete(self, payload: dict[str, Any]) -> dict[str, object]:
        return self.settings_store.delete_vocabulary_item(_string(payload.get("id") or payload.get("vocabId")))

    def vocabulary_rime_export_preview(self, payload: dict[str, Any]) -> dict[str, object]:
        return self.settings_store.rime_export_preview(status=_string(payload.get("status")) or "active")

    def vocabulary_rime_export_apply(self, payload: dict[str, Any]) -> dict[str, object]:
        target = _string(payload.get("targetFile")) or str(Path.home() / "Library/Rime/rag_ime.user.dict.yaml")
        return self.settings_store.rime_export_apply(target_file=target, confirm_text=_string(payload.get("confirmText")))

    def models_status(self) -> dict[str, object]:
        settings = self.settings_store.get_settings()
        return {
            "schemaVersion": "rag-ime.models-status.v3",
            "ok": True,
            "settings": settings.get("models", {}),
            "predictor": self._predictor_status(probe_capabilities=True),
        }

    def model_profiles(self) -> dict[str, object]:
        return {
            "schemaVersion": "rag-ime.model-profiles.v3",
            "ok": True,
            "items": [
                {
                    "id": "qwen3_06b_ime_hot",
                    "label": "Qwen3 0.6B IME Hot",
                    "provider": "mlx",
                    "lane": "hot",
                    "resident": True,
                    "latencyBudgetMs": 500,
                    "enabled": True,
                },
                {
                    "id": "deepseek_v4_flash_active_rag",
                    "label": "DeepSeek V4 Flash Active RAG",
                    "provider": "deepseek",
                    "lane": "active_rag",
                    "enabled": False,
                    "requiresExplicitOptIn": True,
                },
            ],
        }

    def model_probe(self, payload: dict[str, Any]) -> dict[str, object]:
        _ = payload
        return {
            "schemaVersion": "rag-ime.model-probe.v3",
            "ok": True,
            "dryRun": True,
            "predictor": self._predictor_status(probe_capabilities=True, force_refresh=True),
        }

    def model_benchmark_job(self, payload: dict[str, Any]) -> dict[str, object]:
        report = self.predictor_benchmark({**payload, "repeat": _bounded_int(payload.get("repeat"), default=1, minimum=1, maximum=10)})
        return {"schemaVersion": "rag-ime.model-benchmark-job.v3", "ok": True, "job": {"status": "complete", "report": report}}

    def model_activate_dry_run(self, payload: dict[str, Any]) -> dict[str, object]:
        profile_id = _string(payload.get("profileId") or payload.get("id")) or "qwen3_06b_ime_hot"
        return {
            "schemaVersion": "rag-ime.model-activate-dry-run.v3",
            "ok": True,
            "dryRun": True,
            "profileId": profile_id,
            "commands": [
                f"export RAG_IME_PREDICTOR_PROFILE={profile_id}",
                "scripts/restart_rag_ime_runtime.sh",
            ],
        }

    def active_rag_settings(self) -> dict[str, object]:
        settings = self.settings_store.get_settings()
        return {
            "schemaVersion": "rag-ime.active-rag-settings.v3",
            "ok": True,
            "settings": settings.get("activeRag", {}),
        }

    def active_rag_settings_update(self, payload: dict[str, Any]) -> dict[str, object]:
        settings = payload.get("settings") if isinstance(payload.get("settings"), dict) else payload
        update_result = self.settings_store.update_settings(
            {"activeRag": dict(settings)},
            updated_by=_string(payload.get("updatedBy")) or "local-console",
            confirm_text=_string(payload.get("confirmText")),
        )
        self._clear_rime_cache()
        result = {
            **settings_response(update_result.settings),
            "auditId": update_result.audit_id,
            "changedKeys": list(update_result.changed_keys),
        }
        result["runtimeSync"] = _active_rag_runtime_sync_payload(
            active_settings=result.get("settings", {}).get("activeRag", {}) if isinstance(result.get("settings"), dict) else {},
            changed_keys=tuple(str(item) for item in result.get("changedKeys", []) if item),
        )
        return result

    def active_rag_management_preview(self, payload: dict[str, Any]) -> dict[str, object]:
        settings = self.settings_store.get_settings()
        active_settings = settings.get("activeRag") if isinstance(settings.get("activeRag"), dict) else {}
        if not active_settings.get("enabled", True):
            return {"schemaVersion": "rag-ime.active-rag-preview.v3", "ok": False, "error": "Active RAG disabled"}
        max_candidates = _bounded_int(
            payload.get("maxCandidates"),
            default=_bounded_int(active_settings.get("maxCandidates"), default=1, minimum=1, maximum=10),
            minimum=1,
            maximum=10,
        )
        request_payload = {**payload, "maxCandidates": max_candidates}
        local_only = _bool(payload.get("localOnly"), default=bool(active_settings.get("localOnlyDefault", True)))
        try:
            request = self._active_rag_request_from_payload(request_payload)
            preview = self.active_rag.preview(request, local_only=local_only)
        except ValueError as exc:
            return {"schemaVersion": "rag-ime.active-rag-preview.v3", "ok": False, "error": str(exc)}
        return _redact_mapping(
            {
                "schemaVersion": "rag-ime.active-rag-preview.v3",
                "localOnly": local_only,
                "latencyBudgetMs": _bounded_int(
                    payload.get("latencyBudgetMs"),
                    default=_bounded_int(active_settings.get("latencyBudgetMs"), default=15000, minimum=100, maximum=30000),
                    minimum=100,
                    maximum=30000,
                ),
                **preview,
            },
            include_text=self._include_raw_text(),
        )

    def predictor_latency(self, payload: dict[str, Any]) -> dict[str, object]:
        log_path = Path(_string(payload.get("log")) or latency_log_path_from_env())
        return {
            "ok": True,
            **latency_report(log_path, last=_bounded_int(payload.get("last"), default=200, minimum=1, maximum=5000)),
        }

    def predictor_cache_stats(self) -> dict[str, object]:
        status = self._predictor_status(probe_capabilities=True)
        probe = status.get("capabilityProbe") if isinstance(status.get("capabilityProbe"), dict) else {}
        prompt_cache = probe.get("promptCache") if isinstance(probe.get("promptCache"), dict) else {}
        capabilities = status.get("capabilities") if isinstance(status.get("capabilities"), dict) else {}
        return {
            "schemaVersion": "rag-ime.predictor-cache-stats.v1",
            "ok": True,
            "capabilities": capabilities,
            "promptCache": prompt_cache,
            "clearSupported": False,
        }

    def predictor_cache_clear(self, payload: dict[str, Any]) -> dict[str, object]:
        confirm = _string(payload.get("confirmText") or payload.get("confirm"))
        if confirm != "CLEAR PREDICTOR CACHE":
            return {
                "schemaVersion": "rag-ime.predictor-cache-clear.v1",
                "ok": False,
                "cleared": False,
                "error": "confirmText must be CLEAR PREDICTOR CACHE",
            }
        return {
            "schemaVersion": "rag-ime.predictor-cache-clear.v1",
            "ok": True,
            "cleared": False,
            "reason": "current predictor provider does not expose a remote cache clear API",
        }

    def active_rag_preview(self, payload: dict[str, Any]) -> dict[str, object]:
        return self.active_rag_management_preview(payload)

    def active_rag_service_preview(self, payload: dict[str, Any]) -> dict[str, object]:
        started = self.active_rag_start(payload)
        session_id = _string(started.get("sessionId"))
        return self.active_rag_status({"sessionId": session_id}) if session_id else started

    def _active_rag_request_from_payload(self, payload: dict[str, Any]) -> ActiveRagStartRequest:
        selected_text = compact_whitespace(_string(payload.get("selectedText") or payload.get("selected_text")))
        if not selected_text:
            raise ValueError("selectedText is required for explicit Active RAG")
        evidence_pack = (
            tuple(item for item in payload.get("evidencePack", []) if isinstance(item, dict))
            if isinstance(payload.get("evidencePack"), list)
            else ()
        )
        return ActiveRagStartRequest(
            selected_text=selected_text,
            selected_text_hash=_string(payload.get("selectedTextHash") or payload.get("selected_text_hash")) or stable_text_hash(selected_text),
            frontend_revision=_bounded_int(payload.get("frontendRevision"), default=1, minimum=0, maximum=1_000_000_000),
            selection_epoch=_bounded_int(payload.get("selectionEpoch"), default=1, minimum=0, maximum=1_000_000_000),
            panel_session_id=_string(payload.get("panelSessionId")),
            front_app_bundle_id=_string(payload.get("frontAppBundleId")),
            surrounding_before=_string(payload.get("surroundingBefore")),
            surrounding_after=_string(payload.get("surroundingAfter")),
            intent=_string(payload.get("intent")) or "rewrite",
            placement=_string(payload.get("placement")) or "replace_selection",
            context=_string(payload.get("context") or payload.get("currentContext")),
            evidence_pack=evidence_pack,
            project=_string(payload.get("project")) or self.config.project,
            app=_string(payload.get("app")),
            max_candidates=_bounded_int(payload.get("maxCandidates"), default=1, minimum=1, maximum=10),
            max_chars=_bounded_int(
                payload.get("maxChars"),
                default=ACTIVE_RAG_DEFAULT_MAX_CHARS,
                minimum=4,
                maximum=180,
            ),
            latency_budget_ms=_bounded_int(payload.get("latencyBudgetMs"), default=15000, minimum=100, maximum=30000),
        )

    def _active_rag_error_payload(self, error: str) -> dict[str, object]:
        return {
            "schemaVersion": "rag-ime.active-rag-service.v1",
            "ok": False,
            "error": error,
        }

    def active_rag_start(self, payload: dict[str, Any]) -> dict[str, object]:
        if not isinstance(self.core, LocalSqliteCoreClient):
            return self._active_rag_error_payload("Active RAG requires local SQLite core")
        try:
            request = self._active_rag_request_from_payload(payload)
            return self.active_rag.start(request)
        except ValueError as exc:
            return self._active_rag_error_payload(str(exc))

    def active_rag_status(self, payload: dict[str, Any]) -> dict[str, object]:
        session_id = _string(payload.get("sessionId") or payload.get("id"))
        if not session_id:
            return {"schemaVersion": "rag-ime.active-rag-service.v1", "status": "missing", "error": "sessionId is required"}
        return self.active_rag.status(session_id)

    def active_rag_cancel(self, payload: dict[str, Any]) -> dict[str, object]:
        session_id = _string(payload.get("sessionId") or payload.get("id"))
        if not session_id:
            return {"schemaVersion": "rag-ime.active-rag-service.v1", "status": "missing", "error": "sessionId is required"}
        return self.active_rag.cancel(session_id)

    def active_rag_accept(self, payload: dict[str, Any]) -> dict[str, object]:
        return self.active_rag.accept(
            session_id=_string(payload.get("sessionId") or payload.get("id")),
            candidate_id=_string(payload.get("candidateId")),
            selected_text_hash=_string(payload.get("selectedTextHash")),
            frontend_revision=_bounded_int(payload.get("frontendRevision"), default=0, minimum=0, maximum=1_000_000_000),
            selection_epoch=_bounded_int(payload.get("selectionEpoch"), default=0, minimum=0, maximum=1_000_000_000),
            panel_session_id=_string(payload.get("panelSessionId")),
            front_app_bundle_id=_string(payload.get("frontAppBundleId")),
        )

    def predictor_benchmark(self, payload: dict[str, Any]) -> dict[str, object]:
        cases_path = Path(_string(payload.get("cases")) or "docs/eval/predictor_latency_cases.jsonl")
        cases = load_predictor_latency_cases(cases_path)
        return benchmark_predictor_latency(
            self.predictor,
            cases,
            profile=_string(payload.get("profile")) or "qwen3_06b_ime_hot",
            repeat=_bounded_int(payload.get("repeat"), default=3, minimum=1, maximum=100),
            max_candidates=_bounded_int(payload.get("maxCandidates"), default=3, minimum=1, maximum=10),
        )

    def rebuild_vector_index(self, payload: dict[str, Any]) -> dict[str, object]:
        if not isinstance(self.core, LocalSqliteCoreClient):
            return {
                "schemaVersion": "rag-ime.vector-rebuild.v1",
                "ok": False,
                "reason": "vector rebuild is only available for local SQLite core",
            }
        project = _string(payload.get("project")) or self.config.project
        limit = _bounded_int(payload.get("limit"), default=0, minimum=0, maximum=200_000)
        report = self.core.rebuild_vector_index(project=project, limit=limit)
        self._vector_auto_rebuild_report = {
            "trigger": "manual",
            "project": project,
            "limit": limit,
            **report,
        }
        return {
            "schemaVersion": "rag-ime.vector-rebuild.v1",
            "ok": bool(report.get("enabled")),
            "project": project,
            "limit": limit,
            **report,
            "vectorStats": self._vector_index_stats(),
        }

    def memory_history(self, payload: dict[str, Any]) -> dict[str, object]:
        if not isinstance(self.core, LocalSqliteCoreClient):
            return {
                "schemaVersion": "rag-ime.memory-history.v1",
                "ok": False,
                "error": "memory history is only available for local SQLite core",
                "items": [],
            }
        report = self.core.list_memory_events(
            project=_string(payload.get("project")) or self.config.project,
            query=_string(payload.get("query")),
            source=_string(payload.get("source")),
            include_deleted=_bool(payload.get("includeDeleted"), default=False),
            generated_only=_bool(payload.get("generatedOnly"), default=False),
            limit=_bounded_int(payload.get("limit"), default=80, minimum=1, maximum=500),
        )
        return {"ok": True, **report}

    def memory_optimizer_trace(self, payload: dict[str, Any]) -> dict[str, object]:
        if not isinstance(self.core, LocalSqliteCoreClient):
            return {
                "schemaVersion": "rag-ime.memory-optimizer-trace.v1",
                "ok": False,
                "error": "optimizer trace is only available for local SQLite core",
            }
        trace_id = _string(payload.get("traceId"))
        if not trace_id:
            return {
                "schemaVersion": "rag-ime.memory-optimizer-trace.v1",
                "ok": False,
                "error": "traceId is required",
            }
        trace = self.core.get_memory_optimizer_trace(trace_id)
        if trace is None:
            return {
                "schemaVersion": "rag-ime.memory-optimizer-trace.v1",
                "ok": False,
                "error": "trace not found",
                "traceId": trace_id,
            }
        return {
            "schemaVersion": "rag-ime.memory-optimizer-trace.v1",
            "ok": True,
            **trace,
        }

    def memory_candidate_explain(self, payload: dict[str, Any]) -> dict[str, object]:
        candidate_id = _string(payload.get("candidateId"))
        if not candidate_id:
            return {
                "schemaVersion": "rag-ime.memory-candidate-explain.v1",
                "ok": False,
                "error": "candidateId is required",
            }
        explainer = getattr(self.core, "explain_memory_candidate", None)
        if not callable(explainer):
            return {
                "schemaVersion": "rag-ime.memory-candidate-explain.v1",
                "ok": False,
                "error": "core does not support candidate explanation",
            }
        explanation = explainer(candidate_id, context_hash=_string(payload.get("contextHash")) or None)
        if explanation is None:
            return {
                "schemaVersion": "rag-ime.memory-candidate-explain.v1",
                "ok": False,
                "error": "candidate not found",
                "candidateId": candidate_id,
            }
        return {
            "schemaVersion": "rag-ime.memory-candidate-explain.v1",
            "ok": True,
            **explanation,
        }

    def memory_governance(self, payload: dict[str, Any]) -> dict[str, object]:
        if not isinstance(self.core, LocalSqliteCoreClient):
            return {
                "schemaVersion": "rag-ime.memory-governance.v1",
                "ok": False,
                "error": "memory governance is only available for local SQLite core",
            }
        report = self.core.inspect_memory_governance(
            limit=_bounded_int(payload.get("limit"), default=20, minimum=1, maximum=200),
            include_inactive=_bool(payload.get("includeInactive"), default=False),
        )
        return {"ok": True, **report}

    def memory_cleanup_runs(self, payload: dict[str, Any]) -> dict[str, object]:
        if not isinstance(self.core, LocalSqliteCoreClient):
            return {
                "schemaVersion": "rag-ime.memory-cleanup-runs.v1",
                "ok": False,
                "error": "cleanup runs are only available for local SQLite core",
            }
        review_status = _cleanup_review_status(payload)
        if review_status:
            run_id = _string(payload.get("runId"))
            if not run_id:
                return {
                    "schemaVersion": "rag-ime.memory-cleanup-runs.v1",
                    "ok": False,
                    "error": "runId is required for cleanup review",
                }
            report = self.core.review_memory_cleanup_plan(
                run_id=run_id,
                status=review_status,
                diff_ids=_int_list(payload.get("diffIds")),
                diff_indexes=_int_list(payload.get("diffIndexes")),
            )
            return {
                "schemaVersion": "rag-ime.memory-cleanup-runs.v1",
                "ok": True,
                **report,
            }
        report = self.core.list_memory_cleanup_runs(
            limit=_bounded_int(payload.get("limit"), default=20, minimum=1, maximum=100),
            run_id=_string(payload.get("runId")),
            status=_string(payload.get("status")),
        )
        return {"ok": True, **report}

    def rag_core_v3_query_preview(self, payload: dict[str, Any]) -> dict[str, object]:
        if not isinstance(self.core, LocalSqliteCoreClient):
            return {"schemaVersion": "rag-ime.rag-core-v3-preview.v1", "ok": False, "error": "local SQLite core required"}
        query = HybridRagQuery(
            query_text=_string(payload.get("query")) or _string(payload.get("currentInput")),
            raw_input=_string(payload.get("rawInput") or payload.get("currentInput")),
            preedit=_string(payload.get("preedit")),
            committed_tail=_string(payload.get("committedContext") or payload.get("recentContext")),
            rime_candidates=tuple(_string_list(payload.get("rimeCandidates"))),
            project=_string(payload.get("project")) or self.config.project,
            app=_string(payload.get("app")),
            top_k=_bounded_int(payload.get("topK"), default=5, minimum=1, maximum=20),
            latency_budget_ms=_bounded_int(payload.get("latencyBudgetMs"), default=25, minimum=1, maximum=5000),
        )
        with self.core._connect() as conn:  # type: ignore[attr-defined]
            payload_result = retrieve_hybrid_rag_candidates(conn, query)
        include_text = self._include_raw_text()
        candidates = list(payload_result.get("candidates") or [])
        fused = [_debug_redact_rag_candidate(item, include_text=include_text) for item in candidates if isinstance(item, dict)]
        evidence_pack = _debug_deepseek_evidence_pack(candidates, include_text=include_text)
        settings = self.settings_store.get_settings(include_sensitive=True)
        rag_settings = settings.get("rag") if isinstance(settings.get("rag"), dict) else {}
        lane_settings = rag_settings.get("lanes") if isinstance(rag_settings.get("lanes"), dict) else {}
        lane_breakdown = _debug_lane_breakdown(payload_result.get("lanes"))
        disabled_lanes = sorted(str(name) for name, enabled in lane_settings.items() if enabled is False)
        for lane in disabled_lanes:
            lane_breakdown.setdefault(lane, {"count": 0})
            lane_breakdown[lane]["disabledBySettings"] = True
        return {
            "schemaVersion": "rag-ime.rag-core-v3-preview.v1",
            "ok": True,
            "query": _debug_query_preview(payload_result.get("query"), include_text=include_text),
            "lanes": lane_breakdown,
            "fusedCandidates": fused,
            "blocked": [{"lane": lane, "reason": "disabled_by_management_settings"} for lane in disabled_lanes],
            "deepseekEvidencePack": evidence_pack,
            "deepseekCandidates": [],
            "elapsedMs": int(payload_result.get("elapsedMs") or 0),
            "rawTextVisible": include_text,
        }

    def rag_core_v3_rebuild_retrieval_docs(self, payload: dict[str, Any]) -> dict[str, object]:
        if not isinstance(self.core, LocalSqliteCoreClient):
            return {"schemaVersion": "rag-ime.retrieval-docs-rebuild.v1", "ok": False, "error": "local SQLite core required"}
        with self.core._connect() as conn:  # type: ignore[attr-defined]
            report = rebuild_retrieval_docs(
                conn,
                project=_string(payload.get("project")) or self.config.project,
                include_books=not _bool(payload.get("noBooks"), default=False),
                include_atoms=not _bool(payload.get("noAtoms"), default=False),
                include_items=not _bool(payload.get("noItems"), default=False),
            )
        self._clear_rime_cache()
        return {"ok": True, **report}

    def rag_core_v3_memory_book_preview(self, payload: dict[str, Any]) -> dict[str, object]:
        if not isinstance(self.core, LocalSqliteCoreClient):
            return {"schemaVersion": "rag-ime.memory-book-preview.v1", "ok": False, "error": "local SQLite core required"}
        with self.core._connect() as conn:  # type: ignore[attr-defined]
            bundle = build_memory_book_source_bundle(
                conn,
                project=_string(payload.get("project")) or self.config.project,
                since_days=_bounded_int(payload.get("sinceDays"), default=7, minimum=1, maximum=365),
                limit=_bounded_int(payload.get("limit"), default=80, minimum=1, maximum=500),
            )
        safe_bundle = _debug_memory_book_source_bundle(bundle, include_text=self._include_raw_text())
        return {
            "schemaVersion": "rag-ime.memory-book-preview.v1",
            "ok": True,
            "dryRun": True,
            "sourceBundle": safe_bundle,
            "rawTextVisible": self._include_raw_text(),
        }

    def rag_core_v3_doc(self, payload: dict[str, Any]) -> dict[str, object]:
        if not isinstance(self.core, LocalSqliteCoreClient):
            return {"schemaVersion": "rag-ime.rag-core-v3-doc.v1", "ok": False, "error": "local SQLite core required"}
        doc_id = _string(payload.get("id") or payload.get("docId"))
        if not doc_id:
            return {"schemaVersion": "rag-ime.rag-core-v3-doc.v1", "ok": False, "error": "id is required"}
        with self.core._connect() as conn:  # type: ignore[attr-defined]
            row = conn.execute("SELECT * FROM memory_retrieval_docs WHERE doc_id = ? LIMIT 1", (doc_id,)).fetchone()
        if row is None:
            return {"schemaVersion": "rag-ime.rag-core-v3-doc.v1", "ok": False, "error": "doc not found", "docId": doc_id}
        item = {key: row[key] for key in row.keys()}
        item["metadata"] = _json_loads_dict(item.pop("metadata_json", "{}"))
        return {
            "schemaVersion": "rag-ime.rag-core-v3-doc.v1",
            "ok": True,
            "doc": _redact_mapping(item, include_text=self._include_raw_text()),
        }

    def rag_core_v3_tag_graph(self, payload: dict[str, Any]) -> dict[str, object]:
        if not isinstance(self.core, LocalSqliteCoreClient):
            return {"schemaVersion": "rag-ime.rag-core-v3-tag-graph.v1", "ok": False, "error": "local SQLite core required"}
        tag = compact_whitespace(_string(payload.get("tag")))
        with self.core._connect() as conn:  # type: ignore[attr-defined]
            rows = conn.execute(
                """
                SELECT src.tag AS src, dst.tag AS dst, e.edge_type, e.weight, e.direction_bias, e.evidence_count
                FROM memory_tag_edges e
                JOIN memory_tags src ON src.id = e.src_tag_id
                JOIN memory_tags dst ON dst.id = e.dst_tag_id
                WHERE (? = '' OR src.tag = ? OR dst.tag = ?)
                ORDER BY e.weight DESC
                LIMIT ?
                """,
                (tag, tag, tag, _bounded_int(payload.get("limit"), default=50, minimum=1, maximum=200)),
            ).fetchall()
        return {
            "schemaVersion": "rag-ime.rag-core-v3-tag-graph.v1",
            "ok": True,
            "tag": tag,
            "edges": [
                {
                    "src": str(row["src"]),
                    "dst": str(row["dst"]),
                    "edgeType": str(row["edge_type"]),
                    "weight": float(row["weight"] or 0.0),
                    "directionBias": float(row["direction_bias"] or 0.0),
                    "evidenceCount": int(row["evidence_count"] or 0),
                }
                for row in rows
            ],
        }

    def deepseek_completion_preview(self, payload: dict[str, Any]) -> dict[str, object]:
        try:
            assert_deepseek_scene_allowed("active_rag")
        except RuntimeError as exc:
            expected_token = os.environ.get("RAG_IME_DEEPSEEK_PREVIEW_TOKEN", "")
            provided_token = _string(payload.get("previewToken"))
            if not (expected_token and provided_token and provided_token == expected_token):
                return {
                    "schemaVersion": "rag-ime.deepseek-completion-preview.v1",
                    "ok": False,
                    "error": str(exc),
                    "requires": "RAG_IME_DEEPSEEK_ACTIVE_RAG=1 or previewToken",
                }
        current_context = _string(payload.get("currentContext") or payload.get("context"))
        selected_text = _string(payload.get("selectedText"))
        evidence_pack = (
            tuple(item for item in payload.get("evidencePack", []) if isinstance(item, dict))
            if isinstance(payload.get("evidencePack"), list)
            else ()
        )
        if not evidence_pack:
            evidence_pack = self._deepseek_preview_evidence_pack(
                current_context=current_context,
                selected_text=selected_text,
                payload=payload,
            )
        request = DeepSeekCompletionRequest(
            scene="active_rag",
            current_context=current_context,
            selected_text=selected_text,
            evidence_pack=evidence_pack,
            max_candidates=_bounded_int(payload.get("maxCandidates"), default=1, minimum=1, maximum=8),
            max_chars=_bounded_int(
                payload.get("maxChars"),
                default=ACTIVE_RAG_DEFAULT_MAX_CHARS,
                minimum=4,
                maximum=180,
            ),
            latency_budget_ms=_bounded_int(payload.get("latencyBudgetMs"), default=2500, minimum=100, maximum=15000),
        )
        messages = build_deepseek_completion_messages(request)
        if _bool(payload.get("dryRun"), default=True):
            return {
                "schemaVersion": "rag-ime.deepseek-completion-preview.v1",
                "ok": True,
                "dryRun": True,
                "messages": _redact_mapping({"messages": messages}, include_text=self._include_raw_text())["messages"],
                "evidencePack": _redact_mapping({"items": list(evidence_pack)}, include_text=self._include_raw_text())["items"],
                "candidates": [],
            }
        config = load_deepseek_config(_string(payload.get("modelEnvPath")) or None)
        provider = DeepSeekV4FlashCompletionProvider(config, enforce_runtime_flags=False)
        candidates: list[dict[str, object]] = []
        stream_events: list[dict[str, object]] = []
        for item in provider.stream_candidates(request):
            payload_item = item.__dict__
            candidates.append(payload_item)
            stream_events.append(
                {
                    "text": item.text,
                    "insertText": item.insert_text,
                    "sourceLane": item.source_lane,
                    "done": item.done,
                    "elapsedMs": item.metadata.get("elapsedMs"),
                    "metadata": dict(item.metadata),
                }
            )
        return {
            "schemaVersion": "rag-ime.deepseek-completion-preview.v1",
            "ok": True,
            "dryRun": False,
            "messages": _redact_mapping({"messages": messages}, include_text=self._include_raw_text())["messages"],
            "evidencePack": _redact_mapping({"items": list(evidence_pack)}, include_text=self._include_raw_text())["items"],
            "streamEvents": _redact_mapping({"items": stream_events}, include_text=self._include_raw_text())["items"],
            "candidates": _redact_mapping({"items": candidates}, include_text=self._include_raw_text())["items"],
        }

    def _deepseek_preview_evidence_pack(
        self,
        *,
        current_context: str,
        selected_text: str,
        payload: dict[str, Any],
    ) -> tuple[dict[str, object], ...]:
        query = compact_whitespace(_string(payload.get("query")) or current_context or selected_text)
        if not query:
            return ()
        top_k = _bounded_int(payload.get("evidenceTopK"), default=8, minimum=1, maximum=20)
        try:
            suggestions = self.adapter.suggest(
                SuggestionRequest(
                    current_input=query,
                    recent_context=compact_whitespace(selected_text or current_context),
                    project=_string(payload.get("project")) or self.config.project,
                    app=_string(payload.get("app")),
                    top_k=top_k,
                )
            )
        except Exception:
            return ()
        return tuple(_deepseek_evidence_from_suggestion(item) for item in suggestions[:top_k])

    def memory_tombstone(self, payload: dict[str, Any]) -> dict[str, object]:
        if not isinstance(self.core, LocalSqliteCoreClient):
            return {
                "schemaVersion": "rag-ime.memory-tombstone.v1",
                "ok": False,
                "error": "memory tombstone is only available for local SQLite core",
            }
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        try:
            tombstone = self.core.add_memory_tombstone(
                target_type=_string(payload.get("targetType")) or "memory_id",
                target_value=_string(payload.get("targetValue")),
                reason=_string(payload.get("reason")) or "manual",
                metadata=metadata,
                active=_bool(payload.get("active"), default=True),
            )
        except ValueError as exc:
            return {
                "schemaVersion": "rag-ime.memory-tombstone.v1",
                "ok": False,
                "error": str(exc),
            }
        self._clear_rime_cache()
        return {
            "schemaVersion": "rag-ime.memory-tombstone.v1",
            "ok": True,
            **tombstone,
        }

    def memory_cleanup_diff_apply(self, diff_id: int) -> dict[str, object]:
        if not isinstance(self.core, LocalSqliteCoreClient):
            return {
                "schemaVersion": "rag-ime.memory-cleanup-diff.v1",
                "ok": False,
                "error": "cleanup diffs are only available for local SQLite core",
            }
        try:
            report = self.core.apply_memory_cleanup_diff(diff_id=diff_id)
        except ValueError as exc:
            return {
                "schemaVersion": "rag-ime.memory-cleanup-diff.v1",
                "ok": False,
                "error": str(exc),
            }
        self._clear_rime_cache()
        return {"ok": True, **report}

    def memory_cleanup_diff_rollback(self, diff_id: int) -> dict[str, object]:
        if not isinstance(self.core, LocalSqliteCoreClient):
            return {
                "schemaVersion": "rag-ime.memory-cleanup-diff.v1",
                "ok": False,
                "error": "cleanup diffs are only available for local SQLite core",
            }
        try:
            report = self.core.rollback_memory_cleanup_diff(diff_id=diff_id)
        except ValueError as exc:
            return {
                "schemaVersion": "rag-ime.memory-cleanup-diff.v1",
                "ok": False,
                "error": str(exc),
            }
        self._clear_rime_cache()
        return {"ok": True, **report}

    def candidate_explain(self, payload: dict[str, Any]) -> dict[str, object]:
        query = _string(payload.get("query") or payload.get("currentInput")).strip()
        recent_context = _string(payload.get("recentContext") or payload.get("recent_context"))
        top_k = _bounded_int(payload.get("topK"), default=5, minimum=1, maximum=10)
        if not query:
            return {
                "schemaVersion": "rag-ime.management-candidate-explain.v1",
                "ok": False,
                "error": "query is required",
                "candidates": [],
            }
        response = self.suggest(
            {
                "currentInput": query,
                "recentContext": recent_context,
                "project": _string(payload.get("project")) or self.config.project,
                "topK": top_k,
                "app": _string(payload.get("app")),
            }
        )
        suggestions = response.get("suggestions") if isinstance(response.get("suggestions"), list) else []
        model_predictions = response.get("modelPredictions") if isinstance(response.get("modelPredictions"), list) else []
        candidates: list[dict[str, object]] = []
        for rank, item in enumerate(model_predictions[:top_k], start=1):
            if not isinstance(item, dict):
                continue
            candidates.append(
                {
                    "rank": rank,
                    "text": _string(item.get("text")),
                    "sourceType": "model",
                    "lane": "model",
                    "score": float(item.get("confidence") or 0.0),
                    "penalty": 0.0,
                    "reason": _string(item.get("providerName") or item.get("provider_name")) or "model prediction",
                    "diagnostics": _redact_mapping(dict(item.get("metadata") or {}), include_text=self._include_raw_text()),
                }
            )
        for index, item in enumerate(suggestions[:top_k], start=1):
            if not isinstance(item, dict):
                continue
            metadata = dict(item.get("metadata") or {}) if isinstance(item.get("metadata"), dict) else {}
            score_breakdown = metadata.get("scoreBreakdown") or metadata.get("score_breakdown") or {}
            source_type = _string(metadata.get("source_type")) or _string(item.get("suggestionType")) or "rag"
            candidates.append(
                {
                    "rank": len(candidates) + 1,
                    "text": _string(item.get("surfaceText") or item.get("text")),
                    "sourceType": source_type,
                    "lane": "rag" if source_type in {"rag", "memory", "stable_memory"} else source_type,
                    "score": float(item.get("confidence") or 0.0),
                    "penalty": _score_penalty(score_breakdown),
                    "reason": _string(metadata.get("reason")) or _string(item.get("evidencePreview"))[:80] or "local memory",
                    "memoryId": _string(item.get("memoryId")),
                    "sourceEventId": int(item.get("sourceEventId") or 0),
                    "diagnostics": _redact_mapping(metadata, include_text=self._include_raw_text()),
                }
            )
        return {
            "schemaVersion": "rag-ime.management-candidate-explain.v1",
            "ok": True,
            "project": _string(payload.get("project")) or self.config.project,
            "queryHash": _stable_debug_hash(query),
            "queryPreview": _privacy_preview(query),
            "rawTextVisible": self._include_raw_text(),
            "candidates": candidates,
        }

    def management_history(self, payload: dict[str, Any]) -> dict[str, object]:
        if not isinstance(self.core, LocalSqliteCoreClient):
            return {
                "schemaVersion": "rag-ime.management-history.v1",
                "ok": False,
                "error": "history audit is only available for local SQLite core",
                "items": [],
            }
        report = self.core.list_memory_events(
            project=_string(payload.get("project")) or self.config.project,
            query=_string(payload.get("query")),
            source=_string(payload.get("source")),
            include_deleted=_bool(payload.get("includeDeleted"), default=False),
            generated_only=_bool(payload.get("generatedOnly"), default=False),
            limit=_bounded_int(payload.get("limit"), default=100, minimum=1, maximum=500),
        )
        include_text = self._include_raw_text()
        items = [
            _redact_history_item(item, include_text=include_text)
            for item in report.get("items", [])
            if isinstance(item, dict)
        ]
        return {
            "schemaVersion": "rag-ime.management-history.v1",
            "ok": True,
            "project": report.get("project"),
            "queryHash": _stable_debug_hash(_string(payload.get("query"))),
            "limit": report.get("limit"),
            "rawTextVisible": include_text,
            "totals": report.get("totals", {}),
            "items": items,
        }

    def management_history_tombstone(self, payload: dict[str, Any]) -> dict[str, object]:
        if not isinstance(self.core, LocalSqliteCoreClient):
            return {
                "schemaVersion": "rag-ime.management-history-tombstone.v1",
                "ok": False,
                "error": "history tombstone is only available for local SQLite core",
            }
        event_id = _optional_int(payload.get("eventId"))
        memory_id = _string(payload.get("memoryId")) or (f"event:{event_id}" if event_id else "")
        if not memory_id:
            return {
                "schemaVersion": "rag-ime.management-history-tombstone.v1",
                "ok": False,
                "error": "eventId or memoryId is required",
            }
        result = self.memory_tombstone(
            {
                "targetType": "memory_id",
                "targetValue": memory_id,
                "reason": _string(payload.get("reason")) or "debug-management-history",
                "metadata": {"source": "debug-management", "eventId": event_id or 0},
            }
        )
        audit_id = self._record_management_audit(
            action="history_tombstone",
            target_type="history",
            target_id=memory_id,
            payload=payload,
            result=result,
        )
        return {
            "schemaVersion": "rag-ime.management-history-tombstone.v1",
            "ok": bool(result.get("ok")),
            "auditId": audit_id,
            "result": result,
        }

    def management_memories(self, payload: dict[str, Any]) -> dict[str, object]:
        report = self._management_memory_items(payload, lexicon=False)
        report["schemaVersion"] = "rag-ime.management-memories.v1"
        return report

    def management_lexicon(self, payload: dict[str, Any]) -> dict[str, object]:
        report = self._management_memory_items(payload, lexicon=True)
        report["schemaVersion"] = "rag-ime.management-lexicon.v1"
        return report

    def management_lexicon_export_rime(self, payload: dict[str, Any]) -> dict[str, object]:
        if not isinstance(self.core, LocalSqliteCoreClient):
            return {
                "schemaVersion": "rag-ime.management-lexicon-rime-export.v1",
                "ok": False,
                "error": "lexicon export is only available for local SQLite core",
            }
        dry_run = _bool(payload.get("dryRun"), default=True)
        if not dry_run:
            return {
                "schemaVersion": "rag-ime.management-lexicon-rime-export.v1",
                "ok": False,
                "error": "Rime dictionary writes are not implemented; run dryRun first",
                "dryRun": False,
            }
        status = _string(payload.get("status")) or "approved"
        allow_non_approved = _bool(payload.get("allowNonApproved"), default=False)
        if status != "approved" and not allow_non_approved:
            return {
                "schemaVersion": "rag-ime.management-lexicon-rime-export.v1",
                "ok": False,
                "error": 'lexicon export requires status="approved" unless allowNonApproved=true',
                "requiredStatus": "approved",
            }
        kind = _string(payload.get("kind")) or "phrase"
        limit = _bounded_int(payload.get("limit"), default=200, minimum=1, maximum=500)
        project = _string(payload.get("project")) or self.config.project
        report = self.core.inspect_memory_v2(
            project=project,
            limit=limit,
            kind=kind,
            status=status if status != "all" else "",
        )
        entries = [
            _rime_lexicon_export_entry(item)
            for item in report.get("items", [])
            if isinstance(item, dict) and _string(item.get("text"))
        ]
        text = _rime_lexicon_export_text(project=project, status=status, entries=entries)
        return {
            "schemaVersion": "rag-ime.management-lexicon-rime-export.v1",
            "ok": True,
            "dryRun": True,
            "applySupported": False,
            "project": project,
            "kind": kind,
            "status": status,
            "format": "rag-ime-rime-custom-phrase-preview.tsv",
            "formatDescription": "dry-run preview: phrase<TAB>weight<TAB>memory_id",
            "entryCount": len(entries),
            "entries": entries,
            "text": text,
            "rawTextVisible": True,
        }

    def management_memory_action(self, payload: dict[str, Any]) -> dict[str, object]:
        return self._management_item_action(payload, lexicon=False)

    def management_lexicon_action(self, payload: dict[str, Any]) -> dict[str, object]:
        return self._management_item_action(payload, lexicon=True)

    def management_cleanup_diff(self, payload: dict[str, Any]) -> dict[str, object]:
        if not isinstance(self.core, LocalSqliteCoreClient):
            return {
                "schemaVersion": "rag-ime.management-cleanup-diff.v1",
                "ok": False,
                "error": "cleanup diff review is only available for local SQLite core",
            }
        diff_id = _optional_int(payload.get("id") or payload.get("diffId"))
        if diff_id:
            try:
                with self.core._connect() as conn:  # type: ignore[attr-defined]
                    row = _cleanup_diff_payload_for_debug(conn, diff_id=diff_id)
            except ValueError as exc:
                return {"schemaVersion": "rag-ime.management-cleanup-diff.v1", "ok": False, "error": str(exc)}
            return {"schemaVersion": "rag-ime.management-cleanup-diff.v1", "ok": True, "diff": row}
        runs = self.core.list_memory_cleanup_runs(
            limit=_bounded_int(payload.get("limit"), default=20, minimum=1, maximum=100),
            run_id=_string(payload.get("runId")),
            status=_string(payload.get("status")),
        )
        return {
            "schemaVersion": "rag-ime.management-cleanup-diff.v1",
            "ok": True,
            **runs,
        }

    def management_cleanup_diff_apply(self, payload: dict[str, Any]) -> dict[str, object]:
        diff_id = _optional_int(payload.get("id") or payload.get("diffId"))
        confirmation = self._management_cleanup_confirmation(payload, expected="apply")
        if confirmation:
            return confirmation
        result = self.memory_cleanup_diff_apply(diff_id or 0)
        audit_id = self._record_management_audit(
            action="cleanup_diff_apply",
            target_type="cleanup_diff",
            target_id=str(diff_id or ""),
            payload=payload,
            result=result,
        )
        return {
            "schemaVersion": "rag-ime.management-cleanup-diff-action.v1",
            "ok": bool(result.get("ok")),
            "auditId": audit_id,
            "result": result,
        }

    def management_cleanup_diff_rollback(self, payload: dict[str, Any]) -> dict[str, object]:
        diff_id = _optional_int(payload.get("id") or payload.get("diffId"))
        confirmation = self._management_cleanup_confirmation(payload, expected="rollback")
        if confirmation:
            return confirmation
        result = self.memory_cleanup_diff_rollback(diff_id or 0)
        audit_id = self._record_management_audit(
            action="cleanup_diff_rollback",
            target_type="cleanup_diff",
            target_id=str(diff_id or ""),
            payload=payload,
            result=result,
        )
        return {
            "schemaVersion": "rag-ime.management-cleanup-diff-action.v1",
            "ok": bool(result.get("ok")),
            "auditId": audit_id,
            "result": result,
        }

    def _management_cleanup_confirmation(self, payload: dict[str, Any], *, expected: str) -> dict[str, object]:
        confirm = _string(payload.get("confirm"))
        if confirm == expected:
            return {}
        return {
            "schemaVersion": "rag-ime.management-cleanup-diff-action.v1",
            "ok": False,
            "error": f'confirmation required: set confirm="{expected}"',
            "requiredConfirm": expected,
        }

    def _management_memory_items(self, payload: dict[str, Any], *, lexicon: bool) -> dict[str, object]:
        if not isinstance(self.core, LocalSqliteCoreClient):
            return {
                "ok": False,
                "error": "memory item review is only available for local SQLite core",
                "items": [],
            }
        status = _string(payload.get("status")) or "pending"
        kind = _string(payload.get("kind"))
        if lexicon and not kind:
            kind = "phrase"
        report = self.core.inspect_memory_v2(
            project=_string(payload.get("project")) or self.config.project,
            limit=_bounded_int(payload.get("limit"), default=100, minimum=1, maximum=200),
            kind=kind,
            status=status if status != "all" else "",
        )
        include_text = self._include_raw_text()
        items = [
            _redact_memory_item(item, include_text=include_text, lexicon=lexicon)
            for item in report.get("items", [])
            if isinstance(item, dict)
        ]
        return {
            "ok": True,
            "project": report.get("project"),
            "status": status,
            "kind": kind,
            "rawTextVisible": include_text,
            "items": items,
        }

    def _management_item_action(self, payload: dict[str, Any], *, lexicon: bool) -> dict[str, object]:
        if not isinstance(self.core, LocalSqliteCoreClient):
            return {
                "schemaVersion": "rag-ime.management-item-action.v1",
                "ok": False,
                "error": "memory item action is only available for local SQLite core",
            }
        memory_id = _string(payload.get("memoryId") or payload.get("id"))
        action = _management_action(_string(payload.get("action") or payload.get("actionType")))
        if not memory_id:
            return {
                "schemaVersion": "rag-ime.management-item-action.v1",
                "ok": False,
                "error": "memoryId is required",
            }
        if action not in {"approve", "reject", "tombstone", "hide", "restore", "pin", "downrank"}:
            return {
                "schemaVersion": "rag-ime.management-item-action.v1",
                "ok": False,
                "error": f"unsupported action: {action}",
            }
        if action == "tombstone":
            result = self.memory_tombstone(
                {
                    "targetType": "memory_id",
                    "targetValue": memory_id,
                    "reason": _string(payload.get("reason")) or "debug-management-item",
                    "metadata": {"source": "debug-management", "lexicon": lexicon},
                }
            )
        else:
            result = self._update_memory_item_status(memory_id=memory_id, action=action, payload=payload)
        audit_id = self._record_management_audit(
            action=("lexicon_" if lexicon else "memory_") + action,
            target_type="lexicon" if lexicon else "memory",
            target_id=memory_id,
            payload=payload,
            result=result,
        )
        self._clear_rime_cache()
        return {
            "schemaVersion": "rag-ime.management-item-action.v1",
            "ok": bool(result.get("ok")),
            "auditId": audit_id,
            "result": result,
        }

    def _update_memory_item_status(self, *, memory_id: str, action: str, payload: dict[str, Any]) -> dict[str, object]:
        status_by_action = {
            "approve": "approved",
            "reject": "rejected",
            "hide": "hidden",
            "restore": "active",
            "pin": "approved",
            "downrank": "active",
        }
        status = status_by_action[action]
        metadata_update = {
            "lastManagementAction": action,
            "managementReason": _string(payload.get("reason")),
            "managedAtMs": now_ms(),
        }
        with self.core._connect() as conn:  # type: ignore[attr-defined]
            row = conn.execute(
                "SELECT metadata_json FROM memory_items WHERE memory_id = ? LIMIT 1",
                (memory_id,),
            ).fetchone()
            if row is None:
                return {"ok": False, "error": f"memory item not found: {memory_id}", "memoryId": memory_id}
            metadata = _json_loads_dict(row["metadata_json"])
            metadata.update({key: value for key, value in metadata_update.items() if value not in ("", None)})
            quality_expr = "quality_score"
            if action == "pin":
                quality_expr = "MIN(1.0, quality_score + 0.12)"
                metadata["pinned"] = True
            elif action == "downrank":
                quality_expr = "MAX(0.05, quality_score - 0.12)"
                metadata["downranked"] = True
            conn.execute(
                f"""
                UPDATE memory_items
                SET status = ?, quality_score = {quality_expr}, updated_at_ms = ?, metadata_json = ?
                WHERE memory_id = ?
                """,
                (
                    status,
                    now_ms(),
                    json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                    memory_id,
                ),
            )
        return {"ok": True, "memoryId": memory_id, "action": action, "status": status}

    def _include_raw_text(self) -> bool:
        settings = self.settings_store.get_settings(include_sensitive=True)
        privacy = settings.get("privacy") if isinstance(settings.get("privacy"), dict) else {}
        return bool(
            self.config.include_raw_text
            or privacy.get("debugIncludeText") is True
            or os.environ.get("RAG_IME_TRACE_INCLUDE_TEXT") == "1"
            or os.environ.get("RAG_IME_DEBUG_INCLUDE_TEXT") == "1"
        )

    def _record_management_audit(
        self,
        *,
        action: str,
        target_type: str,
        target_id: str,
        payload: dict[str, Any],
        result: dict[str, object],
    ) -> int:
        if not isinstance(self.core, LocalSqliteCoreClient):
            return 0
        safe_payload = _redact_mapping(payload, include_text=False)
        safe_result = _redact_mapping(result, include_text=False)
        with self.core._connect() as conn:  # type: ignore[attr-defined]
            _ensure_management_audit_schema(conn)
            cur = conn.execute(
                """
                INSERT INTO management_audit_log(
                    created_at_ms, action, target_type, target_id, payload_json, result_json
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    now_ms(),
                    action,
                    target_type,
                    target_id,
                    json.dumps(safe_payload, ensure_ascii=False, sort_keys=True),
                    json.dumps(safe_result, ensure_ascii=False, sort_keys=True),
                ),
            )
            return int(cur.lastrowid)

    def organize_rag_database(self, payload: dict[str, Any]) -> dict[str, object]:
        organizer = getattr(self.core, "organize_rag_database", None)
        if not callable(organizer):
            return {
                "schemaVersion": "rag-ime.rag-db-organize.v1",
                "ok": False,
                "error": "core does not support RAG database organization",
            }
        report = organizer(
            project=_string(payload.get("project")) or self.config.project,
            dry_run=_bool(payload.get("dryRun"), default=False),
            min_generated_accepts=_bounded_int(payload.get("minGeneratedAccepts"), default=3, minimum=1, maximum=100),
            sample_size=_bounded_int(payload.get("sampleSize"), default=12, minimum=0, maximum=50),
        )
        if not report.get("dryRun"):
            self._clear_rime_cache()
        return {"schemaVersion": "rag-ime.rag-db-organize.v1", "ok": True, **report}

    def generate_memory(self, payload: dict[str, Any]) -> dict[str, object]:
        if not isinstance(self.core, LocalSqliteCoreClient):
            return {
                "schemaVersion": "rag-ime.generated-memory.v1",
                "ok": False,
                "error": "generated memory writeback is only available for local SQLite core",
            }
        project = _string(payload.get("project")) or self.config.project
        source_text = self._memory_generation_source_text(payload, project=project)
        if not compact_whitespace(source_text):
            return {
                "schemaVersion": "rag-ime.generated-memory.v1",
                "ok": False,
                "error": "text or eventIds are required",
            }
        recent_context = _string(payload.get("recentContext"))
        dry_run = _bool(payload.get("dryRun"), default=False)
        allow_duplicates = _bool(payload.get("allowDuplicates"), default=False)
        try:
            generator = VcpRebuildMemoryGenerator.from_env_path(
                _string(payload.get("modelEnvPath")) or _string(payload.get("vcpEnvPath")) or None
            )
            report = generator.generate(
                text=source_text,
                recent_context=recent_context,
                project=project,
                max_items=_bounded_int(payload.get("maxItems"), default=3, minimum=1, maximum=8),
            )
        except MemoryGenerationError as exc:
            return {
                "schemaVersion": "rag-ime.generated-memory.v1",
                "ok": False,
                "error": str(exc),
            }
        recorded: list[dict[str, object]] = []
        duplicate_skipped = 0
        provider_tag = report.provider
        for item in report.items:
            dedupe_tag = generated_memory_dedupe_tag(item.text)
            if not allow_duplicates and self.core.has_event_tag(dedupe_tag):
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
            if not dry_run:
                event_id = self.adapter.commit_text(
                    item.text,
                    recent_context=generated_memory_context(source_text, recent_context, item.reason),
                    project=project,
                    app=_string(payload.get("app")) or "debug-memory-console",
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
        if not dry_run and recorded:
            self._clear_rime_cache()
        return {
            "schemaVersion": "rag-ime.generated-memory.v1",
            "ok": True,
            "dryRun": dry_run,
            "provider": report.provider,
            "model": report.model,
            "elapsedMs": report.elapsed_ms,
            "generated": len(report.items),
            "recorded": 0 if dry_run else len(recorded),
            "duplicateSkipped": duplicate_skipped,
            "items": recorded,
            "metadata": report.metadata,
        }

    def _memory_generation_source_text(self, payload: dict[str, Any], *, project: str) -> str:
        text = _string(payload.get("text"))
        if text:
            return text
        event_ids = [_optional_int(item) for item in payload.get("eventIds", [])] if isinstance(payload.get("eventIds"), list) else []
        event_ids = [item for item in event_ids if item]
        if not event_ids or not isinstance(self.core, LocalSqliteCoreClient):
            return ""
        report = self.core.list_memory_events(project=project, include_deleted=False, limit=500)
        by_id = {int(item["eventId"]): item for item in report.get("items", []) if isinstance(item, dict) and item.get("eventId")}
        chunks: list[str] = []
        for event_id in event_ids[:20]:
            item = by_id.get(event_id)
            if not item:
                continue
            chunks.append(f"- {item.get('text')} | context: {item.get('recentContext')}")
        return "\n".join(chunks)

    def input_source_status(self) -> dict[str, object]:
        script = self._input_source_check_script()
        payload: dict[str, object] = {
            "schemaVersion": "rag-ime.debug-input-source.v1",
            "inputSourceId": self.config.input_source_id,
            "script": str(script),
            "available": False,
            "ok": False,
            "typingReady": False,
            "readinessState": "unavailable",
            "readinessMessage": "input source check script is not available",
        }
        if script is None or not script.exists():
            return {**payload, "error": "input source check script is not available"}
        args = [str(script)]
        if self.config.input_source_require_hitoolbox:
            args.append("--require-hitoolbox-enabled")
        args.append(self.config.input_source_id)
        try:
            completed = subprocess.run(
                args,
                check=False,
                text=True,
                capture_output=True,
                timeout=5,
            )
        except Exception as exc:
            return {
                **payload,
                "available": True,
                "readinessState": "error",
                "readinessMessage": "input source check failed",
                "error": str(exc),
            }
        output = "\n".join(part for part in (completed.stdout.strip(), completed.stderr.strip()) if part)
        parsed = _parse_input_source_check_output(output)
        ok = completed.returncode == 0
        typing_ready = bool(parsed.get("selected"))
        readiness = _input_source_readiness(parsed, ok=ok, typing_ready=typing_ready)
        return {
            **payload,
            "available": True,
            "ok": ok,
            "typingReady": ok and typing_ready,
            **readiness,
            "exitCode": completed.returncode,
            "rawOutput": output,
            **parsed,
        }

    def predictor_ttfc(self, payload: dict[str, Any]) -> dict[str, object]:
        cases = self._predictor_ttfc_cases(payload)
        repeat = _bounded_int(payload.get("repeat"), default=3, minimum=1, maximum=50)
        max_candidates = _bounded_int(payload.get("maxCandidates"), default=3, minimum=1, maximum=10)
        latency_budget_ms = _bounded_int(payload.get("latencyBudgetMs"), default=200, minimum=1, maximum=20_000)
        report = benchmark_streaming_ttft_provider(
            self.predictor,
            cases,
            max_candidates=max_candidates,
            repeat=repeat,
            latency_budget_ms=latency_budget_ms,
        )
        return {
            "schemaVersion": "rag-ime.debug-predictor-ttfc.v1",
            "project": self.config.project,
            "latencyBudgetMs": latency_budget_ms,
            "repeat": {
                "requested": repeat,
                "baseCaseCount": len(cases),
                "effectiveCaseCount": len(cases) * repeat,
            },
            "predictor": prediction_provider_status(self.predictor),
            "benchmark": report,
        }

    def cache_probe(self, payload: dict[str, Any]) -> dict[str, object]:
        current_input = _string(payload.get("currentInput")).strip() or "RAG 输入法"
        recent_context = _string(payload.get("recentContext"))
        project = _string(payload.get("project")) or self.config.project
        repeat = _bounded_int(payload.get("repeat"), default=3, minimum=2, maximum=20)
        top_k = _bounded_int(payload.get("topK"), default=5, minimum=1, maximum=10)
        before = self.health()
        suggest_samples: list[dict[str, object]] = []
        for index in range(repeat):
            response = self.suggest(
                {
                    "currentInput": current_input,
                    "recentContext": recent_context,
                    "project": project,
                    "topK": top_k,
                }
            )
            if index in (0, repeat - 1):
                suggest_samples.append(
                    {
                        "iteration": index + 1,
                        "suggestionCount": len(response.get("suggestions", [])),
                        "modelPredictionCount": len(response.get("modelPredictions", [])),
                        "topSuggestions": [
                            str(item.get("surfaceText") or "")
                            for item in response.get("suggestions", [])[:3]
                            if isinstance(item, dict)
                        ],
                    }
                )

        rime_payload = self._cache_probe_rime_payload(
            payload,
            current_input=current_input,
            recent_context=recent_context,
            project=project,
        )
        rime_samples: list[dict[str, object]] = []
        for index in range(repeat):
            request_payload = copy.deepcopy(rime_payload)
            request_payload["sessionId"] = f"cache-probe-{index + 1}"
            request_payload["requestSeq"] = index + 1
            response = self.rime_suggest(request_payload)
            cache = response.get("cache") if isinstance(response.get("cache"), dict) else {}
            diagnostics = response.get("rankingDiagnostics") if isinstance(response.get("rankingDiagnostics"), dict) else {}
            rime_samples.append(
                {
                    "iteration": index + 1,
                    "hit": bool(cache.get("hit")) if isinstance(cache, dict) else False,
                    "inFlightHit": bool(cache.get("inFlightHit")) if isinstance(cache, dict) else False,
                    "cacheKey": str(cache.get("key") or "") if isinstance(cache, dict) else "",
                    "displayCandidateCount": len(response.get("displayCandidates", [])),
                    "queryBasis": str(response.get("queryBasis") or ""),
                    "sourceCounts": dict(diagnostics.get("sourceCounts") or {}),
                    "hasRagScoreBreakdown": bool(diagnostics.get("hasRagScoreBreakdown")),
                    "topCandidate": _ranking_top_candidate_summary(diagnostics),
                }
            )
        after = self.health()
        suggestion_delta = _cache_stats_delta(before.get("suggestionCache"), after.get("suggestionCache"))
        rime_delta = _cache_stats_delta(before.get("rimeSuggestCache"), after.get("rimeSuggestCache"))
        expected_warm_hits = repeat - 1
        suggestion_hit_delta = int(suggestion_delta.get("hitsDelta") or 0)
        rime_hit_delta = int(rime_delta.get("hitsDelta") or 0)
        return {
            "schemaVersion": "rag-ime.debug-cache-probe.v1",
            "project": project,
            "currentInput": current_input,
            "recentContextLength": len(recent_context),
            "repeat": repeat,
            "expectedWarmHits": expected_warm_hits,
            "suggestionCache": suggestion_delta,
            "rimeSuggestCache": rime_delta,
            "summary": {
                "suggestionCacheHitDelta": suggestion_hit_delta,
                "rimeCacheHitDelta": rime_hit_delta,
                "suggestionCachePassed": _cache_delta_passed(suggestion_delta, expected_warm_hits),
                "rimeCachePassed": _cache_delta_passed(rime_delta, expected_warm_hits),
            },
            "samples": {
                "suggest": suggest_samples,
                "rimeSuggest": rime_samples,
            },
        }

    def prediction_live_trace(self, payload: dict[str, Any]) -> dict[str, object]:
        limit = _bounded_int(payload.get("limit"), default=100, minimum=1, maximum=500)
        session_id = _string(payload.get("sessionId"))
        with self._rime_cache_lock:
            frames = list(self._prediction_live_trace)
        if session_id:
            frames = [item for item in frames if _string(item.get("sessionId")) == session_id]
        frames = frames[-limit:]
        return {
            "schemaVersion": "rag-ime.prediction-live-trace.v1",
            "ok": True,
            "limit": limit,
            "count": len(frames),
            "rawTextVisible": self._include_raw_text(),
            "frames": frames,
            "dropStats": _prediction_drop_stats(frames),
        }

    def prediction_drop_stats(self, payload: dict[str, Any]) -> dict[str, object]:
        limit = _bounded_int(payload.get("limit"), default=500, minimum=1, maximum=1000)
        with self._rime_cache_lock:
            frames = list(self._prediction_live_trace)[-limit:]
        return {
            "schemaVersion": "rag-ime.prediction-drop-stats.v1",
            "ok": True,
            "limit": limit,
            "frameCount": len(frames),
            **_prediction_drop_stats(frames),
        }

    def seed(self) -> dict[str, object]:
        event_ids = seed_demo_memories(self.adapter, default_fixture_memories())
        self._clear_rime_cache()
        return {
            "ok": True,
            "seeded": len(event_ids),
            "eventCount": self._event_count(),
        }

    def suggest(self, payload: dict[str, Any]) -> dict[str, object]:
        current_input = _string(payload.get("currentInput"))
        recent_context = _string(payload.get("recentContext"))
        project = _string(payload.get("project")) or self.config.project
        app = _string(payload.get("app") or payload.get("frontmostApp"))
        top_k = _bounded_int(payload.get("topK"), default=5, minimum=1, maximum=10)
        prediction_context = build_prediction_context(
            self.core,
            explicit_recent_context=recent_context,
            project=project,
        )
        model_predictions = self.predictor.predict(
            current_input=current_input,
            recent_context=prediction_context,
            max_candidates=5,
        )
        suggestions = self.adapter.suggest(
            SuggestionRequest(
                current_input=current_input,
                recent_context=prediction_context,
                project=project,
                app=app,
                top_k=top_k,
            )
        )
        return suggestions_response_payload(
            current_input=current_input,
            recent_context=recent_context,
            project=project,
            history_context=prediction_context,
            model_predictions=model_predictions,
            suggestions=suggestions,
        )

    def rime_suggest(self, payload: dict[str, Any]) -> dict[str, object]:
        settings = self.settings_store.get_settings(include_sensitive=True)
        _apply_pinyin_settings_to_process_env(settings)
        cache_key = self._rime_suggest_cache_key(payload, settings=settings)
        bypass_cache = self._rime_suggest_cache_bypass(payload)
        cached = None if bypass_cache else self._get_cached_rime_response(cache_key, payload)
        if cached is not None:
            self._record_prediction_live_trace(cached, request_payload=payload)
            return cached
        owner, inflight = self._begin_rime_inflight(cache_key)
        if not owner:
            response = self._wait_for_rime_inflight(cache_key, inflight, payload)
            self._record_prediction_live_trace(response, request_payload=payload)
            return response
        try:
            response = build_rime_sidecar_response(
                payload=payload,
                adapter=self.adapter,
                core=self.core,
                predictor=self.predictor,
                default_project=self.config.project,
            )
        except BaseException as exc:
            self._finish_rime_inflight(cache_key, error=exc)
            raise
        _attach_rime_ranking_diagnostics(response)
        self._apply_management_settings_to_rime_response(response, request_payload=payload, settings=settings)
        if self._rime_response_cacheable(response, request_payload=payload):
            self._store_rime_response(cache_key, response)
        self._finish_rime_inflight(cache_key, response=response)
        response = copy.deepcopy(response)
        response["cache"] = self._cache_payload(hit=False, cache_key=cache_key)
        self._record_prediction_live_trace(response, request_payload=payload)
        return response

    def _apply_management_settings_to_rime_response(
        self,
        response: dict[str, object],
        *,
        request_payload: dict[str, Any],
        settings: dict[str, object] | None = None,
    ) -> None:
        if settings is None:
            settings = self.settings_store.get_settings(include_sensitive=True)
        interaction = settings.get("interaction") if isinstance(settings.get("interaction"), dict) else {}
        composition = interaction.get("composition") if isinstance(interaction.get("composition"), dict) else {}
        post_commit = interaction.get("postCommit") if isinstance(interaction.get("postCommit"), dict) else {}
        display = settings.get("display") if isinstance(settings.get("display"), dict) else {}
        badges = display.get("badges") if isinstance(display.get("badges"), dict) else {}
        colors = display.get("colors") if isinstance(display.get("colors"), dict) else {}
        active_composition = bool(compact_whitespace(_string(request_payload.get("rawInput")) or _string(request_payload.get("preedit"))))
        items = [dict(item) for item in response.get("displayCandidates", []) if isinstance(item, dict)]
        if active_composition and composition.get("showPrediction") is False:
            items = [item for item in items if _string(item.get("sourceType")) in {"rime", "raw_english", "status"}]
        if post_commit.get("showPendingStatus") is False:
            items = [item for item in items if _string(item.get("sourceType")) != "status" and _string(item.get("displayLayout")) != "status_row"]
        max_post_commit = _bounded_int(display.get("maxPostCommitCandidates"), default=5, minimum=1, maximum=10)
        if not active_composition:
            kept: list[dict[str, object]] = []
            selectable_count = 0
            for item in items:
                if _string(item.get("sourceType")) == "status" or _string(item.get("selectionAction")) == "none":
                    kept.append(item)
                    continue
                selectable_count += 1
                if selectable_count <= max_post_commit:
                    kept.append(item)
            items = kept
        show_badges = display.get("showSourceBadge") is not False
        for item in items:
            source_type = _string(item.get("sourceType"))
            custom_badge = _string(badges.get(source_type))
            custom_color = _string(colors.get(source_type))
            if not show_badges:
                item["badge"] = ""
                item["sourceBadge"] = ""
            elif custom_badge:
                item["badge"] = custom_badge
                item["sourceBadge"] = custom_badge
            if custom_color:
                item["colorToken"] = custom_color
        response["displayCandidates"] = items
        response["managementSettings"] = {
            "settingsHash": _settings_hash(settings),
            "interactionApplied": True,
            "displayApplied": True,
        }
        if isinstance(response.get("keyPolicy"), dict) and post_commit.get("numberKeys"):
            response["keyPolicy"]["numberKeys"] = post_commit.get("numberKeys")  # type: ignore[index]
        prediction_session = response.get("predictionSession")
        if isinstance(prediction_session, dict):
            policy = prediction_session.get("keyPolicy")
            if isinstance(policy, dict) and post_commit.get("numberKeys"):
                policy["numberKeys"] = post_commit.get("numberKeys")

    def rime_select(self, payload: dict[str, Any]) -> dict[str, object]:
        response = record_rime_side_candidate_selection(
            payload=payload,
            adapter=self.adapter,
            core=self.core,
            default_project=self.config.project,
        )
        if not response.get("dryRun"):
            self._clear_rime_cache()
        return response

    def commit(self, payload: dict[str, Any]) -> dict[str, object]:
        text = _string(payload.get("text")).strip()
        if not text:
            raise ValueError("text must not be empty")
        event_id = self.adapter.commit_text(
            text,
            recent_context=_string(payload.get("recentContext")),
            preedit=_string(payload.get("preedit")),
            project=_string(payload.get("project")) or self.config.project,
            candidate_rank=_optional_int(payload.get("candidateRank")),
            provider_name=_string(payload.get("providerName")) or "debug-page",
            tags=tuple(_string_list(payload.get("tags"))),
            source=_string(payload.get("source")) or "debug_page_commit",
            context_group_id=_string(payload.get("contextGroupId")),
            context_group_level=_string(payload.get("contextGroupLevel")) or "app",
        )
        self._clear_rime_cache()
        return {"ok": True, "eventId": event_id, "eventCount": self._event_count()}

    def action(self, payload: dict[str, Any]) -> dict[str, object]:
        action_type = _canonical_action(_string(payload.get("actionType")))
        memory_id = _string(payload.get("memoryId"))
        if not memory_id:
            raise ValueError("memoryId must not be empty")
        action = self.core.apply_action(
            MemoryAction(
                action_id=None,
                created_at_ms=now_ms(),
                memory_id=memory_id,
                action_type=action_type,
                query=_string(payload.get("query")),
                suggestion_id=_string(payload.get("suggestionId")),
                source_event_id=_optional_int(payload.get("sourceEventId")),
                metadata={"surface_text": _string(payload.get("surfaceText"))},
            )
        )
        self._clear_rime_cache()
        return action_response_payload(action)

    def _predictor_ttfc_cases(self, payload: dict[str, Any]) -> list[PredictionBenchmarkCase]:
        raw_cases = payload.get("cases")
        case_items: list[object]
        if isinstance(raw_cases, list) and raw_cases:
            case_items = raw_cases
        else:
            case_items = [
                {
                    "id": "debug-current",
                    "currentInput": _string(payload.get("currentInput")) or "RAG 输入法",
                    "recentContext": _string(payload.get("recentContext")),
                }
            ]
        cases: list[PredictionBenchmarkCase] = []
        for index, item in enumerate(case_items, start=1):
            if isinstance(item, str):
                current_input = item
                recent_context = _string(payload.get("recentContext"))
                case_id = f"case-{index}"
            elif isinstance(item, dict):
                current_input = (
                    _string(item.get("currentInput"))
                    or _string(item.get("current_input"))
                    or _string(item.get("query"))
                    or _string(item.get("input"))
                )
                recent_context = _string(item.get("recentContext")) or _string(item.get("recent_context"))
                case_id = _string(item.get("id")) or _string(item.get("caseId")) or f"case-{index}"
            else:
                continue
            current_input = current_input.strip()
            if not current_input:
                continue
            prediction_context = build_prediction_context(
                self.core,
                explicit_recent_context=recent_context,
                project=self.config.project,
            )
            cases.append(
                PredictionBenchmarkCase(
                    current_input=current_input,
                    recent_context=prediction_context,
                    case_id=case_id,
                )
            )
        if not cases:
            raise ValueError("predictor TTFC probe needs at least one non-empty input case")
        return cases

    def _cache_probe_rime_payload(
        self,
        payload: dict[str, Any],
        *,
        current_input: str,
        recent_context: str,
        project: str,
    ) -> dict[str, object]:
        raw_candidates = payload.get("rimeCandidates")
        candidates: list[dict[str, object]] = []
        if isinstance(raw_candidates, list):
            for index, item in enumerate(raw_candidates[:6], start=1):
                if isinstance(item, str):
                    text = item
                    comment = "cache-probe"
                elif isinstance(item, dict):
                    text = _string(item.get("text"))
                    comment = _string(item.get("comment")) or "cache-probe"
                else:
                    continue
                if text.strip():
                    candidates.append({"label": str(index), "text": text.strip(), "comment": comment, "index": index - 1})
        if not candidates:
            candidates = [{"label": "1", "text": current_input, "comment": "cache-probe", "index": 0}]
        return {
            "sessionId": "cache-probe",
            "requestSeq": 0,
            "rawInput": _string(payload.get("rawInput")) or current_input,
            "preedit": _string(payload.get("preedit")) or current_input,
            "committedContext": recent_context,
            "project": project,
            "idleMs": _bounded_int(payload.get("idleMs"), default=200, minimum=0, maximum=60_000),
            "maxVisibleCandidates": _bounded_int(payload.get("maxVisibleCandidates"), default=6, minimum=1, maximum=10),
            "maxSideCandidates": _bounded_int(payload.get("maxSideCandidates"), default=2, minimum=0, maximum=5),
            "forceSideCandidates": bool(payload.get("forceSideCandidates", False)),
            "rimeContext": {
                "candidates": candidates,
                "highlightedIndex": 0,
                "page": 0,
                "isLastPage": True,
            },
        }

    def _event_count(self) -> int | None:
        count = getattr(self.core, "event_count", None)
        return int(count()) if callable(count) else None

    def _action_count(self) -> int | None:
        count = getattr(self.core, "action_count", None)
        return int(count()) if callable(count) else None

    def _suggestion_cache_stats(self) -> dict[str, object] | None:
        stats = getattr(self.core, "suggestion_cache_stats", None)
        return stats() if callable(stats) else None

    def _vector_index_stats(self) -> dict[str, object] | None:
        stats = getattr(self.core, "vector_index_stats", None)
        return stats() if callable(stats) else None

    def _maybe_auto_rebuild_vector_index(self) -> dict[str, object] | None:
        if not isinstance(self.core, LocalSqliteCoreClient):
            return None
        limit = max(0, int(self.config.vector_auto_rebuild_limit))
        if limit <= 0:
            return None
        stats = self.core.vector_index_stats()
        if not bool(stats.get("enabled")):
            return {
                "trigger": "startup",
                "skippedReason": "embedding provider disabled",
                "limit": limit,
                **stats,
            }
        event_count = self._event_count()
        active_vectors = int(stats.get("activeProviderVectors") or 0)
        if event_count is None or event_count <= 0:
            return {
                "trigger": "startup",
                "skippedReason": "no input events",
                "limit": limit,
                **stats,
            }
        if active_vectors > 0:
            return {
                "trigger": "startup",
                "skippedReason": "active provider vectors already present",
                "limit": limit,
                **stats,
            }
        report = self.core.rebuild_vector_index(project=self.config.project, limit=limit)
        return {
            "trigger": "startup",
            "project": self.config.project,
            "limit": limit,
            **report,
        }

    def _vector_auto_rebuild_status(self) -> dict[str, object]:
        limit = max(0, int(self.config.vector_auto_rebuild_limit))
        return {
            "enabled": limit > 0,
            "limit": limit,
            "lastRun": self._vector_auto_rebuild_report,
        }

    def _cache_ttl_ms(self) -> int:
        return max(0, int(self.config.rime_cache_ttl_ms))

    def _rime_cache_size(self) -> int:
        with self._rime_cache_lock:
            self._prune_rime_cache()
            return len(self._rime_cache)

    def _rime_inflight_size(self) -> int:
        with self._rime_cache_lock:
            return len(self._rime_inflight)

    def _rime_suggest_cache_key(self, payload: dict[str, Any], *, settings: dict[str, object] | None = None) -> str:
        snapshot = parse_rime_context_payload(payload, default_project=self.config.project)
        semantic_query, query_basis = choose_semantic_query(snapshot)
        trigger_decision = decide_side_candidate_refresh(
            snapshot=snapshot,
            semantic_query=semantic_query,
            query_basis=query_basis,
        )
        raw_sensitive_input = {}
        if query_basis in ("preedit", "rawInputFallback") or snapshot.force_side_candidates:
            raw_sensitive_input = {
                "rawInput": snapshot.raw_input,
                "preedit": snapshot.preedit,
            }
        normalized_snapshot = {
            "project": snapshot.project or self.config.project,
            "semanticQuery": semantic_query,
            "queryBasis": query_basis,
            "predictionFirstMerge": prediction_first_merge_enabled(payload),
            "triggerDecision": {
                "shouldRefresh": trigger_decision.should_refresh,
                "reason": trigger_decision.reason,
                "forceSideCandidates": snapshot.force_side_candidates,
            },
            "committedContext": snapshot.committed_context,
            "commitTextPreview": snapshot.commit_text_preview,
            "rimeContext": rime_context_to_payload(snapshot),
            "latencyBudgetMs": snapshot.latency_budget_ms,
            "maxVisibleCandidates": snapshot.max_visible_candidates,
            "maxSideCandidates": snapshot.max_side_candidates,
            **raw_sensitive_input,
        }
        material = {
            "snapshot": normalized_snapshot,
            "project": self.config.project,
            "managementSettingsHash": _settings_hash(settings or self.settings_store.get_settings(include_sensitive=True)),
            "eventCount": self._event_count(),
            "actionCount": self._action_count(),
            "vectorStats": self._vector_index_stats(),
            "predictor": self._predictor_fingerprint(),
        }
        raw = json.dumps(material, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _rime_suggest_cache_bypass(self, payload: dict[str, Any]) -> bool:
        return _bool(payload.get("progressiveFollowUp") or payload.get("progressive_follow_up"), default=False)

    def _rime_response_cacheable(self, response: dict[str, object], *, request_payload: dict[str, Any]) -> bool:
        if self._rime_suggest_cache_bypass(request_payload):
            return False
        progressive = response.get("progressive") if isinstance(response.get("progressive"), dict) else {}
        assert isinstance(progressive, dict)
        if bool(progressive.get("shouldFollowUp")):
            return False
        for lane_key in ("modelLane", "ragLane"):
            lane = response.get(lane_key) if isinstance(response.get(lane_key), dict) else {}
            if isinstance(lane, dict) and (bool(lane.get("pending")) or bool(lane.get("inFlight"))):
                return False
        return True

    def _predictor_fingerprint(self) -> str:
        config = getattr(self.predictor, "config", None)
        if config is None:
            return self.predictor.__class__.__name__
        return f"{self.predictor.__class__.__name__}:{config!r}"

    def _predictor_status(
        self,
        *,
        probe_capabilities: bool = False,
        force_refresh: bool = False,
        ttl_ms: int = 5_000,
    ) -> dict[str, object]:
        if not probe_capabilities:
            return prediction_provider_status(self.predictor, probe_capabilities=False)
        ttl_ms = max(0, int(ttl_ms))
        fingerprint = self._predictor_fingerprint()
        now = time.monotonic()
        with self._predictor_status_lock:
            entry = self._predictor_status_cache.get(True)
            if not force_refresh and entry is not None and entry.fingerprint == fingerprint and entry.expires_at > now:
                status = copy.deepcopy(entry.status)
                status["statusCache"] = {"hit": True, "ttlMs": ttl_ms}
                return status

        status = prediction_provider_status(self.predictor, probe_capabilities=True)
        with self._predictor_status_lock:
            self._predictor_status_cache[True] = _PredictorStatusCacheEntry(
                fingerprint=fingerprint,
                expires_at=time.monotonic() + ttl_ms / 1000,
                status=copy.deepcopy(status),
            )
        status = copy.deepcopy(status)
        status["statusCache"] = {"hit": False, "ttlMs": ttl_ms}
        return status

    def _get_cached_rime_response(self, cache_key: str, payload: dict[str, Any]) -> dict[str, object] | None:
        ttl_ms = self._cache_ttl_ms()
        if ttl_ms <= 0:
            return None
        now = time.monotonic()
        with self._rime_cache_lock:
            self._prune_rime_cache(now=now)
            entry = self._rime_cache.get(cache_key)
            if entry is None or entry.expires_at <= now:
                if entry is not None:
                    self._rime_cache.pop(cache_key, None)
                return None
            self._rime_cache_hits += 1
            response = copy.deepcopy(entry.response)
        self._refresh_cached_rime_response(response, payload)
        response["sessionId"] = _string(payload.get("sessionId")) or str(response.get("sessionId") or "default")
        response["requestSeq"] = _bounded_int(payload.get("requestSeq"), default=0, minimum=0, maximum=2**63 - 1)
        response["cache"] = self._cache_payload(hit=True, cache_key=cache_key)
        return response

    def _refresh_cached_rime_response(self, response: dict[str, object], payload: dict[str, Any]) -> None:
        snapshot = parse_rime_context_payload(payload, default_project=self.config.project)
        semantic_query, query_basis = choose_semantic_query(snapshot)
        trigger_decision = decide_side_candidate_refresh(
            snapshot=snapshot,
            semantic_query=semantic_query,
            query_basis=query_basis,
        )
        response.update(
            {
                **frontend_transaction_to_payload(snapshot.frontend_transaction),
                "frontendTransaction": frontend_transaction_to_payload(snapshot.frontend_transaction),
                "project": snapshot.project or self.config.project,
                "rawInput": snapshot.raw_input,
                "preedit": snapshot.preedit,
                "commitTextPreview": snapshot.commit_text_preview,
                "committedContext": snapshot.committed_context,
                "semanticQuery": semantic_query,
                "queryBasis": query_basis,
                "latencyBudgetMs": snapshot.latency_budget_ms,
                "rimeContext": rime_context_to_payload(snapshot),
                "triggerDecision": {
                    "shouldRefresh": trigger_decision.should_refresh,
                    "reason": trigger_decision.reason,
                    "idleMs": snapshot.idle_ms,
                    "semanticSignalLength": semantic_signal_length(semantic_query),
                    "forceSideCandidates": snapshot.force_side_candidates,
                },
            }
        )
        prediction_first = response.get("predictionFirst")
        if isinstance(prediction_first, dict):
            prediction_first["enabled"] = prediction_first_merge_enabled(payload)
            prediction_first["pinyinPrefix"] = snapshot.preedit or snapshot.raw_input
        _rebind_cached_rime_prediction_payload(response, snapshot=snapshot, semantic_query=semantic_query, query_basis=query_basis)
        _attach_rime_ranking_diagnostics(response)

    def _store_rime_response(self, cache_key: str, response: dict[str, object]) -> None:
        ttl_ms = self._cache_ttl_ms()
        if ttl_ms <= 0:
            return
        with self._rime_cache_lock:
            self._rime_cache_misses += 1
            self._rime_cache[cache_key] = _RimeSuggestCacheEntry(
                expires_at=time.monotonic() + ttl_ms / 1000,
                response=copy.deepcopy(response),
            )
            self._prune_rime_cache()

    def _clear_rime_cache(self) -> None:
        with self._rime_cache_lock:
            self._rime_cache.clear()

    def _input_source_check_script(self) -> Path | None:
        if self.config.input_source_check_script is not None:
            return self.config.input_source_check_script
        source_root = os.environ.get("RAG_IME_SOURCE_ROOT") or os.environ.get("RAG_IME_REPO_ROOT")
        candidates = []
        if source_root:
            candidates.append(Path(source_root) / "scripts" / "check_macos_input_source.sh")
        candidates.append(Path.cwd() / "scripts" / "check_macos_input_source.sh")
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return candidates[0] if candidates else None

    def _prune_rime_cache(self, *, now: float | None = None) -> None:
        current = time.monotonic() if now is None else now
        expired = [key for key, entry in self._rime_cache.items() if entry.expires_at <= current]
        for key in expired:
            self._rime_cache.pop(key, None)

    def _cache_payload(self, *, hit: bool, cache_key: str) -> dict[str, object]:
        return {
            "hit": hit,
            "inFlightHit": False,
            "key": cache_key[:16],
            "ttlMs": self._cache_ttl_ms(),
            "size": self._rime_cache_size(),
            "hits": self._rime_cache_hits,
            "misses": self._rime_cache_misses,
            "inFlight": self._rime_inflight_size(),
            "inFlightHits": self._rime_inflight_hits,
        }

    def _begin_rime_inflight(self, cache_key: str) -> tuple[bool, _RimeSuggestInflightEntry]:
        with self._rime_cache_lock:
            entry = self._rime_inflight.get(cache_key)
            if entry is not None:
                entry.waiters += 1
                self._rime_inflight_hits += 1
                return False, entry
            entry = _RimeSuggestInflightEntry(event=Event())
            self._rime_inflight[cache_key] = entry
            return True, entry

    def _wait_for_rime_inflight(
        self,
        cache_key: str,
        entry: _RimeSuggestInflightEntry,
        payload: dict[str, Any],
    ) -> dict[str, object]:
        entry.event.wait()
        if entry.error is not None:
            raise entry.error
        response = copy.deepcopy(entry.response or {})
        self._refresh_cached_rime_response(response, payload)
        response["sessionId"] = _string(payload.get("sessionId")) or str(response.get("sessionId") or "default")
        response["requestSeq"] = _bounded_int(payload.get("requestSeq"), default=0, minimum=0, maximum=2**63 - 1)
        response["cache"] = {
            **self._cache_payload(hit=False, cache_key=cache_key),
            "inFlightHit": True,
        }
        return response

    def _finish_rime_inflight(
        self,
        cache_key: str,
        *,
        response: dict[str, object] | None = None,
        error: BaseException | None = None,
    ) -> None:
        with self._rime_cache_lock:
            entry = self._rime_inflight.pop(cache_key, None)
            if entry is None:
                return
            if error is not None:
                self._rime_inflight_errors += 1
            entry.response = copy.deepcopy(response) if response is not None else None
            entry.error = error
            entry.event.set()

    def _record_prediction_live_trace(self, response: dict[str, object], *, request_payload: dict[str, Any]) -> None:
        frame = _prediction_live_trace_frame(
            response=response,
            request_payload=request_payload,
            include_raw_text=self._include_raw_text(),
        )
        with self._rime_cache_lock:
            self._prediction_live_trace.append(frame)
            if len(self._prediction_live_trace) > 500:
                del self._prediction_live_trace[: len(self._prediction_live_trace) - 500]


class DebugRequestHandler(BaseHTTPRequestHandler):
    service: DebugImeService
    static_dir: Path

    def do_GET(self) -> None:  # noqa: N802 - stdlib API
        parsed = urlparse(self.path)
        if parsed.path == "/api/events/stream":
            self._stream_management_events()
            return
        if parsed.path in ("/api/health", "/health"):
            self._write_json(HTTPStatus.OK, self.service.health())
            return
        if parsed.path in ("/api/input-source", "/input-source"):
            self._write_json(HTTPStatus.OK, self.service.input_source_status())
            return
        query = parse_qs(parsed.query or "")
        if parsed.path == "/api/overview":
            self._write_json(HTTPStatus.OK, self.service.management.overview())
            return
        if parsed.path == "/api/runtime/status":
            self._write_json(HTTPStatus.OK, self.service.management.runtime_status())
            return
        if parsed.path == "/api/runtime/components":
            self._write_json(HTTPStatus.OK, self.service.management.runtime_components())
            return
        if parsed.path.startswith("/api/runtime/job/"):
            job_id = unquote(parsed.path.rsplit("/", 1)[-1])
            self._write_json(HTTPStatus.OK, self.service.management.runtime_job(job_id))
            return
        if parsed.path == "/api/memory/summary":
            self._write_json(HTTPStatus.OK, self.service.management.memory_summary())
            return
        if parsed.path in {
            "/api/memory/books",
            "/api/memory/atoms",
            "/api/memory/phrases",
            "/api/memory/groups",
            "/api/memory/negative",
        }:
            kind = parsed.path.rsplit("/", 1)[-1]
            self._write_json(
                HTTPStatus.OK,
                self.service.management.memory_page(
                    kind,
                    page_request(
                        {
                            "limit": _query_first(query, "limit"),
                            "cursor": _query_first(query, "cursor"),
                            "query": _query_first(query, "query"),
                            "status": _query_first(query, "status"),
                        }
                    ),
                ),
            )
            return
        if parsed.path == "/api/history/page":
            self._write_json(
                HTTPStatus.OK,
                self.service.management.history_page(
                    page_request(
                        {
                            "limit": _query_first(query, "limit"),
                            "cursor": _query_first(query, "cursor"),
                            "query": _query_first(query, "query"),
                            "status": _query_first(query, "filter"),
                        }
                    )
                ),
            )
            return
        if parsed.path in ("/api/predictor/status",):
            self._write_json(HTTPStatus.OK, self.service.predictor_status())
            return
        if parsed.path in ("/api/settings",):
            self._write_json(HTTPStatus.OK, self.service.settings())
            return
        if parsed.path in ("/api/settings/schema",):
            self._write_json(HTTPStatus.OK, self.service.settings_schema())
            return
        if parsed.path in ("/api/profiles",):
            self._write_json(HTTPStatus.OK, self.service.profiles({"kind": _query_first(query, "kind")}))
            return
        if parsed.path in ("/api/audit",):
            self._write_json(
                HTTPStatus.OK,
                self.service.management_audit(
                    {
                        "limit": _query_first(query, "limit"),
                        "action": _query_first(query, "action"),
                    }
                ),
            )
            return
        if parsed.path in ("/api/vocabulary/items",):
            self._write_json(
                HTTPStatus.OK,
                self.service.vocabulary_items(
                    {
                        "status": _query_first(query, "status"),
                        "query": _query_first(query, "query"),
                    }
                ),
            )
            return
        if parsed.path in ("/api/models/status",):
            self._write_json(HTTPStatus.OK, self.service.models_status())
            return
        if parsed.path in ("/api/models/profiles",):
            self._write_json(HTTPStatus.OK, self.service.model_profiles())
            return
        if parsed.path in ("/api/active-rag/settings",):
            self._write_json(HTTPStatus.OK, self.service.active_rag_settings())
            return
        if parsed.path in ("/api/predictor/latency",):
            self._write_json(
                HTTPStatus.OK,
                self.service.predictor_latency(
                    {
                        "log": _query_first(query, "log"),
                        "last": _query_first(query, "last"),
                    }
                ),
            )
            return
        if parsed.path in ("/api/predictor/cache/stats",):
            self._write_json(HTTPStatus.OK, self.service.predictor_cache_stats())
            return
        if parsed.path in ("/api/active-rag/status", "/api/active-rag/session"):
            self._write_json(
                HTTPStatus.OK,
                self.service.active_rag_status({"sessionId": _query_first(query, "sessionId") or _query_first(query, "id")}),
            )
            return
        if parsed.path.startswith("/api/active-rag/session/"):
            session_id = unquote(parsed.path.rsplit("/", 1)[-1])
            self._write_json(HTTPStatus.OK, self.service.active_rag_status({"sessionId": session_id}))
            return
        if parsed.path in ("/api/prediction/live-trace", "/prediction/live-trace"):
            self._write_json(
                HTTPStatus.OK,
                self.service.prediction_live_trace(
                    {
                        "limit": _query_first(query, "limit"),
                        "sessionId": _query_first(query, "sessionId"),
                    }
                ),
            )
            return
        if parsed.path in ("/api/prediction/drop-stats", "/prediction/drop-stats"):
            self._write_json(
                HTTPStatus.OK,
                self.service.prediction_drop_stats({"limit": _query_first(query, "limit")}),
            )
            return
        if parsed.path in ("/api/candidates/explain",):
            self._write_json(
                HTTPStatus.OK,
                self.service.candidate_explain(
                    {
                        "query": _query_first(query, "query"),
                        "currentInput": _query_first(query, "currentInput"),
                        "recentContext": _query_first(query, "recentContext"),
                        "project": _query_first(query, "project"),
                        "app": _query_first(query, "app"),
                        "topK": _query_first(query, "topK"),
                    }
                ),
            )
            return
        if parsed.path in ("/api/history",):
            self._write_json(
                HTTPStatus.OK,
                self.service.management_history(
                    {
                        "limit": _query_first(query, "limit"),
                        "project": _query_first(query, "project"),
                        "query": _query_first(query, "query"),
                        "source": _query_first(query, "source"),
                        "includeDeleted": _query_first(query, "includeDeleted"),
                        "generatedOnly": _query_first(query, "generatedOnly"),
                    }
                ),
            )
            return
        if parsed.path in ("/api/memories",):
            self._write_json(
                HTTPStatus.OK,
                self.service.management_memories(
                    {
                        "limit": _query_first(query, "limit"),
                        "project": _query_first(query, "project"),
                        "status": _query_first(query, "status"),
                        "kind": _query_first(query, "kind"),
                    }
                ),
            )
            return
        if parsed.path in ("/api/lexicon",):
            self._write_json(
                HTTPStatus.OK,
                self.service.management_lexicon(
                    {
                        "limit": _query_first(query, "limit"),
                        "project": _query_first(query, "project"),
                        "status": _query_first(query, "status"),
                        "kind": _query_first(query, "kind"),
                    }
                ),
            )
            return
        if parsed.path in ("/api/lexicon/export-rime",):
            self._write_json(
                HTTPStatus.OK,
                self.service.management_lexicon_export_rime(
                    {
                        "limit": _query_first(query, "limit"),
                        "project": _query_first(query, "project"),
                        "status": _query_first(query, "status"),
                        "kind": _query_first(query, "kind"),
                        "dryRun": _query_first(query, "dryRun"),
                    }
                ),
            )
            return
        if parsed.path in ("/api/cleanup-diff",):
            self._write_json(
                HTTPStatus.OK,
                self.service.management_cleanup_diff(
                    {
                        "id": _query_first(query, "id"),
                        "diffId": _query_first(query, "diffId"),
                        "runId": _query_first(query, "runId"),
                        "status": _query_first(query, "status"),
                        "limit": _query_first(query, "limit"),
                    }
                ),
            )
            return
        if parsed.path.startswith("/api/memory/optimizer/trace/"):
            trace_id = unquote(parsed.path.rsplit("/", 1)[-1])
            self._write_json(HTTPStatus.OK, self.service.memory_optimizer_trace({"traceId": trace_id}))
            return
        if parsed.path.startswith("/api/memory/candidate/") and parsed.path.endswith("/explain"):
            candidate_id = unquote(parsed.path[len("/api/memory/candidate/") : -len("/explain")].strip("/"))
            self._write_json(
                HTTPStatus.OK,
                self.service.memory_candidate_explain(
                    {
                        "candidateId": candidate_id,
                        "contextHash": _query_first(query, "contextHash"),
                    }
                ),
            )
            return
        if parsed.path in ("/api/memory/suppressions", "/api/memory/governance"):
            self._write_json(
                HTTPStatus.OK,
                self.service.memory_governance(
                    {
                        "limit": _query_first(query, "limit"),
                        "includeInactive": _query_first(query, "includeInactive"),
                    }
                ),
            )
            return
        if parsed.path in ("/api/memory/cleanup-runs",):
            self._write_json(
                HTTPStatus.OK,
                self.service.memory_cleanup_runs(
                    {
                        "limit": _query_first(query, "limit"),
                        "runId": _query_first(query, "runId"),
                        "status": _query_first(query, "status"),
                    }
                ),
            )
            return
        if parsed.path in ("/api/rag-core-v3/doc",):
            self._write_json(HTTPStatus.OK, self.service.rag_core_v3_doc({"id": _query_first(query, "id")}))
            return
        if parsed.path in ("/api/rag-core-v3/tag-graph",):
            self._write_json(
                HTTPStatus.OK,
                self.service.rag_core_v3_tag_graph(
                    {
                        "tag": _query_first(query, "tag"),
                        "limit": _query_first(query, "limit"),
                    }
                ),
            )
            return
        self._serve_static(parsed.path)

    def do_POST(self) -> None:  # noqa: N802 - stdlib API
        try:
            path = urlparse(self.path).path
            security_error = self._management_post_security_error(path)
            if security_error is not None:
                self._write_json(HTTPStatus.FORBIDDEN, security_error)
                return
            payload = self._read_json()
            if path in ("/api/suggest", "/suggest"):
                self._write_json(HTTPStatus.OK, self.service.suggest(payload))
            elif path == "/api/runtime/action":
                self._write_json(HTTPStatus.ACCEPTED, self.service.management.start_runtime_action(payload))
            elif path == "/api/memory/action":
                self._write_json(HTTPStatus.OK, self.service.management.memory_action(payload))
            elif path in ("/api/settings/update",):
                self._write_json(HTTPStatus.OK, self.service.settings_update(payload))
            elif path in ("/api/settings/reset-section",):
                self._write_json(HTTPStatus.OK, self.service.settings_reset_section(payload))
            elif path in ("/api/profiles/save",):
                self._write_json(HTTPStatus.OK, self.service.profile_save(payload))
            elif path in ("/api/profiles/activate-dry-run",):
                self._write_json(HTTPStatus.OK, self.service.profile_activate_dry_run(payload))
            elif path in ("/api/vocabulary/item/add",):
                self._write_json(HTTPStatus.OK, self.service.vocabulary_item_save(payload, action="add"))
            elif path in ("/api/vocabulary/item/edit",):
                self._write_json(HTTPStatus.OK, self.service.vocabulary_item_save(payload, action="edit"))
            elif path in ("/api/vocabulary/item/delete",):
                self._write_json(HTTPStatus.OK, self.service.vocabulary_item_delete(payload))
            elif path in ("/api/vocabulary/phonetic-correction/add",):
                payload = {**payload, "tags": [*_string_list(payload.get("tags")), "phonetic_correction"]}
                self._write_json(HTTPStatus.OK, self.service.vocabulary_item_save(payload, action="phonetic_correction_add"))
            elif path in ("/api/vocabulary/rime-export-preview",):
                self._write_json(HTTPStatus.OK, self.service.vocabulary_rime_export_preview(payload))
            elif path in ("/api/vocabulary/rime-export-apply",):
                self._write_json(HTTPStatus.OK, self.service.vocabulary_rime_export_apply(payload))
            elif path in ("/api/models/probe",):
                self._write_json(HTTPStatus.OK, self.service.model_probe(payload))
            elif path in ("/api/models/benchmark",):
                self._write_json(HTTPStatus.OK, self.service.model_benchmark_job(payload))
            elif path in ("/api/models/matrix-eval",):
                self._write_json(HTTPStatus.OK, self.service.model_benchmark_job(payload))
            elif path in ("/api/models/profile/save",):
                self._write_json(HTTPStatus.OK, self.service.profile_save({**payload, "kind": "model_profile"}))
            elif path in ("/api/models/profile/activate-dry-run",):
                self._write_json(HTTPStatus.OK, self.service.model_activate_dry_run(payload))
            elif path in ("/api/active-rag/settings/update",):
                self._write_json(HTTPStatus.OK, self.service.active_rag_settings_update(payload))
            elif path in ("/api/active-rag/preview",):
                self._write_json(HTTPStatus.OK, self.service.active_rag_preview(payload))
            elif path in ("/api/rime-suggest", "/rime-suggest"):
                self._write_json(HTTPStatus.OK, self.service.rime_suggest(payload))
            elif path in ("/api/rime-select", "/rime-select"):
                self._write_json(HTTPStatus.OK, self.service.rime_select(payload))
            elif path in ("/api/predictor-ttfc", "/predictor-ttfc"):
                self._write_json(HTTPStatus.OK, self.service.predictor_ttfc(payload))
            elif path in ("/api/predictor/benchmark",):
                self._write_json(HTTPStatus.OK, self.service.predictor_benchmark(payload))
            elif path in ("/api/predictor/cache/clear",):
                self._write_json(HTTPStatus.OK, self.service.predictor_cache_clear(payload))
            elif path in ("/api/active-rag/preview",):
                self._write_json(HTTPStatus.OK, self.service.active_rag_preview(payload))
            elif path in ("/api/active-rag/start",):
                self._write_json(HTTPStatus.OK, self.service.active_rag_start(payload))
            elif path in ("/api/active-rag/status", "/api/active-rag/session"):
                self._write_json(HTTPStatus.OK, self.service.active_rag_status(payload))
            elif path in ("/api/active-rag/cancel",):
                self._write_json(HTTPStatus.OK, self.service.active_rag_cancel(payload))
            elif path in ("/api/active-rag/accept",):
                self._write_json(HTTPStatus.OK, self.service.active_rag_accept(payload))
            elif path in ("/api/cache-probe", "/cache-probe"):
                self._write_json(HTTPStatus.OK, self.service.cache_probe(payload))
            elif path in ("/api/rebuild-vector-index", "/rebuild-vector-index"):
                self._write_json(HTTPStatus.OK, self.service.rebuild_vector_index(payload))
            elif path in ("/api/memory-history", "/memory-history"):
                self._write_json(HTTPStatus.OK, self.service.memory_history(payload))
            elif path in ("/api/memory-optimizer-trace", "/memory-optimizer-trace"):
                self._write_json(HTTPStatus.OK, self.service.memory_optimizer_trace(payload))
            elif path in ("/api/memory-candidate-explain", "/memory-candidate-explain"):
                self._write_json(HTTPStatus.OK, self.service.memory_candidate_explain(payload))
            elif path in ("/api/memory-governance", "/memory-governance"):
                self._write_json(HTTPStatus.OK, self.service.memory_governance(payload))
            elif path in ("/api/memory-cleanup-runs", "/memory-cleanup-runs"):
                self._write_json(HTTPStatus.OK, self.service.memory_cleanup_runs(payload))
            elif path in ("/api/memory-tombstone", "/memory-tombstone", "/api/memory/tombstone"):
                self._write_json(HTTPStatus.OK, self.service.memory_tombstone(payload))
            elif path in ("/api/history/tombstone",):
                self._write_json(HTTPStatus.OK, self.service.management_history_tombstone(payload))
            elif path in ("/api/memories/action",):
                self._write_json(HTTPStatus.OK, self.service.management_memory_action(payload))
            elif path in ("/api/lexicon/action",):
                self._write_json(HTTPStatus.OK, self.service.management_lexicon_action(payload))
            elif path in ("/api/lexicon/export-rime",):
                self._write_json(HTTPStatus.OK, self.service.management_lexicon_export_rime(payload))
            elif path in ("/api/cleanup-diff/apply",):
                self._write_json(HTTPStatus.OK, self.service.management_cleanup_diff_apply(payload))
            elif path in ("/api/cleanup-diff/rollback",):
                self._write_json(HTTPStatus.OK, self.service.management_cleanup_diff_rollback(payload))
            elif path.startswith("/api/memory/cleanup-diff/") and path.endswith("/apply"):
                diff_id = _cleanup_diff_path_id(path, suffix="/apply")
                self._write_json(HTTPStatus.OK, self.service.memory_cleanup_diff_apply(diff_id))
            elif path.startswith("/api/memory/cleanup-diff/") and path.endswith("/rollback"):
                diff_id = _cleanup_diff_path_id(path, suffix="/rollback")
                self._write_json(HTTPStatus.OK, self.service.memory_cleanup_diff_rollback(diff_id))
            elif path in ("/api/generate-memory", "/generate-memory"):
                self._write_json(HTTPStatus.OK, self.service.generate_memory(payload))
            elif path in ("/api/organize-rag-db", "/organize-rag-db"):
                self._write_json(HTTPStatus.OK, self.service.organize_rag_database(payload))
            elif path in ("/api/rag-core-v3/query-preview",):
                self._write_json(HTTPStatus.OK, self.service.rag_core_v3_query_preview(payload))
            elif path in ("/api/rag-core-v3/rebuild-retrieval-docs",):
                self._write_json(HTTPStatus.OK, self.service.rag_core_v3_rebuild_retrieval_docs(payload))
            elif path in ("/api/rag-core-v3/memory-book-preview",):
                self._write_json(HTTPStatus.OK, self.service.rag_core_v3_memory_book_preview(payload))
            elif path in ("/api/deepseek/completion-preview",):
                self._write_json(HTTPStatus.OK, self.service.deepseek_completion_preview(payload))
            elif path in ("/api/commit", "/commit"):
                self._write_json(HTTPStatus.OK, self.service.commit(payload))
            elif path in ("/api/action", "/action"):
                self._write_json(HTTPStatus.OK, self.service.action(payload))
            elif path in ("/api/seed", "/seed"):
                self._write_json(HTTPStatus.OK, self.service.seed())
            else:
                self._write_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "unknown endpoint"})
        except Exception as exc:  # pragma: no cover - exercised through browser/manual debugging
            self._write_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})

    def log_message(self, fmt: str, *args: object) -> None:
        if self.path.startswith(("/api/active-rag/status", "/api/active-rag/session")):
            return
        print(f"[rag-ime-debug] {self.address_string()} - {fmt % args}")

    def _stream_management_events(self) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        try:
            for chunk in self.service.management.events.subscribe():
                self.wfile.write(chunk)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return

    def _management_post_security_error(self, path: str) -> dict[str, object] | None:
        if not path.startswith("/api/"):
            return None
        settings = self.service.management_security_settings()
        if settings.get("postRequiresJson") is True:
            content_type = self.headers.get("Content-Type", "")
            if "application/json" not in content_type.lower():
                return {"schemaVersion": "rag-ime.management-security.v3", "ok": False, "error": "POST requires application/json"}
        if settings.get("sameOriginOnly") is True:
            origin = self.headers.get("Origin", "")
            if origin and not _origin_matches_host(origin, self.headers.get("Host", "")):
                return {"schemaVersion": "rag-ime.management-security.v3", "ok": False, "error": "cross-origin POST rejected"}
        if settings.get("requireToken") is True:
            expected = os.environ.get("RAG_IME_MANAGEMENT_TOKEN", "") or _string(settings.get("token"))
            provided = self.headers.get("X-RAG-IME-Admin-Token", "")
            if not expected or provided != expected:
                return {"schemaVersion": "rag-ime.management-security.v3", "ok": False, "error": "management token required"}
        return None

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or "0")
        raw = self.rfile.read(length) if length else b"{}"
        if not raw:
            return {}
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("JSON payload must be an object")
        return data

    def _write_json(self, status: HTTPStatus, payload: dict[str, object]) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, OSError):
            return

    def _serve_static(self, request_path: str) -> None:
        relative = "index.html" if request_path in ("", "/") else unquote(request_path.lstrip("/"))
        candidate = (self.static_dir / relative).resolve()
        static_root = self.static_dir.resolve()
        if static_root not in candidate.parents and candidate != static_root:
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        if not candidate.exists() or not candidate.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        body = candidate.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run_debug_server(config: DebugServerConfig) -> None:
    service = DebugImeService(config)
    static_dir = config.static_dir

    class Handler(DebugRequestHandler):
        pass

    Handler.service = service
    Handler.static_dir = static_dir
    server = ThreadingHTTPServer((config.host, config.port), Handler)
    url = f"http://{config.host}:{config.port}/"
    print(f"RAG IME {config.server_name}: {url}")
    print(f"DB: {config.db_path}")
    server.serve_forever()


def _stable_debug_hash(text: str) -> str:
    compact = compact_whitespace(text)
    if not compact:
        return ""
    return "sha256:" + hashlib.sha256(compact.encode("utf-8")).hexdigest()[:16]


def _settings_hash(settings: dict[str, object]) -> str:
    return _stable_debug_hash(json.dumps(settings, ensure_ascii=False, sort_keys=True))


_PINYIN_PAIR_ENV_NAMES = {
    "zZh": "RAG_IME_PINYIN_FUZZY_Z_ZH",
    "cCh": "RAG_IME_PINYIN_FUZZY_C_CH",
    "sSh": "RAG_IME_PINYIN_FUZZY_S_SH",
    "enEng": "RAG_IME_PINYIN_FUZZY_EN_ENG",
    "inIng": "RAG_IME_PINYIN_FUZZY_IN_ING",
    "nL": "RAG_IME_PINYIN_FUZZY_N_L",
    "fH": "RAG_IME_PINYIN_FUZZY_F_H",
}
_PINYIN_PAIR_DEFAULTS = {
    "zZh": True,
    "cCh": True,
    "sSh": True,
    "enEng": True,
    "inIng": True,
    "nL": False,
    "fH": False,
}


def _apply_pinyin_settings_to_process_env(settings: dict[str, object]) -> None:
    pinyin = settings.get("pinyin") if isinstance(settings.get("pinyin"), dict) else {}
    assert isinstance(pinyin, dict)
    profile = compact_whitespace(str(pinyin.get("fuzzyProfile") or "sichuan-mild")).lower() or "sichuan-mild"
    rerank_uses_fuzzy = pinyin.get("rerankUsesFuzzy") is not False
    if profile in {"none", "off", "disabled"} or not rerank_uses_fuzzy:
        os.environ["RAG_IME_PINYIN_FUZZY_ENABLED"] = "0"
        os.environ["RAG_IME_PINYIN_FUZZY_PROFILE"] = "none"
    else:
        os.environ["RAG_IME_PINYIN_FUZZY_ENABLED"] = "1"
        os.environ["RAG_IME_PINYIN_FUZZY_PROFILE"] = profile
    pairs = pinyin.get("pairs") if isinstance(pinyin.get("pairs"), dict) else {}
    assert isinstance(pairs, dict)
    for key, env_name in _PINYIN_PAIR_ENV_NAMES.items():
        if key in pairs:
            os.environ[env_name] = "1" if pairs.get(key) is not False else "0"


def _pinyin_runtime_status(settings: dict[str, object]) -> dict[str, object]:
    pinyin = settings.get("pinyin") if isinstance(settings.get("pinyin"), dict) else {}
    assert isinstance(pinyin, dict)
    profile = compact_whitespace(str(pinyin.get("fuzzyProfile") or "sichuan-mild")).lower() or "sichuan-mild"
    rerank_uses_fuzzy = pinyin.get("rerankUsesFuzzy") is not False
    fuzzy_enabled = profile not in {"none", "off", "disabled"} and rerank_uses_fuzzy
    pairs = pinyin.get("pairs") if isinstance(pinyin.get("pairs"), dict) else {}
    assert isinstance(pairs, dict)
    return {
        "schemaVersion": "rag-ime.pinyin-runtime.v1",
        "fuzzyEnabled": fuzzy_enabled,
        "profile": profile if fuzzy_enabled else "none",
        "rerankUsesFuzzy": rerank_uses_fuzzy,
        "pairs": {
            key: bool(pairs.get(key, _PINYIN_PAIR_DEFAULTS.get(key, False)))
            for key in _PINYIN_PAIR_ENV_NAMES
        },
    }


def _active_rag_runtime_sync_payload(*, active_settings: object, changed_keys: tuple[str, ...]) -> dict[str, object]:
    settings = dict(active_settings) if isinstance(active_settings, dict) else {}
    capture = settings.get("capture") if isinstance(settings.get("capture"), dict) else {}
    shortcut = compact_whitespace(str(settings.get("shortcut") or "ctrl+shift+r")).lower().replace(" ", "")
    domains = ["im.rime.inputmethod.Squirrel"]
    defaults = {
        "RagImeActiveRagShortcut": {"type": "string", "value": shortcut},
        "RagImeActiveRagCaptureAccessibility": {"type": "bool", "value": bool(capture.get("accessibility", True))},
        "RagImeActiveRagCaptureClipboardFallback": {"type": "bool", "value": bool(capture.get("clipboardFallback", True))},
    }
    commands: list[list[str]] = []
    for domain in domains:
        for key, spec in defaults.items():
            value = spec["value"]
            if spec["type"] == "bool":
                commands.append(["defaults", "write", domain, key, "-bool", "true" if value else "false"])
            else:
                commands.append(["defaults", "write", domain, key, "-string", str(value)])
    return {
        "schemaVersion": "rag-ime.active-rag-runtime-sync.v1",
        "changed": bool(changed_keys),
        "changedKeys": list(changed_keys),
        "shortcut": shortcut,
        "userDefaultsDomains": domains,
        "userDefaults": defaults,
        "commands": commands,
        "restartHint": "Restart or reload Squirrel/RAG-IME if the running input method keeps an old UserDefaults cache.",
    }


def _debug_lane_breakdown(raw_lanes: object) -> dict[str, object]:
    if not isinstance(raw_lanes, dict):
        return {}
    result: dict[str, object] = {}
    for name, payload in raw_lanes.items():
        if not isinstance(payload, dict):
            continue
        result[_camel_lane_name(str(name))] = {
            "count": int(payload.get("count") or 0),
            "docIds": list(payload.get("docIds") or []),
        }
    return result


def _debug_query_preview(query: object, *, include_text: bool) -> dict[str, object]:
    if not isinstance(query, dict):
        return {}
    if include_text:
        return dict(query)
    return {
        "primaryHash": _stable_debug_hash(_string(query.get("primary"))),
        "lexicalTermCount": len(query.get("lexicalTerms") or []),
        "matchedAliasCount": len(query.get("matchedAliases") or []),
        "activatedTagCount": len(query.get("activatedTags") or []),
        "negativeTagCount": len(query.get("negativeTags") or []),
        "expansionTermCount": len(query.get("expansionTerms") or []),
    }


def _debug_redact_rag_candidate(item: dict[str, object], *, include_text: bool) -> dict[str, object]:
    if include_text:
        return _redact_mapping(dict(item), include_text=True)
    text = _string(item.get("text") or item.get("insert_text") or item.get("insertText"))
    evidence_preview = _string(item.get("evidence_preview") or item.get("evidencePreview"))
    metadata = dict(item.get("metadata") or {}) if isinstance(item.get("metadata"), dict) else {}
    return {
        "candidateIdHash": _stable_debug_hash(_string(item.get("candidate_id") or item.get("candidateId"))),
        "textHash": _stable_debug_hash(text),
        "sourceType": item.get("source_type") or item.get("sourceType") or "",
        "sourceLane": item.get("source_lane") or item.get("sourceLane") or "",
        "score": float(item.get("score") or 0.0),
        "confidence": float(item.get("confidence") or 0.0),
        "tagCount": len(item.get("tags") or []),
        "memoryIdCount": len(item.get("memory_ids") or item.get("memoryIds") or []),
        "atomIdCount": len(item.get("atom_ids") or item.get("atomIds") or []),
        "bookIdCount": len(item.get("book_ids") or item.get("bookIds") or []),
        "evidenceEventIds": list(item.get("evidence_event_ids") or item.get("evidenceEventIds") or []),
        "evidencePreviewHash": _stable_debug_hash(evidence_preview),
        "debugFeatures": dict(item.get("debug_features") or item.get("debugFeatures") or {})
        if isinstance(item.get("debug_features") or item.get("debugFeatures"), dict)
        else {},
        "metadata": _redact_mapping(metadata, include_text=False),
    }


def _camel_lane_name(name: str) -> str:
    parts = [part for part in name.split("_") if part]
    if not parts:
        return name
    return parts[0] + "".join(part[:1].upper() + part[1:] for part in parts[1:])


def _debug_deepseek_evidence_pack(candidates: list[object], *, include_text: bool) -> list[dict[str, object]]:
    evidence: list[dict[str, object]] = []
    for item in candidates[:8]:
        if not isinstance(item, dict):
            continue
        text = compact_whitespace(str(item.get("text") or ""))
        evidence_preview = compact_whitespace(str(item.get("evidence_preview") or item.get("evidencePreview") or ""))
        payload: dict[str, object] = {
            "sourceType": item.get("source_type") or item.get("sourceType"),
            "sourceLane": item.get("source_lane") or item.get("sourceLane"),
            "textHash": _stable_debug_hash(text),
            "evidencePreviewHash": _stable_debug_hash(evidence_preview),
            "tagCount": len(item.get("tags") or []),
        }
        if include_text:
            payload.update({"text": text, "evidencePreview": evidence_preview, "tags": item.get("tags") or []})
        evidence.append(payload)
    return evidence


def _debug_memory_book_source_bundle(bundle: dict[str, object], *, include_text: bool) -> dict[str, object]:
    events: list[dict[str, object]] = []
    for item in bundle.get("recentEvents") or []:
        if not isinstance(item, dict):
            continue
        text = _string(item.get("text"))
        recent_context = _string(item.get("recentContext"))
        event: dict[str, object] = {
            "eventId": int(item.get("eventId") or 0),
            "createdAtMs": int(item.get("createdAtMs") or 0),
            "source": _string(item.get("source")),
            "app": _string(item.get("app")),
            "project": _string(item.get("project")),
            "tagCount": len(item.get("tags") or []),
            "textHash": _stable_debug_hash(text),
            "recentContextHash": _stable_debug_hash(recent_context),
        }
        if include_text:
            event.update({"text": text, "recentContext": recent_context, "tags": item.get("tags") or []})
        events.append(event)
    return {
        "schemaVersion": bundle.get("schemaVersion") or "rag-ime.memory-book-source-bundle.v1",
        "project": _string(bundle.get("project")),
        "sinceDays": int(bundle.get("sinceDays") or 0),
        "exportedAtMs": int(bundle.get("exportedAtMs") or 0),
        "redactionStats": dict(bundle.get("redactionStats") or {}) if isinstance(bundle.get("redactionStats"), dict) else {},
        "recentEventCount": len(events),
        "recentEvents": events,
    }


def _privacy_preview(text: str, *, max_chars: int = 12) -> str:
    compact = compact_whitespace(text)
    if not compact:
        return ""
    if len(compact) <= max_chars:
        return compact
    return f"{compact[:max_chars]}..."


def _redact_history_item(item: dict[str, object], *, include_text: bool) -> dict[str, object]:
    text = _string(item.get("text"))
    recent_context = _string(item.get("recentContext"))
    preedit = _string(item.get("preedit"))
    payload = {key: value for key, value in item.items() if key not in {"text", "recentContext", "preedit"}}
    payload.update(
        {
            "textHash": _stable_debug_hash(text),
            "textPreview": _privacy_preview(text),
            "recentContextHash": _stable_debug_hash(recent_context),
            "recentContextPreview": _privacy_preview(recent_context),
            "preeditHash": _stable_debug_hash(preedit),
            "preeditPreview": _privacy_preview(preedit),
        }
    )
    if include_text:
        payload.update({"text": text, "recentContext": recent_context, "preedit": preedit})
    return payload


def _rebind_cached_rime_prediction_payload(
    response: dict[str, object],
    *,
    snapshot: object,
    semantic_query: str,
    query_basis: str,
) -> None:
    prediction_session = response.get("predictionSession")
    if not isinstance(prediction_session, dict):
        return
    input_mode = _string(prediction_session.get("inputMode")) or _string(
        response.get("predictionFirst", {}).get("mode") if isinstance(response.get("predictionFirst"), dict) else ""
    )
    transaction_payload = frontend_transaction_to_payload(snapshot.frontend_transaction)
    anchors = build_prediction_anchors_from_snapshot(
        snapshot=snapshot,
        mode=input_mode,
        semantic_query=semantic_query,
        query_basis=query_basis,
        stable_short_pinyin_prefix=snapshot.preedit or snapshot.raw_input,
    )
    anchor_payload = {
        "hardContextAnchor": anchors.hard_context_anchor,
        "queryAnchor": anchors.query_anchor,
        "displayAnchor": anchors.display_anchor,
    }
    prediction_session.update(
        {
            "requestSeq": snapshot.request_seq,
            **transaction_payload,
            **anchor_payload,
            "cacheRebound": True,
        }
    )
    stable_panel = prediction_session.get("stablePanel")
    if isinstance(stable_panel, dict):
        stable_panel.update(anchor_payload)
        stable_panel["cacheRebound"] = True
    for candidate in response.get("displayCandidates") or []:
        if not isinstance(candidate, dict):
            continue
        metadata = candidate.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
            candidate["metadata"] = metadata
        rebound = {
            "requestSeq": snapshot.request_seq,
            "sessionId": snapshot.session_id,
            **transaction_payload,
            **anchor_payload,
            "cacheRebound": True,
        }
        metadata.update(rebound)
        candidate.update(
            {
                "hardContextAnchor": anchors.hard_context_anchor,
                "queryAnchor": anchors.query_anchor,
                "displayAnchor": anchors.display_anchor,
            }
        )
    for trace_event in response.get("predictionTraceEvents") or []:
        if not isinstance(trace_event, dict):
            continue
        fields = trace_event.get("fields")
        if isinstance(fields, dict):
            fields.update({**anchor_payload, "cacheRebound": True})


def _redact_memory_item(item: dict[str, object], *, include_text: bool, lexicon: bool) -> dict[str, object]:
    text = _string(item.get("text"))
    normalized_text = _string(item.get("normalizedText"))
    metadata = dict(item.get("metadata") or {}) if isinstance(item.get("metadata"), dict) else {}
    payload = {key: value for key, value in item.items() if key not in {"text", "normalizedText", "metadata"}}
    payload.update(
        {
            "textHash": _stable_debug_hash(text),
            "textPreview": _privacy_preview(text, max_chars=16 if lexicon else 12),
            "normalizedTextHash": _stable_debug_hash(normalized_text),
            "metadata": _redact_mapping(metadata, include_text=include_text),
        }
    )
    if include_text:
        payload.update({"text": text, "normalizedText": normalized_text})
    return payload


def _rime_lexicon_export_entry(item: dict[str, object]) -> dict[str, object]:
    phrase = compact_whitespace(_string(item.get("text"))).replace("\t", " ")
    quality_score = _float_or_default(item.get("qualityScore"), 0.5)
    confidence = _float_or_default(item.get("confidence"), 0.5)
    weight = max(1, min(100, int(round(((quality_score * 0.7) + (confidence * 0.3)) * 100))))
    return {
        "phrase": phrase,
        "weight": weight,
        "memoryId": _string(item.get("memoryId")),
        "status": _string(item.get("status")),
        "qualityScore": quality_score,
        "confidence": confidence,
    }


def _rime_lexicon_export_text(*, project: str, status: str, entries: list[dict[str, object]]) -> str:
    lines = [
        "# RAG-IME lexicon export preview",
        "# Dry-run only: review before importing or writing to Rime user files.",
        f"# project: {project}",
        f"# status: {status}",
        "# format: phrase<TAB>weight<TAB>memory_id",
    ]
    for entry in entries:
        phrase = _string(entry.get("phrase")).replace("\n", " ").replace("\r", " ").replace("\t", " ")
        memory_id = _string(entry.get("memoryId")).replace("\t", " ")
        lines.append(f"{phrase}\t{int(entry.get('weight') or 1)}\t{memory_id}")
    return "\n".join(lines) + "\n"


def _redact_mapping(value: dict[str, object], *, include_text: bool) -> dict[str, object]:
    redacted: dict[str, object] = {}
    sensitive_keys = {
        "text",
        "rawText",
        "raw_text",
        "recentContext",
        "preedit",
        "committedContext",
        "evidencePreview",
        "evidence_preview",
        "payload",
        "result",
    }
    for key, item in value.items():
        if isinstance(item, dict):
            redacted[key] = _redact_mapping(item, include_text=include_text)
        elif isinstance(item, list):
            redacted[key] = [
                _redact_mapping(part, include_text=include_text) if isinstance(part, dict) else part
                for part in item
            ]
        elif include_text or key not in sensitive_keys:
            redacted[key] = item
        else:
            text = _string(item)
            redacted[f"{key}Hash"] = _stable_debug_hash(text)
            redacted[f"{key}Chars"] = len(text)
    return redacted


def _score_penalty(score_breakdown: object) -> float:
    if not isinstance(score_breakdown, dict):
        return 0.0
    penalty = 0.0
    for key, value in score_breakdown.items():
        if "penalty" not in str(key).lower():
            continue
        try:
            penalty += abs(float(value))
        except (TypeError, ValueError):
            continue
    return penalty


def _management_action(raw: str) -> str:
    normalized = raw.strip().lower().replace("_", "-")
    aliases = {
        "approved": "approve",
        "accept": "approve",
        "accepted": "approve",
        "rejected": "reject",
        "delete": "tombstone",
        "deleted": "tombstone",
        "downranked": "downrank",
        "pinned": "pin",
    }
    return aliases.get(normalized, normalized)


def _ensure_management_audit_schema(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS management_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at_ms INTEGER NOT NULL,
            action TEXT NOT NULL,
            target_type TEXT NOT NULL,
            target_id TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}',
            result_json TEXT NOT NULL DEFAULT '{}'
        )
        """
    )


def _json_loads_dict(raw: object) -> dict[str, object]:
    if isinstance(raw, dict):
        return dict(raw)
    if not isinstance(raw, str) or not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return dict(value) if isinstance(value, dict) else {}


def _cleanup_diff_payload_for_debug(conn, *, diff_id: int) -> dict[str, object]:
    row = conn.execute(
        """
        SELECT id, run_id, op, target_memory_id, payload_json, status, created_at_ms, applied_at_ms, rollback_json
        FROM memory_cleanup_diffs
        WHERE id = ?
        LIMIT 1
        """,
        (int(diff_id),),
    ).fetchone()
    if row is None:
        raise ValueError(f"cleanup diff not found: {diff_id}")
    payload = _json_loads_dict(row["payload_json"])
    rollback = _json_loads_dict(row["rollback_json"])
    return {
        "diffId": int(row["id"]),
        "runId": str(row["run_id"]),
        "op": str(row["op"]),
        "targetMemoryId": str(row["target_memory_id"]),
        "payload": _redact_mapping(payload, include_text=False),
        "status": str(row["status"]),
        "createdAtMs": int(row["created_at_ms"] or 0),
        "appliedAtMs": int(row["applied_at_ms"] or 0),
        "rollback": _redact_mapping(rollback, include_text=False),
    }


def _string(value: object) -> str:
    return value if isinstance(value, str) else ""


def _query_first(query: dict[str, list[str]], key: str) -> str:
    values = query.get(key) or []
    return values[0] if values else ""


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _int_list(value: object) -> list[int]:
    if not isinstance(value, list):
        return []
    parsed: list[int] = []
    for item in value:
        candidate = _optional_int(item)
        if candidate is not None:
            parsed.append(candidate)
    return parsed


def _bool(value: object, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return default


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _bounded_int(value: object, *, default: int, minimum: int, maximum: int) -> int:
    parsed = _optional_int(value)
    if parsed is None:
        return default
    return max(minimum, min(maximum, parsed))


def _float_or_default(value: object, default: float) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return default
    return default


def _cleanup_review_status(payload: dict[str, object]) -> str:
    review_status = _string(payload.get("reviewStatus")).strip().lower()
    action = _string(payload.get("action")).strip().lower()
    if not review_status and action in {"approve", "approved"}:
        review_status = "approved"
    if not review_status and action in {"reject", "rejected"}:
        review_status = "rejected"
    if not review_status and action in {"reset", "pending"}:
        review_status = "pending"
    return review_status


def _cleanup_diff_path_id(path: str, *, suffix: str) -> int:
    prefix = "/api/memory/cleanup-diff/"
    if not path.startswith(prefix) or not path.endswith(suffix):
        raise ValueError("invalid cleanup diff path")
    raw = path[len(prefix) : -len(suffix)].strip("/")
    diff_id = _optional_int(raw)
    if diff_id is None:
        raise ValueError("cleanup diff path requires numeric diff id")
    return diff_id


def _attach_rime_ranking_diagnostics(response: dict[str, object]) -> None:
    response["rankingDiagnostics"] = _rime_ranking_diagnostics(response)


def _rime_ranking_diagnostics(response: dict[str, object]) -> dict[str, object]:
    display_candidates = response.get("displayCandidates")
    if not isinstance(display_candidates, list):
        display_candidates = []
    rag_candidates = response.get("ragCandidates")
    if not isinstance(rag_candidates, list):
        rag_candidates = []
    items: list[dict[str, object]] = []
    evidence_items: list[dict[str, object]] = []
    source_counts: dict[str, int] = {}
    evidence_source_counts: dict[str, int] = {}
    has_rag_breakdown = False
    has_model_candidate_scores = False
    for index, candidate in enumerate(display_candidates, start=1):
        if not isinstance(candidate, dict):
            continue
        source_type = _string(candidate.get("sourceType")) or _string(candidate.get("displayLane")) or "unknown"
        source_counts[source_type] = source_counts.get(source_type, 0) + 1
        diagnostics = _display_candidate_diagnostics(candidate, default_rank=index)
        breakdown = diagnostics.get("scoreBreakdown")
        if isinstance(breakdown, dict):
            has_rag_breakdown = True
        if int(diagnostics.get("candidateScoreCount") or 0) > 0:
            has_model_candidate_scores = True
        items.append(diagnostics)
    for index, candidate in enumerate(rag_candidates, start=1):
        if not isinstance(candidate, dict):
            continue
        metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
        source_type = _string(metadata.get("source_type") or candidate.get("sourceType") or "rag")
        evidence_source_counts[source_type] = evidence_source_counts.get(source_type, 0) + 1
        diagnostics = _rag_evidence_candidate_diagnostics(candidate, default_rank=index)
        if isinstance(diagnostics.get("scoreBreakdown"), dict):
            has_rag_breakdown = True
        evidence_items.append(diagnostics)
    side_count = sum(count for source, count in source_counts.items() if source != "rime")
    rime_count = source_counts.get("rime", 0)
    return {
        "schemaVersion": "rag-ime.ranking-diagnostics.v1",
        "candidateCount": len(items),
        "ragEvidenceCount": len(evidence_items),
        "sideCandidateCount": side_count,
        "rimeCandidateCount": rime_count,
        "sourceCounts": source_counts,
        "evidenceSourceCounts": evidence_source_counts,
        "hasRagScoreBreakdown": has_rag_breakdown,
        "hasModelCandidateScores": has_model_candidate_scores,
        "topCandidate": items[0] if items else None,
        "items": items,
        "evidenceItems": evidence_items,
    }


def _rag_evidence_candidate_diagnostics(candidate: dict[str, object], *, default_rank: int) -> dict[str, object]:
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    normalized = dict(candidate)
    normalized.setdefault("text", candidate.get("surfaceText") or candidate.get("insertText"))
    normalized.setdefault("sourceType", metadata.get("source_type") or "rag")
    normalized.setdefault("displayLane", metadata.get("source_type") or "rag_evidence")
    return _display_candidate_diagnostics(normalized, default_rank=default_rank)


def _display_candidate_diagnostics(candidate: dict[str, object], *, default_rank: int) -> dict[str, object]:
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    source_type = _string(candidate.get("sourceType")) or _string(candidate.get("displayLane")) or "unknown"
    item: dict[str, object] = {
        "selectionKey": _string(candidate.get("selectionKey")) or _string(candidate.get("label")),
        "selectionRank": _optional_int(candidate.get("selectionRank")) or default_rank,
        "text": _string(candidate.get("text")),
        "insertTextLength": len(_string(candidate.get("insertText"))),
        "sourceType": source_type,
        "displayLane": _string(candidate.get("displayLane")) or source_type,
        "displayLayout": _string(candidate.get("displayLayout")),
        "selectionAction": _string(candidate.get("selectionAction")),
        "sourceIndex": _optional_int(candidate.get("sourceIndex")),
        "memoryId": _string(candidate.get("memoryId")),
        "sourceEventId": _optional_int(candidate.get("sourceEventId")),
        "suggestionId": _string(candidate.get("suggestionId")),
        "reason": _string(metadata.get("reason")),
    }
    breakdown = metadata.get("score_breakdown")
    if breakdown is None:
        breakdown = metadata.get("scoreBreakdown")
    if isinstance(breakdown, dict):
        item["scoreBreakdown"] = breakdown
        item["scoreBreakdownTotal"] = _number_or_none(breakdown.get("total"))
        components = breakdown.get("components") if isinstance(breakdown.get("components"), dict) else {}
        item["topScoreComponents"] = _top_score_components(components)
        raw_signals = breakdown.get("rawSignals") if isinstance(breakdown.get("rawSignals"), dict) else {}
        item["rawSignalsSummary"] = _raw_signals_summary(raw_signals)
    candidate_scores = metadata.get("candidate_scores")
    if candidate_scores is None:
        candidate_scores = metadata.get("candidateScores")
    if isinstance(candidate_scores, list):
        item["candidateScoreCount"] = len(candidate_scores)
        item["candidateScoresPreview"] = candidate_scores[:5]
    else:
        item["candidateScoreCount"] = 0
    provider_name = _string(metadata.get("provider_name")) or _string(metadata.get("providerName"))
    if provider_name:
        item["providerName"] = provider_name
    candidate_mode = _string(metadata.get("candidate_mode")) or _string(metadata.get("candidateMode"))
    if not candidate_mode and isinstance(metadata.get("server_timing"), dict):
        candidate_mode = _string(metadata["server_timing"].get("candidateMode"))  # type: ignore[index]
    if candidate_mode:
        item["candidateMode"] = candidate_mode
    return item


def _ranking_top_candidate_summary(diagnostics: dict[str, object]) -> dict[str, object] | None:
    top = diagnostics.get("topCandidate")
    if not isinstance(top, dict):
        return None
    payload = {
        key: value
        for key, value in top.items()
        if key
        in {
            "selectionKey",
            "selectionRank",
            "text",
            "sourceType",
            "displayLane",
            "displayLayout",
            "scoreBreakdownTotal",
            "candidateScoreCount",
            "candidateMode",
            "reason",
        }
        and value not in ("", None)
    }
    top_components = top.get("topScoreComponents")
    if isinstance(top_components, list) and top_components:
        payload["topScoreComponents"] = top_components[:3]
    return payload


def _prediction_live_trace_frame(
    *,
    response: dict[str, object],
    request_payload: dict[str, Any],
    include_raw_text: bool,
) -> dict[str, object]:
    prediction_session = response.get("predictionSession") if isinstance(response.get("predictionSession"), dict) else {}
    rag_lane = response.get("ragLane") if isinstance(response.get("ragLane"), dict) else {}
    model_lane = response.get("modelLane") if isinstance(response.get("modelLane"), dict) else {}
    display_candidates = response.get("displayCandidates") if isinstance(response.get("displayCandidates"), list) else []
    trace_events = response.get("predictionTraceEvents") if isinstance(response.get("predictionTraceEvents"), list) else []
    raw_input = _string(response.get("rawInput") or request_payload.get("rawInput"))
    preedit = _string(response.get("preedit") or request_payload.get("preedit"))
    committed_context = _string(response.get("committedContext") or request_payload.get("committedContext"))
    frame: dict[str, object] = {
        "schemaVersion": "rag-ime.prediction-frame.v1",
        "recordedAtMs": now_ms(),
        "sessionId": _string(response.get("sessionId")),
        "requestSeq": _bounded_int(response.get("requestSeq"), default=0, minimum=0, maximum=2**63 - 1),
        "frontendRevision": _bounded_int(response.get("frontendRevision"), default=0, minimum=0, maximum=2**63 - 1),
        "selectionEpoch": _bounded_int(response.get("selectionEpoch"), default=0, minimum=0, maximum=2**63 - 1),
        "panelSessionId": _string(response.get("panelSessionId")),
        "input": _redacted_text_snapshot(raw_input, include_raw_text=include_raw_text),
        "preedit": _redacted_text_snapshot(preedit, include_raw_text=include_raw_text),
        "committedContext": _redacted_text_snapshot(committed_context, include_raw_text=include_raw_text),
        "predictionSession": {
            "phase": _string(prediction_session.get("phase")),
            "inputMode": _string(prediction_session.get("inputMode")),
            "hardContextAnchor": _string(prediction_session.get("hardContextAnchor")),
            "applyAnchor": _string(prediction_session.get("applyAnchor")),
            "queryAnchor": _string(prediction_session.get("queryAnchor")),
            "displayAnchor": _string(prediction_session.get("displayAnchor")),
            "stablePanelAction": _string(prediction_session.get("stablePanelAction")),
            "stablePanelReason": _string(prediction_session.get("stablePanelReason")),
            "snapshotId": _string(prediction_session.get("snapshotId") or prediction_session.get("stableSnapshotId")),
            "reusedLastGood": _bool(prediction_session.get("reusedLastGood"), default=False),
            "shouldClearPredictionPanel": _bool(prediction_session.get("shouldClearPredictionPanel"), default=False),
        },
        "ragLane": _prediction_lane_summary(rag_lane),
        "modelLane": _prediction_lane_summary(model_lane),
        "display": {
            "visibleCandidateCount": len(display_candidates),
            "sourceCounts": _display_payload_source_counts(display_candidates),
            "statusRowCount": sum(
                1
                for item in display_candidates
                if isinstance(item, dict) and _string(item.get("sourceType")) == "status"
            ),
            "candidates": [
                _prediction_candidate_summary(item, include_raw_text=include_raw_text)
                for item in display_candidates[:10]
                if isinstance(item, dict)
            ],
        },
        "cache": response.get("cache") if isinstance(response.get("cache"), dict) else {},
        "dropReasons": _prediction_drop_reasons(rag_lane=rag_lane, model_lane=model_lane, trace_events=trace_events),
        "traceEvents": _prediction_trace_event_summaries(trace_events),
    }
    return frame


def _redacted_text_snapshot(text: str, *, include_raw_text: bool) -> dict[str, object]:
    normalized = compact_whitespace(text)
    payload: dict[str, object] = {
        "length": len(normalized),
        "hash": _sha16_text(normalized) if normalized else "",
    }
    if include_raw_text:
        payload["text"] = normalized
    return payload


def _sha16_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _prediction_lane_summary(lane: dict[str, object]) -> dict[str, object]:
    keep = (
        "called",
        "timedOut",
        "staleDropped",
        "staleDropReason",
        "waitingForLatest",
        "skippedReason",
        "predictionCount",
        "suggestionCount",
        "elapsedMs",
        "latencyBudgetMs",
        "activeGeneration",
        "providerName",
        "candidateMode",
    )
    return {key: lane.get(key) for key in keep if key in lane and lane.get(key) not in ("", None)}


def _prediction_candidate_summary(candidate: dict[str, object], *, include_raw_text: bool) -> dict[str, object]:
    summary: dict[str, object] = {
        "sourceType": _string(candidate.get("sourceType")),
        "displayLane": _string(candidate.get("displayLane")),
        "displayLayout": _string(candidate.get("displayLayout")),
        "selectionKey": _string(candidate.get("selectionKey")),
        "candidateOrdinal": _bounded_int(candidate.get("candidateOrdinal"), default=0, minimum=0, maximum=100),
        "selectionAction": _string(candidate.get("selectionAction")),
        "badge": _string(candidate.get("badge")),
        "colorToken": _string(candidate.get("colorToken")),
    }
    if include_raw_text:
        summary["text"] = _string(candidate.get("text"))
        summary["insertText"] = _string(candidate.get("insertText"))
    else:
        summary["text"] = _redacted_text_snapshot(_string(candidate.get("text")), include_raw_text=False)
    return {key: value for key, value in summary.items() if value not in ("", None)}


def _display_payload_source_counts(candidates: list[object]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in candidates:
        if not isinstance(item, dict):
            continue
        source = _string(item.get("sourceType")) or "unknown"
        counts[source] = counts.get(source, 0) + 1
    return counts


def _prediction_drop_reasons(
    *,
    rag_lane: dict[str, object],
    model_lane: dict[str, object],
    trace_events: list[object],
) -> list[str]:
    reasons: list[str] = []
    for lane in (rag_lane, model_lane):
        reason = _string(lane.get("staleDropReason") or lane.get("dropReason") or lane.get("skippedReason"))
        if reason and reason not in reasons:
            reasons.append(reason)
    for event in trace_events:
        if not isinstance(event, dict):
            continue
        fields = event.get("fields") if isinstance(event.get("fields"), dict) else {}
        reason = _string(fields.get("reason") or fields.get("staleDropReason") or fields.get("dropReason"))
        if reason and reason not in reasons:
            reasons.append(reason)
    return reasons


def _prediction_trace_event_summaries(trace_events: list[object]) -> list[dict[str, object]]:
    summaries: list[dict[str, object]] = []
    for event in trace_events[-16:]:
        if not isinstance(event, dict):
            continue
        fields = event.get("fields") if isinstance(event.get("fields"), dict) else {}
        summaries.append(
            {
                key: value
                for key, value in {
                    "event": _string(event.get("event")),
                    "action": _string(fields.get("action")),
                    "reason": _string(fields.get("reason")),
                    "snapshotId": _string(fields.get("snapshotId")),
                    "visibleCandidateCount": fields.get("visibleCandidateCount"),
                    "sourceSummary": fields.get("sourceSummary"),
                    "staleDropReason": _string(fields.get("staleDropReason")),
                }.items()
                if value not in ("", None)
            }
        )
    return summaries


def _prediction_drop_stats(frames: list[dict[str, object]]) -> dict[str, object]:
    by_reason: dict[str, int] = {}
    lane_stale_drops = {"rag": 0, "model": 0}
    for frame in frames:
        for reason in frame.get("dropReasons", []) if isinstance(frame.get("dropReasons"), list) else []:
            text = _string(reason)
            if text:
                by_reason[text] = by_reason.get(text, 0) + 1
        rag_lane = frame.get("ragLane") if isinstance(frame.get("ragLane"), dict) else {}
        model_lane = frame.get("modelLane") if isinstance(frame.get("modelLane"), dict) else {}
        if bool(rag_lane.get("staleDropped")):
            lane_stale_drops["rag"] += 1
        if bool(model_lane.get("staleDropped")):
            lane_stale_drops["model"] += 1
    return {
        "byReason": by_reason,
        "laneStaleDrops": lane_stale_drops,
        "totalDropReasons": sum(by_reason.values()),
    }


def _top_score_components(components: dict[object, object], *, limit: int = 5) -> list[dict[str, object]]:
    numeric_components: list[tuple[str, float]] = []
    for key, value in components.items():
        score = _number_or_none(value)
        if score is None or abs(score) <= 0.0005:
            continue
        numeric_components.append((str(key), score))
    numeric_components.sort(key=lambda item: abs(item[1]), reverse=True)
    return [{"name": name, "score": score} for name, score in numeric_components[:limit]]


def _raw_signals_summary(raw_signals: dict[object, object]) -> dict[str, object]:
    keep = (
        "effectiveFrequency",
        "effectiveFrequencyScope",
        "acceptedCount",
        "skippedCount",
        "downrankedCount",
        "pinned",
        "vectorScore",
    )
    return {key: raw_signals[key] for key in keep if key in raw_signals}


def _number_or_none(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _parse_input_source_check_output(output: str) -> dict[str, object]:
    parsed: dict[str, object] = {}
    id_match = re.search(r"\bid=([^\s]+)", output)
    if id_match:
        parsed["id"] = id_match.group(1)
    name_match = re.search(r"\bname=(.*?)\s+enabled=", output)
    if name_match:
        parsed["name"] = name_match.group(1)
    for key, value in re.findall(r"\b(enabled|selectable|selected|hitoolboxEnabled|thirdPartyEnabled)=([^\s]+)", output):
        parsed[key] = value.lower() == "true"
    current_match = re.search(r"\bcurrent=([^\s]+)", output)
    if current_match:
        parsed["current"] = current_match.group(1)
    return parsed


def _input_source_readiness(parsed: dict[str, object], *, ok: bool, typing_ready: bool) -> dict[str, object]:
    enabled = parsed.get("enabled") is True
    selectable = parsed.get("selectable") is True
    hitoolbox_enabled = parsed.get("hitoolboxEnabled") is not False
    third_party_enabled = parsed.get("thirdPartyEnabled") is not False
    current = _string(parsed.get("current"))
    target = _string(parsed.get("id")) or "Squirrel"
    target_name = _string(parsed.get("name")) or _input_source_display_name(target)
    product_name = _input_source_product_name(target_name)
    readiness_checks = [
        {
            "name": "tis-visible",
            "passed": enabled and selectable,
            "enabled": parsed.get("enabled"),
            "selectable": parsed.get("selectable"),
        },
        {
            "name": "third-party-list",
            "passed": hitoolbox_enabled and third_party_enabled,
            "hitoolboxEnabled": parsed.get("hitoolboxEnabled"),
            "thirdPartyEnabled": parsed.get("thirdPartyEnabled"),
        },
        {
            "name": "selected",
            "passed": ok and typing_ready,
            "selected": parsed.get("selected"),
            "current": current,
        },
    ]
    if ok and typing_ready:
        return {
            "readinessState": "ready",
            "readinessMessage": f"{product_name} is the active input source",
            "nextAction": f"start typing with {product_name}",
            "manualAction": "type in a foreground macOS text field",
            "verificationCommand": "scripts/wait_squirrel_typing_ready.sh",
            "readinessChecks": readiness_checks,
        }
    if enabled and selectable and hitoolbox_enabled and third_party_enabled:
        return {
            "readinessState": "switch",
            "readinessMessage": f"{product_name} is installed; switch the menu bar input source",
            "nextAction": f"select {product_name} from the macOS input menu",
            "manualAction": f"macOS input menu -> {target_name}",
            "verificationCommand": "scripts/wait_squirrel_typing_ready.sh",
            "readinessChecks": readiness_checks,
            "expectedInputSourceId": target,
            "currentInputSourceId": current,
        }
    if not enabled or not selectable or not hitoolbox_enabled or not third_party_enabled:
        return {
            "readinessState": "install",
            "readinessMessage": f"{product_name} is not enabled in every macOS input-source list",
            "nextAction": f"add {product_name} in System Settings, then wait for the add gate",
            "manualAction": f"System Settings -> Keyboard -> Input Sources -> Add -> Chinese, Simplified -> {target_name}",
            "helperCommand": "scripts/open_squirrel_input_source_settings.sh --wait",
            "verificationCommand": "scripts/wait_squirrel_input_source_added.sh",
            "readinessChecks": readiness_checks,
            "expectedInputSourceId": target,
            "currentInputSourceId": current,
        }
    return {
        "readinessState": "error" if not ok else "waiting",
        "readinessMessage": "input source state is incomplete",
        "nextAction": "run doctor_squirrel_integration.sh",
        "manualAction": "inspect the input source checker output",
        "verificationCommand": f"scripts/check_macos_input_source.sh {target}",
        "readinessChecks": readiness_checks,
        "expectedInputSourceId": target,
        "currentInputSourceId": current,
    }


def _input_source_display_name(input_source_id: str) -> str:
    if input_source_id.endswith(".Hant"):
        suffix = "Traditional"
    else:
        suffix = "Simplified"
    if "RagIme" in input_source_id or "rag-ime" in input_source_id:
        return f"RAG-IME - {suffix}"
    return f"Squirrel - {suffix}"


def _input_source_product_name(display_name: str) -> str:
    for suffix in (" - Simplified", " - Traditional"):
        if display_name.endswith(suffix):
            return display_name[: -len(suffix)]
    return display_name


def _deepseek_evidence_from_suggestion(suggestion: InputSuggestion) -> dict[str, object]:
    metadata = dict(suggestion.metadata)
    tags = metadata.get("tags")
    return {
        "sourceType": _string(metadata.get("source_type") or "rag"),
        "title": _string(metadata.get("title") or metadata.get("bookTitle")),
        "surfaceHints": [compact_whitespace(suggestion.surface_text)],
        "evidencePreview": compact_whitespace(suggestion.evidence_preview or suggestion.expanded_evidence),
        "confidence": suggestion.confidence,
        "memoryId": _string(metadata.get("memory_id") or suggestion.suggestion_id),
        "sourceEventId": suggestion.source_event_id,
        "tags": [str(tag) for tag in tags[:8]] if isinstance(tags, (list, tuple)) else [],
    }


def _cache_stats_delta(before: object, after: object) -> dict[str, object]:
    if not isinstance(after, dict):
        return {"available": False, "enabled": False}
    before_stats = before if isinstance(before, dict) else {}
    numeric_keys = ("hits", "misses", "inFlightHits", "evictions", "invalidations")
    payload: dict[str, object] = {
        "available": True,
        "enabled": bool(after.get("enabled", True)),
        "before": {
            key: before_stats.get(key)
            for key in ("hits", "misses", "hitRate", "size", "inFlightHits", "evictions", "invalidations")
            if key in before_stats
        },
        "after": {
            key: after.get(key)
            for key in ("hits", "misses", "hitRate", "size", "inFlightHits", "evictions", "invalidations")
            if key in after
        },
    }
    for key in numeric_keys:
        before_value = before_stats.get(key, 0)
        after_value = after.get(key, 0)
        if isinstance(before_value, int) and isinstance(after_value, int):
            payload[f"{key}Delta"] = after_value - before_value
    return payload


def _cache_delta_passed(delta: dict[str, object], expected_warm_hits: int) -> bool | None:
    if not delta.get("available"):
        return None
    if delta.get("enabled") is False:
        return None
    hits_delta = delta.get("hitsDelta")
    if not isinstance(hits_delta, int):
        return None
    return hits_delta >= expected_warm_hits


def _canonical_action(value: str) -> str:
    aliases = {"accepted": "accepted", "accept": "accepted", "skipped": "skipped", "skip": "skipped"}
    action = aliases.get(value, value)
    allowed = {"accepted", "skipped", "pin", "unpin", "downrank", "delete", "hide", "restore"}
    if action not in allowed:
        raise ValueError(f"unsupported actionType: {value}")
    return action
