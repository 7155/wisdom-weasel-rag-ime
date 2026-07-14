import { AlertCircle, PanelLeftClose, PanelLeftOpen } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useControlTransport } from '@/app/control-transport';
import { IconButton } from '@/components/primitives';
import { createAgentDeltaBatcher } from '@/contracts/batching';
import type { UiAgentEvent } from '@/contracts/ui-events';
import { AgentComposer } from './composer/AgentComposer';
import { previewAgentEvents, previewAgentSnapshot, previewModelCatalog, previewPersonas, previewSessions } from './preview-data';
import { SessionRail } from './sessions/SessionRail';
import { agentProjection, useAgentLiveStore } from './state/live-store';
import { AgentTimeline } from './timeline/AgentTimeline';
import {
  isModelCatalog,
  roleItems,
  sessionItems,
  type ComposerAttachment,
  type ModelCatalog,
  type SessionSummary,
  type ThinkingLevel,
} from './types';
import './agent.css';

export function AgentFeature() {
  const transport = useControlTransport();
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [personas, setPersonas] = useState(previewPersonas);
  const [selectedId, setSelectedId] = useState('');
  const [catalog, setCatalog] = useState<ModelCatalog>();
  const [draft, setDraft] = useState('');
  const [attachments, setAttachments] = useState<ComposerAttachment[]>([]);
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [railOpen, setRailOpen] = useState(() => !isMobileViewport());
  const [error, setError] = useState('');
  const ensure = useAgentLiveStore((state) => state.ensure);
  const projectionStatus = useAgentLiveStore((state) => state.projections[selectedId]?.status ?? 'idle');

  const loadSessions = useCallback(async (preferredId = '') => {
    setLoading(true);
    try {
      const [sessionResponse, roleResponse] = await Promise.all([
        transport.request({ pathId: 'agent.sessions.list', query: { limit: 100 } }),
        transport.request({ pathId: 'agent.roles.list' }),
      ]);
      const nextSessions = sessionItems(sessionResponse);
      const nextRoles = roleItems(roleResponse);
      const usableSessions = transport.kind === 'mock' && nextSessions.length === 0 ? previewSessions : nextSessions;
      setSessions(usableSessions);
      if (nextRoles.length) setPersonas(nextRoles);
      setSelectedId((current) => preferredId || current || usableSessions[0]?.id || '');
      setError('');
    } catch (loadError) {
      if (transport.kind === 'mock') {
        setSessions(previewSessions);
        setSelectedId((current) => preferredId || current || previewSessions[0]?.id || '');
      } else {
        setError(errorText(loadError));
      }
    } finally {
      setLoading(false);
    }
  }, [transport]);

  useEffect(() => { void loadSessions(); }, [loadSessions]);

  useEffect(() => {
    if (!selectedId) return;
    ensure(selectedId);
    let active = true;
    let unsubscribe = () => {};
    const batcher = createAgentDeltaBatcher((events) => {
      const needsSnapshot = useAgentLiveStore.getState().applyEvents(selectedId, events);
      if (needsSnapshot) void loadSnapshot();
    });
    async function loadSnapshot(): Promise<void> {
      try {
        const [snapshotResponse, modelResponse] = await Promise.all([
          transport.request({ pathId: 'agent.session.snapshot', params: { sessionId: selectedId } }),
          transport.request({ pathId: 'agent.session.models', params: { sessionId: selectedId } }),
        ]);
        if (!active) return;
        if (transport.kind === 'mock') {
          useAgentLiveStore.getState().hydrateSnapshot(selectedId, previewAgentSnapshot(selectedId));
          useAgentLiveStore.getState().applyEvents(selectedId, previewAgentEvents(selectedId));
          setCatalog(isModelCatalog(modelResponse) ? modelResponse : previewModelCatalog(selectedId));
        } else {
          useAgentLiveStore.getState().hydrate(selectedId, snapshotResponse);
          if (isModelCatalog(modelResponse)) setCatalog(modelResponse);
        }
        const cursor = agentProjection(selectedId).resumeToken;
        unsubscribe();
        unsubscribe = transport.subscribe<UiAgentEvent>(
          { pathId: 'agent.session.events', params: { sessionId: selectedId }, lastEventId: cursor },
          {
            next: (event) => batcher.push(event),
            error: (streamError) => active && setError(streamError.message),
            snapshotRequired: () => void loadSnapshot(),
          },
        );
      } catch (loadError) {
        if (active) setError(errorText(loadError));
      }
    }
    void loadSnapshot();
    return () => { active = false; batcher.clear(); unsubscribe(); };
  }, [ensure, selectedId, transport]);

  const session = sessions.find((item) => item.id === selectedId);
  const persona = personas.find((item) => item.roleId === session?.roleId) ?? personas[0];
  const busy = !['idle', 'ready', 'completed'].includes(projectionStatus);

  function selectSession(sessionId: string): void {
    setSelectedId(sessionId);
    if (isMobileViewport()) setRailOpen(false);
  }

  async function createSession(): Promise<void> {
    try {
      const response = await transport.request<Record<string, unknown>>({
        pathId: 'agent.sessions.create',
        body: { title: '新对话', mode: 'assistant', roleId: persona?.roleId ?? 'zhiyou-v1', roleVersion: persona?.version ?? '1', modelProfile: 'session-selected', toolProfileVersion: 'control-center-v1', workspaceRoots: [] },
      });
      const created = isRecord(response.session) ? response.session as unknown as SessionSummary : undefined;
      if (created?.id) await loadSessions(created.id);
      else if (transport.kind === 'mock') {
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
    const clientMessageId = `web-${crypto.randomUUID()}`;
    useAgentLiveStore.getState().appendOptimistic(session.id, { clientMessageId, text: value || '请查看附件。', attachments: attachments.map((item) => item.id), nowMs: Date.now() });
    setDraft(''); setAttachments([]); setSending(true); setError('');
    try {
      await transport.request({ pathId: 'agent.session.prompt', params: { sessionId: session.id }, body: { message: value || '请查看附件。', attachments: attachments.map((item) => item.id), clientMessageId } });
    } catch (requestError) {
      useAgentLiveStore.getState().failOptimistic(session.id, clientMessageId, errorText(requestError), Date.now());
      setDraft(value); setAttachments(attachments); setError(errorText(requestError));
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

  async function pickFiles(): Promise<void> {
    if (!transport.pickFiles) { setError('当前平台未开放受控文件选择。'); return; }
    try {
      const files = await transport.pickFiles({ accepts: ['image/*', 'text/*', 'application/pdf'], multiple: true, purpose: 'attachment' });
      setAttachments((current) => [...current, ...files.slice(0, 8 - current.length).map((file) => ({ ...file, source: 'picker' as const }))]);
    } catch (pickError) { setError(errorText(pickError)); }
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
    try {
      const selected = isRecord(catalog.selected) ? catalog.selected : {};
      if (selected.provider !== provider || selected.modelId !== modelId) await transport.request({ pathId: 'agent.session.model.select', params: { sessionId: session.id }, body: { provider, modelId } });
      if (catalog.thinkingLevel !== level) await transport.request({ pathId: 'agent.session.thinking.select', params: { sessionId: session.id }, body: { level } });
      setCatalog({ ...catalog, selected: { provider, modelId }, thinkingLevel: level });
    } catch (requestError) { setError(errorText(requestError)); }
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
          <IconButton className="agent-rail-toggle" label={railOpen ? '收起 Sessions' : '展开 Sessions'} icon={railOpen ? <PanelLeftClose size={17} /> : <PanelLeftOpen size={17} />} onClick={() => setRailOpen((value) => !value)} tooltip />
          <span><strong>{session?.title ?? 'Agent'}</strong><small>{session ? `${persona?.displayName ?? '智鼬'} · ${session.mode === 'coordinator' ? '运行协调' : '受控模式'}` : '选择一个 Session'}</small></span>
          {error ? <p role="alert"><AlertCircle size={14} />{error}</p> : null}
        </header>
        {selectedId ? <AgentTimeline sessionId={selectedId} persona={persona} onSuggestion={setDraft} onApprovalDecision={(id, decision, hash) => void decideApproval(id, decision, hash)} /> : null}
        <AgentComposer draft={draft} attachments={attachments} session={session} persona={persona} catalog={catalog} busy={busy} sending={sending} onDraftChange={setDraft} onAttachmentsChange={setAttachments} onPickFiles={() => void pickFiles()} onSend={() => void send()} onStop={() => void stop()} onModeChange={(mode) => void changeMode(mode)} onModelChange={(provider, modelId, level) => void changeModel(provider, modelId, level)} />
      </section>
    </main>
  );
}

function isRecord(value: unknown): value is Record<string, unknown> { return typeof value === 'object' && value !== null && !Array.isArray(value); }
function errorText(value: unknown): string { return value instanceof Error ? value.message : String(value); }
function isMobileViewport(): boolean { return window.matchMedia?.('(max-width: 760px)').matches === true; }
