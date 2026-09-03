import { describe, expect, it, vi } from 'vitest';
import type { AgentLabExperimentV1 as EvalLabExperiment } from '@/contracts/generated/agent-lab-experiment.v1';
import {
  buildEvalLabExperimentAuditBlob,
  buildEvalLabExperimentAuditHtml,
  createEvalLabExperimentAuditDownload,
} from './experiment-audit-html';

describe('Eval Lab per-experiment engineering audit export', () => {
  it('exports a self-contained audit with a result-first reading order', () => {
    const html = buildEvalLabExperimentAuditHtml(experimentFixture(), {
      osOrigin: 'PAWOS / Agent Lab / Validation',
      evidence: [{
        runId: 'candidate-run',
        relation: 'candidate',
        title: 'Candidate public receipt',
        status: 'completed',
        evidenceKind: 'transcript_and_report',
        summary: 'Candidate reached the verified terminal state.',
        refs: ['receipt:candidate', 'report:sha256:ffff'],
      }],
      traces: [{
        traceId: 'trace:candidate:1',
        status: 'completed',
        summary: 'The workflow entered the verified terminal state.',
        evidenceRefs: ['trace-span:terminal'],
      }],
    }, { generatedAtMs: 1_000 });

    expect(html).toContain('<!doctype html>');
    expect(html).toContain('<style>');
    expect(html).toContain('Agent Lab · 单轮评测报告');
    expect(html).toContain('执行摘要');
    expect(html).toContain('本轮变更');
    expect(html).toContain('核心结果');
    expect(html).toContain('结果范围');
    expect(html).toContain('结果对比');
    expect(html).toContain('评测方法与数据');
    expect(html).toContain('EnterpriseOps-Gym');
    expect(html).toContain('Agent 必须遵守');
    expect(html).toContain('为什么这样改');
    expect(html).toContain('跨实体任务需要终态核验');
    expect(html).toContain('具体怎么改');
    expect(html).toContain('直接执行');
    expect(html).toContain('状态合同');
    expect(html).toContain('证据索引');
    expect(html).toContain('receipt:baseline');
    expect(html).toContain('trace:candidate:1');
    expect(html).toContain('任务完成率');
    expect(html).toContain('50.00%');
    expect(html).toContain('100.00%');
    expect(html).toContain('提高 50.00 个百分点');
    expect(html).toContain('缩短 20.00 秒');
    expect(html).toContain('验收标准');
    expect(html).toContain('temporary database cleanup = 100%');
    expect(html).toContain('保留新方案');
    expect(html).toContain('来源');
    expect(html).toContain('PAWOS / Agent Lab / 调优数据');

    const document = new DOMParser().parseFromString(html, 'text/html');
    expect(document.querySelector('[data-finding-tone="confirmed"]')).not.toBeNull();
    expect(document.querySelector('[data-finding-tone="attention"]')).not.toBeNull();
    expect(document.querySelectorAll('.eval-lab-audit__finding-grid')).toHaveLength(1);
    expect(document.querySelector('section.eval-lab-audit__finding-grid')).toBeNull();
    expect(document.querySelector('section.eval-lab-audit__findings')).toBeNull();
    expect(document.body.textContent).not.toContain('红色表示');

    const summaryIndex = html.indexOf('执行摘要');
    const metricsIndex = html.indexOf('结果对比');
    const changesIndex = html.indexOf('变更说明');
    const findingsIndex = html.indexOf('检查结论');
    const datasetIndex = html.indexOf('评测方法与数据');
    const evidenceIndex = html.indexOf('证据索引');
    expect(summaryIndex).toBeGreaterThan(-1);
    expect(summaryIndex).toBeLessThan(metricsIndex);
    expect(metricsIndex).toBeLessThan(changesIndex);
    expect(changesIndex).toBeLessThan(findingsIndex);
    expect(findingsIndex).toBeLessThan(datasetIndex);
    expect(datasetIndex).toBeLessThan(evidenceIndex);
    expect(document.querySelector('script')).toBeNull();
    expect(document.querySelector('link')).toBeNull();
    expect(document.querySelector('[src]')).toBeNull();
  });

  it('marks missing Trace as historical report-only and escapes authored text', () => {
    const experiment = experimentFixture();
    experiment.experimentId = 'custom-audit-v1';
    experiment.vertical = 'other';
    experiment.title = '<script>window.pwned=true</script>';
    experiment.factors[0].reason = '<img src=x onerror=window.pwned=true>';

    const html = buildEvalLabExperimentAuditHtml(experiment, {
      evidence: [{
        runId: 'candidate-run',
        relation: 'candidate',
        status: 'failed',
        evidenceKind: 'report_only',
        summary: 'Historical receipt without a Trace.',
        refs: ['receipt:candidate'],
      }],
    });
    const document = new DOMParser().parseFromString(html, 'text/html');

    expect(document.body.textContent).toContain('历史记录只有报告');
    expect(document.body.textContent).toContain('没有可用 Trace 摘要');
    expect(document.querySelector('script')).toBeNull();
    expect(document.querySelector('h1')?.textContent).toBe('<script>window.pwned=true</script>');
    expect(document.body.textContent).toContain('<img src=x onerror=window.pwned=true>');
  });

  it('exports the strict source-binding contract for a RAG experiment', () => {
    const experiment = {
      ...experimentFixture(),
      experimentId: 'enterprise-rag-answer-evidence-v1',
      title: 'Enterprise RAG answer evidence',
      vertical: 'enterprise-rag',
      evaluationKind: 'answer_evidence',
    } as EvalLabExperiment;

    const html = buildEvalLabExperimentAuditHtml(experiment, {});

    expect(html).toContain('只依据可回跳的业务原文');
    expect(html).toContain('禁止把 room/session/event ID 冒充 sourceId/chunkId');
    expect(html).toContain('没有原文正文与真实绑定时必须拒答');
  });

  it('deduplicates snake_case and camelCase aliases into one readable metric row', () => {
    const experiment = experimentFixture();
    experiment.baseline.metrics = { businessToolCalls: 47 };
    experiment.candidate.metrics = { businessToolCalls: 64 };
    experiment.comparison.metricDeltas = [{ metric: 'business_tool_calls', before: 47, after: 64, delta: 17 }];

    const html = buildEvalLabExperimentAuditHtml(experiment);
    const document = new DOMParser().parseFromString(html, 'text/html');
    const metricLabels = [...document.querySelectorAll('.trace-audit__comparison-table-wrap tbody th')]
      .map((node) => node.textContent);

    expect(metricLabels).toEqual(['业务工具调用']);
    expect(document.body.textContent).not.toContain('business tool calls');
  });

  it('builds a typed Blob and a disposable download URL', () => {
    const createObjectURL = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:eval-lab-audit');
    const revokeObjectURL = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined);
    const experiment = experimentFixture();

    const blob = buildEvalLabExperimentAuditBlob(experiment, {});
    const download = createEvalLabExperimentAuditDownload(experiment, {});

    expect(blob).toBeInstanceOf(Blob);
    expect(blob.type).toBe('text/html;charset=utf-8');
    expect(download.href).toBe('blob:eval-lab-audit');
    expect(download.download).toBe('agent-lab-audit-enterpriseops-csm-v2.html');
    expect(download.blob.type).toBe('text/html;charset=utf-8');

    download.revoke();
    download.revoke();
    expect(createObjectURL).toHaveBeenCalledTimes(1);
    expect(revokeObjectURL).toHaveBeenCalledTimes(1);
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:eval-lab-audit');
  });
});

