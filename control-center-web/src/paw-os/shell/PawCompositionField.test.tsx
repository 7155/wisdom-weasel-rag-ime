import { describe, expect, it } from 'vitest';
import compositionSource from './PawCompositionField.tsx?raw';
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
    // The two always-on animated layers own compositor promotion, and both
    // reduced-motion signals release it again since nothing moves.
    expect(shellCss).toMatch(/\.paw-field__mist-drift\s*\{[^}]*will-change:\s*transform/s);
    expect(shellCss).toMatch(/\.paw-field__warmth\s*\{[^}]*will-change:\s*opacity/s);
    expect(desktopCss.match(/will-change:\s*auto\s*!important/g)?.length).toBeGreaterThanOrEqual(2);
    // Mode dims spend opacity, never a held full-viewport filter raster of
    // the wallpaper: no filter under overview or collaboration focus.
    expect(desktopCss).not.toMatch(/\.paw-desktop\[data-overview\] \.paw-wayfinder\s*\{[^}]*filter:/s);
    expect(desktopCss).not.toMatch(/\.paw-desktop\[data-collaboration-focus\] \.paw-composition-field\s*\{[^}]*filter:/s);
    expect(desktopCss).not.toMatch(/\.paw-desktop\[data-collaboration-focus\] \.paw-wayfinder,\s*\.paw-desktop\[data-collaboration-focus\] \.paw-dock\s*\{[^}]*filter:/s);
  });
});
