import type { TraceDiagnosticReportV1 } from '@/contracts/generated/trace-diagnostic-report.v1';

export const TRACE_AUDIT_DIMENSIONS = [
  ['task_completion', '任务完成度'],
  ['evidence_diagnosis', '证据与诊断质量'],
  ['tool_runtime', 'Tool / Runtime 可靠性'],
  ['context', 'Context 质量'],
  ['room_collaboration', 'Room / 多 Agent 协作'],
  ['memory_rag', 'Memory / RAG'],
  ['efficiency', '效率'],
  ['repair_quality', '修复质量'],
] as const;

export type TraceAuditTone = 'clear' | 'attention' | 'blocked' | 'unverified' | 'failed' | 'generating';

export interface TraceAuditMetric {
  evidenceIds: string[];
  label: string;
  value: string;
}

export interface TraceAuditDimension {
  applicability: string;
  applicabilityLabel: string;
  authority: string;
  authorityLabel: string;
  dimensionId: string;
  evidenceIds: string[];
  judgeExplanation: string;
  judgeScore: number | null;
  metrics: TraceAuditMetric[];
  note: string;
  score: number | null;
  scoreText: string;
  title: string;
}

export interface TraceAuditFinding {
  candidateRepair: string;
  conclusion: string;
  confidence: string;
  confidenceLabel: string;
  dimensionId: string;
  dimensionLabel: string;
  evidenceIds: string[];
  findingId: string;
  hypothesis: string;
  observation: string;
  severity: string;
  severityLabel: string;
  verification: string;
}

export interface TraceAuditEvidence {
  createdAtMs: number;
  createdAtLabel: string;
  evidenceId: string;
  sourceKind: string;
  sourceRef: string;
  status: string;
  summary: string;
  targetKey: string;
  targetLabel: string;
  traceId: string;
}

export interface TraceAuditRequirement {
  authorityLabel: string;
  evidenceIds: string[];
  note: string;
  owner: string;
  requirementId: string;
  sourceRef: string;
  statement: string;
  status: string;
  statusLabel: string;
  targetKey: string;
}

export interface TraceAuditTimelineItem {
  createdAtLabel: string;
  evidenceId: string;
  kind: string;
  sequence: number;
  status: string;
  summary: string;
  targetKey: string;
  targetLabel: string;
  traceId: string;
}

export interface TraceAuditCausalLink {
  authorityLabel: string;
  confidenceLabel: string;
  explanation: string;
  from: TraceAuditEvidence | null;
  fromEvidenceId: string;
  linkId: string;
  relation: string;
  relationLabel: string;
  to: TraceAuditEvidence | null;
  toEvidenceId: string;
}

export interface TraceAuditEnvironmentTarget {
  complete: boolean;
  executionMode: string;
  modelProfile: string;
  policyRevision: string;
  runtime: string;
  shellPolicyVersion: string;
  sourceSha256: string;
  targetKey: string;
  targetLabel: string;
  toolProfileVersion: string;
  traceInputFingerprints: string[];
  traceStatuses: string[];
  workspaceScopeSha256: string;
}

export interface TraceAuditComparisonMetric {
  after: string;
  before: string;
  delta: string;
  metricId: string;
}

export interface TraceAuditRepairLifecycle {
  authorizationId: string;
  authorizationState: string;
  authorizationStateLabel: string;
  authorizedAtLabel: string;
  comparisonMetrics: TraceAuditComparisonMetric[];
  comparisonReason: string;
  comparisonStatus: string;
  comparisonStatusLabel: string;
  evalRunId: string;
  failureRef: string;
  findingId: string;
  repairReceiptId: string;
  repairSessionId: string;
  repairTraceId: string;
  sandboxStatus: string;
  sandboxedTestCount: number;
  sourceScope: string;
  sourceTraceId: string;
  testStatus: string;
  verificationState: string;
  verificationStateLabel: string;
  verifiedAtLabel: string;
  writeAuthorityLabel: string;
}

