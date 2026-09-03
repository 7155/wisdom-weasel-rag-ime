import auditStyles from '@/features/trace-agent/engineering-audit-report.css?raw';
import auditTemplate from '@/features/trace-agent/templates/engineering-audit-report.html?raw';
import type { AgentLabExperimentV1 } from '@/contracts/generated/agent-lab-experiment.v1';

type EvalLabExperiment = AgentLabExperimentV1;

export type EvalLabAuditEvidenceRelation = 'baseline' | 'candidate' | 'related';

/** Public, bounded evidence metadata. Raw transcripts and Tool arguments do not belong here. */
export interface EvalLabAuditEvidenceSummary {
  runId: string;
  relation?: EvalLabAuditEvidenceRelation;
  title?: string;
  status?: string;
  evidenceKind?: string;
  summary?: string;
  refs?: readonly string[];
  osOrigin?: string;
}

/** A caller-owned Trace digest. The exporter never reads a live/private Trace itself. */
export interface EvalLabAuditTraceSummary {
  traceId: string;
  status?: string;
  summary: string;
  evidenceRefs?: readonly string[];
}

export interface EvalLabExperimentAuditSources {
  osOrigin?: string;
  evidence?: readonly EvalLabAuditEvidenceSummary[];
  traces?: readonly EvalLabAuditTraceSummary[];
}

export interface EvalLabExperimentAuditHtmlOptions {
  generatedAtMs?: number;
}

export interface EvalLabExperimentAuditDownload {
  blob: Blob;
  download: string;
  href: string;
  revoke(): void;
}

const TEMPLATE_FIELDS = ['__TRACE_AUDIT_TITLE__', '__TRACE_AUDIT_CSS__', '__TRACE_AUDIT_BODY__'] as const;

/** Build one self-contained, public-safe engineering audit for an Agent Lab experiment. */
export function buildEvalLabExperimentAuditHtml(
  experiment: EvalLabExperiment,
  sources: EvalLabExperimentAuditSources = {},
  { generatedAtMs = Date.now() }: EvalLabExperimentAuditHtmlOptions = {},
): string {
  assertTemplateContract();
  const title = `${reportTitle(experiment)} · Agent Lab 评测报告`;
  return auditTemplate
    .replace('__TRACE_AUDIT_TITLE__', escapeHtml(title))
    .replace('__TRACE_AUDIT_CSS__', `${auditStyles}\n${EVAL_LAB_AUDIT_STYLES}`)
    .replace('__TRACE_AUDIT_BODY__', renderAudit(experiment, sources, generatedAtMs));
}

export function buildEvalLabExperimentAuditBlob(
  experiment: EvalLabExperiment,
  sources: EvalLabExperimentAuditSources = {},
  options: EvalLabExperimentAuditHtmlOptions = {},
): Blob {
  return new Blob(
    [buildEvalLabExperimentAuditHtml(experiment, sources, options)],
    { type: 'text/html;charset=utf-8' },
  );
}

/** Create the href/download pair expected by an anchor; the caller must call revoke on disposal. */
export function createEvalLabExperimentAuditDownload(
  experiment: EvalLabExperiment,
  sources: EvalLabExperimentAuditSources = {},
  options: EvalLabExperimentAuditHtmlOptions = {},
): EvalLabExperimentAuditDownload {
  if (typeof URL.createObjectURL !== 'function') {
    throw new Error('当前环境不支持 Agent Lab HTML 下载。');
  }
  const blob = buildEvalLabExperimentAuditBlob(experiment, sources, options);
  const href = URL.createObjectURL(blob);
  let revoked = false;
  return {
    blob,
    download: `agent-lab-audit-${safeFilenamePart(experiment.experimentId)}.html`,
    href,
    revoke() {
      if (revoked) return;
      revoked = true;
      URL.revokeObjectURL(href);
    },
  };
}

function renderAudit(
  experiment: EvalLabExperiment,
  sources: EvalLabExperimentAuditSources,
  generatedAtMs: number,
): string {
  const evidence = sources.evidence ?? [];
  const traces = sources.traces ?? [];
  const osOrigin = sources.osOrigin?.trim()
    || evidence.find((item) => item.osOrigin?.trim())?.osOrigin?.trim()
    || 'PAWOS · Agent Lab（未提供更细 origin）';
  const traceBoundary = traces.length
    ? `${traces.length} 条运行轨迹（Trace）摘要可供核验。`
    : '本次导出没有包含逐步运行轨迹，只能核验实验账本与公开运行回执。';
  const decision = decisionLabel(experiment);
  const metricRows = buildMetricRows(experiment);
  const dataset = datasetExplanation(experiment);

  return `<main class="trace-audit trace-audit--export eval-lab-audit" data-status="${attr(experiment.status)}">
  <header class="trace-audit__masthead"><div class="trace-audit__identity"><p class="trace-audit__document-type">Agent Lab · 单轮评测报告</p><h1>${escapeHtml(reportTitle(experiment))}</h1><p class="trace-audit__lede">说明这轮实验为什么改、具体改了什么、结果如何，以及最终是否采用。</p></div><dl class="trace-audit__document-meta">${meta('实验 ID', experiment.experimentId, true)}${meta('状态', statusLabel(experiment.status))}${meta('处置结论', decision)}${meta('报告来源', reportHumanText(osOrigin))}</dl></header>
  <div class="trace-audit__scan-layer">
    ${renderSummary(experiment, decision, traceBoundary)}
    ${section('metrics', '结果对比', '基线方案与候选方案使用同一批题和同一验收方法。', renderMetrics(metricRows))}
    ${section('change', '变更说明', '说明问题、改动内容及对照实验中保持不变的条件。', renderChanges(experiment))}
    ${section('findings', '检查结论', '区分已经由回执确认的结果与仍需验证的风险。', renderFindings(experiment, traceBoundary))}
    ${section('gates', '验收标准', '候选方案必须满足全部质量与安全条件。', renderGates(experiment))}
    ${section('dataset', '评测方法与数据', '说明样本来源、金标准、评分方式和适用范围。', renderDataset(experiment, dataset))}
    ${section('evidence', '证据索引', traceBoundary, renderEvidence(experiment, evidence, traces))}
  </div>
  <footer class="trace-audit__provenance"><div><strong>实验修订</strong><span>${escapeHtml(experiment.revisionSha256)}</span></div><div><strong>数据清单哈希</strong><span>${escapeHtml(experiment.dataset.manifestSha256)}</span></div><div><strong>来源</strong><span>${escapeHtml(reportHumanText(osOrigin))}</span></div><div><strong>生成时间</strong><span>${escapeHtml(formatTimestamp(generatedAtMs))}</span></div><p>此导出只包含 Agent Lab 账本与调用方提供的公开证据摘要；不读取私有推理、原始工具参数、模型上下文或最终盲测内容。</p></footer>
</main>`;
}

