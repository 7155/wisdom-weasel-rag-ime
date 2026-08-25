import {
  Archive,
  ArchiveRestore,
  LoaderCircle,
  MoreHorizontal,
  PanelLeft,
  Plus,
  Search,
  Trash2,
} from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { useControlTransport } from '@/app/control-transport';
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Menu,
  MenuCheckboxItem,
  MenuContent,
  MenuItem,
  MenuSeparator,
  MenuTrigger,
} from '@/components/primitives';
import type { AgentPersonaV1 } from '@/contracts/generated/agent-persona.v1';
import { parsePiModelCatalogOptions, type PiModelOption } from '@/features/agent/model-catalog-options';
import { roleItems, sessionItems, type SessionSummary } from '@/features/agent/types';
import { useAgentLiveStore } from '@/features/agent/state/live-store';
import { evidenceEchoFocusFromRoute } from '@/features/evidence-echo/evidence-echo';
import type { RoomSummary } from '@/features/rooms/room-types';
import type { PawOsWindowTarget } from '@/features/paw-os/model/desktop';
import { usePawOsAppSurface, usePawOsDesktop } from '@/features/paw-os/surface-context';
import { PawSessionWorkspace } from './PawSessionWorkspace';
import { PawRoomWorkspace } from './PawRoomWorkspace';
import { PawAgentHome } from './PawAgentHome';
import { PawWindowLeadingPortal, usePawWindowLeadingChromeTarget } from '../shell/PawWindowChrome';

type Selection =
  | { kind: 'new'; draft?: string }
  | { kind: 'session'; id: string; draft?: string }
  | { kind: 'room'; id: string; draft?: string; error?: string };

