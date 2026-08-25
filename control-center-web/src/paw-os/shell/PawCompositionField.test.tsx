import { cleanup, fireEvent, render } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { PawCompositionField } from './PawCompositionField';
import { pulsePawComposition } from '../runtime/composition-pulse';
import compositionSource from './PawCompositionField.tsx?raw';
import desktopShellSource from './PawDesktop.tsx?raw';
import desktopCss from '../styles/paw-os.css?raw';
import shellCss from '../styles/paw-os-shell-migrated-v1.css?raw';

/** The declarations inside one named `@keyframes` block, flattened across
 *  every offset, as `[property, value]` pairs. */
function keyframeDeclarations(css: string, name: string): Array<[string, string]> {
  const block = new RegExp(`@keyframes ${name} \\{([\\s\\S]*?)\\n\\}`).exec(css);
  expect(block, `@keyframes ${name} is declared`).not.toBeNull();
  return [...block![1].matchAll(/([\w-]+)\s*:\s*([^;]+);/g)].map(
    (declaration) => [declaration[1], declaration[2].trim()],
  );
}

/** Mounts the wallpaper under the desktop ancestors whose data attributes the
 *  suspension gates read, and returns the nodes those gates hang off. */
function mountField() {
  const view = render(
    <div className="paw-desktop-root">
      <div className="paw-desktop">
        <div aria-hidden="true" className="paw-field-media">
          <PawCompositionField effects />
        </div>
      </div>
    </div>,
  );
  return {
    desktop: view.container.querySelector<HTMLElement>('.paw-desktop')!,
    live: view.container.querySelector<HTMLElement>('.paw-field-live')!,
    root: view.container.querySelector<HTMLElement>('.paw-desktop-root')!,
  };
}

function energyOf(live: HTMLElement): string {
  return live.style.getPropertyValue('--paw-composition-energy');
}

