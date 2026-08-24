import {
  Activity,
  Bot,
  Brain,
  Braces,
  ChevronDown,
  CircleDotDashed,
  Database,
  FilterX,
  GitBranch,
  KeyRound,
  LockKeyhole,
  MessagesSquare,
  Network,
  Radio,
  RefreshCw,
  Search,
  TimerReset,
  TriangleAlert,
  Wrench,
  type LucideIcon,
} from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Button, Disclosure, EmptyState, IconButton } from '@/components/primitives';
import type { ObservationEventV1 } from '@/contracts/generated/observation-event.v1';
import { DebugContextInspector } from '@/features/agent/status/DebugContextInspector';
import {
  InlineNotice,
  ManagementPage,
  ManagementSection,
  QueryState,
  StatusBadge,
  numberValue,
} from '@/features/overview/management-ui';
import {
  useObservationFeed,
  type ObservationConnectionState,
  type ObservationFilters,
} from './api';
import './observability.css';

const CATEGORY_FILTERS = [
  'all',
  'agent',
  'tool',
  'context',
  'retrieval',
  'memory',
  'room',
  'intercom',
  'approval',
  'runtime',
] as const;

type CategoryFilter = (typeof CATEGORY_FILTERS)[number];

export function ObservabilityFeature() {
  const [searchParams, setSearchParams] = useSearchParams();
  const category = observationCategory(searchParams.get('category')) ?? 'all';
  const [needle, setNeedle] = useState('');
  const filters = useMemo<ObservationFilters>(() => ({
    ...(searchParams.get('sessionId') ? { sessionId: searchParams.get('sessionId') ?? '' } : {}),
    ...(searchParams.get('roomId') ? { roomId: searchParams.get('roomId') ?? '' } : {}),
    ...(searchParams.get('traceId') ? { traceId: searchParams.get('traceId') ?? '' } : {}),
    ...(category === 'all' ? {} : { category }),
  }), [category, searchParams]);
  const feed = useObservationFeed(filters);
  const visibleItems = useMemo(
    () => feed.items.filter((item) => observationMatches(item, needle)),
    [feed.items, needle],
  );
  const [selectedTraceId, setSelectedTraceId] = useState('');
  const [selectedEventId, setSelectedEventId] = useState('');
  const selectedTrace = useMemo(
    () => visibleItems
      .filter((item) => item.traceId === selectedTraceId)
      .sort((left, right) => left.sequence - right.sequence),
    [selectedTraceId, visibleItems],
  );
  const selectedEvent = visibleItems.find((item) => item.eventId === selectedEventId)
    ?? selectedTrace.at(-1);

  useEffect(() => {
    if (!visibleItems.length) {
      setSelectedTraceId('');
      setSelectedEventId('');
      return;
    }
    if (!visibleItems.some((item) => item.traceId === selectedTraceId)) {
      setSelectedTraceId(visibleItems[0].traceId);
    }
    if (!visibleItems.some((item) => item.eventId === selectedEventId)) {
      setSelectedEventId(visibleItems[0].eventId);
    }
  }, [selectedEventId, selectedTraceId, visibleItems]);

  const runningCount = visibleItems.filter((item) =>
    ['queued', 'running', 'waiting'].includes(item.status),
  ).length;
  const failedCount = visibleItems.filter((item) => item.status === 'failed').length;
  const traceCount = new Set(visibleItems.map((item) => item.traceId)).size;
  const averageDuration = average(
    visibleItems
      .filter((item) => ['completed', 'failed', 'cancelled'].includes(item.status))
      .map((item) => item.durationMs)
      .filter((value): value is number => typeof value === 'number' && value > 0),
  );
  const scoped = Boolean(filters.sessionId || filters.roomId || filters.traceId);
  const snapshotTotal = Math.max(feed.items.length, feed.snapshot?.counts.total ?? 0);
  const snapshotTruncated = Boolean(feed.snapshot?.truncated || snapshotTotal > feed.items.length);
  const snapshotGeneratedAtMs = feed.snapshot?.generatedAtMs ?? 0;
  const showSnapshotAge = feed.connection !== 'live' && snapshotGeneratedAtMs > 0;
  const timelineCountLabel = needle.trim()
    ? `${visibleItems.length} / 已载入 ${feed.items.length}`
    : snapshotTruncated
      ? `最近 ${visibleItems.length} / 共 ${snapshotTotal}`
      : `${visibleItems.length} 条`;

  function selectCategory(next: CategoryFilter): void {
    const params = new URLSearchParams(searchParams);
    if (next === 'all') params.delete('category');
    else params.set('category', next);
    setSearchParams(params, { replace: true });
  }

  function clearScope(): void {
    const params = new URLSearchParams(searchParams);
    for (const key of ['sessionId', 'roomId', 'traceId']) params.delete(key);
    setSearchParams(params, { replace: true });
  }

  function clearViewFilters(): void {
    setNeedle('');
    const params = new URLSearchParams(searchParams);
    params.delete('category');
    setSearchParams(params, { replace: true });
  }

  return (
    <ManagementPage
      actions={(
        <Button
          leadingIcon={<RefreshCw size={15} />}
          loading={feed.isFetching}
          onClick={() => void feed.refresh()}
          size="small"
        >
          刷新
        </Button>
      )}
      description="回看伙伴对话、多人协作、记忆检索和工具操作发生了什么。"
      eyebrow="本机记录"
      routeId="observability"
      title="运行记录"
    >
      <QueryState
        error={feed.error}
        isPending={feed.isPending}
        onRetry={() => void feed.refresh()}
      >
        {snapshotTruncated ? (
          <InlineNotice title={`当前显示最近 ${feed.items.length} / 共 ${snapshotTotal} 条`} tone="warning">
            Runtime 当前只返回最近一段记录；这里明确保留该边界，不把这批结果当作完整历史。
          </InlineNotice>
        ) : null}

        {feed.streamError ? (
          <div className="observation-connection-notice">
            <InlineNotice title="实时连接" tone="warning">{feed.streamError}</InlineNotice>
            <Button onClick={() => void feed.refresh()} size="small">重新连接</Button>
          </div>
        ) : null}

        <section aria-label="运行记录工作台" className="observation-console">
          <header aria-label="实时概况" className="observation-pulse" data-connection={feed.connection}>
            <StatusBadge
              label={connectionLabel(feed.connection)}
              tone={connectionTone(feed.connection)}
            />
            {showSnapshotAge ? (
              <span className="observation-pulse__stat" data-role="snapshot-age">
                快照生成于 {formatTime(snapshotGeneratedAtMs)}
              </span>
            ) : null}
            <span className="observation-pulse__stat">
              <GitBranch aria-hidden="true" size={14} />
              {traceCount} 次流程 · {visibleItems.length} 条事件
            </span>
            <span className="observation-pulse__stat" data-tone={runningCount ? 'active' : undefined}>
              <Radio aria-hidden="true" size={14} />
              进行中 {runningCount}
            </span>
            <span className="observation-pulse__stat" data-tone={failedCount ? 'danger' : undefined}>
              <TriangleAlert aria-hidden="true" size={14} />
              异常 {failedCount}
            </span>
            <span className="observation-pulse__stat">
              <TimerReset aria-hidden="true" size={14} />
              平均耗时 {averageDuration ? formatDuration(averageDuration) : '暂无'}
            </span>
          </header>

          <section aria-label="运行记录筛选" className="observation-controls">
            <div aria-label="事件类型" className="observation-category-tabs" role="group">
              {CATEGORY_FILTERS.map((item) => (
                <button
                  aria-pressed={category === item}
                  data-active={category === item}
                  key={item}
                  onClick={() => selectCategory(item)}
                  type="button"
                >
                  {categoryLabel(item)}
                </button>
              ))}
            </div>
            <label className="observation-search">
              <Search aria-hidden="true" size={15} />
              <input
                aria-label="搜索运行记录"
                onChange={(event) => setNeedle(event.target.value)}
                placeholder="搜索流程、对话、协作或步骤"
                type="search"
                value={needle}
              />
            </label>
            {scoped ? (
              <div className="observation-scope">
                <span>{scopeLabel(filters)}</span>
                <IconButton
                  icon={<FilterX size={15} />}
                  label="清除来源范围"
                  onClick={clearScope}
                  tooltip
                />
              </div>
            ) : null}
          </section>

          <div className="observation-workspace">
            <ManagementSection
              title="事件时间线"
              trailing={<StatusBadge label={timelineCountLabel} tone="neutral" />}
            >
              {visibleItems.length ? (
                <ol className="observation-timeline" aria-label="运行记录事件">
                  {visibleItems.map((item) => (
                    <ObservationRow
                      active={item.eventId === selectedEvent?.eventId}
                      item={item}
                      key={item.eventId}
                      onSelect={() => {
                        setSelectedTraceId(item.traceId);
                        setSelectedEventId(item.eventId);
                      }}
                    />
                  ))}
                </ol>
              ) : (
                <EmptyState
                  action={feed.items.length ? <Button onClick={clearViewFilters} size="small">清除筛选</Button> : <Button onClick={() => void feed.refresh()} size="small">重新检查</Button>}
                  description={feed.items.length ? '当前筛选没有匹配的运行记录。' : '当前范围内还没有结构化运行事件。'}
                  icon={Network}
                  title={feed.items.length ? '没有匹配的记录' : '暂无运行记录'}
                />
              )}
            </ManagementSection>

            <ManagementSection
              title="这次是怎样完成的"
              trailing={selectedTrace.length ? (
                <StatusBadge label={`${selectedTrace.length} 步`} tone="neutral" />
              ) : undefined}
            >
              {selectedTrace.length ? (
                <>
                  <header className="observation-trace-heading">
                    <span><GitBranch size={15} />一次完整流程</span>
                    <small>{traceScope(selectedTrace)}</small>
                  </header>
                  <ol className="observation-trace">
                    {selectedTrace.map((item, index) => (
                      <li data-active={item.eventId === selectedEvent?.eventId} data-category={item.category} data-status={item.status} key={`${item.eventId}:trace`}>
                        <article className="observation-trace__card">
                          <button className="observation-trace__summary" onClick={() => setSelectedEventId(item.eventId)} type="button">
                            <span className="observation-trace__index">{index + 1}</span>
                            <span>
                              <strong>{publicObservationSummary(item)}</strong>
                              <small>{categoryLabel(item.category)} · {statusLabel(item.status)}</small>
                            </span>
                            <time dateTime={new Date(item.createdAtMs).toISOString()}>
                              {formatTime(item.createdAtMs)}
                            </time>
                          </button>
                          <ObservationFacts item={item} />
                        </article>
                      </li>
                    ))}
                  </ol>
                  {selectedEvent?.sessionId ? (
                    <div className="observation-debug-actions">
                      <a href={`#/context-debug?sessionId=${encodeURIComponent(selectedEvent.sessionId)}${selectedEvent.turnId ? `&turnId=${encodeURIComponent(selectedEvent.turnId)}` : ''}`}>
                        <Braces size={15} />
                        <span><strong>查看这轮的完整上下文</strong><small>逐次核对新增内容、模型请求和工具执行</small></span>
                      </a>
                      <Disclosure
                        className="observation-debug-context"
                        summary={<><Database size={15} /><span><strong>在这里快速查看</strong><small>{selectedEvent.turnId ? '读取本轮临时快照' : '读取当前对话的最新临时快照'}</small></span></>}
                        title={selectedEvent.turnId || selectedEvent.sessionId}
                      >
                        <DebugContextInspector sessionId={selectedEvent.sessionId} turnId={selectedEvent.turnId || undefined} embedded />
                      </Disclosure>
                    </div>
                  ) : null}
                </>
              ) : (
                <EmptyState
                  description="从左侧时间线选择一条记录后，这里会按顺序还原同一次工作的前后步骤。"
                  icon={GitBranch}
                  title="选择一条运行记录"
                />
              )}
            </ManagementSection>
          </div>

          <footer className="observation-privacy">
            <LockKeyhole aria-hidden="true" size={14} />
            <p>运行记录只保存状态、耗时、数量和脱敏后的标识。开启“本机上下文快照”后，可以在上下文检查中查看指定目录保存的脱敏记录；未开启时只查看当前运行中的内容。</p>
          </footer>
        </section>
      </QueryState>
    </ManagementPage>
  );
}

