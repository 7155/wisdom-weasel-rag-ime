import { LoaderCircle } from 'lucide-react';
import { lazy, Suspense } from 'react';
import type { PawOsWindowTarget } from '@/features/paw-os/model/desktop';
import type { PawAppId } from '../runtime/app-registry';
import { pawApp } from '../runtime/app-registry';
import { PawAgentApp } from './PawAgentApp';
import { PawBrowserApp } from './PawBrowserApp';
import { PawNativeApp, type PawNativeAppId } from './PawNativeApps';
import { PawOsSatelliteHost } from '@/features/paw-os/PawOsSatelliteHost';
import { PawResultWindow } from '@/features/paw-os/PawResultWindow';
import { PawAppIcon } from '../shell/PawAppIcon';
import './paw-apps.css';

const FilesApp = lazy(async () => ({
  default: (await import('@/features/files/PawOsFilesApp')).PawOsFilesApp,
}));
const TerminalApp = lazy(async () => ({
  default: (await import('@/features/terminal/PawOsTerminalApp')).PawOsTerminalApp,
}));

export function PawAppBody({
  appId,
  entityId,
  initialRoute,
  target,
}: {
  appId: PawAppId;
  entityId?: string;
  initialRoute?: string;
  target?: PawOsWindowTarget;
}) {
  return (
    <Suspense fallback={<AppLoading appId={appId} />}>
      {renderApp(appId, entityId, initialRoute, target)}
    </Suspense>
  );
}

function renderApp(appId: PawAppId, entityId?: string, initialRoute?: string, target?: PawOsWindowTarget) {
  if (target?.kind === 'result') return <PawResultWindow target={target} />;
  if (target?.kind === 'process-terminal') return <PawOsSatelliteHost target={target} />;
  if (
    (target?.kind === 'room' && Boolean(target.panel))
    || target?.kind === 'participant'
    || target?.kind === 'subagent'
    || target?.kind === 'work-document'
    || target?.kind === 'project'
    || target?.kind === 'task'
    || target?.kind === 'package'
  ) return <PawOsSatelliteHost target={target} />;
  switch (appId) {
    case 'agent':
      return <PawAgentApp initialRoute={initialRoute} target={target ?? (entityId ? { kind: 'session', id: entityId, title: entityId } : undefined)} />;
    case 'browser':
      return <PawBrowserApp target={target?.kind === 'browser-target' ? target : undefined} />;
    case 'files':
      return <FilesApp initialRoute={initialRoute} />;
    case 'terminal':
      return <TerminalApp />;
    case 'project-workbench':
    case 'memory':
    case 'knowledge':
    case 'input-studio':
    case 'app-center':
    case 'system-monitor':
    case 'system-settings':
      return <PawNativeApp appId={appId as PawNativeAppId} initialRoute={initialRoute} />;
  }
}

function AppLoading({ appId }: { appId: PawAppId }) {
  return (
    <div className="paw-app-loading" role="status">
      <PawAppIcon appId={appId} size={28} />
      <LoaderCircle className="ui-spin" size={18} />
      <span>正在打开 {pawApp(appId).label}</span>
    </div>
  );
}
