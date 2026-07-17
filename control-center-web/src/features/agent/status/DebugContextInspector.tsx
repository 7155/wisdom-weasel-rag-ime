import { useQuery } from '@tanstack/react-query';
import { Braces, Check, Clipboard, Database, FileText, Gauge, Wrench } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useControlTransport } from '@/app/control-transport';
import { IconButton } from '@/components/primitives';
import './DebugContextInspector.css';

interface DebugSection {
  id: string;
  label: string;
  detail: string;
  kind: 'text' | 'json';
  value: unknown;
}

export function DebugContextInspector({
  sessionId,
  turnId,
  enabled = true,
  embedded = false,
}: {
  sessionId: string;
  turnId?: string;
  enabled?: boolean;
  embedded?: boolean;
}) {
  const transport = useControlTransport();
  const query = useQuery({
    queryKey: ['agent', 'debug-context', sessionId, turnId ?? 'latest'],
    queryFn: ({ signal }) => transport.request({
      pathId: 'agent.session.debugContext.get',
      params: { sessionId },
      query: turnId ? { turnId } : {},
      signal,
    }),
    enabled: enabled && Boolean(sessionId),
    retry: false,
    staleTime: 2_000,
  });
  const response = useMemo(() => normalizeDebugResponse(query.data), [query.data]);
  const sections = useMemo(() => debugSections(response.context), [response.context]);
  const [selectedId, setSelectedId] = useState('prompt');
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!sections.some((section) => section.id === selectedId)) {
      setSelectedId(sections[0]?.id ?? '');
    }
  }, [sections, selectedId]);
  const selected = sections.find((section) => section.id === selectedId);
  const rendered = selected ? renderDebugValue(selected) : '';

  async function copySelected(): Promise<void> {
    if (!rendered) return;
    try {
      await navigator.clipboard.writeText(rendered);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1_400);
    } catch {
      setCopied(false);
    }
  }

  return (
    <section className="debug-context-inspector" data-embedded={embedded || undefined}>
      <header className="debug-context-inspector__header">
        <span><Database size={15} /><strong>请求与原始上下文</strong><small>本机 Debug · 临时内存，不写入观察数据库</small></span>
        {selected ? (
          <IconButton
            icon={copied ? <Check size={14} /> : <Clipboard size={14} />}
            label={copied ? '已复制' : '复制当前内容'}
            onClick={() => void copySelected()}
            size="small"
            tooltip
          />
        ) : null}
      </header>
      {query.isPending ? <p className="debug-context-inspector__empty">正在向 Pi Runtime 读取本轮临时快照</p> : null}
      {query.error ? <p className="debug-context-inspector__empty" data-tone="warning">{debugContextErrorMessage(query.error)}</p> : null}
      {!query.isPending && !query.error && !response.available ? <p className="debug-context-inspector__empty">这轮没有可用的临时上下文；Runtime 重启后不会保留旧快照</p> : null}
      {response.available ? <DebugTelemetryStrip telemetry={response.telemetry} /> : null}
      {sections.length ? (
        <div className="debug-context-inspector__workspace">
          <nav aria-label="原始上下文部分">
            {sections.map((section) => (
              <button
                aria-current={section.id === selectedId ? 'true' : undefined}
                key={section.id}
                onClick={() => setSelectedId(section.id)}
                type="button"
              >
                <DebugSectionIcon id={section.id} />
                <span><strong>{section.label}</strong><small>{section.detail}</small></span>
              </button>
            ))}
          </nav>
          <section className="debug-context-inspector__payload" aria-live="polite">
            <header><strong>{selected?.label}</strong><small>{selected?.detail}</small></header>
            <pre>{rendered}</pre>
          </section>
        </div>
      ) : null}
    </section>
  );
}

function DebugTelemetryStrip({ telemetry }: { telemetry: Record<string, unknown> }) {
  const context = record(telemetry.context);
  const latestUsage = record(telemetry.latestUsage);
  const cachePercent = finiteNumber(telemetry.latestCacheHitPercent);
  return (
    <div className="debug-context-inspector__metrics" aria-label="本轮上下文与缓存指标">
      <span><Gauge size={14} /><small>上下文</small><strong>{tokenPair(context.tokens, context.contextWindow)}</strong></span>
      <span><Database size={14} /><small>缓存命中</small><strong>{cachePercent === null ? '待校准' : `${Math.round(cachePercent)}%`}</strong></span>
      <span><FileText size={14} /><small>输入</small><strong>{tokenCount(tokenTotal(latestUsage, ['input', 'cacheRead', 'cacheWrite']))}</strong></span>
      <span><Braces size={14} /><small>输出</small><strong>{tokenCount(finiteNumber(latestUsage.output) ?? 0)}</strong></span>
    </div>
  );
}

