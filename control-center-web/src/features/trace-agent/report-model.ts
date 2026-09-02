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

export const TRACE_FAILURE_LAYERS = [
  { layer: 'tool', label: 'Tool / Runtime' },
  { layer: 'skill', label: 'Skill' },
  { layer: 'template', label: '模板提示' },
  { layer: 'workflow', label: '工作流' },
  { layer: 'model', label: '模型能力' },
] as const;

export type TraceFailureLayer = typeof TRACE_FAILURE_LAYERS[number]['layer'];
export type TraceFailureVerdict = 'primary' | 'contributing' | 'healthy' | 'unknown' | 'not_applicable';

export interface TraceAuditFailureLayer {
  evidenceIds: string[];
  explanation: string;
  label: string;
  layer: TraceFailureLayer;
  verdict: TraceFailureVerdict;
  verdictLabel: string;
}

export interface TraceAuditFailureAttribution {
  layers: TraceAuditFailureLayer[];
  primaryLayer: TraceFailureLayer | 'unknown';
  summary: string;
}

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
  questionTitle: string;
}

export interface TraceAuditEvidence {
  alias: string;
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
  alias: string;
  createdAtMs: number | null;
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

export interface TraceAuditScanMetric {
  available: boolean;
  detail: string;
  key: 'duration' | 'timeline' | 'receipts';
  label: string;
  value: string;
}

export interface TraceAuditStateBadge {
  key: 'incident' | 'diagnosis' | 'repair';
  label: string;
  tone: TraceAuditTone;
  value: string;
}

export interface TraceAuditCauseNode {
  alias: string;
  detail: string;
  evidenceId: string;
  evidenceIds: string[];
  label: string;
  relationAfter: string;
  relationConfidence: string;
  state: 'confirmed' | 'unverified';
  stateLabel: string;
}

export interface TraceAuditAction {
  description: string;
  state: string;
  step: number;
  title: string;
  tone: TraceAuditTone;
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
  actions: TraceAuditAction[];
  causeChain: TraceAuditCauseNode[];
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
  evidenceAliases: Record<string, string>;
  evidenceCount: number;
  evidenceGaps: string[];
  evidenceTruncated: boolean;
  failedGateCount: number;
  failureReason: string;
  failureAttribution: TraceAuditFailureAttribution;
  findings: TraceAuditFinding[];
  gates: TraceAuditGate[];
  highPriorityCount: number;
  inspectionSha256: string;
  impact: string;
  knownFacts: string[];
  metrics: TraceAuditScanMetric[];
  plainConclusion: string;
  reportId: string;
  repairLifecycle: TraceAuditRepairLifecycle;
  requirements: TraceAuditRequirement[];
  requirementsSourceLabel: string;
  requirementsTruncated: boolean;
  revision: number;
  sourceAvailableCount: number;
  status: string;
  statusLabel: string;
  stateBadges: TraceAuditStateBadge[];
  summary: string;
  targets: TraceAuditTarget[];
  timeline: TraceAuditTimelineItem[];
  timelineTruncated: boolean;
  title: string;
  traceIds: string[];
  unknownGateCount: number;
  unresolvedEvidenceIds: string[];
  updatedAtLabel: string;
  dimensionSummary: string;
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
  const presentation = record(result.presentation);
  const presentationKnownFacts = records(presentation.knownFacts);
  const presentationEvidenceGaps = records(presentation.evidenceGaps);
  const presentationCausalNodes = records(presentation.causalNodes);
  const rawFailureAttribution = record(presentation.failureAttribution);
  const rawFailureAttributionLayers = records(rawFailureAttribution.layers);
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
    .map((item, index) => ({
      alias: `E${index + 1}`,
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
          ? '无系统评分'
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
    const conclusion = text(finding.conclusion, '现有证据不足以形成结论。');
    return {
      candidateRepair: text(finding.candidateRepair, '尚未提出候选修复。'),
      conclusion,
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
      verification: text(finding.verification, '授权修复后需要修复 Trace 中已记录的修改与通过测试证据，以及 AI Judge 复检。'),
      questionTitle: findingQuestionTitle(dimensionId, conclusion, confidenceLabel(confidence)),
    };
  });
  const primaryFindingId = text(presentation.primaryFindingId);
  if (primaryFindingId) findings.sort((left, right) => (
    Number(right.findingId === primaryFindingId) - Number(left.findingId === primaryFindingId)
  ));
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
    alias: '',
    detail: '当前报告没有显式因果关联。',
    createdAtMs: finiteNumber(item.createdAtMs),
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
    ...presentationKnownFacts.flatMap((item) => strings(item.evidenceIds)),
    ...presentationCausalNodes.flatMap((item) => strings(item.evidenceIds)),
    ...strings(presentation.recordedStageReceiptEvidenceIds),
    ...rawFailureAttributionLayers.flatMap((item) => strings(item.evidenceIds)),
  ]);
  const unresolvedEvidenceIds = [...evidenceIds].filter((evidenceId) => !evidenceById.has(evidenceId));
  const allEvidenceIds = uniqueStrings([
    ...evidence.map((item) => item.evidenceId),
    ...timeline.map((item) => item.evidenceId),
    ...evidenceIds,
  ]);
  const evidenceAliases = Object.fromEntries(allEvidenceIds.map((evidenceId, index) => [evidenceId, `E${index + 1}`]));
  evidence.forEach((item) => { item.alias = evidenceAliases[item.evidenceId]; });
  timeline.forEach((item) => { item.alias = evidenceAliases[item.evidenceId]; });
  const failureAttribution = buildFailureAttribution(
    rawFailureAttribution,
    evidenceById,
    evidenceAliases,
  );
  findings.forEach((finding) => {
    finding.candidateRepair = aliasEvidenceIds(finding.candidateRepair, evidenceAliases);
    finding.conclusion = aliasEvidenceIds(finding.conclusion, evidenceAliases);
    finding.hypothesis = aliasEvidenceIds(finding.hypothesis, evidenceAliases);
    finding.observation = aliasEvidenceIds(finding.observation, evidenceAliases);
    finding.questionTitle = aliasEvidenceIds(finding.questionTitle, evidenceAliases);
    finding.verification = aliasEvidenceIds(finding.verification, evidenceAliases);
  });
  const failedGateCount = gates.filter((gate) => gate.status === 'failed').length;
  const unknownGateCount = gates.filter((gate) => gate.status === 'unknown').length;
  const highPriorityCount = findings.filter((finding) => ['critical', 'high'].includes(finding.severity)).length;
  const sourceAvailableCount = targets.filter((target) => target.sourceAvailable).length;
  const summary = aliasEvidenceIds(text(result.summary, report.failureReason || '当前报告尚未生成结构化诊断摘要。'), evidenceAliases);
  const metrics = buildScanMetrics(timeline, rawTruncated.timeline === true, presentation);
  const fallbackEvidenceGaps = buildEvidenceGaps({
    causalLinks,
    dimensions,
    environmentStatus,
    environmentLimitations,
    evidenceTruncated: rawTruncated.evidence === true,
    requirements,
    requirementsSource: text(rawRequirements.source, 'unknown'),
    requirementsTruncated: rawRequirements.truncated === true,
    sourceUnavailableCount: targets.length - sourceAvailableCount,
    timeline,
    timelineTruncated: rawTruncated.timeline === true,
    unresolvedEvidenceIds,
  });
  const evidenceGaps = presentationEvidenceGaps.length
    ? presentationEvidenceGaps.map((item) => formatPresentationGap(item, evidenceAliases)).filter(Boolean)
    : fallbackEvidenceGaps;
  const causeChain = presentationCausalNodes.length
    ? buildPresentationCauseChain(presentationCausalNodes, evidenceAliases)
    : buildCauseChain(causalLinks, evidenceAliases);
  const fallbackConclusion = buildPlainConclusion({
    failureReason: report.failureReason,
    findings,
    hasFailure: report.status === 'failed' || failedGateCount > 0 || timeline.some((item) => item.status === 'failed'),
    status: report.status,
    summary,
    targetTitle: targets[0]?.title || report.title,
  });
  const plainConclusion = aliasEvidenceIds(text(presentation.headline, fallbackConclusion), evidenceAliases);
  const impact = aliasEvidenceIds(text(presentation.impact, '结论只来自冻结报告中的结构化字段；没有证据的上游原因保持未知。'), evidenceAliases);
  const stateBadges = buildStateBadges({
    causalLinks,
    evidence,
    findings,
    gates,
    repairLifecycle,
    reportStatus: report.status,
    timeline,
  });
  const actions = buildActions(repairLifecycle);
  const dimensionSummary = buildDimensionSummary(dimensions);
  return {
    actions,
    causalLinks,
    causeChain,
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
    evidenceAliases,
    evidenceCount: evidence.length,
    evidenceGaps,
    evidenceTruncated: rawTruncated.evidence === true,
    failedGateCount,
    failureReason: report.failureReason,
    failureAttribution,
    findings,
    gates,
    highPriorityCount,
    inspectionSha256: report.inspectionSha256,
    impact,
    knownFacts: presentationKnownFacts.length
      ? presentationKnownFacts.map((item) => formatPresentationFact(item, evidenceAliases)).filter(Boolean)
      : buildKnownFacts({ causalLinks, evidence, reportStatus: report.status, targets, timeline }),
    metrics,
    plainConclusion,
    reportId: report.reportId,
    repairLifecycle,
    requirements,
    requirementsSourceLabel: requirementSourceLabel(text(rawRequirements.source, 'unknown')),
    requirementsTruncated: rawRequirements.truncated === true,
    revision: report.revision,
    sourceAvailableCount,
    status: report.status,
    statusLabel: reportStatusLabel(report.status),
    stateBadges,
    summary,
    targets,
    timeline,
    timelineTruncated: rawTruncated.timeline === true,
    title: report.title,
    traceIds: [...report.traceIds],
    unknownGateCount,
    unresolvedEvidenceIds,
    updatedAtLabel: formatTimestamp(report.updatedAtMs),
    dimensionSummary,
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

function buildScanMetrics(
  timeline: TraceAuditTimelineItem[],
  timelineTruncated: boolean,
  presentation: Record<string, unknown>,
): TraceAuditScanMetric[] {
  const timestamps = timeline
    .map((item) => item.createdAtMs)
    .filter((value): value is number => value !== null)
    .sort((left, right) => left - right);
  const hasBoundaries = !timelineTruncated
    && timestamps.length >= 2
    && timestamps[0] !== timestamps[timestamps.length - 1];
  const durationMs = hasBoundaries ? timestamps[timestamps.length - 1] - timestamps[0] : 0;
  const hasPresentation = Object.keys(presentation).length > 0;
  const expectedStageCount = finiteNumber(presentation.expectedStageCount);
  const recordedReceiptIds = strings(presentation.recordedStageReceiptEvidenceIds);
  const receiptAvailable = hasPresentation
    && expectedStageCount !== null
    && expectedStageCount > 0;
  return [{
    available: hasBoundaries,
    detail: hasBoundaries ? '由冻结时间线首尾边界计算' : '冻结时间线没有完整、不同的起止边界',
    key: 'duration',
    label: '持续时间',
    value: hasBoundaries ? formatDuration(durationMs) : '不可用',
  }, {
    available: true,
    detail: timelineTruncated ? '快照已截断，实际事件可能更多' : '报告内冻结的时间线事件',
    key: 'timeline',
    label: '冻结事件',
    value: timelineTruncated ? `${timeline.length}+` : String(timeline.length),
  }, {
    available: receiptAvailable,
    detail: receiptAvailable
      ? `结构化展示层预期 ${Math.round(expectedStageCount)} 个阶段；只统计已绑定 Evidence 的回执`
      : '没有冻结大于 0 的权威阶段预期，不能把 0 当作“没有回执”',
    key: 'receipts',
    label: '阶段回执',
    value: receiptAvailable ? `${recordedReceiptIds.length}/${Math.round(expectedStageCount)}` : '不可用',
  }];
}

function buildFailureAttribution(
  source: Record<string, unknown>,
  evidenceById: Map<string, TraceAuditEvidence>,
  evidenceAliases: Record<string, string>,
): TraceAuditFailureAttribution {
  const declaredPrimaryLayer = failureLayer(source.primaryLayer) ?? 'unknown';
  const rawByLayer = new Map<TraceFailureLayer, Record<string, unknown>>();
  records(source.layers).forEach((item) => {
    const layer = failureLayer(item.layer);
    if (layer && !rawByLayer.has(layer)) rawByLayer.set(layer, item);
  });

  let primaryAssigned = false;
  let claimDowngraded = false;
  const layers = TRACE_FAILURE_LAYERS.map(({ label, layer }) => {
    const raw = rawByLayer.get(layer) ?? {};
    const evidenceIds = uniqueStrings(strings(raw.evidenceIds));
    const requestedVerdict = failureVerdict(raw.verdict);
    const claimNeedsEvidence = ['primary', 'contributing', 'healthy'].includes(requestedVerdict);
    const supportedClaim = !claimNeedsEvidence
      || evidenceIds.some((evidenceId) => evidenceById.has(evidenceId));
    let verdict: TraceFailureVerdict = supportedClaim ? requestedVerdict : 'unknown';
    if (!supportedClaim) claimDowngraded = true;

    if (verdict === 'primary') {
      const agreesWithDeclaredPrimary = declaredPrimaryLayer === 'unknown'
        || declaredPrimaryLayer === layer;
      if (primaryAssigned || !agreesWithDeclaredPrimary) {
        verdict = 'unknown';
        claimDowngraded = true;
      } else {
        primaryAssigned = true;
      }
    }

    let explanation = aliasEvidenceIds(text(raw.explanation), evidenceAliases);
    if (!supportedClaim) {
      explanation = [
        explanation,
        '缺少可解析的冻结证据，因此这一层按“未知”显示。',
      ].filter(Boolean).join(' ');
    }
    if (!explanation) explanation = failureLayerFallback(verdict);

    return {
      evidenceIds,
      explanation,
      label,
      layer,
      verdict,
      verdictLabel: failureVerdictLabel(verdict),
    };
  });
  const primaryLayer = layers.find((item) => item.verdict === 'primary')?.layer ?? 'unknown';
  const fallbackSummary = Object.keys(source).length
    ? primaryLayer === 'unknown'
      ? '报告没有形成带冻结证据的主要故障层判断。'
      : `主要故障层是 ${layers.find((item) => item.layer === primaryLayer)?.label ?? primaryLayer}。`
    : '旧版报告未记录五层归因；以下五层均按“未知”显示。';
  const summary = claimDowngraded
    ? `${fallbackSummary} 缺少冻结证据或相互冲突的归因主张已按“未知”显示。`
    : aliasEvidenceIds(text(source.summary, fallbackSummary), evidenceAliases);
  return {
    layers,
    primaryLayer,
    summary,
  };
}

function failureLayer(value: unknown): TraceFailureLayer | null {
  const normalized = text(value);
  return TRACE_FAILURE_LAYERS.some((item) => item.layer === normalized)
    ? normalized as TraceFailureLayer
    : null;
}

function failureVerdict(value: unknown): TraceFailureVerdict {
  const normalized = text(value);
  return ['primary', 'contributing', 'healthy', 'unknown', 'not_applicable'].includes(normalized)
    ? normalized as TraceFailureVerdict
    : 'unknown';
}

function failureVerdictLabel(value: TraceFailureVerdict): string {
  return ({
    primary: '主要责任',
    contributing: '共同影响',
    healthy: '正常',
    unknown: '未知',
    not_applicable: '不适用',
  } satisfies Record<TraceFailureVerdict, string>)[value];
}

function failureLayerFallback(verdict: TraceFailureVerdict): string {
  if (verdict === 'not_applicable') return '本次失败不涉及这一层。';
  if (verdict === 'healthy') return '冻结证据显示这一层运行正常。';
  if (verdict === 'primary') return '报告将这一层判为主要故障层。';
  if (verdict === 'contributing') return '报告判定这一层共同影响了失败。';
  return '报告没有提供这一层的可验证判断。';
}

function buildEvidenceGaps(input: {
  causalLinks: TraceAuditCausalLink[];
  dimensions: TraceAuditDimension[];
  environmentLimitations: string[];
  environmentStatus: string;
  evidenceTruncated: boolean;
  requirements: TraceAuditRequirement[];
  requirementsSource: string;
  requirementsTruncated: boolean;
  sourceUnavailableCount: number;
  timeline: TraceAuditTimelineItem[];
  timelineTruncated: boolean;
  unresolvedEvidenceIds: string[];
}): string[] {
  const gaps: string[] = ['当前报告契约没有单独冻结阶段回执，不能把缺少记录写成 0 个。'];
  if (input.sourceUnavailableCount) gaps.push(`${input.sourceUnavailableCount} 个诊断对象没有源快照。`);
  if (!input.requirements.length || input.requirementsSource === 'unknown') gaps.push('未绑定稳定的用户要求集，无法逐条判断完成情况。');
  if (input.requirementsTruncated) gaps.push('需求快照已截断。');
  if (!input.timeline.length) gaps.push('没有冻结时间线，事件顺序与持续时间不可判断。');
  if (input.timelineTruncated) gaps.push('时间线快照已截断，不能确认完整起止边界。');
  if (!input.causalLinks.length) gaps.push('没有显式因果关联，不能把相邻事件当作因果。');
  if (input.environmentStatus !== 'complete') gaps.push('环境快照不完整，当前证据不足以保证复现。');
  input.environmentLimitations.forEach((item) => gaps.push(item));
  const insufficientDimensions = input.dimensions.filter((item) => (
    item.applicability !== 'not_applicable' && item.score === null
  )).length;
  if (insufficientDimensions) gaps.push(`${insufficientDimensions} 个评分维度缺少可验证指标。`);
  if (input.evidenceTruncated) gaps.push('Evidence 快照已截断。');
  if (input.unresolvedEvidenceIds.length) gaps.push(`${input.unresolvedEvidenceIds.length} 个证据引用没有在冻结目录中解析。`);
  return uniqueStrings(gaps);
}

function buildCauseChain(
  links: TraceAuditCausalLink[],
  evidenceAliases: Record<string, string>,
): TraceAuditCauseNode[] {
  if (!links.length) return [{
    alias: '',
    detail: '当前报告没有显式因果关联。',
    evidenceId: '',
    evidenceIds: [],
    label: '因果路径尚未冻结',
    relationAfter: '',
    relationConfidence: '',
    state: 'unverified',
    stateLabel: '待验证',
  }];
  const nodes: TraceAuditCauseNode[] = [];
  links.forEach((link) => {
    const from = causeNode(link.from, link.fromEvidenceId, evidenceAliases);
    const to = causeNode(link.to, link.toEvidenceId, evidenceAliases);
    const previous = nodes[nodes.length - 1];
    if (!previous || previous.evidenceId !== from.evidenceId) nodes.push(from);
    const relationOwner = nodes[nodes.length - 1];
    relationOwner.relationAfter = link.relationLabel;
    relationOwner.relationConfidence = link.confidenceLabel;
    nodes.push(to);
  });
  return nodes;
}

function buildPresentationCauseChain(
  rawNodes: Record<string, unknown>[],
  evidenceAliases: Record<string, string>,
): TraceAuditCauseNode[] {
  return rawNodes.map((item, index) => {
    const evidenceIds = strings(item.evidenceIds);
    const evidenceId = evidenceIds[0] ?? '';
    const state = text(item.status) === 'confirmed' ? 'confirmed' : 'unverified';
    return {
      alias: evidenceId ? evidenceAliases[evidenceId] ?? '' : '',
      detail: aliasEvidenceIds(text(item.detail), evidenceAliases),
      evidenceId,
      evidenceIds,
      label: aliasEvidenceIds(text(item.label, '未命名因果节点'), evidenceAliases),
      relationAfter: index < rawNodes.length - 1 ? '下一环' : '',
      relationConfidence: index < rawNodes.length - 1 ? (state === 'confirmed' ? '当前节点已确认' : '当前节点待验证') : '',
      state,
      stateLabel: state === 'confirmed' ? '已确认' : '待验证',
    };
  });
}

function formatPresentationFact(item: Record<string, unknown>, aliases: Record<string, string>): string {
  const fact = aliasEvidenceIds(text(item.fact), aliases);
  if (!fact) return '';
  const citations = strings(item.evidenceIds)
    .map((id) => `[${aliases[id] ?? '?'}]`)
    .filter((citation) => !fact.includes(citation))
    .join(' ');
  return citations ? `${fact} ${citations}` : fact;
}

function formatPresentationGap(item: Record<string, unknown>, aliases: Record<string, string>): string {
  const gap = aliasEvidenceIds(text(item.gap), aliases);
  if (!gap) return '';
  const consequence = aliasEvidenceIds(text(item.consequence), aliases);
  const howToObtain = aliasEvidenceIds(text(item.howToObtain), aliases);
  return [gap, consequence ? `影响：${consequence}` : '', howToObtain ? `补齐：${howToObtain}` : ''].filter(Boolean).join('；');
}

function causeNode(
  evidence: TraceAuditEvidence | null,
  evidenceId: string,
  aliases: Record<string, string>,
): TraceAuditCauseNode {
  const state = evidence ? 'confirmed' : 'unverified';
  return {
    alias: aliases[evidenceId] ?? '',
    detail: '',
    evidenceId,
    evidenceIds: evidenceId ? [evidenceId] : [],
    label: evidence ? evidenceScanLabel(evidence) : '引用的事件未在冻结证据中解析',
    relationAfter: '',
    relationConfidence: '',
    state,
    stateLabel: state === 'confirmed' ? '已确认' : '待验证',
  };
}

function evidenceScanLabel(evidence: TraceAuditEvidence): string {
  const state = ({
    completed: '完成',
    failed: '失败',
    stopped: '停止',
    cancelled: '取消',
  } as Record<string, string>)[evidence.status] ?? '状态变化';
  return `${evidence.targetLabel}记录到${state}事件`;
}

function buildPlainConclusion(input: {
  failureReason: string;
  findings: TraceAuditFinding[];
  hasFailure: boolean;
  status: string;
  summary: string;
  targetTitle: string;
}): string {
  if (input.status === 'generating') return '诊断仍在生成，目前还没有可验证结论。';
  if (input.status === 'failed') return '诊断过程失败，目前还没有形成可验证根因。';
  const primary = input.findings[0];
  if (primary) {
    const conclusion = conciseText(primary.conclusion, '直接原因见下方诊断发现');
    return input.hasFailure
      ? `${input.targetTitle}未完成；当前结构化证据支持的直接原因是：${conclusion}`
      : `诊断发现：${conclusion}`;
  }
  return `诊断已完成；${conciseText(input.summary || input.failureReason, '当前证据没有形成结构化发现')}`;
}

function buildStateBadges(input: {
  causalLinks: TraceAuditCausalLink[];
  evidence: TraceAuditEvidence[];
  findings: TraceAuditFinding[];
  gates: TraceAuditGate[];
  repairLifecycle: TraceAuditRepairLifecycle;
  reportStatus: string;
  timeline: TraceAuditTimelineItem[];
}): TraceAuditStateBadge[] {
  const failedEvidenceStatuses: Record<string, true> = {
    canceled: true,
    cancelled: true,
    error: true,
    failed: true,
    faulted: true,
  };
  const hasRecordedFailedEvidence = input.evidence.some((item) => failedEvidenceStatuses[item.status.toLowerCase()] === true)
    || input.timeline.some((item) => failedEvidenceStatuses[item.status.toLowerCase()] === true);
  const hasFailedGateEvidence = input.gates.some((gate) => (
    gate.status === 'failed'
    && gate.evidenceIds.length > 0
    && gate.evidenceIds.every((evidenceId) => input.evidence.some((item) => item.evidenceId === evidenceId))
  ));
  const hasFailedIncident = hasRecordedFailedEvidence || hasFailedGateEvidence;
  const incident: TraceAuditStateBadge = input.reportStatus === 'generating'
    ? { key: 'incident', label: '事故状态', value: '正在采集', tone: 'generating' }
    : hasFailedIncident
      ? { key: 'incident', label: '事故状态', value: '已确认失败', tone: 'failed' }
      : { key: 'incident', label: '事故状态', value: '未确认故障', tone: 'clear' };
  const diagnosis: TraceAuditStateBadge = input.reportStatus === 'generating'
    ? { key: 'diagnosis', label: '诊断状态', value: '进行中', tone: 'generating' }
    : input.reportStatus === 'failed'
      ? { key: 'diagnosis', label: '诊断状态', value: '未完成', tone: 'failed' }
      : input.findings.length
        ? { key: 'diagnosis', label: '诊断状态', value: input.causalLinks.length ? '已有直接结论' : '结论待验证', tone: input.causalLinks.length ? 'attention' : 'unverified' }
        : { key: 'diagnosis', label: '诊断状态', value: '证据不足', tone: 'unverified' };
  const authorization = input.repairLifecycle.authorizationState;
  const repair: TraceAuditStateBadge = authorization === 'authorized'
    ? { key: 'repair', label: '修复状态', value: input.repairLifecycle.verificationState === 'verified' ? '证据已复检' : '已授权', tone: input.repairLifecycle.verificationState === 'verified' ? 'clear' : 'attention' }
    : authorization === 'not_recorded'
      ? { key: 'repair', label: '修复状态', value: '未授权', tone: 'blocked' }
      : { key: 'repair', label: '修复状态', value: input.repairLifecycle.authorizationStateLabel, tone: 'blocked' };
  return [incident, diagnosis, repair];
}

function buildActions(repair: TraceAuditRepairLifecycle): TraceAuditAction[] {
  const authorized = repair.authorizationState === 'authorized';
  const verified = repair.verificationState === 'verified';
  const hasRepairTrace = Boolean(repair.repairTraceId);
  return [{
    description: authorized
      ? repair.writeAuthorityLabel
      : '由用户一次确认全磁盘、全部 Tools 与自动批准；操作系统权限仍是最终边界。',
    state: authorized ? repair.authorizationStateLabel : '等待用户确认',
    step: 1,
    title: '确认并启动修复',
    tone: authorized ? 'clear' : 'blocked',
  }, {
    description: '读取已持久化、不可变的修复 Trace 中已记录的修改与通过测试证据，由 AI Judge 进行复检；此步骤不会重跑命令或进行同案 Trace 回放。',
    state: hasRepairTrace ? '已有修复 Trace 证据' : '等待修复 Trace 证据',
    step: 2,
    title: '复检修复 Trace 证据',
    tone: verified && hasRepairTrace ? 'clear' : 'unverified',
  }, {
    description: '仅根据已绑定的 Trace / Eval 证据展示对照；不据此声称 source SHA 已验证或已执行回滚。',
    state: verified ? '已完成复检' : hasRepairTrace ? '已绑定修复 Trace' : '等待复检',
    step: 3,
    title: '证据对照',
    tone: verified && hasRepairTrace ? 'clear' : 'unverified',
  }];
}

function buildDimensionSummary(dimensions: TraceAuditDimension[]): string {
  const notApplicable = dimensions.filter((item) => item.applicability === 'not_applicable').length;
  const insufficient = dimensions.filter((item) => (
    item.applicability !== 'not_applicable' && item.score === null
  )).length;
  const measured = Math.max(0, dimensions.length - notApplicable - insufficient);
  const parts = [
    insufficient ? `${insufficient} 维证据不足` : '',
    notApplicable ? `${notApplicable} 维不适用` : '',
    measured ? `${measured} 维已有评分` : '',
  ].filter(Boolean);
  return `${dimensions.length} 维中 ${parts.join('、') || '尚无维度数据'}`;
}

function buildKnownFacts(input: {
  causalLinks: TraceAuditCausalLink[];
  evidence: TraceAuditEvidence[];
  reportStatus: string;
  targets: TraceAuditTarget[];
  timeline: TraceAuditTimelineItem[];
}): string[] {
  const facts = [
    `报告状态为“${reportStatusLabel(input.reportStatus)}”，覆盖 ${input.targets.length} 个对象。`,
    input.timeline.length ? `${input.timeline.length} 条时间线事件已冻结进报告。` : '',
    input.causalLinks.length ? `${input.causalLinks.length} 条因果关联由结构化结果显式提供。` : '',
    input.evidence.length ? `${input.evidence.length} 条公开 Evidence 可在附录核对。` : '',
  ].filter(Boolean);
  return facts.slice(0, 3);
}

function findingQuestionTitle(dimensionId: string, conclusion: string, confidence: string): string {
  const question = ({
    task_completion: '任务完成了吗？',
    evidence_diagnosis: '证据支持什么结论？',
    tool_runtime: '为什么失败？',
    context: '上下文在哪里断了？',
    room_collaboration: '协作在哪里失效？',
    memory_rag: '记忆或检索哪里出错？',
    efficiency: '时间耗在哪里？',
    repair_quality: '修复有效吗？',
  } as Record<string, string>)[dimensionId] ?? '发生了什么？';
  return `${question}——${conciseText(conclusion, '查看结构化结论')}（${confidence}）`;
}

function conciseText(value: string, fallback: string): string {
  const normalized = value.replace(/\s+/g, ' ').trim();
  return normalized && normalized.length <= 88 ? normalized : fallback;
}

function aliasEvidenceIds(value: string, aliases: Record<string, string>): string {
  let rendered = value;
  Object.entries(aliases).forEach(([evidenceId, alias]) => {
    if (rendered.includes(evidenceId)) rendered = rendered.split(evidenceId).join(`[${alias}]`);
  });
  return rendered;
}

function formatDuration(valueMs: number): string {
  const seconds = Math.max(0, Math.round(valueMs / 1000));
  if (seconds < 60) return `${seconds} 秒`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} 分钟`;
  const hours = Math.floor(minutes / 60);
  const remainder = minutes % 60;
  return remainder ? `${hours} 小时 ${remainder} 分钟` : `${hours} 小时`;
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
    comparisonReason: text(comparison.reason, verificationState === 'not_requested'
      ? '尚未授权修复，也没有修复 Trace 证据或 AI Judge 复检。'
      : '等待修复 Trace 中已记录的修改、通过测试证据和 AI Judge 复检。'),
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
    writeAuthorityLabel: authorization.writeAuthority === 'auto_approved_full_trust'
      ? '用户已确认全信任修复：全磁盘、全部 Tools 自动批准；操作系统权限仍是最终边界'
      : authorization.writeAuthority === 'model_arbitrated_full_trust'
        ? '旧版全信任交接：待审批操作由独立模型判定'
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
    unknown: '待确定',
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
    pending: '等待修复 Trace、测试证据与 AI Judge 复检',
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