function experimentFixture(): EvalLabExperiment {
  return {
    schemaVersion: 'rag-ime.agent-lab-experiment.v1',
    experimentId: 'enterpriseops-csm-v2',
    revisionSha256: 'a'.repeat(64),
    title: 'EnterpriseOps CSM workflow',
    vertical: 'enterpriseops',
    evaluationKind: 'workflow',
    status: 'kept',
    claimStatus: 'headline',
    effectStatus: 'improved',
    candidateType: 'single_factor',
    businessProblem: 'Complex support requests lacked a verifiable terminal state.',
    whyAgent: 'The task crosses customer, ticket, and SLA state.',
    dataset: {
      datasetId: 'suite-v2',
      split: 'validation',
      caseCount: 2,
      unit: '2 frozen tasks',
      manifestSha256: 'b'.repeat(64),
      heldOutConsumed: false,
    },
    scoring: {
      primaryMetric: 'taskSuccessRate',
      evaluatorAuthority: 'host verifier',
      goldHiddenFromAgent: true,
      hardGates: ['temporary database cleanup = 100%', 'all required terminal states verified'],
    },
    factors: [{
      name: 'workflow',
      before: '直接执行',
      after: '状态合同',
      reason: '跨实体任务需要终态核验。',
    }],
    frozenControls: [{
      name: 'case_set',
      value: '2 frozen Validation tasks',
      reason: 'Keep the denominator comparable.',
    }],
    baseline: {
      runId: 'baseline-run',
      metrics: { taskSuccessRate: 0.5, latencyMs: 120_000 },
      evidenceRefs: ['receipt:baseline'],
    },
    candidate: {
      runId: 'candidate-run',
      metrics: { taskSuccessRate: 1, latencyMs: 100_000 },
      evidenceRefs: ['receipt:candidate'],
    },
    comparison: {
      decision: 'keep',
      decisionReason: 'The candidate passed the quality and cleanup gates.',
      metricDeltas: [
        { metric: 'taskSuccessRate', before: 0.5, after: 1, delta: 0.5 },
        { metric: 'latencyMs', before: 120_000, after: 100_000, delta: -20_000 },
      ],
    },
    star: {
      situation: 'One task did not reach a verifiable terminal state.',
      task: 'Repair only the workflow contract.',
      action: 'Added explicit terminal-state verification.',
      result: 'The candidate passed the frozen Validation gates.',
    },
    claim: {
      resumeBullet: 'Validation-only workflow result.',
      allowed: 'Claim the recorded Validation delta.',
      forbidden: 'Do not claim Held-out or production success.',
    },
    openGaps: ['Held-out remains unconsumed.'],
    importedAtMs: 900,
  };
}
