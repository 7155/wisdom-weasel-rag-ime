import { ArrowUpRight, Bot, Earth, Grid3X3, LayoutGrid, Maximize2, Minus, PanelLeft, PanelRight, PanelsTopLeft, Settings, X } from 'lucide-react';
import { Fragment, memo, useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type KeyboardEvent as ReactKeyboardEvent, type MouseEvent as ReactMouseEvent, type PointerEvent as ReactPointerEvent, type RefObject } from 'react';
import { ConnectionIndicator } from '@/components/feedback';
import { pawApp, pawApps, pawDockAppIds, type PawAppDefinition, type PawAppId } from '../runtime/app-registry';
import { usePawDesktopApi, usePawDesktopStore } from '../runtime/desktop-context';
import { dockMagnetics } from './dock-magnification';
import { PawAppIcon, PawBrandMark } from './PawAppIcon';
import { PawCompositionField } from './PawCompositionField';
import { pulsePawComposition } from '../runtime/composition-pulse';
import { PawContextMenu, type PawContextMenuItem } from './PawContextMenu';
import { PawFieldLede } from './PawFieldLede';
import { PawWayfinderWork } from './PawWayfinderWork';
import { PawWindowLayer } from './PawWindowLayer';
import { pawBrowserHost } from '../apps/paw-browser-host';

type PawMenuTarget =
  | { kind: 'desktop' }
  | { kind: 'menubar' }
  | { kind: 'apps'; appIds: PawAppId[]; label: string }
  | { kind: 'window'; windowId: string; label: string };

/* The archive is grouped the way the machine is actually laid out: where the
 * work happens (工作), where what came out of it is kept (记忆与知识), what the
 * work reaches for (工具), and what runs underneath (系统). Splitting 工作 from
 * Agent left two lone tiles on their own bands and made eleven Apps read as a
 * half-empty shelf; this order is also the flywheel read left to right —
 * Session, its deposits, its instruments, the floor. */
const LAUNCHPAD_GROUP_ORDER = ['work', 'library', 'tool', 'system'] as const;
const LAUNCHPAD_GROUP_LABEL: Record<(typeof LAUNCHPAD_GROUP_ORDER)[number], string> = {
  work: '工作',
  library: '记忆与知识',
  tool: '工具',
  system: '系统',
};

type PawMenuState = PawMenuTarget & { x: number; y: number };
type PawSelectionRect = { x: number; y: number; width: number; height: number };

const selectMenuSignature = (state: { windows: Record<string, { id: string; appId: PawAppId; placement?: string }> }) => Object
  .values(state.windows)
  .map((node) => `${node.id}\u0001${node.appId}\u0001${node.placement ?? ''}`)
  .sort()
  .join('\u0000');
const selectNoMenuSignature = () => '';