function debugSections(context: Record<string, unknown>): DebugSection[] {
  if (!Object.keys(context).length) return [];
  const sections: DebugSection[] = [
    { id: 'prompt', label: 'Runtime 输入', detail: `${text(context.prompt).length} 字符`, kind: 'text', value: text(context.prompt) },
    { id: 'system-prompt', label: 'System Prompt', detail: `${text(context.systemPrompt).length} 字符`, kind: 'text', value: text(context.systemPrompt) },
    { id: 'system-options', label: 'Prompt 构建选项', detail: 'Pi 资源装配参数', kind: 'json', value: context.systemPromptOptions },
    { id: 'tools', label: '活动工具 Schema', detail: `${array(context.activeTools).length} 个工具`, kind: 'json', value: { activeTools: context.activeTools, schemas: context.toolSchemas } },
  ];
  const modelCalls = array(context.modelCalls);
  if (modelCalls.length) {
    sections.push({
      id: 'model-calls',
      label: '模型调用链',
      detail: `${modelCalls.length} 次模型调用`,
      kind: 'json',
      value: modelCalls,
    });
  }
  const toolExecutions = array(context.toolExecutions);
  if (toolExecutions.length) {
    sections.push({
      id: 'tool-executions',
      label: '工具调用实录',
      detail: `${toolExecutions.length} 次工具执行`,
      kind: 'json',
      value: toolExecutions,
    });
  }
  const toolBatches = array(context.toolBatches);
  if (toolBatches.length) {
    sections.push({
      id: 'tool-batches',
      label: '工具执行批次',
      detail: `${toolBatches.length} 个串并行批次`,
      kind: 'json',
      value: toolBatches,
    });
  }
  array(context.contextWindows).forEach((item, index) => {
    const window = record(item);
    sections.push({
      id: `context:${index}`,
      label: `模型上下文 ${finiteNumber(window.index) ?? index + 1}`,
      detail: `${array(window.messages).length} 条消息`,
      kind: 'json',
      value: window.messages,
    });
  });
  array(context.providerRequests).forEach((item, index) => {
    const request = record(item);
    sections.push({
      id: `provider:${index}`,
      label: `Provider 请求 ${finiteNumber(request.index) ?? index + 1}`,
      detail: '发送前最终 Payload',
      kind: 'json',
      value: request.payload,
    });
  });
  return sections;
}

function DebugSectionIcon({ id }: { id: string }) {
  if (id === 'tools' || id === 'tool-executions' || id === 'tool-batches') return <Wrench size={14} />;
  if (id.startsWith('provider:')) return <Braces size={14} />;
  if (id.startsWith('context:')) return <Database size={14} />;
  return <FileText size={14} />;
}

function renderDebugValue(section: DebugSection): string {
  if (section.kind === 'text') return text(section.value);
  try {
    return JSON.stringify(section.value ?? null, null, 2);
  } catch {
    return String(section.value ?? '');
  }
}

function normalizeDebugResponse(value: unknown): {
  available: boolean;
  context: Record<string, unknown>;
  telemetry: Record<string, unknown>;
} {
  const response = record(value);
  return {
    available: response.available === true,
    context: record(response.context),
    telemetry: record(response.telemetry),
  };
}

function debugContextErrorMessage(error: unknown): string {
  if (error instanceof Error && error.message.trim()) return error.message.trim();
  const value = record(error);
  const message = text(value.message) || text(value.error);
  return message || '无法读取本轮临时上下文，请确认 Pi Runtime 与本机 Debug 设置。';
}

function tokenPair(tokens: unknown, window: unknown): string {
  const used = finiteNumber(tokens);
  const total = finiteNumber(window);
  return used === null || total === null ? '待校准' : `${tokenCount(used)} / ${tokenCount(total)}`;
}

function tokenTotal(value: Record<string, unknown>, keys: string[]): number {
  return keys.reduce((total, key) => total + (finiteNumber(value[key]) ?? 0), 0);
}

function tokenCount(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(value >= 100_000 ? 0 : 1)}K`;
  return String(Math.max(0, Math.round(value)));
}

function finiteNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? Math.max(0, value) : null;
}

function record(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function array(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function text(value: unknown): string {
  return typeof value === 'string' ? value : '';
}
