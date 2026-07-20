import { useQuery } from '@tanstack/react-query';
import {
  Activity,
  ArrowLeft,
  Braces,
  Check,
  Clock3,
  Database,
  FileJson2,
  GitCompareArrows,
  Layers3,
  ListTree,
  Play,
  RefreshCw,
  Server,
  ShieldCheck,
  Wrench,
} from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useControlTransport } from '@/app/control-transport';
import { Button, EmptyState, Select, Switch } from '@/components/primitives';
import { sessionItems, type SessionSummary } from '@/features/agent/types';
import {
  formatJson,
  messagePreview,
  normalizeDebugContextResponse,
  record,
  type DebugContextRecord,
  type DebugModelCall,
  type DebugToolBatch,
  type DebugToolExecution,
} from './model';
import './context-debug.css';

type PayloadTab =
  | 'delta'
  | 'context'
  | 'provider-request'
  | 'provider-response'
  | 'assistant'
  | 'runtime-input'
  | 'system-prompt'
  | 'tool-schemas'
  | 'raw';

const PAYLOAD_TABS: ReadonlyArray<{ id: PayloadTab; label: string }> = [
  { id: 'delta', label: '本次增量' },
  { id: 'context', label: '完整上下文' },
  { id: 'provider-request', label: 'Provider 请求' },
  { id: 'provider-response', label: 'Provider 响应' },
  { id: 'assistant', label: 'Assistant' },
  { id: 'runtime-input', label: 'Runtime 输入' },
  { id: 'system-prompt', label: 'System Prompt' },
  { id: 'tool-schemas', label: '工具 Schema' },
  { id: 'raw', label: '原始记录' },
];

