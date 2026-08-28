import type { ContextXrayLayer, ContextXraySnapshot } from './ContextXrayPanel';

export type ContextUsageLayerId =
  | 'systemPrompt'
  | 'skillsTools'
  | 'projectContext'
  | 'conversationHistory'
  | 'memory'
  | 'knowledge'
  | 'currentInput'
  | 'cache'
  | 'compaction';

export type ContextUsageTokenQuality = 'exact' | 'estimated' | 'unknown';

export type ContextUsageLayer = {
  id: ContextUsageLayerId;
  label: string;
  /** Characters are exact only when Runtime captured the source content. */
  characters: number | null;
  /** Token counts are never inferred from characters. */
  tokens: number | null;
  tokenQuality: ContextUsageTokenQuality;
  state: 'present' | 'absent' | 'unknown';
  source: string;
  note: string;
};

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
  /** User-facing semantic layers; Runtime may expose overlapping projections. */
  layers: ContextUsageLayer[];
  capturedCharacters: number;
  /** Aggregate tokens have no trustworthy semantic allocation. */
  unclassifiedTokens: number | null;
  /** Null when Runtime did not report the aggregate token count. */
  freeTokens: number | null;
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
  const layers = buildContextUsageLayers(input.snapshot);
  return {
    available: windowSize > 0 && (tokens !== null || segments.length > 0),
    tokens,
    contextWindow: windowSize,
    percent,
    segments,
    layers,
    capturedCharacters,
    unclassifiedTokens: tokens,
    freeTokens: tokens === null ? null : Math.max(0, windowSize - used),
    compaction: compactionCount > 0 || compactionStatus || tokensBefore !== null || tokensAfter !== null
      ? { count: compactionCount, status: compactionStatus, tokensBefore, tokensAfter }
      : null,
  };
}

const HIGH_LEVEL_LAYER_SOURCES: ReadonlyArray<{
  id: Exclude<ContextUsageLayerId, 'currentInput' | 'cache' | 'compaction'>;
  label: string;
  sourceIds: ContextXrayLayer['id'][];
  source: string;
}> = [
  {
    id: 'systemPrompt',
    label: '系统提示词',
    sourceIds: ['system'],
    source: '最终 systemPrompt',
  },
  {
    id: 'skillsTools',
    label: 'Skills / 工具定义',
    sourceIds: ['skills', 'tools'],
    source: 'systemPromptOptions.skills + activeTools/toolSchemas',
  },
  {
    id: 'projectContext',
    label: '项目上下文',
    sourceIds: ['project-context', 'role-book', 'workflow-control', 'goal', 'lifecycle-hook'],
    source: '项目规则、Goal 与会话工作状态',
  },
  {
    id: 'conversationHistory',
    label: '对话历史',
    sourceIds: ['user-messages', 'assistant-messages', 'tool-calls', 'tool-results', 'history'],
    source: '最终模型调用 · contextMessages',
  },
  {
    id: 'memory',
    label: 'Memory / 记忆',
    sourceIds: ['session-memory', 'memory-recall', 'timeline'],
    source: 'Session Memory 与 memory_recall',
  },
  {
    id: 'knowledge',
    label: 'Knowledge / RAG',
    sourceIds: ['knowledge-rag'],
    source: 'knowledge_recall / rag',
  },
];

function buildContextUsageLayers(snapshot: ContextXraySnapshot | null | undefined): ContextUsageLayer[] {
  const sourceLayers = snapshot?.layers ?? [];
  const layers = HIGH_LEVEL_LAYER_SOURCES.map((definition) => aggregateSourceLayers(definition, sourceLayers));
  layers.push(currentInputLayer(snapshot));
  layers.push(cacheLayer(snapshot));
  layers.push(compactionLayer(snapshot));
  return layers;
}

function aggregateSourceLayers(
  definition: (typeof HIGH_LEVEL_LAYER_SOURCES)[number],
  sourceLayers: ContextXrayLayer[],
): ContextUsageLayer {
  if (!sourceLayers.length) {
    return unknownLayer(definition.id, definition.label, definition.source);
  }
  const selected = definition.sourceIds.map((id) => sourceLayers.find((layer) => layer.id === id));
  const unavailable = selected.some((layer) => !layer || layer.state === 'unavailable' || layer.characters === null);
  const present = selected.some((layer) => layer?.state === 'present' && (layer.characters ?? 0) > 0);
  const explicitlyAbsent = selected.length > 0 && selected.every((layer) => layer?.state === 'absent');
  const characters = unavailable ? null : selected.reduce((sum, layer) => sum + (layer?.characters ?? 0), 0);
  return {
    id: definition.id,
    label: definition.label,
    characters,
    tokens: null,
    tokenQuality: 'unknown',
    state: unavailable ? 'unknown' : explicitlyAbsent || !present ? 'absent' : 'present',
    source: definition.source,
    note: unavailable
      ? 'Runtime 未提供该层的可核对内容'
      : explicitlyAbsent || !present
        ? '本轮未注入'
        : '字符为 Runtime 捕获值；Token 未单独统计',
  };
}

