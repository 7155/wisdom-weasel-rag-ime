import {
  BrainCircuit,
  BookOpenText,
  Check,
  ChevronRight,
  FolderOpen,
  LockKeyhole,
  LoaderCircle,
  Network,
  Paperclip,
  PencilLine,
  Plus,
  Send,
  ShieldCheck,
  StopCircle,
  TriangleAlert,
  Wrench,
  X,
} from 'lucide-react';
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type ClipboardEvent,
  type CompositionEvent,
  type KeyboardEvent,
} from 'react';
import * as RadioGroup from '@radix-ui/react-radio-group';
import * as Checkbox from '@radix-ui/react-checkbox';
import * as Switch from '@radix-ui/react-switch';
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  IconButton,
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/primitives';
import type { AgentPersonaV1 } from '@/contracts/generated/agent-persona.v1';
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
  onProjectContextChange = () => {},
  onPiSkillsChange = () => {},
  onCodexSkillsChange = () => {},
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
  onDraftChange: (value: string) => void;
  onAttachmentsChange: (value: ComposerAttachment[]) => void;
  onPickAttachments: () => void;
  onPasteFromClipboard?: () => void;
  onPasteImages: (files: File[]) => void;
  onToolSelect: (tool: ToolManifest) => void;
  onProductCommand: (command: AgentProductCommandName) => void;
  onSend: (delivery: AgentMessageDelivery) => void;
  onStop: () => void;
  editState?: AgentComposerEditState;
  onEditPrevious?: () => void;
  onCancelEdit?: () => void;
  onPermissionChange: (selection: AgentPermissionSelection) => void;
  onWorkspaceRootsChange: () => void;
  onProjectContextChange?: (enabled: boolean) => void;
  onPiSkillsChange?: (enabled: boolean) => void;
  onCodexSkillsChange?: (enabled: boolean) => void;
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
    const value = draft.trim().toLowerCase();
    if (helpOpen || paletteOpen) return true;
    return draft !== dismissedDraft && value.startsWith('/') && !value.includes(' ') && (value === '/' || command.invocation.toLowerCase().startsWith(value));
  }), [commandCatalog, dismissedDraft, draft, helpOpen, paletteOpen]);
  const commandPanelVisible = commands.length > 0 && (
    paletteOpen
    || (draft !== dismissedDraft && draft.trim().startsWith('/') && !draft.trim().includes(' '))
  );
  useEffect(() => {
    setActiveCommandIndex(Math.max(0, commands.findIndex((command) => command.enabled)));
  }, [commands, draft]);
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
  const canSend = Boolean(session && (draft.trim() || attachments.length) && !sending);
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
    onDraftChange(nextDraft);
    textareaRef.current?.focus();
  }
  function clearTypedCommandDraft(invocation: string): void {
    const value = draft.trim();
    if (!value.startsWith('/') || value.includes(' ') || !invocation.startsWith(value)) return;
    setComposerDraft('');
    onDraftChange('');
  }
  function changeDraft(event: ChangeEvent<HTMLTextAreaElement>): void {
    const nextDraft = event.currentTarget.value;
    setDismissedDraft(null);
    if (paletteOpen) {
      setPaletteOpen(false);
      setHelpOpen(false);
    }
    setComposerDraft(nextDraft);
    if (!composingRef.current) onDraftChange(nextDraft);
  }
  function startComposition(): void {
    composingRef.current = true;
  }
  function endComposition(event: CompositionEvent<HTMLTextAreaElement>): void {
    const nextDraft = event.currentTarget.value;
    composingRef.current = false;
    setComposerDraft(nextDraft);
    onDraftChange(nextDraft);
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
        setDismissedDraft(draft);
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
      if (canSend) onSend(busy ? (event.altKey ? 'followUp' : busyDelivery) : 'prompt');
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
          rows={2}
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
              disabled={busy || sending || contextResourcesChanging}
              onProjectContextChange={onProjectContextChange}
              onPiSkillsChange={onPiSkillsChange}
              onCodexSkillsChange={onCodexSkillsChange}
            />
            <ToolPicker tools={tools} status={toolCatalogStatus} session={session} disabled={!session || busy || sending} requestOpen={toolPickerRequest} onSelect={onToolSelect} />
            <ModelTree catalog={catalog} disabled={busy || sending} requestOpen={modelPickerRequest} onChange={onModelChange} />
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
              onClick={() => onSend(busy ? busyDelivery : 'prompt')}
              disabled={stopping || !canSend}
              tooltip
            />
          </div>
        </div>
      </div>
    </div>
  );
}