export function PawDesktop() {
  const api = usePawDesktopApi();
  const activeWindowId = usePawDesktopStore((state) => state.activeWindowId);
  const activeAppId = usePawDesktopStore((state) => (
    activeWindowId ? state.windows[activeWindowId]?.appId ?? null : null
  ));
  const launchpadOpen = usePawDesktopStore((state) => state.launchpadOpen);
  const overviewOpen = usePawDesktopStore((state) => state.overviewOpen);
  const collaborationFocusGroup = usePawDesktopStore((state) => state.collaborationFocusGroup);
  const collaborationFocus = Boolean(collaborationFocusGroup);
  /* The wallpaper only spends frames when somebody can actually watch it.
   * The picture itself is a one-time raster; this attribute gates the live
   * pulse overlay: a focused App window, the Launchpad veil, the overview
   * plane and a hidden document all mean the field is covered or unseen, so
   * the pulse driver swallows Runtime/audio pulses outright. Collaboration
   * focus and live drag/resize keep their own suspension rules. */
  const documentHidden = useDocumentHidden();
  const ambientPaused = documentHidden || Boolean(activeWindowId) || launchpadOpen || overviewOpen;
  const [selectedApps, setSelectedApps] = useState<ReadonlySet<PawAppId>>(() => new Set());
  const [contextMenu, setContextMenu] = useState<PawMenuState | null>(null);
  const [lasso, setLasso] = useState<PawSelectionRect | null>(null);
  /* Menus and their disabled states need only structural window facts:
   * identity, owning App and placement. Nobody reads them until a menu is
   * actually open, so a closed desktop subscribes to a constant — window
   * opens, closes, snaps and runtime title binds then cost the shell nothing,
   * and no bounds commit can re-render the menu bar, Wayfinder or Dock. */
  const menuSignature = usePawDesktopStore(contextMenu ? selectMenuSignature : selectNoMenuSignature);
  const menuWindows = useMemo(() => menuSignature.split('\u0000').filter(Boolean).map((item) => {
    const [id, appId, placement] = item.split('\u0001') as [string, PawAppId, string];
    return { id, appId, placement };
  }), [menuSignature]);
  const viewportRef = useRef<HTMLElement>(null);
  const menuAppRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        setContextMenu(null);
        api.getState().setLaunchpadOpen(!api.getState().launchpadOpen);
      } else if ((event.metaKey || event.ctrlKey) && event.key === ',') {
        event.preventDefault();
        setContextMenu(null);
        const state = api.getState();
        const existingWindowId = [...state.stack].reverse().find((windowId) => state.windows[windowId]?.appId === 'system-settings')
          ?? Object.values(state.windows).find((node) => node.appId === 'system-settings')?.id;
        if (existingWindowId) state.focusWindow(existingWindowId);
        else state.openApp('system-settings', { title: pawApp('system-settings').label });
        state.setLaunchpadOpen(false);
      } else if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'h') {
        event.preventDefault();
        const state = api.getState();
        if (state.activeWindowId) state.minimizeWindow(state.activeWindowId);
      } else if (event.key === 'F5') {
        event.preventDefault();
        setContextMenu(null);
        pulsePawComposition('system', .58);
        api.getState().setOverviewOpen(!api.getState().overviewOpen);
      } else if (event.key === 'Escape') {
        setContextMenu(null);
        if (api.getState().launchpadOpen) api.getState().setLaunchpadOpen(false);
        else if (api.getState().overviewOpen) api.getState().setOverviewOpen(false);
        else if (api.getState().collaborationFocusGroup) api.getState().setCollaborationFocusGroup(null);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [api]);
  useEffect(() => {
    const host = pawBrowserHost();
    if (!host) return undefined;
    const openInsidePaw = (url: string, commandId = '') => {
      const state = api.getState();
      const existing = Object.values(state.windows).find((node) => node.appId === 'browser');
      const entityId = existing?.entityId;
      state.openApp('browser', {
        ...(entityId ? { entityId } : {}),
        target: {
          kind: 'browser-target',
          id: entityId || commandId || `shell-url:${Date.now()}`,
          title: 'Browser',
          sessionId: '',
          toolCallId: '',
          targetId: '',
          provisional: true,
          ...(commandId ? { commandId } : {}),
          url,
        },
      });
    };
    const stopCommand = host.onCommand((command) => openInsidePaw(command.url, command.commandId));
    const stopOpenUrl = host.onOpenUrl((url) => openInsidePaw(url));
    return () => {
      stopCommand();
      stopOpenUrl();
    };
  }, [api]);

  /* Every shell callback below reads live state through api.getState()
   * instead of closing over render-time values, so each is created once.
   * That referential stability is what lets Wayfinder and the Dock be memo
   * leaves: focus changes, lasso frames and context menus re-render this
   * component without re-rendering those subtrees. */
  const openApp = useCallback((appId: PawAppId) => {
    const state = api.getState();
    const existingWindowId = [...state.stack].reverse().find((windowId) => state.windows[windowId]?.appId === appId)
      ?? Object.values(state.windows).find((node) => node.appId === appId)?.id;
    if (existingWindowId) state.focusWindow(existingWindowId);
    else state.openApp(appId, { title: pawApp(appId).label });
    state.setLaunchpadOpen(false);
    pulsePawComposition('app', .72);
    window.history.replaceState(null, '', `${window.location.search}#${pawApp(appId).route}`);
  }, [api]);
  const toggleLaunchpad = useCallback(() => {
    const state = api.getState();
    state.setLaunchpadOpen(!state.launchpadOpen);
  }, [api]);
  const closeLaunchpad = useCallback(() => api.getState().setLaunchpadOpen(false), [api]);
  const toggleOverview = useCallback(() => {
    pulsePawComposition('system', .58);
    const state = api.getState();
    state.setOverviewOpen(!state.overviewOpen);
  }, [api]);
  const selectApp = useCallback((appId: PawAppId, additive: boolean) => {
    setSelectedApps((current) => {
      if (!additive) return new Set([appId]);
      const next = new Set(current);
      if (next.has(appId)) next.delete(appId);
      else next.add(appId);
      return next;
    });
  }, []);

  const openContextMenu = useCallback((event: ReactMouseEvent<HTMLElement>) => {
    event.preventDefault();
    event.stopPropagation();
    const target = event.target as HTMLElement;
    const appElement = target.closest<HTMLElement>('[data-desktop-app]');
    if (appElement) {
      const appId = appElement.dataset.desktopApp as PawAppId;
      const appIds = selectedApps.has(appId) ? [...selectedApps] : [appId];
      if (!selectedApps.has(appId)) setSelectedApps(new Set([appId]));
      setContextMenu({
        kind: 'apps',
        appIds,
        label: appIds.length === 1 ? pawApp(appId).label : `${appIds.length} 个 App`,
        x: event.clientX,
        y: event.clientY,
      });
      return;
    }
    const windowElement = target.closest<HTMLElement>('[data-paw-window-id]');
    if (windowElement) {
      const windowId = windowElement.dataset.pawWindowId ?? '';
      const node = api.getState().windows[windowId];
      if (node) {
        setContextMenu({ kind: 'window', windowId, label: node.title, x: event.clientX, y: event.clientY });
        return;
      }
    }
    setSelectedApps(new Set());
    setContextMenu({ kind: 'desktop', x: event.clientX, y: event.clientY });
  }, [api, selectedApps]);

  const startLasso = useCallback((event: ReactPointerEvent<HTMLElement>) => {
    if (event.button !== 0) return;
    const target = event.target as HTMLElement;
    if (target.closest('button, input, textarea, select, a, [data-paw-window-id], [data-paw-text-selection], [data-paw-desktop-panel]')) return;
    event.preventDefault();
    setContextMenu(null);
    const viewport = viewportRef.current;
    if (!viewport) return;
    const viewportBounds = viewport.getBoundingClientRect();
    const origin = { x: event.clientX, y: event.clientY };
    const additive = event.shiftKey || event.metaKey || event.ctrlKey;
    const baseline = additive ? new Set(selectedApps) : new Set<PawAppId>();
    if (!additive) setSelectedApps(new Set());
    event.currentTarget.setPointerCapture?.(event.pointerId);
    /* Desktop identities cannot move while the lasso is being drawn, so their
     * boxes are measured once at the gesture edge. Re-reading them per frame
     * forced a synchronous layout of the whole desktop on every sample — the
     * single most expensive thing a rubber-band selection could do. */
    const targets = Array.from(viewport.querySelectorAll<HTMLElement>('[data-desktop-app]'))
      .map((element) => ({ appId: element.dataset.desktopApp as PawAppId, rect: element.getBoundingClientRect() }));
    let frame = 0;
    let latest: PointerEvent | null = null;
    const apply = () => {
      frame = 0;
      const moveEvent = latest;
      if (!moveEvent) return;
      const left = Math.min(origin.x, moveEvent.clientX);
      const top = Math.min(origin.y, moveEvent.clientY);
      const right = Math.max(origin.x, moveEvent.clientX);
      const bottom = Math.max(origin.y, moveEvent.clientY);
      if (right - left < 3 && bottom - top < 3) return;
      setLasso({
        x: left - viewportBounds.left,
        y: top - viewportBounds.top,
        width: right - left,
        height: bottom - top,
      });
      const next = new Set(baseline);
      for (const { appId, rect } of targets) {
        if (rect.left < right && rect.right > left && rect.top < bottom && rect.bottom > top) next.add(appId);
      }
      // Most frames of a drag cross no new identity; keeping the same Set
      // keeps the Wayfinder out of the frame entirely.
      setSelectedApps((current) => sameAppSelection(current, next) ? current : next);
    };
    const move = (moveEvent: PointerEvent) => {
      latest = moveEvent;
      if (!frame) frame = window.requestAnimationFrame(apply);
    };
    const finish = () => {
      if (frame) window.cancelAnimationFrame(frame);
      apply();
      setLasso(null);
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', finish);
      window.removeEventListener('pointercancel', finish);
    };
    window.addEventListener('pointermove', move, { passive: true });
    window.addEventListener('pointerup', finish);
    window.addEventListener('pointercancel', finish);
  }, [selectedApps]);

  const menuItems = useMemo<readonly PawContextMenuItem[]>(() => {
    if (!contextMenu || contextMenu.kind === 'desktop') {
      return [
        { id: 'new-agent', label: '新建 Agent 工作', icon: <Bot size={15} />, action: () => openApp('agent') },
        { id: 'browser', label: '打开 Browser', icon: <Earth size={15} />, action: () => openApp('browser') },
        { id: 'launchpad', label: '全部 App', icon: <LayoutGrid size={15} />, separatorBefore: true, action: () => api.getState().setLaunchpadOpen(true) },
        { id: 'settings', label: '系统设置', icon: <Settings size={15} />, action: () => openApp('system-settings') },
        {
          id: 'close-all-windows',
          label: '关闭全部窗口',
          icon: <X size={15} />,
          danger: true,
          separatorBefore: true,
          disabled: menuWindows.length === 0,
          action: () => api.getState().closeAllWindows(),
        },
      ];
    }
    if (contextMenu.kind === 'menubar') {
      if (!activeWindowId || !activeAppId) {
        return [
          { id: 'launchpad', label: '全部 App', icon: <LayoutGrid size={15} />, action: () => api.getState().setLaunchpadOpen(true) },
          { id: 'new-agent', label: '新建 Agent 工作', icon: <Bot size={15} />, action: () => openApp('agent') },
          { id: 'settings', label: '系统设置', icon: <Settings size={15} />, action: () => openApp('system-settings') },
        ];
      }
      return [
        { id: 'hide', label: '隐藏窗口', icon: <Minus size={15} />, action: () => api.getState().minimizeWindow(activeWindowId) },
        { id: 'overview', label: '窗口总览', icon: <PanelsTopLeft size={15} />, action: () => api.getState().setOverviewOpen(true) },
        {
          id: 'close',
          label: '关闭窗口',
          icon: <X size={15} />,
          danger: true,
          separatorBefore: true,
          action: () => api.getState().closeWindow(activeWindowId),
        },
      ];
    }
    if (contextMenu.kind === 'apps') {
      const openWindowCount = menuWindows.filter((node) => contextMenu.appIds.includes(node.appId)).length;
      return [
        {
          id: 'open-apps',
          label: contextMenu.appIds.length === 1 ? `打开 ${contextMenu.label}` : `打开 ${contextMenu.appIds.length} 个 App`,
          icon: <ArrowUpRight size={15} />,
          action: () => contextMenu.appIds.forEach(openApp),
        },
        {
          id: 'close-app-windows',
          label: contextMenu.appIds.length === 1
            ? `关闭 ${contextMenu.label} 的全部窗口`
            : `关闭 ${contextMenu.appIds.length} 个 App 的全部窗口`,
          icon: <X size={15} />,
          danger: true,
          separatorBefore: true,
          disabled: openWindowCount === 0,
          action: () => contextMenu.appIds.forEach((appId) => api.getState().closeAppWindows(appId)),
        },
      ];
    }
    const node = menuWindows.find((candidate) => candidate.id === contextMenu.windowId);
    return [
      { id: 'minimize', label: '最小化', icon: <Minus size={15} />, disabled: !node, action: () => api.getState().minimizeWindow(contextMenu.windowId) },
      { id: 'maximize', label: node?.placement === 'maximized' ? '还原窗口' : '最大化', icon: <Maximize2 size={15} />, disabled: !node, action: () => api.getState().toggleMaximize(contextMenu.windowId) },
      { id: 'snap-left', label: '靠左排列', icon: <PanelLeft size={15} />, disabled: !node, action: () => api.getState().snapWindow(contextMenu.windowId, 'left') },
      { id: 'snap-right', label: '靠右排列', icon: <PanelRight size={15} />, disabled: !node, action: () => api.getState().snapWindow(contextMenu.windowId, 'right') },
      {
        id: 'close-app-windows',
        label: node ? `关闭 ${pawApp(node.appId).label} 的全部窗口` : '关闭这个 App 的全部窗口',
        icon: <X size={15} />,
        danger: true,
        separatorBefore: true,
        disabled: !node,
        action: () => {
          if (node) api.getState().closeAppWindows(node.appId);
        },
      },
      {
        id: 'close',
        label: '关闭窗口',
        icon: <X size={15} />,
        danger: true,
        disabled: !node,
        action: () => {
          api.getState().closeWindow(contextMenu.windowId);
        },
      },
    ];
  }, [activeAppId, activeWindowId, api, contextMenu, menuWindows]);
  const menuBarLabel = activeAppId ? pawApp(activeAppId).label : '桌面';
  const openMenuBarMenu = (event: ReactMouseEvent<HTMLButtonElement>) => {
    event.preventDefault();
    event.stopPropagation();
    if (contextMenu?.kind === 'menubar') {
      setContextMenu(null);
      return;
    }
    const rect = event.currentTarget.getBoundingClientRect();
    setContextMenu({ kind: 'menubar', x: rect.left, y: rect.bottom + 6 });
  };
  return (
    <div
      className="paw-desktop"
      data-ambient-paused={ambientPaused || undefined}
      data-collaboration-focus={collaborationFocus || undefined}
      data-overview={overviewOpen || undefined}
      onContextMenu={openContextMenu}
    >
      <header className="paw-menu-bar">
        <button aria-label="打开全部 App" className="paw-system-mark" onClick={toggleLaunchpad} type="button"><PawBrandMark size={15} /><span className="paw-brand-wordmark">PAW</span></button>
        <button
          aria-expanded={contextMenu?.kind === 'menubar'}
          aria-haspopup="menu"
          aria-label={`${menuBarLabel} 菜单`}
          className="paw-menu-app"
          data-app={activeAppId ?? undefined}
          data-idle={activeAppId ? undefined : true}
          onClick={openMenuBarMenu}
          ref={menuAppRef}
          type="button"
        >
          {activeAppId ? <PawAppIcon appId={activeAppId} size={14} /> : null}
          <span>{menuBarLabel}</span>
        </button>
        <div className="paw-menu-status"><ConnectionIndicator /><PawMenuClock /></div>
      </header>

      <main className="paw-desktop-viewport" onPointerDown={startLasso} ref={viewportRef}>
        <Wayfinder onOpen={openApp} onSelect={selectApp} selectedApps={selectedApps} />
        <PawWindowLayer />
        {lasso ? <div className="paw-selection-lasso" data-testid="paw-selection-lasso" style={{ left: lasso.x, top: lasso.y, width: lasso.width, height: lasso.height }} /> : null}
      </main>
      {collaborationFocus ? <button
        className="paw-collaboration-focus-exit"
        onClick={() => api.getState().setCollaborationFocusGroup(null)}
        type="button"
      ><X size={14} />退出协作聚焦</button> : null}
      <PawDock
        activeAppId={activeAppId}
        onLaunchpad={toggleLaunchpad}
        onOpen={openApp}
        onOverview={toggleOverview}
        overviewOpen={overviewOpen}
      />
      {launchpadOpen ? <PawLaunchpad onClose={closeLaunchpad} onOpen={openApp} /> : null}
      {contextMenu ? (
        <PawContextMenu
          anchor={contextMenu.kind === 'menubar' ? menuAppRef : undefined}
          ariaLabel={contextMenuAriaLabel(contextMenu, activeAppId)}
          items={menuItems}
          onClose={() => setContextMenu(null)}
          x={contextMenu.x}
          y={contextMenu.y}
        />
      ) : null}
    </div>
  );
}

