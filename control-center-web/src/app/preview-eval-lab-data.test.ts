import { describe, expect, it } from 'vitest';
import { previewEvalLabEvidence, previewEvalLabRuns } from './preview-eval-lab-data';

describe('preview Agent Lab evidence', () => {
  it('keeps source filter ids aligned with the runs they describe', () => {
    const response = previewEvalLabEvidence() as {
      runs?: Array<{ sourceId?: string }>;
      sources?: Array<{ sourceId?: string }>;
    };
    const sourceIds = new Set((response.sources ?? []).map((source) => source.sourceId));

    expect(response.runs?.every((run) => run.sourceId && sourceIds.has(run.sourceId))).toBe(true);
  });

  it('resolves a real-looking run id to a visible public transcript fixture', () => {
    const response = previewEvalLabEvidence({
      query: {
        runId: 'enterpriseops-csm-suite-v2-final-state-validation-20260901',
        taskIndex: '1',
      },
    }) as { detail?: { status?: string; runId?: string; turns?: unknown[] } };

    expect(response.detail?.status).toBe('available');
    expect(response.detail?.runId).toBe('enterpriseops-csm-suite-v2-final-state-validation-20260901');
    expect(response.detail?.turns?.length).toBeGreaterThan(1);
    expect((response.detail as { origin?: string } | undefined)?.origin).toBe('preview');
  });

  it('does not synthesize turns when the preview transcript is missing', () => {
    const response = previewEvalLabEvidence({
      query: { runId: 'preview-missing-transcript', taskIndex: '1' },
    }) as { detail?: { status?: string; turns?: unknown[]; task?: { transcriptAvailable?: boolean } } };

    expect(response.detail?.status).toBe('transcript_missing');
    expect(response.detail?.turns).toEqual([]);
    expect(response.detail?.task?.transcriptAvailable).toBe(false);
  });

  it('keeps the execution-chain matrix, environment, task and report on the same run', () => {
    const response = previewEvalLabEvidence({
      query: { runId: 'preview-enterpriseops-execution', taskIndex: '1' },
    }) as { detail?: { environment?: Record<string, unknown>; task?: Record<string, unknown>; report?: { metrics?: Record<string, unknown> } } };

    expect(response.detail?.environment?.workflowProfile).toBe('execution-chain-v5');
    expect(response.detail?.task?.verifierPassed).toBe(26);
    expect(response.detail?.task?.verifierTotal).toBe(31);
    expect(response.detail?.task?.toolCalls).toBe(47);
    expect(response.detail?.report?.metrics).toMatchObject({ verifierPassCount: 26, verifierCount: 31, toolCalls: 47 });
  });

  it('keeps report-only cost evidence inspectable without inventing turns', () => {
    const response = previewEvalLabEvidence({
      query: { runId: 'enterpriseops-csm-luna-max-validation-20260901.v1', taskIndex: '0' },
    }) as { detail?: { status?: string; turns?: unknown[]; environment?: Record<string, unknown> } };

    expect(response.detail?.status).toBe('report_only');
    expect(response.detail?.turns).toEqual([]);
    expect(response.detail?.environment?.costEstimate).toBeDefined();
  });

  it('binds RAG lane, CloudOps candidate, and Memory winner to their exact report-only runs', () => {
    for (const runId of [
      'enterprise-rag-answer-evidence-luna-v20-tuned',
      'cloudops-bounded-workflow-validation-reject-20260901-v1',
      'memory-maintenance-luna-max-validation-20260902-v5',
    ]) {
      const response = previewEvalLabEvidence({ query: { runId, taskIndex: '0' } }) as {
        detail?: { status?: string; runId?: string; turns?: unknown[] };
      };
      expect(response.detail?.status).toBe('report_only');
      expect(response.detail?.runId).toBe(runId);
      expect(response.detail?.turns).toEqual([]);
    }
  });

  it('keeps the CloudOps Luna timeout evidence report-only without inventing dialogue or gold', () => {
    const response = previewEvalLabEvidence({
      query: {
        runId: 'cloudops--cloudops-luna-max-baseline-validation-20260902',
        taskIndex: '0',
      },
    }) as {
      runs?: Array<{
        runId?: string;
        sessionCount?: number;
        transcriptCount?: number;
        metrics?: Record<string, unknown>;
      }>;
      detail?: {
        status?: string;
        turns?: unknown[];
        summary?: { metrics?: Record<string, unknown> };
      };
    };

    const run = response.runs?.find((item) => item.runId === 'cloudops--cloudops-luna-max-baseline-validation-20260902');
    expect(run).toMatchObject({
      sessionCount: 3,
      transcriptCount: 0,
      metrics: {
        transcriptToolCalls: 278,
        failedTranscriptToolCalls: 14,
        inputTokens: 916112,
        outputTokens: 57057,
        cacheReadTokens: 18809344,
        latencyMs: 1718516,
      },
    });
    expect(response.detail?.status).toBe('report_only');
    expect(response.detail?.turns).toEqual([]);
    expect(response.detail?.summary?.metrics).toMatchObject({
      thirdBatchTimeout: 1,
      abortTimeout: 1,
      hostFormalCaJraAvailable: 0,
    });
  });

  it('exposes every vertical ablation as an inspectable matrix row', () => {
    const response = previewEvalLabRuns() as {
      experiments?: Array<{
        experimentId?: string;
        factors?: unknown[];
        scoring?: { hardGates?: unknown[] };
        baseline?: { metrics?: Record<string, number>; evidenceRefs?: string[] };
        candidate?: { metrics?: Record<string, number>; evidenceRefs?: string[] };
        comparison?: { decision?: string };
      }>;
    };
    const experiments = new Map(
      (response.experiments ?? []).map((experiment) => [experiment.experimentId, experiment]),
    );
    const requiredRows = [
      'enterprise-rag.tag-graph-readiness.v1',
      'enterprise-rag.answer-luna-baseline.v20',
      'enterprise-rag.answer-luna-skill.v20',
      'enterprise-rag.answer-luna-tuned.v20',
      'enterprise-rag.answer-luna-agentic.v20',
      'cloudops.validation-baseline.v1',
      'cloudops.evidence-search.v2',
      'cloudops.observation-id.v4',
      'memory.maintenance-observed-failure.v0',
      'memory.maintenance-shadow-v1',
      'memory.maintenance-shadow-v3',
      'memory.maintenance-shadow-v4',
    ];

    expect([...experiments.keys()]).toEqual(expect.arrayContaining(requiredRows));
    for (const id of requiredRows) {
      const experiment = experiments.get(id);
      expect(experiment?.factors?.length, id).toBe(1);
      expect(experiment?.scoring?.hardGates?.length, id).toBeGreaterThan(0);
      expect(Object.keys(experiment?.baseline?.metrics ?? {}).length, id).toBeGreaterThan(0);
      expect(Object.keys(experiment?.candidate?.metrics ?? {}).length, id).toBeGreaterThan(0);
      expect(experiment?.candidate?.evidenceRefs?.length, id).toBeGreaterThan(0);
      expect(experiment?.comparison?.decision, id).toBeTruthy();
    }
  });

  it('explains which state-contract changes are shared preconditions versus the compared workflow', () => {
    const response = previewEvalLabRuns() as {
      experiments?: Array<{
        experimentId?: string;
        factors?: Array<{ name?: string; reason?: string }>;
        frozenControls?: Array<{ name?: string; reason?: string }>;
        comparison?: { decision?: string };
      }>;
    };
    const experiment = (response.experiments ?? []).find(
      (item) => item.experimentId === 'enterpriseops-csm.state-contract-suite-v2',
    );
    const factors = new Map((experiment?.factors ?? []).map((item) => [item.name, item]));
    const controls = new Map((experiment?.frozenControls ?? []).map((item) => [item.name, item]));

    expect(factors.get('prompt')?.reason).toContain('不能算 candidate 收益');
    expect(factors.get('tool')?.reason).toContain('公平性前置修复');
    expect(factors.get('workflow')?.reason).toContain('没有写入本题答案');
    expect(controls.get('evaluator')?.reason).toContain('同一 hash');
    expect(experiment?.comparison?.decision).toBe('reject');
  });
});
