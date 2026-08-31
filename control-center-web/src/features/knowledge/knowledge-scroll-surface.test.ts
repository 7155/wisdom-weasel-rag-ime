import { describe, expect, it } from 'vitest';
import knowledgeCss from './knowledge.css?raw';

// Scroll-ownership contract for the PAWOS Knowledge window. A long Markdown
// document (e.g. 261 lines in a short window) must always reach a scroll
// container: the height constraint flows window → library → workspace column →
// active tab panel, and the focusable tab panel owns the scrolling. Three CSS
// regressions each silently broke that chain; every rule below pins one.
describe('knowledge window scroll ownership', () => {
  it('makes the App root a full-height grid whose only row is a minmax(0, 1fr) region', () => {
    // The App root used to be `display: block`, which left the library's
    // `height: 100%` depending on the root keeping an explicit height. As a
    // grid with one minmax(0, 1fr) row the constraint is structural: the
    // library cannot grow past the window and cannot collapse below it.
    const root = /:is\(main, section\)\.knowledge-feature\[data-paw-os-app='knowledge'\]\s*\{([^}]*)\}/su.exec(knowledgeCss);
    expect(root).not.toBeNull();
    expect(root![1]).toMatch(/display:\s*grid;/u);
    expect(root![1]).toMatch(/height:\s*100%;/u);
    expect(root![1]).toMatch(/grid-template-rows:\s*minmax\(0, 1fr\);/u);
    expect(root![1]).toMatch(/container:\s*knowledge-library \/ inline-size;/u);
  });

  it('stretches the window layout rows so the workspace column stays height-constrained', () => {
    // The flowing-sheet route sets `align-items: start` on .knowledge-library.
    // Inside the fixed window that detaches the detail column from its
    // minmax(0, 1fr) row and the library clips it without a scrollbar.
    expect(knowledgeCss).toMatch(
      /\.knowledge-library\[data-native-layout='app'\]\s*\{[^}]*align-items:\s*stretch;[^}]*\}/su,
    );
  });

  it('keeps hidden library tab panels display: none after the block reset', () => {
    // Radix keeps inactive tab panels in the DOM as empty [hidden] divs. A
    // plain `display: block` reset overrides the UA [hidden] rule, so the
    // empty materials panel occupies the flexible grid row and the active
    // panel lands in an unconstrained implicit row.
    const reset = /\.knowledge-library__tabs > \[role='tabpanel'\]\s*\{[^}]*display:\s*block;[^}]*\}/su.exec(knowledgeCss);
    const guard = /\.knowledge-library__tabs > \[role='tabpanel'\]\[hidden\]\s*\{[^}]*display:\s*none;[^}]*\}/su.exec(knowledgeCss);
    expect(reset).not.toBeNull();
    expect(guard).not.toBeNull();
    expect(guard!.index).toBeGreaterThan(reset!.index);
  });

  it('gives the document tabs the remaining viewer height in every state', () => {
    // A fixed three-row grid template only worked while the optional
    // loading/error rows were present; without them the tabs landed in an
    // `auto` row and grew past the window.
    expect(knowledgeCss).toMatch(
      /\.knowledge-viewer\s*\{[^}]*display:\s*flex;[^}]*flex-direction:\s*column;[^}]*\}/su,
    );
    expect(knowledgeCss).toMatch(
      /\.knowledge-viewer > \.knowledge-document-tabs\s*\{[^}]*flex:\s*1 1 auto;[^}]*min-height:\s*0;[^}]*\}/su,
    );
  });

  it('lets reader surfaces grow with content instead of locking viewport height', () => {
    // The Markdown/page/chunk/artifact readers must not pin `height: 100%`:
    // the focusable tab panel above them owns the scroll, so wheel, trackpad,
    // and keyboard all reach the end of the document. The reading desk (目录 +
    // sheet) joined the same contract when it started wrapping the sheet.
    for (const selector of [
      'knowledge-reading-desk',
      'knowledge-markdown-preview',
      'knowledge-page-preview',
      'knowledge-chunk-grid',
      'knowledge-artifacts',
    ]) {
      const blocks = [...knowledgeCss.matchAll(new RegExp(`\\.${selector}\\s*\\{([^}]*)\\}`, 'gsu'))];
      expect(blocks.length).toBeGreaterThan(0);
      for (const [, body] of blocks) {
        expect(body).not.toMatch(/(?<!min-|max-)height:\s*100%/u);
      }
      expect(blocks.some(([, body]) => /min-height:\s*100%/u.test(body))).toBe(true);
    }
  });
});

