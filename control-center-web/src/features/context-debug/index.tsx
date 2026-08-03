import { useQuery } from '@tanstack/react-query';
import {
  Activity,
  ArrowLeft,
  Braces,
  Check,
  Clock3,
  Database,
  Download,
  FileJson2,
  Layers3,
  MessageSquareText,
  Play,
  RefreshCw,
  Search,
  ShieldCheck,
  Sparkles,
} from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useControlTransport } from '@/app/control-transport';
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  EmptyState,
  Select,
  Switch,
} from '@/components/primitives';
import { sessionItems, type SessionSummary } from '@/features/agent/types';
import { MarkdownBody } from '@/features/agent/timeline/MarkdownRenderer';
import {
  formatJson,
  describeDebugTurn,
  messagePreview,
  normalizeDebugContextResponse,
  record,
  type DebugContextRecord,
  type DebugModelCall,
  type DebugToolBatch,
  type DebugToolExecution,
  type DebugTurnSummary,
} from './model';
import { buildContextDebugHtml } from './html-export';
import './context-debug.css';

export function ContextDebugFeature() {
  const transport = useControlTransport();
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedSessionId = searchParams.get('sessionId') ?? '';
  const requestedTurnId = searchParams.get('turnId') ?? '';
  const [live, setLive] = useState(true);
  const [htmlPreviewUrls, setHtmlPreviewUrls] = useState<{ download: string; preview: string } | null>(null);
  const [refreshState, setRefreshState] = useState<'idle' | 'pending' | 'succeeded' | 'failed'>('idle');
  const sessionsQuery = useQuery({
    queryKey: ['context-debug', 'sessions'],
    queryFn: ({ signal }) => transport.request({
      pathId: 'agent.sessions.list',
      query: { includeArchived: true, includeInternal: true, limit: 500 },
      signal,
    }),
    staleTime: 5_000,
    retry: false,
  });
  const sessions = useMemo(() => sessionItems(sessionsQuery.data), [sessionsQuery.data]);
  const sessionId = requestedSessionId || sessions[0]?.id || '';
  const sessionOptions = useMemo(
    () => debugSessionOptions(sessions, requestedSessionId),
    [requestedSessionId, sessions],
  );

  useEffect(() => {
    if (requestedSessionId || !sessionId) return;
    const next = new URLSearchParams(searchParams);
    next.set('sessionId', sessionId);
    setSearchParams(next, { replace: true });
  }, [requestedSessionId, searchParams, sessionId, setSearchParams]);

  const contextQuery = useQuery({
    queryKey: ['context-debug', sessionId, requestedTurnId || 'latest'],
    queryFn: ({ signal }) => transport.request({
      pathId: 'agent.session.debugContext.get',
      params: { sessionId },
      query: requestedTurnId ? { turnId: requestedTurnId } : {},
      signal,
    }),
    enabled: Boolean(sessionId),
    refetchInterval: live ? 1_000 : false,
    retry: false,
  });
  const response = useMemo(
    () => normalizeDebugContextResponse(contextQuery.data),
    [contextQuery.data],
  );
  const context = response.context;

  useEffect(() => () => {
    if (!htmlPreviewUrls) return;
    URL.revokeObjectURL(htmlPreviewUrls.preview);
    URL.revokeObjectURL(htmlPreviewUrls.download);
  }, [htmlPreviewUrls]);

  const selectedSessionTitle = sessions.find((session) => session.id === sessionId)?.title ?? '';

  function selectSession(nextSessionId: string): void {
    const next = new URLSearchParams(searchParams);
    next.set('sessionId', nextSessionId);
    next.delete('turnId');
    setSearchParams(next, { replace: true });
  }

  function selectTurn(nextTurnId: string): void {
    const next = new URLSearchParams(searchParams);
    if (nextTurnId) next.set('turnId', nextTurnId);
    else next.delete('turnId');
    setSearchParams(next, { replace: true });
  }

  async function refreshContext(): Promise<void> {
    setRefreshState('pending');
    try {
      const result = await contextQuery.refetch();
      setRefreshState(result.isError ? 'failed' : 'succeeded');
    } catch {
      setRefreshState('failed');
    }
  }

  function showHtmlPreview(): void {
    const generatedAtMs = Date.now();
    const options = {
      generatedAtMs,
      response,
      sessionTitle: selectedSessionTitle,
    };
    const downloadHtml = buildContextDebugHtml(options);
    const previewHtml = buildContextDebugHtml({
      ...options,
      reportScriptSrc: new URL('context-debug-report.js', document.baseURI).href,
    });
    setHtmlPreviewUrls({
      download: URL.createObjectURL(new Blob([downloadHtml], { type: 'text/html;charset=utf-8' })),
      preview: URL.createObjectURL(new Blob([previewHtml], { type: 'text/html;charset=utf-8' })),
    });
  }

  return (
    <>
    <main className="context-debug-feature" data-route-id="context-debug">
      <header className="context-debug-header">
        <div className="context-debug-heading">
          <span className="context-debug-heading__icon"><Braces size={18} /></span>
          <span>
            <h1>上下文检查</h1>
            <small><ShieldCheck size={12} />逐轮还原模型真正收到的上下文；原始载荷按需展开</small>
          </span>
        </div>
        <div className="context-debug-controls">
          <Select
            aria-label="选择对话"
            className="context-debug-select context-debug-select--session"
            disabled={!sessionOptions.length}
            onValueChange={selectSession}
            options={sessionOptions}
            placeholder="选择会话"
            value={sessionId}
          />
          <Switch
            checked={live}
            className="context-debug-live-switch"
            label={live ? '实时' : '暂停'}
            onCheckedChange={setLive}
          />
          <Button
            aria-label="刷新原始上下文"
            aria-live="polite"
            leadingIcon={<RefreshCw size={15} />}
            loading={refreshState === 'pending' || contextQuery.isFetching}
            onClick={() => void refreshContext()}
            size="small"
          >
            {refreshState === 'succeeded' ? '已刷新' : refreshState === 'failed' ? '刷新失败' : '刷新'}
          </Button>
          <Button
            disabled={!context}
            leadingIcon={<FileJson2 size={15} />}
            onClick={showHtmlPreview}
            size="small"
            variant="quiet"
          >
            HTML 报告
          </Button>
          <a className="context-debug-back" href={sessionId ? `#/agent?sessionId=${encodeURIComponent(sessionId)}` : '#/agent'}>
            <ArrowLeft size={14} />对话
          </a>
        </div>
      </header>

      {sessionsQuery.error ? (
        <DebugNotice tone="danger">{errorText(sessionsQuery.error)}</DebugNotice>
      ) : null}
      {contextQuery.error ? (
        <DebugNotice tone="danger">{errorText(contextQuery.error)}</DebugNotice>
      ) : null}
      {!contextQuery.isPending && !contextQuery.error && sessionId && !response.available ? (
        <DebugNotice tone="warning">
          {response.error || '当前回合没有上下文快照。请在“设置 → 隐私与安全”开启本机上下文快照并选择保存目录；未开启时，应用重启后无法恢复旧的系统指令。'}
        </DebugNotice>
      ) : null}

      <ContextDebugDocument
        availableTurns={response.availableTurns}
        context={context}
        loading={contextQuery.isPending}
        onSelectTurn={selectTurn}
        selectedTurnId={requestedTurnId || response.turnId || context?.turnId || ''}
        telemetry={response.telemetry}
      />
    </main>
    <Dialog
      onOpenChange={(open) => {
        if (!open) setHtmlPreviewUrls(null);
      }}
      open={Boolean(htmlPreviewUrls)}
    >
      <DialogContent className="context-debug-html-dialog">
        <DialogHeader>
          <DialogTitle>逐次上下文装配</DialogTitle>
          <DialogDescription>
            这是打开按钮时冻结的本机快照。每个模型调用分别展示当时实际送入模型服务的系统指令、消息、工具定义、请求及工具回写。
          </DialogDescription>
        </DialogHeader>
        {htmlPreviewUrls ? (
          <iframe
            sandbox="allow-scripts"
            src={htmlPreviewUrls.preview}
            title="逐次上下文报告"
          />
        ) : null}
        <footer className="context-debug-html-dialog__footer">
          <span>报告只在本机临时生成；关闭窗口后即释放。</span>
          {htmlPreviewUrls ? (
            <a download="agent-context-debug.html" href={htmlPreviewUrls.download}>
              <Download size={14} />
              下载报告
            </a>
          ) : null}
        </footer>
      </DialogContent>
    </Dialog>
    </>
  );
}

