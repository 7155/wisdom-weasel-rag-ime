/**
 * PawAgentHome — Agent 新建工作主页
 *
 * 创建链路、乐观入场（optimistic admission）、模型/思考配置与 Room 创建语义
 * 与 PawAgentApp 原内联实现逐项一致。
 *
 * 设计合同：
 * - 桌面首屏合同：这是一块固定的 App 表面，不是往下翻的落地页。新建 Composer
 *   与「继续工作」在同一屏内完成；继续工作列表只在自身内部滚动，页脚是钉在
 *   底部的状态条。
 * - UR-002/040：单一 Agent 入口，Session / Room 在 Composer 底栏选择；
 *   PF-CM-003：所选工作类型的真实后果（谁来做、哪些伙伴加入、过程在哪里看得见）
 *   就写在 Composer 下方；Session 一句指向 PawSessionWorkspace 里真实存在的
 *   「Agent 轨迹 / 上下文装配」，不描述任何这里没有的界面。「记有来源的装配
 *   节点能直接打开那条证据」对应 PawContextTrace 已落地的双向证据链：只有
 *   metadata 里带具体实体标识的节点才可点击，这句因此不构成过度承诺。
 * - UR-046：两档全系统权限（全权限逐项确认 / 全自动），全自动明确提示自动批准与 OS 边界。
 * - UR-011/025 与 PF-CM-018/021：页脚只投影真实目录状态（读取中 / 失败可重试 /
 *   模型数量），不虚构“Runtime 已连接”这类前端无法证明的声明。
 *
 * 样式：paw-os/styles/paw-os-agent-next.css（类名 an-* 作用域）。
 */

import {
  ArrowUp,
  Check,
  ChevronDown,
  CircleAlert,
  LoaderCircle,
  Minus,
  Plus,
  Users,
} from 'lucide-react';
import { useEffect, useId, useMemo, useRef, useState, type ClipboardEvent } from 'react';
import { useControlTransport } from '@/app/control-transport';
import {
  useAgentPreferencesRead,
  type AgentExecutionMode,
} from '@/features/agent/composer/agent-preferences-store';
import { unrestrictedWorkspaceRoots } from '@/features/agent/composer/permission-policy';
import {
  supportedPiThinkingLevels,
  type PiModelOption,
} from '@/features/agent/model-catalog-options';
import {
  PermissionMark,
  ProviderMark,
  WorkspaceMark,
} from '@/features/agent/marks/ConversationMarks';
import type { AgentPersonaV1 } from '@/contracts/generated/agent-persona.v1';
import type { RoomAttachmentReceipt } from '@/contracts/room-reducer';
import type { SessionSummary } from '@/features/agent/types';
import { ComposerAttachmentPreview, type ComposerShellAttachment } from '@/features/composer/ComposerShell';
import {
  MAX_COMPOSER_ATTACHMENT_BYTES,
  MAX_COMPOSER_ATTACHMENTS,
  normalizeComposerAttachmentMimeType,
} from '@/contracts/attachment-policy';
import {
  defaultRoomPermissionPolicy,
  roomPermissionPolicyNeedsDangerousConfirmation,
  roomPermissionPolicyNeedsWorkspaceConfirmation,
  type RoomPermissionPolicy,
  type RoomSummary,
} from '@/features/rooms/room-types';
import {
  RoomPermissionPolicyEditor,
  roomPermissionLayerPresentation,
} from '@/features/rooms/room-presentation';
import { roomPlanetName } from '@/features/rooms/room-participant-identity';
import { useAgentLiveStore } from '@/features/agent/state/live-store';
import { useRoomLiveStore } from '@/features/rooms/state/live-store';
import { clipboardFilesFromEvent } from '@/features/agent/composer/AgentComposer';
import type { PickedFile } from '@/platform/transport';
import { pawBrowserHost } from './paw-browser-host';
import { PawAppIcon } from '../shell/PawAppIcon';

type WorkMode = 'session' | 'room';
type Selection =
  | { kind: 'new'; draft?: string }
  | { kind: 'session'; id: string; draft?: string }
  | { kind: 'room'; id: string; draft?: string; error?: string };

type OptionsPanel = 'project' | 'model' | 'permission' | null;

type HomePendingAttachment = {
  id: string;
  file: File;
};

const PERMISSION_PRESETS: ReadonlyArray<{
  executionMode: AgentExecutionMode;
  toolProfileVersion: 'control-center-full-access-v1' | 'control-center-auto-approve-v1';
  label: string;
  description: string;
}> = [
  {
    executionMode: 'per_action',
    toolProfileVersion: 'control-center-full-access-v1',
    label: '全权限',
    description: '整个系统与所有 Tool 可用；有影响的操作逐项请求确认',
  },
  {
    executionMode: 'full_trust',
    toolProfileVersion: 'control-center-auto-approve-v1',
    label: '全自动',
    description: '整个系统与所有 Tool 可用；每个动作自动批准，仍受操作系统边界约束',
  },
];
const PROMPT_STARTERS: ReadonlyArray<{ label: string; prompt: string }> = [
  { label: '梳理现状', prompt: '梳理这个项目的当前状态：正在进行什么、被什么卡住、下一步最值得做什么。' },
  { label: '审查改动', prompt: '审查最近的改动，指出风险、遗漏和需要跟进的问题。' },
  { label: '拆解任务', prompt: '把这件事拆成可执行的步骤，并从第一步开始：' },
];

