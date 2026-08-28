import { Activity, Archive, ArrowLeft, Bot, ChevronDown, ChevronRight, CircleAlert, FileText, FolderClosed, FolderOpen, LoaderCircle, MessagesSquare, RotateCcw, Search, Settings2, SlidersHorizontal, Users, X } from 'lucide-react';
import { memo, useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type DragEvent, type KeyboardEvent as ReactKeyboardEvent, type RefObject } from 'react';
import { useControlTransport } from '@/app/control-transport';
import { sessionItems } from '@/features/agent/types';
import { usePawDesktopApi, usePawDesktopStore } from '../runtime/desktop-context';
import type { PawWayfinderIconPosition, PawWayfinderState } from '../runtime/desktop-store';
import {
  projectWayfinderWork,
  bucketizeWayfinderWork,
  wayfinderWorkTime,
  type WayfinderWorkBucket,
  type WayfinderWorkItem,
  type WayfinderWorkProject,
  type WayfinderWorkRoomSource,
  type WayfinderWorkView,
} from './wayfinder-work-projection';

export const WAYFINDER_DRAG_MIME = 'application/x-paw-wayfinder-icon';
export const WAYFINDER_ICON_WIDTH = 96;
export const WAYFINDER_ICON_HEIGHT = 92;
const WAYFINDER_SESSION_LIMIT_MAX = 500;
const WAYFINDER_ROOM_LIMIT_MAX = 200;
const WAYFINDER_PAGE_SIZE = 100;

/**
 * PawWayfinderWork — PAWOS' project folders and conversation files.
 *
 * The desktop plane is the contract: the projection is still read-only over
 * the Agent directory, but folders and dialogue files live on the same visual
 * canvas as App shortcuts. Dragging changes only PAWOS coordinates, folder
 * assignment, or archive visibility; every click opens the canonical Agent
 * Session/Room window.
 *
 * The panel takes no props, so memo makes it a true leaf: it re-renders when
 * its own directory read, query or expansion state changes, and never because
 * the desktop above it moved a window, drew a lasso or ticked the clock.
 */
