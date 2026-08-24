import { describe, expect, it } from 'vitest';
import shellCss from './paw-os-shell-migrated-v1.css?raw';
import pawOsCss from './paw-os.css?raw';
import motionCss from './paw-os-motion.css?raw';

/* The redesigned OS shell speaks one chrome language: menu bar, Dock and the
 * Launchpad veil share a single --paw-chrome-* material recipe, blur exists on
 * exactly those three surfaces, and every piece of shell text sits on an
 * opaque or contrast-proven ground. These tests read the stylesheets as a
 * contract so a fourth glass layer, a translucent tooltip, or an unreadable
 * dark-chrome title cannot land silently. */

function hexToRgb(value: string): [number, number, number] {
  const hex = value.replace('#', '');
  const full = hex.length === 3 ? hex.split('').map((c) => c + c).join('') : hex;
  expect(full, `${value} must be a 6-digit hex colour`).toMatch(/^[0-9a-f]{6}$/i);
  return [
    Number.parseInt(full.slice(0, 2), 16),
    Number.parseInt(full.slice(2, 4), 16),
    Number.parseInt(full.slice(4, 6), 16),
  ];
}

function luminance([r, g, b]: [number, number, number]): number {
  const [lr, lg, lb] = [r, g, b].map((channel) => {
    const srgb = channel / 255;
    return srgb <= 0.04045 ? srgb / 12.92 : ((srgb + 0.055) / 1.055) ** 2.4;
  }) as [number, number, number];
  return 0.2126 * lr + 0.7152 * lg + 0.0722 * lb;
}

function contrast(ink: [number, number, number], ground: [number, number, number]): number {
  const [light, dark] = [luminance(ink), luminance(ground)].sort((x, y) => y - x);
  return (light + 0.05) / (dark + 0.05);
}

/** Composite `rgb(r g b / a)` over an opaque hex backdrop. */
function composite(veil: string, backdrop: string): [number, number, number] {
  const match = veil.match(/rgb\((\d+) (\d+) (\d+) \/ \.?(\d+)\)/);
  expect(match, `${veil} must be rgb(r g b / a)`).toBeTruthy();
  const [, r, g, b, alphaDigits] = match!;
  const alpha = Number.parseFloat(`0.${alphaDigits}`);
  const under = hexToRgb(backdrop);
  return [Number(r), Number(g), Number(b)].map(
    (channel, index) => Math.round(channel * alpha + under[index]! * (1 - alpha)),
  ) as [number, number, number];
}

function shellToken(name: string): string {
  const match = shellCss.match(new RegExp(`--${name}:\\s*([^;]+);`));
  expect(match?.[1], `--${name}`).toBeTruthy();
  return match?.[1]?.trim() ?? '';
}

function rule(css: string, selector: string): string {
  const start = css.indexOf(`${selector} {`);
  expect(start, `${selector} rule`).toBeGreaterThan(-1);
  return css.slice(start, css.indexOf('}', start));
}