export function ContextDebugFeature() {
  const transport = useControlTransport();
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedSessionId = searchParams.get('sessionId') ?? '';
  const requestedTurnId = searchParams.get('turnId') ?? '';
  const [live, setLive] = useState(true);
  const [selectedCallIndex, setSelectedCallIndex] = useState(0);
  const [payloadTab, setPayloadTab] = useState<PayloadTab>('delta');

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
  const calls = context?.modelCalls ?? [];

  useEffect(() => {
    if (!calls.length) {
      setSelectedCallIndex(0);
      return;
    }
    if (!calls.some((call) => call.index === selectedCallIndex)) {
      setSelectedCallIndex(calls.at(-1)?.index ?? calls[0]?.index ?? 0);
    }
  }, [calls, selectedCallIndex]);

  const selectedCall = calls.find((call) => call.index === selectedCallIndex) ?? calls.at(-1);
  const turnOptions = [
    { value: '', label: '最新回合（自动跟随）' },
    ...response.availableTurns.map((turn) => ({
      value: turn.turnId,
      label: `${formatTimestamp(turn.capturedAtMs)} · ${turn.modelCallCount} 次调用 · ${turn.toolCallCount} 个工具`,
    })),
  ];

  function selectSession(nextSessionId: string): void {
    const next = new URLSearchParams(searchParams);
    next.set('sessionId', nextSessionId);
    next.delete('turnId');
    setSearchParams(next, { replace: true });
    setSelectedCallIndex(0);
  }

  function selectTurn(nextTurnId: string): void {
    const next = new URLSearchParams(searchParams);
    if (nextTurnId) next.set('turnId', nextTurnId);
    else next.delete('turnId');
    setSearchParams(next, { replace: true });
    setSelectedCallIndex(0);
  }

  return (
    <main className="context-debug-feature" data-route-id="context-debug">
      <header className="context-debug-header">
        <div className="context-debug-heading">
          <span className="context-debug-heading__icon"><Braces size={18} /></span>
          <span>
            <h1>上下文透视</h1>
            <small><ShieldCheck size={12} />默认只显示结构和用量，正文仅在审计区按需展开</small>
          </span>
        </div>
        <div className="context-debug-controls">
          <Select
            aria-label="选择 Agent 会话"
            className="context-debug-select context-debug-select--session"
            disabled={!sessionOptions.length}
            onValueChange={selectSession}
            options={sessionOptions}
            placeholder="选择会话"
            value={sessionId}
          />
          <Select
            aria-label="选择上下文回合"
            className="context-debug-select context-debug-select--turn"
            disabled={!sessionId}
            onValueChange={selectTurn}
            options={turnOptions}
            value={requestedTurnId}
          />
          <Switch
            checked={live}
            className="context-debug-live-switch"
            label={live ? '实时' : '暂停'}
            onCheckedChange={setLive}
          />
          <Button
            aria-label="刷新原始上下文"
            leadingIcon={<RefreshCw size={15} />}
            loading={contextQuery.isFetching}
            onClick={() => void contextQuery.refetch()}
            size="small"
          >
            刷新
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
          {response.error || '当前回合没有原始上下文。Pi Runtime 重启后不会保留旧的原始 Prompt，但对话中的脱敏工具轨迹仍会从 JSONL 恢复。'}
        </DebugNotice>
      ) : null}

      <ContextXraySummary call={selectedCall} context={context} telemetry={response.telemetry} />

      <details className="context-debug-audit">
        <summary><Braces size={15} /><span><strong>展开原始审计区</strong><small>按需显示消息正文、Provider 载荷、System Prompt、工具 Schema 与原始记录</small></span></summary>
      <div className="context-debug-workspace">
        <aside className="context-debug-call-rail" aria-label="LLM 调用列表">
          <DebugSummary context={context} />
          <div className="context-debug-call-rail__heading">
            <span><Layers3 size={14} />LLM 调用</span>
            <b>{calls.length}</b>
          </div>
          {calls.length ? (
            <ol>
              {calls.map((call) => (
                <li key={call.index}>
                  <button
                    aria-current={selectedCall?.index === call.index ? 'true' : undefined}
                    onClick={() => setSelectedCallIndex(call.index)}
                    type="button"
                  >
                    <span className="context-debug-call__index">{call.index}</span>
                    <span className="context-debug-call__copy">
                      <strong>模型调用 {call.index}</strong>
                      <small>{call.contextMessages.length} 条消息 · {call.providerExchanges.length} 次 Provider 尝试</small>
                      <span>
                        <em data-tone="added">+{call.contextDelta.addedMessageCount}</em>
                        <em data-tone="removed">-{call.contextDelta.removedMessageCount}</em>
                        <time>{formatTimestamp(call.capturedAtMs)}</time>
                      </span>
                    </span>
                  </button>
                </li>
              ))}
            </ol>
          ) : (
            <p className="context-debug-call-rail__empty">
              {contextQuery.isPending ? '正在读取 Pi Runtime' : '这轮还没有模型调用'}
            </p>
          )}
        </aside>

        <section className="context-debug-main">
          <section className="context-debug-payload" aria-label="原始上下文载荷">
            <header>
              <div>
                <GitCompareArrows size={15} />
                <span>
                  <strong>{selectedCall ? `模型调用 ${selectedCall.index}` : '等待模型调用'}</strong>
                  <small>{selectedCall ? callCaption(selectedCall) : '选择有可用临时上下文的回合'}</small>
                </span>
              </div>
              {selectedCall?.completedAtMs ? <span className="context-debug-state" data-tone="success">已完成</span> : null}
              {selectedCall && !selectedCall.completedAtMs ? <span className="context-debug-state" data-tone="warning">进行中</span> : null}
            </header>
            <nav className="context-debug-tabs" aria-label="上下文载荷类型" role="tablist">
              {PAYLOAD_TABS.map((tab) => (
                <button
                  aria-selected={payloadTab === tab.id}
                  key={tab.id}
                  onClick={() => setPayloadTab(tab.id)}
                  role="tab"
                  type="button"
                >
                  {tab.label}
                </button>
              ))}
            </nav>
            <div className="context-debug-payload__body">
              {context && selectedCall ? (
                <PayloadView call={selectedCall} context={context} tab={payloadTab} />
              ) : (
                <EmptyState
                  description="发送一条 Agent 消息后，这里会按 Provider 调用逐次展示真实请求。"
                  icon={Database}
                  title="暂无原始上下文"
                />
              )}
            </div>
          </section>

          <ToolExecutionTimeline
            batches={context?.toolBatches ?? []}
            selectedCallIndex={selectedCall?.index}
            tools={context?.toolExecutions ?? []}
          />
        </section>
      </div>
      </details>
    </main>
  );
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
  return <section className="context-xray-summary" aria-label="Session 上下文结构">
    <header><span><Layers3 size={16} /><strong>Session Context X-ray</strong></span><small>{context ? `Turn ${shortId(context.turnId)}` : '等待 Runtime 投影'}</small></header>
    <dl>
      <XrayMetric label="Stable prefix" value={stablePrefix} suffix="条" />
      <XrayMetric label="Dynamic tail" value={dynamicTail} suffix="条" />
      <XrayMetric label="Sealed" value={sealed} suffix="条" />
      <XrayMetric label="Pending" value={pending} suffix="条" />
      <XrayMetric label="Cache read" value={cacheRead} suffix="tokens" />
      <XrayMetric label="Cache write" value={cacheWrite} suffix="tokens" />
    </dl>
    <div className="context-xray-summary__states"><span><strong>Cache support / hit</strong><small>{cacheEvidence ? cacheEvidence.capability === 'unsupported' ? 'unsupported · Provider 未报告' : cacheEvidence.cacheReadTokens > 0 ? 'supported · hit' : 'supported · no hit' : '后端未投影'}</small></span><span><strong>Compaction / Recovery</strong><small>{compaction || '未投影'} / {recovery || '未投影'}</small></span><span><strong>Context delta</strong><small>{call ? `共同前缀 ${call.contextDelta.commonPrefixMessages} 条${call.contextDelta.prefixBytes !== undefined ? ` / ${call.contextDelta.prefixBytes} bytes` : ''} · +${call.contextDelta.addedMessageCount} / -${call.contextDelta.removedMessageCount}` : '暂无模型调用'}</small></span></div>
    <p>来源正文默认隐藏。展开下方审计区后，才会显示具体消息、评分调试、Provider 载荷和工具 Schema。</p>
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

