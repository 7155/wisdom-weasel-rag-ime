import { ChevronRight, LoaderCircle } from 'lucide-react';
import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from 'react';
import { routeGroupLabels } from '@/app/route-registry';
import { router } from '@/app/router';
import { ConnectionIndicator, GlobalNoticeRegion } from '@/components/feedback';
import { useProductIdentity } from '@/features/identity/product-identity';
import { DesktopNavigation, MobileBottomNavigation } from './Navigation';
import { ShellSidebarResizer } from './ShellSidebarResizer';
import { ThemeMenu } from './ThemeMenu';
import { useHashRoute } from './useHashRoute';

const SIDEBAR_STORAGE_KEY = 'rag-ime-control-sidebar-collapsed';

function getInitialCollapsed(): boolean {
  if (typeof window === 'undefined') return false;
  return window.localStorage.getItem(SIDEBAR_STORAGE_KEY) === 'true';
}

export function AppShell({ children }: { children: ReactNode }) {
  const activeRoute = useHashRoute();
  const identity = useProductIdentity();
  const navigationState = useSyncExternalStore(
    router.subscribe,
    () => router.state.navigation.state,
    () => 'idle',
  );
  const routePending = navigationState !== 'idle';
  const [routeIsSlow, setRouteIsSlow] = useState(false);
  const immersive = activeRoute.id === 'project-field';
  const [collapsed, setCollapsedState] = useState(getInitialCollapsed);
  const previousRouteId = useRef(activeRoute.id);
  const routeScrollPositions = useRef(new Map<string, number>());
  const routeStageRef = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    if (previousRouteId.current !== activeRoute.id) {
      routeScrollPositions.current.set(previousRouteId.current, window.scrollY);
      window.scrollTo({
        left: 0,
        top: routeScrollPositions.current.get(activeRoute.id) ?? 0,
        behavior: 'auto',
      });
      routeStageRef.current?.focus({ preventScroll: true });
      previousRouteId.current = activeRoute.id;
    }
  }, [activeRoute.id]);

  useEffect(() => {
    document.title = `${activeRoute.label} · ${identity.productName}`;
  }, [activeRoute.label, identity.productName]);

  useEffect(() => {
    setRouteIsSlow(false);
    if (!routePending) return;
    const timeout = window.setTimeout(() => setRouteIsSlow(true), 8_000);
    return () => window.clearTimeout(timeout);
  }, [activeRoute.id, routePending]);

  const setCollapsed = (next: boolean) => {
    setCollapsedState(next);
    window.localStorage.setItem(SIDEBAR_STORAGE_KEY, String(next));
  };

  return (
    <div
      className="control-shell"
      data-immersive={immersive || undefined}
      data-sidebar-collapsed={collapsed || undefined}
    >
      <a
        className="shell-skip-link"
        href="#workspace-main"
        onClick={(event) => {
          event.preventDefault();
          routeStageRef.current?.focus();
          routeStageRef.current?.scrollIntoView({ block: 'start' });
        }}
      >
        跳到主工作区
      </a>
      {!immersive ? (
        <DesktopNavigation
          activeRouteId={activeRoute.id}
          collapsed={collapsed}
          identity={identity}
          onCollapsedChange={setCollapsed}
        />
      ) : null}
      {!immersive ? <ShellSidebarResizer /> : null}
      <div className="shell-workspace">
        {!immersive ? (
          <header className="shell-topbar">
            <div className="shell-topbar__title" key={activeRoute.id}>
              <span>{routeGroupLabels[activeRoute.group]}</span>
              <ChevronRight aria-hidden="true" size={13} strokeWidth={1.8} />
              {activeRoute.id === 'agent' || activeRoute.id === 'rooms'
                ? <h1>{activeRoute.label}</h1>
                : <strong>{activeRoute.label}</strong>}
            </div>
            <div className="shell-topbar__actions">
              <ConnectionIndicator />
              <ThemeMenu />
            </div>
          </header>
        ) : null}
        <GlobalNoticeRegion />
        <div
          ref={routeStageRef}
          className="shell-route-stage"
          data-active-route={activeRoute.id}
          data-route-pending={routePending || undefined}
          id="workspace-main"
          tabIndex={-1}
          role="region"
          aria-label={`${activeRoute.label}主内容`}
          aria-busy={routePending}
        >
          {children}
          {routePending ? (
            <div className="shell-route-pending" role="status" aria-live="polite">
              {routeIsSlow ? (
                <div className="shell-route-pending__slow">
                  <strong>{activeRoute.label}还没有打开</strong>
                  <span>界面仍在载入，连接不稳定时可能需要更久。你可以继续等待，或留在当前页面。</span>
                  <div className="shell-route-pending__actions">
                    <button
                      className="ui-button"
                      data-variant="primary"
                      onClick={() => router.navigate(0)}
                      type="button"
                    >
                      重新载入
                    </button>
                    <button
                      className="ui-button"
                      data-variant="secondary"
                      onClick={() => void router.navigate(router.state.location.pathname, { replace: true })}
                      type="button"
                    >
                      留在当前页
                    </button>
                  </div>
                </div>
              ) : (
                <>
                  <LoaderCircle className="ui-spin" size={18} aria-hidden="true" />
                  <span>正在打开{activeRoute.label}</span>
                </>
              )}
            </div>
          ) : null}
        </div>
        {!immersive ? <MobileBottomNavigation activeRouteId={activeRoute.id} /> : null}
      </div>
    </div>
  );
}