export interface TraceAuditGate {
  evidenceIds: string[];
  gateId: string;
  reason: string;
  status: string;
  statusLabel: string;
}

export interface TraceAuditTarget {
  id: string;
  kind: string;
  kindLabel: string;
  sourceAvailable: boolean;
  targetKey: string;
  title: string;
  traceIds: string[];
}

export interface TraceAuditReportModel {
  causalLinks: TraceAuditCausalLink[];
  createdAtLabel: string;
  diagnosticSessionId: string;
  dimensions: TraceAuditDimension[];
  environment: {
    capturedAtLabel: string;
    limitations: string[];
    rubricVersion: string;
    status: string;
    statusLabel: string;
    targets: TraceAuditEnvironmentTarget[];
  };
  evidence: TraceAuditEvidence[];
  evidenceCount: number;
  evidenceTruncated: boolean;
  failedGateCount: number;
  failureReason: string;
  findings: TraceAuditFinding[];
  gates: TraceAuditGate[];
  highPriorityCount: number;
  inspectionSha256: string;
  reportId: string;
  repairLifecycle: TraceAuditRepairLifecycle;
  requirements: TraceAuditRequirement[];
  requirementsSourceLabel: string;
  requirementsTruncated: boolean;
  revision: number;
  sourceAvailableCount: number;
  status: string;
  statusLabel: string;
  summary: string;
  targets: TraceAuditTarget[];
  timeline: TraceAuditTimelineItem[];
  timelineTruncated: boolean;
  title: string;
  traceIds: string[];
  unknownGateCount: number;
  unresolvedEvidenceIds: string[];
  updatedAtLabel: string;
  verdict: {
    detail: string;
    title: string;
    tone: TraceAuditTone;
  };
}

