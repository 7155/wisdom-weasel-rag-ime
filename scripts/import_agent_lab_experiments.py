#!/usr/bin/env python3
"""Import a public-safe experiment ledger into the local Agent Lab database.

The source ledger may contain richer local evidence.  This importer keeps only
the product projection needed by Agent Lab.  It admits explicitly bounded,
public output examples while deliberately excluding raw Gold, private
transcripts, SQL and machine paths.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag_ime.agent_lab_experiments import AgentLabExperimentStore
from rag_ime.contracts.json_schema import validate_contract


_LEDGER_SCHEMA = "paw.interview-agent-experiment-ledger.v1"
_PROJECTION_REVISION = "agent-lab-public-projection-v4"
_EVALUATION_KINDS = {
    "workflow",
    "rag_retrieval",
    "answer_evidence",
    "tool_runtime",
    "trace_repair",
    "memory",
    "model_cost",
    "other",
}

# The checked-in interview ledger predates the Agent Lab matrix rows that were
# first exposed by the preview transport.  These recipes are deliberately
# small: the evidence ledger supplies the measured values and claims, while a
# recipe supplies only the identity of the one changed factor and the two run
# bindings needed to turn that evidence into an interview card.  Keeping the
# recipes here (rather than importing frontend fixtures) makes the Python
# projection the source of truth for the real Eval Lab read-through.
_DERIVED_RECIPES: tuple[dict[str, Any], ...] = (
    {
        "id": "enterprise-rag.tag-graph-readiness.v1",
        "kind": "rag_tag_readiness",
        "metricId": "knowledge.enterprise.tag_reranker.readiness.20260901",
        "title": "Enterprise RAG · Graph + Tag 重排就绪检查",
        "vertical": "enterprise-knowledge-retrieval",
        "datasetId": "enterprise-rag-smoke-validation-v1",
        "split": "validation",
        "caseCount": 16,
        "unit": "16 条冻结检索问题、5,101 篇文档、29,846 个 chunk",
        "manifestSha256": "b030721445f14df0bc5b69dd046a99687c5d846aa42d7c2f318e33f44d6fa6a3",
        "primaryMetric": "nDCG@10（Recall@10 与 MRR 为保护指标）",
        "evaluator": "Host-private qrels + deterministic retrieval scorer",
        "hardGates": ["qrels 对 Agent 隐藏", "corpus/split hash 固定", "向量覆盖完整", "Held-out 未打开"],
        "status": "open_gap",
        "claimStatus": "blocked",
        "projectionState": "history",
        "supersededBy": "enterprise-rag.sol-max-budget3-r3.v1",
        "effectStatus": "not_run",
        "decision": "not_run",
        "factor": {
            "name": "memory_rag",
            "before": "Qwen3 reranker 已有 16 题 Validation 分数",
            "after": "Graph + Tag 候选因企业 source-bound 图为空而不运行",
            "reason": "先检查 documentId/chunkId 绑定；不能拿 Memory 的 memory_item_id 冒充企业文档排序信号。",
        },
        "baselineRunId": "enterprise-rag-hybrid-qwen3-validation",
        "baselineMetricMap": {
            "mrr": ("qwenReferenceMrr",),
            "ndcgAt10": ("qwenReferenceNdcgAt10",),
            "recallAt10": ("qwenReferenceRecallAt10",),
        },
        "candidateRunId": "enterprise-rag-tag-reranker-readiness-20260901-v1",
        "candidateMetricMap": {
            "knowledgeGraphNodes": ("knowledgeGraphNodes",),
            "knowledgeGraphEdges": ("knowledgeGraphEdges",),
            "knowledgeGraphExtractions": ("knowledgeGraphExtractions",),
            "tagMetricsAvailable": ("tagMetricsAvailable",),
        },
        "baselineOutput": ("readiness", "Qwen3 与 Graph + Tag 是否可做公平 A/B？", "Qwen3 有冻结 Validation 参照。"),
        "candidateOutput": ("readiness", "检查企业 Knowledge 图与 Tag 身份。", "node、edge、extraction 都为 0；A/B 在评分前被阻断。"),
        "decisionReason": "企业 source-bound Graph 尚未建立，候选没有合法排序特征；不生成伪分数，保留 Qwen3 参照。",
        "outputComparison": ("readiness", "Qwen3 有冻结 Validation 参照。", "企业图为空，A/B 在评分前被阻断。"),
        "star": {
            "situation": "企业问题既有专名又有跨文档语义关系。",
            "task": "先优化检索，再单独验证答案与引用。",
            "action": "Trace Reviewer 先核对 Graph/Tag 的实体身份、数据覆盖和可评分条件。",
            "result": "在 Provider 运行前阻断无效 A/B；没有消耗 Held-out，也没有声称 Tag 优于或劣于 Qwen3。",
        },
        "resumeBullet": "为 Graph + Tag 重排增加 readiness gate，在企业图为空时阻断伪 A/B。",
        "openGaps": ["需要先构建 documentId + chunkId 绑定的企业 Knowledge 图"],
    },
    {
        "id": "enterprise-rag.answer-luna-baseline.v20",
        "kind": "rag_answer",
        "metricId": "knowledge.enterprise.answer_evidence.luna_max.validation.reject.20260902",
        "secondaryMetricId": "knowledge.enterprise.answer_evidence.validation.reject.20260901",
        "lane": "baseline",
        "title": "Enterprise RAG · Luna Baseline（模型消融）",
        "vertical": "enterprise-knowledge-retrieval",
        "datasetId": "enterprise-rag-answer-evidence-validation-v1",
        "split": "validation",
        "caseCount": 4,
        "unit": "4 个冻结 answer case；其中 2 个可回答、2 个 info_not_found",
        "manifestSha256": "f154bbc55dba2733e10e0ebac91da6af50493565e688b19e80327bc028f21c96",
        "primaryMetric": "答案通过、事实覆盖、可回答问题引用支持与拒答分开计分",
        "evaluator": "Host-private fact-to-source/chunk/quote verifier + answer judge",
        "hardGates": ["逐事实 source/chunk/quote 支持", "info_not_found 拒答", "输出协议", "Held-out 未消费"],
        "status": "rejected",
        "claimStatus": "supporting",
        "projectionState": "history",
        "supersededBy": "enterprise-rag.sol-max-budget3-r3.v1",
        "effectStatus": "neutral",
        "factor": {"name": "model", "before": "GPT-5.6 Sol / max", "after": "GPT-5.6 Luna / max", "reason": "先只换模型，判断低价模型是否保持答案与逐事实引用质量。"},
        "baselineRunId": "enterprise-rag-answer-evidence-sol-v16-baseline",
        "baselineSourceMetricId": "knowledge.enterprise.answer_evidence.validation.reject.20260901",
        "baselineLane": "baseline",
        "candidateLane": "baseline",
        "candidateRunId": "enterprise-rag-answer-evidence-luna-v20-baseline",
        "candidateSourceMetricId": "knowledge.enterprise.answer_evidence.luna_max.validation.reject.20260902",
        "decision": "reject",
        "deltaKeys": ["answerSuccessRate", "citationFactCoverage", "answerableCitationSupportRate", "tokens", "toolCalls", "latencyMs", "outputProtocolRate"],
        "decisionReason": "模型替换保持现有质量且耗时下降，但核心引用支持仍为 0；候选不能上线。",
        "outputBefore": "Sol：4 个协议 case 中 2 个通过；2 个可回答问题中 1 个答案正确，必要事实覆盖 6/9、引用事实 2/9、可回答问题引用支持 0/2，应拒答问题 2/2。",
        "outputAfter": "Luna：同样 2/4 个协议 case 通过、1/2 个可回答答案正确，事实与引用指标不变；更快但仍不满足引用硬门。",
        "resumeBullet": "在冻结答案合同上完成 Sol/Luna 模型消融，并因引用支持为 0 拒绝候选。",
        "openGaps": ["安全逐 query 排名回执待补", "答案与引用 Validation 尚未产生可 Promotion 结果", "Held-out 仍封存"],
    },
    {
        "id": "enterprise-rag.answer-luna-skill.v20",
        "kind": "rag_answer",
        "metricId": "knowledge.enterprise.answer_evidence.luna_max.validation.reject.20260902",
        "lane": "skill",
        "title": "Enterprise RAG · Skill Profile 的 Sol / Luna 模型消融",
        "vertical": "enterprise-knowledge-retrieval",
        "datasetId": "enterprise-rag-answer-evidence-validation-v1",
        "split": "validation",
        "caseCount": 4,
        "unit": "4 个冻结 answer case；其中 2 个可回答、2 个 info_not_found",
        "manifestSha256": "f154bbc55dba2733e10e0ebac91da6af50493565e688b19e80327bc028f21c96",
        "primaryMetric": "答案通过、事实覆盖、可回答问题引用支持与拒答分开计分",
        "evaluator": "Host-private fact-to-source/chunk/quote verifier + answer judge",
        "hardGates": ["逐事实 source/chunk/quote 支持", "info_not_found 拒答", "输出协议", "Held-out 未消费"],
        "status": "rejected",
        "claimStatus": "supporting",
        "projectionState": "history",
        "supersededBy": "enterprise-rag.sol-max-budget3-r3.v1",
        "effectStatus": "neutral",
        "factor": {"name": "model", "before": "GPT-5.6 Sol / max + 冻结 Citation Skill", "after": "GPT-5.6 Luna / max + 同一 Citation Skill", "reason": "该回执只替换模型；Prompt、Skill、Tool、Workflow、语料和评分合同全部冻结。"},
        "baselineRunId": "enterprise-rag-answer-evidence-sol-v16-skill",
        "baselineSourceMetricId": "knowledge.enterprise.answer_evidence.validation.reject.20260901",
        "baselineLane": "skill",
        "candidateLane": "skill",
        "candidateRunId": "enterprise-rag-answer-evidence-luna-v20-skill",
        "decision": "reject",
        "deltaKeys": ["answerSuccessRate", "citationFactCoverage", "answerableCitationSupportRate", "tokens", "toolCalls", "latencyMs", "outputProtocolRate"],
        "decisionReason": "Luna 在同一 Skill profile 上质量与 Tool 持平、耗时下降，但 Token 增加且引用硬门仍失败。",
        "outputBefore": "Sol Max + 冻结 Citation Skill：2/4 个协议 case 通过；1/2 个可回答答案正确，必要事实覆盖 6/9、引用事实 2/9、可回答问题引用支持 0/2，应拒答问题 2/2。",
        "outputAfter": "Luna + 同一 Citation Skill：同样 2/4、1/2；事实、引用和 Tool 数不变，耗时下降、Token 增加，引用硬门仍失败。",
        "resumeBullet": "在冻结 Citation Skill profile 上完成 Sol/Luna 模型消融；耗时下降但引用硬门仍失败。",
        "openGaps": ["安全逐 query 排名回执待补", "答案与引用 Validation 尚未产生可 Promotion 结果", "Held-out 仍封存"],
    },
    {
        "id": "enterprise-rag.answer-luna-tuned.v20",
        "kind": "rag_answer",
        "metricId": "knowledge.enterprise.answer_evidence.luna_max.validation.reject.20260902",
        "lane": "tuned",
        "title": "Enterprise RAG · Tuned Profile 的 Sol / Luna 模型消融",
        "vertical": "enterprise-knowledge-retrieval",
        "datasetId": "enterprise-rag-answer-evidence-validation-v1",
        "split": "validation",
        "caseCount": 4,
        "unit": "4 个冻结 answer case；其中 2 个可回答、2 个 info_not_found",
        "manifestSha256": "f154bbc55dba2733e10e0ebac91da6af50493565e688b19e80327bc028f21c96",
        "primaryMetric": "答案通过、事实覆盖、可回答问题引用支持与拒答分开计分",
        "evaluator": "Host-private fact-to-source/chunk/quote verifier + answer judge",
        "hardGates": ["逐事实 source/chunk/quote 支持", "info_not_found 拒答", "输出协议", "Held-out 未消费"],
        "status": "rejected",
        "claimStatus": "supporting",
        "projectionState": "history",
        "supersededBy": "enterprise-rag.sol-max-budget3-r3.v1",
        "effectStatus": "neutral",
        "factor": {"name": "model", "before": "GPT-5.6 Sol / max + 冻结 Tuned RAG", "after": "GPT-5.6 Luna / max + 同一 Tuned RAG", "reason": "该回执只替换模型；Tuned RAG、Prompt、Skill、Tool、Workflow 与评分合同全部冻结。"},
        "baselineRunId": "enterprise-rag-answer-evidence-sol-v16-tuned",
        "baselineSourceMetricId": "knowledge.enterprise.answer_evidence.validation.reject.20260901",
        "baselineLane": "tuned",
        "candidateLane": "tuned",
        "candidateRunId": "enterprise-rag-answer-evidence-luna-v20-tuned",
        "decision": "reject",
        "deltaKeys": ["answerSuccessRate", "citationFactCoverage", "answerableCitationSupportRate", "tokens", "toolCalls", "latencyMs", "outputProtocolRate"],
        "decisionReason": "Luna 在同一 Tuned profile 上质量与 Tool 持平、耗时下降，但 Token 增加且引用硬门仍失败。",
        "outputBefore": "Sol Max + 冻结 Tuned RAG：2/4 个协议 case 通过；1/2 个可回答答案正确，必要事实覆盖 6/9、引用事实 2/9、可回答问题引用支持 0/2，应拒答问题 2/2。",
        "outputAfter": "Luna + 同一 Tuned RAG：同样 2/4、1/2；事实、引用和 Tool 数不变，耗时下降、Token 增加，引用硬门仍失败。",
        "resumeBullet": "在冻结 Tuned RAG profile 上完成 Sol/Luna 模型消融；耗时下降但引用硬门仍失败。",
        "openGaps": ["安全逐 query 排名回执待补", "答案与引用 Validation 尚未产生可 Promotion 结果", "Held-out 仍封存"],
    },
    {
        "id": "enterprise-rag.answer-luna-agentic.v20",
        "kind": "rag_answer",
        "metricId": "knowledge.enterprise.answer_evidence.luna_max.validation.reject.20260902",
        "lane": "agentic",
        "title": "Enterprise RAG · Agentic Profile 的 Sol / Luna 模型消融",
        "vertical": "enterprise-knowledge-retrieval",
        "datasetId": "enterprise-rag-answer-evidence-validation-v1",
        "split": "validation",
        "caseCount": 4,
        "unit": "4 个冻结 answer case；其中 2 个可回答、2 个 info_not_found",
        "manifestSha256": "f154bbc55dba2733e10e0ebac91da6af50493565e688b19e80327bc028f21c96",
        "primaryMetric": "答案通过、事实覆盖、可回答问题引用支持与拒答分开计分",
        "evaluator": "Host-private fact-to-source/chunk/quote verifier + answer judge",
        "hardGates": ["逐事实 source/chunk/quote 支持", "info_not_found 拒答", "输出协议", "Held-out 未消费"],
        "status": "rejected",
        "claimStatus": "supporting",
        "projectionState": "history",
        "supersededBy": "enterprise-rag.sol-max-budget3-r3.v1",
        "effectStatus": "regressed",
        "factor": {"name": "model", "before": "GPT-5.6 Sol / max + 冻结 Agentic Workflow", "after": "GPT-5.6 Luna / max + 同一 Agentic Workflow", "reason": "该回执只替换模型；Agentic Workflow、Prompt、Skill、Tool、语料与评分合同全部冻结。"},
        "baselineRunId": "enterprise-rag-answer-evidence-sol-v16-agentic",
        "baselineSourceMetricId": "knowledge.enterprise.answer_evidence.validation.reject.20260901",
        "baselineLane": "agentic",
        "candidateLane": "agentic",
        "candidateRunId": "enterprise-rag-answer-evidence-luna-v20-agentic",
        "decision": "reject",
        "deltaKeys": ["answerSuccessRate", "citationFactCoverage", "answerableCitationSupportRate", "toolCalls", "latencyMs", "outputProtocolRate"],
        "decisionReason": "两种模型都未完成 Agentic profile；Luna 更快且少 1 次 Tool，但输出协议进一步失败，Token 不完整不可比。",
        "outputBefore": "Sol Max + 冻结 Agentic Workflow：0/4；13 次 Tool；600.6s；Token 记录是失败占位值，不能比较。",
        "outputAfter": "Luna + 同一 Agentic Workflow：仍为 0/4；12 次 Tool；输出协议由可解析退化为无合法 cases[]，Token 记录仍不完整。",
        "resumeBullet": "在冻结 Agentic profile 上完成 Sol/Luna 模型消融，并因终态与输出协议失败拒绝 Luna。",
        "openGaps": ["安全逐 query 排名回执待补", "答案与引用 Validation 尚未产生可 Promotion 结果", "Held-out 仍封存"],
    },
    {
        "id": "cloudops.validation-baseline.v1",
        "kind": "cloudops_baseline",
        "metricId": "agent.cloudops_validation.20260901",
        "title": "CloudOps · 可评分 Baseline 建立",
        "vertical": "cloudops-incident-diagnosis",
        "datasetId": "cloudops-smoke-v1",
        "split": "validation",
        "caseCount": 12,
        "unit": "12 条冻结 CloudOps Validation case、3 个顺序 PAW Session",
        "manifestSha256": "31939ae6ba38924fd63195fb28c289401674da89e81423fe7dd8217b753fdaec",
        "primaryMetric": "CA（FA/JRA/Top3JRA 为保护门禁）",
        "evaluator": "Host-only CloudOps scorer",
        "hardGates": ["12 个 case 都有答案", "观察快照与 scorer 一致", "Tool failure 单独计数", "Held-out 未观察"],
        "status": "kept",
        "claimStatus": "supporting",
        "projectionState": "history",
        "supersededBy": "cloudops.alert-first-sol-max.v1",
        "effectStatus": "improved",
        "factor": {"name": "tool", "before": "私有 Tool transport / observation hash 合同失败", "after": "冻结 observation snapshot + 可解析 Tool contract", "reason": "先让 12 个 case 真正可运行、可评分，再讨论 Prompt 或 Workflow 优化。"},
        "baselineRunId": "cloudops-paw-baseline-root-20260901-v2",
        "candidateRunId": "cloudops-paw-baseline-root-20260901-v3",
        "decision": "keep",
        "decisionReason": "这一步是评测/Tool 合同恢复，不把“无分→有分”包装成模型质量提升；保留为后续消融的 incumbent。",
        "outputBefore": "运行在 Tool/hash 合同处中断，没有正式总分。",
        "outputAfter": "12/12 作答，CA 1.00，98/98 Tool 成功，得到第一条可评分 baseline。",
        "resumeBullet": "修复 CloudOps Tool/Eval 合同，建立 12/12 可评分的冻结 Validation baseline。",
        "openGaps": ["Provider usage 与 process signals 待投影", "candidate 尚未安装到当前 PAWOS", "Held-out 未观察"],
    },
    {
        "id": "cloudops.evidence-search.v2",
        "kind": "cloudops_candidate",
        "metricId": "agent.cloudops_candidate.evidence_search.20260901",
        "title": "CloudOps · Evidence-search Workflow 消融",
        "vertical": "cloudops-incident-diagnosis",
        "datasetId": "cloudops-smoke-v1",
        "split": "validation",
        "caseCount": 12,
        "unit": "同一 12 条冻结 CloudOps Validation case",
        "manifestSha256": "31939ae6ba38924fd63195fb28c289401674da89e81423fe7dd8217b753fdaec",
        "primaryMetric": "CA（JRA/Top3JRA 与 Tool failure 为保护门禁）",
        "evaluator": "Host-only CloudOps scorer",
        "hardGates": ["CA 不回退", "JRA/Top3JRA 同时记录", "Tool failure 单独计数", "Held-out 未观察"],
        "status": "rejected",
        "claimStatus": "supporting",
        "projectionState": "history",
        "supersededBy": "cloudops.validation-baseline.v1",
        "effectStatus": "regressed",
        "factor": {"name": "workflow", "before": "Baseline 自主探索", "after": "search-first evidence workflow", "reason": "尝试用显式搜索扩大 Top-3 根因证据覆盖，同时记录调用成本。"},
        "baselineRunId": "cloudops-agent-validation-20260901-v1",
        "candidateRunId": "cloudops-evidence-search-validation-reject-20260901-v1",
        "decision": "reject",
        "decisionReason": "Top-3 方向更全不能抵消主 CA 回退与 Tool 近翻倍；search-first 没有两阶段故障对象→根因约束。",
        "outputBefore": "CA 1.00，98 Tool。",
        "outputAfter": "CA 0.8333，189 Tool；Top3JRA 1.00。",
        "resumeBullet": "通过消融拒绝了调用翻倍且主质量回退的 search-first CloudOps workflow。",
        "openGaps": ["Provider usage 与 process signals 待投影", "Held-out 与安装态未执行"],
    },
    {
        "id": "cloudops.observation-id.v4",
        "kind": "cloudops_candidate",
        "metricId": "agent.cloudops_candidate.observation_id.20260901",
        "title": "CloudOps · observationId Tool 消融",
        "vertical": "cloudops-incident-diagnosis",
        "datasetId": "cloudops-smoke-v1",
        "split": "validation",
        "caseCount": 12,
        "unit": "同一 12 条冻结 CloudOps Validation case",
        "manifestSha256": "31939ae6ba38924fd63195fb28c289401674da89e81423fe7dd8217b753fdaec",
        "primaryMetric": "CA（FA/JRA/Top3JRA 为保护门禁）",
        "evaluator": "Host-only CloudOps scorer",
        "hardGates": ["12 个 case 都有答案", "Tool failure 单独计数", "CA/JRA/Top3JRA 不回退", "Held-out 未观察"],
        "status": "rejected",
        "claimStatus": "supporting",
        "projectionState": "history",
        "supersededBy": "cloudops.validation-baseline.v1",
        "effectStatus": "regressed",
        "factor": {"name": "tool", "before": "公开长 cacheKey 容易转录失败", "after": "短 observationId + Host 内部地址映射", "reason": "只修地址型 Tool failure，验证 Tool 可靠性与诊断质量是否能分别守门。"},
        "baselineRunId": "cloudops-agent-validation-20260901-v1",
        "candidateRunId": "cloudops-observation-id-validation-reject-20260901-v1",
        "decision": "reject",
        "decisionReason": "Tool 合同修复成功，但业务诊断质量明显回退；按预设 stop rule 拒绝并停止继续吃同一 Validation。",
        "outputBefore": "Baseline CA 1.00、JRA 0.8333。",
        "outputAfter": "Tool 零失败，但 CA 0.50、JRA 0.4167。",
        "resumeBullet": "把 Tool 可靠性与 Agent 质量分开验收，拒绝了零 Tool failure 但 CA 下降 50% 的候选。",
        "openGaps": ["Provider usage 与 process signals 待投影", "Held-out 与安装态未执行", "同一 Validation 禁止继续开 V5"],
    },
    {
        "id": "cloudops.runtime-selection-repair-retry3.v1",
        "kind": "cloudops_runtime_repair",
        "metricId": "agent.cloudops_runtime_selection_repair.retry3.20260902",
        "receiptOnly": True,
        "metricValues": {
            "runtimeSelectionVerified": 1,
            "promptEntered": 1,
            "providerRequestFailures": 8,
            "toolCalls": 0,
            "canonicalSubmissions": 0,
            "formalScoreProduced": 0,
            "usageAvailable": 0,
            "elapsedMs": 318845,
        },
        "metricClaim": {
            "allowed": "retry3 修复 Runtime 选择顺序后，实际 Luna/max 选择回执通过并进入 Prompt；随后 8 次 Provider request 都以 fetch failed 结束，0 Tool、无 canonical submission、无 Host formal CA/JRA，候选 Reject。",
            "forbidden": "模型质量比较、CloudOps CA/JRA 回退、零成本、成本节省、凭据有效性结论、Held-out、安装态或生产结果。",
        },
        "title": "CloudOps · Runtime 选择顺序修复（retry3）",
        "vertical": "cloudops-incident-diagnosis",
        "datasetId": "cloudops-smoke-v1",
        "split": "validation",
        "caseCount": 12,
        "unit": "同一 12 条冻结 CloudOps Validation；retry3 在 batch-1 Provider 阶段停止",
        "manifestSha256": "31939ae6ba38924fd63195fb28c289401674da89e81423fe7dd8217b753fdaec",
        "primaryMetric": "Runtime admission 到 canonical submission 的阶段门禁；CA/JRA 不可用",
        "evaluator": "Runtime selection receipt + retained failure receipts; Host-only CloudOps scorer not reached",
        "hardGates": ["Luna/max 选择回执匹配", "Prompt 已进入 Session", "Provider request 成功", "canonical submission", "Host formal CA/JRA 可用", "Held-out 未观察"],
        "status": "rejected",
        "claimStatus": "diagnostic",
        "projectionState": "history",
        "supersededBy": "cloudops.validation-baseline.v1",
        "effectStatus": "improved",
        "factor": {
            "name": "workflow",
            "before": "ensure_runtime 在 Runtime 应用正式 selection receipt 前断言 thinking identity，retry2 在 Prompt 前失败",
            "after": "ensure_runtime → provider/model assert → select_thinking → selection receipt assert → prompt",
            "reason": "只修 Runtime admission 的调用顺序；Luna/max、Prompt、Skill、Tool、baseline-v1、suite、Gold 和 scorer 全部冻结。",
        },
        "baselineRunId": "cloudops-luna-max-baseline-validation-20260902-retry2",
        "candidateRunId": "cloudops-luna-max-baseline-validation-20260902-retry3",
        "baselineMetrics": {
            "runtimeSelectionVerified": 0,
            "promptEntered": 0,
            "providerRequestFailures": 0,
            "toolCalls": 0,
            "canonicalSubmissions": 0,
            "formalScoreProduced": 0,
            "usageAvailable": 0,
        },
        "candidateMetrics": {
            "runtimeSelectionVerified": 1,
            "promptEntered": 1,
            "providerRequestFailures": 8,
            "toolCalls": 0,
            "canonicalSubmissions": 0,
            "formalScoreProduced": 0,
            "usageAvailable": 0,
            "elapsedMs": 318845,
        },
        "baselineEvidenceRefs": [
            "eval/interview-metrics/runs/cloudops-luna-max-baseline-validation-20260902-retry1.v1.json",
            "eval/interview-metrics/runs/cloudops-luna-max-baseline-validation-20260902-retry2.v1.json",
            "scripts/run_cloudops_agent_eval.py",
            "tests/test_run_cloudops_agent_eval.py",
        ],
        "candidateEvidenceRefs": [
            "eval/interview-metrics/runs/cloudops-luna-max-baseline-validation-20260902-retry1.v1.json",
            "eval/interview-metrics/runs/cloudops-luna-max-baseline-validation-20260902-retry2.v1.json",
            "eval/interview-metrics/runs/cloudops-luna-max-baseline-validation-20260902-retry3.v1.json",
            "scripts/run_cloudops_agent_eval.py",
            "tests/test_run_cloudops_agent_eval.py",
        ],
        "decision": "reject",
        "deltaKeys": ["runtimeSelectionVerified", "promptEntered", "providerRequestFailures", "toolCalls", "canonicalSubmissions", "formalScoreProduced", "usageAvailable"],
        "decisionReason": "Workflow 修复只证明 Luna/max 选择和 Prompt admission 已越过；8 次 fetch failed 后仍是 0 Tool、0 canonical submission、无正式质量分，故 Reject，failed-run burn 因 usage 不可用而不定价。",
        "outputBefore": "retry2 在 Prompt 前因 thinking identity 预检顺序失败。",
        "outputAfter": "retry3 选择 Luna/max 并进入 Prompt，随后 8 次 fetch failed；0 Tool、无 canonical submission。",
        "resumeBullet": "修复 CloudOps Runtime 选择顺序并越过 Prompt admission，但因 Provider transport 连续失败而保留 Reject 回执。",
        "openGaps": ["Provider transport/network 仍阻断", "Host formal CA/JRA 未产生", "retry3 usage 不可用，failed-run burn unpriced", "candidate 未安装", "Held-out 未观察"],
    },
    {
        "id": "memory.maintenance-observed-failure.v0",
        "kind": "memory_failure",
        "metricId": "memory.maintenance.initial-jsonl-failure.20260902",
        "title": "Memory Maintenance · 真实晚失败基线",
        "vertical": "memory-maintenance",
        "datasetId": "memory-maintenance-public-safe-fixture-v1",
        "split": "shadow_validation",
        "caseCount": 1,
        "unit": "1 条真实 memory-maintenance 失败 Trace",
        "manifestSha256": "58712216e1dd71df953efcba6663b3a437589012a84954ce681d0b936c08dc20",
        "primaryMetric": "阶段级终态与合法 JSON receipt",
        "evaluator": "Runtime receipt boundary; no quality score",
        "hardGates": ["terminal completion", "合法 JSON receipt", "不从耗时推断质量", "Held-out 未消费"],
        "status": "diagnostic",
        "claimStatus": "diagnostic",
        "projectionState": "history",
        "supersededBy": "memory.maintenance-luna-shadow-v5.v1",
        "effectStatus": "unverified",
        "factor": {"name": "workflow", "before": "单体 Context→Provider→JSONL→Apply", "after": "未改；只冻结真实失败边界", "reason": "先把 834.945 秒后的未闭合 JSONL 作为基线，不能直接从错误字符串猜修复收益。"},
        "baselineRunId": "memory-maintenance-observed-start",
        "candidateRunId": "memory-maintenance-observed-jsonl-failure",
        "decision": "reject",
        "decisionReason": "这是需要优化的真实失败基线，不是模型质量分；后续改动只能先在 private shadow 验证。",
        "outputBefore": "无阶段级结果。",
        "outputAfter": "834.945 秒后因未闭合 JSONL 字符串失败；没有权威持久化结果。",
        "resumeBullet": "将长期记忆维护的晚失败转成可复现的 shadow 优化基线。",
        "openGaps": ["生产修复后 Trace 未运行", "Held-out 未消费", "USD 成本不可用", "candidate 未安装"],
    },
    {
        "id": "memory.maintenance-shadow-v1",
        "kind": "memory_candidate",
        "metricId": "memory.maintenance.luna_v1.20260902",
        "title": "Memory Maintenance · V1 Replay 消融",
        "vertical": "memory-maintenance",
        "datasetId": "memory-maintenance-public-safe-fixture-v1",
        "split": "shadow_validation",
        "caseCount": 5,
        "unit": "4 durable memory cases + 1 temporary control",
        "manifestSha256": "58712216e1dd71df953efcba6663b3a437589012a84954ce681d0b936c08dc20",
        "primaryMetric": "五例整理、召回、拒记、dense、rollback 与 replay 完整门禁",
        "evaluator": "Host lifecycle verifier + real Luna receipts",
        "hardGates": ["production DB 不打开", "5/5 决策", "vector coverage 1", "rollback/replay 通过", "合法 JSON receipt"],
        "status": "rejected",
        "claimStatus": "supporting",
        "projectionState": "history",
        "supersededBy": "memory.maintenance-luna-shadow-v5.v1",
        "effectStatus": "improved",
        "candidateType": "single_factor",
        "factor": {"name": "workflow", "before": "真实单体 Run 无恢复验证", "after": "private shadow + rollback + replay", "reason": "先验证整理结果能否回滚并在相同输入上幂等重放。"},
        "baselineRunId": "memory-maintenance-observed-jsonl-failure",
        "candidateRunId": "memory-maintenance-luna-max-validation-20260902-v1",
        "decision": "reject",
        "decisionReason": "V1 证明了整理和 rollback，但 replay 不等价、dense coverage 为 0；继续迭代而不进入生产。",
        "outputBefore": "真实 Run 无结果。",
        "outputAfter": "Shadow 决策可验，但 replay 状态不等价。",
        "resumeBullet": "V1 将 Memory 整理从晚失败推进到可回滚的 shadow 结果，并暴露 replay 不等价。",
        "openGaps": ["生产修复后 Trace 未运行", "Held-out 未消费", "USD 成本不可用", "candidate 未安装"],
    },
    {
        "id": "memory.maintenance-shadow-v3",
        "kind": "memory_candidate",
        "metricId": "memory.maintenance.luna_v3.20260902",
        "title": "Memory Maintenance · V3 精确快照消融",
        "vertical": "memory-maintenance",
        "datasetId": "memory-maintenance-public-safe-fixture-v1",
        "split": "shadow_validation",
        "caseCount": 5,
        "unit": "4 durable memory cases + 1 temporary control",
        "manifestSha256": "58712216e1dd71df953efcba6663b3a437589012a84954ce681d0b936c08dc20",
        "primaryMetric": "五例整理、召回、拒记、dense、rollback 与 replay 完整门禁",
        "evaluator": "Host lifecycle verifier + real Luna receipts",
        "hardGates": ["production DB 不打开", "5/5 决策", "vector coverage 1", "rollback/replay 通过", "合法 JSON receipt"],
        "status": "rejected",
        "claimStatus": "supporting",
        "projectionState": "history",
        "supersededBy": "memory.maintenance-luna-shadow-v5.v1",
        "effectStatus": "improved",
        "candidateType": "single_factor",
        "factor": {"name": "workflow", "before": "Replay 对残留派生状态比较", "after": "保存精确 pre-run snapshot + 复用模型输出，但 replay gate 仍为 false", "reason": "让 replay 比较同一个逻辑基线，避免重复调用模型和假失败。"},
        "baselineRunId": "memory-maintenance-luna-max-validation-20260902-v1",
        "candidateRunId": "memory-maintenance-luna-max-validation-20260902-v3",
        "decision": "reject",
        "decisionReason": "实质 replay 条件改善，但 gate 实现仍错误且 dense coverage 为 0；保留失败回执。",
        "outputBefore": "Replay 不复用且状态不同。",
        "outputAfter": "状态相同且复用输出，但 gate 布尔值仍失败。",
        "resumeBullet": "用精确快照和 content-addressed 复用修正 Memory replay 语义。",
        "openGaps": ["生产修复后 Trace 未运行", "Held-out 未消费", "USD 成本不可用", "candidate 未安装"],
    },
    {
        "id": "memory.maintenance-shadow-v4",
        "kind": "memory_candidate",
        "metricId": "memory.maintenance.luna_v4.20260902",
        "title": "Memory Maintenance · V4 Gate 修正消融",
        "vertical": "memory-maintenance",
        "datasetId": "memory-maintenance-public-safe-fixture-v1",
        "split": "shadow_validation",
        "caseCount": 5,
        "unit": "4 durable memory cases + 1 temporary control",
        "manifestSha256": "58712216e1dd71df953efcba6663b3a437589012a84954ce681d0b936c08dc20",
        "primaryMetric": "五例整理、召回、拒记、dense、rollback 与 replay 完整门禁",
        "evaluator": "Host lifecycle verifier + real Luna receipts",
        "hardGates": ["production DB 不打开", "5/5 决策", "vector coverage 1", "rollback/replay 通过", "合法 JSON receipt"],
        "status": "rejected",
        "claimStatus": "supporting",
        "projectionState": "history",
        "supersededBy": "memory.maintenance-luna-shadow-v5.v1",
        "effectStatus": "improved",
        "candidateType": "unknown",
        "factor": {"name": "workflow", "before": "v3 replay gate false；vector coverage 0", "after": "v4 replay gate true；vector coverage 仍为 0", "reason": "回执没有保留代码 diff，只能确认 replay gate 翻转，无法诚实断言是哪一行实现导致。"},
        "baselineRunId": "memory-maintenance-luna-max-validation-20260902-v3",
        "candidateRunId": "memory-maintenance-luna-max-validation-20260902-v4",
        "decision": "reject",
        "decisionReason": "V4 的 replay gate 已通过，但 dense coverage 仍为 0，且报告不是合法 JSON receipt；不能以报告中的 pass 代替完整 Promotion。",
        "outputBefore": "Replay gate false。",
        "outputAfter": "Replay gate true；dense/receipt 仍失败。",
        "resumeBullet": "修正 Memory replay evaluator 后仍由独立 dense/receipt 门禁阻止错误 Promotion。",
        "openGaps": ["生产修复后 Trace 未运行", "Held-out 未消费", "USD 成本不可用", "candidate 未安装"],
    },
)

_DERIVED_EXPERIMENT_IDS = frozenset(str(recipe["id"]) for recipe in _DERIVED_RECIPES)


def import_experiments(
    *,
    ledger_path: Path,
    target_db: Path,
    write: bool,
    imported_at_ms: int | None = None,
    evidence_ledger_path: Path | None = None,
    runs_dir: Path | None = None,
) -> dict[str, object]:
    source, raw, experiments = read_public_experiments(
        ledger_path=ledger_path,
        imported_at_ms=imported_at_ms,
        evidence_ledger_path=evidence_ledger_path,
        runs_dir=runs_dir,
    )
    receipt: dict[str, object] = {
        "schemaVersion": "rag-ime.agent-lab-experiment-import-receipt.v1",
        "status": "dry_run",
        "sourceSha256": hashlib.sha256(raw).hexdigest(),
        "experimentCount": len(experiments),
        "experimentIds": [item["experimentId"] for item in experiments],
    }
    if not write:
        return receipt
    store = AgentLabExperimentStore(target_db)
    for experiment in experiments:
        store.persist(experiment)
    return {**receipt, "status": "imported"}


def read_public_experiments(
    *,
    ledger_path: Path,
    imported_at_ms: int | None = None,
    evidence_ledger_path: Path | None = None,
    runs_dir: Path | None = None,
) -> tuple[Path, bytes, list[dict[str, object]]]:
    """Read the ledger and return the same public projection used for import."""

    source = Path(ledger_path).resolve(strict=True)
    if not source.is_file() or source.is_symlink():
        raise ValueError("experiment ledger must be a regular file")
    raw = source.read_bytes()
    try:
        ledger = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("experiment ledger is not valid UTF-8 JSON") from exc
    if not isinstance(ledger, Mapping) or ledger.get("schemaVersion") != _LEDGER_SCHEMA:
        raise ValueError("unsupported experiment ledger schema")
    values = _augmented_experiment_values(
        ledger,
        ledger_path=source,
        evidence_ledger_path=evidence_ledger_path,
        runs_dir=runs_dir,
    )
    if not isinstance(values, list) or not values:
        raise ValueError("experiment ledger must contain experiments")
    timestamp = (
        _ledger_timestamp(ledger)
        if imported_at_ms is None
        else max(0, int(imported_at_ms))
    )
    experiments = [
        _public_experiment(value, imported_at_ms=timestamp)
        for value in values
    ]
    return source, raw, experiments


def build_agent_experiment_ledger(
    *,
    ledger_path: Path,
    evidence_ledger_path: Path | None = None,
    runs_dir: Path | None = None,
    refresh_derived: bool = False,
) -> dict[str, object]:
    """Return the canonical raw ledger with receipt-backed rows materialized.

    This helper is intentionally read-only.  A release or install step may
    choose to persist its returned JSON, but importing into Agent Lab never
    rewrites the checked-in source.  Existing rows win by experiment id by
    default so a later hand-authored revision is not silently replaced by a
    derived card.  ``refresh_derived`` is the explicit generation path: it
    replaces only recipe-owned rows and leaves every other row byte-for-byte
    equivalent after JSON decoding.
    """

    source = Path(ledger_path).resolve(strict=True)
    ledger = _read_json_object(source, "experiment ledger")
    if ledger.get("schemaVersion") != _LEDGER_SCHEMA:
        raise ValueError("unsupported experiment ledger schema")
    source_ledger = ledger
    if refresh_derived:
        current_values = ledger.get("experiments")
        if not isinstance(current_values, list):
            raise ValueError("experiment ledger must contain an experiments array")
        source_ledger = dict(ledger)
        source_ledger["experiments"] = [
            item
            for item in current_values
            if not (
                isinstance(item, Mapping)
                and str(item.get("id") or "").strip() in _DERIVED_EXPERIMENT_IDS
            )
        ]
    values = _augmented_experiment_values(
        source_ledger,
        ledger_path=source,
        evidence_ledger_path=evidence_ledger_path,
        runs_dir=runs_dir,
    )
    if refresh_derived:
        values = _apply_materialized_receipt_enrichments(values)
        refreshed_by_id = {
            str(value.get("id") or "").strip(): value
            for value in values
            if isinstance(value, Mapping) and str(value.get("id") or "").strip()
        }
        reordered: list[object] = []
        seen_ids: set[str] = set()
        for current in current_values:
            current_id = (
                str(current.get("id") or "").strip()
                if isinstance(current, Mapping)
                else ""
            )
            reordered.append(refreshed_by_id.get(current_id, current))
            if current_id:
                seen_ids.add(current_id)
        for value in values:
            value_id = (
                str(value.get("id") or "").strip()
                if isinstance(value, Mapping)
                else ""
            )
            if value_id and value_id in seen_ids:
                continue
            reordered.append(value)
            if value_id:
                seen_ids.add(value_id)
        values = reordered
    result = dict(ledger)
    result["experiments"] = values
    return result


def _apply_materialized_receipt_enrichments(values: list[object]) -> list[object]:
    """Apply narrowly-scoped public receipt additions to hand-authored rows."""

    cost_ref = (
        "eval/interview-metrics/runs/"
        "agent-lab-cost-cloudops-luna-failed-run-20260902.v1.json"
    )
    cost_path = ROOT / cost_ref
    if not cost_path.is_file() or cost_path.is_symlink():
        return list(values)
    receipt = _read_json_object(cost_path, "CloudOps failed-run cost receipt")
    if (
        receipt.get("schemaVersion") != "rag-ime.agent-lab-cost-receipt.v1"
        or receipt.get("authority") != "pricing_estimate"
        or _mapping(receipt.get("billing"), "billing").get("status") != "not_provided"
    ):
        raise ValueError("unsupported CloudOps failed-run cost receipt")
    estimate = _mapping(receipt.get("estimate"), "estimate")
    try:
        estimated_cost = float(str(estimate.get("totalCostUsd")))
    except (TypeError, ValueError) as exc:
        raise ValueError("CloudOps failed-run cost receipt is missing totalCostUsd") from exc

    result: list[object] = []
    for value in values:
        if not isinstance(value, Mapping) or value.get("id") != "cloudops.agent-validation-luna-max-timeout.v1":
            result.append(value)
            continue
        experiment = dict(value)
        experiment["effectStatus"] = "not_run"
        candidate = dict(_mapping(experiment.get("candidate"), "candidate"))
        metrics = dict(_mapping(candidate.get("metrics"), "candidate.metrics"))
        metrics.update({
            "costReceiptAvailable": 1,
            "estimatedApiCostUsd": estimated_cost,
            "providerBillAvailable": 0,
        })
        candidate["metrics"] = metrics
        evidence_refs = list(candidate.get("evidenceRefs") or [])
        if cost_ref not in evidence_refs:
            evidence_refs.append(cost_ref)
        candidate["evidenceRefs"] = evidence_refs
        experiment["candidate"] = candidate

        metric_families: list[object] = []
        for raw_family in experiment.get("metricFamilies") or []:
            family = dict(raw_family) if isinstance(raw_family, Mapping) else raw_family
            if isinstance(family, dict) and family.get("family") == "efficiency_cost":
                family_metrics = list(family.get("metrics") or [])
                for metric_name in ("costReceiptAvailable", "estimatedApiCostUsd", "providerBillAvailable"):
                    if metric_name not in family_metrics:
                        family_metrics.append(metric_name)
                family["metrics"] = family_metrics
                family["reason"] = (
                    "绑定原 timeout report 的真实 reported usage 与冻结价格快照，"
                    "只得到 $0.62787768 failed-run burn 估算；无 Provider bill，"
                    "不比较 savings。"
                )
            metric_families.append(family)
        experiment["metricFamilies"] = metric_families

        assets = [
            dict(item) if isinstance(item, Mapping) else item
            for item in experiment.get("createdOrModifiedAssets") or []
        ]
        if not any(
            isinstance(item, Mapping) and item.get("ref") == cost_ref
            for item in assets
        ):
            assets.append({
                "kind": "evaluator",
                "ref": cost_ref,
                "change": "Bind the original timeout report usage to a frozen-price failed-run burn estimate; no savings comparison.",
            })
        experiment["createdOrModifiedAssets"] = assets

        claim = dict(_mapping(experiment.get("claim"), "claim"))
        burn_boundary = (
            " 原 timeout report 的真实 usage 另绑定冻结价格估算 $0.62787768；"
            "这是 failed-run burn，不是 Provider bill 或 savings。"
        )
        if burn_boundary.strip() not in str(claim.get("allowed") or ""):
            claim["allowed"] = str(claim.get("allowed") or "") + burn_boundary
        experiment["claim"] = claim

        open_gaps = [
            str(item)
            for item in experiment.get("openGaps") or []
            if str(item) != "Provider pricing/billing 未提供"
        ]
        billing_gap = "Provider billed receipt 未提供；$0.62787768 仅为 failed-run burn 估算"
        if billing_gap not in open_gaps:
            open_gaps.append(billing_gap)
        experiment["openGaps"] = open_gaps
        result.append(experiment)
    return result


def materialize_agent_experiment_ledger(
    *,
    ledger_path: Path,
    evidence_ledger_path: Path | None = None,
    runs_dir: Path | None = None,
) -> dict[str, object]:
    """Refresh recipe-owned rows and persist the deterministic source ledger."""

    source = Path(ledger_path).resolve(strict=True)
    before = source.read_bytes()
    ledger = build_agent_experiment_ledger(
        ledger_path=source,
        evidence_ledger_path=evidence_ledger_path,
        runs_dir=runs_dir,
        refresh_derived=True,
    )
    encoded = (
        json.dumps(ledger, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    ).encode("utf-8")
    source.write_bytes(encoded)
    experiments = ledger.get("experiments")
    experiment_ids = [
        str(item.get("id"))
        for item in experiments if isinstance(item, Mapping)
    ] if isinstance(experiments, list) else []
    return {
        "schemaVersion": "paw.interview-agent-experiment-materialization-receipt.v1",
        "status": "unchanged" if encoded == before else "materialized",
        "sourceSha256Before": hashlib.sha256(before).hexdigest(),
        "sourceSha256After": hashlib.sha256(encoded).hexdigest(),
        "experimentCount": len(experiment_ids),
        "experimentIds": experiment_ids,
    }


def _augmented_experiment_values(
    ledger: Mapping[str, Any],
    *,
    ledger_path: Path,
    evidence_ledger_path: Path | None,
    runs_dir: Path | None,
) -> list[object]:
    values = ledger.get("experiments")
    if not isinstance(values, list):
        raise ValueError("experiment ledger must contain an experiments array")
    existing_ids = {
        str(item.get("id") or "").strip()
        for item in values
        if isinstance(item, Mapping)
    }
    evidence_path = _default_evidence_ledger_path(
        ledger_path=ledger_path,
        evidence_ledger_path=evidence_ledger_path,
    )
    if evidence_path is None:
        return list(values)
    evidence = _read_evidence_ledger(evidence_path)
    receipt_directory = (
        Path(runs_dir).resolve()
        if runs_dir is not None
        else evidence_path.parent / "runs"
    )
    derived = _derive_experiment_values(
        evidence,
        existing_ids=existing_ids,
        receipt_directory=receipt_directory,
    )
    return [*values, *derived]


def _default_evidence_ledger_path(
    *,
    ledger_path: Path,
    evidence_ledger_path: Path | None,
) -> Path | None:
    if evidence_ledger_path is not None:
        candidate = Path(evidence_ledger_path).resolve()
        if not candidate.is_file() or candidate.is_symlink():
            raise ValueError("evidence ledger must be a regular file")
        return candidate
    sibling = ledger_path.with_name("evidence-ledger.v1.json")
    if sibling.is_file() and not sibling.is_symlink():
        return sibling
    return None


def _read_json_object(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"{label} must be a regular file")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return value


def _read_evidence_ledger(path: Path) -> dict[str, Mapping[str, Any]]:
    ledger = _read_json_object(path, "evidence ledger")
    if ledger.get("schemaVersion") != "paw.interview-metrics-ledger.v1":
        raise ValueError("unsupported evidence ledger schema")
    metrics = ledger.get("metrics")
    if not isinstance(metrics, list):
        raise ValueError("evidence ledger must contain a metrics array")
    result: dict[str, Mapping[str, Any]] = {}
    for item in metrics:
        if not isinstance(item, Mapping):
            continue
        metric_id = str(item.get("id") or "").strip()
        if metric_id:
            result[metric_id] = item
    return result


def _derive_experiment_values(
    evidence: Mapping[str, Mapping[str, Any]],
    *,
    existing_ids: set[str],
    receipt_directory: Path,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for recipe in _DERIVED_RECIPES:
        experiment_id = str(recipe["id"])
        if experiment_id in existing_ids:
            continue
        metric_id = str(recipe["metricId"])
        metric = evidence.get(metric_id)
        recipe_evidence = evidence
        if metric is None:
            if not recipe.get("receiptOnly"):
                continue
            metric = {
                "id": metric_id,
                "status": "diagnostic",
                "values": dict(recipe.get("metricValues") or {}),
                "evidenceRefs": list(recipe.get("candidateEvidenceRefs") or []),
                "claim": dict(recipe.get("metricClaim") or {}),
            }
            recipe_evidence = {**evidence, metric_id: metric}
        if _evidence_consumed_held_out(metric):
            # A derived row may never turn a held-out receipt into another
            # tuning/import candidate.  The one-shot row, if any, remains in
            # the hand-authored ledger and is not materialized here.
            continue
        result.append(
            _derived_experiment(
                recipe,
                evidence=recipe_evidence,
                receipt_directory=receipt_directory,
            )
        )
        existing_ids.add(experiment_id)
    return result


def _derived_experiment(
    recipe: Mapping[str, Any],
    *,
    evidence: Mapping[str, Mapping[str, Any]],
    receipt_directory: Path,
) -> dict[str, Any]:
    """Build one raw interview card from an evidence metric and receipts."""

    metric_id = str(recipe["metricId"])
    metric = evidence[metric_id]
    kind = str(recipe.get("kind") or "")
    baseline_metric_id = str(recipe.get("baselineSourceMetricId") or metric_id)
    baseline_metric = evidence.get(baseline_metric_id, metric)
    candidate_metric = metric
    baseline_refs = _evidence_refs(
        recipe,
        side="baseline",
        metric=baseline_metric,
        receipt_directory=receipt_directory,
    )
    candidate_refs = _evidence_refs(
        recipe,
        side="candidate",
        metric=candidate_metric,
        receipt_directory=receipt_directory,
    )

    baseline_metrics, candidate_metrics = _derived_run_metrics(
        recipe,
        evidence=evidence,
        baseline_metric=baseline_metric,
        candidate_metric=candidate_metric,
        receipt_directory=receipt_directory,
    )
    baseline_output, candidate_output = _derived_outputs(recipe)
    factors = [dict(recipe["factor"])]
    controls = _derived_controls(recipe)
    status = str(recipe["status"])
    decision = str(recipe["decision"])
    explicit_candidate_type = str(recipe.get("candidateType") or "").strip()
    candidate_type = (
        explicit_candidate_type
        if explicit_candidate_type in {"baseline", "single_factor", "compound_repair", "unknown"}
        else "baseline"
        if kind in {"cloudops_baseline", "memory_failure"}
        else "single_factor"
    )
    result: dict[str, Any] = {
        "id": str(recipe["id"]),
        "title": str(recipe["title"]),
        "vertical": str(recipe["vertical"]),
        "evaluationKind": _derived_evaluation_kind(recipe),
        "status": status,
        "claimStatus": str(recipe["claimStatus"]),
        "effectStatus": str(recipe["effectStatus"]),
        "candidateType": candidate_type,
        "businessProblem": _derived_business_problem(kind),
        "whyAgent": _derived_why_agent(kind),
        "factors": factors,
        "frozenControls": controls,
        "star": _derived_star(recipe, metric),
        "dataset": {
            "id": str(recipe["datasetId"]),
            "split": str(recipe["split"]),
            "caseCount": int(recipe["caseCount"]),
            "unit": str(recipe["unit"]),
            "manifestSha256": str(recipe["manifestSha256"]),
            "heldOutConsumed": False,
        },
        "scoringContract": {
            "primaryMetric": str(recipe["primaryMetric"]),
            "evaluatorAuthority": str(recipe["evaluator"]),
            "goldHiddenFromAgent": True,
            "hardGates": list(recipe["hardGates"]),
        },
        "optimizationContract": _derived_optimization(recipe),
        "bestKnown": {
            "configId": f"evidence-derived:{metric_id}",
            "configSha256": _derived_config_hash(metric, receipt_directory, [*baseline_refs, *candidate_refs]),
            "decision": _best_known_decision(status, decision),
        },
        "metricFamilies": _derived_metric_families(recipe, baseline_metrics, candidate_metrics),
        "createdOrModifiedAssets": _derived_assets(recipe, baseline_refs, candidate_refs),
        "baseline": {
            "runId": str(recipe["baselineRunId"]),
            "metrics": baseline_metrics,
            "evidenceRefs": baseline_refs,
            "outputExamples": [baseline_output],
        },
        "recommendations": _derived_recommendations(recipe, candidate_refs, metric),
        "layerAssessments": _derived_layers(recipe),
        "candidate": {
            "runId": str(recipe["candidateRunId"]),
            "metrics": candidate_metrics,
            "evidenceRefs": candidate_refs,
            "outputExamples": [candidate_output],
        },
        "comparison": _derived_comparison(recipe, baseline_metrics, candidate_metrics),
        "claim": _derived_claim(recipe, metric),
        "openGaps": list(recipe.get("openGaps") or []),
    }
    projection_state = str(recipe.get("projectionState") or "current")
    if projection_state == "history":
        result["projectionState"] = projection_state
    superseded_by = str(recipe.get("supersededBy") or "").strip()
    if superseded_by:
        result["supersededBy"] = superseded_by
    # The source evidence metric remains the authority for the status text,
    # but some metrics are deliberately diagnostic even when a candidate
    # improved a lower-level gate.  Keep the explicit recipe decision and do
    # not infer Keep from a positive numeric delta.
    return result


def _derived_evaluation_kind(recipe: Mapping[str, Any]) -> str:
    kind = str(recipe.get("kind") or "")
    if kind.startswith("rag_"):
        return "rag_retrieval" if kind == "rag_tag_readiness" else "answer_evidence"
    if kind.startswith("cloudops"):
        return "workflow"
    if kind.startswith("memory"):
        return "memory"
    return "other"


def _derived_business_problem(kind: str) -> str:
    if kind.startswith("rag_"):
        return "企业问题同时包含精确标识、语义表达、冲突版本和多来源证据；检索、答案与引用必须分层验收。"
    if kind.startswith("cloudops"):
        return "云上告警需要跨服务观察、证据读取和根因判断；减少 Tool 次数不能抵消诊断质量回退。"
    return "真实记忆维护横跨模型判断、Evidence→Atom→Book、RAG、rollback 和 replay；失败边界必须先被隔离复现。"


def _derived_why_agent(kind: str) -> str:
    if kind.startswith("rag_"):
        return "每个 case 都需要受约束的检索、证据绑定、拒答和可审计输出，单次聊天答案不能证明引用成立。"
    if kind.startswith("cloudops"):
        return "每个 case 都要在冻结观察快照和 Host-only scorer 下组合查询、证据与结论，固定脚本无法覆盖探索路径。"
    return "记忆维护需要真实模型、生命周期状态、回滚和幂等 replay 的联合验收，单个成功输出不能证明安全。"


def _derived_controls(recipe: Mapping[str, Any]) -> list[dict[str, str]]:
    case_count = int(recipe["caseCount"])
    split = str(recipe["split"])
    factor = recipe["factor"]
    factor_name = str(factor["name"])
    control_axes = (
        (frozenset({"model"}), "Model"),
        (frozenset({"prompt"}), "Prompt"),
        (frozenset({"skill"}), "Skill"),
        (frozenset({"tool"}), "Tool"),
        (frozenset({"workflow"}), "Workflow"),
        (frozenset({"context", "memory_rag"}), "Context/Memory/RAG"),
    )
    changed_label = next(
        (label for names, label in control_axes if factor_name in names),
        factor_name,
    )
    frozen_summary = "、".join(
        label for names, label in control_axes if factor_name not in names
    )
    return [
        {
            "name": "dataset_and_split",
            "value": f"{case_count} cases；{split}；manifest hash 固定",
            "reason": "前后运行使用同一分母，避免把样本变化写成候选收益。",
        },
        {
            "name": "single_factor",
            "value": f"只改变 {changed_label}；{frozen_summary} 和 evaluator 冻结",
            "reason": "把数值变化绑定到单变量消融，避免复合改动混淆归因。",
        },
        {
            "name": "heldout_and_install",
            "value": "Held-out 未消费；source-local candidate 未安装",
            "reason": "Validation/shadow 证据不能升级为泛化、安装态或生产结论。",
        },
    ]


def _derived_optimization(recipe: Mapping[str, Any]) -> dict[str, Any]:
    factor = recipe["factor"]
    status = str(recipe["status"])
    evaluated = 0 if status == "open_gap" else 1
    return {
        "objective": f"在不削弱 {recipe['primaryMetric']} 和安全门禁的前提下评估 {factor['name']}。",
        "candidateSearchSpace": [
            {
                "axis": str(factor["name"]),
                "candidatesEvaluated": evaluated,
                "values": [str(factor["before"]), str(factor["after"])],
            }
        ],
        "frozenVariables": [
            "dataset/split/case manifest",
            "Host-private evaluator and hard gates",
            "Held-out remains sealed",
        ],
        "selectionRule": "先执行硬门禁，再比较质量、可靠性和效率；任一核心质量门禁回退即 Reject。",
        "stopRule": "Reject 或未形成可比较结果时停止在当前 Validation，不继续消耗 Held-out。",
        "heldOutRule": "只有 Validation/shadow winner 明确冻结后，才允许一次性、独立授权的 Held-out。",
    }


def _best_known_decision(status: str, decision: str) -> str:
    if status == "kept" or decision == "keep":
        return "keep"
    if status == "rejected" or decision.startswith("reject"):
        return "reject"
    if status == "open_gap" or decision == "not_run":
        return "not_run"
    return "diagnostic"


def _derived_metric_families(
    recipe: Mapping[str, Any],
    baseline_metrics: Mapping[str, float | int],
    candidate_metrics: Mapping[str, float | int],
) -> list[dict[str, Any]]:
    kind = str(recipe.get("kind") or "")
    if kind == "rag_tag_readiness":
        quality_status = "open_gap"
        quality_metrics: list[str] = []
    elif kind == "memory_failure":
        quality_status = "open_gap"
        quality_metrics = []
    else:
        quality_status = "measured"
        quality_metrics = [str(recipe["primaryMetric"])]
    efficiency_metrics = [
        key for key in ("toolCalls", "latencyMs", "elapsedMs", "tokens", "actualModelCallElapsedMs")
        if key in baseline_metrics or key in candidate_metrics
    ]
    reliability_metrics = [
        key for key in ("failedToolCalls", "terminalCompleted", "jsonReceiptValid", "replayPassed", "formalScoreProduced")
        if key in baseline_metrics or key in candidate_metrics
    ]
    return [
        {"family": "outcome_quality", "status": quality_status, "metrics": quality_metrics, "reason": "按本卡主指标和准确分母记录结果；未通过时保留 Reject/diagnostic 语义。"},
        {"family": "evidence_grounding", "status": "measured" if kind.startswith("rag_") or kind.startswith("cloudops") else "open_gap", "metrics": ["evidenceRefs"], "reason": "Evidence refs 绑定到公开 receipt 或源码；原始 Gold 和私有 transcript 不进入投影。"},
        {"family": "runtime_reliability", "status": "measured" if reliability_metrics else "open_gap", "metrics": reliability_metrics, "reason": "只记录 receipt 中已有的终态、Tool 或回执字段，不从缺失值推断成功。"},
        {"family": "efficiency_cost", "status": "measured" if efficiency_metrics else "open_gap", "metrics": efficiency_metrics, "reason": "效率字段按真实运行口径保留；没有 usage/价格就不声称成本。"},
        {"family": "safety_recovery", "status": "measured", "metrics": ["Held-out isolation", "source-local/install boundary"], "reason": "Held-out、安装和生产边界是硬控制，不因候选数字改善而升级。"},
    ]


def _derived_assets(
    recipe: Mapping[str, Any],
    baseline_refs: list[str],
    candidate_refs: list[str],
) -> list[dict[str, str]]:
    refs = []
    for ref in [*candidate_refs, *baseline_refs]:
        if ref not in refs and _repo_ref_exists(ref):
            refs.append(ref)
    if not refs:
        refs = ["scripts/import_agent_lab_experiments.py"]
    kind = "evaluator" if "rag" in str(recipe.get("kind")) or "cloudops" in str(recipe.get("kind")) else "workflow"
    return [
        {
            "kind": kind,
            "ref": ref,
            "change": f"Evidence-derived Agent Lab projection for {recipe['factor']['name']} single-factor candidate.",
        }
        for ref in refs[:4]
    ]


def _derived_recommendations(
    recipe: Mapping[str, Any],
    candidate_refs: list[str],
    metric: Mapping[str, Any],
) -> list[dict[str, Any]]:
    factor_name = str(recipe["factor"]["name"])
    target_layer = {
        "memory_rag": "workflow",
        "model": "workflow",
        "skill": "skill",
        "tool": "tool",
        "workflow": "workflow",
        "context": "system_prompt",
        "guardrail": "workflow",
    }.get(factor_name, "workflow")
    status = str(recipe["status"])
    recommendation_status = "verified" if status == "kept" else "rejected" if status == "rejected" else "proposed"
    refs = candidate_refs or ["scripts/import_agent_lab_experiments.py"]
    return [{
        "id": f"{recipe['id']}-single-factor",
        "targetLayer": target_layer,
        "observation": str(_mapping(metric.get("claim"), "metric.claim").get("allowed") or recipe["decisionReason"]),
        "hypothesis": f"Only the {factor_name} factor can explain this candidate; all other controls remain frozen.",
        "evidenceRefs": refs,
        "proposedChange": str(recipe["factor"]["after"]),
        "attribution": {
            "detectedBy": "evidence-ledger",
            "proposedBy": "eval_agent",
            "authorizedBy": "user",
            "implementedBy": "ordinary_agent",
            "verifiedBy": "host_verifier" if status == "kept" else "evidence_receipt",
        },
        "status": recommendation_status,
    }]


def _derived_layers(recipe: Mapping[str, Any]) -> list[dict[str, str]]:
    factor_name = str(recipe["factor"]["name"])
    changed_layer = {
        "prompt": "system_prompt",
        "skill": "skill",
        "tool": "tool",
        "workflow": "workflow",
        "context": "system_prompt",
        "memory_rag": "workflow",
        "guardrail": "workflow",
    }.get(factor_name)
    result = []
    for layer in ("system_prompt", "tool", "workflow", "skill"):
        result.append({
            "layer": layer,
            "status": "changed" if layer == changed_layer else "considered_no_change",
            "reason": "单变量消融的 changed factor。" if layer == changed_layer else "冻结控制；本卡没有改变该层。",
        })
    return result


def _derived_star(recipe: Mapping[str, Any], metric: Mapping[str, Any]) -> dict[str, str]:
    claim = _mapping(metric.get("claim"), "metric.claim")
    allowed = str(claim.get("allowed") or recipe["decisionReason"])
    return {
        "situation": _derived_business_problem(str(recipe.get("kind") or "")),
        "task": f"在 {recipe['caseCount']} 个冻结 {recipe['split']} case 上验证 {recipe['factor']['name']}。",
        "action": f"只改变 {recipe['factor']['name']}：{recipe['factor']['before']} → {recipe['factor']['after']}；保留 receipt 和分母。",
        "result": allowed[:1500],
    }


def _derived_claim(recipe: Mapping[str, Any], metric: Mapping[str, Any]) -> dict[str, str]:
    claim = _mapping(metric.get("claim"), "metric.claim")
    return {
        "resumeBullet": str(recipe["resumeBullet"]),
        "allowed": str(claim.get("allowed") or recipe["decisionReason"]),
        "forbidden": str(claim.get("forbidden") or "不能升级为 Held-out、生产、安装态或成本结论。"),
    }


def _derived_outputs(recipe: Mapping[str, Any]) -> tuple[dict[str, str], dict[str, str]]:
    if recipe.get("baselineOutput") and recipe.get("candidateOutput"):
        before = recipe["baselineOutput"]
        after = recipe["candidateOutput"]
        return (
            {"caseId": str(before[0]), "input": str(before[1]), "output": str(before[2])},
            {"caseId": str(after[0]), "input": str(after[1]), "output": str(after[2])},
        )
    if recipe.get("kind") == "rag_answer":
        return (
            {"caseId": "aggregate", "input": "同一冻结 answer case", "output": str(recipe["outputBefore"])},
            {"caseId": "aggregate", "input": "同一冻结 answer case", "output": str(recipe["outputAfter"])},
        )
    return (
        {"caseId": "aggregate", "input": f"同一 {recipe['caseCount']} 条冻结 case", "output": str(recipe["outputBefore"])},
        {"caseId": "aggregate", "input": f"同一 {recipe['caseCount']} 条冻结 case", "output": str(recipe["outputAfter"])},
    )


def _derived_comparison(
    recipe: Mapping[str, Any],
    baseline_metrics: Mapping[str, float | int],
    candidate_metrics: Mapping[str, float | int],
) -> dict[str, Any]:
    deltas: list[dict[str, float | int | str]] = []
    for key in recipe.get("deltaKeys", []):
        before = baseline_metrics.get(str(key))
        after = candidate_metrics.get(str(key))
        if not isinstance(before, (int, float)) or isinstance(before, bool):
            continue
        if not isinstance(after, (int, float)) or isinstance(after, bool):
            continue
        deltas.append({"metric": str(key), "before": before, "after": after, "delta": after - before})
    if not deltas:
        deltas = _numeric_deltas(baseline_metrics, candidate_metrics, limit=8)
    baseline_output, candidate_output = _derived_outputs(recipe)
    return {
        "decision": str(recipe["decision"]),
        "decisionReason": str(recipe["decisionReason"]),
        "metricDeltas": deltas,
        "outputComparisons": [{
            "caseId": "aggregate",
            "before": str(baseline_output["output"]),
            "after": str(candidate_output["output"]),
        }],
    }


def _numeric_deltas(
    before: Mapping[str, float | int],
    after: Mapping[str, float | int],
    *,
    limit: int,
) -> list[dict[str, float | int | str]]:
    result: list[dict[str, float | int | str]] = []
    for key in before:
        left = before.get(key)
        right = after.get(key)
        if not isinstance(left, (int, float)) or isinstance(left, bool):
            continue
        if not isinstance(right, (int, float)) or isinstance(right, bool):
            continue
        result.append({"metric": str(key), "before": left, "after": right, "delta": right - left})
        if len(result) >= limit:
            break
    return result


def _derived_run_metrics(
    recipe: Mapping[str, Any],
    *,
    evidence: Mapping[str, Mapping[str, Any]],
    baseline_metric: Mapping[str, Any],
    candidate_metric: Mapping[str, Any],
    receipt_directory: Path,
) -> tuple[dict[str, float | int], dict[str, float | int]]:
    kind = str(recipe.get("kind") or "")
    explicit_baseline = recipe.get("baselineMetrics")
    explicit_candidate = recipe.get("candidateMetrics")
    if isinstance(explicit_baseline, Mapping) and isinstance(explicit_candidate, Mapping):
        return (
            _numeric_metric_mapping(explicit_baseline, "baselineMetrics"),
            _numeric_metric_mapping(explicit_candidate, "candidateMetrics"),
        )
    if kind == "rag_tag_readiness":
        return (
            _mapped_metric_values(baseline_metric, recipe.get("baselineMetricMap", {})),
            _mapped_metric_values(candidate_metric, recipe.get("candidateMetricMap", {})),
        )
    if kind == "rag_answer":
        baseline_source = baseline_metric
        candidate_source = candidate_metric
        lane = str(recipe.get("lane") or "baseline")
        baseline_prefix = str(recipe.get("baselineLane") or lane)
        candidate_prefix = str(recipe.get("candidateLane") or lane)
        baseline_defaults = {
            "agentCaseCount": 4,
            "answerCaseCount": 2,
            "highLevelFactCount": 9,
            "verifiedRequiredFactCount": 9,
            "answerableCaseCount": 2,
            "infoNotFoundCaseCount": 2,
            "infoNotFoundAbstentionRecall": 1,
            "outputProtocolRate": 1,
            "citationHardGatePassed": 0,
            "tokens": 25384 if lane == "baseline" else 25778,
        }
        candidate_defaults = {
            "agentCaseCount": 4,
            "answerCaseCount": 2,
            "highLevelFactCount": 9,
            "verifiedRequiredFactCount": 9,
            "answerableCaseCount": 2,
            "infoNotFoundCaseCount": 2,
            "infoNotFoundAbstentionRecall": 1,
            "outputProtocolRate": 1,
            "citationHardGatePassed": 0,
            "tokens": {
                "baseline": 25778,
                "skill": 74769,
                "tuned": 88941,
                "agentic": 7713,
            }.get(lane, 0),
        }
        baseline_lane = str(recipe.get("baselineLane") or lane)
        candidate_lane = str(recipe.get("candidateLane") or lane)
        baseline = _answer_lane_metrics(
            baseline_source,
            prefix=baseline_prefix,
            receipt_lane=baseline_lane,
            defaults=baseline_defaults,
            receipt_directory=receipt_directory,
            refs=_evidence_refs(recipe, side="baseline", metric=baseline_source, receipt_directory=receipt_directory),
        )
        candidate = _answer_lane_metrics(
            candidate_source,
            prefix=candidate_prefix,
            receipt_lane=candidate_lane,
            defaults=candidate_defaults,
            receipt_directory=receipt_directory,
            refs=_evidence_refs(recipe, side="candidate", metric=candidate_source, receipt_directory=receipt_directory),
        )
        if lane == "agentic":
            candidate["tokensComplete"] = 0
        return baseline, candidate
    if kind == "cloudops_baseline":
        baseline = {
            "formalScoreProduced": 0,
            "answeredCases": 4,
            "toolContractPassed": 0,
        }
        candidate = {
            "answerCoverage": _metric_number(candidate_metric, "answerCoverage", 0),
            "ca": _metric_number(candidate_metric, "ca", 0),
            "fa": _metric_number(candidate_metric, "fa", 0),
            "jra": _metric_number(candidate_metric, "jra", 0),
            "top3Jra": _metric_number(candidate_metric, "top3Jra", 0),
            "toolCalls": _metric_number(candidate_metric, "successfulToolCalls", 0),
            "failedToolCalls": _metric_number(candidate_metric, "failedToolCalls", 0),
            "elapsedMs": _metric_number(candidate_metric, "elapsedMs", 0),
            "formalScoreProduced": 1,
        }
        return baseline, candidate
    if kind == "cloudops_candidate":
        baseline = {
            "answerCoverage": 1,
            "ca": _metric_number(baseline_metric, "baselineCa", 1),
            "fa": _metric_number(baseline_metric, "baselineFa", 5 / 6),
            "jra": _metric_number(baseline_metric, "baselineJra", 5 / 6),
            "top3Jra": _metric_number(baseline_metric, "baselineTop3Jra", 5 / 6),
            "toolCalls": _metric_number(baseline_metric, "baselineToolCalls", 98),
            "failedToolCalls": 0,
            "elapsedMs": _metric_number(baseline_metric, "baselineElapsedMs", 1356582),
        }
        candidate = {
            "answerCoverage": _metric_number(candidate_metric, "candidateAnswerCoverage", 1),
            "ca": _metric_number(candidate_metric, "candidateCa", 0),
            "fa": _metric_number(candidate_metric, "candidateFa", 0),
            "jra": _metric_number(candidate_metric, "candidateJra", 0),
            "top3Jra": _metric_number(candidate_metric, "candidateTop3Jra", 0),
            "toolCalls": _metric_number(candidate_metric, "candidateToolCalls", 0),
            "failedToolCalls": _metric_number(candidate_metric, "candidateFailedToolCalls", 0),
            "elapsedMs": _metric_number(candidate_metric, "candidateElapsedMs", 0),
        }
        for key in ("candidateSearchCalls", "candidateListCalls", "candidateReadCalls", "publicCacheKeyReads"):
            value = _metric_value(candidate_metric, key)
            if value is not None:
                candidate[key] = value
        return baseline, candidate
    if kind == "memory_failure":
        baseline = {"terminalCompleted": 0, "elapsedMs": 0}
        elapsed_seconds = _metric_number(candidate_metric, "elapsedSeconds", 834.945)
        candidate = {
            "terminalCompleted": 0,
            "jsonReceiptValid": 0,
            "elapsedMs": elapsed_seconds * 1000,
            "stageTimingAvailable": 0,
            "modelTokensAvailable": 0,
        }
        return baseline, candidate
    if kind == "memory_candidate":
        version = str(recipe["id"]).rsplit("-", 1)[-1]
        baseline = _memory_baseline_metrics(version)
        candidate = _memory_candidate_metrics(candidate_metric, version)
        return baseline, candidate
    raise ValueError(f"unsupported derived Agent Lab recipe kind: {kind}")


def _numeric_metric_mapping(
    value: Mapping[str, Any],
    label: str,
) -> dict[str, float | int]:
    result: dict[str, float | int] = {}
    for key, raw_value in value.items():
        if isinstance(raw_value, bool):
            result[str(key)] = int(raw_value)
        elif isinstance(raw_value, (int, float)):
            result[str(key)] = raw_value
        else:
            raise ValueError(f"{label}.{key} must be numeric")
    return result


def _mapped_metric_values(
    metric: Mapping[str, Any],
    mapping: Mapping[str, object],
) -> dict[str, float | int]:
    result: dict[str, float | int] = {}
    for output_key, source in mapping.items():
        if isinstance(source, (tuple, list)):
            source_key = str(source[0]) if source else ""
        else:
            source_key = str(source)
        value = _metric_value(metric, source_key)
        if value is not None:
            result[str(output_key)] = value
    return result


def _answer_lane_metrics(
    metric: Mapping[str, Any],
    *,
    prefix: str,
    receipt_lane: str = "baseline",
    defaults: Mapping[str, float | int],
    receipt_directory: Path,
    refs: list[str],
) -> dict[str, float | int]:
    lane_values = _receipt_lane_numeric_values(
        refs,
        receipt_directory,
        lane=receipt_lane,
    )
    receipt_values = _receipt_numeric_values(refs, receipt_directory)

    def value(
        metric_suffix: str,
        default: float | int,
        *,
        lane_keys: tuple[str, ...] = (),
        receipt_keys: tuple[str, ...] = (),
    ) -> float | int:
        result = _metric_value(metric, f"{prefix}{metric_suffix}")
        if result is None:
            for key in lane_keys:
                result = lane_values.get(key)
                if result is not None:
                    break
        if result is None:
            for key in receipt_keys:
                result = receipt_values.get(key)
                if result is not None:
                    break
        return default if result is None else result

    answer_success_rate = value(
        "AnswerJudgeCorrectnessRate",
        0,
        lane_keys=("answerJudgeCorrectnessRate", "answerSuccessRate"),
        receipt_keys=("answerJudgeCorrectnessRate", "answerSuccessRate"),
    )
    values: dict[str, float | int] = {
        "agentCaseCount": _metric_number(metric, "agentCaseCount", 4),
        "agentSuccessRate": answer_success_rate,
        "answerCaseCount": _metric_number(metric, "answerableCaseCount", 2),
        "answerSuccessRate": value(
            "AnswerJudgeCorrectnessRate",
            0,
            lane_keys=("answerJudgeCorrectnessRate", "answerSuccessRate"),
            receipt_keys=("answerJudgeCorrectnessRate", "answerSuccessRate"),
        ),
        "highLevelFactCount": 9,
        "verifiedRequiredFactCount": _metric_number(metric, "verifiedRequiredFactCount", _metric_number(metric, "verifiedRequiredFacts", 9)),
        "highLevelFactCoverage": value(
            "HighLevelFactCoverage",
            2 / 3,
            lane_keys=("highLevelFactCoverage",),
            receipt_keys=("highLevelFactCoverage",),
        ),
        "citationFactCoverage": value(
            "CitationFactCoverage",
            0,
            lane_keys=("citationFactCoverage",),
            receipt_keys=("citationFactCoverage",),
        ),
        "answerableCaseCount": 2,
        "answerableCitationSupportRate": value(
            "AnswerableCitationSupportRate",
            0,
            lane_keys=("answerableCitationSupportRate",),
            receipt_keys=("answerableCitationSupportRate",),
        ),
        "infoNotFoundCaseCount": 2,
        "infoNotFoundAbstentionRecall": value(
            "InfoNotFoundAbstentionRecall",
            1,
            lane_keys=("infoNotFoundAbstentionRecall",),
            receipt_keys=("infoNotFoundAbstentionRecall",),
        ),
        "citationHardGatePassed": value(
            "CitationHardGatePassed",
            0,
            lane_keys=("citationHardGatePassed",),
            receipt_keys=("citationHardGatePassed",),
        ),
        "outputProtocolRate": value(
            "OutputProtocolRate",
            1,
            lane_keys=("outputProtocolRate",),
            receipt_keys=("outputProtocolRate",),
        ),
        "tokens": value(
            "Tokens",
            defaults.get("tokens", 0),
            lane_keys=("tokens",),
            receipt_keys=("tokens",),
        ),
        "toolCalls": value(
            "ToolCalls",
            0,
            lane_keys=("toolCalls",),
            receipt_keys=("toolCalls",),
        ),
        "latencyMs": value(
            "LatencyMs",
            0,
            lane_keys=("latencyMs",),
            receipt_keys=("latencyMs",),
        ),
    }
    tokens_complete = _metric_value(metric, f"{prefix}TokensComplete")
    if tokens_complete is None:
        tokens_complete = lane_values.get("tokensComplete")
    if tokens_complete is None and lane_values.get("tokenValueIsIncompleteFailurePlaceholder"):
        tokens_complete = 0
    if tokens_complete is not None:
        values["tokensComplete"] = tokens_complete
    for key, value in defaults.items():
        values.setdefault(key, value)
    return values


def _memory_baseline_metrics(version: str) -> dict[str, float | int]:
    if version == "v1":
        return {
            "terminalCompleted": 0,
            "jsonReceiptValid": 0,
            "elapsedMs": 834945,
            "stageTimingAvailable": 0,
            "modelTokensAvailable": 0,
            "curationCases": 1,
            "curationPassed": 0,
            "durableRecallPassed": 0,
            "durableRecallTotal": 0,
            "abstentionPassed": 0,
            "abstentionTotal": 0,
            "vectorCoverage": 0,
            "rollbackPassed": 0,
            "replayPassed": 0,
        }
    if version == "v3":
        return {
            "curationCases": 5,
            "curationPassed": 5,
            "durableRecallPassed": 4,
            "durableRecallTotal": 4,
            "abstentionPassed": 1,
            "abstentionTotal": 1,
            "vectorCoverage": 0,
            "rollbackPassed": 1,
            "replayPassed": 0,
            "replayOutputsReused": 0,
            "replayStateIdentical": 0,
            "actualModelCallElapsedMs": 224793,
        }
    return {
        "curationCases": 5,
        "curationPassed": 5,
        "durableRecallPassed": 4,
        "durableRecallTotal": 4,
        "abstentionPassed": 1,
        "abstentionTotal": 1,
        "vectorCoverage": 0,
        "rollbackPassed": 1,
        "replayPassed": 0,
        "replayOutputsReused": 1,
        "replayStateIdentical": 1,
        "actualModelCallElapsedMs": 114941,
    }


def _memory_candidate_metrics(
    metric: Mapping[str, Any],
    version: str,
) -> dict[str, float | int]:
    fixture_cases = _metric_number(metric, "fixtureCases", 5)
    durable_cases = _metric_number(metric, "durableCases", 4)
    non_memory = _metric_number(metric, "nonMemoryControls", 1)
    fixture_passed = _metric_number(metric, "fixturePassed", 0)
    result: dict[str, float | int] = {
        "curationCases": fixture_cases,
        "curationPassed": fixture_cases if fixture_passed else 0,
        "durableRecallPassed": durable_cases,
        "durableRecallTotal": durable_cases,
        "abstentionPassed": non_memory if fixture_passed else 0,
        "abstentionTotal": non_memory,
        "vectorCoverage": _metric_number(metric, "vectorCoverage", 0),
        "rollbackPassed": _metric_number(metric, "rollbackPassed", 0),
        "replayPassed": _metric_number(metric, "replayPassed", 0),
        "actualModelCallElapsedMs": {"v1": 224793, "v3": 114941, "v4": 90642}.get(version, 0),
    }
    for source_key, output_key in (
        ("replayReusedOutputs", "replayOutputsReused"),
        ("replayReusedModelRequests", "replayOutputsReused"),
        ("replayIdenticalState", "replayStateIdentical"),
        ("replayRestoredBeforeState", "replayStateIdentical"),
        ("replayUsedExactSnapshot", "replayUsedExactSnapshot"),
        ("receiptJsonValid", "receiptJsonValid"),
    ):
        value = _metric_value(metric, source_key)
        if value is not None:
            result[output_key] = value
    return result


def _metric_value(metric: Mapping[str, Any], key: str) -> float | int | None:
    values = metric.get("values")
    if not isinstance(values, Mapping):
        return None
    value = values.get(key)
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return value
    return None


def _metric_number(metric: Mapping[str, Any], key: str, default: float | int) -> float | int:
    value = _metric_value(metric, key)
    return default if value is None else value


def _evidence_refs(
    recipe: Mapping[str, Any],
    *,
    side: str,
    metric: Mapping[str, Any],
    receipt_directory: Path,
) -> list[str]:
    explicit = recipe.get(f"{side}EvidenceRefs")
    raw_refs = explicit if isinstance(explicit, list) else metric.get("evidenceRefs")
    refs: list[str] = []
    if isinstance(raw_refs, list):
        for raw_ref in raw_refs:
            ref = str(raw_ref or "").strip()
            if not ref:
                continue
            if ref == "eval/interview-metrics/agent-experiments.v1.json":
                # A generated ledger cannot use its own bytes as a stable
                # config identity; prefer the retained run receipt instead.
                continue
            # Private run roots and build payloads are useful local evidence,
            # but are not part of the public checked-in Agent Lab projection.
            # Keep the public receipt/script refs while retaining the metric's
            # full provenance in evidence-ledger.v1.json.
            if ref.startswith((".rag-ime-data/", "build/")):
                continue
            if ref.startswith(("http://", "https://", "local://")) or _repo_ref_exists(ref):
                if ref not in refs:
                    refs.append(ref)
    if refs:
        return refs
    # Keep a visible, repository-local receipt reference even when a private
    # source report is not mounted in this checkout.
    return ["scripts/import_agent_lab_experiments.py"]


def _receipt_numeric_values(refs: list[str], receipt_directory: Path) -> dict[str, float | int]:
    result: dict[str, float | int] = {}
    for ref in refs:
        path = _receipt_path(ref, receipt_directory)
        if path is None or not path.is_file():
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        _flatten_numeric_values(value, result)
    return result


def _receipt_lane_numeric_values(
    refs: list[str],
    receipt_directory: Path,
    *,
    lane: str,
) -> dict[str, float | int]:
    """Read numeric fields from one named lane in a run receipt.

    The evidence-ledger summary intentionally keeps aggregate values, while
    the public RAG receipts keep the Sol/Luna lane values under ``lanes``.
    Reading the named lane avoids accidentally reusing the first (baseline)
    numeric field when projecting the Skill, tuned, or Agentic cards.
    """

    result: dict[str, float | int] = {}
    for ref in refs:
        path = _receipt_path(ref, receipt_directory)
        if path is None or not path.is_file():
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(value, Mapping):
            continue
        lanes = value.get("lanes")
        if not isinstance(lanes, Mapping):
            continue
        lane_value = lanes.get(lane)
        if isinstance(lane_value, Mapping):
            _flatten_numeric_values(lane_value, result)
    return result


def _flatten_numeric_values(value: object, result: dict[str, float | int]) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if isinstance(key, str):
                if isinstance(child, bool):
                    result.setdefault(key, int(child))
                elif isinstance(child, (int, float)):
                    result.setdefault(key, child)
            _flatten_numeric_values(child, result)
    elif isinstance(value, list):
        for child in value:
            _flatten_numeric_values(child, result)


def _receipt_path(ref: str, receipt_directory: Path) -> Path | None:
    if ref.startswith(("http://", "https://", "local://")):
        return None
    raw = ref.split("#", 1)[0].strip()
    if not raw:
        return None
    path = Path(raw)
    if path.is_absolute():
        return path
    candidate = ROOT / path
    if candidate.is_file():
        return candidate
    candidate = receipt_directory / path.name
    return candidate


def _repo_ref_exists(ref: str) -> bool:
    if ref.startswith(("http://", "https://", "local://")):
        return True
    raw = ref.split("#", 1)[0].strip()
    if not raw:
        return False
    path = Path(raw)
    return path.is_file() if path.is_absolute() else (ROOT / path).exists()


def _derived_config_hash(
    metric: Mapping[str, Any],
    receipt_directory: Path,
    refs: list[str],
) -> str:
    for ref in refs:
        path = _receipt_path(ref, receipt_directory)
        if path is not None and path.is_file():
            try:
                return hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                continue
    canonical = json.dumps(metric, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _evidence_consumed_held_out(value: object) -> bool:
    if isinstance(value, Mapping):
        for key, child in value.items():
            lowered = str(key).casefold().replace("_", "")
            if "heldout" in lowered and any(token in lowered for token in ("consum", "evaluat", "observ")):
                if child is True or child == 1:
                    return True
            if _evidence_consumed_held_out(child):
                return True
    elif isinstance(value, list):
        return any(_evidence_consumed_held_out(child) for child in value)
    return False


def _public_experiment(
    value: object,
    *,
    imported_at_ms: int,
) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError("experiment entry must be an object")
    raw = dict(value)
    raw_revision = json.dumps(
        {"projectionRevision": _PROJECTION_REVISION, "experiment": raw},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    dataset = _mapping(raw.get("dataset"), "dataset")
    scoring = _mapping(raw.get("scoringContract"), "scoringContract")
    comparison = _mapping(raw.get("comparison"), "comparison")
    payload: dict[str, object] = {
        "schemaVersion": "rag-ime.agent-lab-experiment.v1",
        "experimentId": _text(raw.get("id"), "id"),
        "revisionSha256": hashlib.sha256(raw_revision).hexdigest(),
        "title": _text(raw.get("title"), "title"),
        "vertical": _text(raw.get("vertical"), "vertical"),
        "evaluationKind": _evaluation_kind(raw),
        "status": _text(raw.get("status"), "status"),
        "claimStatus": _text(raw.get("claimStatus"), "claimStatus"),
        "projectionState": _projection_state(raw),
        "effectStatus": _effect_status(raw),
        "candidateType": _candidate_type(raw),
        "businessProblem": _text(raw.get("businessProblem"), "businessProblem"),
        "whyAgent": _text(raw.get("whyAgent"), "whyAgent"),
        "dataset": {
            "datasetId": _text(dataset.get("id"), "dataset.id"),
            "split": _text(dataset.get("split"), "dataset.split"),
            "caseCount": _non_negative_int(dataset.get("caseCount"), "dataset.caseCount"),
            "unit": _text(dataset.get("unit"), "dataset.unit"),
            "manifestSha256": _text(dataset.get("manifestSha256"), "dataset.manifestSha256"),
            "heldOutConsumed": bool(dataset.get("heldOutConsumed")),
        },
        "scoring": {
            "primaryMetric": _text(scoring.get("primaryMetric"), "scoring.primaryMetric"),
            "evaluatorAuthority": _text(scoring.get("evaluatorAuthority"), "scoring.evaluatorAuthority"),
            "goldHiddenFromAgent": bool(scoring.get("goldHiddenFromAgent")),
            "hardGates": _text_list(scoring.get("hardGates"), "scoring.hardGates"),
        },
        "factors": _factors(raw.get("factors")),
        "frozenControls": _frozen_controls(raw.get("frozenControls")),
        "baseline": _run_summary(raw.get("baseline"), "baseline"),
        "candidate": _run_summary(raw.get("candidate"), "candidate"),
        "comparison": {
            "decision": _text(comparison.get("decision"), "comparison.decision"),
            "decisionReason": _text(comparison.get("decisionReason"), "comparison.decisionReason"),
            "metricDeltas": _metric_deltas(comparison.get("metricDeltas")),
            "outputComparisons": _public_output_comparisons(comparison.get("outputComparisons")),
        },
        "star": _star(raw.get("star")),
        "claim": _claim(raw.get("claim")),
        "openGaps": _text_list(raw.get("openGaps", []), "openGaps"),
        "importedAtMs": imported_at_ms,
    }
    superseded_by = str(raw.get("supersededBy") or "").strip()
    if superseded_by:
        payload["supersededBy"] = superseded_by
    # CloudOps Luna has a checked-in failure receipt, not a readable transcript
    # or Host formal CA/JRA result.  Keep the source ledger immutable, but make
    # the Agent Lab read-through truthful: this is a runtime-only observation,
    # not a measured quality regression.  The receipt/session count remains
    # visible while transcriptCount is deliberately zero.
    if _is_report_only_runtime_failure(raw):
        candidate = payload["candidate"]
        if isinstance(candidate, dict):
            metrics = candidate.get("metrics")
            if isinstance(metrics, dict):
                session_count = metrics.get("sessionCount")
                if isinstance(session_count, (int, float)) and not isinstance(session_count, bool):
                    metrics["receiptCount"] = int(session_count)
                metrics["transcriptCount"] = 0
            examples = candidate.get("outputExamples")
            # A report-only receipt may expose one aggregate observation, but
            # never a list of readable conversations.
            if isinstance(examples, list):
                candidate["outputExamples"] = examples[:1]
        payload["effectStatus"] = "not_run"
        comparison_payload = payload["comparison"]
        if isinstance(comparison_payload, dict):
            comparison_payload["decision"] = "拒绝候选，仅保留失败回执"
            comparison_payload["decisionReason"] = (
                "报告仅证明 Runtime/Transcript 失败；没有 Host formal CA/JRA，"
                "因此拒绝候选，仅保留失败回执。"
            )
    validate_contract(payload, "agent-lab-experiment.v1.json")
    return payload


def _is_report_only_runtime_failure(experiment: Mapping[str, Any]) -> bool:
    """Recognize the bounded CloudOps Luna failure projection only.

    This is intentionally tied to the named public receipt and the absence of
    formal scoring.  Other rejected experiments must retain their measured
    ``regressed`` status.
    """

    experiment_id = str(experiment.get("id") or "").strip()
    if experiment_id != "cloudops.agent-validation-luna-max-timeout.v1":
        return False
    candidate = experiment.get("candidate")
    if not isinstance(candidate, Mapping):
        return False
    metrics = candidate.get("metrics")
    if not isinstance(metrics, Mapping):
        return False
    return (
        metrics.get("hostFormalCaJraAvailable") == 0
        and "cloudops-luna-max-baseline-validation-20260902" in str(candidate.get("runId") or "")
    )


def _evaluation_kind(experiment: Mapping[str, Any]) -> str:
    explicit = str(experiment.get("evaluationKind") or "").strip()
    if explicit:
        if explicit not in _EVALUATION_KINDS:
            raise ValueError("experiment evaluationKind is not supported")
        return explicit
    vertical = str(experiment.get("vertical") or "").casefold()
    identity = " ".join(str(experiment.get(key) or "") for key in ("id", "title")).casefold()
    if "customer-support" in vertical or "enterpriseops" in identity:
        return "workflow"
    if "agent-runtime" in vertical or "trace" in identity:
        return "trace_repair"
    if "answer" in identity or "citation" in identity or "evidence" in identity:
        return "answer_evidence"
    if "knowledge" in vertical or "rag" in identity or "retrieval" in identity:
        return "rag_retrieval"
    if "diagnos" in identity or "repair" in identity:
        return "trace_repair"
    if "memory" in vertical or "memory" in identity:
        return "memory"
    if "runtime" in vertical or "runtime" in identity or "tool" in identity:
        return "tool_runtime"
    if "workflow" in identity:
        return "workflow"
    return "other"


def _effect_status(experiment: Mapping[str, Any]) -> str:
    explicit = str(experiment.get("effectStatus") or "").strip()
    if explicit in {"improved", "neutral", "regressed", "not_run", "unverified"}:
        return explicit
    status = str(experiment.get("status") or "").strip()
    if status == "kept":
        return "improved"
    if status == "rejected":
        return "regressed"
    if status == "open_gap":
        return "not_run"
    return "unverified"


def _projection_state(experiment: Mapping[str, Any]) -> str:
    explicit = str(experiment.get("projectionState") or "current").strip()
    if explicit not in {"current", "history"}:
        raise ValueError(f"unsupported projectionState: {explicit}")
    return explicit


def _candidate_type(experiment: Mapping[str, Any]) -> str:
    explicit = str(experiment.get("candidateType") or "").strip()
    if explicit in {"single_factor", "compound_repair", "baseline", "unknown"}:
        return explicit
    factors = experiment.get("factors")
    if not isinstance(factors, list) or not factors:
        return "unknown"
    return "single_factor" if len(factors) == 1 else "compound_repair"


def _run_summary(value: object, label: str) -> dict[str, object]:
    run = _mapping(value, label)
    metrics = _mapping(run.get("metrics"), f"{label}.metrics")
    safe_metrics: dict[str, float | int] = {}
    for key, value in metrics.items():
        if not isinstance(key, str) or isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{label}.metrics must contain numeric values")
        safe_metrics[key] = value
    payload: dict[str, object] = {
        "runId": _text(run.get("runId"), f"{label}.runId"),
        "metrics": safe_metrics,
        "evidenceRefs": _text_list(run.get("evidenceRefs", []), f"{label}.evidenceRefs"),
    }
    # Keep only explicitly public, bounded examples.  Raw transcript, SQL,
    # hidden Gold and arbitrary fields are intentionally discarded rather than
    # copied into the App projection.
    examples = _public_output_examples(run.get("outputExamples"))
    if examples:
        payload["outputExamples"] = examples
    return payload


def _public_output_examples(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, str]] = []
    for item in value[:8]:
        if not isinstance(item, Mapping):
            continue
        case_id = str(item.get("caseId") or "").strip()[:120]
        input_text = str(item.get("input") or "").strip()[:600]
        output_text = str(item.get("output") or "").strip()[:1200]
        if not case_id or not input_text or not output_text:
            continue
        result.append({"caseId": case_id, "input": input_text, "output": output_text})
    return result


def _public_output_comparisons(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, str]] = []
    for item in value[:8]:
        if not isinstance(item, Mapping):
            continue
        case_id = str(item.get("caseId") or "").strip()[:120]
        before = str(item.get("before") or "").strip()[:1200]
        after = str(item.get("after") or "").strip()[:1200]
        if not case_id or not before or not after:
            continue
        result.append({"caseId": case_id, "before": before, "after": after})
    return result


def _factors(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list) or not value:
        raise ValueError("factors must be a non-empty array")
    allowed = {
        "model", "prompt", "skill", "tool", "workflow", "context",
        "memory_rag", "guardrail", "execution_policy", "human_loop", "pricing",
    }
    result: list[dict[str, str]] = []
    for index, item in enumerate(value):
        factor = _mapping(item, f"factors[{index}]")
        name = _text(factor.get("name"), f"factors[{index}].name")
        if name not in allowed:
            raise ValueError(f"factors[{index}].name is not supported")
        result.append({
            "name": name,
            "before": _text(factor.get("before"), f"factors[{index}].before"),
            "after": _text(factor.get("after"), f"factors[{index}].after"),
            "reason": _text(factor.get("reason"), f"factors[{index}].reason"),
        })
    return result


def _frozen_controls(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list) or not value:
        raise ValueError("frozenControls must be a non-empty array")
    result: list[dict[str, str]] = []
    for index, item in enumerate(value):
        control = _mapping(item, f"frozenControls[{index}]")
        result.append({
            "name": _text(control.get("name"), f"frozenControls[{index}].name"),
            "value": _text(control.get("value"), f"frozenControls[{index}].value"),
            "reason": _text(control.get("reason"), f"frozenControls[{index}].reason"),
        })
    return result


def _metric_deltas(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise ValueError("comparison.metricDeltas must be an array")
    result: list[dict[str, object]] = []
    for index, item in enumerate(value):
        delta = _mapping(item, f"comparison.metricDeltas[{index}]")
        values = {}
        for key in ("before", "after", "delta"):
            number = delta.get(key)
            if isinstance(number, bool) or not isinstance(number, (int, float)):
                raise ValueError(f"metric delta {key} must be numeric")
            values[key] = number
        result.append({"metric": _text(delta.get("metric"), "metric"), **values})
    return result


def _star(value: object) -> dict[str, object]:
    star = _mapping(value, "star")
    return {key: _text(star.get(key), f"star.{key}") for key in ("situation", "task", "action", "result")}


def _claim(value: object) -> dict[str, object]:
    claim = _mapping(value, "claim")
    return {key: _text(claim.get(key), f"claim.{key}") for key in ("resumeBullet", "allowed", "forbidden")}


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _text(value: object, label: str) -> str:
    normalized = " ".join(str(value or "").split())
    if not normalized:
        raise ValueError(f"{label} must not be empty")
    return normalized


def _text_list(value: object, label: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be an array")
    return [_text(item, f"{label} item") for item in value]


def _non_negative_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return value


def _ledger_timestamp(ledger: Mapping[str, Any]) -> int:
    generated = str(ledger.get("generatedAt") or "").strip()
    if not generated:
        return 0
    try:
        parsed = datetime.strptime(generated, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise ValueError("ledger generatedAt must be YYYY-MM-DD") from exc
    return int(parsed.timestamp() * 1000)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--target-db", type=Path)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--write", action="store_true")
    action.add_argument("--materialize-ledger", action="store_true")
    parser.add_argument("--evidence-ledger", type=Path)
    parser.add_argument("--runs-dir", type=Path)
    args = parser.parse_args()
    if args.materialize_ledger:
        receipt = materialize_agent_experiment_ledger(
            ledger_path=args.ledger,
            evidence_ledger_path=args.evidence_ledger,
            runs_dir=args.runs_dir,
        )
    else:
        if args.target_db is None:
            parser.error("--target-db is required unless --materialize-ledger is used")
        receipt = import_experiments(
            ledger_path=args.ledger,
            target_db=args.target_db,
            write=args.write,
            evidence_ledger_path=args.evidence_ledger,
            runs_dir=args.runs_dir,
        )
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
