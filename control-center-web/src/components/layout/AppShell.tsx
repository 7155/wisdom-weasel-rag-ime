import { useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { ConnectionIndicator, GlobalNoticeRegion } from '@/components/feedback';
import { DesktopNavigation, MobileBottomNavigation, MobileRouteMenu } from './Navigation';
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
  const [collapsed, setCollapsedState] = useState(getInitialCollapsed);
  const previousRouteId = useRef(activeRoute.id);
  const routeStageRef = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    window.scrollTo({ left: 0, top: 0, behavior: 'auto' });
    if (previousRouteId.current !== activeRoute.id) {
      routeStageRef.current?.focus({ preventScroll: true });
      previousRouteId.current = activeRoute.id;
    }
  }, [activeRoute.id]);

  const setCollapsed = (next: boolean) => {
    setCollapsedState(next);
    window.localStorage.setItem(SIDEBAR_STORAGE_KEY, String(next));
  };

  return (
    <div className="control-shell" data-sidebar-collapsed={collapsed || undefined}>
      <a className="shell-skip-link" href="#workspace-main">跳到主工作区</a>
      <DesktopNavigation
        activeRouteId={activeRoute.id}
        collapsed={collapsed}
        onCollapsedChange={setCollapsed}
      />
      <ShellSidebarResizer />
      <div className="shell-workspace">
        <header className="shell-topbar">
          <div className="shell-topbar__mobile-brand">
            <img
              className="shell-brand__mark"
              src="./companions/personas/companion-present-v2.webp"
              alt=""
              aria-hidden="true"
            />
            <MobileRouteMenu activeRouteId={activeRoute.id} />
          </div>
          <div className="shell-topbar__title" key={activeRoute.id}>
            <h1>{activeRoute.label}</h1>
            <span>{activeRoute.group === 'operations' ? '治理与系统' : activeRoute.group === 'capability' ? '能力与知识' : '工作台'}</span>
          </div>
          <div className="shell-topbar__actions">
            <ConnectionIndicator />
            <ThemeMenu />
          </div>
        </header>
        <GlobalNoticeRegion />
        <div
          ref={routeStageRef}
          className="shell-route-stage"
          data-active-route={activeRoute.id}
          id="workspace-main"
          tabIndex={-1}
        >
          {children}
        </div>
        <MobileBottomNavigation activeRouteId={activeRoute.id} />
      </div>
    </div>
  );
}
