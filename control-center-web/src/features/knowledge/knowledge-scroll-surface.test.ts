import { describe, expect, it } from 'vitest';
import knowledgeCss from './knowledge.css?raw';

// Scroll-ownership contract for the PAWOS Knowledge window. A long Markdown
// document (e.g. 261 lines in a short window) must always reach a scroll
// container: the height constraint flows window → library → detail → active
// tab panel, and the focusable tab panel owns the scrolling. Three CSS
// regressions each silently broke that chain; every rule below pins one.
describe('knowledge window scroll ownership', () => {
  it('stretches the window layout rows so the detail column stays height-constrained', () => {
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
