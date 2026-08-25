import { describe, expect, it } from 'vitest';
import {
  MAX_PIXEL_RATIO,
  MAX_RENDER_PIXELS,
  SPHERE_SEGMENTS,
  sphereLodLevels,
  starfieldPixelRatio,
  surfaceTextureSize,
} from './starfield-render-quality';

describe('starfield render quality budget', () => {
  it('caps device pixel ratio at the hard ceiling on ordinary viewports', () => {
    expect(starfieldPixelRatio(3, 1280, 720)).toBe(MAX_PIXEL_RATIO);
    expect(starfieldPixelRatio(1.5, 1280, 720)).toBe(1.5);
    expect(starfieldPixelRatio(0, 1280, 720)).toBe(1);
  });

  it('shrinks the ratio further so huge viewports stay inside the pixel budget', () => {
    const ratio = starfieldPixelRatio(2, 1920, 1080);
    expect(ratio).toBeLessThan(MAX_PIXEL_RATIO);
    expect(ratio).toBeGreaterThan(1);
    expect(1920 * 1080 * ratio * ratio).toBeLessThanOrEqual(MAX_RENDER_PIXELS * 1.05);
    // Never below 1 even for viewports that exceed the budget at ratio 1.
    expect(starfieldPixelRatio(2, 3840, 2160)).toBe(1);
    expect(starfieldPixelRatio(2, 10_000, 10_000)).toBe(1);
  });

  it('orders sphere LOD levels near-to-far with detail decreasing', () => {
    for (const size of [0.3, 0.56, 1.5]) {
      const levels = sphereLodLevels(size);
      expect(levels[0]).toEqual({ detail: 'high', distance: 0 });
      expect(levels.map((level) => level.distance)).toEqual(
        [...levels.map((level) => level.distance)].sort((a, b) => a - b),
      );
    }
    // Small moons drop detail closer to the camera than large planets.
    expect(sphereLodLevels(0.3)[1]!.distance).toBeLessThan(sphereLodLevels(1.5)[1]!.distance);
    for (const [widthSegments, heightSegments] of Object.values(SPHERE_SEGMENTS)) {
      expect(widthSegments).toBeGreaterThan(0);
      expect(heightSegments).toBeGreaterThan(0);
    }
  });

  it('bounds surface texture resolution by body size', () => {
    expect(surfaceTextureSize(0.3)).toEqual({ width: 128, height: 64 });
    expect(surfaceTextureSize(0.56)).toEqual({ width: 256, height: 128 });
    expect(surfaceTextureSize(1.5)).toEqual({ width: 512, height: 256 });
  });
});
