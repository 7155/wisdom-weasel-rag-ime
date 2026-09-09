import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { buildTraceOptimizationReadingModel } from './optimization-report-model';
import { TraceOptimizationReportContent } from './optimization-report-content';
import optimizationStyles from './optimization-report.css?raw';
import type { TraceDiagnosticReportV1 } from '@/contracts/generated/trace-diagnostic-report.v1';
import reportStyles from './engineering-audit-report.css?raw';
import reportTemplate from './templates/engineering-audit-report.html?raw';
import { buildTraceAuditReportModel, type TraceAuditDimension, type TraceAuditReportModel } from './report-model';

export interface TraceDiagnosticHtmlOptions { generatedAtMs?: number; appUrl?: string }
const TEMPLATE_FIELDS = ['__TRACE_AUDIT_TITLE__', '__TRACE_AUDIT_CSS__', '__TRACE_AUDIT_BODY__'] as const;

/** Self-contained, privacy-bounded export of the same two-layer report shown in PAW. */
export function buildTraceDiagnosticReportHtml(report: TraceDiagnosticReportV1, { generatedAtMs = Date.now(), appUrl = '' }: TraceDiagnosticHtmlOptions = {}): string {
  for (const field of TEMPLATE_FIELDS) {
    if (reportTemplate.split(field).length !== 2) throw new Error(`Trace diagnostic HTML template must contain exactly one ${field}`);
  }
  const model = buildTraceAuditReportModel(report);
  return reportTemplate
    .replace('__TRACE_AUDIT_TITLE__', escapeHtml(`${model.title} · 工程审计报告`))
    .replace('__TRACE_AUDIT_CSS__', `${reportStyles}\n${optimizationStyles}`)
    .replace('__TRACE_AUDIT_BODY__', renderReport(model, report, generatedAtMs, safeAppUrl(appUrl)));
}

function renderReport(model: TraceAuditReportModel, report: TraceDiagnosticReportV1, generatedAtMs: number, appReturnHref: string): string {
  const reading = buildTraceOptimizationReadingModel(report);
  return `<main class="trace-audit trace-audit--export" data-status="${attr(model.status)}" data-tone="${attr(model.verdict.tone)}">
  <header class="trace-audit__masthead"><div class="trace-audit__identity"><h1>${escapeHtml(model.title)}</h1></div><dl class="trace-audit__document-meta">${meta('报告状态', model.statusLabel)}${meta('报告修订', `Revision ${model.revision}`)}${meta('更新时间', model.updatedAtLabel)}</dl></header>
  ${renderToStaticMarkup(createElement(TraceOptimizationReportContent, { model, reading, exported: true, appReturnHref }))}
  ${renderAppendix(model)}
  <footer class="trace-audit__provenance"><div><strong>报告身份</strong><span>${escapeHtml(model.reportId)}</span></div><div><strong>冻结检查摘要</strong><span>${escapeHtml(model.inspectionSha256)}</span></div><div><strong>生成时间</strong><span>${escapeHtml(formatTimestamp(generatedAtMs))}</span></div><p>此文件包含持久化报告的公开证据与候选 diff；版本状态记录到导出时刻。</p></footer>
</main>`;
}

function renderCauseChain(model: TraceAuditReportModel): string {
  return `<ol class="trace-audit__cause-nodes">${model.causeChain.map((node, index) => `<li data-state="${node.state}"><div class="trace-audit__cause-node"><span>${escapeHtml(node.stateLabel)}</span><strong>${escapeHtml(node.label)}</strong>${node.detail ? `<p>${escapeHtml(node.detail)}</p>` : ''}${node.evidenceIds.length ? evidenceIds(node.evidenceIds, model) : ''}</div>${index < model.causeChain.length - 1 ? `<div class="trace-audit__cause-connector" aria-label="${attr(`${node.relationAfter || '关联'}，${node.relationConfidence || '置信度未知'}`)}"><span>${escapeHtml(node.relationAfter || '关联待验证')}</span><small>${escapeHtml(node.relationConfidence || '置信度未知')}</small></div>` : ''}</li>`).join('')}</ol>`;
}