export function PawAgentHome({
  catalogError = '',
  catalogLoading = false,
  defaultModel,
  initialDraft,
  models,
  onCreated,
  onOpenRoom,
  onOpenSession,
  onReloadCatalog,
  personas,
  projectRoots,
  rooms,
  sessions,
}: {
  catalogError?: string;
  catalogLoading?: boolean;
  defaultModel: string;
  initialDraft?: string;
  models: PiModelOption[];
  onCreated: (selection: Selection, created?: SessionSummary, createdRoom?: RoomSummary) => void;
  onOpenRoom: (id: string) => void;
  onOpenSession: (id: string) => void;
  onReloadCatalog?: () => void;
  personas: AgentPersonaV1[];
  projectRoots: string[];
  rooms: RoomSummary[];
  sessions: SessionSummary[];
}) {
  const transport = useControlTransport();
  const electronHost = pawBrowserHost();
  const preferenceRead = useAgentPreferencesRead();
  const preferences = preferenceRead.preferences;
  const [mode, setMode] = useState<WorkMode>('session');
  const [prompt, setPrompt] = useState(initialDraft ?? '');
  const [workspaceRoot, setWorkspaceRoot] = useState('');
  const [executionMode, setExecutionMode] = useState<AgentExecutionMode>(selectableExecutionMode(preferences.executionMode));
  const [modelReference, setModelReference] = useState(preferences.modelReference || defaultModel);
  const [thinking, setThinking] = useState(preferences.thinking);
  const [roomParticipantOverride, setRoomParticipantOverride] = useState<number | null>(null);
  const [roomPermissionPolicy, setRoomPermissionPolicy] = useState<RoomPermissionPolicy>(
    () => defaultRoomPermissionPolicy('collaboration'),
  );
  const [optionsPanel, setOptionsPanel] = useState<OptionsPanel>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [pendingAttachments, setPendingAttachments] = useState<HomePendingAttachment[]>([]);
  const [pendingClipboardPaste, setPendingClipboardPaste] = useState(false);
  const composerRef = useRef<HTMLDivElement>(null);
  const promptRef = useRef<HTMLTextAreaElement>(null);
  const chipRefs = useRef<Record<Exclude<OptionsPanel, null>, HTMLButtonElement | null>>({
    permission: null,
    model: null,
    project: null,
  });
  const preferenceHydratedRef = useRef(false);
  const preferenceEditedRef = useRef({ executionMode: false, modelReference: false, thinking: false });
  const modeBriefId = useId();

  useEffect(() => {
    if (!modelReference && (preferences.modelReference || defaultModel)) {
      setModelReference(preferences.modelReference || defaultModel);
    }
  }, [defaultModel, modelReference, preferences.modelReference]);
  useEffect(() => {
    if (preferenceRead.isPending || preferenceRead.readError || preferenceHydratedRef.current) return;
    preferenceHydratedRef.current = true;
    if (!preferenceEditedRef.current.executionMode) setExecutionMode(selectableExecutionMode(preferences.executionMode));
    if (!preferenceEditedRef.current.modelReference) setModelReference(preferences.modelReference || defaultModel);
    if (!preferenceEditedRef.current.thinking) setThinking(preferences.thinking);
  }, [defaultModel, preferenceRead.isPending, preferenceRead.readError, preferences.executionMode, preferences.modelReference, preferences.thinking]);
  useEffect(() => {
    if (!workspaceRoot && projectRoots[0]) setWorkspaceRoot(projectRoots[0]);
  }, [projectRoots, workspaceRoot]);

  const selectedModel = models.find((item) => item.reference === modelReference);
  const thinkingLevels = supportedPiThinkingLevels(selectedModel, { includeOff: true });
  const availableRoomPersonas = personas
    .filter((persona) => persona.selectableModes.includes('coordinator'))
    .slice(0, 8);
  const suggestedParticipantCount = suggestedRoomParticipantCount(prompt, availableRoomPersonas.length);
  const roomParticipantCount = Math.min(
    availableRoomPersonas.length,
    Math.max(0, roomParticipantOverride ?? suggestedParticipantCount),
  );
  const roomPersonas = availableRoomPersonas.slice(0, roomParticipantCount);
  const roomReady = roomPersonas.length >= 2;
  const modelGroups = useMemo(() => {
    const groups = new Map<string, PiModelOption[]>();
    for (const model of models) groups.set(model.provider, [...(groups.get(model.provider) ?? []), model]);
    return [...groups.entries()];
  }, [models]);
  const sessionPermission = PERMISSION_PRESETS.find((item) => item.executionMode === executionMode) ?? PERMISSION_PRESETS[0]!;
  const roomPermission = roomPermissionLayerPresentation(
    roomPermissionPolicy,
    'room',
    'collaboration',
  );
  const permissionLabel = mode === 'room'
    ? `${roomPermission.effectiveLabel} · 分层`
    : sessionPermission.label;
  const permissionMode = mode === 'room'
    ? roomPermissionPolicy.room.executionMode
    : executionMode;

  // 继续工作按真实更新时间取最近四条，而不是按目录返回顺序截断。
  const recents = useMemo(() => [
    ...sessions.map((item) => ({ kind: 'session' as const, item })),
    ...rooms.map((item) => ({ kind: 'room' as const, item })),
  ]
    .sort((left, right) => right.item.updatedAtMs - left.item.updatedAtMs)
    .slice(0, 4), [rooms, sessions]);

  useEffect(() => {
    if (!optionsPanel) return;
    const closeOutside = (event: PointerEvent) => {
      if (event.target instanceof Node && !composerRef.current?.contains(event.target)) setOptionsPanel(null);
    };
    const closeWithEscape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      setOptionsPanel(null);
      chipRefs.current[optionsPanel]?.focus();
    };
    document.addEventListener('pointerdown', closeOutside);
    document.addEventListener('keydown', closeWithEscape);
    return () => {
      document.removeEventListener('pointerdown', closeOutside);
      document.removeEventListener('keydown', closeWithEscape);
    };
  }, [optionsPanel]);

  async function pickWorkspace(): Promise<void> {
    if (!transport.pickFiles && !electronHost?.pickWorkspaceDirectory) {
      setError('当前运行环境不能选择本地目录。');
      return;
    }
    try {
      const path = transport.pickFiles
        ? (await transport.pickFiles({ purpose: 'workspace-root', selection: 'directory', multiple: false, maxFiles: 1 }))[0]?.path?.trim()
        : (await electronHost?.pickWorkspaceDirectory?.())?.path?.trim();
      if (path) {
        setWorkspaceRoot(path);
        setOptionsPanel(null);
      }
    } catch (pickError) {
      setError(errorText(pickError));
    }
  }

  function addPastedFiles(files: File[]): void {
    if (!transport.pasteImages) {
      setError('当前运行环境不能导入剪贴板文件。');
      return;
    }
    const remaining = MAX_COMPOSER_ATTACHMENTS - pendingAttachments.length;
    if (files.length > remaining) {
      setError(`当前输入还可以粘贴 ${remaining} 个附件。`);
      return;
    }
    const oversized = files.find((file) => file.size <= 0 || file.size > MAX_COMPOSER_ATTACHMENT_BYTES);
    if (oversized) {
      setError(`${oversized.name || '附件'} 必须小于 20 MiB 且不能为空。`);
      return;
    }
    setPendingClipboardPaste(false);
    setPendingAttachments((current) => [
      ...current,
      ...files.map((file) => ({ id: clientId('home-attachment'), file })),
    ]);
    setError('');
  }

  function pasteIntoHome(event: ClipboardEvent<HTMLTextAreaElement>): void {
    const { files, hasFileItem } = clipboardFilesFromEvent(event);
    if (!files.length && !hasFileItem) {
      const pastedText = event.clipboardData.getData?.('text/plain') ?? '';
      if (pastedText || !transport.pasteImages) return;
      event.preventDefault();
      setPendingClipboardPaste(true);
      setError('');
      return;
    }
    event.preventDefault();
    if (files.length) {
      addPastedFiles(files);
      return;
    }
    if (!transport.pasteImages) {
      setError('当前运行环境不能导入剪贴板文件。');
      return;
    }
    // WebKit can expose the image item but not its bytes. The native transport
    // will inspect its trusted pasteboard after a Session/Room owner exists.
    setPendingClipboardPaste(true);
    setError('');
  }

  async function importPendingAttachments(
    owner: { sessionId: string } | { roomId: string },
  ): Promise<PickedFile[]> {
    const files = pendingAttachments.map((item) => item.file);
    if (!files.length && !pendingClipboardPaste) return [];
    if (!transport.pasteImages) throw new Error('当前运行环境不能导入剪贴板文件。');
    const imported = await transport.pasteImages({
      ...owner,
      ...(files.length ? { files } : {}),
      maxFiles: files.length || 1,
    });
    if (!imported.length) throw new Error('剪贴板里没有可导入的文件。');
    return imported;
  }

  function clearPendingAttachments(): void {
    setPendingAttachments([]);
    setPendingClipboardPaste(false);
  }

  async function startWork(): Promise<void> {
    const message = prompt.trim() || (pendingAttachments.length || pendingClipboardPaste ? '请查看附件。' : '');
    if (!message || submitting) return;
    if (mode === 'room' && !roomReady) {
      setError('当前没有足够的 Room 伙伴。');
      return;
    }
    setSubmitting(true);
    setError('');
    const toolProfileVersion = executionMode === 'full_trust'
      ? 'control-center-auto-approve-v1'
      : 'control-center-full-access-v1';
    const workspaceRoots = unrestrictedWorkspaceRoots(workspaceRoot);
    const roomWorkspaceRoots = (
      roomPermissionPolicy.room.executionMode === 'per_action'
      || roomPermissionPolicy.room.executionMode === 'full_trust'
    )
      ? workspaceRoots
      : workspaceRoot ? [workspaceRoot] : [];
    try {
      if (mode === 'session') {
        const response = await transport.request<Record<string, unknown>>({
          pathId: 'agent.sessions.create',
          body: {
            title: workTitle(message),
            mode: 'coordinator',
            executionMode,
            toolProfileVersion,
            workspaceRoots,
            ...(executionMode === 'full_trust'
              ? { dangerousModeConfirmation: 'ENABLE_FULL_TRUST' }
              : {}),
          },
        });
        const rawSession = record(record(response).session);
        const sessionId = text(rawSession.id);
        if (!sessionId) throw new Error('服务端没有返回可验证的 Session。');
        const clientMessageId = clientId('session');
        const createdSession = createdSessionSummary(rawSession, message, workspaceRoot, executionMode);
        const importedAttachments = await importPendingAttachments({ sessionId });
        const attachmentIds = importedAttachments.map((attachment) => attachment.id);
        clearPendingAttachments();
        // Tutti 入场顺序：先让 Session 与首条用户消息可见，配置与回执后台补齐。
        useAgentLiveStore.getState().appendOptimistic(sessionId, {
          clientMessageId,
          text: message,
          attachments: attachmentIds,
          nowMs: Date.now(),
        });
        onCreated({ kind: 'session', id: sessionId }, createdSession);
        void (async () => {
          try {
            const configuration = [] as Promise<unknown>[];
            const explicitModelSelection = preferenceEditedRef.current.modelReference
              || Boolean(preferences.modelReference && preferences.modelReference !== 'inherit');
            if (selectedModel && explicitModelSelection) {
              configuration.push(transport.request({
                pathId: 'agent.session.model.select',
                params: { sessionId },
                body: { provider: selectedModel.provider, modelId: selectedModel.id },
              }));
              if (thinkingLevels.includes(thinking)) {
                configuration.push(transport.request({
                  pathId: 'agent.session.thinking.select',
                  params: { sessionId },
                  body: { level: thinking },
                }));
              }
            }
            void Promise.allSettled(configuration);
            await transport.request({
              pathId: 'agent.session.prompt',
              params: { sessionId },
              body: { message, attachments: attachmentIds, clientMessageId },
            });
            useAgentLiveStore.getState().acknowledgeOptimistic(sessionId, clientMessageId, Date.now());
          } catch (requestError) {
            useAgentLiveStore.getState().failOptimistic(sessionId, clientMessageId, errorText(requestError), Date.now());
          }
        })();
      } else {
        const selectedPersonas = roomPersonas;
        const response = await transport.request<Record<string, unknown>>({
          pathId: 'agent.rooms.create',
          body: {
            title: workTitle(message),
            roomKind: 'collaboration',
            avatar: 'briefcase',
            description: message,
            scenarioPrompt: '',
            participants: selectedPersonas.map((persona, index) => ({
              roleId: persona.roleId,
              roleVersion: persona.version,
              displayName: persona.displayName,
              collaborationRole: index === 0 ? 'coordinator' : index === 1 ? 'reviewer' : 'specialist',
            })),
            routingPolicy: 'parallel',
            routingConfig: { maxResponders: selectedPersonas.length, naturalJitter: 0, fallbackParticipantId: '' },
            workspaceRoots: roomWorkspaceRoots,
            permissionPolicy: roomPermissionPolicy,
            ...(roomPermissionPolicyNeedsWorkspaceConfirmation(roomPermissionPolicy)
              ? { workspaceScopeConfirmation: 'APPROVE_WORKSPACE_SCOPE' }
              : {}),
            ...(roomPermissionPolicyNeedsDangerousConfirmation(roomPermissionPolicy)
              ? { dangerousModeConfirmation: 'ENABLE_FULL_TRUST' }
              : {}),
          },
        });
        const rawRoom = record(record(response).room);
        const roomId = text(rawRoom.id);
        if (!roomId) throw new Error('服务端没有返回可验证的 Room。');
        const clientMessageId = clientId('room');
        const createdRoom = createdRoomSummary(
          rawRoom,
          message,
          roomWorkspaceRoots,
          selectedPersonas,
        );
        const importedAttachments = await importPendingAttachments({ roomId });
        const attachmentIds = importedAttachments.map((attachment) => attachment.id);
        clearPendingAttachments();
        useRoomLiveStore.getState().appendOptimistic(roomId, {
          clientMessageId,
          text: message,
          attachments: roomAttachmentReceipts(importedAttachments, roomId),
          nowMs: Date.now(),
        });
        onCreated({ kind: 'room', id: roomId }, undefined, createdRoom);
        void transport.request<Record<string, unknown>>({
          pathId: 'agent.room.message',
          params: { roomId },
          body: { message, clientMessageId, attachmentIds },
        }).then((messageResponse) => {
          useRoomLiveStore.getState().acceptMessage(roomId, messageResponse);
        }).catch((requestError) => {
          useRoomLiveStore.getState().discardOptimistic(roomId, clientMessageId);
          onCreated({ kind: 'room', id: roomId, draft: message, error: errorText(requestError) });
        });
      }
    } catch (requestError) {
      setError(errorText(requestError));
    } finally {
      setSubmitting(false);
    }
  }

  const greeting = timeGreeting();

  return (
    <div className="paw-agent-next an-home-root">
      <div className="an-home">
        <svg className="an-home-geo" aria-hidden="true">
          <defs>
            <pattern id="an-reg" width="220" height="220" patternUnits="userSpaceOnUse">
              <path d="M110 96v28M96 110h28" stroke="var(--an-ink)" strokeOpacity=".05" strokeWidth="1.5" />
            </pattern>
          </defs>
          <rect width="100%" height="100%" fill="url(#an-reg)" />
          <circle cx="86%" cy="18%" r="180" fill="none" stroke="var(--an-violet)" strokeOpacity=".08" strokeWidth="1.5" />
          <circle className="an-geo-orbit" cx="86%" cy="18%" r="120" fill="none" stroke="var(--an-cobalt)" strokeOpacity=".07" strokeWidth="1.5" strokeDasharray="2 7" />
        </svg>
        <div className="an-home-wrap">
          <div className="an-home-greet">{greeting}</div>
          <h1 className="an-home-title">交给 Agent <em>一件事</em>。</h1>

          <div className="an-composer" ref={composerRef}>
            {pendingAttachments.length || pendingClipboardPaste ? (
              <div aria-label="待发送附件" className="agent-composer__attachments" role="list">
                {pendingAttachments.map(({ id, file }) => {
                  const attachment: ComposerShellAttachment = {
                    id,
                    name: file.name || 'clipboard-file',
                    mimeType: normalizeComposerAttachmentMimeType(file.type),
                    byteSize: file.size,
                    previewFile: file,
                  };
                  return (
                    <span
                      className="agent-composer__attachment-chip"
                      data-attachment-kind={attachment.mimeType.startsWith('image/') ? 'image' : 'file'}
                      key={id}
                      role="listitem"
                    >
                      <ComposerAttachmentPreview attachment={attachment} />
                      <b title={attachment.name}>{attachment.name}</b>
                      <button
                        aria-label={`移除 ${attachment.name}`}
                        onClick={() => setPendingAttachments((current) => current.filter((item) => item.id !== id))}
                        type="button"
                      >×</button>
                    </span>
                  );
                })}
                {pendingClipboardPaste ? (
                  <span className="agent-composer__attachment-chip" data-attachment-kind="image" role="listitem">
                    <ComposerAttachmentPreview attachment={{ id: 'pending-clipboard-image', name: '剪贴板图片', mimeType: 'image/png' }} />
                    <b>剪贴板图片</b>
                    <button aria-label="移除 剪贴板图片" onClick={() => setPendingClipboardPaste(false)} type="button">×</button>
                  </span>
                ) : null}
              </div>
            ) : null}
            <textarea
              aria-describedby={modeBriefId}
              aria-label="描述你想完成的工作"
              onChange={(event) => setPrompt(event.target.value)}
              onPaste={pasteIntoHome}
              ref={promptRef}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
                  event.preventDefault();
                  void startWork();
                }
              }}
              placeholder="描述目标、上下文和验收方式…（Enter 发送，Shift+Enter 换行）"
              value={prompt}
            />
            <div className="an-composer-foot">
              <span className="an-mode-seg" role="radiogroup" aria-label="工作类型">
                <button
                  aria-checked={mode === 'session'}
                  aria-label="Session"
                  onClick={() => setMode('session')}
                  role="radio"
                  title="Session"
                  type="button"
                >
                  <PawAppIcon appId="agent" size={14} />
                  <span className="an-chip-text">Session</span>
                </button>
                <button
                  aria-checked={mode === 'room'}
                  aria-label="Room"
                  onClick={() => setMode('room')}
                  role="radio"
                  title="Room"
                  type="button"
                >
                  <PawAppIcon appId="room" size={14} />
                  <span className="an-chip-text">Room</span>
                </button>
              </span>

              <span className="an-anchor">
                <button
                  aria-expanded={optionsPanel === 'permission'}
                  aria-label={`权限 · ${permissionLabel}`}
                  className="an-chip"
                  onClick={() => setOptionsPanel(optionsPanel === 'permission' ? null : 'permission')}
                  ref={(node) => { chipRefs.current.permission = node; }}
                  title={`权限 · ${permissionLabel}`}
                  type="button"
                >
                  <PermissionMark mode={permissionMode} size={14} />
                  <span className="an-chip-text">{permissionLabel}</span>
                  <ChevronDown className="caret" size={13} />
                </button>
                {optionsPanel === 'permission' ? (
                  <div className="an-menu" role={mode === 'session' ? 'menu' : undefined}>
                    <div className="an-menu-title">
                      {mode === 'room' ? 'Room 三层权限' : '权限模式'}
                    </div>
                    {mode === 'room' ? (
                      <RoomPermissionPolicyEditor
                        compact
                        onChange={setRoomPermissionPolicy}
                        policy={roomPermissionPolicy}
                        roomKind="collaboration"
                      />
                    ) : PERMISSION_PRESETS.map((item) => (
                      <button
                        aria-checked={item.executionMode === executionMode}
                        className="an-menu-item"
                        key={item.executionMode}
                        onClick={() => {
                          preferenceEditedRef.current.executionMode = true;
                          setExecutionMode(item.executionMode);
                          setOptionsPanel(null);
                        }}
                        role="menuitemradio"
                        type="button"
                      >
                        <span style={{ minWidth: 0 }}>
                          <span className="mi-tt">{item.executionMode === executionMode ? <Check size={12} style={{ marginRight: 6, verticalAlign: -1 }} /> : null}{item.label}</span>
                          <span className="mi-sub">{item.description}</span>
                        </span>
                      </button>
                    ))}
                  </div>
                ) : null}
              </span>

              <span className="an-anchor">
                <button
                  aria-expanded={optionsPanel === 'model'}
                  aria-label={`模型与推理 · ${selectedModel?.name ?? '自动模型'} · ${thinkingLabel(thinking)}`}
                  className="an-chip"
                  onClick={() => setOptionsPanel(optionsPanel === 'model' ? null : 'model')}
                  ref={(node) => { chipRefs.current.model = node; }}
                  title={`模型与推理 · ${selectedModel?.name ?? '自动模型'} · ${thinkingLabel(thinking)}`}
                  type="button"
                >
                  <ProviderMark providerId={selectedModel?.provider} size={14} />
                  <span className="an-chip-text">{selectedModel?.name ?? '自动模型'}</span>
                  <span className="an-chip-detail"> · {thinkingLabel(thinking)}</span>
                  <ChevronDown className="caret" size={13} />
                </button>
                {optionsPanel === 'model' ? (
                  <div aria-label="选择模型与推理强度" className="an-menu" role="menu">
                    <div aria-label="模型" role="group">
                      <div className="an-menu-title">模型</div>
                      {modelGroups.map(([provider, group]) => (
                        <div key={provider}>
                          <div className="an-menu-group">{provider}</div>
                          {group.map((model) => (
                            <button
                              aria-checked={model.reference === modelReference}
                              className="an-menu-item"
                              key={model.reference}
                              onClick={() => {
                                preferenceEditedRef.current.modelReference = true;
                                setModelReference(model.reference);
                                setOptionsPanel(null);
                              }}
                              role="menuitemradio"
                              type="button"
                            >
                              <span style={{ minWidth: 0 }}>
                                <span className="mi-tt">{model.reference === modelReference ? <Check size={12} style={{ marginRight: 6, verticalAlign: -1 }} /> : null}{model.name}</span>
                              </span>
                            </button>
                          ))}
                        </div>
                      ))}
                    </div>
                    {selectedModel && thinkingLevels.length > 0 ? (
                      <>
                        <div className="an-menu-sep" />
                        <div aria-label="推理强度" role="group">
                          <div className="an-menu-title">推理强度</div>
                          {thinkingLevels.map((level) => (
                            <button
                              aria-checked={level === thinking}
                              className="an-menu-item"
                              key={level}
                              onClick={() => {
                                preferenceEditedRef.current.thinking = true;
                                setThinking(level);
                                setOptionsPanel(null);
                              }}
                              role="menuitemradio"
                              type="button"
                            >
                              <span className="mi-tt">{level === thinking ? <Check size={12} style={{ marginRight: 6, verticalAlign: -1 }} /> : null}{thinkingLabel(level)}</span>
                            </button>
                          ))}
                        </div>
                      </>
                    ) : null}
                  </div>
                ) : null}
              </span>

              <span className="an-anchor">
                <button
                  aria-expanded={optionsPanel === 'project'}
                  aria-label={workspaceRoot ? `起始项目 · ${projectName([workspaceRoot])}` : '起始项目（可选）'}
                  className="an-chip"
                  onClick={() => setOptionsPanel(optionsPanel === 'project' ? null : 'project')}
                  ref={(node) => { chipRefs.current.project = node; }}
                  title={workspaceRoot || '起始项目（可选）'}
                  type="button"
                >
                  <WorkspaceMark bound={Boolean(workspaceRoot)} size={14} />
                  <span className="an-chip-text">{workspaceRoot ? projectName([workspaceRoot]) : '起始项目（可选）'}</span>
                  <ChevronDown className="caret" size={13} />
                </button>
                {optionsPanel === 'project' ? (
                  <div className="an-menu" role="menu">
                    <div className="an-menu-title">起始项目（可选）</div>
                    {projectRoots.map((root) => (
                      <button
                        aria-checked={root === workspaceRoot}
                        className="an-menu-item"
                        key={root}
                        onClick={() => { setWorkspaceRoot(root); setOptionsPanel(null); }}
                        role="menuitemradio"
                        type="button"
                      >
                        <span style={{ minWidth: 0 }}>
                          <span className="mi-tt">{root === workspaceRoot ? <Check size={12} style={{ marginRight: 6, verticalAlign: -1 }} /> : null}{projectName([root])}</span>
                          <span className="mi-sub" style={{ fontFamily: 'var(--an-mono)' }}>{root}</span>
                        </span>
                      </button>
                    ))}
                    {transport.pickFiles || electronHost?.pickWorkspaceDirectory ? (
                      <>
                        <div className="an-menu-sep" />
                        <button className="an-menu-item" onClick={() => void pickWorkspace()} type="button">
                          <span className="mi-tt">浏览其他目录…</span>
                        </button>
                      </>
                    ) : null}
                  </div>
                ) : null}
              </span>

              <button
                aria-label={submitting ? '正在创建' : `开始 ${mode === 'session' ? 'Session' : 'Room'}`}
                className="an-send"
                disabled={(!prompt.trim() && !pendingAttachments.length && !pendingClipboardPaste) || submitting || (mode === 'room' && !roomReady)}
                onClick={() => void startWork()}
                type="button"
              >
                {submitting ? <LoaderCircle className="ui-spin" size={14} /> : <ArrowUp size={14} />}
              </button>
            </div>
          </div>
          {!prompt.trim() ? (
            <div aria-label="快速开始" className="an-starters" role="group">
              {PROMPT_STARTERS.map((starter) => (
                <button
                  className="an-starter"
                  key={starter.label}
                  onClick={() => {
                    setPrompt(starter.prompt);
                    promptRef.current?.focus();
                  }}
                  title={starter.prompt}
                  type="button"
                >
                  {starter.label}
                </button>
              ))}
            </div>
          ) : null}
          {mode === 'session' ? (
            <p className="an-mode-brief" id={modeBriefId}>
              一位 Agent 在同一条时间线里完成这件事；随时可中止或追问。过程可切到 Agent 轨迹，看每一轮装配了哪些上下文——记有来源的装配节点，能直接打开那条记忆、知识或文件。
            </p>
          ) : availableRoomPersonas.length > 0 ? (
            <div className="an-mode-brief an-room-plan" id={modeBriefId}>
              <span className="an-room-plan__label">任务建议 {suggestedParticipantCount} 位</span>
              <span aria-label="Room 伙伴数量" className="an-room-plan__stepper" role="group">
                <button
                  aria-label="减少 Room 伙伴"
                  disabled={roomParticipantCount <= 1}
                  onClick={() => setRoomParticipantOverride(Math.max(1, roomParticipantCount - 1))}
                  type="button"
                ><Minus size={12} /></button>
                <output aria-live="polite">{roomParticipantCount}</output>
                <button
                  aria-label="增加 Room 伙伴"
                  disabled={roomParticipantCount >= availableRoomPersonas.length || roomParticipantCount >= 8}
                  onClick={() => setRoomParticipantOverride(Math.min(8, roomParticipantCount + 1))}
                  type="button"
                ><Plus size={12} /></button>
              </span>
              {roomPersonas.map((persona, index) => (
                <span className="an-room-plan__chip" data-testid="room-planned-participant" key={persona.roleId}>
                  {roomPlanetName(index)}
                  <i>{collaborationRoleLabel(index)}</i>
                </span>
              ))}
              {!roomReady ? (
                <span className="an-room-plan__constraint">
                  Room Runtime 当前要求至少 2 位伙伴；你可以预览 1 位，但需增加后才能开始。
                </span>
              ) : null}
            </div>
          ) : (
            <div className="an-mode-brief an-room-plan is-blocked" id={modeBriefId}>
              <span>当前没有可用的 Room 伙伴，暂时无法开始。</span>
            </div>
          )}
          {preferenceRead.readError ? (
            <p className="an-home-error" role="alert">
              <CircleAlert size={14} />{preferenceRead.readError}
              <button onClick={preferenceRead.reload} type="button">重新读取</button>
            </p>
          ) : null}
          {error ? (
            <p className="an-home-error" role="alert"><CircleAlert size={14} />{error}</p>
          ) : null}

          {recents.length ? (
            /* 桌面首屏合同：继续工作与 Composer 同屏。列表在自身内部滚动，
               绝不把页面推成一篇往下翻的长文。 */
            <div className="an-home-section an-home-recents">
              <h2>继续工作</h2>
              <div className="an-recent-list">
                {recents.map((entry) => entry.kind === 'session' ? (
                  <button className="an-recent-card" key={`session:${entry.item.id}`} onClick={() => onOpenSession(entry.item.id)} type="button">
                    <span className="rc-top"><span className={`an-dot ${entry.item.status === 'archived' ? '' : 'is-ok'}`} /><span className="rc-title">{entry.item.title}</span></span>
                    {entry.item.lastMessagePreview ? <span className="rc-preview">{entry.item.lastMessagePreview}</span> : null}
                    <span className="rc-meta">{projectName(entry.item.workspaceRoots)} · {relativeTime(entry.item.updatedAtMs)}</span>
                  </button>
                ) : (
                  <button className="an-recent-card is-room" key={`room:${entry.item.id}`} onClick={() => onOpenRoom(entry.item.id)} type="button">
                    <span className="rc-top"><span className={`an-dot ${entry.item.status === 'active' ? 'is-run' : ''}`} /><span className="rc-title">{entry.item.title}</span></span>
                    {entry.item.description ? <span className="rc-preview">{entry.item.description}</span> : null}
                    <span className="rc-meta"><Users size={11} style={{ verticalAlign: -1 }} /> {entry.item.participants?.length ?? 0} 位伙伴 · {relativeTime(entry.item.updatedAtMs)}</span>
                  </button>
                ))}
              </div>
            </div>
          ) : null}

          {/* 只陈述有真实目录数据支撑的事实；连接状态由 Session 工作区的运行时行负责。 */}
          {(catalogLoading || catalogError || models.length || defaultModel) ? (
            <div className="an-home-foot">
              {catalogLoading ? (
                <span><LoaderCircle className="ui-spin" size={12} />正在读取模型与工作记录…</span>
              ) : null}
              {!catalogLoading && catalogError ? (
                <span className="is-warn" role="status">
                  <CircleAlert size={12} />{catalogError}
                  {onReloadCatalog ? <button onClick={onReloadCatalog} type="button">重新读取目录</button> : null}
                </span>
              ) : null}
              {models.length ? <span><span className="an-dot is-ok" />{models.length} 个可用模型</span> : null}
              {defaultModel ? <span>默认模型 {defaultModel.split('/').pop()}</span> : null}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}

/* ---------- 本地工具（与 PawAgentApp 原实现语义一致） ---------- */

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}
function record(value: unknown): Record<string, unknown> {
  return isRecord(value) ? value : {};
}
function text(value: unknown): string {
  return typeof value === 'string' ? value : '';
}
function workTitle(message: string): string {
  const singleLine = message.replace(/\s+/g, ' ').trim();
  return singleLine.length > 28 ? `${singleLine.slice(0, 28)}…` : singleLine || '未命名工作';
}
function clientId(prefix: string): string {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}
function selectableExecutionMode(mode: AgentExecutionMode): AgentExecutionMode {
  return mode === 'full_trust' ? 'full_trust' : 'per_action';
}


