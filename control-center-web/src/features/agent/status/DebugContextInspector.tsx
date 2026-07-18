import { useQuery } from '@tanstack/react-query';
import {
  Braces,
  Check,
  ChevronRight,
  Clipboard,
  Database,
  FileText,
  Gauge,
  HardDrive,
  Layers3,
  MessageSquareText,
  PackageOpen,
  Wrench,
  X,
} from 'lucide-react';
import { useMemo, useState, type ReactNode } from 'react';
import { useControlTransport } from '@/app/control-transport';
import { IconButton, SegmentedControl } from '@/components/primitives';
import './DebugContextInspector.css';

type DebugView = 'semantic' | 'raw';

interface DebugStage {
  id: string;
  label: string;
  detail: string;
  kind: 'text' | 'json';
  value: unknown;
  channel: 'system' | 'tools' | 'messages' | 'wire';
  note?: string;
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
  const stages = useMemo(() => debugStages(response.context), [response.context]);
  const [copiedId, setCopiedId] = useState('');
  const [view, setView] = useState<DebugView>('semantic');
  const [selectedStageId, setSelectedStageId] = useState('');
  const selectedStage = stages.find((stage) => stage.id === selectedStageId);

  async function copyStage(stage: DebugStage): Promise<void> {
    const rendered = renderDebugValue(stage, view);
    if (!rendered) return;
    try {
      await navigator.clipboard.writeText(rendered);
      setCopiedId(stage.id);
      window.setTimeout(() => setCopiedId(''), 1_400);
    } catch {
      setCopiedId('');
    }
  }

