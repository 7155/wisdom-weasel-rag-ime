#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag_ime.input_quality import assess_input_text
from rag_ime.memory_ingest import normalize_text
from rag_ime.memory_rebuild import audit_memory_database
from rag_ime.memory_tag_graph import recompute_tag_graph
from rag_ime.retrieval_docs import rebuild_retrieval_docs
from rag_ime.text_utils import compact_whitespace, now_ms


PROJECT = "wisdom-weasel-rag-ime"

# Only semantic equivalents or a narrower stale wording are merged. A target is
# never also a source, which prevents the merge chains produced by model-only
# catalog audits.
ATOM_MERGES = {
    "atom:sha256:f578d25c0": "atom:continuous-prediction-needed",
    "atom:sha256:20e4edd52": "atom:continuous-prediction-needed",
    "atom:llm-immediate-popup": "atom:continuous-prediction-needed",
    "atom:sha256:39e04f338": "atom:sha256:0788a525a",
    "atom:sha256:2c5b00561": "atom:sha256:be16ab4ad",
    "atom:sha256:07d2b8902": "atom:sha256:6bd20303a",
    "atom:sha256:7f2048cf0": "atom:sha256:8828a17be",
    "atom:sha256:7bbcb3be3": "atom:sha256:d3eab1773",
    "atom:sha256:feca769cd": "atom:sha256:5798a237a",
    "atom:sha256:d2f192395": "atom:sha256:2dec6b2ef",
    "atom:sha256:efcce494c": "atom:sha256:79ebf54e6",
    "atom:deepseek-for-memory": "atom:deepseek-history-rag-cleanup",
    "atom:deepseek-rag-001": "atom:deepseek-history-rag-cleanup",
    "atom:sha256:ce03ea347": "atom:deepseek-history-rag-cleanup",
    "atom-browser-plugin": "atom:pi-agent-plugin-browser-extension",
    "atom:rag-ime-candidate-display-001": "atom-local-memory",
    "atom:llm-prediction-slow": "atom-inference-speed",
    "atom:product-ui-optimization": "atom:sha256:69e482edf",
    "atom:voice-input-doubao-streaming": "atom:doubao-api-stream",
    "atom:context-switch-issue": "atom:model-context-issue",
    "atom:front-context-not-obtained": "atom:model-context-issue",
    "atom:sha256:c4a51864a": "atom:sha256:66f5b705c",
    "atom:agent-interview-geo-data": "atom:interview-architecture-expansion",
}

ATOM_ARCHIVES = {
    "atom-project-packing",
    "atom:model-replace-gpt4o-mini",
    "atom:permission-multiple-apps",
    "atom:memory-4g",
    "atom:ui-overlap",
    "atom:11793-11803",
    "atom:11829-11833",
    "atom:11815-11822",
    "atom:rag-shows-7-items",
    "atom:context-cancelled-no-double",
    "atom:10526",
    "atom:sha256:5b7519e3b",
    "atom:sha256:2bbd155bf",
    "atom:sha256:a516ba87d",
    "atom:sha256:ff93e5ea8",
    "atom:sha256:2962e7160",
    "atom:sha256:077d487fe",
    "atom:sha256:d5bd46660",
    "atom:sha256:19c920991",
    "atom:sha256:d722e0f53",
    "atom:sha256:923a5c43a",
    "atom:sha256:266efda00",
    "atom:sha256:2638611a8",
    "atom:sha256:60fba168b",
    "atom:sha256:7bcf45f1f",
    "atom:sha256:5e40fcadb",
    "atom:sha256:b6a3a2c5f",
    "atom:sha256:d5ff4d2f1",
    "atom:sha256:f9027014f",
    "atom:sha256:0ed077a57",
    # These rows were inferred from isolated Rime commits or describe a
    # completed one-off task. Preserve them as history, but never inject them.
    "atom:incremental-training",
    "atom:sha256:104b6a395",
    "atom:sha256:5ccdc3b21",
    "atom:sha256:635dd622d",
    "atom:sha256:7b1a7322f",
    "atom:sha256:8097f29fb",
    "atom:sha256:888cd9295",
    "atom:sha256:ab7181246",
    "atom:sha256:b75b49c46",
    "atom:sha256:ec344c9d0",
    "atom:voice-input-rag-001",
}

