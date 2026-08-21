import {
  BatteryMedium,
  ChevronRight,
  Command,
  Compass,
  Grid3X3,
  Home,
  Layers3,
  LoaderCircle,
  Maximize2,
  Minus,
  Search,
  Sparkles,
  Wifi,
  X,
} from 'lucide-react';
import {
  useEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
  useSyncExternalStore,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from 'react';
import { routeRegistry, type RouteId } from '@/app/route-registry';
import { prefetchRoute, router } from '@/app/router';
import { ConnectionIndicator, GlobalNoticeRegion } from '@/components/feedback';
import { useHashRoute } from '@/components/layout/useHashRoute';
import { usePawOsAppearance } from '@/design/paw-os-themes';
import { pawOsAppIcons } from '@/features/paw-os/app-icons';
import {
  pawOsApp,
  pawOsAppForRoute,
  pawOsAppRegistry,
  primaryDockAppIds,
  routePath,
  wayfinderRouteId,
  type PawOsAppId,
  type PawOsAppDefinition,
} from '@/features/paw-os/model/app-registry';
import {
  createPawOsDesktopState,
  createPawOsWindow,
  pawOsDesktopReducer,
  windowZIndex,
  type PawOsDesktopAction,
  type PawOsDesktopState,
  type PawOsDesktopWindow,
  type PawOsRect,
} from '@/features/paw-os/model/desktop';
import { useProductIdentity } from '@/features/identity/product-identity';
import { PawOsAppSurfaceProvider } from '@/features/paw-os/surface-context';
import './paw-os-shell.css';

export function PawOsShell({ children }: { children: ReactNode }) {
  const activeRoute = useHashRoute();
  const appearance = usePawOsAppearance();
  const identity = useProductIdentity();
  const desktopRef = useRef<HTMLElement>(null);
  const routeApp = pawOsAppForRoute(activeRoute.id);
  const [state, dispatch] = useReducer(
    pawOsDesktopReducer,
    activeRoute,
    (route) => {
      const initialApp = pawOsAppForRoute(route.id);
      return createPawOsDesktopState({
        windows: initialApp ? [createPawOsWindow({
          appId: initialApp.id,
          title: initialApp.label,
          sequence: 0,
          surface: { width: 1440, height: 788 },
        })] : [],
      });
    },
  );
  const navigationState = useSyncExternalStore(
    router.subscribe,
    () => router.state.navigation.state,
    () => 'idle',
  );
  const routePending = navigationState !== 'idle';
  const activeWindow = state.windows.find((window) => window.id === state.activeWindowId) ?? null;

  useEffect(() => {
    document.title = `${routeApp?.label ?? 'Wayfinder'} · PAWOS`;
    if (!routeApp) return;
    dispatch({
      type: 'open',
      window: createPawOsWindow({
        appId: routeApp.id,
        title: routeApp.label,
        sequence: state.windows.length,
        surface: state.surface,
      }),
    });
    // A route change is the external App-open signal. Window geometry is only
    // presentation state and must not reopen a window the user just closed.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeRoute.id, routeApp?.id, routeApp?.label]);

  useEffect(() => {
    const desktop = desktopRef.current;
    if (!desktop) return undefined;
    const update = () => {
      dispatch({
        type: 'setSurface',
        width: desktop.clientWidth || window.innerWidth,
        height: desktop.clientHeight || Math.max(320, window.innerHeight - 36),
      });
    };
    update();
    if (typeof ResizeObserver === 'undefined') {
      window.addEventListener('resize', update);
      return () => window.removeEventListener('resize', update);
    }
    const observer = new ResizeObserver(update);
    observer.observe(desktop);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && state.overlay) {
        event.preventDefault();
        dispatch({ type: 'showOverlay', overlay: null });
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [state.overlay]);

  const activateApp = (appId: PawOsAppId) => {
    const app = pawOsApp(appId);
    const windowId = `${appId}:primary`;
    const existing = state.windows.find((window) => window.id === windowId);
    dispatch(existing
      ? { type: 'focus', windowId }
      : {
          type: 'open',
          window: createPawOsWindow({
            appId,
            title: app.label,
            sequence: state.windows.length,
            surface: state.surface,
          }),
        });
    if (app.defaultRouteId && activeRoute.id !== app.defaultRouteId) {
      window.location.hash = routePath(app.defaultRouteId);
    }
  };

  const closeWindow = (windowId: string) => {
    const remaining = [...state.stack]
      .reverse()
      .map((id) => state.windows.find((window) => window.id === id))
      .find((window) => window && window.id !== windowId && !window.minimized);
    dispatch({ type: 'close', windowId });
    const fallbackRouteId = remaining ? pawOsApp(remaining.appId).defaultRouteId : wayfinderRouteId;
    window.location.hash = fallbackRouteId ? routePath(fallbackRouteId) : routePath(wayfinderRouteId);
  };

  return (
    <div
      className="paw-os-shell"
      data-frontend-product="paw-os"
      data-paw-os-theme={appearance.theme}
    >
      <a className="paw-os-skip-link" href="#paw-os-workspace">跳到当前 App</a>
      <PawOsMenuBar
        activeApp={activeWindow ? pawOsApp(activeWindow.appId) : null}
        activeRouteLabel={activeRoute.label}
        identityName={identity.productName}
        onMissionControl={() => dispatch({ type: 'showOverlay', overlay: 'mission-control' })}
      />
      <main
        className="paw-os-desktop"
        data-window-count={state.windows.length}
        ref={desktopRef}
        data-testid="paw-os-desktop"
      >
        <div className="paw-os-wallpaper" aria-hidden="true">
          <div className="paw-os-wallpaper__orb paw-os-wallpaper__orb--one" />
          <div className="paw-os-wallpaper__orb paw-os-wallpaper__orb--two" />
          <span className="paw-os-wallpaper__signature">PAW<span>OS</span></span>
        </div>
        <PawOsSystemRail
          activeAppId={activeWindow?.appId ?? routeApp?.id ?? null}
          onActivate={activateApp}
          onLaunchpad={() => dispatch({ type: 'showOverlay', overlay: 'launchpad' })}
          onWayfinder={() => { window.location.hash = routePath(wayfinderRouteId); }}
        />
        <PawOsContextSidebar activeApp={routeApp} activeRouteId={activeRoute.id} />
        {!routeApp ? (
          <div className="paw-os-wayfinder" id="paw-os-workspace">
            <div className="paw-os-wayfinder__heading">
              <span><Compass aria-hidden="true" size={17} /> PROJECT FIELD</span>
              <strong>沿着项目继续工作</strong>
              <small>选择一个项目、文档或正在进行的任务；这里是桌面入口，不是普通 App。</small>
            </div>
            <div className="paw-os-wayfinder__runtime">{children}</div>
          </div>
        ) : null}
        <GlobalNoticeRegion />
        <div className="paw-os-window-layer" aria-label="打开的 App">
          {state.windows.map((desktopWindow) => (
            <PawOsWindow
              active={desktopWindow.id === state.activeWindowId}
              app={pawOsApp(desktopWindow.appId)}
              dispatch={dispatch}
              key={desktopWindow.id}
              state={state}
              window={desktopWindow}
              onClose={() => closeWindow(desktopWindow.id)}
            >
              {desktopWindow.appId === routeApp?.id ? (
                <PawOsAppSurfaceProvider
                  appId={desktopWindow.appId}
                  height={Math.max(0, desktopWindow.rect.height - 42)}
                  width={desktopWindow.rect.width}
                >
                  <div
                    aria-busy={routePending}
                    className="paw-os-app-window__runtime"
                    data-active-route={activeRoute.id}
                    id={desktopWindow.id === state.activeWindowId ? 'paw-os-workspace' : undefined}
                  >
                    {children}
                    {routePending ? (
                      <div className="paw-os-route-pending" role="status" aria-live="polite">
                        <LoaderCircle aria-hidden="true" className="ui-spin" size={18} />
                        <span>正在打开{activeRoute.label}</span>
                      </div>
                    ) : null}
                  </div>
                </PawOsAppSurfaceProvider>
              ) : pawOsApp(desktopWindow.appId).defaultRouteId ? (
                <PawOsSleepingApp app={pawOsApp(desktopWindow.appId)} onActivate={() => activateApp(desktopWindow.appId)} />
              ) : (
                <PawOsNativeAppPlaceholder app={pawOsApp(desktopWindow.appId)} />
              )}
            </PawOsWindow>
          ))}
        </div>
        {state.overlay === 'launchpad' ? (
          <PawOsLaunchpad
            activeAppId={routeApp?.id ?? null}
            onActivate={activateApp}
            onClose={() => dispatch({ type: 'showOverlay', overlay: null })}
          />
        ) : null}
        {state.overlay === 'mission-control' ? (
          <PawOsMissionControl
            state={state}
            onActivate={(desktopWindow) => activateApp(desktopWindow.appId)}
            onClose={() => dispatch({ type: 'showOverlay', overlay: null })}
          />
        ) : null}
      </main>
      <PawOsDock
        activeWindowId={state.activeWindowId}
        onActivate={activateApp}
        onLaunchpad={() => dispatch({ type: 'showOverlay', overlay: 'launchpad' })}
        windows={state.windows}
      />
    </div>
  );
}

function PawOsMenuBar({
  activeApp,
  activeRouteLabel,
  identityName,
  onMissionControl,
}: {
  activeApp: PawOsAppDefinition | null;
  activeRouteLabel: string;
  identityName: string;
  onMissionControl: () => void;
}) {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const interval = window.setInterval(() => setNow(new Date()), 30_000);
    return () => window.clearInterval(interval);
  }, []);
  return (
    <header className="paw-os-menubar">
      <div className="paw-os-menubar__left">
        <button className="paw-os-system-mark" type="button" aria-label="PAWOS 系统菜单"><Sparkles aria-hidden="true" size={15} /></button>
        <strong>PAWOS</strong>
        <span className="paw-os-menubar__app-name">{activeApp?.label ?? 'Wayfinder'}</span>
        <span className="paw-os-menubar__route-name">{activeRouteLabel}</span>
        <span className="paw-os-menubar__menu">文件</span>
        <span className="paw-os-menubar__menu">窗口</span>
        <span className="paw-os-menubar__menu">帮助</span>
      </div>
      <div className="paw-os-menubar__right">
        <button className="paw-os-menubar__action" onClick={onMissionControl} type="button" aria-label="窗口总览"><Layers3 aria-hidden="true" size={15} /><span>窗口</span></button>
        <Wifi aria-hidden="true" size={15} />
        <BatteryMedium aria-hidden="true" size={16} />
        <time dateTime={now.toISOString()}>{new Intl.DateTimeFormat('zh-CN', { weekday: 'short', hour: '2-digit', minute: '2-digit' }).format(now)}</time>
        <span className="paw-os-menubar__identity">{identityName}</span>
        <ConnectionIndicator />
      </div>
    </header>
  );
}

function PawOsSystemRail({
  activeAppId,
  onActivate,
  onLaunchpad,
  onWayfinder,
}: {
  activeAppId: PawOsAppId | null;
  onActivate: (appId: PawOsAppId) => void;
  onLaunchpad: () => void;
  onWayfinder: () => void;
}) {
  const coreApps: readonly PawOsAppId[] = ['project-workbench', 'agent', 'rooms', 'knowledge', 'input-studio'];
  const systemApps: readonly PawOsAppId[] = ['app-center', 'system-monitor', 'system-settings'];
  const appButton = (appId: PawOsAppId) => {
    const app = pawOsApp(appId);
    const Icon = pawOsAppIcons[appId];
    return (
      <button
        aria-label={`打开${app.label}`}
        className="paw-os-system-rail__app"
        data-active={activeAppId === appId || undefined}
        key={appId}
        onClick={() => onActivate(appId)}
        title={app.label}
        type="button"
      >
        <Icon aria-hidden="true" size={20} />
        <span>{app.shortLabel}</span>
      </button>
    );
  };
  return (
    <nav aria-label="PAWOS 系统栏" className="paw-os-system-rail">
      <button aria-label="返回 Project Field" className="paw-os-system-rail__home" onClick={onWayfinder} type="button">
        <Home aria-hidden="true" size={21} />
        <span>主页</span>
      </button>
      <div className="paw-os-system-rail__group">{coreApps.map(appButton)}</div>
      <div className="paw-os-system-rail__spacer" />
      <div className="paw-os-system-rail__group">{systemApps.map(appButton)}</div>
      <button aria-label="打开全部 App" className="paw-os-system-rail__home" onClick={onLaunchpad} type="button">
        <Grid3X3 aria-hidden="true" size={20} />
        <span>全部</span>
      </button>
    </nav>
  );
}

function PawOsContextSidebar({
  activeApp,
  activeRouteId,
}: {
  activeApp: PawOsAppDefinition | null;
  activeRouteId: RouteId;
}) {
  const Icon = activeApp ? pawOsAppIcons[activeApp.id] : Compass;
  const routes = activeApp
    ? activeApp.routeIds.map((routeId) => routeRegistry.find((route) => route.id === routeId)).filter(Boolean)
    : [];
  return (
    <aside className="paw-os-context-sidebar" data-wayfinder={!activeApp || undefined}>
      <header className="paw-os-context-sidebar__header">
        <span className="paw-os-context-sidebar__mark"><Icon aria-hidden="true" size={18} /></span>
        <div>
          <strong>{activeApp?.label ?? 'Project Field'}</strong>
          <small>{activeApp?.tagline ?? '项目、工作区与当前方向'}</small>
        </div>
      </header>
      {activeApp ? (
        <nav aria-label={`${activeApp.label}功能`} className="paw-os-context-sidebar__routes">
          {routes.map((route) => route ? (
            <button
              data-active={route.id === activeRouteId || undefined}
              key={route.id}
              onClick={() => { window.location.hash = route.path; }}
              type="button"
            >
              <span>{route.label}</span>
              <ChevronRight aria-hidden="true" size={14} />
            </button>
          ) : null)}
        </nav>
      ) : (
        <div className="paw-os-context-sidebar__wayfinder">
          <span className="paw-os-context-sidebar__section">当前项目</span>
          <button className="paw-os-context-sidebar__project" type="button">
            <span className="paw-os-project-glyph">P</span>
            <span><strong>Personal Agent Workbench</strong><small>正在开发 · 本机</small></span>
          </button>
          <span className="paw-os-context-sidebar__section">继续工作</span>
          <button type="button"><span>最近的 Session</span><ChevronRight aria-hidden="true" size={14} /></button>
          <button type="button"><span>正在进行的 Room</span><ChevronRight aria-hidden="true" size={14} /></button>
          <button type="button"><span>工作文档</span><ChevronRight aria-hidden="true" size={14} /></button>
        </div>
      )}
    </aside>
  );
}

function PawOsNativeAppPlaceholder({ app }: { app: PawOsAppDefinition }) {
  const Icon = pawOsAppIcons[app.id];
  return (
    <div className="paw-os-native-app">
      <span className="paw-os-app-icon paw-os-app-icon--hero" data-accent={app.accent}><Icon aria-hidden="true" size={30} /></span>
      <span className="paw-os-native-app__eyebrow">PAWOS NATIVE APP</span>
      <h2>{app.label}</h2>
      <p>{app.tagline}</p>
      <small>正在把 Tutti 的成熟交互适配到 PAW Runtime；不会复制 Tutti 的运行时所有权。</small>
    </div>
  );
}

function PawOsWindow({
  active,
  app,
  children,
  dispatch,
  onClose,
  state,
  window: desktopWindow,
}: {
  active: boolean;
  app: PawOsAppDefinition;
  children: ReactNode;
  dispatch: (action: PawOsDesktopAction) => void;
  onClose: () => void;
  state: PawOsDesktopState;
  window: PawOsDesktopWindow;
}) {
  const interactionRef = useRef<{ mode: 'move' | 'resize'; pointerX: number; pointerY: number; rect: PawOsRect } | null>(null);
  const [interaction, setInteraction] = useState<'move' | 'resize' | null>(null);
  const Icon = pawOsAppIcons[app.id];
  const startInteraction = (event: ReactPointerEvent<HTMLElement>, mode: 'move' | 'resize') => {
    if (event.button !== 0 || desktopWindow.maximized) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    interactionRef.current = { mode, pointerX: event.clientX, pointerY: event.clientY, rect: desktopWindow.rect };
    setInteraction(mode);
    dispatch({ type: 'focus', windowId: desktopWindow.id });
  };
  const continueInteraction = (event: ReactPointerEvent<HTMLElement>) => {
    const current = interactionRef.current;
    if (!current) return;
    const dx = event.clientX - current.pointerX;
    const dy = event.clientY - current.pointerY;
    dispatch({
      type: current.mode,
      windowId: desktopWindow.id,
      rect: current.mode === 'move'
        ? { ...current.rect, x: current.rect.x + dx, y: current.rect.y + dy }
        : { ...current.rect, width: current.rect.width + dx, height: current.rect.height + dy },
    });
  };
  const stopInteraction = (event: ReactPointerEvent<HTMLElement>) => {
    if (!interactionRef.current) return;
    interactionRef.current = null;
    setInteraction(null);
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
  };
  if (desktopWindow.minimized) return null;
  return (
    <section
      aria-label={`${app.label} App`}
      className="paw-os-app-window"
      data-active={active || undefined}
      data-interaction={interaction ?? undefined}
      data-paw-os-app={app.id}
      data-presentation={app.presentation}
      onPointerDown={() => dispatch({ type: 'focus', windowId: desktopWindow.id })}
      role="region"
      style={{ left: desktopWindow.rect.x, top: desktopWindow.rect.y, width: desktopWindow.rect.width, height: desktopWindow.rect.height, zIndex: windowZIndex(state, desktopWindow.id) }}
    >
      <header
        className="paw-os-app-window__titlebar"
        onDoubleClick={() => dispatch({ type: 'toggleMaximize', windowId: desktopWindow.id })}
        onPointerDown={(event) => startInteraction(event, 'move')}
        onPointerMove={continueInteraction}
        onPointerUp={stopInteraction}
        onPointerCancel={stopInteraction}
      >
        <div
          className="paw-os-traffic-lights"
          onDoubleClick={(event) => event.stopPropagation()}
          onPointerDown={(event) => event.stopPropagation()}
        >
          <button aria-label={`关闭${app.label}`} className="paw-os-traffic-light paw-os-traffic-light--close" onClick={onClose} type="button"><X aria-hidden="true" size={8} /></button>
          <button aria-label={`最小化${app.label}`} className="paw-os-traffic-light paw-os-traffic-light--minimize" onClick={() => dispatch({ type: 'minimize', windowId: desktopWindow.id })} type="button"><Minus aria-hidden="true" size={8} /></button>
          <button aria-label={`${desktopWindow.maximized ? '还原' : '放大'}${app.label}`} className="paw-os-traffic-light paw-os-traffic-light--maximize" onClick={() => dispatch({ type: 'toggleMaximize', windowId: desktopWindow.id })} type="button"><Maximize2 aria-hidden="true" size={7} /></button>
        </div>
        <div className="paw-os-app-window__identity"><span className="paw-os-app-icon paw-os-app-icon--small" data-accent={app.accent}><Icon aria-hidden="true" size={15} /></span><strong>{app.label}</strong></div>
        <span className="paw-os-app-window__context">{app.tagline}</span>
      </header>
      <div className="paw-os-app-window__body">{children}</div>
      <div
        aria-hidden="true"
        className="paw-os-app-window__resize paw-os-app-window__resize--se"
        onPointerDown={(event) => startInteraction(event, 'resize')}
        onPointerMove={continueInteraction}
        onPointerUp={stopInteraction}
        onPointerCancel={stopInteraction}
      />
    </section>
  );
}

function PawOsSleepingApp({ app, onActivate }: { app: PawOsAppDefinition; onActivate: () => void }) {
  const Icon = pawOsAppIcons[app.id];
  return <button className="paw-os-sleeping-app" onClick={onActivate} type="button"><span className="paw-os-app-icon paw-os-app-icon--hero" data-accent={app.accent}><Icon aria-hidden="true" size={30} /></span><strong>{app.label}</strong><span>{app.tagline}</span><small>点按返回这个 App</small></button>;
}

function PawOsDock({ activeWindowId, onActivate, onLaunchpad, windows }: { activeWindowId: string | null; onActivate: (appId: PawOsAppId) => void; onLaunchpad: () => void; windows: PawOsDesktopWindow[] }) {
  return (
    <nav className="paw-os-dock" aria-label="PAWOS 应用坞">
      <button className="paw-os-dock__launchpad" onClick={onLaunchpad} type="button" aria-label="从应用坞打开全部 App"><Grid3X3 aria-hidden="true" size={21} /></button>
      <span className="paw-os-dock__divider" aria-hidden="true" />
      {primaryDockAppIds.map((appId) => {
        const app = pawOsApp(appId);
        const Icon = pawOsAppIcons[appId];
        const runningWindow = windows.find((window) => window.appId === appId);
        return (
          <button
            aria-label={`打开${app.label}`}
            className="paw-os-dock__app"
            data-active={runningWindow?.id === activeWindowId || undefined}
            data-running={Boolean(runningWindow) || undefined}
            key={appId}
            onClick={() => onActivate(appId)}
            onFocus={() => { if (app.defaultRouteId) prefetchRoute(app.defaultRouteId); }}
            onPointerEnter={() => { if (app.defaultRouteId) prefetchRoute(app.defaultRouteId); }}
            title={app.label}
            type="button"
          >
            <span className="paw-os-app-icon" data-accent={app.accent}><Icon aria-hidden="true" size={22} /></span><span className="paw-os-dock__label">{app.shortLabel}</span>
          </button>
        );
      })}
    </nav>
  );
}

function PawOsLaunchpad({ activeAppId, onActivate, onClose }: { activeAppId: PawOsAppId | null; onActivate: (appId: PawOsAppId) => void; onClose: () => void }) {
  const [query, setQuery] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);
  useEffect(() => inputRef.current?.focus(), []);
  const apps = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase();
    if (!normalized) return pawOsAppRegistry;
    return pawOsAppRegistry.filter((app) => `${app.label}${app.shortLabel}${app.tagline}`.toLocaleLowerCase().includes(normalized));
  }, [query]);
  return (
    <div aria-label="全部 App" aria-modal="false" className="paw-os-overlay paw-os-launchpad" role="dialog" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <div className="paw-os-launchpad__surface">
        <header><div><span className="paw-os-overlay__eyebrow"><Command aria-hidden="true" size={14} /> PAWOS APP CENTER</span><h2>全部 App</h2><p>每个能力都是独立 App，可在桌面打开、切换和组合。</p></div><button aria-label="关闭全部 App" className="paw-os-overlay__close" onClick={onClose} type="button"><X aria-hidden="true" size={18} /></button></header>
        <label className="paw-os-launchpad__search"><Search aria-hidden="true" size={17} /><input ref={inputRef} onChange={(event) => setQuery(event.target.value)} placeholder="搜索 App" value={query} /></label>
        <div className="paw-os-launchpad__grid">
          {apps.map((app) => {
            const Icon = pawOsAppIcons[app.id];
            return <button aria-label={`${app.label} · ${app.tagline}`} data-active={app.id === activeAppId || undefined} key={app.id} onClick={() => { onActivate(app.id); onClose(); }} onPointerEnter={() => { if (app.defaultRouteId) prefetchRoute(app.defaultRouteId); }} type="button"><span className="paw-os-app-icon paw-os-app-icon--launchpad" data-accent={app.accent}><Icon aria-hidden="true" size={27} /></span><strong>{app.label}</strong><small>{app.tagline}</small></button>;
          })}
        </div>
      </div>
    </div>
  );
}

