import {
  createContext,
  useContext,
  useMemo,
  type ReactNode,
} from 'react';

import { HttpControlTransport } from '@/platform/http-transport';
import {
  NativeBridgeUnavailableError,
  NativeControlTransport,
} from '@/platform/native-transport';
import type { ControlTransport } from '@/platform/transport';
import { createPreviewTransport } from './preview-control-transport';

const ControlTransportContext = createContext<ControlTransport | null>(null);

export function ControlTransportProvider({
  children,
  transport,
}: {
  children: ReactNode;
  transport?: ControlTransport;
}) {
  const value = useMemo(
    () => transport ?? createConfiguredControlTransport(),
    [transport],
  );
  return (
    <ControlTransportContext.Provider value={value}>
      {children}
    </ControlTransportContext.Provider>
  );
}

export function useControlTransport(): ControlTransport {
  const transport = useContext(ControlTransportContext);
  if (!transport) {
    throw new Error(
      'useControlTransport must be used inside ControlTransportProvider',
    );
  }
  return transport;
}

export function useOptionalControlTransport(): ControlTransport | null {
  return useContext(ControlTransportContext);
}

export function createConfiguredControlTransport(): ControlTransport {
  const developmentOverride = developmentTransportOverride();
  const requested = developmentOverride
    ?? import.meta.env.VITE_CONTROL_TRANSPORT
    ?? (import.meta.env.DEV ? 'http' : detectTransport());
  if (requested === 'native') {
    try {
      return new NativeControlTransport();
    } catch (error) {
      if (!(error instanceof NativeBridgeUnavailableError)) throw error;
    }
  }
  if (requested === 'http') {
    return new HttpControlTransport({
      baseUrl: developmentOverride === 'http'
        ? window.location.origin
        : isElectronPawHost()
          ? window.location.origin
          : import.meta.env.VITE_CONTROL_BASE_URL ?? 'http://127.0.0.1:8766',
    });
  }
  return createPreviewTransport();
}

function isElectronPawHost(): boolean {
  return window.pawBrowserHost?.kind === 'electron-webview'
    || new URLSearchParams(window.location.search).get('pawHost') === 'electron';
}

function developmentTransportOverride(): 'http' | 'mock' | null {
  if (!import.meta.env.DEV) return null;
  const requested = new URLSearchParams(window.location.search).get('controlTransport');
  if (requested === 'http' || requested === 'mock') return requested;
  return null;
}

function detectTransport(): 'native' | 'http' {
  if (window.webkit?.messageHandlers?.ragImeNativeBridge) return 'native';
  return 'http';
}
