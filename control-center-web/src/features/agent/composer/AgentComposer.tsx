import {
  Archive,
  ArrowDown,
  Bot,
  BrainCircuit,
  ChartNoAxesCombined,
  CircleHelp,
  Cpu,
  FileText,
  GitBranch,
  History,
  Keyboard,
  LoaderCircle,
  MessageSquarePlus,
  PanelRight,
  Paperclip,
  PencilLine,
  Plug,
  Plus,
  Send,
  Settings2,
  ShieldCheck,
  Sparkles,
  StopCircle,
  Wrench,
  X,
  type LucideIcon,
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
import { useOptionalControlTransport } from '@/app/control-transport';
import { IconButton } from '@/components/primitives';
import type { AgentPersonaV1 } from '@/contracts/generated/agent-persona.v1';
import type {
  CapabilityCatalog,
  CapabilityPreference,
} from '@/features/plugins/capability-policy';
import { managedContentUrl } from '../file-preview/file-descriptor';
import {
  buildCommandCatalog,
  commandTitle,
  nextEnabledCommandIndex,
  type ComposerCommand,
} from './command-catalog';
import { ComposerShell } from './ComposerShell';
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
  resolving?: boolean;
}

const productCommandIcons: Record<AgentProductCommandName, LucideIcon> = {
  new: MessageSquarePlus,
  resume: History,
  name: PencilLine,
  branch: GitBranch,
  compact: Archive,
  model: Cpu,
  thinking: BrainCircuit,
  permissions: ShieldCheck,
  tools: Wrench,
  session: ChartNoAxesCombined,
  status: PanelRight,
  subagents: Bot,
  settings: Settings2,
  hotkeys: Keyboard,
  stop: StopCircle,
  help: CircleHelp,
};

const piCommandIcons: Record<Exclude<ComposerCommand['source'], 'product'>, LucideIcon> = {
  extension: Plug,
  prompt: FileText,
  skill: Sparkles,
};