type DatasetStory = { source: string; preparation: string; gold: string; agentContract: string; boundary: string };

function reportTitle(experiment: EvalLabExperiment): string {
  const identity = `${experiment.experimentId} ${experiment.title} ${experiment.vertical}`.toLowerCase();
  if (identity.includes('execution-chain')) return '企业客户支持 · 执行链修复';
  if (identity.includes('state-contract')) return '企业客户支持 · 状态合同工作流';
  if (identity.includes('model-cost') || identity.includes('sol versus luna')) return '企业客户支持 · 低成本模型对照';
  if (identity.includes('enterprise-rag') && experiment.evaluationKind === 'answer_evidence') return '企业知识库问答 · 答案与引用验证';
  if (identity.includes('enterprise-rag') || identity.includes('knowledge')) return '企业知识库问答 · 检索方案对照';
  if (identity.includes('cloudops')) return '云上事故诊断 · 工作流对照';
  if (identity.includes('memory')) return '长期记忆整理 · 维护流程对照';
  if (identity.includes('enterpriseops')) return '企业客户支持 · 工作流优化';
  return reportHumanText(experiment.title);
}

function reportHumanText(value: string): string {
  return value.trim()
    .replace(/^可表述为[:：]?\s*/u, '本轮证据支持：')
    .replace(/^可以说[:：]?\s*/u, '本轮证据支持：')
    .replace(/^不能表述为[:：]?\s*/u, '本轮证据不支持：')
    .replace(/^不能说[:：]?\s*/u, '本轮证据不支持：')
    .replace(/synthetic preview/giu, '演示数据')
    .replace(/source-local candidate/giu, '隔离实验中的候选方案')
    .replace(/source-local/giu, '隔离源码环境')
    .replace(/report-only/giu, '仅有报告')
    .replace(/\bbaseline\b/giu, '原方案')
    .replace(/\bcandidate\b/giu, '新方案')
    .replace(/\bproduction\b/giu, '生产环境')
    .replace(/\bPrompt\b/gu, '提示词')
    .replace(/\bSkill\b/gu, '技能说明')
    .replace(/Tool Gateway/gu, '工具网关')
    .replace(/Tool transport/giu, '工具连接')
    .replace(/business Tool/giu, '业务工具')
    .replace(/\bTool\b/gu, '工具')
    .replace(/\bVerifier\b/giu, '自动验收')
    .replace(/\bHost\b/gu, '独立评测程序')
    .replace(/\bValidation\b/gu, '调优数据')
    .replace(/\bHeld-out\b/giu, '最终盲测')
    .replace(/\bPromotion\b/gu, '正式晋级')
    .replace(/\bRuntime\b/gu, '运行环境')
    .replace(/\btranscript\b/giu, '对话记录')
    .replace(/\bauthority\b/giu, '授权')
    .replace(/fail-closed cleanup/giu, '失败时强制清理');
}

function summaryChange(experiment: EvalLabExperiment): string {
  if (!experiment.factors.length) return reportHumanText(experiment.star.action || '本轮没有记录具体改动。');
  if (experiment.factors.length === 1) {
    const factor = experiment.factors[0]!;
    return `只调整${factorLabel(factor.name)}：${reportHumanText(factor.before)} → ${reportHumanText(factor.after)}`;
  }
  return `联合调整${experiment.factors.map((factor) => factorLabel(factor.name)).join('、')}；详细前后差异见“变更说明”。`;
}

function datasetScope(experiment: EvalLabExperiment): string {
  if (experiment.dataset.split === 'held-out') return `一次性最终盲测，共 ${experiment.dataset.caseCount} 个任务；结果已经冻结。`;
  if (experiment.dataset.split === 'validation') return `仅代表本轮 ${experiment.dataset.caseCount} 个调优任务，不等于生产环境表现。`;
  if (experiment.dataset.split === 'shadow_validation') return `仅代表 ${experiment.dataset.caseCount} 个隔离影子任务，没有改动生产数据。`;
  return `仅代表本轮 ${experiment.dataset.caseCount} 个${splitLabel(experiment.dataset.split)}任务。`;
}

function renderSummary(experiment: EvalLabExperiment, decision: string, traceBoundary: string): string {
  return `<section class="trace-audit__tldr eval-lab-audit__summary" aria-labelledby="eval-lab-audit-summary"><header class="eval-lab-audit__summary-decision" data-status="${attr(experiment.status)}"><span>执行摘要</span><h2 id="eval-lab-audit-summary">${escapeHtml(decision)}</h2><p>${escapeHtml(reportHumanText(experiment.comparison.decisionReason))}</p></header><dl class="eval-lab-audit__summary-list">${meta('本轮变更', summaryChange(experiment))}${meta('核心结果', reportHumanText(experiment.star.result))}${meta('结果范围', datasetScope(experiment))}${meta('证据状态', traceBoundary)}</dl></section>`;
}