function createdSessionSummary(
  raw: Record<string, unknown>,
  firstMessage: string,
  workspaceRoot: string,
  executionMode: AgentExecutionMode,
): SessionSummary {
  return {
    id: text(raw.id),
    title: text(raw.title) || workTitle(firstMessage),
    mode: 'coordinator',
    status: text(raw.status) || 'running',
    roleId: text(raw.roleId),
    roleVersion: text(raw.roleVersion),
    roleBookRevisionId: text(raw.roleBookRevisionId),
    updatedAtMs: typeof raw.updatedAtMs === 'number' ? raw.updatedAtMs : Date.now(),
    workspaceRoots: Array.isArray(raw.workspaceRoots)
      ? unrestrictedWorkspaceRoots(...(raw.workspaceRoots as string[]))
      : unrestrictedWorkspaceRoots(workspaceRoot),
    lastMessagePreview: firstMessage,
    executionMode,
  } as SessionSummary;
}
function createdRoomSummary(
  raw: Record<string, unknown>,
  firstMessage: string,
  fallbackWorkspaceRoots: string[],
  selectedPersonas: AgentPersonaV1[],
): RoomSummary {
  return {
    ...raw,
    id: text(raw.id),
    title: text(raw.title) || workTitle(firstMessage),
    status: text(raw.status) || 'active',
    description: text(raw.description) || firstMessage,
    routingPolicy: raw.routingPolicy ?? 'parallel',
    moderatorParticipantId: text(raw.moderatorParticipantId),
    updatedAtMs: typeof raw.updatedAtMs === 'number' ? raw.updatedAtMs : Date.now(),
    participants: Array.isArray(raw.participants)
      ? raw.participants
      : selectedPersonas.map((persona, ordinal) => ({ id: persona.roleId, ordinal })),
    workspaceRoots: Array.isArray(raw.workspaceRoots)
      ? raw.workspaceRoots.filter((value): value is string => typeof value === 'string')
      : fallbackWorkspaceRoots,
  } as RoomSummary;
}

