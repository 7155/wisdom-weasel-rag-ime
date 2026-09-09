import { describe, expect, it } from 'vitest';
import type { TraceDiagnosticReportV1 } from '@/contracts/generated/trace-diagnostic-report.v1';
import { buildTraceDiagnosticReportHtml } from './html-export';
import { buildTraceAuditReportModel } from './report-model';

describe('Trace diagnostic report reading contract', () => {
  it('derives only supported scan metrics and keeps unavailable receipts honest', () => {
    const report = reportFixture();
    (report.result as Record<string, unknown>).judgeScores = [{
      dimensionId: 'task_completion',
      score: 0,
      authority: 'ai_judge_estimate',
      explanation: '任务已经失败，但没有产物回执。',
      evidenceIds: ['evidence:task-failed'],
    }];
    const model = buildTraceAuditReportModel(report);

    expect(model.metrics).toEqual([
      expect.objectContaining({ key: 'duration', value: '11 分钟', available: true }),
      expect.objectContaining({ key: 'timeline', value: '2', available: true }),
      expect.objectContaining({ key: 'receipts', value: '不可用', available: false }),
    ]);
    expect(model.evidence.map((item) => item.alias)).toEqual(['E1', 'E2']);
    expect(model.evidenceGaps).toContain('当前报告契约没有单独冻结阶段回执，不能把缺少记录写成 0 个。');
    expect(model.failureAttribution.primaryLayer).toBe('unknown');
    expect(model.failureAttribution.layers.map((item) => [item.layer, item.label, item.verdict])).toEqual([
      ['tool', 'Tool / Runtime', 'unknown'],
      ['skill', 'Skill', 'unknown'],
      ['template', '模板提示', 'unknown'],
      ['workflow', '工作流', 'unknown'],
      ['model', '模型能力', 'unknown'],
    ]);
    expect(model.failureAttribution.summary).toContain('旧版报告未记录五层归因');
    expect(model.dimensions[0]).toEqual(expect.objectContaining({
      applicabilityLabel: '待确定',
      scoreText: '无系统评分',
      judgeScore: 0,
    }));

    const incomplete = reportFixture();
    const inspection = incomplete.inspection as { timeline: unknown[] };
    inspection.timeline = inspection.timeline.slice(0, 1);
    expect(buildTraceAuditReportModel(incomplete).metrics[0]).toEqual(expect.objectContaining({
      value: '不可用',
      available: false,
    }));
  });

  it('confirms incidents only from recorded failure evidence or resolved failed gates', () => {
    const completedEvidence = reportFixture();
    const inspection = completedEvidence.inspection as Record<string, unknown>;
    inspection.timeline = (inspection.timeline as Array<Record<string, unknown>>).map((item) => ({
      ...item,
      status: 'completed',
    }));
    inspection.evidence = (inspection.evidence as Array<Record<string, unknown>>).map((item) => ({
      ...item,
      status: 'completed',
    }));
    const result = completedEvidence.result as Record<string, unknown>;
    result.findings = [{
      ...(result.findings as Array<Record<string, unknown>>)[0],
      confidence: 'high',
      evidenceIds: ['evidence:runtime-timeout'],
      severity: 'critical',
    }];

    expect(buildTraceAuditReportModel(completedEvidence).stateBadges[0]).toEqual(expect.objectContaining({
      tone: 'clear',
      value: '未确认故障',
    }));

    const failedGate = reportFixture();
    const failedGateInspection = failedGate.inspection as Record<string, unknown>;
    failedGateInspection.timeline = (failedGateInspection.timeline as Array<Record<string, unknown>>).map((item) => ({
      ...item,
      status: 'completed',
    }));
    failedGateInspection.evidence = (failedGateInspection.evidence as Array<Record<string, unknown>>).map((item) => ({
      ...item,
      status: 'completed',
    }));
    (failedGate.result as Record<string, unknown>).hardGates = [{
      evidenceIds: ['evidence:runtime-timeout'],
      gateId: 'gate:completion',
      reason: '任务结果没有完成。',
      status: 'failed',
    }];

    expect(buildTraceAuditReportModel(failedGate).stateBadges[0]).toEqual(expect.objectContaining({
      tone: 'failed',
      value: '已确认失败',
    }));
    expect(buildTraceAuditReportModel(reportFixture()).stateBadges[0]).toEqual(expect.objectContaining({
      tone: 'failed',
      value: '已确认失败',
    }));
  });

  it('prefers the governed presentation layer without inventing missing stage receipts', () => {
    const report = reportFixture();
    const result = report.result as Record<string, unknown>;
    result.presentation = {
      headline: '记忆整理任务失败；直接原因是会话结算超时。',
      impact: '本轮没有生成可验证的记忆产物。',
      primaryFindingId: 'finding:settlement-timeout',
      failureAttribution: {
        primaryLayer: 'tool',
        summary: '主要故障在 Tool / Runtime；工作流也放大了影响。',
        layers: [
          { layer: 'tool', verdict: 'primary', explanation: 'Runtime 命令超时。', evidenceIds: ['evidence:runtime-timeout'] },
          { layer: 'skill', verdict: 'healthy', explanation: 'Skill 已正确要求检查 Runtime。', evidenceIds: ['evidence:runtime-timeout'] },
          { layer: 'template', verdict: 'unknown', explanation: '没有冻结模板提示证据。', evidenceIds: [] },
          { layer: 'workflow', verdict: 'contributing', explanation: '流程没有及时停止等待。', evidenceIds: ['evidence:task-failed'] },
          { layer: 'model', verdict: 'not_applicable', explanation: '确定性 Runtime 超时已经解释失败。', evidenceIds: [] },
        ],
      },
      knownFacts: [{ fact: 'Runtime 命令已经超时。', evidenceIds: ['evidence:runtime-timeout'] }],
      evidenceGaps: [{ gap: '上游原因未知。', consequence: '无法定位更早故障点。', howToObtain: '补采 Runtime 上游 Trace。' }],
      causalNodes: [{ label: '请求记忆模型', detail: '模型请求已经发出。', status: 'confirmed', evidenceIds: ['evidence:runtime-timeout'] }, { label: '上游响应', detail: '没有冻结响应。', status: 'unverified', evidenceIds: [] }],
      expectedStageCount: 4,
      recordedStageReceiptEvidenceIds: [],
    };

    const model = buildTraceAuditReportModel(report);
    expect(model.plainConclusion).toBe('记忆整理任务失败；直接原因是会话结算超时。');
    expect(model.impact).toBe('本轮没有生成可验证的记忆产物。');
    expect(model.knownFacts).toEqual(['Runtime 命令已经超时。 [E1]']);
    expect(model.evidenceGaps).toEqual(['上游原因未知。；影响：无法定位更早故障点。；补齐：补采 Runtime 上游 Trace。']);
    expect(model.causeChain.map((node) => [node.label, node.state])).toEqual([
      ['请求记忆模型', 'confirmed'],
      ['上游响应', 'unverified'],
    ]);
    expect(model.metrics[2]).toEqual(expect.objectContaining({ value: '0/4', available: true }));
    expect(model.failureAttribution.primaryLayer).toBe('tool');
    expect(model.failureAttribution.layers.map((item) => [item.label, item.verdictLabel])).toEqual([
      ['Tool / Runtime', '主要责任'],
      ['Skill', '正常'],
      ['模板提示', '未知'],
      ['工作流', '共同影响'],
      ['模型能力', '不适用'],
    ]);
    expect(model.failureAttribution.layers[0]?.evidenceIds).toEqual(['evidence:runtime-timeout']);

    const presentationRecord = result.presentation as Record<string, unknown>;
    const attributionRecord = presentationRecord.failureAttribution as Record<string, unknown>;
    const attributionLayers = attributionRecord.layers as Array<Record<string, unknown>>;
    attributionLayers[0]!.evidenceIds = ['evidence:not-frozen'];
    const unsupportedAttributionModel = buildTraceAuditReportModel(report);
    expect(unsupportedAttributionModel.failureAttribution.primaryLayer).toBe('unknown');
    expect(unsupportedAttributionModel.failureAttribution.layers[0]).toEqual(expect.objectContaining({ verdict: 'unknown' }));
    expect(unsupportedAttributionModel.failureAttribution.summary).toContain('缺少冻结证据');
    attributionLayers[0]!.evidenceIds = ['evidence:runtime-timeout'];

    presentationRecord.expectedStageCount = 0;
    expect(buildTraceAuditReportModel(report).metrics[2]).toEqual(expect.objectContaining({
      value: '不可用',
      available: false,
    }));
    presentationRecord.expectedStageCount = 4;

    const html = buildTraceDiagnosticReportHtml(report);
    expect(html).toContain('记忆整理任务失败；直接原因是会话结算超时。');
    expect(html).toContain('本轮没有生成可验证的记忆产物。');
    expect(html).toContain('<dd>0/4</dd>');
    expect(html).toContain('Runtime 命令已经超时。 [E1]');
    const htmlDocument = new DOMParser().parseFromString(html, 'text/html');
    expect([...htmlDocument.querySelectorAll('.trace-audit__attribution-list > li')].map((item) => [
      item.getAttribute('data-layer'),
      item.getAttribute('data-verdict'),
      item.querySelector('strong')?.textContent,
      item.querySelector('.trace-audit__attribution-label span')?.textContent,
    ])).toEqual(model.failureAttribution.layers.map((item) => [
      item.layer,
      item.verdict,
      item.label,
      item.verdictLabel,
    ]));
  });

  it('exports the scan path first and moves all deep evidence into one collapsed appendix', () => {
    const html = buildTraceDiagnosticReportHtml(reportFixture(), { generatedAtMs: 700_000 });
    const document = new DOMParser().parseFromString(html, 'text/html');
    const report = document.querySelector('.trace-audit');
    const appendix = document.querySelector('details.trace-audit__appendix');

    expect(report).not.toBeNull();
    expect(appendix).not.toBeNull();
    expect(appendix?.hasAttribute('open')).toBe(false);
    expect(report?.textContent).toContain('11 分钟');
    expect(report?.textContent).toContain('阶段回执');
    expect(report?.textContent).toContain('不可用');
    expect(report?.textContent).toContain('已知事实');
    expect(report?.textContent).toContain('证据缺口');
    expect(report?.textContent).toContain('问题出在哪一层');
    expect(report?.textContent).toContain('Tool / Runtime');
    expect(report?.textContent).toContain('模板提示');
    expect(report?.textContent).toContain('模型能力');
    expect(report?.textContent).toContain('下一步怎么做');
    expect(report?.textContent).toContain('发现了什么，为什么这样判断');
    expect(report?.textContent).toContain('[E1]');
    expect(report?.textContent).toContain('settlement（会话结算）');
    expect(appendix?.textContent).toContain('完整时间线');
    expect(appendix?.textContent).toContain('环境快照');
    expect(appendix?.textContent).toContain('八维评分明细');
    expect(appendix?.textContent).toContain('Evidence 目录');
    expect(appendix?.textContent).toContain('需求矩阵');
    expect(appendix?.textContent).toContain('修复对照');

    const scanLayer = document.querySelector('.trace-audit__scan-layer');
    expect(scanLayer?.textContent).not.toContain('evidence:runtime-timeout');
    expect(scanLayer?.textContent).not.toContain('11 分钟');
    expect(scanLayer?.textContent).toContain('未记录关注方向');
    expect(scanLayer?.textContent).toContain('尚无同条件的原版 / 候选对照');
    expect(scanLayer?.querySelector('.trace-audit__attribution')).toBeNull();
    expect(appendix?.textContent).toContain('11 分钟');
    expect(appendix?.textContent).toContain('阶段回执');
    expect(appendix?.textContent).toContain('evidence:runtime-timeout');

    const scanOrder = [
      '#trace-reading-objective',
      '#trace-reading-conclusion',
      '#trace-reading-findings',
      '#trace-reading-changes',
      '#trace-reading-validation',
      '#trace-reading-decision',
    ].map((selector) => document.querySelector(selector));
    expect(scanOrder.every(Boolean)).toBe(true);
    scanOrder.slice(0, -1).forEach((element, index) => {
      const next = scanOrder[index + 1];
      expect(element && next ? element.compareDocumentPosition(next) & Node.DOCUMENT_POSITION_FOLLOWING : 0).toBeTruthy();
    });

    document.querySelectorAll('[aria-labelledby]').forEach((element) => {
      const id = element.getAttribute('aria-labelledby');
      expect(id).toMatch(/^trace-(audit|reading)-[a-z0-9-]+$/);
      expect(document.getElementById(id ?? '')).not.toBeNull();
    });
  });

  it('restores the persisted same-case Keep decision after report reload', () => {
    const report = reportFixture();
    report.repairLifecycle = {
      authorization: {
        state: 'authorized',
        authorizationKind: 'repair_handoff',
        writeAuthority: 'auto_approved_full_trust',
        authorizationId: 'repair-authorization:1',
        findingId: 'finding:settlement-timeout',
        sourceScope: 'session:memory',
        sourceTraceId: 'trace:memory',
        failureRef: 'evidence:runtime-timeout',
        repairSessionId: 'agent:repair:1',
        authorizedAtMs: 700_000,
      },
      verification: {
        state: 'verified',
        repairReceiptId: 'repair-receipt:1',
        repairTraceId: 'trace:repair:1',
        evalRunId: 'eval:repair:1',
        verificationReceiptId: 'trace-verification:1',
        replayCaseId: 'replay-case:1',
        decision: 'kept',
        testStatus: 'passed',
        sandboxStatus: 'passed',
        sandboxedTestCount: 1,
        verifiedAtMs: 710_000,
        comparison: {
          status: 'incomparable',
          reason: 'AI Judge comparison is supplemental.',
          sourceStatus: 'failed',
          repairStatus: 'completed',
          sourceFingerprint: `sha256:${'1'.repeat(64)}`,
          repairFingerprint: `sha256:${'2'.repeat(64)}`,
          beforeMetrics: {},
          afterMetrics: {},
          deltas: {},
        },
      },
    } as TraceDiagnosticReportV1['repairLifecycle'];

    const model = buildTraceAuditReportModel(report);
    expect(model.repairLifecycle.verificationReceiptId).toBe('trace-verification:1');
    expect(model.repairLifecycle.replayCaseId).toBe('replay-case:1');
    expect(model.repairLifecycle.decision).toBe('kept');
    expect(buildTraceDiagnosticReportHtml(report)).toContain('Keep');
    expect(buildTraceDiagnosticReportHtml(report)).toContain('trace-verification:1');
  });
});