function DebugSummary({ context }: { context?: DebugContextRecord }) {
  const model = context?.model ?? {};
  return (
    <dl className="context-debug-summary">
      <div><dt><Server size={13} />模型</dt><dd>{modelLabel(model)}</dd></div>
      <div><dt><ListTree size={13} />回合</dt><dd title={context?.turnId}>{shortId(context?.turnId ?? '') || '未捕获'}</dd></div>
      <div><dt><Wrench size={13} />工具</dt><dd>{context?.toolExecutions.length ?? 0}</dd></div>
      <div><dt><Clock3 size={13} />更新</dt><dd>{formatTimestamp(context?.updatedAtMs ?? 0)}</dd></div>
    </dl>
  );
}

function PayloadView({
  call,
  context,
  tab,
}: {
  call: DebugModelCall;
  context: DebugContextRecord;
  tab: PayloadTab;
}) {
  if (tab === 'delta') {
    return (
      <div className="context-debug-delta">
        <dl>
          <div><dt>共同前缀</dt><dd>{call.contextDelta.commonPrefixMessages} 条</dd></div>
          <div data-tone="added"><dt>新增</dt><dd>+{call.contextDelta.addedMessageCount}</dd></div>
          <div data-tone="removed"><dt>移除</dt><dd>-{call.contextDelta.removedMessageCount}</dd></div>
          <div><dt>基准调用</dt><dd>{call.contextDelta.baseCallIndex ? `#${call.contextDelta.baseCallIndex}` : '初始上下文'}</dd></div>
        </dl>
        <MessageList emptyLabel="本次调用没有新增消息" messages={call.contextDelta.addedMessages} />
      </div>
    );
  }
  if (tab === 'context') return <MessageList emptyLabel="当前调用上下文为空" messages={call.contextMessages} />;
  if (tab === 'provider-request') {
    return <JsonPayload value={call.providerExchanges.map((exchange) => ({ index: exchange.index, capturedAtMs: exchange.capturedAtMs, payload: exchange.payload }))} />;
  }
  if (tab === 'provider-response') {
    return <JsonPayload value={call.providerExchanges.map((exchange) => ({ index: exchange.index, status: exchange.status, headers: exchange.headers }))} />;
  }
  if (tab === 'assistant') return <JsonPayload value={call.assistantMessage ?? null} />;
  if (tab === 'runtime-input') return <TextPayload value={context.prompt} />;
  if (tab === 'system-prompt') return <TextPayload value={context.systemPrompt} />;
  if (tab === 'tool-schemas') return <JsonPayload value={{ activeTools: context.activeTools, schemas: context.toolSchemas }} />;
  return <JsonPayload value={context.raw} />;
}

