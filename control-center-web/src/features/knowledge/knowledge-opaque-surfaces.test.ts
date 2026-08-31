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
    expect(knowledgeCss).not.toMatch(/transition:\s*width/);
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

  it('keeps all four graph controls in one reachable 44px row in narrow windows', () => {
    expect(knowledgeCss).toMatch(
      /\.knowledge-graph__canvas-controls \.ui-button\s*\{[^}]*width:\s*44px;[^}]*min-width:\s*44px;[^}]*min-height:\s*44px;/s,
    );
    const compact = /@container knowledge-graph \(max-width: 560px\)\s*\{([\s\S]*?)\n\}/.exec(knowledgeCss)?.[1] ?? '';
    const controls = /\.knowledge-graph__canvas-controls\s*\{([^}]*)\}/s.exec(compact)?.[1] ?? '';
    expect(controls).toMatch(/display:\s*flex;/);
    expect(controls).not.toContain('grid-template-columns');
  });

  it('rounds the shared library panel radius to the PAWOS panel scale instead of the legacy 4px paper corner', () => {
    expect(knowledgeCss).toMatch(/--radius-3:\s*12px;/);
  });
});