export const PawWayfinderWork = memo(function PawWayfinderWork() {
  const transport = useControlTransport();
  const api = usePawDesktopApi();
  const desktopIdle = usePawDesktopStore((state) => Object.keys(state.windows).length === 0);
  const wayfinder = usePawDesktopStore((state) => state.wayfinder);
  const [sessions, setSessions] = useState<ReturnType<typeof sessionItems>>([]);
  const [rooms, setRooms] = useState<WayfinderWorkRoomSource[]>([]);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [loadedOnce, setLoadedOnce] = useState(false);
  const [sessionLimit, setSessionLimit] = useState(WAYFINDER_PAGE_SIZE);
  const [roomLimit, setRoomLimit] = useState(WAYFINDER_PAGE_SIZE);
  const [sessionHasMore, setSessionHasMore] = useState(false);
  const [roomHasMore, setRoomHasMore] = useState(false);
  const [query, setQuery] = useState('');
  const [expandedBuckets, setExpandedBuckets] = useState<ReadonlySet<string>>(new Set());
  const [expandedRepeats, setExpandedRepeats] = useState<ReadonlySet<string>>(new Set());
  /* An expanded folder owns one floating content panel. Keeping a single id
     is important on the desktop coordinate plane: two neighbouring folders
     may be icons, but their scrollable panels must never occupy the same
     pixels. `undefined` means the first project gets the useful initial
     preview; `null` is an explicit user fold-all state. */
  const [expandedProjectId, setExpandedProjectId] = useState<string | null | undefined>(undefined);
  const [showArchived, setShowArchived] = useState(false);
  const [draggingKey, setDraggingKey] = useState<string | null>(null);
  const [contextProjectId, setContextProjectId] = useState<string | null>(null);
  const contextTriggerRef = useRef<HTMLButtonElement | null>(null);
  const contextSheetRef = useRef<HTMLElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLDivElement>(null);
  const lastLoadRef = useRef(0);

  const load = useCallback(async () => {
    lastLoadRef.current = Date.now();
    setLoading(true);
    const [sessionResult, roomResult] = await Promise.allSettled([
      transport.request({ pathId: 'agent.sessions.list', query: { limit: sessionLimit } }),
      transport.request({ pathId: 'agent.rooms.list', query: { limit: roomLimit } }),
    ]);
    if (sessionResult.status === 'fulfilled') {
      const page = sessionItems(sessionResult.value);
      setSessions(page);
      setSessionHasMore(page.length >= sessionLimit && sessionLimit < WAYFINDER_SESSION_LIMIT_MAX);
    }
    if (roomResult.status === 'fulfilled') {
      const page = roomSources(roomResult.value);
      setRooms(page);
      setRoomHasMore(page.length >= roomLimit && roomLimit < WAYFINDER_ROOM_LIMIT_MAX);
    }
    setFailed(sessionResult.status === 'rejected' && roomResult.status === 'rejected');
    setLoading(false);
    setLoadedOnce(true);
  }, [roomLimit, sessionLimit, transport]);

  useEffect(() => { void load(); }, [load]);

  // Returning to an empty desktop is the moment the panel is actually read;
  // refresh then instead of polling while a window covers it.
  useEffect(() => {
    if (!desktopIdle || !loadedOnce) return;
    if (Date.now() - lastLoadRef.current < 5_000) return;
    void load();
  }, [desktopIdle, load, loadedOnce]);

  const fullView = useMemo(
    () => projectWayfinderWork({ nowMs: Date.now(), rooms, sessions }),
    [rooms, sessions],
  );
  const sourceView = useMemo(
    () => query.trim()
      ? projectWayfinderWork({ nowMs: Date.now(), query, rooms, sessions })
      : fullView,
    [fullView, query, rooms, sessions],
  );
  const view = useMemo(
    () => applyWayfinderUiState(sourceView, wayfinder, fullView.projects),
    [fullView.projects, sourceView, wayfinder],
  );
  const archivedItems = useMemo(() => {
    const visibleKeys = new Set(sourceView.projects.flatMap((project) => project.items.map((item) => item.key)));
    return fullView.projects.flatMap((project) => project.items)
      .filter((item) => wayfinder.archived.includes(item.key) && visibleKeys.has(item.key));
  }, [fullView.projects, sourceView.projects, wayfinder.archived]);
  const searching = query.trim().length > 0;
  const visibleExpandedProjectId = searching
    ? view.projects[0]?.id ?? null
    : expandedProjectId === undefined
      ? view.projects[0]?.id ?? null
      : expandedProjectId;
  const contextProject = contextProjectId
    ? fullView.projects.find((project) => project.id === contextProjectId) ?? null
    : null;

  useEffect(() => {
    if (contextProjectId && !contextProject) setContextProjectId(null);
  }, [contextProject, contextProjectId]);

  useEffect(() => {
    if (!contextProject) return;
    contextSheetRef.current?.querySelector<HTMLButtonElement>('[data-wayfinder-context-back]')?.focus();
  }, [contextProject]);

  useEffect(() => {
    if (contextProjectId !== null) return;
    contextTriggerRef.current?.focus();
  }, [contextProjectId]);

  useEffect(() => {
    if (!contextProject) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      event.preventDefault();
      setContextProjectId(null);
    };
    document.addEventListener('keydown', closeOnEscape);
    return () => document.removeEventListener('keydown', closeOnEscape);
  }, [contextProject]);

  const openItem = useCallback((kind: 'session' | 'room', id: string, title: string) => {
    const state = api.getState();
    state.openApp('agent', {
      entityId: id,
      initialRoute: `/agent?${kind === 'room' ? 'room' : 'session'}=${encodeURIComponent(id)}`,
      target: { kind, id, title },
      title: 'Agent',
    });
  }, [api]);

  const openSystemSettings = useCallback(() => {
    api.getState().openApp('system-settings', { initialRoute: '/configuration' });
  }, [api]);

  const openObservability = useCallback(() => {
    api.getState().openApp('system-monitor', { initialRoute: '/observability' });
  }, [api]);

  const iconPosition = useCallback((iconId: string, index: number): PawWayfinderIconPosition => (
    wayfinder.iconPositions[iconId] ?? defaultIconPosition(index)
  ), [wayfinder.iconPositions]);

  const startDrag = useCallback((event: DragEvent<HTMLElement>, iconId: string) => {
    event.stopPropagation();
    setDraggingKey(iconId);
    event.dataTransfer.effectAllowed = 'move';
    event.dataTransfer.setData(WAYFINDER_DRAG_MIME, iconId);
    event.dataTransfer.setData('text/plain', iconId);
  }, []);

  const endDrag = useCallback(() => setDraggingKey(null), []);

  const dropKey = useCallback((event: DragEvent<HTMLElement>): string => (
    event.dataTransfer.getData(WAYFINDER_DRAG_MIME) || event.dataTransfer.getData('text/plain')
  ), []);

  const dropOnCanvas = useCallback((event: DragEvent<HTMLDivElement>) => {
    const iconId = dropKey(event);
    if (!iconId || (!isDialogueIcon(iconId) && !iconId.startsWith('project:'))) return;
    event.preventDefault();
    event.stopPropagation();
    const canvas = canvasRef.current;
    if (canvas) {
      const rect = canvas.getBoundingClientRect();
      const x = event.clientX - rect.left + canvas.scrollLeft - WAYFINDER_ICON_WIDTH / 2;
      const y = event.clientY - rect.top + canvas.scrollTop - WAYFINDER_ICON_HEIGHT / 2;
      api.getState().setWayfinderIconPosition(iconId, clampWayfinderIconPosition({ x, y }, canvas));
    }
    if (isDialogueIcon(iconId)) api.getState().setWayfinderProjectAssignment(iconId, null);
    api.getState().setWayfinderArchived(iconId, false);
    setDraggingKey(null);
  }, [api, dropKey]);

  const dropOnProject = useCallback((event: DragEvent<HTMLElement>, projectId: string) => {
    const iconId = dropKey(event);
    if (!iconId || !isDialogueIcon(iconId)) return;
    event.preventDefault();
    event.stopPropagation();
    api.getState().setWayfinderProjectAssignment(iconId, projectId);
    api.getState().setWayfinderArchived(iconId, false);
    setExpandedProjectId(projectId);
    setDraggingKey(null);
  }, [api, dropKey]);

  const dropOnArchive = useCallback((event: DragEvent<HTMLElement>) => {
    const iconId = dropKey(event);
    if (!iconId || !isDialogueIcon(iconId)) return;
    event.preventDefault();
    event.stopPropagation();
    api.getState().setWayfinderArchived(iconId, true);
    setShowArchived(true);
    setDraggingKey(null);
  }, [api, dropKey]);

  const restoreItem = useCallback((iconId: string) => {
    api.getState().setWayfinderArchived(iconId, false);
  }, [api]);

  // Same roving-arrow contract as the desktop shortcut column: focus walks the
  // rows without tabbing through every control on the desktop.
  const walkRows = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return;
    const host = listRef.current;
    if (!host) return;
    const rows = Array.from(host.querySelectorAll<HTMLButtonElement>('button[data-wayfinder-row]'));
    const current = rows.indexOf(document.activeElement as HTMLButtonElement);
    if (current === -1) return;
    event.preventDefault();
    const next = event.key === 'Home'
      ? 0
      : event.key === 'End'
      ? rows.length - 1
      : Math.min(Math.max(current + (event.key === 'ArrowDown' ? 1 : -1), 0), rows.length - 1);
    rows[next]?.focus();
  };

  const hasRows = view.rowCount > 0;
  const canvasMinHeight = Math.max(360, Math.ceil(view.projects.length / 4) * 112 + 122);
  return (
    <section aria-label="最近工作" className="paw-wayfinder-work" data-paw-desktop-panel data-paw-desktop-work-files onPointerDown={(event) => event.stopPropagation()}>
      <header className="paw-wayfinder-work__head">
        <span>
          <strong>项目桌面</strong>
          <small>项目文件夹 · 对话图标</small>
        </span>
        {hasRows ? <span className="paw-wayfinder-work__count">{view.projects.length} 个项目 · {view.rowCount} 个对话</span> : null}
      </header>
      {!contextProject ? <div className="paw-wayfinder-work__toolbar">
        <label className="paw-wayfinder-work__search">
          <Search aria-hidden="true" size={14} />
          <input
            aria-label="搜索最近工作"
            onChange={(event) => setQuery(event.target.value)}
            placeholder="查找对话图标"
            type="search"
            value={query}
          />
        </label>
        <button
          aria-expanded={showArchived}
          aria-label={`归档 ${wayfinder.archived.length} 个对话`}
          className="paw-wayfinder-work__archive-dropzone"
          data-wayfinder-archive
          onClick={() => setShowArchived((value) => !value)}
          onDragOver={(event) => { event.preventDefault(); event.dataTransfer.dropEffect = 'move'; }}
          onDrop={dropOnArchive}
          type="button"
        >
          <Archive aria-hidden="true" size={14} />
          <span>归档</span>
          <small>{wayfinder.archived.length || ''}</small>
        </button>
        {sessionHasMore || roomHasMore ? (
          <button
            aria-label="加载更多工作记录"
            className="paw-wayfinder-work__load-more"
            disabled={loading}
            onClick={() => {
              if (sessionHasMore) setSessionLimit((current) => Math.min(current + WAYFINDER_PAGE_SIZE, WAYFINDER_SESSION_LIMIT_MAX));
              if (roomHasMore) setRoomLimit((current) => Math.min(current + WAYFINDER_PAGE_SIZE, WAYFINDER_ROOM_LIMIT_MAX));
            }}
            type="button"
          >
            {loading ? <LoaderCircle aria-hidden="true" className="paw-wayfinder-work__spin" size={13} /> : <ChevronDown aria-hidden="true" size={13} />}
            <span>更多</span>
          </button>
        ) : null}
      </div> : null}
      {showArchived && !contextProject ? (
        <ArchiveTray items={archivedItems} onDragEnd={endDrag} onDragStart={startDrag} onOpen={openItem} onRestore={restoreItem} />
      ) : null}
      <div
        aria-busy={loading || undefined}
        aria-hidden={contextProject ? true : undefined}
        className="paw-wayfinder-work__list paw-wayfinder-work__canvas"
        data-wayfinder-canvas
        hidden={Boolean(contextProject)}
        onDragOver={(event) => { event.preventDefault(); event.dataTransfer.dropEffect = 'move'; }}
        onDrop={dropOnCanvas}
        onKeyDown={walkRows}
        ref={(node) => { listRef.current = node; canvasRef.current = node; }}
        style={{ minHeight: `${canvasMinHeight}px` }}
      >
        {loading && !loadedOnce ? (
          <p className="paw-wayfinder-work__state" role="status"><LoaderCircle className="paw-wayfinder-work__spin" size={13} />正在读取</p>
        ) : failed ? (
          <p className="paw-wayfinder-work__state" role="alert">
            <CircleAlert size={13} />工作记录暂时无法读取
            <button onClick={() => void load()} type="button">重试</button>
          </p>
        ) : !hasRows ? (
          <p className="paw-wayfinder-work__state">
            {searching ? '没有匹配的工作' : '还没有工作记录'}
            {searching ? null : (
              <button onClick={() => openAgentHome(api)} type="button">开始一件事</button>
            )}
          </p>
        ) : view.projects.map((project, index) => {
          const folderExpanded = visibleExpandedProjectId === project.id;
          return (
            <ProjectFolder
              expandedBuckets={expandedBuckets}
              expandedRepeats={expandedRepeats}
              expanded={folderExpanded}
              iconPosition={iconPosition(`project:${project.id}`, index)}
              onDragEnd={endDrag}
              onDragStart={startDrag}
              key={project.id}
              onContext={(trigger) => {
                contextTriggerRef.current = trigger;
                setContextProjectId(project.id);
              }}
              onDrop={(event) => dropOnProject(event, project.id)}
              onOpen={openItem}
              onToggle={() => setExpandedProjectId(folderExpanded ? null : project.id)}
              onToggleBucket={(key) => setExpandedBuckets((current) => toggled(current, key))}
              onToggleRepeats={(key) => setExpandedRepeats((current) => toggled(current, key))}
              project={project}
              searching={searching}
            />
          );
        })}
        {draggingKey ? <p className="paw-wayfinder-work__drop-hint">拖到空白处放回项目桌面，拖到项目文件夹归类</p> : null}
      </div>
      {contextProject ? (
        <ProjectContextSheet
          onBack={() => setContextProjectId(null)}
          onOpen={openItem}
          onOpenObservability={openObservability}
          onOpenSystemSettings={openSystemSettings}
          project={contextProject}
          sheetRef={contextSheetRef}
        />
      ) : null}
    </section>
  );
});

