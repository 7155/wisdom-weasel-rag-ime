import { describe, expect, it } from 'vitest';
import {
  fallbackSurfaceTextureSize,
  MAX_PIXEL_RATIO,
  MAX_RENDER_PIXELS,
  SPHERE_SEGMENTS,
  sphereLodLevels,
  starfieldPixelRatio,
  surfaceTextureSize,
} from './starfield-render-quality';

describe('starfield render budget', () => {
  it('caps the device pixel ratio at the hard ceiling for small canvases', () => {
    expect(starfieldPixelRatio(1, 800, 600)).toBe(1);
    expect(starfieldPixelRatio(3, 800, 600)).toBe(MAX_PIXEL_RATIO);
    // Broken DPR input still yields a sane ratio.
    expect(starfieldPixelRatio(0, 800, 600)).toBe(1);
  });

  it('never renders above 1.5× device pixels, however retina the display', () => {
    // The performance contract for the sky, not an incidental constant: a
    // 3× phone screen and a 2× laptop both stay at or below 1.5.
    expect(MAX_PIXEL_RATIO).toBeLessThanOrEqual(1.5);
    for (const dpr of [1, 1.5, 2, 2.75, 3, 4]) {
      expect(starfieldPixelRatio(dpr, 1440, 900)).toBeLessThanOrEqual(1.5);
    }
  });

  it('shrinks the ratio so a fullscreen retina sky stays within the pixel budget', () => {
    const ratio = starfieldPixelRatio(2, 1920, 1080);
    expect(ratio).toBeLessThan(MAX_PIXEL_RATIO);
    expect(ratio).toBeGreaterThanOrEqual(1);
    expect(1920 * 1080 * ratio * ratio).toBeLessThanOrEqual(MAX_RENDER_PIXELS * 1.01);
    // Never below 1 even for extreme canvases.
    expect(starfieldPixelRatio(2, 4000, 3000)).toBe(1);
    // Monotonic: a bigger viewport never gets a bigger ratio.
    expect(starfieldPixelRatio(2, 2560, 1440)).toBeLessThanOrEqual(ratio);
  });

  it('scales LOD switch distances with body size so moons drop detail sooner', () => {
    const moon = sphereLodLevels(0.3);
    const planet = sphereLodLevels(1.5);
    expect(moon.map((level) => level.detail)).toEqual(['high', 'medium', 'low']);
    expect(moon[0]!.distance).toBe(0);
    expect(moon[1]!.distance).toBeLessThan(moon[2]!.distance);
    expect(moon[1]!.distance).toBeLessThan(planet[1]!.distance);
    expect(moon[2]!.distance).toBeLessThan(planet[2]!.distance);
    // Every detail level has a shared geometry definition.
    for (const level of moon) expect(SPHERE_SEGMENTS[level.detail]).toBeDefined();
  });

  it('bounds surface texture resolution per body size', () => {
    expect(surfaceTextureSize(0.3)).toEqual({ width: 128, height: 64 });
    expect(surfaceTextureSize(0.56)).toEqual({ width: 256, height: 128 });
    expect(surfaceTextureSize(1.5)).toEqual({ width: 512, height: 256 });
    expect(surfaceTextureSize(99).width).toBeLessThanOrEqual(512);
  });

  it('synthesises a smaller fallback for bodies whose photo is on its way', () => {
    // Generation cost scales with area, so one tier down is a ~4× saving on
    // a map that a photographic surface is about to replace.
    for (const size of [0.3, 0.56, 1.5, 99]) {
      const full = surfaceTextureSize(size);
      const fallback = fallbackSurfaceTextureSize(size);
      expect(fallback.width).toBeLessThanOrEqual(full.width);
      expect(fallback.height).toBe(fallback.width / 2);
    }
    expect(fallbackSurfaceTextureSize(1.5)).toEqual({ width: 256, height: 128 });
    // An offline sky still needs a readable surface: never below 128.
    expect(fallbackSurfaceTextureSize(0.1).width).toBe(128);
  });
});