beforeEach(() => {
  // jsdom ships neither media queries nor Web Animations. Full motion is the
  // interesting case here: the pulse driver must reach its suspension gates
  // rather than bail out early on a reduced-motion signal.
  vi.stubGlobal('matchMedia', vi.fn((query: string) => ({ matches: false, media: query })));
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  delete (document as { hidden?: boolean }).hidden;
});

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
      'paw-field__pillar--sky',
      'paw-field__pillar--valley',
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
    // The sky and the ridge ramp cover a real value range: a glacial zenith
    // over near-black near terrain is what stops the picture reading as an
    // unpainted placeholder.
    expect(compositionSource).toContain('stopColor="#a7bdda"');
    expect(compositionSource).toContain('stopColor="#202c46"');
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
    // The live overlay — ambient veils and pulse glow alike — clears entirely
    // behind focused work.
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
    expect(shellCss).toMatch(/\.paw-field__bloom\s*\{\s*opacity:\s*\.7;\s*\}/);
    expect(shellCss).toMatch(/\.paw-field__warmth\s*\{\s*opacity:\s*\.6;\s*\}/);
    expect(shellCss).toMatch(/\.paw-field__daylight\s*\{\s*opacity:\s*\.34;\s*\}/);
    // A still picture holds no compositor promotions open.
    expect(shellCss).not.toMatch(/paw-field__[\w-]*[^{]*\{[^}]*will-change/s);
  });

  it('gives the desktop ambient weather on three compositor-only overlay layers', () => {
    // The wallpaper has to read as living atmosphere, and the only place that
    // is free is above the painting: pre-blurred gradients on HTML nodes,
    // moved by transform/opacity alone.
    expect(compositionSource).toContain('const pawFieldWeather = (');
    for (const layer of [
      'paw-field-live__veil--high',
      'paw-field-live__veil--low',
      'paw-field-live__sheen',
    ]) {
      expect(compositionSource).toContain(layer);
      expect(shellCss).toContain(`.paw-desktop-root .${layer}`);
    }
    // Ambient motion is pure CSS on a fixed node set: no script drives a
    // frame of it, and no React state can re-render the weather.
    expect(compositionSource).not.toMatch(/setInterval|setTimeout|requestAnimationFrame/);
    expect(compositionSource).not.toMatch(/useState|useMemo/);
    // Motion registers as weather, not as animation: every loop is slow,
    // eased and alternating, so no cycle ever snaps back to its start.
    const loops = [...shellCss.matchAll(/animation: (paw-field-(?:veil-high|veil-low|sheen)) (\d+)s ([^;]+);/g)];
    expect(loops.map((loop) => loop[1])).toEqual(['paw-field-veil-high', 'paw-field-veil-low', 'paw-field-sheen']);
    for (const [, name, seconds, rest] of loops) {
      expect(Number(seconds), `${name} is slow enough to read as weather`).toBeGreaterThanOrEqual(30);
      expect(rest).toBe('ease-in-out infinite alternate');
    }
    // Every animated property is one the compositor can carry on its own.
    for (const name of ['paw-field-veil-high', 'paw-field-veil-low', 'paw-field-sheen']) {
      for (const [property, value] of keyframeDeclarations(shellCss, name)) {
        expect(['transform', 'opacity'], `${name} animates ${property}`).toContain(property);
        if (property === 'transform') expect(value).toMatch(/^translate3d\([^)]*\)(?: scale\([\d.]+\))?$|^scale\([\d.]+\)$/);
      }
    }
    // Static placement uses the individual transform properties, so the
    // reduced-motion `transform: none` reset flattens the choreography
    // without dragging a layer off its mark.
    expect(desktopCss).toMatch(/\.paw-field-live__veil--high\s*\{[^}]*rotate:\s*-7deg/s);
    expect(desktopCss).toMatch(/\.paw-field-live__veil--low\s*\{[^}]*rotate:\s*6deg/s);
    expect(desktopCss).toMatch(/\.paw-field-live__sheen\s*\{[^}]*translate:\s*-50% -50%/s);
    // Cold PAWOS language: glacial cyan and steel blue, never a violet wash.
    expect(shellCss).not.toMatch(/\.paw-field-live__(veil|sheen)[^{]*\{[^}]*rgb\(1[0-9]{2} (?:5[0-9]|6[0-9]|7[0-9]) 2[0-9]{2}/s);
  });

  it('suspends ambient motion under every gate that owns the frame budget', () => {
    // Pausing rather than hiding: the composited layers stay where they
    // stopped, so nothing is spent behind work and resuming costs no raster.
    expect(desktopCss).toMatch(
      /\.paw-desktop\[data-ambient-paused\] \.paw-field-live > \*,\s*\.paw-desktop\[data-collaboration-focus\] \.paw-field-live > \*,\s*\.paw-desktop-root\[data-window-interaction\] \.paw-field-live > \*\s*\{\s*animation-play-state: paused;\s*\}/,
    );
    // Both reduced-motion signals stop the weather outright.
    expect(desktopCss).toMatch(/prefers-reduced-motion:[^)]+\)[^{]*\{[\s\S]*\.paw-field-live \*/);
    expect(desktopCss).toMatch(/:root\[data-reduce-motion='true'\] \.paw-field-live \*/);
    expect(shellCss).toMatch(/prefers-reduced-motion:[^)]+\)[\s\S]*\.paw-field-live__veil,\s*\.paw-desktop-root \.paw-field-live__sheen,/);
    // Ambient layers never spend a filter, at rest or in motion.
    expect(shellCss).not.toMatch(/\.paw-field-live__(veil|sheen)[\w-]*[^{]*\{[^}]*(?:backdrop-)?filter:/s);
    expect(desktopCss).not.toMatch(/\.paw-field-live__(veil|sheen)[\w-]*[^{]*\{[^}]*(?:backdrop-)?filter:/s);
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
    // property, and the property lives on the overlay subtree.
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

  it('answers a live Runtime pulse with residual horizon light', () => {
    const { live } = mountField();

    expect(live.querySelectorAll('.paw-field-live__veil')).toHaveLength(2);
    expect(live.querySelector('.paw-field-live__sheen')).not.toBeNull();
    expect(energyOf(live)).toBe('');

    pulsePawComposition('agent', .82);

    expect(live.dataset.drive).toBe('agent');
    expect(energyOf(live)).toBe('0.820');
  });

  it.each([
    { gate: 'a hidden document', apply: () => Object.defineProperty(document, 'hidden', { configurable: true, value: true }) },
    { gate: 'an unwatched desktop', apply: ({ desktop }: ReturnType<typeof mountField>) => desktop.setAttribute('data-ambient-paused', 'true') },
    { gate: 'collaboration focus', apply: ({ desktop }: ReturnType<typeof mountField>) => desktop.setAttribute('data-collaboration-focus', 'true') },
    { gate: 'a live window gesture', apply: ({ root }: ReturnType<typeof mountField>) => { root.dataset.windowInteraction = 'true'; } },
  ])('swallows pulses entirely under $gate', ({ apply }) => {
    const mounted = mountField();
    pulsePawComposition('agent', .82);
    expect(energyOf(mounted.live)).toBe('0.820');

    apply(mounted);
    pulsePawComposition('room', .2);

    // No energy write, no glow transition, no WAAPI: the earlier residual
    // light is simply left where it was.
    expect(mounted.live.dataset.drive).toBe('agent');
    expect(energyOf(mounted.live)).toBe('0.820');
  });

  it('swallows playing-audio pulses under the same gates', () => {
    const { live, root } = mountField();
    const audio = document.createElement('audio');
    document.body.append(audio);
    Object.defineProperty(audio, 'paused', { configurable: true, value: false });
    Object.defineProperty(audio, 'volume', { configurable: true, value: .5 });

    fireEvent(audio, new Event('play', { bubbles: true }));
    expect(energyOf(live)).toBe('0.500');

    root.dataset.windowInteraction = 'true';
    Object.defineProperty(audio, 'volume', { configurable: true, value: .9 });
    fireEvent(audio, new Event('play', { bubbles: true }));

    expect(energyOf(live)).toBe('0.500');
    audio.remove();
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
    // The fog banks and the light pillar stay pre-blurred gradients, not
    // filtered geometry.
    expect(compositionSource).toContain('url(#paw-field-mist-ball)');
    for (const line of compositionSource.split('\n')) {
      if (!/paw-field__(mist|cirrus|daylight|warmth|bloom|pillar)/.test(line)) continue;
      expect(line, `soft layer stays filter-free: ${line.trim()}`).not.toContain('filter=');
    }
    // The wallpaper is one sealed paint world behind the desktop.
    expect(desktopCss).toMatch(/\.paw-field-media\s*\{[^}]*contain:\s*strict/s);
    // Mode dims spend opacity, never a held full-viewport filter raster of
    // the wallpaper: no filter under overview or collaboration focus.
    expect(desktopCss).not.toMatch(/\.paw-desktop\[data-overview\] \.paw-wayfinder\s*\{[^}]*filter:/s);
    expect(desktopCss).not.toMatch(/\.paw-desktop\[data-collaboration-focus\] \.paw-composition-field\s*\{[^}]*filter:/s);
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
});