function renderDataset(experiment: EvalLabExperiment, story: DatasetStory): string {
  return `<dl class="eval-lab-audit__dataset-story">${meta('原始数据', story.source)}${meta('怎样处理', story.preparation)}${meta('金标准', story.gold)}${meta('Agent 必须遵守', story.agentContract)}${meta('能说明什么', story.boundary)}${meta('技术索引', `${experiment.dataset.datasetId} · ${experiment.dataset.caseCount} ${experiment.dataset.unit}`, true)}</dl>`;
}

function renderFindings(experiment: EvalLabExperiment, traceBoundary: string): string {
  const gaps = experiment.openGaps.length ? experiment.openGaps.map(reportHumanText).join('；') : '没有记录待补事项。';
  const frozenFacts = `本轮固定 ${experiment.dataset.caseCount} 个任务、${experiment.factors.length} 个改动层和 ${experiment.frozenControls.length} 项控制条件。`;
  return `<div class="eval-lab-audit__finding-grid">
    ${finding('confirmed', '已确认', '这轮已经证明什么', `${reportHumanText(experiment.claim.allowed)} ${frozenFacts}`)}
    ${finding('attention', '待验证', '哪些结论还不能下', `${reportHumanText(experiment.claim.forbidden)} ${gaps} ${traceBoundary}`)}
  </div>`;
}

function renderChanges(experiment: EvalLabExperiment): string {
  const factors = experiment.factors.length
    ? experiment.factors.map((factor) => `<article><header><strong>${escapeHtml(factorLabel(factor.name))}</strong><span>${escapeHtml(reportHumanText(factor.reason))}</span></header><div><section><h3>原来</h3><p>${escapeHtml(reportHumanText(factor.before))}</p></section><section><h3>改成</h3><p>${escapeHtml(reportHumanText(factor.after))}</p></section></div></article>`).join('')
    : '<p class="trace-audit__empty">账本没有记录具体改动。</p>';
  const controls = experiment.frozenControls.length
    ? `<ul>${experiment.frozenControls.map((control) => `<li><strong>${escapeHtml(controlLabel(control.name))}</strong> · ${escapeHtml(reportHumanText(control.value))}<small>${escapeHtml(reportHumanText(control.reason))}</small></li>`).join('')}</ul>`
    : '<p class="trace-audit__empty">账本没有记录冻结控制。</p>';
  return `<div class="trace-audit__knowledge-columns"><section><h3>为什么这样改</h3><p>${escapeHtml(reportHumanText(experiment.businessProblem))}</p><p>${escapeHtml(reportHumanText(experiment.whyAgent))}</p><dl class="eval-lab-audit__dataset">${meta('原始问题', reportHumanText(experiment.star.situation))}${meta('优化目标', reportHumanText(experiment.star.task))}${meta('实验方式', candidateTypeLabel(experiment.candidateType))}</dl><h3 class="eval-lab-audit__change-heading">具体怎么改</h3><div class="eval-lab-audit__changes">${factors}</div></section><section><h3>对照条件</h3>${controls}<dl class="eval-lab-audit__dataset">${meta('数据集 ID', experiment.dataset.datasetId, true)}${meta('评测阶段', splitLabel(experiment.dataset.split))}${meta('任务数量', String(experiment.dataset.caseCount))}${meta('数据清单哈希', experiment.dataset.manifestSha256, true)}</dl></section></div>`;
}

type MetricRow = { metric: string; before?: number; after?: number; delta?: number };

const METRIC_DISPLAY_ORDER = [
  'taskSuccessRate', 'taskSuccessCount', 'taskPassed', 'verifierPassRate', 'verifierPassCount', 'verifierPassed',
  'agentSuccessRate', 'answerSuccessRate', 'highLevelFactCoverage', 'answerableCitationSupportRate',
  'infoNotFoundAbstentionRecall', 'citationFactCoverage', 'recallAt10', 'recall_at_10', 'mrr', 'ndcgAt10', 'ndcg_at_10',
  'ca', 'jra', 'top3Jra', 'answerCoverage', 'outputProtocolRate', 'vectorCoverage',
  'failedToolCalls', 'allDatabasesCleaned', 'temporaryDatabasesDeleted', 'databasesCleaned',
  'apiCostUsd', 'estimatedApiCostUsd', 'costReceiptAvailable', 'totalTokens', 'tokens', 'providerCalls',
  'latencyMs', 'elapsedMs', 'actualModelCallElapsedMs', 'toolCalls', 'businessToolCalls',
] as const;

const METRIC_DISPLAY_PRIORITY = new Map<string, number>(METRIC_DISPLAY_ORDER.map((metric, index) => [metric, index]));

const METRIC_ALIASES: Readonly<Record<string, string>> = {
  task_success_rate: 'taskSuccessRate',
  task_success_count: 'taskSuccessCount',
  task_passed: 'taskPassed',
  task_total: 'taskTotal',
  verifier_pass_rate: 'verifierPassRate',
  verifier_pass_count: 'verifierPassCount',
  verifier_passed: 'verifierPassed',
  verifier_total: 'verifierTotal',
  business_tool_calls: 'businessToolCalls',
  tool_calls: 'toolCalls',
  failed_tool_calls: 'failedToolCalls',
  latency_ms: 'latencyMs',
  elapsed_ms: 'elapsedMs',
  actual_model_call_elapsed_ms: 'actualModelCallElapsedMs',
  api_cost_usd: 'apiCostUsd',
  estimated_api_cost_usd: 'estimatedApiCostUsd',
  recall_at_10: 'recallAt10',
  ndcg_at_10: 'ndcgAt10',
};

