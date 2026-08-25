import { createContext, useContext, useEffect, useRef, type ReactNode } from 'react';
import { useStore } from 'zustand';
import { createPawDesktopStore, type PawDesktopSnapshot, type PawDesktopState, type PawDesktopStore } from './desktop-store';
import type { PawAppId } from './app-registry';

const PawDesktopContext = createContext<PawDesktopStore | null>(null);
const pawDesktopSnapshotKey = 'pawos.desktop.v1';
const pawDesktopPersistDelayMs = 200;

export function PawDesktopProvider({ children, initialAppId, initialRoute }: { children: ReactNode; initialAppId?: PawAppId | null; initialRoute?: string }) {
  const storeRef = useRef<PawDesktopStore | null>(null);
  storeRef.current ??= createPawDesktopStore(initialAppId, initialRoute, readPawDesktopSnapshot());
  useEffect(() => {
    const store = storeRef.current;
    if (!store) return undefined;
    /* Persistence is a trailing debounce, not a per-mutation write: focus
     * churn, geometry commits and open/close bursts each land as one
     * synchronous localStorage/JSON.stringify instead of one per store set —
     * that serialization was interaction-path jank with many windows open.
     * pagehide/hidden flush the pending snapshot so a reload never loses the
     * last 200ms of desktop state. */
    let timer = 0;
    const write = () => {
      timer = 0;
      const state = store.getState();
      const snapshot: PawDesktopSnapshot = {
        windows: state.windows,
        stack: state.stack,
        activeWindowId: state.activeWindowId,
      };
      window.localStorage.setItem(pawDesktopSnapshotKey, JSON.stringify(snapshot));
    };
    const unsubscribe = store.subscribe(() => {
      if (!timer) timer = window.setTimeout(write, pawDesktopPersistDelayMs);
    });
    const flush = () => {
      if (!timer) return;
      window.clearTimeout(timer);
      write();
    };
    const flushWhenHidden = () => {
      if (document.visibilityState === 'hidden') flush();
    };
    window.addEventListener('pagehide', flush);
    document.addEventListener('visibilitychange', flushWhenHidden);
    return () => {
      unsubscribe();
      window.removeEventListener('pagehide', flush);
      document.removeEventListener('visibilitychange', flushWhenHidden);
      flush();
    };
  }, []);
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
