export type GalaxyLabelAnchor = { id: string; x: number; y: number; radius: number; width: number; height: number };
export type GalaxyLabelPlacement = GalaxyLabelAnchor & { left: number; top: number };

export function placeGalaxyLabels(anchors: readonly GalaxyLabelAnchor[], width: number, height: number, selected: string | null): GalaxyLabelPlacement[] {
  const placed: GalaxyLabelPlacement[] = [];
  const clamp = (value: number, low: number, high: number) => Math.max(low, Math.min(Math.max(low, high), value));
  const ordered = [...anchors].sort((a, b) => Number(b.id === selected) - Number(a.id === selected));
  for (const anchor of ordered) {
    let best: GalaxyLabelPlacement | undefined;
    let bestScore = Infinity;
    // Start near the body, then search the surrounding screen space. No DOM
    // measurement or simulation mutation is needed to keep labels readable.
    for (let ring = 0; ring < 7; ring++) {
      for (const [dx, dy] of [[0, 1], [0, -1], [1, 0], [-1, 0], [1, 1], [-1, 1], [1, -1], [-1, -1]]) {
        const left = clamp(anchor.x - anchor.width / 2 + dx! * (anchor.width / 2 + anchor.radius + 14 + ring * 28), 12, width - anchor.width - 12);
        const top = clamp(anchor.y - anchor.height / 2 + dy! * (anchor.height / 2 + anchor.radius + 12 + ring * 34), 100, height - anchor.height - 110);
        let score = Math.hypot(left + anchor.width / 2 - anchor.x, top - anchor.y - anchor.radius - 12);
        for (const other of placed) {
          const overlapX = Math.max(0, Math.min(left + anchor.width + 7, other.left + other.width + 7) - Math.max(left, other.left));
          const overlapY = Math.max(0, Math.min(top + anchor.height + 7, other.top + other.height + 7) - Math.max(top, other.top));
          score += overlapX * overlapY * 1000;
        }
        for (const body of anchors) {
          const x = clamp(body.x, left, left + anchor.width), y = clamp(body.y, top, top + anchor.height);
          score += Math.max(0, body.radius + 5 - Math.hypot(body.x - x, body.y - y)) ** 2 * 300;
        }
        if (score < bestScore) { bestScore = score; best = { ...anchor, left, top }; }
      }
    }
    if (best) placed.push(best);
  }
  return placed;
}