ATOM_REWRITES: dict[str, dict[str, object]] = {
    "atom:continuous-prediction-needed": {
        "text": "LLM 候选需稳定且及时出现；选择后立即生成下一批，不限制为四字词。",
        "kind": "project_requirement",
        "tags": ["预测稳定性", "连续补全"],
        "events": [],
    },
    "atom-local-memory": {
        "text": "LLM、RAG 和记忆三类候选需同时可见、标明来源，并可用数字键提交。",
        "kind": "project_requirement",
        "tags": ["候选展示", "个人知识库"],
        "events": [5145],
    },
    "atom:ime-model-training-001": {
        "text": "本地模型只做下一段补全，不回答问题、不复读已输入内容；拼音锚定首词，后文预测优先。",
        "kind": "project_requirement",
        "tags": ["补全", "模型训练"],
        "events": [5135, 5138, 5144, 5177],
    },
    "atom:deepseek-history-rag-cleanup": {
        "text": "DeepSeek 只在离线知识工作台中整理历史、记忆、标签和词库草案，不进入输入法热路径；结果审核后入库。",
        "kind": "project_decision",
        "tags": ["DeepSeek", "记忆整理流程"],
        "events": [],
    },
    "atom:model-context-issue": {
        "text": "候选上下文必须随前台 App 和当前输入实时刷新，不得沿用上一应用或上一轮输入。",
        "kind": "project_requirement",
        "tags": ["上下文构建", "前台上下文"],
        "events": [592, 593, 5133, 5136],
    },
    "atom:sha256:0788a525a": {
        "text": "主题书不限制理论总数，但仅在必要时新建；长期不更新的主题应归档并降低检索权重。",
        "kind": "project_requirement",
        "tags": ["主题书管理"],
        "events": [],
    },
    "atom:sha256:be16ab4ad": {
        "text": "提供一键导出设置与数据库的迁移包；API 密钥只走安全凭据通道，不写入普通导出正文。",
        "kind": "project_requirement",
        "tags": ["一键导出设置", "隐私边界"],
        "events": [],
    },
    "atom:sha256:6bd20303a": {
        "text": "普通上下文按预算动态截取最近 10-20 条完整输入，可超过 2K，但不得注入单词碎片。",
        "kind": "project_requirement",
        "tags": ["上下文构建", "句子边界"],
        "events": [],
    },
    "atom:sha256:8828a17be": {
        "text": "记忆需增量更新并保留前后版本关系；旧信息按时间衰减，明确的新决定优先。",
        "kind": "project_requirement",
        "tags": ["增量更新与时间衰减"],
        "events": [],
    },
    "atom:sha256:d3eab1773": {
        "text": "等待检索或生成时，候选框显示“正在翻书”“正在思考”等动态状态，但不得阻塞输入。",
        "kind": "project_requirement",
        "tags": ["UI灵动性"],
        "events": [],
    },
    "atom:sha256:5798a237a": {
        "text": "输入法采用统一、可爱的二次元视觉，可参考阿库娅形象与表情反馈，但不照搬其他产品。",
        "kind": "durable_preference",
        "tags": ["二次元角色", "UI优化"],
        "events": [],
    },
    "atom:sha256:2dec6b2ef": {
        "text": "训练数据先确定格式与质量标准，再逐句生成和复核；语言需日常、自然、无明显 GPT 味。",
        "kind": "project_requirement",
        "tags": ["训练数据生成", "自然语言风格"],
        "events": [],
    },
    "atom:sha256:79ebf54e6": {
        "text": "控制面板的可写能力通过权限受控工具暴露给 Pi；工具调用需预览、审批、回执和回滚。",
        "kind": "project_decision",
        "tags": ["工具暴露", "Pi集成"],
        "events": [],
    },
    "atom:sha256:66f5b705c": {
        "text": "记忆维护采用 Atom-first：周期性清洗完整输入、复用或合并原子，再派生粗粒度分组、受控标签、主题书与关系图；只生成待审草案。",
        "kind": "project_decision",
        "tags": ["记忆整理流程", "Group设计", "自动标签污染"],
        "events": [],
    },
    "atom-inference-speed": {
        "text": "输入法热路径优先降低首候选延迟和内存占用，模型常驻、KV cache 与推理后端优化均需以真实前台测试验收。",
        "kind": "project_requirement",
        "tags": ["性能", "KV cache"],
        "events": [],
    },
    "atom:sha256:69e482edf": {
        "text": "输入法候选框、系统动画和控制面板采用统一视觉语言，保证流畅、清晰且无文字重叠。",
        "kind": "project_requirement",
        "tags": ["UI优化", "控制面板"],
        "events": [],
    },
    "atom:doubao-api-stream": {
        "text": "豆包等语音 API 的流式转写需做增量去重和终稿修正，并允许在设置中切换供应商。",
        "kind": "project_requirement",
        "tags": ["豆包API", "语音输入", "流式输出"],
        "events": [],
    },
    "atom:interview-architecture-expansion": {
        "text": "Agent 面试项目以真实 RAG、记忆、浏览器控制和可选地理数据工具展示完整工程链路，而不是堆功能名。",
        "kind": "project_plan",
        "tags": ["Agent", "面试架构", "地理数据"],
        "events": [],
    },
    "atom:ds-output-issue": {
        "text": "DeepSeek 面向用户的结果只保留最终整理内容，不泄露思考过程、不复述原句或输出提示词痕迹。",
        "kind": "project_requirement",
        "tags": ["DeepSeek", "模型校验"],
        "events": [],
    },
    "atom:10555": {
        "text": "候选框需统一承载普通拼音、LLM、RAG 和记忆候选，布局灵动流畅且不遮挡、不跳动。",
        "kind": "project_requirement",
        "tags": ["候选框", "UI灵动性"],
        "events": [],
    },
    "atom:sha256:822eb8ca7": {
        "text": "Agent 与 Session 权威状态和输入法输入路径平行；Sidecar 不得成为输入法热路径的权威会话中间层。",
        "kind": "project_decision",
        "tags": ["Sidecar架构", "网关型Agent"],
        "events": [],
    },
    "atom:sha256:cd876c52e": {
        "text": "多端对话通过 Agent Gateway 的全局序号、SSE 重放和 snapshot_required 实时同步，不把 Telegram 作为默认入口。",
        "kind": "project_decision",
        "tags": ["多端同步", "网关型Agent"],
        "events": [],
    },
    "atom:rag-output-llm-streaming": {
        "text": "显式生成与检索结果采用平滑流式刷新；输入法热路径只消费最新可用候选，不等待完整长回答。",
        "kind": "project_requirement",
        "tags": ["流式输出", "性能"],
        "events": [],
    },
    "atom:sha256:46278610e": {
        "text": "只有经 Backspace 修正并由 Enter、提交或 App 切换封口的完整输入可进入普通 Agent 上下文；单词和碎片必须隔离。",
        "kind": "project_requirement",
        "tags": ["句子边界", "上下文构建"],
        "events": [],
    },
    "atom:todo-iteration": {
        "text": "每轮工程迭代维护明确 TODO，并在实现和验证完成后同步更新。",
        "kind": "durable_preference",
        "tags": ["工程工作流"],
        "events": [],
    },
    "atom:logic-conclusion-first": {
        "text": "解释和记忆正文先给结论，再补充必要原因与证据。",
        "kind": "durable_preference",
        "tags": ["工程工作流"],
        "events": [],
    },
}

NEW_ATOMS = {
    "atom:learning:record-all-questions": {
        "text": "学习过程中提出的概念、代码、命令和排错问题都要简洁留痕，作为后续复习轨迹。",
        "kind": "durable_preference",
        "events": [7605, 8605],
        "tags": ["学习偏好", "学习记录"],
        "groups": ["group:learning-system"],
    },
    "atom:learning:code-with-notes": {
        "text": "工程实现应同时沉淀面向学习的笔记，说明机制、数据流和验证方法。",
        "kind": "durable_preference",
        "events": [7613],
        "tags": ["学习偏好", "工程工作流"],
        "groups": ["group:learning-system"],
    },
    "atom:learning:morning-review": {
        "text": "每日学习计划先回看上一日问题与进度，安排复习，再给出当天任务。",
        "kind": "durable_preference",
        "events": [7603, 7604],
        "tags": ["学习偏好", "每日规划"],
        "groups": ["group:learning-system"],
    },
    "atom:engineering:reuse-reference-projects": {
        "text": "实现重要功能前应对比多个成熟项目并选择最合适的方案，避免重复踩已知工程坑。",
        "kind": "durable_preference",
        "events": [2127, 5192],
        "tags": ["工程工作流", "源码调研"],
        "groups": ["group:agent-interview"],
    },
    "atom:engineering:quality-over-speed": {
        "text": "长期项目以真实可用和充分打磨优先，不以赶时间替代验收质量。",
        "kind": "durable_preference",
        "events": [5187, 5189],
        "tags": ["工程工作流", "项目目标"],
        "groups": ["group:agent-interview"],
    },
    "atom:engineering:avoid-duplicate-work": {
        "text": "同一项目的并行任务先核对已有进度和产物，尽量避免重复实现。",
        "kind": "durable_preference",
        "events": [189],
        "tags": ["工程工作流"],
        "groups": ["group:agent-interview"],
    },
    "atom:network:avoid-proxy-large-downloads": {
        "text": "下载模型或大型数据集时优先直连，避免无意占用代理流量。",
        "kind": "durable_preference",
        "events": [2047],
        "tags": ["工程工作流", "模型训练"],
        "groups": ["group:model-and-data"],
    },
}

GROUPS = {
    "group:input-method": (
        "输入法",
        "输入法热路径、候选生成、上下文、RAG、记忆和交互要求。",
    ),
    "group:agent-interview": (
        "Agent 与工程展示",
        "Pi/Agent Runtime、工具边界、浏览器控制、工程方法与面试展示。",
    ),
    "group:ui-design": (
        "UI 设计",
        "候选框、控制面板、动画、角色视觉和交互反馈。",
    ),
    "group:memory-rag": (
        "记忆与 RAG",
        "完整输入、长期记忆、检索、主题书、标签图和上下文注入。",
    ),
    "group:model-and-data": (
        "模型与数据",
        "补全模型、推理性能、训练数据、词库和反馈学习。",
    ),
    "group:voice-input": (
        "语音输入",
        "流式语音识别、终稿修正、供应商切换和语音交互。",
    ),
    "group:learning-system": (
        "学习系统",
        "问题留痕、复习计划、源码学习和工程笔记偏好。",
    ),
}

