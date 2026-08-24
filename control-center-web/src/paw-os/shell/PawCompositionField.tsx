import { useEffect, useRef } from 'react';
import { PAW_COMPOSITION_PULSE_EVENT, type PawCompositionPulseSource } from '../runtime/composition-pulse';

/**
 * PAWOS desktop wallpaper — the Wayfinder daybreak field. The whole field is
 * deterministic SVG in the shell's own glacial palette: a cold-light sky, one
 * warm signal beacon on a meridian track, layered translucent ridge terrain
 * and sparse survey marks. No raster asset remains, so the field stays crisp
 * and full-bleed at any scale (`slice` cover on a 1440x900 stage).
 *
 * Runtime pulses (`pulsePawComposition` / playing audio) land as one expanding
 * signal ring at the beacon, a brief rise of the lit ridge crests and survey
 * packets travelling the meridian. Ambient motion is near-imperceptible drift
 * and disappears entirely under reduced motion.
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
      const reduceMotionAttr = document.documentElement.getAttribute('data-reduce-motion') === 'true';
      if (reducedMotion.matches || reduceMotionAttr || energy === 0) return;
      const signal = field.querySelector<SVGCircleElement>('.paw-field__signal');
      if (signal) {
        signal.getAnimations().forEach((animation) => animation.cancel());
        signal.animate([
          { transform: 'scale(.3)', opacity: 0 },
          { transform: 'scale(.8)', opacity: .3 + energy * .3, offset: .28 },
          { transform: `scale(${(1.9 + energy * 1.4).toFixed(2)})`, opacity: 0 },
        ], { duration: 860 + energy * 320, easing: 'cubic-bezier(.16, 1, .3, 1)' });
      }
      const crests = field.querySelector<SVGGElement>('.paw-field__crest-lights');
      if (crests) {
        crests.getAnimations().forEach((animation) => animation.cancel());
        crests.animate([
          { opacity: .55 },
          { opacity: (.55 + energy * .45).toFixed(3), offset: .3 },
          { opacity: .55 },
        ], { duration: 980 + energy * 260, easing: 'cubic-bezier(.65, 0, .35, 1)' });
      }
      const packets = field.querySelectorAll<SVGCircleElement>('.paw-field__packet');
      packets.forEach((packet, index) => {
        packet.getAnimations().forEach((animation) => animation.cancel());
        packet.animate([
          { offsetDistance: '0%', opacity: 0 },
          { offsetDistance: '12%', opacity: .9 },
          { offsetDistance: '86%', opacity: .9 },
          { offsetDistance: '100%', opacity: 0 },
        ], { delay: index * 90, duration: 920 + energy * 260 + index * 70, easing: 'cubic-bezier(.42, 0, .28, 1)' });
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
        <linearGradient id="paw-field-sky" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stopColor="#fcfeff" />
          <stop offset=".34" stopColor="#f3f7fc" />
          <stop offset=".56" stopColor="#e7eff9" />
          <stop offset=".665" stopColor="#dae6f6" />
          <stop offset="1" stopColor="#cfdcef" />
        </linearGradient>
        <radialGradient id="paw-field-daycore" cx="50%" cy="50%" r="50%">
          <stop offset="0" stopColor="#ffffff" stopOpacity=".9" />
          <stop offset=".55" stopColor="#fdf6e6" stopOpacity=".34" />
          <stop offset="1" stopColor="#ffffff" stopOpacity="0" />
        </radialGradient>
        <radialGradient id="paw-field-cloud" cx="50%" cy="50%" r="50%">
          <stop offset="0" stopColor="#ffffff" stopOpacity=".85" />
          <stop offset="1" stopColor="#ffffff" stopOpacity="0" />
        </radialGradient>
        <radialGradient id="paw-field-halo" cx="50%" cy="50%" r="50%">
          <stop offset="0" stopColor="#f6d88f" stopOpacity=".78" />
          <stop offset=".62" stopColor="#eebd62" stopOpacity=".3" />
          <stop offset="1" stopColor="#eebd62" stopOpacity="0" />
        </radialGradient>
        <radialGradient id="paw-field-core" cx="42%" cy="38%" r="72%">
          <stop offset="0" stopColor="#fbe7b4" />
          <stop offset=".6" stopColor="#f0c469" />
          <stop offset="1" stopColor="#e0a53f" />
        </radialGradient>
        <linearGradient id="paw-field-crestlight" x1="0" x2="1" y1="0" y2="0">
          <stop offset="0" stopColor="#ffffff" stopOpacity=".05" />
          <stop offset=".55" stopColor="#ffffff" stopOpacity=".4" />
          <stop offset=".82" stopColor="#fff4dd" stopOpacity=".9" />
          <stop offset="1" stopColor="#ffffff" stopOpacity=".5" />
        </linearGradient>
        <linearGradient id="paw-field-ridge-far" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stopColor="#d3e1f6" />
          <stop offset="1" stopColor="#dde8f8" />
        </linearGradient>
        <linearGradient id="paw-field-ridge-mid" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stopColor="#b7cdee" />
          <stop offset="1" stopColor="#c9daf3" />
        </linearGradient>
        <linearGradient id="paw-field-ridge-close" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stopColor="#93b2e0" />
          <stop offset="1" stopColor="#accaee" />
        </linearGradient>
        <linearGradient id="paw-field-ridge-near" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stopColor="#6f92cb" />
          <stop offset="1" stopColor="#8fabd9" />
        </linearGradient>
      </defs>
      <rect className="paw-field__sky" width="1440" height="900" fill="url(#paw-field-sky)" />
      <circle className="paw-field__daycore" cx="1042" cy="268" r="340" fill="url(#paw-field-daycore)" />
      <g className="paw-field__clouds">
        <ellipse className="paw-field__cloud paw-field__cloud--one" cx="400" cy="168" rx="270" ry="34" fill="url(#paw-field-cloud)" />
        <ellipse className="paw-field__cloud paw-field__cloud--two" cx="1180" cy="112" rx="200" ry="26" fill="url(#paw-field-cloud)" />
        <ellipse className="paw-field__cloud paw-field__cloud--haze" cx="820" cy="530" rx="360" ry="30" fill="url(#paw-field-cloud)" />
      </g>
      <g className="paw-field__meridians" fill="none" strokeLinecap="round">
        <path className="paw-field__meridian paw-field__meridian--track" d="M -80 486 C 300 356 720 256 1520 318" />
        <path className="paw-field__meridian paw-field__meridian--high" d="M 180 96 C 520 168 920 176 1280 96" />
        <circle className="paw-field__orbit" cx="1042" cy="268" r="124" />
        <circle className="paw-field__waypoint paw-field__waypoint--cobalt" cx="488" cy="341" r="3" />
        <circle className="paw-field__waypoint paw-field__waypoint--teal" cx="858" cy="304" r="2.5" />
      </g>
      <g className="paw-field__beacon">
        <circle className="paw-field__beacon-ring" cx="1042" cy="268" r="86" />
        <circle className="paw-field__beacon-halo" cx="1042" cy="268" r="52" fill="url(#paw-field-halo)" />
        <circle className="paw-field__beacon-core" cx="1042" cy="268" r="22" fill="url(#paw-field-core)" />
        <circle className="paw-field__signal" cx="1042" cy="268" r="30" />
      </g>
      <g className="paw-field__survey" fill="none" strokeLinecap="round">
        <path className="paw-field__mark paw-field__mark--cross" d="M 392 478 v 16 M 384 486 h 16" />
        <path className="paw-field__mark paw-field__mark--station" d="m 1218 509 8 14 h -16 Z" />
        <path className="paw-field__mark paw-field__mark--ticks" d="M 168 590 v 8 M 196 590 v 8 M 224 590 v 8" />
      </g>
      <g className="paw-field__terrain">
        <path
          className="paw-field__ridge paw-field__ridge--far"
          d="M -40 662 C 150 612 320 594 480 612 C 660 632 760 672 930 656 C 1090 641 1210 602 1330 610 C 1394 614 1444 626 1480 622 L 1480 940 L -40 940 Z"
          fill="url(#paw-field-ridge-far)"
        />
        <path
          className="paw-field__ridge paw-field__ridge--mid"
          d="M -40 742 C 110 688 250 658 420 676 C 590 694 690 742 870 728 C 1030 715 1150 676 1300 690 C 1370 696 1436 712 1480 706 L 1480 940 L -40 940 Z"
          fill="url(#paw-field-ridge-mid)"
        />
        <path
          className="paw-field__ridge paw-field__ridge--close"
          d="M -40 810 C 160 780 320 748 520 764 C 700 778 820 818 1000 800 C 1150 785 1270 742 1480 766 L 1480 940 L -40 940 Z"
          fill="url(#paw-field-ridge-close)"
        />
        <path
          className="paw-field__ridge paw-field__ridge--near"
          d="M -40 856 C 140 826 300 806 470 820 C 640 834 760 866 940 872 C 1100 877 1260 848 1480 838 L 1480 940 L -40 940 Z"
          fill="url(#paw-field-ridge-near)"
        />
      </g>
      <g className="paw-field__crest-lights" fill="none" strokeLinecap="round">
        <path
          className="paw-field__crest paw-field__crest--far"
          d="M -40 662 C 150 612 320 594 480 612 C 660 632 760 672 930 656 C 1090 641 1210 602 1330 610 C 1394 614 1444 626 1480 622"
        />
        <path
          className="paw-field__crest paw-field__crest--mid"
          d="M -40 742 C 110 688 250 658 420 676 C 590 694 690 742 870 728 C 1030 715 1150 676 1300 690 C 1370 696 1436 712 1480 706"
        />
        <path
          className="paw-field__crest paw-field__crest--close"
          d="M -40 810 C 160 780 320 748 520 764 C 700 778 820 818 1000 800 C 1150 785 1270 742 1480 766"
        />
      </g>
      <g className="paw-field__contours" fill="none" strokeLinecap="round">
        <path className="paw-field__contour" d="M -40 786 C 160 756 320 726 520 742 C 700 756 820 794 1000 778 C 1150 764 1270 726 1480 748" />
        <path className="paw-field__contour paw-field__contour--near" d="M -40 834 C 140 806 300 786 470 800 C 640 814 760 844 940 850 C 1100 855 1260 828 1480 818" />
      </g>
      <g className="paw-field__packets">
        <circle className="paw-field__packet paw-field__packet--cobalt" r="4.5" />
        <circle className="paw-field__packet paw-field__packet--teal" r="4" />
        <circle className="paw-field__packet paw-field__packet--gold" r="3.5" />
      </g>
    </svg>
  );
}
