import { createContext, useContext, useMemo, type ReactNode } from 'react';
import { NativeControlTransport } from '@/platform/native-transport';
import type { ControlTransport } from '@/platform/transport';

const ControlTransportContext = createContext<ControlTransport | null>(null);

export function ControlTransportProvider({
  children,
  transport,
}: {
  children: ReactNode;
  transport?: ControlTransport;
}) {
  const value = useMemo(() => transport ?? createConfiguredControlTransport(), [transport]);
  return (
    <ControlTransportContext.Provider value={value}>
      {children}
    </ControlTransportContext.Provider>
  );
}

export function useControlTransport(): ControlTransport {
  const transport = useContext(ControlTransportContext);
  if (!transport) {
    throw new Error('useControlTransport must be used inside ControlTransportProvider');
  }
  return transport;
}

export function useOptionalControlTransport(): ControlTransport | null {
  return useContext(ControlTransportContext);
}

export function createConfiguredControlTransport(): ControlTransport {
  return new NativeControlTransport();
}
