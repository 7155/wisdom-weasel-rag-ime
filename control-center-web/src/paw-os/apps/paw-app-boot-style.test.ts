import { describe, expect, it } from 'vitest';
import bootCss from './paw-app-boot.css?raw';
import appsCss from './paw-apps.css?raw';
import iconCss from '../shell/paw-app-icon.css?raw';
import pawAppsSource from './PawApps.tsx?raw';

/**
 * The App boot state is the window between pressing an App and that App's code
 * arriving. Its whole failure mode is an ordering one: a rule that ships inside
 * the lazy chunk being awaited can never style the state that waits for it.
 * These tests hold the ownership, not the pixels.
 */
describe('PAWOS App boot state', () => {
  it('is styled by a stylesheet the eager module loads, never by the lazy chunk', () => {
    expect(pawAppsSource).toContain("import './paw-app-boot.css'");
    // paw-apps.css belongs to PawAppsRuntime, the chunk the boot state awaits.
    expect(pawAppsSource).not.toMatch(/^import\s+['"][^'"]*paw-apps\.css['"]/mu);
    expect(appsCss).not.toMatch(/^\s*\.paw-app-boot[\s,{.]/mu);
    expect(appsCss).not.toMatch(/[,}]\s*\.paw-app-boot[\s,{.]/u);
  });

  it('keeps one owner for the state instead of forks racing across files', () => {
    // Three definitions once described this one surface; the two that could
    // not load in time left a doubled-class patch behind to undo them.
    expect(iconCss).not.toContain('.paw-app-boot.paw-app-boot');
    expect(iconCss).not.toMatch(/^\s*\.paw-app-boot[\s,{.]/mu);
  });

  it('centres the boot mark in the window instead of leaving a bare block box', () => {
    const rule = bootCss.match(/\.paw-app-boot \{(?<body>[^}]*)\}/su)?.groups?.body ?? '';
    expect(rule).toContain('display: flex');
    expect(rule).toContain('align-items: center');
    expect(rule).toContain('justify-content: center');
    // A block box would silently drop both, so the surface must claim the
    // window's height rather than collapse to its content.
    expect(rule).toContain('min-height: 100%');
  });

  it('stacks the caption above the App name so they cannot read as one run', () => {
    const label = bootCss.match(/\.paw-app-boot > span \{(?<body>[^}]*)\}/su)?.groups?.body ?? '';
    expect(label).toContain('display: grid');
    // Only the App name carries the wordmark tracking.
    expect(bootCss).toMatch(/\.paw-app-boot > span small \{[^}]*letter-spacing: normal/su);
    expect(bootCss).toMatch(/\.paw-app-boot > span strong \{[^}]*letter-spacing: \.28em/su);
  });
});
