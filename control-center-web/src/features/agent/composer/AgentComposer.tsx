import {
  BrainCircuit,
  Check,
  ChevronRight,
  LockKeyhole,
  Network,
  Paperclip,
  Plus,
  Send,
  ShieldCheck,
  StopCircle,
  Wrench,
  X,
} from 'lucide-react';
import { useMemo, useRef, type ClipboardEvent, type KeyboardEvent } from 'react';
import {
  Button,
  IconButton,
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/primitives';
import type { AgentPersonaV1 } from '@/contracts/generated/agent-persona.v1';
import type { ComposerAttachment, ModelCatalog, SessionSummary, ThinkingLevel, ToolManifest } from '../types';

export function AgentComposer({
  draft,
  attachments,
  session,
  persona,
  catalog,
  tools,
  busy,
  sending,
  onDraftChange,
  onAttachmentsChange,
  onPickFiles,
  onPasteImages,
  onToolSelect,
  onSend,
  onStop,
  onModeChange,
  onModelChange,
}: {
  draft: string;
  attachments: ComposerAttachment[];
  session?: SessionSummary;
  persona?: AgentPersonaV1;
  catalog?: ModelCatalog;
  tools: ToolManifest[];
  busy: boolean;
  sending: boolean;
  onDraftChange: (value: string) => void;
  onAttachmentsChange: (value: ComposerAttachment[]) => void;
  onPickFiles: () => void;
  onPasteImages: (files: File[]) => void;
  onToolSelect: (tool: ToolManifest) => void;
  onSend: () => void;
  onStop: () => void;
  onModeChange: (mode: 'assistant' | 'coordinator') => void;
  onModelChange: (provider: string, modelId: string, level: ThinkingLevel) => void;
}) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const commands = useMemo(() => slashCommands.filter((command) => {
    const value = draft.trim().toLowerCase();
    return value.startsWith('/') && !value.includes(' ') && (value === '/' || command.command.startsWith(value));
  }), [draft]);
  const canSend = Boolean(session && (draft.trim() || attachments.length) && !sending);
  function keyDown(event: KeyboardEvent<HTMLTextAreaElement>): void {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      if (busy) onStop(); else if (canSend) onSend();
    }
  }
  function paste(event: ClipboardEvent<HTMLTextAreaElement>): void {
    const files = [...event.clipboardData.files];
    const items = event.clipboardData.items;
    if (!files.length && items) {
      for (const item of items) {
        if (item.kind !== 'file') continue;
        const file = item.getAsFile();
        if (file) files.push(file);
      }
    }
    if (!files.length) return;
    event.preventDefault();
    onPasteImages(files);
  }
  return (
    <div className="agent-composer-wrap">
      {commands.length ? (
        <div className="agent-command-palette" role="listbox" aria-label="命令面板">
          {commands.map((command) => (
            <button key={command.command} type="button" onClick={() => {
              onDraftChange(`${command.command} `);
              textareaRef.current?.focus();
            }}>
              <kbd>{command.command}</kbd><span><strong>{command.title}</strong><small>{command.detail}</small></span>
            </button>
          ))}
        </div>
      ) : null}
      <div className="agent-composer" data-busy={busy || undefined}>
        {attachments.length ? (
          <div className="agent-composer__attachments">
            {attachments.map((attachment) => (
              <span key={attachment.id}><Paperclip size={13} /><b>{attachment.name}</b><button type="button" aria-label={`移除 ${attachment.name}`} onClick={() => onAttachmentsChange(attachments.filter((item) => item.id !== attachment.id))}><X size={12} /></button></span>
            ))}
          </div>
        ) : null}
        <textarea
          ref={textareaRef}
          rows={2}
          value={draft}
          onChange={(event) => onDraftChange(event.target.value)}
          onKeyDown={keyDown}
          onPaste={paste}
          placeholder={`给${persona?.displayName ?? '智鼬'}发消息，输入 / 查看命令，或粘贴图片…`}
          aria-label="消息"
        />
        <div className="agent-composer__toolbar">
          <IconButton label="添加附件" icon={<Plus size={18} />} onClick={onPickFiles} disabled={!session || sending} tooltip />
          <PermissionPicker session={session} persona={persona} disabled={busy || sending} onChange={onModeChange} />
          <ToolPicker tools={tools} mode={session?.mode ?? 'assistant'} disabled={!session || busy || sending} onSelect={onToolSelect} />
          <ModelTree catalog={catalog} disabled={busy || sending} onChange={onModelChange} />
          <span className="agent-composer__spacer" />
          <IconButton
            className="agent-composer__send"
            label={busy ? '停止本轮' : '发送'}
            icon={busy ? <StopCircle size={18} /> : <Send size={18} />}
            onClick={busy ? onStop : onSend}
            disabled={!busy && !canSend}
            tooltip
          />
        </div>
      </div>
    </div>
  );
}

function ToolPicker({
  tools,
  mode,
  disabled,
  onSelect,
}: {
  tools: ToolManifest[];
  mode: 'assistant' | 'coordinator';
  disabled: boolean;
  onSelect: (tool: ToolManifest) => void;
}) {
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button aria-label={`受控工具：${tools.length} 个`} className="agent-composer__picker" size="small" variant="quiet" disabled={!tools.length || disabled} leadingIcon={<Wrench size={15} />}>工具 · {tools.length}</Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="agent-tool-picker">
        <header><strong>受控工具</strong><small>由当前 Session 的真实 capability catalog 提供</small></header>
        <div>
          {tools.map((tool) => {
            const available = tool.availability === 'online' && tool.sessionModes.includes(mode);
            return (
              <button type="button" key={tool.id} disabled={!available} onClick={() => onSelect(tool)}>
                <span><strong>{tool.displayName}</strong><small>{tool.description}</small></span>
                <i data-risk={tool.riskLevel}>{available ? tool.riskLevel : '当前模式不可用'}</i>
              </button>
            );
          })}
        </div>
      </PopoverContent>
    </Popover>
  );
}