export function AgentComposer({
  draft,
  attachments,
  session,
  persona,
  catalog,
  commands: piCommands,
  tools,
  toolCatalogStatus,
  capabilityCatalog,
  capabilityPolicyPending = false,
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
  onCapabilityPreferenceChange = () => {},
  onProductCommand,
  onSend,
  onStop,
  editState,
  onEditPrevious,
  onCancelEdit,
  onPermissionChange,
  onWorkspaceRootsChange,
  onModelChange,
  modelPickerRequest = 0,
  permissionPickerRequest = 0,
  toolPickerRequest = 0,
  helpRequest = 0,
  imageSupport = 'unknown',
  showJumpLatest = false,
  onJumpLatest,
}: {
  assistantName?: string;
  draft: string;
  attachments: ComposerAttachment[];
  session?: SessionSummary;
  persona?: AgentPersonaV1;
  catalog?: ModelCatalog;
  commands: AgentCommand[];
  tools: ToolManifest[];
  toolCatalogStatus: 'loading' | 'ready' | 'failed';
  capabilityCatalog?: CapabilityCatalog;
  capabilityPolicyPending?: boolean;
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
  onCapabilityPreferenceChange?: (canonicalId: string, preference: CapabilityPreference) => void;
  onProductCommand: (command: AgentProductCommandName) => void;
  onSend: (delivery: AgentMessageDelivery, draft: string) => void;
  onStop: () => void;
  editState?: AgentComposerEditState;
  onEditPrevious?: () => void;
  onCancelEdit?: () => void;
  onPermissionChange: (selection: AgentPermissionSelection) => void;
  onWorkspaceRootsChange: () => void;
  onModelChange: (provider: string, modelId: string, level: ThinkingLevel) => void;
  modelPickerRequest?: number;
  permissionPickerRequest?: number;
  toolPickerRequest?: number;
  helpRequest?: number;
  imageSupport?: 'supported' | 'unsupported' | 'unknown';
  showJumpLatest?: boolean;
  onJumpLatest?: () => void;
}) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const commandPanelRef = useRef<HTMLDivElement>(null);
  const composingRef = useRef(false);
  const lastEscapeAtRef = useRef(0);
  const escapeResetRef = useRef(0);
  const [composerDraft, setComposerDraft] = useState(draft);
  const [activeCommandIndex, setActiveCommandIndex] = useState(0);
  const [dismissedDraft, setDismissedDraft] = useState<string | null>(null);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [commandInputFocused, setCommandInputFocused] = useState(false);
  const [busyDelivery, setBusyDelivery] = useState<Exclude<AgentMessageDelivery, 'prompt'>>('steer');
  const commandCatalog = useMemo(
    () => buildCommandCatalog({ session, catalog, piCommands, tools, toolCatalogStatus, busy, sending }),
    [busy, catalog, piCommands, sending, session, toolCatalogStatus, tools],
  );
  const commands = useMemo(() => commandCatalog.filter((command) => {
    const value = composerDraft.toLowerCase();
    if (helpOpen || paletteOpen) return true;
    return composerDraft !== dismissedDraft
      && isCommandLookupDraft(value)
      && (value === '/' || command.invocation.toLowerCase().startsWith(value));
  }), [commandCatalog, composerDraft, dismissedDraft, helpOpen, paletteOpen]);
  const commandPanelVisible = commands.length > 0 && (
    paletteOpen
    || (
      commandInputFocused
      && composerDraft !== dismissedDraft
      && isCommandLookupDraft(composerDraft)
    )
  );
  useEffect(() => {
    setActiveCommandIndex(Math.max(0, commands.findIndex((command) => command.enabled)));
  }, [commands, composerDraft]);
  useEffect(() => {
    if (!commandPanelVisible) return;
    commandPanelRef.current
      ?.querySelector<HTMLElement>(`[data-command-index="${activeCommandIndex}"]`)
      ?.scrollIntoView?.({ block: 'nearest' });
  }, [activeCommandIndex, commandPanelVisible]);
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
  // A silently disabled send button hides the one fact the user needs; the
  // label carries the same condition that gates `canSend`/`stopping`.
  const sendBlockedReason = stopping
    ? '正在停止本轮'
    : !session
      ? '先选择或创建对话'
      : sending
        ? '正在发送上一条消息'
        : modelChanging
          ? '正在切换模型'
          : !(composerDraft.trim() || attachments.length)
            ? '先输入内容或添加附件'
            : '';
  const sendActionLabel = busy
    ? (busyDelivery === 'steer' ? '干预当前执行' : '当前执行完成后接续')
    : '发送';
  function publishDraft(value: string): void {
    // The textarea owns keystroke latency; the parent only needs a deferred
    // projection for navigation and recovery. Send receives the local snapshot.
    startTransition(() => onDraftChange(value));
  }
  function selectCommand(
    command: ComposerCommand,
    intent: 'activate' | 'complete' = 'activate',
  ): void {
    if (!command.enabled) return;
    if (intent === 'complete') {
      completeCommand(command);
      return;
    }
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
    completeCommand(command);
  }
  function completeCommand(command: ComposerCommand): void {
    const nextDraft = `${command.invocation} `;
    setPaletteOpen(false);
    setHelpOpen(false);
    setDismissedDraft(nextDraft);
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
    if (commandPanelVisible && commands.length) {
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
      if (event.key === 'Tab' && !event.shiftKey) {
        event.preventDefault();
        const command = commands[activeCommandIndex] ?? commands[0];
        if (command) selectCommand(command, 'complete');
        return;
      }
      if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
        event.preventDefault();
        const command = commands[activeCommandIndex] ?? commands[0];
        if (command) selectCommand(command, 'activate');
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
    // Any pasted File — image, PDF, audio, or text document — rides the same
    // managed attach path as the paperclip; the owner surfaces a truthful
    // error for types the Runtime media store refuses.
    const files = [...event.clipboardData.files];
    if (!files.length) {
      for (const item of event.clipboardData.items ?? []) {
        if (item.kind !== 'file') continue;
        const file = item.getAsFile();
        if (file) files.push(file);
      }
    }
    if (files.length) {
      event.preventDefault();
      onPasteImages(files);
      return;
    }
    const pastedText = event.clipboardData.getData?.('text/plain') ?? '';
    if (pastedText || !onPasteFromClipboard) return;
    event.preventDefault();
    onPasteFromClipboard();
  }
  return (
    <div className="agent-composer-wrap">
      {commandPanelVisible ? (
        <div ref={commandPanelRef} id="agent-command-palette" className="agent-command-palette" role="listbox" aria-label="命令面板">
          <header>
            <span className="agent-command-palette__heading">
              <Keyboard aria-hidden="true" size={14} />
              <strong>{helpOpen ? '命令帮助' : '命令'}</strong>
              <small>{session ? `${permissionLabel(session)} · ${commands.length}` : '未选择对话'}</small>
            </span>
            {helpOpen
              ? <p>控制中心命令直接操作界面或 API；Pi 命令只来自当前对话的 RPC 目录。</p>
              : <p id="agent-command-palette-hint"><kbd>↑↓</kbd> 选择 <kbd>Tab</kbd> 补全 <kbd>Esc</kbd> 关闭</p>}
          </header>
          {commands.map((command, index) => (
            <button id={`agent-command-option-${index}`} key={`${command.source}:${command.invocation}`} type="button" role="option" tabIndex={-1} data-command-index={index} data-source={command.source} aria-label={`${command.invocation} ${command.description || commandTitle(command.source)} ${commandTitle(command.source)}`} aria-selected={index === activeCommandIndex} aria-disabled={!command.enabled} disabled={!command.enabled} title={command.disabledReason} onMouseDown={(event) => event.preventDefault()} onMouseEnter={() => command.enabled && setActiveCommandIndex(index)} onClick={() => selectCommand(command)}>
              <span className="agent-command-palette__icon" aria-hidden="true">
                <CommandIcon command={command} />
              </span>
              <span className="agent-command-palette__identity">
                <kbd title={command.invocation}>{command.invocation}</kbd>
              </span>
              <span className="agent-command-palette__copy">
                <strong>{command.description || commandTitle(command.source)}</strong>
                {command.disabledReason ? <small>{command.disabledReason}</small> : null}
              </span>
              <span className="agent-command-palette__shortcut" data-visible={index === activeCommandIndex || undefined} aria-hidden="true"><kbd>Tab</kbd></span>
            </button>
          ))}
        </div>
      ) : null}
      {showJumpLatest ? (
        <button className="agent-jump-latest" onClick={onJumpLatest} type="button">
          <ArrowDown aria-hidden="true" size={14} />
          <span>回到最新</span>
        </button>
      ) : null}
      <ComposerShell
        attachments={attachments.map((attachment) => ({
          id: attachment.id,
          name: attachment.name,
          preview: <ComposerAttachmentPreview attachment={attachment} sessionId={session?.id ?? ''} />,
        }))}
        attachmentsLabel="待发送附件"
        banner={editState ? (
          <div className="agent-composer__edit" role="status">
            <PencilLine size={15} aria-hidden="true" />
            <span><strong>正在修改这条消息</strong><small>{editState.resolving ? '正在定位历史锚点；内容现在就可以编辑' : '发送后将从这里重新生成后续对话'}</small></span>
            <IconButton label="取消修改" icon={<X size={15} />} size="small" onClick={onCancelEdit} tooltip />
          </div>
        ) : undefined}
        busy={busy}
        focusRef={textareaRef}
        jumpLatest={showJumpLatest}
        onRemoveAttachment={(id) => onAttachmentsChange(attachments.filter((item) => item.id !== id))}
        controls={(
          <>
            <IconButton
              className="agent-composer__attachment"
              label={attachmentButtonLabel(imageSupport)}
              icon={<Plus size={18} />}
              onClick={onPickAttachments}
              disabled={!session || sending}
              tooltip
            />
            <PermissionPicker session={session} persona={persona} tools={tools} disabled={busy || sending} requestOpen={permissionPickerRequest} onChange={onPermissionChange} onWorkspaceRootsChange={onWorkspaceRootsChange} />
            <ToolPicker
              adjustmentDisabled={busy || sending}
              capabilityCatalog={capabilityCatalog}
              capabilityPolicyPending={capabilityPolicyPending}
              disabled={!session}
              requestOpen={toolPickerRequest}
              session={session}
              status={toolCatalogStatus}
              tools={tools}
              onCapabilityPreferenceChange={onCapabilityPreferenceChange}
              onSelect={(tool) => {
                onToolSelect(tool);
                window.requestAnimationFrame(() => textareaRef.current?.focus());
              }}
            />
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
          </>
        )}
        actions={(
          <>
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
              label={sendBlockedReason ? `${sendActionLabel}（${sendBlockedReason}）` : sendActionLabel}
              icon={<Send size={18} />}
              onClick={() => submit(busy ? busyDelivery : 'prompt')}
              disabled={stopping || !canSend}
              tooltip
            />
          </>
        )}
      >
        <textarea
          ref={textareaRef}
          rows={1}
          value={composerDraft}
          onChange={changeDraft}
          onCompositionStart={startComposition}
          onCompositionEnd={endComposition}
          onKeyDown={keyDown}
          onPaste={paste}
          onFocus={() => setCommandInputFocused(true)}
          onBlur={() => {
            setCommandInputFocused(false);
            setPaletteOpen(false);
            setHelpOpen(false);
            setDismissedDraft(composerDraft);
          }}
          autoCapitalize="none"
          autoComplete="off"
          autoCorrect="off"
          spellCheck={false}
          placeholder={composerPlaceholder(persona?.displayName ?? 'Agent', imageSupport)}
          aria-label="消息"
          aria-autocomplete="list"
          aria-expanded={commandPanelVisible}
          aria-controls={commandPanelVisible ? 'agent-command-palette' : undefined}
          aria-describedby={commandPanelVisible && !helpOpen ? 'agent-command-palette-hint' : undefined}
          aria-activedescendant={commandPanelVisible && commands[activeCommandIndex]
            ? `agent-command-option-${activeCommandIndex}`
            : undefined}
        />
      </ComposerShell>
    </div>
  );
}

