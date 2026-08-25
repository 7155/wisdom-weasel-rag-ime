import { describe, expect, it } from 'vitest';
import compositionSource from './PawCompositionField.tsx?raw';
import desktopShellSource from './PawDesktop.tsx?raw';
import desktopCss from '../styles/paw-os.css?raw';
import shellCss from '../styles/paw-os-shell-migrated-v1.css?raw';

describe('PAWOS Wayfinder fog terrain', () => {
  it('stands alone as deterministic SVG built from photographic technique', () => {
    expect(compositionSource).not.toMatch(/kandinsky|<image/i);
    expect(compositionSource).toContain('preserveAspectRatio="xMidYMid slice"');
    expect(compositionSource).toContain('viewBox="0 0 1440 900"');
    // Six ridge lines under a diffuse light: the depth stack that replaces
    // any drawn-shape composition.
    for (const layer of [
      'paw-field__sky',
      'paw-field__bloom',
      'paw-field__warmth',
      'paw-field__cirrus',
      'paw-field__daylight',
      'paw-field__ridge--veil',
      'paw-field__ridge--far',
      'paw-field__ridge--midfar',
      'paw-field__ridge--mid',
      'paw-field__ridge--close',
      'paw-field__ridge--near',
      'paw-field__airlight--far',
      'paw-field__airlight--near',
      'paw-field__mist--far',
      'paw-field__mist--mid',
      'paw-field__mist--near',
      'paw-field__grain',
    ]) {
      expect(compositionSource).toContain(layer);
    }
    // Depth of field on the far ranges and deterministic, stitched film grain.
    expect(compositionSource).toContain('feGaussianBlur');
    expect(compositionSource).toContain('feTurbulence');
    expect(compositionSource).toContain('seed="7"');
    expect(compositionSource).toMatch(/stitchTiles="stitch"/);
    // Every ridge dissolves into fog through its own atmospheric gradient.
    for (const ramp of ['ridge-veil', 'ridge-far', 'ridge-midfar', 'ridge-mid', 'ridge-close', 'ridge-near']) {
      expect(compositionSource).toContain(`url(#paw-field-${ramp})`);
    }
  });

  it('carries no drawn-sun, orbit, packet or dashed line work', () => {
    expect(compositionSource).not.toMatch(/stroke-dasharray|strokeDasharray/);
    expect(compositionSource).not.toMatch(/paw-field__(orbit|beacon|packet|meridian|waypoint|mark|cloud|crest|contour|daycore)/);
    // The legacy flat-gold sun palette stays retired.
    expect(compositionSource).not.toMatch(/#e0a53f|#eebd62|#f0c469/i);
    expect(shellCss).not.toMatch(/paw-field__(orbit|beacon|packet|meridian|crest)/);
    expect(shellCss).not.toContain('offset-path');
  });

  it('keeps the wallpaper full-bleed behind chrome and quiet under collaboration focus', () => {
    expect(desktopCss).toMatch(/\.paw-composition-field\s*\{[^}]*inset:\s*0/s);
    expect(desktopCss).toMatch(/\.paw-composition-field\s*\{[^}]*width:\s*100%/s);
    expect(desktopCss).toMatch(/\.paw-desktop\[data-collaboration-focus\] \.paw-composition-field\s*\{[^}]*opacity:\s*\.7/s);
    expect(shellCss).toMatch(/\.paw-wayfinder \.paw-composition-field\s*\{[^}]*opacity:\s*1/s);
  });

  it('answers the existing pulse contract and playing audio without new callers', () => {
    expect(compositionSource).toContain('PAW_COMPOSITION_PULSE_EVENT');
    expect(compositionSource).toContain('--paw-composition-energy');
    expect(compositionSource).toContain('field.dataset.drive = source');
    expect(compositionSource).toContain("document.addEventListener('timeupdate', handleMedia, true)");
    expect(compositionSource).toContain("querySelector<SVGCircleElement>('.paw-field__signal')");
    expect(compositionSource).toContain("querySelectorAll<SVGGElement>('.paw-field__mist')");
    // The horizon keeps residual light after activity via the energy custom
    // property that the bloom reads in CSS.
    expect(shellCss).toMatch(/\.paw-field__bloom\s*\{[^}]*var\(--paw-composition-energy/s);
    // Pulse animations are id-scoped so cancelling them can never kill the
    // CSS-driven ambient mist drift on the same elements.
    expect(compositionSource).toContain("const pulseId = 'paw-field-pulse'");
    expect(compositionSource).toContain('if (animation.id === pulseId) animation.cancel()');
  });

  it('keeps every filter on static geometry so the moving weather is cheap to draw', () => {
    // Ridge depth-of-field and film grain rasterize once and never animate;
    // everything that moves (mist, cirrus, daylight, warmth, signal) is plain
    // gradient geometry with no filter attribute, so a weather step repaints
    // cached gradients instead of re-running Gaussian blurs.
    expect(compositionSource).not.toContain('paw-field-mist-soften');
    expect(compositionSource).toContain('url(#paw-field-mist-ball)');
    expect(compositionSource).toContain('url(#paw-field-daylight)');
    for (const line of compositionSource.split('\n')) {
      if (!/paw-field__(mist|cirrus|daylight|warmth|signal|bloom)/.test(line)) continue;
      expect(line, `animated layer stays filter-free: ${line.trim()}`).not.toContain('filter=');
    }
    // The wallpaper is one sealed paint world behind the desktop.
    expect(desktopCss).toMatch(/\.paw-field-media\s*\{[^}]*contain:\s*strict/s);
  });

  it('moves on a stepped minutes-long clock and pauses whenever it cannot be watched', () => {
    // steps() turns sixty invisible sub-pixel updates per second into one
    // visible update every few seconds — the picture moves the same, the
    // idle desktop stops re-rasterizing and re-blurring chrome glass.
    expect(shellCss).toMatch(/paw-field-mist-drift 2[0-9]{2}s steps\([45][0-9]\)/);
    expect(shellCss).toMatch(/paw-field-cirrus-drift 3[0-9]{2}s steps\(/);
    expect(shellCss).toMatch(/paw-field-daylight 1[0-9]{2}s steps\(/);
    expect(shellCss).toMatch(/paw-field-breathe 26s steps\(/);
    // A live window drag/resize freezes the weather in place instead of
    // resetting it (collaboration focus has its own identical pause rule).
    expect(desktopCss).toMatch(/\.paw-desktop-root\[data-window-interaction\] \.paw-composition-field \*\s*\{[^}]*animation-play-state:\s*paused/s);
    // Pulses stay silent while hidden, focused-away or mid-gesture: no energy
    // write, no bloom transition, no WAAPI.
    expect(compositionSource).toContain('if (pulsesSuspended()) return;');
    expect(compositionSource).toContain('if (document.hidden) return true;');
    expect(compositionSource).toContain("field.closest('[data-collaboration-focus]')");
    expect(compositionSource).toContain('root?.dataset.windowInteraction');
  });

  it('steps every ambient weather clock no faster than once every few seconds', () => {
    // Each visible step invalidates a full-bleed SVG raster (with the grain
    // pass on top) and re-runs the chrome backdrop blurs above the field.
    // Rare steps keep the watched idle desktop around one repaint per second
    // in total across all six clocks; a sub-second clock here is a P0 jank
    // regression (the warmth breathe once stepped every single second).
    const clocks = [...shellCss.matchAll(/paw-field-(?:mist-drift|cirrus-drift|daylight|breathe) (\d+)s steps\((\d+)\)/g)];
    expect(clocks.length).toBeGreaterThanOrEqual(6);
    for (const [clock, duration, steps] of clocks) {
      expect(Number(duration) / Number(steps), `at most one repaint every 4s: ${clock}`).toBeGreaterThanOrEqual(4);
    }
  });

  it('freezes entirely whenever the shell marks the wallpaper unwatched', () => {
    // A focused App window, the Launchpad veil, the overview plane and a
    // hidden document all mean nobody is watching the scenery. The desktop
    // shell stamps one attribute from those store slices plus the platform
    // visibility signal, and CSS freezes every weather clock in place.
    expect(desktopCss).toMatch(/\.paw-desktop\[data-ambient-paused\] \.paw-composition-field \*\s*\{[^}]*animation-play-state:\s*paused/s);
    expect(desktopShellSource).toContain('data-ambient-paused={ambientPaused || undefined}');
    expect(desktopShellSource).toMatch(/ambientPaused = documentHidden \|\| Boolean\(activeWindowId\) \|\| launchpadOpen \|\| overviewOpen/);
    expect(desktopShellSource).toContain("document.addEventListener('visibilitychange', update)");
    // Pulses respect the same signal: playing audio or runtime events can
    // never restart wallpaper choreography behind a focused window.
    expect(compositionSource).toContain("field.closest('[data-ambient-paused]')");
  });

  it('rests still under both reduced-motion signals and keeps the pulse bloom invisible at rest', () => {
    expect(compositionSource).toContain("window.matchMedia('(prefers-reduced-motion: reduce)')");
    expect(compositionSource).toContain("getAttribute('data-reduce-motion') === 'true'");
    expect(desktopCss).toMatch(/prefers-reduced-motion:[^)]+\)[^{]*\{[\s\S]*\.paw-composition-field \*/);
    expect(desktopCss).toMatch(/:root\[data-reduce-motion='true'\] \.paw-composition-field \*/);
    expect(desktopCss).toMatch(/\.paw-field__signal\s*\{[^}]*opacity:\s*0/s);
    // The warmth core holds a static rest opacity, so a killed breathe
    // animation can never snap it to full strength.
    expect(shellCss).toMatch(/\.paw-field__warmth\s*\{[^}]*opacity:\s*\.64/s);
    // Ambient drift is minutes-long weather, not UI motion.
    expect(shellCss).toMatch(/paw-field-mist-drift 2[0-9]{2}s/);
  });

  it('stays fully quiet while collaboration focus owns the desktop', () => {
    // The pulse driver skips choreography behind the focus plane, and CSS
    // pauses the ambient drift/breathe so nothing animates under focused work.
    expect(compositionSource).toContain("field.closest('[data-collaboration-focus]')");
    expect(desktopCss).toMatch(/\.paw-desktop\[data-collaboration-focus\] \.paw-composition-field \*\s*\{[^}]*animation-play-state:\s*paused/s);
  });

  it('keeps ambient motion off the filter path and inside a bounded raster budget', () => {
    // The forever-animated drift groups may never carry an SVG filter: a
    // filtered drift re-runs its Gaussian blur every frame. The fog banks are
    // pre-blurred radial gradients instead.
    expect(compositionSource).not.toContain('paw-field-mist-soften');
    expect(compositionSource).not.toMatch(/paw-field__mist-drift"\s+filter=/);
    expect(compositionSource).toContain('url(#paw-field-mist-ball)');
    // Both grain speckle passes resolve from one feTurbulence evaluation on
    // one full-bleed surface (dark keys off red noise, light off green).
    expect(compositionSource.match(/<feTurbulence/g)).toHaveLength(1);
    expect(compositionSource.match(/<feColorMatrix/g)).toHaveLength(2);
    // Depth-of-field blur exists only where it reads: the three far ranges.
    expect(compositionSource).toContain('url(#paw-field-dof-veil)');
    expect(compositionSource).toContain('url(#paw-field-dof-far)');
    expect(compositionSource).toContain('url(#paw-field-dof-midfar)');
    expect(compositionSource).not.toMatch(/paw-field-dof-mid\)/);
    expect(compositionSource).not.toMatch(/paw-field-dof-close\)/);
    // No wallpaper layer holds a standing compositor promotion: will-change
    // on the drift/warmth subtrees pinned several near-full-viewport GPU
    // layers for scenery that steps once every few seconds at most, and the
    // unwatched-freeze contract already removes all idle work. Reduced motion
    // still releases any stray promotion defensively.
    expect(shellCss.match(/paw-field[^{]*\{[^}]*will-change/g)).toBeNull();
    expect(desktopCss.match(/will-change:\s*auto\s*!important/g)?.length).toBeGreaterThanOrEqual(2);
    // Mode dims spend opacity, never a held full-viewport filter raster of
    // the wallpaper: no filter under overview or collaboration focus.
    expect(desktopCss).not.toMatch(/\.paw-desktop\[data-overview\] \.paw-wayfinder\s*\{[^}]*filter:/s);
    expect(desktopCss).not.toMatch(/\.paw-desktop\[data-collaboration-focus\] \.paw-composition-field\s*\{[^}]*filter:/s);
    expect(desktopCss).not.toMatch(/\.paw-desktop\[data-collaboration-focus\] \.paw-wayfinder,\s*\.paw-desktop\[data-collaboration-focus\] \.paw-dock\s*\{[^}]*filter:/s);
  });
});
