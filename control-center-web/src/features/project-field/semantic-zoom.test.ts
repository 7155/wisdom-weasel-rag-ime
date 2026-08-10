import { describe, expect, it } from 'vitest';
import { projectFieldZoomProjection } from './semantic-zoom';

describe('projectFieldZoomProjection', () => {
  it('switches between waypoint, voyage, and close projections', () => {
    expect(projectFieldZoomProjection(0.75).level).toBe('far');
    expect(projectFieldZoomProjection(0.92).level).toBe('mid');
    expect(projectFieldZoomProjection(1.1).level).toBe('near');
  });

  it('keeps labels readable without letting them dominate the map', () => {
    expect(projectFieldZoomProjection(0.75).counterScale).toBeCloseTo(1.333, 2);
    expect(projectFieldZoomProjection(0.4).counterScale).toBe(1.42);
    expect(projectFieldZoomProjection(1.1).counterScale).toBe(1);
  });

  it('falls back safely for invalid transform values', () => {
    expect(projectFieldZoomProjection(Number.NaN)).toEqual({ counterScale: 1, level: 'mid' });
    expect(projectFieldZoomProjection(0)).toEqual({ counterScale: 1, level: 'mid' });
  });
});