function renderFailureAttribution(model: TraceAuditReportModel): string {
  return `<ol class="trace-audit__attribution-list" data-primary-layer="${attr(model.failureAttribution.primaryLayer)}">${model.failureAttribution.layers.map((item) => `<li aria-label="${attr(`${item.label}：${item.verdictLabel}`)}" data-layer="${attr(item.layer)}" data-verdict="${attr(item.verdict)}"><div class="trace-audit__attribution-label"><strong>${escapeHtml(item.label)}</strong><span>${escapeHtml(item.verdictLabel)}</span></div><p>${escapeHtml(item.explanation)}</p>${evidenceIds(item.evidenceIds, model)}</li>`).join('')}</ol>`;
}

function renderAppendix(model: TraceAuditReportModel): string {
  return `<details class="trace-audit__appendix"><summary><span><strong>证据详情与技术附录</strong><small>原记录、诊断归因、时间线、版本和评分</small></span><span class="trace-audit__details-affordance">展开明细</span></summary><div class="trace-audit__appendix-body">
    ${appendixSection('states', '诊断与修复记录', `<dl class="trace-reading__scope">${model.stateBadges.map((badge) => meta(badge.label, badge.value)).join('')}</dl>`)}
    ${scanSection('failure-attribution', '问题出在哪一层', model.failureAttribution.summary, renderFailureAttribution(model), 'trace-audit__attribution')}
    ${scanSection('knowledge', '支持这个判断的事实', '把已确认事实和仍缺少的证据放在一起，避免把未知写成结论。', `<div class="trace-audit__knowledge-columns"><section aria-labelledby="trace-audit-known-title"><h3 id="trace-audit-known-title">已知事实</h3><ul>${model.knownFacts.map((item) => `<li>${escapeHtml(item)}</li>`).join('')}</ul></section><section aria-labelledby="trace-audit-gaps-title"><h3 id="trace-audit-gaps-title">证据缺口</h3><ul>${model.evidenceGaps.map((item) => `<li>${escapeHtml(item)}</li>`).join('')}</ul></section></div>`, 'trace-audit__knowledge')}
    ${scanSection('actions', '下一步怎么做', '先确认修复授权，再读取修复 Trace 中已记录的修改与测试证据，由 AI Judge 复检；不声称在复检中重跑命令或进行同案 Trace 回放。', `<ol class="trace-audit__actions">${model.actions.map((action) => `<li data-tone="${attr(action.tone)}"><span aria-hidden="true">${action.step}</span><div><strong>${escapeHtml(action.title)}</strong><p>${escapeHtml(action.description)}</p></div><small>${escapeHtml(action.state)}</small></li>`).join('')}</ol>`, 'trace-audit__actions-section')}
    ${scanSection('cause-chain', '发生过程（证据链）', '只连接报告明确提供的因果关系；没有从错误字符串补写中间环节。', renderCauseChain(model), 'trace-audit__cause-chain')}

    ${appendixSection('verdict', '原始审计判决', `<div class="trace-audit__verdict"><strong>${escapeHtml(model.verdict.title)}</strong><p>${escapeHtml(model.verdict.detail)}</p>${model.failureReason ? `<p><strong>报告失败原因：</strong>${escapeHtml(model.failureReason)}</p>` : ''}</div>`)}
    ${appendixSection('scope', '冻结诊断范围', renderTargets(model))}
    ${appendixSection('requirements', '用户需求完成矩阵 · 需求矩阵', renderRequirements(model))}
    ${model.gates.length ? appendixSection('gates', '硬门槛', `<div class="trace-audit__gates">${model.gates.map((gate) => `<article data-status="${attr(gate.status)}"><strong>${escapeHtml(gate.gateId)}</strong><span>${escapeHtml(gate.statusLabel)}</span><p>${escapeHtml(gate.reason)}</p>${evidenceIds(gate.evidenceIds, model, true)}</article>`).join('')}</div>`) : ''}
    ${appendixSection('metrics', '扫描指标', `<dl class="trace-audit__metrics">${model.metrics.map((metric) => `<div data-available="${metric.available}"><dt>${escapeHtml(metric.label)}</dt><dd>${escapeHtml(metric.value)}</dd><small>${escapeHtml(metric.detail)}</small></div>`).join('')}</dl>`)}
    ${appendixSection('timeline', '跨 Session / Agent 因果时间线 · 查看完整冻结时间线 · 完整时间线', renderTimeline(model))}
    ${appendixSection('environment', '可复现环境快照 · 环境快照', renderEnvironment(model))}
    ${appendixSection('dimensions', `八维诊断评分 · 八维评分明细（${model.dimensionSummary}）`, renderDimensions(model))}
    ${appendixSection('repair', '修复授权状态', renderRepair(model))}
    ${appendixSection('comparison', '修复前后 Trace / Eval 对照 · 修复对照', renderComparison(model))}
    ${appendixSection('evidence', 'Evidence 目录', renderEvidence(model))}
  </div></details>`;
}

