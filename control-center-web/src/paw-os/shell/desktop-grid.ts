import { useEffect, useState } from 'react';

/* The desktop's one grid authority. App shortcuts, project folders and loose
 * conversation files all live on the same coordinate plane, so a single slot
 * rhythm — one origin, one pitch, one column count derived from the plane
 * width — is what keeps every identity looking placed by a system instead of
 * scattered. Persisted icon positions always win; these slots are only the
 * default flow for icons the user has never dragged. */
export const PAW_DESKTOP_GRID = {
  originX: 24,
  originY: 24,
  pitchX: 104,
  pitchY: 102,
} as const;

/* The Wayfinder's App rail keeps five identities on the desktop. The work
 * canvas starts one clear band below whatever rows they occupy. */
export const PAW_DESKTOP_SHORTCUT_COUNT = 5;

export function pawDesktopGridColumns(planeWidth: number): number {
  return Math.max(2, Math.floor((planeWidth - PAW_DESKTOP_GRID.originX) / PAW_DESKTOP_GRID.pitchX));
}

export function pawDesktopGridPosition(slot: number, columns: number): { x: number; y: number } {
  const safeColumns = Math.max(1, columns);
  return {
    x: PAW_DESKTOP_GRID.originX + (slot % safeColumns) * PAW_DESKTOP_GRID.pitchX,
    y: PAW_DESKTOP_GRID.originY + Math.floor(slot / safeColumns) * PAW_DESKTOP_GRID.pitchY,
  };
}

/** The y where the work canvas's first default row starts: one breathing gap
 * below the last App-shortcut row, so the two families never share a band. */
export function pawDesktopWorkOriginY(columns: number): number {
  const appRows = Math.ceil(PAW_DESKTOP_SHORTCUT_COUNT / Math.max(1, columns));
  return PAW_DESKTOP_GRID.originY + appRows * PAW_DESKTOP_GRID.pitchY + 14;
}

/** Default slot for a work-canvas icon (project folder or loose conversation
 * file): the same pitch as the App rail, starting below it. */
export function pawDesktopWorkPosition(slot: number, columns: number): { x: number; y: number } {
  const safeColumns = Math.max(1, columns);
  return {
    x: PAW_DESKTOP_GRID.originX + (slot % safeColumns) * PAW_DESKTOP_GRID.pitchX,
    y: pawDesktopWorkOriginY(safeColumns) + Math.floor(slot / safeColumns) * PAW_DESKTOP_GRID.pitchY,
  };
}

/* Both desktop planes span the full viewport, so one window-width listener
 * keeps every default slot computation on the same column count. */
export function usePawDesktopGridColumns(): number {
  const read = () => pawDesktopGridColumns(typeof window === 'undefined' ? 1280 : window.innerWidth);
  const [columns, setColumns] = useState(read);
  useEffect(() => {
    const update = () => setColumns(read());
    window.addEventListener('resize', update);
    return () => window.removeEventListener('resize', update);
  }, []);
  return columns;
}
