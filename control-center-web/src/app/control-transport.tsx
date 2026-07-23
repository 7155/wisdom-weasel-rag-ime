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
  const requested = import.meta.env.VITE_CONTROL_TRANSPORT ?? detectTransport();
  if (requested === 'native') {
    try {
      return new NativeControlTransport();
    } catch (error) {
      if (!(error instanceof NativeBridgeUnavailableError)) throw error;
    }
  }
  if (requested === 'http') {
    return new HttpControlTransport({
      baseUrl: import.meta.env.VITE_CONTROL_BASE_URL
        ?? 'http://127.0.0.1:8766',
    });
  }
  return createPreviewTransport();
}

function detectTransport(): 'native' | 'http' | 'mock' {
  if (window.webkit?.messageHandlers?.ragImeNativeBridge) return 'native';
  return import.meta.env.DEV ? 'mock' : 'http';
}
