import { describe, expect, it } from 'vitest';
import {
  EVOLUTION_REPORT_PATH,
  standaloneSurfaceForPath,
} from './standalone-surface';

describe('standaloneSurfaceForPath', () => {
  it('owns the Evolution Report as a document path outside the PAWOS desktop', () => {
    expect(EVOLUTION_REPORT_PATH).toBe('/evolution-report');
    expect(standaloneSurfaceForPath('/evolution-report')).toBe('evolution-report');
    expect(standaloneSurfaceForPath('/evolution-report/')).toBe('evolution-report');
  });

  it('does not steal ordinary PAWOS application routes', () => {
    expect(standaloneSurfaceForPath('/')).toBeNull();
    expect(standaloneSurfaceForPath('/observability')).toBeNull();
    expect(standaloneSurfaceForPath('/evolution-report-extra')).toBeNull();
  });
});
