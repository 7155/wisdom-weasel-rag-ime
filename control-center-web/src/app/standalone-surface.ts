export const EVOLUTION_REPORT_PATH = '/evolution-report';

export type StandaloneSurfaceId = 'evolution-report';

export function standaloneSurfaceForPath(pathname: string): StandaloneSurfaceId | null {
  const normalized = pathname.length > 1 ? pathname.replace(/\/+$/, '') : pathname;
  return normalized === EVOLUTION_REPORT_PATH ? 'evolution-report' : null;
}