function canonicalMetricName(metric: string): string {
  return METRIC_ALIASES[metric] ?? metric;
}

function metricValue(metrics: Readonly<Record<string, number>>, canonicalMetric: string): number | undefined {
  const direct = metrics[canonicalMetric];
  if (direct !== undefined) return direct;
  const alias = Object.entries(metrics).find(([metric]) => canonicalMetricName(metric) === canonicalMetric);
  return alias?.[1];
}

function buildMetricRows(experiment: EvalLabExperiment): MetricRow[] {
  const recordedDeltas = new Map(experiment.comparison.metricDeltas.map((item) => {
    const metric = canonicalMetricName(item.metric);
    return [metric, { ...item, metric }] as const;
  }));
  const metrics = new Set([
    ...Object.keys(experiment.baseline.metrics).map(canonicalMetricName),
    ...Object.keys(experiment.candidate.metrics).map(canonicalMetricName),
    ...recordedDeltas.keys(),
  ]);
  return [...metrics].sort((left, right) => {
    const leftPriority = METRIC_DISPLAY_PRIORITY.get(left) ?? Number.MAX_SAFE_INTEGER;
    const rightPriority = METRIC_DISPLAY_PRIORITY.get(right) ?? Number.MAX_SAFE_INTEGER;
    return leftPriority - rightPriority || left.localeCompare(right);
  }).map((metric) => {
    const recorded = recordedDeltas.get(metric);
    const before = recorded?.before ?? metricValue(experiment.baseline.metrics, metric);
    const after = recorded?.after ?? metricValue(experiment.candidate.metrics, metric);
    return {
      metric,
      ...(before === undefined ? {} : { before }),
      ...(after === undefined ? {} : { after }),
      ...(recorded ? { delta: recorded.delta } : before === undefined || after === undefined ? {} : { delta: after - before }),
    };
  });
}

function renderMetrics(rows: readonly MetricRow[]): string {
  if (!rows.length) return '<p class="trace-audit__empty">没有可展示的前后指标。</p>';
  return `<div class="trace-audit__comparison-table-wrap"><table><thead><tr><th>指标</th><th>原方案</th><th>新方案</th><th>结果变化</th></tr></thead><tbody>${rows.map((row) => `<tr><th scope="row">${escapeHtml(metricLabel(row.metric))}</th><td>${formatMetricByName(row.metric, row.before)}</td><td>${formatMetricByName(row.metric, row.after)}</td><td>${formatMetricChange(row)}</td></tr>`).join('')}</tbody></table></div>`;
}

function renderGates(experiment: EvalLabExperiment): string {
  if (!experiment.scoring.hardGates.length) return '<p class="trace-audit__empty">未记录硬门禁。</p>';
  return `<div class="trace-audit__gates">${experiment.scoring.hardGates.map((gate, index) => `<article data-status="contract"><strong>底线 ${index + 1}</strong><span>必须满足</span><p>${escapeHtml(reportHumanText(gate))}</p><small>以外部验收或运行回执判定</small></article>`).join('')}</div><dl class="eval-lab-audit__dataset">${meta('主要指标', metricLabel(experiment.scoring.primaryMetric))}${meta('谁来判定', reportHumanText(experiment.scoring.evaluatorAuthority))}${meta('标准答案', experiment.scoring.goldHiddenFromAgent ? '对 Agent 隐藏' : '对 Agent 可见')}</dl>`;
}

function renderEvidence(
  experiment: EvalLabExperiment,
  evidence: readonly EvalLabAuditEvidenceSummary[],
  traces: readonly EvalLabAuditTraceSummary[],
): string {
  const ledgerEvidence = [
    evidenceEntry('原方案', experiment.baseline.runId, experiment.baseline.evidenceRefs),
    evidenceEntry('新方案', experiment.candidate.runId, experiment.candidate.evidenceRefs),
  ].join('');
  const suppliedEvidence = evidence.map((item) => `<article data-relation="${attr(item.relation ?? 'related')}"><header><strong>${escapeHtml(reportHumanText(item.title || item.runId))}</strong><span>${escapeHtml(evidenceRelationLabel(item.relation))} · ${escapeHtml(evidenceStatusLabel(item.status))} · ${escapeHtml(evidenceKindLabel(item.evidenceKind))}</span></header><p>${escapeHtml(reportHumanText(item.summary || '调用方未提供公开摘要。'))}</p>${refs(item.refs ?? [])}</article>`).join('');
  const traceEvidence = traces.length
    ? traces.map((trace) => `<article data-relation="trace"><header><strong>${escapeHtml(trace.traceId)}</strong><span>运行轨迹（Trace） · ${escapeHtml(evidenceStatusLabel(trace.status))}</span></header><p>${escapeHtml(reportHumanText(trace.summary))}</p>${refs(trace.evidenceRefs ?? [])}</article>`).join('')
    : '<article class="eval-lab-audit__report-only" data-relation="report-only"><header><strong>历史记录只有报告</strong><span>逐步运行轨迹缺失</span></header><p>没有可用 Trace 摘要；本报告只保留账本与公开回执位置，不补写逐轮行为。</p></article>';
  return `<div class="eval-lab-audit__evidence">${ledgerEvidence}${suppliedEvidence}${traceEvidence}</div>`;
}