function ObservationRow({
  active,
  item,
  onSelect,
}: {
  active: boolean;
  item: ObservationEventV1;
  onSelect: () => void;
}) {
  const Icon = categoryIcon(item.category);
  return (
    <li data-active={active} data-category={item.category} data-status={item.status}>
      <button aria-current={active ? 'true' : undefined} onClick={onSelect} type="button">
        <span className="observation-row__icon"><Icon size={16} /></span>
        <span className="observation-row__copy">
          <strong>{publicObservationSummary(item)}</strong>
          <small>{categoryLabel(item.category)} · {phaseLabel(item.phase)}</small>
        </span>
        <span className="observation-row__scope">
          <small>{primaryScope(item)}</small>
          <time dateTime={new Date(item.createdAtMs).toISOString()}>
            {formatTime(item.createdAtMs)}
          </time>
        </span>
        <StatusBadge label={statusLabel(item.status)} tone={statusTone(item.status)} />
      </button>
    </li>
  );
}

function ObservationFacts({ item }: { item: ObservationEventV1 }) {
  const [expanded, setExpanded] = useState(false);
  const progress = observationProgress(item);
  const facts = observationFacts(item, new Set(progress?.sourceKeys ?? []));
  const initialFacts = facts.slice(0, 8);
  const additionalFacts = facts.slice(8);
  if (!facts.length && !progress) return null;
  return (
    <div className="observation-facts-shell">
      {progress ? (
        <div className="observation-progress">
          <span><strong>工具进度</strong><small>{progress.current} / {progress.total}</small></span>
          <progress aria-label={`工具进度 ${progress.current} / ${progress.total}`} max={progress.total} value={progress.current} />
        </div>
      ) : null}
      {initialFacts.length ? <ObservationFactList facts={initialFacts} /> : null}
      {additionalFacts.length ? (
        <Disclosure
          className="observation-facts__disclosure"
          onOpenChange={setExpanded}
          revealClassName="observation-facts__reveal"
          summary={<>
            <ChevronDown aria-hidden="true" size={14} />
            {expanded ? `收起其余 ${additionalFacts.length} 项事实` : `查看其余 ${additionalFacts.length} 项事实`}
          </>}
        >
          <ObservationFactList facts={additionalFacts} nested />
        </Disclosure>
      ) : null}
    </div>
  );
}

