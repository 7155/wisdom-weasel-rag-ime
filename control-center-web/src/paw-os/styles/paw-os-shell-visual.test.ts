import { describe, expect, it } from 'vitest';
import shellCss from './paw-os-shell-migrated-v1.css?raw';
import pawOsCss from './paw-os.css?raw';
import motionCss from './paw-os-motion.css?raw';
import controlsCss from './paw-os-controls.css?raw';
import webmodelCss from './paw-os-webmodel-v1.css?raw';
import appIconCss from '../shell/paw-app-icon.css?raw';

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

/** The body of one top-level `@container paw-window (max-width: …)` block. */
function windowContainerStep(css: string, maxWidth: string): string {
  const header = `@container paw-window (max-width: ${maxWidth})`;
  const start = css.indexOf(header);
  expect(start, `${header} step`).toBeGreaterThan(-1);
  const end = css.indexOf('\n}', start);
  expect(end, `${header} closing brace`).toBeGreaterThan(start);
  return css.slice(start, end);
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

  it('binds every identity placement to the one size ladder and one paper token', () => {
    // Five steps, defined once; a placement may only resolve a ladder step,
    // so identical surfaces can never drift apart by a stray pixel value.
    for (const step of ['xs', 'sm', 'md', 'lg', 'xl']) {
      expect(appIconCss, `ladder step --paw-icon-step-${step} is defined once`)
        .toContain(`--paw-icon-step-${step}:`);
    }
    expect(appIconCss, 'no placement hardcodes an icon size outside the ladder')
      .not.toMatch(/\.paw-app-icon\s*\{[^}]*width:\s*\d/);
    expect(rule(appIconCss, '.paw-dock .paw-app-icon')).toContain('var(--paw-icon-step-lg)');
    expect(rule(appIconCss, '.paw-launchpad .paw-app-icon')).toContain('var(--paw-icon-step-xl)');
    // One paper white for every internal detail cut; no per-App tint overrides
    // and no per-surface recolour of any identity.
    expect(appIconCss.match(/--paw-icon-paper:/g)).toHaveLength(1);
    expect(appIconCss).not.toMatch(/data-paw-app-icon='[a-z-]+'\]/);
  });

  it('speaks one selected and running language across Dock, desktop and launcher', () => {
    // The identity wash tokens are declared exactly once, on the owning
    // buttons, so every surface resolves the App's own colour the same way.
    for (const token of ['--paw-identity-wash:', '--paw-identity-wash-strong:', '--paw-identity-ring:', '--paw-identity-dot:']) {
      expect(appIconCss.split(token), `${token} declared once in the identity system`).toHaveLength(2);
    }
    const dockCurrent = rule(shellCss, ".paw-desktop-root .paw-dock button[aria-current='page']");
    expect(dockCurrent).toContain('var(--paw-identity-wash-strong)');
    expect(dockCurrent).toContain('var(--paw-identity-ring)');
    // Never again an opaque white plate behind the current App's bare icon.
    expect(dockCurrent).not.toContain('#fff');
    const shortcutSelected = rule(pawOsCss, ".paw-desktop-shortcuts button[aria-selected='true']");
    expect(shortcutSelected).toContain('var(--paw-identity-wash-strong)');
    expect(shortcutSelected).toContain('var(--paw-identity-ring)');
    expect(rule(pawOsCss, '.paw-desktop-shortcuts button:hover')).toContain('var(--paw-identity-wash)');
    // The running pill is the one notification dot, in the App's own colour.
    expect(rule(pawOsCss, '.paw-dock button[data-open]::after')).toContain('var(--paw-identity-dot');
    expect(rule(shellCss, '.paw-desktop-root .paw-dock button[data-open]::after')).toContain('var(--paw-identity-dot');
  });

  it('keeps the Wayfinder list dense on one blur-free plate with a single style owner', () => {
    // One owner: the migrated theme may not re-style the desktop list, so the
    // identity wash/ring language can never be overridden back into a second
    // hardcoded plate recipe like the pre-density desktop.
    expect(shellCss).not.toContain('.paw-desktop-shortcuts');
    const plate = rule(pawOsCss, '.paw-desktop-shortcuts');
    expect(plate).not.toContain('backdrop-filter');
    expect(plate).toContain('background: rgb(249 251 254 / .66);');
    // List ink stays AA-readable composited over the brightest fog band.
    const ground = composite('rgb(249 251 254 / .66)', '#f5f8fc');
    expect(contrast(hexToRgb('#0f172a'), ground)).toBeGreaterThanOrEqual(7);
    expect(contrast(hexToRgb('#5d6675'), ground)).toBeGreaterThanOrEqual(4.5);
    // Rows carry the Dock's running shape language: long pill = visible
    // window, short soft pill = minimized only — never colour alone.
    const running = rule(pawOsCss, '.paw-desktop-shortcuts button[data-open] > i');
    expect(running).toContain('var(--paw-identity-dot)');
    expect(running).toContain('height: 3px');
    expect(rule(pawOsCss, '.paw-desktop-shortcuts button[data-minimized] > i')).toContain('width: 6px');
    // Dense rows resolve the md ladder step, not the launcher's 48px tile.
    expect(rule(appIconCss, '.paw-desktop-shortcuts .paw-app-icon')).toContain('var(--paw-icon-step-md)');
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

  it('never transitions the all keyword anywhere in shell-owned styles', () => {
    // `transition: all` re-runs unrelated computed-value changes (visibility,
    // layout, filters) through the transition engine, which reads as flicker
    // during drag and stream reflow. Every shell owner names its properties.
    for (const [name, css] of Object.entries({
      'paw-os.css': pawOsCss,
      'paw-os-motion.css': motionCss,
      'paw-os-shell-migrated-v1.css': shellCss,
      'paw-os-controls.css': controlsCss,
      'paw-app-icon.css': appIconCss,
    })) {
      expect(css, `${name} must not transition the all keyword`)
        .not.toMatch(/transition(-property)?\s*:[^;]*\ball\b/);
    }
  });

  it('moves placement changes as one gesture and promotes only the dragged frame', () => {
    // Snap/maximize/restore animate transform and size on the same clock so
    // the frame cannot tear; live drag/resize opts out entirely.
    const shell = rule(pawOsCss, '.paw-window-shell');
    expect(shell).toMatch(/transition:[^;]*transform 240ms/s);
    expect(shell).toMatch(/transition:[^;]*width 240ms/s);
    expect(shell).toMatch(/transition:[^;]*height 240ms/s);
    expect(rule(pawOsCss, '.paw-window-shell[data-interaction]')).toContain('transition: none');
    // will-change exists only for the duration of a drag gesture — the
    // resting shell must never hold a compositor layer.
    expect(rule(pawOsCss, ".paw-window-shell[data-interaction='dragging']")).toContain('will-change: transform');
    expect(shell).not.toContain('will-change');
    // Same doctrine for the Room flow overlay: a resting flow SVG holds no
    // full-viewport layer; promotion is scoped to a live drag stream or a
    // live packet pulse, the only times its geometry mutates per frame.
    expect(rule(pawOsCss, '.paw-room-window-flow')).not.toContain('will-change');
    expect(pawOsCss).toMatch(/\.paw-desktop-root\[data-window-interaction\] \.paw-room-window-flow,\s*\.paw-room-window-flow:has\(g\[data-live\]\)\s*\{[^}]*will-change: transform/s);
  });

  it('signs the focused window with a static aurora hairline in its own App key', () => {
    const aurora = rule(shellCss, ".paw-desktop-root .paw-window-shell[data-active][data-app] .paw-window-titlebar::after");
    expect(aurora).toContain('linear-gradient(');
    expect(aurora).toContain('var(--paw-app-accent');
    expect(aurora).toContain('var(--paw-app-support');
    expect(aurora).toContain('height: 1px');
    expect(aurora).toContain('pointer-events: none');
    // A signature, not a show: the hairline never animates or blurs.
    expect(aurora).not.toContain('animation');
    expect(aurora).not.toContain('backdrop-filter');
  });

  it('lets Launchpad group headers lead their tiles in the same cascade', () => {
    const header = rule(shellCss, '.paw-desktop-root .paw-launchpad-group');
    expect(header).toMatch(/animation:\s*paw-shell-group-arrive/);
    expect(header).toContain('animation-delay: calc(var(--paw-tile-i, 0) * 22ms)');
    // The tile beat unit is identical, so headers and tiles share one clock.
    expect(rule(shellCss, '.paw-desktop-root .paw-launchpad section > div > button'))
      .toContain('animation-delay: calc(var(--paw-tile-i, 0) * 22ms)');
    // Reduced motion silences the header cascade with everything else.
    expect(shellCss).toMatch(/@media \(prefers-reduced-motion: reduce\)[\s\S]*?\.paw-desktop-root \.paw-launchpad-group,/);
  });

  it('keeps traffic lights the fixed leftmost column of every window titlebar', () => {
    // The titlebar grid's first track is a fixed pixel column that always
    // resolves to the traffic-light slot, at both the default and the narrow
    // breakpoint, so no App can push the lights out of their left position by
    // widening the title or chrome-slot tracks.
    // Both widths resolve one shared token, so a window that docks App
    // chrome widens the column through --paw-titlebar-lead instead of any
    // owner re-declaring a competing pixel value.
    expect(pawOsCss).toMatch(/\.paw-window-titlebar\s*\{[^}]*grid-template-columns:\s*var\(--paw-titlebar-lead, 76px\) minmax\(0, 1fr\) minmax\(0, auto\);/s);
    expect(pawOsCss).toMatch(/@media \(max-width: 820px\)[\s\S]*?\.paw-window-titlebar\s*\{\s*grid-template-columns:\s*var\(--paw-titlebar-lead, 70px\) minmax\(0, 1fr\) minmax\(0, auto\);/);
    // No shell owner may re-key that grid per App: the recipe is one shared
    // geometry, not a per-window rediscovery.
    for (const [name, css] of Object.entries({
      'paw-os.css': pawOsCss,
      'paw-os-shell-migrated-v1.css': shellCss,
      'paw-os-motion.css': motionCss,
      'paw-os-controls.css': controlsCss,
      'paw-os-webmodel-v1.css': webmodelCss,
    })) {
      expect(css, `${name} must not re-key the titlebar grid per data-app`)
        .not.toMatch(/\[data-app[^\]]*\][^{]*\.paw-window-titlebar[^{]*\{[^}]*grid-template-columns/s);
    }
  });

  it('gives every window one titlebar height and one corner radius regardless of its App', () => {
    // --paw-titlebar-h and --paw-radius are declared exactly once each in the
    // structure owner and (where restated) agree with the visual owner, so
    // the chrome scale can never fork between the two files that touch it.
    expect(pawOsCss.match(/--paw-titlebar-h:/g)).toHaveLength(1);
    expect(pawOsCss).toContain('--paw-titlebar-h: 40px;');
    const structureRadius = pawOsCss.match(/--paw-radius:\s*([^;]+);/)?.[1]?.trim();
    const visualRadius = shellCss.match(/--paw-radius:\s*([^;]+);/)?.[1]?.trim();
    expect(structureRadius, '--paw-radius in paw-os.css').toBe('12px');
    expect(visualRadius, '--paw-radius in paw-os-shell-migrated-v1.css').toBe(structureRadius);
    // No shell owner may give one named App's titlebar its own height or give
    // one named App's window its own corner radius: identity speaks through
    // ink, icon and the documented Terminal ink/aurora hairline only. The
    // generic `[data-app]` presence selector (shared by every App, e.g. the
    // active-window aurora hairline `::after`) is deliberately excluded here
    // — only a selector naming one specific App value is a fork.
    for (const [name, css] of Object.entries({
      'paw-os.css': pawOsCss,
      'paw-os-shell-migrated-v1.css': shellCss,
      'paw-os-motion.css': motionCss,
      'paw-os-webmodel-v1.css': webmodelCss,
    })) {
      expect(css, `${name} must not give one named App its own titlebar height`)
        .not.toMatch(/\[data-app='[a-z-]+'\][^{]*\.paw-window-titlebar(?!::)[^{]*\{[^}]*\bheight:/s);
      expect(css, `${name} must not give one named App its own window corner radius`)
        .not.toMatch(/\[data-app='[a-z-]+'\][^{]*\.paw-window\b[^-][^{]*\{[^}]*border-radius/s);
    }
  });

  it('makes the resized window frame the one App query container', () => {
    // The container sits on the frame the pointer drags and resizes, so every
    // App's `@container paw-window` rule answers the real window width — not
    // the width of some inner surface that an App or a focus mode could
    // restyle underneath it.
    expect(rule(pawOsCss, '.paw-window-shell')).toContain('container: paw-window / inline-size');
    // Exactly one owner. A second `paw-window` container anywhere would make
    // two Apps in the same window resolve different widths for one query.
    expect(pawOsCss.match(/container(-name)?:\s*[^;]*\bpaw-window\b/g)).toHaveLength(1);
    for (const [name, css] of Object.entries({
      'paw-os-shell-migrated-v1.css': shellCss,
      'paw-os-motion.css': motionCss,
      'paw-os-controls.css': controlsCss,
      'paw-os-webmodel-v1.css': webmodelCss,
    })) {
      expect(css, `${name} must not declare a second paw-window container`)
        .not.toMatch(/container(-name)?:\s*[^;]*\bpaw-window\b/);
    }
  });

  it('gives the window body an App skeleton that clips at the window boundary', () => {
    // A window is an App container, not a page: both tracks floor at 0, so a
    // wide table or a long path reflows or scrolls inside the App instead of
    // widening the window's own box.
    const body = rule(pawOsCss, '.paw-window-body');
    for (const declaration of [
      'min-width: 0',
      'min-height: 0',
      'overflow: hidden',
      'display: grid',
      'grid-template-columns: minmax(0, 1fr)',
      'grid-template-rows: minmax(0, 1fr)',
    ]) expect(body, `.paw-window-body ${declaration}`).toContain(declaration);
    const surface = rule(pawOsCss, '.paw-window-route-surface');
    expect(surface).toContain('overflow: hidden');
    expect(surface).toContain('grid-template-columns: minmax(0, 1fr)');
    expect(surface).toContain('grid-template-rows: minmax(0, 1fr)');
    // The clip chain continues up to the document, so resizing a window can
    // never turn into page-level horizontal scroll.
    expect(rule(pawOsCss, '.paw-desktop-root')).toContain('overflow: hidden');
    expect(rule(pawOsCss, '.paw-desktop-viewport')).toContain('overflow: hidden');
  });

  it('yields window caption text before any window control down to 375px', () => {
    // The acceptance widths are read from the window container, not the
    // document: a 375px-wide window on a 1440px desktop has the 375px problem.
    expect(windowContainerStep(pawOsCss, '760px')).toMatch(/\.paw-window-titlebar\s*\{[^}]*padding-inline:\s*12px;/s);
    // Docked trailing chrome already takes the caption at 620; leading chrome
    // shares the traffic-light column, so it takes it one step later.
    expect(windowContainerStep(pawOsCss, '620px'))
      .toMatch(/\.paw-window-titlebar:has\(\.paw-window-chrome-slot:not\(:empty\)\) \.paw-window-title\s*\{[^}]*visibility:\s*hidden;/s);
    expect(windowContainerStep(pawOsCss, '560px'))
      .toMatch(/\.paw-window-titlebar:has\(\.paw-window-leading-slot:not\(:empty\)\) \.paw-window-title\s*\{[^}]*visibility:\s*hidden;/s);
    const narrowest = windowContainerStep(pawOsCss, '375px');
    // Labels hide before icons, and the docked leading control is bounded so
    // it can never grow its column across the title.
    expect(narrowest).toMatch(/\.paw-window-title > strong\s*\{\s*display:\s*none;/);
    expect(narrowest).toMatch(/\.paw-window-leading-slot\s*\{[^}]*max-width:\s*32px;/s);
    // No step ever removes or shrinks a window verb.
    expect(narrowest).not.toMatch(/\.paw-traffic-lights[^{]*\{[^}]*display:\s*none/s);
    expect(narrowest).not.toContain('.paw-traffic-lights > button');
    expect(narrowest).not.toContain('.paw-window-chrome-slot');
  });

  it('limits window titlebar background overrides to the one documented Terminal exception', () => {
    // Every App resolves the shared background recipe —
    // `background: var(--paw-app-nav, #fff)` on the one `[data-app]` rule —
    // with only the --paw-app-nav *value* changing per App palette. Terminal
    // is the sole named exception, repainting its own obsidian material to
    // match its whole-App dark surface; no other App may fork a second one.
    expect(shellCss).toMatch(/\.paw-window-shell\[data-app\] \.paw-window-titlebar\s*\{[^}]*background:\s*var\(--paw-app-nav,/s);
    const appSpecificTitlebarBackgrounds: string[] = [];
    for (const css of [pawOsCss, shellCss, motionCss, webmodelCss]) {
      appSpecificTitlebarBackgrounds.push(...[...css.matchAll(
        /\.paw-window-shell\[data-app='([a-z-]+)'\]\s*\.paw-window-titlebar(?=\s*[,{])[^{]*\{[^}]*background:/gs,
      )].map((match) => match[1]!));
    }
    expect(appSpecificTitlebarBackgrounds).toEqual(['terminal']);
  });
});
