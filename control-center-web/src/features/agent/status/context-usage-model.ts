import type { ContextXrayLayer, ContextXraySnapshot } from './ContextXrayPanel';

export type ContextUsageCategoryId =
  | 'system'
  | 'tools'
  | 'rules'
  | 'skills'
  | 'mcp'
  | 'subagents'
  | 'summarized'
  | 'user'
  | 'assistant'
  | 'toolCalls'
  | 'toolResults';

export type ContextUsageSegment = {
  id: ContextUsageCategoryId;
  label: string;
  characters: number;
  color: string;
};

export type ContextUsageView = {
  available: boolean;
  tokens: number | null;
  contextWindow: number;
  percent: number | null;
  segments: ContextUsageSegment[];
  capturedCharacters: number;
  /** Aggregate tokens have no trustworthy semantic allocation. */
  unclassifiedTokens: number | null;
  freeTokens: number;
  compaction: {
    count: number;
    status: string;
    tokensBefore: number | null;
    tokensAfter: number | null;
  } | null;
};

const CATEGORY_ORDER: readonly ContextUsageCategoryId[] = [
  'system',
  'tools',
  'rules',
  'skills',
  'mcp',
  'subagents',
  'summarized',
  'user',
  'assistant',
  'toolCalls',
  'toolResults',
];

const CATEGORY_META: Record<ContextUsageCategoryId, { label: string; color: string }> = {
  system: { label: '系统提示词', color: '#8b919a' },
  tools: { label: '工具定义', color: '#7c5cbf' },
  rules: { label: '项目规则与 Goal', color: '#2f9a5f' },
  skills: { label: 'Skills', color: '#8a6a3d' },
  mcp: { label: '动态上下文', color: '#c44d9a' },
  subagents: { label: '伙伴定义', color: '#4a7fd4' },
  summarized: { label: '压缩摘要与历史', color: '#d45a7a' },
  user: { label: '用户消息', color: '#e07a3f' },
  assistant: { label: 'Agent 消息', color: '#4a7fd4' },
  toolCalls: { label: '工具调用', color: '#7c5cbf' },
  toolResults: { label: '工具结果', color: '#2f9a5f' },
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
  'compaction-summary': 'summarized',
  timeline: 'summarized',
  'user-messages': 'user',
  'assistant-messages': 'assistant',
  'tool-calls': 'toolCalls',
  'tool-results': 'toolResults',
};

export function buildContextUsageView(input: {
  telemetry?: {
    tokens: number | null;
    contextWindow: number;
    percent: number | null;
    compactionCount?: number;
    latestCompaction?: {
      status: string;
      tokensBefore?: number;
      estimatedTokensAfter?: number;
    };
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
    if (layer.state !== 'present' || !layer.characters) continue;
    const category = LAYER_TO_CATEGORY[layer.id];
    if (!category) continue;
    totals[category] += layer.characters;
  }

  const capturedCharacters = CATEGORY_ORDER.reduce((sum, id) => sum + totals[id], 0);

  const segments = CATEGORY_ORDER
    .filter((id) => totals[id] > 0)
    .map((id) => ({
      id,
      label: CATEGORY_META[id].label,
      characters: totals[id],
      color: CATEGORY_META[id].color,
    }));

  const used = tokens ?? 0;
  const snapshotCompaction = input.snapshot?.compaction;
  const telemetryCompaction = input.telemetry?.latestCompaction;
  const compactionCount = snapshotCompaction?.count ?? input.telemetry?.compactionCount ?? 0;
  const compactionStatus = snapshotCompaction?.status || telemetryCompaction?.status || '';
  const tokensBefore = snapshotCompaction?.tokensBefore ?? telemetryCompaction?.tokensBefore ?? null;
  const tokensAfter = snapshotCompaction?.tokensAfter ?? telemetryCompaction?.estimatedTokensAfter ?? null;
  return {
    available: windowSize > 0 && (tokens !== null || segments.length > 0),
    tokens,
    contextWindow: windowSize,
    percent,
    segments,
    capturedCharacters,
    unclassifiedTokens: tokens,
    freeTokens: Math.max(0, windowSize - used),
    compaction: compactionCount > 0 || compactionStatus || tokensBefore !== null || tokensAfter !== null
      ? { count: compactionCount, status: compactionStatus, tokensBefore, tokensAfter }
      : null,
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
