/**
 * Pure geometry for the magnetic Dock. The pointer lifts and grows the
 * nearest identities on a smooth cosine falloff, every other child is pushed
 * outward by half of each grown neighbour's extra width, and the whole
 * neighbourhood leans slightly toward the pointer on a sine curve — zero
 * directly under the cursor, zero at the influence edge, strongest halfway.
 * The gather is what makes the shelf feel magnetic instead of merely scaled;
 * its amplitude stays below the resting gap headroom so grown neighbours can
 * never overlap (dock-magnification.test.ts proves the worst mid-gap case).
 * The caller applies the result as CSS custom properties driving
 * transform-only styles: layout never changes, nothing repaints, dragging
 * cannot flicker.
 */
export type DockMagnetics = {
  /** 0..1 magnification energy per child, 1 directly under the pointer. */
  mag: number[];
  /** Signed horizontal travel in px per child: neighbour push + magnet gather. */
  shift: number[];
};

export type DockMagneticsOptions = {
  /** Pointer influence radius in px. */
  radius?: number;
  /** Maximum extra scale at energy 1 (e.g. .3 => scale 1.3). */
  grow?: number;
  /** Resting child width in px used to convert growth into push distance. */
  baseWidth?: number;
  /** Maximum magnet gather toward the pointer in px, at half the radius. */
  attract?: number;
};

export const DOCK_MAGNIFY_RADIUS = 96;
/** Matches the rendered `scale(1 + mag * .32)` in paw-os.css exactly, so the
 * neighbour push always clears the real grown width, not an estimate. */
export const DOCK_MAGNIFY_GROW = 0.32;
export const DOCK_MAGNIFY_BASE_WIDTH = 44;
export const DOCK_MAGNIFY_ATTRACT = 3;

export function dockMagnetics(
  centers: readonly number[],
  pointerX: number,
  options: DockMagneticsOptions = {},
): DockMagnetics {
  const radius = options.radius ?? DOCK_MAGNIFY_RADIUS;
  const grow = options.grow ?? DOCK_MAGNIFY_GROW;
  const baseWidth = options.baseWidth ?? DOCK_MAGNIFY_BASE_WIDTH;
  const attract = options.attract ?? DOCK_MAGNIFY_ATTRACT;
  const mag = centers.map((center) => {
    const distance = Math.abs(center - pointerX);
    if (!Number.isFinite(distance) || distance >= radius) return 0;
    return (Math.cos((distance / radius) * Math.PI) + 1) / 2;
  });
  const growth = mag.map((energy) => energy * grow * baseWidth);
  const shift = centers.map((center, index) => {
    let push = 0;
    for (let other = 0; other < centers.length; other += 1) {
      if (other === index) continue;
      push += (other < index ? 1 : -1) * (growth[other] / 2);
    }
    const offset = center - pointerX;
    const distance = Math.abs(offset);
    const gather = Number.isFinite(distance) && distance > 0 && distance < radius
      ? -Math.sign(offset) * Math.sin((distance / radius) * Math.PI) * attract
      : 0;
    return push + gather;
  });
  return { mag, shift };
}
