import { useQuery } from '@tanstack/react-query';
import {
  BookUser,
  Brain,
  Bot,
  Check,
  ChevronRight,
  CircleHelp,
  Clock3,
  Database,
  FileText,
  Flag,
  History,
  Layers3,
  ListChecks,
  Minimize2,
  PackageOpen,
  ScanSearch,
  Sparkles,
  UserRound,
  Wrench,
  type LucideIcon,
} from 'lucide-react';
import { useId, useMemo, useState } from 'react';
import { useControlTransport } from '@/app/control-transport';
import {
  normalizeDebugContextResponse,
  type DebugContextResponse,
  type DebugModelCall,
} from '@/features/context-debug/model';
import './ContextXrayPanel.css';

type ContextLayerId =
  | 'system'
  | 'project-context'
  | 'role-book'
  | 'workflow-control'
  | 'goal'
  | 'lifecycle-hook'
  | 'session-memory'
  | 'timeline'
  | 'skills'
  | 'tools'
  | 'compaction-summary'
  | 'user-messages'
  | 'assistant-messages'
  | 'tool-calls'
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
  /** Runtime does not expose a trustworthy per-layer token count. */
  tokens: number | null;
  providerDelivery: ProviderDelivery;
  /** 该层实际注入的捕获原文；absent/unavailable 层为 null（PF-CM-010）。 */
  content: string | null;
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
  'project-context': FileText,
  'role-book': BookUser,
  'workflow-control': ListChecks,
  goal: Flag,
  'lifecycle-hook': Sparkles,
  'session-memory': Brain,
  timeline: Clock3,
  skills: Sparkles,
  tools: Wrench,
  'compaction-summary': Minimize2,
  'user-messages': UserRound,
  'assistant-messages': Bot,
  'tool-calls': Wrench,
  history: History,
  'tool-results': PackageOpen,
};

