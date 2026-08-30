import { useMemo, useSyncExternalStore } from 'react';
import { pawApps } from '../runtime/app-registry';

/* The desktop's one grid authority. App shortcuts, project folders and loose
 * conversation files all live on the same coordinate plane, so a single slot
 * rhythm — one origin, one pitch, one column count derived from the plane
 * width — is what keeps every identity looking placed by a system instead of
 * scattered. Persisted icon positions always win; these slots are only the
 * default flow for icons the user has never dragged. */
export const PAW_DESKTOP_GRID = {
  originX: 24,
  originY: 24,
  pitchX: 112,
  pitchY: 116,
} as const;

/* Every registered App is a desktop identity. The work canvas starts one
 * clear band below however many rows that complete registry occupies. */
export const PAW_DESKTOP_SHORTCUT_COUNT = pawApps.length;

export type PawDesktopShortcutLayout = {
  columns: number;
  originY: number;
};

export function pawDesktopGridColumns(planeWidth: number): number {
  return Math.max(2, Math.floor((planeWidth - PAW_DESKTOP_GRID.originX) / PAW_DESKTOP_GRID.pitchX));
}

/** The project-dashboard masthead is gone: every desktop width now shares one
 * full-plane grid, and the work-file row begins after every registered App. */
export function pawDesktopShortcutLayout(planeWidth: number): PawDesktopShortcutLayout {
  const safeWidth = Math.max(PAW_DESKTOP_GRID.pitchX * 2, planeWidth);
  return {
    columns: pawDesktopGridColumns(safeWidth),
    originY: PAW_DESKTOP_GRID.originY,
  };
}

export function pawDesktopGridPosition(
  slot: number,
  columns: number,
  originY: number = PAW_DESKTOP_GRID.originY,
): { x: number; y: number } {
  const safeColumns = Math.max(1, columns);
  return {
    x: PAW_DESKTOP_GRID.originX + (slot % safeColumns) * PAW_DESKTOP_GRID.pitchX,
    y: originY + Math.floor(slot / safeColumns) * PAW_DESKTOP_GRID.pitchY,
  };
}

/** The y where the work canvas's first default row starts: one breathing gap
 * below the last App-shortcut row, so the two families never share a band. */
export function pawDesktopWorkOriginY(
  columns: number,
  shortcutOriginY: number = PAW_DESKTOP_GRID.originY,
): number {
  const appRows = Math.ceil(PAW_DESKTOP_SHORTCUT_COUNT / Math.max(1, columns));
  return shortcutOriginY + appRows * PAW_DESKTOP_GRID.pitchY + 18;
}

/** Default slot for a work-canvas icon (project folder or loose conversation
 * file): the same pitch as the App rail, starting below it. */
export function pawDesktopWorkPosition(
  slot: number,
  columns: number,
  shortcutOriginY: number = PAW_DESKTOP_GRID.originY,
): { x: number; y: number } {
  const safeColumns = Math.max(1, columns);
  return {
    x: PAW_DESKTOP_GRID.originX + (slot % safeColumns) * PAW_DESKTOP_GRID.pitchX,
    y: pawDesktopWorkOriginY(safeColumns, shortcutOriginY) + Math.floor(slot / safeColumns) * PAW_DESKTOP_GRID.pitchY,
  };
}

/* Both desktop planes span the full viewport. A shared external-store listener
 * gives App shortcuts and Wayfinder work icons one resize sample and one exact
 * furniture-aware layout instead of registering independent window handlers. */
const viewportListeners = new Set<() => void>();

function notifyViewportListeners(): void {
  for (const listener of viewportListeners) listener();
}

function subscribeViewportWidth(listener: () => void): () => void {
  if (typeof window === 'undefined') return () => undefined;
  if (viewportListeners.size === 0) window.addEventListener('resize', notifyViewportListeners);
  viewportListeners.add(listener);
  return () => {
    viewportListeners.delete(listener);
    if (viewportListeners.size === 0) window.removeEventListener('resize', notifyViewportListeners);
  };
}

function readViewportWidth(): number {
  return typeof window === 'undefined' ? 1280 : window.innerWidth;
}

function readServerViewportWidth(): number {
  return 1280;
}

export function usePawDesktopGridLayout(): PawDesktopShortcutLayout {
  const viewportWidth = useSyncExternalStore(
    subscribeViewportWidth,
    readViewportWidth,
    readServerViewportWidth,
  );
  return useMemo(() => pawDesktopShortcutLayout(viewportWidth), [viewportWidth]);
}

export function usePawDesktopGridColumns(): number {
  return usePawDesktopGridLayout().columns;
}