function renderTargets(model: TraceAuditReportModel): string { return `<div class="trace-audit__targets">${model.targets.map((target) => `<article data-source-available="${target.sourceAvailable}"><div><strong>${escapeHtml(target.title)}</strong><span>${escapeHtml(target.kindLabel)} · ${escapeHtml(target.id)}</span></div><span>${target.sourceAvailable ? '源快照可用' : '源快照不可用'}</span></article>`).join('')}</div>`; }
function renderRequirements(model: TraceAuditReportModel): string { return model.requirements.length ? `<div class="trace-audit__requirements">${model.requirements.map((item) => `<article data-status="${attr(item.status)}"><div><strong>${escapeHtml(item.statement)}</strong><span>${escapeHtml(item.owner)} · ${escapeHtml(item.authorityLabel)}</span><p>${escapeHtml(item.note)}</p></div><span>${escapeHtml(item.statusLabel)}</span>${evidenceIds(item.evidenceIds, model, true)}</article>`).join('')}</div>` : `<p class="trace-audit__empty">${escapeHtml(model.requirementsSourceLabel)}；不能从聚合数量倒推出逐条完成情况。</p>`; }
function renderTimeline(model: TraceAuditReportModel): string { return model.timeline.length ? `<ol class="trace-audit__timeline">${model.timeline.map((item) => `<li><time>${escapeHtml(item.createdAtLabel)}</time><div><span>${escapeHtml(item.targetLabel)} · ${escapeHtml(item.kind)}</span><strong>${escapeHtml(item.summary)}</strong></div>${evidenceIds([item.evidenceId], model, true)}</li>`).join('')}</ol>` : '<p class="trace-audit__empty">没有公开时间线。</p>'; }
function renderEnvironment(model: TraceAuditReportModel): string { const targets = model.environment.targets.length ? `<div class="trace-audit__environment-targets">${model.environment.targets.map((target) => `<article><h3>${escapeHtml(target.targetLabel)}</h3><dl>${meta('Runtime', target.runtime)}${meta('模型配置', target.modelProfile)}${meta('Tool 配置', target.toolProfileVersion)}${meta('执行模式', target.executionMode)}${meta('策略修订', target.policyRevision)}${meta('Shell 策略', target.shellPolicyVersion)}${meta('源快照 SHA-256', target.sourceSha256, true)}${meta('Workspace scope SHA-256', target.workspaceScopeSha256, true)}${meta('Trace input fingerprint', target.traceInputFingerprints.join(' · ') || '未冻结', true)}${meta('Trace 状态', target.traceStatuses.join(' · ') || '未知')}</dl></article>`).join('')}</div>` : '<p class="trace-audit__empty">没有 Runtime 权威环境数据，不能声称可复现。</p>'; return `<p class="trace-audit__appendix-status">${escapeHtml(model.environment.statusLabel)} · 捕获于 ${escapeHtml(model.environment.capturedAtLabel)}</p>${targets}${model.environment.limitations.length ? `<ul class="trace-audit__limitations">${model.environment.limitations.map((item) => `<li>${escapeHtml(item)}</li>`).join('')}</ul>` : ''}`; }
function renderDimensions(model: TraceAuditReportModel): string { return `<div class="trace-audit__score-table-wrap"><table class="trace-audit__score-table"><thead><tr><th>维度与适用性</th><th>系统分数</th><th>AI 估计</th><th>指标与证据边界</th></tr></thead><tbody>${model.dimensions.map((dimension) => renderDimension(dimension, model)).join('')}</tbody></table></div>`; }
function renderDimension(dimension: TraceAuditDimension, model: TraceAuditReportModel): string { const judgeScore = dimension.applicability === 'not_applicable' ? '不评分' : dimension.judgeScore === null ? '没有估计' : `${dimension.judgeScore}/3`; const judgeExplanation = dimension.judgeExplanation ? `<span>${escapeHtml(dimension.judgeExplanation)}</span>` : ''; const metrics = dimension.metrics.length ? dimension.metrics.map((metric) => `<span><strong>${escapeHtml(metric.label)}</strong> ${escapeHtml(metric.value)}</span>`).join('') : `<span>${escapeHtml(dimension.note)}</span>`; return `<tr data-applicability="${attr(dimension.applicability)}" data-dimension-id="${attr(dimension.dimensionId)}"><th scope="row"><strong>${escapeHtml(dimension.title)}</strong><span>${escapeHtml(dimension.applicabilityLabel)}</span></th><td><strong>${escapeHtml(dimension.scoreText)}</strong><span>${escapeHtml(dimension.authorityLabel)}</span></td><td><strong>${escapeHtml(judgeScore)}</strong>${judgeExplanation}</td><td>${metrics}${evidenceIds(dimension.evidenceIds, model, true)}</td></tr>`; }
function renderRepair(model: TraceAuditReportModel): string { const repair = model.repairLifecycle; return `<article class="trace-audit__repair-state" data-state="${attr(repair.authorizationState)}"><div><span>修复交接</span><strong>${escapeHtml(repair.authorizationStateLabel)}</strong><p>${escapeHtml(repair.writeAuthorityLabel)}</p></div><dl>${meta('Finding', repair.findingId || '尚未选择', true)}${meta('来源对象', repair.sourceScope || '尚未冻结', true)}${meta('失败引用', repair.failureRef || '尚未冻结', true)}${meta('修复 Session', repair.repairSessionId || '尚未创建', true)}${meta('授权回执', repair.authorizationId || '尚未记录', true)}${meta('授权时间', repair.authorizedAtLabel)}</dl></article>`; }
function renderComparison(model: TraceAuditReportModel): string {
  const repair = model.repairLifecycle;
  const metrics = repair.comparisonMetrics.length ? `<div class="trace-audit__comparison-table-wrap"><table><thead><tr><th>指标</th><th>Before</th><th>After</th><th>Δ</th></tr></thead><tbody>${repair.comparisonMetrics.map((metric) => `<tr><th scope="row">${escapeHtml(metric.metricId)}</th><td>${escapeHtml(metric.before)}</td><td>${escapeHtml(metric.after)}</td><td>${escapeHtml(metric.delta)}</td></tr>`).join('')}</tbody></table></div>` : '<p class="trace-audit__empty">还没有可展示的修复前后指标。</p>';
  const testAuthorityLabel = repair.sandboxStatus === 'not_required'
    ? '全信任 Session 终态测试证据'
    : 'Host 沙盒测试证据';
  const testAuthorityValue = repair.sandboxStatus === 'not_required'
    ? `${repair.testStatus} · 未在 Host 沙盒复跑`
    : `${repair.sandboxStatus} · ${repair.sandboxedTestCount} 次`;
  return `<div class="trace-audit__comparison" data-status="${attr(repair.comparisonStatus)}"><header><div><span>验证状态</span><strong>${escapeHtml(repair.verificationStateLabel)}</strong></div><div><span>同 Case 决策</span><strong>${escapeHtml(repair.decision === 'kept' ? 'Keep' : repair.decision === 'rejected' ? 'Reject' : '尚无回执')}</strong></div><div><span>测试证据</span><strong>${escapeHtml(repair.testStatus)}</strong></div><div><span>${escapeHtml(testAuthorityLabel)}</span><strong>${escapeHtml(testAuthorityValue)}</strong></div></header><dl class="trace-audit__comparison-refs">${meta('诊断 Trace', repair.sourceTraceId || '未绑定', true)}${meta('修复 Trace', repair.repairTraceId || '等待修复 Trace', true)}${meta('Replay Case', repair.replayCaseId || '尚未冻结', true)}${meta('Verification Receipt', repair.verificationReceiptId || '尚未生成', true)}${meta('AI Judge EvalRun', repair.evalRunId || '等待 AI Judge Eval', true)}${meta('修复回执', repair.repairReceiptId || '尚未生成', true)}</dl><p>${escapeHtml(repair.comparisonReason)}</p>${metrics}</div>`;
}
function renderEvidence(model: TraceAuditReportModel): string { const entries = model.evidence.length ? `<div class="trace-audit__evidence-appendix">${model.evidence.map((item) => `<article id="evidence-${attr(item.alias.toLowerCase())}"><code>[${item.alias}] ${escapeHtml(item.evidenceId)}</code><p>${escapeHtml(item.summary)}</p><dl>${meta('来源类型', item.sourceKind)}${meta('Source ref', item.sourceRef, true)}${meta('诊断对象', item.targetLabel)}${meta('Trace', item.traceId || '未绑定', true)}${meta('状态', item.status)}${meta('时间', item.createdAtLabel)}</dl></article>`).join('')}</div>` : '<p class="trace-audit__empty">冻结报告不包含可公开展示的 Evidence。</p>'; return `${entries}${model.unresolvedEvidenceIds.length ? `<p class="trace-audit__unresolved">${model.unresolvedEvidenceIds.length} 个引用未解析，未尝试从实时系统补齐。</p>` : ''}`; }

