import { describe, expect, it } from 'vitest';
import activityTimelineCss from './activity-timeline.css?raw';
import memoryCss from './memory.css?raw';

// One PAWOS UI contract: control/panel surfaces are opaque (paw-os-controls.css)
// and controls/panels round to the shared 8px/12px scale, not the legacy
// near-square "paper" corners (2/3/4px) design/tokens.css still exposes to
// callers that never opted into the rounded PAWOS geometry.
describe('Memory floating surfaces stay opaque and PAWOS-rounded', () => {
  it('never applies backdrop-filter to the relation canvas overlays or the native action bar', () => {
    expect(memoryCss).not.toMatch(/backdrop-filter:\s*blur/);
  });

  it('keeps the relation canvas focus card and native action bar on a solid surface colour', () => {
    expect(memoryCss).toMatch(
      /\.memory-relation-canvas__focus\s*\{[^}]*background:\s*var\(--color-surface\);/s,
    );
    expect(memoryCss).toContain('--memory-surface: var(--paw-panel, var(--color-surface, #fff))');
    expect(memoryCss).toMatch(
      /> \.mgmt-page__native-actions\s*\{[^}]*background:\s*var\(--memory-surface\);/s,
    );
  });

  it('retires the legacy 2/3/4px paper corner scale for every --radius-1/2/3 consumer on this route', () => {
    expect(memoryCss).toMatch(/--radius-1:\s*6px;/);
    expect(memoryCss).toMatch(/--radius-2:\s*8px;/);
    expect(memoryCss).toMatch(/--radius-3:\s*12px;/);
  });

  it('gives the daily-journal and period icon marks a real, defined corner radius', () => {
    // --radius-md was never defined anywhere in the design system, so the
    // custom property silently dropped the corner (square icon glyph).
    expect(activityTimelineCss).not.toContain('var(--radius-md)');
    expect(activityTimelineCss).toMatch(/\.daily-journal__mark\s*\{[^}]*border-radius:\s*10px;/s);
    expect(activityTimelineCss).toMatch(/\.activity-timeline__period-icon\s*\{[^}]*border-radius:\s*10px;/s);
  });
});