export function buildTraceAuditReportModel(report: TraceDiagnosticReportV1): TraceAuditReportModel {
  const inspection = record(report.inspection);
  const scorecard = record(inspection.scorecard);
  const result = record(report.result);
  const rawDimensions = records(scorecard.dimensions);
  const rawFindings = records(result.findings);
  const rawJudgeScores = records(result.judgeScores);
  const rawEvidence = records(inspection.evidence);
  const rawTimeline = records(inspection.timeline);
  const rawRequirements = record(inspection.requirements);
  const rawEnvironment = record(inspection.environment);
  const rawTruncated = record(inspection.truncated);
  const rawGates = records(result.hardGates).length
    ? records(result.hardGates)
    : records(scorecard.hardGates);
  const targets = report.targets.map((target) => ({
    id: target.id,
    kind: target.kind,
    kindLabel: targetKindLabel(target.kind),
    sourceAvailable: target.sourceAvailable,
    targetKey: target.targetKey,
    title: target.title || target.id,
    traceIds: [...target.traceIds],
  }));
  const targetLabels = new Map(targets.map((target) => [target.targetKey, target.title]));
  const evidence = rawEvidence
    .map((item) => ({
      createdAtMs: integer(item.createdAtMs),
      createdAtLabel: formatTimestamp(integer(item.createdAtMs)),
      evidenceId: text(item.evidenceId),
      sourceKind: text(item.sourceKind, 'unknown'),
      sourceRef: text(item.sourceRef),
      status: text(item.status, 'unknown'),
      summary: text(item.summary, '冻结证据没有公开摘要。'),
      targetKey: text(item.targetKey),
      targetLabel: targetLabels.get(text(item.targetKey)) ?? text(item.targetKey, '未绑定对象'),
      traceId: text(item.traceId),
    }))
    .filter((item) => item.evidenceId && item.sourceRef);
  const evidenceById = new Map(evidence.map((item) => [item.evidenceId, item]));
  const dimensionsById = new Map(rawDimensions.map((item) => [text(item.dimensionId), item]));
  const judgeById = new Map(rawJudgeScores.map((item) => [text(item.dimensionId), item]));
  const dimensions = TRACE_AUDIT_DIMENSIONS.map(([dimensionId, title]) => {
    const dimension = dimensionsById.get(dimensionId) ?? {};
    const judge = judgeById.get(dimensionId) ?? {};
    const score = finiteNumber(dimension.score);
    const judgeScore = finiteNumber(judge.score);
    const authority = text(dimension.authority, judgeScore === null ? 'unknown' : 'ai_judge_estimate');
    const applicability = text(dimension.applicability, 'unknown');
    const metrics = records(dimension.metrics).map((metric) => ({
      evidenceIds: strings(metric.evidenceIds),
      label: text(metric.label, text(metric.metricId, '指标')),
      value: metricValue(metric.value, metric.unit),
    }));
    return {
      applicability,
      applicabilityLabel: applicabilityLabel(applicability),
      authority,
      authorityLabel: authorityLabel(authority),
      dimensionId,
      evidenceIds: uniqueStrings([
        ...strings(dimension.evidenceIds),
        ...strings(judge.evidenceIds),
        ...metrics.flatMap((metric) => metric.evidenceIds),
      ]),
      judgeExplanation: text(judge.explanation),
      judgeScore,
      metrics,
      note: text(dimension.note, text(judge.explanation, '暂无可验证指标')),
      score,
      scoreText: applicability === 'not_applicable'
        ? '不评分'
        : score === null
          ? '未知'
          : `${Math.round(score)}/100`,
      title,
    };
  });
  const gates = rawGates.map((gate) => {
    const status = text(gate.status, 'unknown');
    return {
      evidenceIds: strings(gate.evidenceIds),
      gateId: text(gate.gateId, 'unknown_gate'),
      reason: text(gate.reason, '没有提供判断理由。'),
      status,
      statusLabel: gateStatusLabel(status),
    };
  });
  const findings = rawFindings.map((finding) => {
    const dimensionId = text(finding.dimensionId);
    const severity = text(finding.severity, 'medium');
    const confidence = text(finding.confidence, 'unknown');
    return {
      candidateRepair: text(finding.candidateRepair, '尚未提出候选修复。'),
      conclusion: text(finding.conclusion, '现有证据不足以形成结论。'),
      confidence,
      confidenceLabel: confidenceLabel(confidence),
      dimensionId,
      dimensionLabel: TRACE_AUDIT_DIMENSIONS.find(([id]) => id === dimensionId)?.[1] ?? dimensionId,
      evidenceIds: strings(finding.evidenceIds),
      findingId: text(finding.findingId, 'finding:unknown'),
      hypothesis: text(finding.hypothesis, '没有剩余假设。'),
      observation: text(finding.observation, '没有记录可直接观察的现象。'),
      severity,
      severityLabel: severityLabel(severity),
      verification: text(finding.verification, '授权修复后需要新 Trace 或 Eval 证明结果。'),
    };
  });
  const assessmentsById = new Map(records(result.requirementAssessments).map((item) => [text(item.requirementId), item]));
  const requirements = records(rawRequirements.items).map((item) => {
    const requirementId = text(item.requirementId);
    const assessment = assessmentsById.get(requirementId) ?? {};
    const status = text(assessment.status, 'unverified');
    return {
      authorityLabel: authorityLabel(text(assessment.authority, 'unknown')),
      evidenceIds: uniqueStrings([...strings(item.evidenceIds), ...strings(assessment.evidenceIds)]),
      note: text(assessment.note, '尚未形成带证据的完成判断。'),
      owner: text(assessment.owner, 'Owner 未确认'),
      requirementId,
      sourceRef: text(item.sourceRef),
      statement: text(item.statement, '未提供需求原文。'),
      status,
      statusLabel: requirementStatusLabel(status),
      targetKey: text(item.targetKey),
    };
  }).filter((item) => item.requirementId);
  const timeline = rawTimeline.map((item) => ({
    createdAtLabel: formatTimestamp(integer(item.createdAtMs)),
    evidenceId: text(item.evidenceId),
    kind: text(item.kind, 'event'),
    sequence: finiteNumber(item.sequence) ?? 0,
    status: text(item.status, 'unknown'),
    summary: text(item.summary, '冻结事件没有公开摘要。'),
    targetKey: text(item.targetKey),
    targetLabel: targetLabels.get(text(item.targetKey)) ?? text(item.targetKey, '未绑定对象'),
    traceId: text(item.traceId),
  })).filter((item) => item.evidenceId);
  const causalLinks = records(result.causalLinks).map((item) => {
    const fromEvidenceId = text(item.fromEvidenceId);
    const toEvidenceId = text(item.toEvidenceId);
    const relation = text(item.relation, 'caused');
    return {
      authorityLabel: authorityLabel(text(item.authority, 'ai_judge_estimate')),
      confidenceLabel: confidenceLabel(text(item.confidence, 'unknown')),
      explanation: text(item.explanation, '没有提供因果解释。'),
      from: evidenceById.get(fromEvidenceId) ?? null,
      fromEvidenceId,
      linkId: text(item.linkId, `${fromEvidenceId}:${toEvidenceId}`),
      relation,
      relationLabel: causalRelationLabel(relation),
      to: evidenceById.get(toEvidenceId) ?? null,
      toEvidenceId,
    };
  }).filter((item) => item.fromEvidenceId && item.toEvidenceId)
    .sort((left, right) => (
      (left.from?.createdAtMs ?? left.to?.createdAtMs ?? 0)
      - (right.from?.createdAtMs ?? right.to?.createdAtMs ?? 0)
      || left.linkId.localeCompare(right.linkId)
    ));
  const environmentTargets = records(rawEnvironment.targets).map((item) => {
    const targetKey = text(item.targetKey);
    const runtimeKind = text(item.runtimeKind);
    const runtimeGeneration = finiteNumber(item.runtimeGeneration);
    const policyRevision = finiteNumber(item.policyRevision);
    const sourceSha256 = text(item.sourceSha256);
    const modelProfile = text(item.modelProfile);
    const toolProfileVersion = text(item.toolProfileVersion);
    const executionMode = text(item.executionMode);
    const workspaceScopeSha256 = text(item.workspaceScopeSha256);
    const shellPolicyVersion = text(item.shellPolicyVersion);
    const traceInputFingerprints = strings(item.traceInputFingerprints);
    const traceStatuses = strings(item.traceStatuses);
    return {
      complete: Boolean(
        sourceSha256
        && modelProfile
        && toolProfileVersion
        && executionMode
        && policyRevision !== null
        && workspaceScopeSha256
        && shellPolicyVersion
        && runtimeKind
        && runtimeGeneration !== null
        && traceInputFingerprints.length
        && traceStatuses.length
      ),
      executionMode: executionMode || '未冻结',
      modelProfile: modelProfile || '未冻结',
      policyRevision: policyRevision === null ? '未冻结' : `Revision ${Math.round(policyRevision)}`,
      runtime: runtimeKind ? `${runtimeKind}${runtimeGeneration === null ? '' : ` · Generation ${Math.round(runtimeGeneration)}`}` : '未冻结',
      shellPolicyVersion: shellPolicyVersion || '未冻结',
      sourceSha256: sourceSha256 || '未冻结',
      targetKey,
      targetLabel: targetLabels.get(targetKey) ?? targetKey,
      toolProfileVersion: toolProfileVersion || '未冻结',
      traceInputFingerprints,
      traceStatuses,
      workspaceScopeSha256: workspaceScopeSha256 || '未冻结',
    };
  }).filter((item) => item.targetKey);
  const environmentLimitations = strings(rawEnvironment.limitations);
  const environmentStatus = !environmentTargets.length
    ? 'unavailable'
    : environmentLimitations.length || environmentTargets.some((target) => !target.complete)
      ? 'partial'
      : 'complete';
  const repairLifecycle = buildRepairLifecycle(report);
  const evidenceIds = new Set([
    ...gates.flatMap((gate) => gate.evidenceIds),
    ...findings.flatMap((finding) => finding.evidenceIds),
    ...requirements.flatMap((requirement) => requirement.evidenceIds),
    ...causalLinks.flatMap((link) => [link.fromEvidenceId, link.toEvidenceId]),
    ...dimensions.flatMap((dimension) => dimension.evidenceIds),
  ]);
  const unresolvedEvidenceIds = [...evidenceIds].filter((evidenceId) => !evidenceById.has(evidenceId));
  const failedGateCount = gates.filter((gate) => gate.status === 'failed').length;
  const unknownGateCount = gates.filter((gate) => gate.status === 'unknown').length;
  const highPriorityCount = findings.filter((finding) => ['critical', 'high'].includes(finding.severity)).length;
  const sourceAvailableCount = targets.filter((target) => target.sourceAvailable).length;
  const summary = text(result.summary, report.failureReason || '当前报告尚未生成结构化诊断摘要。');
  return {
    causalLinks,
    createdAtLabel: formatTimestamp(report.createdAtMs),
    diagnosticSessionId: report.diagnosticSessionId,
    dimensions,
    environment: {
      capturedAtLabel: formatTimestamp(integer(rawEnvironment.capturedAtMs)),
      limitations: environmentLimitations,
      rubricVersion: text(rawEnvironment.rubricVersion, text(scorecard.rubricVersion, '未冻结')),
      status: environmentStatus,
      statusLabel: environmentStatusLabel(environmentStatus),
      targets: environmentTargets,
    },
    evidence,
    evidenceCount: evidence.length,
    evidenceTruncated: rawTruncated.evidence === true,
    failedGateCount,
    failureReason: report.failureReason,
    findings,
    gates,
    highPriorityCount,
    inspectionSha256: report.inspectionSha256,
    reportId: report.reportId,
    repairLifecycle,
    requirements,
    requirementsSourceLabel: requirementSourceLabel(text(rawRequirements.source, 'unknown')),
    requirementsTruncated: rawRequirements.truncated === true,
    revision: report.revision,
    sourceAvailableCount,
    status: report.status,
    statusLabel: reportStatusLabel(report.status),
    summary,
    targets,
    timeline,
    timelineTruncated: rawTruncated.timeline === true,
    title: report.title,
    traceIds: [...report.traceIds],
    unknownGateCount,
    unresolvedEvidenceIds,
    updatedAtLabel: formatTimestamp(report.updatedAtMs),
    verdict: verdictFor({
      failedGateCount,
      failureReason: report.failureReason,
      highPriorityCount,
      sourceAvailableCount,
      status: report.status,
      summary,
      targetCount: targets.length,
      unknownGateCount,
    }),
  };
}

