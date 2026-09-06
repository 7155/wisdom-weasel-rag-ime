import { describe, expect, it } from 'vitest';
import appSource from '@/app/App.tsx?raw';
import pawOsAppSource from '../PawOsApp.tsx?raw';
import darkCss from './paw-os-stellar-dark.css?raw';
import stellarCss from './paw-os-stellar.css?raw';

describe('PAWOS stellar dark theme integration', () => {
  it('defines a scoped cosmic palette for the sky, chrome, and live agent captions', () => {
    expect(darkCss).toContain(":root[data-theme='dark'] .paw-desktop-root[data-paw-visual='stellar']");
    expect(darkCss).toContain('--paw-stellar-bg: #050817;');
    expect(darkCss).toContain('--paw-stellar-accent: #82b7ff;');
    expect(darkCss).toContain('color-scheme: dark;');
    expect(darkCss).toContain('.paw-stellar-scene__stars i');
    expect(darkCss).toContain('.paw-stellar-agent__caption');
    expect(darkCss).toMatch(/\.paw-wayfinder-work\s*\{[^}]*background:\s*transparent;/s);
    expect(darkCss).not.toMatch(/filter\s*:\s*invert/i);
  });

  it('covers the real Agent, Room, Memory, and Browser reading surfaces', () => {
    for (const selector of [
      ".paw-window-shell[data-app='agent']",
      '.paw-room-workspace',
      '.paw-system-app',
      '.paw-system-app__nav',
      '.mgmt-page',
      '.mgmt-section',
      ".paw-window-shell[data-app='memory']",
      '.memory-topic-map__claim',
      ".paw-window-shell[data-app='browser']",
      '.paw-direct-browser',
    ]) {
      expect(darkCss, selector).toContain(selector);
    }
  });

  it('loads after the light stellar identity and leaves Evolution Report light', () => {
    expect(pawOsAppSource.indexOf("./styles/paw-os-stellar.css")).toBeGreaterThanOrEqual(0);
    expect(pawOsAppSource.indexOf("./styles/paw-os-stellar-dark.css")).toBeGreaterThan(
      pawOsAppSource.indexOf("./styles/paw-os-stellar.css"),
    );
    expect(appSource).not.toContain("forcedTheme={product === 'paw-os'");
    expect(appSource).toContain('<ThemeProvider forcedTheme="light">');
  });
});
