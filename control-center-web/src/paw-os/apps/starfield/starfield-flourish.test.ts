import { describe, expect, it } from 'vitest';
import {
  METEOR_POOL_SIZE,
  METEOR_TRAIL_POINTS,
  METEOR_TRAIL_SPAN_S,
  meteorFade,
  meteorSpawn,
  nebulaBreath,
  twinkleOpacity,
} from './starfield-flourish';

/** Same LCG family the scene seeds with — deterministic across runs. */
function lcg(seed: number): () => number {
  let state = seed >>> 0 || 1;
  return () => {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
    return state / 0x100000000;
  };
}

const SHELL = 84;

describe('星空 flourish — decorative presence stays bounded and honest', () => {
  it('spawns deterministic meteors: same stream, same streak', () => {
    expect(meteorSpawn(lcg(7), SHELL)).toEqual(meteorSpawn(lcg(7), SHELL));
    expect(meteorSpawn(lcg(7), SHELL)).not.toEqual(meteorSpawn(lcg(8), SHELL));
  });

  it('keeps every meteor on the deep-sky shell, dipping down at bounded pace', () => {
    const random = lcg(20260825);
    for (let index = 0; index < 60; index += 1) {
      const spawn = meteorSpawn(random, SHELL);
      const horizontal = Math.hypot(spawn.origin[0], spawn.origin[2]);
      expect(horizontal).toBeGreaterThanOrEqual(SHELL * 0.72 - 1e-9);
      expect(horizontal).toBeLessThanOrEqual(SHELL * 1.08 + 1e-9);
      // Upper sky only, and the streak always travels downward — a shooting
      // star, never an object rising through the orbits.
      expect(spawn.origin[1]).toBeGreaterThan(0);
      expect(spawn.velocity[1]).toBeLessThan(0);
      const speed = Math.hypot(spawn.velocity[0], spawn.velocity[1], spawn.velocity[2]);
      expect(speed).toBeGreaterThanOrEqual(SHELL * 0.55 - 1e-6);
      expect(speed).toBeLessThanOrEqual(SHELL * 1.05 + 1e-6);
      expect(spawn.lifeS).toBeGreaterThanOrEqual(0.9);
      expect(spawn.lifeS).toBeLessThanOrEqual(1.8);
      // Long quiet gaps: the sky must not turn into a fireworks show.
      expect(spawn.delayS).toBeGreaterThanOrEqual(2.5);
      expect(spawn.delayS).toBeLessThanOrEqual(9);
    }
  });

  it('ignites fast, fades slow, and is dark outside its life', () => {
    const life = 1.2;
    expect(meteorFade(-0.1, life)).toBe(0);
    expect(meteorFade(0, life)).toBe(0);
    expect(meteorFade(life, life)).toBe(0);
    expect(meteorFade(life + 1, life)).toBe(0);
    expect(meteorFade(0, 0)).toBe(0);
    expect(meteorFade(0.18 * life, life)).toBeCloseTo(1, 6);
    expect(meteorFade(0.09 * life, life)).toBeCloseTo(0.5, 6);
    // Monotonic fade-out over the long tail.
    expect(meteorFade(0.4 * life, life)).toBeGreaterThan(meteorFade(0.8 * life, life));
  });

  it('keeps twinkle and nebula breathing subtle — presence, never strobe', () => {
    for (let t = 0; t < 25; t += 0.37) {
      const opacity = twinkleOpacity(0.6, t, 1.3);
      expect(opacity).toBeGreaterThanOrEqual(0.6 * 0.72 - 1e-9);
      expect(opacity).toBeLessThanOrEqual(0.6 + 1e-9);
      const breath = nebulaBreath(t, 0.4);
      expect(breath).toBeGreaterThanOrEqual(0.96 - 1e-9);
      expect(breath).toBeLessThanOrEqual(1.04 + 1e-9);
    }
  });

  it('bounds the render cost of the whole flourish layer', () => {
    expect(METEOR_POOL_SIZE).toBeLessThanOrEqual(4);
    expect(METEOR_TRAIL_POINTS).toBeLessThanOrEqual(16);
    expect(METEOR_TRAIL_SPAN_S).toBeLessThan(0.5);
  });
});