function ProjectFolder({ expanded, expandedBuckets, expandedRepeats, iconPosition, onContext, onDragEnd, onDragStart, onDrop, onOpen, onToggle, onToggleBucket, onToggleRepeats, project, searching }: {
  expanded: boolean;
  expandedBuckets: ReadonlySet<string>;
  expandedRepeats: ReadonlySet<string>;
  iconPosition: PawWayfinderIconPosition;
  onContext: (trigger: HTMLButtonElement) => void;
  onDragEnd: () => void;
  onDragStart: (event: DragEvent<HTMLElement>, iconId: string) => void;
  onDrop: (event: DragEvent<HTMLElement>) => void;
  onOpen: (kind: 'session' | 'room', id: string, title: string) => void;
  onToggle: () => void;
  onToggleBucket: (key: string) => void;
  onToggleRepeats: (key: string) => void;
  project: WayfinderWorkProject;
  searching: boolean;
}) {
  const displayedOpen = searching || expanded;
  const style = { '--wayfinder-x': `${iconPosition.x}px`, '--wayfinder-y': `${iconPosition.y}px` } as CSSProperties;
  return (
    <div className="paw-wayfinder-work__project-shell" style={style}>
      <details
        className="paw-wayfinder-work__project"
        data-project-folder
        onDragOver={(event) => { event.preventDefault(); event.stopPropagation(); event.dataTransfer.dropEffect = 'move'; }}
        onDrop={onDrop}
        open={displayedOpen}
      >
        <summary
          aria-expanded={displayedOpen}
          data-wayfinder-project
          draggable
          onClick={(event) => { event.preventDefault(); onToggle(); }}
          onDoubleClick={() => { if (!displayedOpen) onToggle(); }}
          onDragEnd={onDragEnd}
          onDragStart={(event) => onDragStart(event, `project:${project.id}`)}
          title={`${project.label} · ${project.items.length} 个对话`}
        >
          <span className="paw-wayfinder-work__folder-art" data-attention={project.attentionCount > 0 || undefined} data-running={project.runningCount > 0 || undefined}>
            {displayedOpen ? <FolderOpen aria-hidden="true" size={30} /> : <FolderClosed aria-hidden="true" size={30} />}
            <span aria-hidden="true" className="paw-wayfinder-work__folder-mark">
              {project.roomCount > 0 ? <MessagesSquare size={11} /> : <Bot size={11} />}
            </span>
            <i aria-hidden="true" />
          </span>
          <span className="paw-wayfinder-work__project-copy">
            <strong>{project.label}</strong>
            <small>{project.runningCount ? `${project.runningCount} 个进行中` : project.attentionCount ? `${project.attentionCount} 个需处理` : '项目对话'}</small>
          </span>
          <small className="paw-wayfinder-work__project-count">{project.items.length} 个文件</small>
        </summary>
        <div
          aria-label={`${project.label} 项目窗口`}
          className="paw-wayfinder-work__project-content"
          data-wayfinder-project-window
          role="dialog"
        >
          <header className="paw-wayfinder-work__project-content-head">
            <div>
              <span>项目文件夹</span>
              <strong>{project.label}</strong>
              <small>{project.items.length} 个对话 · {project.runningCount ? `${project.runningCount} 个进行中` : project.attentionCount ? `${project.attentionCount} 个需处理` : '已准备好'}</small>
            </div>
            <div className="paw-wayfinder-work__project-content-actions">
              <button
                aria-label={`打开 ${project.label} 项目设置`}
                className="paw-wayfinder-work__project-content-context"
                data-wayfinder-context
                onClick={(event) => { event.preventDefault(); event.stopPropagation(); onContext(event.currentTarget); }}
                title="项目设置与上下文"
                type="button"
              >
                <Settings2 aria-hidden="true" size={14} />
              </button>
              <button aria-label={`关闭 ${project.label} 项目窗口`} onClick={(event) => { event.preventDefault(); event.stopPropagation(); onToggle(); }} type="button">
                <X aria-hidden="true" size={15} />
              </button>
            </div>
          </header>
          <div className="paw-wayfinder-work__project-content-scroll">
            {project.buckets.map((bucket) => (
              <WorkBucket
                bucket={bucket}
                expanded={searching || expandedBuckets.has(`${project.id}:${bucket.id}`)}
                expandedRepeats={expandedRepeats}
                onDragEnd={onDragEnd}
                onDragStart={onDragStart}
                key={bucket.id}
                onOpen={onOpen}
                onToggle={() => onToggleBucket(`${project.id}:${bucket.id}`)}
                onToggleRepeats={onToggleRepeats}
                searching={searching}
              />
            ))}
          </div>
        </div>
      </details>
      <button
        aria-label={`查看 ${project.label} 项目上下文`}
        className="paw-wayfinder-work__project-context"
        data-wayfinder-context
        onClick={(event) => { event.stopPropagation(); onContext(event.currentTarget); }}
        title="项目设置与上下文"
        type="button"
      >
        <SlidersHorizontal aria-hidden="true" size={12} />
      </button>
    </div>
  );
}