  return (
    <section className="debug-context-inspector" data-embedded={embedded || undefined}>
      <header className="debug-context-inspector__header">
        <span>
          <Layers3 size={15} />
          <strong>模型上下文增量</strong>
          <small>按 Pi 实际装配顺序，每步只显示本次新增内容</small>
        </span>
        <SegmentedControl
          aria-label="上下文展示形式"
          items={[
            { value: 'semantic', label: '模型语义' },
            { value: 'raw', label: '原始 JSON' },
          ]}
          onValueChange={setView}
          value={view}
        />
      </header>
      <DebugStorage storage={response.storage} />
      {query.isPending ? <p className="debug-context-inspector__empty">正在读取本轮上下文快照</p> : null}
      {query.error ? <p className="debug-context-inspector__empty" data-tone="warning">上下文快照不可用，或本轮来自旧版 Runtime</p> : null}
      {!query.isPending && !query.error && !response.available ? <p className="debug-context-inspector__empty">这轮尚未生成上下文快照</p> : null}
      {response.available ? <DebugTelemetryStrip telemetry={response.telemetry} /> : null}
      {stages.length ? (
        <div className="debug-context-inspector__workspace" data-detail-open={Boolean(selectedStage) || undefined}>
          <ol className="debug-context-inspector__pipeline" data-view={view} aria-label="模型上下文注入顺序">
            {stages.map((stage, index) => (
              <li key={stage.id} data-channel={stage.channel}>
                <button
                  aria-pressed={selectedStage?.id === stage.id}
                  onClick={() => setSelectedStageId(stage.id)}
                  type="button"
                >
                  <span className="debug-context-inspector__ordinal">{index + 1}</span>
                  <DebugStageIcon channel={stage.channel} />
                  <span className="debug-context-inspector__stage-copy">
                    <strong>{stage.label}</strong>
                    <small>{stage.detail}</small>
                  </span>
                  <em>{view === 'semantic' ? '模型语义' : stage.channel === 'wire' ? '传输 JSON' : '原始数据'}</em>
                  <ChevronRight size={14} />
                </button>
              </li>
            ))}
          </ol>
          {selectedStage ? (
            <aside className="debug-context-inspector__stage-detail" data-view={view} aria-label={`${selectedStage.label}详情`}>
              <header>
                <span>
                  <small>{selectedStage.channel === 'wire' ? 'Provider 传输' : '本步上下文增量'}</small>
                  <strong>{selectedStage.label}</strong>
                  <p>{selectedStage.detail}</p>
                </span>
                <div>
                  <IconButton
                    icon={copiedId === selectedStage.id ? <Check size={14} /> : <Clipboard size={14} />}
                    label={copiedId === selectedStage.id ? '已复制' : `复制${selectedStage.label}`}
                    onClick={() => void copyStage(selectedStage)}
                    size="small"
                    tooltip
                  />
                  <IconButton
                    icon={<X size={15} />}
                    label="关闭上下文详情"
                    onClick={() => setSelectedStageId('')}
                    size="small"
                    tooltip
                  />
                </div>
              </header>
              {selectedStage.note ? <p className="debug-context-inspector__stage-note">{selectedStage.note}</p> : null}
              <pre>{renderDebugValue(selectedStage, view)}</pre>
            </aside>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

function DebugStorage({ storage }: { storage: Record<string, unknown> }) {
  const persistent = storage.persistent === true;
  const directory = text(storage.directory);
  if (!Object.keys(storage).length) return null;
  return (
    <div className="debug-context-inspector__storage" data-persistent={persistent || undefined}>
      <HardDrive size={14} />
      <span>
        <strong>{persistent ? '快照已持久化' : '快照存储不可用'}</strong>
        <small title={directory}>{directory || text(storage.error) || 'Pi Runtime 未返回存储位置'}</small>
      </span>
      <b>{formatBytes(finiteNumber(storage.usedBytes) ?? 0)} / {formatBytes(finiteNumber(storage.maxBytes) ?? 0)}</b>
    </div>
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

function debugStages(context: Record<string, unknown>): DebugStage[] {
  if (!Object.keys(context).length) return [];
  const stages: DebugStage[] = [];
  const options = record(context.systemPromptOptions);
  const customPrompt = text(options.customPrompt);
  const finalSystemPrompt = text(context.systemPrompt);
  if (customPrompt) {
    stages.push(stage('system:base', 'System 基础指令', customPrompt, 'system'));
  } else if (finalSystemPrompt) {
    stages.push({
      ...stage('system:base', 'System Prompt', finalSystemPrompt, 'system'),
      note: '当前 Runtime 没有暴露更细的基础模板分段，因此这里只显示这一段原始结果。',
    });
  }

  const appendSystemPrompt = text(options.appendSystemPrompt);
  if (appendSystemPrompt) {
    stages.push(stage('system:append', '附加 System 指令', appendSystemPrompt, 'system'));
  }

  array(options.contextFiles).forEach((item, index) => {
    const contextFile = record(item);
    const path = text(contextFile.path) || `项目指令 ${index + 1}`;
    stages.push({
      ...stage(`system:context:${index}`, fileName(path), text(contextFile.content), 'system'),
      detail: `${path} · ${text(contextFile.content).length} 字符`,
    });
  });

  const skills = array(options.skills).map(skillSummary);
  if (skills.length) {
    stages.push({
      id: 'system:skills',
      label: 'Skills 目录',
      detail: `${skills.length} 项 · Pi 将这些记录编码为可加载技能清单`,
      kind: 'json',
      value: skills,
      channel: 'system',
    });
  }

  const cwd = text(options.cwd);
  if (cwd) {
    stages.push(stage('system:cwd', '当前工作目录', `Current working directory: ${cwd}`, 'system'));
  }

  const activeTools = array(context.activeTools).map(String);
  const toolSchemas = array(context.toolSchemas);
  if (activeTools.length || toolSchemas.length) {
    stages.push({
      id: 'tools',
      label: '活动工具定义',
      detail: `${activeTools.length || toolSchemas.length} 个工具 · 独立结构通道`,
      kind: 'json',
      value: { activeTools, schemas: toolSchemas },
      channel: 'tools',
      note: '工具名称和参数 Schema 由 Provider 作为结构化 tools 字段传入，不会伪装成一段普通 System 文本。',
    });
  }

  const windows = array(context.contextWindows);
  const initialMessages = array(record(windows[0]).messages);
  const currentMessageIndex = lastUserMessageIndex(initialMessages);
  const history = currentMessageIndex >= 0
    ? initialMessages.filter((_, index) => index !== currentMessageIndex)
    : initialMessages;
  if (history.length) {
    stages.push({
      id: 'messages:history',
      label: '历史消息',
      detail: `${history.length} 条模型上下文消息`,
      kind: 'json',
      value: history,
      channel: 'messages',
    });
  }

  const prompt = text(context.prompt);
  if (prompt || currentMessageIndex >= 0) {
    stages.push(stage(
      'messages:current',
      '当前用户输入',
      prompt || initialMessages[currentMessageIndex],
      'messages',
    ));
  }

  const modelCalls = array(context.modelCalls);
  const providerRequests = array(context.providerRequests);
  const callCount = Math.max(modelCalls.length, windows.length, providerRequests.length);
  for (let index = 0; index < callCount; index += 1) {
    if (index > 0) {
      const delta = modelCallDelta(modelCalls, windows, index);
      if (delta.length) {
        stages.push({
          id: `messages:delta:${index + 1}`,
          label: `模型调用 ${index + 1} 上下文增量`,
          detail: `${delta.length} 条新增消息`,
          kind: 'json',
          value: delta,
          channel: 'messages',
        });
      }
    }
    const request = record(providerRequests[index]);
    if (Object.keys(request).length) {
      stages.push({
        id: `wire:${index + 1}`,
        label: `Provider 请求 ${finiteNumber(request.index) ?? index + 1}`,
        detail: 'OpenAI 兼容传输信封',
        kind: 'json',
        value: request.payload,
        channel: 'wire',
        note: '这是 API 线上的 JSON 信封。model、stream 等是请求控制字段；role、content、tools 保留结构边界，Provider 再用模板或特殊 Token 编码，并不是把 JSON 标点原样拼成普通文本。',
      });
    }
  }
  return stages;
}

function stage(
  id: string,
  label: string,
  value: unknown,
  channel: DebugStage['channel'],
): DebugStage {
  const length = typeof value === 'string' ? value.length : 0;
  return {
    id,
    label,
    detail: length ? `${length} 字符` : '本步原始增量',
    kind: typeof value === 'string' ? 'text' : 'json',
    value,
    channel,
  };
}

function modelCallDelta(modelCalls: unknown[], windows: unknown[], index: number): unknown[] {
  const captured = record(record(modelCalls[index]).contextDelta);
  const added = array(captured.addedMessages);
  if (added.length) return added;
  const previous = array(record(windows[index - 1]).messages);
  const current = array(record(windows[index]).messages);
  let prefix = 0;
  while (prefix < previous.length && prefix < current.length && stableJson(previous[prefix]) === stableJson(current[prefix])) {
    prefix += 1;
  }
  return current.slice(prefix);
}

function skillSummary(value: unknown): Record<string, unknown> {
  const skill = record(value);
  return Object.fromEntries(
    ['name', 'description', 'filePath', 'baseDir', 'source', 'disableModelInvocation']
      .filter((key) => skill[key] !== undefined)
      .map((key) => [key, skill[key]]),
  );
}

function lastUserMessageIndex(messages: unknown[]): number {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    if (text(record(messages[index]).role) === 'user') return index;
  }
  return -1;
}

function DebugStageIcon({ channel }: { channel: DebugStage['channel'] }): ReactNode {
  if (channel === 'tools') return <Wrench size={14} />;
  if (channel === 'wire') return <Braces size={14} />;
  if (channel === 'messages') return <MessageSquareText size={14} />;
  return <PackageOpen size={14} />;
}

function renderDebugValue(stage: DebugStage, view: DebugView): string {
  if (view === 'semantic') return renderSemanticValue(stage);
  if (stage.kind === 'text') return text(stage.value);
  try {
    return JSON.stringify(stage.value ?? null, null, 2);
  } catch {
    return String(stage.value ?? '');
  }
}

function renderSemanticValue(stage: DebugStage): string {
  if (stage.kind === 'text') return text(stage.value);
  if (stage.channel === 'tools') return semanticTools(stage.value);
  if (stage.channel === 'wire') return semanticProviderRequest(stage.value);
  if (stage.channel === 'messages') return semanticMessages(stage.value);
  if (stage.id === 'system:skills') {
    return array(stage.value).map((item, index) => {
      const skill = record(item);
      return [
        `${index + 1}. ${text(skill.name) || '未命名 Skill'}`,
        text(skill.description) ? `   ${text(skill.description)}` : '',
        text(skill.filePath) ? `   来源: ${text(skill.filePath)}` : '',
      ].filter(Boolean).join('\n');
    }).join('\n\n');
  }
  return semanticObject(stage.value);
}

function semanticProviderRequest(value: unknown): string {
  const payload = record(value);
  const sections: string[] = [];
  const controls = [
    ['模型', payload.model],
    ['接口', payload.api],
    ['流式', payload.stream],
    ['最大输出', payload.max_tokens ?? payload.max_output_tokens],
    ['思考强度', payload.reasoning_effort ?? record(payload.reasoning).effort],
  ].filter(([, item]) => item !== undefined);
  if (controls.length) {
    sections.push(`[请求控制]\n${controls.map(([label, item]) => `${label}: ${scalar(item)}`).join('\n')}`);
  }
  const instructions = text(payload.instructions) || text(payload.system);
  if (instructions) sections.push(`[SYSTEM / INSTRUCTIONS]\n${instructions}`);
  const messages = payload.input ?? payload.messages;
  if (messages !== undefined) sections.push(semanticMessages(messages));
  const tools = payload.tools;
  if (Array.isArray(tools) && tools.length) sections.push(semanticTools({ schemas: tools }));
  const known = new Set([
    'model', 'api', 'stream', 'max_tokens', 'max_output_tokens', 'reasoning_effort',
    'reasoning', 'instructions', 'system', 'input', 'messages', 'tools',
  ]);
  const remaining = Object.fromEntries(Object.entries(payload).filter(([key]) => !known.has(key)));
  if (Object.keys(remaining).length) {
    sections.push(`[其他传输参数]\n${semanticObject(remaining)}`);
  }
  return sections.filter(Boolean).join('\n\n') || '本次 Provider 请求没有可显示的语义内容。';
}

function semanticMessages(value: unknown): string {
  const messages = Array.isArray(value) ? value : [value];
  return messages.map((item, index) => {
    if (typeof item === 'string') return `[MESSAGE ${index + 1}]\n${item}`;
    const message = record(item);
    const role = text(message.role).toUpperCase() || `MESSAGE ${index + 1}`;
    const name = text(message.name) || text(message.toolName);
    const heading = name ? `[${role} · ${name}]` : `[${role}]`;
    const content = semanticContent(message.content ?? message);
    return `${heading}\n${content || '(无文本内容)'}`;
  }).join('\n\n');
}

function semanticContent(value: unknown): string {
  if (typeof value === 'string') return value;
  if (Array.isArray(value)) return value.map(semanticContent).filter(Boolean).join('\n');
  const item = record(value);
  const type = text(item.type);
  const directText = text(item.text) || text(item.input_text) || text(item.output_text);
  if (directText) return directText;
  const name = text(item.name) || text(record(item.function).name);
  const argumentsValue = item.arguments ?? record(item.function).arguments;
  if (type.toLowerCase().includes('tool') || type.toLowerCase().includes('function') || name) {
    const label = name || '未命名工具';
    const argumentsText = typeof argumentsValue === 'string'
      ? argumentsValue
      : semanticObject(argumentsValue);
    return `调用工具: ${label}${argumentsText ? `\n参数: ${argumentsText}` : ''}`;
  }
  if (item.content !== undefined && item.content !== value) return semanticContent(item.content);
  return semanticObject(item);
}

function semanticTools(value: unknown): string {
  const container = record(value);
  const schemas = array(container.schemas ?? value);
  const activeTools = array(container.activeTools).map(String);
  const lines = schemas.map((item, index) => {
    const schema = record(item);
    const fn = record(schema.function);
    const name = text(schema.name) || text(fn.name) || activeTools[index] || `工具 ${index + 1}`;
    const description = text(schema.description) || text(fn.description);
    const parameters = record(schema.parameters ?? fn.parameters);
    const properties = record(parameters.properties);
    const required = new Set(array(parameters.required).map(String));
    const fields = Object.entries(properties).map(([key, definition]) => {
      const field = record(definition);
      const type = text(field.type) || 'any';
      return `  - ${key}: ${type}${required.has(key) ? '（必填）' : ''}${text(field.description) ? ` · ${text(field.description)}` : ''}`;
    });
    return [
      `${index + 1}. ${name}`,
      description ? `   ${description}` : '',
      fields.length ? `   参数\n${fields.join('\n')}` : '   参数: 无或由 Provider 管理',
    ].filter(Boolean).join('\n');
  });
  if (!lines.length && activeTools.length) return activeTools.map((name, index) => `${index + 1}. ${name}`).join('\n');
  return `[可用工具]\n${lines.join('\n\n')}`;
}

function semanticObject(value: unknown): string {
  if (value === null || value === undefined) return '';
  if (typeof value !== 'object') return scalar(value);
  if (Array.isArray(value)) return value.map((item, index) => `${index + 1}. ${semanticContent(item)}`).join('\n');
  return Object.entries(record(value)).map(([key, item]) => {
    if (item !== null && typeof item === 'object') return `${key}:\n${indent(semanticObject(item))}`;
    return `${key}: ${scalar(item)}`;
  }).join('\n');
}

function scalar(value: unknown): string {
  if (typeof value === 'string') return value;
  if (value === null) return 'null';
  if (value === undefined) return '';
  return String(value);
}

function indent(value: string): string {
  return value.split('\n').map((line) => `  ${line}`).join('\n');
}

function normalizeDebugResponse(value: unknown): {
  available: boolean;
  context: Record<string, unknown>;
  telemetry: Record<string, unknown>;
  storage: Record<string, unknown>;
} {
  const response = record(value);
  return {
    available: response.available === true,
    context: record(response.context),
    telemetry: record(response.telemetry),
    storage: record(response.storage),
  };
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

function formatBytes(value: number): string {
  if (value >= 1024 ** 3) return `${(value / 1024 ** 3).toFixed(value === 1024 ** 3 ? 0 : 1)} GiB`;
  if (value >= 1024 ** 2) return `${(value / 1024 ** 2).toFixed(1)} MiB`;
  if (value >= 1024) return `${(value / 1024).toFixed(1)} KiB`;
  return `${Math.round(value)} B`;
}

function finiteNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? Math.max(0, value) : null;
}

function fileName(path: string): string {
  return path.split('/').filter(Boolean).at(-1) || path;
}

function stableJson(value: unknown): string {
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
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
