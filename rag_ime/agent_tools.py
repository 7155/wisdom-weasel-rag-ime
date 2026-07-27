from __future__ import annotations

import hashlib
import json
import os
import re
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from urllib.parse import urlsplit

from .agent_governed_memory_tools import (
    AgentRoleBookToolAdapter,
    MemoryGovernanceProposalStore,
)
from .agent_execution_policy import (
    APPROVAL_AUTO,
    APPROVAL_DENY,
    approval_strategy,
)
from .agent_memory_sources import AgentMemorySourceStore
from .agent_role_book import AgentRoleBookStore
from .agent_tool_artifacts import AgentToolArtifactProjector
from .agent_tool_ids import CONTROL_TOOL_IDS, DANGEROUS_AUTO_APPROVE_TOOL_PROFILE
from .agent_sessions import AgentSessionStore
from .agent_workspace import PreparedWorkspaceCommand, WorkspaceHarness
from .browser_control import BrowserControlService
from .contracts.json_schema import validate_contract
from .desktop_bridge import DesktopBridgeClient
from .management_service import ManagementService, page_request
from .memory_ownership import agent_visible_memory_owners
from .settings_schema import default_settings, flatten_settings, settings_schema


_TOOL_SPECS: tuple[dict[str, object], ...] = (
    {
        "id": "ime_overview",
        "domain": "overview",
        "displayName": "控制中心概览",
        "description": "查看 Agent、模型、记忆、输入和最近活动的整体状态",
        "when": ("用户询问当前 Agent 整体状态、能力或最近活动",),
        "notFor": ("已明确要检查某一个具体子系统",),
        "input": "可选查询与返回条数",
        "output": "Agent、模型、记忆、输入和最近活动概览",
        "does": "汇总控制中心整体状态。",
        "operations": ("status", "capabilities", "recent_activity"),
        "resultPresentation": "status",
    },
    {
        "id": "ime_input",
        "domain": "input",
        "displayName": "输入法",
        "description": "查看输入设置、方案、候选解释，并在原生批准后调整设置或词表",
        "when": ("用户询问或要求调整输入法设置、候选或词表",),
        "notFor": ("语音 Provider、模型或普通文本生成",),
        "input": "操作名及设置变更、候选查询或审批引用",
        "output": "输入设置、候选解释、预览或带回执的变更结果",
        "does": "读取并受控调整输入法能力。",
        "operations": (
            "get_settings",
            "preview_settings",
            "apply_settings",
            "rollback_settings",
            "profile",
            "candidate_explain",
            "lexicon_review",
            "lexicon_apply",
            "lexicon_rollback",
        ),
        "operationRisks": {
            "apply_settings": "R1",
            "rollback_settings": "R1",
            "lexicon_apply": "R1",
            "lexicon_rollback": "R1",
        },
        "resultPresentation": "table",
    },
    {
        "id": "ime_voice",
        "domain": "voice",
        "displayName": "语音输入",
        "description": "查看语音状态，并在原生批准后切换已配置的语音 Provider",
        "when": ("用户询问语音输入状态、隐私或要求切换语音 Provider",),
        "notFor": ("让 Agent 或 Room 朗读、配音或持续输出音频",),
        "input": "操作名、Provider 与可选审批引用",
        "output": "语音输入状态、隐私策略、预览或变更回执",
        "does": "读取并受控配置语音输入。",
        "operations": (
            "status",
            "privacy_policy",
            "provider_status",
            "provider_preview",
            "provider_apply",
            "provider_rollback",
        ),
        "operationRisks": {"provider_apply": "R1", "provider_rollback": "R1"},
        "resultPresentation": "status",
    },
    {
        "id": "ime_planning",
        "domain": "planning",
        "displayName": "规划与任务",
        "description": "查看每日计划，并在原生确认后更新任务状态",
        "when": ("用户要查看每日计划或更新真实任务状态",),
        "notFor": ("维护 Agent 自己的执行清单",),
        "input": "操作名、真实 taskId、日期与动作",
        "output": "计划面板、审批预览或任务变更回执",
        "does": "读取并受控更新用户每日规划。",
        "operations": ("dashboard", "task_action", "undo_task_event"),
        "operationRisks": {"dashboard": "R0", "task_action": "R1", "undo_task_event": "R1"},
        "resultPresentation": "tool_result",
    },
    {
        "id": "agent_schedule",
        "domain": "planning",
        "displayName": "Agent 预约唤醒",
        "description": "查看预约，并在原生批准后安排自己、其他线程或角色于指定时间执行任务",
        "when": ("用户要求定时、延期或重复唤醒某个 Agent 任务",),
        "notFor": ("当前回合立即执行或仅口头提醒",),
        "input": "目标、指令、唤醒时间、时区和重复规则",
        "output": "预约、运行记录或带回执的状态变更",
        "does": "管理可取消、可审计的 Agent 预约。",
        "operations": ("list", "runs", "schedule", "pause", "resume", "cancel", "retry"),
        "operationRisks": {
            "schedule": "R2",
            "pause": "R1",
            "resume": "R2",
            "cancel": "R1",
            "retry": "R2",
        },
        "resultPresentation": "tool_result",
    },
    {
        "id": "ime_memory",
        "domain": "memory",
        "displayName": "个人上下文记忆",
        "description": (
            "查询用户 Evidence、Atom、Book 与已批准 Timeline；"
            "Role Book 请用 agent_role_book。写操作只能经持久提议和原生审批。"
        ),
        "when": ("任务需要查找历史输入、用户事实、偏好或治理记忆变更",),
        "notFor": ("当前对话已经足够或只是流程噪声、失败回执和临时指令",),
        "input": "检索问题、范围、证据引用或待审变更",
        "output": "带证据的记忆结果、草案、审批或回滚状态",
        "does": "检索并治理用户长期上下文记忆。",
        "operations": (
            "catalog",
            "read",
            "recent",
            "trace",
            "capture",
            "maintenance_status",
            "curation_prepare",
            "maintenance_preview",
            "maintenance_review",
            "maintenance_apply",
            "maintenance_rollback",
            "list",
            "search",
            "get",
            "explain",
            "review",
            "remember_preview",
            "correct_preview",
            "forget_preview",
            "remember_apply",
            "correct_apply",
            "forget_apply",
            "governance_rollback",
        ),
        "operationRisks": {
            "maintenance_apply": "R1",
            "maintenance_rollback": "R1",
            "remember_apply": "R1",
            "correct_apply": "R1",
            "forget_apply": "R1",
            "governance_rollback": "R1",
        },
        "resultPresentation": "citation",
    },
    {
        "id": "agent_role_book",
        "domain": "agents",
        "displayName": "Agent 角色书",
        "description": (
            "读取角色书；仅在任务完成且有可复用变化时生成待审草案；"
            "原始聊天只审计，不直接写入；"
            "不能激活草案或修改身份、权限、安全策略与工具白名单"
        ),
        "when": ("任务需要读取固定角色版本或提议可复用的角色变化",),
        "notFor": ("用户长期记忆、权限扩张或把普通聊天写入角色书",),
        "input": "固定 revision、证据与受限角色字段更新",
        "output": "角色书、历史或待审 revision 草案",
        "does": "读取并受控提议 Agent 角色书变化。",
        "operations": ("get", "history", "propose_revision", "review"),
        "resultPresentation": "tool_result",
    },
    {
        "id": "ime_knowledge",
        "domain": "knowledge",
        "displayName": "文档知识库",
        "description": "渐进检索用户明确加载并授权给 Agent 的文档知识库",
        "when": ("问题需要查找用户已授权文档中的事实或原文",),
        "notFor": ("个人历史输入、当前会话内容或未授权文件",),
        "input": "知识库、查询、定位线索或文档引用",
        "output": "带来源的搜索、定位、原文或索引状态",
        "does": "渐进检索已授权文档知识。",
        "operations": ("list_bases", "search", "find", "open", "status"),
        "resultPresentation": "citation",
    },
    {
        "id": "ime_models",
        "domain": "models",
        "displayName": "模型",
        "description": "查看模型与 Provider，并在原生批准后调整不含密钥的 Provider 配置",
        "when": ("用户询问模型、Provider、缓存或要求调整模型配置",),
        "notFor": ("执行普通模型对话或处理 API 密钥",),
        "input": "操作名、模型槽位、Provider、端点或审批引用",
        "output": "模型状态、探测、缓存统计、预览或变更回执",
        "does": "读取并受控配置模型与 Provider。",
        "operations": (
            "status",
            "profiles",
            "probe",
            "cache_stats",
            "profile_preview",
            "profile_apply",
            "profile_rollback",
        ),
        "operationRisks": {"profile_apply": "R1", "profile_rollback": "R1"},
        "resultPresentation": "status",
    },
    {
        "id": "ime_runtime",
        "domain": "runtime",
        "displayName": "诊断与运行时",
        "description": "查看运行组件，并在原生批准后暂停 AI、重启 Sidecar 或预测器、重新部署 Rime",
        "when": ("用户要诊断运行组件或执行受控恢复操作",),
        "notFor": ("一般代码调试或无证据地重启服务",),
        "input": "诊断或恢复操作及可选组件参数",
        "output": "健康状态、诊断证据或带回执的恢复结果",
        "does": "诊断并受控恢复本机 Agent 运行组件。",
        "operations": (
            "health",
            "components",
            "diagnose",
            "pause_ai",
            "resume_ai",
            "restart_sidecar",
            "restart_predictor",
            "redeploy_rime",
        ),
        "operationRisks": {
            "pause_ai": "R1",
            "resume_ai": "R1",
            "restart_sidecar": "R2",
            "restart_predictor": "R2",
            "redeploy_rime": "R2",
        },
        "resultPresentation": "status",
    },
    {
        "id": "ime_configuration",
        "domain": "configuration",
        "displayName": "历史与配置",
        "description": "查看隐私化历史与审计，并通过原生审批导出或恢复不含密钥的便携备份",
        "when": ("用户询问审计历史、导出或恢复便携配置",),
        "notFor": ("查看个人语义记忆或导出密钥",),
        "input": "查询、条数、导出或恢复动作与审批引用",
        "output": "隐私化历史、审计、备份预览或恢复回执",
        "does": "读取审计并受控迁移无密钥配置。",
        "operations": (
            "history",
            "audit",
            "export_preview",
            "export",
            "restore_preview",
            "restore_apply",
        ),
        "operationRisks": {"export": "R1", "restore_apply": "R3"},
        "resultPresentation": "table",
    },
    {
        "id": "ime_agents",
        "domain": "agents",
        "displayName": "多 Agent 协作",
        "description": "管理当前 Session 的有界子 Agent 委派",
        "when": ("任务需要并行研究、实现、复核或停止子 Agent",),
        "notFor": ("单 Agent 可直接完成且无需协作记录",),
        "input": "操作名、受管 Agent、任务、上下文方式或运行 ID",
        "output": "子 Agent 目录、运行状态、产物或取消回执",
        "does": "执行有界、可审计、可取消的子 Agent 委派。",
        "operations": (
            "catalog",
            "delegate",
            "status",
            "artifact",
            "abort",
        ),
        "resultPresentation": "tool_result",
    },
    {
        "id": "ime_browser",
        "domain": "browser",
        "displayName": "浏览器共驾",
        "description": "按需读取已配对浏览器的页面快照，并在用户批准后执行可追踪的网页操作",
        "when": ("任务需要读取或操作已配对浏览器的真实页面",),
        "notFor": ("已有 API 或连接器，或只需一般网页知识",),
        "input": "标签页、快照 ref、URL、文本或滚动参数",
        "output": "页面快照、截图、轨迹或带回执的操作结果",
        "does": "观察并受控操作已配对浏览器。",
        "operations": (
            "status",
            "tabs",
            "snapshot",
            "screenshot",
            "trace",
            "navigate",
            "click",
            "type",
            "scroll",
            "wait",
            "stop",
        ),
        "operationRisks": {
            "navigate": "R1",
            "click": "R1",
            "type": "R1",
            "scroll": "R1",
            "wait": "R1",
            "stop": "R1",
        },
        "resultPresentation": "tool_result",
    },
    {
        "id": "agent_plan",
        "domain": "planning",
        "displayName": "任务执行清单",
        "description": "维护跨回合与压缩保留的 Session 执行清单；它不修改用户的每日规划",
        "when": ("复杂任务需要跨回合维护执行步骤、复核或完成状态",),
        "notFor": ("修改用户每日计划或简单单步任务",),
        "input": "清单项、状态、证据、复核或取消动作",
        "output": "跨回合保留的 Agent 执行清单与状态",
        "does": (
            "维护 Session 内可恢复的任务执行清单；每完成一步就更新状态，"
            "全部验收后先 complete 再最终答复。"
        ),
        "operations": ("list", "update", "submit_review", "complete", "cancel"),
        "resultPresentation": "tool_result",
    },
    {
        "id": "ime_plugins",
        "domain": "agents",
        "displayName": "插件制作与安装",
        "description": "制作、校验并提交插件安装提议；最终应用必须由用户在控制中心批准",
        "when": ("用户要求制作、校验或提议安装当前 Agent 插件",),
        "notFor": ("直接安装、启停、回滚或写入密钥",),
        "input": "插件 manifest、文件、来源路径或验证 token",
        "output": "插件草案、校验结果或待审安装提议",
        "does": "制作并受控提交当前 Agent 插件。",
        "operations": ("list", "create_draft", "validate", "propose_install"),
        "resultPresentation": "tool_result",
    },
    {
        "id": "desktop_semantic",
        "domain": "desktop",
        "displayName": "桌面语义操作",
        "description": "通过 macOS Accessibility 读取目标窗口语义树和差分，并在原生批准后按语义节点操作；不截屏、不做 OCR",
        "when": ("任务必须读取或操作本机 Mac 应用的可访问性语义树",),
        "notFor": ("浏览器有专用工具、需要截图 OCR 或存在直接 API",),
        "input": "应用或窗口目标、语义节点与动作",
        "output": "可访问性树、差分、状态或操作回执",
        "does": "通过可访问性语义读取并受控操作桌面应用。",
        "operations": ("status", "list", "inspect", "act"),
        "operationRisks": {"act": "R2"},
        "resultPresentation": "tool_result",
    },
    {
        "id": "workspace_list",
        "domain": "workspace",
        "displayName": "工作区浏览",
        "description": "浏览当前运行协调 Session 明确授权的工作区",
        "when": ("协调 Session 需要查看授权工作区目录结构",),
        "notFor": ("读取文件内容、搜索文本或访问未授权路径",),
        "input": "相对路径、深度与条数上限",
        "output": "有界目录和文件条目",
        "does": "列出授权工作区结构。",
        "operations": ("list",),
        "sessionModes": ("coordinator",),
        "resultPresentation": "table",
    },
    {
        "id": "workspace_read",
        "domain": "workspace",
        "displayName": "工作区读取",
        "description": "读取授权工作区内的非敏感 UTF-8 文本",
        "when": ("协调 Session 需要读取已知授权文本文件",),
        "notFor": ("二进制、敏感文件、未知位置搜索或未授权路径",),
        "input": "相对文件路径、UTF-8 字节偏移与请求上限",
        "output": "Pi 50 KiB/2000 行预算内的 UTF-8 文本、续读偏移与文件元数据",
        "does": "读取授权工作区文本。",
        "operations": ("read",),
        "sessionModes": ("coordinator",),
        "resultPresentation": "tool_result",
    },
    {
        "id": "workspace_search",
        "domain": "workspace",
        "displayName": "工作区搜索",
        "description": "在授权工作区内有界搜索非敏感文件名与 UTF-8 文本内容",
        "when": ("协调 Session 需要定位文件、符号或文本位置",),
        "notFor": ("已知文件直接读取、互联网搜索或未授权路径",),
        "input": "查询、相对路径、模式、大小写与条数上限",
        "output": "带路径和位置的有界匹配结果",
        "does": "搜索授权工作区文件与文本。",
        "operations": ("search",),
        "sessionModes": ("coordinator",),
        "resultPresentation": "table",
    },
    {
        "id": "workspace_patch",
        "domain": "workspace",
        "displayName": "精确文件修改",
        "description": "预览精确文本替换，并在原生批准和文件哈希复验后原子写入",
        "when": ("协调 Session 需要对授权文本做精确可复验修改",),
        "notFor": ("模糊重写、二进制编辑、未授权路径或无需修改",),
        "input": "路径、旧文本、新文本与预期匹配次数",
        "output": "修改预览、审批状态和原子写入回执",
        "does": "受控执行精确文本替换。",
        "operations": ("apply",),
        "operationRisks": {"apply": "R2"},
        "sessionModes": ("coordinator",),
        "resultPresentation": "tool_result",
    },
    {
        "id": "workspace_shell",
        "domain": "workspace",
        "displayName": "受控命令",
        "description": "经原生批准后，在授权工作区的 macOS 沙箱中运行有界命令",
        "when": ("协调 Session 必须运行构建、测试或诊断命令",),
        "notFor": (
            "已知文本可由 workspace_read 或 workspace_patch 完成",
            "用 apply_patch、heredoc 等 Shell 包装修改文件",
            "用 sleep 或轮询等待其他 Room 成员",
            "命令越过授权边界",
        ),
        "input": "命令、工作目录、超时和网络开关",
        "output": "退出状态、标准输出、错误输出和执行回执",
        "does": "在授权工作区受控运行命令。",
        "operations": ("run",),
        "operationRisks": {"run": "R2"},
        "sessionModes": ("coordinator",),
        "resultPresentation": "terminal",
    },
)
_TOOL_SPEC_BY_ID = {str(item["id"]): item for item in _TOOL_SPECS}

_RUNTIME_TOOL_PARAMETER_SCHEMAS: dict[str, dict[str, object]] = {
    "ime_planning": {
        "type": "object",
        "oneOf": [
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["op"],
                "properties": {
                    "op": {"const": "dashboard"},
                    "date": {
                        "type": "string",
                        "maxLength": 24,
                        "description": "可选计划日期；省略时读取本地今天。",
                    },
                },
            },
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["op", "taskId", "date", "action"],
                "properties": {
                    "op": {"const": "task_action"},
                    "taskId": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 240,
                        "description": "必须原样使用同一日期 dashboard 返回的 tasks[].id，不能根据标题猜测。",
                    },
                    "date": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 24,
                        "description": "必须原样使用 dashboard 返回的 date。",
                    },
                    "action": {
                        "type": "string",
                        "enum": ["complete", "start", "reopen", "cancel"],
                    },
                },
            },
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["op", "eventId"],
                "properties": {
                    "op": {"const": "undo_task_event"},
                    "eventId": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 240,
                        "description": "必须使用已应用 task_action 回执中的 taskEventId。",
                    },
                },
            },
        ],
    },
    "ime_knowledge": {
        "type": "object",
        "oneOf": [
            *[
                {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["op"],
                    "properties": {"op": {"const": operation}},
                }
                for operation in ("list_bases", "status")
            ],
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["op", "kbId", "query"],
                "properties": {
                    "op": {"const": "search"},
                    "kbId": {"type": "string", "minLength": 1, "maxLength": 240},
                    "query": {"type": "string", "minLength": 1, "maxLength": 500},
                    "topK": {"type": "integer", "minimum": 1, "maximum": 12},
                    "searchMode": {
                        "type": "string",
                        "enum": ["hybrid", "lexical", "dense"],
                    },
                    "fileName": {"type": "string", "maxLength": 240},
                },
            },
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["op", "kbId", "fileId", "patterns"],
                "properties": {
                    "op": {"const": "find"},
                    "kbId": {"type": "string", "minLength": 1, "maxLength": 240},
                    "fileId": {"type": "string", "minLength": 1, "maxLength": 240},
                    "patterns": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 10,
                        "items": {"type": "string", "minLength": 1, "maxLength": 240},
                    },
                    "useRegex": {"type": "boolean"},
                    "caseSensitive": {"type": "boolean"},
                    "maxWindows": {"type": "integer", "minimum": 1, "maximum": 20},
                    "windowSize": {"type": "integer", "minimum": 4, "maximum": 120},
                    "offset": {"type": "integer", "minimum": 0, "maximum": 1_000_000},
                },
            },
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["op", "kbId", "fileId"],
                "properties": {
                    "op": {"const": "open"},
                    "kbId": {"type": "string", "minLength": 1, "maxLength": 240},
                    "fileId": {"type": "string", "minLength": 1, "maxLength": 240},
                    "line": {"type": "integer", "minimum": 1, "maximum": 50_000_000},
                    "offset": {"type": "integer", "minimum": 0, "maximum": 50_000_000},
                    "windowSize": {"type": "integer", "minimum": 1, "maximum": 300},
                },
            },
        ],
    },
    "agent_plan": {
        "type": "object",
        "oneOf": [
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["op"],
                "properties": {
                    "op": {"const": "list"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                },
            },
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["op"],
                "anyOf": [
                    {"required": ["title"]},
                    {"required": ["itemId"]},
                ],
                "properties": {
                    "op": {"const": "update"},
                    "itemId": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 160,
                        "description": "更新已有计划项时使用 list 返回的 itemId；创建时可省略。",
                    },
                    "title": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 240,
                        "description": "创建新计划项时必填。",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["pending", "in_progress", "completed"],
                    },
                },
            },
            *[
                {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["op"],
                    "properties": {
                        "op": {"const": operation},
                        "note": {"type": "string", "maxLength": 600},
                    },
                }
                for operation in ("submit_review", "complete", "cancel")
            ],
        ],
    },
    "desktop_semantic": {
        "type": "object",
        "oneOf": [
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["op"],
                "properties": {"op": {"const": "status"}},
            },
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["op"],
                "properties": {
                    "op": {"const": "list"},
                    "includeBackground": {"type": "boolean"},
                },
            },
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["op"],
                "properties": {
                    "op": {"const": "inspect"},
                    "bundleId": {"type": "string", "maxLength": 300},
                    "pid": {"type": "integer", "minimum": 1, "maximum": 2147483647},
                    "query": {"type": "string", "maxLength": 300},
                    "maxNodes": {"type": "integer", "minimum": 1, "maximum": 400},
                    "maxDepth": {"type": "integer", "minimum": 1, "maximum": 12},
                    "sinceSnapshotId": {"type": "string", "maxLength": 200},
                },
            },
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["op", "snapshotId", "revision", "nodeRef", "action"],
                "properties": {
                    "op": {"const": "act"},
                    "snapshotId": {"type": "string", "minLength": 1, "maxLength": 200},
                    "revision": {"type": "integer", "minimum": 1},
                    "nodeRef": {"type": "string", "minLength": 1, "maxLength": 200},
                    "action": {
                        "type": "string",
                        "enum": [
                            "press", "click", "double_click", "right_click", "long_press",
                            "focus", "set_text", "type_text", "key", "increment", "decrement",
                            "show_menu", "scroll"
                        ],
                    },
                    "text": {"type": "string", "maxLength": 8000},
                    "key": {
                        "type": "string",
                        "enum": [
                            "return", "enter", "tab", "escape", "space", "delete",
                            "forward_delete", "left", "right", "up", "down", "home",
                            "end", "page_up", "page_down"
                        ],
                    },
                    "modifiers": {
                        "type": "array",
                        "maxItems": 5,
                        "uniqueItems": True,
                        "items": {
                            "type": "string",
                            "enum": ["command", "option", "control", "shift", "fn"],
                        },
                    },
                    "durationMs": {"type": "integer", "minimum": 100, "maximum": 3000},
                    "scrollDelta": {
                        "type": "integer",
                        "minimum": -20,
                        "maximum": 20,
                        "not": {"const": 0},
                    },
                },
            },
        ],
    },
}

_RUNTIME_TOOL_ARGUMENT_SCHEMAS: dict[str, dict[str, object]] = {
    "query": {"type": "string", "maxLength": 500},
    "limit": {"type": "integer", "minimum": 1, "maximum": 100},
    "changes": {
        "type": "array",
        "minItems": 1,
        "maxItems": 12,
        "items": {
            "type": "object",
            "additionalProperties": False,
            "required": ["key", "value"],
            "properties": {
                "key": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 160,
                    "description": "只能使用 ime_input.get_settings/preview_settings 暴露的 Agent 可管理键。",
                },
                "value": {
                    "oneOf": [
                        {"type": "boolean"},
                        {"type": "integer"},
                        {"type": "string"},
                    ]
                },
            },
        },
    },
    "selectedKeys": {
        "type": "array",
        "minItems": 1,
        "maxItems": 100,
        "items": {"type": "string", "minLength": 1, "maxLength": 300},
    },
    "sourceApprovalId": {
        "type": "string",
        "minLength": 1,
        "maxLength": 240,
        "description": "使用对应已应用回执中的 approvalId。",
    },
    "currentInput": {"type": "string", "maxLength": 240},
    "recentContext": {"type": "string", "maxLength": 800},
    "topK": {"type": "integer", "minimum": 1, "maximum": 12},
    "provider": {"type": "string", "minLength": 1, "maxLength": 80},
    "slot": {"type": "string", "enum": ["instant", "knowledge"]},
    "endpoint": {"type": "string", "minLength": 1, "maxLength": 320},
    "model": {"type": "string", "maxLength": 200},
    "bookId": {"type": "string", "minLength": 1, "maxLength": 240},
    "traceId": {"type": "string", "minLength": 1, "maxLength": 240},
    "runId": {"type": "string", "minLength": 1, "maxLength": 240},
    "proposalId": {"type": "string", "minLength": 1, "maxLength": 240},
    "idempotencyKey": {"type": "string", "minLength": 1, "maxLength": 240},
    "claimKey": {"type": "string", "minLength": 1, "maxLength": 240},
    "revisionId": {"type": "string", "minLength": 1, "maxLength": 240},
    "instruction": {"type": "string", "minLength": 1, "maxLength": 8_000},
    # `text` and `reason` were declared twice in this literal. Python keeps the
    # last binding, so these earlier entries never took effect: the schemas
    # actually in force are the ones defined further down. They are removed so
    # the table states what the runtime really enforces. This is not a schema
    # change -- the emitted argument schemas are byte-identical before and
    # after. The narrower limits these lines appeared to impose (text
    # minLength 1 / maxLength 1200, reason maxLength 400) have never been
    # applied, which is recorded as a separate finding rather than silently
    # "restored" here, because tightening them would change Tool validation.
    "memoryKind": {
        "type": "string",
        "enum": ["fact", "preference", "decision", "commitment", "project_state"],
    },
    "evidenceIds": {
        "type": "array",
        "minItems": 1,
        "maxItems": 16,
        "items": {"type": "string", "minLength": 1, "maxLength": 240},
    },
    "changeSummary": {"type": "string", "maxLength": 400},
    "updates": {
        "type": "object",
        "additionalProperties": False,
        "$defs": {
            "item": {
                "type": "object",
                "additionalProperties": False,
                "required": ["text", "provenance", "evidenceIds"],
                "properties": {
                    "itemId": {"type": "string", "maxLength": 160},
                    "text": {"type": "string", "minLength": 1, "maxLength": 280},
                    "provenance": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["sourceType", "sourceId"],
                        "properties": {
                            "sourceType": {
                                "type": "string",
                                "minLength": 1,
                                "maxLength": 80,
                            },
                            "sourceId": {
                                "type": "string",
                                "minLength": 1,
                                "maxLength": 240,
                            },
                            "observedAtMs": {
                                "type": ["integer", "null"],
                                "minimum": 0,
                            },
                        },
                    },
                    "evidenceIds": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 16,
                        "items": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 240,
                        },
                    },
                },
            }
        },
        "properties": {
            section: {
                "type": "array",
                "maxItems": limit,
                "items": {"$ref": "#/properties/updates/$defs/item"},
            }
            for section, limit in {
                "personality": 6,
                "capabilities": 12,
                "recentWork": 8,
                "lessonsAndLimits": 8,
                "activeCommitments": 8,
            }.items()
        },
    },
    "kind": {
        "type": "string",
        "enum": [
            "apps",
            "books",
            "atoms",
            "timelines",
            "evidence",
            "tags",
            "phrases",
            "groups",
        ],
    },
    "scheduleId": {
        "type": "string",
        "minLength": 1,
        "maxLength": 240,
        "description": "使用 agent_schedule.list 返回的 scheduleId。",
    },
    "title": {"type": "string", "minLength": 1, "maxLength": 240},
    "targetType": {"type": "string", "enum": ["session", "role"]},
    "targetId": {"type": "string", "maxLength": 240},
    "targetSessionId": {"type": "string", "maxLength": 240},
    "targetRoleId": {"type": "string", "maxLength": 120},
    "targetRoleVersion": {"type": "string", "maxLength": 40},
    "planningTaskId": {"type": "string", "maxLength": 240},
    "wakeAtMs": {"type": "integer", "minimum": 1},
    "timezone": {"type": "string", "maxLength": 80},
    "recurrenceKind": {"type": "string", "enum": ["once", "daily", "weekly"]},
    "recurrenceInterval": {"type": "integer", "minimum": 1, "maximum": 30},
    "maxRuns": {"type": "integer", "minimum": 1, "maximum": 100},
    "status": {"type": "string", "maxLength": 40},
    "agent": {
        "type": "string",
        "enum": ["researcher", "planner", "worker", "reviewer", "delegate"],
    },
    "version": {"type": "string", "enum": ["1"]},
    "task": {"type": "string", "minLength": 1, "maxLength": 8_000},
    "tasks": {
        "type": "array",
        "minItems": 1,
        "maxItems": 2,
        "description": "批量委派；也可以改用 agent、version、task 提交单项任务。",
        "items": {
            "type": "object",
            "additionalProperties": False,
            "required": ["agent", "task"],
            "properties": {
                "agent": {
                    "type": "string",
                    "enum": ["researcher", "planner", "worker", "reviewer", "delegate"],
                },
                "version": {"type": "string", "enum": ["1"]},
                "task": {"type": "string", "minLength": 1, "maxLength": 8_000},
            },
        },
    },
    "contextMode": {"type": "string", "enum": ["fresh", "fork"]},
    "wait": {"type": "boolean"},
    "batchId": {"type": "string", "minLength": 1, "maxLength": 240},
    "artifactId": {"type": "string", "minLength": 1, "maxLength": 240},
    "reason": {"type": "string", "minLength": 1, "maxLength": 2_000},
    "draftId": {"type": "string", "minLength": 1, "maxLength": 160},
    "manifest": {"type": "object"},
    "files": {"type": "object"},
    "sourcePath": {"type": "string", "minLength": 1, "maxLength": 1_024},
    "validationToken": {"type": "string", "minLength": 1, "maxLength": 240},
    "enable": {"type": "boolean"},
    "path": {"type": "string", "minLength": 1, "maxLength": 1_024},
    "depth": {"type": "integer", "minimum": 1, "maximum": 3},
    "offset": {"type": "integer", "minimum": 0, "maximum": 50_000_000},
    "mode": {"type": "string", "enum": ["content", "name", "both"]},
    "oldText": {"type": "string", "minLength": 1, "maxLength": 65_536},
    "newText": {"type": "string", "maxLength": 131_072},
    "expectedOccurrences": {"type": "integer", "minimum": 1, "maximum": 100},
    "command": {"type": "string", "minLength": 1, "maxLength": 2_000},
    "cwd": {"type": "string", "maxLength": 1_024},
    "timeoutSeconds": {"type": "integer", "minimum": 1, "maximum": 120},
    "allowNetwork": {"type": "boolean"},
    "action": {"type": "string", "minLength": 1, "maxLength": 120},
    "caseSensitive": {"type": "boolean"},
    "deviceId": {"type": "string", "minLength": 1, "maxLength": 160},
    "tabId": {"type": "integer", "minimum": 1},
    "refId": {"type": "string", "minLength": 1, "maxLength": 160},
    "url": {"type": "string", "minLength": 1, "maxLength": 4_000},
    "text": {"type": "string", "maxLength": 8_000},
    "clear": {"type": "boolean"},
    "direction": {"type": "string", "enum": ["up", "down", "left", "right"]},
    "amount": {"type": "integer", "minimum": 80, "maximum": 2_400},
    "timeoutMs": {"type": "integer", "minimum": 100, "maximum": 20_000},
    "maxChars": {"type": "integer", "minimum": 1_000, "maximum": 80_000},
}