/* One subscription to the platform visibility signal: a hidden document can
 * never be watched, so the wallpaper weather pauses with it. */
function useDocumentHidden(): boolean {
  const [hidden, setHidden] = useState(() => typeof document !== 'undefined' && document.visibilityState === 'hidden');
  useEffect(() => {
    const update = () => setHidden(document.visibilityState === 'hidden');
    document.addEventListener('visibilitychange', update);
    return () => document.removeEventListener('visibilitychange', update);
  }, []);
  return hidden;
}

/* The half-minute clock tick lives in its own leaf so it re-renders one
 * <span>, never the whole desktop chrome. */
function PawMenuClock() {
  const [clock, setClock] = useState(() => timeLabel());
  useEffect(() => {
    const timer = window.setInterval(() => setClock(timeLabel()), 30_000);
    return () => window.clearInterval(timer);
  }, []);
  return <span>{clock}</span>;
}

/* The Wayfinder is the desktop's heaviest resting subtree: the wallpaper, the
 * lede, the identity rail and the recent-work panel. Its props are the two
 * stable callbacks plus the selection set, so clock ticks, menus, focus
 * changes and every lasso frame that crosses no new identity leave it
 * untouched. */
const Wayfinder = memo(function Wayfinder({ onOpen, onSelect, selectedApps }: {
  onOpen: (id: PawAppId) => void;
  onSelect: (id: PawAppId, additive: boolean) => void;
  selectedApps: ReadonlySet<PawAppId>;
}) {
  const desktopApps: PawAppId[] = ['project-workbench', 'agent', 'files', 'browser', 'terminal'];
  const shortcutsRef = useRef<HTMLDivElement>(null);
  const running = usePawRunningApps();
  // Roving arrows walk the shortcut list like a real desktop: focus moves
  // between identities without tabbing out of the Wayfinder, and Enter on the
  // focused identity still opens it (owned by the per-button handler below).
  const walkShortcuts = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (!['ArrowDown', 'ArrowUp', 'ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    const host = shortcutsRef.current;
    if (!host) return;
    const buttons = Array.from(host.querySelectorAll<HTMLButtonElement>('button[data-desktop-app]'));
    const current = buttons.indexOf(document.activeElement as HTMLButtonElement);
    if (current === -1) return;
    event.preventDefault();
    const forward = event.key === 'ArrowDown' || event.key === 'ArrowRight';
    const next = event.key === 'Home'
      ? 0
      : event.key === 'End'
      ? buttons.length - 1
      : Math.min(Math.max(current + (forward ? 1 : -1), 0), buttons.length - 1);
    buttons[next]?.focus();
  };
  return (
    <section className="paw-wayfinder" aria-label="项目场">
      <div aria-hidden="true" className="paw-field-media">
        <PawCompositionField effects />
      </div>
      {/* The first viewport is one composition, not two matching corner cards
          around an empty middle: a single column states what the machine is
          for and indexes the identities directly underneath that sentence,
          and recent work keeps the opposite corner as the one live
          instrument. The column's ground is a feathered opening in the fog,
          so the type belongs to the picture instead of sitting on a card. */}
      <div className="paw-field-stage">
        <PawFieldLede onOpen={onOpen} />
        {/* The identity rail is the lede's index: same column, same ground.
            Each tile keeps the selection/open contracts (click selects,
            double-click or Enter opens) and mirrors the Dock's
            open/minimized running language so live work is visible from the
            desktop. */}
        <div className="paw-desktop-shortcuts" aria-label="桌面 App" onKeyDown={walkShortcuts} ref={shortcutsRef}>
          {desktopApps.map((id) => {
            const open = running.open.has(id);
            const minimizedOnly = open && !running.visible.has(id);
            return (
              <button
                aria-selected={selectedApps.has(id) || undefined}
                data-app={id}
                data-desktop-app={id}
                data-minimized={minimizedOnly || undefined}
                data-open={open || undefined}
                key={id}
                onClick={(event) => onSelect(id, event.shiftKey || event.metaKey || event.ctrlKey)}
                onDoubleClick={() => onOpen(id)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') onOpen(id);
                }}
                title={minimizedOnly ? `${pawApp(id).shortLabel} · 已最小化` : open ? `${pawApp(id).shortLabel} · 运行中` : undefined}
                type="button"
              >
                <span><PawAppIcon appId={id} size={28} /></span>
                <strong>{pawApp(id).shortLabel}</strong>
                <i aria-hidden="true" />
              </button>
            );
          })}
        </div>
      </div>
      <PawWayfinderWork />
    </section>
  );
});