function ContextResourcesPicker({
  session,
  disabled,
  onProjectContextChange,
  onPiSkillsChange,
  onCodexSkillsChange,
}: {
  session?: SessionSummary;
  disabled: boolean;
  onProjectContextChange: (enabled: boolean) => void;
  onPiSkillsChange: (enabled: boolean) => void;
  onCodexSkillsChange: (enabled: boolean) => void;
}) {
  const projectContextEnabled = session?.projectContextEnabled !== false;
  const piSkillsEnabled = session?.piSkillsEnabled === true;
  const codexSkillsEnabled = session?.codexSkillsEnabled === true;
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          aria-label={`项目指令：${projectContextEnabled ? '已加载' : '未加载'}`}
          className="agent-composer__picker agent-composer__project-context"
          data-enabled={projectContextEnabled || piSkillsEnabled || codexSkillsEnabled || undefined}
          size="small"
          title="项目指令与 Skill 来源"
          variant="quiet"
          disabled={!session || disabled}
          leadingIcon={<BookOpenText size={15} />}
        >项目指令</Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="agent-picker-popover agent-project-context-picker">
        <header>
          <BookOpenText size={16} />
          <span><strong>上下文资源</strong><small>当前对话的项目指令与 Skill 来源</small></span>
        </header>
        <label className="agent-project-context-picker__toggle">
          <span>
            <strong>加载 AGENTS.md / CLAUDE.md</strong>
            <small>从全局目录和当前工作区祖先目录按 Pi 原生顺序读取</small>
          </span>
          <Switch.Root
            aria-label="加载 AGENTS.md / CLAUDE.md"
            checked={projectContextEnabled}
            disabled={disabled}
            onCheckedChange={onProjectContextChange}
          >
            <Switch.Thumb />
          </Switch.Root>
        </label>
        <label className="agent-project-context-picker__toggle">
          <span>
            <strong>加载 Pi Skills</strong>
            <small>读取 Pi 用户 Skill 目录；输入法自己的 Skills 不受此开关影响</small>
          </span>
          <Switch.Root
            aria-label="加载 Pi Skills"
            checked={piSkillsEnabled}
            disabled={disabled}
            onCheckedChange={onPiSkillsChange}
          >
            <Switch.Thumb />
          </Switch.Root>
        </label>
        <label className="agent-project-context-picker__toggle">
          <span>
            <strong>加载 Codex Skills</strong>
            <small>读取 Codex 与通用 Agents Skill 目录；默认关闭</small>
          </span>
          <Switch.Root
            aria-label="加载 Codex Skills"
            checked={codexSkillsEnabled}
            disabled={disabled}
            onCheckedChange={onCodexSkillsChange}
          >
            <Switch.Thumb />
          </Switch.Root>
        </label>
        <p className="agent-picker-popover__note">切换后会重建 Pi Runtime；历史消息不变，下一轮使用新的上下文资源设置。</p>
      </PopoverContent>
    </Popover>
  );
}

export interface AgentComposerEditState {
  entryId: string;
  messageId: string;
}

