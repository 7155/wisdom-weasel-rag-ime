import { describe, expect, it } from 'vitest';
import agentAppSource from '../apps/PawAgentApp.tsx?raw';
import contextTraceSource from '../apps/PawContextTrace.tsx?raw';
import appCss from '../apps/paw-apps.css?raw';
import agentNextCss from './paw-os-agent-next.css?raw';
import pawOsCss from './paw-os.css?raw';

const appIds = [
  'project-workbench',
  'agent',
  'memory',
  'knowledge',
  'input-studio',
  'app-center',
  'system-monitor',
  'system-settings',
  'files',
  'browser',
  'terminal',
] as const;

function appPaletteBlock(appId: string): string {
  const match = pawOsCss.match(new RegExp(`\\[data-app=['\"]${appId}['\"]\\]\\s*\\{(?<body>[\\s\\S]*?)\\n\\}`));
  expect(match?.groups?.body, `${appId} palette`).toBeTruthy();
  return match?.groups?.body ?? '';
}

function token(block: string, name: string): string {
  const match = block.match(new RegExp(`--${name}:\\s*([^;]+);`));
  expect(match?.[1], name).toBeTruthy();
  return match?.[1]?.trim() ?? '';
}

describe('UR-104 PAWOS App color identities', () => {
  it('gives all eleven Apps distinct primary, supporting, and surface relationships', () => {
    const palettes = appIds.map((appId) => {
      const block = appPaletteBlock(appId);
      return {
        accent: token(block, 'paw-app-accent'),
        support: token(block, 'paw-app-support'),
        family: token(block, 'paw-app-material-family'),
        canvas: token(block, 'paw-app-canvas'),
        nav: token(block, 'paw-app-nav'),
        surface: token(block, 'paw-app-surface'),
        selection: token(block, 'paw-app-selection'),
      };
    });

    expect(new Set(palettes.map(({ accent }) => accent)).size).toBe(appIds.length);
    expect(new Set(palettes.map(({ support }) => support)).size).toBe(appIds.length);
    expect(new Set(palettes.map(({ family }) => family)).size).toBeGreaterThanOrEqual(5);
    for (const materialToken of ['canvas', 'nav', 'surface', 'selection'] as const) {
      expect(new Set(palettes.map((palette) => palette[materialToken])).size).toBe(appIds.length);
    }
  });

  it('keeps semantic status colors system-owned while App colors own selection and surfaces', () => {
    for (const appId of appIds) {
      const block = appPaletteBlock(appId);
      expect(block).not.toMatch(/--paw-(?:success|warning|danger)\s*:/);
    }

    expect(pawOsCss).toContain('.paw-window-shell[data-app]');
    expect(pawOsCss).toContain('--paw-app-canvas:');
    expect(pawOsCss).toContain('--paw-app-selection:');
    expect(pawOsCss).toContain('.paw-window-shell[data-app] .paw-native-app');
    expect(pawOsCss).toContain(".paw-window-shell[data-app='files'] .paw-files-app");
    expect(pawOsCss).not.toContain(".paw-window-shell[data-app='browser'] .paw-direct-browser");
    expect(pawOsCss).toContain(".paw-window-shell[data-app='terminal'] .paw-terminal-app");
  });

  it('keeps the deferred theme variants from owning current shell geometry', () => {
    expect(pawOsCss).not.toContain(".paw-desktop-root[data-paw-theme='glacier']");
    expect(pawOsCss).not.toContain(".paw-desktop-root[data-paw-theme='ink-paper']");
    expect(pawOsCss).not.toContain(".paw-desktop-root[data-paw-theme='blueprint']");
  });

  it('uses the current Agent Home owner instead of the retired flow-map prototype', () => {
    expect(agentAppSource).not.toContain('kandinsky-field-v1');
    expect(agentAppSource).toContain('<PawAgentHome');
    expect(agentAppSource).not.toContain('paw-agent-flow-map');
    expect(appCss).not.toContain('Composition VIII');
    expect(appCss).not.toContain('.paw-agent-flow-map');
    expect(agentNextCss).toContain('.an-home');
    expect(agentNextCss).toContain('.an-composer');
  });

  it('draws Agent 轨迹 assembly stages from the workspace palette, not a private one', () => {
    /* The tokenbar and its legend are the only place seven hues appear at
       once. When they came from literals in the component, the view carried a
       second violet, red, cobalt and teal alongside the status dots that use
       the real tokens. */
    for (let stage = 1; stage <= 7; stage += 1) {
      const declaration = agentNextCss.match(new RegExp(`--an-stage-${stage}:\\s*([^;]+);`));
      expect(declaration?.[1], `--an-stage-${stage}`).toMatch(/^var\(--an-[a-z0-9-]+\)$/);
      expect(contextTraceSource).toContain(`var(--an-stage-${stage})`);
    }

    const traceColorLiterals = contextTraceSource.match(/#[0-9a-fA-F]{3,8}\b/g) ?? [];
    expect(traceColorLiterals).toEqual([]);

    /* The retired palette also survived in the stylesheet, so the same three
       hues sat next to their token twins. */
    for (const retired of ['rgba(47, 77, 164', 'rgba(209, 52, 44', 'rgba(106, 61, 154']) {
      expect(agentNextCss).not.toContain(retired);
    }
  });
});
