import { describe, expect, it } from 'vitest';
import controlsCss from './paw-os-controls.css?raw';
import sysAppsCss from './paw-os-sys-apps-migrated-v1.css?raw';

/* Input Studio, App Center, System Monitor, and System Settings are one
 * PAWOS instrument, not four branded products. These tests guard the shared
 * cobalt accent and the paw-os-controls radius/height scale so a future
 * per-App palette (the retired #5e5ce6 purple / #0e9f8a teal / #42688a and
 * #5b6f96 blue-greys) cannot silently return. */

function token(css: string, name: string): string {
  const match = css.match(new RegExp(`--${name}:\\s*([^;]+);`));
  expect(match?.[1], `--${name}`).toBeTruthy();
  return match?.[1]?.trim() ?? '';
}

describe('PAWOS system Apps shared accent', () => {
  it('gives every system App the exact same --paw-system-accent (no per-App override block)', () => {
    const declarations = [...sysAppsCss.matchAll(/--paw-system-accent:\s*([^;]+);/g)].map((match) => match[1]?.trim());
    expect(declarations).toEqual(['#1e57e7']);
    // No [data-system-app='…'] selector may reintroduce its own accent.
    expect(sysAppsCss).not.toMatch(/\[data-system-app='[^']+'\]\s*\{[^}]*--paw-system-accent/s);
  });

  it('matches the shared cobalt from paw-os-controls.css instead of an invented hue', () => {
    expect(token(sysAppsCss, 'paw-system-accent')).toBe('#1e57e7');
    expect(token(controlsCss, 'paw-button-primary-bg')).toBe('#1e57e7');
    expect(token(controlsCss, 'paw-menu-selected-bg')).toBe('#1e57e7');
  });

  it('retires every previously competing per-App accent', () => {
    for (const retiredHue of ['#5e5ce6', '#0e9f8a', '#42688a', '#5b6f96']) {
      // The only allowed mention is the explanatory "no longer used" comment.
      const occurrences = sysAppsCss.split(retiredHue).length - 1;
      expect(occurrences, `${retiredHue} should only appear in a retirement comment`).toBeLessThanOrEqual(1);
    }
  });

  it('bridges the shared cobalt into the generic --color-accent-* tokens feature content reads', () => {
    const block = sysAppsCss.match(/\.paw-desktop-root \.paw-system-app \{([\s\S]*?)\n\}/)?.[1] ?? '';
    expect(block).toMatch(/--color-accent:\s*var\(--paw-system-accent\);/);
    expect(block).toMatch(/--color-accent-soft:\s*color-mix\(in srgb, var\(--paw-system-accent\)/);
    expect(block).toMatch(/--color-accent-border:\s*color-mix\(in srgb, var\(--paw-system-accent\)/);
    expect(block).toMatch(/--color-accent-text:\s*#fff;/);
  });

  it('derives its radius scale from paw-os-controls.css instead of ad hoc 9/11/13/14px values', () => {
    const block = sysAppsCss.match(/\.paw-desktop-root \.paw-system-app \{([\s\S]*?)\n\}/)?.[1] ?? '';
    expect(block).toContain('--paw-system-radius-sm: var(--paw-control-radius, 8px);');
    expect(block).toContain('--paw-system-radius-md: var(--paw-menu-radius, 10px);');
    expect(block).toContain('--paw-system-radius-lg: var(--paw-panel-radius, 12px);');
    // Structural surfaces reference the token scale, not a fourth hand-picked number.
    for (const radiusToken of ['--paw-system-radius-sm', '--paw-system-radius-md', '--paw-system-radius-lg']) {
      expect(sysAppsCss).toContain(`border-radius: var(${radiusToken})`);
    }
  });

  it('gives the rail and compact ui-* controls a shared paw-os-controls height instead of an invented 30px', () => {
    expect(sysAppsCss).toMatch(/\.paw-system-app__nav nav button\s*\{[^}]*min-height:\s*var\(--paw-control-h, 32px\);/s);
    expect(sysAppsCss).toMatch(/:is\(\.ui-button, \.ui-input, \.ui-select__trigger\)\s*\{[^}]*min-height:\s*var\(--paw-control-h-sm, 28px\);/s);
  });
});
