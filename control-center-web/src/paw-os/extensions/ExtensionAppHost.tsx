import { AlertTriangle, LoaderCircle } from 'lucide-react';
import { Component, lazy, Suspense, useMemo, type ErrorInfo, type ReactNode } from 'react';

import type { PawOsWindowTarget } from '@/features/paw-os/model/desktop';
import type { PawExtensionAppId } from './types';
import { loadPawExtensionApp, pawExtensionApp } from './registry';

export function PawExtensionAppHost({
  appId,
  entityId,
  initialRoute,
  target,
}: {
  appId: PawExtensionAppId;
  entityId?: string;
  initialRoute?: string;
  target?: PawOsWindowTarget;
}) {
  const manifest = pawExtensionApp(appId);
  const App = useMemo(() => lazy(async () => loadPawExtensionApp(appId)), [appId]);
  return (
    <ExtensionAppErrorBoundary appId={appId}>
      <Suspense fallback={<div className="paw-extension-app-state" role="status"><LoaderCircle className="ui-spin" size={18} />正在载入 {manifest.label}</div>}>
        <App entityId={entityId} initialRoute={initialRoute} manifest={manifest} target={target} />
      </Suspense>
    </ExtensionAppErrorBoundary>
  );
}

class ExtensionAppErrorBoundary extends Component<
  { appId: PawExtensionAppId; children: ReactNode },
  { error?: Error }
> {
  state: { error?: Error } = {};

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(_error: Error, _info: ErrorInfo): void {
    // The visible boundary is authoritative for this App chunk; global error
    // reporting still receives the thrown error through React in development.
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="paw-extension-app-state" role="alert">
        <AlertTriangle size={20} />
        <strong>扩展 App 没有打开</strong>
        <span>{this.state.error.message || this.props.appId}</span>
      </div>
    );
  }
}