function buildRepairLifecycle(report: TraceDiagnosticReportV1): TraceAuditRepairLifecycle {
  const lifecycle = record(report.repairLifecycle);
  const authorization = record(lifecycle.authorization);
  const verification = record(lifecycle.verification);
  const comparison = record(verification.comparison);
  const authorizationState = text(authorization.state, 'not_recorded');
  const verificationState = text(verification.state, 'not_requested');
  const comparisonStatus = text(comparison.status, verificationState === 'not_requested' ? 'not_requested' : 'pending');
  const before = numericRecord(comparison.beforeMetrics);
  const after = numericRecord(comparison.afterMetrics);
  const deltas = numericRecord(comparison.deltas);
  const metricIds = uniqueStrings([...Object.keys(before), ...Object.keys(after), ...Object.keys(deltas)]);
  return {
    authorizationId: text(authorization.authorizationId),
    authorizationState,
    authorizationStateLabel: repairAuthorizationLabel(authorizationState),
    authorizedAtLabel: formatTimestamp(integer(authorization.authorizedAtMs)),
    comparisonMetrics: metricIds.map((metricId) => ({
      after: metricNumber(after[metricId]),
      before: metricNumber(before[metricId]),
      delta: comparisonStatus === 'available' ? metricDelta(deltas[metricId]) : '不可计算',
      metricId,
    })),
    comparisonReason: text(comparison.reason, verificationState === 'not_requested' ? '尚未授权修复，也没有新的 Trace/Eval。' : '等待新 Trace/Eval。'),
    comparisonStatus,
    comparisonStatusLabel: comparisonStatusLabel(comparisonStatus),
    evalRunId: text(verification.evalRunId),
    failureRef: text(authorization.failureRef),
    findingId: text(authorization.findingId),
    repairReceiptId: text(verification.repairReceiptId),
    repairSessionId: text(authorization.repairSessionId),
    repairTraceId: text(verification.repairTraceId),
    sandboxStatus: text(verification.sandboxStatus, '未运行'),
    sandboxedTestCount: integer(verification.sandboxedTestCount),
    sourceScope: text(authorization.sourceScope),
    sourceTraceId: text(authorization.sourceTraceId),
    testStatus: text(verification.testStatus, '未运行'),
    verificationState,
    verificationStateLabel: repairVerificationLabel(verificationState),
    verifiedAtLabel: formatTimestamp(integer(verification.verifiedAtMs)),
    writeAuthorityLabel: authorization.writeAuthority === 'model_arbitrated_full_trust'
      ? '全自动修复；待审批操作由独立 Luna Max 判定'
      : authorization.writeAuthority === 'per_action_required'
        ? '旧版交接：实际写入仍需逐次审批'
      : authorizationState === 'not_recorded'
        ? '没有修复授权回执'
        : '未记录写入授权边界',
  };
}

