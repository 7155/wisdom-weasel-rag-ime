import { describe, expect, it } from 'vitest';
import type { AgentSubagentRunV1 } from '@/contracts/generated/agent-subagent-run.v1';
import {
  isUnverifiedReturn,
  subagentFailurePolicy,
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

  it('keeps an invalid structured delivery local to its node', () => {
    const run = sampleRun({
      state: 'completed',
      contract: {
        status: 'invalid',
        error: 'claims must be an array',
        toolCallId: '',
        validatedAtMs: null,
      },
    });

    expect(isUnverifiedReturn(run)).toBe(false);
    expect(subagentPresentationState(run)).toBe('contract_invalid');
    expect(subagentStateLabel(run)).toBe('合同无效');
    expect(subagentStateLabel(run, 'result')).toBe('已返回，合同无效');
  });

  it('names a token budget failure and gives the parent a recovery action', () => {
    const run = sampleRun({
      state: 'failed',
      error: 'token budget exceeded',
      result: { failureClass: 'logic_error' },
    });

    expect(subagentFailurePolicy(run)).toContain('Token 预算');
    expect(subagentFailurePolicy(run)).toContain('改派');
    expect(subagentFailurePolicy(run)).toContain('不会自动重试');
  });
});

function sampleRun(
  overrides: Partial<AgentSubagentRunV1>,
): AgentSubagentRunV1 {
  const base: AgentSubagentRunV1 = {
    schemaVersion: 'rag-ime.agent-subagent-run.v1',
    id: 'subagent-run:test',
    nodeId: 'subagent-node:test',
    attemptId: 'subagent-attempt:test:1',
    attemptNumber: 1,
    predecessorAttemptId: '',
    ownerRunId: 'session:parent',
    parentRunId: '',
    depth: 1,
    batchId: 'subagent-batch:test',
    childSessionId: 'session-child',
    todoTask: '核对子 Agent 证据',
    todoPhase: '验证',
    templateId: 'worker',
    templateVersion: '1',
    ordinal: 0,
    task: '返回实现结果',
    expectedOutput: '可核对的实现结果',
    acceptanceCriteria: ['结果包含验证证据'],
    launchDigest: sampleLaunchDigest(),
    contract: {
      status: 'not_requested',
      error: '',
      toolCallId: '',
      validatedAtMs: null,
    },
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
    resultContextScheduledAtMs: null,
    error: '',
    createdAtMs: 1,
    startedAtMs: 2,
    updatedAtMs: 3,
    completedAtMs: null,
  };
  return { ...base, ...overrides };
}

function sampleLaunchDigest(): AgentSubagentRunV1['launchDigest'] {
  return {
    schemaVersion: 'rag-ime.agent-subagent-launch-digest.v1',
    contextMode: 'fresh',
    templateId: 'worker',
    templateVersion: '1',
    modelProfile: 'openai-codex/gpt-5.6-sol',
    thinkingLevel: 'high',
    toolProfileVersion: 'subagent-readonly-v1',
    toolAllowlistMode: 'profile',
    tools: ['knowledge'],
    piSkillsEnabled: false,
    codexSkillsEnabled: false,
    workspaceAccess: 'read_only',
    workspaceRootCount: 1,
    outputContract: { required: false, schemaSha256: '' },
    extensionRuntime: 'pi_host_managed',
  };
}