export function PawAgentApp({
  initialRoute = '',
  target,
}: {
  initialRoute?: string;
  target?: PawOsWindowTarget;
}) {
  const transport = useControlTransport();
  const desktop = usePawOsDesktop();
  const surface = usePawOsAppSurface();
  /* The rail toggle reveals a leading-edge aside, so it docks in the leading
     titlebar slot and falls back inline only when that slot is absent. */
  const windowChromeTarget = usePawWindowLeadingChromeTarget();
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [rooms, setRooms] = useState<RoomSummary[]>([]);
  const [personas, setPersonas] = useState<AgentPersonaV1[]>([]);
  const [models, setModels] = useState<PiModelOption[]>([]);
  const [defaultModel, setDefaultModel] = useState('');
  const [selection, setSelection] = useState<Selection>(() => initialSelection(
    initialRoute,
    target?.kind,
    target?.id,
    target?.kind === 'participant' ? target.roomId : undefined,
  ));
  const [railOpen, setRailOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [actionError, setActionError] = useState('');
  const [showArchived, setShowArchived] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<SessionSummary>();
  const [deleting, setDeleting] = useState(false);
  const [catalogRevision, setCatalogRevision] = useState(0);
  const railToggleRef = useRef<HTMLButtonElement>(null);
  const optimisticSessionsRef = useRef<Record<string, SessionSummary>>({});
  const optimisticRoomsRef = useRef<Record<string, RoomSummary>>({});
  const targetKind = target?.kind;
  const targetId = target?.id;
  const targetRoomId = target?.kind === 'participant' ? target.roomId : undefined;
  /* 反向证据链只对它自己指名的那段 Session 生效；在同一扇窗里换一段
     Session 之后，落点就过期了，不该继续劫持视图。 */
  const evidenceFocus = useMemo(() => {
    const focus = evidenceEchoFocusFromRoute(initialRoute);
    if (!focus) return '';
    const routeSessionId = new URLSearchParams(initialRoute.split('?', 2)[1] ?? '').get('session') ?? '';
    return routeSessionId && selection.kind === 'session' && selection.id === routeSessionId ? focus.nodeId : '';
  }, [initialRoute, selection]);

  useEffect(() => {
    setSelection(initialSelection(initialRoute, targetKind, targetId, targetRoomId));
    setRailOpen(false);
  }, [initialRoute, targetId, targetKind, targetRoomId]);

  const loadCatalog = useCallback(async () => {
    setLoading(true);
    setLoadError('');
    const [sessionResult, roomResult, roleResult, modelResult] = await Promise.allSettled([
      transport.request({ pathId: 'agent.sessions.list', query: { limit: 100, includeArchived: showArchived } }),
      transport.request({ pathId: 'agent.rooms.list', query: { limit: 100 } }),
      transport.request({ pathId: 'agent.roles.list' }),
      transport.request({ pathId: 'agent.role.models' }),
    ]);
    if (sessionResult.status === 'fulfilled') {
      const listed = sessionItems(sessionResult.value).filter((item) => !item.roomParticipant);
      const listedIds = new Set(listed.map((item) => item.id));
      for (const id of Object.keys(optimisticSessionsRef.current)) {
        if (listedIds.has(id)) delete optimisticSessionsRef.current[id];
      }
      setSessions([
        ...Object.values(optimisticSessionsRef.current),
        ...listed.filter((item) => !optimisticSessionsRef.current[item.id]),
      ]);
    }
    if (roomResult.status === 'fulfilled') {
      const listed = roomItems(roomResult.value);
      const listedIds = new Set(listed.map((item) => item.id));
      for (const id of Object.keys(optimisticRoomsRef.current)) {
        if (listedIds.has(id)) delete optimisticRoomsRef.current[id];
      }
      setRooms([
        ...Object.values(optimisticRoomsRef.current),
        ...listed.filter((item) => !optimisticRoomsRef.current[item.id]),
      ]);
    }
    if (roleResult.status === 'fulfilled') setPersonas(roleItems(roleResult.value));
    if (modelResult.status === 'fulfilled') {
      const catalog = parsePiModelCatalogOptions(modelResult.value);
      setModels(catalog.models);
      setDefaultModel(catalog.selectedReference);
    }
    const failures = [sessionResult, roomResult, roleResult, modelResult]
      .filter((result) => result.status === 'rejected').length;
    if (failures) setLoadError(failures === 4 ? 'Agent 工作记录暂时无法读取。' : '部分 Agent 目录暂时不可用。');
    setLoading(false);
  }, [showArchived, transport]);

  useEffect(() => { void loadCatalog(); }, [catalogRevision, loadCatalog]);

  useEffect(() => {
    if (!railOpen) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      event.preventDefault();
      setRailOpen(false);
      railToggleRef.current?.focus();
    };
    window.addEventListener('keydown', closeOnEscape);
    return () => window.removeEventListener('keydown', closeOnEscape);
  }, [railOpen]);

  const normalizedQuery = query.trim().toLocaleLowerCase();
  const visibleSessions = sessions.filter((item) => searchable(item.title, item.lastMessagePreview, normalizedQuery));
  const visibleRooms = rooms.filter((item) => searchable(item.title, item.description, normalizedQuery));
  const projectRoots = useMemo(() => uniquePaths([
    ...sessions.flatMap((item) => item.workspaceRoots ?? []),
    ...rooms.flatMap((item) => item.workspaceRoots ?? []),
  ]), [rooms, sessions]);
  const selectedSession = selection.kind === 'session'
    ? sessions.find((item) => item.id === selection.id)
    : undefined;
  const selectedRoom = selection.kind === 'room'
    ? rooms.find((item) => item.id === selection.id)
    : undefined;

  useEffect(() => {
    if (!surface?.windowId || !desktop?.bindAgentMain) return;
    if (selection.kind === 'new') {
      desktop.bindAgentMain(surface.windowId);
      return;
    }
    if (selection.kind === 'session' && selectedSession) {
      desktop.bindAgentMain(surface.windowId, {
        kind: 'session',
        id: selectedSession.id,
        title: selectedSession.title,
      });
      return;
    }
    if (selection.kind === 'room' && selectedRoom) {
      desktop.bindAgentMain(surface.windowId, {
        kind: 'room',
        id: selectedRoom.id,
        title: selectedRoom.title,
        subtitle: selectedRoom.description,
      });
    }
  }, [desktop, selectedRoom, selectedSession, selection.kind, surface?.windowId]);

  async function archiveSession(session: SessionSummary): Promise<void> {
    const archived = session.status === 'archived';
    setActionError('');
    try {
      await transport.request({
        pathId: 'agent.session.archive',
        params: { sessionId: session.id },
        body: { archived: !archived },
      });
      if (!archived && !showArchived) {
        setSessions((current) => current.filter((item) => item.id !== session.id));
        if (selection.kind === 'session' && selection.id === session.id) setSelection({ kind: 'new' });
      } else {
        setSessions((current) => current.map((item) => item.id === session.id
          ? { ...item, status: archived ? 'idle' : 'archived', updatedAtMs: Date.now() }
          : item));
      }
      setCatalogRevision((value) => value + 1);
    } catch (reason) {
      setActionError(errorText(reason));
    }
  }

  async function deleteSession(): Promise<void> {
    if (!deleteTarget || deleting) return;
    setDeleting(true);
    setActionError('');
    try {
      await transport.request({ pathId: 'agent.session.delete', params: { sessionId: deleteTarget.id } });
      useAgentLiveStore.getState().clear(deleteTarget.id);
      delete optimisticSessionsRef.current[deleteTarget.id];
      setSessions((current) => current.filter((item) => item.id !== deleteTarget.id));
      if (selection.kind === 'session' && selection.id === deleteTarget.id) setSelection({ kind: 'new' });
      setDeleteTarget(undefined);
    } catch (reason) {
      setActionError(errorText(reason));
    } finally {
      setDeleting(false);
    }
  }

  const railToggle = <button aria-controls="paw-agent-work-records" aria-expanded={railOpen} aria-label={railOpen ? '收起工作记录' : '打开工作记录'} className="paw-agent-rail-toggle" onClick={() => setRailOpen((open) => !open)} ref={railToggleRef} type="button"><PanelLeft size={16} /></button>;
  return (
    <main className="paw-agent-app" data-rail-open={railOpen || undefined} data-selection={selection.kind}>
      {windowChromeTarget ? <PawWindowLeadingPortal>{railToggle}</PawWindowLeadingPortal> : null}
      <aside aria-label="Agent 工作记录" className="paw-agent-rail" id="paw-agent-work-records">
        <header>
          <span><strong>工作记录</strong></span>
          <div className="paw-agent-rail__actions">
            <button aria-label="新建工作" onClick={() => { setSelection({ kind: 'new' }); setRailOpen(false); }} type="button"><Plus size={17} /></button>
            <Menu>
              <MenuTrigger asChild><button aria-label="工作记录选项" type="button"><MoreHorizontal size={17} /></button></MenuTrigger>
              <MenuContent align="end">
                <MenuCheckboxItem checked={showArchived} onCheckedChange={(checked) => setShowArchived(checked === true)}>显示已归档 Session</MenuCheckboxItem>
              </MenuContent>
            </Menu>
          </div>
        </header>
        <label className="paw-agent-search">
          <Search size={14} />
          <input aria-label="搜索 Session 与 Room" onChange={(event) => setQuery(event.target.value)} placeholder="搜索" value={query} />
        </label>
        <div className="paw-agent-recents" aria-busy={loading || undefined}>
          {loading && !sessions.length && !rooms.length ? <RailNotice icon={<LoaderCircle className="ui-spin" size={15} />} text="正在读取工作记录" /> : null}
          {loadError ? <RailNotice action={() => setCatalogRevision((value) => value + 1)} text={loadError} /> : null}
          {actionError ? <RailNotice action={() => setActionError('')} text={actionError} /> : null}
          {visibleSessions.length ? <WorkGroup label="Session">
            {visibleSessions.map((session) => (
              <WorkRow
                active={selection.kind === 'session' && selection.id === session.id}
                key={session.id}
                meta={sessionMeta(session)}
                onClick={() => { setSelection({ kind: 'session', id: session.id }); setRailOpen(false); }}
                title={session.title}
                trailing={<SessionActions onArchive={() => void archiveSession(session)} onDelete={() => { setActionError(''); setDeleteTarget(session); }} session={session} />}
              />
            ))}
          </WorkGroup> : null}
          {visibleRooms.length ? <WorkGroup label="Room">
            {visibleRooms.map((room) => (
              <WorkRow
                active={selection.kind === 'room' && selection.id === room.id}
                key={room.id}
                meta={`${room.participants.length} 位伙伴 · ${relativeTime(room.updatedAtMs)}`}
                onClick={() => { setSelection({ kind: 'room', id: room.id }); setRailOpen(false); }}
                title={room.title}
              />
            ))}
          </WorkGroup> : null}
          {!loading && !loadError && !visibleSessions.length && !visibleRooms.length ? <RailNotice text={normalizedQuery ? '没有匹配的工作记录' : '还没有工作记录'} /> : null}
        </div>
      </aside>
      {windowChromeTarget ? null : railToggle}
      {railOpen ? <button aria-label="关闭工作记录" className="paw-agent-rail-backdrop" onClick={() => { setRailOpen(false); railToggleRef.current?.focus(); }} type="button" /> : null}
      <section className="paw-agent-stage">
        {selection.kind === 'new' ? (
          <PawAgentHome
            catalogError={loadError}
            catalogLoading={loading}
            defaultModel={defaultModel}
            initialDraft={selection.draft}
            key={`new:${selection.draft ?? ''}`}
            models={models}
            onOpenRoom={(id) => setSelection({ kind: 'room', id })}
            onOpenSession={(id) => setSelection({ kind: 'session', id })}
            onReloadCatalog={() => setCatalogRevision((value) => value + 1)}
            personas={personas}
            projectRoots={projectRoots}
            rooms={visibleRooms}
            sessions={visibleSessions}
            onCreated={(next, created, createdRoom) => {
              if (created) {
                optimisticSessionsRef.current[created.id] = created;
                setSessions((current) => [created, ...current.filter((item) => item.id !== created.id)]);
              }
              if (createdRoom) {
                optimisticRoomsRef.current[createdRoom.id] = createdRoom;
                setRooms((current) => [createdRoom, ...current.filter((item) => item.id !== createdRoom.id)]);
              }
              setSelection(next);
              setCatalogRevision((value) => value + 1);
            }}
          />
        ) : selection.kind === 'session' ? (
          <PawSessionWorkspace
            key={`session:${selection.id}`}
            initialDraft={selection.draft}
            persona={personas.find((item) => item.roleId === sessions.find((session) => session.id === selection.id)?.roleId)}
            record={sessions.find((item) => item.id === selection.id)}
            recordId={selection.id}
            traceFocusNodeId={evidenceFocus}
            onNewWork={() => setSelection({ kind: 'new' })}
            onSessionCreated={(created, draft) => {
              optimisticSessionsRef.current[created.id] = created;
              setSessions((current) => [created, ...current.filter((item) => item.id !== created.id)]);
              setSelection({ kind: 'session', id: created.id, ...(draft ? { draft } : {}) });
            }}
            onSessionUpdated={(updated) => {
              if (optimisticSessionsRef.current[updated.id]) optimisticSessionsRef.current[updated.id] = updated;
              setSessions((current) => current.map((item) => item.id === updated.id ? updated : item));
            }}
          />
        ) : selection.kind === 'room' ? (
          <PawRoomWorkspace
            initialDraft={selection.draft}
            initialError={selection.error}
            key={`room:${selection.id}`}
            personas={personas}
            record={rooms.find((item) => item.id === selection.id)}
            recordId={selection.id}
            onRoomUpdated={(updated) => {
              if (optimisticRoomsRef.current[updated.id]) optimisticRoomsRef.current[updated.id] = updated;
              setRooms((current) => current.map((item) => item.id === updated.id ? updated : item));
            }}
          />
        ) : null}
      </section>
      <Dialog open={Boolean(deleteTarget)} onOpenChange={(open) => {
        if (!open && !deleting) {
          setActionError('');
          setDeleteTarget(undefined);
        }
      }}>
        <DialogContent className="paw-agent-delete-dialog">
          <DialogHeader>
            <DialogTitle>删除“{deleteTarget?.title ?? 'Session'}”</DialogTitle>
            <DialogDescription>将删除这段 Session 及其本地附件。暂时不想看到它，可以先归档。</DialogDescription>
          </DialogHeader>
          {actionError ? <p className="paw-agent-delete-dialog__error" role="alert">{actionError}</p> : null}
          <DialogFooter>
            <Button disabled={deleting} onClick={() => setDeleteTarget(undefined)} variant="quiet">取消</Button>
            <Button leadingIcon={<Trash2 size={15} />} loading={deleting} onClick={() => void deleteSession()} variant="danger">删除</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </main>
  );
}

