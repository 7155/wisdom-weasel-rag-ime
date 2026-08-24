import { createContext, useContext, useEffect, useRef, type ReactNode } from 'react';
import { useStore } from 'zustand';
import { createPawDesktopStore, type PawDesktopSnapshot, type PawDesktopState, type PawDesktopStore } from './desktop-store';
import type { PawAppId } from './app-registry';

const PawDesktopContext = createContext<PawDesktopStore | null>(null);
const pawDesktopSnapshotKey = 'pawos.desktop.v1';

export function PawDesktopProvider({ children, initialAppId, initialRoute }: { children: ReactNode; initialAppId?: PawAppId | null; initialRoute?: string }) {
  const storeRef = useRef<PawDesktopStore | null>(null);
  storeRef.current ??= createPawDesktopStore(initialAppId, initialRoute, readPawDesktopSnapshot());
  useEffect(() => storeRef.current?.subscribe((state) => {
    const snapshot: PawDesktopSnapshot = {
      windows: state.windows,
      stack: state.stack,
      activeWindowId: state.activeWindowId,
    };
    window.localStorage.setItem(pawDesktopSnapshotKey, JSON.stringify(snapshot));
  }), []);
  return <PawDesktopContext.Provider value={storeRef.current}>{children}</PawDesktopContext.Provider>;
}

function readPawDesktopSnapshot(): PawDesktopSnapshot | undefined {
  if (typeof window === 'undefined') return undefined;
  const value = window.localStorage.getItem(pawDesktopSnapshotKey);
  return value ? JSON.parse(value) as PawDesktopSnapshot : undefined;
}

export function usePawDesktopStore<T>(selector: (state: PawDesktopState) => T): T {
  const store = useContext(PawDesktopContext);
  if (!store) throw new Error('usePawDesktopStore must be used inside PawDesktopProvider');
  return useStore(store, selector);
}

export function usePawDesktopApi(): PawDesktopStore {
  const store = useContext(PawDesktopContext);
  if (!store) throw new Error('usePawDesktopApi must be used inside PawDesktopProvider');
  return store;
}