function ToolPicker({
  tools,
  status,
  session,
  disabled,
  requestOpen,
  onSelect,
}: {
  tools: ToolManifest[];
  status: 'loading' | 'ready' | 'failed';
  session?: SessionSummary;
  disabled: boolean;
  requestOpen: number;
  onSelect: (tool: ToolManifest) => void;
}) {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    if (requestOpen > 0 && status === 'ready' && !disabled) setOpen(true);
  }, [disabled, requestOpen, status]);
  const availableCount = tools.filter((tool) => toolAvailableForCurrentSession(tool, session)).length;
  const label = status === 'loading'
    ? '受控工具：加载中'
    : status === 'failed'
      ? '受控工具目录加载失败'
      : `当前权限可用工具：${availableCount} 个`;
  const text = status === 'loading' ? '工具 · 加载中' : status === 'failed' ? '工具 · 未加载' : `工具 · ${availableCount}`;
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button aria-label={label} className="agent-composer__picker" data-status={status} size="small" title={label} variant="quiet" disabled={status !== 'ready' || !tools.length || disabled} leadingIcon={<Wrench size={15} />}>{text}</Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="agent-tool-picker">
        <header><strong>受控工具</strong><small>当前模式可用 {availableCount} / 目录共 {tools.length}</small></header>
        <div>
          {tools.map((tool) => {
            const available = toolAvailableForCurrentSession(tool, session);
            return (
              <button type="button" key={tool.id} disabled={!available} onClick={() => onSelect(tool)}>
                <span><strong>{tool.displayName}</strong><small>{tool.description}</small></span>
                <i data-risk={tool.riskLevel}>{available ? riskLabel(tool.riskLevel) : '当前权限不可用'}</i>
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
  tools,
  disabled,
  requestOpen,
  onChange,
  onWorkspaceRootsChange,
}: {
  session?: SessionSummary;
  persona?: AgentPersonaV1;
  tools: ToolManifest[];
  disabled: boolean;
  requestOpen: number;
  onChange: (selection: AgentPermissionSelection) => void;
  onWorkspaceRootsChange: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [dangerousOpen, setDangerousOpen] = useState(false);
  const [dangerousAcknowledged, setDangerousAcknowledged] = useState(false);
  const mode = session?.mode ?? 'assistant';
  const profile = session?.toolProfileVersion ?? 'control-center-v1';
  const current = permissionPreset(mode, profile);
  const canCoordinate = persona?.selectableModes.includes('coordinator') ?? false;
  useEffect(() => {
    if (requestOpen > 0 && session && !disabled) setOpen(true);
  }, [disabled, requestOpen, session]);
  return (
    <>
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button aria-label={`对话权限：${current.label}`} className="agent-composer__picker" data-permission={current.id} size="small" title={`对话权限：${current.label}`} variant="quiet" disabled={!session || disabled} leadingIcon={permissionIcon(current.icon, 15)}>{current.label}</Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="agent-picker-popover">
        <header><LockKeyhole size={16} /><span><strong>对话权限</strong><small>模式、工具范围与审批共同生效</small></span></header>
        <RadioGroup.Root
          className="agent-picker-popover__options"
          aria-label="对话权限模式"
          value={current.id}
          onValueChange={(presetId) => {
            const preset = PERMISSION_PRESETS.find((item) => item.id === presetId);
            if (!preset) return;
            if (preset.id === 'dangerous') {
              setOpen(false);
              setDangerousAcknowledged(false);
              setDangerousOpen(true);
              return;
            }
            onChange({ mode: preset.mode, toolProfileVersion: preset.toolProfileVersion });
            setOpen(false);
          }}
        >
          {PERMISSION_PRESETS.map((preset) => {
            const selected = current.id === preset.id;
            const available = preset.mode !== 'coordinator' || canCoordinate;
            const toolCount = tools.filter((tool) => toolAvailableForPolicy(tool, preset.mode, preset.toolProfileVersion)).length;
            return (
              <RadioGroup.Item
                className="agent-picker-popover__option"
                data-danger={preset.id === 'dangerous' || undefined}
                value={preset.id}
                key={preset.id}
                disabled={!available}
              >
                {permissionIcon(preset.icon, 17)}
                <span>
                  <strong>{preset.label}</strong>
                  <small>{available ? `${preset.description} · ${toolCount} 个工具` : '当前角色未开放协调权限'}</small>
                </span>
                {selected ? <Check size={15} /> : null}
              </RadioGroup.Item>
            );
          })}
        </RadioGroup.Root>
        {session?.mode === 'coordinator' ? (
          <section className="agent-picker-popover__workspace" aria-label="授权工作区">
            <FolderOpen size={16} />
            <span>
              <strong>授权工作区</strong>
              <small title={session.workspaceRoots.join('\n')}>
                {session.workspaceRoots.length > 0
                  ? `${session.workspaceRoots.length} 个目录 · ${session.workspaceRoots.map(shortPath).join('、')}`
                  : '尚未授权目录，工作区工具无法运行'}
              </small>
            </span>
            <Button size="small" variant="quiet" disabled={disabled} onClick={onWorkspaceRootsChange}>
              {session.workspaceRoots.length > 0 ? '更改' : '选择'}
            </Button>
          </section>
        ) : null}
        {session?.toolAllowlistMode === 'explicit' ? <p className="agent-picker-popover__note">当前会话还受 {session.allowedTools?.length ?? 0} 项自定义工具上限约束；选择预设后恢复该预设的完整工具范围。</p> : null}
      </PopoverContent>
    </Popover>
    <Dialog
      open={dangerousOpen}
      onOpenChange={(nextOpen) => {
        setDangerousOpen(nextOpen);
        if (!nextOpen) setDangerousAcknowledged(false);
      }}
    >
      <DialogContent className="agent-dangerous-permission-dialog">
        <DialogHeader>
          <span className="agent-dangerous-permission-dialog__symbol"><TriangleAlert size={20} /></span>
          <DialogTitle>启用完全信任？</DialogTitle>
          <DialogDescription>
            当前对话内的写入、命令、重启、导入与部署操作将根据结构化预览自动批准，不再逐项等待你确认。
          </DialogDescription>
        </DialogHeader>
        <div className="agent-dangerous-permission-dialog__limits">
          <p><ShieldCheck size={16} /><span><strong>仍然保留</strong> 工作区和路径边界、哈希复验、备份、审计回执与回滚记录</span></p>
          <p><TriangleAlert size={16} /><span><strong>不再保留</strong> 每次写操作前的人工确认机会</span></p>
        </div>
        <label className="agent-dangerous-permission-dialog__check">
          <Checkbox.Root checked={dangerousAcknowledged} onCheckedChange={(checked) => setDangerousAcknowledged(checked === true)}>
            <Checkbox.Indicator><Check size={14} /></Checkbox.Indicator>
          </Checkbox.Root>
          <span>我确认让此对话自动批准全部受控写操作</span>
        </label>
        <DialogFooter>
          <Button variant="quiet" onClick={() => setDangerousOpen(false)}>取消</Button>
          <Button
            variant="danger"
            disabled={!dangerousAcknowledged}
            leadingIcon={<TriangleAlert size={15} />}
            onClick={() => {
              onChange({
                mode: 'coordinator',
                toolProfileVersion: 'control-center-auto-approve-v1',
                dangerousModeConfirmed: true,
              });
              setDangerousOpen(false);
            }}
          >启用完全信任</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
    </>
  );
}

type PermissionPreset = AgentPermissionSelection & {
  id: string;
  label: string;
  description: string;
  icon: 'shield' | 'lock' | 'network' | 'danger';
};

const PERMISSION_PRESETS: PermissionPreset[] = [
  {
    id: 'controlled',
    label: '受控助手',
    description: '可读取产品状态，写操作逐项批准',
    icon: 'shield',
    mode: 'assistant',
    toolProfileVersion: 'control-center-v1',
  },
  {
    id: 'readonly',
    label: '只读观察',
    description: '只允许检索、查看与维护会话计划',
    icon: 'lock',
    mode: 'assistant',
    toolProfileVersion: 'subagent-readonly-v1',
  },
  {
    id: 'coordinator',
    label: '运行协调',
    description: '可编排受控子 Agent 与授权工作区工具',
    icon: 'network',
    mode: 'coordinator',
    toolProfileVersion: 'control-center-v1',
  },
  {
    id: 'dangerous',
    label: '完全信任',
    description: '全部受控写操作自动批准',
    icon: 'danger',
    mode: 'coordinator',
    toolProfileVersion: 'control-center-auto-approve-v1',
  },
];

function permissionPreset(mode: SessionSummary['mode'], profile: string): PermissionPreset {
  const exact = PERMISSION_PRESETS.find((item) => item.mode === mode && item.toolProfileVersion === profile);
  if (exact) return exact;
  if (profile === 'subagent-readonly-v1') {
    return {
      ...PERMISSION_PRESETS[1]!,
      id: 'readonly-coordinator',
      label: mode === 'coordinator' ? '只读协调' : '只读观察',
      mode,
      icon: mode === 'coordinator' ? 'network' : 'lock',
    };
  }
  if (profile === 'control-center-auto-approve-v1') return PERMISSION_PRESETS[3]!;
  return mode === 'coordinator' ? PERMISSION_PRESETS[2]! : PERMISSION_PRESETS[0]!;
}

function permissionIcon(icon: PermissionPreset['icon'], size: number) {
  if (icon === 'network') return <Network size={size} />;
  if (icon === 'lock') return <LockKeyhole size={size} />;
  if (icon === 'danger') return <TriangleAlert size={size} />;
  return <ShieldCheck size={size} />;
}

function shortPath(path: string): string {
  const parts = path.split('/').filter(Boolean);
  return parts.at(-1) || path;
}

function toolAvailableForPolicy(
  tool: ToolManifest,
  mode: SessionSummary['mode'],
  profile: AgentPermissionSelection['toolProfileVersion'],
): boolean {
  if (tool.availability !== 'online' || !tool.sessionModes.includes(mode)) return false;
  const operationsByProfile = record(tool.profileOperations);
  const operations = operationsByProfile[profile];
  return !Array.isArray(operations) || operations.length > 0;
}

function toolAvailableForCurrentSession(tool: ToolManifest, session?: SessionSummary): boolean {
  if (!session) return false;
  if (!toolAvailableForPolicy(
    tool,
    session.mode,
    session.toolProfileVersion === 'subagent-readonly-v1'
      ? 'subagent-readonly-v1'
      : session.toolProfileVersion === 'control-center-auto-approve-v1'
        ? 'control-center-auto-approve-v1'
        : 'control-center-v1',
  )) return false;
  return tool.enabled !== false;
}

function ModelTree({
  catalog,
  disabled,
  requestOpen,
  onChange,
}: {
  catalog?: ModelCatalog;
  disabled: boolean;
  requestOpen: number;
  onChange: (provider: string, modelId: string, level: ThinkingLevel) => void;
}) {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    if (requestOpen > 0 && catalog && !disabled) setOpen(true);
  }, [catalog, disabled, requestOpen]);
  const selected = record(catalog?.selected);
  const selectedProviderId = text(selected.provider);
  const selectedModelId = text(selected.id) || text(selected.modelId);
  const selectedProvider = catalog?.providers.find((item) => item.id === selectedProviderId);
  const selectedModel = selectedProvider?.models.find((item) => item.id === selectedModelId);
  const displayedProviderId = selectedModel ? selectedProviderId : '';
  const displayedModelId = selectedModel?.id ?? '';
  const thinking = catalog?.thinkingLevel ?? 'off';
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button aria-label={`模型：${selectedModel?.name ?? '未选择'}，思考强度：${thinkingLabel(thinking)}`} className="agent-composer__picker" size="small" title={`模型：${selectedModel?.name ?? '未选择'}，思考强度：${thinkingLabel(thinking)}`} variant="quiet" disabled={!catalog || disabled} leadingIcon={<BrainCircuit size={15} />}>{selectedModel?.name ?? '选择模型'} · {thinkingLabel(thinking)}</Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="agent-model-tree">
        <header><strong>模型与推理强度</strong></header>
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

type ComposerCommand = ResolvedPiCommand | ProductCommand;

interface CommandAvailability {
  enabled: boolean;
  disabledReason?: string;
}

type ResolvedPiCommand = AgentCommand & CommandAvailability;

interface ProductCommand extends CommandAvailability {
  name: AgentProductCommandName;
  invocation: `/${AgentProductCommandName}`;
  description: string;
  source: 'product';
  behavior: 'execute' | 'insert';
}

const productCommandDefinitions: Omit<ProductCommand, keyof CommandAvailability>[] = [
  { name: 'new', invocation: '/new', description: '创建一段独立对话', source: 'product', behavior: 'execute' },
  { name: 'resume', invocation: '/resume', description: '打开连续对话列表并恢复其他对话', source: 'product', behavior: 'execute' },
  { name: 'name', invocation: '/name', description: '重命名当前对话', source: 'product', behavior: 'insert' },
  { name: 'branch', invocation: '/branch', description: '从历史用户消息创建独立分支', source: 'product', behavior: 'execute' },
  { name: 'compact', invocation: '/compact', description: '保留连续会话并缩短上下文', source: 'product', behavior: 'insert' },
  { name: 'model', invocation: '/model', description: '选择当前对话的模型', source: 'product', behavior: 'execute' },
  { name: 'thinking', invocation: '/thinking', description: '调整当前模型的思考强度', source: 'product', behavior: 'execute' },
  { name: 'permissions', invocation: '/permissions', description: '查看或切换当前对话权限', source: 'product', behavior: 'execute' },
  { name: 'tools', invocation: '/tools', description: '查看当前权限可用的工具', source: 'product', behavior: 'execute' },
  { name: 'session', invocation: '/session', description: '查看当前对话、计划与运行统计', source: 'product', behavior: 'execute' },
  { name: 'status', invocation: '/status', description: '打开当前对话状态', source: 'product', behavior: 'execute' },
  { name: 'settings', invocation: '/settings', description: '打开控制中心配置', source: 'product', behavior: 'execute' },
  { name: 'hotkeys', invocation: '/hotkeys', description: '查看 Web Agent 命令和键盘操作', source: 'product', behavior: 'execute' },
  { name: 'stop', invocation: '/stop', description: '停止当前处理', source: 'product', behavior: 'execute' },
  { name: 'help', invocation: '/help', description: '查看命令及其来源', source: 'product', behavior: 'execute' },
];

function buildCommandCatalog({
  session,
  catalog,
  piCommands,
  tools,
  toolCatalogStatus,
  busy,
  sending,
}: {
  session?: SessionSummary;
  catalog?: ModelCatalog;
  piCommands: AgentCommand[];
  tools: ToolManifest[];
  toolCatalogStatus: 'loading' | 'ready' | 'failed';
  busy: boolean;
  sending: boolean;
}): ComposerCommand[] {
  const productCommands = productCommandDefinitions.map((command): ProductCommand => ({
    ...command,
    ...productCommandAvailability(command.name, { session, catalog, tools, toolCatalogStatus, busy, sending }),
  }));
  const reserved = new Set(productCommands.map((command) => command.invocation.toLowerCase()));
  const piAvailability = genericCommandAvailability({ session, busy, sending });
  const resolvedPiCommands = piCommands.map((command): ResolvedPiCommand => ({
    ...command,
    ...(reserved.has(command.invocation.toLowerCase())
      ? { enabled: false, disabledReason: '同名命令由控制中心接管' }
      : piAvailability),
  }));
  return [...productCommands, ...resolvedPiCommands];
}

function productCommandAvailability(
  name: AgentProductCommandName,
  context: {
    session?: SessionSummary;
    catalog?: ModelCatalog;
    tools: ToolManifest[];
    toolCatalogStatus: 'loading' | 'ready' | 'failed';
    busy: boolean;
    sending: boolean;
  },
): CommandAvailability {
  const { session, catalog, tools, toolCatalogStatus, busy, sending } = context;
  if ((busy || sending) && name !== 'resume' && name !== 'session' && name !== 'status' && name !== 'stop') {
    return { enabled: false, disabledReason: '当前处理中，仅可切换对话、查看状态或停止' };
  }
  if (name === 'new' || name === 'settings' || name === 'help' || name === 'hotkeys') return { enabled: true };
  if (!session) return { enabled: false, disabledReason: '请先选择对话' };
  if (name === 'stop') {
    return busy
      ? { enabled: true }
      : { enabled: false, disabledReason: '当前没有正在处理的任务' };
  }
  if ((name === 'model' || name === 'thinking') && !catalog) {
    return { enabled: false, disabledReason: '模型目录暂不可用' };
  }
  if (name === 'tools') {
    if (toolCatalogStatus !== 'ready') return { enabled: false, disabledReason: '工具目录暂不可用' };
    const hasAvailableTool = tools.some((tool) => toolAvailableForCurrentSession(tool, session));
    if (!hasAvailableTool) {
      return { enabled: false, disabledReason: `${permissionLabel(session)}没有可用工具` };
    }
  }
  return { enabled: true };
}

function genericCommandAvailability({
  session,
  busy,
  sending,
}: {
  session?: SessionSummary;
  busy: boolean;
  sending: boolean;
}): CommandAvailability {
  if (!session) return { enabled: false, disabledReason: '请先选择对话' };
  if (busy || sending) return { enabled: false, disabledReason: '当前处理中，仅可查看状态或停止' };
  return { enabled: true };
}

function nextEnabledCommandIndex(commands: ComposerCommand[], current: number, delta: 1 | -1): number {
  if (!commands.some((command) => command.enabled)) return current;
  let candidate = current;
  do {
    candidate = (candidate + delta + commands.length) % commands.length;
  } while (!commands[candidate]?.enabled && candidate !== current);
  return candidate;
}

function commandTitle(source: ComposerCommand['source']): string {
  return ({ product: '控制中心', extension: 'Pi 扩展', prompt: 'Pi 提示模板', skill: 'Pi Skill' })[source];
}

function permissionLabel(session: SessionSummary): string {
  return permissionPreset(
    session.mode,
    session.toolProfileVersion ?? 'control-center-v1',
  ).label;
}

function composerPlaceholder(name: string, support: 'supported' | 'unsupported' | 'unknown'): string {
  if (support === 'supported') return `给${name}发消息，输入 / 查看命令，或粘贴图片…`;
  if (support === 'unsupported') return `给${name}发消息，输入 / 查看命令；当前模型不支持图片…`;
  return `给${name}发消息，输入 / 查看命令；当前模型图片能力未知…`;
}

function thinkingLabel(value: string): string {
  return ({ off: '不启用推理', minimal: '最小', low: '低', medium: '中', high: '高', xhigh: '极高', max: 'Max' } as Record<string, string>)[value] ?? value;
}

function riskLabel(value: string): string {
  return ({ R0: '只读', R1: '需确认', R2: '高风险确认', R3: '禁止' } as Record<string, string>)[value] ?? '受控';
}

function record(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function text(value: unknown): string { return typeof value === 'string' ? value : ''; }