function evidenceEntry(label: string, runId: string, evidenceRefs: readonly string[]): string {
  return `<article data-relation="${label.toLowerCase()}"><header><strong>${escapeHtml(label)} · ${escapeHtml(runId || '运行 ID 未记录')}</strong><span>账本证据引用</span></header>${refs(evidenceRefs)}</article>`;
}

function evidenceRelationLabel(relation: EvalLabAuditEvidenceRelation | undefined): string {
  if (relation === 'baseline') return '原方案';
  if (relation === 'candidate') return '新方案';
  return '相关证据';
}

function evidenceStatusLabel(status: string | undefined): string {
  if (!status) return '状态未知';
  if (status === 'completed') return '已完成';
  if (status === 'failed') return '失败';
  if (status === 'cancelled' || status === 'aborted') return '已停止';
  return reportHumanText(status);
}

function evidenceKindLabel(kind: string | undefined): string {
  if (!kind) return '证据摘要';
  if (kind === 'transcript_and_report') return '对话与报告';
  if (kind === 'report_only') return '仅有报告';
  if (kind === 'transcript') return '对话记录';
  return reportHumanText(kind.replaceAll('_', ' '));
}

function section(id: string, title: string, description: string, body: string): string {
  const headingId = `eval-lab-audit-${id}`;
  return `<section class="trace-audit__section eval-lab-audit__section eval-lab-audit__section--${attr(id)}" aria-labelledby="${headingId}"><header class="trace-audit__section-heading"><h2 id="${headingId}">${escapeHtml(title)}</h2><p>${escapeHtml(description)}</p></header>${body}</section>`;
}

function finding(tone: 'confirmed' | 'attention', label: string, title: string, text: string): string {
  return `<article class="eval-lab-audit__finding" data-finding-tone="${tone}"><span>${label}</span><h3>${escapeHtml(title)}</h3><p>${escapeHtml(text)}</p></article>`;
}

function refs(values: readonly string[]): string {
  if (!values.length) return '<span class="trace-audit__evidence-empty">无公开 evidence ref</span>';
  return `<div class="trace-audit__evidence-ids">${values.map((value) => `<code>${escapeHtml(value)}</code>`).join('')}</div>`;
}

function datasetExplanation(experiment: EvalLabExperiment): DatasetStory {
  const identity = `${experiment.vertical} ${experiment.title}`.toLowerCase();
  if (identity.includes('enterpriseops') || identity.includes('customer-support') || identity.includes('agent-evaluation-cost')) {
    return {
      source: 'EnterpriseOps-Gym 客户支持任务；每道题都在独立的临时业务数据库中执行。',
      preparation: '固定任务文字、业务日期、可用工具、数据库初始状态和题目清单，并用哈希防止中途换题。',
      gold: `由 Agent 之外的独立评测程序检查数据库最终状态；本轮 ${experiment.dataset.caseCount} 个任务的验收查询和期望值不会提供给 Agent。`,
      agentContract: '精确保留日期、标题、角色与依赖；写入后回读。只有数据库终态和全部验收条件都通过，才算完成。',
      boundary: experiment.dataset.split === 'held-out' ? '这是已经使用的一次性最终盲测，不能拿来继续调参。' : '这是调优数据，用于选择方案；通过不等于生产环境已经成功。',
    };
  }
  if (identity.includes('rag') || identity.includes('knowledge')) {
    const answerLane = experiment.evaluationKind === 'answer_evidence';
    return {
      source: answerLane ? 'EnterpriseRAG-Bench 冻结语料中的 4 个回答任务：2 个有答案、2 个故意没有答案。' : 'EnterpriseRAG-Bench 冻结子集：5,101 篇文档、29,846 个文本块和 16 个检索问题。',
      preparation: answerLane ? '先冻结语料、问题与检索配置；有答案和无答案分开计分，避免“每题都答”刷高分。' : '把公开标注的相关文档转成隐藏答案表，并固定候选池、索引、Top-K 与问题清单。',
      gold: answerLane ? '可回答问题逐条绑定必要事实、原始文档和文本块；无答案问题的正确行为是明确拒答。答案正确、引用支持和拒答分别计算。' : '公开相关性标注就是检索金标准；标准答案不进入 Agent 上下文。',
      agentContract: '只依据可回跳的业务原文；数字、日期、否定、范围与限制不得擅自改变。Room 简报、Agent 消息和指标账本不是业务原文，禁止把 room/session/event ID 冒充 sourceId/chunkId；没有原文正文与真实绑定时必须拒答。',
      boundary: answerLane ? '答案与引用必须单独过门，检索分数变好不能代替最终回答正确。' : '只代表当前冻结检索题；没有合法 Graph/Tag 数据时不生成对比分数。',
    };
  }
  if (identity.includes('cloudops')) {
    return {
      source: '12 条冻结的云故障诊断任务；每条都绑定同一份只读观测快照与工具清单。',
      preparation: '固定题目、日志/指标快照、运行环境、工具地址和评分程序；每个新方案只改一处。',
      gold: '独立评测程序在 Agent 之外比较最终根因与标准根因，并单独检查回答覆盖、根因方向和工具失败。',
      agentContract: '只依据冻结日志、指标、Trace 与 runbook；观察、推断和未知分开，没有观测证据就不猜根因。',
      boundary: '少调用或更快不能抵消诊断质量下降，也不能抵消一次工具失败。',
    };
  }
  if (identity.includes('memory')) {
    const observed = experiment.experimentId.includes('observed-failure');
    return {
      source: observed ? 'PAW 自己的一条真实月度记忆整理失败记录，公开报告只保留脱敏错误和耗时。' : '从真实维护问题抽出的 5 条隐私安全样例：4 条应长期保留，1 条只是临时任务。',
      preparation: observed ? '冻结失败终态，不公开私人记忆原文，也不从错误字符串猜测上游原因。' : '人工先标注“长期保留 / 临时拒记”，固定输入快照；每轮用全新的影子数据库验证。',
      gold: observed ? '只检查是否产出合法 JSON 与持久化回执，不评价内容好坏。' : '程序检查 5/5 判断、4/4 召回、1/1 拒记、向量覆盖、无重复、合法 JSON、回滚和重复运行一致；内容表达由人工样例复核。',
      agentContract: '严格按人工冻结标准整理；输出合法 JSON，不重复写入，能够回滚、重新读取和再次验证。',
      boundary: observed ? '真实失败与五条影子样例不是同一批题，不能计算成一个成功率提升。' : '影子测试通过不等于生产记忆已经修复。',
    };
  }
  return {
    source: `${experiment.dataset.caseCount} ${experiment.dataset.unit}`,
    preparation: '按数据清单哈希固定题目、用途和输入文件。',
    gold: experiment.scoring.goldHiddenFromAgent ? '标准答案由独立评测程序保存，对 Agent 隐藏。' : '当前合同允许 Agent 看到标准答案。',
    agentContract: '只使用本轮授权数据和工具；不知道就写不知道，完成只由外部验收回执判定。',
    boundary: '只说明当前冻结数据上的结果。',
  };
}