_RUNTIME_TOOL_ARGUMENT_SCHEMA_OVERRIDES: dict[tuple[str, str], dict[str, object]] = {
    ("workspace_list", "path"): {
        "type": "string",
        "maxLength": 1_024,
        "description": "可省略或传空字符串以列出当前授权工作区根目录。",
    },
    ("workspace_list", "limit"): {"type": "integer", "minimum": 1, "maximum": 300},
    ("workspace_read", "limit"): {
        "type": "integer",
        "minimum": 1,
        "maximum": 65_536,
        "description": (
            "请求读取的 UTF-8 字节数；实际模型可见结果仍受 Pi "
            "50 KiB 与 2000 行上限约束，按 nextOffset 续读。"
        ),
    },
    ("ime_memory", "mode"): {
        "type": "string",
        "enum": ["current", "historical", "change"],
        "description": "默认 current；只有显式选择 historical/change 才读取历史或变更。",
    },
    ("workspace_search", "query"): {
        "type": "string",
        "minLength": 1,
        "maxLength": 200,
        "pattern": r"^[^\r\n\u0000]+$",
    },
    ("workspace_search", "path"): {
        "type": "string",
        "maxLength": 1_024,
        "description": "可省略或传空字符串以搜索全部授权工作区。",
    },
}

_RUNTIME_TOOL_ARGUMENTS: dict[str, tuple[str, ...]] = {
    "ime_overview": ("query", "limit"),
    "ime_input": (
        "changes", "selectedKeys", "sourceApprovalId", "query", "currentInput",
        "recentContext", "topK", "limit",
    ),
    "ime_voice": ("provider", "sourceApprovalId"),
    "agent_schedule": (
        "scheduleId", "title", "instruction", "targetType", "targetId",
        "targetSessionId", "targetRoleId", "targetRoleVersion", "planningTaskId",
        "wakeAtMs", "timezone", "recurrenceKind", "recurrenceInterval", "maxRuns",
        "status", "limit",
    ),
    "ime_memory": (
        "query", "limit", "kind", "bookId", "traceId", "runId", "instruction",
        "targetId", "text", "reason", "memoryKind", "evidenceIds", "claimKey",
        "idempotencyKey", "proposalId", "draftId", "mode", "trigger",
        "claim", "sourceId", "captureScope", "basis", "futureUse", "supersedes",
    ),
    "agent_role_book": (
        "revisionId", "draftId", "limit", "updates", "changeSummary",
    ),
    "ime_models": ("slot", "provider", "endpoint", "model", "sourceApprovalId"),
    "ime_configuration": ("query", "limit", "action", "sourceApprovalId"),
    "ime_agents": (
        "agent", "version", "task", "tasks", "contextMode", "wait", "runId", "batchId",
        "artifactId", "limit",
    ),
    "ime_plugins": ("draftId", "manifest", "files", "sourcePath", "validationToken", "enable"),
    "ime_browser": (
        "deviceId", "tabId", "refId", "url", "text", "clear", "direction",
        "amount", "timeoutMs", "maxChars", "limit",
    ),
    "workspace_list": ("path", "depth", "limit"),
    "workspace_read": ("path", "offset", "limit"),
    "workspace_search": ("query", "path", "mode", "caseSensitive", "limit"),
    "workspace_patch": ("path", "oldText", "newText", "expectedOccurrences"),
    "workspace_shell": ("command", "cwd", "timeoutSeconds", "allowNetwork"),
}

_RUNTIME_TOOL_REQUIRED_ARGUMENTS: dict[tuple[str, str], tuple[str, ...]] = {
    ("ime_input", "preview_settings"): ("changes",),
    ("ime_input", "apply_settings"): ("changes",),
    ("ime_input", "rollback_settings"): ("sourceApprovalId",),
    ("ime_input", "candidate_explain"): ("query",),
    ("ime_input", "lexicon_apply"): ("selectedKeys",),
    ("ime_input", "lexicon_rollback"): ("sourceApprovalId",),
    ("ime_voice", "provider_preview"): ("provider",),
    ("ime_voice", "provider_apply"): ("provider",),
    ("ime_voice", "provider_rollback"): ("sourceApprovalId",),
    ("agent_schedule", "runs"): ("scheduleId",),
    ("agent_schedule", "schedule"): ("instruction", "targetType", "wakeAtMs"),
    ("agent_schedule", "pause"): ("scheduleId",),
    ("agent_schedule", "resume"): ("scheduleId",),
    ("agent_schedule", "cancel"): ("scheduleId",),
    ("agent_schedule", "retry"): ("scheduleId",),
    ("ime_memory", "read"): ("bookId",),
    ("ime_memory", "trace"): ("traceId",),
    ("ime_memory", "capture"): (
        "kind",
        "claim",
        "captureScope",
        "basis",
        "futureUse",
    ),
    ("ime_memory", "curation_prepare"): ("trigger",),
    ("ime_memory", "maintenance_preview"): ("trigger",),
    ("ime_memory", "maintenance_review"): ("runId",),
    ("ime_memory", "maintenance_apply"): ("runId",),
    ("ime_memory", "maintenance_rollback"): ("runId",),
    ("ime_memory", "remember_preview"): ("text",),
    ("ime_memory", "correct_preview"): ("targetId", "text"),
    ("ime_memory", "forget_preview"): ("targetId", "reason"),
    ("ime_memory", "remember_apply"): ("proposalId",),
    ("ime_memory", "correct_apply"): ("proposalId",),
    ("ime_memory", "forget_apply"): ("proposalId",),
    ("ime_memory", "governance_rollback"): ("proposalId",),
    ("ime_memory", "explain"): ("targetId",),
    ("ime_memory", "review"): ("draftId",),
    ("agent_role_book", "propose_revision"): ("updates",),
    ("ime_models", "profile_preview"): ("slot",),
    ("ime_models", "profile_apply"): ("slot",),
    ("ime_models", "profile_rollback"): ("sourceApprovalId",),
    ("ime_configuration", "restore_preview"): ("sourceApprovalId",),
    ("ime_configuration", "restore_apply"): ("sourceApprovalId",),
    ("ime_agents", "artifact"): ("artifactId",),
    ("ime_plugins", "create_draft"): ("draftId", "manifest", "files"),
    ("ime_plugins", "validate"): ("sourcePath",),
    ("ime_plugins", "propose_install"): ("validationToken",),
    ("ime_browser", "navigate"): ("url",),
    ("ime_browser", "click"): ("refId",),
    ("ime_browser", "type"): ("refId", "text"),
    ("workspace_read", "read"): ("path",),
    ("workspace_search", "search"): ("query",),
    ("workspace_patch", "apply"): ("path", "oldText", "newText"),
    ("workspace_shell", "run"): ("command",),
}

_RUNTIME_TOOL_REQUIRED_ALTERNATIVES: dict[
    tuple[str, str], tuple[tuple[str, ...], ...]
] = {
    ("ime_models", "profile_preview"): (("provider",), ("endpoint",), ("model",)),
    ("ime_models", "profile_apply"): (("provider",), ("endpoint",), ("model",)),
    ("ime_agents", "delegate"): (("tasks",), ("agent", "task")),
    ("ime_agents", "abort"): (("runId",), ("batchId",)),
    ("agent_role_book", "review"): (("revisionId",), ("draftId",)),
    ("ime_memory", "get"): (("targetId",), ("draftId",)),
}

_RUNTIME_TOOL_USAGE: dict[str, str] = {
    "ime_planning": (
        "调用顺序：先用 dashboard 读取真实 taskId 和 date；再用 task_action 创建审批预览。"
        "不要用任务标题代替 taskId，也不要在审批完成前声称任务已经执行。"
    ),
    "ime_memory": (
        "Session 启动快照只在首轮注入一次。Timeline 不能单独证明稳定事实。"
        "无事实问题/流程噪声/失败回执/重复问句/临时指令 not_for_memory；禁止原样复制长输入。"
        "普通聊天禁 curation_prepare；候选捕获只使用常驻 memory_capture，不从本工具调用 capture。"
        "task_completion/explicit_request/idle_batch 且有事实时才整理；"
    ),
    "ime_browser": (
        "先用 tabs 或 snapshot 获取真实 tabId、snapshotId 与 refId。"
        "页面变化后旧 refId 会失效；执行 navigate、click、type、scroll、wait 或 stop 前需要用户批准。"
    ),
    "agent_role_book": (
        "Role Book 是 Agent 自身画像并随 Session 固定版本注入系统提示词，不是用户记忆。"
        "get 默认读取当前 Session 固定的 revision；history/review 用于检查每日整理产生的草案。"
        "需要补充最近工作、能力、性格或经验教训时，先引用真实 Evidence，"
        "再用 propose_revision 提交 personality/capabilities/recentWork/lessonsAndLimits/activeCommitments。"
        "propose_revision 只保存 draft，不能激活或改变身份、权限、安全策略和工具白名单。"
    ),
}

_RUNTIME_TOOL_PROJECTIONS: dict[str, tuple[dict[str, str], ...]] = {
    "ime_memory": (
        {
            "name": "memory_capture",
            "operation": "capture",
        },
    ),
}

_PLANNING_TARGET_STATUS = {
    "complete": "done",
    "start": "in_progress",
    "reopen": "todo",
    "cancel": "cancelled",
}
_PLANNING_ACTION_LABELS = {
    "complete": "标记为已完成",
    "start": "标记为进行中",
    "reopen": "重新打开",
    "cancel": "取消任务",
}
_PLANNING_STATUS_LABELS = {
    "todo": "待办",
    "in_progress": "进行中",
    "done": "已完成",
    "completed": "已完成",
    "cancelled": "已取消",
}

# Agent writes intentionally cover only ordinary, non-secret input settings.
# Provider, privacy, management-token and Pi-runtime changes remain outside this
# tool until their own preview/restart contracts exist.
_INPUT_SETTING_FIELDS: dict[str, dict[str, object]] = {
    "interaction.postCommit.enabled": {"label": "提交后预测"},
    "interaction.postCommit.showPendingStatus": {"label": "立即显示处理状态"},
    "interaction.postCommit.idleTriggerMs": {"label": "停顿触发时间", "min": 100, "max": 5_000},
    "interaction.postCommit.minDeltaChars": {"label": "最少新增字数", "min": 1, "max": 100},
    "interaction.postCommit.maxCallsPer10s": {"label": "10 秒最大调用数", "min": 1, "max": 20},
    "interaction.postCommit.cooldownMs": {"label": "空结果冷却时间", "min": 0, "max": 30_000},
    "interaction.postCommit.pendingStatusDelayMs": {"label": "状态显示延迟", "min": 0, "max": 5_000},
    "interaction.postCommit.panelTtlMs": {"label": "预测面板停留时间", "min": 1_000, "max": 60_000},
    "interaction.postCommit.tabAction": {"label": "Tab 行为"},
    "display.showSourceBadge": {"label": "显示来源标记"},
    "display.showDiagnosticsInline": {"label": "候选行内诊断"},
    "display.maxPostCommitCandidates": {"label": "预测候选数量", "min": 1, "max": 10},
    "display.panelStyle": {"label": "候选面板样式"},
    "display.candidateFontSize": {"label": "候选字号", "min": 10, "max": 28},
    "display.fadeAnimation": {"label": "候选动画"},
    "display.maxWidth": {"label": "候选面板宽度", "min": 280, "max": 1_200},
    "activeRag.enabled": {"label": "知识生成入口"},
    "activeRag.localOnlyDefault": {"label": "预览默认仅本地检索"},
    "pinyin.fuzzyProfile": {"label": "模糊音方案"},
    "pinyin.rimeManagedPatch": {"label": "Rime 模糊音补丁"},
    "pinyin.rerankUsesFuzzy": {"label": "重排使用模糊音"},
    "pinyin.pairs.zZh": {"label": "z / zh 模糊音"},
    "pinyin.pairs.cCh": {"label": "c / ch 模糊音"},
    "pinyin.pairs.sSh": {"label": "s / sh 模糊音"},
    "pinyin.pairs.enEng": {"label": "en / eng 模糊音"},
    "pinyin.pairs.inIng": {"label": "in / ing 模糊音"},
    "pinyin.pairs.ongOn": {"label": "on / ong 模糊音"},
    "pinyin.pairs.nL": {"label": "n / l 模糊音"},
    "pinyin.pairs.fH": {"label": "f / h 模糊音"},
}
_SETTING_DEFAULTS = flatten_settings(default_settings())
_SETTING_SCHEMA_FIELDS = {
    str(field.get("key") or ""): dict(field)
    for section in settings_schema().get("sections", [])
    if isinstance(section, Mapping)
    for field in section.get("fields", [])
    if isinstance(field, Mapping) and str(field.get("key") or "")
}


def _normalize_runtime_tool_args(
    tool: str,
    args: Mapping[str, object],
) -> dict[str, object]:
    normalized = dict(args)
    if tool != "ime_memory" or str(normalized.get("op") or "").strip():
        return normalized

    query = str(normalized.get("query") or "").strip()
    scope = str(normalized.get("scope") or "").strip().lower()
    if not query:
        return normalized
    if scope == "recent":
        normalized["op"] = "recent"
        normalized.pop("scope", None)
        return normalized
    if scope in {"", "current", "historical", "change"}:
        normalized["op"] = "search"
        normalized.pop("scope", None)
        if scope:
            normalized.setdefault("mode", scope)
    return normalized


