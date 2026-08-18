import type { AgentSubagentBatchV1 } from '@/contracts/generated/agent-subagent-batch.v1';
import type { AgentSubagentRunV1 } from '@/contracts/generated/agent-subagent-run.v1';

export type AgentSubagentBatchWithRuns = Omit<AgentSubagentBatchV1, 'runs'> & {
  runs: AgentSubagentRunV1[];
};

export interface SubagentTreeNode {
  run: AgentSubagentRunV1;
  children: SubagentTreeNode[];
}

export interface SubagentRunTree {
  schemaVersion: 'rag-ime.agent-subagent-tree.v1';
  rootSessionId: string;
  nodeCount: number;
  maxDepth: number;
  roots: SubagentTreeNode[];
}

export function subagentBatches(value: unknown): AgentSubagentBatchWithRuns[] {
  const source = Array.isArray(record(value).items) ? record(value).items as unknown[] : [];
  return source.filter(isSubagentBatch);
}

export function subagentRuns(value: unknown): AgentSubagentRunV1[] {
  const tree = subagentTree(value);
  if (tree.roots.length) return flattenTree(tree.roots);
  return subagentBatches(value).flatMap((batch) => batch.runs);
}

export function subagentTree(value: unknown): SubagentRunTree {
  const source = record(record(value).tree);
  const roots = Array.isArray(source.roots)
    ? source.roots
      .map((item) => parseTreeNode(item, new Set(), 0))
      .filter((item): item is SubagentTreeNode => item !== null)
    : [];
  return {
    schemaVersion: 'rag-ime.agent-subagent-tree.v1',
    rootSessionId: text(source.rootSessionId),
    nodeCount: roots.length ? flattenTree(roots).length : 0,
    maxDepth: Math.max(0, Number(source.maxDepth) || 0),
    roots,
  };
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
    && typeof item.nodeId === 'string'
    && typeof item.attemptId === 'string'
    && Number.isFinite(item.attemptNumber)
    && Number.isFinite(item.depth)
    && typeof item.task === 'string'
    && typeof item.childSessionId === 'string'
    && templates.includes(item.templateId as AgentSubagentRunV1['templateId'])
    && ['queued', 'running', 'completed', 'failed', 'aborted', 'timed_out'].includes(text(item.state))
    && Number.isFinite(usage.turnCount)
    && Number.isFinite(usage.toolCount)
    && Number.isFinite(usage.totalTokens);
}

function parseTreeNode(
  value: unknown,
  ancestors: Set<string>,
  level: number,
): SubagentTreeNode | null {
  if (level > 2) return null;
  const item = record(value);
  if (!isSubagentRun(item.run)) return null;
  const run = item.run;
  if (ancestors.has(run.id)) return null;
  const nextAncestors = new Set(ancestors).add(run.id);
  const children = Array.isArray(item.children)
    ? item.children
      .map((child) => parseTreeNode(child, nextAncestors, level + 1))
      .filter((child): child is SubagentTreeNode => child !== null)
    : [];
  return { run, children };
}

function flattenTree(roots: readonly SubagentTreeNode[]): AgentSubagentRunV1[] {
  return roots.flatMap((node) => [node.run, ...flattenTree(node.children)]);
}

export function isSubagentBatch(value: unknown): value is AgentSubagentBatchWithRuns {
  const item = record(value);
  const causal = record(item.causalMetadata);
  return item.schemaVersion === 'rag-ime.agent-subagent-batch.v1'
    && typeof item.id === 'string'
    && typeof item.parentSessionId === 'string'
    && typeof item.parentRunId === 'string'
    && ['fresh', 'fork'].includes(text(item.contextMode))
    && ['inline', 'next_turn'].includes(text(item.resultDeliveryMode))
    && ['queued', 'running', 'completed', 'failed', 'aborted', 'timed_out'].includes(text(item.state))
    && typeof causal.roomBound === 'boolean'
    && Array.isArray(item.runs)
    && item.runs.length > 0
    && item.runs.every(isSubagentRun);
}

function record(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function text(value: unknown): string {
  return typeof value === 'string' ? value : '';
}
