import { describe, expect, it } from 'vitest';
import workbenchCss from './paw-os-workbench-migrated-v1.css?raw';

// One PAWOS UI contract: a single cobalt accent, not a competing purple
// flourish layered on top of it. Project Workbench previously mixed its
// cobalt identity (--paw-wb-accent, matching [data-app='project-workbench']
// in paw-os.css) with an unrelated violet (#6850d9) across four decorative
// gradients — a second, dead-var-only hue that read as a second theme.
describe('Project Workbench stays on one cobalt accent', () => {
  it('never declares or references the retired violet decoration token', () => {
    expect(workbenchCss).not.toMatch(/--paw-wb-violet/);
    expect(workbenchCss).not.toContain('6850d9');
    expect(workbenchCss).not.toContain('104 80 217');
  });

  it('keeps the ambient canvas, project mark and ledger divider on the shared cobalt hue', () => {
    expect(workbenchCss).toMatch(
      /radial-gradient\(1000px 520px at 98% -8%, rgb\(49 94 172 \/ 7%\), transparent 58%\)/,
    );
    expect(workbenchCss).toMatch(
      /\.paw-wb-ledger__mark\s*\{[^}]*background:\s*linear-gradient\(135deg, rgb\(49 94 172 \/ 16%\), rgb\(49 94 172 \/ 11%\)\);/s,
    );
    expect(workbenchCss).toMatch(
      /\.paw-wb-ledger::before\s*\{[^}]*background:\s*linear-gradient\(90deg, transparent 2%, rgb\(49 94 172 \/ 45%\) 30%, rgb\(49 94 172 \/ 34%\) 70%, transparent 98%\);/s,
    );
  });
});

