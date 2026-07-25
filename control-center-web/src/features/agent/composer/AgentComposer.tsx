import {
  LoaderCircle,
  Paperclip,
  PencilLine,
  Plus,
  Send,
  StopCircle,
  X,
} from 'lucide-react';
import {
  startTransition,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type ClipboardEvent,
  type CompositionEvent,
  type KeyboardEvent,
} from 'react';
import { IconButton } from '@/components/primitives';
import type { AgentPersonaV1 } from '@/contracts/generated/agent-persona.v1';
import {
  buildCommandCatalog,
  commandTitle,
  nextEnabledCommandIndex,
  type ComposerCommand,
} from './command-catalog';
import type { ContextResourceSelection } from '../context-resource-profile';
import { ContextResourcesPicker } from './ContextResourcesPicker';
import { ModelPicker } from './ModelPicker';
import { PermissionPicker } from './PermissionPicker';
import { ToolPicker } from './ToolPicker';
import { permissionLabel } from './permission-policy';
import type {
  AgentCommand,
  AgentPermissionSelection,
  AgentProductCommandName,
  ComposerAttachment,
  ModelCatalog,
  SessionSummary,
  ThinkingLevel,
  ToolManifest,
} from '../types';

export type AgentMessageDelivery = 'prompt' | 'steer' | 'followUp';

export interface AgentComposerEditState {
  entryId: string;
  messageId: string;
}

