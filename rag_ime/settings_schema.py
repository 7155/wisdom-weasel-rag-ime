from __future__ import annotations

import copy
import json
from typing import Any, Mapping


DEFAULT_SETTINGS: dict[str, object] = {
    "interaction": {
        "composition": {
            "showPrediction": True,
            "showOnlyRime": False,
            "numberKeys": "select_rime_candidate",
        },
        "postCommit": {
            "enabled": True,
            "showPendingStatus": True,
            "pendingStatusDelayMs": 150,
            "numberKeys": "pass_through",
            "tabAction": "accept_top_prediction",
            "optionNumber": "select_prediction_by_ordinal",
            "escape": "dismiss_prediction",
            "panelTtlMs": 4200,
        },
    },
    "display": {
        "badges": {
            "rime": "词",
            "model": "模",
            "rag": "查",
            "memory": "忆",
            "status": "查忆",
            "raw_english": "input",
        },
        "colors": {
            "rime": "default",
            "model": "blue",
            "rag": "teal",
            "memory": "purple",
            "status": "gray",
            "raw_english": "gray",
        },
        "maxCompositionCandidates": 8,
        "maxPostCommitCandidates": 5,
        "showSourceBadge": True,
        "showDiagnosticsInline": False,
        "statusRowStyle": "compact",
    },
    "rag": {
        "hybrid": {"enabled": True, "budgetMs": 25},
        "lanes": {
            "bm25Raw": True,
            "bm25Tags": True,
            "vectorRaw": True,
            "vectorTagBoost": True,
            "tagMemo": True,
            "timeDailyBook": True,
            "feedback": True,
        },
        "weights": {
            "bm25Raw": 1.0,
            "bm25Tags": 1.15,
            "vectorRaw": 0.95,
            "vectorTagBoost": 1.05,
            "tagMemo": 1.1,
            "timeDailyBook": 0.9,
            "feedback": 1.2,
        },
        "antiEcho": {
            "blockRawHistoryLongCandidate": True,
            "blockCommittedTailEcho": True,
            "blockSelectedTextEcho": True,
        },
    },
    "memory": {
        "rawHistoryRedacted": True,
        "directCandidateDefault": False,
        "retentionDays": 30,
    },
    "models": {
        "hot": "qwen3_06b_ime_hot",
        "main": "",
        "quality": "",
        "activeRag": "local",
        "offlineCleanup": "x1api",
        "embedding": "local-hash",
    },
    "activeRag": {
        "enabled": True,
        "shortcut": "ctrl+enter",
        "capture": {
            "accessibility": True,
            "clipboardFallback": True,
            "manualClipboardFallback": True,
        },
        "defaultIntent": "auto",
        "defaultPlacement": "replace_selection",
        "maxCandidates": 5,
        "latencyBudgetMs": 2500,
        "localOnlyDefault": True,
        "allowRemoteModel": False,
        "sensitiveTextGuard": True,
    },
    "privacy": {
        "traceIncludeText": False,
        "debugIncludeText": False,
        "redactEmails": True,
        "redactPaths": True,
        "redactSecrets": True,
        "blockSensitiveSelectedText": True,
        "allowRemoteModelForActiveRag": False,
        "allowRemoteModelForOfflineCompile": True,
        "retentionDays": 30,
    },
    "diagnostics": {
        "liveTrace": True,
        "dropStats": True,
        "candidateExplain": True,
    },
    "managementSecurity": {
        "requireToken": False,
        "sameOriginOnly": True,
        "postRequiresJson": True,
        "destructiveActionConfirmText": True,
    },
}