type ContextTreeFilter = 'all' | 'default' | 'no-tools' | 'user-only';

interface ContextTreeEntry {
  depth: 0 | 1;
  id: string;
  kind: 'assistant' | 'call' | 'context' | 'tool' | 'user';
  label: string;
  preview: string;
}

function ContextDebugDocument({
  availableTurns,
  context,
  loading,
  onSelectTurn,
  selectedTurnId,
  telemetry,
}: {
  availableTurns: DebugTurnSummary[];
  context?: DebugContextRecord;
  loading: boolean;
  onSelectTurn: (turnId: string) => void;
  selectedTurnId: string;
  telemetry: Record<string, unknown>;
}) {
  const [activeEntryId, setActiveEntryId] = useState('');
  const [treeFilter, setTreeFilter] = useState<ContextTreeFilter>('default');
  const [treeQuery, setTreeQuery] = useState('');
  const treeEntries = useMemo(() => context ? buildContextTree(context) : [], [context]);
  const visibleTreeEntries = useMemo(
    () => treeEntries.filter((entry) => contextTreeEntryVisible(entry, treeFilter, treeQuery)),
    [treeEntries, treeFilter, treeQuery],
  );
  const orderedTurns = useMemo(
    () => [...availableTurns].sort((left, right) => left.capturedAtMs - right.capturedAtMs),
    [availableTurns],
  );

  useEffect(() => {
    setActiveEntryId('');
    setTreeQuery('');
  }, [context?.turnId]);

  if (!context?.modelCalls.length) {
    return (
      <div className="context-debug-reader__empty">
        <EmptyState
          description={loading ? '正在读取运行上下文。' : '发送一条消息后，这里会按模型调用恢复实际上下文。'}
          icon={Database}
          title={loading ? '正在读取' : '暂无模型调用'}
        />
      </div>
    );
  }

  function revealEntry(id: string): void {
    setActiveEntryId(id);
    const target = document.getElementById(id);
    if (!target) return;
    const reduceMotion = typeof window.matchMedia === 'function'
      && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    target.scrollIntoView?.({ behavior: reduceMotion ? 'auto' : 'smooth', block: 'start' });
    target.focus({ preventScroll: true });
  }

  return (
    <section className="context-debug-session-viewer" aria-label="逐次上下文阅读">
      <aside className="context-debug-session-tree" aria-label="上下文目录">
        <TurnJourney
          currentContext={context}
          onSelectTurn={onSelectTurn}
          selectedTurnId={selectedTurnId || context.turnId}
          turns={orderedTurns}
        />
        <header>
          <label>
            <Search aria-hidden="true" size={13} />
            <input
              aria-label="搜索上下文条目"
              onChange={(event) => setTreeQuery(event.target.value)}
              placeholder="搜索消息或工具…"
              spellCheck={false}
              type="search"
              value={treeQuery}
            />
          </label>
          <div aria-label="上下文目录筛选">
            {([
              ['default', '默认'],
              ['no-tools', '无工具'],
              ['user-only', '用户'],
              ['all', '全部'],
            ] as const).map(([value, label]) => (
              <button
                aria-pressed={treeFilter === value}
                key={value}
                onClick={() => setTreeFilter(value)}
                type="button"
              >
                {label}
              </button>
            ))}
          </div>
        </header>
        <ol>
          {visibleTreeEntries.map((entry) => (
            <li data-depth={entry.depth} data-kind={entry.kind} key={entry.id}>
              <button
                aria-current={activeEntryId === entry.id ? 'location' : undefined}
                onClick={() => revealEntry(entry.id)}
                type="button"
              >
                <span aria-hidden="true">{treeMarker(entry)}</span>
                <strong>{entry.label}</strong>
                <small>{entry.preview}</small>
              </button>
            </li>
          ))}
        </ol>
        <footer>{visibleTreeEntries.length} / {treeEntries.length} 条 · {context.modelCalls.length} 次调用</footer>
      </aside>

      <article className="context-debug-session-content">
        <ContextAssemblyOverview context={context} telemetry={telemetry} turns={orderedTurns} />

        <div className="context-debug-session-preamble">
          <ContextDisclosure
            label="System prompt"
            meta={`${context.systemPrompt.length.toLocaleString('zh-CN')} 字符`}
            tone="system"
          >
            <pre className="context-debug-reader__code context-debug-reader__code--text">
              {context.systemPrompt || '没有捕获 System prompt'}
            </pre>
          </ContextDisclosure>
          <ContextDisclosure
            label={`Available tools (${context.activeTools.length})`}
            meta={context.activeTools.slice(0, 6).join(' · ') || '没有启用工具'}
            tone="tools"
          >
            <div className="context-debug-session-tool-chips">
              {context.activeTools.map((tool) => <span key={tool}>{tool}</span>)}
            </div>
            <pre className="context-debug-reader__code">{formatJson(context.toolSchemas)}</pre>
          </ContextDisclosure>
        </div>

        <div className="context-debug-session-messages">
          {context.modelCalls.map((call) => (
            <ContextCallDocument call={call} context={context} key={call.index} />
          ))}
        </div>

        <footer className="context-debug-session-footer">
          <ContextDisclosure
            label="本轮原始输入"
            meta={`${context.prompt.length.toLocaleString('zh-CN')} 字符`}
            tone="messages"
          >
            <pre className="context-debug-reader__code context-debug-reader__code--text">
              {context.prompt || '没有捕获本轮原始输入'}
            </pre>
          </ContextDisclosure>
          <ContextDisclosure label="本回合原始记录" meta="逐字段核对" tone="raw">
            <pre className="context-debug-reader__code">{formatJson(context.raw)}</pre>
          </ContextDisclosure>
        </footer>
      </article>
    </section>
  );
}