function WorkGroup({ children, label }: { children: ReactNode; label: string }) {
  return <section className="paw-agent-group"><header>{label}</header>{children}</section>;
}

function WorkRow({ active, meta, onClick, title, trailing }: { active: boolean; meta: string; onClick: () => void; title: string; trailing?: ReactNode }) {
  return <div className="paw-agent-row-shell" data-active={active || undefined}><button aria-current={active ? 'page' : undefined} className="paw-agent-row" onClick={onClick} title={title} type="button"><span><strong>{title}</strong><small>{meta}</small></span></button>{trailing}</div>;
}

function SessionActions({ onArchive, onDelete, session }: { onArchive: () => void; onDelete: () => void; session: SessionSummary }) {
  const archived = session.status === 'archived';
  return <Menu><MenuTrigger asChild><button aria-label={`更多“${session.title}”操作`} className="paw-agent-row-menu" type="button"><MoreHorizontal size={14} /></button></MenuTrigger><MenuContent align="end"><MenuItem onSelect={onArchive}>{archived ? <ArchiveRestore size={15} /> : <Archive size={15} />}{archived ? '恢复 Session' : '归档 Session'}</MenuItem><MenuSeparator /><MenuItem className="paw-agent-row-menu__danger" onSelect={onDelete}><Trash2 size={15} />删除 Session</MenuItem></MenuContent></Menu>;
}

