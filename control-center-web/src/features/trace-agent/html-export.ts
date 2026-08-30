import type { TraceDiagnosticReportV1 } from '@/contracts/generated/trace-diagnostic-report.v1';
import reportStyles from './engineering-audit-report.css?raw';
import reportTemplate from './templates/engineering-audit-report.html?raw';
import {
  buildTraceAuditReportModel,
  type TraceAuditDimension,
  type TraceAuditFinding,
  type TraceAuditGate,
  type TraceAuditReportModel,
} from './report-model';

export interface TraceDiagnosticHtmlOptions {
  generatedAtMs?: number;
}

const TEMPLATE_FIELDS = [
  '__TRACE_AUDIT_TITLE__',
  '__TRACE_AUDIT_CSS__',
  '__TRACE_AUDIT_BODY__',
] as const;

/**
 * Render a privacy-bounded, self-contained report from the immutable persisted
 * report projection. Agent prose never becomes markup and the exported file
 * contains no external scripts, fonts, images, or network requests.
 */
export function buildTraceDiagnosticReportHtml(
  report: TraceDiagnosticReportV1,
  { generatedAtMs = Date.now() }: TraceDiagnosticHtmlOptions = {},
): string {
  for (const field of TEMPLATE_FIELDS) {
    if (reportTemplate.split(field).length !== 2) {
      throw new Error(`Trace diagnostic HTML template must contain exactly one ${field}`);
    }
  }
  const model = buildTraceAuditReportModel(report);
  return reportTemplate
    .replace('__TRACE_AUDIT_TITLE__', escapeHtml(`${model.title} · 工程审计报告`))
    .replace('__TRACE_AUDIT_CSS__', reportStyles)
    .replace('__TRACE_AUDIT_BODY__', renderReport(model, generatedAtMs));
}

function renderReport(model: TraceAuditReportModel, generatedAtMs: number): string {
  return `<main class="trace-audit trace-audit--export" data-status="${escapeAttribute(model.status)}" data-tone="${escapeAttribute(model.verdict.tone)}">
  <header class="trace-audit__masthead">
    <div class="trace-audit__identity">
      <p class="trace-audit__document-type">PAW Trace Diagnostic · 工程审计报告</p>
      <h1>${escapeHtml(model.title)}</h1>
      <p class="trace-audit__lede">基于冻结 Trace、Runtime 回执与 Eval 证据生成；候选修复不等于已经应用。</p>
    </div>
    <dl class="trace-audit__document-meta">
      ${meta('报告状态', model.statusLabel)}
      ${meta('报告修订', `Revision ${model.revision}`)}
      ${meta('更新时间', model.updatedAtLabel)}
    </dl>
  </header>
  ${renderVerdict(model)}
  ${model.failureReason ? `<p class="trace-audit__failure" role="alert"><strong>报告失败原因：</strong><span>${escapeHtml(model.failureReason)}</span></p>` : ''}
  ${renderTargets(model)}
  ${renderRequirements(model)}
  ${renderGates(model.gates)}
  ${renderTimeline(model)}
  ${renderFindings(model.findings, model.summary)}
  ${renderDimensions(model.dimensions)}
  ${renderEnvironment(model)}
  ${renderRepairLifecycle(model)}
  ${renderComparison(model)}
  ${renderEvidenceAppendix(model)}
  <footer class="trace-audit__provenance">
    <div><strong>报告身份</strong><span>${escapeHtml(model.reportId)}</span></div>
    <div><strong>冻结检查摘要</strong><span>${escapeHtml(model.inspectionSha256)}</span></div>
    <div><strong>生成时间</strong><span>${escapeHtml(formatTimestamp(generatedAtMs))}</span></div>
    <p>这份文件只包含持久化报告的公开投影，不包含私有推理、原始 Tool 参数、Provider 上下文或机器路径。</p>
  </footer>
</main>`;
}

function renderVerdict(model: TraceAuditReportModel): string {
  return `<section class="trace-audit__verdict" data-tone="${escapeAttribute(model.verdict.tone)}" aria-labelledby="trace-audit-verdict-title">
    <div class="trace-audit__verdict-copy">
      <span class="trace-audit__section-label">审计判决</span>
      <h2 id="trace-audit-verdict-title">${escapeHtml(model.verdict.title)}</h2>
      <p>${escapeHtml(model.verdict.detail)}</p>
    </div>
    <dl class="trace-audit__verdict-metrics">
      ${meta('高优先级问题', String(model.highPriorityCount))}
      ${meta('失败硬门槛', String(model.failedGateCount))}
      ${meta('冻结证据', String(model.evidenceCount))}
      ${meta('可用来源', `${model.sourceAvailableCount}/${model.targets.length}`)}
    </dl>
  </section>`;
}