function verdictFor(input: {
  failedGateCount: number;
  failureReason: string;
  highPriorityCount: number;
  sourceAvailableCount: number;
  status: string;
  summary: string;
  targetCount: number;
  unknownGateCount: number;
}): TraceAuditReportModel['verdict'] {
  if (input.status === 'generating') {
    return { title: '证据正在冻结', detail: '诊断 Agent 尚未提交可校验的结构化结果。', tone: 'generating' };
  }
  if (input.status === 'failed') {
    return { title: '诊断未完成', detail: input.failureReason || '诊断 Session 没有产生可校验结果。', tone: 'failed' };
  }
  if (input.failedGateCount) {
    return { title: '任务完成门槛未通过', detail: `${input.failedGateCount} 个硬门槛失败；评分不能掩盖未完成结果。`, tone: 'blocked' };
  }
  if (input.unknownGateCount || input.sourceAvailableCount < input.targetCount) {
    return { title: '结论仍待验证', detail: '部分硬门槛或诊断来源缺少足够证据。', tone: 'unverified' };
  }
  if (input.highPriorityCount) {
    return { title: `发现 ${input.highPriorityCount} 项高优先级风险`, detail: input.summary, tone: 'attention' };
  }
  return { title: '诊断已完成', detail: input.summary, tone: 'clear' };
}

