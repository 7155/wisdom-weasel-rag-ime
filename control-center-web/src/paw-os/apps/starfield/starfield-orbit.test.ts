import { describe, expect, it } from 'vitest';
import {
  ellipticOrbitSamples,
  ellipticPosition,
  ellipticRadius,
  ellipticTrailSamples,
} from './starfield-orbit';

describe('starfield Kepler orbit helpers', () => {
  it('collapses to a circle when eccentricity is zero', () => {
    expect(ellipticRadius(10, 0, 0)).toBeCloseTo(10, 10);
    expect(ellipticRadius(10, 0, Math.PI / 2)).toBeCloseTo(10, 10);
    const pos = ellipticPosition(10, 0, Math.PI / 2, { x: 0, y: 0, z: 0 });
    expect(pos.x).toBeCloseTo(0, 10);
    expect(pos.z).toBeCloseTo(10, 10);
  });

  it('puts periapsis closer than apoapsis for eccentric orbits', () => {
    const peri = ellipticRadius(8, 0.35, 0);
    const apo = ellipticRadius(8, 0.35, Math.PI);
    expect(peri).toBeLessThan(apo);
    expect(peri).toBeCloseTo(8 * (1 - 0.35), 5);
    expect(apo).toBeCloseTo(8 * (1 + 0.35), 5);
  });

  it('samples a closed elliptical path and a trailing arc', () => {
    const loop = ellipticOrbitSamples(6, 0.2, 64);
    expect(loop).toHaveLength(64 * 3);
    // First sample is periapsis on +X.
    expect(loop[0]).toBeCloseTo(ellipticRadius(6, 0.2, 0), 5);
    expect(loop[1]).toBe(0);
    expect(loop[2]).toBeCloseTo(0, 5);

    const trail = ellipticTrailSamples(6, 0.2, Math.PI / 3, 0.9, 16);
    expect(trail).toHaveLength(16 * 3);
    // Head of the trail sits on the current anomaly.
    const head = ellipticPosition(6, 0.2, Math.PI / 3, { x: 0, y: 0, z: 0 });
    expect(trail[0]).toBeCloseTo(head.x, 5);
    expect(trail[2]).toBeCloseTo(head.z, 5);
  });
});