function renderTargets(model: TraceAuditReportModel): string {
  return `<section class="trace-audit__section" aria-labelledby="trace-audit-scope-title">
    ${sectionHeading('trace-audit-scope-title', '冻结诊断范围', `${model.targets.length} 个对象 · ${model.traceIds.length} 条 Trace`)}
    <div class="trace-audit__targets">
      ${model.targets.map((target) => `<article class="trace-audit__target" data-source-available="${target.sourceAvailable}">
        <div><strong>${escapeHtml(target.title)}</strong><span>${escapeHtml(target.kindLabel)} · ${escapeHtml(target.id)}</span></div>
        <span class="trace-audit__source-state">${target.sourceAvailable ? '源快照可用' : '源快照不可用'}</span>
      </article>`).join('')}
    </div>
  </section>`;
}

function renderRequirements(model: TraceAuditReportModel): string {
  const truncation = model.requirementsTruncated ? ' · 冻结快照已截断' : '';
  const body = model.requirements.length
    ? `<div class="trace-audit__requirements">${model.requirements.map((requirement) => `<article class="trace-audit__requirement" data-status="${escapeAttribute(requirement.status)}">
        <div class="trace-audit__requirement-copy"><strong>${escapeHtml(requirement.statement)}</strong><span>${escapeHtml(requirement.owner)} · ${escapeHtml(requirement.authorityLabel)}</span><p>${escapeHtml(requirement.note)}</p></div>
        <span class="trace-audit__requirement-status">${escapeHtml(requirement.statusLabel)}</span>
        ${renderEvidenceIds(requirement.evidenceIds)}
      </article>`).join('')}</div>`
    : '<p class="trace-audit__empty">未绑定稳定的用户要求集；不能从聚合数量倒推出逐条完成情况。</p>';
  return `<section class="trace-audit__section" aria-labelledby="trace-audit-requirements-title">
    ${sectionHeading('trace-audit-requirements-title', '用户需求完成矩阵', `${model.requirementsSourceLabel} · ${model.requirements.length} 条${truncation}`)}
    ${body}
  </section>`;
}

function renderTimeline(model: TraceAuditReportModel): string {
  const description = model.causalLinks.length
    ? `${model.causalLinks.length} 条显式关联 · ${model.timeline.length} 条冻结事件${model.timelineTruncated ? ' · 快照已截断' : ''} · 因果判断均标注权威与置信度`
    : `${model.timeline.length} 条冻结事件 · 仅按时间排序，未把相邻事件冒充因果${model.timelineTruncated ? ' · 快照已截断' : ''}`;
  let body = '<p class="trace-audit__empty">冻结报告没有公开时间线，因果关系不可判断。</p>';
  if (model.causalLinks.length) {
    body = `<ol class="trace-audit__causal-list">${model.causalLinks.map((link) => `<li>
      <div class="trace-audit__causal-event"><span>${escapeHtml(link.from?.targetLabel ?? '来源未解析')}</span><strong>${escapeHtml(link.from?.summary ?? link.fromEvidenceId)}</strong>${renderEvidenceIds([link.fromEvidenceId])}</div>
      <div class="trace-audit__causal-relation"><strong>${escapeHtml(link.relationLabel)}</strong><span>${escapeHtml(link.authorityLabel)} · ${escapeHtml(link.confidenceLabel)}</span><p>${escapeHtml(link.explanation)}</p></div>
      <div class="trace-audit__causal-event"><span>${escapeHtml(link.to?.targetLabel ?? '目标未解析')}</span><strong>${escapeHtml(link.to?.summary ?? link.toEvidenceId)}</strong>${renderEvidenceIds([link.toEvidenceId])}</div>
    </li>`).join('')}</ol><details class="trace-audit__timeline-details"><summary><strong>查看完整冻结时间线</strong><span>${model.timeline.length} 条，包含未关联事件</span></summary>${renderTimelineItems(model)}</details>`;
  } else if (model.timeline.length) {
    body = renderTimelineItems(model);
  }
  return `<section class="trace-audit__section" aria-labelledby="trace-audit-timeline-title">
    ${sectionHeading('trace-audit-timeline-title', '跨 Session / Agent 因果时间线', description)}
    ${body}
  </section>`;
}