function ProjectContextSheet({ onBack, onOpen, onOpenObservability, onOpenSystemSettings, project, sheetRef }: {
  onBack: () => void;
  onOpen: (kind: 'session' | 'room', id: string, title: string) => void;
  onOpenObservability: () => void;
  onOpenSystemSettings: () => void;
  project: WayfinderWorkProject;
  sheetRef: RefObject<HTMLElement | null>;
}) {
  return (
    <aside
      aria-label={`${project.label} 项目上下文`}
      aria-modal="false"
      className="paw-wayfinder-work__context-sheet"
      data-wayfinder-context-sheet
      ref={sheetRef}
      role="dialog"
    >
      <header className="paw-wayfinder-work__context-head">
        <button aria-label="返回最近工作" className="paw-wayfinder-work__context-back" data-wayfinder-context-back onClick={onBack} type="button">
          <ArrowLeft aria-hidden="true" size={13} />
        </button>
        <div>
          <small>项目上下文</small>
          <h2>{project.label}</h2>
        </div>
      </header>

      <dl className="paw-wayfinder-work__context-stats">
        <div><dt>Session</dt><dd>{project.sessionCount}</dd></div>
        <div><dt>Room</dt><dd>{project.roomCount}</dd></div>
        <div><dt>进行中</dt><dd>{project.runningCount}</dd></div>
        <div data-attention={project.attentionCount > 0 || undefined}><dt>需处理</dt><dd>{project.attentionCount}</dd></div>
      </dl>

      <section className="paw-wayfinder-work__context-roots">
        <h3>工作区</h3>
        {project.workspaceRoots.length ? project.workspaceRoots.map((root) => (
          <code key={root}>{root}</code>
        )) : <p>未绑定工作区</p>}
      </section>

      <section className="paw-wayfinder-work__context-conversations">
        <header>
          <h3>当前对话</h3>
          <small>{project.items.length}</small>
        </header>
        <div className="paw-wayfinder-work__context-items">
          {project.items.map((item) => (
            <button
              className="paw-wayfinder-work__context-item"
              data-activity={item.activity}
              data-wayfinder-context-item
              key={item.key}
              onClick={() => onOpen(item.kind, item.id, item.title)}
              type="button"
            >
              <i aria-hidden="true" className="paw-wayfinder-work__dot" />
              <span>
                <strong>{item.title}</strong>
                <small>{item.kind === 'room' ? 'Room' : 'Session'} · {item.statusLabel}</small>
                <small>{item.detail}</small>
              </span>
            </button>
          ))}
        </div>
      </section>

      <nav aria-label="项目快捷入口" className="paw-wayfinder-work__context-shortcuts">
        <button data-wayfinder-context-shortcut="settings" onClick={onOpenSystemSettings} type="button">
          <Settings2 aria-hidden="true" size={13} />系统设置
        </button>
        <button data-wayfinder-context-shortcut="observability" onClick={onOpenObservability} type="button">
          <Activity aria-hidden="true" size={13} />Trace / Eval
        </button>
      </nav>

      <p className="paw-wayfinder-work__context-note">这是 PAWOS 的显示上下文，不会创建 Finder/Git 文件，也不负责管理 ProjectSettings。</p>
    </aside>
  );
}

