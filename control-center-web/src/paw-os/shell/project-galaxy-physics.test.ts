import { describe, expect, it } from 'vitest';
import { advanceOrbit, createOrbit, galaxyAngularSpeed, orbitEnergy } from './project-galaxy-physics';

const orbit = (eccentricity = 0) => createOrbit({ orbitRadius: 8, phaseRad: .4, inclinationRad: .17, eccentricity });
const radius = (state: ReturnType<typeof orbit>) => Math.hypot(state.x, state.y, state.z);
const momentum = (s: ReturnType<typeof orbit>) => Math.hypot(s.y * s.vz - s.z * s.vy, s.z * s.vx - s.x * s.vz, s.x * s.vy - s.y * s.vx);

describe('galactic orbit integration', () => {
  it('advances a circular orbit without changing its radius or plane', () => {
    const state = orbit();
    const before = { ...state };
    for (let i = 0; i < 1000; i++) advanceOrbit(state, .02);
    expect(Math.hypot(state.x - before.x, state.z - before.z)).toBeGreaterThan(5);
    expect(radius(state)).toBeCloseTo(8, 3);
    expect(state.y / state.z).toBeCloseTo(Math.tan(.17), 6);
  });
  it('speeds up toward periapsis while conserving energy and angular momentum', () => {
    const state = orbit(.18);
    const energy = orbitEnergy(state), angularMomentum = momentum(state);
    const initialSpeed = Math.hypot(state.vx, state.vy, state.vz);
    let nearest = 8, fastest = initialSpeed;
    for (let i = 0; i < 20_000; i++) {
      advanceOrbit(state, .02);
      nearest = Math.min(nearest, radius(state));
      fastest = Math.max(fastest, Math.hypot(state.vx, state.vy, state.vz));
    }
    expect(nearest).toBeLessThan(7.5);
    expect(fastest).toBeGreaterThan(initialSpeed * 1.05);
    expect(Math.abs(orbitEnergy(state) - energy)).toBeLessThan(1e-5);
    expect(momentum(state)).toBeCloseTo(angularMomentum, 8);
  });
  it('has differential galactic rotation and preserves a paused orbit', () => {
    expect(galaxyAngularSpeed(4)).toBeGreaterThan(galaxyAngularSpeed(12));
    const state = orbit(.1), initial = { ...state };
    advanceOrbit(state, 0);
    expect(state).toEqual(initial);
  });
});