function renderGates(gates: TraceAuditGate[]): string {
  if (!gates.length) return '';
  return `<section class="trace-audit__section" aria-labelledby="trace-audit-gates-title">
    ${sectionHeading('trace-audit-gates-title', '硬门槛', '硬门槛失败时，低成本或局部高分不能把任务判为完成。')}
    <div class="trace-audit__gates">
      ${gates.map((gate) => `<article class="trace-audit__gate" data-status="${escapeAttribute(gate.status)}">
        <div><strong>${escapeHtml(gate.gateId)}</strong><span>${escapeHtml(gate.statusLabel)}</span></div>
        <p>${escapeHtml(gate.reason)}</p>
        ${renderEvidenceIds(gate.evidenceIds)}
      </article>`).join('')}
    </div>
  </section>`;
}

function renderFindings(findings: TraceAuditFinding[], summary: string): string {
  return `<section class="trace-audit__section" aria-labelledby="trace-audit-findings-title">
    ${sectionHeading('trace-audit-findings-title', '诊断结论', summary)}
    <div class="trace-audit__findings">
      ${findings.length ? findings.map(renderFinding).join('') : '<p class="trace-audit__empty">没有结构化 Finding；这不等同于已经证明系统没有问题。</p>'}
    </div>
  </section>`;
}

function renderFinding(finding: TraceAuditFinding): string {
  const open = ['critical', 'high'].includes(finding.severity) ? ' open' : '';
  return `<details class="trace-audit__finding" data-severity="${escapeAttribute(finding.severity)}"${open}>
    <summary>
      <span class="trace-audit__finding-index">${escapeHtml(finding.severityLabel)}</span>
      <span><strong>${escapeHtml(finding.conclusion)}</strong><small>${escapeHtml(finding.dimensionLabel)} · ${escapeHtml(finding.confidenceLabel)}</small></span>
      <code>${escapeHtml(finding.findingId)}</code>
    </summary>
    <div class="trace-audit__finding-body">
      ${findingField('观察事实', finding.observation)}
      ${findingField('待验证假设', finding.hypothesis)}
      ${findingField('支持结论', finding.conclusion)}
      ${findingField('候选修复', finding.candidateRepair)}
      ${findingField('验证要求', finding.verification)}
      <section class="trace-audit__evidence"><h3>证据引用</h3>${renderEvidenceIds(finding.evidenceIds)}</section>
    </div>
  </details>`;
}

function renderDimensions(dimensions: TraceAuditDimension[]): string {
  return `<section class="trace-audit__section" aria-labelledby="trace-audit-score-title">
    ${sectionHeading('trace-audit-score-title', '八维诊断评分', '系统指标、冻结真值与 AI 评审估计分别标注；未知不按零分处理。')}
    <div class="trace-audit__score-table-wrap">
      <table class="trace-audit__score-table">
        <thead><tr><th>维度</th><th>分数</th><th>证据权威</th><th>指标与边界</th></tr></thead>
        <tbody>${dimensions.map(renderDimension).join('')}</tbody>
      </table>
    </div>
  </section>`;
}

function renderEnvironment(model: TraceAuditReportModel): string {
  const targets = model.environment.targets.length
    ? `<div class="trace-audit__environment-targets">${model.environment.targets.map((target) => `<article>
        <h4>${escapeHtml(target.targetLabel)}</h4><dl>
          ${meta('Runtime', target.runtime)}${meta('模型配置', target.modelProfile)}${meta('Tool 配置', target.toolProfileVersion)}${meta('执行模式', target.executionMode)}${meta('策略修订', target.policyRevision)}${meta('Shell 策略', target.shellPolicyVersion)}${meta('源快照 SHA-256', target.sourceSha256, true)}${meta('Workspace scope SHA-256', target.workspaceScopeSha256, true)}${meta('Trace input fingerprint', target.traceInputFingerprints.join(' · ') || '未冻结', true)}${meta('Trace 状态', target.traceStatuses.join(' · ') || '未知')}
        </dl>
      </article>`).join('')}</div>`
    : '<p class="trace-audit__empty">没有 Runtime 权威环境数据，不能声称可复现。</p>';
  const limitations = model.environment.limitations.length
    ? `<div class="trace-audit__limitations"><strong>复现边界</strong><ul>${model.environment.limitations.map((item) => `<li>${escapeHtml(item)}</li>`).join('')}</ul></div>`
    : '';
  return `<section class="trace-audit__section" aria-labelledby="trace-audit-environment-title">
    ${sectionHeading('trace-audit-environment-title', '可复现环境快照', `${model.environment.statusLabel} · 捕获于 ${model.environment.capturedAtLabel}`)}
    <details class="trace-audit__environment"${model.environment.status !== 'complete' ? ' open' : ''}><summary><strong>${escapeHtml(model.environment.statusLabel)}</strong><span>${escapeHtml(model.environment.rubricVersion)}</span></summary>${targets}${limitations}</details>
  </section>`;
}

