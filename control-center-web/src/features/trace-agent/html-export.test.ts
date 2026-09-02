import { describe, expect, it } from 'vitest';
import type { TraceDiagnosticReportV1 } from '@/contracts/generated/trace-diagnostic-report.v1';
import { buildTraceDiagnosticReportHtml } from './html-export';

describe('buildTraceDiagnosticReportHtml', () => {
  it('exports one self-contained engineering audit report from the persisted authority', () => {
    const html = buildTraceDiagnosticReportHtml(auditReportFixture(), { generatedAtMs: 300 });

    expect(html).toContain('<!doctype html>');
    expect(html).toContain('Trace 诊断 · 写入失败');
    expect(html).toContain('工程审计报告');
    expect(html).toContain('任务完成门槛未通过');
    expect(html).toContain('resource revision 已过期');
    expect(html).toContain('系统确定性');
    expect(html).toContain('AI 评审估计');
    expect(html).toContain('用户需求完成矩阵');
    expect(html).toContain('问题出在哪一层');
    expect(html).toContain('主要故障在 Tool / Runtime');
    expect(html).toContain('模板提示');
    expect(html).toContain('模型能力');
    expect(html).toContain('跨 Session / Agent 因果时间线');
    expect(html).toContain('写入目标文件');
    expect(html).toContain('workspace edit 返回 stale_snapshot');
    expect(html).toContain('Evidence 目录');
    expect(html).toContain('查看完整冻结时间线');
    expect(html).toContain('可复现环境快照');
    expect(html).toContain('修复授权状态');
    expect(html).toContain('修复前后 Trace / Eval 对照');
    expect(html).toContain('Host 沙盒测试证据');
    expect(html).toContain('passed · 1 次');
    expect(html).toContain('输入 fingerprint 不同，不能声称效果提升');
    expect(html).toContain('用户已确认全信任修复：全磁盘、全部 Tools 自动批准');
    expect(html).toContain('证据已复检');
    expect(html).toContain('不据此声称 source SHA 已验证或已执行回滚');
    expect(html).not.toContain('沙盒回放');
    expect(html).not.toContain('独立复验');
    expect(html).toContain('trace-report:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa');
    expect(html).toContain('a'.repeat(64));
    expect(html).not.toContain('<script src=');
    expect(html).not.toContain('http://');
    expect(html).not.toContain('https://');
    expect(html).not.toContain('PRIVATE_RAW_INSPECTION_DETAIL');

    const document = new DOMParser().parseFromString(html, 'text/html');
    expect(document.querySelectorAll('[data-dimension-id]')).toHaveLength(8);
    expect(document.querySelectorAll('.trace-audit__finding')).toHaveLength(1);
    expect(document.querySelector('.trace-audit__verdict')?.textContent).toContain('任务完成门槛未通过');
    expect([...document.querySelectorAll('.trace-audit__attribution-list > li')].map((item) => [
      item.getAttribute('data-layer'),
      item.getAttribute('data-verdict'),
    ])).toEqual([
      ['tool', 'primary'],
      ['skill', 'healthy'],
      ['template', 'unknown'],
      ['workflow', 'contributing'],
      ['model', 'not_applicable'],
    ]);
    expect(document.querySelector('.trace-audit__scan-layer .trace-audit__score-table')).toBeNull();
    expect(document.querySelector('.trace-audit__appendix .trace-audit__score-table')).not.toBeNull();
    expect(document.querySelector('script')).toBeNull();
  });

  it('escapes report-authored text instead of exporting executable markup', () => {
    const report = auditReportFixture();
    report.title = '<script>window.pwned=true</script>';
    const result = report.result as Record<string, unknown>;
    const presentation = result.presentation as Record<string, unknown>;
    const attribution = presentation.failureAttribution as Record<string, unknown>;
    attribution.summary = '<img src=x onerror=window.pwned=true>';
    const layers = attribution.layers as Array<Record<string, unknown>>;
    layers[0]!.explanation = '<script>window.layerPwned=true</script>';
    const html = buildTraceDiagnosticReportHtml(report);
    const document = new DOMParser().parseFromString(html, 'text/html');

    expect(document.querySelector('script')).toBeNull();
    expect(document.querySelector('h1')?.textContent).toBe('<script>window.pwned=true</script>');
    expect(document.body.textContent).toContain('<img src=x onerror=window.pwned=true>');
    expect(document.body.textContent).toContain('<script>window.layerPwned=true</script>');
  });

  it('keeps legacy repair authority labels readable', () => {
    const report = auditReportFixture();
    const authorization: unknown = report.repairLifecycle?.authorization;
    if (!authorization || typeof authorization !== 'object' || !('writeAuthority' in authorization)) {
      throw new Error('repair authorization fixture is missing');
    }

    authorization.writeAuthority = 'model_arbitrated_full_trust';
    expect(buildTraceDiagnosticReportHtml(report)).toContain('旧版全信任交接：待审批操作由独立模型判定');

    authorization.writeAuthority = 'per_action_required';
    expect(buildTraceDiagnosticReportHtml(report)).toContain('旧版交接：实际写入仍需逐次审批');
  });

  it('labels full-trust Session terminal tests without claiming a Host sandbox rerun', () => {
    const report = auditReportFixture();
    const verification = report.repairLifecycle?.verification;
    if (!verification) throw new Error('repair verification fixture is missing');
    verification.sandboxStatus = 'not_required';
    verification.sandboxedTestCount = 0;

    const html = buildTraceDiagnosticReportHtml(report);

    expect(html).toContain('全信任 Session 终态测试证据');
    expect(html).toContain('passed · 未在 Host 沙盒复跑');
    expect(html).not.toContain('<span>Host 沙盒测试证据</span><strong>not_required');
  });
});

