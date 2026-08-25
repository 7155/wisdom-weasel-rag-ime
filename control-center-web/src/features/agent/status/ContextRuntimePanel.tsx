import {
  Check,
  ChevronRight,
  CircleDot,
  Clock3,
  Inbox,
  LoaderCircle,
  Network,
  TriangleAlert,
} from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type MouseEvent as ReactMouseEvent,
  type ReactNode,
} from 'react';
import { useControlTransport } from '@/app/control-transport';
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/primitives';
import type { AgentContextItemV1 } from '@/contracts/generated/agent-context-item.v1';
import type { AgentContextTraceV1 } from '@/contracts/generated/agent-context-trace.v1';
import {
  normalizeDebugContextResponse,
  type DebugContextRecord,
} from '@/features/context-debug/model';
import { assemblyStageEvidence, orderContextTraceNodes } from './context-evidence';
import { DebugContextInspector } from './DebugContextInspector';

interface ContextTraceSummary {
  traceId: string;
  sessionId: string;
  turnId: string;
  sourceKind: string;
  status: AgentContextTraceV1['status'];
  finalFingerprint: string;
  nodeCount: number;
  createdAtMs: number;
  updatedAtMs: number;
}

export function ContextRuntimeSections({ sessionId, open }: { sessionId: string; open: boolean }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <>
      <section className="agent-status-section agent-context-runtime">
        <header>
          <Network size={15} />
          <strong>上下文运行时</strong>
        </header>
        <button
          aria-expanded={expanded}
          className="agent-context-runtime-trigger"
          onClick={() => setExpanded((value) => !value)}
          type="button"
        >
          <span>
            <strong>{expanded ? '收起上下文状态' : '查看上下文状态'}</strong>
            <small>异步收件箱与本轮组装管线</small>
          </span>
          <ChevronRight size={14} />
        </button>
      </section>
      {open && expanded ? <ContextRuntimeDetails sessionId={sessionId} /> : null}
    </>
  );
}