/* One projection answers "which Apps are running, which are hidden" for both
 * the Wayfinder list and the Dock. The sorted string signature keeps the
 * store subscription referentially stable, so rows and pills re-render only
 * when an App's running state actually changes. */
function usePawRunningApps(): { open: ReadonlySet<PawAppId>; visible: ReadonlySet<PawAppId> } {
  const signature = usePawDesktopStore((state) => Object.values(state.windows)
    .map((node) => `${node.appId}\u0001${node.minimized ? '1' : '0'}`)
    .sort()
    .join('\u0000'));
  return useMemo(() => {
    const open = new Set<PawAppId>();
    const visible = new Set<PawAppId>();
    for (const item of signature.split('\u0000').filter(Boolean)) {
      const [appId, minimized] = item.split('\u0001') as [PawAppId, string];
      open.add(appId);
      if (minimized === '0') visible.add(appId);
    }
    return { open, visible };
  }, [signature]);
}

/* The shelf answers the pointer directly through dock-magnification's style
 * writes, so React only owns its resting content: which App is current, which
 * are running, whether the overview is open. Everything else on the desktop
 * re-renders without touching it. */
const PawDock = memo(function PawDock({ activeAppId, onLaunchpad, onOpen, onOverview, overviewOpen }: {
  activeAppId: PawAppId | null;
  onLaunchpad: () => void;
  onOpen: (id: PawAppId) => void;
  onOverview: () => void;
  overviewOpen: boolean;
}) {
  const dockRef = useRef<HTMLElement>(null);
  useDockMagnification(dockRef);
  const dockState = usePawRunningApps();
  return (
    <nav aria-label="PAWOS 工具架" className="paw-dock" ref={dockRef}>
      {pawDockAppIds.map((appId) => {
        const minimizedOnly = dockState.open.has(appId) && !dockState.visible.has(appId);
        return (
          <button
            aria-current={activeAppId === appId ? 'page' : undefined}
            aria-label={pawApp(appId).label}
            data-app={appId}
            data-desktop-app={appId}
            data-minimized={minimizedOnly || undefined}
            data-open={dockState.open.has(appId) || undefined}
            key={appId}
            onClick={() => onOpen(appId)}
            title={minimizedOnly ? `${pawApp(appId).label} 已最小化，点击恢复` : undefined}
            type="button"
          >
            <PawAppIcon appId={appId} size={32} />
            <span aria-hidden="true" className="paw-dock-tip">{minimizedOnly ? `${pawApp(appId).label} · 已最小化` : pawApp(appId).label}</span>
          </button>
        );
      })}
      <i aria-hidden="true" />
      <button aria-label="窗口总览" aria-pressed={overviewOpen} className="paw-dock-overview" onClick={onOverview} type="button"><PanelsTopLeft size={19} /><span aria-hidden="true" className="paw-dock-tip">窗口总览</span></button>
      <button aria-label="全部 App" className="paw-dock-launchpad" onClick={onLaunchpad} type="button"><Grid3X3 size={19} /><span aria-hidden="true" className="paw-dock-tip">全部 App</span></button>
    </nav>
  );
});

