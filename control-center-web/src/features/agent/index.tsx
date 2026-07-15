import { AlertCircle, PanelLeftClose, PanelLeftOpen } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useControlTransport } from '@/app/control-transport';
import { IconButton } from '@/components/primitives';
import { createAgentDeltaBatcher } from '@/contracts/batching';
import type { UiAgentEvent } from '@/contracts/ui-events';
import { AgentComposer } from './composer/AgentComposer';
import { previewAgentEvents, previewAgentSnapshot, previewModelCatalog, previewPersonas, previewSessions } from '@/features/agent/preview-data';
import { SessionRail } from './sessions/SessionRail';
import { agentProjection, useAgentLiveStore } from './state/live-store';
import { AgentTimeline } from './timeline/AgentTimeline';
import { publicAgentErrorText } from './public-error';
import {
  activeSessionId,
  commandItems,
  isModelCatalog,
  roleItems,
  sessionItems,
  toolItems,
  type AgentCommand,
  type ComposerAttachment,
  type ModelCatalog,
  type SessionSummary,
  type ThinkingLevel,
  type ToolManifest,
} from './types';
import './agent.css';

export function AgentFeature() {
  const transport = useControlTransport();
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedSessionId = searchParams.get('session')?.trim() ?? '';
  const requestedDraft = searchParams.get('draft')?.trim().slice(0, 4_000) ?? '';
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [personas, setPersonas] = useState(() => __CONTROL_PREVIEW__ && transport.kind === 'mock' ? previewPersonas : []);
  const [selectedId, setSelectedId] = useState('');
  const [catalog, setCatalog] = useState<ModelCatalog>();
  const [commands, setCommands] = useState<AgentCommand[]>([]);
  const [tools, setTools] = useState<ToolManifest[]>([]);
  const [toolCatalogStatus, setToolCatalogStatus] = useState<'loading' | 'ready' | 'failed'>('loading');
  const [draft, setDraft] = useState('');
  const [attachments, setAttachments] = useState<ComposerAttachment[]>([]);
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [modelChanging, setModelChanging] = useState(false);
  const [railOpen, setRailOpen] = useState(() => !isMobileViewport());
  const [error, setError] = useState('');
  const selectedIdRef = useRef(selectedId);
  selectedIdRef.current = selectedId;
  const ensure = useAgentLiveStore((state) => state.ensure);
  const projectionStatus = useAgentLiveStore((state) => state.projections[selectedId]?.status ?? 'idle');

  const loadSessions = useCallback(async (preferredId = '') => {
    setLoading(true);
    setToolCatalogStatus('loading');
    try {
      const [sessionResponse, roleResponse, toolResult] = await Promise.all([
        transport.request({ pathId: 'agent.sessions.list', query: { limit: 100 } }),
        transport.request({ pathId: 'agent.roles.list' }),
        transport.request({ pathId: 'agent.tools.list' }).then(
          (value) => ({ ok: true as const, value }),
          (reason: unknown) => ({ ok: false as const, reason }),
        ),
      ]);
      const nextSessions = sessionItems(sessionResponse);
      const nextRoles = roleItems(roleResponse);
      const usableSessions = __CONTROL_PREVIEW__ && transport.kind === 'mock' && nextSessions.length === 0 ? previewSessions : nextSessions;
      setSessions(usableSessions);
      if (nextRoles.length) setPersonas(nextRoles);
      if (toolResult.ok) {
        setTools(toolItems(toolResult.value));
        setToolCatalogStatus('ready');
      } else {
        setTools([]);
        setToolCatalogStatus('failed');
      }
      const preferredSessionId = usableSessions.some((item) => item.id === preferredId) ? preferredId : '';
      const backendActiveId = activeSessionId(sessionResponse);
      const activeId = usableSessions.some((item) => item.id === backendActiveId) ? backendActiveId : '';
      const meaningful = (item: SessionSummary): boolean => (
        (item.messageCount ?? 0) > 0 || Boolean(item.lastMessagePreview?.trim())
      );
      const meaningfulId = usableSessions.find(meaningful)?.id ?? '';
      const activeMeaningfulId = usableSessions.find((item) => item.id === activeId && meaningful(item))?.id ?? '';
      setSelectedId((current) => {
        const currentId = usableSessions.some((item) => item.id === current) ? current : '';
        return preferredSessionId || currentId || activeMeaningfulId || meaningfulId || activeId || usableSessions[0]?.id || '';
      });
      setError('');
    } catch (loadError) {
      if (__CONTROL_PREVIEW__ && transport.kind === 'mock') {
        setSessions(previewSessions);
        const preferredSessionId = previewSessions.some((item) => item.id === preferredId) ? preferredId : '';
        setSelectedId((current) => preferredSessionId || current || previewSessions[0]?.id || '');
      } else {
        setError(errorText(loadError));
      }
      setToolCatalogStatus('failed');
    } finally {
      setLoading(false);
    }
  }, [transport]);

  useEffect(() => { void loadSessions(requestedSessionId); }, [loadSessions, requestedSessionId]);
  useEffect(() => {
    setAttachments([]);
    setCatalog(undefined);
    setCommands([]);
  }, [selectedId]);
  useEffect(() => {
    if (!requestedDraft) return;
    setDraft((current) => current.trim() ? current : requestedDraft);
    const next = new URLSearchParams(searchParams);
    next.delete('draft');
    setSearchParams(next, { replace: true });
  }, [requestedDraft, searchParams, setSearchParams]);

  useEffect(() => {
    if (!selectedId) return;
    ensure(selectedId);
    let active = true;
    let unsubscribe = () => {};
    const batcher = createAgentDeltaBatcher((events) => {
      const needsSnapshot = useAgentLiveStore.getState().applyEvents(selectedId, events);
      if (needsSnapshot) void loadSnapshot();
    });
    async function loadSnapshot(): Promise<boolean> {
      try {
        const snapshotResponse = await transport.request({
          pathId: 'agent.session.snapshot',
          params: { sessionId: selectedId },
        });
        if (!active) return false;
        if (__CONTROL_PREVIEW__ && transport.kind === 'mock') {
          useAgentLiveStore.getState().hydrateSnapshot(selectedId, previewAgentSnapshot(selectedId));
          useAgentLiveStore.getState().applyEvents(selectedId, previewAgentEvents(selectedId));
        } else {
          useAgentLiveStore.getState().hydrate(selectedId, snapshotResponse);
        }
        const cursor = agentProjection(selectedId).resumeToken;
        unsubscribe();
        unsubscribe = transport.subscribe<UiAgentEvent>(
          { pathId: 'agent.session.events', params: { sessionId: selectedId }, lastEventId: cursor },
          {
            next: (event) => batcher.push(event),
            error: (streamError) => active && setError(errorText(streamError)),
            snapshotRequired: () => void loadSnapshot(),
          },
        );
        return true;
      } catch (loadError) {
        if (active) setError(`对话记录暂时无法恢复。${errorText(loadError)}`);
        return false;
      }
    }
    async function loadSessionCatalogs(): Promise<void> {
      const [modelResult, commandResult] = await Promise.allSettled([
        transport.request({ pathId: 'agent.session.models', params: { sessionId: selectedId } }),
        transport.request({ pathId: 'agent.session.commands', params: { sessionId: selectedId } }),
      ]);
      if (!active) return;
      const notices: string[] = [];
      if (modelResult.status === 'fulfilled' && isModelCatalog(modelResult.value)) {
        setCatalog(modelResult.value);
      } else if (__CONTROL_PREVIEW__ && transport.kind === 'mock') {
        setCatalog(previewModelCatalog(selectedId));
      } else {
        setCatalog(undefined);
        notices.push('模型目录暂时不可用，对话记录仍可查看。');
      }
      if (commandResult.status === 'fulfilled') {
        setCommands(commandItems(commandResult.value));
      } else {
        setCommands([]);
        notices.push('Pi 命令暂时不可用，仍可直接发送消息。');
      }
      if (notices.length) setError(notices.join(' '));
    }
    void (async () => {
      if (await loadSnapshot()) await loadSessionCatalogs();
    })();
    return () => { active = false; batcher.clear(); unsubscribe(); };
  }, [ensure, selectedId, transport]);

  const session = sessions.find((item) => item.id === selectedId);
  const defaultPersona = personas.find((item) => item.defaults.modelPolicy.toLowerCase().includes('luna')) ?? personas[0];
  const persona = personas.find((item) => item.roleId === session?.roleId) ?? defaultPersona;
  const busy = !['idle', 'ready', 'completed'].includes(projectionStatus);
  const imageSupport = useMemo(() => selectedModelImageSupport(catalog), [catalog]);

  function selectSession(sessionId: string): void {
    setSelectedId(sessionId);
    if (isMobileViewport()) setRailOpen(false);
  }

  async function createSession(): Promise<void> {
    const creationPersona = defaultPersona;
    if (!creationPersona) {
      setError('角色目录尚未加载，暂时不能创建对话。');
      return;
    }
    try {
      const response = await transport.request<Record<string, unknown>>({
        pathId: 'agent.sessions.create',
        body: { title: '新对话', mode: 'assistant', roleId: creationPersona.roleId, roleVersion: creationPersona.version, toolProfileVersion: creationPersona.defaults.toolProfileVersion, workspaceRoots: [] },
      });
      const created = isRecord(response.session) ? response.session as unknown as SessionSummary : undefined;
      if (created?.id) await loadSessions(created.id);
      else if (__CONTROL_PREVIEW__ && transport.kind === 'mock') {
        const mockSession = { ...previewSessions[0], id: `session-${Date.now()}`, title: '新对话', updatedAtMs: Date.now(), messageCount: 0, lastMessagePreview: '' };
        setSessions((current) => [mockSession, ...current]);
        setSelectedId(mockSession.id);
      }
    } catch (requestError) { setError(errorText(requestError)); }
  }

  async function send(): Promise<void> {
    if (!session || sending) return;
    const value = draft.trim();
    if (value === '/new') { setDraft(''); await createSession(); return; }
    if (value.startsWith('/compact')) {
      setSending(true);
      try { await transport.request({ pathId: 'agent.session.compact', params: { sessionId: session.id }, body: { instructions: value.slice('/compact'.length).trim() } }); setDraft(''); }
      catch (requestError) { setError(errorText(requestError)); }
      finally { setSending(false); }
      return;
    }
    if (value === '/stop') { setDraft(''); await stop(); return; }
    if (!value && attachments.length === 0) return;
    if (attachments.length && imageSupport !== 'supported') {
      setError(imageSupport === 'unsupported'
        ? '当前模型不支持图片，请移除图片或切换到支持图片的模型。'
        : '尚未确认当前模型的图片能力，请稍后再发送。');
      return;
    }
    const clientMessageId = `web-${crypto.randomUUID()}`;
    useAgentLiveStore.getState().appendOptimistic(session.id, { clientMessageId, text: value || '请查看附件。', attachments: attachments.map((item) => item.id), nowMs: Date.now() });
    setDraft(''); setAttachments([]); setSending(true); setError('');
    try {
      await transport.request({ pathId: 'agent.session.prompt', params: { sessionId: session.id }, body: { message: value || '请查看附件。', attachments: attachments.map((item) => item.id), clientMessageId } });
    } catch (requestError) {
      const failure = publicAgentErrorText(requestError);
      const projection = agentProjection(session.id);
      const hasOptimisticTurn = Boolean(projection.optimisticByClientMessageId[clientMessageId]);
      useAgentLiveStore.getState().failOptimistic(session.id, clientMessageId, failure, Date.now());
      setDraft(value); setAttachments(attachments); setError(hasOptimisticTurn ? '' : failure);
    } finally { setSending(false); }
  }

  async function stop(): Promise<void> {
    if (!session) return;
    try {
      await transport.request({ pathId: 'agent.session.abort', params: { sessionId: session.id } });
      const projection = agentProjection(session.id);
      const turnId = [...projection.turnOrder].reverse().find((id) => ['running', 'queued', 'waiting'].includes(projection.turnsById[id]?.status ?? ''));
      if (turnId) useAgentLiveStore.getState().abortTurn(session.id, turnId, Date.now());
    } catch (requestError) { setError(errorText(requestError)); }
  }

  async function pasteImages(files?: File[]): Promise<void> {
    if (!session) { setError('请先选择一个对话。'); return; }
    if (imageSupport !== 'supported') {
      setError(imageSupport === 'unsupported' ? '当前模型不支持图片，请先切换模型。' : '正在确认当前模型的图片能力。');
      return;
    }
    if (!transport.pasteImages) { setError('当前平台暂不支持从剪贴板导入图片。'); return; }
    const remaining = 8 - attachments.length;
    if (remaining <= 0) { setError('单次消息最多支持 8 张图片。'); return; }
    if (files && files.length > remaining) { setError(`当前消息还可以粘贴 ${remaining} 张图片。`); return; }
    const unsupported = files?.find((file) => !PASTED_IMAGE_MIME_TYPES.has(file.type.toLowerCase()));
    if (unsupported) { setError(`不支持粘贴 ${unsupported.type || unsupported.name}；仅支持 PNG、JPEG、GIF 和 WebP。`); return; }
    const oversized = files?.find((file) => file.size <= 0 || file.size > MAX_AGENT_IMAGE_BYTES);
    if (oversized) { setError(`${oversized.name || '图片'} 必须小于 20 MiB 且不能为空。`); return; }
    try {
      const maxFiles = files?.length || remaining;
      const imported = await transport.pasteImages({
        sessionId: session.id,
        ...(files?.length ? { files } : {}),
        maxFiles,
      });
      if (selectedIdRef.current !== session.id) {
        setError('对话已切换，刚粘贴的图片未加入当前消息。');
        return;
      }
      if (!imported.length) {
        setError('剪贴板里没有可导入的 PNG、JPEG、GIF 或 WebP 图片。');
        return;
      }
      mergeAttachments(imported, 'clipboard');
      setError('');
    } catch (pasteError) { setError(errorText(pasteError)); }
  }

  async function pickAttachments(): Promise<void> {
    if (!session) { setError('请先选择一个对话。'); return; }
    if (imageSupport !== 'supported') {
      setError(imageSupport === 'unsupported' ? '当前模型不支持图片，请先切换模型。' : '正在确认当前模型的图片能力。');
      return;
    }
    if (!transport.pickFiles) { setError('当前平台暂不支持选择图片。'); return; }
    const remaining = 8 - attachments.length;
    if (remaining <= 0) { setError('单次消息最多支持 8 张图片。'); return; }
    try {
      const imported = await transport.pickFiles({
        accepts: [...PASTED_IMAGE_MIME_TYPES],
        multiple: true,
        purpose: 'attachment',
        sessionId: session.id,
        maxFiles: remaining,
      });
      if (selectedIdRef.current !== session.id) {
        setError('对话已切换，刚选择的图片未加入当前消息。');
        return;
      }
      if (!imported.length) return;
      mergeAttachments(imported, 'picker');
      setError('');
    } catch (pickError) { setError(errorText(pickError)); }
  }

  function mergeAttachments(files: Omit<ComposerAttachment, 'source'>[], source: ComposerAttachment['source']): void {
    setAttachments((current) => {
      const byId = new Map(current.map((item) => [item.id, item]));
      for (const file of files) byId.set(file.id, { ...file, source });
      return [...byId.values()].slice(0, 8);
    });
  }

  function chooseTool(tool: ToolManifest): void {
    const intent = `请使用“${tool.displayName}”`;
    setDraft((current) => current.trim() ? `${current.trimEnd()}\n${intent}：` : `${intent}：`);
  }

  async function changeMode(mode: 'assistant' | 'coordinator'): Promise<void> {
    if (!session || mode === session.mode) return;
    try {
      await transport.request({ pathId: 'agent.session.mode.update', params: { sessionId: session.id }, body: { mode, workspaceRoots: session.workspaceRoots } });
      setSessions((current) => current.map((item) => item.id === session.id ? { ...item, mode } : item));
    } catch (requestError) { setError(errorText(requestError)); }
  }

  async function changeModel(provider: string, modelId: string, level: ThinkingLevel): Promise<void> {
    if (!session || !catalog) return;
    const targetModel = catalog.providers.find((item) => item.id === provider)?.models.find((item) => item.id === modelId);
    if (!targetModel) { setError('Pi 模型目录中没有这个模型。'); return; }
    if (attachments.length && !targetModel.supportsImages) {
      setError('当前消息含有图片，请先移除图片再切换到不支持图片的模型。');
      return;
    }
    const selected = isRecord(catalog.selected) ? catalog.selected : {};
    const selectedModelId = typeof selected.id === 'string' && selected.id
      ? selected.id
      : selected.modelId;
    const modelChanged = selected.provider !== provider || selectedModelId !== modelId;
    const thinkingChanged = catalog.thinkingLevel !== level;
    if (!modelChanged && !thinkingChanged) return;
    setModelChanging(true);
    try {
      if (modelChanged) await transport.request({ pathId: 'agent.session.model.select', params: { sessionId: session.id }, body: { provider, modelId } });
      if (modelChanged || thinkingChanged) await transport.request({ pathId: 'agent.session.thinking.select', params: { sessionId: session.id }, body: { level } });
      const refreshed = await transport.request({ pathId: 'agent.session.models', params: { sessionId: session.id } });
      if (!isModelCatalog(refreshed)) throw new Error('Pi 没有返回有效的模型目录。');
      setCatalog(refreshed);
      setError('');
    } catch (requestError) {
      setError(errorText(requestError));
      try {
        const refreshed = await transport.request({ pathId: 'agent.session.models', params: { sessionId: session.id } });
        if (isModelCatalog(refreshed)) setCatalog(refreshed);
      } catch {
        // Keep the last confirmed Pi catalog when recovery also fails.
      }
    } finally {
      setModelChanging(false);
    }
  }

  async function decideApproval(approvalId: string, decision: 'approved' | 'rejected', payloadSha256: string): Promise<void> {
    try { await transport.request({ pathId: 'agent.approval.decide', params: { approvalId }, body: { decision, payloadSha256 } }); }
    catch (requestError) { setError(errorText(requestError)); }
  }

  return (
    <main className="agent-feature" data-route-id="agent" data-rail-open={railOpen}>
      <SessionRail sessions={sessions} selectedId={selectedId} loading={loading} onSelect={selectSession} onCreate={() => void createSession()} />
      <section className="agent-conversation">
        <header className="agent-conversation__header">
          <IconButton className="agent-rail-toggle" label={railOpen ? '收起对话列表' : '展开对话列表'} icon={railOpen ? <PanelLeftClose size={17} /> : <PanelLeftOpen size={17} />} onClick={() => setRailOpen((value) => !value)} tooltip />
          <span><strong>{session?.title ?? '智鼬'}</strong><small>{session ? `${persona?.displayName ?? '智鼬'} · ${session.mode === 'coordinator' ? '运行协调' : '受控模式'}` : '选择一个对话'}</small></span>
          {error ? <p role="alert"><AlertCircle size={14} />{error}</p> : null}
        </header>
        {selectedId ? <AgentTimeline sessionId={selectedId} persona={persona} onSuggestion={setDraft} onApprovalDecision={(id, decision, hash) => void decideApproval(id, decision, hash)} /> : null}
        <AgentComposer draft={draft} attachments={attachments} session={session} persona={persona} catalog={catalog} commands={commands} tools={tools} toolCatalogStatus={toolCatalogStatus} busy={busy} sending={sending || modelChanging} imageSupport={imageSupport} onDraftChange={setDraft} onAttachmentsChange={setAttachments} onPickAttachments={() => void pickAttachments()} onPasteFromClipboard={() => void pasteImages()} onPasteImages={(files) => void pasteImages(files)} onToolSelect={chooseTool} onSend={() => void send()} onStop={() => void stop()} onModeChange={(mode) => void changeMode(mode)} onModelChange={(provider, modelId, level) => void changeModel(provider, modelId, level)} />
      </section>
    </main>
  );
}