class ControlToolGateway:
    """Capability-scoped gateway over the existing control-plane services.

    Pi never receives a database handle. Each operation is an explicit adapter
    over the same management/core services used by the native control center.
    R1+ operations always create a hash-bound preview. They wait for native UI
    approval by default; a natively confirmed dangerous Session may decide that
    approval automatically while retaining validation, receipts, and rollback.
    """

    def __init__(
        self,
        *,
        sessions: AgentSessionStore,
        management: ManagementService,
        core: object,
        project: str,
        facade: object | None = None,
        knowledge_client: object | None = None,
        workspace_harness: WorkspaceHarness | None = None,
        delegation: object | None = None,
        collaboration: object | None = None,
        extensions: object | None = None,
        scheduling: object | None = None,
        browser_control: BrowserControlService | None = None,
        desktop_client: object | None = None,
        role_books: object | None = None,
        artifact_projector: AgentToolArtifactProjector | None = None,
        workflow_publisher: Callable[[str, str], object] | None = None,
    ) -> None:
        self.sessions = sessions
        self.management = management
        self.core = core
        self.project = project
        self.facade = facade
        self.knowledge_client = knowledge_client
        self.workspace_harness = workspace_harness or WorkspaceHarness()
        self.delegation = delegation
        self.collaboration = collaboration
        self.extensions = extensions
        self.scheduling = scheduling
        self.browser_control = browser_control
        self.desktop_client = desktop_client or DesktopBridgeClient()
        self.role_books = role_books
        self.artifact_projector = artifact_projector
        self.workflow_publisher = workflow_publisher
        self._role_book_tool_adapter: AgentRoleBookToolAdapter | None = None
        self._memory_governance_store: MemoryGovernanceProposalStore | None = None
        self._auto_approval_executor: (
            Callable[[Mapping[str, object]], Mapping[str, object]] | None
        ) = None

    def bind_auto_approval_executor(
        self,
        executor: Callable[[Mapping[str, object]], Mapping[str, object]],
    ) -> None:
        self._auto_approval_executor = executor

    def manifests(self, *, session_id: str = "") -> dict[str, object]:
        session = self.sessions.get(session_id) if session_id else None
        manifests = self._manifest_items(session)
        response: dict[str, object] = {
            "schemaVersion": "rag-ime.control-tool-list.v1",
            "ok": True,
            "items": manifests,
        }
        if session is not None:
            response["sessionPolicy"] = {
                "sessionId": session["id"],
                "mode": session["mode"],
                "executionMode": session.get("executionMode", "per_action"),
                "workspaceScopeGranted": session.get(
                    "workspaceScopeGranted",
                    False,
                ),
                "toolProfileVersion": session["toolProfileVersion"],
                "toolAllowlistMode": session.get("toolAllowlistMode", "profile"),
                "allowedTools": list(session.get("allowedTools") or []),
            }
        return response

    def runtime_manifests(self, session: Mapping[str, object]) -> list[Mapping[str, object]]:
        manifests: list[Mapping[str, object]] = []
        for manifest in self._manifest_items(session):
            if manifest.get("enabled") is not True:
                continue
            spec = _TOOL_SPEC_BY_ID[str(manifest["id"])]
            operations = list(manifest.get("effectiveOperations") or [])
            parameter_schema = _runtime_tool_parameter_schema(
                str(manifest["id"]),
                operations,
            )
            usage = _RUNTIME_TOOL_USAGE.get(str(manifest["id"]), "")
            base_description = str(manifest["description"]).rstrip("。")
            item: dict[str, object] = {
                "name": manifest["id"],
                "description": f"{base_description}。{usage}" if usage else base_description,
                "parameters": parameter_schema,
                "when": list(spec["when"]),
                "notFor": list(spec["notFor"]),
                "input": spec["input"],
                "output": spec["output"],
                "does": spec["does"],
                "profile": session.get("toolProfileVersion") or "control-center-v1",
                "risk": manifest.get("riskLevel") or "R0",
            }
            projections = [
                dict(projection)
                for projection in _RUNTIME_TOOL_PROJECTIONS.get(
                    str(manifest["id"]),
                    (),
                )
                if projection["operation"] in operations
            ]
            if projections:
                item["runtimeProjections"] = projections
            manifests.append(item)
        return manifests

    def _manifest_items(
        self,
        session: Mapping[str, object] | None,
    ) -> list[dict[str, object]]:
        manifests = []
        for spec in _TOOL_SPECS:
            operations = list(spec["operations"])
            operation_risks = {
                operation: str(dict(spec.get("operationRisks") or {}).get(operation) or "R0")
                for operation in operations
            }
            manifest = {
                "schemaVersion": "rag-ime.control-tool-manifest.v1",
                "id": spec["id"],
                "domain": spec["domain"],
                "displayName": spec["displayName"],
                "description": spec["description"],
                "category": spec["domain"],
                "riskLevel": _highest_risk(operation_risks.values()),
                "sessionModes": list(spec.get("sessionModes") or ("assistant", "coordinator")),
                "operations": operations,
                "operationRisks": operation_risks,
                "resultPresentation": spec["resultPresentation"],
                "availability": "online",
                "version": "1",
            }
            validate_contract(manifest, "control-tool-manifest.v1.json")
            if session is not None:
                mode_compatible = str(session.get("mode") or "assistant") in manifest["sessionModes"]
                manifest["profileOperations"] = {
                    profile: [
                        operation
                        for operation in operations
                        if _tool_profile_allows(
                            {
                                **session,
                                "toolProfileVersion": profile,
                                "toolAllowlistMode": "profile",
                                "allowedTools": [],
                            },
                            tool=str(spec["id"]),
                            operation=operation,
                            spec=spec,
                        )
                    ]
                    for profile in (
                        "control-center-v1",
                        "subagent-readonly-v1",
                        DANGEROUS_AUTO_APPROVE_TOOL_PROFILE,
                    )
                }
                effective_operations = [
                    operation
                    for operation in operations
                    if mode_compatible
                    and _tool_profile_allows(
                        session,
                        tool=str(spec["id"]),
                        operation=operation,
                        spec=spec,
                    )
                ]
                manifest["enabled"] = bool(effective_operations)
                manifest["effectiveOperations"] = effective_operations
                manifest["explicitlyAllowed"] = (
                    str(session.get("toolAllowlistMode") or "profile") != "explicit"
                    or str(spec["id"]) in {str(value) for value in session.get("allowedTools") or []}
                )
            manifests.append(manifest)
        return manifests

    def execute(self, payload: Mapping[str, object]) -> dict[str, object]:
        request = dict(payload)
        validate_contract(request, "agent-tool-call.v1.json")
        session_id = str(request["sessionId"])
        session = self.sessions.get(session_id)
        if session.get("status") == "archived":
            raise ValueError("archived sessions cannot execute tools")
        tool = str(request["tool"])
        raw_args = request.get("args") if isinstance(request.get("args"), Mapping) else {}
        args = _normalize_runtime_tool_args(tool, raw_args)
        if tool in {
            "room_state",
            "room_collaborate",
            "room_post",
            "room_commit",
        }:
            if self.collaboration is None:
                raise ValueError("managed room collaboration is unavailable")
            result = self.collaboration.execute_room_capability_tool(  # type: ignore[attr-defined]
                session_id,
                tool,
                args,
                tool_call_id=str(request["toolCallId"]),
                load_receipt_id=str(request.get("loadReceiptId") or ""),
            )
            if result is None:
                raise ValueError("canonical Room tools require an active RoomBinding")
            return dict(result)
        spec = _TOOL_SPEC_BY_ID.get(tool)
        if spec is None:
            raise ValueError("tool is not enabled for this session")
        session_modes = tuple(spec.get("sessionModes") or ("assistant", "coordinator"))
        if str(session.get("mode") or "assistant") not in session_modes:
            raise ValueError("tool is not enabled for this session mode")
        operation = str(args.get("op") or "")
        if operation not in spec["operations"]:
            raise ValueError(f"unsupported {tool} operation")

        room_authorization = self._authorize_room_product_tool(
            session_id=session_id,
            tool=tool,
            args=args,
            tool_call_id=str(request["toolCallId"]),
            load_receipt_id=str(request.get("loadReceiptId") or ""),
        )
        try:
            response = self._execute_product_tool(
                request=request,
                session=session,
                tool=tool,
                args=args,
                spec=spec,
                operation=operation,
                room_authorization=room_authorization,
            )
        except Exception as exc:
            self._record_failed_room_product_tool(
                session_id=session_id,
                authorization=room_authorization,
                error=exc,
            )
            raise

        pending_room_approval = (
            room_authorization is not None
            and isinstance(response.get("result"), Mapping)
            and response["result"].get("approvalRequired") is True
        )
        if pending_room_approval:
            invocation = room_authorization.get("invocationReceipt")
            if not isinstance(invocation, Mapping):
                raise ValueError(
                    "Room product Tool authorization has no invocation receipt"
                )
            response["roomInvocationReceipt"] = dict(invocation)
        elif room_authorization is not None:
            sealed_receipt = _auto_approved_room_execution_receipt(response)
            auto_approved = (
                isinstance(response.get("result"), Mapping)
                and response["result"].get("autoApproved") is True
            )
            if auto_approved:
                if sealed_receipt is None:
                    raise ValueError(
                        "automatic Room Tool approval completed without "
                        "an execution receipt"
                    )
                response["roomExecutionReceipt"] = sealed_receipt
                validate_contract(response, "agent-tool-result.v1.json")
                return response
            execution = self._record_room_product_tool_execution(
                session_id=session_id,
                authorization=room_authorization,
                status="applied",
                result_hash=_sha256_json(response),
            )
            receipt = execution.get("executionReceipt")
            if isinstance(receipt, Mapping):
                response["roomExecutionReceipt"] = dict(receipt)
        validate_contract(response, "agent-tool-result.v1.json")
        return response

    def _execute_product_tool(
        self,
        *,
        request: Mapping[str, object],
        session: Mapping[str, object],
        tool: str,
        args: Mapping[str, object],
        spec: Mapping[str, object],
        operation: str,
        room_authorization: Mapping[str, object] | None,
    ) -> dict[str, object]:
        session_id = str(session["id"])
        if not _tool_profile_allows(session, tool=tool, operation=operation, spec=spec):
            raise ValueError("tool operation is not enabled for this session tool profile")
        if (tool, operation) in {
            ("workspace_patch", "apply"),
            ("workspace_shell", "run"),
        }:
            # A preview request is still planning. Prove Act is open here, but
            # transition to executing only when an approved write is applied.
            self.sessions.require_workspace_act(
                session_id,
                room_dispatch_authorized=(room_authorization is not None),
            )
        handlers = {
            "ime_overview": self._overview,
            "ime_input": self._input,
            "ime_voice": self._voice,
            "ime_planning": self._planning,
            "agent_schedule": self._agent_schedule,
            "ime_memory": self._memory,
            "agent_role_book": self._role_book,
            "ime_knowledge": self._knowledge,
            "ime_models": self._models,
            "ime_runtime": self._runtime,
            "ime_configuration": self._configuration,
            "ime_agents": self._agents,
            "ime_browser": self._browser,
            "agent_plan": self._agent_plan,
            "ime_plugins": self._plugins,
        }
        risk_level = str(dict(spec.get("operationRisks") or {}).get(operation) or "R0")
        if risk_level == "R0":
            if tool == "workspace_list":
                result = self.workspace_harness.list(session, args)
            elif tool == "workspace_read":
                result = self.workspace_harness.read(session, args)
            elif tool == "workspace_search":
                result = self.workspace_harness.search(session, args)
            else:
                handler_args = dict(args)
                handler_args["_sessionId"] = session_id
                runtime_context = request.get("runtimeContext")
                if tool == "ime_agents":
                    handler_args["_toolCallId"] = str(request["toolCallId"])
                    handler_args["_loadReceiptId"] = str(request.get("loadReceiptId") or "")
                if tool == "ime_agents" and operation == "delegate":
                    if isinstance(runtime_context, Mapping):
                        handler_args["_runtimeContext"] = dict(runtime_context)
                if tool == "desktop_semantic":
                    result = self._desktop(operation, handler_args)
                else:
                    result = handlers[tool](operation, handler_args)
        else:
            strategy = approval_strategy(
                session,
                tool=tool,
                operation=operation,
            )
            if strategy == APPROVAL_DENY:
                # A denied operation must not leave a pending approval behind.
                # Read-only is a hard runtime policy, not an approval workflow.
                raise ValueError(
                    "write and Shell operations are blocked in read-only mode"
                )
            result = self._prepare_approval(
                session_id=session_id,
                tool=tool,
                operation=operation,
                args=args,
                risk_level=risk_level,
                room_invocation_receipt_id=(
                    _room_invocation_receipt_id(room_authorization)
                ),
            )
            if strategy == APPROVAL_AUTO:
                approval = result.get("approval") if isinstance(result.get("approval"), Mapping) else None
                if approval is None or self._auto_approval_executor is None:
                    raise ValueError("automatic approval bridge is unavailable")
                result = dict(self._auto_approval_executor(approval))
        response = {
            "schemaVersion": "rag-ime.agent-tool-result.v1",
            "ok": True,
            "tool": tool,
            "operation": operation,
            "result": result,
        }
        return response

    def _authorize_room_product_tool(
        self,
        *,
        session_id: str,
        tool: str,
        args: Mapping[str, object],
        tool_call_id: str,
        load_receipt_id: str,
    ) -> Mapping[str, object] | None:
        authorize = getattr(
            self.collaboration,
            "authorize_room_product_tool",
            None,
        )
        if not callable(authorize):
            return None
        result = authorize(
            session_id,
            tool,
            args,
            tool_call_id=tool_call_id,
            load_receipt_id=load_receipt_id,
        )
        if result is None:
            return None
        if not isinstance(result, Mapping):
            raise ValueError("Room product Tool authorization returned an invalid receipt")
        return dict(result)

    def _record_room_product_tool_execution(
        self,
        *,
        session_id: str,
        authorization: Mapping[str, object],
        status: str,
        result_hash: str,
    ) -> Mapping[str, object]:
        invocation = authorization.get("invocationReceipt")
        if not isinstance(invocation, Mapping):
            raise ValueError("Room product Tool authorization has no invocation receipt")
        invocation_receipt_id = str(invocation.get("receiptId") or "").strip()
        if not invocation_receipt_id:
            raise ValueError("Room product Tool invocation receipt has no id")
        record = getattr(
            self.collaboration,
            "record_room_product_tool_execution",
            None,
        )
        if not callable(record):
            raise ValueError("Room product Tool execution receipt owner is unavailable")
        result = record(
            session_id,
            invocation_receipt_id,
            status=status,
            result_hash=result_hash,
        )
        if not isinstance(result, Mapping):
            raise ValueError("Room product Tool execution returned an invalid receipt")
        return dict(result)

    def _record_failed_room_product_tool(
        self,
        *,
        session_id: str,
        authorization: Mapping[str, object] | None,
        error: Exception,
    ) -> None:
        if authorization is None:
            return
        try:
            self._record_room_product_tool_execution(
                session_id=session_id,
                authorization=authorization,
                status="failed",
                result_hash=_sha256_json(
                    {
                        "errorType": type(error).__name__,
                        "message": str(error),
                    }
                ),
            )
        except Exception:
            # Preserve the original Tool failure. A revoked binding still keeps
            # this late result from being returned on the success path.
            return

    def _validate_room_product_tool_approval(
        self,
        *,
        session_id: str,
        invocation_receipt_id: str,
        tool: str,
    ) -> Mapping[str, object]:
        validate = getattr(
            self.collaboration,
            "validate_room_product_tool_approval",
            None,
        )
        if not callable(validate):
            raise ValueError("Room approval fence owner is unavailable")
        result = validate(
            session_id,
            invocation_receipt_id,
            tool_name=tool,
        )
        if not isinstance(result, Mapping):
            raise ValueError("Room approval fence returned an invalid receipt")
        return dict(result)

    def _bind_room_invocation_to_approval(
        self,
        prepared: Mapping[str, object],
        *,
        session_id: str,
        tool: str,
        operation: str,
        invocation_receipt_id: str,
    ) -> dict[str, object]:
        if not invocation_receipt_id:
            return dict(prepared)
        approval = prepared.get("approval")
        if not isinstance(approval, Mapping):
            raise ValueError(
                "Room approval preparation returned no approval record"
            )
        preview = approval.get("preview")
        if not isinstance(preview, Mapping):
            raise ValueError("Room approval has no hash-bound preview")
        action_payload = preview.get("actionPayload")
        base_state = preview.get("baseState")
        if not isinstance(action_payload, Mapping) or not isinstance(
            base_state, Mapping
        ):
            raise ValueError(
                "Room approval preview has no action payload or base state"
            )
        existing_receipt_id = _bounded_text(
            base_state.get("roomInvocationReceiptId"), maximum=240
        )
        if existing_receipt_id and existing_receipt_id != invocation_receipt_id:
            raise ValueError(
                "Room approval is already bound to another invocation"
            )
        rebound_base_state = {
            **base_state,
            "roomInvocationReceiptId": invocation_receipt_id,
        }
        rebound_preview = {
            **preview,
            "baseState": rebound_base_state,
        }
        payload_sha256 = _approval_payload_digest(
            session_id=session_id,
            tool=tool,
            operation=operation,
            action_payload=action_payload,
            base_state=rebound_base_state,
        )
        rebound = self.sessions.rebind_pending_approval(
            str(approval.get("approvalId") or ""),
            expected_payload_sha256=str(
                approval.get("payloadSha256") or ""
            ),
            payload_sha256=payload_sha256,
            preview=rebound_preview,
        )
        return {
            **prepared,
            "approvalId": rebound["approvalId"],
            "approval": rebound,
        }

    def _seal_room_approval_execution(
        self,
        *,
        approval: Mapping[str, object],
        result: Mapping[str, object],
    ) -> dict[str, object]:
        invocation_receipt_id = _approval_room_invocation_receipt_id(
            approval
        )
        sealed = dict(result)
        if not invocation_receipt_id:
            return sealed
        if sealed.get("externalActionPending") is True:
            # The native supervisor is the execution owner from this point.
            # Keep the Room invocation open until its final, verified receipt.
            return sealed
        execution = self._record_room_product_tool_execution(
            session_id=str(approval.get("sessionId") or ""),
            authorization={
                "invocationReceipt": {
                    "receiptId": invocation_receipt_id,
                }
            },
            status=(
                "applied"
                if sealed.get("mutationApplied") is True
                else "failed"
            ),
            result_hash=_sha256_json(sealed),
        )
        receipt = execution.get("executionReceipt")
        if not isinstance(receipt, Mapping):
            raise ValueError(
                "Room approval execution returned no execution receipt"
            )
        sealed["roomExecutionReceipt"] = dict(receipt)
        return sealed

    def _plugins(self, operation: str, args: Mapping[str, object]) -> dict[str, object]:
        if self.extensions is None:
            raise ValueError("managed plugin lifecycle is unavailable")
        if operation == "list":
            return dict(self.extensions.list())  # type: ignore[attr-defined]
        if operation == "create_draft":
            return dict(self.extensions.create_draft(args))  # type: ignore[attr-defined]
        if operation == "validate":
            return dict(self.extensions.validate(args))  # type: ignore[attr-defined]
        if operation == "propose_install":
            return dict(
                self.extensions.preview(  # type: ignore[attr-defined]
                    {
                        "action": "install",
                        "validationToken": args.get("validationToken"),
                        "enable": args.get("enable") is True,
                    }
                )
            )
        raise ValueError("unsupported ime_plugins operation")

    def _browser(self, operation: str, args: Mapping[str, object]) -> dict[str, object]:
        service = self.browser_control
        if service is None:
            raise ValueError("browser co-pilot is unavailable")
        if operation == "status":
            return service.status(agent_safe=True)
        if operation == "tabs":
            return service.tabs()
        if operation == "snapshot":
            result = service.latest_snapshot(
                device_id=_bounded_text(args.get("deviceId"), maximum=160),
                tab_id=(
                    _bounded_int(args.get("tabId"), default=0, minimum=0, maximum=2_147_483_647)
                    or None
                ),
                include_markdown=True,
            )
            maximum = _bounded_int(
                args.get("maxChars"),
                default=24_000,
                minimum=1_000,
                maximum=80_000,
            )
            markdown = str(result.get("markdown") or "")
            result["markdown"] = markdown[:maximum]
            result["truncated"] = len(markdown) > maximum
            result["untrustedData"] = True
            return result
        if operation == "trace":
            return service.traces(
                limit=_bounded_int(args.get("limit"), default=20, minimum=1, maximum=100)
            )
        if operation == "screenshot":
            return service.submit_command(
                "screenshot",
                args,
                session_id=_bounded_text(args.get("_sessionId"), maximum=240),
                timeout_seconds=20.0,
            )
        raise ValueError(f"unsupported ime_browser operation: {operation}")

    def _desktop(self, operation: str, args: Mapping[str, object]) -> dict[str, object]:
        if operation == "status":
            return dict(self.desktop_client.status())  # type: ignore[attr-defined]
        if operation == "list":
            return dict(
                self.desktop_client.list_applications(  # type: ignore[attr-defined]
                    include_background=args.get("includeBackground") is True,
                )
            )
        if operation == "inspect":
            return dict(
                self.desktop_client.inspect(  # type: ignore[attr-defined]
                    bundle_id=_bounded_text(args.get("bundleId"), maximum=300),
                    pid=_bounded_int(args.get("pid"), default=0, minimum=0, maximum=2_147_483_647),
                    query=_bounded_text(args.get("query"), maximum=300),
                    max_nodes=_bounded_int(args.get("maxNodes"), default=160, minimum=1, maximum=400),
                    max_depth=_bounded_int(args.get("maxDepth"), default=8, minimum=1, maximum=12),
                    since_snapshot_id=_bounded_text(args.get("sinceSnapshotId"), maximum=200),
                )
            )
        raise ValueError("unsupported desktop_semantic operation")

    def _agents(self, operation: str, args: Mapping[str, object]) -> dict[str, object]:
        if self.delegation is None:
            raise ValueError("managed delegation is unavailable")
        session_id = _bounded_text(args.get("_sessionId"), maximum=240)
        if not session_id:
            raise ValueError("agent collaboration session is missing")
        if operation == "catalog":
            return dict(self.delegation.catalog())  # type: ignore[attr-defined]
        if operation == "delegate":
            return dict(self.delegation.delegate(session_id, args))  # type: ignore[attr-defined]
        if operation == "status":
            return dict(self.delegation.status(session_id, args))  # type: ignore[attr-defined]
        if operation == "artifact":
            return dict(
                self.delegation.inspect_artifact(  # type: ignore[attr-defined]
                    session_id,
                    _bounded_text(args.get("artifactId"), maximum=240),
                    limit=_bounded_int(args.get("limit"), default=50, minimum=1, maximum=500),
                )
            )
        if operation == "abort":
            return dict(self.delegation.abort(session_id, args))  # type: ignore[attr-defined]
        raise ValueError("unsupported ime_agents operation")

    def _agent_plan(self, operation: str, args: Mapping[str, object]) -> dict[str, object]:
        session_id = _bounded_text(args.get("_sessionId"), maximum=240)
        if not session_id:
            raise ValueError("agent plan session is missing")
        if operation == "list":
            plan = self.sessions.agent_plan(
                session_id,
                limit=_bounded_int(args.get("limit"), default=100, minimum=1, maximum=100),
            )
            counts = plan["counts"] if isinstance(plan.get("counts"), Mapping) else {}
            return {
                "summary": (
                    f"当前计划有 {_safe_int(counts.get('pending'))} 项待办、"
                    f"{_safe_int(counts.get('inProgress'))} 项进行中、"
                    f"{_safe_int(counts.get('completed'))} 项已完成"
                ),
                "presentationKind": "task_plan",
                "plan": plan,
                "items": list(plan.get("items") or []),
            }
        if operation == "update":
            result = self.sessions.update_agent_plan_item(
                session_id,
                item_id=_bounded_text(args.get("itemId"), maximum=160),
                title=_bounded_text(args.get("title"), maximum=240),
                status=_bounded_text(args.get("status"), maximum=40),
            )
            event = result["event"] if isinstance(result.get("event"), Mapping) else {}
            plan = result["plan"] if isinstance(result.get("plan"), Mapping) else {}
            self._publish_workflow(session_id, "plan:item_update")
            return {
                "summary": f"计划项《{event.get('title', '')}》已更新为 {event.get('status', '')}",
                "presentationKind": "task_plan",
                "event": event,
                "plan": plan,
                "items": list(plan.get("items") or []),
            }
        if operation in {"submit_review", "complete", "cancel"}:
            action = {
                "submit_review": "submit_review",
                "complete": "complete",
                "cancel": "cancel",
            }[operation]
            result = self.sessions.mutate_agent_plan(
                session_id,
                {
                    "action": action,
                    "note": _bounded_text(args.get("note"), maximum=600),
                },
                actor="agent-runtime",
            )
            plan = result["plan"] if isinstance(result.get("plan"), Mapping) else {}
            self._publish_workflow(session_id, f"plan:{action}")
            return {
                "summary": f"执行计划已进入 {plan.get('status', '')} 状态",
                "presentationKind": "task_plan",
                "plan": plan,
                "items": list(plan.get("items") or []),
            }
        raise ValueError("unsupported agent_plan operation")

    def _publish_workflow(self, session_id: str, reason: str) -> None:
        if self.workflow_publisher is None:
            return
        self.workflow_publisher(session_id, reason)

    def apply_approval(self, approval: Mapping[str, object]) -> dict[str, object]:
        """Execute one already-approved operation after revalidating its preview."""

        if str(approval.get("state") or "") != "approved":
            raise ValueError("approval must be in approved state before execution")
        tool = str(approval.get("toolId") or "")
        operation = str(approval.get("operation") or "")
        session_id = str(approval.get("sessionId") or "")
        room_invocation_receipt_id = _approval_room_invocation_receipt_id(
            approval
        )
        if room_invocation_receipt_id:
            self._validate_room_product_tool_approval(
                session_id=session_id,
                invocation_receipt_id=room_invocation_receipt_id,
                tool=tool,
            )
        elif (tool, operation) in {
            ("workspace_patch", "apply"),
            ("workspace_shell", "run"),
        }:
            self.sessions.require_workspace_act(session_id)
        result = self._apply_approved_operation(approval)
        return self._seal_room_approval_execution(
            approval=approval,
            result=result,
        )

    def _apply_approved_operation(
        self,
        approval: Mapping[str, object],
    ) -> dict[str, object]:
        tool = str(approval.get("toolId") or "")
        operation = str(approval.get("operation") or "")
        if (tool, operation) == ("workspace_shell", "run"):
            result = self._apply_workspace_command(approval)
            if (
                result.get("mutationApplied") is True
                and _safe_int(result.get("exitCode")) == 0
                and result.get("timedOut") is not True
                and result.get("outputLimited") is not True
            ):
                self._mark_workspace_execution_started(approval)
            return result
        if (tool, operation) == ("workspace_patch", "apply"):
            result = self._apply_workspace_patch(approval)
            self._mark_workspace_execution_started(approval)
            return result
        if (tool, operation) == ("desktop_semantic", "act"):
            return self._apply_desktop_action(approval)
        if (tool, operation) == ("ime_planning", "undo_task_event"):
            return self._apply_planning_undo(approval)
        if tool == "agent_schedule":
            return self._apply_agent_schedule(approval)
        if tool == "ime_memory" and operation in {"maintenance_apply", "maintenance_rollback"}:
            return self._apply_memory_mutation(approval)
        if tool == "ime_memory" and operation in {
            "remember_apply",
            "correct_apply",
            "forget_apply",
            "governance_rollback",
        }:
            return self._apply_governed_memory_mutation(approval)
        if tool == "ime_input" and operation in {"apply_settings", "rollback_settings"}:
            return self._apply_input_settings(approval)
        if tool == "ime_input" and operation in {"lexicon_apply", "lexicon_rollback"}:
            return self._apply_lexicon_mutation(approval)
        if tool == "ime_runtime" and operation in {
            "pause_ai",
            "resume_ai",
            "restart_sidecar",
            "restart_predictor",
            "redeploy_rime",
        }:
            return self._apply_runtime_mutation(approval)
        if tool == "ime_models" and operation in {"profile_apply", "profile_rollback"}:
            return self._apply_model_profile_mutation(approval)
        if tool == "ime_voice" and operation in {"provider_apply", "provider_rollback"}:
            return self._apply_voice_provider_mutation(approval)
        if (tool, operation) == ("ime_configuration", "export"):
            return self._apply_configuration_export(approval)
        if (tool, operation) == ("ime_configuration", "restore_apply"):
            return self._apply_configuration_restore(approval)
        if tool == "ime_browser":
            return self._apply_browser_action(approval)
        if (tool, operation) != ("ime_planning", "task_action"):
            raise ValueError("approved operation is not enabled")
        preview = approval.get("preview") if isinstance(approval.get("preview"), Mapping) else {}
        action_payload = (
            preview.get("actionPayload") if isinstance(preview.get("actionPayload"), Mapping) else {}
        )
        base_state = preview.get("baseState") if isinstance(preview.get("baseState"), Mapping) else {}
        expected_digest = _approval_payload_digest(
            session_id=str(approval.get("sessionId") or ""),
            tool=tool,
            operation=operation,
            action_payload=action_payload,
            base_state=base_state,
        )
        if expected_digest != str(approval.get("payloadSha256") or ""):
            raise ValueError("approval payload no longer matches its preview")

        task_id = _bounded_text(action_payload.get("taskId"), maximum=240)
        action = _bounded_text(action_payload.get("action"), maximum=40)
        plan_date = _bounded_text(action_payload.get("date"), maximum=24)
        if not task_id or action not in _PLANNING_TARGET_STATUS or not plan_date:
            raise ValueError("approved task action payload is invalid")
        task = self._planning_task(task_id=task_id, plan_date=plan_date)
        if (
            str(task.get("status") or "") != str(base_state.get("status") or "")
            or _safe_int(task.get("updatedAtMs")) != _safe_int(base_state.get("updatedAtMs"))
        ):
            raise ValueError("task changed after the approval preview was created")

        target_status = _PLANNING_TARGET_STATUS[action]
        try:
            result = self.management.planning_task_action({"taskId": task_id, "action": action})
        except Exception as exc:
            # The task mutation and audit use separate service calls. If an audit
            # write fails after the task commit, report the observed mutation so
            # Pi cannot retry and duplicate the action.
            observed = self._planning_task(task_id=task_id, plan_date=plan_date)
            if (
                str(observed.get("status") or "") == target_status
                and _safe_int(observed.get("updatedAtMs")) != _safe_int(base_state.get("updatedAtMs"))
            ):
                return self._planning_receipt(
                    approval=approval,
                    action=action,
                    result={"task": observed, "undoAvailable": False},
                    audit_persisted=False,
                    warning=_bounded_text(exc, maximum=240),
                )
            raise
        return self._planning_receipt(
            approval=approval,
            action=action,
            result=result,
            audit_persisted=True,
        )

    def _mark_workspace_execution_started(self, approval: Mapping[str, object]) -> None:
        """Advance Plan only after the hash-bound workspace write succeeds."""

        session_id = str(approval.get("sessionId") or "")
        before = self.sessions.agent_plan(session_id)
        if before.get("status") != "approved":
            return
        self.sessions.mutate_agent_plan(
            session_id,
            {
                "action": "start_execution",
                "expectedRevision": before.get("revision"),
                "note": "首个受控工作区写操作已完成",
            },
            actor="agent-runtime",
        )
        self._publish_workflow(session_id, "plan:start_execution")

    def _prepare_browser_action(
        self,
        *,
        session_id: str,
        operation: str,
        args: Mapping[str, object],
        risk_level: str,
    ) -> dict[str, object]:
        service = self.browser_control
        if service is None:
            raise ValueError("browser co-pilot is unavailable")
        allowed_fields = {
            "deviceId",
            "tabId",
            "refId",
            "url",
            "text",
            "clear",
            "direction",
            "amount",
            "timeoutMs",
        }
        action_payload = {
            str(key): value
            for key, value in args.items()
            if str(key) in allowed_fields and value is not None
        }
        base_state = {
            "mode": service.mode(),
        }
        if operation in {"click", "type"}:
            snapshot = service.latest_snapshot(
                device_id=_bounded_text(action_payload.get("deviceId"), maximum=160),
                tab_id=(
                    _bounded_int(
                        action_payload.get("tabId"),
                        default=0,
                        minimum=0,
                        maximum=2_147_483_647,
                    )
                    or None
                ),
                include_markdown=False,
            )
            base_state["snapshotId"] = str(snapshot.get("snapshotId") or "")
        digest = _approval_payload_digest(
            session_id=session_id,
            tool="ime_browser",
            operation=operation,
            action_payload=action_payload,
            base_state=base_state,
        )
        labels = {
            "navigate": "打开网页",
            "click": "点击页面元素",
            "type": "向页面输入文本",
            "scroll": "滚动页面",
            "wait": "等待页面内容",
            "stop": "停止浏览器任务",
        }
        operation_label = labels.get(operation, operation)
        preview = {
            "title": f"确认{operation_label}",
            "summary": f"浏览器共驾将{operation_label}，操作结果会写入执行轨迹",
            "operationLabel": operation_label,
            "changes": [
                {
                    "label": "目标",
                    "path": operation,
                    "before": "当前页面",
                    "after": (
                        _bounded_text(action_payload.get("url"), maximum=320)
                        or _bounded_text(action_payload.get("refId"), maximum=160)
                        or operation_label
                    ),
                }
            ],
            "actionPayload": action_payload,
            "baseState": base_state,
        }
        if operation == "type":
            preview["changes"].append(
                {
                    "label": "输入内容",
                    "path": "text",
                    "before": "",
                    "after": _bounded_text(action_payload.get("text"), maximum=320),
                }
            )
        approval = self.sessions.create_approval(
            session_id=session_id,
            tool_name="ime_browser",
            operation=operation,
            payload_sha256=digest,
            preview=preview,
            risk_level=risk_level,
            ttl_ms=60_000,
        )
        return {
            "summary": f"等待确认：{preview['summary']}",
            "approvalRequired": True,
            "approvalId": approval["approvalId"],
            "approval": approval,
        }

    def _apply_browser_action(self, approval: Mapping[str, object]) -> dict[str, object]:
        service = self.browser_control
        if service is None:
            raise ValueError("browser co-pilot is unavailable")
        operation = str(approval.get("operation") or "")
        preview = approval.get("preview") if isinstance(approval.get("preview"), Mapping) else {}
        action_payload = (
            preview.get("actionPayload") if isinstance(preview.get("actionPayload"), Mapping) else {}
        )
        base_state = preview.get("baseState") if isinstance(preview.get("baseState"), Mapping) else {}
        expected_digest = _approval_payload_digest(
            session_id=str(approval.get("sessionId") or ""),
            tool="ime_browser",
            operation=operation,
            action_payload=action_payload,
            base_state=base_state,
        )
        if expected_digest != str(approval.get("payloadSha256") or ""):
            raise ValueError("approval payload no longer matches its preview")
        if service.mode() != str(base_state.get("mode") or ""):
            raise ValueError("browser mode changed after the approval preview was created")
        snapshot_id = str(base_state.get("snapshotId") or "")
        if snapshot_id:
            current = service.latest_snapshot(
                device_id=_bounded_text(action_payload.get("deviceId"), maximum=160),
                tab_id=(
                    _bounded_int(
                        action_payload.get("tabId"),
                        default=0,
                        minimum=0,
                        maximum=2_147_483_647,
                    )
                    or None
                ),
                include_markdown=False,
            )
            if str(current.get("snapshotId") or "") != snapshot_id:
                raise ValueError("browser page changed after the approval preview was created")
        if operation == "stop":
            result = service.stop()
        else:
            result = service.submit_command(
                operation,
                action_payload,
                session_id=str(approval.get("sessionId") or ""),
                timeout_seconds=25.0 if operation in {"navigate", "wait"} else 15.0,
            )
        return {
            **result,
            "approvalId": str(approval.get("approvalId") or ""),
            "toolId": "ime_browser",
            "operation": operation,
            "auditId": str(approval.get("approvalId") or ""),
        }

    def _prepare_approval(
        self,
        *,
        session_id: str,
        tool: str,
        operation: str,
        args: Mapping[str, object],
        risk_level: str,
        room_invocation_receipt_id: str = "",
    ) -> dict[str, object]:
        prepared = self._prepare_approval_operation(
            session_id=session_id,
            tool=tool,
            operation=operation,
            args=args,
            risk_level=risk_level,
        )
        return self._bind_room_invocation_to_approval(
            prepared,
            session_id=session_id,
            tool=tool,
            operation=operation,
            invocation_receipt_id=room_invocation_receipt_id,
        )

    def _prepare_approval_operation(
        self,
        *,
        session_id: str,
        tool: str,
        operation: str,
        args: Mapping[str, object],
        risk_level: str,
    ) -> dict[str, object]:
        if (tool, operation) == ("workspace_shell", "run"):
            return self._prepare_workspace_command(
                session_id=session_id,
                args=args,
                risk_level=risk_level,
            )
        if (tool, operation) == ("workspace_patch", "apply"):
            return self._prepare_workspace_patch(
                session_id=session_id,
                args=args,
                risk_level=risk_level,
            )
        if (tool, operation) == ("desktop_semantic", "act"):
            return self._prepare_desktop_action(
                session_id=session_id,
                args=args,
                risk_level=risk_level,
            )
        if (tool, operation) == ("ime_planning", "undo_task_event"):
            return self._prepare_planning_undo(
                session_id=session_id,
                args=args,
                risk_level=risk_level,
            )
        if tool == "agent_schedule":
            return self._prepare_agent_schedule(
                session_id=session_id,
                operation=operation,
                args=args,
                risk_level=risk_level,
            )
        if tool == "ime_memory" and operation in {"maintenance_apply", "maintenance_rollback"}:
            return self._prepare_memory_mutation(
                session_id=session_id,
                operation=operation,
                args=args,
                risk_level=risk_level,
            )
        if tool == "ime_memory" and operation in {
            "remember_apply",
            "correct_apply",
            "forget_apply",
            "governance_rollback",
        }:
            return self._prepare_governed_memory_mutation(
                session_id=session_id,
                operation=operation,
                args=args,
                risk_level=risk_level,
            )
        if tool == "ime_input" and operation in {"apply_settings", "rollback_settings"}:
            return self._prepare_input_settings(
                session_id=session_id,
                operation=operation,
                args=args,
                risk_level=risk_level,
            )
        if tool == "ime_input" and operation in {"lexicon_apply", "lexicon_rollback"}:
            return self._prepare_lexicon_mutation(
                session_id=session_id,
                operation=operation,
                args=args,
                risk_level=risk_level,
            )
        if tool == "ime_runtime" and operation in {
            "pause_ai",
            "resume_ai",
            "restart_sidecar",
            "restart_predictor",
            "redeploy_rime",
        }:
            return self._prepare_runtime_mutation(
                session_id=session_id,
                operation=operation,
                risk_level=risk_level,
            )
        if tool == "ime_models" and operation in {"profile_apply", "profile_rollback"}:
            return self._prepare_model_profile_mutation(
                session_id=session_id,
                operation=operation,
                args=args,
                risk_level=risk_level,
            )
        if tool == "ime_voice" and operation in {"provider_apply", "provider_rollback"}:
            return self._prepare_voice_provider_mutation(
                session_id=session_id,
                operation=operation,
                args=args,
                risk_level=risk_level,
            )
        if (tool, operation) == ("ime_configuration", "export"):
            return self._prepare_configuration_export(
                session_id=session_id,
                risk_level=risk_level,
            )
        if (tool, operation) == ("ime_configuration", "restore_apply"):
            return self._prepare_configuration_restore(
                session_id=session_id,
                args=args,
                risk_level=risk_level,
            )
        if tool == "ime_browser":
            return self._prepare_browser_action(
                session_id=session_id,
                operation=operation,
                args=args,
                risk_level=risk_level,
            )
        if (tool, operation) != ("ime_planning", "task_action"):
            raise ValueError("write operation is not enabled")
        task_id = _bounded_text(args.get("taskId"), maximum=240)
        action = _bounded_text(args.get("action"), maximum=40).lower()
        plan_date = _bounded_text(args.get("date"), maximum=24)
        if not task_id:
            raise ValueError("taskId is required for ime_planning.task_action")
        if action not in _PLANNING_TARGET_STATUS:
            raise ValueError("action must be complete, start, reopen, or cancel")
        task = self._planning_task(task_id=task_id, plan_date=plan_date)
        previous_status = str(task.get("status") or "todo")
        target_status = _PLANNING_TARGET_STATUS[action]
        if previous_status == target_status:
            raise ValueError("task is already in the requested state")
        action_payload = {
            "taskId": task_id,
            "action": action,
            "date": str(task.get("date") or plan_date),
            "project": str(task.get("project") or ""),
        }
        base_state = {
            "status": previous_status,
            "updatedAtMs": _safe_int(task.get("updatedAtMs")),
        }
        digest = _approval_payload_digest(
            session_id=session_id,
            tool=tool,
            operation=operation,
            action_payload=action_payload,
            base_state=base_state,
        )
        title = _bounded_text(task.get("title"), maximum=160) or "未命名任务"
        action_label = _PLANNING_ACTION_LABELS[action]
        preview = {
            "title": "确认更新任务",
            "summary": f"将《{title}》{action_label}",
            "operationLabel": action_label,
            "changes": [
                {
                    "label": "任务状态",
                    "before": _planning_status_label(previous_status),
                    "after": _planning_status_label(target_status),
                }
            ],
            "actionPayload": action_payload,
            "baseState": base_state,
        }
        approval = self.sessions.create_approval(
            session_id=session_id,
            tool_name=tool,
            operation=operation,
            payload_sha256=digest,
            preview=preview,
            risk_level=risk_level,
            ttl_ms=60_000,
        )
        return {
            "summary": f"等待确认：{preview['summary']}",
            "approvalRequired": True,
            "approvalId": approval["approvalId"],
            "approval": approval,
        }

    def _prepare_desktop_action(
        self,
        *,
        session_id: str,
        args: Mapping[str, object],
        risk_level: str,
    ) -> dict[str, object]:
        prepared = self.desktop_client.prepare_action(  # type: ignore[attr-defined]
            snapshot_id=_bounded_text(args.get("snapshotId"), maximum=200),
            revision=_bounded_int(args.get("revision"), default=0, minimum=0, maximum=2_147_483_647),
            node_ref=_bounded_text(args.get("nodeRef"), maximum=200),
            action=_bounded_text(args.get("action"), maximum=80),
            text=str(args.get("text"))[:8_000] if isinstance(args.get("text"), str) else None,
            key=_bounded_text(args.get("key"), maximum=40),
            modifiers=tuple(
                str(value)
                for value in args.get("modifiers", [])
                if isinstance(value, str)
            )
            if isinstance(args.get("modifiers"), list)
            else (),
            duration_ms=(
                _bounded_int(args.get("durationMs"), default=650, minimum=100, maximum=3_000)
                if args.get("durationMs") is not None
                else None
            ),
            scroll_delta=(
                _bounded_int(args.get("scrollDelta"), default=3, minimum=-20, maximum=20)
                if args.get("scrollDelta") is not None
                else None
            ),
        )
        if not isinstance(prepared, Mapping):
            raise ValueError("desktop action preview is invalid")
        action_payload = (
            dict(prepared.get("actionPayload"))
            if isinstance(prepared.get("actionPayload"), Mapping)
            else {}
        )
        base_state = (
            dict(prepared.get("baseState"))
            if isinstance(prepared.get("baseState"), Mapping)
            else {}
        )
        if not action_payload or not base_state:
            raise ValueError("desktop action preview is incomplete")
        digest = _approval_payload_digest(
            session_id=session_id,
            tool="desktop_semantic",
            operation="act",
            action_payload=action_payload,
            base_state=base_state,
        )
        summary = _bounded_text(prepared.get("summary"), maximum=240) or "执行桌面语义动作"
        action = _bounded_text(action_payload.get("action"), maximum=80)
        text_chars = _safe_int(action_payload.get("textChars"))
        changes = [
            {
                "label": "桌面动作",
                "before": "未执行",
                "after": action,
            },
            {
                "label": "目标快照",
                "before": _bounded_text(action_payload.get("snapshotId"), maximum=80),
                "after": f"revision {_safe_int(action_payload.get('revision'))}",
            },
        ]
        if text_chars > 0:
            changes.append(
                {
                    "label": "输入文本",
                    "before": "未输入",
                    "after": f"{text_chars} 个字符（内容不在审批摘要显示）",
                }
            )
        preview = {
            "title": "确认桌面操作",
            "summary": summary,
            "operationLabel": "执行 Accessibility 语义动作",
            "changes": changes,
            "actionPayload": action_payload,
            "baseState": base_state,
        }
        approval = self.sessions.create_approval(
            session_id=session_id,
            tool_name="desktop_semantic",
            operation="act",
            payload_sha256=digest,
            preview=preview,
            risk_level=risk_level,
            ttl_ms=30_000,
        )
        return {
            "summary": f"等待确认：{summary}",
            "approvalRequired": True,
            "approvalId": approval["approvalId"],
            "approval": approval,
        }

    def _apply_desktop_action(self, approval: Mapping[str, object]) -> dict[str, object]:
        preview = approval.get("preview") if isinstance(approval.get("preview"), Mapping) else {}
        action_payload = (
            preview.get("actionPayload")
            if isinstance(preview.get("actionPayload"), Mapping)
            else {}
        )
        base_state = (
            preview.get("baseState")
            if isinstance(preview.get("baseState"), Mapping)
            else {}
        )
        expected_digest = _approval_payload_digest(
            session_id=str(approval.get("sessionId") or ""),
            tool="desktop_semantic",
            operation="act",
            action_payload=action_payload,
            base_state=base_state,
        )
        if expected_digest != str(approval.get("payloadSha256") or ""):
            raise ValueError("desktop approval no longer matches its preview")
        receipt = self.desktop_client.act(  # type: ignore[attr-defined]
            action_payload=action_payload,
            base_state=base_state,
        )
        if not isinstance(receipt, Mapping):
            raise ValueError("desktop action receipt is invalid")
        return {
            "summary": (
                f"桌面动作 {_bounded_text(action_payload.get('action'), maximum=80)} 已执行，"
                "并已重新读取窗口语义状态"
            ),
            "presentationKind": "desktop_snapshot",
            "approvalId": str(approval.get("approvalId") or ""),
            "receipt": dict(receipt),
        }

    def _prepare_memory_mutation(
        self,
        *,
        session_id: str,
        operation: str,
        args: Mapping[str, object],
        risk_level: str,
    ) -> dict[str, object]:
        run_id = _bounded_text(args.get("runId"), maximum=240)
        if not run_id:
            raise ValueError(f"runId is required for ime_memory.{operation}")
        visible_owners, mutable_owner = self._memory_owner_context(session_id)
        review = self._facade_call(
            "agent_memory_maintenance_run",
            {
                "runId": run_id,
                "project": self.project,
                "visibleOwners": _owner_payloads(visible_owners),
            },
        )
        run = review.get("run") if isinstance(review.get("run"), Mapping) else {}
        run_owner = _memory_run_owner(run)
        if run_owner not in _memory_mutation_owners(
            visible_owners,
            mutable_owner=mutable_owner,
        ):
            raise ValueError("memory run is outside the current writable owner scope")
        applying = operation == "maintenance_apply"
        if applying and review.get("canApply") is not True:
            raise ValueError("memory draft is not currently applicable")
        if not applying and review.get("canRollback") is not True:
            raise ValueError("memory run is not currently rollbackable")
        revision_hash = _bounded_text(review.get("revisionHash"), maximum=96)
        if not revision_hash:
            raise ValueError("memory run revision is unavailable")
        action_payload = {
            "runId": run_id,
            "project": self.project,
            "expectedOwnerKind": run_owner[0],
            "expectedOwnerId": run_owner[1],
        }
        base_state = {
            "revisionHash": revision_hash,
            "status": _bounded_text(run.get("status"), maximum=40),
            "bundleHash": _bounded_text(run.get("bundleHash"), maximum=96),
        }
        digest = _approval_payload_digest(
            session_id=session_id,
            tool="ime_memory",
            operation=operation,
            action_payload=action_payload,
            base_state=base_state,
        )
        pending_count = _safe_int(run.get("pendingDiffCount"))
        applied_count = _safe_int(run.get("appliedDiffCount"))
        diff_count = _safe_int(run.get("diffCount"))
        before_status = _memory_run_status_label(str(run.get("status") or ""))
        after_status = "已应用" if applying else "已回滚"
        operation_label = "应用记忆草案" if applying else "回滚记忆整理"
        summary = (
            f"将应用草案 {run_id} 的 {pending_count} 项已选差异"
            if applying
            else f"将回滚整理 {run_id} 的 {applied_count} 项已应用差异"
        )
        source_cursor = run.get("sourceCursor") if isinstance(run.get("sourceCursor"), Mapping) else {}
        from_event = _safe_int(source_cursor.get("fromEventId"))
        to_event = _safe_int(source_cursor.get("toEventId"))
        changes = [
            {"label": "整理状态", "before": before_status, "after": after_status},
            {
                "label": "记忆差异",
                "before": f"{diff_count} 项草案",
                "after": f"{pending_count if applying else applied_count} 项{after_status}",
            },
        ]
        if to_event > 0:
            changes.append(
                {
                    "label": "证据范围",
                    "before": f"事件 {from_event or 1}",
                    "after": f"事件 {to_event}",
                }
            )
        review_changes = run.get("changes") if isinstance(run.get("changes"), list) else []
        for item in review_changes[:3]:
            if not isinstance(item, Mapping) or item.get("selected") is False:
                continue
            title = _bounded_text(item.get("title"), maximum=80) or "记忆差异"
            label = _bounded_text(item.get("operationLabel"), maximum=40) or "整理记忆"
            changes.append(
                {
                    "label": title,
                    "before": "待审阅" if applying else "已应用",
                    "after": label if applying else "恢复应用前状态",
                }
            )
        preview = {
            "title": f"确认{operation_label}",
            "summary": summary,
            "operationLabel": operation_label,
            "changes": changes,
            "actionPayload": action_payload,
            "baseState": base_state,
        }
        approval = self.sessions.create_approval(
            session_id=session_id,
            tool_name="ime_memory",
            operation=operation,
            payload_sha256=digest,
            preview=preview,
            risk_level=risk_level,
            ttl_ms=60_000,
        )
        return {
            "summary": f"等待确认：{summary}",
            "approvalRequired": True,
            "approvalId": approval["approvalId"],
            "approval": approval,
        }

    def _apply_memory_mutation(self, approval: Mapping[str, object]) -> dict[str, object]:
        tool = str(approval.get("toolId") or "")
        operation = str(approval.get("operation") or "")
        preview = approval.get("preview") if isinstance(approval.get("preview"), Mapping) else {}
        action_payload = preview.get("actionPayload") if isinstance(preview.get("actionPayload"), Mapping) else {}
        base_state = preview.get("baseState") if isinstance(preview.get("baseState"), Mapping) else {}
        expected_digest = _approval_payload_digest(
            session_id=str(approval.get("sessionId") or ""),
            tool=tool,
            operation=operation,
            action_payload=action_payload,
            base_state=base_state,
        )
        if expected_digest != str(approval.get("payloadSha256") or ""):
            raise ValueError("approval payload no longer matches its preview")
        run_id = _bounded_text(action_payload.get("runId"), maximum=240)
        project = _bounded_text(action_payload.get("project"), maximum=160)
        expected_owner = (
            _bounded_text(action_payload.get("expectedOwnerKind"), maximum=40),
            _bounded_text(action_payload.get("expectedOwnerId"), maximum=160),
        )
        if not run_id or project != self.project:
            raise ValueError("approved memory action payload is invalid")
        if not all(expected_owner):
            raise ValueError("approved memory owner is invalid")
        session_id = _bounded_text(approval.get("sessionId"), maximum=240)
        visible_owners, mutable_owner = self._memory_owner_context(session_id)
        if expected_owner not in _memory_mutation_owners(
            visible_owners,
            mutable_owner=mutable_owner,
        ):
            raise ValueError("approved memory owner is no longer writable by this session")
        current = self._facade_call(
            "agent_memory_maintenance_run",
            {
                "runId": run_id,
                "project": self.project,
                "visibleOwners": _owner_payloads(visible_owners),
            },
        )
        current_run = current.get("run") if isinstance(current.get("run"), Mapping) else {}
        _require_memory_run_owner(current_run, expected_owner)
        if (
            _bounded_text(current.get("revisionHash"), maximum=96)
            != _bounded_text(base_state.get("revisionHash"), maximum=96)
            or _bounded_text(_mapping_value(current, "run", "status"), maximum=40)
            != _bounded_text(base_state.get("status"), maximum=40)
        ):
            raise ValueError("memory draft changed after the approval preview was created")
        applying = operation == "maintenance_apply"
        if applying and current.get("canApply") is not True:
            raise ValueError("memory draft is no longer applicable")
        if not applying and current.get("canRollback") is not True:
            raise ValueError("memory run is no longer rollbackable")
        action_result = self._facade_call(
            "knowledge_workbench_database_apply" if applying else "knowledge_workbench_database_rollback",
            {
                "runId": run_id,
                "confirm": "apply" if applying else "rollback",
                "expectedOwnerKind": expected_owner[0],
                "expectedOwnerId": expected_owner[1],
            },
        )
        if action_result.get("ok") is not True:
            raise ValueError(_bounded_text(action_result.get("error"), maximum=240) or "memory action failed")
        after = self._facade_call(
            "agent_memory_maintenance_run",
            {
                "runId": run_id,
                "project": self.project,
                "visibleOwners": _owner_payloads(visible_owners),
            },
        )
        after_run = after.get("run") if isinstance(after.get("run"), Mapping) else {}
        _require_memory_run_owner(after_run, expected_owner)
        after_status = _bounded_text(after_run.get("status"), maximum=40)
        mutation_applied = (
            after_status in {"applied", "partial"}
            if applying
            else after_status == "rolled_back"
        )
        if not mutation_applied:
            raise ValueError(f"memory action ended in unexpected status: {after_status or 'unknown'}")
        diff_count = (
            _safe_int(after_run.get("appliedDiffCount"))
            if applying
            else _safe_int(_mapping_value(current, "run", "appliedDiffCount"))
        )
        receipt = {
            "schemaVersion": "rag-ime.agent-operation-receipt.v1",
            "mutationApplied": True,
            "approvalId": str(approval.get("approvalId") or ""),
            "toolId": tool,
            "operation": operation,
            "auditId": str(approval.get("approvalId") or ""),
            "runId": run_id,
            "status": after_status,
            "diffCount": diff_count,
            "summary": (
                f"已应用记忆草案，共写入 {diff_count} 项差异"
                if applying
                else f"已回滚记忆整理，共恢复 {diff_count} 项差异"
            ),
            "undoAvailable": applying,
        }
        if applying:
            receipt["rollback"] = {
                "tool": "ime_memory",
                "operation": "maintenance_rollback",
                "args": {"runId": run_id},
            }
        else:
            receipt["revertedRunId"] = run_id
        return receipt

    def _prepare_governed_memory_mutation(
        self,
        *,
        session_id: str,
        operation: str,
        args: Mapping[str, object],
        risk_level: str,
    ) -> dict[str, object]:
        proposal_id = _bounded_text(args.get("proposalId"), maximum=240)
        if not proposal_id:
            raise ValueError(f"proposalId is required for ime_memory.{operation}")
        store = self._governed_memory_store()
        if operation == "governance_rollback":
            prepared = store.prepare_rollback(
                proposal_id=proposal_id,
                session_id=session_id,
            )
        else:
            prepared = store.prepare_apply(
                operation,
                proposal_id=proposal_id,
                session_id=session_id,
            )
        action_payload = (
            prepared.get("actionPayload")
            if isinstance(prepared.get("actionPayload"), Mapping)
            else {}
        )
        base_state = (
            prepared.get("baseState")
            if isinstance(prepared.get("baseState"), Mapping)
            else {}
        )
        digest = _approval_payload_digest(
            session_id=session_id,
            tool="ime_memory",
            operation=operation,
            action_payload=action_payload,
            base_state=base_state,
        )
        preview = {
            "title": _bounded_text(prepared.get("title"), maximum=160),
            "summary": _bounded_text(prepared.get("summary"), maximum=400),
            "operationLabel": _bounded_text(
                prepared.get("operationLabel"),
                maximum=80,
            ),
            "changes": _safe_payload(prepared.get("changes")),
            "actionPayload": dict(action_payload),
            "baseState": dict(base_state),
        }
        approval = self.sessions.create_approval(
            session_id=session_id,
            tool_name="ime_memory",
            operation=operation,
            payload_sha256=digest,
            preview=preview,
            risk_level=risk_level,
            ttl_ms=60_000,
        )
        return {
            "summary": f"等待确认：{preview['summary']}",
            "approvalRequired": True,
            "approvalId": approval["approvalId"],
            "approval": approval,
        }

    def _apply_governed_memory_mutation(
        self,
        approval: Mapping[str, object],
    ) -> dict[str, object]:
        operation = str(approval.get("operation") or "")
        preview = (
            approval.get("preview")
            if isinstance(approval.get("preview"), Mapping)
            else {}
        )
        action_payload = (
            preview.get("actionPayload")
            if isinstance(preview.get("actionPayload"), Mapping)
            else {}
        )
        base_state = (
            preview.get("baseState")
            if isinstance(preview.get("baseState"), Mapping)
            else {}
        )
        expected_digest = _approval_payload_digest(
            session_id=str(approval.get("sessionId") or ""),
            tool="ime_memory",
            operation=operation,
            action_payload=action_payload,
            base_state=base_state,
        )
        if expected_digest != str(approval.get("payloadSha256") or ""):
            raise ValueError("approval payload no longer matches its preview")
        proposal_id = _bounded_text(action_payload.get("proposalId"), maximum=240)
        payload_sha256 = _bounded_text(
            action_payload.get("payloadSha256"),
            maximum=64,
        )
        if not proposal_id or len(payload_sha256) != 64:
            raise ValueError("approved memory proposal payload is invalid")
        store = self._governed_memory_store()
        if operation == "governance_rollback":
            rollback_state_sha256 = _bounded_text(
                base_state.get("rollbackStateSha256"),
                maximum=64,
            )
            if len(rollback_state_sha256) != 64:
                raise ValueError("approved memory rollback state is invalid")
            return store.rollback(
                proposal_id=proposal_id,
                session_id=str(approval.get("sessionId") or ""),
                approval_id=str(approval.get("approvalId") or ""),
                expected_state_sha256=rollback_state_sha256,
            )
        return store.apply(
            operation,
            proposal_id=proposal_id,
            session_id=str(approval.get("sessionId") or ""),
            approval_id=str(approval.get("approvalId") or ""),
        )

    def _prepare_input_settings(
        self,
        *,
        session_id: str,
        operation: str,
        args: Mapping[str, object],
        risk_level: str,
    ) -> dict[str, object]:
        snapshot = self._input_settings_snapshot()
        current_flat = flatten_settings(snapshot["settings"])
        source_approval_id = ""
        if operation == "rollback_settings":
            source = self._settings_rollback_source(
                session_id=session_id,
                source_approval_id=_bounded_text(args.get("sourceApprovalId"), maximum=240),
            )
            receipt = source.get("receipt") if isinstance(source.get("receipt"), Mapping) else {}
            previous_values = (
                receipt.get("beforeValues") if isinstance(receipt.get("beforeValues"), Mapping) else {}
            )
            applied_values = (
                receipt.get("afterValues") if isinstance(receipt.get("afterValues"), Mapping) else {}
            )
            if not previous_values or set(previous_values) != set(applied_values):
                raise ValueError("settings rollback receipt is incomplete")
            for key, value in applied_values.items():
                if current_flat.get(str(key)) != value:
                    raise ValueError("input settings changed after the source operation")
            normalized = _normalize_input_setting_changes(
                [{"key": key, "value": value} for key, value in previous_values.items()]
            )
            source_approval_id = str(source.get("approvalId") or "")
        else:
            normalized = _normalize_input_setting_changes(args.get("changes"))

        actual = [
            item
            for item in normalized
            if current_flat.get(str(item["key"])) != item["value"]
        ]
        if not actual:
            raise ValueError("input settings already match the requested values")
        before_values = {str(item["key"]): current_flat.get(str(item["key"])) for item in actual}
        after_values = {str(item["key"]): item["value"] for item in actual}
        action_payload: dict[str, object] = {"changes": actual}
        if source_approval_id:
            action_payload["sourceApprovalId"] = source_approval_id
        base_state = {
            "settingsHash": snapshot["settingsHash"],
            "values": before_values,
        }
        digest = _approval_payload_digest(
            session_id=session_id,
            tool="ime_input",
            operation=operation,
            action_payload=action_payload,
            base_state=base_state,
        )
        rolling_back = operation == "rollback_settings"
        operation_label = "撤销输入设置变更" if rolling_back else "应用输入设置"
        preview = {
            "title": f"确认{operation_label}",
            "summary": (
                f"将恢复 {len(actual)} 项输入设置"
                if rolling_back
                else f"将更新 {len(actual)} 项输入设置"
            ),
            "operationLabel": operation_label,
            "changes": [
                {
                    "label": _input_setting_label(str(item["key"])),
                    "path": str(item["key"]),
                    "before": before_values[str(item["key"])],
                    "after": item["value"],
                }
                for item in actual
            ],
            "actionPayload": action_payload,
            "baseState": base_state,
        }
        approval = self.sessions.create_approval(
            session_id=session_id,
            tool_name="ime_input",
            operation=operation,
            payload_sha256=digest,
            preview=preview,
            risk_level=risk_level,
            ttl_ms=60_000,
        )
        return {
            "summary": f"等待确认：{preview['summary']}",
            "approvalRequired": True,
            "approvalId": approval["approvalId"],
            "approval": approval,
        }

    def _apply_input_settings(self, approval: Mapping[str, object]) -> dict[str, object]:
        tool = str(approval.get("toolId") or "")
        operation = str(approval.get("operation") or "")
        preview = approval.get("preview") if isinstance(approval.get("preview"), Mapping) else {}
        action_payload = preview.get("actionPayload") if isinstance(preview.get("actionPayload"), Mapping) else {}
        base_state = preview.get("baseState") if isinstance(preview.get("baseState"), Mapping) else {}
        expected_digest = _approval_payload_digest(
            session_id=str(approval.get("sessionId") or ""),
            tool=tool,
            operation=operation,
            action_payload=action_payload,
            base_state=base_state,
        )
        if expected_digest != str(approval.get("payloadSha256") or ""):
            raise ValueError("approval payload no longer matches its preview")
        normalized = _normalize_input_setting_changes(action_payload.get("changes"))
        snapshot = self._input_settings_snapshot()
        if snapshot["settingsHash"] != str(base_state.get("settingsHash") or ""):
            raise ValueError("input settings changed after the approval preview was created")
        current_flat = flatten_settings(snapshot["settings"])
        before_values = base_state.get("values") if isinstance(base_state.get("values"), Mapping) else {}
        if not before_values or any(current_flat.get(str(key)) != value for key, value in before_values.items()):
            raise ValueError("input settings no longer match the approval preview")
        source_approval_id = _bounded_text(action_payload.get("sourceApprovalId"), maximum=240)
        if operation == "rollback_settings":
            self._settings_rollback_source(
                session_id=str(approval.get("sessionId") or ""),
                source_approval_id=source_approval_id,
            )

        updates = {str(item["key"]): item["value"] for item in normalized}
        result = self._facade_call(
            "settings_update",
            {**updates, "updatedBy": "pi-control-agent"},
        )
        if result.get("ok") is False:
            raise ValueError(_bounded_text(result.get("error"), maximum=240) or "settings update failed")
        changed_keys = sorted(str(value) for value in result.get("changedKeys", []) if str(value))
        expected_keys = sorted(updates)
        if changed_keys != expected_keys:
            raise ValueError("settings update did not apply the exact approved keys")
        after_snapshot = self._input_settings_snapshot()
        after_flat = flatten_settings(after_snapshot["settings"])
        if any(after_flat.get(key) != value for key, value in updates.items()):
            raise ValueError("settings update could not be verified")

        rolling_back = operation == "rollback_settings"
        receipt: dict[str, object] = {
            "schemaVersion": "rag-ime.agent-operation-receipt.v1",
            "mutationApplied": True,
            "approvalId": str(approval.get("approvalId") or ""),
            "toolId": "ime_input",
            "operation": operation,
            "auditId": _safe_int(result.get("auditId")),
            "summary": (
                f"已恢复 {len(expected_keys)} 项输入设置"
                if rolling_back
                else f"已更新 {len(expected_keys)} 项输入设置"
            ),
            "settingKeys": expected_keys,
            "changeCount": len(expected_keys),
            "beforeValues": {key: before_values[key] for key in expected_keys},
            "afterValues": {key: updates[key] for key in expected_keys},
            "settingsHash": after_snapshot["settingsHash"],
            "settingsRevision": _bounded_text(result.get("settingsRevision"), maximum=96),
            "runtimeRevision": _safe_int(result.get("runtimeRevision")),
            "undoAvailable": not rolling_back,
        }
        if rolling_back:
            receipt["revertedSettingsApprovalId"] = source_approval_id
        else:
            receipt["rollback"] = {
                "toolId": "ime_input",
                "operation": "rollback_settings",
                "args": {"sourceApprovalId": str(approval.get("approvalId") or "")},
                "requiresApproval": True,
            }
        return receipt

    def _input_settings_snapshot(self) -> dict[str, object]:
        payload = self._facade_call("settings")
        settings = payload.get("settings") if isinstance(payload.get("settings"), Mapping) else {}
        settings_hash = _bounded_text(payload.get("settingsHash"), maximum=96)
        if not settings_hash:
            settings_hash = hashlib.sha256(
                json.dumps(settings, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
        return {"settings": dict(settings), "settingsHash": settings_hash}

    def _settings_rollback_source(
        self,
        *,
        session_id: str,
        source_approval_id: str,
    ) -> dict[str, object]:
        if not source_approval_id:
            raise ValueError("sourceApprovalId is required for ime_input.rollback_settings")
        approvals = self.sessions.list_approvals(session_id=session_id, state="applied", limit=500)
        for item in approvals:
            receipt = item.get("receipt") if isinstance(item.get("receipt"), Mapping) else {}
            if str(receipt.get("revertedSettingsApprovalId") or "") == source_approval_id:
                raise ValueError("settings change has already been rolled back")
        for item in approvals:
            receipt = item.get("receipt") if isinstance(item.get("receipt"), Mapping) else {}
            if (
                str(item.get("approvalId") or "") == source_approval_id
                and str(item.get("toolId") or "") == "ime_input"
                and str(item.get("operation") or "") == "apply_settings"
                and receipt.get("undoAvailable") is True
            ):
                return item
        raise ValueError("settings change is not backed by an applied approval receipt")

    def _prepare_lexicon_mutation(
        self,
        *,
        session_id: str,
        operation: str,
        args: Mapping[str, object],
        risk_level: str,
    ) -> dict[str, object]:
        if operation == "lexicon_rollback":
            source = self._lexicon_rollback_source(
                session_id=session_id,
                source_approval_id=_bounded_text(args.get("sourceApprovalId"), maximum=240),
            )
            receipt = source.get("receipt") if isinstance(source.get("receipt"), Mapping) else {}
            rollback_id = _bounded_text(receipt.get("rollbackId"), maximum=240)
            entry_count = _safe_int(receipt.get("entryCount"))
            if not rollback_id:
                raise ValueError("lexicon rollback receipt is incomplete")
            action_payload = {
                "sourceApprovalId": str(source.get("approvalId") or ""),
                "rollbackId": rollback_id,
            }
            base_state = {
                "rollbackIdSha256": _sha256_text(rollback_id),
                "entryCount": entry_count,
            }
            summary = f"将恢复应用前的词表，并撤销 {entry_count} 条个人词条"
            changes = [
                {
                    "label": "个人词表",
                    "before": f"已应用 {entry_count} 条建议",
                    "after": "恢复应用前版本",
                }
            ]
            operation_label = "回滚个人词表"
        else:
            limit = _bounded_int(args.get("limit"), default=100, minimum=1, maximum=100)
            selected_keys = _review_key_list(args.get("selectedKeys"), limit=100)
            if not selected_keys:
                raise ValueError("selectedKeys is required for ime_input.lexicon_apply")
            review = self._facade_call(
                "rime_lexicon_review",
                {"project": self.project, "limit": limit},
            )
            entries = review.get("entries") if isinstance(review.get("entries"), list) else []
            entry_by_key = {
                str(item.get("reviewKey") or f"{item.get('text', '')}\t{item.get('pinyin', '')}"): item
                for item in entries
                if isinstance(item, Mapping)
            }
            unknown = [key for key in selected_keys if key not in entry_by_key]
            if unknown:
                raise ValueError("selected lexicon entries changed; review them again")
            token = str(review.get("reviewToken") or "")
            if not token:
                raise ValueError("lexicon review token is unavailable")
            selected_entries = [entry_by_key[key] for key in selected_keys]
            action_payload = {
                "project": self.project,
                "limit": limit,
                "selectedKeys": selected_keys,
            }
            base_state = {
                "reviewTokenSha256": _sha256_text(token),
                "selectedEntriesSha256": _sha256_json(selected_entries),
            }
            summary = f"将把 {len(selected_entries)} 条已审阅建议增量加入个人词表"
            changes = [
                {
                    "label": _bounded_text(item.get("text"), maximum=80) or "个人词条",
                    "before": "未加入",
                    "after": _bounded_text(item.get("pinyin"), maximum=120) or "加入个人词表",
                }
                for item in selected_entries[:8]
            ]
            operation_label = "应用已审词条并重新部署"

        digest = _approval_payload_digest(
            session_id=session_id,
            tool="ime_input",
            operation=operation,
            action_payload=action_payload,
            base_state=base_state,
        )
        preview = {
            "title": f"确认{operation_label}",
            "summary": summary,
            "operationLabel": operation_label,
            "changes": changes,
            "actionPayload": action_payload,
            "baseState": base_state,
        }
        approval = self.sessions.create_approval(
            session_id=session_id,
            tool_name="ime_input",
            operation=operation,
            payload_sha256=digest,
            preview=preview,
            risk_level=risk_level,
            ttl_ms=60_000,
        )
        return {
            "summary": f"等待确认：{summary}",
            "approvalRequired": True,
            "approvalId": approval["approvalId"],
            "approval": approval,
        }

    def _apply_lexicon_mutation(self, approval: Mapping[str, object]) -> dict[str, object]:
        operation = str(approval.get("operation") or "")
        preview = approval.get("preview") if isinstance(approval.get("preview"), Mapping) else {}
        action_payload = preview.get("actionPayload") if isinstance(preview.get("actionPayload"), Mapping) else {}
        base_state = preview.get("baseState") if isinstance(preview.get("baseState"), Mapping) else {}
        expected_digest = _approval_payload_digest(
            session_id=str(approval.get("sessionId") or ""),
            tool="ime_input",
            operation=operation,
            action_payload=action_payload,
            base_state=base_state,
        )
        if expected_digest != str(approval.get("payloadSha256") or ""):
            raise ValueError("approval payload no longer matches its preview")

        rolling_back = operation == "lexicon_rollback"
        source_approval_id = _bounded_text(action_payload.get("sourceApprovalId"), maximum=240)
        if rolling_back:
            source = self._lexicon_rollback_source(
                session_id=str(approval.get("sessionId") or ""),
                source_approval_id=source_approval_id,
            )
            source_receipt = source.get("receipt") if isinstance(source.get("receipt"), Mapping) else {}
            rollback_id = _bounded_text(action_payload.get("rollbackId"), maximum=240)
            if (
                not rollback_id
                or rollback_id != _bounded_text(source_receipt.get("rollbackId"), maximum=240)
                or _sha256_text(rollback_id) != str(base_state.get("rollbackIdSha256") or "")
            ):
                raise ValueError("lexicon rollback no longer matches its source receipt")
            result = self._facade_call("rime_lexicon_rollback", {"rollbackId": rollback_id})
            if result.get("ok") is not True or result.get("rolledBack") is not True:
                raise ValueError(
                    _bounded_text(result.get("reason") or result.get("error"), maximum=240)
                    or "lexicon rollback failed"
                )
            entry_count = _safe_int(source_receipt.get("entryCount"))
        else:
            limit = _bounded_int(action_payload.get("limit"), default=100, minimum=1, maximum=100)
            selected_keys = _review_key_list(action_payload.get("selectedKeys"), limit=100)
            review = self._facade_call(
                "rime_lexicon_review",
                {"project": self.project, "limit": limit},
            )
            token = str(review.get("reviewToken") or "")
            entries = review.get("entries") if isinstance(review.get("entries"), list) else []
            entry_by_key = {
                str(item.get("reviewKey") or f"{item.get('text', '')}\t{item.get('pinyin', '')}"): item
                for item in entries
                if isinstance(item, Mapping)
            }
            selected_entries = [entry_by_key[key] for key in selected_keys if key in entry_by_key]
            if (
                not token
                or _sha256_text(token) != str(base_state.get("reviewTokenSha256") or "")
                or len(selected_entries) != len(selected_keys)
                or _sha256_json(selected_entries) != str(base_state.get("selectedEntriesSha256") or "")
            ):
                raise ValueError("lexicon review changed after the approval preview was created")
            result = self._facade_call(
                "rime_lexicon_apply",
                {
                    "project": self.project,
                    "limit": limit,
                    "reviewToken": token,
                    "selectedKeys": selected_keys,
                    "confirmText": str(review.get("confirmText") or ""),
                },
            )
            if result.get("ok") is not True or result.get("applied") is not True:
                raise ValueError(
                    _bounded_text(result.get("reason") or result.get("error"), maximum=240)
                    or "lexicon apply failed"
                )
            rollback_id = _bounded_text(result.get("rollbackId"), maximum=240)
            entry_count = _safe_int(result.get("entryCount"))
            if not rollback_id:
                raise ValueError("lexicon apply returned no rollback receipt")

        deployment = self._redeploy_rime_and_wait()
        deployment_status = _bounded_text(deployment.get("status"), maximum=80)
        deployed = deployment_status == "succeeded"
        receipt: dict[str, object] = {
            "schemaVersion": "rag-ime.agent-operation-receipt.v1",
            "mutationApplied": True,
            "approvalId": str(approval.get("approvalId") or ""),
            "toolId": "ime_input",
            "operation": operation,
            "auditId": str(approval.get("approvalId") or ""),
            "summary": (
                f"已回滚个人词表并重新部署，共恢复 {entry_count} 条词条"
                if rolling_back and deployed
                else f"已应用并重新部署 {entry_count} 条个人词条"
                if deployed
                else f"词表文件已更新，但重新部署未完成；共 {entry_count} 条词条"
            ),
            "entryCount": entry_count,
            "rollbackId": rollback_id,
            "deploymentJobId": _bounded_text(deployment.get("jobId"), maximum=240),
            "deploymentStatus": deployment_status or "unknown",
            "status": "applied" if deployed else "partial",
            "undoAvailable": not rolling_back,
        }
        if not deployed:
            receipt["warning"] = _bounded_text(
                deployment.get("error") or "Rime 重新部署未成功，请在诊断页处理后再验证候选",
                maximum=240,
            )
        if rolling_back:
            receipt["revertedLexiconApprovalId"] = source_approval_id
        else:
            receipt["rollback"] = {
                "toolId": "ime_input",
                "operation": "lexicon_rollback",
                "args": {"sourceApprovalId": str(approval.get("approvalId") or "")},
                "requiresApproval": True,
            }
        return receipt

    def _lexicon_rollback_source(
        self,
        *,
        session_id: str,
        source_approval_id: str,
    ) -> dict[str, object]:
        if not source_approval_id:
            raise ValueError("sourceApprovalId is required for ime_input.lexicon_rollback")
        approvals = self.sessions.list_approvals(session_id=session_id, state="applied", limit=500)
        for item in approvals:
            receipt = item.get("receipt") if isinstance(item.get("receipt"), Mapping) else {}
            if str(receipt.get("revertedLexiconApprovalId") or "") == source_approval_id:
                raise ValueError("lexicon change has already been rolled back")
        for item in approvals:
            receipt = item.get("receipt") if isinstance(item.get("receipt"), Mapping) else {}
            if (
                str(item.get("approvalId") or "") == source_approval_id
                and str(item.get("toolId") or "") == "ime_input"
                and str(item.get("operation") or "") == "lexicon_apply"
                and receipt.get("undoAvailable") is True
                and _bounded_text(receipt.get("rollbackId"), maximum=1)
            ):
                return item
        raise ValueError("lexicon change is not backed by an applied approval receipt")

    def _voice_provider_snapshot(self) -> dict[str, object]:
        payload = self.management.provider_configuration()
        providers = payload.get("providers") if isinstance(payload.get("providers"), Mapping) else {}
        voice = providers.get("voice") if isinstance(providers.get("voice"), Mapping) else {}
        provider = _bounded_text(voice.get("provider"), maximum=80) or "native_streaming"
        return {
            "configurationHash": _bounded_text(payload.get("configurationHash"), maximum=96),
            "provider": provider,
            "settingsRevision": _bounded_text(payload.get("settingsRevision"), maximum=96),
            "runtimeRevision": _safe_int(payload.get("runtimeRevision")),
        }

    @staticmethod
    def _normalize_voice_provider(value: object) -> str:
        provider = _bounded_text(value, maximum=80)
        if provider not in {"native_streaming", "realtime_websocket", "http_transcription"}:
            raise ValueError("voice provider is unsupported")
        return provider

    def _prepare_voice_provider_mutation(
        self,
        *,
        session_id: str,
        operation: str,
        args: Mapping[str, object],
        risk_level: str,
    ) -> dict[str, object]:
        snapshot = self._voice_provider_snapshot()
        current = str(snapshot["provider"])
        source_approval_id = ""
        if operation == "provider_rollback":
            source = self._voice_provider_rollback_source(
                session_id=session_id,
                source_approval_id=_bounded_text(args.get("sourceApprovalId"), maximum=240),
            )
            receipt = source.get("receipt") if isinstance(source.get("receipt"), Mapping) else {}
            if current != str(receipt.get("afterProvider") or ""):
                raise ValueError("voice provider changed after the source operation")
            desired = self._normalize_voice_provider(receipt.get("beforeProvider"))
            source_approval_id = str(source.get("approvalId") or "")
        else:
            allowed = {"op", "provider"}
            unknown = sorted(str(key) for key in set(args) - allowed)
            if unknown:
                raise ValueError(f"unsupported voice provider field: {unknown[0]}")
            desired = self._normalize_voice_provider(args.get("provider"))
        if desired == current:
            raise ValueError("voice provider already matches the requested value")
        action_payload: dict[str, object] = {"provider": desired}
        if source_approval_id:
            action_payload["sourceApprovalId"] = source_approval_id
        base_state = {
            "configurationHash": snapshot["configurationHash"],
            "provider": current,
        }
        digest = _approval_payload_digest(
            session_id=session_id,
            tool="ime_voice",
            operation=operation,
            action_payload=action_payload,
            base_state=base_state,
        )
        rolling_back = operation == "provider_rollback"
        preview = {
            "title": "确认恢复语音 Provider" if rolling_back else "确认切换语音 Provider",
            "summary": "只切换已配置的语音服务；不会读取、写入或显示任何凭据",
            "operationLabel": "恢复语音 Provider" if rolling_back else "切换语音 Provider",
            "changes": [
                {
                    "label": "语音服务",
                    "path": "voice.provider",
                    "before": current,
                    "after": desired,
                }
            ],
            "actionPayload": action_payload,
            "baseState": base_state,
            "secretsPreserved": True,
            "restartComponent": "voice",
        }
        approval = self.sessions.create_approval(
            session_id=session_id,
            tool_name="ime_voice",
            operation=operation,
            payload_sha256=digest,
            preview=preview,
            risk_level=risk_level,
            ttl_ms=60_000,
        )
        return {
            "summary": f"等待确认：{preview['summary']}",
            "approvalRequired": True,
            "approvalId": approval["approvalId"],
            "approval": approval,
        }

    def _apply_voice_provider_mutation(self, approval: Mapping[str, object]) -> dict[str, object]:
        operation = str(approval.get("operation") or "")
        preview = approval.get("preview") if isinstance(approval.get("preview"), Mapping) else {}
        action_payload = preview.get("actionPayload") if isinstance(preview.get("actionPayload"), Mapping) else {}
        base_state = preview.get("baseState") if isinstance(preview.get("baseState"), Mapping) else {}
        expected_digest = _approval_payload_digest(
            session_id=str(approval.get("sessionId") or ""),
            tool="ime_voice",
            operation=operation,
            action_payload=action_payload,
            base_state=base_state,
        )
        if expected_digest != str(approval.get("payloadSha256") or ""):
            raise ValueError("approval payload no longer matches its preview")
        snapshot = self._voice_provider_snapshot()
        if (
            snapshot["configurationHash"] != str(base_state.get("configurationHash") or "")
            or snapshot["provider"] != str(base_state.get("provider") or "")
        ):
            raise ValueError("voice provider changed after the approval preview was created")
        desired = self._normalize_voice_provider(action_payload.get("provider"))
        source_approval_id = _bounded_text(action_payload.get("sourceApprovalId"), maximum=240)
        if operation == "provider_rollback":
            self._voice_provider_rollback_source(
                session_id=str(approval.get("sessionId") or ""),
                source_approval_id=source_approval_id,
            )
        result = self.management.provider_configuration_apply(
            {
                "slot": "voice",
                "provider": desired,
                "expectedConfigurationHash": snapshot["configurationHash"],
            }
        )
        after = result.get("after") if isinstance(result.get("after"), Mapping) else {}
        if str(after.get("provider") or "") != desired:
            raise ValueError("voice provider update could not be verified")
        rolling_back = operation == "provider_rollback"
        receipt: dict[str, object] = {
            "schemaVersion": "rag-ime.agent-operation-receipt.v1",
            "mutationApplied": True,
            "approvalId": str(approval.get("approvalId") or ""),
            "toolId": "ime_voice",
            "operation": operation,
            "auditId": result.get("auditId") or str(approval.get("approvalId") or ""),
            "summary": (
                "语音 Provider 已恢复；重新启动语音代理后激活"
                if rolling_back
                else "语音 Provider 已保存；重新启动语音代理后激活"
            ),
            "beforeProvider": snapshot["provider"],
            "afterProvider": desired,
            "configurationHash": _bounded_text(result.get("configurationHash"), maximum=96),
            "restartComponent": "voice",
            "activationStatus": "pending_external_restart",
            "secretsPreserved": result.get("existingSecretPreserved") is True,
            "undoAvailable": not rolling_back,
        }
        if rolling_back:
            receipt["revertedVoiceProviderApprovalId"] = source_approval_id
        else:
            receipt["rollback"] = {
                "toolId": "ime_voice",
                "operation": "provider_rollback",
                "args": {"sourceApprovalId": str(approval.get("approvalId") or "")},
                "requiresApproval": True,
            }
        return receipt

    def _voice_provider_rollback_source(
        self,
        *,
        session_id: str,
        source_approval_id: str,
    ) -> dict[str, object]:
        if not source_approval_id:
            raise ValueError("sourceApprovalId is required for ime_voice.provider_rollback")
        approvals = self.sessions.list_approvals(session_id=session_id, state="applied", limit=500)
        for item in approvals:
            receipt = item.get("receipt") if isinstance(item.get("receipt"), Mapping) else {}
            if str(receipt.get("revertedVoiceProviderApprovalId") or "") == source_approval_id:
                raise ValueError("voice provider change has already been rolled back")
        for item in approvals:
            receipt = item.get("receipt") if isinstance(item.get("receipt"), Mapping) else {}
            if (
                str(item.get("approvalId") or "") == source_approval_id
                and str(item.get("toolId") or "") == "ime_voice"
                and str(item.get("operation") or "") == "provider_apply"
                and receipt.get("undoAvailable") is True
            ):
                return item
        raise ValueError("voice provider change is not backed by an applied approval receipt")

    def _model_profile_snapshot(self) -> dict[str, object]:
        payload = self.management.provider_configuration()
        configuration_hash = _bounded_text(payload.get("configurationHash"), maximum=96)
        providers = payload.get("providers") if isinstance(payload.get("providers"), Mapping) else {}
        profiles: dict[str, dict[str, str]] = {}
        for slot in ("instant", "knowledge"):
            raw = providers.get(slot) if isinstance(providers.get(slot), Mapping) else {}
            profiles[slot] = {
                "provider": _bounded_text(raw.get("provider"), maximum=80),
                "endpoint": _bounded_text(raw.get("endpoint"), maximum=320),
                "model": _bounded_text(raw.get("model"), maximum=200),
            }
        if not configuration_hash:
            configuration_hash = "sha256:" + _sha256_text(
                json.dumps(profiles, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            )
        return {
            "configurationHash": configuration_hash,
            "profiles": profiles,
            "settingsRevision": _bounded_text(payload.get("settingsRevision"), maximum=96),
            "runtimeRevision": _safe_int(payload.get("runtimeRevision")),
        }

    def _normalize_model_profile(
        self,
        *,
        slot: str,
        requested: Mapping[str, object],
        current: Mapping[str, object],
    ) -> dict[str, str]:
        if slot not in {"instant", "knowledge"}:
            raise ValueError("slot must be instant or knowledge")
        forbidden = {"apiKey", "accessToken", "headers", "headersJSON", "token", "secret"}
        if forbidden.intersection(requested):
            raise ValueError("model profile changes cannot include secrets or custom headers")
        profile = {
            key: _bounded_text(
                requested.get(key) if key in requested else current.get(key),
                maximum=320 if key == "endpoint" else 200,
            )
            for key in ("provider", "endpoint", "model")
        }
        allowed_providers = {
            "instant": {"mlx", "ollama", "openai-compatible"},
            "knowledge": {"deepseek", "openai-compatible"},
        }[slot]
        if profile["provider"] not in allowed_providers:
            raise ValueError(f"unsupported {slot} provider")
        try:
            parsed = urlsplit(profile["endpoint"])
            port = parsed.port
        except ValueError as exc:
            raise ValueError("provider endpoint is invalid") from exc
        if (
            parsed.scheme.lower() not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or port is not None and not (1 <= port <= 65_535)
        ):
            raise ValueError("provider endpoint must be a plain HTTP(S) URL without credentials or query")
        if profile["provider"] == "mlx" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("the managed MLX provider must use a loopback endpoint")
        if profile["provider"] != "mlx" and not profile["model"]:
            raise ValueError("model is required for the selected provider")
        return profile

    def _prepare_model_profile_mutation(
        self,
        *,
        session_id: str,
        operation: str,
        args: Mapping[str, object],
        risk_level: str,
    ) -> dict[str, object]:
        snapshot = self._model_profile_snapshot()
        profiles = snapshot["profiles"] if isinstance(snapshot.get("profiles"), Mapping) else {}
        source_approval_id = ""
        if operation == "profile_rollback":
            source = self._model_profile_rollback_source(
                session_id=session_id,
                source_approval_id=_bounded_text(args.get("sourceApprovalId"), maximum=240),
            )
            receipt = source.get("receipt") if isinstance(source.get("receipt"), Mapping) else {}
            slot = _bounded_text(receipt.get("slot"), maximum=40)
            before = receipt.get("beforeProfile") if isinstance(receipt.get("beforeProfile"), Mapping) else {}
            after = receipt.get("afterProfile") if isinstance(receipt.get("afterProfile"), Mapping) else {}
            current = profiles.get(slot) if isinstance(profiles.get(slot), Mapping) else {}
            if not before or not after or dict(current) != dict(after):
                raise ValueError("model provider profile changed after the source operation")
            desired = self._normalize_model_profile(slot=slot, requested=before, current=current)
            source_approval_id = str(source.get("approvalId") or "")
        else:
            allowed = {"op", "slot", "provider", "endpoint", "model"}
            unknown = sorted(str(key) for key in set(args) - allowed)
            if unknown:
                raise ValueError(f"unsupported model profile field: {unknown[0]}")
            slot = _bounded_text(args.get("slot"), maximum=40)
            current = profiles.get(slot) if isinstance(profiles.get(slot), Mapping) else {}
            desired = self._normalize_model_profile(slot=slot, requested=args, current=current)

        changes = [
            {
                "label": {"provider": "服务", "endpoint": "服务地址", "model": "模型"}[key],
                "path": f"{slot}.{key}",
                "before": current.get(key, ""),
                "after": desired[key],
            }
            for key in ("provider", "endpoint", "model")
            if current.get(key, "") != desired[key]
        ]
        if not changes:
            raise ValueError("model provider profile already matches the requested values")
        action_payload: dict[str, object] = {"slot": slot, "profile": desired}
        if source_approval_id:
            action_payload["sourceApprovalId"] = source_approval_id
        base_state = {
            "configurationHash": snapshot["configurationHash"],
            "profile": dict(current),
        }
        digest = _approval_payload_digest(
            session_id=session_id,
            tool="ime_models",
            operation=operation,
            action_payload=action_payload,
            base_state=base_state,
        )
        rolling_back = operation == "profile_rollback"
        slot_label = "即时补全" if slot == "instant" else "知识模型"
        preview = {
            "title": "确认恢复模型 Provider" if rolling_back else "确认更新模型 Provider",
            "summary": f"将{'恢复' if rolling_back else '更新'}{slot_label}的非密钥配置",
            "operationLabel": "恢复 Provider 配置" if rolling_back else "更新 Provider 配置",
            "changes": changes,
            "actionPayload": action_payload,
            "baseState": base_state,
            "secretsPreserved": True,
            "restartComponent": "predictor" if slot == "instant" else "sidecar",
        }
        approval = self.sessions.create_approval(
            session_id=session_id,
            tool_name="ime_models",
            operation=operation,
            payload_sha256=digest,
            preview=preview,
            risk_level=risk_level,
            ttl_ms=60_000,
        )
        return {
            "summary": f"等待确认：{preview['summary']}",
            "approvalRequired": True,
            "approvalId": approval["approvalId"],
            "approval": approval,
        }

    def _apply_model_profile_mutation(self, approval: Mapping[str, object]) -> dict[str, object]:
        operation = str(approval.get("operation") or "")
        preview = approval.get("preview") if isinstance(approval.get("preview"), Mapping) else {}
        action_payload = preview.get("actionPayload") if isinstance(preview.get("actionPayload"), Mapping) else {}
        base_state = preview.get("baseState") if isinstance(preview.get("baseState"), Mapping) else {}
        expected_digest = _approval_payload_digest(
            session_id=str(approval.get("sessionId") or ""),
            tool="ime_models",
            operation=operation,
            action_payload=action_payload,
            base_state=base_state,
        )
        if expected_digest != str(approval.get("payloadSha256") or ""):
            raise ValueError("approval payload no longer matches its preview")
        slot = _bounded_text(action_payload.get("slot"), maximum=40)
        desired_raw = action_payload.get("profile") if isinstance(action_payload.get("profile"), Mapping) else {}
        snapshot = self._model_profile_snapshot()
        profiles = snapshot["profiles"] if isinstance(snapshot.get("profiles"), Mapping) else {}
        current = profiles.get(slot) if isinstance(profiles.get(slot), Mapping) else {}
        if (
            snapshot["configurationHash"] != str(base_state.get("configurationHash") or "")
            or dict(current) != dict(base_state.get("profile") or {})
        ):
            raise ValueError("model provider profile changed after the approval preview was created")
        desired = self._normalize_model_profile(slot=slot, requested=desired_raw, current=current)
        source_approval_id = _bounded_text(action_payload.get("sourceApprovalId"), maximum=240)
        if operation == "profile_rollback":
            self._model_profile_rollback_source(
                session_id=str(approval.get("sessionId") or ""),
                source_approval_id=source_approval_id,
            )
        result = self.management.provider_configuration_apply(
            {
                "slot": slot,
                **desired,
                "expectedConfigurationHash": snapshot["configurationHash"],
            }
        )
        after = result.get("after") if isinstance(result.get("after"), Mapping) else {}
        if any(str(after.get(key) or "") != desired[key] for key in desired):
            raise ValueError("model provider update could not be verified")

        restart_component = _bounded_text(result.get("restartComponent"), maximum=40)
        activation_status = "pending_external_restart"
        activation_error = ""
        job_id = ""
        if restart_component == "predictor":
            job = self._run_runtime_action_and_wait("restart_predictor")
            activation_status = _bounded_text(job.get("status"), maximum=80) or "unknown"
            activation_error = _bounded_text(job.get("error"), maximum=240)
            job_id = _bounded_text(job.get("jobId"), maximum=240)

        rolling_back = operation == "profile_rollback"
        slot_label = "即时补全" if slot == "instant" else "知识模型"
        summary = f"已{'恢复' if rolling_back else '保存'}{slot_label} Provider 配置"
        if activation_status == "succeeded":
            summary += "并重启本地预测器"
        elif activation_status == "pending_external_restart":
            summary += "；需由外部 Supervisor 重启 Sidecar 后激活"
        else:
            summary += "；预测器重启未完成"
        receipt: dict[str, object] = {
            "schemaVersion": "rag-ime.agent-operation-receipt.v1",
            "mutationApplied": True,
            "approvalId": str(approval.get("approvalId") or ""),
            "toolId": "ime_models",
            "operation": operation,
            "auditId": result.get("auditId") or str(approval.get("approvalId") or ""),
            "summary": summary,
            "slot": slot,
            "beforeProfile": dict(current),
            "afterProfile": dict(after),
            "configurationHash": _bounded_text(result.get("configurationHash"), maximum=96),
            "restartComponent": restart_component,
            "activationStatus": activation_status,
            "jobId": job_id,
            "secretsPreserved": result.get("existingSecretPreserved") is True,
            "undoAvailable": not rolling_back,
        }
        if activation_error:
            receipt["warning"] = activation_error
        if rolling_back:
            receipt["revertedModelProfileApprovalId"] = source_approval_id
        else:
            receipt["rollback"] = {
                "toolId": "ime_models",
                "operation": "profile_rollback",
                "args": {"sourceApprovalId": str(approval.get("approvalId") or "")},
                "requiresApproval": True,
            }
        return receipt

    def _model_profile_rollback_source(
        self,
        *,
        session_id: str,
        source_approval_id: str,
    ) -> dict[str, object]:
        if not source_approval_id:
            raise ValueError("sourceApprovalId is required for ime_models.profile_rollback")
        approvals = self.sessions.list_approvals(session_id=session_id, state="applied", limit=500)
        for item in approvals:
            receipt = item.get("receipt") if isinstance(item.get("receipt"), Mapping) else {}
            if str(receipt.get("revertedModelProfileApprovalId") or "") == source_approval_id:
                raise ValueError("model provider change has already been rolled back")
        for item in approvals:
            receipt = item.get("receipt") if isinstance(item.get("receipt"), Mapping) else {}
            if (
                str(item.get("approvalId") or "") == source_approval_id
                and str(item.get("toolId") or "") == "ime_models"
                and str(item.get("operation") or "") == "profile_apply"
                and receipt.get("undoAvailable") is True
            ):
                return item
        raise ValueError("model provider change is not backed by an applied approval receipt")

    def _prepare_runtime_mutation(
        self,
        *,
        session_id: str,
        operation: str,
        risk_level: str,
    ) -> dict[str, object]:
        status = self.management.overview()
        ai_paused = status.get("aiPaused") is True
        if operation == "pause_ai" and ai_paused:
            raise ValueError("AI assistance is already paused")
        if operation == "resume_ai" and not ai_paused:
            raise ValueError("AI assistance is already running")
        management_action = {
            "pause_ai": "stop_ai",
            "resume_ai": "resume_ai",
            "restart_sidecar": "restart_sidecar",
            "restart_predictor": "restart_predictor",
            "redeploy_rime": "redeploy_rime",
        }[operation]
        labels = {
            "pause_ai": ("暂停 AI 辅助", "运行中", "已暂停"),
            "resume_ai": ("恢复 AI 辅助", "已暂停", "运行中"),
            "restart_sidecar": ("重启 Sidecar", "当前服务进程", "外部监督器启动的新进程"),
            "restart_predictor": ("重启本地预测器", "当前进程", "新进程"),
            "redeploy_rime": ("重新部署 Rime 配置", "当前部署", "重新编译并加载"),
        }
        operation_label, before_label, after_label = labels[operation]
        action_payload = {"action": management_action}
        base_state = {
            "settingsRevision": _bounded_text(status.get("settingsRevision"), maximum=96),
            "runtimeRevision": _safe_int(status.get("runtimeRevision")),
            "aiPaused": ai_paused,
        }
        digest = _approval_payload_digest(
            session_id=session_id,
            tool="ime_runtime",
            operation=operation,
            action_payload=action_payload,
            base_state=base_state,
        )
        preview = {
            "title": f"确认{operation_label}",
            "summary": (
                "暂停期间普通拼音仍可使用，AI 候选与生成入口暂不工作"
                if operation == "pause_ai"
                else "恢复提交后预测和 AI 生成能力"
                if operation == "resume_ai"
                else "先让当前 Pi 回合完成，再由控制中心的外部监督器重启 Sidecar；普通 Rime 拼音继续可用"
                if operation == "restart_sidecar"
                else "预测器会短暂不可用，普通 Rime 拼音不受影响"
                if operation == "restart_predictor"
                else "将重新编译并加载当前 Rime 配置，输入法可能短暂刷新"
            ),
            "operationLabel": operation_label,
            "changes": [
                {
                    "label": "AI 辅助" if operation in {"pause_ai", "resume_ai"} else "运行组件",
                    "before": before_label,
                    "after": after_label,
                }
            ],
            "actionPayload": action_payload,
            "baseState": base_state,
        }
        approval = self.sessions.create_approval(
            session_id=session_id,
            tool_name="ime_runtime",
            operation=operation,
            payload_sha256=digest,
            preview=preview,
            risk_level=risk_level,
            ttl_ms=60_000,
        )
        return {
            "summary": f"等待确认：{operation_label}",
            "approvalRequired": True,
            "approvalId": approval["approvalId"],
            "approval": approval,
        }

    def _apply_runtime_mutation(self, approval: Mapping[str, object]) -> dict[str, object]:
        operation = str(approval.get("operation") or "")
        preview = approval.get("preview") if isinstance(approval.get("preview"), Mapping) else {}
        action_payload = preview.get("actionPayload") if isinstance(preview.get("actionPayload"), Mapping) else {}
        base_state = preview.get("baseState") if isinstance(preview.get("baseState"), Mapping) else {}
        expected_digest = _approval_payload_digest(
            session_id=str(approval.get("sessionId") or ""),
            tool="ime_runtime",
            operation=operation,
            action_payload=action_payload,
            base_state=base_state,
        )
        if expected_digest != str(approval.get("payloadSha256") or ""):
            raise ValueError("approval payload no longer matches its preview")
        current = self.management.overview()
        if (
            _bounded_text(current.get("settingsRevision"), maximum=96)
            != _bounded_text(base_state.get("settingsRevision"), maximum=96)
            or _safe_int(current.get("runtimeRevision")) != _safe_int(base_state.get("runtimeRevision"))
            or (current.get("aiPaused") is True) != bool(base_state.get("aiPaused"))
        ):
            raise ValueError("runtime state changed after the approval preview was created")
        action = _bounded_text(action_payload.get("action"), maximum=80)
        expected_action = {
            "pause_ai": "stop_ai",
            "resume_ai": "resume_ai",
            "restart_sidecar": "restart_sidecar",
            "restart_predictor": "restart_predictor",
            "redeploy_rime": "redeploy_rime",
        }.get(operation)
        if not expected_action or action != expected_action:
            raise ValueError("approved runtime action is invalid")
        job = self._run_runtime_action_and_wait(action)
        status = _bounded_text(job.get("status"), maximum=80)
        succeeded = status == "succeeded"
        after = self.management.overview()
        summaries = {
            "pause_ai": "AI 辅助已暂停，普通 Rime 拼音仍可使用",
            "resume_ai": "AI 辅助已恢复",
            "restart_sidecar": "Sidecar 已重启",
            "restart_predictor": "本地预测器已重启",
            "redeploy_rime": "Rime 配置已重新部署",
        }
        if operation == "restart_sidecar" and status == "external-supervisor-required":
            external_command = job.get("externalCommand")
            if not isinstance(external_command, list) or not external_command:
                raise ValueError("Sidecar restart returned no external supervisor command")
            command = [_bounded_text(value, maximum=300) for value in external_command]
            if any(not value for value in command):
                raise ValueError("Sidecar restart returned an invalid external supervisor command")
            expected_command = [
                "launchctl",
                "kickstart",
                "-k",
                f"gui/{os.getuid()}/com.rag-ime.sidecar",
            ]
            if command != expected_command:
                raise ValueError("Sidecar restart command does not match the fixed supervisor policy")
            return {
                "schemaVersion": "rag-ime.agent-operation-receipt.v1",
                "mutationApplied": False,
                "externalActionPending": True,
                "approvalId": str(approval.get("approvalId") or ""),
                "toolId": "ime_runtime",
                "operation": operation,
                "auditId": job.get("auditId") or str(approval.get("approvalId") or ""),
                "summary": "Sidecar 重启已批准；Pi 完成当前回答后，由控制中心外部监督器执行",
                "jobId": _bounded_text(job.get("jobId"), maximum=240),
                "status": status,
                "externalAction": "restart_sidecar",
                "externalCommand": command,
                "externalCommandSha256": _sha256_json(command),
                "runtimeRevision": _safe_int(after.get("runtimeRevision")),
                "settingsRevision": _bounded_text(after.get("settingsRevision"), maximum=96),
                "aiPaused": after.get("aiPaused") is True,
                "undoAvailable": False,
            }
        receipt: dict[str, object] = {
            "schemaVersion": "rag-ime.agent-operation-receipt.v1",
            "mutationApplied": succeeded,
            "approvalId": str(approval.get("approvalId") or ""),
            "toolId": "ime_runtime",
            "operation": operation,
            "auditId": job.get("auditId") or str(approval.get("approvalId") or ""),
            "summary": summaries[operation] if succeeded else f"{summaries[operation]}失败",
            "jobId": _bounded_text(job.get("jobId"), maximum=240),
            "status": status or "unknown",
            "runtimeRevision": _safe_int(after.get("runtimeRevision")),
            "settingsRevision": _bounded_text(after.get("settingsRevision"), maximum=96),
            "aiPaused": after.get("aiPaused") is True,
            "undoAvailable": False,
        }
        if not succeeded:
            receipt["reason"] = "runtime_action_failed"
            receipt["error"] = _bounded_text(job.get("error"), maximum=240) or "运行组件没有成功完成操作"
        return receipt

    def _redeploy_rime_and_wait(self) -> dict[str, object]:
        return self._run_runtime_action_and_wait("redeploy_rime")

    def _run_runtime_action_and_wait(self, action: str) -> dict[str, object]:
        starter = getattr(self.management, "start_runtime_action", None)
        reader = getattr(self.management, "runtime_job", None)
        if not callable(starter) or not callable(reader):
            raise ValueError("runtime action service is unavailable")
        queued = starter({"action": action, "requestedBy": "pi-control-agent"})
        job_id = _bounded_text(queued.get("jobId"), maximum=240)
        if not job_id:
            raise ValueError("runtime action returned no jobId")
        deadline = time.monotonic() + 95.0
        while time.monotonic() < deadline:
            report = reader(job_id)
            job = report.get("job") if isinstance(report.get("job"), Mapping) else {}
            status = _bounded_text(job.get("status"), maximum=80)
            if status in {"succeeded", "failed", "timed_out", "external-supervisor-required"}:
                result = job.get("result") if isinstance(job.get("result"), Mapping) else {}
                external_command = result.get("externalCommand")
                return {
                    "jobId": job_id,
                    "status": status,
                    "error": _bounded_text(job.get("error"), maximum=240),
                    "auditId": queued.get("auditId"),
                    "externalCommand": list(external_command)
                    if isinstance(external_command, list)
                    else [],
                }
            time.sleep(0.1)
        return {
            "jobId": job_id,
            "status": "timed_out",
            "error": "runtime action timed out",
            "auditId": queued.get("auditId"),
        }

    def _prepare_configuration_export(
        self,
        *,
        session_id: str,
        risk_level: str,
    ) -> dict[str, object]:
        overview = self.management.overview()
        export_id = f"agent-{int(time.time() * 1000)}-{_sha256_text(session_id)[:8]}"
        relative_path = f"Backups/{export_id}.ragime-backup"
        action_payload = {"exportId": export_id, "managedRelativePath": relative_path}
        base_state = {
            "scopeVersion": "portable-backup-v1",
            "secretsIncluded": False,
        }
        digest = _approval_payload_digest(
            session_id=session_id,
            tool="ime_configuration",
            operation="export",
            action_payload=action_payload,
            base_state=base_state,
        )
        memory = overview.get("memory") if isinstance(overview.get("memory"), Mapping) else {}
        preview = {
            "title": "确认导出便携备份",
            "summary": "导出当前数据库、非敏感设置和安全的 Rime 配置；不会包含 API Key 或模型文件",
            "operationLabel": "导出无密钥备份",
            "changes": [
                {
                    "label": "备份内容",
                    "before": "仅保存在当前设备",
                    "after": "数据库 + 设置 + Rime 配置",
                },
                {
                    "label": "敏感信息",
                    "before": "Keychain / API Key",
                    "after": "不导出",
                },
                {
                    "label": "记忆工具书",
                    "before": "当前数据库",
                    "after": f"备份 {_safe_int(memory.get('memoryBookCount'))} 本工具书",
                },
            ],
            "actionPayload": action_payload,
            "baseState": base_state,
        }
        approval = self.sessions.create_approval(
            session_id=session_id,
            tool_name="ime_configuration",
            operation="export",
            payload_sha256=digest,
            preview=preview,
            risk_level=risk_level,
            ttl_ms=60_000,
        )
        return {
            "summary": "等待确认：导出不含密钥的便携备份",
            "approvalRequired": True,
            "approvalId": approval["approvalId"],
            "approval": approval,
        }

    def _apply_configuration_export(self, approval: Mapping[str, object]) -> dict[str, object]:
        preview = approval.get("preview") if isinstance(approval.get("preview"), Mapping) else {}
        action_payload = preview.get("actionPayload") if isinstance(preview.get("actionPayload"), Mapping) else {}
        base_state = preview.get("baseState") if isinstance(preview.get("baseState"), Mapping) else {}
        expected_digest = _approval_payload_digest(
            session_id=str(approval.get("sessionId") or ""),
            tool="ime_configuration",
            operation="export",
            action_payload=action_payload,
            base_state=base_state,
        )
        if expected_digest != str(approval.get("payloadSha256") or ""):
            raise ValueError("approval payload no longer matches its preview")
        if base_state.get("secretsIncluded") is not False or base_state.get("scopeVersion") != "portable-backup-v1":
            raise ValueError("approved backup scope is invalid")
        relative_path = _bounded_text(action_payload.get("managedRelativePath"), maximum=300)
        target = self._managed_backup_target(relative_path)
        if target.exists() or target.is_symlink():
            raise ValueError("managed backup target already exists")
        result = self.management.portable_backup_export({"destination": str(target)})
        if result.get("ok") is False or result.get("secretsIncluded") is not False:
            raise ValueError(_bounded_text(result.get("error"), maximum=240) or "portable backup export failed")
        if Path(str(result.get("path") or "")).expanduser().resolve() != target.resolve():
            raise ValueError("portable backup was written outside the approved managed path")
        return {
            "schemaVersion": "rag-ime.agent-operation-receipt.v1",
            "mutationApplied": True,
            "approvalId": str(approval.get("approvalId") or ""),
            "toolId": "ime_configuration",
            "operation": "export",
            "auditId": result.get("auditId") or str(approval.get("approvalId") or ""),
            "summary": f"已导出无密钥备份 {target.name}",
            "exportId": _bounded_text(action_payload.get("exportId"), maximum=120),
            "fileName": target.name,
            "managedRelativePath": relative_path,
            "sizeBytes": _safe_int(result.get("sizeBytes")),
            "databaseCounts": _safe_payload(result.get("databaseCounts")),
            "rimeFileCount": _safe_int(result.get("rimeFileCount")),
            "secretsIncluded": False,
            "undoAvailable": False,
        }

    def _prepare_configuration_restore(
        self,
        *,
        session_id: str,
        args: Mapping[str, object],
        risk_level: str,
    ) -> dict[str, object]:
        source_approval_id = _bounded_text(args.get("sourceApprovalId"), maximum=240)
        _source, target = self._configuration_export_source(
            session_id=session_id,
            source_approval_id=source_approval_id,
        )
        restored = self.management.portable_restore_preview({"path": str(target)})
        if restored.get("valid") is not True or restored.get("requiresRestart") is not True:
            raise ValueError("managed backup is not eligible for an external restore")
        archive_revision = _bounded_text(restored.get("restoreToken"), maximum=96)
        if len(archive_revision) != 64:
            raise ValueError("managed backup preview returned an invalid archive revision")
        action_payload = {"sourceApprovalId": source_approval_id}
        base_state = {
            "archiveRevision": archive_revision,
            "createdAtMs": _safe_int(restored.get("createdAtMs")),
            "databaseMigrationVersion": _safe_int(restored.get("databaseMigrationVersion")),
            "databaseCounts": _safe_payload(restored.get("databaseCounts")),
            "rimeFileCount": _safe_int(restored.get("rimeFileCount")),
        }
        digest = _approval_payload_digest(
            session_id=session_id,
            tool="ime_configuration",
            operation="restore_apply",
            action_payload=action_payload,
            base_state=base_state,
        )
        counts = restored.get("databaseCounts") if isinstance(restored.get("databaseCounts"), Mapping) else {}
        preview = {
            "title": "强确认：恢复便携备份",
            "summary": (
                "Pi 当前回合结束后，原生监督器会停止 Sidecar、恢复数据库与安全配置，"
                "再启动新 Sidecar；恢复前会自动生成回滚包"
            ),
            "operationLabel": "停止 Sidecar 并恢复备份",
            "changes": [
                {
                    "label": "本地数据库",
                    "before": "当前数据",
                    "after": f"备份中的 {_safe_int(counts.get('input_events'))} 条输入事件",
                },
                {
                    "label": "Memory Book",
                    "before": "当前工具书",
                    "after": f"备份中的 {_safe_int(counts.get('memory_books'))} 本工具书",
                },
                {
                    "label": "Rime 配置",
                    "before": "当前安全配置",
                    "after": f"备份中的 {_safe_int(restored.get('rimeFileCount'))} 个文件",
                },
            ],
            "warnings": [
                "恢复会替换当前数据库和安全配置；API Key、Keychain 与模型文件不在备份内",
                "普通 Rime 拼音在 Sidecar 停止期间仍可使用，AI 能力会短暂离线",
            ],
            "actionPayload": action_payload,
            "baseState": base_state,
        }
        approval = self.sessions.create_approval(
            session_id=session_id,
            tool_name="ime_configuration",
            operation="restore_apply",
            payload_sha256=digest,
            preview=preview,
            risk_level=risk_level,
            ttl_ms=120_000,
        )
        return {
            "summary": "等待强确认：停止 Sidecar 并恢复受管备份",
            "approvalRequired": True,
            "approvalId": approval["approvalId"],
            "approval": approval,
        }

    def _apply_configuration_restore(self, approval: Mapping[str, object]) -> dict[str, object]:
        preview = approval.get("preview") if isinstance(approval.get("preview"), Mapping) else {}
        action_payload = preview.get("actionPayload") if isinstance(preview.get("actionPayload"), Mapping) else {}
        base_state = preview.get("baseState") if isinstance(preview.get("baseState"), Mapping) else {}
        expected_digest = _approval_payload_digest(
            session_id=str(approval.get("sessionId") or ""),
            tool="ime_configuration",
            operation="restore_apply",
            action_payload=action_payload,
            base_state=base_state,
        )
        if expected_digest != str(approval.get("payloadSha256") or ""):
            raise ValueError("approval payload no longer matches its preview")
        source_approval_id = _bounded_text(action_payload.get("sourceApprovalId"), maximum=240)
        _source, target = self._configuration_export_source(
            session_id=str(approval.get("sessionId") or ""),
            source_approval_id=source_approval_id,
        )
        current = self.management.portable_restore_preview({"path": str(target)})
        if (
            current.get("valid") is not True
            or _bounded_text(current.get("restoreToken"), maximum=96)
            != _bounded_text(base_state.get("archiveRevision"), maximum=96)
            or _safe_int(current.get("databaseMigrationVersion"))
            != _safe_int(base_state.get("databaseMigrationVersion"))
        ):
            raise ValueError("managed backup changed after the restore approval preview")

        support = self._managed_support_directory()
        database = Path(getattr(self.management, "db_path", support / "rag-ime.sqlite")).expanduser().resolve()
        rime_directory = Path(
            os.environ.get("RAG_IME_RIME_USER_DIR") or Path.home() / "Library" / "Rime"
        ).expanduser().resolve()
        return {
            "schemaVersion": "rag-ime.agent-operation-receipt.v1",
            "mutationApplied": False,
            "externalActionPending": True,
            "approvalId": str(approval.get("approvalId") or ""),
            "toolId": "ime_configuration",
            "operation": "restore_apply",
            "auditId": str(approval.get("approvalId") or ""),
            "summary": (
                "数据库恢复已批准；Pi 完成当前回答后，由原生监督器停止 Sidecar、恢复并重新启动"
            ),
            "status": "external-supervisor-required",
            "externalAction": "restore_backup",
            "undoAvailable": False,
            "_externalPlanPayload": {
                "archivePath": str(target),
                "databasePath": str(database),
                "restoreToken": str(current.get("restoreToken") or ""),
                "rimeUserDirectory": str(rime_directory),
                "supportDirectory": str(support),
                "launchAgentPlist": str(
                    Path.home() / "Library" / "LaunchAgents" / "com.rag-ime.sidecar.plist"
                ),
                "launchAgentTarget": f"gui/{os.getuid()}/com.rag-ime.sidecar",
            },
        }

    @staticmethod
    def _managed_support_directory() -> Path:
        raw = Path(
            os.environ.get("RAG_IME_APP_SUPPORT_DIR")
            or Path.home() / "Library" / "Application Support" / "RagIme"
        ).expanduser()
        if raw.is_symlink():
            raise ValueError("managed application support directory must not be a symlink")
        return raw.resolve()

    def _managed_backup_target(self, relative_path: str) -> Path:
        if not relative_path or Path(relative_path).is_absolute():
            raise ValueError("managed backup path is invalid")
        support = self._managed_support_directory()
        raw_backup_root = support / "Backups"
        if raw_backup_root.is_symlink():
            raise ValueError("managed backup directory must not be a symlink")
        backup_root = raw_backup_root.resolve()
        target = (support / relative_path).resolve()
        if target.parent != backup_root or target.suffix != ".ragime-backup":
            raise ValueError("managed backup path escaped its approved directory")
        return target

    def _configuration_export_source(
        self,
        *,
        session_id: str,
        source_approval_id: str,
    ) -> tuple[dict[str, object], Path]:
        if not source_approval_id:
            raise ValueError("sourceApprovalId is required for ime_configuration.restore_preview")
        approvals = self.sessions.list_approvals(session_id=session_id, state="applied", limit=500)
        for item in approvals:
            receipt = item.get("receipt") if isinstance(item.get("receipt"), Mapping) else {}
            if (
                str(item.get("approvalId") or "") == source_approval_id
                and str(item.get("toolId") or "") == "ime_configuration"
                and str(item.get("operation") or "") == "export"
                and receipt.get("secretsIncluded") is False
            ):
                relative_path = _bounded_text(receipt.get("managedRelativePath"), maximum=300)
                target = self._managed_backup_target(relative_path)
                if not target.is_file() or target.is_symlink():
                    raise ValueError("managed backup file is no longer available")
                return item, target
        raise ValueError("backup is not backed by an applied export receipt")

    def _prepare_workspace_command(
        self,
        *,
        session_id: str,
        args: Mapping[str, object],
        risk_level: str,
    ) -> dict[str, object]:
        session = self.sessions.get(session_id)
        prepared = self.workspace_harness.prepare_command(session, args)
        preview = self.workspace_harness.preview(prepared)
        action_payload = preview.get("actionPayload")
        base_state = preview.get("baseState")
        assert isinstance(action_payload, Mapping)
        assert isinstance(base_state, Mapping)
        digest = _approval_payload_digest(
            session_id=session_id,
            tool="workspace_shell",
            operation="run",
            action_payload=action_payload,
            base_state=base_state,
        )
        approval = self.sessions.create_approval(
            session_id=session_id,
            tool_name="workspace_shell",
            operation="run",
            payload_sha256=digest,
            preview=preview,
            risk_level=risk_level,
            ttl_ms=60_000,
        )
        return {
            "summary": "等待确认：运行受沙箱保护的工作区命令",
            "approvalRequired": True,
            "approvalId": approval["approvalId"],
            "approval": approval,
        }

    def _apply_workspace_command(self, approval: Mapping[str, object]) -> dict[str, object]:
        preview = approval.get("preview") if isinstance(approval.get("preview"), Mapping) else {}
        action_payload = (
            preview.get("actionPayload") if isinstance(preview.get("actionPayload"), Mapping) else {}
        )
        base_state = preview.get("baseState") if isinstance(preview.get("baseState"), Mapping) else {}
        expected_digest = _approval_payload_digest(
            session_id=str(approval.get("sessionId") or ""),
            tool="workspace_shell",
            operation="run",
            action_payload=action_payload,
            base_state=base_state,
        )
        if expected_digest != str(approval.get("payloadSha256") or ""):
            raise ValueError("approval payload no longer matches its preview")
        session = self.sessions.get(str(approval.get("sessionId") or ""))
        prepared: PreparedWorkspaceCommand = self.workspace_harness.prepare_command(
            session,
            action_payload,
        )
        if prepared.roots_digest != str(base_state.get("workspaceRootsSha256") or ""):
            raise ValueError("authorized workspace changed after approval preview")
        receipt = self.workspace_harness.execute(prepared)
        return {
            **receipt,
            "approvalId": str(approval.get("approvalId") or ""),
            "toolId": "workspace_shell",
            "operation": "run",
            "auditId": str(approval.get("approvalId") or ""),
        }

    def _prepare_workspace_patch(
        self,
        *,
        session_id: str,
        args: Mapping[str, object],
        risk_level: str,
    ) -> dict[str, object]:
        session = self.sessions.get(session_id)
        prepared = self.workspace_harness.prepare_patch(session, args)
        preview = self.workspace_harness.patch_preview(prepared)
        action_payload = preview.get("actionPayload")
        base_state = preview.get("baseState")
        assert isinstance(action_payload, Mapping)
        assert isinstance(base_state, Mapping)
        digest = _approval_payload_digest(
            session_id=session_id,
            tool="workspace_patch",
            operation="apply",
            action_payload=action_payload,
            base_state=base_state,
        )
        approval = self.sessions.create_approval(
            session_id=session_id,
            tool_name="workspace_patch",
            operation="apply",
            payload_sha256=digest,
            preview=preview,
            risk_level=risk_level,
            ttl_ms=60_000,
        )
        return {
            "summary": f"等待确认：{preview['summary']}",
            "approvalRequired": True,
            "approvalId": approval["approvalId"],
            "approval": approval,
        }

    def _apply_workspace_patch(self, approval: Mapping[str, object]) -> dict[str, object]:
        preview = approval.get("preview") if isinstance(approval.get("preview"), Mapping) else {}
        action_payload = (
            preview.get("actionPayload") if isinstance(preview.get("actionPayload"), Mapping) else {}
        )
        base_state = preview.get("baseState") if isinstance(preview.get("baseState"), Mapping) else {}
        session_id = str(approval.get("sessionId") or "")
        expected_digest = _approval_payload_digest(
            session_id=session_id,
            tool="workspace_patch",
            operation="apply",
            action_payload=action_payload,
            base_state=base_state,
        )
        if expected_digest != str(approval.get("payloadSha256") or ""):
            raise ValueError("approval payload no longer matches its preview")
        session = self.sessions.get(session_id)
        receipt = self.workspace_harness.apply_patch(session, action_payload, base_state)
        result = {
            **receipt,
            "approvalId": str(approval.get("approvalId") or ""),
            "toolId": "workspace_patch",
            "operation": "apply",
            "auditId": str(approval.get("approvalId") or ""),
        }
        if self.artifact_projector is not None:
            projection = self.artifact_projector.project_workspace_patch(
                session=session,
                approval_id=str(approval.get("approvalId") or ""),
                receipt=result,
                preview=preview,
            )
            result.update(projection.receipt_fields())
        return result

    def _prepare_planning_undo(
        self,
        *,
        session_id: str,
        args: Mapping[str, object],
        risk_level: str,
    ) -> dict[str, object]:
        event_id = _bounded_text(args.get("eventId"), maximum=240)
        if not event_id:
            raise ValueError("eventId is required for ime_planning.undo_task_event")
        source_approval = self._rollback_source_approval(session_id=session_id, event_id=event_id)
        source_receipt = (
            source_approval.get("receipt") if isinstance(source_approval.get("receipt"), Mapping) else {}
        )
        source_preview = (
            source_approval.get("preview") if isinstance(source_approval.get("preview"), Mapping) else {}
        )
        source_base = (
            source_preview.get("baseState") if isinstance(source_preview.get("baseState"), Mapping) else {}
        )
        task = source_receipt.get("task") if isinstance(source_receipt.get("task"), Mapping) else {}
        task_id = _bounded_text(task.get("id"), maximum=240)
        plan_date = _bounded_text(task.get("date"), maximum=24)
        target_status = _bounded_text(source_base.get("status"), maximum=40)
        if not task_id or not plan_date or not target_status:
            raise ValueError("rollback receipt does not contain a complete task snapshot")
        current = self._planning_task(task_id=task_id, plan_date=plan_date)
        expected_current_status = _bounded_text(task.get("status"), maximum=40)
        if str(current.get("status") or "") != expected_current_status:
            raise ValueError("task no longer matches the rollback receipt")
        action_payload = {
            "eventId": event_id,
            "taskId": task_id,
            "date": plan_date,
            "targetStatus": target_status,
            "sourceApprovalId": str(source_approval.get("approvalId") or ""),
        }
        base_state = {
            "status": str(current.get("status") or ""),
            "updatedAtMs": _safe_int(current.get("updatedAtMs")),
        }
        digest = _approval_payload_digest(
            session_id=session_id,
            tool="ime_planning",
            operation="undo_task_event",
            action_payload=action_payload,
            base_state=base_state,
        )
        title = _bounded_text(current.get("title"), maximum=160) or "未命名任务"
        preview = {
            "title": "确认撤销任务变更",
            "summary": f"把《{title}》恢复为{_planning_status_label(target_status)}",
            "operationLabel": "撤销上一次任务变更",
            "changes": [
                {
                    "label": "任务状态",
                    "before": _planning_status_label(str(current.get("status") or "")),
                    "after": _planning_status_label(target_status),
                }
            ],
            "actionPayload": action_payload,
            "baseState": base_state,
        }
        approval = self.sessions.create_approval(
            session_id=session_id,
            tool_name="ime_planning",
            operation="undo_task_event",
            payload_sha256=digest,
            preview=preview,
            risk_level=risk_level,
            ttl_ms=60_000,
        )
        return {
            "summary": f"等待确认：{preview['summary']}",
            "approvalRequired": True,
            "approvalId": approval["approvalId"],
            "approval": approval,
        }

    def _apply_planning_undo(self, approval: Mapping[str, object]) -> dict[str, object]:
        preview = approval.get("preview") if isinstance(approval.get("preview"), Mapping) else {}
        action_payload = (
            preview.get("actionPayload") if isinstance(preview.get("actionPayload"), Mapping) else {}
        )
        base_state = preview.get("baseState") if isinstance(preview.get("baseState"), Mapping) else {}
        expected_digest = _approval_payload_digest(
            session_id=str(approval.get("sessionId") or ""),
            tool="ime_planning",
            operation="undo_task_event",
            action_payload=action_payload,
            base_state=base_state,
        )
        if expected_digest != str(approval.get("payloadSha256") or ""):
            raise ValueError("approval payload no longer matches its preview")
        event_id = _bounded_text(action_payload.get("eventId"), maximum=240)
        task_id = _bounded_text(action_payload.get("taskId"), maximum=240)
        plan_date = _bounded_text(action_payload.get("date"), maximum=24)
        target_status = _bounded_text(action_payload.get("targetStatus"), maximum=40)
        source_approval_id = _bounded_text(action_payload.get("sourceApprovalId"), maximum=240)
        if not event_id or not task_id or not plan_date or not target_status or not source_approval_id:
            raise ValueError("approved rollback payload is invalid")
        self._rollback_source_approval(
            session_id=str(approval.get("sessionId") or ""),
            event_id=event_id,
            expected_approval_id=source_approval_id,
        )
        task = self._planning_task(task_id=task_id, plan_date=plan_date)
        if (
            str(task.get("status") or "") != str(base_state.get("status") or "")
            or _safe_int(task.get("updatedAtMs")) != _safe_int(base_state.get("updatedAtMs"))
        ):
            raise ValueError("task changed after the rollback preview was created")
        try:
            result = self.management.planning_undo_task_event({"eventId": event_id})
        except Exception as exc:
            observed = self._planning_task(task_id=task_id, plan_date=plan_date)
            if (
                str(observed.get("status") or "") == target_status
                and _safe_int(observed.get("updatedAtMs")) != _safe_int(base_state.get("updatedAtMs"))
            ):
                return self._planning_undo_receipt(
                    approval=approval,
                    result={"task": observed},
                    event_id=event_id,
                    source_approval_id=source_approval_id,
                    audit_persisted=False,
                    warning=_bounded_text(exc, maximum=240),
                )
            raise
        return self._planning_undo_receipt(
            approval=approval,
            result=result,
            event_id=event_id,
            source_approval_id=source_approval_id,
            audit_persisted=True,
        )

    def _rollback_source_approval(
        self,
        *,
        session_id: str,
        event_id: str,
        expected_approval_id: str = "",
    ) -> dict[str, object]:
        applied = self.sessions.list_approvals(session_id=session_id, state="applied", limit=200)
        for item in applied:
            receipt = item.get("receipt") if isinstance(item.get("receipt"), Mapping) else {}
            if str(receipt.get("revertedTaskEventId") or "") == event_id:
                raise ValueError("task event has already been rolled back")
        for item in applied:
            if expected_approval_id and str(item.get("approvalId") or "") != expected_approval_id:
                continue
            receipt = item.get("receipt") if isinstance(item.get("receipt"), Mapping) else {}
            rollback = receipt.get("rollback") if isinstance(receipt.get("rollback"), Mapping) else {}
            if (
                str(receipt.get("taskEventId") or "") == event_id
                and str(rollback.get("operation") or "") == "undo_task_event"
                and receipt.get("undoAvailable") is True
            ):
                return item
        raise ValueError("task event is not backed by an applied approval receipt")

    def _planning_undo_receipt(
        self,
        *,
        approval: Mapping[str, object],
        result: Mapping[str, object],
        event_id: str,
        source_approval_id: str,
        audit_persisted: bool,
        warning: str = "",
    ) -> dict[str, object]:
        task = result.get("task") if isinstance(result.get("task"), Mapping) else {}
        receipt: dict[str, object] = {
            "schemaVersion": "rag-ime.agent-operation-receipt.v1",
            "mutationApplied": True,
            "approvalId": str(approval.get("approvalId") or ""),
            "toolId": "ime_planning",
            "operation": "undo_task_event",
            "summary": f"已撤销《{_bounded_text(task.get('title'), maximum=160) or '任务'}》的上一次状态变更",
            "auditId": _safe_int(result.get("auditId")),
            "auditPersisted": audit_persisted,
            "task": _safe_payload(task),
            "revertedTaskEventId": event_id,
            "sourceApprovalId": source_approval_id,
            "undoAvailable": False,
        }
        if warning:
            receipt["warning"] = warning
        return receipt

    def _planning_task(self, *, task_id: str, plan_date: str) -> dict[str, object]:
        dashboard = self.management.planning_dashboard(
            plan_date=plan_date,
            project=self.project,
        )
        tasks = dashboard.get("tasks") if isinstance(dashboard.get("tasks"), list) else []
        for item in tasks:
            if isinstance(item, Mapping) and str(item.get("id") or "") == task_id:
                return dict(item)
        raise ValueError("task is not visible in the current planning scope")

    def _planning_receipt(
        self,
        *,
        approval: Mapping[str, object],
        action: str,
        result: Mapping[str, object],
        audit_persisted: bool,
        warning: str = "",
    ) -> dict[str, object]:
        task = result.get("task") if isinstance(result.get("task"), Mapping) else {}
        event_id = _bounded_text(result.get("eventId"), maximum=240)
        undo_available = bool(result.get("undoAvailable")) and bool(event_id)
        receipt: dict[str, object] = {
            "schemaVersion": "rag-ime.agent-operation-receipt.v1",
            "mutationApplied": True,
            "approvalId": str(approval.get("approvalId") or ""),
            "toolId": "ime_planning",
            "operation": "task_action",
            "summary": f"已将《{_bounded_text(task.get('title'), maximum=160) or '任务'}》{_PLANNING_ACTION_LABELS[action]}",
            "auditId": _safe_int(result.get("auditId")),
            "auditPersisted": audit_persisted,
            "taskEventId": event_id,
            "task": _safe_payload(task),
            "undoAvailable": undo_available,
        }
        if undo_available:
            receipt["rollback"] = {
                "toolId": "ime_planning",
                "operation": "undo_task_event",
                "args": {"eventId": event_id},
                "requiresApproval": True,
            }
        if warning:
            receipt["warning"] = warning
        return receipt

    def _overview(self, operation: str, args: Mapping[str, object]) -> dict[str, object]:
        if operation == "status":
            payload = self.management.overview()
            components = payload.get("components") if isinstance(payload.get("components"), Mapping) else {}
            unhealthy = [
                str(key)
                for key, value in components.items()
                if isinstance(value, Mapping) and value.get("ok") is not True
            ]
            return {
                "summary": "控制中心运行正常" if not unhealthy else f"发现 {len(unhealthy)} 个未就绪组件",
                "components": _safe_payload(components),
                "memory": _safe_payload(payload.get("memory")),
                "lastPrediction": _safe_payload(payload.get("lastPrediction")),
                "unhealthyComponents": unhealthy,
            }
        if operation == "capabilities":
            return {
                "summary": "已连接 9 个控制中心领域；运行协调会话另有 3 个受 Harness 保护的工作区工具",
                "readOnly": False,
                "toolCount": len(_TOOL_SPECS),
                "tools": [
                    {
                        "id": spec["id"],
                        "displayName": spec["displayName"],
                        "operations": list(spec["operations"]),
                    }
                    for spec in _TOOL_SPECS
                ],
                "approvalGatedOperations": [
                    "ime_input.apply_settings",
                    "ime_input.rollback_settings",
                    "ime_input.lexicon_apply",
                    "ime_input.lexicon_rollback",
                    "ime_planning.task_action",
                    "ime_memory.maintenance_apply",
                    "ime_memory.maintenance_rollback",
                    "ime_runtime.pause_ai",
                    "ime_runtime.resume_ai",
                    "ime_runtime.restart_sidecar",
                    "ime_runtime.restart_predictor",
                    "ime_runtime.redeploy_rime",
                    "ime_configuration.export",
                ],
                "writePolicy": "R1 以上操作必须生成差异、校验快照、原生确认并保存 receipt",
            }
        limit = _bounded_int(args.get("limit"), default=8, minimum=1, maximum=20)
        query = _bounded_text(args.get("query"), maximum=240)
        history = self.management.history_page(page_request({"query": query, "limit": limit}))
        items = history.get("items", []) if isinstance(history, Mapping) else []
        return {
            "summary": f"读取 {len(items)} 条近期活动摘要",
            "items": _safe_payload(items),
            "nextCursor": _bounded_text(history.get("nextCursor"), maximum=80),
        }

    def _input(self, operation: str, args: Mapping[str, object]) -> dict[str, object]:
        if operation == "get_settings":
            payload = self._facade_call("settings")
            settings = payload.get("settings") if isinstance(payload.get("settings"), Mapping) else {}
            visible = {
                key: settings[key]
                for key in ("interaction", "pinyin", "privacy", "memory", "activeRag", "agent")
                if key in settings
            }
            return {
                "summary": "已读取输入法的非敏感设置",
                "settings": _safe_payload(visible),
                "runtimeConfig": _safe_payload(payload.get("runtimeConfig")),
            }
        if operation == "preview_settings":
            snapshot = self._input_settings_snapshot()
            current_flat = flatten_settings(snapshot["settings"])
            normalized = _normalize_input_setting_changes(args.get("changes"))
            actual = [
                item
                for item in normalized
                if current_flat.get(str(item["key"])) != item["value"]
            ]
            return {
                "summary": (
                    f"有 {len(actual)} 项输入设置会发生变化"
                    if actual
                    else "输入设置已经符合请求，无需修改"
                ),
                "changeCount": len(actual),
                "changes": [
                    {
                        "label": _input_setting_label(str(item["key"])),
                        "path": str(item["key"]),
                        "before": current_flat.get(str(item["key"])),
                        "after": item["value"],
                    }
                    for item in actual
                ],
                "approvalRequiredForApply": True,
            }
        if operation == "profile":
            capabilities = self._facade_call("frontend_capabilities")
            source = self._facade_call("input_source_status")
            return {
                "summary": "已读取当前输入方案和前端能力",
                "inputSource": _safe_payload(source),
                "frontend": _safe_payload(capabilities),
            }
        if operation == "candidate_explain":
            query = _bounded_text(args.get("query") or args.get("currentInput"), maximum=240)
            if not query:
                raise ValueError("query is required for ime_input.candidate_explain")
            payload = self._facade_call(
                "candidate_explain",
                {
                    "query": query,
                    "recentContext": _bounded_text(args.get("recentContext"), maximum=800),
                    "project": self.project,
                    "topK": _bounded_int(args.get("topK"), default=5, minimum=1, maximum=10),
                },
            )
            return {"summary": "已解释当前候选的来源与排序", **_safe_mapping_payload(payload)}
        review = self._facade_call(
            "rime_lexicon_review",
            {"project": self.project, "limit": _bounded_int(args.get("limit"), default=50, minimum=1, maximum=100)},
        )
        entries = review.get("entries") if isinstance(review.get("entries"), list) else []
        return {
            "summary": f"有 {len(entries)} 条词表建议等待用户审阅",
            "entryCount": len(entries),
            "reviewRequired": True,
            "entries": [
                _safe_lexicon_review_entry(item)
                for item in entries[:100]
                if isinstance(item, Mapping)
            ],
            "safety": "应用前必须经过词表质量 harness、原生批准和可回滚快照",
        }

    def _voice(self, operation: str, args: Mapping[str, object]) -> dict[str, object]:
        if operation == "privacy_policy":
            return {
                "summary": "语音只把用户确认的最终文本送入对话",
                "partialStored": False,
                "rawAudioStoredByRagIme": False,
                "automaticSend": False,
                "memorySource": "用户发送后的 final/canonical 文本",
                "sensitiveFields": "安全输入框不启动语音写入",
            }
        if operation == "provider_preview":
            allowed = {"op", "provider", "_sessionId"}
            unknown = sorted(str(key) for key in set(args) - allowed)
            if unknown:
                raise ValueError(f"unsupported voice provider field: {unknown[0]}")
            snapshot = self._voice_provider_snapshot()
            desired = self._normalize_voice_provider(args.get("provider"))
            changed = desired != snapshot["provider"]
            return {
                "summary": "语音 Provider 已匹配，无需修改" if not changed else "将切换语音 Provider",
                "changes": (
                    [
                        {
                            "label": "语音服务",
                            "path": "voice.provider",
                            "before": snapshot["provider"],
                            "after": desired,
                        }
                    ]
                    if changed
                    else []
                ),
                "configurationHash": snapshot["configurationHash"],
                "approvalRequiredForApply": changed,
                "requiresVoiceRestart": changed,
                "secretsPreserved": True,
            }
        status = _read_voice_agent_status()
        if operation == "provider_status":
            snapshot = self._voice_provider_snapshot()
            return {
                "summary": "语音 Provider 已就绪" if status.get("credentialsConfigured") else "语音 Provider 尚未就绪",
                "provider": snapshot["provider"],
                "running": bool(status.get("running")),
                "credentialsConfigured": bool(status.get("credentialsConfigured")),
                "networkState": _bounded_text(_mapping_value(status, "telemetry", "networkState"), maximum=80),
                "updatedAtMs": _safe_int(status.get("updatedAtMs")),
            }
        return {
            "summary": "语音输入正在运行" if status.get("running") else "语音输入当前未运行",
            "status": _safe_payload(status),
        }

    def _planning(self, operation: str, args: Mapping[str, object]) -> dict[str, object]:
        if operation != "dashboard":
            raise ValueError("planning write operations require native approval")
        dashboard = self.management.planning_dashboard(
            plan_date=_bounded_text(args.get("date"), maximum=24),
            project=self.project,
        )
        tasks = dashboard.get("tasks") if isinstance(dashboard.get("tasks"), list) else []
        open_count = sum(
            1
            for item in tasks
            if isinstance(item, Mapping) and str(item.get("status") or "") not in {"done", "completed", "cancelled"}
        )
        return {
            "summary": f"当前有 {open_count} 个未完成任务",
            "dashboard": _safe_payload(dashboard),
        }

    def _agent_schedule(
        self,
        operation: str,
        args: Mapping[str, object],
    ) -> dict[str, object]:
        if self.scheduling is None:
            raise ValueError("Agent wake scheduling is unavailable")
        if operation == "list":
            result = self.scheduling.list_wake_schedules(  # type: ignore[attr-defined]
                {
                    "status": args.get("status"),
                    "targetType": args.get("targetType"),
                    "targetId": args.get("targetId"),
                    "limit": args.get("limit"),
                }
            )
            items = result.get("items") if isinstance(result, Mapping) else []
            return {
                "summary": f"共有 {len(items) if isinstance(items, list) else 0} 个可见预约",
                "schedulerActive": bool(result.get("schedulerActive")),
                "items": _safe_payload(items),
            }
        if operation == "runs":
            schedule_id = _bounded_text(args.get("scheduleId"), maximum=240)
            if not schedule_id:
                raise ValueError("scheduleId is required for agent_schedule.runs")
            result = self.scheduling.wake_schedule_runs(  # type: ignore[attr-defined]
                schedule_id,
                {"limit": args.get("limit")},
            )
            return {
                "summary": "已读取预约执行记录",
                "schedule": _safe_payload(result.get("schedule")),
                "items": _safe_payload(result.get("items")),
            }
        raise ValueError("Agent schedule changes require native approval")

    def _prepare_agent_schedule(
        self,
        *,
        session_id: str,
        operation: str,
        args: Mapping[str, object],
        risk_level: str,
    ) -> dict[str, object]:
        if self.scheduling is None:
            raise ValueError("Agent wake scheduling is unavailable")
        if operation == "schedule":
            preview_result = self.scheduling.preview_wake_schedule(  # type: ignore[attr-defined]
                args,
                requested_by_session_id=session_id,
            )
            schedule = (
                preview_result.get("schedule")
                if isinstance(preview_result.get("schedule"), Mapping)
                else {}
            )
            action_payload = {
                key: schedule.get(key)
                for key in (
                    "title",
                    "instruction",
                    "targetType",
                    "targetSessionId",
                    "targetRoleId",
                    "targetRoleVersion",
                    "planningTaskId",
                    "timezone",
                    "recurrenceKind",
                    "recurrenceInterval",
                    "maxRuns",
                    "wakeAtMs",
                )
            }
            base_state: dict[str, object] = {}
            target_name = _bounded_text(schedule.get("targetDisplayName"), maximum=120)
            summary = f"安排{target_name or 'Agent'}在指定时间执行《{schedule.get('title', '')}》"
            changes = [
                {"label": "唤醒对象", "before": "未安排", "after": target_name},
                {
                    "label": "执行次数",
                    "before": "0 次",
                    "after": f"最多 {_safe_int(schedule.get('maxRuns'))} 次",
                },
            ]
        else:
            schedule_id = _bounded_text(args.get("scheduleId"), maximum=240)
            if not schedule_id:
                raise ValueError(f"scheduleId is required for agent_schedule.{operation}")
            schedule = self.scheduling.get_wake_schedule(schedule_id)  # type: ignore[attr-defined]
            action_payload = {"scheduleId": schedule_id, "action": operation}
            base_state = {
                "status": str(schedule.get("status") or ""),
                "updatedAtMs": _safe_int(schedule.get("updatedAtMs")),
            }
            labels = {
                "pause": "暂停预约",
                "resume": "恢复预约",
                "cancel": "取消预约",
                "retry": "重新执行预约",
            }
            summary = f"{labels[operation]}《{schedule.get('title', '')}》"
            changes = [
                {
                    "label": "预约状态",
                    "before": str(schedule.get("status") or ""),
                    "after": operation,
                }
            ]
        digest = _approval_payload_digest(
            session_id=session_id,
            tool="agent_schedule",
            operation=operation,
            action_payload=action_payload,
            base_state=base_state,
        )
        preview = {
            "title": "确认 Agent 预约",
            "summary": summary,
            "operationLabel": "安排未来 Agent 执行" if operation == "schedule" else summary,
            "changes": changes,
            "actionPayload": action_payload,
            "baseState": base_state,
        }
        approval = self.sessions.create_approval(
            session_id=session_id,
            tool_name="agent_schedule",
            operation=operation,
            payload_sha256=digest,
            preview=preview,
            risk_level=risk_level,
            ttl_ms=60_000,
        )
        return {
            "summary": f"等待确认：{summary}",
            "approvalRequired": True,
            "approvalId": approval["approvalId"],
            "approval": approval,
        }

    def _apply_agent_schedule(
        self,
        approval: Mapping[str, object],
    ) -> dict[str, object]:
        if self.scheduling is None:
            raise ValueError("Agent wake scheduling is unavailable")
        operation = str(approval.get("operation") or "")
        preview = approval.get("preview") if isinstance(approval.get("preview"), Mapping) else {}
        action_payload = (
            preview.get("actionPayload")
            if isinstance(preview.get("actionPayload"), Mapping)
            else {}
        )
        base_state = preview.get("baseState") if isinstance(preview.get("baseState"), Mapping) else {}
        expected_digest = _approval_payload_digest(
            session_id=str(approval.get("sessionId") or ""),
            tool="agent_schedule",
            operation=operation,
            action_payload=action_payload,
            base_state=base_state,
        )
        if expected_digest != str(approval.get("payloadSha256") or ""):
            raise ValueError("Agent schedule approval no longer matches its preview")
        if operation == "schedule":
            result = self.scheduling.create_wake_schedule(  # type: ignore[attr-defined]
                action_payload,
                created_by_session_id=str(approval.get("sessionId") or ""),
                require_confirmation=False,
            )
        else:
            schedule_id = _bounded_text(action_payload.get("scheduleId"), maximum=240)
            current = self.scheduling.get_wake_schedule(schedule_id)  # type: ignore[attr-defined]
            if (
                str(current.get("status") or "") != str(base_state.get("status") or "")
                or _safe_int(current.get("updatedAtMs")) != _safe_int(base_state.get("updatedAtMs"))
            ):
                raise ValueError("Agent schedule changed after the approval preview was created")
            result = self.scheduling.wake_schedule_action(  # type: ignore[attr-defined]
                schedule_id,
                {"action": operation},
                require_confirmation=False,
            )
        schedule = result.get("schedule") if isinstance(result, Mapping) else {}
        return {
            "schemaVersion": "rag-ime.agent-operation-receipt.v1",
            "mutationApplied": True,
            "approvalId": str(approval.get("approvalId") or ""),
            "toolId": "agent_schedule",
            "operation": operation,
            "summary": f"预约《{schedule.get('title', '')}》已更新",
            "schedule": _safe_payload(schedule),
            "undoAvailable": False,
        }

    def _memory(self, operation: str, args: Mapping[str, object]) -> dict[str, object]:
        session_id = _bounded_text(args.get("_sessionId"), maximum=240)
        if operation == "capture":
            try:
                capture = AgentMemorySourceStore(
                    self.sessions.db_path,
                    project=self.project,
                ).capture_hint(
                    session_id=session_id,
                    kind=_bounded_text(args.get("kind"), maximum=40),
                    claim=_bounded_text(args.get("claim"), maximum=800),
                    scope=_bounded_text(args.get("captureScope"), maximum=24)
                    or "project",
                    basis=_bounded_text(args.get("basis"), maximum=40),
                    future_use=_bounded_text(args.get("futureUse"), maximum=300),
                    supersedes=_bounded_text(args.get("supersedes"), maximum=800),
                    source_id=_bounded_text(args.get("sourceId"), maximum=240),
                    evidence_ids=[
                        _bounded_text(value, maximum=240)
                        for value in args.get("evidenceIds") or []
                        if _bounded_text(value, maximum=240)
                    ]
                    if isinstance(args.get("evidenceIds"), (list, tuple))
                    else [],
                )
            except ValueError as exc:
                message = str(exc)
                reason_code = next(
                    (
                        code
                        for marker, code in (
                            ("workflow noise or transient input", "not_durable"),
                            ("sensitive content", "sensitive"),
                            ("no active user evidence", "no_user_evidence"),
                            ("missing or outside this session", "needs_source"),
                            ("source is not eligible", "conflict_needs_review"),
                            ("unsupported memory capture basis", "invalid_basis"),
                            ("only a correction", "invalid_correction"),
                        )
                        if marker in message
                    ),
                    "invalid_candidate",
                )
                return {
                    "summary": "这条内容没有进入记忆候选层",
                    "candidate": "rejected",
                    "createsDurableMemory": False,
                    "reasonCode": reason_code,
                    "retryable": reason_code == "needs_source",
                }
            return {
                "summary": "已标记一条待后台整理的记忆候选，不创建正式 Atom",
                **capture,
            }
        visible_owners, mutable_owner = self._memory_owner_context(session_id)
        curation_owner = _personal_memory_curation_owner(
            visible_owners,
            fallback=mutable_owner,
        )
        visible_owner_payload = _owner_payloads(visible_owners)
        if operation in {"remember_preview", "correct_preview", "forget_preview"}:
            return self._governed_memory_store().preview(
                operation,
                args,
                session_id=session_id,
            )
        if operation in {"get", "review"} and _bounded_text(
            args.get("draftId"),
            maximum=240,
        ):
            return self._governed_memory_store().daily_user_memory_draft(
                draft_id=_bounded_text(args.get("draftId"), maximum=240),
                session_id=_bounded_text(args.get("_sessionId"), maximum=240),
            )
        if operation == "review":
            raise ValueError("draftId is required for ime_memory.review")
        if operation in {"search", "get", "explain"}:
            kind = _bounded_text(args.get("kind"), maximum=40) or "atoms"
            if kind in {"atoms", "timelines"}:
                return self._governed_memory_store().read(operation, args)
            if operation != "search":
                raise ValueError(
                    f"ime_memory.{operation} only supports governed Atom records"
                )
            if _bounded_text(args.get("mode"), maximum=24) not in {"", "current"}:
                raise ValueError(
                    "historical/change modes are only available for governed Atom records"
                )
        if operation == "catalog":
            return self._catalog(args, visible_owners=visible_owners)
        if operation == "read":
            return self._read(args, visible_owners=visible_owners)
        if operation == "recent":
            return self._recent(args, visible_owners=visible_owners)
        if operation == "trace":
            trace_id = _bounded_text(args.get("traceId"), maximum=240)
            if not trace_id:
                raise ValueError("traceId is required for ime_memory.trace")
            payload = self._facade_call("memory_optimizer_trace", {"traceId": trace_id})
            return {"summary": "已读取记忆整理追溯信息", "trace": _safe_payload(payload)}
        if operation == "maintenance_status":
            payload = self._facade_call(
                "agent_memory_maintenance_status",
                {
                    "project": self.project,
                    "limit": _bounded_int(args.get("limit"), default=10, minimum=1, maximum=30),
                    "ownerKind": curation_owner[0],
                    "ownerId": curation_owner[1],
                    "scope": _bounded_text(args.get("scope"), maximum=24) or "incremental",
                    "policy": _bounded_text(args.get("policy"), maximum=24) or "conservative",
                },
            )
            draft_count = _safe_int(payload.get("pendingDraftCount"))
            pending_count = _safe_int(
                _mapping_value(payload, "compileState", "pendingEventCount")
            )
            return {
                "summary": f"有 {pending_count} 条来源待整理、{draft_count} 份草案待审阅",
                "maintenance": _safe_payload(payload),
            }
        if operation in {"curation_prepare", "maintenance_preview"}:
            trigger = _bounded_text(args.get("trigger"), maximum=40)
            if trigger not in {"task_completion", "explicit_request", "idle_batch"}:
                raise ValueError(
                    "ime_memory.curation_prepare requires trigger="
                    "task_completion, explicit_request, or idle_batch"
                )
            payload = self._facade_call(
                "agent_memory_maintenance_prepare",
                {
                    "project": self.project,
                    "instruction": _bounded_text(args.get("instruction"), maximum=800),
                    "trigger": trigger,
                    "ownerKind": curation_owner[0],
                    "ownerId": curation_owner[1],
                },
            )
            if payload.get("ok") is not True:
                raise ValueError(_memory_curation_error(payload))
            source = payload.get("source") if isinstance(payload.get("source"), Mapping) else {}
            pending_count = _safe_int(source.get("pendingSourceCount"))
            needs_review_count = _safe_int(source.get("needsReviewSourceCount"))
            batch_count = _safe_int(source.get("batchCount"))
            drain_limited = source.get("drainLimited") is True
            stored = payload.get("storedRun") if isinstance(payload.get("storedRun"), Mapping) else {}
            run_id = _bounded_text(stored.get("runId"), maximum=240)
            if not run_id:
                return {
                    "summary": (
                        "当前没有新增个人记忆证据需要整理"
                        if pending_count <= 0
                        else (
                            f"仍有 {needs_review_count} 条个人记忆证据需要人工确认"
                            if needs_review_count > 0
                            else f"仍有 {pending_count} 条个人记忆证据等待后续整理"
                        )
                    ),
                    "runId": "",
                    "counts": {},
                    "diffCount": 0,
                    "needsReview": False,
                    "reviewRequired": False,
                    "storedDraft": False,
                    "reusedDraft": payload.get("reusedDraft") is True,
                    "skipped": True,
                    "reason": _memory_curation_skip_reason(payload),
                    "pendingSourceCount": pending_count,
                    "needsReviewSourceCount": needs_review_count,
                    "batchCount": batch_count,
                    "drainLimited": drain_limited,
                }
            review = self._facade_call(
                "agent_memory_maintenance_run",
                {
                    "runId": run_id,
                    "project": self.project,
                    "visibleOwners": visible_owner_payload,
                },
            )
            run = review.get("run") if isinstance(review.get("run"), Mapping) else {}
            _require_memory_run_owner(run, curation_owner)
            diff_count = _safe_int(run.get("diffCount"))
            reused = payload.get("reusedDraft") is True
            receipt = _compact_memory_run_for_agent(run)
            needs_review = receipt["status"] == "draft" and diff_count > 0
            return {
                "summary": (
                    (
                        f"已复用现有记忆草案，共 {diff_count} 项差异"
                        + (
                            f"；另有 {pending_count} 条证据留待下一轮整理"
                            if pending_count > 0
                            else ""
                        )
                    )
                    if reused
                    else (
                        (
                            f"已生成记忆草案，共 {diff_count} 项差异"
                            + (
                                f"；另有 {pending_count} 条证据留待下一轮整理"
                                if pending_count > 0
                                else ""
                            )
                        )
                        if needs_review
                        else (
                            (
                                f"已整理 {max(batch_count, 1)} 批证据，有 "
                                f"{needs_review_count} 条需要人工确认"
                            )
                            if needs_review_count > 0
                            else (
                                f"已整理 {max(batch_count, 1)} 批证据，仍有 "
                                f"{pending_count} 条等待后续整理"
                                if pending_count > 0
                                else "全部新增证据已完成整理，没有需要写入的变更"
                            )
                        )
                    )
                ),
                "runId": receipt["runId"],
                "counts": receipt["operationCounts"],
                "diffCount": receipt["diffCount"],
                "needsReview": needs_review,
                # Pi's native review bridge still consumes this compatibility
                # field; the semantic result field is needsReview.
                "reviewRequired": needs_review,
                "storedDraft": needs_review,
                "reusedDraft": reused,
                "pendingSourceCount": pending_count,
                "needsReviewSourceCount": needs_review_count,
                "batchCount": batch_count,
                "drainLimited": drain_limited,
                # The Memory page fetches full diffs out of band. Returning the
                # whole draft here would feed dozens of database operations
                # back into the main Agent transcript for no useful reason.
            }
        if operation == "maintenance_review":
            run_id = _bounded_text(args.get("runId"), maximum=240)
            if not run_id:
                raise ValueError("runId is required for ime_memory.maintenance_review")
            review = self._facade_call(
                "agent_memory_maintenance_run",
                {
                    "runId": run_id,
                    "project": self.project,
                    "visibleOwners": visible_owner_payload,
                },
            )
            run = review.get("run") if isinstance(review.get("run"), Mapping) else {}
            _require_memory_run_visible(run, visible_owners)
            receipt = _compact_memory_run_for_agent(run)
            needs_review = (
                receipt["status"] == "draft"
                and int(receipt["diffCount"]) > 0
            )
            return {
                "summary": f"已读取记忆草案 {run_id} 的 {_safe_int(run.get('diffCount'))} 项差异",
                "runId": receipt["runId"],
                "counts": receipt["operationCounts"],
                "diffCount": receipt["diffCount"],
                "needsReview": needs_review,
                "reviewRequired": needs_review,
                "canApply": review.get("canApply") is True,
                "canRollback": review.get("canRollback") is True,
                "stale": review.get("stale") is True,
            }
        kind = _bounded_text(args.get("kind"), maximum=40) or "atoms"
        if kind not in {
            "apps",
            "books",
            "atoms",
            "timelines",
            "evidence",
            "tags",
            "phrases",
            "groups",
        }:
            raise ValueError("unsupported memory list kind")
        query = _bounded_text(args.get("query"), maximum=240)
        limit = _bounded_int(args.get("limit"), default=8, minimum=1, maximum=20)
        page = self.management.memory_page(
            kind,
            page_request(
                {
                    "query": query,
                    "limit": limit,
                    "visibleOwners": visible_owner_payload,
                    "project": self.project,
                }
            ),
        )
        items = page.get("items", []) if isinstance(page, Mapping) else []
        return {
            "summary": f"检索到 {len(items)} 条 {kind} 记忆记录",
            "kind": kind,
            "query": query,
            "items": _safe_payload(items),
            "nextCursor": _bounded_text(page.get("nextCursor"), maximum=80),
        }

    def _governed_memory_store(self) -> MemoryGovernanceProposalStore:
        if self._memory_governance_store is None:
            db_path = getattr(self.sessions, "db_path", None)
            if db_path is None:
                raise ValueError("memory governance storage is unavailable")
            store = MemoryGovernanceProposalStore(db_path, project=self.project)
            store.initialize()
            self._memory_governance_store = store
        return self._memory_governance_store

    def _role_book(
        self,
        operation: str,
        args: Mapping[str, object],
    ) -> dict[str, object]:
        session_id = _bounded_text(args.get("_sessionId"), maximum=240)
        if not session_id:
            raise ValueError("agent_role_book session is missing")
        if self._role_book_tool_adapter is None:
            store = self.role_books
            if store is None:
                db_path = getattr(self.sessions, "db_path", None)
                if db_path is None:
                    raise ValueError("Agent Role Book storage is unavailable")
                store = AgentRoleBookStore(db_path)
                store.initialize()
                self.role_books = store
            db_path = getattr(store, "db_path", None) or getattr(
                self.sessions, "db_path", None
            )
            if db_path is None:
                raise ValueError("Agent Role Book history storage is unavailable")
            self._role_book_tool_adapter = AgentRoleBookToolAdapter(
                store,
                db_path=db_path,
                project=self.project,
            )
        return self._role_book_tool_adapter.execute(
            operation,
            args,
            session=self.sessions.get(session_id),
        )

    def _knowledge(self, operation: str, args: Mapping[str, object]) -> dict[str, object]:
        if operation == "status" and self.knowledge_client is None:
            return {
                "summary": "文档知识库当前不可用",
                "available": False,
                "state": "unavailable",
                "reason": "knowledge_client_not_configured",
            }
        client = self.knowledge_client
        if client is None:
            raise ValueError("document knowledge library is unavailable")

        payload: dict[str, object] = {}
        if operation in {"search", "find", "open"}:
            base_id = _bounded_text(args.get("kbId") or args.get("baseId"), maximum=240)
            if not base_id:
                raise ValueError(f"kbId is required for ime_knowledge.{operation}")
            payload["kbId"] = base_id
        if operation == "search":
            query = _bounded_text(args.get("query"), maximum=500)
            if not query:
                raise ValueError("query is required for ime_knowledge.search")
            search_mode = _bounded_text(args.get("searchMode"), maximum=24) or "hybrid"
            if search_mode not in {"hybrid", "lexical", "dense"}:
                raise ValueError("searchMode must be hybrid, lexical, or dense")
            payload.update(
                {
                    "query": query,
                    "topK": _bounded_int(args.get("topK"), default=6, minimum=1, maximum=12),
                    "mode": search_mode,
                }
            )
            file_name = _bounded_text(args.get("fileName"), maximum=240)
            if file_name:
                payload["fileName"] = file_name
        elif operation == "find":
            file_id = _bounded_text(args.get("fileId"), maximum=240)
            raw_patterns = args.get("patterns")
            if isinstance(raw_patterns, str):
                patterns = [_bounded_text(raw_patterns, maximum=240)]
            elif isinstance(raw_patterns, (list, tuple)):
                patterns = [_bounded_text(item, maximum=240) for item in raw_patterns[:10]]
            else:
                patterns = []
            patterns = [item for item in patterns if item]
            if not file_id:
                raise ValueError("fileId is required for ime_knowledge.find")
            if not patterns:
                raise ValueError("patterns are required for ime_knowledge.find")
            payload.update(
                {
                    "fileId": file_id,
                    "patterns": patterns,
                    "useRegex": args.get("useRegex") is True,
                    "caseSensitive": args.get("caseSensitive") is True,
                    "maxWindows": _bounded_int(
                        args.get("maxWindows"), default=8, minimum=1, maximum=20
                    ),
                    "windowSize": _bounded_int(
                        args.get("windowSize"), default=24, minimum=4, maximum=120
                    ),
                    "offset": _bounded_int(args.get("offset"), default=0, minimum=0, maximum=1_000_000),
                }
            )
        elif operation == "open":
            file_id = _bounded_text(args.get("fileId"), maximum=240)
            if not file_id:
                raise ValueError("fileId is required for ime_knowledge.open")
            payload.update(
                {
                    "fileId": file_id,
                    "line": _bounded_int(args.get("line"), default=1, minimum=1, maximum=50_000_000),
                    "offset": _bounded_int(
                        args.get("offset"), default=0, minimum=0, maximum=50_000_000
                    ),
                    "windowSize": _bounded_int(
                        args.get("windowSize"), default=180, minimum=1, maximum=300
                    ),
                }
            )

        handler = getattr(client, operation, None)
        if not callable(handler):
            raise ValueError(f"document knowledge operation {operation} is unavailable")
        result = handler(payload)
        if not isinstance(result, Mapping):
            raise ValueError("document knowledge client returned an invalid result")
        safe_result = _safe_knowledge_payload(result)
        if "summary" not in safe_result:
            counts = safe_result.get("items")
            count = len(counts) if isinstance(counts, list) else 0
            summaries = {
                "list_bases": f"已列出 {count} 个可供 Agent 使用的文档知识库",
                "search": f"文档知识库返回 {count} 条引用证据",
                "find": f"在文档内找到 {count} 个匹配窗口",
                "open": "已读取文档引用窗口",
                "status": "已读取文档知识库状态",
            }
            safe_result["summary"] = summaries[operation]
        safe_result.setdefault("untrustedData", True)
        return safe_result

    def _models(self, operation: str, args: Mapping[str, object]) -> dict[str, object]:
        if operation == "status":
            payload = self._facade_call("models_status")
            return {"summary": _model_status_summary(payload), "status": _safe_payload(payload)}
        if operation == "profiles":
            snapshot = self._model_profile_snapshot()
            return {
                "summary": "已读取即时补全与知识模型的非密钥 Provider 配置",
                "profiles": _safe_payload(snapshot["profiles"]),
                "configurationHash": snapshot["configurationHash"],
                "secretsVisible": False,
            }
        if operation == "profile_preview":
            allowed = {"op", "slot", "provider", "endpoint", "model", "_sessionId"}
            unknown = sorted(str(key) for key in set(args) - allowed)
            if unknown:
                raise ValueError(f"unsupported model profile field: {unknown[0]}")
            snapshot = self._model_profile_snapshot()
            profiles = snapshot["profiles"] if isinstance(snapshot.get("profiles"), Mapping) else {}
            slot = _bounded_text(args.get("slot"), maximum=40)
            current = profiles.get(slot) if isinstance(profiles.get(slot), Mapping) else {}
            desired = self._normalize_model_profile(slot=slot, requested=args, current=current)
            changes = [
                {
                    "label": {"provider": "服务", "endpoint": "服务地址", "model": "模型"}[key],
                    "path": f"{slot}.{key}",
                    "before": current.get(key, ""),
                    "after": desired[key],
                }
                for key in ("provider", "endpoint", "model")
                if current.get(key, "") != desired[key]
            ]
            return {
                "summary": "配置已匹配，无需修改" if not changes else f"将更新 {len(changes)} 项 Provider 配置",
                "slot": slot,
                "changes": changes,
                "configurationHash": snapshot["configurationHash"],
                "restartComponent": "predictor" if slot == "instant" else "sidecar",
                "approvalRequiredForApply": bool(changes),
                "secretsPreserved": True,
            }
        if operation == "probe":
            payload = self._facade_call("model_probe", {})
            return {"summary": "已完成只读模型能力探测", "probe": _safe_payload(payload)}
        stats = getattr(self.core, "suggestion_cache_stats", None)
        payload = stats() if callable(stats) else {"available": False}
        return {"summary": "已读取本地候选缓存统计", "cache": _safe_payload(payload)}

    def _runtime(self, operation: str, args: Mapping[str, object]) -> dict[str, object]:
        del args
        if operation == "components":
            payload = self.management.runtime_components()
            return {"summary": "已读取运行组件列表", "runtime": _safe_payload(payload)}
        status = self.management.runtime_status()
        components = status.get("components") if isinstance(status.get("components"), Mapping) else {}
        unhealthy = [
            str(key)
            for key, value in components.items()
            if isinstance(value, Mapping) and value.get("ok") is not True
        ]
        if operation == "diagnose":
            return {
                "summary": "未发现异常" if not unhealthy else f"发现 {len(unhealthy)} 个未就绪组件",
                "unhealthyComponents": unhealthy,
                "components": _safe_payload(components),
                "mutationsAvailable": False,
            }
        return {"summary": "运行时状态已读取", "runtime": _safe_payload(status)}

    def _configuration(self, operation: str, args: Mapping[str, object]) -> dict[str, object]:
        limit = _bounded_int(args.get("limit"), default=20, minimum=1, maximum=50)
        query = _bounded_text(args.get("query"), maximum=240)
        if operation == "history":
            history = self.management.history_page(page_request({"query": query, "limit": limit}))
            items = history.get("items", []) if isinstance(history, Mapping) else []
            return {
                "summary": f"读取 {len(items)} 条隐私化历史摘要",
                "items": _safe_payload(items),
                "rawTextVisible": False,
                "nextCursor": _bounded_text(history.get("nextCursor"), maximum=80),
            }
        if operation == "export_preview":
            overview = self.management.overview()
            memory = overview.get("memory") if isinstance(overview.get("memory"), Mapping) else {}
            return {
                "summary": "可导出数据库、非敏感设置和安全的 Rime 配置",
                "scope": ["database", "redacted_settings", "safe_rime_configuration"],
                "memoryBookCount": _safe_int(memory.get("memoryBookCount")),
                "secretsIncluded": False,
                "modelFilesIncluded": False,
                "approvalRequiredForExport": True,
            }
        if operation == "restore_preview":
            source_approval_id = _bounded_text(args.get("sourceApprovalId"), maximum=240)
            _source, target = self._configuration_export_source(
                session_id=_bounded_text(args.get("sessionId"), maximum=240)
                or _bounded_text(args.get("_sessionId"), maximum=240),
                source_approval_id=source_approval_id,
            )
            payload = self.management.portable_restore_preview({"path": str(target)})
            return {
                "summary": f"已验证备份 {target.name}，恢复会替换数据库、设置和 Rime 配置",
                "sourceApprovalId": source_approval_id,
                "fileName": target.name,
                "valid": payload.get("valid") is True,
                "createdAtMs": _safe_int(payload.get("createdAtMs")),
                "databaseCounts": _safe_payload(payload.get("databaseCounts")),
                "databaseMigrationVersion": _safe_int(payload.get("databaseMigrationVersion")),
                "rimeFileCount": _safe_int(payload.get("rimeFileCount")),
                "requiresRestart": payload.get("requiresRestart") is True,
                "restoreApplyAvailable": True,
                "restoreApplyRisk": "R3",
                "externalSupervisorRequired": True,
            }
        payload = self._facade_call(
            "management_audit",
            {"limit": limit, "action": _bounded_text(args.get("action"), maximum=120)},
        )
        items = payload.get("items") if isinstance(payload.get("items"), list) else []
        return {"summary": f"读取 {len(items)} 条管理审计记录", "items": _safe_payload(items)}

    def _facade_call(self, name: str, payload: Mapping[str, object] | None = None) -> dict[str, object]:
        target = getattr(self.facade, name, None)
        if not callable(target):
            raise ValueError(f"control capability is unavailable: {name}")
        result = target(dict(payload)) if payload is not None else target()
        if not isinstance(result, Mapping):
            raise ValueError(f"control capability returned an invalid payload: {name}")
        return dict(result)

    def _catalog(
        self,
        args: Mapping[str, object],
        *,
        visible_owners: tuple[tuple[str, str], ...],
    ) -> dict[str, object]:
        query = _bounded_text(args.get("query"), maximum=240)
        limit = _bounded_int(args.get("limit"), default=5, minimum=1, maximum=8)
        request = page_request(
            {
                "query": query,
                "limit": limit,
                "visibleOwners": _owner_payloads(visible_owners),
            }
        )
        books = self.management.memory_page("books", request).get("items", [])
        groups = self.management.memory_page("groups", request).get("items", [])
        tags = self.management.memory_page("tags", request).get("items", [])
        safe_books = [_catalog_book(item) for item in books if isinstance(item, Mapping)]
        safe_groups = [_catalog_group(item) for item in groups if isinstance(item, Mapping)]
        safe_tags = [_catalog_tag(item) for item in tags if isinstance(item, Mapping)]
        items = [*safe_books, *safe_groups, *safe_tags]
        return {
            "summary": (
                f"查询到 {len(safe_books)} 本工具书、"
                f"{len(safe_groups)} 个 Group、{len(safe_tags)} 个 Tag"
            ),
            "query": query,
            "counts": {
                "books": len(safe_books),
                "groups": len(safe_groups),
                "tags": len(safe_tags),
            },
            "items": items,
        }

    def _read(
        self,
        args: Mapping[str, object],
        *,
        visible_owners: tuple[tuple[str, str], ...],
    ) -> dict[str, object]:
        book_id = _bounded_text(args.get("bookId"), maximum=240)
        if not book_id:
            raise ValueError("bookId is required for ime_memory.read")
        report = self.management.memory_page(
            "books",
            page_request(
                {
                    "limit": 500,
                    "visibleOwners": _owner_payloads(visible_owners),
                }
            ),
        )
        match = next(
            (
                item
                for item in report.get("items", [])
                if isinstance(item, Mapping) and str(item.get("id") or "") == book_id
            ),
            None,
        )
        if match is None:
            raise ValueError("memory book not found")
        memories = [
            {
                "memoryId": _bounded_text(item.get("id"), maximum=240),
                "type": _bounded_text(item.get("type"), maximum=80),
                "text": _bounded_text(item.get("text"), maximum=1200),
                "updatedAtMs": _safe_int(item.get("updatedAtMs")),
                **(
                    {
                        "ref": _memory_reference(
                            "atom",
                            _bounded_text(item.get("id"), maximum=240),
                            legacy_type="memory_atom",
                        )
                    }
                    if _bounded_text(item.get("id"), maximum=240)
                    else {}
                ),
            }
            for item in match.get("memories", [])
            if isinstance(item, Mapping)
        ][:20]
        title = _bounded_text(match.get("title"), maximum=180)
        book_ref = _coerce_memory_reference(
            match.get("ref"),
            fallback_kind="book",
            fallback_id=book_id,
            legacy_type="book",
        )
        evidence_refs = _safe_memory_references(match.get("evidenceRefs"), limit=80)
        return {
            "summary": f"已读取工具书《{title or '未命名'}》，包含 {len(memories)} 条相关记忆",
            "book": {
                "bookId": book_id,
                "title": title,
                "summary": _bounded_text(match.get("summary"), maximum=1600),
                "type": _bounded_text(match.get("type"), maximum=80),
                "tags": _string_list(match.get("tags"), limit=20),
                "sourceStartMs": _safe_int(match.get("sourceStartMs")),
                "sourceEndMs": _safe_int(match.get("sourceEndMs")),
                "memories": memories,
                "ref": book_ref,
                "evidenceRefs": evidence_refs,
            },
            "items": [{"title": title, "kind": "book", "ref": book_ref}],
        }

    def _recent(
        self,
        args: Mapping[str, object],
        *,
        visible_owners: tuple[tuple[str, str], ...],
    ) -> dict[str, object]:
        query = _bounded_text(args.get("query"), maximum=240)
        limit = _bounded_int(args.get("limit"), default=8, minimum=1, maximum=12)
        raw_items: list[Mapping[str, object]] = []
        for disposition in ("remember", "consolidated"):
            report = self.management.memory_page(
                "evidence",
                page_request(
                    {
                        "query": query,
                        "limit": limit,
                        "status": disposition,
                        "visibleOwners": _owner_payloads(visible_owners),
                    }
                ),
            )
            raw_items.extend(
                item
                for item in report.get("items", [])
                if isinstance(item, Mapping)
            )

        seen: set[str] = set()
        items: list[dict[str, object]] = []
        for item in sorted(
            raw_items,
            key=lambda value: (
                _safe_int(value.get("createdAtMs")),
                _bounded_text(value.get("id") or value.get("itemId"), maximum=240),
            ),
            reverse=True,
        ):
            source_id = _bounded_text(
                item.get("id") or item.get("itemId"),
                maximum=240,
            )
            disposition = _bounded_text(
                item.get("disposition") or item.get("status"),
                maximum=40,
            )
            text = _bounded_text(item.get("text"), maximum=1200)
            if (
                not source_id
                or source_id in seen
                or disposition not in {"remember", "consolidated"}
                or item.get("sensitive") is True
                or not text
            ):
                continue
            seen.add(source_id)
            raw_source = item.get("source")
            source_ref = (
                _safe_memory_source(raw_source)
                if isinstance(raw_source, Mapping)
                else {}
            )
            legacy_source = (
                _bounded_text(item.get("transportSource"), maximum=80)
                if source_ref
                else _bounded_text(raw_source, maximum=80)
            )
            ref = _coerce_memory_reference(
                item.get("ref"),
                fallback_kind="evidence",
                fallback_id=source_id,
                legacy_type="evidence",
            )
            items.append(
                {
                    "sourceId": source_id,
                    "createdAtMs": _safe_int(item.get("createdAtMs")),
                    # Keep the historical string field while exposing the new
                    # structured source and actionable stable reference.
                    "source": legacy_source,
                    "sourceRef": source_ref,
                    "ref": ref,
                    "evidenceRefs": _safe_memory_references(
                        item.get("evidenceRefs"),
                        limit=40,
                    ),
                    "sourceKind": _bounded_text(item.get("type"), maximum=80),
                    "text": text,
                    "app": _bounded_text(item.get("app"), maximum=160),
                    "project": _bounded_text(item.get("project"), maximum=160),
                    "ownerKind": _bounded_text(item.get("ownerKind"), maximum=40),
                    "ownerId": _bounded_text(item.get("ownerId"), maximum=160),
                    "disposition": disposition,
                }
            )
            if len(items) >= limit:
                break
        return {
            "summary": f"召回 {len(items)} 段已治理记忆证据",
            "query": query,
            "count": len(items),
            "items": items,
        }

    def _memory_owner_context(
        self,
        session_id: str,
    ) -> tuple[tuple[tuple[str, str], ...], tuple[str, str]]:
        if not session_id:
            raise ValueError("memory tool session is missing")
        session = self.sessions.get(session_id)
        role_id = _bounded_text(session.get("roleId"), maximum=160)
        mutable_owner = ("agent", role_id) if role_id else ("session", session_id)
        room_ids: tuple[str, ...] = ()
        rooms = getattr(self.collaboration, "rooms", None)
        participant_for_session = getattr(rooms, "participant_for_session", None)
        if callable(participant_for_session):
            participant = participant_for_session(session_id)
            if isinstance(participant, Mapping):
                room_id = _bounded_text(participant.get("roomId"), maximum=240)
                if room_id:
                    room_ids = (room_id,)
        visible = agent_visible_memory_owners(
            project=self.project,
            role_id=role_id,
            session_id=session_id,
            room_ids=room_ids,
        )
        return visible, mutable_owner


def _catalog_book(item: Mapping[str, object]) -> dict[str, object]:
    book_id = _bounded_text(item.get("id"), maximum=240)
    return {
        "kind": "book",
        "bookId": book_id,
        "title": _bounded_text(item.get("title"), maximum=180),
        "summary": _bounded_text(item.get("summary"), maximum=800),
        "tags": _string_list(item.get("tags"), limit=20),
        "atomCount": _safe_int(item.get("atomCount")),
        "updatedAtMs": _safe_int(item.get("updated_at_ms") or item.get("updatedAtMs")),
        "ownerKind": _bounded_text(item.get("ownerKind"), maximum=40),
        "ownerId": _bounded_text(item.get("ownerId"), maximum=160),
        "ref": _coerce_memory_reference(
            item.get("ref"),
            fallback_kind="book",
            fallback_id=book_id,
            legacy_type="book",
        ),
        "evidenceRefs": _safe_memory_references(
            item.get("evidenceRefs"),
            limit=80,
        ),
    }


_MEMORY_REFERENCE_KINDS = frozenset(
    {"event", "evidence", "atom", "book", "timeline", "role_book_revision"}
)


def _memory_reference(
    kind: str,
    reference_id: str,
    *,
    legacy_type: str = "",
    label: str = "",
) -> dict[str, object]:
    value: dict[str, object] = {
        "kind": kind,
        "id": reference_id,
        "referenceKind": kind,
        "referenceId": reference_id,
    }
    if legacy_type:
        value["type"] = legacy_type
    if label:
        value["label"] = label
    return value


def _coerce_memory_reference(
    value: object,
    *,
    fallback_kind: str,
    fallback_id: str,
    legacy_type: str,
) -> dict[str, object]:
    source = value if isinstance(value, Mapping) else {}
    kind = _bounded_text(
        source.get("referenceKind") or source.get("kind") or fallback_kind,
        maximum=40,
    )
    if kind not in _MEMORY_REFERENCE_KINDS:
        kind = fallback_kind
    reference_id = _bounded_text(
        source.get("referenceId") or source.get("id") or fallback_id,
        maximum=240,
    )
    if not reference_id:
        return {}
    return _memory_reference(
        kind,
        reference_id,
        legacy_type=_bounded_text(source.get("type"), maximum=80) or legacy_type,
        label=_bounded_text(source.get("label"), maximum=180),
    )


def _safe_memory_references(value: object, *, limit: int) -> list[dict[str, object]]:
    if not isinstance(value, (list, tuple)):
        return []
    result: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for raw in value[: max(0, limit)]:
        if not isinstance(raw, Mapping):
            continue
        kind = _bounded_text(
            raw.get("referenceKind") or raw.get("kind"),
            maximum=40,
        )
        reference_id = _bounded_text(
            raw.get("referenceId") or raw.get("id"),
            maximum=240,
        )
        identity = (kind, reference_id)
        if kind not in _MEMORY_REFERENCE_KINDS or not reference_id or identity in seen:
            continue
        seen.add(identity)
        result.append(
            _memory_reference(
                kind,
                reference_id,
                legacy_type=_bounded_text(raw.get("type"), maximum=80) or kind,
                label=_bounded_text(raw.get("label"), maximum=180),
            )
        )
    return result


def _safe_memory_source(value: Mapping[str, object]) -> dict[str, object]:
    kind = _bounded_text(value.get("kind") or value.get("type"), maximum=80)
    source_id = _bounded_text(value.get("id"), maximum=320)
    if not kind or not source_id:
        return {}
    result: dict[str, object] = {"kind": kind, "id": source_id}
    source_kind = _bounded_text(value.get("sourceKind"), maximum=120)
    if source_kind:
        result["sourceKind"] = source_kind
    legacy_type = _bounded_text(value.get("type"), maximum=80)
    if legacy_type:
        result["type"] = legacy_type
    return result


def _compact_memory_run_for_agent(run: Mapping[str, object]) -> dict[str, object]:
    return {
        "runId": _bounded_text(run.get("runId"), maximum=240),
        "createdAtMs": _safe_int(run.get("createdAtMs")),
        "status": _bounded_text(run.get("status"), maximum=40),
        "summary": _bounded_text(run.get("summary"), maximum=240),
        "diffCount": _safe_int(run.get("diffCount")),
        "pendingDiffCount": _safe_int(run.get("pendingDiffCount")),
        "appliedDiffCount": _safe_int(run.get("appliedDiffCount")),
        "operationCounts": _safe_payload(run.get("operationCounts")),
        "sourceCursor": _safe_payload(run.get("sourceCursor")),
    }


def _catalog_group(item: Mapping[str, object]) -> dict[str, object]:
    return {
        "kind": "group",
        "title": _bounded_text(item.get("title"), maximum=180),
        "summary": _bounded_text(item.get("note"), maximum=600),
        "tags": _string_list(item.get("tags"), limit=20),
        "itemCount": _safe_int(item.get("event_count")),
        "updatedAtMs": _safe_int(item.get("updated_at_ms") or item.get("latestAtMs")),
    }


def _catalog_tag(item: Mapping[str, object]) -> dict[str, object]:
    return {
        "kind": "tag",
        "title": _bounded_text(item.get("tag"), maximum=180),
        "summary": _bounded_text(item.get("description"), maximum=600),
        "itemCount": _safe_int(item.get("item_count")),
        "updatedAtMs": _safe_int(item.get("updated_at_ms") or item.get("updatedAtMs")),
    }


def _owner_payloads(
    owners: tuple[tuple[str, str], ...],
) -> list[dict[str, str]]:
    return [
        {"ownerKind": owner_kind, "ownerId": owner_id}
        for owner_kind, owner_id in owners
    ]


def _personal_memory_curation_owner(
    visible_owners: tuple[tuple[str, str], ...],
    *,
    fallback: tuple[str, str],
) -> tuple[str, str]:
    personal_owner = ("user", "default")
    return personal_owner if personal_owner in visible_owners else fallback


def _memory_mutation_owners(
    visible_owners: tuple[tuple[str, str], ...],
    *,
    mutable_owner: tuple[str, str],
) -> frozenset[tuple[str, str]]:
    owners = {mutable_owner}
    personal_owner = ("user", "default")
    if personal_owner in visible_owners:
        owners.add(personal_owner)
    return frozenset(owners)


def _memory_run_owner(run: Mapping[str, object]) -> tuple[str, str]:
    owner = (
        _bounded_text(run.get("ownerKind"), maximum=40),
        _bounded_text(run.get("ownerId"), maximum=160),
    )
    if not all(owner):
        raise ValueError("memory run owner is unavailable")
    return owner


def _require_memory_run_owner(
    run: Mapping[str, object],
    expected_owner: tuple[str, str],
) -> None:
    actual = _memory_run_owner(run)
    if actual != expected_owner:
        raise ValueError("memory run is outside the current role")


def _require_memory_run_visible(
    run: Mapping[str, object],
    visible_owners: tuple[tuple[str, str], ...],
) -> None:
    if _memory_run_owner(run) not in visible_owners:
        raise ValueError("memory run is outside the current visible owner scope")


def _memory_curation_error(payload: Mapping[str, object]) -> str:
    validation = payload.get("validation")
    errors = validation.get("errors") if isinstance(validation, Mapping) else None
    if isinstance(errors, (list, tuple)):
        messages = [
            _bounded_text(item, maximum=160)
            for item in errors
            if _bounded_text(item, maximum=160)
        ]
        if messages:
            return "; ".join(messages)[:240]
    message = _bounded_text(errors, maximum=240)
    return message or _bounded_text(payload.get("error"), maximum=240) or "memory draft generation failed validation"


def _memory_curation_skip_reason(payload: Mapping[str, object]) -> str:
    curation = payload.get("curation")
    results = curation.get("results") if isinstance(curation, Mapping) else None
    if isinstance(results, list):
        for item in results:
            if not isinstance(item, Mapping):
                continue
            reason = _bounded_text(item.get("reason"), maximum=80)
            if reason:
                return reason
    return "no_durable_changes"


def _safe_lexicon_review_entry(item: Mapping[str, object]) -> dict[str, object]:
    text = _bounded_text(item.get("text"), maximum=120)
    pinyin = _bounded_text(item.get("pinyin"), maximum=240)
    review_key = str(item.get("reviewKey") or f"{text}\t{pinyin}").strip()[:300]
    return {
        "text": text,
        "pinyin": pinyin,
        "reviewKey": review_key,
        "selected": item.get("selected") is not False,
        "weight": _safe_int(item.get("weight")),
        "positiveCount": _safe_int(item.get("positiveCount")),
        "reviewSource": _bounded_text(item.get("reviewSource"), maximum=80),
        "reviewReason": _bounded_text(item.get("reviewReason"), maximum=240),
    }


def _bounded_text(value: object, *, maximum: int) -> str:
    text = " ".join(str(value or "").split())
    text = re.sub(r"\[L:[^\]]+\]", "", text)
    return " ".join(text.split())[:maximum]


def _normalize_input_setting_changes(value: object) -> list[dict[str, object]]:
    if isinstance(value, Mapping):
        raw_items = [{"key": key, "value": child} for key, child in value.items()]
    elif isinstance(value, list):
        raw_items = value
    else:
        raise ValueError("changes must be an array of setting key/value pairs")
    if not raw_items:
        raise ValueError("at least one input setting change is required")
    if len(raw_items) > 12:
        raise ValueError("at most 12 input settings may change in one approval")
    result: list[dict[str, object]] = []
    seen: set[str] = set()
    for raw in raw_items:
        if not isinstance(raw, Mapping):
            raise ValueError("each input setting change must be an object")
        key = str(raw.get("key") or "").strip()
        if key not in _INPUT_SETTING_FIELDS:
            raise ValueError(f"input setting is not agent-manageable: {key or 'missing key'}")
        if key in seen:
            raise ValueError(f"duplicate input setting: {key}")
        if "value" not in raw:
            raise ValueError(f"input setting value is required: {key}")
        result.append({"key": key, "value": _normalize_input_setting_value(key, raw["value"])})
        seen.add(key)
    return sorted(result, key=lambda item: str(item["key"]))


def _normalize_input_setting_value(key: str, value: object) -> object:
    default = _SETTING_DEFAULTS[key]
    if isinstance(default, bool):
        if not isinstance(value, bool):
            raise ValueError(f"setting {key} must be a boolean")
        normalized: object = value
    elif isinstance(default, int):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"setting {key} must be an integer")
        if isinstance(value, float) and not value.is_integer():
            raise ValueError(f"setting {key} must be an integer")
        normalized = int(value)
    elif isinstance(default, str):
        if not isinstance(value, str):
            raise ValueError(f"setting {key} must be a string")
        normalized = value.strip()
    else:
        raise ValueError(f"setting {key} has an unsupported value type")
    schema_field = _SETTING_SCHEMA_FIELDS.get(key, {})
    options = schema_field.get("options")
    if isinstance(options, list) and normalized not in options:
        raise ValueError(f"setting {key} must be one of: {', '.join(str(item) for item in options)}")
    bounds = _INPUT_SETTING_FIELDS[key]
    if isinstance(normalized, int) and not isinstance(normalized, bool):
        minimum = bounds.get("min")
        maximum = bounds.get("max")
        if isinstance(minimum, int) and normalized < minimum:
            raise ValueError(f"setting {key} must be >= {minimum}")
        if isinstance(maximum, int) and normalized > maximum:
            raise ValueError(f"setting {key} must be <= {maximum}")
    return normalized


def _input_setting_label(key: str) -> str:
    return str(_INPUT_SETTING_FIELDS.get(key, {}).get("label") or key)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_json(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _room_invocation_receipt_id(
    authorization: Mapping[str, object] | None,
) -> str:
    if not isinstance(authorization, Mapping):
        return ""
    invocation = authorization.get("invocationReceipt")
    if not isinstance(invocation, Mapping):
        return ""
    return _bounded_text(invocation.get("receiptId"), maximum=240)


def _auto_approved_room_execution_receipt(
    response: Mapping[str, object],
) -> dict[str, object] | None:
    result = response.get("result")
    if not isinstance(result, Mapping) or result.get("autoApproved") is not True:
        return None
    receipt = result.get("receipt")
    if not isinstance(receipt, Mapping):
        return None
    room_receipt = receipt.get("roomExecutionReceipt")
    return dict(room_receipt) if isinstance(room_receipt, Mapping) else None


def _approval_room_invocation_receipt_id(
    approval: Mapping[str, object],
) -> str:
    preview = approval.get("preview")
    if not isinstance(preview, Mapping):
        return ""
    base_state = preview.get("baseState")
    if not isinstance(base_state, Mapping):
        return ""
    return _bounded_text(
        base_state.get("roomInvocationReceiptId"),
        maximum=240,
    )


def _approval_payload_digest(
    *,
    session_id: str,
    tool: str,
    operation: str,
    action_payload: Mapping[str, object],
    base_state: Mapping[str, object],
) -> str:
    material = {
        "schemaVersion": "rag-ime.agent-approved-operation.v1",
        "sessionId": session_id,
        "tool": tool,
        "operation": operation,
        "actionPayload": dict(action_payload),
        "baseState": dict(base_state),
    }
    encoded = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _highest_risk(values: object) -> str:
    priority = {"R0": 0, "R1": 1, "R2": 2, "R3": 3}
    normalized = [str(value) for value in values] if values is not None else ["R0"]
    return max(normalized or ["R0"], key=lambda value: priority.get(value, 3))


def _planning_status_label(value: str) -> str:
    return _PLANNING_STATUS_LABELS.get(value, value or "未知")


def _memory_run_status_label(value: str) -> str:
    return {
        "draft": "待审草案",
        "applied": "已应用",
        "partial": "部分应用",
        "rolled_back": "已回滚",
        "superseded": "已被新草案替代",
    }.get(value, value or "未知")


def _bounded_int(value: object, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value if value is not None else default)
    except (TypeError, ValueError):
        parsed = default
    return min(maximum, max(minimum, parsed))


def _safe_int(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _string_list(value: object, *, limit: int) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [_bounded_text(item, maximum=120) for item in value[:limit] if _bounded_text(item, maximum=1)]


def _review_key_list(value: object, *, limit: int) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    result: list[str] = []
    for item in value[:limit]:
        key = str(item or "").strip()[:300]
        if key and key not in result:
            result.append(key)
    return result


def _safe_mapping_payload(value: Mapping[str, object]) -> dict[str, object]:
    safe = _safe_payload(value)
    return safe if isinstance(safe, dict) else {}


def _safe_payload(value: object, *, depth: int = 0) -> object:
    if depth > 6:
        return "[truncated]"
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for raw_key, child in list(value.items())[:100]:
            key = _bounded_text(raw_key, maximum=120)
            if not key or _secret_key(key):
                continue
            result[key] = _safe_payload(child, depth=depth + 1)
        return result
    if isinstance(value, (list, tuple)):
        return [_safe_payload(item, depth=depth + 1) for item in value[:100]]
    if isinstance(value, str):
        return _bounded_text(value, maximum=2000)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _bounded_text(value, maximum=500)


def _safe_knowledge_payload(value: Mapping[str, object]) -> dict[str, object]:
    """Bound document evidence without exposing worker or filesystem details."""

    blocked_keys = {
        "absolutepath",
        "localpath",
        "sourcepath",
        "storedpath",
        "workertoken",
        "workerurl",
        "endpoint",
    }

    def visit(item: object, *, depth: int = 0) -> object:
        if depth > 6:
            return "[truncated]"
        if isinstance(item, Mapping):
            result: dict[str, object] = {}
            for raw_key, child in list(item.items())[:100]:
                key = _bounded_text(raw_key, maximum=120)
                normalized = re.sub(r"[^a-z0-9]", "", key.lower())
                if not key or normalized in blocked_keys or _secret_key(key):
                    continue
                result[key] = visit(child, depth=depth + 1)
            return result
        if isinstance(item, (list, tuple)):
            return [visit(child, depth=depth + 1) for child in item[:100]]
        if isinstance(item, str):
            return _bounded_text(item, maximum=2000)
        if item is None or isinstance(item, (bool, int, float)):
            return item
        return _bounded_text(item, maximum=500)

    safe = visit(value)
    return safe if isinstance(safe, dict) else {}


def _secret_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", key.lower())
    return any(
        token in normalized
        for token in ("apikey", "token", "secret", "password", "authorization", "cookie", "credential")
    )


def _tool_profile_allows(
    session: Mapping[str, object],
    *,
    tool: str,
    operation: str,
    spec: Mapping[str, object],
) -> bool:
    if (
        str(session.get("toolAllowlistMode") or "profile") == "explicit"
        and tool not in {str(value) for value in session.get("allowedTools") or []}
    ):
        return False
    profile = str(session.get("toolProfileVersion") or "control-center-v1")
    if profile in {"control-center-v1", "subagent-worker-v1"}:
        return True
    if profile != "subagent-readonly-v1":
        return not profile.startswith("subagent-")
    allowed: dict[str, frozenset[str]] = {
        "ime_overview": frozenset({"status", "capabilities", "recent_activity"}),
        "ime_memory": frozenset(
            {
                "catalog",
                "read",
                "recent",
                "trace",
                "maintenance_status",
                "list",
                "search",
                "get",
                "explain",
                "review",
                "remember_preview",
                "correct_preview",
                "forget_preview",
            }
        ),
        "agent_role_book": frozenset({"get", "history", "review"}),
        "ime_knowledge": frozenset({"list_bases", "search", "find", "open", "status"}),
        "ime_models": frozenset({"status", "profiles", "probe", "cache_stats"}),
        "ime_runtime": frozenset({"health", "components", "diagnose"}),
        "ime_browser": frozenset({"status", "tabs", "snapshot", "screenshot", "trace"}),
        "ime_agents": frozenset(
            {
                "catalog",
                "status",
                "artifact",
            }
        ),
        "agent_schedule": frozenset({"list", "runs"}),
        "agent_plan": frozenset({"list"}),
        "workspace_list": frozenset({"list"}),
        "workspace_read": frozenset({"read"}),
        "workspace_search": frozenset({"search"}),
        "desktop_semantic": frozenset({"status", "list", "inspect"}),
    }
    operation_risk = str(dict(spec.get("operationRisks") or {}).get(operation) or "R0")
    return operation_risk == "R0" and operation in allowed.get(tool, frozenset())


def _runtime_memory_tool_parameter_schema(
    operations: list[str],
) -> dict[str, object]:
    argument_names = (*_RUNTIME_TOOL_ARGUMENTS["ime_memory"], "scope", "policy")
    properties = {
        "op": {"type": "string", "enum": operations},
        **{
        name: dict(
            _RUNTIME_TOOL_ARGUMENT_SCHEMA_OVERRIDES.get(
                ("ime_memory", name),
                _RUNTIME_TOOL_ARGUMENT_SCHEMAS[name],
            )
        )
        for name in argument_names
        if name in _RUNTIME_TOOL_ARGUMENT_SCHEMAS
        or ("ime_memory", name) in _RUNTIME_TOOL_ARGUMENT_SCHEMA_OVERRIDES
        },
    }
    properties.update(
        {
            "query": {"type": "string", "maxLength": 240},
            "limit": {"type": "integer", "minimum": 1, "maximum": 30},
            "instruction": {"type": "string", "maxLength": 800},
            "trigger": {
                "type": "string",
                "enum": ["task_completion", "explicit_request", "idle_batch"],
            },
            "scope": {
                "type": "string",
                "enum": [
                    "incremental",
                    "global",
                    "recent",
                    "current",
                    "historical",
                    "change",
                ],
            },
            "policy": {"type": "string", "enum": ["conservative"]},
            "claim": {"type": "string", "minLength": 1, "maxLength": 800},
            "sourceId": {"type": "string", "maxLength": 240},
            "captureScope": {
                "type": "string",
                "enum": ["user", "project"],
            },
            "basis": {
                "type": "string",
                "enum": [
                    "explicit_user_request",
                    "explicit_user_statement",
                    "user_correction",
                    "repeated_user_signal",
                    "verified_outcome",
                ],
            },
            "futureUse": {
                "type": "string",
                "minLength": 1,
                "maxLength": 300,
            },
            "supersedes": {
                "type": "string",
                "maxLength": 800,
                "description": "仅 correction 可填写；写被纠正的旧说法，不写内部 ID。",
            },
        }
    )
    branches: list[dict[str, object]] = []
    for operation in operations:
        branch: dict[str, object] = {
            "required": [
                "op",
                *_RUNTIME_TOOL_REQUIRED_ARGUMENTS.get(
                    ("ime_memory", operation),
                    (),
                ),
            ],
            "properties": {"op": {"const": operation}},
        }
        alternatives = _RUNTIME_TOOL_REQUIRED_ALTERNATIVES.get(
            ("ime_memory", operation),
            (),
        )
        if alternatives:
            branch["anyOf"] = [
                {"required": list(alternative)} for alternative in alternatives
            ]
        if operation == "capture":
            branch["properties"] = {
                "op": {"const": operation},
                "kind": {
                    "type": "string",
                    "enum": [
                        "preference",
                        "fact",
                        "decision",
                        "correction",
                        "pitfall",
                    ],
                },
                "captureScope": {
                    "type": "string",
                    "enum": ["user", "project"],
                },
                "basis": {
                    "type": "string",
                    "enum": [
                        "explicit_user_request",
                        "explicit_user_statement",
                        "user_correction",
                        "repeated_user_signal",
                        "verified_outcome",
                    ],
                },
            }
        elif operation == "maintenance_status":
            branch["properties"] = {
                "op": {"const": operation},
                "scope": {
                    "type": "string",
                    "enum": ["incremental", "global"],
                },
            }
        branches.append(branch)
    # Older and weaker OpenAI-compatible models sometimes infer the obvious
    # read-only call from the compact catalog before emitting `op`. Accept only
    # this bounded compatibility shape; every mutation still requires an exact
    # operation branch and its operation-specific fields.
    branches.append(
        {
            "description": (
                "只读兼容：query 必填；scope=recent 读取近期证据，"
                "current/historical/change 转为对应检索视图。新调用应显式传 op。"
            ),
            "required": ["query"],
            "not": {"required": ["op"]},
            "properties": {
                "scope": {
                    "type": "string",
                    "enum": ["recent", "current", "historical", "change"],
                },
            },
        }
    )
    return {
        "type": "object",
        "description": "Evidence->Atom->Book/Timeline；Role Book 用 agent_role_book。",
        "additionalProperties": False,
        "properties": properties,
        "oneOf": branches,
    }


def _runtime_tool_parameter_schema(
    tool_id: str,
    operations: list[object],
) -> dict[str, object]:
    normalized_operations = [str(operation) for operation in operations]
    if tool_id == "ime_memory":
        return _runtime_memory_tool_parameter_schema(normalized_operations)
    configured = _RUNTIME_TOOL_PARAMETER_SCHEMAS.get(tool_id)
    if configured is not None:
        allowed = {str(operation) for operation in operations}
        branches = configured.get("oneOf")
        if isinstance(branches, list):
            filtered = [
                branch
                for branch in branches
                if isinstance(branch, Mapping)
                and str(
                    (
                        branch.get("properties", {}).get("op", {})
                        if isinstance(branch.get("properties"), Mapping)
                        else {}
                    ).get("const")
                    or ""
                )
                in allowed
            ]
            return {**configured, "oneOf": filtered}
        return dict(configured)
    argument_names = _RUNTIME_TOOL_ARGUMENTS.get(tool_id, ())
    properties = {
        "op": {"type": "string", "enum": normalized_operations},
        **{
            name: dict(
                _RUNTIME_TOOL_ARGUMENT_SCHEMA_OVERRIDES.get(
                    (tool_id, name),
                    _RUNTIME_TOOL_ARGUMENT_SCHEMAS[name],
                )
            )
            for name in argument_names
        },
    }
    branches: list[dict[str, object]] = []
    for operation in normalized_operations:
        required = [
            "op",
            *_RUNTIME_TOOL_REQUIRED_ARGUMENTS.get((tool_id, operation), ()),
        ]
        branch: dict[str, object] = {
            "required": required,
            "properties": {"op": {"const": operation}},
        }
        alternatives = _RUNTIME_TOOL_REQUIRED_ALTERNATIVES.get((tool_id, operation), ())
        if alternatives:
            branch["anyOf"] = [
                {"required": list(alternative)} for alternative in alternatives
            ]
        branches.append(branch)
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["op"],
        "properties": properties,
        "oneOf": branches,
    }


def _read_voice_agent_status() -> dict[str, object]:
    app_support = Path(
        os.environ.get("RAG_IME_APP_SUPPORT_DIR")
        or Path.home() / "Library" / "Application Support" / "RagIme"
    ).expanduser()
    path = app_support / "voice-agent-status.json"
    if not path.is_file() or path.is_symlink():
        return {
            "available": False,
            "running": False,
            "state": "unavailable",
            "statusText": "语音代理没有可用状态",
        }
    try:
        if path.stat().st_size > 256 * 1024:
            raise ValueError("voice status is too large")
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return {
            "available": False,
            "running": False,
            "state": "invalid",
            "statusText": "语音代理状态不可解析",
        }
    if not isinstance(raw, Mapping):
        return {"available": False, "running": False, "state": "invalid"}
    allowed = (
        "schemaVersion",
        "running",
        "accessibilityTrusted",
        "microphoneAuthorization",
        "credentialsConfigured",
        "hotkeyMode",
        "hotwordsEnabled",
        "hotwordCount",
        "hotkeyInstalled",
        "state",
        "statusText",
        "updatedAtMs",
    )
    result = {key: raw.get(key) for key in allowed if key in raw}
    telemetry = raw.get("telemetry")
    if isinstance(telemetry, Mapping):
        result["telemetry"] = {
            key: telemetry.get(key)
            for key in (
                "networkState",
                "sessionActive",
                "sessionStartedAtMs",
                "firstPartialLatencyMs",
                "finalLatencyMs",
                "pcmFrameCount",
                "droppedPCMFrameCount",
                "partialRevisionCount",
                "finalReceived",
            )
            if key in telemetry
        }
    result["available"] = True
    return result


def _mapping_value(value: Mapping[str, object], parent: str, child: str) -> object:
    nested = value.get(parent)
    return nested.get(child) if isinstance(nested, Mapping) else None


def _memory_evidence(value: object) -> dict[str, object]:
    if isinstance(value, Mapping):
        getter = value.get
    else:
        getter = lambda key, default=None: getattr(value, key, default)
    source_event_id = getter("source_event_id", "")
    return {
        "kind": "source",
        "sourceId": f"event:{source_event_id}" if source_event_id else "",
        "text": _bounded_text(getter("text", ""), maximum=1600),
        "evidence": _bounded_text(getter("evidence_preview", ""), maximum=1200),
        "score": max(0.0, float(getter("score", 0.0) or 0.0)),
        "reason": _bounded_text(getter("reason", ""), maximum=300),
        "project": _bounded_text(getter("project", ""), maximum=160),
        "tags": _string_list(getter("tags", ()), limit=20),
        "createdAtMs": _safe_int(getter("created_at_ms", 0)),
    }


def _model_status_summary(payload: Mapping[str, object]) -> str:
    predictor = payload.get("predictor") if isinstance(payload.get("predictor"), Mapping) else {}
    active = payload.get("activeRagRoute") if isinstance(payload.get("activeRagRoute"), Mapping) else {}
    predictor_ready = predictor.get("ok") is True or predictor.get("available") is True
    remote_ready = active.get("remoteReady") is True
    if predictor_ready and remote_ready:
        return "本地预测与深度知识模型均已就绪"
    if predictor_ready:
        return "本地预测已就绪，深度知识模型当前不可用"
    return "模型运行链路当前未就绪"