function renderRepairLifecycle(model: TraceAuditReportModel): string {
  const repair = model.repairLifecycle;
  return `<section class="trace-audit__section" aria-labelledby="trace-audit-repair-title">
    ${sectionHeading('trace-audit-repair-title', '修复授权状态', '修复交接授权与实际写入权限分开记录；候选修复不会自动执行。')}
    <article class="trace-audit__repair-state" data-state="${escapeAttribute(repair.authorizationState)}">
      <div><span>修复交接</span><strong>${escapeHtml(repair.authorizationStateLabel)}</strong><p>${escapeHtml(repair.writeAuthorityLabel)}</p></div>
      <dl>${meta('Finding', repair.findingId || '尚未选择', true)}${meta('授权范围', repair.sourceScope || '尚未冻结', true)}${meta('失败引用', repair.failureRef || '尚未冻结', true)}${meta('修复 Session', repair.repairSessionId || '尚未创建', true)}${meta('授权回执', repair.authorizationId || '尚未记录', true)}${meta('授权时间', repair.authorizedAtLabel)}</dl>
    </article>
  </section>`;
}

function renderComparison(model: TraceAuditReportModel): string {
  const repair = model.repairLifecycle;
  const metrics = repair.comparisonMetrics.length
    ? `<div class="trace-audit__comparison-table-wrap"><table class="trace-audit__comparison-table"><thead><tr><th>指标</th><th>Before</th><th>After</th><th>Δ</th></tr></thead><tbody>${repair.comparisonMetrics.map((metric) => `<tr><th scope="row">${escapeHtml(metric.metricId)}</th><td>${escapeHtml(metric.before)}</td><td>${escapeHtml(metric.after)}</td><td>${escapeHtml(metric.delta)}</td></tr>`).join('')}</tbody></table></div>`
    : '<p class="trace-audit__empty">还没有可展示的修复前后指标。</p>';
  const caveat = repair.verificationState === 'verified'
    ? '<p class="trace-audit__comparison-note">“修复证据已绑定”只证明新 Trace、测试回执和 Eval 存在；是否改善仍由上面的可比性判定。</p>'
    : '';
  return `<section class="trace-audit__section" aria-labelledby="trace-audit-comparison-title">
    ${sectionHeading('trace-audit-comparison-title', '修复前后 Trace / Eval 对照', repair.comparisonReason)}
    <div class="trace-audit__comparison" data-status="${escapeAttribute(repair.comparisonStatus)}">
      <header><div><span>验证状态</span><strong>${escapeHtml(repair.verificationStateLabel)}</strong></div><div><span>可比性</span><strong>${escapeHtml(repair.comparisonStatusLabel)}</strong></div><div><span>测试证据</span><strong>${escapeHtml(repair.testStatus)}</strong></div><div><span>沙盒回放</span><strong>${escapeHtml(repair.sandboxStatus)} · ${repair.sandboxedTestCount} 次</strong></div></header>
      <dl class="trace-audit__comparison-refs">${meta('Before Trace', repair.sourceTraceId || '未绑定', true)}${meta('After Trace', repair.repairTraceId || '等待新 Trace', true)}${meta('EvalRun', repair.evalRunId || '等待 Eval', true)}${meta('修复回执', repair.repairReceiptId || '尚未生成', true)}</dl>
      ${metrics}${caveat}
    </div>
  </section>`;
}