function roomAttachmentReceipts(files: readonly PickedFile[], roomId: string): RoomAttachmentReceipt[] {
  return files.map((file) => ({
    mediaId: file.id,
    roomId,
    fileName: file.name || '附件',
    mimeType: file.mimeType,
    byteSize: file.byteSize,
    sha256: file.sha256 ?? '',
  }));
}

function projectName(roots: readonly string[] | undefined): string {
  const first = roots?.[0] ?? '';
  if (!first) return '未绑定项目';
  const parts = first.split('/').filter(Boolean);
  return parts.slice(-2).join('/') || first;
}
function relativeTime(atMs: number): string {
  const diff = Date.now() - atMs;
  const minutes = Math.max(0, Math.round(diff / 60_000));
  if (minutes < 1) return '刚刚';
  if (minutes < 60) return `${minutes} 分钟前`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} 小时前`;
  const days = Math.round(hours / 24);
  return `${days} 天前`;
}
function timeGreeting(): string {
  const now = new Date();
  const weekdays = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];
  const hour = now.getHours();
  const phase = hour < 5 ? '夜深了' : hour < 9 ? '早上好' : hour < 12 ? '上午好' : hour < 14 ? '中午好' : hour < 18 ? '下午好' : '晚上好';
  const hh = String(hour).padStart(2, '0');
  const mm = String(now.getMinutes()).padStart(2, '0');
  return `${weekdays[now.getDay()]} · ${hh}:${mm} · ${phase}`;
}
/** 与 startWork 的 Room 创建 payload 保持同一映射：0=协调，1=审阅，其余=专家。 */
function collaborationRoleLabel(index: number): string {
  return index === 0 ? '协调' : index === 1 ? '审阅' : '专家';
}
function thinkingLabel(level: string): string {
  if (!level || level === 'off') return '关闭';
  if (level === 'low') return '低';
  if (level === 'medium') return '中';
  if (level === 'high') return '高';
  if (level === 'max') return 'Max';
  return level;
}
function suggestedRoomParticipantCount(prompt: string, available: number): number {
  if (available <= 0) return 0;
  if (available === 1) return 1;
  const normalized = prompt.trim();
  let suggested = 2;
  if (/(?:并行|分别|前端|后端|测试|发布|审查|实现|调研|设计|、|以及)/u.test(normalized) || normalized.length >= 80) suggested = 4;
  if (normalized.length >= 240) suggested = 6;
  return Math.min(8, available, suggested);
}
function errorText(reason: unknown): string {
  if (reason instanceof Error && reason.message) return reason.message;
  if (typeof reason === 'string' && reason) return reason;
  return '操作没有完成，请重试。';
}