function ContextRuntimeDetails({ sessionId }: { sessionId: string }) {
  const transport = useControlTransport();
  const [acknowledgingId, setAcknowledgingId] = useState('');
  const [ackError, setAckError] = useState('');
  const itemsQuery = useQuery({
    queryKey: ['agent', 'context-runtime', 'items', sessionId],
    queryFn: ({ signal }) => transport.request({
      pathId: 'agent.session.contextItems.list',
      params: { sessionId },
      query: { limit: 30 },
      signal,
    }),
    enabled: Boolean(sessionId),
    refetchInterval: 3_000,
    retry: false,
  });
  const tracesQuery = useQuery({
    queryKey: ['agent', 'context-runtime', 'traces', sessionId],
    queryFn: ({ signal }) => transport.request({
      pathId: 'agent.session.contextTraces.list',
      params: { sessionId },
      query: { limit: 20 },
      signal,
    }),
    enabled: Boolean(sessionId),
    refetchInterval: 3_000,
    retry: false,
  });
  const items = useMemo(() => contextItems(itemsQuery.data), [itemsQuery.data]);
  const traces = useMemo(() => contextTraceSummaries(tracesQuery.data), [tracesQuery.data]);
  const activeItems = items.filter((item) => item.status === 'pending' || item.status === 'delivered');
  const [visibleItemCount, setVisibleItemCount] = useState(4);
  const visibleItems = activeItems.slice(0, visibleItemCount);

  async function acknowledge(itemId: string): Promise<void> {
    if (acknowledgingId) return;
    setAcknowledgingId(itemId);
    setAckError('');
    try {
      await transport.request({
        pathId: 'agent.session.contextItems.ack',
        params: { sessionId, itemId },
      });
      await itemsQuery.refetch();
    } catch {
      setAckError('上下文信息确认失败；该信息仍保留，请再次点击它的“确认”。');
    } finally {
      setAcknowledgingId('');
    }
  }

  return (
    <>
      <section className="agent-status-section agent-context-inbox">
        <header>
          <Inbox size={15} />
          <strong>上下文收件箱</strong>
          {activeItems.length > 0 ? <span>{activeItems.length}</span> : null}
        </header>
        {itemsQuery.isPending ? <ContextEmpty animated>正在读取分流上下文</ContextEmpty> : null}
        {itemsQuery.error ? (
          <ContextFailure
            loading={itemsQuery.isFetching}
            owner="上下文收件箱"
            onRetry={() => void itemsQuery.refetch()}
          />
        ) : null}
        {ackError ? <ContextEmpty tone="danger">{ackError}</ContextEmpty> : null}
        {!itemsQuery.isPending && !itemsQuery.error && activeItems.length === 0
          ? <ContextEmpty>没有等待处理的异步信息</ContextEmpty>
          : null}
        {activeItems.length ? (
          <div className="agent-context-items">
            {visibleItems.map((item) => (
              <article key={item.itemId}>
                <CircleDot size={13} />
                <span>
                  <strong>{item.title}</strong>
                  <small>{contextItemDetail(item)}</small>
                </span>
                {item.lifecycle === 'until_ack' || item.lifecycle === 'persistent' ? (
                  <Button
                    aria-label={`确认 ${item.title}`}
                    loading={acknowledgingId === item.itemId}
                    onClick={() => void acknowledge(item.itemId)}
                    size="small"
                    variant="quiet"
                  >
                    确认
                  </Button>
                ) : null}
              </article>
            ))}
            {visibleItems.length < activeItems.length ? <Button className="agent-context-items__load-more" onClick={() => setVisibleItemCount((count) => Math.min(activeItems.length, count + 4))} size="small" variant="quiet">显示更多（{visibleItems.length}/{activeItems.length}）</Button> : null}
          </div>
        ) : null}
      </section>

      <section className="agent-status-section agent-context-traces">
        <header>
          <Network size={15} />
          <strong>上下文管线</strong>
          {traces.length > 0 ? <span>{traces.length}</span> : null}
        </header>
        {tracesQuery.isPending ? <ContextEmpty animated>正在读取组装记录</ContextEmpty> : null}
        {tracesQuery.error ? (
          <ContextFailure
            loading={tracesQuery.isFetching}
            owner="上下文组装记录"
            onRetry={() => void tracesQuery.refetch()}
          />
        ) : null}
        {!tracesQuery.isPending && !tracesQuery.error && traces.length === 0
          ? <ContextEmpty>发送消息后会记录组装阶段</ContextEmpty>
          : null}
        {traces.length ? (
          <ContextPipelineDialog sessionId={sessionId} traces={traces}>
            <button className="agent-context-trace-trigger" type="button">
              <span>
                <strong>{contextSourceLabel(traces[0].sourceKind)}</strong>
                <small>{traceSummary(traces[0])}</small>
              </span>
              <ChevronRight size={14} />
            </button>
          </ContextPipelineDialog>
        ) : null}
      </section>
    </>
  );
}

