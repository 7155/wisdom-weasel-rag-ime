import { describe, expect, it } from 'vitest';
import { dockMagnetics } from './dock-magnification';

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
});