export function AgentComposer({
  draft,
  attachments,
  session,
  persona,
  catalog,
  commands: piCommands,
  tools,
  toolCatalogStatus,
  busy,
  stopping = false,
  sending,
  modelChanging = false,
  onDraftChange,
  onAttachmentsChange,
  onPickAttachments,
  onPasteFromClipboard,
  onPasteImages,
  onToolSelect,
  onProductCommand,
  onSend,
  onStop,
  editState,
  onEditPrevious,
  onCancelEdit,
  onPermissionChange,
  onWorkspaceRootsChange,
  onContextResourcesChange = () => {},
  onModelChange,
  modelPickerRequest = 0,
  permissionPickerRequest = 0,
  toolPickerRequest = 0,
  helpRequest = 0,
  imageSupport = 'unknown',
  contextResourcesChanging = false,
}: {
  draft: string;
  attachments: ComposerAttachment[];
  session?: SessionSummary;
  persona?: AgentPersonaV1;
  catalog?: ModelCatalog;
  commands: AgentCommand[];
  tools: ToolManifest[];
  toolCatalogStatus: 'loading' | 'ready' | 'failed';
  busy: boolean;
  stopping?: boolean;
  sending: boolean;
  modelChanging?: boolean;
  onDraftChange: (value: string) => void;
  onAttachmentsChange: (value: ComposerAttachment[]) => void;
  onPickAttachments: () => void;
  onPasteFromClipboard?: () => void;
  onPasteImages: (files: File[]) => void;
  onToolSelect: (tool: ToolManifest) => void;
  onProductCommand: (command: AgentProductCommandName) => void;
  onSend: (delivery: AgentMessageDelivery, draft: string) => void;
  onStop: () => void;
  editState?: AgentComposerEditState;
  onEditPrevious?: () => void;
  onCancelEdit?: () => void;
  onPermissionChange: (selection: AgentPermissionSelection) => void;
  onWorkspaceRootsChange: () => void;
  onContextResourcesChange?: (selection: ContextResourceSelection) => void;
  onModelChange: (provider: string, modelId: string, level: ThinkingLevel) => void;
  modelPickerRequest?: number;
  permissionPickerRequest?: number;
  toolPickerRequest?: number;
  helpRequest?: number;
  imageSupport?: 'supported' | 'unsupported' | 'unknown';
  contextResourcesChanging?: boolean;
}) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const composingRef = useRef(false);
  const lastEscapeAtRef = useRef(0);
  const escapeResetRef = useRef(0);
  const [composerDraft, setComposerDraft] = useState(draft);
  const [activeCommandIndex, setActiveCommandIndex] = useState(0);
  const [dismissedDraft, setDismissedDraft] = useState<string | null>(null);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [busyDelivery, setBusyDelivery] = useState<Exclude<AgentMessageDelivery, 'prompt'>>('steer');
  const commandCatalog = useMemo(
    () => buildCommandCatalog({ session, catalog, piCommands, tools, toolCatalogStatus, busy, sending }),
    [busy, catalog, piCommands, sending, session, toolCatalogStatus, tools],
  );
  const commands = useMemo(() => commandCatalog.filter((command) => {
    const value = composerDraft.trim().toLowerCase();
    if (helpOpen || paletteOpen) return true;
    return composerDraft !== dismissedDraft && value.startsWith('/') && !value.includes(' ') && (value === '/' || command.invocation.toLowerCase().startsWith(value));
  }), [commandCatalog, composerDraft, dismissedDraft, helpOpen, paletteOpen]);
  const commandPanelVisible = commands.length > 0 && (
    paletteOpen
    || (composerDraft !== dismissedDraft && composerDraft.trim().startsWith('/') && !composerDraft.trim().includes(' '))
  );
  useEffect(() => {
    setActiveCommandIndex(Math.max(0, commands.findIndex((command) => command.enabled)));
  }, [commands, composerDraft]);
  useEffect(() => {
    if (helpRequest <= 0) return;
    setHelpOpen(true);
    setPaletteOpen(true);
    setDismissedDraft(null);
    textareaRef.current?.focus();
  }, [helpRequest]);
  useEffect(() => {
    // Do not let event-stream/catalog rerenders replace WebKit's marked text.
    if (!composingRef.current) setComposerDraft(draft);
  }, [draft]);
  useEffect(() => {
    if (!editState) return;
    const frame = window.requestAnimationFrame(() => {
      const textarea = textareaRef.current;
      if (!textarea) return;
      textarea.focus();
      textarea.setSelectionRange(textarea.value.length, textarea.value.length);
    });
    return () => window.cancelAnimationFrame(frame);
  }, [editState?.messageId]);
  useEffect(() => () => window.clearTimeout(escapeResetRef.current), []);
  const canSend = Boolean(
    session
    && (composerDraft.trim() || attachments.length)
    && !sending
    && !modelChanging,
  );
  function publishDraft(value: string): void {
    // The textarea owns keystroke latency; the parent only needs a deferred
    // projection for navigation and recovery. Send receives the local snapshot.
    startTransition(() => onDraftChange(value));
  }
  function selectCommand(command: ComposerCommand): void {
    if (!command.enabled) return;
    if (command.source === 'product' && command.name === 'help') {
      clearTypedCommandDraft(command.invocation);
      setHelpOpen(true);
      setPaletteOpen(true);
      return;
    }
    if (command.source === 'product' && command.behavior === 'execute') {
      clearTypedCommandDraft(command.invocation);
      setPaletteOpen(false);
      setHelpOpen(false);
      onProductCommand(command.name);
      return;
    }
    const nextDraft = `${command.invocation} `;
    setPaletteOpen(false);
    setHelpOpen(false);
    setComposerDraft(nextDraft);
    publishDraft(nextDraft);
    textareaRef.current?.focus();
  }
  function clearTypedCommandDraft(invocation: string): void {
    const value = composerDraft.trim();
    if (!value.startsWith('/') || value.includes(' ') || !invocation.startsWith(value)) return;
    setComposerDraft('');
    publishDraft('');
  }
  function changeDraft(event: ChangeEvent<HTMLTextAreaElement>): void {
    const nextDraft = event.currentTarget.value;
    setDismissedDraft(null);
    if (paletteOpen) {
      setPaletteOpen(false);
      setHelpOpen(false);
    }
    setComposerDraft(nextDraft);
    if (!composingRef.current) publishDraft(nextDraft);
  }
  function startComposition(): void {
    composingRef.current = true;
  }
  function endComposition(event: CompositionEvent<HTMLTextAreaElement>): void {
    const nextDraft = event.currentTarget.value;
    composingRef.current = false;
    setComposerDraft(nextDraft);
    publishDraft(nextDraft);
  }
  function submit(delivery: AgentMessageDelivery): void {
    if (!canSend) return;
    const value = composerDraft;
    setComposerDraft('');
    setPaletteOpen(false);
    setHelpOpen(false);
    setDismissedDraft(null);
    publishDraft('');
    onSend(delivery, value);
  }
  function keyDown(event: KeyboardEvent<HTMLTextAreaElement>): void {
    // WebKit can report isComposing=false on the Enter that commits an IME
    // candidate. The ref and legacy 229 keyCode keep that key inside the IME.
    if (composingRef.current || event.nativeEvent.isComposing || event.nativeEvent.keyCode === 229) return;
    if (commands.length) {
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault();
        const delta = event.key === 'ArrowDown' ? 1 : -1;
        setActiveCommandIndex((current) => nextEnabledCommandIndex(commands, current, delta));
        return;
      }
      if (event.key === 'Escape') {
        event.preventDefault();
        setPaletteOpen(false);
        setHelpOpen(false);
        setDismissedDraft(composerDraft);
        return;
      }
      if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
        event.preventDefault();
        const command = commands[activeCommandIndex] ?? commands[0];
        if (command) selectCommand(command);
        return;
      }
    }
    if (event.key === 'Escape') {
      event.preventDefault();
      if (editState) {
        lastEscapeAtRef.current = 0;
        onCancelEdit?.();
        return;
      }
      const now = Date.now();
      if (lastEscapeAtRef.current > 0 && now - lastEscapeAtRef.current <= 650) {
        lastEscapeAtRef.current = 0;
        window.clearTimeout(escapeResetRef.current);
        onEditPrevious?.();
        return;
      }
      lastEscapeAtRef.current = now;
      window.clearTimeout(escapeResetRef.current);
      escapeResetRef.current = window.setTimeout(() => { lastEscapeAtRef.current = 0; }, 650);
      return;
    }
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      submit(busy ? (event.altKey ? 'followUp' : busyDelivery) : 'prompt');
    }
  }
  function paste(event: ClipboardEvent<HTMLTextAreaElement>): void {
    const files = [...event.clipboardData.files];
    const items = event.clipboardData.items;
    let hasImageFileItem = files.some((file) => file.type.toLowerCase().startsWith('image/'));
    if (!files.length && items) {
      for (const item of items) {
        if (item.kind !== 'file') continue;
        if (String(item.type || '').toLowerCase().startsWith('image/')) hasImageFileItem = true;
        const file = item.getAsFile();
        if (file) files.push(file);
      }
    }
    if (!files.length && !hasImageFileItem) {
      const pastedText = event.clipboardData.getData?.('text/plain') ?? '';
      if (pastedText || !onPasteFromClipboard) return;
      event.preventDefault();
      onPasteFromClipboard();
      return;
    }
    event.preventDefault();
    if (imageSupport !== 'supported') {
      if (files.length) onPasteImages(files);
      else onPasteFromClipboard?.();
      return;
    }
    if (!files.length) {
      onPasteFromClipboard?.();
      return;
    }
    onPasteImages(files);
  }
  return (
    <div className="agent-composer-wrap">
      {commandPanelVisible ? (
        <div className="agent-command-palette" role="listbox" aria-label="命令面板">
          <header>
            <span><strong>{helpOpen ? '命令帮助' : '当前可用命令'}</strong><small>{session ? `${permissionLabel(session)} · ${commands.length} 项` : '未选择对话'}</small></span>
            {helpOpen ? <p>控制中心命令直接操作界面或 API；Pi 命令只来自当前对话的 RPC 目录。</p> : null}
          </header>
          {commands.map((command, index) => (
            <button key={`${command.source}:${command.invocation}`} type="button" role="option" data-source={command.source} aria-selected={index === activeCommandIndex} aria-disabled={!command.enabled} disabled={!command.enabled} title={command.disabledReason} onMouseEnter={() => command.enabled && setActiveCommandIndex(index)} onClick={() => selectCommand(command)}>
              <kbd title={command.invocation}>{command.invocation}</kbd>
              <span className="agent-command-palette__copy">
                <strong>{command.description || commandTitle(command.source)}</strong>
                <small>{commandTitle(command.source)}{command.disabledReason ? ` · ${command.disabledReason}` : ''}</small>
              </span>
            </button>
          ))}
        </div>
      ) : null}
      <div className="agent-composer" data-busy={busy || undefined}>
        {editState ? (
          <div className="agent-composer__edit" role="status">
            <PencilLine size={15} aria-hidden="true" />
            <span><strong>正在修改这条消息</strong><small>发送后将从这里重新生成后续对话</small></span>
            <IconButton label="取消修改" icon={<X size={15} />} size="small" onClick={onCancelEdit} tooltip />
          </div>
        ) : null}
        {attachments.length ? (
          <div className="agent-composer__attachments">
            {attachments.map((attachment) => (
              <span key={attachment.id}><Paperclip size={13} /><b>{attachment.name}</b><button type="button" aria-label={`移除 ${attachment.name}`} onClick={() => onAttachmentsChange(attachments.filter((item) => item.id !== attachment.id))}><X size={12} /></button></span>
            ))}
          </div>
        ) : null}
        <textarea
          ref={textareaRef}
          rows={1}
          value={composerDraft}
          onChange={changeDraft}
          onCompositionStart={startComposition}
          onCompositionEnd={endComposition}
          onKeyDown={keyDown}
          onPaste={paste}
          autoCapitalize="none"
          autoComplete="off"
          autoCorrect="off"
          spellCheck={false}
          placeholder={composerPlaceholder(persona?.displayName ?? '智鼬', imageSupport)}
          aria-label="消息"
        />
        <div className="agent-composer__toolbar">
          <div className="agent-composer__controls">
            <IconButton
              className="agent-composer__attachment"
              label={imageSupport === 'supported' ? '添加图片' : imageSupport === 'unsupported' ? '当前模型不支持图片' : '正在确认图片能力'}
              icon={<Plus size={18} />}
              onClick={onPickAttachments}
              disabled={!session || sending || imageSupport !== 'supported'}
              tooltip
            />
            <PermissionPicker session={session} persona={persona} tools={tools} disabled={busy || sending} requestOpen={permissionPickerRequest} onChange={onPermissionChange} onWorkspaceRootsChange={onWorkspaceRootsChange} />
            <ContextResourcesPicker
              session={session}
              disabled={busy || sending}
              pending={contextResourcesChanging}
              onChange={onContextResourcesChange}
            />
            <ToolPicker tools={tools} status={toolCatalogStatus} session={session} disabled={!session || busy || sending} requestOpen={toolPickerRequest} onSelect={onToolSelect} />
            <ModelPicker
              catalog={catalog}
              disabled={busy || sending}
              pending={modelChanging}
              requestOpen={modelPickerRequest}
              onChange={onModelChange}
            />
            {busy ? (
              <div className="agent-composer__delivery" role="radiogroup" aria-label="消息投递方式">
                <button type="button" role="radio" aria-checked={busyDelivery === 'steer'} data-active={busyDelivery === 'steer' || undefined} onClick={() => setBusyDelivery('steer')} disabled={sending}>干预</button>
                <button type="button" role="radio" aria-checked={busyDelivery === 'followUp'} data-active={busyDelivery === 'followUp' || undefined} onClick={() => setBusyDelivery('followUp')} disabled={sending}>接续</button>
              </div>
            ) : null}
          </div>
          <div className="agent-composer__actions">
            {busy ? (
              <IconButton
                className="agent-composer__stop"
                label={stopping ? '正在停止本轮' : '停止本轮'}
                icon={stopping ? <LoaderCircle className="ui-spin" size={18} /> : <StopCircle size={18} />}
                onClick={onStop}
                disabled={stopping}
                aria-busy={stopping || undefined}
                tooltip
              />
            ) : null}
            <IconButton
              className="agent-composer__send"
              label={busy ? (busyDelivery === 'steer' ? '干预当前执行' : '当前执行完成后接续') : '发送'}
              icon={<Send size={18} />}
              onClick={() => submit(busy ? busyDelivery : 'prompt')}
              disabled={stopping || !canSend}
              tooltip
            />
          </div>
        </div>
      </div>
    </div>
  );
}

function composerPlaceholder(name: string, support: 'supported' | 'unsupported' | 'unknown'): string {
  if (support === 'supported') return `给${name}发消息，输入 / 查看命令，或粘贴图片…`;
  if (support === 'unsupported') return `给${name}发消息，输入 / 查看命令；当前模型不支持图片…`;
  return `给${name}发消息，输入 / 查看命令；当前模型图片能力未知…`;
}
