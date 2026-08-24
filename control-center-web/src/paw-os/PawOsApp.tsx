import { useEffect, useMemo } from 'react';
import { usePawOsAppearance } from '@/design/paw-os-themes';
import { pawAppForPath } from './runtime/app-registry';
import { PawDesktopProvider, usePawDesktopApi } from './runtime/desktop-context';
import type { PawDesktopStore } from './runtime/desktop-store';
import { PawDesktop } from './shell/PawDesktop';
import './styles/paw-os.css';
import './styles/paw-os-motion.css';
import './styles/paw-os-agent-composition.css';
import './styles/paw-os-agent-next.css';
import './styles/paw-os-webmodel-v1.css';
import './styles/paw-os-shell-migrated-v1.css';
import './styles/paw-os-agent-migrated-v1.css';
import './styles/paw-os-agent-fx.css';
import './styles/paw-os-room-migrated-v1.css';
import './styles/paw-os-room-focus.css';
import './styles/paw-os-sys-apps-migrated-v1.css';
import './styles/paw-os-tools-files-migrated-v1.css';

export function PawOsApp() {
  const { theme } = usePawOsAppearance();
  const initialRoute = useMemo(() => currentHashRoute(), []);
  const initialApp = useMemo(() => pawAppForPath(initialRoute), [initialRoute]);
  return (
    <PawDesktopProvider initialAppId={initialApp?.id} initialRoute={initialRoute}>
      <PawOsRouteBridge />
      <div className="paw-desktop-root" data-paw-theme={theme} data-testid="paw-os-product-root">
        <PawDesktop />
      </div>
    </PawDesktopProvider>
  );
}

function PawOsRouteBridge() {
  const api = usePawDesktopApi();
  useEffect(() => {
    const sync = () => syncPawOsRoute(api);
    sync();
    window.addEventListener('hashchange', sync);
    return () => window.removeEventListener('hashchange', sync);
  }, [api]);
  return null;
}

export function syncPawOsRoute(api: PawDesktopStore) {
  const route = currentHashRoute();
  const app = pawAppForPath(route);
  if (app) api.getState().openApp(app.id, { initialRoute: route });
  else api.getState().showWayfinder();
}

function currentHashRoute(): string {
  if (typeof window === 'undefined') return '/project-field';
  return window.location.hash.replace(/^#/, '') || '/project-field';
}