function renderEvidenceAppendix(model: TraceAuditReportModel): string {
  const entries = model.evidence.length
    ? model.evidence.map((item) => `<article id="${escapeAttribute(`evidence-${item.evidenceId}`)}"><code>${escapeHtml(item.evidenceId)}</code><p>${escapeHtml(item.summary)}</p><dl>${meta('来源类型', item.sourceKind)}${meta('Source ref', item.sourceRef, true)}${meta('诊断对象', item.targetLabel)}${meta('Trace', item.traceId || '未绑定', true)}${meta('状态', item.status)}${meta('时间', item.createdAtLabel)}</dl></article>`).join('')
    : '<p class="trace-audit__empty">冻结报告不包含可公开展示的 Evidence。</p>';
  const unresolved = model.unresolvedEvidenceIds.length
    ? `<p class="trace-audit__unresolved">${model.unresolvedEvidenceIds.length} 个引用未在冻结 Evidence 目录中解析，未尝试从实时系统补齐。</p>`
    : '';
  return `<section class="trace-audit__section" aria-labelledby="trace-audit-evidence-title">
    ${sectionHeading('trace-audit-evidence-title', 'Evidence 目录', `${model.evidence.length} 条服务端脱敏公开投影${model.evidenceTruncated ? ' · 快照已截断' : ''}`)}
    <details class="trace-audit__evidence-catalog"><summary><strong>查看 Evidence 附录</strong><span>静态导出不包含实时跳转</span></summary><div class="trace-audit__evidence-appendix">${entries}</div>${unresolved}</details>
  </section>`;
}

function renderDimension(dimension: TraceAuditDimension): string {
  const judge = dimension.judgeScore === null
    ? ''
    : `<span class="trace-audit__judge">AI 评审估计 ${dimension.judgeScore}/3</span>`;
  const metrics = dimension.metrics.length
    ? dimension.metrics.map((metric) => `<span><strong>${escapeHtml(metric.label)}</strong> ${escapeHtml(metric.value)}</span>`).join('')
    : `<span>${escapeHtml(dimension.note)}</span>`;
  return `<tr data-applicability="${escapeAttribute(dimension.applicability)}" data-dimension-id="${escapeAttribute(dimension.dimensionId)}">
    <th scope="row"><strong>${escapeHtml(dimension.title)}</strong><span>${escapeHtml(dimension.applicabilityLabel)}</span></th>
    <td><strong>${escapeHtml(dimension.scoreText)}</strong>${judge}</td>
    <td>${escapeHtml(dimension.authorityLabel)}</td>
    <td><div class="trace-audit__metric-list">${metrics}</div>${renderEvidenceIds(dimension.evidenceIds)}</td>
  </tr>`;
}

function renderTimelineItems(model: TraceAuditReportModel): string {
  return `<ol class="trace-audit__timeline">${model.timeline.map((item) => `<li>
    <time>${escapeHtml(item.createdAtLabel)}</time><div><span>${escapeHtml(item.targetLabel)} · ${escapeHtml(item.kind)}</span><strong>${escapeHtml(item.summary)}</strong></div>${renderEvidenceIds([item.evidenceId])}
  </li>`).join('')}</ol>`;
}

function sectionHeading(id: string, title: string, description: string): string {
  return `<header class="trace-audit__section-heading"><div><h2 id="${escapeAttribute(id)}">${escapeHtml(title)}</h2><p>${escapeHtml(description)}</p></div></header>`;
}

function findingField(title: string, value: string): string {
  return `<section><h3>${escapeHtml(title)}</h3><p>${escapeHtml(value)}</p></section>`;
}

function renderEvidenceIds(evidenceIds: string[]): string {
  if (!evidenceIds.length) return '<span class="trace-audit__evidence-empty">没有可引用证据</span>';
  return `<div class="trace-audit__evidence-ids">${evidenceIds.map((id) => `<code>${escapeHtml(id)}</code>`).join('')}</div>`;
}

function meta(label: string, value: string, mono = false): string {
  return `<div><dt>${escapeHtml(label)}</dt><dd${mono ? ' data-mono="true"' : ''}>${escapeHtml(value)}</dd></div>`;
}

function formatTimestamp(value: number): string {
  return value ? new Date(value).toLocaleString('zh-CN') : '时间未知';
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (character) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  })[character] ?? character);
}

function escapeAttribute(value: string): string {
  return escapeHtml(value).replace(/`/g, '&#96;');
}