function PermissionPicker({
  session,
  persona,
  disabled,
  onChange,
}: {
  session?: SessionSummary;
  persona?: AgentPersonaV1;
  disabled: boolean;
  onChange: (mode: 'assistant' | 'coordinator') => void;
}) {
  const mode = session?.mode ?? 'assistant';
  const canCoordinate = persona?.selectableModes.includes('coordinator') ?? false;
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button aria-label={`Session 权限：${mode === 'coordinator' ? '运行协调' : '受控模式'}`} className="agent-composer__picker" size="small" variant="quiet" disabled={!session || disabled} leadingIcon={mode === 'coordinator' ? <Network size={15} /> : <ShieldCheck size={15} />}>{mode === 'coordinator' ? '运行协调' : '受控模式'}</Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="agent-picker-popover">
        <header><LockKeyhole size={16} /><span><strong>Session 权限</strong><small>以服务端 Policy 回执为准</small></span></header>
        <button type="button" aria-current={mode === 'assistant'} onClick={() => onChange('assistant')}><ShieldCheck size={17} /><span><strong>受控模式</strong><small>只读优先，写操作逐项批准</small></span>{mode === 'assistant' ? <Check size={15} /> : null}</button>
        <button type="button" disabled={!canCoordinate} aria-current={mode === 'coordinator'} onClick={() => onChange('coordinator')}><Network size={17} /><span><strong>运行协调</strong><small>可编排受控子 Agent</small></span>{mode === 'coordinator' ? <Check size={15} /> : null}</button>
      </PopoverContent>
    </Popover>
  );
}

function ModelTree({
  catalog,
  disabled,
  onChange,
}: {
  catalog?: ModelCatalog;
  disabled: boolean;
  onChange: (provider: string, modelId: string, level: ThinkingLevel) => void;
}) {
  const selected = record(catalog?.selected);
  const selectedProviderId = text(selected.provider);
  const selectedModelId = text(selected.id) || text(selected.modelId);
  const selectedProvider = catalog?.providers.find((item) => item.id === selectedProviderId);
  const selectedModel = selectedProvider?.models.find((item) => item.id === selectedModelId);
  const hasBackendSelection = Boolean(selectedProviderId && selectedModelId);
  const luna = hasBackendSelection ? undefined : catalog?.providers.flatMap((item) => item.models.map((modelItem) => ({ provider: item, model: modelItem }))).find(({ model: item }) => /luna/i.test(`${item.id} ${item.name}`));
  const provider = selectedModel ? selectedProvider : luna?.provider ?? selectedProvider ?? catalog?.providers[0];
  const model = selectedModel ?? luna?.model ?? provider?.models[0];
  const displayedProviderId = provider?.id ?? '';
  const displayedModelId = model?.id ?? '';
  const thinking = catalog?.thinkingLevel ?? 'off';
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button aria-label={`模型：${model?.name ?? '未选择'}，思考强度：${thinkingLabel(thinking)}`} className="agent-composer__picker" size="small" variant="quiet" disabled={!catalog || disabled} leadingIcon={<BrainCircuit size={15} />}>{model?.name ?? '选择模型'} · {thinkingLabel(thinking)}</Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="agent-model-tree">
        <header><strong>Provider → Model → Thinking</strong></header>
        {catalog?.providers.map((providerItem) => (
          <details key={providerItem.id} open={providerItem.id === displayedProviderId}>
            <summary>{providerItem.displayName}<ChevronRight size={14} /></summary>
            {providerItem.models.map((modelItem) => (
              <details key={modelItem.id} open={modelItem.id === displayedModelId}>
                <summary>{modelItem.name}{modelItem.id === displayedModelId ? <Check size={14} /> : <ChevronRight size={14} />}</summary>
                <div className="agent-model-tree__levels">
                  {modelItem.thinkingLevels.map((level) => (
                    <button type="button" key={level} aria-current={modelItem.id === displayedModelId && level === thinking} onClick={() => onChange(providerItem.id, modelItem.id, level)}>{thinkingLabel(level)}</button>
                  ))}
                </div>
              </details>
            ))}
          </details>
        ))}
      </PopoverContent>
    </Popover>
  );
}

const slashCommands = [
  { command: '/new', title: '新建对话', detail: '创建独立 Session' },
  { command: '/compact', title: '压缩上下文', detail: '保留连续会话并缩短上下文' },
  { command: '/memory', title: '查找记忆', detail: '检索工具书与近期对话' },
  { command: '/read', title: '读取路径', detail: '后面粘贴文件或文件夹路径' },
  { command: '/stop', title: '停止本轮', detail: '中止当前 Agent Loop' },
];

function thinkingLabel(value: string): string {
  return ({ off: '关闭', minimal: '最小', low: '低', medium: '中', high: '高', xhigh: '最高' } as Record<string, string>)[value] ?? value;
}

function record(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function text(value: unknown): string { return typeof value === 'string' ? value : ''; }
