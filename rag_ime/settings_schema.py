from __future__ import annotations

import copy
import json
from typing import Any, Mapping


DEFAULT_SETTINGS: dict[str, object] = {
    "interaction": {
        "composition": {
            "showPrediction": False,
            "showOnlyRime": True,
            "numberKeys": "select_rime_candidate",
        },
        "postCommit": {
            "enabled": True,
            "idleTriggerMs": 420,
            "minDeltaChars": 8,
            "maxCallsPer10s": 2,
            "cooldownMs": 2500,
            "showPendingStatus": False,
            "pendingStatusDelayMs": 150,
            "numberKeys": "pass_through",
            "tabAction": "accept_top_prediction",
            "optionNumber": "select_prediction_by_ordinal",
            "escape": "dismiss_prediction",
            "panelTtlMs": 2800,
        },
    },
    "display": {
        "badges": {
            "rime": "词",
            "model": "模",
            "rag": "查",
            "memory": "忆",
            "status": "查忆",
            "action": "生成",
            "raw_english": "input",
        },
        "colors": {
            "rime": "default",
            "model": "blue",
            "rag": "teal",
            "memory": "purple",
            "status": "gray",
            "action": "blue",
            "raw_english": "gray",
        },
        "maxCompositionCandidates": 8,
        "maxPostCommitCandidates": 5,
        "showSourceBadge": True,
        "showDiagnosticsInline": False,
        "statusRowStyle": "compact",
        "candidateFontSize": 14,
        "panelStyle": "compact",
        "fadeAnimation": True,
        "maxWidth": 520,
    },
    "rag": {
        "hybrid": {"enabled": True, "budgetMs": 400},
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
        "enabled": True,
        "rawHistoryRedacted": True,
        "directCandidateDefault": False,
        "retentionDays": 30,
        "shortTermItems": 20,
        "shortTermTtlMinutes": 30,
        "allowProjectFallback": True,
        "allowAppFallback": True,
        "allowGlobalMemory": True,
    },
    "models": {
        "hot": "minimind_ime_v2",
        "main": "",
        "quality": "",
        "activeRag": "local",
        "offlineCleanup": "x1api",
        "embedding": "local-hash",
    },
    "activeRag": {
        "enabled": True,
        "shortcut": "ctrl+.",
        "capture": {
            "accessibility": True,
            "clipboardFallback": True,
            "manualClipboardFallback": True,
        },
        "defaultIntent": "auto",
        "defaultPlacement": "replace_selection",
        "maxCandidates": 1,
        "latencyBudgetMs": 15000,
        "localOnlyDefault": True,
        "allowRemoteModel": False,
        "sensitiveTextGuard": True,
    },
    "pinyin": {
        "fuzzyProfile": "sichuan-mild",
        "rimeManagedPatch": True,
        "rerankUsesFuzzy": True,
        "pairs": {
            "zZh": True,
            "cCh": True,
            "sSh": True,
            "enEng": True,
            "inIng": True,
            "ongOn": True,
            "nL": False,
            "fH": False,
        },
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
                {"key": "interaction.composition.showPrediction", "type": "boolean", "label": "输入拼音时显示 AI 候选", "default": False},
                {"key": "interaction.composition.showOnlyRime", "type": "boolean", "label": "输入拼音时只显示 Rime 候选", "default": True},
                {"key": "interaction.postCommit.showPendingStatus", "type": "boolean", "label": "Rime 选词后显示查忆状态行", "default": False},
                {"key": "interaction.postCommit.enabled", "type": "boolean", "label": "启用提交后预测", "default": True},
                {"key": "interaction.postCommit.idleTriggerMs", "type": "integer", "label": "停顿触发时间", "default": 420},
                {"key": "interaction.postCommit.minDeltaChars", "type": "integer", "label": "最少新增字符数", "default": 8},
                {"key": "interaction.postCommit.maxCallsPer10s", "type": "integer", "label": "10 秒最大模型调用", "default": 2},
                {"key": "interaction.postCommit.cooldownMs", "type": "integer", "label": "空结果冷却", "default": 2500},
                {"key": "interaction.postCommit.pendingStatusDelayMs", "type": "integer", "label": "状态行延迟", "default": 150},
                {"key": "interaction.postCommit.panelTtlMs", "type": "integer", "label": "预测面板 TTL", "default": 2800},
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
                {"key": "display.badges.action", "type": "string", "label": "手动生成按钮徽标", "default": "生成"},
                {"key": "display.panelStyle", "type": "enum", "label": "候选界面", "options": ["compact", "expanded"], "default": "compact"},
                {"key": "display.candidateFontSize", "type": "integer", "label": "候选字号", "default": 14},
                {"key": "display.fadeAnimation", "type": "boolean", "label": "淡入动画", "default": True},
                {"key": "display.maxWidth", "type": "integer", "label": "最大宽度", "default": 520},
            ],
        },
        {
            "id": "rag",
            "label": "RAG Core",
            "fields": [
                {"key": "rag.hybrid.enabled", "type": "boolean", "label": "启用 Hybrid RAG", "default": True},
                {"key": "rag.hybrid.budgetMs", "type": "integer", "label": "RAG 预算 ms", "default": 400},
                {"key": "rag.lanes.bm25Raw", "type": "boolean", "label": "原文词法召回（非 FTS5 BM25）", "default": True},
                {"key": "rag.lanes.bm25Tags", "type": "boolean", "label": "标签词法召回（非 FTS5 BM25）", "default": True},
                {"key": "rag.lanes.vectorRaw", "type": "boolean", "label": "向量召回", "default": True},
                {"key": "rag.lanes.tagMemo", "type": "boolean", "label": "TagMemo", "default": True},
                {"key": "rag.lanes.timeDailyBook", "type": "boolean", "label": "Time/Daily Book", "default": True},
            ],
        },
        {
            "id": "models",
            "label": "Models",
            "fields": [
                {"key": "models.hot", "type": "string", "label": "Hot path model", "default": "minimind_ime_v2"},
                {"key": "models.activeRag", "type": "string", "label": "Active RAG model", "default": "local"},
                {"key": "models.offlineCleanup", "type": "string", "label": "Offline cleanup model", "default": "x1api"},
            ],
        },
        {
            "id": "activeRag",
            "label": "Active RAG",
            "fields": [
                {"key": "activeRag.enabled", "type": "boolean", "label": "启用 Active RAG", "default": True},
                {"key": "activeRag.shortcut", "type": "shortcut", "label": "快捷键", "default": "ctrl+."},
                {"key": "activeRag.capture.accessibility", "type": "boolean", "label": "优先读取系统选区", "default": True},
                {"key": "activeRag.capture.clipboardFallback", "type": "boolean", "label": "显式触发允许剪贴板 fallback", "default": True},
                {"key": "activeRag.capture.manualClipboardFallback", "type": "boolean", "label": "允许手动剪贴板兜底", "default": True},
                {"key": "activeRag.defaultPlacement", "type": "enum", "label": "插入方式", "options": ["replace_selection", "insert_after_selection", "show_only"], "default": "replace_selection"},
                {"key": "activeRag.maxCandidates", "type": "integer", "label": "生成候选数量", "default": 1},
                {"key": "activeRag.latencyBudgetMs", "type": "integer", "label": "强模型等待毫秒", "default": 15000},
                {"key": "activeRag.localOnlyDefault", "type": "boolean", "label": "预览默认仅使用本地 RAG", "default": True},
                {"key": "activeRag.allowRemoteModel", "type": "boolean", "label": "允许远程模型", "default": False},
            ],
        },
        {
            "id": "memory",
            "label": "Memory",
            "fields": [
                {"key": "memory.enabled", "type": "boolean", "label": "启用记忆增强", "default": True},
                {"key": "memory.shortTermItems", "type": "integer", "label": "短期记忆条数", "default": 20},
                {"key": "memory.shortTermTtlMinutes", "type": "integer", "label": "短期记忆 TTL", "default": 30},
                {"key": "memory.allowProjectFallback", "type": "boolean", "label": "允许项目级回退", "default": True},
                {"key": "memory.allowAppFallback", "type": "boolean", "label": "允许 App 级回退", "default": True},
                {"key": "memory.allowGlobalMemory", "type": "boolean", "label": "允许全局记忆", "default": True},
            ],
        },
        {
            "id": "pinyin",
            "label": "Pinyin",
            "fields": [
                {"key": "pinyin.fuzzyProfile", "type": "enum", "label": "模糊音配置", "options": ["sichuan-mild", "none"], "default": "sichuan-mild"},
                {"key": "pinyin.rimeManagedPatch", "type": "boolean", "label": "安装 Rime 模糊音 patch", "default": True},
                {"key": "pinyin.rerankUsesFuzzy", "type": "boolean", "label": "RAG/词库重排使用模糊音", "default": True},
                {"key": "pinyin.pairs.zZh", "type": "boolean", "label": "z/zh", "default": True},
                {"key": "pinyin.pairs.cCh", "type": "boolean", "label": "c/ch", "default": True},
                {"key": "pinyin.pairs.sSh", "type": "boolean", "label": "s/sh", "default": True},
                {"key": "pinyin.pairs.enEng", "type": "boolean", "label": "en/eng", "default": True},
                {"key": "pinyin.pairs.inIng", "type": "boolean", "label": "in/ing", "default": True},
                {"key": "pinyin.pairs.ongOn", "type": "boolean", "label": "on/ong（漏 g）", "default": True},
                {"key": "pinyin.pairs.nL", "type": "boolean", "label": "n/l", "default": False},
                {"key": "pinyin.pairs.fH", "type": "boolean", "label": "f/h", "default": False},
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
    schema = copy.deepcopy(SETTINGS_SCHEMA)
    for section in schema["sections"]:  # type: ignore[index]
        for field in section.get("fields", []):
            key = str(field.get("key") or "")
            field_type = str(field.get("type") or "string")
            metadata = _FIELD_METADATA.get(key, {})
            field.setdefault("description", metadata.get("description", str(field.get("label") or key)))
            field.setdefault("applyMode", metadata.get("applyMode", "live"))
            field.setdefault("risk", metadata.get("risk", "safe"))
            field.setdefault("expert", metadata.get("expert", key.startswith("rag.weights.")))
            field.setdefault("min", metadata.get("min"))
            field.setdefault("max", metadata.get("max"))
            field.setdefault("step", metadata.get("step", 1 if field_type == "integer" else None))
            field.setdefault("unit", metadata.get("unit", ""))
            field.setdefault("validation", metadata.get("validation", {}))
            field.setdefault("restartComponent", metadata.get("restartComponent", ""))
    return schema


_FIELD_METADATA: dict[str, dict[str, object]] = {
    "interaction.postCommit.idleTriggerMs": {"description": "连续输入合并后等待多久触发预测", "min": 40, "max": 3000, "step": 20, "unit": "ms"},
    "interaction.postCommit.minDeltaChars": {"description": "相较上次预测至少新增的字符数", "min": 1, "max": 32, "unit": "字符"},
    "interaction.postCommit.maxCallsPer10s": {"description": "限制连续输入期间的模型调用预算", "min": 0, "max": 10, "unit": "次"},
    "interaction.postCommit.cooldownMs": {"description": "空结果后再次调用模型前的等待时间", "min": 0, "max": 10000, "step": 100, "unit": "ms"},
    "interaction.postCommit.panelTtlMs": {"description": "预测候选自动关闭前的保留时间", "min": 500, "max": 15000, "step": 100, "unit": "ms", "applyMode": "restart_input_method", "restartComponent": "squirrel"},
    "display.maxPostCommitCandidates": {"min": 1, "max": 8, "unit": "项", "applyMode": "restart_input_method", "restartComponent": "squirrel"},
    "display.candidateFontSize": {"min": 11, "max": 24, "unit": "pt", "applyMode": "restart_input_method", "restartComponent": "squirrel"},
    "display.maxWidth": {"min": 320, "max": 760, "step": 20, "unit": "pt", "applyMode": "restart_input_method", "restartComponent": "squirrel"},
    "activeRag.shortcut": {"description": "显式生成快捷键", "applyMode": "restart_input_method", "restartComponent": "squirrel"},
    "activeRag.allowRemoteModel": {"description": "只允许显式 Active RAG 使用远程模型", "risk": "sensitive", "validation": {"confirmText": "ALLOW REMOTE MODEL"}},
    "pinyin.rimeManagedPatch": {"description": "写入受管理的 Rime 模糊音 patch", "applyMode": "redeploy_rime", "restartComponent": "rime"},
    "pinyin.fuzzyProfile": {"applyMode": "redeploy_rime", "restartComponent": "rime"},
    "models.hot": {"applyMode": "restart_predictor", "restartComponent": "predictor"},
    "models.activeRag": {"applyMode": "restart_sidecar", "restartComponent": "sidecar"},
    "models.offlineCleanup": {"applyMode": "restart_sidecar", "restartComponent": "sidecar", "expert": True},
    "privacy.traceIncludeText": {"risk": "sensitive", "expert": True},
    "privacy.debugIncludeText": {"risk": "sensitive", "expert": True},
    "managementSecurity.requireToken": {"applyMode": "restart_sidecar", "restartComponent": "sidecar", "expert": True},
}


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