SETTINGS_SCHEMA: dict[str, object] = {
    "schemaVersion": "rag-ime.settings-schema.v3",
    "sections": [
        {
            "id": "interaction",
            "label": "Interaction",
            "fields": [
                {"key": "interaction.composition.showPrediction", "type": "boolean", "label": "输入拼音时显示 AI 候选", "default": True},
                {"key": "interaction.composition.showOnlyRime", "type": "boolean", "label": "输入拼音时只显示 Rime 候选", "default": False},
                {"key": "interaction.postCommit.showPendingStatus", "type": "boolean", "label": "Rime 选词后显示查忆状态行", "default": True},
                {"key": "interaction.postCommit.pendingStatusDelayMs", "type": "integer", "label": "状态行延迟", "default": 150},
                {"key": "interaction.postCommit.panelTtlMs", "type": "integer", "label": "预测面板 TTL", "default": 4200},
                {"key": "interaction.postCommit.numberKeys", "type": "enum", "label": "Post-commit 数字键", "options": ["pass_through", "select_prediction"], "default": "pass_through"},
                {"key": "interaction.postCommit.tabAction", "type": "enum", "label": "Tab 行为", "options": ["accept_top_prediction", "rime_default", "disabled"], "default": "accept_top_prediction"},
            ],
        },
        {
            "id": "display",
            "label": "Display",
            "fields": [
                {"key": "display.showSourceBadge", "type": "boolean", "label": "显示来源徽标", "default": True},
                {"key": "display.showDiagnosticsInline", "type": "boolean", "label": "候选行内诊断", "default": False},
                {"key": "display.maxPostCommitCandidates", "type": "integer", "label": "Post-commit 候选数量", "default": 5},
                {"key": "display.badges.model", "type": "string", "label": "模型徽标", "default": "模"},
                {"key": "display.badges.rag", "type": "string", "label": "RAG 徽标", "default": "查"},
                {"key": "display.badges.memory", "type": "string", "label": "记忆徽标", "default": "忆"},
                {"key": "display.badges.status", "type": "string", "label": "状态行徽标", "default": "查忆"},
            ],
        },
        {
            "id": "rag",
            "label": "RAG Core",
            "fields": [
                {"key": "rag.hybrid.enabled", "type": "boolean", "label": "启用 Hybrid RAG", "default": True},
                {"key": "rag.hybrid.budgetMs", "type": "integer", "label": "RAG 预算 ms", "default": 25},
                {"key": "rag.lanes.bm25Raw", "type": "boolean", "label": "BM25 原文", "default": True},
                {"key": "rag.lanes.bm25Tags", "type": "boolean", "label": "BM25 Tags", "default": True},
                {"key": "rag.lanes.vectorRaw", "type": "boolean", "label": "向量召回", "default": True},
                {"key": "rag.lanes.tagMemo", "type": "boolean", "label": "TagMemo", "default": True},
                {"key": "rag.lanes.timeDailyBook", "type": "boolean", "label": "Time/Daily Book", "default": True},
            ],
        },
        {
            "id": "models",
            "label": "Models",
            "fields": [
                {"key": "models.hot", "type": "string", "label": "Hot path model", "default": "qwen3_06b_ime_hot"},
                {"key": "models.activeRag", "type": "string", "label": "Active RAG model", "default": "local"},
                {"key": "models.offlineCleanup", "type": "string", "label": "Offline cleanup model", "default": "x1api"},
            ],
        },
        {
            "id": "activeRag",
            "label": "Active RAG",
            "fields": [
                {"key": "activeRag.enabled", "type": "boolean", "label": "启用 Active RAG", "default": True},
                {"key": "activeRag.shortcut", "type": "string", "label": "快捷键", "default": "ctrl+enter"},
                {"key": "activeRag.capture.accessibility", "type": "boolean", "label": "优先读取系统选区", "default": True},
                {"key": "activeRag.capture.clipboardFallback", "type": "boolean", "label": "显式触发允许剪贴板 fallback", "default": True},
                {"key": "activeRag.capture.manualClipboardFallback", "type": "boolean", "label": "允许手动剪贴板兜底", "default": True},
                {"key": "activeRag.defaultPlacement", "type": "enum", "label": "插入方式", "options": ["replace_selection", "insert_after_selection", "show_only"], "default": "replace_selection"},
                {"key": "activeRag.allowRemoteModel", "type": "boolean", "label": "允许远程模型", "default": False},
            ],
        },
        {
            "id": "privacy",
            "label": "Privacy",
            "fields": [
                {"key": "privacy.debugIncludeText", "type": "boolean", "label": "管理页显示原文", "default": False},
                {"key": "privacy.traceIncludeText", "type": "boolean", "label": "trace 包含原文", "default": False},
                {"key": "privacy.allowRemoteModelForActiveRag", "type": "boolean", "label": "Active RAG 可用远程模型", "default": False},
                {"key": "managementSecurity.requireToken", "type": "boolean", "label": "POST 需要管理 token", "default": False},
            ],
        },
    ],
}


SENSITIVE_SETTING_SUFFIXES = ("apiKey", "api_key", "token", "secret", "password")


def default_settings() -> dict[str, object]:
    return copy.deepcopy(DEFAULT_SETTINGS)


def settings_schema() -> dict[str, object]:
    return copy.deepcopy(SETTINGS_SCHEMA)


def deep_merge_settings(base: Mapping[str, object], updates: Mapping[str, object]) -> dict[str, object]:
    result = copy.deepcopy(dict(base))
    for key, value in updates.items():
        if isinstance(value, Mapping) and isinstance(result.get(key), Mapping):
            result[key] = deep_merge_settings(result[key], value)  # type: ignore[arg-type]
        else:
            result[key] = copy.deepcopy(value)
    return result


def flatten_settings(value: Mapping[str, object], prefix: str = "") -> dict[str, object]:
    result: dict[str, object] = {}
    for key, item in value.items():
        full_key = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(item, Mapping):
            result.update(flatten_settings(item, full_key))
        else:
            result[full_key] = item
    return result


def unflatten_settings(value: Mapping[str, object]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, item in value.items():
        parts = str(key).split(".")
        cursor = result
        for part in parts[:-1]:
            existing = cursor.get(part)
            if not isinstance(existing, dict):
                cursor[part] = {}
            cursor = cursor[part]  # type: ignore[assignment]
        cursor[parts[-1]] = item
    return result


def section_defaults(section: str) -> dict[str, object]:
    value = DEFAULT_SETTINGS.get(section)
    return copy.deepcopy(value) if isinstance(value, dict) else {}


def redact_settings(settings: Mapping[str, object]) -> dict[str, object]:
    redacted = copy.deepcopy(dict(settings))
    flat = flatten_settings(redacted)
    for key in list(flat):
        lowered = key.lower()
        if any(lowered.endswith(suffix.lower()) for suffix in SENSITIVE_SETTING_SUFFIXES):
            flat[key] = "<redacted>"
    return unflatten_settings(flat)


def stable_settings_hash(settings: Mapping[str, object]) -> str:
    body = json.dumps(settings, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    import hashlib

    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]