function RailNotice({ action, icon, text }: { action?: () => void; icon?: ReactNode; text: string }) {
  return <div className="paw-agent-rail-notice">{icon}<span>{text}</span>{action ? <button onClick={action} type="button">重试</button> : null}</div>;
}

function initialSelection(
  initialRoute: string,
  targetKind?: PawOsWindowTarget['kind'],
  targetId?: string,
  targetRoomId?: string,
): Selection {
  if (targetKind === 'session' && targetId) return { kind: 'session', id: targetId };
  if (targetKind === 'room' && targetId) return { kind: 'room', id: targetId };
  if (targetKind === 'participant' && targetRoomId) return { kind: 'room', id: targetRoomId };
  if (initialRoute.startsWith('/rooms')) {
    const roomId = new URLSearchParams(initialRoute.split('?', 2)[1] ?? '').get('room');
    return roomId ? { kind: 'room', id: roomId } : { kind: 'new' };
  }
  const query = new URLSearchParams(initialRoute.split('?', 2)[1] ?? '');
  const roomId = query.get('room');
  if (roomId) return { kind: 'room', id: roomId };
  const sessionId = query.get('session') || query.get('sessionId');
  const draft = query.get('draft')?.trim();
  if (draft) return { kind: 'new', draft };
  return sessionId ? { kind: 'session', id: sessionId } : { kind: 'new' };
}