function TurnJourney({
  currentContext,
  onSelectTurn,
  selectedTurnId,
  turns,
}: {
  currentContext: DebugContextRecord;
  onSelectTurn: (turnId: string) => void;
  selectedTurnId: string;
  turns: DebugTurnSummary[];
}) {
  const selectedButtonRef = useRef<HTMLButtonElement>(null);
  const selectedDescription = describeDebugTurn(currentContext, turns);
  useEffect(() => {
    selectedButtonRef.current?.scrollIntoView?.({ block: 'nearest' });
  }, [selectedTurnId]);
  return (
    <nav className="context-debug-turns" aria-label="对话轮次">
      <header>
        <span><Clock3 aria-hidden="true" size={15} /><strong>轮次轨迹</strong></span>
        <small>本机保留 {turns.length} 轮</small>
      </header>
      <ol>
        {turns.map((turn, index) => {
          const label = turn.turnId === currentContext.turnId
            ? selectedDescription.label
            : turnSummaryLabel(turn, index);
          return (
            <li data-phase={turn.assemblyPhase ?? 'unknown'} key={turn.turnId}>
              <button
                aria-current={selectedTurnId === turn.turnId ? 'step' : undefined}
                onClick={() => onSelectTurn(turn.turnId)}
                ref={selectedTurnId === turn.turnId ? selectedButtonRef : undefined}
                type="button"
              >
                <span className="context-debug-turns__ordinal">
                  {String(turn.turnOrdinal ?? index + 1).padStart(2, '0')}
                </span>
                <span className="context-debug-turns__copy">
                  <span><strong>{label}</strong><time>{formatTimestamp(turn.capturedAtMs)}</time></span>
                  <small>{turn.summary || `${turn.modelCallCount} 次模型调用 · ${turn.toolCallCount} 次工具`}</small>
                </span>
              </button>
            </li>
          );
        })}
      </ol>
      <p>这里是可核对的保留窗口；轮换掉的旧轮次不会被伪装成仍然可读。</p>
    </nav>
  );
}