// Window-bound layout contract. Inside PAWOS the Knowledge App is sized by its
// window, so every layout decision must read a container — the window for the
// rail/selector choice, the workspace column for what happens inside a tab.
// A viewport `@media` rule reaching a window selector is the regression this
// suite exists to catch: it refolds windows whose own size never changed.
describe('knowledge app window layout', () => {
  const containerBlocks = (name: string): string[] => [
    ...knowledgeCss.matchAll(new RegExp(`@container ${name} \\(([^)]*)\\)\\s*\\{((?:[^{}]|\\{[^{}]*\\})*)\\}`, 'gsu')),
  ].map(([, condition, body]) => `${condition}${body}`);

  const mediaBlocks = [...knowledgeCss.matchAll(/@media \((?:max|min)-width[^)]*\)\s*\{((?:[^{}]|\{[^{}]*\})*)\}/gsu)];

  it('lays the window out as rail + workspace and keeps both selector states in one DOM', () => {
    const library = /\.knowledge-library\[data-native-layout='app'\]\s*\{([^}]*)\}/su.exec(knowledgeCss);
    expect(library).not.toBeNull();
    expect(library![1]).toMatch(/grid-template-columns:\s*var\(--knowledge-rail-width\) minmax\(0, 1fr\);/u);
    expect(library![1]).toMatch(/grid-template-areas:\s*\n?\s*'band band'\s*\n?\s*'rail workspace';/u);

    // The rail is the wide-window selector, so the band names the library
    // instead of repeating a select next to it.
    expect(knowledgeCss).toMatch(/\.knowledge-base-switcher > \.ui-field\s*\{[^}]*display:\s*none;[^}]*\}/su);
  });

  it('swaps the rail for the labelled selector on a window container query', () => {
    const swap = containerBlocks('knowledge-library').find((block) => block.startsWith('max-width: 880px'));
    expect(swap).toBeDefined();
    expect(swap!).toMatch(/\.knowledge-base-rail\[data-variant='app'\]\s*\{[^}]*display:\s*none;/su);
    expect(swap!).toMatch(/\.knowledge-base-switcher > \.ui-field\s*\{[^}]*display:\s*grid;/su);
    expect(swap!).toMatch(/grid-template-areas:\s*\n?\s*'band'\s*\n?\s*'workspace';/u);
    // The narrow state must be a labelled field, never an icon-only strip.
    expect(swap!).not.toMatch(/\.knowledge-base-switcher > \.ui-field > label\s*\{[^}]*display:\s*none;/su);
  });

  it('measures everything inside a tab panel against the workspace column', () => {
    const workspace = containerBlocks('knowledge-workspace');
    expect(workspace.length).toBeGreaterThan(0);
    expect(knowledgeCss).toMatch(
      /\.knowledge-library__detail\s*\{[^}]*container:\s*knowledge-workspace \/ inline-size;[^}]*\}/su,
    );
    // The two-column material/search surfaces fold on the column they live in,
    // not on the window that also carries the rail.
    expect(workspace.some((block) => /\.knowledge-material-workspace,[\s\S]*?grid-template-columns:\s*minmax\(0, 1fr\);/u.test(block))).toBe(true);
  });

  it('allocates a real compact list row after the narrow header is removed', () => {
    // Hiding the 34px column header without replacing the explicit three-row
    // template leaves the virtualized list in a 0px grid track. Its own
    // min-height then paints over the document summary that follows it.
    const compact = containerBlocks('knowledge-workspace').find((block) => block.startsWith('max-width: 460px'));
    expect(compact).toBeDefined();
    expect(compact!).toMatch(
      /\.knowledge-material-list\s*\{[^}]*min-height:\s*224px;[^}]*grid-template-rows:\s*auto minmax\(224px, 1fr\);/su,
    );
    expect(compact!).toMatch(/\.knowledge-material-list__body\s*\{[^}]*min-height:\s*224px;/su);
  });

  it('lets a wrapped compact tablist contribute both rows to layout', () => {
    // The migrated window normally reserves one 46px tab row. At three tabs
    // per row, six tabs are 68px tall; keeping 46px makes the active panel
    // cover the second row even though its labels remain visible.
    const compact = containerBlocks('knowledge-workspace').find((block) => block.startsWith('max-width: 560px'));
    expect(compact).toBeDefined();
    expect(compact!).toMatch(
      /\.knowledge-library__tabs\s*\{[^}]*grid-template-rows:\s*auto minmax\(0, 1fr\);/su,
    );
  });

  it('keeps every viewport breakpoint out of the window frame', () => {
    for (const [, body] of mediaBlocks) {
      const windowScoped = [...body.matchAll(/\[data-paw-os-app(?:='knowledge')?\]/gu)];
      for (const [match] of windowScoped) {
        const index = body.indexOf(match);
        expect(body.slice(Math.max(0, index - 5), index)).toBe(':not(');
      }
    }
  });

  it('sizes the window graph pane from the window instead of a viewport slice', () => {
    const pane = /:is\(main, section\)\.knowledge-feature--migrated-v1\[data-paw-os-app='knowledge'\] \.knowledge-graph\s*\{([^}]*)\}/su.exec(knowledgeCss);
    expect(pane).not.toBeNull();
    expect(pane![1]).toMatch(/height:\s*100%;/u);
    expect(pane![1]).toMatch(/flex-direction:\s*column;/u);
    expect(knowledgeCss).toMatch(
      /\[data-paw-os-app='knowledge'\] \.knowledge-graph__workspace\s*\{[^}]*flex:\s*1 1 auto;[^}]*\}/su,
    );
    expect(knowledgeCss).toMatch(
      /\[data-paw-os-app='knowledge'\] \.knowledge-graph__canvas,\s*:is\(main, section\)[^{]*\.knowledge-graph__list\s*\{[^}]*height:\s*auto;[^}]*\}/su,
    );
  });
});