function PawOsMissionControl({ onActivate, onClose, state }: { onActivate: (window: PawOsDesktopWindow) => void; onClose: () => void; state: PawOsDesktopState }) {
  return (
    <div aria-label="窗口总览" aria-modal="false" className="paw-os-overlay paw-os-mission-control" role="dialog" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <header><span className="paw-os-overlay__eyebrow"><Layers3 aria-hidden="true" size={14} /> MISSION CONTROL</span><h2>窗口总览</h2><p>{state.windows.length} 个 App 窗口</p></header>
      <div className="paw-os-mission-control__grid">
        {state.windows.map((desktopWindow) => {
          const app = pawOsApp(desktopWindow.appId);
          const Icon = pawOsAppIcons[app.id];
          return <button aria-label={`${app.label}窗口`} key={desktopWindow.id} onClick={() => { onActivate(desktopWindow); onClose(); }} type="button"><span className="paw-os-mission-control__preview" data-accent={app.accent}><span className="paw-os-mission-control__preview-bar"><i /><i /><i /></span><span className="paw-os-mission-control__preview-body"><Icon aria-hidden="true" size={34} /></span></span><strong>{app.label}</strong><small>{desktopWindow.minimized ? '已最小化' : desktopWindow.id === state.activeWindowId ? '当前窗口' : '在桌面打开'}</small></button>;
        })}
      </div>
      <button className="paw-os-mission-control__done" onClick={onClose} type="button">返回桌面</button>
    </div>
  );
}
