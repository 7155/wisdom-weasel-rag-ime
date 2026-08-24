import { describe, expect, it } from 'vitest';
import {
  DOCK_MAGNIFY_BASE_WIDTH,
  DOCK_MAGNIFY_GROW,
  dockMagnetics,
} from './dock-magnification';

const centers = [22, 71, 120, 169, 218];

describe('Dock proximity magnification geometry', () => {
  it('peaks directly under the pointer and falls off smoothly with distance', () => {
    const { mag } = dockMagnetics(centers, 120, { radius: 96 });
    expect(mag[2]).toBe(1);
    expect(mag[1]).toBeGreaterThan(0);
    expect(mag[1]).toBeLessThan(1);
    expect(mag[1]).toBeCloseTo(mag[3], 10);
    expect(mag[1]).toBeGreaterThan(mag[0]);
  });

  it('leaves children outside the influence radius completely at rest', () => {
    const { mag, shift } = dockMagnetics(centers, 22, { radius: 60 });
    expect(mag[2]).toBe(0);
    expect(mag[4]).toBe(0);
    // A resting child is still pushed by its grown neighbours.
    expect(shift[4]).toBeGreaterThan(0);
  });

  it('pushes neighbours outward from the magnified zone symmetrically', () => {
    const { shift } = dockMagnetics(centers, 120, { radius: 96 });
    expect(shift[2]).toBeCloseTo(0, 10);
    expect(shift[0]).toBeLessThan(0);
    expect(shift[4]).toBeGreaterThan(0);
    expect(shift[0]).toBeCloseTo(-shift[4], 10);
    // The outermost child accumulates the most push.
    expect(Math.abs(shift[0])).toBeGreaterThan(Math.abs(shift[1]));
  });

  it('converts growth into push using half of each neighbour extra width', () => {
    const { mag, shift } = dockMagnetics([0, 100], 0, { radius: 50, grow: 0.5, baseWidth: 40 });
    // Only the first child grows: energy 1 * .5 * 40px = 20px extra width.
    expect(mag).toEqual([1, 0]);
    expect(shift[0]).toBe(0);
    expect(shift[1]).toBe(10);
  });

  it('returns zeroed rest state for a pointer far away', () => {
    const { mag, shift } = dockMagnetics(centers, 10_000);
    expect(mag.every((value) => value === 0)).toBe(true);
    expect(shift.every((value) => value === 0)).toBe(true);
  });

  it('gathers the neighbourhood toward the pointer like a magnet', () => {
    // With push disabled the remaining travel is pure attraction. Children at
    // half the radius lean hardest toward the pointer, the lean dies at the
    // influence edge, and everything beyond the radius stays at rest.
    const { shift } = dockMagnetics([0, 48, 90, 140], 0, { grow: 0, radius: 96, attract: 3 });
    expect(shift[0]).toBe(0);
    expect(shift[1]).toBeCloseTo(-3, 10);
    expect(shift[2]).toBeLessThan(0);
    expect(Math.abs(shift[1])).toBeGreaterThan(Math.abs(shift[2]));
    expect(shift[3]).toBe(0);
  });

  it('keeps the magnet gather zero under the pointer and symmetric around it', () => {
    const { shift } = dockMagnetics(centers, 120, { grow: 0 });
    expect(shift[2]).toBe(0);
    expect(shift[1]).toBeCloseTo(-shift[3], 10);
    expect(shift[1]).toBeGreaterThan(0);
    expect(shift[3]).toBeLessThan(0);
  });

  it('never lets grown neighbours overlap, even at the worst mid-gap pointer', () => {
    // Real shelf geometry: 44px children with a 5px resting gap. The edge of
    // each grown child i is centre + shift ± grownWidth/2; adjacent edges must
    // keep clearance at every pointer position across the shelf.
    const gap = 5;
    const spacing = DOCK_MAGNIFY_BASE_WIDTH + gap;
    const shelf = Array.from({ length: 9 }, (_, index) => 22 + index * spacing);
    for (let pointerX = shelf[0]! - 60; pointerX <= shelf.at(-1)! + 60; pointerX += 1) {
      const { mag, shift } = dockMagnetics(shelf, pointerX);
      for (let index = 0; index < shelf.length - 1; index += 1) {
        const rightEdge = shelf[index]! + shift[index]!
          + (DOCK_MAGNIFY_BASE_WIDTH * (1 + mag[index]! * DOCK_MAGNIFY_GROW)) / 2;
        const nextLeftEdge = shelf[index + 1]! + shift[index + 1]!
          - (DOCK_MAGNIFY_BASE_WIDTH * (1 + mag[index + 1]! * DOCK_MAGNIFY_GROW)) / 2;
        expect(nextLeftEdge - rightEdge, `clearance at pointer ${pointerX} between ${index} and ${index + 1}`)
          .toBeGreaterThan(0);
      }
    }
  });
});