function ContextAssemblyOverview({
  context,
  telemetry,
  turns,
}: {
  context: DebugContextRecord;
  telemetry: Record<string, unknown>;
  turns: DebugTurnSummary[];
}) {
  const description = describeDebugTurn(context, turns);
  const currentIndex = Math.max(0, turns.findIndex((turn) => turn.turnId === context.turnId));
  const latestCall = context.modelCalls.at(-1);
  const messageChanges = context.modelCalls.reduce(
    (total, call) => ({
      added: total.added + call.contextDelta.addedMessageCount,
      removed: total.removed + call.contextDelta.removedMessageCount,
    }),
    { added: 0, removed: 0 },
  );
  const providerMessages = latestCall ? callProviderMessages(latestCall) : [];
  const telemetryContext = record(telemetry.context);
  const tokenCount = projectedNumber(telemetryContext, ['tokens']);
  const layers = contextAssemblyLayers(context, providerMessages, description.phase);
  return (
    <header className="context-debug-assembly" data-phase={description.phase}>
      <div className="context-debug-assembly__title">
        <span className="context-debug-assembly__mark"><Sparkles aria-hidden="true" size={17} /></span>
        <span>
          <small>TURN {String(description.ordinal ?? currentIndex + 1).padStart(2, '0')} · CONTEXT ASSEMBLY</small>
          <h2>{description.label}</h2>
          <p>{description.description}</p>
        </span>
        <em>{formatTimestamp(context.capturedAtMs)}</em>
      </div>
      <dl className="context-debug-assembly__metrics">
        <div><dt>模型</dt><dd>{modelLabel(context.model)}</dd></div>
        <div><dt>最终消息</dt><dd>{providerMessages.length} 条</dd></div>
        <div><dt>本轮调用</dt><dd>{context.modelCalls.length} 次</dd></div>
        <div><dt>上下文用量</dt><dd>{tokenCount === undefined ? '未报告' : `${tokenCount.toLocaleString('zh-CN')} 词元`}</dd></div>
        <div><dt>累计变化</dt><dd>+{messageChanges.added} / -{messageChanges.removed}</dd></div>
      </dl>
      <ol className="context-debug-assembly__layers" aria-label="本轮上下文装配顺序">
        {layers.map((layer, index) => (
          <li data-channel={layer.channel} key={layer.label}>
            <span>{String(index + 1).padStart(2, '0')}</span>
            <div><strong>{layer.label}</strong><small>{layer.detail}</small></div>
            <em>{layer.meta}</em>
          </li>
        ))}
      </ol>
    </header>
  );
}

function contextAssemblyLayers(
  context: DebugContextRecord,
  providerMessages: unknown[],
  phase: ReturnType<typeof describeDebugTurn>['phase'],
): Array<{ label: string; detail: string; meta: string; channel: string }> {
  const options = record(context.systemPromptOptions);
  const skills = Array.isArray(options.skills) ? options.skills : [];
  const injectedMessages = providerMessages.filter((message) => Boolean(record(message).customType));
  const dialogueMessages = providerMessages.filter((message) => !record(message).customType);
  const injectedLabels = [...new Set(injectedMessages.map((message) => (
    customMessageLabel(String(record(message).customType ?? ''))
  )))].filter(Boolean);
  const prioritizedInjectedLabels = phase === 'compaction_recovery'
    ? [...injectedLabels].sort((left, right) => (
        Number(right === '压缩恢复' || right === 'Room 恢复')
        - Number(left === '压缩恢复' || left === 'Room 恢复')
      ))
    : injectedLabels;
  return [
    {
      channel: 'system',
      label: 'System 与项目指令',
      detail: context.systemPrompt ? '角色、边界和项目级约束' : '本轮未捕获系统指令',
      meta: `${context.systemPrompt.length.toLocaleString('zh-CN')} 字符`,
    },
    {
      channel: 'tools',
      label: 'Skills 与工具',
      detail: skills.length ? skills.map((skill) => String(record(skill).name ?? 'Skill')).slice(0, 3).join(' · ') : '按本轮权限声明能力',
      meta: `${skills.length} Skill · ${context.activeTools.length} 工具`,
    },
    {
      channel: 'runtime',
      label: phase === 'compaction_recovery' ? '压缩恢复与运行时' : '项目与运行时上下文',
      detail: prioritizedInjectedLabels.slice(0, 3).join(' · ') || '本轮没有额外注入',
      meta: `${injectedMessages.length} 条注入`,
    },
    {
      channel: 'history',
      label: 'Provider 对话尾部',
      detail: dialogueMessages.length ? '历史与本轮消息按最终发送顺序保留' : '本轮没有对话消息',
      meta: `${dialogueMessages.length} 条消息`,
    },
    {
      channel: 'input',
      label: '当前用户输入',
      detail: compactTreePreview(context.prompt),
      meta: `${context.prompt.length.toLocaleString('zh-CN')} 字符`,
    },
  ];
}