function CommandIcon({ command }: { command: ComposerCommand }) {
  const Icon = command.source === 'product'
    ? productCommandIcons[command.name]
    : piCommandIcons[command.source];
  return <Icon size={17} strokeWidth={1.8} />;
}

function isCommandLookupDraft(value: string): boolean {
  return value.startsWith('/') && !/\s/u.test(value);
}

function ComposerAttachmentPreview({
  attachment,
  sessionId,
}: {
  attachment: ComposerAttachment;
  sessionId: string;
}) {
  const transport = useOptionalControlTransport();
  const [localUrl, setLocalUrl] = useState('');
  const [failed, setFailed] = useState(false);
  const isImage = attachment.mimeType.toLowerCase().startsWith('image/');
  const managedPath = isImage
    && attachment.sessionId === sessionId
    && attachment.sha256
    ? managedContentUrl({
      mediaId: attachment.id,
      sessionId,
      expectedSha256: attachment.sha256,
      fileNameHint: attachment.name,
      mimeTypeHint: attachment.mimeType,
      byteSizeHint: attachment.byteSize,
    })
    : null;
  const managedUrl = managedPath
    ? transport?.agentMediaContentUrl?.(managedPath) ?? managedPath
    : null;

  useEffect(() => {
    setFailed(false);
    if (!attachment.previewFile || typeof URL.createObjectURL !== 'function') {
      setLocalUrl('');
      return undefined;
    }
    const nextUrl = URL.createObjectURL(attachment.previewFile);
    setLocalUrl(nextUrl);
    return () => URL.revokeObjectURL(nextUrl);
  }, [attachment.previewFile]);

  const previewUrl = attachment.previewFile ? localUrl : managedUrl;
  if (!previewUrl || failed) return <Paperclip aria-hidden="true" size={16} />;
  return (
    <img
      alt=""
      draggable={false}
      src={previewUrl}
      onError={() => setFailed(true)}
    />
  );
}

function composerPlaceholder(name: string, support: 'supported' | 'unsupported' | 'unknown'): string {
  if (support === 'supported') return `给${name}发消息，输入 / 查看命令，或粘贴图片与文件…`;
  if (support === 'unsupported') return `给${name}发消息，输入 / 查看命令；可粘贴文件，当前模型不支持图片…`;
  return `给${name}发消息，输入 / 查看命令；可粘贴文件，当前模型图片能力未知…`;
}

/** Attach stays available for PDF/audio/text even when the model cannot see
 * images; the label keeps the image capability state truthful (PF-CM-009). */
function attachmentButtonLabel(support: 'supported' | 'unsupported' | 'unknown'): string {
  if (support === 'supported') return '添加附件';
  if (support === 'unsupported') return '添加附件；当前模型不支持图片';
  return '添加附件；当前模型图片能力未知';
}
