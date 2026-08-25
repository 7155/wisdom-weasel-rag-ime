import { describe, expect, it } from 'vitest';
import { synthesizeSurface, type SurfaceArchetype } from './starfield-texture-synth';

const ARCHETYPES: SurfaceArchetype[] = ['sun', 'gas', 'rocky', 'ice', 'cratered'];

function averageChannel(color: Uint8Array, channel: 0 | 1 | 2): number {
  let sum = 0;
  for (let offset = channel; offset < color.length; offset += 4) sum += color[offset]!;
  return sum / (color.length / 4);
}

function luminance(color: Uint8Array): number {
  let sum = 0;
  for (let offset = 0; offset < color.length; offset += 4) {
    sum += color[offset]! * 0.2126 + color[offset + 1]! * 0.7152 + color[offset + 2]! * 0.0722;
  }
  return sum / (color.length / 4);
}

describe('starfield surface synthesis', () => {
  it('emits correctly sized, fully opaque equirect maps for every archetype', () => {
    for (const archetype of ARCHETYPES) {
      const maps = synthesizeSurface({ archetype, seed: 'body-1', width: 64 });
      expect(maps.width).toBe(64);
      expect(maps.height).toBe(32);
      expect(maps.color).toHaveLength(64 * 32 * 4);
      expect(maps.bump).toHaveLength(64 * 32);
      for (let offset = 3; offset < maps.color.length; offset += 4) {
        expect(maps.color[offset]).toBe(255);
      }
    }
  });

  it('is deterministic per seed and diverges across seeds', () => {
    const first = synthesizeSurface({ archetype: 'rocky', seed: 'run-a', width: 32 });
    const again = synthesizeSurface({ archetype: 'rocky', seed: 'run-a', width: 32 });
    const other = synthesizeSurface({ archetype: 'rocky', seed: 'run-b', width: 32 });
    expect(Buffer.from(again.color).equals(Buffer.from(first.color))).toBe(true);
    expect(Buffer.from(again.bump).equals(Buffer.from(first.bump))).toBe(true);
    expect(Buffer.from(other.color).equals(Buffer.from(first.color))).toBe(false);
  });

  it('wraps seamlessly at the longitude seam', () => {
    // Sampling happens on the unit sphere, so the first and last columns are
    // adjacent directions — bytes may differ slightly but never jump.
    const { width, height, bump } = synthesizeSurface({ archetype: 'gas', seed: 'seam', width: 64 });
    for (let row = 0; row < height; row += 1) {
      const left = bump[row * width]!;
      const right = bump[row * width + width - 1]!;
      expect(Math.abs(left - right)).toBeLessThan(48);
    }
  });

  it('keeps sun surfaces warm and heat-sensitive', () => {
    const cool = synthesizeSurface({ archetype: 'sun', seed: 'sol', width: 32, hue: 0.1 });
    const hot = synthesizeSurface({ archetype: 'sun', seed: 'sol', width: 32, hue: 0.95 });
    expect(averageChannel(cool.color, 0)).toBeGreaterThan(averageChannel(cool.color, 2));
    expect(luminance(hot.color)).toBeGreaterThan(luminance(cool.color));
  });

  it('keeps ice bright and cratered regolith darker with real relief', () => {
    const ice = synthesizeSurface({ archetype: 'ice', seed: 'moon-1', width: 32, hue: 0.55 });
    const rock = synthesizeSurface({ archetype: 'cratered', seed: 'moon-1', width: 32, hue: 0.55 });
    expect(luminance(ice.color)).toBeGreaterThan(luminance(rock.color));
    const heights = [...rock.bump];
    expect(Math.max(...heights) - Math.min(...heights)).toBeGreaterThan(60);
  });

  it('tints gas giants by the requested hue', () => {
    const red = synthesizeSurface({ archetype: 'gas', seed: 'p', width: 32, hue: 0.02 });
    const blue = synthesizeSurface({ archetype: 'gas', seed: 'p', width: 32, hue: 0.6 });
    expect(averageChannel(red.color, 0)).toBeGreaterThan(averageChannel(red.color, 2));
    expect(averageChannel(blue.color, 2)).toBeGreaterThan(averageChannel(blue.color, 0));
  });
});