function turnSummaryLabel(turn: DebugTurnSummary, index: number): string {
  if (turn.assemblyPhase === 'initial' || turn.turnOrdinal === 1) return '首轮装配';
  if (turn.assemblyPhase === 'compaction_recovery') return '压缩后恢复';
  if (turn.assemblyPhase === 'incremental') return '增量装配';
  return index === 0 ? '最早保留轮次' : '对话轮次';
}

function ContextCallDocument({ call, context }: { call: DebugModelCall; context: DebugContextRecord }) {
  const tools = context.toolExecutions.filter((tool) => tool.modelCallIndex === call.index);
  const batches = context.toolBatches.filter((batch) => batch.modelCallIndex === call.index);
  const providerMessages = callProviderMessages(call);
  const titleId = `context-debug-call-${call.index}-title`;
  return (
    <section
      aria-labelledby={titleId}
      className="context-debug-session-call"
      id={callEntryId(call.index)}
      tabIndex={-1}
    >
      <header className="context-debug-session-call__marker">
        <h3 id={titleId}>model call <b>{call.index}</b></h3>
        <span>{call.completedAtMs ? 'completed' : 'running'}</span>
        <time>{formatTimestamp(call.capturedAtMs)}</time>
        <small>
          {call.contextDelta.baseCallIndex ? `base #${call.contextDelta.baseCallIndex}` : 'initial context'} · +{call.contextDelta.addedMessageCount} / -{call.contextDelta.removedMessageCount}
        </small>
      </header>

      {!hasExactProviderContext(call) ? (
        <p className="context-debug-session-call__warning">
          legacy snapshot · System prompt 与工具定义来自整轮记录，不是这次请求的精确证据
        </p>
      ) : null}

      <ReadableMessageList
        callIndex={call.index}
        emptyLabel="本次调用没有新增消息"
        messages={call.contextDelta.addedMessages}
      />

      {call.assistantMessage !== undefined ? (
        <ReadableMessageList
          callIndex={call.index}
          emptyLabel="没有捕获模型回复"
          messageId={(index) => assistantEntryId(call.index, index)}
          messages={[call.assistantMessage]}
        />
      ) : null}

      {batches.length || tools.length ? <ContextCallTools batches={batches} tools={tools} /> : null}

      <div className="context-debug-session-call__request">
        <ContextDisclosure
          label="Request details"
          meta={`${providerMessages.length} messages · ${callProviderTools(call, context).length} tools · ${call.providerExchanges.length} provider attempt`}
          tone="provider"
        >
          <dl className="context-debug-session-delta" aria-label={`模型调用 ${call.index} 上下文变化`}>
            <div><dt>common prefix</dt><dd>{call.contextDelta.commonPrefixMessages}</dd></div>
            <div><dt>added</dt><dd>+{call.contextDelta.addedMessageCount}</dd></div>
            <div><dt>removed</dt><dd>-{call.contextDelta.removedMessageCount}</dd></div>
            <div><dt>duration</dt><dd>{durationLabel(call.capturedAtMs, call.completedAtMs)}</dd></div>
          </dl>
          <ContextDisclosure label="System prompt" meta={`${callProviderSystemPrompt(call, context).length} 字符`} tone="system">
            <pre className="context-debug-reader__code context-debug-reader__code--text">{callProviderSystemPrompt(call, context) || '没有捕获 System prompt'}</pre>
          </ContextDisclosure>
          <ContextDisclosure label="Full messages" meta={`${providerMessages.length} 条`} tone="messages">
            <ReadableMessageList callIndex={call.index} emptyLabel="当前调用上下文为空" messages={providerMessages} nested />
          </ContextDisclosure>
          <ContextDisclosure label="Tool schemas" meta={`${callProviderTools(call, context).length} 个`} tone="tools">
            <pre className="context-debug-reader__code">{formatJson(callProviderTools(call, context))}</pre>
          </ContextDisclosure>
          <ContextDisclosure label="Provider exchange" meta={`${call.providerExchanges.length} 次`} tone="provider">
            <pre className="context-debug-reader__code">{formatJson(call.providerExchanges)}</pre>
          </ContextDisclosure>
          <ContextDisclosure label="Raw call" meta="逐字段核对" tone="raw">
            <pre className="context-debug-reader__code">{formatJson(call)}</pre>
          </ContextDisclosure>
        </ContextDisclosure>
      </div>
    </section>
  );
}

function ReadableMessageList({
  callIndex,
  emptyLabel,
  messageId,
  messages,
  nested = false,
}: {
  callIndex: number;
  emptyLabel: string;
  messageId?: (index: number) => string;
  messages: unknown[];
  nested?: boolean;
}) {
  if (!messages.length) return <p className="context-debug-reader__empty-copy">{emptyLabel}</p>;
  return (
    <ol className="context-debug-session-message-list" data-nested={nested || undefined}>
      {messages.map((message, index) => {
        const item = record(message);
        const role = String(item.role ?? 'message').toLowerCase();
        const customType = String(item.customType ?? '');
        const body = readableMessageContent(message);
        const id = messageId?.(index) ?? messageEntryId(callIndex, index);
        return (
          <li
            data-custom={customType || undefined}
            data-role={customType ? 'context' : role}
            id={nested ? undefined : id}
            key={`${role}:${customType}:${index}`}
            tabIndex={nested ? undefined : -1}
          >
            <header>
              <strong>{customType ? customMessageLabel(customType) : contextMessageRoleLabel(role)}</strong>
              <small>#{index + 1}</small>
            </header>
            <div className="context-debug-session-message__body">
              {customType ? body : <MarkdownBody text={body} />}
            </div>
            <details>
              <summary>raw message</summary>
              <pre className="context-debug-reader__code">{formatJson(message)}</pre>
            </details>
          </li>
        );
      })}
    </ol>
  );
}