function factorLabel(value: string): string {
  return ({ model: '模型', prompt: '提示词', skill: '技能说明', tool: '工具', workflow: '工作流程', context: '提供给模型的上下文', memory_rag: '检索与记忆', guardrail: '安全与质量底线', execution_policy: '执行权限', human_loop: '人工审核', pricing: '价格口径' } as Record<string, string>)[value] ?? value;
}

function controlLabel(value: string): string {
  return ({ validation_cases: '调优任务与验收条件', validation: '调优范围', split: '数据用途', suite: '题目集合', cases: '任务数量', seed_and_gold: '初始数据与标准答案', gold_and_seed: '初始数据与标准答案', runtime_identity: '运行环境与模型身份', held_out: '最终盲测状态', run_receipt: '运行回执', case_set: '固定题目' } as Record<string, string>)[value] ?? value.replaceAll('_', ' ');
}

function candidateTypeLabel(value: EvalLabExperiment['candidateType']): string {
  if (value === 'single_factor') return '本轮只改一处';
  if (value === 'compound_repair') return '历史组合修复，无法把收益归到单独一层';
  if (value === 'baseline') return '原始基线';
  return '历史结果，改动归因不完整';
}

function splitLabel(value: string): string {
  if (value === 'validation') return '调优数据';
  if (value === 'held-out') return '最终盲测';
  if (value === 'shadow_validation') return '隔离影子测试';
  if (value === 'historical_replay') return '历史复盘';
  return value;
}

function metricLabel(value: string): string {
  return ({
    taskSuccessRate: '任务完成率', taskSuccessCount: '完成任务数', taskCount: '任务总数', taskPassed: '完成任务数', taskTotal: '任务总数',
    verifierPassRate: '验收条件通过率', verifierPassCount: '通过的验收条件', verifierCount: '验收条件总数', verifierPassed: '通过的验收条件', verifierTotal: '验收条件总数',
    toolCalls: '工具调用', businessToolCalls: '业务工具调用', failedToolCalls: '工具失败', latencyMs: '总耗时', elapsedMs: '总耗时', actualModelCallElapsedMs: '模型调用耗时',
    apiCostUsd: '估算 API 成本', estimatedApiCostUsd: '估算 API 成本', totalTokens: '总 Token', tokens: 'Token', providerCalls: '模型请求数',
    costReceiptAvailable: '成本回执',
    recallAt10: '前 10 条覆盖率', recall_at_10: '前 10 条覆盖率', mrr: '首个正确结果排名', ndcgAt10: '前 10 条排序质量', ndcg_at_10: '前 10 条排序质量',
    agentCaseCount: 'Agent 任务数', agentSuccessRate: 'Agent 任务通过率', answerCaseCount: '可评分答案数', answerSuccessRate: '答案通过率',
    highLevelFactCount: '必要事实总数', verifiedRequiredFactCount: '已核验必要事实数', highLevelFactCoverage: '必要事实覆盖率', citationFactCoverage: '带有效引用的事实比例', answerableCitationSupportRate: '可回答问题的引用支持率', infoNotFoundCaseCount: '应拒答案例数', infoNotFoundAbstentionRecall: '正确拒答率', citationHardGatePassed: '引用底线', outputProtocolRate: '输出格式通过率',
    answerCoverage: '回答覆盖率', ca: '诊断正确率', fa: '事实准确率', jra: '根因覆盖率', top3Jra: '前三根因覆盖率',
    curationCases: '记忆判断总数', curationPassed: '记忆判断通过数', durableRecallPassed: '长期记忆召回通过数', durableRecallTotal: '长期记忆召回总数', abstentionPassed: '临时信息拒记通过数', abstentionTotal: '临时信息拒记总数', vectorCoverage: '向量可检索覆盖率', rollbackPassed: '回滚验证', replayPassed: '重复运行验证', receiptJsonValid: 'JSON 结果可解析', jsonReceiptValid: 'JSON 结果可解析',
    temporaryDatabasesDeleted: '临时数据库清理数', databasesCleaned: '临时数据库清理数', allDatabasesCleaned: '临时数据库全部清理',
  } as Record<string, string>)[value] ?? value.replaceAll('_', ' ');
}

