import { describe, expect, it } from 'vitest';
import compositionSource from './PawCompositionField.tsx?raw';
import desktopCss from '../styles/paw-os.css?raw';
import shellCss from '../styles/paw-os-shell-migrated-v1.css?raw';

describe('PAWOS Wayfinder daybreak field', () => {
  it('stands alone as deterministic SVG with the raster wallpaper retired', () => {
    expect(compositionSource).not.toMatch(/kandinsky|<image/i);
    expect(compositionSource).toContain('preserveAspectRatio="xMidYMid slice"');
    expect(compositionSource).toContain('viewBox="0 0 1440 900"');
    for (const layer of [
      'paw-field__sky',
      'paw-field__beacon-core',
      'paw-field__ridge--near',
      'paw-field__crest-lights',
      'paw-field__survey',
    ]) {
      expect(compositionSource).toContain(layer);
    }
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
    expect(compositionSource).toContain("querySelectorAll<SVGCircleElement>('.paw-field__packet')");
    // The survey packets travel exactly the meridian that is drawn in the sky.
    expect(compositionSource).toContain('d="M -80 486 C 300 356 720 256 1520 318"');
    expect(shellCss).toContain("offset-path: path('M -80 486 C 300 356 720 256 1520 318')");
  });

  it('rests still under both reduced-motion signals and keeps pulse layers invisible at rest', () => {
    expect(compositionSource).toContain("window.matchMedia('(prefers-reduced-motion: reduce)')");
    expect(compositionSource).toContain("getAttribute('data-reduce-motion') === 'true'");
    expect(desktopCss).toMatch(/prefers-reduced-motion:[^)]+\)[^{]*\{[\s\S]*\.paw-composition-field \*/);
    expect(desktopCss).toMatch(/:root\[data-reduce-motion='true'\] \.paw-composition-field \*/);
    expect(desktopCss).toMatch(/\.paw-field__signal\s*\{[^}]*opacity:\s*0/s);
    expect(desktopCss).toMatch(/\.paw-field__packet\s*\{[^}]*opacity:\s*0/s);
  });
});
