/**
 * 星空 render budget — pure quality/performance decisions for the WebGL
 * stage, kept renderer-free so they stay unit-testable in Node:
 *
 * - device pixel ratio is capped by a hard ceiling *and* a total pixel
 *   budget, so a fullscreen retina sky never renders 8M+ pixels per frame;
 * - a one-way quality ladder lowers that ceiling further under sustained
 *   slow frames, so a loaded machine gets its GPU headroom back instead of
 *   the sky dragging the whole OS;
 * - sphere geometry LOD levels whose switch distances scale with body size,
 *   so far-away moons cost a fraction of the vertices;
 * - surface texture resolutions bounded per body size, so a Session with
 *   fifty moons stays within a few megabytes of texture memory.
 */

/**
 * Hard DPR ceiling. A deep-space scene is dominated by smooth gradients and
 * additive glows, so anything beyond 1.5 spends GPU time on pixels the eye
 * cannot separate — the fill-rate saving at 1.5 vs 2 is ~44% per frame.
 */
export const MAX_PIXEL_RATIO = 1.5;

/** Total pixel budget per frame ≈ 1080p × 1.5² supersample, minus headroom. */
export const MAX_RENDER_PIXELS = 4_200_000;

function round2(value: number): number {
  return Math.round(value * 100) / 100;
}

/**
 * Effective renderer pixel ratio: clamp to [1, MAX_PIXEL_RATIO], then shrink
 * further whenever width × height × ratio² would exceed the pixel budget.
 */
export function starfieldPixelRatio(devicePixelRatio: number, width: number, height: number): number {
  const capped = Math.min(Math.max(devicePixelRatio || 1, 1), MAX_PIXEL_RATIO);
  const area = Math.max(width * height, 1);
  if (area * capped * capped <= MAX_RENDER_PIXELS) return round2(capped);
  return round2(Math.max(1, Math.sqrt(MAX_RENDER_PIXELS / area)));
}

/**
 * Adaptive resolution ladder: each step lowers the effective DPR ceiling.
 * One-way (never steps back up) so the sky cannot oscillate between
 * resolutions while load fluctuates around the threshold.
 */
export const PIXEL_RATIO_LADDER = [MAX_PIXEL_RATIO, 1.25, 1] as const;

/** A frame slower than this (≈38 fps) counts against the budget. */
export const SLOW_FRAME_S = 0.026;

/** Sustained slow frames required before stepping the ladder down. */
export const SLOW_FRAMES_BEFORE_STEP = 60;

/** Pixel-budgeted ratio further capped by the current ladder step. */
export function ladderedPixelRatio(
  devicePixelRatio: number,
  width: number,
  height: number,
  step: number,
): number {
  const bounded = Math.min(Math.max(step, 0), PIXEL_RATIO_LADDER.length - 1);
  return Math.min(starfieldPixelRatio(devicePixelRatio, width, height), PIXEL_RATIO_LADDER[bounded]!);
}

/**
 * Slow-frame accounting: sustained misses accumulate, healthy frames pay the
 * counter down twice as fast, so only genuine load (not a single GC pause)
 * reaches `SLOW_FRAMES_BEFORE_STEP`.
 */
export function nextSlowFrameCount(current: number, frameDtS: number): number {
  return frameDtS > SLOW_FRAME_S ? current + 1 : Math.max(0, current - 2);
}

/**
 * Whether the WebGL context should allocate a multisampled buffer.
 *
 * MSAA and supersampling solve the same problem twice. On a retina display
 * the stage already renders above 1 device pixel per CSS pixel, which smooths
 * the thin orbit lines MSAA was there for — so the extra samples buy almost
 * nothing while costing real bandwidth on the largest surface in the app. A
 * 1× display has no such headroom and keeps its multisampling.
 */
export function starfieldAntialias(devicePixelRatio: number): boolean {
  return (devicePixelRatio || 1) < 1.5;
}

export type SphereDetail = 'high' | 'medium' | 'low';

/** Width/height segment pairs for the three shared unit-sphere geometries. */
export const SPHERE_SEGMENTS: Record<SphereDetail, readonly [number, number]> = {
  high: [48, 28],
  medium: [24, 16],
  low: [12, 8],
};

export interface SphereLodLevel {
  detail: SphereDetail;
  /** World distance at which this level becomes active. */
  distance: number;
}

/**
 * LOD switch distances scale with the square root of body size: a small moon
 * drops detail much closer to the camera than a large planet, because its
 * screen footprint shrinks faster.
 */
export function sphereLodLevels(size: number): SphereLodLevel[] {
  const scale = Math.sqrt(Math.min(Math.max(size, 0.2), 2));
  return [
    { detail: 'high', distance: 0 },
    { detail: 'medium', distance: round2(15 * scale) },
    { detail: 'low', distance: round2(30 * scale) },
  ];
}

export interface SurfaceTextureSize {
  width: number;
  height: number;
}

/** Equirect surface resolution per body size — bounded at 512×256. */
export function surfaceTextureSize(bodySize: number): SurfaceTextureSize {
  const width = bodySize < 0.45 ? 128 : bodySize < 1 ? 256 : 512;
  return { width, height: width / 2 };
}

/**
 * Resolution for a body that also has a photographic map on its way: the
 * procedural surface is only the stand-in until the file lands, so it is
 * synthesised one tier smaller. Generation cost scales with area, making
 * this a ~4× saving on exactly the bodies whose noise map is about to be
 * thrown away — while an offline sky still gets a complete surface.
 */
export function fallbackSurfaceTextureSize(bodySize: number): SurfaceTextureSize {
  const width = Math.max(128, surfaceTextureSize(bodySize).width >> 1);
  return { width, height: width / 2 };
}