function MessageList({ emptyLabel, messages }: { emptyLabel: string; messages: unknown[] }) {
  if (!messages.length) return <p className="context-debug-empty-copy">{emptyLabel}</p>;
  return (
    <ol className="context-debug-message-list">
      {messages.map((message, index) => {
        const role = String(record(message).role ?? 'message');
        return (
          <li key={`${role}:${index}`}>
            <details>
              <summary>
                <span data-role={role}>{role}</span>
                <strong>{messagePreview(message) || '结构化消息'}</strong>
                <small>#{index + 1}</small>
              </summary>
              <pre>{formatJson(message)}</pre>
            </details>
          </li>
        );
      })}
    </ol>
  );
}

function JsonPayload({ value }: { value: unknown }) {
  return <pre className="context-debug-code">{formatJson(value)}</pre>;
}

function TextPayload({ value }: { value: string }) {
  return value ? <pre className="context-debug-code context-debug-code--text">{value}</pre> : <p className="context-debug-empty-copy">没有捕获文本</p>;
}

function ToolExecutionTimeline({
  batches,
  selectedCallIndex,
  tools,
}: {
  batches: DebugToolBatch[];
  selectedCallIndex?: number;
  tools: DebugToolExecution[];
}) {
  const toolsById = new Map(tools.map((tool) => [tool.toolCallId, tool]));
  return (
    <section className="context-debug-tools" aria-label="工具串并行执行">
      <header>
        <div><Wrench size={15} /><span><strong>工具执行拓扑</strong><small>按真实生命周期重叠判定并行或串行</small></span></div>
        <span>{tools.length} 次工具 · {batches.length} 个阶段</span>
      </header>
      <div className="context-debug-tools__body">
        {batches.length ? batches.map((batch) => (
          <section
            className="context-debug-tool-stage"
            data-active={batch.modelCallIndex === selectedCallIndex || undefined}
            data-mode={batch.executionMode}
            key={batch.id}
          >
            <header>
              <span className="context-debug-tool-stage__number">阶段 {batch.stage}</span>
              <strong>{batch.executionMode === 'parallel' ? `并行 ${batch.toolCallIds.length} 项` : '串行'}</strong>
              <small>{batch.modelCallIndex ? `模型调用 ${batch.modelCallIndex}` : '未关联模型调用'} · {durationLabel(batch.startedAtMs, batch.endedAtMs)}</small>
            </header>
            <div className="context-debug-tool-stage__items">
              {batch.toolCallIds.map((toolCallId) => {
                const tool = toolsById.get(toolCallId);
                return tool ? <ToolExecutionDetails key={toolCallId} tool={tool} /> : null;
              })}
            </div>
          </section>
        )) : (
          <p className="context-debug-empty-copy">这轮没有工具调用</p>
        )}
      </div>
    </section>
  );
}

function ToolExecutionDetails({ tool }: { tool: DebugToolExecution }) {
  const [open, setOpen] = useState(tool.status !== 'completed');
  return (
    <details
      className="context-debug-tool"
      onToggle={(event) => setOpen(event.currentTarget.open)}
      open={open}
    >
      <summary>
        <span className="context-debug-tool__state" data-status={tool.status}>
          {tool.status === 'running' ? <Play size={12} /> : tool.status === 'failed' ? <Activity size={12} /> : <Check size={12} />}
        </span>
        <span><strong>{tool.toolName}</strong><small>{shortId(tool.toolCallId)}</small></span>
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
  const runtime = call.runtimeTurnIndex === undefined ? '' : `Agent Loop ${call.runtimeTurnIndex + 1}`;
  const attempts = `${call.providerExchanges.length} 次 Provider 尝试`;
  return [runtime, attempts, `${call.contextMessages.length} 条消息`].filter(Boolean).join(' · ');
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
  return error instanceof Error && error.message.trim() ? error.message.trim() : '无法读取本机 Debug 数据';
}
