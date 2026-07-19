import { useQuery } from '@tanstack/react-query';
import {
  BookUser,
  Brain,
  Check,
  ChevronRight,
  CircleHelp,
  Clock3,
  Database,
  History,
  Layers3,
  Minimize2,
  PackageOpen,
  ScanSearch,
  Sparkles,
  Wrench,
  type LucideIcon,
} from 'lucide-react';
import { useMemo, useState } from 'react';
import { useControlTransport } from '@/app/control-transport';
import {
  normalizeDebugContextResponse,
  type DebugContextResponse,
  type DebugModelCall,
} from '@/features/context-debug/model';
import './ContextXrayPanel.css';

type ContextLayerId =
  | 'system'
  | 'role-book'
  | 'session-memory'
  | 'timeline'
  | 'skills'
  | 'tools'
  | 'history'
  | 'tool-results';

type ContextLayerState = 'present' | 'absent' | 'unavailable';
type ProviderDelivery = 'delivered' | 'missing' | 'pending' | 'unavailable';

export interface ContextXrayLayer {
  id: ContextLayerId;
  label: string;
  source: string;
  state: ContextLayerState;
  characters: number | null;
  estimatedTokens: number | null;
  providerDelivery: ProviderDelivery;
}

export interface ContextXraySnapshot {
  available: boolean;
  layers: ContextXrayLayer[];
  contextTokens: number | null;
  contextWindow: number | null;
  cacheHitPercent: number | null;
  compaction: {
    count: number | null;
    status: string;
    tokensBefore: number | null;
    tokensAfter: number | null;
  };
  providerStatus: number | null;
  providerCaptured: boolean;
  updatedAtMs: number | null;
}

interface LayerSource {
  id: ContextLayerId;
  label: string;
  source: string;
  content: string;
  identifiers?: string[];
  knowable: boolean;
}

const layerIcons: Record<ContextLayerId, LucideIcon> = {
  system: Layers3,
  'role-book': BookUser,
  'session-memory': Brain,
  timeline: Clock3,
  skills: Sparkles,
  tools: Wrench,
  history: History,
  'tool-results': PackageOpen,
};