/* Magnetic Dock conduction. A rAF-throttled pointer stream feeds the pure
 * magnet geometry in dock-magnification.ts (cosine grow, neighbour push and
 * the sine gather toward the pointer) and lands as two custom properties per
 * shelf child, driving transform-only styles. The shelf is measured once per
 * hover on pointerenter — the resting layout cannot change while the pointer
 * conducts, because every response below is a transform — so the per-frame
 * path is pure math plus style writes: no layout reads, no repaints, and
 * dragging a window across the Dock cannot flicker. Coarse pointers, the
 * narrow scrolling Dock, a live window drag/resize, and both reduced-motion
 * signals opt out entirely, leaving the resting shelf untouched. */
function useDockMagnification(dockRef: RefObject<HTMLElement | null>) {
  useEffect(() => {
    const dock = dockRef.current;
    if (!dock) return undefined;
    const finePointer = window.matchMedia('(hover: hover) and (pointer: fine)');
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
    const wideShelf = window.matchMedia('(min-width: 821px)');
    let frame = 0;
    let pointerX = 0;
    let shelf: { items: HTMLElement[]; centers: number[] } | null = null;
    const children = () => Array.from(dock.children).filter((child): child is HTMLElement => child instanceof HTMLElement);
    const measure = () => {
      const items = children();
      const dockLeft = dock.getBoundingClientRect().left;
      shelf = { items, centers: items.map((item) => dockLeft + item.offsetLeft + item.offsetWidth / 2) };
    };
    const rest = () => {
      if (frame) window.cancelAnimationFrame(frame);
      frame = 0;
      shelf = null;
      delete dock.dataset.magnify;
      for (const child of children()) {
        child.style.removeProperty('--paw-dock-mag');
        child.style.removeProperty('--paw-dock-shift');
      }
    };
    const apply = () => {
      frame = 0;
      if (!shelf) measure();
      const { items, centers } = shelf!;
      const { mag, shift } = dockMagnetics(centers, pointerX);
      items.forEach((item, index) => {
        item.style.setProperty('--paw-dock-mag', mag[index].toFixed(4));
        item.style.setProperty('--paw-dock-shift', shift[index].toFixed(2));
      });
    };
    const windowGestureOwnsPointer = () => Boolean(dock.closest<HTMLElement>('.paw-desktop-root')?.dataset.windowInteraction);
    const conducting = () => {
      if (!finePointer.matches || !wideShelf.matches || reducedMotion.matches) return false;
      if (windowGestureOwnsPointer()) return false;
      return document.documentElement.getAttribute('data-reduce-motion') !== 'true';
    };
    const enter = () => {
      if (conducting()) measure();
    };
    const move = (event: PointerEvent) => {
      if (!conducting()) {
        if (dock.dataset.magnify) rest();
        return;
      }
      pointerX = event.clientX;
      dock.dataset.magnify = 'true';
      if (!frame) frame = window.requestAnimationFrame(apply);
    };
    dock.addEventListener('pointerenter', enter);
    dock.addEventListener('pointermove', move);
    dock.addEventListener('pointerleave', rest);
    dock.addEventListener('pointercancel', rest);
    return () => {
      dock.removeEventListener('pointerenter', enter);
      dock.removeEventListener('pointermove', move);
      dock.removeEventListener('pointerleave', rest);
      dock.removeEventListener('pointercancel', rest);
      rest();
    };
  }, [dockRef]);
}