const roleBookPattern = /<agent-profile\b[^>]*>([\s\S]*?)<\/agent-profile>/giu;
const workflowStatePattern = /<workflow-state\b[^>]*>([\s\S]*?)<\/workflow-state>/giu;
const managedContextPattern = /<rag-ime-context\b[^>]*>([\s\S]*?)<\/rag-ime-context>/giu;
const sessionMemoryPattern = typedContextPattern('session_memory');
const goalPattern = typedContextPattern('goal');
const lifecycleHookPattern = typedContextPattern('lifecycle_hook');
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
    // This panel is explicit diagnostics, not runtime state. Repeating a raw
    // context request can compete with the active Session and turn an optional
    // inspector into background load. Collapse/reopen to request a fresh view.
    refetchInterval: false,
    retry: false,
  });
  const response = useMemo(
    () => normalizeDebugContextResponse(query.data),
    [query.data],
  );
  const snapshot = useMemo(() => buildContextXraySnapshot(response), [response]);
  const presentCount = snapshot.layers.filter((layer) => layer.state === 'present').length;
  const deliveredCount = snapshot.layers.filter((layer) => layer.providerDelivery === 'delivered').length;

  return (
    <section className="agent-status-section agent-context-xray">
      <header>
        <ScanSearch size={15} />
        <strong>上下文检查</strong>
        {snapshot.available ? <span>{presentCount}</span> : null}
      </header>
      <button
        aria-expanded={expanded}
        className="agent-context-xray__trigger"
        onClick={() => setExpanded((value) => !value)}
        type="button"
      >
        <span>
          <strong>{expanded ? '收起上下文检查' : '查看上下文检查'}</strong>
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
            <XrayNotice>
              {response.error === 'session_not_resident'
                ? '该 Session 当前未驻留；上下文检查不会为诊断强制唤醒它'
                : response.error === 'runtime_unresponsive'
                  ? 'Runtime 未及时返回上下文快照；正常对话不会被诊断请求阻塞'
                : '这轮尚未形成可核对的上下文快照'}
            </XrayNotice>
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
                字符来自 Runtime 捕获；各层 Token 未单独统计。整轮 Token 与缓存来自 Runtime / Provider，不能可靠分摊到单层。
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
  // 每个已注入分层都能展开到实际内容，摘要行不允许是死行（PF-CM-010）。
  // 原文默认折叠，只有本人显式点开这一层时才进入 DOM。
  const [expanded, setExpanded] = useState(false);
  const contentId = `agent-context-xray-layer-${useId().replaceAll(':', '')}`;
  const Icon = layerIcons[layer.id];
  const summary = (
    <>
      <Icon size={14} />
      <span>
        <strong>{layer.label}</strong>
        <small>{layerMetric(layer)}</small>
        <em>{layer.source}</em>
      </span>
      <ProviderState delivery={layer.providerDelivery} state={layer.state} />
    </>
  );
  if (layer.content === null) {
    return <li data-state={layer.state}><div className="agent-context-xray__layer-row">{summary}</div></li>;
  }
  return (
    <li data-expanded={expanded || undefined} data-state={layer.state}>
      <button
        aria-controls={expanded ? contentId : undefined}
        aria-expanded={expanded}
        className="agent-context-xray__layer-row agent-context-xray__layer-toggle"
        onClick={() => setExpanded((value) => !value)}
        type="button"
      >
        {summary}
        <ChevronRight className="agent-context-xray__layer-caret" size={13} />
      </button>
      {expanded ? (
        <div className="agent-context-xray__layer-content" id={contentId}>
          <pre
            aria-label={`${layer.label} 实际注入内容，可滚动原文`}
            role="region"
            tabIndex={0}
          >
            {layer.content}
          </pre>
        </div>
      ) : null}
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
  const providerContextCaptured = Object.keys(latestCall?.providerContext ?? {}).length > 0;
  const providerCaptured = latestExchange?.payload !== undefined || providerContextCaptured;
  const providerStatus = finiteNumber(latestExchange?.status);
  const providerReceipt = [...array(context.raw.providerRequestReceipts)]
    .map(record)
    .reverse()
    .find((receipt) => (
      finiteNumber(receipt.index) === finiteNumber(latestExchange?.index)
    ));
  const providerAcknowledged = providerStatus !== null || (
    providerReceipt !== undefined
    && Object.prototype.hasOwnProperty.call(providerReceipt, 'usage')
  );
  const providerText = latestExchange?.payload !== undefined
    ? collectProviderText(latestExchange.payload)
    : providerContextCaptured
      ? collectProviderText({
          ...latestCall?.providerContext,
          messages: latestCall?.contextMessages ?? [],
        })
      : '';
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
          tokens: null,
          providerDelivery: 'unavailable',
          content: null,
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
          tokens: null,
          providerDelivery: providerCaptured ? 'missing' : 'unavailable',
          content: null,
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
        tokens: null,
        providerDelivery: !providerCaptured
          ? 'unavailable'
          : !payloadContainsLayer
            ? 'missing'
            : !providerAcknowledged
              ? 'pending'
              : 'delivered',
        content,
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
  const workflowStates = captures(systemPrompt, workflowStatePattern);
  const goals = captures(systemPrompt, goalPattern);
  const lifecycleHooks = captures(systemPrompt, lifecycleHookPattern);
  const sessionBlocks = captures(systemPrompt, sessionMemoryPattern);
  const sessionContent = sessionBlocks.join('\n');
  const timelines = captures(sessionContent, timelineSectionPattern);
  const timelineContent = timelines.join('\n');
  const sessionWithoutTimeline = sessionContent.replace(timelineSectionPattern, '\n').trim();
  const systemWithoutManagedLayers = systemPrompt
    .replace(roleBookPattern, '\n')
    .replace(workflowStatePattern, '\n')
    .replace(managedContextPattern, '\n')
    .replace(/\n{3,}/gu, '\n\n')
    .trim();
  const options = record(systemPromptOptions);
  const contextFiles = array(options.contextFiles).map(record);
  const projectContextContent = contextFiles
    .map((item) => text(item.content).trim())
    .filter(Boolean)
    .join('\n');
  const projectContextNames = contextFiles
    .map((item) => contextFileName(text(item.path)))
    .filter(Boolean);
  const systemWithoutProjectContext = contextFiles.reduce(
    (value, item) => removeLiteral(value, text(item.content)),
    systemWithoutManagedLayers,
  ).replace(/\n{3,}/gu, '\n\n').trim();
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
  const userMessages = messages.filter((message) => messageRole(message) === 'user');
  const assistantMessages = messages
    .filter((message) => messageRole(message) === 'assistant')
    .map(withoutToolCalls);
  const compactionSummaries = messages.filter((message) => messageRole(message) === 'compactionsummary');
  const toolCalls = messages.flatMap((message, messageIndex) => {
    if (messageRole(message) !== 'assistant') return [];
    const calls = array(record(message).content).filter(isToolCallBlock);
    return calls.length ? [{ messageIndex, calls }] : [];
  });
  const toolResults = messages.filter(isToolResultMessage);
  const otherMessages = messages.filter((message) => (
    messageRole(message) !== 'user'
    && messageRole(message) !== 'assistant'
    && messageRole(message) !== 'compactionsummary'
    && !isToolResultMessage(message)
  ));

  return [
    layer(
      'system',
      'System',
      '最终 systemPrompt（已剔除独立上下文层）',
      systemWithoutProjectContext,
      Boolean(systemPrompt),
      contentIdentifiers(systemWithoutProjectContext),
    ),
    layer(
      'project-context',
      '项目规则',
      projectContextNames.length
        ? `systemPromptOptions.contextFiles · ${projectContextNames.join('、')}`
        : 'systemPromptOptions.contextFiles',
      projectContextContent,
      Boolean(Object.keys(options).length),
      contentIdentifiers(projectContextContent),
    ),
    layer('role-book', '伙伴画像', '<agent-profile>', roleBooks.join('\n'), Boolean(systemPrompt)),
    layer(
      'workflow-control',
      '工作状态',
      '<workflow-state>',
      workflowStates.join('\n'),
      Boolean(systemPrompt),
      contentIdentifiers(workflowStates.join('\n')),
    ),
    layer(
      'goal',
      'Goal',
      'type="goal"',
      goals.join('\n'),
      Boolean(systemPrompt),
      contentIdentifiers(goals.join('\n')),
    ),
    layer(
      'lifecycle-hook',
      'Lifecycle Hook',
      'type="lifecycle_hook"',
      lifecycleHooks.join('\n'),
      Boolean(systemPrompt),
      contentIdentifiers(lifecycleHooks.join('\n')),
    ),
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
      'compaction-summary',
      '压缩摘要',
      '最终模型调用 · role=compactionSummary',
      stableJson(compactionSummaries),
      Boolean(latestCall),
      stringLeaves(compactionSummaries),
    ),
    layer(
      'user-messages',
      '用户消息',
      '最终模型调用 · role=user',
      stableJson(userMessages),
      Boolean(latestCall),
      stringLeaves(userMessages),
    ),
    layer(
      'assistant-messages',
      'Agent 消息',
      '最终模型调用 · role=assistant',
      stableJson(assistantMessages),
      Boolean(latestCall),
      stringLeaves(assistantMessages),
    ),
    layer(
      'tool-calls',
      '工具调用',
      '最终模型调用 · assistant.toolCall',
      stableJson(toolCalls),
      Boolean(latestCall),
      stringLeaves(toolCalls),
    ),
    layer(
      'history',
      '其他消息',
      '最终模型调用 · 未识别角色',
      stableJson(otherMessages),
      Boolean(latestCall),
      stringLeaves(otherMessages),
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

function contextFileName(path: string): string {
  return path.split(/[\\/]/u).filter(Boolean).at(-1) ?? '';
}

function removeLiteral(value: string, literal: string): string {
  const trimmed = literal.trim();
  return trimmed ? value.split(trimmed).join('\n') : value;
}

function captures(value: string, pattern: RegExp): string[] {
  pattern.lastIndex = 0;
  return [...value.matchAll(pattern)].map((match) => (match[1] ?? '').trim()).filter(Boolean);
}

function typedContextPattern(type: string): RegExp {
  return new RegExp(
    `<rag-ime-context\\b(?=[^>]*\\btype=["']${type}["'])[^>]*>([\\s\\S]*?)<\\/rag-ime-context>`,
    'giu',
  );
}

function isToolResultMessage(value: unknown): boolean {
  const message = record(value);
  const role = text(message.role).toLowerCase();
  const type = text(message.type).toLowerCase();
  return role === 'tool' || role === 'toolresult' || type.includes('toolresult') || type.includes('tool_result');
}

function isToolCallBlock(value: unknown): boolean {
  const type = text(record(value).type).toLowerCase().replaceAll('_', '').replaceAll('-', '');
  return type === 'toolcall';
}

function withoutToolCalls(value: unknown): unknown {
  const message = record(value);
  if (!Array.isArray(message.content)) return value;
  return { ...message, content: message.content.filter((block) => !isToolCallBlock(block)) };
}

function messageRole(value: unknown): string {
  return text(record(value).role).toLowerCase();
}

function toolName(value: Record<string, unknown>): string {
  return text(value.name) || text(record(value.function).name);
}

function layerMetric(layer: ContextXrayLayer): string {
  if (layer.state === 'unavailable' || layer.characters === null) return '数据不可用';
  if (layer.state === 'absent') return '0 字符 · 本轮未注入';
  return `${formatNumber(layer.characters)} 字符 · Token 未单独统计`;
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
    tokens: null,
    providerDelivery: 'unavailable',
    content: null,
  });
  return {
    available: false,
    layers: [
      unavailable('system', 'System', '最终 systemPrompt'),
      unavailable('project-context', '项目规则', 'systemPromptOptions.contextFiles'),
      unavailable('role-book', '伙伴画像', '<agent-profile>'),
      unavailable('workflow-control', '工作状态', '<workflow-state>'),
      unavailable('goal', 'Goal', 'type="goal"'),
      unavailable('lifecycle-hook', 'Lifecycle Hook', 'type="lifecycle_hook"'),
      unavailable('session-memory', 'Session Memory', 'type="session_memory"'),
      unavailable('timeline', 'Timeline', 'Session Memory · 近期时间线'),
      unavailable('skills', 'Skills', 'systemPromptOptions.skills'),
      unavailable('tools', 'Tools', 'activeTools + toolSchemas'),
      unavailable('compaction-summary', '压缩摘要', '最终模型调用 · role=compactionSummary'),
      unavailable('user-messages', '用户消息', '最终模型调用 · role=user'),
      unavailable('assistant-messages', 'Agent 消息', '最终模型调用 · role=assistant'),
      unavailable('tool-calls', '工具调用', '最终模型调用 · assistant.toolCall'),
      unavailable('history', '其他消息', '最终模型调用 · 未识别角色'),
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
