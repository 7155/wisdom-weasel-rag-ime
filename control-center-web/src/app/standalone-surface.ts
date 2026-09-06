export const EVOLUTION_REPORT_PATH = '/evolution-report';

export type StandaloneSurfaceId = 'evolution-report' | 'screen-assistant';

export function standaloneSurfaceForPath(pathname: string): StandaloneSurfaceId | null {
  const normalized = pathname.length > 1 ? pathname.replace(/\/+$/, '') : pathname;
  if (normalized === '/screen-assistant') return 'screen-assistant';
  return normalized === EVOLUTION_REPORT_PATH ? 'evolution-report' : null;
}