function ContextCallTools({ batches, tools }: { batches: DebugToolBatch[]; tools: DebugToolExecution[] }) {
  const toolsById = new Map(tools.map((tool) => [tool.toolCallId, tool]));
  const visibleBatches = batches.length ? batches : tools.map((tool, index) => ({
    id: `tool:${tool.toolCallId}`,
    modelCallIndex: tool.modelCallIndex,
    runtimeTurnIndex: tool.runtimeTurnIndex,
    stage: index + 1,
    executionMode: 'serial' as const,
    startedAtMs: tool.startedAtMs,
    endedAtMs: tool.endedAtMs,
    status: tool.status,
    toolCallIds: [tool.toolCallId],
  }));
  return (
    <div className="context-debug-session-tools">
      {visibleBatches.map((batch) => (
        <section data-mode={batch.executionMode} key={batch.id}>
          <header>
            <span>stage {batch.stage}</span>
            <strong>{batch.executionMode === 'parallel' ? `parallel · ${batch.toolCallIds.length} tools` : 'serial'}</strong>
            <small>{durationLabel(batch.startedAtMs, batch.endedAtMs)}</small>
          </header>
          <div>
            {batch.toolCallIds.map((toolCallId) => {
              const tool = toolsById.get(toolCallId);
              return tool ? <ToolExecutionDetails entryId={toolEntryId(toolCallId)} key={toolCallId} tool={tool} /> : null;
            })}
          </div>
        </section>
      ))}
    </div>
  );
}

function buildContextTree(context: DebugContextRecord): ContextTreeEntry[] {
  return context.modelCalls.flatMap((call) => {
    const entries: ContextTreeEntry[] = [{
      depth: 0,
      id: callEntryId(call.index),
      kind: 'call',
      label: `model call ${call.index}`,
      preview: `+${call.contextDelta.addedMessageCount} · ${formatTimestamp(call.capturedAtMs)}`,
    }];
    call.contextDelta.addedMessages.forEach((message, index) => {
      const item = record(message);
      const role = String(item.role ?? 'message').toLowerCase();
      const customType = String(item.customType ?? '');
      entries.push({
        depth: 1,
        id: messageEntryId(call.index, index),
        kind: customType ? 'context' : role === 'user' ? 'user' : role === 'assistant' ? 'assistant' : role.includes('tool') ? 'tool' : 'context',
        label: customType ? customMessageLabel(customType) : contextMessageRoleLabel(role),
        preview: compactTreePreview(readableMessageContent(message)),
      });
    });
    if (call.assistantMessage !== undefined) {
      entries.push({
        depth: 1,
        id: assistantEntryId(call.index, 0),
        kind: 'assistant',
        label: 'Assistant',
        preview: compactTreePreview(readableMessageContent(call.assistantMessage)),
      });
    }
    context.toolExecutions
      .filter((tool) => tool.modelCallIndex === call.index)
      .forEach((tool) => entries.push({
        depth: 1,
        id: toolEntryId(tool.toolCallId),
        kind: 'tool',
        label: tool.toolName,
        preview: compactTreePreview(messagePreview(tool.args) || shortId(tool.toolCallId)),
      }));
    return entries;
  });
}

function contextTreeEntryVisible(entry: ContextTreeEntry, filter: ContextTreeFilter, query: string): boolean {
  const normalizedQuery = query.trim().toLocaleLowerCase('zh-CN');
  if (normalizedQuery && !`${entry.label} ${entry.preview}`.toLocaleLowerCase('zh-CN').includes(normalizedQuery)) return false;
  if (entry.kind === 'call') return filter !== 'user-only' || Boolean(normalizedQuery);
  if (filter === 'default') return entry.kind !== 'context';
  if (filter === 'no-tools') return entry.kind !== 'context' && entry.kind !== 'tool';
  if (filter === 'user-only') return entry.kind === 'user';
  return true;
}

function treeMarker(entry: ContextTreeEntry): string {
  if (entry.kind === 'call') return '◆';
  if (entry.kind === 'user') return '›';
  if (entry.kind === 'assistant') return '•';
  if (entry.kind === 'tool') return '$';
  return '·';
}

function compactTreePreview(value: string): string {
  const compact = value.replace(/\s+/gu, ' ').trim();
  return compact.length > 54 ? `${compact.slice(0, 51)}…` : compact || '结构化消息';
}

function callEntryId(callIndex: number): string {
  return `context-call-${callIndex}`;
}

function messageEntryId(callIndex: number, messageIndex: number): string {
  return `context-call-${callIndex}-message-${messageIndex + 1}`;
}

function assistantEntryId(callIndex: number, messageIndex: number): string {
  return `context-call-${callIndex}-assistant-${messageIndex + 1}`;
}

function toolEntryId(toolCallId: string): string {
  return `context-tool-${toolCallId.replace(/[^A-Za-z0-9_-]/gu, '-')}`;
}

