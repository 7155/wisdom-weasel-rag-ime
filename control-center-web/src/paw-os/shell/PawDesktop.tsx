import { ArrowUpRight, Bot, Earth, Grid3X3, LayoutGrid, Maximize2, Minus, PanelLeft, PanelRight, PanelsTopLeft, Settings, X } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState, type MouseEvent as ReactMouseEvent, type PointerEvent as ReactPointerEvent } from 'react';
import { ConnectionIndicator } from '@/components/feedback';
import { pawApp, pawApps, pawDockAppIds, type PawAppId } from '../runtime/app-registry';
import { usePawDesktopApi, usePawDesktopStore } from '../runtime/desktop-context';
import { PawAppIcon } from './PawAppIcon';
import { PawCompositionField } from './PawCompositionField';
import { pulsePawComposition } from '../runtime/composition-pulse';
import { PawContextMenu, type PawContextMenuItem } from './PawContextMenu';
import { PawWindowLayer } from './PawWindowLayer';
import { pawBrowserHost } from '../apps/paw-browser-host';

type PawMenuTarget =
  | { kind: 'desktop' }
  | { kind: 'apps'; appIds: PawAppId[]; label: string }
  | { kind: 'window'; windowId: string; label: string };

type PawMenuState = PawMenuTarget & { x: number; y: number };
type PawSelectionRect = { x: number; y: number; width: number; height: number };

export function PawDesktop() {
  const api = usePawDesktopApi();
  const activeWindowId = usePawDesktopStore((state) => state.activeWindowId);
  const activeAppId = usePawDesktopStore((state) => (
    activeWindowId ? state.windows[activeWindowId]?.appId ?? null : null
  ));
  const launchpadOpen = usePawDesktopStore((state) => state.launchpadOpen);
  const overviewOpen = usePawDesktopStore((state) => state.overviewOpen);
  const windows = usePawDesktopStore((state) => state.windows);
  const collaborationFocusGroup = usePawDesktopStore((state) => state.collaborationFocusGroup);
  const collaborationFocus = Boolean(collaborationFocusGroup);
  const menuAppId = activeAppId ?? 'project-workbench';
  const [clock, setClock] = useState(() => timeLabel());
  const [selectedApps, setSelectedApps] = useState<ReadonlySet<PawAppId>>(() => new Set());
  const [contextMenu, setContextMenu] = useState<PawMenuState | null>(null);
  const [lasso, setLasso] = useState<PawSelectionRect | null>(null);
  const viewportRef = useRef<HTMLElement>(null);
  useEffect(() => {
    const timer = window.setInterval(() => setClock(timeLabel()), 30_000);
    return () => window.clearInterval(timer);
  }, []);
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        setContextMenu(null);
        api.getState().setLaunchpadOpen(!api.getState().launchpadOpen);
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

  const openApp = (appId: PawAppId) => {
    const state = api.getState();
    const existingWindowId = [...state.stack].reverse().find((windowId) => state.windows[windowId]?.appId === appId)
      ?? Object.values(state.windows).find((node) => node.appId === appId)?.id;
    if (existingWindowId) state.focusWindow(existingWindowId);
    else state.openApp(appId, { title: pawApp(appId).label });
    state.setLaunchpadOpen(false);
    pulsePawComposition('app', .72);
    window.history.replaceState(null, '', `${window.location.search}#${pawApp(appId).route}`);
  };
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
      const node = windows[windowId];
      if (node) {
        setContextMenu({ kind: 'window', windowId, label: node.title, x: event.clientX, y: event.clientY });
        return;
      }
    }
    setSelectedApps(new Set());
    setContextMenu({ kind: 'desktop', x: event.clientX, y: event.clientY });
  }, [selectedApps, windows]);

  const startLasso = useCallback((event: ReactPointerEvent<HTMLElement>) => {
    if (event.button !== 0) return;
    const target = event.target as HTMLElement;
    if (target.closest('button, input, textarea, select, a, [data-paw-window-id], [data-paw-text-selection]')) return;
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
    const move = (moveEvent: PointerEvent) => {
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
      viewport.querySelectorAll<HTMLElement>('[data-desktop-app]').forEach((element) => {
        const rect = element.getBoundingClientRect();
        if (rect.left < right && rect.right > left && rect.top < bottom && rect.bottom > top) {
          next.add(element.dataset.desktopApp as PawAppId);
        }
      });
      setSelectedApps(next);
    };
    const finish = () => {
      setLasso(null);
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', finish);
      window.removeEventListener('pointercancel', finish);
    };
    window.addEventListener('pointermove', move);
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
          disabled: Object.keys(windows).length === 0,
          action: () => api.getState().closeAllWindows(),
        },
      ];
    }
    if (contextMenu.kind === 'apps') {
      const openWindowCount = Object.values(windows).filter((node) => contextMenu.appIds.includes(node.appId)).length;
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
    const node = windows[contextMenu.windowId];
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
  }, [api, contextMenu, windows]);
  return (
    <div
      className="paw-desktop"
      data-collaboration-focus={collaborationFocus || undefined}
      data-overview={overviewOpen || undefined}
      onContextMenu={openContextMenu}
    >
      <header className="paw-menu-bar">
        <button aria-label="打开全部 App" className="paw-system-mark" onClick={() => api.getState().setLaunchpadOpen(!launchpadOpen)} type="button"><span className="paw-brand-wordmark">PAW</span></button>
        <span className="paw-menu-app"><PawAppIcon appId={menuAppId} size={14} /><span>{activeAppId ? pawApp(activeAppId).label : '项目'}</span></span>
        <div className="paw-menu-status"><ConnectionIndicator /><span>{clock}</span></div>
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
        onLaunchpad={() => api.getState().setLaunchpadOpen(!launchpadOpen)}
        onOpen={openApp}
        onOverview={() => {
          pulsePawComposition('system', .58);
          api.getState().setOverviewOpen(!overviewOpen);
        }}
        overviewOpen={overviewOpen}
      />
      {launchpadOpen ? <PawLaunchpad onClose={() => api.getState().setLaunchpadOpen(false)} onOpen={openApp} /> : null}
      {contextMenu ? (
        <PawContextMenu
          ariaLabel={contextMenu.kind === 'desktop' ? '桌面菜单' : `${contextMenu.label} 菜单`}
          items={menuItems}
          onClose={() => setContextMenu(null)}
          x={contextMenu.x}
          y={contextMenu.y}
        />
      ) : null}
    </div>
  );
}