function auditReportFixture(): TraceDiagnosticReportV1 {
  const dimensions = [
    'task_completion',
    'evidence_diagnosis',
    'tool_runtime',
    'context',
    'room_collaboration',
    'memory_rag',
    'efficiency',
    'repair_quality',
  ].map((dimensionId) => ({
    dimensionId,
    title: dimensionId,
    applicability: 'measured',
    authority: 'deterministic',
    score: 72,
    scoreMax: 100,
    metrics: [{ metricId: `${dimensionId}.metric`, label: '通过率', value: 0.72, unit: 'ratio' }],
    evidenceIds: ['evidence:source'],
    note: '冻结 Trace 计算结果',
  }));
  return {
    schemaVersion: 'rag-ime.trace-diagnostic-report.v1',
    reportId: `trace-report:${'a'.repeat(32)}`,
    revision: 2,
    status: 'completed',
    title: 'Trace 诊断 · 写入失败',
    diagnosticSessionId: 'agent:trace-diagnostic',
    targets: [{
      targetKey: 'session:source',
      kind: 'session',
      id: 'source',
      title: '写入失败的 Session',
      traceIds: ['trace:source'],
      sourceAvailable: true,
    }],
    traceIds: ['trace:source'],
    inspectionSha256: 'a'.repeat(64),
    inspection: {
      timeline: [{
        evidenceId: 'evidence:source',
        targetKey: 'session:source',
        kind: 'tool_result',
        status: 'failed',
        summary: 'workspace edit 返回 stale_snapshot。',
        sequence: 2,
        createdAtMs: 120,
        sourceRef: 'trace:source:span:edit',
        traceId: 'trace:source',
      }],
      evidence: [{
        evidenceId: 'evidence:source',
        targetKey: 'session:source',
        sourceKind: 'trace_span',
        sourceRef: 'trace:source:span:edit',
        status: 'failed',
        summary: 'workspace edit 返回 stale_snapshot。',
        createdAtMs: 120,
        traceId: 'trace:source',
      }, { summary: 'PRIVATE_RAW_INSPECTION_DETAIL' }],
      requirements: {
        source: 'user_input',
        items: [{
          requirementId: 'requirement:write',
          statement: '写入目标文件',
          targetKey: 'session:source',
          sourceRef: 'session:source:message:user',
          evidenceIds: ['evidence:source'],
        }],
        truncated: false,
      },
      environment: {
        capturedAtMs: 100,
        rubricVersion: 'trace-score-v1',
        targets: [{
          targetKey: 'session:source',
          sourceSha256: 'b'.repeat(64),
          modelProfile: 'codex',
          toolProfileVersion: 'control-center-v1',
          executionMode: 'per_action',
          policyRevision: 9,
          workspaceScopeSha256: 'c'.repeat(64),
          shellPolicyVersion: 'workspace-v2',
          runtimeKind: 'pi',
          runtimeGeneration: 3,
          traceInputFingerprints: [`sha256:${'d'.repeat(64)}`],
          traceStatuses: ['failed'],
        }],
        limitations: ['未冻结 Provider 服务端构建版本。'],
      },
      truncated: { timeline: false, evidence: false, traceIds: false },
      scorecard: {
        dimensions,
        hardGates: [],
        comparison: { eligible: false, status: 'incomparable', reason: '单个对象不可形成对照。' },
      },
    },
    result: {
      schemaVersion: 'rag-ime.trace-diagnostic-result.v1',
      summary: '写入使用了过期的资源版本。',
      hardGates: [{
        gateId: 'task_completion',
        status: 'failed',
        reason: '任务没有产生通过验证的文件。',
        evidenceIds: ['evidence:source'],
      }],
      judgeScores: [{
        dimensionId: 'context',
        score: 2,
        authority: 'ai_judge_estimate',
        explanation: '上下文大体完整，但资源版本过期。',
        evidenceIds: ['evidence:source'],
      }],
      requirementAssessments: [{
        requirementId: 'requirement:write',
        status: 'unsatisfied',
        owner: 'Workspace Writer',
        authority: 'ai_judge_estimate',
        evidenceIds: ['evidence:source'],
        note: '没有产生通过验证的文件。',
      }],
      causalLinks: [{
        linkId: 'causal:write-failed',
        fromEvidenceId: 'evidence:source',
        toEvidenceId: 'evidence:source',
        relation: 'triggered',
        authority: 'ai_judge_estimate',
        confidence: 'high',
        explanation: '写入尝试触发 stale_snapshot。',
      }],
      findings: [{
        findingId: 'finding:stale-revision',
        dimensionId: 'tool_runtime',
        severity: 'high',
        observation: 'workspace edit 返回 stale_snapshot。',
        hypothesis: 'Agent 在批准等待期间继续使用旧快照。',
        conclusion: 'resource revision 已过期。',
        confidence: 'high',
        evidenceIds: ['evidence:source'],
        candidateRepair: '重新读取目标文件，再生成 edit。',
        verification: '新 Trace 中 edit 成功且测试通过。',
      }],
      presentation: {
        headline: '写入没有完成；Tool 使用了过期快照。',
        impact: '目标文件没有产生可验证的新版本。',
        primaryFindingId: 'finding:stale-revision',
        failureAttribution: {
          primaryLayer: 'tool',
          summary: '主要故障在 Tool / Runtime；工作流也共同影响了失败。',
          layers: [
            { layer: 'tool', verdict: 'primary', explanation: '写入 Tool 返回 stale_snapshot。', evidenceIds: ['evidence:source'] },
            { layer: 'skill', verdict: 'healthy', explanation: 'Skill 已要求重新读取后写入。', evidenceIds: ['evidence:source'] },
            { layer: 'template', verdict: 'unknown', explanation: '没有冻结模板提示证据。', evidenceIds: [] },
            { layer: 'workflow', verdict: 'contributing', explanation: '批准等待后没有刷新快照。', evidenceIds: ['evidence:source'] },
            { layer: 'model', verdict: 'not_applicable', explanation: '本次失败由确定性 Tool 错误解释。', evidenceIds: [] },
          ],
        },
        knownFacts: [{ fact: '写入 Tool 返回 stale_snapshot。', evidenceIds: ['evidence:source'] }],
        evidenceGaps: [],
        causalNodes: [],
        expectedStageCount: 1,
        recordedStageReceiptEvidenceIds: [],
      },
    },
    repairLifecycle: {
      authorization: {
        state: 'authorized',
        authorizationKind: 'repair_handoff',
        writeAuthority: 'auto_approved_full_trust',
        authorizationId: 'repair-authorization:1',
        findingId: 'finding:stale-revision',
        sourceScope: 'session:source',
        sourceTraceId: 'trace:source',
        failureRef: 'evidence:source',
        repairSessionId: 'agent:repair',
        authorizedAtMs: 220,
      },
      verification: {
        state: 'verified',
        repairReceiptId: 'repair-receipt:1',
        repairTraceId: 'trace:repair',
        evalRunId: 'eval:repair',
        testStatus: 'passed',
        sandboxStatus: 'passed',
        sandboxedTestCount: 1,
        verifiedAtMs: 280,
        comparison: {
          status: 'incomparable',
          reason: '输入 fingerprint 不同，不能声称效果提升。',
          sourceStatus: 'failed',
          repairStatus: 'completed',
          sourceFingerprint: `sha256:${'d'.repeat(64)}`,
          repairFingerprint: `sha256:${'e'.repeat(64)}`,
          beforeMetrics: { task_completion: 0 },
          afterMetrics: { task_success: 1 },
          deltas: {},
        },
      },
    },
    failureReason: '',
    createdAtMs: 100,
    updatedAtMs: 200,
  } as unknown as TraceDiagnosticReportV1;
}
