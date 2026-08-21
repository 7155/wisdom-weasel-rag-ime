import { createContext, useContext, useMemo, type ReactNode } from 'react';
import type { PawOsAppId } from './model/app-registry';

export type PawOsAppSurface = {
  appId: PawOsAppId;
  width: number;
  height: number;
  compact: boolean;
};

const PawOsAppSurfaceContext = createContext<PawOsAppSurface | null>(null);

export function PawOsAppSurfaceProvider({
  appId,
  children,
  height,
  width,
}: {
  appId: PawOsAppId;
  children: ReactNode;
  height: number;
  width: number;
}) {
  const value = useMemo<PawOsAppSurface>(() => ({
    appId,
    width,
    height,
    compact: width <= 760,
  }), [appId, height, width]);

  return <PawOsAppSurfaceContext.Provider value={value}>{children}</PawOsAppSurfaceContext.Provider>;
}

export function usePawOsAppSurface(): PawOsAppSurface | null {
  return useContext(PawOsAppSurfaceContext);
}