function ContextDisclosure({
  children,
  label,
  meta,
  tone,
}: {
  children: React.ReactNode;
  label: string;
  meta: string;
  tone: 'messages' | 'provider' | 'raw' | 'system' | 'tools';
}) {
  const [open, setOpen] = useState(false);
  return (
    <details
      className="context-debug-reader__disclosure"
      data-tone={tone}
      onToggle={(event) => setOpen(event.currentTarget.open)}
      open={open}
    >
      <summary><span><strong>{label}</strong><small>{meta}</small></span></summary>
      {open ? <div>{children}</div> : null}
    </details>
  );
}

function readableMessageContent(value: unknown): string {
  if (typeof value === 'string') return value;
  if (Array.isArray(value)) return value.map(readableMessageContent).filter(Boolean).join('\n\n');
  const item = record(value);
  const content = item.content;
  if (content !== undefined && content !== value) {
    const rendered = readableMessageContent(content);
    if (rendered) return rendered;
  }
  const direct = [item.text, item.input_text, item.output_text, item.thinking]
    .find((candidate) => typeof candidate === 'string' && candidate.trim());
  if (typeof direct === 'string') return direct;
  const type = String(item.type ?? '').toLowerCase();
  const name = String(item.name ?? record(item.function).name ?? '').trim();
  if (type.includes('tool') || type.includes('function') || name) {
    const args = item.arguments ?? record(item.function).arguments;
    return [`调用工具：${name || '未命名工具'}`, args === undefined ? '' : `参数：${typeof args === 'string' ? args : formatJson(args)}`]
      .filter(Boolean)
      .join('\n');
  }
  return messagePreview(value) || formatJson(value);
}

function customMessageLabel(value: string): string {
  const labels: Record<string, string> = {
    'rag-ime-execution-mode': '执行模式',
    'rag-ime-memory-recall': '记忆召回',
    'rag-ime-work-state': '工作状态',
    'rag-ime-compaction-recovery': '压缩恢复',
    'rag-ime-room-compaction-recovery': 'Room 恢复',
    'rag-ime-session-context': 'Session 上下文',
    'rag-ime-workflow': '工作流',
    'rag-ime-lifecycle': '生命周期',
    'rag-ime-turn-context': '本轮上下文',
  };
  return labels[value] ?? value;
}

function contextMessageRoleLabel(value: string): string {
  const labels: Record<string, string> = {
    assistant: 'Assistant',
    developer: 'System',
    system: 'System',
    tool: 'Tool',
    toolresult: 'Tool Result',
    user: 'User',
  };
  return labels[value.toLowerCase()] ?? 'Message';
}

function ContextXraySummary({ call, context, telemetry }: { call?: DebugModelCall; context?: DebugContextRecord; telemetry: Record<string, unknown> }) {
  const raw = record(context?.raw);
  const projection = record(raw.contextProjection ?? raw.contextAssembly ?? telemetry.contextProjection);
  const usage = record(telemetry.cumulativeUsage ?? telemetry.usage ?? raw.usage);
  const cacheEvidence = context?.cacheEvidence.at(-1);
  const stablePrefix = projectedNumber(projection, ['stablePrefixMessages', 'stablePrefixCount']) ?? call?.contextDelta.commonPrefixMessages;
  const dynamicTail = projectedNumber(projection, ['dynamicTailMessages', 'dynamicTailCount']) ?? call?.contextDelta.addedMessageCount;
  const sealed = projectedNumber(projection, ['sealedMessages', 'sealedCount']);
  const pending = projectedNumber(projection, ['pendingMessages', 'pendingCount']);
  const cacheRead = cacheEvidence?.capability === 'reported' ? cacheEvidence.cacheReadTokens : projectedNumber(usage, ['cacheRead', 'cache_read_input_tokens']);
  const cacheWrite = cacheEvidence?.capability === 'reported' ? cacheEvidence.cacheWriteTokens : projectedNumber(usage, ['cacheWrite', 'cache_creation_input_tokens']);
  const compaction = projectedText(projection, ['compactionState', 'compaction', 'lastCompactionStatus']);
  const recovery = projectedText(projection, ['recoveryState', 'recovery', 'bootstrapRecoveryState']);
  return <section className="context-xray-summary" aria-label="对话上下文结构">
    <header><span><Layers3 size={16} /><strong>上下文组成</strong></span><small>{context ? `回合 ${shortId(context.turnId)}` : '等待运行状态'}</small></header>
    <dl>
      <XrayMetric label="稳定前缀" value={stablePrefix} suffix="条" />
      <XrayMetric label="本轮新增" value={dynamicTail} suffix="条" />
      <XrayMetric label="已封存" value={sealed} suffix="条" />
      <XrayMetric label="待处理" value={pending} suffix="条" />
      <XrayMetric label="缓存读取" value={cacheRead} suffix="词元" />
      <XrayMetric label="缓存写入" value={cacheWrite} suffix="词元" />
    </dl>
    <div className="context-xray-summary__states"><span><strong>缓存状态</strong><small>{cacheEvidence ? cacheEvidence.capability === 'unsupported' ? '模型服务未报告' : cacheEvidence.cacheReadTokens > 0 ? '可用 · 已命中' : '可用 · 未命中' : '尚未收到状态'}</small></span><span><strong>压缩与恢复</strong><small>{compaction || '未报告'} / {recovery || '未报告'}</small></span><span><strong>本轮变化</strong><small>{call ? `共同前缀 ${call.contextDelta.commonPrefixMessages} 条${call.contextDelta.prefixBytes !== undefined ? ` / ${call.contextDelta.prefixBytes} 字节` : ''} · 新增 ${call.contextDelta.addedMessageCount} 条 · 移除 ${call.contextDelta.removedMessageCount} 条` : '暂无模型调用'}</small></span></div>
    <p>正文默认隐藏。打开下方逐次上下文后，可按发生顺序阅读；完整请求和原始结构仍需就地展开。</p>
  </section>;
}