MODEL_ATOMS = {
    "atom:ime-model-training-001",
    "atom-training",
    "atom:model-training-data-quality",
    "atom:local-model-prediction",
    "atom-inference-speed",
    "atom:incremental-training",
    "atom:dataset-classification",
    "atom:sha256:5ccdc3b21",
    "atom:sha256:8cc30753d",
    "atom:sha256:89d217417",
    "atom:sha256:2dec6b2ef",
    "atom:sha256:399c82136",
    "atom:sha256:60e12f1c6",
    "atom:network:avoid-proxy-large-downloads",
}

MEMORY_ATOMS = {
    "atom-local-memory",
    "atom:deepseek-history-rag-cleanup",
    "atom:rag-dedup-needed",
    "atom:rag-deepseek-context-verify",
    "atom:rag-filter-better-than-training",
    "atom:sha256:9635720d0",
    "atom:sha256:8ccfe6026",
    "atom:sha256:66f5b705c",
    "atom:sha256:8d111db4a",
    "atom:sha256:e43deebf3",
    "atom:sha256:f47d38a37",
    "atom:sha256:82a808ee1",
    "atom:sha256:91eb5857b",
    "atom:sha256:8828a17be",
    "atom:sha256:0788a525a",
    "atom:sha256:be16ab4ad",
    "atom:sha256:6bd20303a",
    "atom:sha256:224d7f8b9",
    "atom:sha256:b88f4e637",
    "atom:sha256:aaed4fbec",
    "atom:sha256:bc26cb831",
    "atom:sha256:46278610e",
}

VOICE_ATOMS = {
    "atom:voice-input-rag-001",
    "atom:doubao-api-stream",
    "atom:sha256:3c4da9940",
    "atom:sha256:97e5c007a",
    "atom:sha256:53706e186",
    "atom:sha256:ab7181246",
}

UI_ATOMS = {
    "atom:10555",
    "atom:control-panel-unified",
    "atom:11714-11792",
    "atom:sha256:41cbe95b3",
    "atom:sha256:5798a237a",
    "atom:sha256:69e482edf",
    "atom:sha256:35dce1ce3",
    "atom:sha256:4764a8b66",
    "atom:sha256:d3eab1773",
    "atom:sha256:7a3f02f91",
}

AGENT_ATOMS = {
    "atom:pi-agent-001",
    "atom:pi-agent-plugin-browser-extension",
    "atom:interview-architecture-expansion",
    "atom:project-iteration-mature-engineering",
    "atom:sha256:c9a2a0078",
    "atom:sha256:7a0c3423f",
    "atom:sha256:51ea31059",
    "atom:sha256:405db84a6",
    "atom:sha256:1b39b6272",
    "atom:sha256:79ebf54e6",
    "atom:sha256:22637db23",
    "atom:sha256:822eb8ca7",
    "atom:sha256:cd876c52e",
    "atom:engineering:reuse-reference-projects",
    "atom:engineering:quality-over-speed",
    "atom:engineering:avoid-duplicate-work",
}

CANDIDATE_ATOMS = {
    "atom-local-memory",
    "atom:continuous-prediction-needed",
    "atom:rime-latency-001",
    "atom:candidate-deduplication",
    "atom:model-context-issue",
    "atom:rag-deepseek-context-verify",
    "atom:rag-output-llm-streaming",
    "atom:sha256:168b992b3",
    "atom:sha256:6bd20303a",
    "atom:sha256:46278610e",
    "atom:sha256:a5c5eedb1",
    "atom:sha256:11a405f65",
    "atom:real-squirrel-rime-chain",
    "atom:sha256:36430a39e",
    "atom:sha256:b75b49c46",
    "atom:sha256:a3f8ce1b6",
    "atom:sha256:ec344c9d0",
    "atom:sha256:409da7912",
}

LEARNING_ATOMS = set(NEW_ATOMS)

LEARNING_ATOMS |= {
    "atom:logic-conclusion-first",
    "atom:todo-iteration",
}

AGENT_ATOMS |= {
    "atom:interview-demo-quality-priority",
    "atom:project-public-readme",
    "atom:sha256:53fc2e9f2",
    "atom:sha256:81b18909e",
}

MODEL_ATOMS |= {
    "atom-training",
    "atom:ml-completion-example",
}

MEMORY_ATOMS |= {
    "atom:ds-output-issue",
    "atom:sha256:104b6a395",
    "atom:sha256:3aa6dc67b",
    "atom:sha256:6e80ee9eb",
    "atom:sha256:7b1a7322f",
    "atom:sha256:888cd9295",
    "atom:sha256:9e29523a3",
    "atom:sha256:b726297a8",
}

CANDIDATE_ATOMS |= {
    "atom:10612",
    "atom:demo:ime-flow",
    "atom:demo:knowledge-workbench",
}