function WorkBucket({ bucket, expanded, expandedRepeats, onDragEnd, onDragStart, onOpen, onToggle, onToggleRepeats, searching }: {
  bucket: WayfinderWorkBucket;
  expanded: boolean;
  expandedRepeats: ReadonlySet<string>;
  onDragEnd: () => void;
  onDragStart: (event: DragEvent<HTMLElement>, iconId: string) => void;
  onOpen: (kind: 'session' | 'room', id: string, title: string) => void;
  onToggle: () => void;
  onToggleRepeats: (key: string) => void;
  searching: boolean;
}) {
  // 更早 rests fully collapsed; 今天/本周 preview a short slice and only then
  // offer the rest inside the panel's own scroll area.
  const restingCount = Math.min(bucket.previewCount, bucket.items.length);
  const visibleItems = expanded ? bucket.items : bucket.items.slice(0, restingCount);
  const hiddenCount = bucket.items.length - visibleItems.length;
  const collapsedWholeBucket = !searching && bucket.previewCount === 0;
  return (
    <section className="paw-wayfinder-work__bucket" data-bucket={bucket.id}>
      {collapsedWholeBucket ? (
        <button
          aria-expanded={expanded}
          className="paw-wayfinder-work__bucket-toggle"
          onClick={onToggle}
          type="button"
        >
          {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
          <span>{bucket.label}</span>
          <small>{bucket.items.length}</small>
        </button>
      ) : (
        <h3 className="paw-wayfinder-work__bucket-label">{bucket.label}<small>{bucket.items.length}</small></h3>
      )}
      {(!collapsedWholeBucket || expanded) ? visibleItems.map((item) => (
        <WorkRow
          expandedRepeats={expandedRepeats}
          item={item}
          onDragEnd={onDragEnd}
          onDragStart={onDragStart}
          key={item.key}
          onOpen={onOpen}
          onToggleRepeats={onToggleRepeats}
        />
      )) : null}
      {!collapsedWholeBucket && hiddenCount > 0 ? (
        <button className="paw-wayfinder-work__more" onClick={onToggle} type="button">
          还有 {hiddenCount} 段
        </button>
      ) : null}
    </section>
  );
}

function WorkRow({ expandedRepeats, item, onDragEnd, onDragStart, onOpen, onToggleRepeats }: {
  expandedRepeats: ReadonlySet<string>;
  item: WayfinderWorkItem;
  onDragEnd: () => void;
  onDragStart: (event: DragEvent<HTMLElement>, iconId: string) => void;
  onOpen: (kind: 'session' | 'room', id: string, title: string) => void;
  onToggleRepeats: (key: string) => void;
}) {
  const repeatsOpen = expandedRepeats.has(item.key);
  const meta = [item.project, wayfinderWorkTime(item.updatedAtMs, Date.now())].filter(Boolean).join(' · ');
  return (
    <div className="paw-wayfinder-work__row-shell">
      <button
        className="paw-wayfinder-work__row"
        data-activity={item.activity}
        data-dialogue-file
        data-kind={item.kind}
        data-wayfinder-row
        draggable
        onClick={() => onOpen(item.kind, item.id, item.title)}
        onDragEnd={onDragEnd}
        onDragStart={(event) => onDragStart(event, item.key)}
        title={`${item.title} · ${meta}`}
        type="button"
      >
        <span aria-hidden="true" className="paw-wayfinder-work__file-icon" data-kind={item.kind}>
          {item.kind === 'room' ? <MessagesSquare size={22} /> : <FileText size={22} />}
          <i className="paw-wayfinder-work__dot" />
        </span>
        <span className="paw-wayfinder-work__copy">
          <strong>{item.title}</strong>
          <small>
            {item.kind === 'room' ? <Users aria-hidden="true" size={11} /> : null}
            <span className="paw-wayfinder-work__kind" data-kind={item.kind}>{item.kind === 'room' ? 'Room' : 'Session'}</span>
            {item.agents.length ? (
              <span aria-label={`${item.agents.length} 位伙伴`} className="paw-wayfinder-work__agents">
                {item.agents.slice(0, 4).map((agent) => <b key={agent}>{agent}</b>)}
                {item.agents.length > 4 ? <b>+{item.agents.length - 4}</b> : null}
              </span>
            ) : null}
            <span>{item.statusLabel}{meta ? ` · ${meta}` : ''}</span>
          </small>
          <small className="paw-wayfinder-work__detail">{item.detail}</small>
        </span>
      </button>
      {item.repeats.length ? (
        <button
          aria-expanded={repeatsOpen}
          aria-label={`同名工作还有 ${item.repeats.length} 段`}
          className="paw-wayfinder-work__repeats-toggle"
          onClick={() => onToggleRepeats(item.key)}
          title={`同名工作还有 ${item.repeats.length} 段`}
          type="button"
        >
          ×{item.repeats.length + 1}
        </button>
      ) : null}
      {repeatsOpen ? item.repeats.map((repeat) => (
        <button
          className="paw-wayfinder-work__repeat"
          data-wayfinder-row
          draggable
          key={`${repeat.kind}:${repeat.id}`}
          onClick={() => onOpen(repeat.kind, repeat.id, item.title)}
          onDragEnd={onDragEnd}
          onDragStart={(event) => onDragStart(event, `${repeat.kind}:${repeat.id}`)}
          type="button"
        >
          <span>较早一段</span>
          <small>{wayfinderWorkTime(repeat.updatedAtMs, Date.now())}</small>
        </button>
      )) : null}
    </div>
  );
}

function ArchiveTray({ items, onDragEnd, onDragStart, onOpen, onRestore }: {
  items: WayfinderWorkItem[];
  onDragEnd: () => void;
  onDragStart: (event: DragEvent<HTMLElement>, iconId: string) => void;
  onOpen: (kind: 'session' | 'room', id: string, title: string) => void;
  onRestore: (iconId: string) => void;
}) {
  return (
    <section aria-label="已归档对话" className="paw-wayfinder-work__archive-tray" data-wayfinder-archive-tray>
      <header>
        <span><Archive aria-hidden="true" size={13} /><strong>已归档</strong></span>
        <small>点击恢复到桌面 · 双击打开</small>
      </header>
      {items.length ? (
        <div className="paw-wayfinder-work__archive-icons">
          {items.map((item) => (
            <button
              aria-label={`恢复 ${item.title}`}
              className="paw-wayfinder-work__archive-item"
              data-activity={item.activity}
              data-kind={item.kind}
              draggable
              key={item.key}
              onClick={() => onRestore(item.key)}
              onDoubleClick={() => onOpen(item.kind, item.id, item.title)}
              onDragEnd={onDragEnd}
              onDragStart={(event) => onDragStart(event, item.key)}
              title={`${item.title} · 双击打开`}
              type="button"
            >
              <span className="paw-wayfinder-work__archive-icon" aria-hidden="true">
                {item.kind === 'room' ? <MessagesSquare size={20} /> : <FileText size={20} />}
              </span>
              <strong>{item.title}</strong>
              <small>{item.kind === 'room' ? 'Room' : 'Session'}</small>
              <span className="paw-wayfinder-work__archive-restore"><RotateCcw aria-hidden="true" size={10} />恢复</span>
            </button>
          ))}
        </div>
      ) : <p>归档区还是空的</p>}
    </section>
  );
}

function applyWayfinderUiState(
  source: WayfinderWorkView,
  state: PawWayfinderState,
  baseProjects: readonly WayfinderWorkProject[],
): WayfinderWorkView {
  const archived = new Set(state.archived);
  const projectById = new Map(baseProjects.map((project) => [project.id, project]));

  const grouped = new Map<string, WayfinderWorkItem[]>();
  for (const sourceProject of source.projects) {
    for (const item of sourceProject.items) {
      if (archived.has(item.key)) continue;
      const target = state.projectAssignments[item.key]
        ? projectById.get(state.projectAssignments[item.key]!) ?? sourceProject
        : sourceProject;
      const projected = target.id === item.projectKey && target.label === item.project
        ? item
        : { ...item, projectKey: target.id, project: target.label };
      const items = grouped.get(target.id) ?? [];
      items.push(projected);
      grouped.set(target.id, items);
    }
  }

  const projects = [...grouped.entries()]
    .map(([id, items]) => {
      const sourceProject = projectById.get(id) ?? source.projects.find((project) => project.id === id);
      /* `items` may include a file dragged here from another project. Build
         buckets from the resulting destination set instead of filtering the
         old project's buckets, otherwise the destination summary updates but
         its opened folder renders no moved file. */
      const buckets = bucketizeWayfinderWork(items, Date.now());
      return {
        ...(sourceProject ?? {
          id,
          label: items[0]?.project ?? '未绑定项目',
          workspaceRoots: items.flatMap((item) => item.workspaceRoots),
          sessionCount: 0,
          roomCount: 0,
          runningCount: 0,
          attentionCount: 0,
          items: [],
          buckets: [],
        }),
        id,
        items,
        buckets,
        sessionCount: items.filter((item) => item.kind === 'session').length,
        roomCount: items.filter((item) => item.kind === 'room').length,
        runningCount: items.filter((item) => item.activity === 'running').length,
        attentionCount: items.filter((item) => item.activity === 'attention').length,
      } satisfies WayfinderWorkProject;
    })
    .sort((left, right) => (right.items[0]?.updatedAtMs ?? 0) - (left.items[0]?.updatedAtMs ?? 0));

  const visibleKeys = new Set(projects.flatMap((project) => project.items.map((item) => item.key)));
  return {
    ...source,
    buckets: source.buckets
      .map((bucket) => ({ ...bucket, items: bucket.items.filter((item) => visibleKeys.has(item.key)) }))
      .filter((bucket) => bucket.items.length > 0),
    projects,
    rowCount: visibleKeys.size,
  };
}

function defaultIconPosition(index: number): PawWayfinderIconPosition {
  return {
    x: 18 + (index % 4) * 112,
    y: 132 + Math.floor(index / 4) * 112,
  };
}

export function clampWayfinderIconPosition(position: PawWayfinderIconPosition, canvas: HTMLElement): PawWayfinderIconPosition {
  const width = Math.max(canvas.clientWidth, canvas.scrollWidth);
  const height = Math.max(canvas.clientHeight, canvas.scrollHeight);
  return {
    x: Math.round(Math.max(8, Math.min(Math.max(8, width - WAYFINDER_ICON_WIDTH - 8), position.x))),
    y: Math.round(Math.max(8, Math.min(Math.max(8, height - WAYFINDER_ICON_HEIGHT - 8), position.y))),
  };
}

function isDialogueIcon(iconId: string): boolean {
  return iconId.startsWith('session:') || iconId.startsWith('room:');
}

function openAgentHome(api: ReturnType<typeof usePawDesktopApi>): void {
  api.getState().openApp('agent', { title: 'Agent' });
}

function toggled(current: ReadonlySet<string>, key: string): ReadonlySet<string> {
  const next = new Set(current);
  if (next.has(key)) next.delete(key);
  else next.add(key);
  return next;
}

function roomSources(value: unknown): WayfinderWorkRoomSource[] {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return [];
  const envelope = value as Record<string, unknown>;
  const source = Array.isArray(envelope.items) ? envelope.items : Array.isArray(envelope.rooms) ? envelope.rooms : [];
  return source.filter((item): item is WayfinderWorkRoomSource => {
    if (typeof item !== 'object' || item === null) return false;
    const room = item as Record<string, unknown>;
    return typeof room.id === 'string'
      && typeof room.title === 'string'
      && typeof room.updatedAtMs === 'number';
  });
}
