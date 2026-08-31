import { lazy, memo, Suspense } from 'react';
import type { PawOsWindowTarget } from '@/features/paw-os/model/desktop';
import type { PawAppId } from '../runtime/app-registry';
import { pawApp } from '../runtime/app-registry';
import { PawAppIcon } from '../shell/PawAppIcon';
// Eager: the boot state below is what the window shows while the App chunk —
// and everything it imports, including paw-apps.css — is still loading.
import './paw-app-boot.css';

const loadPawAppsRuntime = () => import('./PawAppsRuntime');
const PawAppBody = lazy(async () => ({
  default: (await loadPawAppsRuntime()).PawAppBody,
}));

/** Start both dynamic boundaries while the pointer is approaching an App (or
 * the desktop is idle), so the launch click only commits window state. Native
 * import caching makes repeated hover/focus calls free. */
export function warmPawAppProcess(appId: PawAppId): void {
  void loadPawAppsRuntime()
    .then((runtime) => runtime.warmPawAppBody(appId))
    .catch(() => undefined);
}

export const PawAppProcess = memo(function PawAppProcess({ appId, entityId, initialRoute, target }: { appId: PawAppId; entityId?: string; initialRoute?: string; target?: PawOsWindowTarget }) {
  return (
    <Suspense fallback={<PawAppBoot appId={appId} />}>
      <PawAppBody appId={appId} entityId={entityId} initialRoute={initialRoute} target={target} />
    </Suspense>
  );
});

function PawAppBoot({ appId }: { appId: PawAppId }) {
  const app = pawApp(appId);
  return (
    <div className="paw-app-boot" role="status">
      <PawAppIcon appId={appId} size={32} />
      <span><small>正在打开</small><strong>{app.label}</strong></span>
    </div>
  );
}
