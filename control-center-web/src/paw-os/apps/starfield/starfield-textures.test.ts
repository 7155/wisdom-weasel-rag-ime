import { describe, expect, it } from 'vitest';
import * as THREE from 'three';
import {
  archetypeForPalette,
  archetypeForSeed,
  generatePlanetMaps,
  generateRadialGlow,
  generateRingMap,
  generateSkyMap,
  generateStarMap,
  generateSunMap,
  periodicFbm,
  StarfieldTextureFactory,
  type GeneratedTextureData,
  type PlanetArchetype,
} from './starfield-textures';

/** FNV-1a over the raw bytes — cheap whole-image fingerprint. */
function digest(image: GeneratedTextureData): number {
  let state = 0x811c9dc5;
  for (let index = 0; index < image.data.length; index += 1) {
    state ^= image.data[index]!;
    state = Math.imul(state, 0x01000193);
  }
  return state >>> 0;
}

function channelMean(image: GeneratedTextureData, channel: number): number {
  let sum = 0;
  for (let index = channel; index < image.data.length; index += 4) sum += image.data[index]!;
  return sum / (image.data.length / 4);
}

function channelMax(image: GeneratedTextureData, channel: number): number {
  let max = 0;
  for (let index = channel; index < image.data.length; index += 4) {
    if (image.data[index]! > max) max = image.data[index]!;
  }
  return max;
}

const SMALL = { width: 64, height: 32 };

describe('starfield procedural textures', () => {
  it('wraps fBm noise horizontally so equirect surfaces are seamless', () => {
    for (const y of [0.3, 1.7, 3.2]) {
      expect(periodicFbm(0, y, 12, 7)).toBeCloseTo(periodicFbm(12, y, 12, 7), 10);
    }
  });

  it('generates deterministic planet maps: same identity, same surface', () => {
    const options = { seed: 'run-live', archetype: 'rocky' as PlanetArchetype, baseColor: 0xde8273, ...SMALL };
    const first = generatePlanetMaps(options);
    const second = generatePlanetMaps(options);
    expect(digest(first.albedo)).toBe(digest(second.albedo));
    expect(digest(first.normal)).toBe(digest(second.normal));
    // A different Runtime identity gets a visibly different surface.
    const other = generatePlanetMaps({ ...options, seed: 'run-done' });
    expect(digest(other.albedo)).not.toBe(digest(first.albedo));
    // Albedo stays fully opaque.
    expect(channelMean(first.albedo, 3)).toBe(255);
  });

  it('keeps the six archetypes visually distinct on the same seed and hue', () => {
    const archetypes: PlanetArchetype[] = ['ocean', 'rocky', 'desert', 'gas', 'ice', 'terra'];
    const digests = archetypes.map((archetype) =>
      digest(generatePlanetMaps({ seed: 'body-1', archetype, baseColor: 0x5b9bf0, ...SMALL }).albedo));
    expect(new Set(digests).size).toBe(archetypes.length);
  });

  it('derives a plausible tangent-space normal map from the height field', () => {
    const { normal } = generatePlanetMaps({
      seed: 'body-1',
      archetype: 'rocky',
      baseColor: 0x5b9bf0,
      ...SMALL,
    });
    // Mostly outward-facing: strong blue, red/green centered near 128.
    expect(channelMean(normal, 2)).toBeGreaterThan(180);
    expect(channelMean(normal, 0)).toBeGreaterThan(108);
    expect(channelMean(normal, 0)).toBeLessThan(148);
    expect(channelMean(normal, 1)).toBeGreaterThan(108);
    expect(channelMean(normal, 1)).toBeLessThan(148);
    // Actual relief: some texel meaningfully deviates from flat.
    const deviates = Array.from({ length: normal.data.length / 4 }, (_, index) =>
      Math.abs(normal.data[index * 4]! - 128)).some((delta) => delta > 12);
    expect(deviates).toBe(true);
  });

  it('bakes a warm granulated sun and a neutral star map for tinting', () => {
    const sun = generateSunMap('room-1', 64);
    expect(digest(sun)).toBe(digest(generateSunMap('room-1', 64)));
    expect(channelMean(sun, 0)).toBeGreaterThan(channelMean(sun, 2));
    expect(channelMax(sun, 0)).toBeGreaterThanOrEqual(240);
    const star = generateStarMap('shared-star', 64);
    // Neutral: channels close so the material color owns the hue.
    expect(Math.abs(channelMean(star, 0) - channelMean(star, 2))).toBeLessThan(14);
  });

  it('bakes a deep sky with a bright star scatter over a dark base', () => {
    const sky = generateSkyMap('session-1', 128);
    expect(digest(sky)).toBe(digest(generateSkyMap('session-1', 128)));
    expect(digest(sky)).not.toBe(digest(generateSkyMap('session-2', 128)));
    // Dark space base with genuinely bright stars punched through.
    expect(channelMean(sky, 2)).toBeLessThan(90);
    expect(channelMax(sky, 1)).toBeGreaterThan(220);
  });

  it('bakes a banded ring with transparent gaps and solid bands', () => {
    const ring = generateRingMap('room-1', 64);
    let transparent = 0;
    let solid = 0;
    for (let index = 3; index < ring.data.length; index += 4) {
      if (ring.data[index]! === 0) transparent += 1;
      if (ring.data[index]! > 110) solid += 1;
    }
    expect(transparent).toBeGreaterThan(0);
    expect(solid).toBeGreaterThan(0);
  });

  it('shapes radial glows with an opaque core and transparent edge', () => {
    const glow = generateRadialGlow({ size: 32 });
    const center = ((16 * 32) + 16) * 4 + 3;
    expect(glow.data[center]!).toBeGreaterThan(200);
    expect(glow.data[3]!).toBe(0);
  });

  it('maps palette slots to stable archetypes and wraps out-of-range slots', () => {
    expect([0, 1, 2, 3, 4, 5].map(archetypeForPalette)).toEqual([
      'ocean', 'rocky', 'desert', 'gas', 'ice', 'terra',
    ]);
    expect(archetypeForPalette(7)).toBe(archetypeForPalette(1));
    expect(archetypeForSeed('session-1')).toBe(archetypeForSeed('session-1'));
  });
});

describe('starfield texture factory', () => {
  it('caches by identity, marks ownership, and survives dispose cleanly', () => {
    const factory = new StarfieldTextureFactory();
    const sun = factory.sun('sol');
    expect(factory.sun('sol')).toBe(sun);
    expect(factory.sun('other')).not.toBe(sun);
    expect(factory.owns(sun)).toBe(true);
    expect(factory.owns(new THREE.Texture())).toBe(false);

    const pair = factory.planet({ seed: 'p', archetype: 'terra', baseColor: 0x5b9bf0, width: 32 });
    // Albedo is sRGB while the normal map stays linear, both wrapping in x.
    expect(pair.map.colorSpace).toBe(THREE.SRGBColorSpace);
    expect(pair.normalMap.colorSpace).toBe(THREE.NoColorSpace);
    expect(pair.map.wrapS).toBe(THREE.RepeatWrapping);
    expect(factory.planet({ seed: 'p', archetype: 'terra', baseColor: 0x5b9bf0, width: 32 }).map).toBe(pair.map);

    factory.dispose();
    expect(factory.owns(sun)).toBe(false);
    // A fresh acquire after dispose regenerates rather than reusing disposed GPU state.
    expect(factory.sun('sol')).not.toBe(sun);
  });
});