function isRateMetric(name: string): boolean {
  return name.endsWith('Rate') || ['taskSuccessRate', 'verifierPassRate', 'recallAt10', 'recall_at_10', 'mrr', 'ndcgAt10', 'ndcg_at_10', 'agentSuccessRate', 'answerSuccessRate', 'highLevelFactCoverage', 'citationFactCoverage', 'answerableCitationSupportRate', 'infoNotFoundAbstentionRecall', 'outputProtocolRate', 'answerCoverage', 'ca', 'fa', 'jra', 'top3Jra', 'vectorCoverage'].includes(name);
}

function formatMetricByName(name: string, value: number | undefined): string {
  if (value === undefined) return '—';
  if (isRateMetric(name)) return `${(value * 100).toFixed(2)}%`;
  if (name === 'latencyMs' || name === 'elapsedMs' || name === 'actualModelCallElapsedMs') return `${(value / 1000).toFixed(2)} 秒`;
  if (name === 'apiCostUsd' || name === 'estimatedApiCostUsd') return `$${value.toFixed(4)}`;
  if (name === 'costReceiptAvailable') return value > 0 ? '已提供' : '缺失';
  if (['rollbackPassed', 'replayPassed', 'receiptJsonValid', 'jsonReceiptValid', 'citationHardGatePassed', 'allDatabasesCleaned'].includes(name)) return value > 0 ? '通过' : '未通过';
  return formatMetric(value);
}

function formatMetricChange(row: MetricRow): string {
  const { metric, before, after, delta } = row;
  if (delta === undefined || before === undefined || after === undefined) return '—';
  if (['rollbackPassed', 'replayPassed', 'receiptJsonValid', 'jsonReceiptValid', 'citationHardGatePassed', 'allDatabasesCleaned', 'costReceiptAvailable'].includes(metric)) {
    if (before > 0 && after > 0) return '保持通过';
    if (before <= 0 && after > 0) return '由未通过变为通过';
    if (before > 0 && after <= 0) return '由通过变为未通过';
    return '仍未通过';
  }
  if (delta === 0) return '持平';
  if (isRateMetric(metric)) return `${delta > 0 ? '提高' : '下降'} ${Math.abs(delta * 100).toFixed(2)} 个百分点`;
  if (metric === 'latencyMs' || metric === 'elapsedMs' || metric === 'actualModelCallElapsedMs') return `${delta < 0 ? '缩短' : '增加'} ${Math.abs(delta / 1000).toFixed(2)} 秒`;
  if (metric === 'apiCostUsd' || metric === 'estimatedApiCostUsd') return `${delta < 0 ? '降低' : '增加'} $${Math.abs(delta).toFixed(4)}`;
  return `${delta < 0 ? '减少' : '增加'} ${formatMetric(Math.abs(delta))}`;
}

function decisionLabel(experiment: EvalLabExperiment): string {
  const raw = experiment.comparison.decision.trim().toLowerCase();
  if (raw === 'keep') return '保留新方案';
  if (raw === 'reject') return '回退到原方案';
  if (experiment.status === 'kept') return '保留新方案';
  if (experiment.status === 'rejected') return '回退到原方案';
  if (experiment.status === 'open_gap') return '证据不足，暂不运行';
  return '只做诊断';
}

function statusLabel(status: EvalLabExperiment['status']): string {
  return ({ kept: '已保留', rejected: '已回退', diagnostic: '只做诊断', open_gap: '证据不足' })[status];
}

function meta(label: string, value: string, mono = false): string {
  return `<div><dt>${escapeHtml(label)}</dt><dd${mono ? ' data-mono="true"' : ''}>${escapeHtml(value || '—')}</dd></div>`;
}

function formatMetric(value: number | undefined): string {
  return value === undefined ? '—' : escapeHtml(formatNumber(value));
}

function formatNumber(value: number): string {
  if (!Number.isFinite(value)) return String(value);
  return new Intl.NumberFormat('en-US', { maximumFractionDigits: 8, useGrouping: false }).format(value);
}

function formatTimestamp(value: number): string {
  if (!Number.isFinite(value)) return '时间未知';
  const timestamp = new Date(value);
  return Number.isNaN(timestamp.getTime()) ? '时间未知' : timestamp.toISOString();
}

function safeFilenamePart(value: string): string {
  return value.trim().toLowerCase()
    .replace(/[^a-z0-9._-]+/gu, '-')
    .replace(/^-+|-+$/gu, '')
    || 'experiment';
}

function assertTemplateContract(): void {
  for (const field of TEMPLATE_FIELDS) {
    if (auditTemplate.split(field).length !== 2) {
      throw new Error(`Agent Lab audit template must contain exactly one ${field}`);
    }
  }
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/gu, (character) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  })[character] ?? character);
}

