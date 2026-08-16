import type { AgentSubagentRunV1 } from '@/contracts/generated/agent-subagent-run.v1';

export function subagentRuns(value: unknown): AgentSubagentRunV1[] {
  const source = Array.isArray(record(value).items) ? record(value).items as unknown[] : [];
  const runs = source.flatMap((batch) => (
    Array.isArray(record(batch).runs) ? record(batch).runs as unknown[] : []
  ));
  return runs.filter(isSubagentRun);
}

export function isActiveSubagentRun(run: AgentSubagentRunV1): boolean {
  return run.state === 'queued' || run.state === 'running';
}

export function hasActiveSubagentRuns(runs: readonly AgentSubagentRunV1[]): boolean {
  return runs.some(isActiveSubagentRun);
}

export function isSubagentRun(value: unknown): value is AgentSubagentRunV1 {
  const item = record(value);
  const usage = record(item.usage);
  const templates: AgentSubagentRunV1['templateId'][] = [
    'researcher',
    'planner',
    'worker',
    'reviewer',
    'delegate',
  ];
  return item.schemaVersion === 'rag-ime.agent-subagent-run.v1'
    && typeof item.id === 'string'
    && typeof item.task === 'string'
    && typeof item.childSessionId === 'string'
    && templates.includes(item.templateId as AgentSubagentRunV1['templateId'])
    && ['queued', 'running', 'completed', 'failed', 'aborted', 'timed_out'].includes(text(item.state))
    && Number.isFinite(usage.turnCount)
    && Number.isFinite(usage.toolCount)
    && Number.isFinite(usage.totalTokens);
}

function record(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function text(value: unknown): string {
  return typeof value === 'string' ? value : '';
}