function isRecord(value: unknown): value is Record<string, unknown> { return typeof value === 'object' && value !== null && !Array.isArray(value); }
function errorText(value: unknown): string {
  const message = value instanceof Error ? value.message : String(value);
  if (/invalid route parameter:\s*limit/i.test(message)) return '对话列表暂时无法加载，请刷新后重试。';
  return publicAgentErrorText(value, '操作未完成，请刷新状态后重试。');
}
function isMobileViewport(): boolean { return window.matchMedia?.('(max-width: 760px)').matches === true; }

const PASTED_IMAGE_MIME_TYPES = new Set(['image/png', 'image/jpeg', 'image/gif', 'image/webp']);
const MAX_AGENT_IMAGE_BYTES = 20 * 1024 * 1024;

function selectedModelImageSupport(catalog?: ModelCatalog): 'supported' | 'unsupported' | 'unknown' {
  if (!catalog) return 'unknown';
  const selected = isRecord(catalog.selected) ? catalog.selected : {};
  const providerId = typeof selected.provider === 'string' ? selected.provider : '';
  const modelId = typeof selected.id === 'string' && selected.id
    ? selected.id
    : typeof selected.modelId === 'string'
      ? selected.modelId
      : '';
  const model = catalog.providers.find((provider) => provider.id === providerId)?.models.find((item) => item.id === modelId);
  if (!model && typeof selected.supportsImages === 'boolean') {
    return selected.supportsImages ? 'supported' : 'unsupported';
  }
  if (!model) return 'unknown';
  return model.supportsImages ? 'supported' : 'unsupported';
}