describe('PAWOS shell visual language', () => {
  it('derives menu bar, Dock and Launchpad from one chrome material recipe', () => {
    for (const token of ['paw-chrome-veil', 'paw-chrome-hairline', 'paw-chrome-highlight', 'paw-chrome-blur']) {
      expect(shellCss, `--${token} is defined once as the shared recipe`).toContain(`--${token}:`);
    }
    for (const surface of ['.paw-desktop-root .paw-menu-bar', '.paw-desktop-root .paw-dock']) {
      const body = rule(shellCss, surface);
      expect(body, `${surface} uses the shared veil`).toContain('background: var(--paw-chrome-veil)');
      expect(body, `${surface} uses the shared hairline`).toContain('var(--paw-chrome-hairline)');
      expect(body, `${surface} uses the shared blur`).toContain('backdrop-filter: var(--paw-chrome-blur)');
    }
  });

  it('keeps the blur budget at exactly three true-chrome surfaces', () => {
    // Standard-property declarations that actually blur; -webkit- mirrors them.
    const active = [...shellCss.matchAll(/(?<!-webkit-)backdrop-filter:\s*([^;]+);/g)]
      .map((match) => match[1]?.trim() ?? '')
      .filter((value) => value !== 'none');
    expect(active).toHaveLength(3);
    // Menu bar and Dock resolve the shared recipe; the Launchpad veil is the
    // one modal surface allowed its own heavier setting.
    expect(active.filter((value) => value === 'var(--paw-chrome-blur)')).toHaveLength(2);
    expect(rule(shellCss, '.paw-desktop-root .paw-launchpad')).toMatch(/backdrop-filter:\s*blur/);
    // No other shell owner may introduce glass.
    expect(pawOsCss).not.toContain('backdrop-filter: blur');
    expect(motionCss).not.toContain('backdrop-filter: blur');
  });

  it('renders the Launchpad as one immersive layer instead of glass-on-glass', () => {
    const panel = rule(shellCss, '.paw-desktop-root .paw-launchpad > section');
    expect(panel).toContain('background: transparent');
    expect(panel).toContain('box-shadow: none');
    expect(panel).not.toContain('backdrop-filter');
    // Text grounds on the veil keep AA contrast once composited over the
    // brightest desktop backdrop.
    const veil = composite(shellToken('paw-chrome-veil'), '#eef1f6');
    const launchpadVeil = composite('rgb(240 243 248 / .86)', '#eef1f6');
    expect(shellCss).toContain('background: rgb(240 243 248 / .86);');
    for (const ink of ['#525b6a', '#5d6675']) {
      expect(contrast(hexToRgb(ink), launchpadVeil)).toBeGreaterThanOrEqual(4.5);
      expect(contrast(hexToRgb(ink), veil)).toBeGreaterThanOrEqual(4.5);
    }
    expect(contrast(hexToRgb('#171a21'), launchpadVeil)).toBeGreaterThanOrEqual(7);
  });

  it('gives the Dock a shaped running language and an opaque hover label', () => {
    // Long pill = visible window, short pill = minimized; shape, not colour alone.
    const open = rule(pawOsCss, '.paw-dock button[data-open]::after');
    expect(open).toContain('height: 3px');
    expect(open).toContain('border-radius: 999px');
    expect(rule(pawOsCss, '.paw-dock button[data-minimized]::after')).toContain('width: 6px');
    // The label centres with the separate translate property so reduced
    // motion's transform reset can never knock it off its icon.
    const tip = rule(pawOsCss, '.paw-dock-tip');
    expect(tip).toContain('translate: -50% 4px');
    expect(tip).not.toContain('transform:');
    expect(tip).toContain('pointer-events: none');
    // Hover reveal is gated to hover-capable pointers; the scrolling narrow
    // Dock hides the label entirely instead of clipping it.
    expect(pawOsCss).toMatch(/@media \(hover: hover\) and \(pointer: fine\)\s*\{\s*\.paw-dock button:hover \.paw-dock-tip/);
    expect(pawOsCss).toMatch(/@media \(max-width: 820px\)[\s\S]*?\.paw-dock-tip\s*\{\s*display:\s*none;/);
    // Ink on an opaque white ground — never text over glass.
    const tipVisual = rule(shellCss, '.paw-desktop-root .paw-dock-tip');
    expect(tipVisual).toContain('background: #fff');
    expect(contrast(hexToRgb('#171a21'), hexToRgb('#ffffff'))).toBeGreaterThanOrEqual(7);
  });

  it('re-pairs the window title ink on the dark Terminal chrome', () => {
    expect(shellCss).toMatch(/\.paw-window-shell\[data-app='terminal'\] \.paw-window-title\s*\{\s*color:\s*#8fd08a;/);
    expect(shellCss).toMatch(/\.paw-window-shell\[data-app='terminal'\]:not\(\[data-active\]\) \.paw-window-title\s*\{\s*color:\s*#93a0ae;/);
    // Both inks clear AA against the Terminal titlebar base (#161b22 family).
    expect(contrast(hexToRgb('#8fd08a'), hexToRgb('#161b22'))).toBeGreaterThanOrEqual(4.5);
    expect(contrast(hexToRgb('#93a0ae'), hexToRgb('#161b22'))).toBeGreaterThanOrEqual(4.5);
  });

  it('keeps window depth on two named tiers and signs the active window with its accent', () => {
    expect(shellCss).toContain('--paw-shadow-rest:');
    expect(rule(shellCss, ".paw-desktop-root .paw-window-shell:not([data-active]):not([data-overview]):not([data-collaboration-role]) .paw-window"))
      .toContain('box-shadow: var(--paw-shadow-rest)');
    expect(shellCss).toMatch(/\.paw-window-shell\[data-active\]\[data-app\] \.paw-window-titlebar\s*\{[^}]*border-bottom-color:\s*color-mix\(in srgb, var\(--paw-app-accent/s);
  });

  it('separates overview windows with the shared quiet plane instead of a second dimmer', () => {
    expect(motionCss).toMatch(/\.paw-desktop\[data-overview\]:not\(\[data-collaboration-focus\]\) \.paw-desktop-viewport::before\s*\{[^}]*opacity:\s*1;/s);
    // The plane itself only ever animates opacity — never inset or filters.
    expect(rule(motionCss, '.paw-desktop-viewport::before')).toMatch(/transition:\s*opacity/);
  });
});
