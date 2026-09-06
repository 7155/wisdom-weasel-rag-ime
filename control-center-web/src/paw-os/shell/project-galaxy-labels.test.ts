import { describe, expect, it } from 'vitest';
import { placeGalaxyLabels, type GalaxyLabelPlacement } from './project-galaxy-labels';

const overlaps = (a: GalaxyLabelPlacement, b: GalaxyLabelPlacement) => a.left < b.left + b.width && a.left + a.width > b.left && a.top < b.top + b.height && a.top + a.height > b.top;
describe('moving galaxy labels', () => {
  it('keeps close projected planets readable without changing their anchors', () => {
    const anchors = Array.from({ length: 4 }, (_, i) => ({ id: String(i), x: 470 + i * 22, y: 290 + i * 14, radius: 30, width: 152, height: 46 }));
    const labels = placeGalaxyLabels(anchors, 1000, 700, '2');
    for (const [i, label] of labels.entries()) {
      expect(label.x).toBe(anchors.find((anchor) => anchor.id === label.id)!.x);
      labels.slice(i + 1).forEach((other) => expect(overlaps(label, other)).toBe(false));
    }
  });
  it('keeps crowded labels within a narrow map below the header and above navigation', () => {
    const anchors = Array.from({ length: 6 }, (_, i) => ({ id: String(i), x: 160 + i * 8, y: 300 + i * 9, radius: 13, width: 138, height: 44 }));
    const labels = placeGalaxyLabels(anchors, 390, 760, null);
    for (const [i, label] of labels.entries()) {
      expect(label.left).toBeGreaterThanOrEqual(12);
      expect(label.left + label.width).toBeLessThanOrEqual(378);
      expect(label.top).toBeGreaterThanOrEqual(100);
      expect(label.top + label.height).toBeLessThanOrEqual(650);
      labels.slice(i + 1).forEach((other) => expect(overlaps(label, other)).toBe(false));
    }
  });
});
