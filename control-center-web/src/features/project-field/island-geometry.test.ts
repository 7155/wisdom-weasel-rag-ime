import { describe, expect, it } from 'vitest';
import { createWayfinderIslandGeometry } from './island-geometry';

const decisions = [
  { title: 'Project 是长期空间' },
  { title: 'Room 不是工单' },
  { title: '聚焦不离开项目' },
  { title: '导航只决定归属' },
] as const;

describe('Wayfinder island geometry', () => {
  it('turns stable decisions into deterministic SVG terrain', () => {
    const first = createWayfinderIslandGeometry(decisions);
    const second = createWayfinderIslandGeometry(decisions);

    expect(first).toEqual(second);
    expect(first?.semanticAnchors.map((anchor) => anchor.title)).toEqual(
      decisions.map((decision) => decision.title),
    );
    expect(first?.water).toMatch(/^M.+Z$/);
    expect(first?.shore).toMatch(/^M.+Z$/);
    expect(first?.highland).toMatch(/^M.+Z$/);
    expect(first?.contour).toMatch(/^M.+Z$/);
  });

  it('changes the coastline when the set of decisions changes', () => {
    const complete = createWayfinderIslandGeometry(decisions);
    const earlier = createWayfinderIslandGeometry(decisions.slice(0, 3));

    expect(complete?.shore).not.toBe(earlier?.shore);
  });

  it('declines to invent terrain before a Room has enough decisions', () => {
    expect(createWayfinderIslandGeometry(decisions.slice(0, 1))).toBeNull();
  });
});