function Wayfinder({ onOpen, onSelect, selectedApps }: {
  onOpen: (id: PawAppId) => void;
  onSelect: (id: PawAppId, additive: boolean) => void;
  selectedApps: ReadonlySet<PawAppId>;
}) {
  const desktopApps: PawAppId[] = ['project-workbench', 'agent', 'files', 'browser', 'terminal'];
  return (
    <section className="paw-wayfinder" aria-label="Project Field">
      <div aria-hidden="true" className="paw-field-media">
        <PawCompositionField effects />
      </div>
      <div className="paw-desktop-shortcuts" aria-label="桌面 App">
        {desktopApps.map((id) => (
          <button
            aria-selected={selectedApps.has(id) || undefined}
            data-app={id}
            data-desktop-app={id}
            key={id}
            onClick={(event) => onSelect(id, event.shiftKey || event.metaKey || event.ctrlKey)}
            onDoubleClick={() => onOpen(id)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') onOpen(id);
            }}
            type="button"
          >
            <span><PawAppIcon appId={id} size={48} /></span>
            <strong>{pawApp(id).shortLabel}</strong>
          </button>
        ))}
      </div>
    </section>
  );
}

function PawDock({ activeAppId, onLaunchpad, onOpen, onOverview, overviewOpen }: {
  activeAppId: PawAppId | null;
  onLaunchpad: () => void;
  onOpen: (id: PawAppId) => void;
  onOverview: () => void;
  overviewOpen: boolean;
}) {
  // 运行状态必须诚实：某个 App 只剩最小化窗口时，Dock 不再显示与
  // 可见窗口相同的实心圆点，而是空心圆点表示“仍在运行，已收起”。
  const dockStateSignature = usePawDesktopStore((state) => Object.values(state.windows)
    .map((node) => `${node.appId}\u0001${node.minimized ? '1' : '0'}`)
    .sort()
    .join('\u0000'));
  const dockState = useMemo(() => {
    const open = new Set<PawAppId>();
    const visible = new Set<PawAppId>();
    for (const item of dockStateSignature.split('\u0000').filter(Boolean)) {
      const [appId, minimized] = item.split('\u0001') as [PawAppId, string];
      open.add(appId);
      if (minimized === '0') visible.add(appId);
    }
    return { open, visible };
  }, [dockStateSignature]);
  return (
    <nav aria-label="PAWOS 工具架" className="paw-dock">
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
          </button>
        );
      })}
      <i aria-hidden="true" />
      <button aria-label="窗口总览" aria-pressed={overviewOpen} className="paw-dock-overview" onClick={onOverview} type="button"><PanelsTopLeft size={19} /></button>
      <button aria-label="全部 App" className="paw-dock-launchpad" onClick={onLaunchpad} type="button"><Grid3X3 size={19} /></button>
    </nav>
  );
}

function PawLaunchpad({ onClose, onOpen }: { onClose: () => void; onOpen: (id: PawAppId) => void }) {
  return <div className="paw-launchpad" role="dialog" aria-label="全部 App" aria-modal="true" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}><section><header><span className="paw-launchpad-title"><b className="paw-brand-wordmark">PAW</b><span>全部 App</span></span><button onClick={onClose} type="button">完成</button></header><div>{pawApps.map((app) => <button data-app={app.id} key={app.id} onClick={() => onOpen(app.id)} type="button"><span><PawAppIcon appId={app.id} size={48} /></span><strong>{app.label}</strong><small>{app.tagline}</small></button>)}</div></section></div>;
}

function timeLabel(): string {
  return new Intl.DateTimeFormat('zh-CN', { weekday: 'short', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date());
}
