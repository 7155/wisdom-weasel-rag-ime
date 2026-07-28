import type { AgentSubagentRunV1 } from '@/contracts/generated/agent-subagent-run.v1';

export const UNVERIFIED_SUBAGENT_NOTICE = '该结果未经主持会话核验，不代表父任务验收通过';

export type SubagentPresentationState = AgentSubagentRunV1['state'] | 'returned';

export function subagentPresentationState(
  run: AgentSubagentRunV1,
): SubagentPresentationState {
  return isUnverifiedReturn(run) ? 'returned' : run.state;
}

export function subagentStateLabel(
  run: AgentSubagentRunV1,
  mode: 'short' | 'result' | 'console' = 'short',
): string {
  if (isUnverifiedReturn(run)) {
    return mode === 'short' ? '已返回' : '结果已返回';
  }
  if (mode === 'console' && run.state === 'running') return '执行中';
  return ({
    queued: '排队中',
    running: '进行中',
    completed: '已完成',
    failed: '失败',
    aborted: '已停止',
    timed_out: '已超时',
  })[run.state];
}

export function isUnverifiedReturn(run: AgentSubagentRunV1): boolean {
  if (run.state === 'queued' || run.state === 'running') return false;
  const source = record(run);
  const result = record(run.result);
  const deliveryStatus = text(source.deliveryStatus) || text(result.deliveryStatus);
  const verificationStatus = text(source.verificationStatus) || text(result.verificationStatus);
  return deliveryStatus === 'returned' || verificationStatus === 'unverified';
}

function record(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function text(value: unknown): string {
  return typeof value === 'string' ? value : '';
}