const roleBookPattern = /<agent-role-book\b[^>]*>([\s\S]*?)<\/agent-role-book>/giu;
const managedContextPattern = /<rag-ime-context\b[^>]*>([\s\S]*?)<\/rag-ime-context>/giu;
const sessionMemoryPattern = /<rag-ime-context\s+type=["']session_memory["'][^>]*>([\s\S]*?)<\/rag-ime-context>/giu;
const timelineSectionPattern = /(?:^|\n)###\s+近期时间线\s*\n([\s\S]*?)(?=\n###\s+|\s*$)/giu;

export function ContextXraySections({
  sessionId,
  open,
}: {
  sessionId: string;
  open: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const transport = useControlTransport();
  const query = useQuery({
    queryKey: ['agent', 'context-xray', sessionId],
    queryFn: ({ signal }) => transport.request({
      pathId: 'agent.session.debugContext.get',
      params: { sessionId },
      signal,
    }),
    enabled: open && expanded && Boolean(sessionId),
    refetchInterval: open && expanded ? 3_000 : false,
    retry: false,
  });
  const snapshot = useMemo(
    () => buildContextXraySnapshot(normalizeDebugContextResponse(query.data)),
    [query.data],
  );
  const presentCount = snapshot.layers.filter((layer) => layer.state === 'present').length;
  const deliveredCount = snapshot.layers.filter((layer) => layer.providerDelivery === 'delivered').length;

  return (
    <section className="agent-status-section agent-context-xray">
      <header>
        <ScanSearch size={15} />
        <strong>Context X-ray</strong>
        {snapshot.available ? <span>{presentCount}</span> : null}
      </header>
      <button
        aria-expanded={expanded}
        className="agent-context-xray__trigger"
        onClick={() => setExpanded((value) => !value)}
        type="button"
      >
        <span>
          <strong>{expanded ? '收起上下文透视' : '查看上下文透视'}</strong>
          <small>
            {snapshot.available
              ? `${deliveredCount}/${presentCount} 层确认到达 Provider`
              : '逐层核对注入、压缩与缓存'}
          </small>
        </span>
        <ChevronRight size={14} />
      </button>
      {expanded ? (
        <div className="agent-context-xray__body" aria-live="polite">
          {query.isPending ? <XrayNotice>正在读取 Runtime 快照</XrayNotice> : null}
          {query.error ? (
            <XrayNotice tone="warning">
              原始上下文调试未启用，无法确认真实 Provider Payload
            </XrayNotice>
          ) : null}
          {!query.isPending && !query.error && !snapshot.available ? (
            <XrayNotice>这轮尚未形成可核对的上下文快照</XrayNotice>
          ) : null}
          {snapshot.available ? (
            <>
              <XrayRuntimeStrip snapshot={snapshot} />
              <ol className="agent-context-xray__layers" aria-label="上下文分层指标">
                {snapshot.layers.map((layer) => (
                  <ContextLayerRow key={layer.id} layer={layer} />
                ))}
              </ol>
              <p className="agent-context-xray__footnote">
                字符来自 Runtime 快照；Token 为模型无关估算。缓存只提供整轮命中率，不能可靠分摊到单层。
              </p>
            </>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

function XrayRuntimeStrip({ snapshot }: { snapshot: ContextXraySnapshot }) {
  return (
    <dl className="agent-context-xray__runtime">
      <div>
        <dt><Layers3 size={13} />上下文</dt>
        <dd>{tokenPair(snapshot.contextTokens, snapshot.contextWindow)}</dd>
      </div>
      <div>
        <dt><Database size={13} />缓存</dt>
        <dd>{formatPercent(snapshot.cacheHitPercent)}</dd>
      </div>
      <div>
        <dt><Minimize2 size={13} />压缩</dt>
        <dd>{formatCompaction(snapshot.compaction)}</dd>
      </div>
    </dl>
  );
}

function ContextLayerRow({ layer }: { layer: ContextXrayLayer }) {
  const Icon = layerIcons[layer.id];
  return (
    <li data-state={layer.state}>
      <Icon size={14} />
      <span>
        <strong>{layer.label}</strong>
        <small>{layerMetric(layer)}</small>
        <em>{layer.source}</em>
      </span>
      <ProviderState delivery={layer.providerDelivery} state={layer.state} />
    </li>
  );
}

function ProviderState({
  delivery,
  state,
}: {
  delivery: ProviderDelivery;
  state: ContextLayerState;
}) {
  if (state === 'absent') return <b data-state="absent">未注入</b>;
  if (delivery === 'delivered') return <b data-state="delivered"><Check size={11} />已接收</b>;
  if (delivery === 'missing') return <b data-state="missing">未送达</b>;
  if (delivery === 'pending') return <b data-state="pending">待确认</b>;
  return <b data-state="unavailable"><CircleHelp size={11} />不可确认</b>;
}

function XrayNotice({
  children,
  tone = 'neutral',
}: {
  children: string;
  tone?: 'neutral' | 'warning';
}) {
  return <p className="agent-context-xray__notice" data-tone={tone}>{children}</p>;
}

export function buildContextXraySnapshot(response: DebugContextResponse): ContextXraySnapshot {
  const context = response.context;
  if (!response.available || !context) return emptySnapshot();

  const latestCall = context.modelCalls.at(-1);
  const latestExchange = latestCall?.providerExchanges.at(-1);
  const providerCaptured = latestExchange?.payload !== undefined;
  const providerStatus = finiteNumber(latestExchange?.status);
  const providerAcknowledged = providerStatus !== null;
  const providerText = providerCaptured ? collectProviderText(latestExchange?.payload) : '';
  const sources = contextLayerSources(context.systemPrompt, context.systemPromptOptions, context.activeTools, context.toolSchemas, latestCall);
  const telemetry = response.telemetry;
  const telemetryContext = record(telemetry.context);
  const compaction = record(telemetry.latestCompaction);

  return {
    available: true,
    layers: sources.map((source) => {
      if (!source.knowable) {
        return {
          id: source.id,
          label: source.label,
          source: source.source,
          state: 'unavailable',
          characters: null,
          estimatedTokens: null,
          providerDelivery: 'unavailable',
        };
      }
      const content = source.content.trim();
      if (!content) {
        return {
          id: source.id,
          label: source.label,
          source: source.source,
          state: 'absent',
          characters: 0,
          estimatedTokens: 0,
          providerDelivery: providerCaptured ? 'missing' : 'unavailable',
        };
      }
      const payloadContainsLayer = providerCaptured
        ? layerReachedProvider(content, source.identifiers ?? [], providerText)
        : false;
      return {
        id: source.id,
        label: source.label,
        source: source.source,
        state: 'present',
        characters: content.length,
        estimatedTokens: estimateTokens(content),
        providerDelivery: !providerCaptured
          ? 'unavailable'
          : !payloadContainsLayer
            ? 'missing'
            : !providerAcknowledged
              ? 'pending'
              : 'delivered',
      };
    }),
    contextTokens: finiteNumber(telemetryContext.tokens),
    contextWindow: finiteNumber(telemetryContext.contextWindow),
    cacheHitPercent: finiteNumber(telemetry.latestCacheHitPercent),
    compaction: {
      count: finiteNumber(telemetry.compactionCount),
      status: text(compaction.status),
      tokensBefore: finiteNumber(compaction.tokensBefore),
      tokensAfter: finiteNumber(compaction.estimatedTokensAfter),
    },
    providerStatus,
    providerCaptured,
    updatedAtMs: finiteNumber(telemetry.updatedAtMs) ?? finiteNumber(context.updatedAtMs),
  };
}

function contextLayerSources(
  systemPrompt: string,
  systemPromptOptions: unknown,
  activeTools: string[],
  toolSchemas: Record<string, unknown>[],
  latestCall: DebugModelCall | undefined,
): LayerSource[] {
  const roleBooks = captures(systemPrompt, roleBookPattern);
  const sessionBlocks = captures(systemPrompt, sessionMemoryPattern);
  const sessionContent = sessionBlocks.join('\n');
  const timelines = captures(sessionContent, timelineSectionPattern);
  const timelineContent = timelines.join('\n');
  const sessionWithoutTimeline = sessionContent.replace(timelineSectionPattern, '\n').trim();
  const systemWithoutManagedLayers = systemPrompt
    .replace(roleBookPattern, '\n')
    .replace(managedContextPattern, '\n')
    .replace(/\n{3,}/gu, '\n\n')
    .trim();
  const options = record(systemPromptOptions);
  const skills = array(options.skills);
  const skillsContent = stableJson(skills);
  const skillIdentifiers = skills.flatMap((item) => {
    const skill = record(item);
    return [text(skill.name), text(skill.description)].filter(Boolean);
  });
  const toolsContent = activeTools.length || toolSchemas.length
    ? stableJson({ activeTools, toolSchemas })
    : '';
  const toolIdentifiers = [
    ...activeTools,
    ...toolSchemas.map(toolName).filter(Boolean),
  ];
  const messages = latestCall?.contextMessages ?? [];
  const currentUserIndex = lastUserMessageIndex(messages);
  const toolResults = messages.filter(isToolResultMessage);
  const history = messages.filter((message, index) => (
    index !== currentUserIndex && !isToolResultMessage(message)
  ));

  return [
    layer(
      'system',
      'System',
      '最终 systemPrompt（已剔除独立记忆块）',
      systemWithoutManagedLayers,
      Boolean(systemPrompt),
      contentIdentifiers(systemWithoutManagedLayers),
    ),
    layer('role-book', 'Role Book', '<agent-role-book>', roleBooks.join('\n'), Boolean(systemPrompt)),
    layer(
      'session-memory',
      'Session Memory',
      'type="session_memory"（不含时间线）',
      sessionWithoutTimeline,
      Boolean(systemPrompt),
      contentIdentifiers(sessionWithoutTimeline),
    ),
    layer('timeline', 'Timeline', 'Session Memory · 近期时间线', timelineContent, Boolean(systemPrompt)),
    layer('skills', 'Skills', 'systemPromptOptions.skills', skillsContent, Boolean(Object.keys(options).length), skillIdentifiers),
    layer('tools', 'Tools', 'activeTools + toolSchemas', toolsContent, Boolean(latestCall || activeTools.length || toolSchemas.length), toolIdentifiers),
    layer(
      'history',
      'History',
      '最终模型调用 · 历史消息',
      stableJson(history),
      Boolean(latestCall),
      stringLeaves(history),
    ),
    layer(
      'tool-results',
      'Tool Results',
      '最终模型调用 · 工具结果',
      stableJson(toolResults),
      Boolean(latestCall),
      stringLeaves(toolResults),
    ),
  ];
}

function layer(
  id: ContextLayerId,
  label: string,
  source: string,
  content: string,
  knowable: boolean,
  identifiers?: string[],
): LayerSource {
  return { id, label, source, content, knowable, identifiers };
}

function layerReachedProvider(content: string, identifiers: string[], providerText: string): boolean {
  if (!providerText) return false;
  const compactContent = compact(content);
  const compactPayload = compact(providerText);
  if (compactContent && compactPayload.includes(compactContent)) return true;
  const stableIdentifiers = identifiers
    .map(compact)
    .filter((value) => value.length >= 2);
  return stableIdentifiers.length > 0 && stableIdentifiers.every((value) => compactPayload.includes(value));
}

function collectProviderText(value: unknown): string {
  return stringLeaves(value).join('\n');
}

function collectStrings(value: unknown, result: string[]): void {
  if (typeof value === 'string') {
    result.push(value);
    return;
  }
  if (Array.isArray(value)) {
    value.forEach((item) => collectStrings(item, result));
    return;
  }
  if (value && typeof value === 'object') {
    Object.values(value as Record<string, unknown>).forEach((item) => collectStrings(item, result));
  }
}

function stringLeaves(value: unknown): string[] {
  const result: string[] = [];
  collectStrings(value, result);
  return result.filter(Boolean);
}

function contentIdentifiers(value: string): string[] {
  return value
    .split('\n')
    .map(compact)
    .filter((line) => line.length >= 3);
}

function captures(value: string, pattern: RegExp): string[] {
  pattern.lastIndex = 0;
  return [...value.matchAll(pattern)].map((match) => (match[1] ?? '').trim()).filter(Boolean);
}

function isToolResultMessage(value: unknown): boolean {
  const message = record(value);
  const role = text(message.role).toLowerCase();
  const type = text(message.type).toLowerCase();
  return role === 'tool' || role === 'toolresult' || type.includes('toolresult') || type.includes('tool_result');
}

function lastUserMessageIndex(messages: unknown[]): number {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    if (text(record(messages[index]).role).toLowerCase() === 'user') return index;
  }
  return -1;
}

function toolName(value: Record<string, unknown>): string {
  return text(value.name) || text(record(value.function).name);
}

function estimateTokens(value: string): number {
  let cjk = 0;
  let other = 0;
  for (const character of value) {
    if (/\s/u.test(character)) continue;
    if (/[\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}\p{Script=Hangul}]/u.test(character)) cjk += 1;
    else other += 1;
  }
  return Math.max(0, cjk + Math.ceil(other / 4));
}

function layerMetric(layer: ContextXrayLayer): string {
  if (layer.state === 'unavailable' || layer.characters === null || layer.estimatedTokens === null) return '数据不可用';
  if (layer.state === 'absent') return '0 字符 · 本轮未注入';
  return `${formatNumber(layer.characters)} 字符 · 约 ${formatTokenCount(layer.estimatedTokens)} token`;
}

function tokenPair(tokens: number | null, window: number | null): string {
  if (tokens === null || window === null) return '不可用';
  return `${formatTokenCount(tokens)} / ${formatTokenCount(window)}`;
}

function formatPercent(value: number | null): string {
  return value === null ? '不可用' : `${Math.round(value)}%`;
}

function formatCompaction(value: ContextXraySnapshot['compaction']): string {
  if (value.status === 'running') return '进行中';
  if (value.tokensBefore !== null && value.tokensAfter !== null) {
    return `${formatTokenCount(value.tokensBefore)} → ${formatTokenCount(value.tokensAfter)}`;
  }
  if (value.count === 0) return '未发生';
  if (value.count !== null) return `${formatNumber(value.count)} 次`;
  return '不可用';
}

function formatTokenCount(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(value >= 10_000_000 ? 1 : 2)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(value >= 100_000 ? 0 : 1)}K`;
  return formatNumber(value);
}

function formatNumber(value: number): string {
  return new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 0 }).format(Math.max(0, value));
}

function compact(value: string): string {
  return value.replace(/\s+/gu, ' ').trim();
}

function stableJson(value: unknown): string {
  if (Array.isArray(value) && value.length === 0) return '';
  if (value && typeof value === 'object' && !Array.isArray(value) && Object.keys(value as object).length === 0) return '';
  try {
    return JSON.stringify(value);
  } catch {
    return '';
  }
}

function array(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function text(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

function finiteNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null;
  const parsed = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function emptySnapshot(): ContextXraySnapshot {
  const unavailable = (id: ContextLayerId, label: string, source: string): ContextXrayLayer => ({
    id,
    label,
    source,
    state: 'unavailable',
    characters: null,
    estimatedTokens: null,
    providerDelivery: 'unavailable',
  });
  return {
    available: false,
    layers: [
      unavailable('system', 'System', '最终 systemPrompt'),
      unavailable('role-book', 'Role Book', '<agent-role-book>'),
      unavailable('session-memory', 'Session Memory', 'type="session_memory"'),
      unavailable('timeline', 'Timeline', 'Session Memory · 近期时间线'),
      unavailable('skills', 'Skills', 'systemPromptOptions.skills'),
      unavailable('tools', 'Tools', 'activeTools + toolSchemas'),
      unavailable('history', 'History', '最终模型调用 · 历史消息'),
      unavailable('tool-results', 'Tool Results', '最终模型调用 · 工具结果'),
    ],
    contextTokens: null,
    contextWindow: null,
    cacheHitPercent: null,
    compaction: {
      count: null,
      status: '',
      tokensBefore: null,
      tokensAfter: null,
    },
    providerStatus: null,
    providerCaptured: false,
    updatedAtMs: null,
  };
}