// Window logic, not page logic: every Workbench page is fixed chrome around a
// flexible band, and the band hands its scroll to the pane that owns the work.
describe('Project Workbench lays out as a window, not a document', () => {
  it('keeps the overview a fixed shell whose panes own their own scroll', () => {
    expect(workbenchCss).toMatch(
      /\.paw-wb-overview\s*\{[^}]*display:\s*flex;[^}]*flex-direction:\s*column;[^}]*overflow:\s*hidden;/s,
    );
    expect(workbenchCss).toMatch(
      /\.paw-wb-overview__workspace\s*\{[^}]*flex:\s*1 1 auto;[^}]*grid-template-rows:\s*minmax\(0, 1fr\);/s,
    );
    expect(workbenchCss).toMatch(
      /\.paw-wb-pane > :is\(\.paw-wb-pane__list, \.paw-wb-pane__rows, \.paw-wb-pane__goals, \.paw-wb-empty\)\s*\{[^}]*flex:\s*1 1 auto;[^}]*overflow:\s*auto;/s,
    );
    // The retired hero plate and stat rail must not come back above the work.
    expect(workbenchCss).not.toContain('.paw-wb-project-lead');
    expect(workbenchCss).not.toContain('.paw-wb-overview__columns');
  });

  it('keeps the WorkDocument reader header fixed above one scrolling body', () => {
    expect(workbenchCss).toMatch(
      /\.paw-wb-document-reader\s*\{[^}]*display:\s*flex;[^}]*flex-direction:\s*column;[^}]*overflow:\s*hidden;/s,
    );
    expect(workbenchCss).toMatch(
      /\.paw-wb-document-reader__body\s*\{[^}]*flex:\s*1 1 auto;[^}]*overflow:\s*auto;/s,
    );
    expect(workbenchCss).toMatch(
      /\.paw-wb-document-index > ol\s*\{[^}]*flex:\s*1 1 auto;[^}]*overflow:\s*auto;/s,
    );
  });

  it('draws dependency lane ownership and keeps the lane header on the vertical scroll', () => {
    expect(workbenchCss).toMatch(/\.paw-wb-graph__band\s*\{[^}]*transform:\s*translateX\(calc\(var\(--paw-wb-lane-x\) - 12px\)\);/s);
    expect(workbenchCss).toMatch(/\.paw-wb-graph__lanes\s*\{[^}]*position:\s*sticky;[^}]*top:\s*0;/s);
    // Sticky on the block axis only, or the header stops naming its column.
    expect(workbenchCss).not.toMatch(/\.paw-wb-graph__lanes\s*\{[^}]*left:\s*0;/s);
  });

  it('keeps every decorative motion bounded and reduced-motion safe', () => {
    const keyframes = [...workbenchCss.matchAll(/@keyframes\s+([\w-]+)/g)].map(([, name]) => name);
    expect(keyframes).toEqual([
      'paw-wb-edge-flow',
      'paw-wb-packet-visible',
      'paw-wb-spin',
      'paw-wb-node-enter',
      'paw-wb-pane-rise',
    ]);
    expect(workbenchCss).toMatch(
      /@media \(prefers-reduced-motion: reduce\)[\s\S]*?animation-duration:\s*\.01ms\s*!important;[\s\S]*?\.paw-wb-flow-packet\s*\{\s*display:\s*none;/,
    );
  });

  it('lets the deck chrome wrap before command labels are clipped', () => {
    // Commands keep intrinsic width; the strip wraps instead of scrolling a
    // hidden scrollbar that ate mid-glyph labels in a crowded window.
    expect(workbenchCss).toMatch(
      /\.paw-wb-chrome\s*\{[^}]*flex-wrap:\s*wrap;/s,
    );
    expect(workbenchCss).toMatch(
      /\.paw-wb-chrome__commands\s*\{[^}]*min-width:\s*max-content;[^}]*overflow:\s*visible;/s,
    );
    expect(workbenchCss).toMatch(
      /\.paw-wb-chrome__identity\s*\{[^}]*max-width:\s*240px;/s,
    );
    // Mid-width stages must not hide command names — that read as broken UI.
    expect(workbenchCss).not.toMatch(
      /@container paw-native-stage \(max-width: 520px\)[\s\S]*?\.paw-wb-chrome__commands button > span \{ display: none;/,
    );
  });

  it('gives the wrapped deck an auto chrome row instead of a fixed 36px track', () => {
    // A wrapping deck inside a pinned 36px grid row clips its own second row.
    // The row is auto; the single-row minimum stays the shared 36px strip.
    expect(workbenchCss).toMatch(
      /\.paw-workbench-migrated\s*\{[^}]*grid-template-rows:\s*auto minmax\(0, 1fr\);/s,
    );
    expect(workbenchCss).toMatch(
      /\.paw-wb-chrome\s*\{[^}]*min-height:\s*36px;/s,
    );
    expect(workbenchCss).not.toMatch(
      /\.paw-workbench-migrated\s*\{[^}]*grid-template-rows:\s*36px/s,
    );
  });

  it('keeps toolbars off hidden scrollports that clip button labels', () => {
    // Window scrollbars are suppressed shell-wide (paw-os.css), so any
    // overflow-x toolbar reads as half-cut buttons. Toolbars wrap instead.
    const baseCss = workbenchCss.slice(0, workbenchCss.indexOf('@container paw-native-stage'));
    expect(baseCss).toMatch(/\.paw-wb-planning-tools\s*\{[^}]*flex-wrap:\s*wrap;/s);
    expect(baseCss).toMatch(
      /\.paw-wb-planning-tools__date,\s*\.paw-workbench-migrated \.paw-wb-planning-tools__actions\s*\{[^}]*flex-wrap:\s*wrap;/s,
    );
    expect(baseCss).not.toMatch(/\.paw-wb-planning-tools__actions\s*\{[^}]*overflow-x:\s*auto;/s);
    expect(baseCss).toMatch(/\.paw-wb-metrics\s*\{[^}]*flex-wrap:\s*wrap;/s);
    expect(baseCss).not.toMatch(/\.paw-wb-metrics\s*\{[^}]*overflow-x:\s*auto;/s);
    expect(baseCss).not.toMatch(/\.paw-wb-chrome__commands\s*\{[^}]*overflow-x:\s*auto;/s);
  });
});
