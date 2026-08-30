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
    expect(html).toContain('跨 Session / Agent 因果时间线');
    expect(html).toContain('写入目标文件');
    expect(html).toContain('workspace edit 返回 stale_snapshot');
    expect(html).toContain('Evidence 目录');
    expect(html).toContain('查看完整冻结时间线');
    expect(html).toContain('可复现环境快照');
    expect(html).toContain('修复授权状态');
    expect(html).toContain('修复前后 Trace / Eval 对照');
    expect(html).toContain('沙盒回放');
    expect(html).toContain('passed · 1 次');
    expect(html).toContain('输入 fingerprint 不同，不能声称效果提升');
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
    expect(document.querySelector('script')).toBeNull();
  });

  it('escapes report-authored text instead of exporting executable markup', () => {
    const report = auditReportFixture();
    report.title = '<script>window.pwned=true</script>';
    const html = buildTraceDiagnosticReportHtml(report);
    const document = new DOMParser().parseFromString(html, 'text/html');

    expect(document.querySelector('script')).toBeNull();
    expect(document.querySelector('h1')?.textContent).toBe('<script>window.pwned=true</script>');
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
    },
    repairLifecycle: {
      authorization: {
        state: 'authorized',
        authorizationKind: 'repair_handoff',
        writeAuthority: 'per_action_required',
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
