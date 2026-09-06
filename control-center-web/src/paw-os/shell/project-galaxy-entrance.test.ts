import { describe, expect, it } from 'vitest';
import { starfieldEntrance } from './project-galaxy-entrance';

describe('starfield entrance', () => {
  it('reveals every planet from the core and settles in its actual orbit', () => {
    const start = starfieldEntrance(0, 0, false);
    const middle = starfieldEntrance(.5, 0, false);
    const end = starfieldEntrance(2, 11, false);
    expect(start.radius).toBeLessThan(.2);
    expect(middle.radius).toBeGreaterThan(start.radius);
    expect(start.phase).toBeLessThan(0);
    expect(end).toEqual({ radius: 1, scale: 1, phase: 0, complete: true });
  });
  it('skips the whole entrance for reduced motion instead of freezing mid-flight', () => {
    expect(starfieldEntrance(0, 11, true)).toEqual({ radius: 1, scale: 1, phase: 0, complete: true });
  });
});
