import { useEffect, useRef } from 'react';
import { PAW_COMPOSITION_PULSE_EVENT, type PawCompositionPulseSource } from '../runtime/composition-pulse';

/**
 * Bright PAWOS desktop field. The legacy Composition 8 raster remains a
 * low-presence provenance layer; the visible field and motion are deterministic
 * SVG geometry derived from the accepted shell studies.
 */
export function PawCompositionField({ effects = false }: { effects?: boolean } = {}) {
  const fieldRef = useRef<SVGSVGElement>(null);
  useEffect(() => {
    if (!effects) return undefined;
    const field = fieldRef.current;
    if (!field) return undefined;
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
    const drive = (source: PawCompositionPulseSource, energyValue: number) => {
      const energy = Math.max(0, Math.min(1, Number.isFinite(energyValue) ? energyValue : .65));
      field.dataset.drive = source;
      field.style.setProperty('--paw-composition-energy', energy.toFixed(3));
      field.style.setProperty('--paw-composition-opacity', (.82 + energy * .12).toFixed(3));
      if (reducedMotion.matches || energy === 0) return;
      const layers = field.querySelectorAll<SVGGElement>('.paw-composition__event-layer');
      layers.forEach((layer, index) => {
        layer.getAnimations().forEach((animation) => animation.cancel());
        const direction = index === 0 ? -1 : 1;
        layer.animate([
          { transform: 'translate3d(0, 0, 0)', opacity: 1 },
          {
            transform: `translate3d(${(direction * energy * 1.8).toFixed(2)}px, ${(-energy * 1.4).toFixed(2)}px, 0)`,
            opacity: .84 + energy * .16,
          },
          { transform: 'translate3d(0, 0, 0)', opacity: 1 },
        ], {
          duration: 420 + energy * 180 + index * 70,
          easing: 'cubic-bezier(.16, 1, .3, 1)',
        });
      });
      const packets = field.querySelectorAll<SVGCircleElement>('.paw-comp8-packet');
      packets.forEach((packet, index) => {
        packet.getAnimations().forEach((animation) => {
          if (animation instanceof CSSAnimation) return;
          animation.cancel();
        });
        packet.animate([
          { offsetDistance: '0%', opacity: 0, filter: 'drop-shadow(0 0 2px currentColor)' },
          { offsetDistance: '10%', opacity: 1, filter: `drop-shadow(0 0 ${(5 + energy * 7).toFixed(1)}px currentColor)` },
          { offsetDistance: '88%', opacity: 1, filter: `drop-shadow(0 0 ${(6 + energy * 8 + index * 2).toFixed(1)}px currentColor)` },
          { offsetDistance: '100%', opacity: 0, filter: 'drop-shadow(0 0 2px currentColor)' },
        ], { delay: index * 80, duration: 620 + energy * 180, easing: 'cubic-bezier(.42, 0, .28, 1)' });
      });
    };
    const handlePulse = (event: Event) => {
      const detail = (event as CustomEvent<{ energy?: number; source?: PawCompositionPulseSource }>).detail;
      drive(detail?.source ?? 'system', detail?.energy ?? .65);
    };
    let lastMediaPulse = 0;
    const handleMedia = (event: Event) => {
      const media = event.target;
      if (!(media instanceof HTMLAudioElement)) return;
      const now = performance.now();
      if (event.type === 'timeupdate' && now - lastMediaPulse < 650) return;
      lastMediaPulse = now;
      drive('music', media.paused ? 0 : Math.max(.2, media.volume));
    };
    window.addEventListener(PAW_COMPOSITION_PULSE_EVENT, handlePulse);
    document.addEventListener('play', handleMedia, true);
    document.addEventListener('timeupdate', handleMedia, true);
    document.addEventListener('pause', handleMedia, true);
    return () => {
      window.removeEventListener(PAW_COMPOSITION_PULSE_EVENT, handlePulse);
      document.removeEventListener('play', handleMedia, true);
      document.removeEventListener('timeupdate', handleMedia, true);
      document.removeEventListener('pause', handleMedia, true);
    };
  }, [effects]);
  return (
    <svg
      aria-hidden="true"
      className="paw-composition-field"
      preserveAspectRatio="xMidYMid slice"
      ref={fieldRef}
      viewBox="0 0 1440 900"
    >
      <defs>
        <radialGradient id="paw-shell-air" cx="28%" cy="14%" r="95%">
          <stop offset="0" stopColor="#ffffff" stopOpacity=".96" />
          <stop offset="1" stopColor="#ffffff" stopOpacity="0" />
        </radialGradient>
        <linearGradient id="paw-comp8-scan-gradient" x1="0" x2="1" y1="0" y2="0">
          <stop offset="0" stopColor="#fff" stopOpacity="0" />
          <stop offset=".5" stopColor="#fff" stopOpacity=".72" />
          <stop offset="1" stopColor="#fff" stopOpacity="0" />
        </linearGradient>
      </defs>
      <rect className="paw-composition__mist" width="1440" height="900" fill="url(#paw-shell-air)" />
      <image
        className="paw-composition__background"
        height="900"
        href="/paw-media/kandinsky-composition-viii-motion-base-v2.png"
        preserveAspectRatio="xMidYMid slice"
        width="1440"
        x="0"
        y="0"
      />
      <g className="paw-composition__geometry" fill="none" strokeLinecap="round">
        <circle cx="1010" cy="320" r="196" className="paw-composition__ring paw-composition__ring--outer" />
        <circle cx="1010" cy="320" r="126" className="paw-composition__ring paw-composition__ring--inner" />
        <path d="M1010 124A196 196 0 0 1 1206 320" className="paw-composition__blue-arc" />
        <path d="M1120 186A156 156 0 0 1 1072 462" className="paw-composition__violet-orbit" />
        <path d="M72 780 660 116" className="paw-composition__diagonal" />
        <path d="M236 664A120 120 0 0 1 424 524" className="paw-composition__agent-orbit" />
        <circle cx="424" cy="530" r="7" className="paw-composition__node paw-composition__node--blue" />
        <circle cx="330" cy="600" r="30" className="paw-composition__agent-core" />
        <circle cx="356" cy="246" r="8" className="paw-composition__node paw-composition__node--mint" />
        <circle cx="1262" cy="486" r="5" className="paw-composition__node paw-composition__node--red" />
        <path d="m1160 566 64 94h-98Z" className="paw-composition__triangle" />
        <path d="M566 640v22m-11-11h22" className="paw-composition__cross" />
        <circle cx="716" cy="772" r="14" className="paw-composition__registration-ring" />
        <circle cx="140" cy="112" r="3.4" className="paw-composition__registration-dot paw-composition__registration-dot--one" />
        <circle cx="170" cy="112" r="3.4" className="paw-composition__registration-dot paw-composition__registration-dot--two" />
        <circle cx="200" cy="112" r="3.4" className="paw-composition__registration-dot paw-composition__registration-dot--three" />
        <path d="M120 706h440m620 0h160" className="paw-composition__rule" />
      </g>
      <g className="paw-composition__ambient" data-layer="orbits">
        <circle className="paw-comp8-orbit paw-comp8-orbit--violet" cx="1010" cy="320" r="220" />
        <circle className="paw-comp8-orbit paw-comp8-orbit--ink" cx="330" cy="600" r="44" />
        <circle className="paw-comp8-orbit paw-comp8-orbit--blue" cx="716" cy="772" r="28" />
      </g>
      <rect
        className="paw-comp8-scan"
        fill="url(#paw-comp8-scan-gradient)"
        height="900"
        width="260"
        x="-260"
        y="0"
      />
      <g className="paw-composition__ambient" data-layer="packets">
        <circle className="paw-comp8-packet paw-comp8-packet--red" r="5" style={{ color: '#d1342c' }} />
        <circle className="paw-comp8-packet paw-comp8-packet--cobalt" r="4.5" style={{ color: '#2f4da4' }} />
        <circle className="paw-comp8-packet paw-comp8-packet--yellow" r="4" style={{ color: '#e3a91c' }} />
      </g>
      <g
        className="paw-composition__event-layer paw-composition__event-layer--upper"
        data-source-region="upper-notation"
      >
        <path d="M1040 300C995 236 855 238 752 296" />
        <circle cx="1040" cy="300" r="7" />
      </g>
      <g
        className="paw-composition__event-layer paw-composition__event-layer--grid"
        data-source-region="right-grid"
      >
        <circle cx="752" cy="296" r="12" />
        <circle cx="752" cy="296" r="21" opacity=".34" />
      </g>
    </svg>
  );
}
