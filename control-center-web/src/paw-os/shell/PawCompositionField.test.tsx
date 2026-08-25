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
    // The live glow clears entirely behind focused work.
    expect(desktopCss).toMatch(/\.paw-desktop\[data-collaboration-focus\] \.paw-field-live\s*\{[^}]*opacity:\s*0/s);
    expect(shellCss).toMatch(/\.paw-wayfinder \.paw-composition-field\s*\{[^}]*opacity:\s*1/s);
  });

  it('rasterizes the picture exactly once: nothing ever animates inside the SVG', () => {
    // The freeze fix. The picture is a module constant that React reconciles
    // by reference; no SMIL, no WAAPI target, no CSS animation and no custom
    // property ever lands on an SVG node, so the full-bleed grain/blur stack
    // rasterizes one time and the raster pipeline stays empty at rest.
    expect(compositionSource).toContain('const pawFieldPicture = (');
    expect(compositionSource).not.toContain('<animate');
    expect(compositionSource).not.toMatch(/querySelector(All)?<SVG/);
    expect(compositionSource).not.toMatch(/SVGSVGElement|SVGGElement|SVGCircleElement/);
    // The retired stepped weather clocks stay retired: they invalidated the
    // SVG's paint every second or two forever, which starved the pointer.
    expect(shellCss).not.toMatch(/@keyframes paw-field-(mist-drift|cirrus-drift|breathe|daylight)/);
    expect(shellCss).not.toMatch(/\.paw-field__[\w-]*[^{]*\{[^}]*animation:/s);
    expect(desktopCss).not.toMatch(/\.paw-field__[\w-]*[^{]*\{[^}]*animation:/s);
    // Static rest densities replace the old animated swells.
    expect(shellCss).toMatch(/\.paw-field__bloom\s*\{\s*opacity:\s*\.66;\s*\}/);
    expect(shellCss).toMatch(/\.paw-field__warmth\s*\{\s*opacity:\s*\.64;\s*\}/);
    expect(shellCss).toMatch(/\.paw-field__daylight\s*\{\s*opacity:\s*\.3;\s*\}/);
    // A still picture holds no compositor promotions open.
    expect(shellCss).not.toMatch(/paw-field__[\w-]*[^{]*\{[^}]*will-change/s);
  });

  it('drives Runtime pulses and playing audio through the HTML overlay, never the picture', () => {
    expect(compositionSource).toContain('PAW_COMPOSITION_PULSE_EVENT');
    expect(compositionSource).toContain('--paw-composition-energy');
    expect(compositionSource).toContain('live.dataset.drive = source');
    expect(compositionSource).toContain("document.addEventListener('timeupdate', handleMedia, true)");
    expect(compositionSource).toContain("querySelector<HTMLElement>('.paw-field-live__glow')");
    // Pulse animations are id-scoped so a fresh pulse cancels exactly the
    // previous pulse and nothing else on the overlay.
    expect(compositionSource).toContain("const pulseId = 'paw-field-pulse'");
    expect(compositionSource).toContain('if (animation.id === pulseId) animation.cancel()');
    // Residual horizon light: the glow's rest opacity reads the energy custom
    // property, and the property lives on the two-node overlay subtree.
    expect(desktopCss).toMatch(/\.paw-field-live\s*\{[^}]*--paw-composition-energy:\s*0/s);
    expect(desktopCss).toMatch(/\.paw-field-live__glow\s*\{[^}]*var\(--paw-composition-energy/s);
    // The centring offset is the separate translate property, so the pulse's
    // transform keyframes cannot knock the glow off the light gap.
    expect(desktopCss).toMatch(/\.paw-field-live__glow\s*\{[^}]*translate:\s*-50% -50%/s);
    expect(shellCss).toMatch(/\.paw-field-live__glow\s*\{[^}]*radial-gradient/s);
    // The overlay ignores the pointer and never carries a filter.
    expect(desktopCss).toMatch(/\.paw-field-live\s*\{[^}]*pointer-events:\s*none/s);
    expect(desktopCss).not.toMatch(/\.paw-field-live[\w_-]*\s*\{[^}]*filter:/s);
  });

  it('stays silent whenever it cannot be watched and under both reduced-motion signals', () => {
    // Hidden document, unwatched wallpaper, collaboration focus and a live
    // window drag/resize all swallow pulses entirely — no energy write, no
    // glow transition, no WAAPI.
    expect(compositionSource).toContain('if (pulsesSuspended()) return;');
    expect(compositionSource).toContain('if (document.hidden) return true;');
    expect(compositionSource).toContain("live.closest('[data-ambient-paused]')");
    expect(compositionSource).toContain("live.closest('[data-collaboration-focus]')");
    expect(compositionSource).toContain('root?.dataset.windowInteraction');
    // The desktop shell stamps the unwatched signal from its store slices
    // plus the platform visibility signal: a focused App window, the
    // Launchpad veil, the overview plane or a hidden document all mean
    // nobody is watching the scenery, so pulses never fire behind work.
    expect(desktopShellSource).toContain('data-ambient-paused={ambientPaused || undefined}');
    expect(desktopShellSource).toMatch(/ambientPaused = documentHidden \|\| Boolean\(activeWindowId\) \|\| launchpadOpen \|\| overviewOpen/);
    expect(desktopShellSource).toContain("document.addEventListener('visibilitychange', update)");
    // Both reduced-motion signals drop the choreography and keep only the
    // residual light.
    expect(compositionSource).toContain("window.matchMedia('(prefers-reduced-motion: reduce)')");
    expect(compositionSource).toContain("getAttribute('data-reduce-motion') === 'true'");
    expect(desktopCss).toMatch(/prefers-reduced-motion:[^)]+\)[^{]*\{[\s\S]*\.paw-field-live \*/);
    expect(desktopCss).toMatch(/:root\[data-reduce-motion='true'\] \.paw-field-live \*/);
  });

  it('keeps the one-time filters and containment that seal the picture', () => {
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
    // The fog banks stay pre-blurred gradients, not filtered geometry.
    expect(compositionSource).toContain('url(#paw-field-mist-ball)');
    for (const line of compositionSource.split('\n')) {
      if (!/paw-field__(mist|cirrus|daylight|warmth|bloom)/.test(line)) continue;
      expect(line, `soft layer stays filter-free: ${line.trim()}`).not.toContain('filter=');
    }
    // The wallpaper is one sealed paint world behind the desktop.
    expect(desktopCss).toMatch(/\.paw-field-media\s*\{[^}]*contain:\s*strict/s);
    // Mode dims spend opacity, never a held full-viewport filter raster of
    // the wallpaper: no filter under overview or collaboration focus.
    expect(desktopCss).not.toMatch(/\.paw-desktop\[data-overview\] \.paw-wayfinder\s*\{[^}]*filter:/s);
    expect(desktopCss).not.toMatch(/\.paw-desktop\[data-collaboration-focus\] \.paw-composition-field\s*\{[^}]*filter:/s);
  });
});