function ObservationFactList({ facts, nested = false }: { facts: [string, string][]; nested?: boolean }) {
  return (
    <dl className="observation-facts" data-nested={nested || undefined}>
      {facts.map(([label, value], index) => (
        <div key={`${label}:${value}:${index}`}>
          <dt>{label}</dt>
          <dd title={value}>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function observationFacts(item: ObservationEventV1, excludedMetricKeys = new Set<string>()): [string, string][] {
  const facts: [string, string][] = [];
  if (item.durationMs !== null) facts.push(['耗时', formatDuration(item.durationMs)]);
  const model = primitiveAttribute(item.attributes.modelName) || primitiveAttribute(item.attributes.model);
  const provider = primitiveAttribute(item.attributes.provider);
  if (model) facts.push(['模型', model]);
  if (provider) facts.push(['模型服务', provider]);
  for (const [key, value] of Object.entries(item.metrics)) {
    if (excludedMetricKeys.has(key) || value === null || typeof value === 'object') continue;
    facts.push([metricLabel(key), displayMetric(key, value)]);
  }
  if (item.refs.length) facts.push(['引用', String(item.refs.length)]);
  facts.push(['隐私', privacyLabel(item.privacyClass)]);
  return facts;
}

type ObservationProgress = {
  current: number;
  total: number;
  sourceKeys: string[];
};

function observationProgress(item: ObservationEventV1): ObservationProgress | null {
  if (item.category !== 'tool') return null;
  const nested = item.metrics.progress;
  if (nested && typeof nested === 'object' && !Array.isArray(nested)) {
    const current = finiteMetric((nested as Record<string, unknown>).current);
    const total = finiteMetric((nested as Record<string, unknown>).total);
    if (current !== null && total !== null && total > 0) {
      return { current: Math.min(current, total), total, sourceKeys: ['progress'] };
    }
  }
  for (const [currentKey, totalKey] of [
    ['progressCurrent', 'progressTotal'],
    ['completedCount', 'totalCount'],
    ['processedCount', 'totalCount'],
    ['scannedCount', 'totalCount'],
    ['scanned', 'total'],
    ['current', 'total'],
  ] as const) {
    const current = finiteMetric(item.metrics[currentKey]);
    const total = finiteMetric(item.metrics[totalKey]);
    if (current !== null && total !== null && total > 0) {
      return { current: Math.min(current, total), total, sourceKeys: [currentKey, totalKey] };
    }
  }
  return null;
}

function finiteMetric(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null;
}

function categoryIcon(category: ObservationEventV1['category']): LucideIcon {
  return {
    context: Brain,
    retrieval: Database,
    memory: Brain,
    tool: Wrench,
    agent: Bot,
    room: MessagesSquare,
    intercom: KeyRound,
    approval: LockKeyhole,
    runtime: Activity,
    system: CircleDotDashed,
  }[category];
}

function observationMatches(item: ObservationEventV1, rawNeedle: string): boolean {
  const needle = rawNeedle.trim().toLocaleLowerCase();
  if (!needle) return true;
  return [
    item.summary,
    item.traceId,
    item.spanId,
    item.sessionId,
    item.roomId,
    item.turnId,
    item.runId,
    item.phase,
    item.name,
  ].some((value) => value.toLocaleLowerCase().includes(needle));
}

function primaryScope(item: ObservationEventV1): string {
  if (item.roomId) return '多人协作';
  if (item.sessionId) return '伙伴对话';
  if (item.runId) return '后台任务';
  return '一次流程';
}

function traceScope(items: ObservationEventV1[]): string {
  const item = items[0];
  return item ? primaryScope(item) : '';
}

function scopeLabel(filters: ObservationFilters): string {
  if (filters.sessionId) return '只看这段对话';
  if (filters.roomId) return '只看这个协作空间';
  if (filters.traceId) return '只看这次流程';
  return '限定范围';
}

function categoryLabel(value: CategoryFilter | ObservationEventV1['category']): string {
  return {
    all: '全部',
    context: '上下文',
    retrieval: '检索',
    memory: '记忆',
    tool: '工具',
    agent: '伙伴',
    room: '协作',
    intercom: '伙伴消息',
    approval: '确认',
    runtime: '系统',
    system: '系统',
  }[value];
}

function statusLabel(status: ObservationEventV1['status']): string {
  return {
    queued: '排队',
    running: '运行中',
    waiting: '等待',
    completed: '已完成',
    failed: '失败',
    cancelled: '已取消',
    info: '信息',
  }[status];
}

/**
 * Shared PAWOS status language: queued stays neutral, running uses the active
 * blue, waiting alone is amber, completed is quiet green, failed is red.
 * Folding queued/running into amber would overstate how much needs attention.
 */
function statusTone(status: ObservationEventV1['status']): 'success' | 'warning' | 'danger' | 'info' | 'neutral' {
  if (status === 'completed') return 'success';
  if (status === 'failed') return 'danger';
  if (status === 'running') return 'info';
  if (status === 'waiting') return 'warning';
  return 'neutral';
}

function connectionLabel(state: ObservationConnectionState): string {
  return {
    connecting: '正在连接',
    live: '实时',
    reconnecting: '正在重连',
    offline: '快照模式',
  }[state];
}

function connectionTone(state: ObservationConnectionState): 'success' | 'warning' | 'neutral' {
  if (state === 'live') return 'success';
  if (state === 'offline' || state === 'reconnecting') return 'warning';
  return 'neutral';
}

function phaseLabel(phase: string): string {
  return ({
    tool_started: '开始',
    tool_progress: '执行中',
    tool_finished: '结束',
    turn_completed: '回合完成',
    turn_failed: '回合失败',
    message_completed: '消息完成',
    compaction_started: '开始压缩',
    compaction_completed: '压缩完成',
    status_changed: '状态更新',
    started: '已捕获',
    retrieval_complete: '检索完成',
    draft_ready: '草案就绪',
    approval_required: '等待确认',
    delivered: '已送达',
    applied: '已应用',
    rolled_back: '已回滚',
  } as Record<string, string>)[phase] ?? '其他步骤';
}

function metricLabel(key: string): string {
  return ({
    argumentFieldCount: '参数字段',
    resultFieldCount: '结果字段',
    evidenceCount: '证据',
    candidateCount: '候选',
    elapsedMs: '累计耗时',
    eventCount: '输入事件',
    changeCount: '变更',
    messageCount: '消息',
    characterCount: '字符',
    pendingEventCount: '待整理',
    pendingDraftCount: '待审草案',
    contextTokens: '上下文用量',
    contextWindowTokens: '窗口',
    contextPercent: '上下文占用',
    remainingTokens: '剩余',
    compactAtTokens: '压缩阈值',
    tokensUntilCompact: '距压缩',
    inputTokens: '输入用量',
    outputTokens: '输出用量',
    cacheReadTokens: '缓存读取',
    cacheWriteTokens: '缓存写入',
    totalTokens: '总用量',
    cacheHitPercent: '缓存命中',
    compactionCount: '压缩次数',
    tokensBefore: '压缩前',
    estimatedTokensAfter: '压缩后约',
  } as Record<string, string>)[key] ?? '其他数据';
}

function displayMetric(key: string, value: unknown): string {
  if (key.endsWith('Percent') && typeof value === 'number') return `${Math.round(value)}%`;
  if (key.toLocaleLowerCase().includes('token') && typeof value === 'number') return formatTokens(value);
  return displayValue(value);
}

function displayValue(value: unknown): string {
  if (typeof value === 'boolean') return value ? '是' : '否';
  if (typeof value === 'number') return String(numberValue(value));
  return String(value);
}

function publicObservationSummary(item: ObservationEventV1): string {
  const value = item.summary.trim()
    .replace(/\bime\.memory\b/giu, '记忆工具')
    .replace(/\bsidecar\b/giu, '本机补全服务')
    .replace(/\bprovider\b/giu, '模型服务')
    .replace(/\bAgent 私信\b/giu, '伙伴消息')
    .replace(/\bAgent 回合\b/giu, '伙伴本轮')
    .replace(/\bAgent\b/giu, '伙伴');
  return value || `${categoryLabel(item.category)}进度已更新`;
}

function primitiveAttribute(value: unknown): string {
  return typeof value === 'string' || typeof value === 'number' ? String(value) : '';
}

function formatTokens(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(value >= 100_000 ? 0 : 1)}K`;
  return String(Math.max(0, Math.round(value)));
}

function privacyLabel(value: ObservationEventV1['privacyClass']): string {
  return {
    metadata: '仅元数据',
    redacted: '已脱敏',
    owner_local: '仅本机所有者',
  }[value];
}

function observationCategory(value: string | null): CategoryFilter | null {
  return CATEGORY_FILTERS.includes(value as CategoryFilter) ? value as CategoryFilter : null;
}

function formatTime(timestampMs: number): string {
  return new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).format(new Date(timestampMs));
}

function formatDuration(durationMs: number): string {
  if (durationMs < 1_000) return `${Math.round(durationMs)} ms`;
  if (durationMs < 60_000) return `${(durationMs / 1_000).toFixed(1)} s`;
  return `${Math.floor(durationMs / 60_000)}m ${Math.round((durationMs % 60_000) / 1_000)}s`;
}

function average(values: number[]): number {
  return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : 0;
}