function XrayMetric({ label, suffix, value }: { label: string; suffix: string; value?: number }) {
  return <div data-available={value !== undefined}><dt>{label}</dt><dd>{value === undefined ? '未投影' : `${value.toLocaleString('zh-CN')} ${suffix}`}</dd></div>;
}

function projectedNumber(source: Record<string, unknown>, keys: string[]): number | undefined {
  for (const key of keys) if (typeof source[key] === 'number' && Number.isFinite(source[key])) return source[key] as number;
  return undefined;
}

function projectedText(source: Record<string, unknown>, keys: string[]): string {
  for (const key of keys) if (typeof source[key] === 'string' && source[key]) return source[key] as string;
  return '';
}

function ToolExecutionDetails({ entryId, tool }: { entryId?: string; tool: DebugToolExecution }) {
  const [open, setOpen] = useState(tool.status !== 'completed');
  return (
    <details
      className="context-debug-tool"
      id={entryId}
      onToggle={(event) => setOpen(event.currentTarget.open)}
      open={open}
      tabIndex={entryId ? -1 : undefined}
    >
      <summary>
        <span className="context-debug-tool__state" data-status={tool.status}>
          {tool.status === 'running' ? <Play size={12} /> : tool.status === 'failed' ? <Activity size={12} /> : <Check size={12} />}
        </span>
        <span><strong>{tool.toolName}</strong><small>{compactTreePreview(messagePreview(tool.args) || shortId(tool.toolCallId))}</small></span>
        <em>{durationLabel(tool.startedAtMs, tool.endedAtMs)}</em>
      </summary>
      <div className="context-debug-tool__payloads">
        <section><h4>参数</h4><pre>{formatJson(tool.args)}</pre></section>
        <section><h4>结果</h4><pre>{formatJson(tool.result ?? null)}</pre></section>
        {tool.updates.length ? <section><h4>过程更新</h4><pre>{formatJson(tool.updates)}</pre></section> : null}
      </div>
    </details>
  );
}

function DebugNotice({ children, tone }: { children: string; tone: 'danger' | 'warning' }) {
  return <div className="context-debug-notice" data-tone={tone}>{children}</div>;
}

function debugSessionOptions(sessions: SessionSummary[], requestedSessionId: string) {
  const options = sessions.map((session) => ({
    value: session.id,
    label: `${session.title || '未命名会话'} · ${shortId(session.id)}`,
  }));
  if (requestedSessionId && !sessions.some((session) => session.id === requestedSessionId)) {
    options.unshift({ value: requestedSessionId, label: `指定会话 · ${shortId(requestedSessionId)}` });
  }
  return options;
}

function modelLabel(model: Record<string, unknown>): string {
  const provider = String(model.provider ?? '').trim();
  const name = String(model.name ?? model.id ?? '').trim();
  return [provider, name].filter(Boolean).join(' / ') || '待捕获';
}

function callCaption(call: DebugModelCall): string {
  const runtime = call.runtimeTurnIndex === undefined ? '' : `处理步骤 ${call.runtimeTurnIndex + 1}`;
  const attempts = `${call.providerExchanges.length} 次模型服务尝试`;
  return [runtime, attempts, `${callProviderMessages(call).length} 条消息`].filter(Boolean).join(' · ');
}

function callProviderMessages(call: DebugModelCall): unknown[] {
  if (!Object.hasOwn(call.providerContext, 'messages')) return call.contextMessages;
  return Array.isArray(call.providerContext.messages) ? call.providerContext.messages : [];
}

function callProviderSystemPrompt(call: DebugModelCall, context: DebugContextRecord): string {
  return typeof call.providerContext.systemPrompt === 'string'
    ? call.providerContext.systemPrompt
    : context.systemPrompt;
}

function callProviderTools(call: DebugModelCall, context: DebugContextRecord): unknown[] {
  if (!Object.hasOwn(call.providerContext, 'tools')) return context.toolSchemas;
  return Array.isArray(call.providerContext.tools) ? call.providerContext.tools : [];
}

function hasExactProviderContext(call: DebugModelCall): boolean {
  return Object.keys(call.providerContext).length > 0;
}

function durationLabel(startedAtMs: number, endedAtMs?: number): string {
  if (!startedAtMs) return endedAtMs ? formatTimestamp(endedAtMs) : '时间未知';
  if (!endedAtMs) return '运行中';
  return `${Math.max(0, endedAtMs - startedAtMs)} ms`;
}

function formatTimestamp(value: number): string {
  if (!value) return '待捕获';
  return new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(new Date(value));
}

function shortId(value: string): string {
  if (value.length <= 22) return value;
  return `${value.slice(0, 9)}…${value.slice(-7)}`;
}

function errorText(error: unknown): string {
  return error instanceof Error && error.message.trim() ? error.message.trim() : '无法读取本机上下文记录';
}