function PawLaunchpad({ onClose, onOpen }: { onClose: () => void; onOpen: (id: PawAppId) => void }) {
  const [query, setQuery] = useState('');
  const searchRef = useRef<HTMLInputElement>(null);
  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return pawApps.filter((app) => {
      if (!needle) return true;
      return [app.label, app.shortLabel, app.tagline, app.id].some((part) => part.toLowerCase().includes(needle));
    });
  }, [query]);
  const groups = useMemo(() => {
    // A running index across groups drives the cascade arrival: each group
    // header takes its own beat and its tiles follow, so the archive opens as
    // one choreography that reads in document order — section, then contents.
    let order = 0;
    return LAUNCHPAD_GROUP_ORDER.flatMap((kind) => {
      const apps = filtered.filter((app) => launchpadGroup(app) === kind);
      return apps.length
        ? [{ kind, label: LAUNCHPAD_GROUP_LABEL[kind], order: order++, apps: apps.map((app) => ({ app, order: order++ })) }]
        : [];
    });
  }, [filtered]);
  useEffect(() => {
    searchRef.current?.focus();
  }, []);
  return (
    <div
      aria-label="全部 App"
      aria-modal="true"
      className="paw-launchpad"
      onKeyDown={(event) => {
        if (event.key === 'Escape' && query) {
          event.stopPropagation();
          setQuery('');
          return;
        }
        if (event.key === 'Enter' && filtered.length === 1) {
          event.preventDefault();
          onOpen(filtered[0].id);
        }
      }}
      onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}
      role="dialog"
    >
      <section>
        <header>
          <span className="paw-launchpad-title"><PawBrandMark size={16} /><b className="paw-brand-wordmark">PAW</b><span>全部 App</span></span>
          <input
            aria-label="搜索 App"
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索 App"
            ref={searchRef}
            type="search"
            value={query}
          />
          <button onClick={onClose} type="button">完成</button>
        </header>
        <div>
          {groups.length === 0 ? (
            <p className="paw-launchpad-empty">没有匹配的 App</p>
          ) : groups.map((group) => (
            <Fragment key={group.kind}>
              <h2 className="paw-launchpad-group" style={{ '--paw-tile-i': group.order } as CSSProperties}>{group.label}</h2>
              {group.apps.map(({ app, order }) => (
                <button data-app={app.id} key={app.id} onClick={() => onOpen(app.id)} style={{ '--paw-tile-i': order } as CSSProperties} type="button">
                  <span><PawAppIcon appId={app.id} size={48} /></span>
                  <strong>{app.label}</strong>
                  <small>{app.tagline}</small>
                </button>
              ))}
            </Fragment>
          ))}
        </div>
      </section>
    </div>
  );
}

function timeLabel(): string {
  return new Intl.DateTimeFormat('zh-CN', {
    month: 'numeric',
    day: 'numeric',
    weekday: 'short',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(new Date());
}

function sameAppSelection(left: ReadonlySet<PawAppId>, right: ReadonlySet<PawAppId>): boolean {
  if (left.size !== right.size) return false;
  for (const appId of right) {
    if (!left.has(appId)) return false;
  }
  return true;
}

function launchpadGroup(app: PawAppDefinition): (typeof LAUNCHPAD_GROUP_ORDER)[number] {
  if (app.id === 'memory' || app.id === 'knowledge') return 'library';
  if (app.id === 'project-workbench' || app.kind === 'agent') return 'work';
  if (app.kind === 'system') return 'system';
  return 'tool';
}

function contextMenuAriaLabel(menu: PawMenuState, activeAppId: PawAppId | null): string {
  if (menu.kind === 'desktop') return '桌面菜单';
  if (menu.kind === 'menubar') return activeAppId ? `${pawApp(activeAppId).label} 菜单` : '桌面菜单';
  return `${menu.label} 菜单`;
}
