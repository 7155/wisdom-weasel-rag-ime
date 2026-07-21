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
            "idleTriggerMs": 220,
            "minDeltaChars": 2,
            "maxCallsPer10s": 6,
            "cooldownMs": 1500,
            "showPendingStatus": False,
            "pendingStatusDelayMs": 600,
            "numberKeys": "pass_through",
            "tabAction": "accept_top_prediction",
            "optionNumber": "select_prediction_by_ordinal",
            "escape": "dismiss_prediction",
            "panelTtlMs": 5000,
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
        "archiveInactiveDays": 60,
        "timeDecay": {
            "temporaryHalfLifeDays": 14,
            "projectHalfLifeDays": 120,
            "topicBookHalfLifeDays": 180,
            "stablePreferenceHalfLifeDays": 365,
        },
        "automaticOrganization": {
            "enabled": True,
            "model": "deepseek-v4-flash",
            "runsPerDay": 2,
            "includeAgentDialogue": True,
        },
        "dreaming": {
            "enabled": True,
            "model": "deepseek-v4-flash",
            "runsPerDay": 2,
        },
        "recall": {
            "detailLevel": "compact",
            "timelineEnabled": True,
            "timelineMaxItems": 2,
        },
    },
    "context": {
        "recentInputBaseline": 20,
        "recentInputMaximum": 80,
        "tokenBudget": 4096,
        "reservedOutputTokens": 1024,
        "temporalRecall": True,
    },
    "planning": {
        "enabled": True,
        "injectIntoContext": True,
        "detectExplicitCompletion": True,
    },
    "agent": {
        "pi": {
            "enabled": False,
            "startup": "lazy",
            "idleTimeoutSeconds": 900,
            "resumeLastSession": True,
            "defaultRoleId": "companion-future-v1",
            "toolProfile": "control-center-v1",
            "coordinatorEnabled": False,
        },
    },
    "voice": {
        "provider": "native_streaming",
        "hotkey": "middle_mouse",
        "hotwordsEnabled": False,
        "hotwords": [],
    },
    "models": {
        "hot": "minimind_ime_v2",
        "main": "",
        "quality": "",
        "activeRag": "deepseek-v4",
        "offlineCleanup": "deepseek-v4",
        "embedding": "local-hash",
    },
    "activeRag": {
        "enabled": True,
        "quickModel": "deepseek/deepseek-v4-flash",
        "quickThinkingLevel": "off",
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
        "allowRemoteModel": True,
        "sensitiveTextGuard": True,
    },
    "knowledgeLibrary": {
        "parser": {
            "mineru": {
                "enabled": False,
                "port": 30001,
            },
        },
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
        "allowRemoteModelForActiveRag": True,
        "allowRemoteModelForOfflineCompile": True,
        "retentionDays": 30,
    },
    "diagnostics": {
        "liveTrace": False,
        "dropStats": False,
        "candidateExplain": False,
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
                {"key": "interaction.postCommit.showPendingStatus", "type": "boolean", "label": "预测开始时立即显示反馈", "default": False},
                {"key": "interaction.postCommit.enabled", "type": "boolean", "label": "启用提交后预测", "default": True},
                {"key": "interaction.postCommit.idleTriggerMs", "type": "integer", "label": "停顿触发时间", "default": 220},
                {"key": "interaction.postCommit.minDeltaChars", "type": "integer", "label": "最少新增字符数", "default": 2},
                {"key": "interaction.postCommit.maxCallsPer10s", "type": "integer", "label": "10 秒最大模型调用", "default": 6},
                {"key": "interaction.postCommit.cooldownMs", "type": "integer", "label": "空结果冷却", "default": 1500},
                {"key": "interaction.postCommit.pendingStatusDelayMs", "type": "integer", "label": "状态行延迟", "default": 600},
                {"key": "interaction.postCommit.panelTtlMs", "type": "integer", "label": "预测面板 TTL", "default": 5000},
                {"key": "interaction.postCommit.numberKeys", "type": "enum", "label": "Post-commit 数字键", "options": ["pass_through", "select_prediction"], "default": "pass_through"},
                {"key": "interaction.postCommit.tabAction", "type": "enum", "label": "Tab 行为", "options": ["accept_top_prediction", "rime_default", "disabled"], "default": "accept_top_prediction"},
            ],
        },
        {
            "id": "display",
            "label": "Display",
            "fields": [
                {"key": "display.showSourceBadge", "type": "boolean", "label": "显示来源图标", "default": True},
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
                {"key": "rag.lanes.bm25Raw", "type": "boolean", "label": "原文 BM25（SQLite FTS5）", "default": True},
                {"key": "rag.lanes.bm25Tags", "type": "boolean", "label": "标签 BM25（SQLite FTS5）", "default": True},
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
                {"key": "models.activeRag", "type": "string", "label": "显式生成模型", "default": "deepseek-v4", "expert": True},
                {"key": "models.offlineCleanup", "type": "string", "label": "离线整理模型", "default": "deepseek-v4"},
            ],
        },
        {
            "id": "activeRag",
            "label": "Active RAG",
            "fields": [
                {"key": "activeRag.enabled", "type": "boolean", "label": "启用 Active RAG", "default": True},
                {
                    "key": "activeRag.quickModel",
                    "type": "pi-model",
                    "label": "闪电生成模型",
                    "default": "deepseek/deepseek-v4-flash",
                },
                {
                    "key": "activeRag.quickThinkingLevel",
                    "type": "pi-thinking",
                    "label": "闪电生成思考",
                    "default": "off",
                    "modelKey": "activeRag.quickModel",
                    "options": ["off", "minimal", "low", "medium", "high", "xhigh", "max"],
                },
                {"key": "activeRag.shortcut", "type": "shortcut", "label": "快捷键", "default": "ctrl+."},
                {"key": "activeRag.capture.accessibility", "type": "boolean", "label": "优先读取系统选区", "default": True},
                {"key": "activeRag.capture.clipboardFallback", "type": "boolean", "label": "显式触发允许剪贴板 fallback", "default": True},
                {"key": "activeRag.capture.manualClipboardFallback", "type": "boolean", "label": "允许手动剪贴板兜底", "default": True},
                {"key": "activeRag.defaultPlacement", "type": "enum", "label": "插入方式", "options": ["replace_selection", "insert_after_selection", "show_only"], "default": "replace_selection"},
                {"key": "activeRag.maxCandidates", "type": "integer", "label": "生成候选数量", "default": 1},
                {"key": "activeRag.latencyBudgetMs", "type": "integer", "label": "生成等待毫秒", "default": 15000},
                {"key": "activeRag.localOnlyDefault", "type": "boolean", "label": "预览默认仅使用本地 RAG", "default": True},
                {"key": "activeRag.allowRemoteModel", "type": "boolean", "label": "启用高质量生成", "default": True},
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
                {"key": "memory.archiveInactiveDays", "type": "integer", "label": "主题书闲置归档天数", "default": 60},
                {"key": "memory.timeDecay.temporaryHalfLifeDays", "type": "integer", "label": "临时事项衰减半衰期", "default": 14},
                {"key": "memory.timeDecay.projectHalfLifeDays", "type": "integer", "label": "项目事实衰减半衰期", "default": 120},
                {"key": "memory.timeDecay.topicBookHalfLifeDays", "type": "integer", "label": "主题书衰减半衰期", "default": 180},
                {"key": "memory.timeDecay.stablePreferenceHalfLifeDays", "type": "integer", "label": "稳定偏好衰减半衰期", "default": 365},
                {"key": "memory.automaticOrganization.enabled", "type": "boolean", "label": "自动整理", "default": True},
                {"key": "memory.automaticOrganization.model", "type": "string", "label": "自动整理模型", "default": "deepseek-v4-flash"},
                {"key": "memory.automaticOrganization.runsPerDay", "type": "integer", "label": "每天自动整理次数", "default": 2},
                {"key": "memory.automaticOrganization.includeAgentDialogue", "type": "boolean", "label": "整理 Agent 对话摘要", "default": True},
                {"key": "memory.dreaming.enabled", "type": "boolean", "label": "记忆做梦", "default": True},
                {"key": "memory.dreaming.model", "type": "string", "label": "做梦模型", "default": "deepseek-v4-flash"},
                {"key": "memory.dreaming.runsPerDay", "type": "integer", "label": "每天做梦次数", "default": 2},
                {"key": "memory.recall.detailLevel", "type": "enum", "label": "召回详细程度", "options": ["compact", "balanced", "detailed"], "default": "compact"},
                {"key": "memory.recall.timelineEnabled", "type": "boolean", "label": "按需召回时间线", "default": True},
                {"key": "memory.recall.timelineMaxItems", "type": "integer", "label": "时间线最多召回条数", "default": 2},
            ],
        },
        {
            "id": "knowledgeLibrary",
            "label": "文档知识库",
            "fields": [
                {
                    "key": "knowledgeLibrary.parser.mineru.enabled",
                    "type": "boolean",
                    "label": "启用本机 MinerU",
                    "default": False,
                },
                {
                    "key": "knowledgeLibrary.parser.mineru.port",
                    "type": "integer",
                    "label": "MinerU 本机端口",
                    "default": 30001,
                },
            ],
        },
        {
            "id": "context",
            "label": "上下文",
            "fields": [
                {"key": "context.recentInputBaseline", "type": "integer", "label": "最近完整输入基线", "default": 20},
                {"key": "context.recentInputMaximum", "type": "integer", "label": "最近完整输入上限", "default": 80},
                {"key": "context.tokenBudget", "type": "integer", "label": "上下文 token 预算", "default": 4096},
                {"key": "context.reservedOutputTokens", "type": "integer", "label": "预留输出 token", "default": 1024},
                {"key": "context.temporalRecall", "type": "boolean", "label": "识别昨天、上周等时间表达", "default": True},
            ],
        },
        {
            "id": "planning",
            "label": "任务与规划",
            "fields": [
                {"key": "planning.enabled", "type": "boolean", "label": "启用规划与任务", "default": True},
                {"key": "planning.injectIntoContext", "type": "boolean", "label": "将今日计划注入上下文", "default": True},
                {"key": "planning.detectExplicitCompletion", "type": "boolean", "label": "从明确表达识别任务完成", "default": True},
            ],
        },
        {
            "id": "agent",
            "label": "Agent 运行时",
            "fields": [
                {"key": "agent.pi.enabled", "type": "boolean", "label": "连接 Pi", "default": False},
                {"key": "agent.pi.idleTimeoutSeconds", "type": "integer", "label": "空闲退出时间", "default": 900},
                {"key": "agent.pi.resumeLastSession", "type": "boolean", "label": "恢复上次对话", "default": True},
            ],
        },
        {
            "id": "voice",
            "label": "语音输入",
            "fields": [
                {"key": "voice.provider", "type": "enum", "label": "语音服务", "options": ["native_streaming", "realtime_websocket", "http_transcription"], "default": "native_streaming"},
                {"key": "voice.hotkey", "type": "enum", "label": "按住说话", "options": ["middle_mouse", "right_option", "option_space"], "default": "middle_mouse"},
                {"key": "voice.hotwordsEnabled", "type": "boolean", "label": "启用语音热词", "default": False},
                {"key": "voice.hotwords", "type": "string-list", "label": "语音热词", "default": []},
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
                {"key": "privacy.allowRemoteModelForActiveRag", "type": "boolean", "label": "显式生成可使用联网模型", "default": True},
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
    "display.badges.model": {"expert": True},
    "display.badges.rag": {"expert": True},
    "display.badges.memory": {"expert": True},
    "display.badges.status": {"expert": True},
    "display.badges.action": {"expert": True},
    "activeRag.shortcut": {"description": "显式生成快捷键", "applyMode": "restart_input_method", "restartComponent": "squirrel"},
    "activeRag.quickModel": {"description": "闪电按钮每次从 Pi 实时目录校验并调用的单次回复模型"},
    "activeRag.quickThinkingLevel": {"description": "闪电按钮使用模型支持的思考档；关闭思考可降低首字延迟，且不创建会话、不加载工具"},
    "activeRag.latencyBudgetMs": {"description": "显式多段生成的最长等待时间", "min": 1000, "max": 300000, "step": 1000, "unit": "ms"},
    "activeRag.allowRemoteModel": {"description": "只允许显式 Active RAG 使用远程模型", "risk": "sensitive", "validation": {"confirmText": "ALLOW REMOTE MODEL"}},
    "knowledgeLibrary.parser.mineru.enabled": {
        "description": "只连接本机 loopback MinerU 解析服务；不会启动命令或使用云端 API",
        "applyMode": "restart_knowledge_worker",
        "restartComponent": "knowledge-worker",
    },
    "knowledgeLibrary.parser.mineru.port": {
        "description": "MinerU loopback HTTP 端口，主机和路径由服务端固定",
        "min": 1024,
        "max": 65535,
        "unit": "端口",
        "applyMode": "restart_knowledge_worker",
        "restartComponent": "knowledge-worker",
    },
    "agent.pi.enabled": {"description": "按需启动受管理的 Pi RPC，不影响普通输入路径"},
    "agent.pi.idleTimeoutSeconds": {"description": "Pi 无活动后自动退出的等待时间", "min": 0, "max": 86400, "step": 60, "unit": "秒"},
    "voice.provider": {"description": "选择语音代理下一次连接使用的识别服务", "applyMode": "next_voice_session", "restartComponent": "voice"},
    "voice.hotkey": {"description": "选择全局按住说话快捷键", "applyMode": "next_voice_session", "restartComponent": "voice"},
    "voice.hotwordsEnabled": {"description": "仅在豆包/火山原生流式识别请求中发送已确认的热词", "applyMode": "next_voice_session", "restartComponent": "voice"},
    "voice.hotwords": {"description": "每行一个中英文或技术词，最多 32 个，每个 2 至 9 个字符", "applyMode": "next_voice_session", "restartComponent": "voice"},
    "pinyin.rimeManagedPatch": {"description": "写入受管理的 Rime 模糊音 patch", "applyMode": "redeploy_rime", "restartComponent": "rime"},
    "pinyin.fuzzyProfile": {"applyMode": "redeploy_rime", "restartComponent": "rime"},
    "models.hot": {"applyMode": "restart_predictor", "restartComponent": "predictor"},
    "models.activeRag": {"applyMode": "restart_sidecar", "restartComponent": "sidecar"},
    "models.offlineCleanup": {"applyMode": "restart_sidecar", "restartComponent": "sidecar", "expert": True},
    "privacy.traceIncludeText": {"risk": "sensitive", "expert": True},
    "privacy.debugIncludeText": {"risk": "sensitive", "expert": True},
    "managementSecurity.requireToken": {"applyMode": "restart_sidecar", "restartComponent": "sidecar", "expert": True},
    "memory.archiveInactiveDays": {"min": 7, "max": 3650, "unit": "天"},
    "memory.timeDecay.temporaryHalfLifeDays": {"min": 1, "max": 365, "unit": "天", "expert": True},
    "memory.timeDecay.projectHalfLifeDays": {"min": 7, "max": 1825, "unit": "天", "expert": True},
    "memory.timeDecay.topicBookHalfLifeDays": {"min": 7, "max": 3650, "unit": "天", "expert": True},
    "memory.timeDecay.stablePreferenceHalfLifeDays": {"min": 30, "max": 3650, "unit": "天", "expert": True},
    "memory.automaticOrganization.enabled": {
        "description": "把新的用户最终输入、成功回执和压缩后的 Agent 对话异步编译为 Atom 与 Topic Book；关闭后仍保留现有记忆",
        "applyMode": "next_maintenance_run",
    },
    "memory.automaticOrganization.model": {
        "description": "下一次自动整理使用的模型，不影响输入法热路径",
        "applyMode": "next_maintenance_run",
        "validation": "必须是以 deepseek-v4 开头的模型 ID",
    },
    "memory.automaticOrganization.runsPerDay": {
        "description": "后台按此频率判断新来源并自动应用治理后的低风险记忆变更",
        "applyMode": "next_maintenance_run",
        "min": 1,
        "max": 6,
        "unit": "次/天",
    },
    "memory.automaticOrganization.includeAgentDialogue": {
        "description": "只传入最新会话摘要和摘要后的短尾窗，不把完整原始对话送给整理模型",
        "applyMode": "next_maintenance_run",
    },
    "memory.dreaming.enabled": {
        "description": "周期性跨 Session 压缩近期工作、关系和角色连续性；关闭后不会删除已生成产物",
        "applyMode": "next_maintenance_run",
    },
    "memory.dreaming.model": {
        "description": "下一次记忆做梦使用的模型，不参与当前问题的同步回答",
        "applyMode": "next_maintenance_run",
        "validation": "必须是以 deepseek-v4 开头的模型 ID",
    },
    "memory.dreaming.runsPerDay": {
        "description": "后台做梦的逻辑频率；系统会轻量轮询，只有到期才调用模型",
        "applyMode": "next_maintenance_run",
        "min": 1,
        "max": 6,
        "unit": "次/天",
    },
    "memory.recall.detailLevel": {
        "description": "compact 只注入主题摘要和最相关 Atom；balanced 与 detailed 逐步放宽片段预算",
        "applyMode": "next_request",
    },
    "memory.recall.timelineEnabled": {
        "description": "仅在统一 TimelineIntent 判定命中明确日期、相对时间或时间线表达时开放 Timeline 通道",
        "applyMode": "next_request",
    },
    "memory.recall.timelineMaxItems": {
        "description": "一次问题最多注入的独立 Timeline 片段数量",
        "applyMode": "next_request",
        "min": 1,
        "max": 4,
        "unit": "条",
    },
    "context.recentInputBaseline": {"min": 10, "max": 80, "unit": "条"},
    "context.recentInputMaximum": {"min": 20, "max": 200, "unit": "条"},
    "context.tokenBudget": {"min": 2048, "max": 32768, "step": 512, "unit": "token"},
    "context.reservedOutputTokens": {"min": 256, "max": 8192, "step": 256, "unit": "token"},
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