function attr(value: string): string {
  return escapeHtml(value).replace(/`/gu, '&#96;');
}

const EVAL_LAB_AUDIT_STYLES = `
html, body.trace-audit-export { min-height: 100%; margin: 0; background: #eef2ef; }
body.trace-audit-export { padding: clamp(12px, 3vw, 36px); }
.eval-lab-audit { box-shadow: 0 18px 60px rgba(24, 33, 28, .08); }
.eval-lab-audit__section { display: block; min-width: 0; }
.eval-lab-audit__summary { display: grid; grid-template-columns: minmax(220px, .34fr) minmax(0, 1fr); gap: clamp(28px, 5vw, 64px); }
.eval-lab-audit__summary-decision { display: grid; align-content: start; gap: 7px; min-width: 0; }
.eval-lab-audit__summary-decision > span { color: var(--audit-muted); font-size: 11px; font-weight: 760; letter-spacing: .06em; }
.eval-lab-audit__summary-decision h2 { margin: 0; color: var(--audit-success); font-family: var(--font-editorial-serif, Georgia, serif); font-size: clamp(28px, 4vw, 42px); line-height: 1.12; }
.eval-lab-audit__summary-decision[data-status='rejected'] h2 { color: var(--audit-danger); }
.eval-lab-audit__summary-decision[data-status='diagnostic'] h2, .eval-lab-audit__summary-decision[data-status='open_gap'] h2 { color: var(--audit-warning); }
.eval-lab-audit__summary-decision p { margin: 5px 0 0; color: var(--audit-secondary); overflow-wrap: anywhere; }
.eval-lab-audit__summary-list { margin: 0; border-top: 1px solid var(--audit-rule-strong); }
.eval-lab-audit__summary-list > div { display: grid; grid-template-columns: minmax(104px, .25fr) minmax(0, 1fr); gap: 18px; padding: 12px 0; border-bottom: 1px solid var(--audit-rule); }
.eval-lab-audit__summary-list dt { font-weight: 720; }
.eval-lab-audit__summary-list dd { color: var(--audit-secondary); overflow-wrap: anywhere; }
.eval-lab-audit__finding-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
.eval-lab-audit__finding { min-width: 0; padding: 18px; border: 1px solid var(--audit-rule); border-radius: 14px; background: var(--audit-paper); }
.eval-lab-audit__finding > span { display: inline-flex; min-height: 24px; align-items: center; padding: 2px 8px; border-radius: 999px; font-size: 10px; font-weight: 760; }
.eval-lab-audit__finding h3 { margin: 10px 0 0; font-size: 15px; }
.eval-lab-audit__finding p { margin: 6px 0 0; color: var(--audit-secondary); overflow-wrap: anywhere; }
.eval-lab-audit__finding[data-finding-tone='confirmed'] { border-color: color-mix(in srgb, var(--audit-success) 30%, var(--audit-rule)); background: color-mix(in srgb, var(--audit-success-soft) 62%, var(--audit-paper)); }
.eval-lab-audit__finding[data-finding-tone='confirmed'] > span { color: var(--audit-success); background: var(--audit-paper); }
.eval-lab-audit__finding[data-finding-tone='attention'] { border-color: color-mix(in srgb, var(--audit-warning) 34%, var(--audit-rule)); background: color-mix(in srgb, var(--audit-warning-soft) 66%, var(--audit-paper)); }
.eval-lab-audit__finding[data-finding-tone='attention'] > span { color: var(--audit-warning); background: var(--audit-paper); }
.eval-lab-audit__changes { display: grid; gap: 12px; margin-top: 18px; }
.eval-lab-audit__changes article { padding: 14px; border: 1px solid var(--audit-rule); border-radius: 12px; }
.eval-lab-audit__changes article > header { display: grid; gap: 2px; margin-bottom: 10px; }
.eval-lab-audit__changes article > header span, .eval-lab-audit__changes small { color: var(--audit-muted); font-size: 11px; }
.eval-lab-audit__changes article > div { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.eval-lab-audit__changes section { padding: 10px; border-radius: 8px; background: var(--audit-paper-muted); }
.eval-lab-audit__changes h3 { margin: 0 0 4px; color: var(--audit-muted); font-size: 10px; text-transform: uppercase; }
.eval-lab-audit__changes p, .eval-lab-audit__change p { margin: 0; }
.eval-lab-audit__change p + p { margin-top: 8px; }
.eval-lab-audit__change li small { display: block; margin-top: 2px; }
.eval-lab-audit__dataset { margin-top: 18px; }
.eval-lab-audit__dataset > div { display: grid; grid-template-columns: minmax(120px, .35fr) minmax(0, 1fr); gap: 12px; padding: 7px 0; border-bottom: 1px solid var(--audit-rule); }
.eval-lab-audit__dataset-story { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); margin: 0; border: 1px solid var(--audit-rule); border-radius: 14px; overflow: hidden; }
.eval-lab-audit__dataset-story > div { display: grid; gap: 5px; padding: 14px 16px; background: var(--audit-paper); }
.eval-lab-audit__dataset-story > div:nth-child(even) { border-left: 1px solid var(--audit-rule); }
.eval-lab-audit__dataset-story > div:nth-child(n + 3) { border-top: 1px solid var(--audit-rule); }
.eval-lab-audit__dataset-story dt { color: var(--audit-muted); font-size: 11px; font-weight: 760; }
.eval-lab-audit__dataset-story dd { margin: 0; color: var(--audit-secondary); line-height: 1.55; overflow-wrap: anywhere; }
.eval-lab-audit__evidence { display: grid; gap: 12px; }
.eval-lab-audit__evidence article { padding: 14px; border: 1px solid var(--audit-rule); border-radius: 12px; }
.eval-lab-audit__evidence article > header { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 8px 20px; }
.eval-lab-audit__evidence article > header span { color: var(--audit-muted); font-size: 11px; }
.eval-lab-audit__evidence article > p { margin: 8px 0; color: var(--audit-secondary); }
.eval-lab-audit__report-only { border-color: color-mix(in srgb, var(--audit-warning) 42%, var(--audit-rule)) !important; background: var(--audit-warning-soft); }
@container (max-width: 720px) {
  .eval-lab-audit__summary, .eval-lab-audit__finding-grid, .eval-lab-audit__changes article > div, .eval-lab-audit__dataset-story { grid-template-columns: 1fr; }
  .eval-lab-audit__summary-list > div { grid-template-columns: 1fr; gap: 4px; }
  .eval-lab-audit__dataset-story > div:nth-child(even) { border-left: 0; }
  .eval-lab-audit__dataset-story > div + div { border-top: 1px solid var(--audit-rule); }
}
@media print {
  html, body.trace-audit-export { background: #fff; }
  body.trace-audit-export { padding: 0; }
  .eval-lab-audit { box-shadow: none; }
}
`;