ACTIVE_BOOKS = {
    "book:topic:input-method-features": {
        "title": "输入法产品与上下文边界",
        "summary": "输入法作为跨 App 输入入口，普通上下文只接收封口后的完整输入；候选、生成、记忆和设置能力保持清晰边界。",
        "tags": ["输入法", "上下文构建", "工程化"],
        "atoms": CANDIDATE_ATOMS | {
            "atom:10612",
            "atom:project-iteration-mature-engineering",
            "atom:sha256:2c5b00561",
        },
        "groups": ["group:input-method"],
    },
    "book:topic:rag-ime-candidate-display": {
        "title": "候选生成与交互",
        "summary": "统一呈现普通拼音、LLM、RAG 和记忆候选，保证来源可见、数字键可提交、连续预测稳定且不遮挡输入。",
        "tags": ["候选展示", "连续补全", "UI灵动性"],
        "atoms": CANDIDATE_ATOMS | UI_ATOMS,
        "groups": ["group:input-method", "group:ui-design"],
    },
    "book:topic:rime-squirrel-real-link": {
        "title": "Squirrel/Rime 真实链路",
        "summary": "所有性能与候选能力以真实前台输入法链路验收，覆盖首候选延迟、上下文刷新、流式更新和可追踪日志。",
        "tags": ["Rime", "鼠须管", "真实链路", "性能"],
        "atoms": CANDIDATE_ATOMS | {"atom-inference-speed"},
        "groups": ["group:input-method"],
    },
    "book:topic:deepseek-rag-integration": {
        "title": "记忆与 RAG 治理",
        "summary": "完整输入先通过质量门禁，再由 Atom-first 流程形成待审草案；主题书、标签图和词库是派生视图，不允许碎片直接进入 Agent 上下文。",
        "tags": ["记忆", "RAG", "DeepSeek", "Atom-first"],
        "atoms": MEMORY_ATOMS,
        "groups": ["group:memory-rag", "group:input-method"],
    },
    "book:topic:ime-model-training": {
        "title": "补全模型与训练数据",
        "summary": "模型仅做自然、低延迟、无复读的下一段补全；训练与评测以高质量真实句子、反馈学习和前台效果为准。",
        "tags": ["模型训练", "补全", "训练数据", "性能"],
        "atoms": MODEL_ATOMS,
        "groups": ["group:model-and-data", "group:input-method"],
    },
    "book:topic:voice-input-rag": {
        "title": "语音输入与流式修正",
        "summary": "语音输入支持可切换供应商、增量去重、终稿修正、状态反馈和记忆联动，并与整体 UI 保持一致。",
        "tags": ["语音输入", "流式输出", "豆包API"],
        "atoms": VOICE_ATOMS,
        "groups": ["group:voice-input", "group:input-method"],
    },
    "book:topic:pi-integration-and-control-panel": {
        "title": "Pi Agent Gateway 与控制面板",
        "summary": "Pi 作为网关型 Agent，通过受控工具操作输入法和知识功能；会话权威、观察面和多端同步均与输入热路径平行。",
        "tags": ["PI", "网关型Agent", "控制面板", "工具暴露"],
        "atoms": AGENT_ATOMS,
        "groups": ["group:agent-interview", "group:input-method"],
    },
    "book:topic:agent-interview-architecture": {
        "title": "Agent 工程与面试展示",
        "summary": "以真实工具、RAG、记忆、浏览器控制、可观察性和端到端验证展示 Agent Runtime 工程能力。",
        "tags": ["Agent", "面试架构", "工程化"],
        "atoms": AGENT_ATOMS,
        "groups": ["group:agent-interview"],
    },
    "book:topic:learning-workflow": {
        "title": "学习与工程协作偏好",
        "summary": "学习问题持续留痕，代码同步沉淀笔记；每天先复习再规划，重要实现优先参考成熟源码并以质量验收。",
        "tags": ["学习偏好", "工程工作流", "学习记录"],
        "atoms": LEARNING_ATOMS,
        "groups": ["group:learning-system"],
    },
    "book:demo:ime-first": {
        "title": "输入法优先演示路线",
        "summary": "演示普通拼音、连续短补全、可追踪 RAG 和显式知识工作台，所有结果来自真实链路。",
        "tags": ["输入法", "演示", "RAG"],
        "atoms": {"atom:demo:ime-flow", "atom:demo:knowledge-workbench"},
        "groups": ["group:input-method"],
    },
}

ARCHIVE_BOOK_IDS = {
    "book:daily:2026-07-07",
    "book:daily:2026-07-08",
    "book:daily:2026-07-10",
    "book:daily:2026-07-12",
    "book:daily:2026-07-13",
    "book:topic:pi-agent-integration",
}

HIDDEN_TAGS = {
    "账号",
    "中转站API",
    "生成失败",
    "流式输出卡顿",
    "Git历史公开",
    "安全限制调整",
}

APP_TITLES = {
    "com.openai.codex": "Codex",
    "com.mitchellh.ghostty": "Ghostty",
    "com.microsoft.VSCode": "Visual Studio Code",
    "com.microsoft.edgemac": "Microsoft Edge",
}

ELIGIBLE_SOURCES = {
    "codex_history",
    "voice_streaming_asr",
    "pi_agent_user",
    "curated_user_feedback",
    "manual_commit",
    "rag-ime-mac-native",
    "squirrel_input_segment",
}

