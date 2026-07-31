import { LoaderCircle } from 'lucide-react';
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

  useEffect(() => {
    document.title = `${identity.productName} · Agent 记忆与协作`;
  }, [identity.productName]);

  const setCollapsed = (next: boolean) => {
    setCollapsedState(next);
    window.localStorage.setItem(SIDEBAR_STORAGE_KEY, String(next));
  };

  return (
    <div className="control-shell" data-sidebar-collapsed={collapsed || undefined}>
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
      <DesktopNavigation
        activeRouteId={activeRoute.id}
        collapsed={collapsed}
        identity={identity}
        onCollapsedChange={setCollapsed}
      />
      <ShellSidebarResizer />
      <div className="shell-workspace">
        <header className="shell-topbar">
          <div className="shell-topbar__title" key={activeRoute.id}>
            <h1>{activeRoute.label}</h1>
            <span>{routeGroupLabels[activeRoute.group]}</span>
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
          data-route-pending={routePending || undefined}
          id="workspace-main"
          tabIndex={-1}
          aria-busy={routePending}
        >
          {children}
          {routePending ? (
            <div className="shell-route-pending" role="status" aria-live="polite">
              <LoaderCircle className="ui-spin" size={18} aria-hidden="true" />
              <span>正在打开{activeRoute.label}</span>
            </div>
          ) : null}
        </div>
        <MobileBottomNavigation activeRouteId={activeRoute.id} />
      </div>
    </div>
  );
}