function roomItems(value: unknown): RoomSummary[] {
  const envelope = record(value);
  const source = Array.isArray(envelope.items) ? envelope.items : Array.isArray(envelope.rooms) ? envelope.rooms : [];
  return source.filter((item): item is RoomSummary => {
    const room = record(item);
    return typeof room.id === 'string' && typeof room.title === 'string' && Array.isArray(room.participants);
  });
}

function searchable(title: string, detail: string | undefined, query: string): boolean {
  return !query || `${title}\n${detail ?? ''}`.toLocaleLowerCase().includes(query);
}

function uniquePaths(values: string[]): string[] {
  return values.map((value) => value.trim()).filter((value, index, all) => value.startsWith('/') && all.indexOf(value) === index).slice(0, 24);
}

function pathName(path: string): string {
  return path.split('/').filter(Boolean).at(-1) ?? path;
}

function projectName(paths: string[] | undefined): string {
  return paths?.[0] ? pathName(paths[0]) : '无项目';
}

// 行内 meta 只在状态可行动时前置：归档、执行中、故障；idle/active 不加噪声。
function sessionMeta(session: SessionSummary): string {
  const base = `${projectName(session.workspaceRoots)} · ${relativeTime(session.updatedAtMs)}`;
  const state = session.status === 'archived' ? '已归档'
    : session.status === 'busy' ? '进行中'
    : session.status === 'faulted' ? '需要处理'
    : '';
  return state ? `${state} · ${base}` : base;
}

function relativeTime(timestamp: number): string {
  const delta = Date.now() - timestamp;
  if (delta < 60_000) return '刚刚';
  if (delta < 3_600_000) return `${Math.max(1, Math.floor(delta / 60_000))} 分钟前`;
  if (delta < 86_400_000) return `${Math.max(1, Math.floor(delta / 3_600_000))} 小时前`;
  return new Intl.DateTimeFormat('zh-CN', { month: 'numeric', day: 'numeric' }).format(new Date(timestamp));
}

function record(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function errorText(error: unknown): string {
  return error instanceof Error && error.message ? error.message : '工作没有成功开始，请重试。';
}