INTERNAL_APPS = {
    "cli",
    "manual",
    "ragimecontrol",
    "ragimemac",
    "squirrel",
    "unknown-app",
    "com.rag-ime.control",
    "com.rag-ime.control.agent",
    "com.rag-ime.control.demo",
    "demo.textedit",
}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Apply the reviewed 2026-07-16 memory baseline to a SQLite copy."
    )
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    source = args.source.expanduser().resolve()
    output = args.output.expanduser().resolve()
    if not source.is_file():
        parser.error(f"source database does not exist: {source}")
    if output.exists():
        parser.error(f"output already exists: {output}")
    if output == source:
        parser.error("output must differ from source")

    _validate_constants()
    output.parent.mkdir(parents=True, exist_ok=True)
    _online_backup(source, output)
    report: dict[str, object] = {
        "schemaVersion": "rag-ime.curated-memory-baseline.v1",
        "sourcePath": str(source),
        "outputPath": str(output),
        "startedAtMs": now_ms(),
    }
    try:
        with sqlite3.connect(output) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            report["before"] = audit_memory_database(conn)
            timestamp = now_ms()
            with conn:
                _upsert_groups(conn, timestamp=timestamp)
                merged = [
                    _merge_atom(conn, old_id=old_id, keeper_id=keeper_id, timestamp=timestamp)
                    for old_id, keeper_id in ATOM_MERGES.items()
                ]
                archived = _archive_atoms(conn, timestamp=timestamp)
                rewritten = _rewrite_atoms(conn, timestamp=timestamp)
                created = _create_atoms(conn, timestamp=timestamp)
                _assign_group_memberships(conn, timestamp=timestamp)
                archived_books = _archive_legacy_books(conn, timestamp=timestamp)
                active_books = _upsert_active_books(conn, timestamp=timestamp)
                app_archives = _upsert_app_archive_books(conn, timestamp=timestamp)
                phrase_cleanup = _clean_phrase_items(conn, timestamp=timestamp)
                tag_cleanup = _clean_tags(conn, timestamp=timestamp)
                _supersede_pending_drafts(conn)
                graph_report = recompute_tag_graph(conn)
                retrieval_report = rebuild_retrieval_docs(conn, project=PROJECT)
                changes = {
                    "mergedAtoms": sum(1 for item in merged if item),
                    "archivedAtoms": archived,
                    "rewrittenAtoms": rewritten,
                    "createdAtoms": created,
                    "archivedBooks": archived_books,
                    "activeBooks": active_books,
                    "appArchiveBooks": app_archives,
                    "phrases": phrase_cleanup,
                    "tags": tag_cleanup,
                    "tagGraph": graph_report,
                    "retrievalDocuments": retrieval_report,
                }
                conn.execute(
                    """
                    INSERT INTO management_audit_log(
                        created_at_ms, action, target_type, target_id,
                        payload_json, result_json
                    ) VALUES (?, ?, 'memory_database', ?, ?, ?)
                    """,
                    (
                        timestamp,
                        "apply_curated_memory_baseline",
                        PROJECT,
                        json.dumps(
                            {
                                "schemaVersion": report["schemaVersion"],
                                "sourcePath": str(source),
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        json.dumps(changes, ensure_ascii=False, sort_keys=True),
                    ),
                )
            report["changes"] = changes
            report["after"] = audit_memory_database(conn)
            report["integrityCheck"] = str(
                conn.execute("PRAGMA integrity_check").fetchone()[0]
            )
            report["foreignKeyViolations"] = [
                list(row) for row in conn.execute("PRAGMA foreign_key_check").fetchall()
            ]
            report["finishedAtMs"] = now_ms()

        if report["integrityCheck"] != "ok" or report["foreignKeyViolations"]:
            raise RuntimeError("curated database failed SQLite validation")
        report_path = output.with_suffix(output.suffix + ".baseline-report.json")
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(json.dumps({**report, "reportPath": str(report_path)}, ensure_ascii=False, indent=2))
        return 0
    except Exception:
        _remove_sqlite_files(output)
        raise


def _validate_constants() -> None:
    overlap = set(ATOM_MERGES) & set(ATOM_MERGES.values())
    if overlap:
        raise ValueError(f"merge chains are forbidden: {sorted(overlap)}")
    if ATOM_ARCHIVES & set(ATOM_MERGES.values()):
        raise ValueError("a merge keeper cannot also be archived")


def _upsert_groups(conn: sqlite3.Connection, *, timestamp: int) -> None:
    for group_id, (title, description) in GROUPS.items():
        conn.execute(
            """
            INSERT INTO memory_semantic_groups(
                group_id, title, description, project, aliases_json, tags_json,
                source_event_ids_json, status, confidence, quality_score,
                created_at_ms, updated_at_ms, metadata_json
            ) VALUES (?, ?, ?, ?, '[]', '[]', '[]', 'active', 0.95, 0.95, ?, ?, ?)
            ON CONFLICT(group_id) DO UPDATE SET
                title = excluded.title,
                description = excluded.description,
                project = excluded.project,
                status = 'active',
                confidence = MAX(memory_semantic_groups.confidence, excluded.confidence),
                quality_score = MAX(memory_semantic_groups.quality_score, excluded.quality_score),
                updated_at_ms = excluded.updated_at_ms,
                metadata_json = excluded.metadata_json
            """,
            (
                group_id,
                title,
                description,
                PROJECT,
                timestamp,
                timestamp,
                json.dumps({"source": "curated_baseline"}, ensure_ascii=False),
            ),
        )


def _merge_atom(
    conn: sqlite3.Connection,
    *,
    old_id: str,
    keeper_id: str,
    timestamp: int,
) -> bool:
    old = conn.execute("SELECT * FROM memory_atoms WHERE id = ?", (old_id,)).fetchone()
    keeper = conn.execute("SELECT * FROM memory_atoms WHERE id = ?", (keeper_id,)).fetchone()
    if old is None or keeper is None:
        return False
    source_event_ids = _unique_ints(
        _json_list(keeper["source_event_ids_json"])
        + _json_list(old["source_event_ids_json"])
    )
    source_memory_ids = _unique_strings(
        _json_list(keeper["source_memory_ids_json"])
        + _json_list(old["source_memory_ids_json"])
    )
    conn.execute(
        """
        UPDATE memory_atoms
        SET source_event_ids_json = ?, source_memory_ids_json = ?,
            confidence = MAX(confidence, ?), quality_score = MAX(quality_score, ?),
            status = 'active', updated_at_ms = ?
        WHERE id = ?
        """,
        (
            json.dumps(source_event_ids, ensure_ascii=False),
            json.dumps(source_memory_ids, ensure_ascii=False),
            float(old["confidence"] or 0),
            float(old["quality_score"] or 0),
            timestamp,
            keeper_id,
        ),
    )
    conn.execute(
        """
        INSERT INTO memory_atom_tags(memory_atom_id, tag_id, weight, source)
        SELECT ?, tag_id, weight, 'curated_baseline'
        FROM memory_atom_tags WHERE memory_atom_id = ?
        ON CONFLICT(memory_atom_id, tag_id) DO UPDATE SET
            weight = MAX(memory_atom_tags.weight, excluded.weight)
        """,
        (keeper_id, old_id),
    )
    conn.execute(
        """
        INSERT INTO memory_semantic_group_members(
            group_id, member_type, member_id, weight, source, updated_at_ms
        )
        SELECT group_id, member_type, ?, weight, 'curated_baseline', ?
        FROM memory_semantic_group_members
        WHERE member_type = 'atom' AND member_id = ?
        ON CONFLICT(group_id, member_type, member_id) DO UPDATE SET
            weight = MAX(memory_semantic_group_members.weight, excluded.weight),
            updated_at_ms = excluded.updated_at_ms
        """,
        (keeper_id, timestamp, old_id),
    )
    conn.execute(
        "UPDATE memory_aliases SET memory_atom_id = ? WHERE memory_atom_id = ?",
        (keeper_id, old_id),
    )
    for row in conn.execute(
        "SELECT book_id, memory_atom_ids_json FROM memory_books"
    ).fetchall():
        atom_ids = _unique_strings(_json_list(row["memory_atom_ids_json"]))
        if old_id not in atom_ids:
            continue
        replaced = _unique_strings(
            keeper_id if atom_id == old_id else atom_id for atom_id in atom_ids
        )
        conn.execute(
            "UPDATE memory_books SET memory_atom_ids_json = ?, updated_at_ms = ? WHERE book_id = ?",
            (json.dumps(replaced, ensure_ascii=False), timestamp, str(row["book_id"])),
        )
    conn.execute(
        "UPDATE memory_atoms SET status = 'superseded', updated_at_ms = ? WHERE id = ?",
        (timestamp, old_id),
    )
    digest = hashlib.sha256(f"{old_id}->{keeper_id}".encode()).hexdigest()[:24]
    conn.execute(
        """
        INSERT OR REPLACE INTO memory_supersessions(
            supersession_id, old_memory_id, new_memory_id, reason,
            source_event_ids_json, status, created_at_ms, rolled_back_at_ms,
            metadata_json
        ) VALUES (?, ?, ?, 'curated semantic equivalent', ?, 'active', ?, NULL, ?)
        """,
        (
            f"supersession:{digest}",
            old_id,
            keeper_id,
            json.dumps(source_event_ids, ensure_ascii=False),
            timestamp,
            json.dumps({"source": "curated_baseline"}, ensure_ascii=False),
        ),
    )
    return True


def _archive_atoms(conn: sqlite3.Connection, *, timestamp: int) -> int:
    count = 0
    for atom_id in sorted(ATOM_ARCHIVES):
        cursor = conn.execute(
            """
            UPDATE memory_atoms
            SET status = 'hidden', updated_at_ms = ?
            WHERE id = ? AND status IN ('active', 'approved')
            """,
            (timestamp, atom_id),
        )
        count += int(cursor.rowcount or 0)
    return count


def _rewrite_atoms(conn: sqlite3.Connection, *, timestamp: int) -> int:
    count = 0
    for atom_id, spec in ATOM_REWRITES.items():
        row = conn.execute(
            "SELECT source_event_ids_json FROM memory_atoms WHERE id = ?",
            (atom_id,),
        ).fetchone()
        if row is None:
            continue
        event_ids = _unique_ints(
            _json_list(row["source_event_ids_json"]) + list(spec.get("events") or [])
        )
        conn.execute(
            """
            UPDATE memory_atoms
            SET kind = ?, text = ?, canonical_text = ?, source_event_ids_json = ?,
                status = 'active', confidence = MAX(confidence, 0.9),
                quality_score = MAX(quality_score, 0.9), updated_at_ms = ?
            WHERE id = ?
            """,
            (
                str(spec["kind"]),
                str(spec["text"]),
                str(spec["text"]),
                json.dumps(event_ids, ensure_ascii=False),
                timestamp,
                atom_id,
            ),
        )
        for tag in spec.get("tags") or []:
            _link_atom_tag(conn, atom_id=atom_id, tag=str(tag), timestamp=timestamp)
        count += 1
    return count


def _create_atoms(conn: sqlite3.Connection, *, timestamp: int) -> int:
    count = 0
    for atom_id, spec in NEW_ATOMS.items():
        conn.execute(
            """
            INSERT INTO memory_atoms(
                id, kind, text, canonical_text, source_event_ids_json,
                source_memory_ids_json, scope_app, scope_project, language,
                confidence, quality_score, echo_risk, privacy_level, status,
                created_at_ms, updated_at_ms, last_used_at_ms
            ) VALUES (?, ?, ?, ?, ?, '[]', '', '', 'zh', 0.95, 0.95, 0.0,
                      'local', 'active', ?, ?, NULL)
            ON CONFLICT(id) DO UPDATE SET
                kind = excluded.kind,
                text = excluded.text,
                canonical_text = excluded.canonical_text,
                source_event_ids_json = excluded.source_event_ids_json,
                confidence = excluded.confidence,
                quality_score = excluded.quality_score,
                status = 'active',
                updated_at_ms = excluded.updated_at_ms
            """,
            (
                atom_id,
                str(spec["kind"]),
                str(spec["text"]),
                str(spec["text"]),
                json.dumps(_unique_ints(spec.get("events") or []), ensure_ascii=False),
                timestamp,
                timestamp,
            ),
        )
        for tag in spec.get("tags") or []:
            _link_atom_tag(conn, atom_id=atom_id, tag=str(tag), timestamp=timestamp)
        count += 1
    return count


def _assign_group_memberships(conn: sqlite3.Connection, *, timestamp: int) -> None:
    assignments = {
        "group:model-and-data": MODEL_ATOMS,
        "group:memory-rag": MEMORY_ATOMS,
        "group:voice-input": VOICE_ATOMS,
        "group:ui-design": UI_ATOMS,
        "group:agent-interview": AGENT_ATOMS,
        "group:learning-system": LEARNING_ATOMS,
        "group:input-method": (
            CANDIDATE_ATOMS | MODEL_ATOMS | MEMORY_ATOMS | VOICE_ATOMS | UI_ATOMS | AGENT_ATOMS
        ),
    }
    for group_id, atom_ids in assignments.items():
        for atom_id in atom_ids:
            if not _active_atom_exists(conn, atom_id):
                continue
            conn.execute(
                """
                INSERT INTO memory_semantic_group_members(
                    group_id, member_type, member_id, weight, source, updated_at_ms
                ) VALUES (?, 'atom', ?, 0.9, 'curated_baseline', ?)
                ON CONFLICT(group_id, member_type, member_id) DO UPDATE SET
                    weight = MAX(memory_semantic_group_members.weight, excluded.weight),
                    source = excluded.source,
                    updated_at_ms = excluded.updated_at_ms
                """,
                (group_id, atom_id, timestamp),
            )
    conn.execute(
        """
        INSERT INTO memory_semantic_group_members(
            group_id, member_type, member_id, weight, source, updated_at_ms
        )
        SELECT 'group:input-method', 'atom', a.id, 0.7,
               'curated_baseline_fallback', ?
        FROM memory_atoms a
        WHERE a.status = 'active'
          AND NOT EXISTS (
              SELECT 1
              FROM memory_semantic_group_members gm
              WHERE gm.member_type = 'atom' AND gm.member_id = a.id
          )
        """,
        (timestamp,),
    )
    untagged = conn.execute(
        """
        SELECT a.id, MIN(gm.group_id) AS group_id
        FROM memory_atoms a
        LEFT JOIN memory_atom_tags tags ON tags.memory_atom_id = a.id
        LEFT JOIN memory_semantic_group_members gm
          ON gm.member_type = 'atom' AND gm.member_id = a.id
        WHERE a.status = 'active' AND tags.memory_atom_id IS NULL
        GROUP BY a.id
        """
    ).fetchall()
    for row in untagged:
        group_id = str(row["group_id"] or "")
        tag = GROUPS.get(group_id, ("长期记忆", ""))[0]
        _link_atom_tag(
            conn,
            atom_id=str(row["id"]),
            tag=tag,
            timestamp=timestamp,
        )


def _archive_legacy_books(conn: sqlite3.Connection, *, timestamp: int) -> int:
    count = 0
    for book_id in ARCHIVE_BOOK_IDS:
        cursor = conn.execute(
            """
            UPDATE memory_books
            SET status = 'archived', archived_at_ms = ?,
                archive_reason = 'superseded_by_curated_baseline',
                updated_at_ms = ?
            WHERE book_id = ? AND status != 'archived'
            """,
            (timestamp, timestamp, book_id),
        )
        count += int(cursor.rowcount or 0)
    return count


def _upsert_active_books(conn: sqlite3.Connection, *, timestamp: int) -> int:
    count = 0
    for book_id, spec in ACTIVE_BOOKS.items():
        atom_ids = [
            atom_id
            for atom_id in sorted(spec["atoms"])
            if _active_atom_exists(conn, atom_id)
        ]
        source_ids = _atom_source_ids(conn, atom_ids)
        book_key = book_id.split(":", 2)[-1]
        conn.execute(
            """
            INSERT INTO memory_books(
                book_id, book_type, book_key, title, summary, normalized_text,
                project, app, tags_json, surface_hints_json,
                query_expansions_json, source_event_ids_json,
                memory_atom_ids_json, status, confidence, quality_score,
                created_at_ms, updated_at_ms, metadata_json, archived_at_ms,
                last_active_at_ms, archive_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, '', ?, '[]', '[]', ?, ?, 'active',
                      0.95, 0.95, ?, ?, ?, NULL, ?, '')
            ON CONFLICT(book_id) DO UPDATE SET
                book_type = excluded.book_type,
                book_key = excluded.book_key,
                title = excluded.title,
                summary = excluded.summary,
                normalized_text = excluded.normalized_text,
                project = excluded.project,
                app = excluded.app,
                tags_json = excluded.tags_json,
                source_event_ids_json = excluded.source_event_ids_json,
                memory_atom_ids_json = excluded.memory_atom_ids_json,
                status = 'active',
                confidence = excluded.confidence,
                quality_score = excluded.quality_score,
                updated_at_ms = excluded.updated_at_ms,
                metadata_json = excluded.metadata_json,
                archived_at_ms = NULL,
                last_active_at_ms = excluded.last_active_at_ms,
                archive_reason = ''
            """,
            (
                book_id,
                "demo" if book_id.startswith("book:demo:") else "topic",
                book_key,
                str(spec["title"]),
                str(spec["summary"]),
                normalize_text(f"{spec['title']} {spec['summary']}"),
                PROJECT,
                json.dumps(list(spec["tags"]), ensure_ascii=False),
                json.dumps(source_ids, ensure_ascii=False),
                json.dumps(atom_ids, ensure_ascii=False),
                timestamp,
                timestamp,
                json.dumps(
                    {"source": "curated_baseline", "atomCount": len(atom_ids)},
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                timestamp,
            ),
        )
        conn.execute(
            "DELETE FROM memory_semantic_group_members WHERE member_type = 'book' AND member_id = ?",
            (book_id,),
        )
        for group_id in spec["groups"]:
            conn.execute(
                """
                INSERT INTO memory_semantic_group_members(
                    group_id, member_type, member_id, weight, source, updated_at_ms
                ) VALUES (?, 'book', ?, 0.95, 'curated_baseline', ?)
                """,
                (group_id, book_id, timestamp),
            )
        count += 1
    orphan_rows = conn.execute(
        """
        SELECT a.id
        FROM memory_atoms a
        WHERE a.status = 'active'
          AND NOT EXISTS (
              SELECT 1
              FROM memory_books b, json_each(b.memory_atom_ids_json) atom_ref
              WHERE b.status = 'active' AND atom_ref.value = a.id
          )
        ORDER BY a.id
        """
    ).fetchall()
    if orphan_rows:
        core_book_id = "book:topic:input-method-features"
        row = conn.execute(
            "SELECT memory_atom_ids_json FROM memory_books WHERE book_id = ?",
            (core_book_id,),
        ).fetchone()
        atom_ids = _unique_strings(
            _json_list(row["memory_atom_ids_json"] if row is not None else "[]")
            + [str(item["id"]) for item in orphan_rows]
        )
        source_ids = _atom_source_ids(conn, atom_ids)
        conn.execute(
            """
            UPDATE memory_books
            SET memory_atom_ids_json = ?, source_event_ids_json = ?,
                updated_at_ms = ?
            WHERE book_id = ?
            """,
            (
                json.dumps(atom_ids, ensure_ascii=False),
                json.dumps(source_ids, ensure_ascii=False),
                timestamp,
                core_book_id,
            ),
        )
    return count


def _upsert_app_archive_books(conn: sqlite3.Connection, *, timestamp: int) -> int:
    by_app: dict[str, list[sqlite3.Row]] = defaultdict(list)
    rows = conn.execute(
        """
        SELECT e.id, e.created_at_ms, e.source, e.committed_text, e.app, e.tags_json
        FROM input_events e
        LEFT JOIN memory_state s ON s.event_id = e.id
        WHERE COALESCE(s.deleted, 0) = 0
        ORDER BY e.created_at_ms ASC, e.id ASC
        """
    ).fetchall()
    for row in rows:
        source = compact_whitespace(str(row["source"] or ""))
        if source not in ELIGIBLE_SOURCES:
            continue
        tags = _json_list(row["tags_json"])
        if source == "codex_history" and "role:user" not in tags:
            continue
        app = _normalize_app(str(row["app"] or ""))
        if not app or app.casefold() in INTERNAL_APPS:
            continue
        quality = assess_input_text(
            str(row["committed_text"] or ""),
            source=source,
            tags=[str(tag) for tag in tags],
        )
        if quality.injectable:
            by_app[app].append(row)

    for app, app_rows in by_app.items():
        event_ids = [int(row["id"]) for row in app_rows]
        first_ms = int(app_rows[0]["created_at_ms"] or 0)
        last_ms = int(app_rows[-1]["created_at_ms"] or 0)
        first_day = _local_day(conn, first_ms)
        last_day = _local_day(conn, last_ms)
        title = f"{APP_TITLES.get(app, app)} 完整输入归档"
        summary = (
            f"保留 {first_day} 至 {last_day} 的 {len(event_ids)} 段完整用户输入；"
            "按 App 边界用于时间检索和追溯，不把原始记录直接当作长期记忆注入。"
        )
        digest = hashlib.sha256(app.encode()).hexdigest()[:12]
        book_id = f"book:app-archive:{digest}"
        conn.execute(
            """
            INSERT INTO memory_books(
                book_id, book_type, book_key, title, summary, normalized_text,
                project, app, tags_json, surface_hints_json,
                query_expansions_json, source_event_ids_json,
                memory_atom_ids_json, status, confidence, quality_score,
                created_at_ms, updated_at_ms, metadata_json, archived_at_ms,
                last_active_at_ms, archive_reason
            ) VALUES (?, 'app_archive', ?, ?, ?, ?, ?, ?, ?, '[]', '[]', ?,
                      '[]', 'archived', 1.0, 1.0, ?, ?, ?, ?, ?,
                      'complete_input_history')
            ON CONFLICT(book_id) DO UPDATE SET
                title = excluded.title,
                summary = excluded.summary,
                normalized_text = excluded.normalized_text,
                project = excluded.project,
                app = excluded.app,
                tags_json = excluded.tags_json,
                source_event_ids_json = excluded.source_event_ids_json,
                status = 'archived',
                confidence = 1.0,
                quality_score = 1.0,
                updated_at_ms = excluded.updated_at_ms,
                metadata_json = excluded.metadata_json,
                archived_at_ms = excluded.archived_at_ms,
                last_active_at_ms = excluded.last_active_at_ms,
                archive_reason = excluded.archive_reason
            """,
            (
                book_id,
                f"app-{digest}",
                title,
                summary,
                normalize_text(f"{title} {summary}"),
                PROJECT,
                app,
                json.dumps(["输入历史", "App边界"], ensure_ascii=False),
                json.dumps(event_ids, ensure_ascii=False),
                first_ms,
                timestamp,
                json.dumps(
                    {
                        "source": "curated_baseline",
                        "inputCount": len(event_ids),
                        "firstEventId": event_ids[0],
                        "lastEventId": event_ids[-1],
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                timestamp,
                last_ms,
            ),
        )
    return len(by_app)


def _clean_phrase_items(conn: sqlite3.Connection, *, timestamp: int) -> dict[str, int]:
    rows = conn.execute(
        """
        SELECT id, text, metadata_json
        FROM memory_items
        WHERE kind = 'phrase' AND status = 'approved'
        """
    ).fetchall()
    transport_count = 0
    sentence_count = 0
    for row in rows:
        text = compact_whitespace(str(row["text"] or ""))
        metadata = str(row["metadata_json"] or "")
        transport = any(
            marker in metadata
            for marker in (
                "rime-commit",
                "group-buffer",
                "sidecar-selected",
                "source:model",
            )
        )
        sentence = len(text) > 18
        if not transport and not sentence:
            continue
        conn.execute(
            "UPDATE memory_items SET status = 'hidden', updated_at_ms = ? WHERE id = ?",
            (timestamp, int(row["id"])),
        )
        transport_count += int(transport)
        sentence_count += int(sentence and not transport)
    return {
        "transportFragmentsHidden": transport_count,
        "sentenceLikePhrasesHidden": sentence_count,
    }


def _clean_tags(conn: sqlite3.Connection, *, timestamp: int) -> dict[str, int]:
    hidden = 0
    for tag in HIDDEN_TAGS:
        cursor = conn.execute(
            """
            UPDATE memory_tags
            SET status = 'hidden', updated_at_ms = ?
            WHERE normalized_tag = ? AND status = 'active'
            """,
            (timestamp, normalize_text(tag)),
        )
        hidden += int(cursor.rowcount or 0)
    conn.execute(
        """
        UPDATE memory_tags
        SET tag = 'README', normalized_tag = ?, description = ?,
            updated_at_ms = ?
        WHERE normalized_tag = ?
        """,
        (
            normalize_text("README"),
            "项目说明、功能截图、安装与验证文档。",
            timestamp,
            normalize_text("readme"),
        ),
    )
    descriptions = {
        "ArcGIS": "地理数据与地图平台能力。",
        "LLM": "大语言模型生成与补全能力。",
        "PI": "Pi Agent Runtime 及其插件生态。",
        "RAG": "基于本地证据的检索增强生成。",
        "Rime": "Rime/Squirrel 输入法运行链路。",
        "UI": "候选框与控制面板用户界面。",
        "上下文": "当前输入、前台 App 与近期完整输入。",
        "插件": "可安装、授权和回滚的扩展能力。",
        "数据库": "本地 SQLite 记忆、索引与配置数据。",
        "机器学习": "从数据和反馈中学习的模型方法。",
        "架构": "模块边界、数据流与运行时职责。",
        "模型": "补全、生成、语音与检索模型。",
        "深度学习": "神经网络训练与推理机制。",
        "自然语言处理": "文本理解、生成与检索处理。",
        "训练": "模型训练、评测与迭代流程。",
        "记忆": "可追溯、可更新的长期用户记忆。",
        "预测": "根据输入上下文生成下一段候选。",
    }
    for name, description in descriptions.items():
        conn.execute(
            """
            UPDATE memory_tags
            SET description = ?, updated_at_ms = ?
            WHERE normalized_tag = ? AND status = 'active'
            """,
            (description, timestamp, normalize_text(name)),
        )
    for name, description in (
        ("输入历史", "按 App 和时间保留的完整用户输入归档。"),
        ("App边界", "输入与上下文不得跨前台 App 自动拼接。"),
        ("学习偏好", "用户稳定的学习与讲解方式偏好。"),
        ("学习记录", "问题、复习和学习进度留痕。"),
        ("工程工作流", "源码调研、TODO、验证和交付方式。"),
        ("源码调研", "从成熟项目源码与真实调用链提炼机制。"),
        ("多端同步", "Agent Gateway 的序号、重放与快照恢复。"),
        ("连续补全", "选择候选后继续预测下一段。"),
        ("Atom-first", "先整理记忆原子，再派生主题书、标签和关系。"),
    ):
        _ensure_tag(conn, name=name, description=description, timestamp=timestamp)
    return {"hiddenEphemeralTags": hidden}


def _supersede_pending_drafts(conn: sqlite3.Connection) -> None:
    run_ids = [
        str(row[0])
        for row in conn.execute(
            "SELECT run_id FROM memory_cleanup_runs WHERE status = 'draft' AND run_id LIKE 'memory_book_%'"
        ).fetchall()
    ]
    if not run_ids:
        return
    placeholders = ",".join("?" for _ in run_ids)
    conn.execute(
        f"UPDATE memory_cleanup_runs SET status = 'superseded' WHERE run_id IN ({placeholders})",
        run_ids,
    )
    conn.execute(
        f"""
        UPDATE memory_cleanup_diffs
        SET status = 'rejected'
        WHERE run_id IN ({placeholders}) AND status IN ('pending', 'approved')
        """,
        run_ids,
    )
    conn.execute(
        """
        UPDATE memory_compile_state
        SET last_drafted_event_id = 0, last_draft_ms = 0,
            last_draft_bundle_hash = '', last_draft_run_id = ''
        WHERE last_draft_run_id != ''
        """
    )


def _link_atom_tag(
    conn: sqlite3.Connection,
    *,
    atom_id: str,
    tag: str,
    timestamp: int,
) -> None:
    tag_id = _ensure_tag(
        conn,
        name=tag,
        description=f"{tag}相关的稳定记忆。",
        timestamp=timestamp,
    )
    conn.execute(
        """
        INSERT INTO memory_atom_tags(memory_atom_id, tag_id, weight, source)
        VALUES (?, ?, 0.9, 'curated_baseline')
        ON CONFLICT(memory_atom_id, tag_id) DO UPDATE SET
            weight = MAX(memory_atom_tags.weight, excluded.weight),
            source = excluded.source
        """,
        (atom_id, str(tag_id)),
    )


def _ensure_tag(
    conn: sqlite3.Connection,
    *,
    name: str,
    description: str,
    timestamp: int,
) -> int:
    normalized = normalize_text(name)
    row = conn.execute(
        "SELECT id FROM memory_tags WHERE normalized_tag = ? ORDER BY status = 'active' DESC LIMIT 1",
        (normalized,),
    ).fetchone()
    if row is not None:
        tag_id = int(row["id"])
        conn.execute(
            """
            UPDATE memory_tags
            SET tag = ?, description = CASE WHEN trim(description) = '' THEN ? ELSE description END,
                source = CASE WHEN source = 'legacy_auto' THEN 'user' ELSE source END,
                status = 'active', quality_score = MAX(quality_score, 0.9),
                updated_at_ms = ?
            WHERE id = ?
            """,
            (name, description, timestamp, tag_id),
        )
        return tag_id
    cursor = conn.execute(
        """
        INSERT INTO memory_tags(
            tag, normalized_tag, tag_type, vector_json, model_fingerprint,
            quality_score, created_at_ms, updated_at_ms, description,
            source, status, metadata_json
        ) VALUES (?, ?, 'concept', NULL, '', 0.9, ?, ?, ?, 'user', 'active', ?)
        """,
        (
            name,
            normalized,
            timestamp,
            timestamp,
            description,
            json.dumps({"source": "curated_baseline"}, ensure_ascii=False),
        ),
    )
    return int(cursor.lastrowid)


def _active_atom_exists(conn: sqlite3.Connection, atom_id: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM memory_atoms WHERE id = ? AND status IN ('active', 'approved')",
            (atom_id,),
        ).fetchone()
        is not None
    )


def _atom_source_ids(conn: sqlite3.Connection, atom_ids: list[str]) -> list[int]:
    if not atom_ids:
        return []
    placeholders = ",".join("?" for _ in atom_ids)
    rows = conn.execute(
        f"SELECT source_event_ids_json FROM memory_atoms WHERE id IN ({placeholders})",
        atom_ids,
    ).fetchall()
    return _unique_ints(
        event_id
        for row in rows
        for event_id in _json_list(row["source_event_ids_json"])
    )


def _normalize_app(value: str) -> str:
    app = compact_whitespace(value)
    return "com.openai.codex" if app.casefold() == "codex" else app


def _local_day(conn: sqlite3.Connection, timestamp_ms: int) -> str:
    return str(
        conn.execute(
            "SELECT date(? / 1000, 'unixepoch', 'localtime')",
            (timestamp_ms,),
        ).fetchone()[0]
    )


def _json_list(raw: object) -> list[object]:
    if isinstance(raw, list):
        return raw
    try:
        payload = json.loads(str(raw or "[]"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    return payload if isinstance(payload, list) else []


def _unique_ints(values: object) -> list[int]:
    result: list[int] = []
    for value in values:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed > 0 and parsed not in result:
            result.append(parsed)
    return result


def _unique_strings(values: object) -> list[str]:
    return list(
        dict.fromkeys(
            compact_whitespace(str(value))
            for value in values
            if compact_whitespace(str(value))
        )
    )


def _read_only_connection(path: Path) -> sqlite3.Connection:
    uri = f"file:{quote(str(path))}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _online_backup(source: Path, output: Path) -> None:
    with _read_only_connection(source) as source_conn, sqlite3.connect(output) as target_conn:
        source_conn.backup(target_conn, pages=2048, sleep=0.01)
        target_conn.execute(
            "PRAGMA user_version = "
            + str(int(source_conn.execute("PRAGMA user_version").fetchone()[0]))
        )


def _remove_sqlite_files(path: Path) -> None:
    path.unlink(missing_ok=True)
    Path(str(path) + "-wal").unlink(missing_ok=True)
    Path(str(path) + "-shm").unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