function scanSection(id: string, title: string, description: string, body: string, className: string): string { const headingId = `trace-audit-${id}-title`; return `<section class="trace-audit__section ${className}" aria-labelledby="${headingId}"><header class="trace-audit__section-heading"><h2 id="${headingId}">${escapeHtml(title)}</h2><p>${escapeHtml(description)}</p></header>${body}</section>`; }
function appendixSection(id: string, title: string, body: string): string { const headingId = `trace-audit-appendix-${id}-title`; return `<section class="trace-audit__appendix-section" aria-labelledby="${headingId}"><h2 id="${headingId}">${escapeHtml(title)}</h2>${body}</section>`; }
function evidenceIds(ids: string[], model: TraceAuditReportModel, full = false): string { if (!ids.length) return '<span class="trace-audit__evidence-empty">无冻结证据引用</span>'; return `<div class="trace-audit__evidence-ids">${ids.map((id) => { const alias = model.evidenceAliases[id] ?? '?'; return `<code>${full ? `[${alias}] ${escapeHtml(id)}` : `[${alias}]`}</code>`; }).join('')}</div>`; }
function meta(label: string, value: string, mono = false): string { return `<div><dt>${escapeHtml(label)}</dt><dd${mono ? ' data-mono="true"' : ''}>${escapeHtml(value)}</dd></div>`; }
function formatTimestamp(value: number): string { return value ? new Date(value).toLocaleString('zh-CN') : '时间未知'; }
function escapeHtml(value: string): string { return value.replace(/[&<>"']/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[character] ?? character); }
function attr(value: string): string { return escapeHtml(value).replace(/`/g, '&#96;'); }
function safeAppUrl(value: string): string { try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) ? url.href : ''; } catch { return ''; } }
