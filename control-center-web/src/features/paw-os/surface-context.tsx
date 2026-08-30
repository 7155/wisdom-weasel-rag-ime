import { createContext, useContext, useMemo, type ReactNode } from 'react';
import type { PawOsDesktopAppId } from './model/app-registry';
import type { PawOsWindowTarget } from './model/desktop';

export type PawOsAppSurface = {
  appId: PawOsDesktopAppId;
  active: boolean;
  windowId?: string;
  width: number;
  height: number;
  compact: boolean;
};

const PawOsAppSurfaceContext = createContext<PawOsAppSurface | null>(null);

export type PawOsWindowRequest = {
  appId: PawOsDesktopAppId;
  target: PawOsWindowTarget;
  background?: boolean;
};

type PawOsDesktopControls = {
  openWindow: (request: PawOsWindowRequest) => void;
  openApp?: (appId: PawOsDesktopAppId, initialRoute?: string) => void;
  openRoute?: (route: string) => void;
  bindAgentMain?: (
    windowId: string,
    target?: Extract<PawOsWindowTarget, { kind: 'session' | 'room' }>,
  ) => void;
  bindRoomMain?: (target: Extract<PawOsWindowTarget, { kind: 'room' }>) => void;
  setCollaborationFocusGroup?: (group: string | null) => void;
  closeWindow?: (windowId: string) => void;
};

const PawOsDesktopContext = createContext<PawOsDesktopControls | null>(null);

export function PawOsDesktopProvider({
  children,
  bindAgentMain,
  bindRoomMain,
  setCollaborationFocusGroup,
  closeWindow,
  openApp,
  openRoute,
  openWindow,
}: {
  children: ReactNode;
  bindAgentMain?: PawOsDesktopControls['bindAgentMain'];
  bindRoomMain?: PawOsDesktopControls['bindRoomMain'];
  setCollaborationFocusGroup?: PawOsDesktopControls['setCollaborationFocusGroup'];
  closeWindow?: PawOsDesktopControls['closeWindow'];
  openApp?: PawOsDesktopControls['openApp'];
  openRoute?: PawOsDesktopControls['openRoute'];
  openWindow: PawOsDesktopControls['openWindow'];
}) {
  const value = useMemo(() => ({ bindAgentMain, bindRoomMain, setCollaborationFocusGroup, closeWindow, openApp, openRoute, openWindow }), [bindAgentMain, bindRoomMain, setCollaborationFocusGroup, closeWindow, openApp, openRoute, openWindow]);
  return <PawOsDesktopContext.Provider value={value}>{children}</PawOsDesktopContext.Provider>;
}

export function PawOsAppSurfaceProvider({
  active = true,
  appId,
  children,
  height,
  windowId,
  width,
}: {
  active?: boolean;
  appId: PawOsDesktopAppId;
  children: ReactNode;
  height: number;
  windowId?: string;
  width: number;
}) {
  const value = useMemo<PawOsAppSurface>(() => ({
    active,
    appId,
    windowId,
    width,
    height,
    compact: width <= 760,
  }), [active, appId, height, width, windowId]);

  return <PawOsAppSurfaceContext.Provider value={value}>{children}</PawOsAppSurfaceContext.Provider>;
}

export function usePawOsAppSurface(): PawOsAppSurface | null {
  return useContext(PawOsAppSurfaceContext);
}

export function usePawOsDesktop(): PawOsDesktopControls | null {
  return useContext(PawOsDesktopContext);
}

export function openPawOsRoute(desktop: PawOsDesktopControls | null, route: string): void {
  if (desktop?.openRoute) {
    desktop.openRoute(route);
    return;
  }
  window.location.hash = route;
}