export function authorityLabel(value: string): string {
  return ({
    deterministic: '系统确定性',
    ground_truth: '冻结真值',
    mixed: '混合证据',
    ai_judge_estimate: 'AI 评审估计',
    unknown: '依据未知',
  } as Record<string, string>)[value] ?? value;
}

export function reportStatusLabel(value: string): string {
  return ({ generating: '生成中', completed: '已完成', failed: '失败' } as Record<string, string>)[value] ?? value;
}

function applicabilityLabel(value: string): string {
  return ({
    measured: '已测量',
    partial: '部分可测',
    not_applicable: '不适用',
    unavailable: '证据不可用',
    unknown: '未知',
  } as Record<string, string>)[value] ?? value;
}

function gateStatusLabel(value: string): string {
  return ({ passed: '通过', failed: '未通过', unknown: '未知' } as Record<string, string>)[value] ?? value;
}

function requirementStatusLabel(value: string): string {
  return ({
    satisfied: '已满足',
    partial: '部分满足',
    unsatisfied: '未满足',
    unverified: '未验证',
  } as Record<string, string>)[value] ?? value;
}

function requirementSourceLabel(value: string): string {
  return ({
    user_input: '冻结用户原话',
    work_item: '冻结 WorkItem',
    eval: '冻结 Eval 要求集',
    unknown: '未绑定要求集',
  } as Record<string, string>)[value] ?? value;
}

