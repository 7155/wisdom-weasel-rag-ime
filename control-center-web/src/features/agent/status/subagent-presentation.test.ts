import { describe, expect, it } from 'vitest';
import type { AgentSubagentRunV1 } from '@/contracts/generated/agent-subagent-run.v1';
import {
  isUnverifiedReturn,
  subagentPresentationState,
  subagentStateLabel,
} from './subagent-presentation';

describe('subagent presentation semantics', () => {
  it('does not let terminal delivery imply parent verification', () => {
    const run = sampleRun({
      state: 'completed',
      result: { deliveryStatus: 'returned' },
    });

    expect(isUnverifiedReturn(run)).toBe(true);
    expect(subagentPresentationState(run)).toBe('returned');
    expect(subagentStateLabel(run)).toBe('已返回');
    expect(subagentStateLabel(run, 'result')).toBe('结果已返回');
  });

  it('keeps a verified completed run completed', () => {
    const run = sampleRun({
      state: 'completed',
      result: { verificationStatus: 'verified' },
    });

    expect(isUnverifiedReturn(run)).toBe(false);
    expect(subagentStateLabel(run)).toBe('已完成');
  });

  it('does not relabel active progress from an early result field', () => {
    const run = sampleRun({
      state: 'running',
      result: { verificationStatus: 'unverified' },
    });

    expect(isUnverifiedReturn(run)).toBe(false);
    expect(subagentPresentationState(run)).toBe('running');
    expect(subagentStateLabel(run)).toBe('进行中');
  });
});

function sampleRun(
  overrides: Partial<AgentSubagentRunV1>,
): AgentSubagentRunV1 {
  return {
    schemaVersion: 'rag-ime.agent-subagent-run.v1',
    id: 'subagent-run:test',
    batchId: 'subagent-batch:test',
    childSessionId: 'session-child',
    templateId: 'worker',
    templateVersion: '1',
    ordinal: 0,
    task: '返回实现结果',
    state: 'running',
    budget: {
      maxTurns: 1,
      maxToolCalls: 1,
      maxTotalTokens: 1_000,
      maxDurationMs: 60_000,
      maxOutputChars: 1_000,
    },
    usage: { turnCount: 1, toolCount: 1, totalTokens: 200 },
    result: {},
    error: '',
    createdAtMs: 1,
    startedAtMs: 2,
    updatedAtMs: 3,
    completedAtMs: null,
    ...overrides,
  };
}