function ContextPipelineDialog({
  sessionId,
  traces,
  children,
}: {
  sessionId: string;
  traces: ContextTraceSummary[];
  children: ReactNode;
}) {
  const transport = useControlTransport();
  const [open, setOpen] = useState(false);
  const [selectedTraceId, setSelectedTraceId] = useState(traces[0]?.traceId ?? '');
  const [drawerWidth, setDrawerWidth] = useState(() => initialContextDrawerWidth());
  const [resizing, setResizing] = useState(false);
  const resizeCleanup = useRef<(() => void) | null>(null);
  useEffect(() => {
    if (!traces.some((trace) => trace.traceId === selectedTraceId)) {
      setSelectedTraceId(traces[0]?.traceId ?? '');
    }
  }, [selectedTraceId, traces]);
  useEffect(() => {
    if (!open) return undefined;
    const clampToViewport = () => setDrawerWidth((width) => clampContextDrawerWidth(width));
    window.addEventListener('resize', clampToViewport);
    return () => window.removeEventListener('resize', clampToViewport);
  }, [open]);
  useEffect(() => () => resizeCleanup.current?.(), []);
  const traceQuery = useQuery({
    queryKey: ['agent', 'context-runtime', 'trace', sessionId, selectedTraceId],
    queryFn: ({ signal }) => transport.request<AgentContextTraceV1>({
      pathId: 'agent.session.contextTrace.get',
      params: { sessionId, traceId: selectedTraceId },
      signal,
    }),
    enabled: open && Boolean(selectedTraceId),
    retry: false,
  });
  // 与下方内嵌的 DebugContextInspector 使用同一 queryKey，共享同一次
  // debugContext 请求；节点详情因此能直接打开该阶段的具体捕获原文。
  const evidenceTurnId = traceQuery.data?.turnId ?? '';
  const evidenceQuery = useQuery({
    queryKey: ['agent', 'debug-context', sessionId, evidenceTurnId || 'latest'],
    queryFn: ({ signal }) => transport.request({
      pathId: 'agent.session.debugContext.get',
      params: { sessionId },
      query: evidenceTurnId ? { turnId: evidenceTurnId } : {},
      signal,
    }),
    enabled: open && Boolean(evidenceTurnId),
    retry: false,
    staleTime: 2_000,
  });
  const evidenceContext = useMemo(
    () => normalizeDebugContextResponse(evidenceQuery.data).context,
    [evidenceQuery.data],
  );

  function beginResize(event: ReactMouseEvent<HTMLDivElement>): void {
    const dialog = event.currentTarget.closest<HTMLElement>('.agent-context-pipeline-dialog');
    if (!dialog) return;
    const startX = event.clientX;
    const startWidth = dialog.getBoundingClientRect().width;
    const move = (moveEvent: globalThis.MouseEvent) => {
      setDrawerWidth(clampContextDrawerWidth(startWidth + startX - moveEvent.clientX));
    };
    const finish = () => {
      document.removeEventListener('mousemove', move);
      document.removeEventListener('mouseup', finish);
      resizeCleanup.current = null;
      setResizing(false);
    };
    resizeCleanup.current?.();
    resizeCleanup.current = finish;
    document.addEventListener('mousemove', move);
    document.addEventListener('mouseup', finish);
    setResizing(true);
    event.preventDefault();
  }

  function resizeWithKeyboard(event: KeyboardEvent<HTMLDivElement>): void {
    if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
    const delta = event.key === 'ArrowLeft' ? 32 : -32;
    setDrawerWidth((width) => clampContextDrawerWidth(width + delta));
    event.preventDefault();
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>{children}</DialogTrigger>
      <DialogContent
        className="agent-context-pipeline-dialog"
        data-resizing={resizing || undefined}
        style={{ '--agent-context-drawer-width': `${drawerWidth}px` } as CSSProperties}
      >
        <div
          aria-label="调整上下文面板宽度"
          aria-orientation="vertical"
          aria-valuemax={contextDrawerMaximumWidth()}
          aria-valuemin={contextDrawerMinimumWidth()}
          aria-valuenow={Math.round(drawerWidth)}
          className="agent-context-pipeline-resizer"
          onDoubleClick={() => setDrawerWidth(initialContextDrawerWidth())}
          onKeyDown={resizeWithKeyboard}
          onMouseDown={beginResize}
          role="separator"
          tabIndex={0}
        />
        <DialogHeader>
          <DialogTitle>上下文管线</DialogTitle>
          <DialogDescription>查看每个阶段如何形成当前 Pi Runtime 请求；本机 Debug 模式下可继续核对原始输入与最终 Provider Payload。</DialogDescription>
        </DialogHeader>
        <div className="agent-context-pipeline-layout">
          <nav aria-label="上下文组装记录">
            {traces.map((trace) => (
              <button
                aria-current={trace.traceId === selectedTraceId ? 'true' : undefined}
                key={trace.traceId}
                onClick={() => setSelectedTraceId(trace.traceId)}
                type="button"
              >
                <span><strong>{contextSourceLabel(trace.sourceKind)}</strong><small>{formatContextTime(trace.createdAtMs)}</small></span>
                <i data-state={trace.status}>{traceStatusLabel(trace.status)}</i>
              </button>
            ))}
          </nav>
          <section className="agent-context-pipeline-detail" aria-live="polite">
            {traceQuery.isPending ? <ContextEmpty animated>正在读取管线</ContextEmpty> : null}
            {traceQuery.error ? (
              <ContextFailure
                loading={traceQuery.isFetching}
                owner="当前上下文管线"
                onRetry={() => void traceQuery.refetch()}
              />
            ) : null}
            {traceQuery.data ? (
              <>
                <ContextTraceGraph
                  evidenceContext={evidenceContext}
                  evidencePending={evidenceQuery.isPending && Boolean(evidenceTurnId)}
                  trace={traceQuery.data}
                />
                <DebugContextInspector sessionId={sessionId} turnId={traceQuery.data.turnId} embedded />
              </>
            ) : null}
          </section>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function contextDrawerMaximumWidth(): number {
  return Math.max(360, window.innerWidth - 12);
}

function contextDrawerMinimumWidth(): number {
  return Math.min(720, contextDrawerMaximumWidth());
}

function initialContextDrawerWidth(): number {
  return Math.min(1180, contextDrawerMaximumWidth());
}

function clampContextDrawerWidth(width: number): number {
  return Math.min(contextDrawerMaximumWidth(), Math.max(contextDrawerMinimumWidth(), width));
}

function ContextTraceGraph({
  evidenceContext,
  evidencePending = false,
  trace,
}: {
  evidenceContext?: DebugContextRecord;
  evidencePending?: boolean;
  trace: AgentContextTraceV1;
}) {
  const layers = useMemo(() => contextTraceLayers(trace), [trace]);
  const [selectedNodeId, setSelectedNodeId] = useState(trace.nodes.at(-1)?.nodeId ?? '');
  useEffect(() => {
    if (!trace.nodes.some((node) => node.nodeId === selectedNodeId)) {
      setSelectedNodeId(trace.nodes.at(-1)?.nodeId ?? '');
    }
  }, [selectedNodeId, trace]);
  const selected = trace.nodes.find((node) => node.nodeId === selectedNodeId);
  return (
    <>
      <div className="agent-context-trace-meta">
        <span><Clock3 size={14} />{formatContextTime(trace.createdAtMs)}</span>
        <span data-state={trace.status}>{traceStatusLabel(trace.status)}</span>
        <span>{trace.nodes.length} 个阶段</span>
      </div>
      <div className="agent-context-dag" aria-label="上下文组装阶段图">
        {layers.map((layer, index) => (
          <div className="agent-context-dag__layer" key={`layer:${index}`}>
            {layer.map((node) => (
              <button
                aria-pressed={node.nodeId === selectedNodeId}
                data-state={node.disposition}
                key={node.nodeId}
                onClick={() => setSelectedNodeId(node.nodeId)}
                type="button"
              >
                <span>{node.ordinal}</span>
                <strong>{node.label}</strong>
                <small>{node.summary || dispositionLabel(node.disposition)}</small>
              </button>
            ))}
          </div>
        ))}
      </div>
      {selected ? (
        <section className="agent-context-node-detail">
          <header>
            <span>
              <strong>{selected.label}</strong>
              <small>{selected.summary || dispositionLabel(selected.disposition)}</small>
            </span>
            <i data-state={selected.disposition}>{dispositionLabel(selected.disposition)}</i>
          </header>
          <dl>
            <div><dt>来源</dt><dd>{contextSourceLabel(selected.sourceKind)}</dd></div>
            <div><dt>字符</dt><dd>{selected.charCount}</dd></div>
            <div><dt>Token 估算</dt><dd>{selected.tokenEstimate}</dd></div>
            <div><dt>耗时</dt><dd>{selected.durationMs} ms</dd></div>
          </dl>
          {Object.keys(selected.metadata).length ? (
            <div className="agent-context-node-metadata">
              {Object.entries(selected.metadata).map(([key, value]) => (
                <span key={key}><b>{metadataLabel(key)}</b>{String(value)}</span>
              ))}
            </div>
          ) : null}
          {selected.reason ? <p><TriangleAlert size={14} />{selected.reason}</p> : null}
          <ContextNodeEvidence
            context={evidenceContext}
            node={selected}
            pending={evidencePending}
          />
        </section>
      ) : null}
    </>
  );
}

function ContextNodeEvidence({
  context,
  node,
  pending,
}: {
  context?: DebugContextRecord;
  node: AgentContextTraceV1['nodes'][number];
  pending: boolean;
}) {
  if (node.disposition === 'redacted') {
    return <p className="agent-context-node-evidence__note">该阶段内容被权威标记为已隐藏，这里不展示原文。</p>;
  }
  if (node.disposition === 'omitted') {
    return <p className="agent-context-node-evidence__note">该阶段本轮未加入上下文，因此没有随请求发送的原文。</p>;
  }
  if (!context) {
    return (
      <p className="agent-context-node-evidence__note">
        {pending ? '正在读取本轮原文快照…' : '本轮原文快照不可用；以上指标仍来自真实装配记录。'}
      </p>
    );
  }
  const evidence = assemblyStageEvidence(node.stage, context);
  if (!evidence) {
    return <p className="agent-context-node-evidence__note">该阶段没有独立捕获的原文；完整证据见下方「模型上下文增量」。</p>;
  }
  return (
    <section aria-label={evidence.label} className="agent-context-node-evidence">
      <header>
        <strong>{evidence.label}</strong>
        <span>{evidence.value.length.toLocaleString('zh-CN')} 字符</span>
      </header>
      <pre
        aria-label={`${evidence.label}，可滚动原文`}
        data-kind={evidence.kind}
        role="region"
        tabIndex={0}
      >
        {evidence.value}
      </pre>
    </section>
  );
}

export function contextTraceLayers(trace: AgentContextTraceV1): AgentContextTraceV1['nodes'][] {
  const parents = new Map<string, string[]>();
  for (const edge of trace.edges) {
    const list = parents.get(edge.target) ?? [];
    list.push(edge.source);
    parents.set(edge.target, list);
  }
  const depth = new Map<string, number>();
  const resolveDepth = (nodeId: string, visiting = new Set<string>()): number => {
    const cached = depth.get(nodeId);
    if (cached !== undefined) return cached;
    if (visiting.has(nodeId)) return 0;
    const nextVisiting = new Set(visiting).add(nodeId);
    const parentIds = parents.get(nodeId) ?? [];
    const value = parentIds.length
      ? Math.max(...parentIds.map((parentId) => resolveDepth(parentId, nextVisiting))) + 1
      : 0;
    depth.set(nodeId, value);
    return value;
  };
  const layers: AgentContextTraceV1['nodes'][] = [];
  for (const node of orderContextTraceNodes(trace.nodes)) {
    const nodeDepth = Math.min(resolveDepth(node.nodeId), 12);
    (layers[nodeDepth] ??= []).push(node);
  }
  return layers.filter(Boolean);
}

export function contextItems(value: unknown): AgentContextItemV1[] {
  const items = Array.isArray(record(value).items) ? record(value).items as unknown[] : [];
  return items.filter(isContextItem);
}

export function contextTraceSummaries(value: unknown): ContextTraceSummary[] {
  const items = Array.isArray(record(value).items) ? record(value).items as unknown[] : [];
  return items.flatMap((item) => {
    const candidate = record(item);
    const status = text(candidate.status);
    if (!text(candidate.traceId) || !['building', 'accepted', 'failed'].includes(status)) return [];
    return [{
      traceId: text(candidate.traceId),
      sessionId: text(candidate.sessionId),
      turnId: text(candidate.turnId),
      sourceKind: text(candidate.sourceKind),
      status: status as ContextTraceSummary['status'],
      finalFingerprint: text(candidate.finalFingerprint),
      nodeCount: number(candidate.nodeCount),
      createdAtMs: number(candidate.createdAtMs),
      updatedAtMs: number(candidate.updatedAtMs),
    }];
  });
}

function isContextItem(value: unknown): value is AgentContextItemV1 {
  const item = record(value);
  return item.schemaVersion === 'rag-ime.agent-context-item.v1'
    && Boolean(text(item.itemId))
    && Boolean(text(item.sessionId))
    && ['result', 'status', 'notification', 'room', 'schedule', 'fact'].includes(text(item.lane))
    && ['once', 'turn', 'until_ack', 'persistent'].includes(text(item.lifecycle))
    && ['pending', 'delivered', 'consumed', 'acknowledged', 'expired'].includes(text(item.status));
}

function contextItemDetail(item: AgentContextItemV1): string {
  const lane = ({
    result: '结果',
    status: '状态',
    notification: '通知',
    room: 'Room',
    schedule: '日程',
    fact: '事实',
  } as const)[item.lane];
  return `${lane} · ${lifecycleLabel(item.lifecycle)}${item.summary ? ` · ${item.summary}` : ''}`;
}

function lifecycleLabel(value: AgentContextItemV1['lifecycle']): string {
  return ({
    once: '投递一次',
    turn: '本回合',
    until_ack: '确认前保留',
    persistent: '持续可见',
  } as const)[value];
}

function traceSummary(trace: ContextTraceSummary): string {
  return `${trace.nodeCount} 个阶段 · ${formatContextTime(trace.createdAtMs)} · ${traceStatusLabel(trace.status)}`;
}

function traceStatusLabel(value: AgentContextTraceV1['status']): string {
  if (value === 'accepted') return '已交给 Runtime';
  if (value === 'failed') return '组装失败';
  return '正在组装';
}

function dispositionLabel(value: AgentContextTraceV1['nodes'][number]['disposition']): string {
  if (value === 'included') return '已加入';
  if (value === 'omitted') return '未加入';
  if (value === 'redacted') return '已隐藏';
  return '失败';
}

function contextSourceLabel(value: string): string {
  return ({
    user: '用户输入',
    schedule: '日程唤醒',
    room: 'Room 协作',
    room_intercom: 'Room 消息',
    gateway: '产品层 Gateway',
    runtime: 'Pi Runtime',
    wake_schedule: '日程',
  } as Record<string, string>)[value] ?? (value || '未知来源');
}

function metadataLabel(value: string): string {
  return ({
    accepted: '已接受',
    contextItemCount: '上下文项',
    hasImages: '包含图片',
    imageCount: '图片',
    itemCount: '收件箱项',
    mode: '模式',
    modelConfigured: '模型已配置',
    roleId: '角色',
    toolCount: '工具',
    workspaceCount: '工作区',
  } as Record<string, string>)[value] ?? value;
}

function formatContextTime(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return '时间未知';
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(value);
}

function ContextFailure({
  loading,
  owner,
  onRetry,
}: {
  loading: boolean;
  owner: string;
  onRetry: () => void;
}) {
  return (
    <div className="agent-status-query-error" role="alert">
      <span>
        <strong>{owner}读取失败</strong>
        <small>失败结果没有被当作空状态；重新读取只刷新这一项。</small>
      </span>
      <Button size="small" loading={loading} onClick={onRetry}>重新读取{owner}</Button>
    </div>
  );
}

function ContextEmpty({
  children,
  animated = false,
  tone = 'neutral',
}: {
  children: ReactNode;
  animated?: boolean;
  tone?: 'neutral' | 'danger';
}) {
  return (
    <p className="agent-status-empty" data-animated={animated || undefined} data-tone={tone} role={tone === 'danger' ? 'alert' : undefined}>
      {animated ? <LoaderCircle size={13} /> : null}
      {children}
    </p>
  );
}

function record(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function text(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

function number(value: unknown): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}
