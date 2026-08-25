import type { ContextXrayLayer, ContextXraySnapshot } from './ContextXrayPanel';

export type ContextUsageCategoryId =
  | 'system'
  | 'tools'
  | 'rules'
  | 'skills'
  | 'mcp'
  | 'subagents'
  | 'summarized'
  | 'conversation';

export type ContextUsageSegment = {
  id: ContextUsageCategoryId;
  label: string;
  tokens: number;
  color: string;
};

export type ContextUsageView = {
  available: boolean;
  tokens: number | null;
  contextWindow: number;
  percent: number | null;
  segments: ContextUsageSegment[];
  freeTokens: number;
};

const CATEGORY_ORDER: readonly ContextUsageCategoryId[] = [
  'system',
  'tools',
  'rules',
  'skills',
  'mcp',
  'subagents',
  'summarized',
  'conversation',
];

const CATEGORY_META: Record<ContextUsageCategoryId, { label: string; color: string }> = {
  system: { label: 'System prompt', color: '#8b919a' },
  tools: { label: 'Tool definitions', color: '#7c5cbf' },
  rules: { label: 'Rules', color: '#2f9a5f' },
  skills: { label: 'Skills', color: '#8a6a3d' },
  mcp: { label: 'MCP & dynamic tools', color: '#c44d9a' },
  subagents: { label: 'Subagent definitions', color: '#4a7fd4' },
  summarized: { label: 'Summarized conversation', color: '#d45a7a' },
  conversation: { label: 'Conversation', color: '#e85a3c' },
};

const LAYER_TO_CATEGORY: Partial<Record<ContextXrayLayer['id'], ContextUsageCategoryId>> = {
  system: 'system',
  tools: 'tools',
  'project-context': 'rules',
  'workflow-control': 'rules',
  goal: 'rules',
  skills: 'skills',
  'lifecycle-hook': 'mcp',
  'role-book': 'subagents',
  'session-memory': 'summarized',
  history: 'summarized',
  timeline: 'conversation',
  'tool-results': 'conversation',
};

export function buildContextUsageView(input: {
  telemetry?: {
    tokens: number | null;
    contextWindow: number;
    percent: number | null;
  } | null;
  snapshot?: ContextXraySnapshot | null;
}): ContextUsageView {
  const windowSize = Math.max(
    0,
    input.snapshot?.contextWindow
      ?? input.telemetry?.contextWindow
      ?? 0,
  );
  const tokens = input.snapshot?.contextTokens
    ?? input.telemetry?.tokens
    ?? null;
  const percent = tokens === null || windowSize <= 0
    ? input.telemetry?.percent ?? null
    : Math.min(100, Math.max(0, (tokens / windowSize) * 100));

  const totals = Object.fromEntries(
    CATEGORY_ORDER.map((id) => [id, 0]),
  ) as Record<ContextUsageCategoryId, number>;

  for (const layer of input.snapshot?.layers ?? []) {
    if (layer.state !== 'present' || !layer.estimatedTokens) continue;
    const category = LAYER_TO_CATEGORY[layer.id];
    if (!category) continue;
    totals[category] += layer.estimatedTokens;
  }

  const segmentSum = CATEGORY_ORDER.reduce((sum, id) => sum + totals[id], 0);
  if (tokens !== null && tokens > segmentSum && segmentSum > 0) {
    totals.conversation += tokens - segmentSum;
  } else if (tokens !== null && segmentSum === 0 && tokens > 0) {
    totals.conversation = tokens;
  }

  const segments = CATEGORY_ORDER
    .filter((id) => totals[id] > 0)
    .map((id) => ({
      id,
      label: CATEGORY_META[id].label,
      tokens: totals[id],
      color: CATEGORY_META[id].color,
    }));

  const used = tokens ?? segmentSum;
  return {
    available: windowSize > 0 && (tokens !== null || segments.length > 0),
    tokens,
    contextWindow: windowSize,
    percent,
    segments,
    freeTokens: Math.max(0, windowSize - used),
  };
}

export function formatContextTokenCount(value: number): string {
  if (value >= 1_000_000) {
    const scaled = value / 1_000_000;
    return `${scaled >= 10 ? scaled.toFixed(1) : scaled.toFixed(2)}M`;
  }
  if (value >= 1_000) {
    const scaled = value / 1_000;
    if (Number.isInteger(scaled)) return `${scaled}K`;
    return `${scaled.toFixed(1)}K`;
  }
  return String(Math.round(value));
}
