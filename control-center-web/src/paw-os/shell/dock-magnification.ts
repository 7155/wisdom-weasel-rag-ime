/**
 * Pure geometry for the Dock proximity magnification. The pointer lifts and
 * grows the nearest identities on a smooth cosine falloff, and every other
 * child is pushed outward by half of each grown neighbour's extra width, so
 * the shelf reads like real material instead of overlapping sprites. The
 * caller applies the result as CSS custom properties driving transform-only
 * styles: layout never changes, nothing repaints, dragging cannot flicker.
 */
export type DockMagnetics = {
  /** 0..1 magnification energy per child, 1 directly under the pointer. */
  mag: number[];
  /** Signed horizontal push in px per child, away from the magnified zone. */
  shift: number[];
};

export type DockMagneticsOptions = {
  /** Pointer influence radius in px. */
  radius?: number;
  /** Maximum extra scale at energy 1 (e.g. .3 => scale 1.3). */
  grow?: number;
  /** Resting child width in px used to convert growth into push distance. */
  baseWidth?: number;
};

export const DOCK_MAGNIFY_RADIUS = 96;
export const DOCK_MAGNIFY_GROW = 0.3;
export const DOCK_MAGNIFY_BASE_WIDTH = 44;

export function dockMagnetics(
  centers: readonly number[],
  pointerX: number,
  options: DockMagneticsOptions = {},
): DockMagnetics {
  const radius = options.radius ?? DOCK_MAGNIFY_RADIUS;
  const grow = options.grow ?? DOCK_MAGNIFY_GROW;
  const baseWidth = options.baseWidth ?? DOCK_MAGNIFY_BASE_WIDTH;
  const mag = centers.map((center) => {
    const distance = Math.abs(center - pointerX);
    if (!Number.isFinite(distance) || distance >= radius) return 0;
    return (Math.cos((distance / radius) * Math.PI) + 1) / 2;
  });
  const growth = mag.map((energy) => energy * grow * baseWidth);
  const shift = centers.map((_, index) => {
    let push = 0;
    for (let other = 0; other < centers.length; other += 1) {
      if (other === index) continue;
      push += (other < index ? 1 : -1) * (growth[other] / 2);
    }
    return push;
  });
  return { mag, shift };
}
