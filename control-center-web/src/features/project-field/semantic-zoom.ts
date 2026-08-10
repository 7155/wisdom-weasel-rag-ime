export type ProjectFieldZoomLevel = 'far' | 'mid' | 'near';

export type ProjectFieldZoomProjection = {
  counterScale: number;
  level: ProjectFieldZoomLevel;
};

/**
 * The map moves in world space, while Room labels retain a readable screen size.
 * The cap keeps distant waypoints compact instead of turning them into floating cards.
 */
export function projectFieldZoomProjection(scale: number): ProjectFieldZoomProjection {
  const safeScale = Number.isFinite(scale) && scale > 0 ? scale : 1;
  const level = safeScale < 0.86 ? 'far' : safeScale > 1.04 ? 'near' : 'mid';

  return {
    counterScale: Math.min(1.42, Math.max(1, 1 / safeScale)),
    level,
  };
}