function currentInputLayer(snapshot: ContextXraySnapshot | null | undefined): ContextUsageLayer {
  const prompt = typeof snapshot?.prompt === 'string' ? snapshot.prompt.trim() : '';
  if (!snapshot) {
    return unknownLayer('currentInput', '当前输入', 'Runtime debugContext.prompt');
  }
  if (!prompt) {
    return {
      ...unknownLayer('currentInput', '当前输入', 'Runtime debugContext.prompt'),
      note: 'Runtime 未捕获本轮输入原文',
    };
  }
  return {
    id: 'currentInput',
    label: '当前输入',
    characters: prompt.length,
    tokens: null,
    tokenQuality: 'unknown',
    state: 'present',
    source: 'Runtime debugContext.prompt',
    note: '字符为 Runtime 捕获值；通常已包含在对话历史的 user message 中；Token 未单独统计',
  };
}

function cacheLayer(snapshot: ContextXraySnapshot | null | undefined): ContextUsageLayer {
  const cache = snapshot?.cache;
  const hitPercent = snapshot?.cacheHitPercent ?? null;
  const readTokens = cache?.cacheReadTokens ?? null;
  const writeTokens = cache?.cacheWriteTokens ?? null;
  const reported = cache?.capability === 'reported' || hitPercent !== null;
  const unsupported = cache?.capability === 'unsupported';
  if (!snapshot || unsupported) {
    return {
      id: 'cache',
      label: 'Cache / 前缀缓存',
      characters: null,
      tokens: null,
      tokenQuality: 'unknown',
      state: 'unknown',
      source: 'Provider usage / cacheEvidence',
      note: unsupported ? 'Provider 明确未报告缓存计量' : 'Runtime 未提供缓存计量',
    };
  }
  const noteParts = [
    hitPercent === null ? '' : `命中率 ${Math.round(hitPercent)}%`,
    readTokens === null ? '' : `read ${formatContextTokenCount(readTokens)} Tokens`,
    writeTokens === null ? '' : `write ${formatContextTokenCount(writeTokens)} Tokens`,
  ].filter(Boolean);
  return {
    id: 'cache',
    label: 'Cache / 前缀缓存',
    characters: null,
    tokens: readTokens,
    tokenQuality: reported && readTokens !== null ? 'exact' : 'unknown',
    state: reported ? 'present' : 'unknown',
    source: 'Provider usage / cacheEvidence',
    note: noteParts.length ? noteParts.join(' · ') : 'Provider 未报告可核对的缓存数值',
  };
}

function compactionLayer(snapshot: ContextXraySnapshot | null | undefined): ContextUsageLayer {
  const summary = snapshot?.layers.find((layer) => layer.id === 'compaction-summary');
  const compaction = snapshot?.compaction;
  if (!snapshot || !compaction) return unknownLayer('compaction', 'Compaction / 压缩', 'Runtime compaction');
  const happened = compaction.count !== null && compaction.count > 0
    || Boolean(compaction.status)
    || compaction.tokensBefore !== null
    || compaction.tokensAfter !== null
    || (summary?.characters ?? 0) > 0;
  if (!happened) {
    return {
      id: 'compaction',
      label: 'Compaction / 压缩',
      characters: summary?.characters ?? 0,
      tokens: null,
      tokenQuality: 'unknown',
      state: 'absent',
      source: 'Runtime compaction + role=compactionSummary',
      note: '本轮未发生压缩',
    };
  }
  const noteParts = [
    compaction.count === null ? '' : `${formatContextCount(compaction.count)} 次`,
    compaction.tokensBefore === null ? '' : `before ${formatContextTokenCount(compaction.tokensBefore)} Tokens`,
    compaction.tokensAfter === null ? '' : `after ≈${formatContextTokenCount(compaction.tokensAfter)} Tokens`,
    compaction.status,
  ].filter(Boolean);
  return {
    id: 'compaction',
    label: 'Compaction / 压缩',
    characters: summary?.characters ?? null,
    tokens: compaction.tokensAfter,
    tokenQuality: compaction.tokensAfter === null ? 'unknown' : 'estimated',
    state: 'present',
    source: 'Runtime compaction + role=compactionSummary',
    note: noteParts.length ? noteParts.join(' · ') : '已发生压缩；Runtime 未提供更多计量',
  };
}

function formatContextCount(value: number): string {
  return new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 0 }).format(Math.max(0, value));
}

function unknownLayer(
  id: ContextUsageLayerId,
  label: string,
  source: string,
): ContextUsageLayer {
  return {
    id,
    label,
    characters: null,
    tokens: null,
    tokenQuality: 'unknown',
    state: 'unknown',
    source,
    note: 'Runtime 未提供该层的可核对数据',
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