function reportFixture(): TraceDiagnosticReportV1 {
  const evidenceId = 'evidence:runtime-timeout';
  const nextEvidenceId = 'evidence:task-failed';
  const dimensions = [
    'task_completion',
    'evidence_diagnosis',
    'tool_runtime',
    'context',
    'room_collaboration',
    'memory_rag',
    'efficiency',
    'repair_quality',
  ].map((dimensionId, index) => ({
    dimensionId,
    title: dimensionId,
    applicability: index === 4 ? 'not_applicable' : 'unknown',
    authority: 'unknown',
    score: null,
    scoreMax: 100,
    metrics: [],
    evidenceIds: [],
    note: '证据不足',
  }));
  return {
    schemaVersion: 'rag-ime.trace-diagnostic-report.v1',
    reportId: 'trace-report:plain-language',
    revision: 2,
    status: 'completed',
    title: '记忆整理任务',
    diagnosticSessionId: 'agent:trace-diagnostic',
    targets: [{
      targetKey: 'session:memory',
      kind: 'session',
      id: 'memory',
      title: '记忆整理任务',
      traceIds: ['trace:memory'],
      sourceAvailable: false,
    }],
    traceIds: ['trace:memory'],
    inspectionSha256: 'a'.repeat(64),
    inspection: {
      timeline: [{
        evidenceId,
        targetKey: 'session:memory',
        kind: 'runtime_command',
        status: 'failed',
        summary: 'Runtime Host 的 session.settlement.get 命令超时。',
        sequence: 1,
        createdAtMs: 0,
        sourceRef: 'trace:memory:runtime',
        traceId: 'trace:memory',
      }, {
        evidenceId: nextEvidenceId,
        targetKey: 'session:memory',
        kind: 'session_result',
        status: 'failed',
        summary: '记忆整理任务失败，产物不可验证。',
        sequence: 2,
        createdAtMs: 660_000,
        sourceRef: 'trace:memory:result',
        traceId: 'trace:memory',
      }],
      evidence: [{
        evidenceId,
        targetKey: 'session:memory',
        sourceKind: 'trace_span',
        sourceRef: 'trace:memory:runtime',
        status: 'failed',
        summary: 'Runtime Host 的 session.settlement.get 命令超时。',
        createdAtMs: 0,
        traceId: 'trace:memory',
      }, {
        evidenceId: nextEvidenceId,
        targetKey: 'session:memory',
        sourceKind: 'trace_span',
        sourceRef: 'trace:memory:result',
        status: 'failed',
        summary: '记忆整理任务失败，产物不可验证。',
        createdAtMs: 660_000,
        traceId: 'trace:memory',
      }],
      requirements: { source: 'unknown', items: [], truncated: false },
      environment: { capturedAtMs: 0, rubricVersion: 'trace-score-v1', targets: [], limitations: [] },
      truncated: { timeline: false, evidence: false, traceIds: false },
      scorecard: { dimensions, hardGates: [], comparison: { eligible: false, status: 'unknown', reason: '没有修复 Trace 证据。' } },
    },
    result: {
      schemaVersion: 'rag-ime.trace-diagnostic-result.v1',
      summary: '记忆整理任务失败，直接原因是 Runtime Host 命令超时；上游原因未知。',
      hardGates: [],
      judgeScores: [],
      requirementAssessments: [],
      causalLinks: [{
        linkId: 'runtime-to-failure',
        fromEvidenceId: evidenceId,
        toEvidenceId: nextEvidenceId,
        relation: 'caused',
        authority: 'ground_truth',
        confidence: 'medium',
        explanation: '冻结 Trace 明确记录命令超时后任务失败。',
      }],
      findings: [{
        findingId: 'finding:settlement-timeout',
        dimensionId: 'tool_runtime',
        severity: 'high',
        observation: 'Runtime Host 命令超时，任务没有生成可验证产物。',
        hypothesis: '上游服务未及时返回，但当前 Trace 没有冻结上游证据。',
        conclusion: 'settlement（会话结算）请求超时。',
        confidence: 'medium',
        evidenceIds: [evidenceId, nextEvidenceId],
        candidateRepair: '授权后完成最小修复，并保留修改与测试证据。',
        verification: '由 AI Judge 复检修复 Trace 中已记录的修改与通过测试证据。',
      }],
    },
    repairLifecycle: null,
    failureReason: '',
    createdAtMs: 0,
    updatedAtMs: 660_000,
  } as unknown as TraceDiagnosticReportV1;
}
