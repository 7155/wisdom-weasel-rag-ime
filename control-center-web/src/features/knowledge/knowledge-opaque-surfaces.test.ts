import { describe, expect, it } from 'vitest';
import knowledgeCss from './knowledge.css?raw';

// One PAWOS UI contract: control/panel surfaces are opaque (paw-os-controls.css).
// Knowledge's floating graph controls, legend and inspector used to rely on
// backdrop-filter over the live canvas — a "glass" material the shared control
// language explicitly forbids outside true window chrome. They must stay
// fully opaque so their text never depends on an unknown backdrop.
describe('Knowledge floating surfaces stay opaque', () => {
  it('never applies backdrop-filter to the graph overlay controls', () => {
    expect(knowledgeCss).not.toMatch(/backdrop-filter:\s*blur/);
  });

  it('keeps the graph canvas controls, legend and inspector on a solid surface colour', () => {
    expect(knowledgeCss).toMatch(
      /\.knowledge-graph__canvas-controls\s*\{[^}]*background:\s*var\(--color-surface\);/s,
    );
    expect(knowledgeCss).toMatch(
      /\.knowledge-graph__legend\s*\{[^}]*background:\s*var\(--color-surface\);/s,
    );
    expect(knowledgeCss).toMatch(
      /\.knowledge-graph__inspector\s*\{[^}]*background:\s*var\(--color-surface\);/s,
    );
  });

  it('rounds the shared library panel radius to the PAWOS panel scale instead of the legacy 4px paper corner', () => {
    expect(knowledgeCss).toMatch(/--radius-3:\s*12px;/);
  });
});