function causalRelationLabel(value: string): string {
  return ({
    triggered: '触发',
    delegated: '派工',
    responded_to: '响应',
    returned: '返回',
    verified: '验证',
    caused: '导致',
    recovered: '恢复',
  } as Record<string, string>)[value] ?? value;
}

function environmentStatusLabel(value: string): string {
  return ({ complete: '完整冻结', partial: '部分冻结', unavailable: '不可复现' } as Record<string, string>)[value] ?? value;
}

function repairAuthorizationLabel(value: string): string {
  return ({
    not_recorded: '尚未记录修复授权',
    authorized: '已授权进入修复流程',
    declined: '已拒绝',
    blocked: '当前不可授权',
    expired: '授权已过期',
  } as Record<string, string>)[value] ?? value;
}

function repairVerificationLabel(value: string): string {
  return ({
    not_requested: '尚未开始验证',
    pending: '等待新 Trace/Eval',
    verified: '修复证据已绑定',
    failed: '验证失败',
  } as Record<string, string>)[value] ?? value;
}

function comparisonStatusLabel(value: string): string {
  return ({
    not_requested: '尚未请求',
    pending: '等待对照证据',
    available: '可比较',
    incomparable: '不可比较',
    failed: '比较失败',
    unknown: '可比性未知',
  } as Record<string, string>)[value] ?? value;
}

function severityLabel(value: string): string {
  return ({ critical: '严重', high: '高', medium: '中', low: '低' } as Record<string, string>)[value] ?? value;
}

function confidenceLabel(value: string): string {
  return ({ high: '高置信', medium: '中置信', low: '低置信', unknown: '置信度未知' } as Record<string, string>)[value] ?? value;
}

function targetKindLabel(value: string): string {
  return ({ session: 'Session', room: 'Room', run: '运行记录' } as Record<string, string>)[value] ?? value;
}

function metricValue(value: unknown, unit: unknown): string {
  const numeric = finiteNumber(value);
  if (numeric === null) return '未知';
  const normalizedUnit = text(unit);
  if (normalizedUnit === 'ratio') return `${Math.round(numeric * 1000) / 10}%`;
  const rendered = Number.isInteger(numeric) ? String(numeric) : numeric.toFixed(3).replace(/0+$/, '').replace(/\.$/, '');
  return `${rendered}${normalizedUnit ? ` ${normalizedUnit}` : ''}`;
}

function formatTimestamp(value: number): string {
  if (!value) return '时间未知';
  return new Date(value).toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function integer(value: unknown): number {
  const numeric = finiteNumber(value);
  return numeric === null ? 0 : Math.max(0, Math.round(numeric));
}

function numericRecord(value: unknown): Record<string, number> {
  const source = record(value);
  return Object.fromEntries(Object.entries(source).filter((entry): entry is [string, number] => (
    typeof entry[1] === 'number' && Number.isFinite(entry[1])
  )));
}

function metricNumber(value: number | undefined): string {
  if (value === undefined) return '—';
  return Number.isInteger(value) ? String(value) : value.toFixed(3).replace(/0+$/, '').replace(/\.$/, '');
}

function metricDelta(value: number | undefined): string {
  if (value === undefined) return '—';
  const rendered = metricNumber(Math.abs(value));
  return value > 0 ? `+${rendered}` : value < 0 ? `−${rendered}` : '0';
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function records(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.map(record).filter((item) => Object.keys(item).length > 0) : [];
}

function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.map((item) => text(item)).filter(Boolean) : [];
}

function uniqueStrings(values: string[]): string[] {
  return [...new Set(values.filter(Boolean))];
}

function text(value: unknown, fallback = ''): string {
  return typeof value === 'string' && value.trim() ? value.trim() : fallback;
}

function finiteNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}
