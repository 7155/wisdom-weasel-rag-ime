import { useEffect, useRef } from 'react';
import { PAW_COMPOSITION_PULSE_EVENT, type PawCompositionPulseSource } from '../runtime/composition-pulse';

/**
 * PAWOS desktop wallpaper — the Wayfinder fog terrain at first light. One
 * coherent direction pushed as far as deterministic SVG allows: a photographic
 * landscape of six ridge lines sinking into valley fog under a deep glacial
 * sky, lit by a source that is never drawn as a shape. Depth comes from real
 * photographic technique, not from line work: atmospheric perspective (each
 * ridge fades into the fog that separates it from the next), depth-of-field
 * blur on the far ranges, airlight veils that scatter around the light,
 * resting mist banks, and a static film grain pass that kills gradient
 * banding. No sun disc, no dashed orbits, no icon-like marks — nothing on the
 * desktop asks to be read. The ridgeline polylines are baked from seeded
 * fractal noise (ridged fBm for the far ranges, rolling fBm for the
 * foothills), so the silhouettes carry real terrain character while staying
 * byte-for-byte deterministic.
 *
 * Value is the whole composition. An earlier pass held the entire sky in the
 * pale end of the range, and the result was a picture with nothing in it: six
 * ridges resolved to the same milky grey, the horizon read as unpainted paper,
 * and the ambient weather had no ground dark enough to register against. The
 * ramp now runs from near-navy at the zenith to near-black in the near terrain
 * with one narrow luminous band between them, and that band is deliberately
 * not blown out across its full width — a skyline equally bright at every x
 * has no light direction. The brightness at the gap comes from the bloom and
 * daylight radials anchored on it, so the light has somewhere it comes from.
 *
 * Render budget — the rule that fixed the desktop freeze: the SVG is a
 * painting, not a stage. It rasterizes once (film grain and the three
 * depth-of-field blurs run exactly one time) and nothing ever invalidates it
 * again — no CSS animation targets an SVG node, no WAAPI runs inside it, no
 * custom property lands on it. The earlier ambient weather (mist drift,
 * cirrus, daylight tide, warmth breathe) stepped the SVG's paint every one to
 * two seconds forever, and every step re-rastered the full-bleed
 * feTurbulence/blur stack under the chrome glass — on large or HiDPI screens
 * the raster pipeline never drained and the pointer starved.
 *
 * Everything that moves therefore lives in the `.paw-field-live` HTML overlay
 * above the painting, and every moving property is compositor-only —
 * transform and opacity, never a filter, never layout, never paint:
 *
 * - Ambient weather, five layers: volumetric shafts fanning out of the horizon
 *   gap, two cold aurora curtains crossing the upper sky, a fog bank drifting
 *   along the valley, and a sheen breathing on the light. They loop in CSS on
 *   174s / 132s / 96s / 118s / 34s ease-in-out alternating cycles; no script
 *   drives a frame of it. Attribute selectors pause every loop while the
 *   desktop is unwatched (`data-ambient-paused` covers a hidden document, a
 *   focused App window, Launchpad and the overview plane), while collaboration
 *   focus owns the stage, and while a window drag/resize owns the frame
 *   budget. Where a layer needs a soft boundary it carries a static
 *   `mask-image`, which bakes into that layer's one raster — unlike a filter,
 *   it costs nothing per frame and cannot reach the picture underneath.
 * - Runtime pulses (`pulsePawComposition` / playing audio): one pre-blurred
 *   radial-gradient glow over the light gap, animated with compositor-only
 *   opacity/scale, plus a residual `--paw-composition-energy` that keeps the
 *   horizon slightly lit after activity. Pulses are skipped under the same
 *   four suspension signals.
 *
 * Both reduced-motion signals drop all choreography and keep only the
 * residual light and the resting veil densities.
 */

/* The picture is a module constant: React reconciles it by reference, so a
 * Wayfinder re-render can never walk the terrain subtree again. */
const pawFieldPicture = (
  <svg
    aria-hidden="true"
    className="paw-composition-field"
    preserveAspectRatio="xMidYMid slice"
    viewBox="0 0 1440 900"
  >
    <defs>
      {/* Sky: the picture's whole drama lives in this one ramp. A deep glacial
          zenith falls through cold blue into a narrow luminous ice band right
          above the ridge lines, so the light source is implied by the
          atmosphere rather than drawn. The zenith is dark on purpose — a pale
          sky flattens every ridge into the same milky grey and leaves the
          aurora nothing to glow against; carrying real value from near-navy to
          near-white is what makes the horizon read as light instead of as
          unpainted paper, and what lets one soft layer of weather register at
          all. */}
      <linearGradient gradientUnits="userSpaceOnUse" id="paw-field-sky" x1="0" x2="0" y1="0" y2="900">
        <stop offset="0" stopColor="#22355c" />
        <stop offset=".16" stopColor="#2e4470" />
        <stop offset=".32" stopColor="#425e8f" />
        <stop offset=".46" stopColor="#6285ae" />
        <stop offset=".56" stopColor="#87aacb" />
        {/* The horizon band stays a moderate value on its own. A full-width
            blown-out band gives the picture no light direction — every point
            along the skyline is equally lit and the scene reads flat. The
            luminance at the gap comes from the bloom and daylight radials
            instead, which are anchored at x=985, so the light has somewhere
            it is actually coming from and the left horizon can stay deep. */}
        <stop offset=".615" stopColor="#cadced" />
        <stop offset=".66" stopColor="#bcd2e7" />
        <stop offset=".78" stopColor="#9db8d6" />
        <stop offset="1" stopColor="#8aa6ca" />
      </linearGradient>
      <radialGradient cx="985" cy="552" gradientUnits="userSpaceOnUse" id="paw-field-bloom" r="560">
        <stop offset="0" stopColor="#ffffff" stopOpacity=".95" />
        <stop offset=".3" stopColor="#eef7fb" stopOpacity=".46" />
        <stop offset=".6" stopColor="#dfeaf8" stopOpacity=".18" />
        <stop offset="1" stopColor="#dfeaf8" stopOpacity="0" />
      </radialGradient>
      {/* The single temperature accent in an otherwise cold world: a whisper
          of low sun inside the gap, small enough to stay light rather than
          turn the picture into paper. */}
      <radialGradient cx="985" cy="552" gradientUnits="userSpaceOnUse" id="paw-field-warmth" r="210">
        <stop offset="0" stopColor="#ffeed2" stopOpacity=".4" />
        <stop offset=".6" stopColor="#fdf3e2" stopOpacity=".16" />
        <stop offset="1" stopColor="#fdf3e2" stopOpacity="0" />
      </radialGradient>
      {/* Airlight: light scattered by the atmosphere in front of the far
          ranges. Shared by both veils; nearer terrain receives less. */}
      <radialGradient id="paw-field-airlight" cx="50%" cy="50%" r="50%">
        <stop offset="0" stopColor="#ffffff" stopOpacity=".58" />
        <stop offset=".5" stopColor="#eef7fc" stopOpacity=".27" />
        <stop offset="1" stopColor="#ffffff" stopOpacity="0" />
      </radialGradient>
      {/* Atmospheric perspective: every ridge is darkest at its crest and
          dissolves into the fog pooling at its base; each nearer layer
          starts deeper and its fog is a step less bright. The ramp now runs
          the full way from pale ice to near-black slate, so the six
          silhouettes separate at a glance instead of blurring into one
          grey. The chrome that sits over the deep end — Dock, windows,
          menu bar — carries its own bright ground. */}
      <linearGradient gradientUnits="userSpaceOnUse" id="paw-field-ridge-veil" x1="0" x2="0" y1="545" y2="760">
        <stop offset="0" stopColor="#bed2ec" />
        <stop offset="1" stopColor="#dfe9f6" />
      </linearGradient>
      <linearGradient gradientUnits="userSpaceOnUse" id="paw-field-ridge-far" x1="0" x2="0" y1="495" y2="800">
        <stop offset="0" stopColor="#a2b9da" />
        <stop offset=".55" stopColor="#c9daf0" />
        <stop offset="1" stopColor="#dee8f6" />
      </linearGradient>
      <linearGradient gradientUnits="userSpaceOnUse" id="paw-field-ridge-midfar" x1="0" x2="0" y1="585" y2="850">
        <stop offset="0" stopColor="#86a0c9" />
        <stop offset=".55" stopColor="#b4c9e6" />
        <stop offset="1" stopColor="#d4e2f3" />
      </linearGradient>
      <linearGradient gradientUnits="userSpaceOnUse" id="paw-field-ridge-mid" x1="0" x2="0" y1="685" y2="910">
        <stop offset="0" stopColor="#5f7aa6" />
        <stop offset=".6" stopColor="#99b1d4" />
        <stop offset="1" stopColor="#c4d5ec" />
      </linearGradient>
      <linearGradient gradientUnits="userSpaceOnUse" id="paw-field-ridge-close" x1="0" x2="0" y1="755" y2="960">
        <stop offset="0" stopColor="#3d5075" />
        <stop offset=".62" stopColor="#7389b2" />
        <stop offset="1" stopColor="#a9bddb" />
      </linearGradient>
      <linearGradient gradientUnits="userSpaceOnUse" id="paw-field-ridge-near" x1="0" x2="0" y1="838" y2="980">
        <stop offset="0" stopColor="#202c46" />
        <stop offset=".65" stopColor="#45567a" />
        <stop offset="1" stopColor="#7f93b6" />
      </linearGradient>
      {/* Mist banks: soft edges come from the gradient itself instead of a
          live feGaussianBlur, so the fog costs one gradient fill in the
          picture's single rasterization. */}
      <radialGradient id="paw-field-mist-ball" cx="50%" cy="50%" r="50%">
        <stop offset="0" stopColor="#ffffff" stopOpacity="1" />
        <stop offset=".55" stopColor="#ffffff" stopOpacity=".92" />
        <stop offset=".8" stopColor="#ffffff" stopOpacity=".45" />
        <stop offset="1" stopColor="#ffffff" stopOpacity="0" />
      </radialGradient>
      {/* Early daylight resting over the light gap in the valley. */}
      <radialGradient id="paw-field-daylight" cx="50%" cy="50%" r="50%">
        <stop offset="0" stopColor="#ffffff" stopOpacity=".72" />
        <stop offset=".55" stopColor="#e8f3fb" stopOpacity=".3" />
        <stop offset="1" stopColor="#ffffff" stopOpacity="0" />
      </radialGradient>
      {/* Depth of field: only the far ranges soften into the haze — the
          near terrain reads sharp without spending blur. One-time rasters;
          nothing here ever re-filters. */}
      <filter id="paw-field-dof-veil"><feGaussianBlur stdDeviation="4.5" /></filter>
      <filter id="paw-field-dof-far"><feGaussianBlur stdDeviation="3" /></filter>
      <filter id="paw-field-dof-midfar"><feGaussianBlur stdDeviation="1.8" /></filter>
      {/* Deterministic film grain (fixed seed, stitched tiles): the dark
          speckles key off the red noise channel and the light speckles off
          the independent green channel, so one feTurbulence evaluation
          yields both passes with their few-percent strengths baked in. */}
      <filter id="paw-field-grain" x="0" y="0" width="100%" height="100%">
        <feTurbulence baseFrequency=".8" numOctaves="2" result="paw-grain-noise" seed="7" stitchTiles="stitch" type="fractalNoise" />
        <feColorMatrix in="paw-grain-noise" result="paw-grain-dark" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  .036 0 0 0 -.0072" />
        <feColorMatrix in="paw-grain-noise" result="paw-grain-light" type="matrix" values="0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  0 .045 0 0 -.009" />
        <feMerge>
          <feMergeNode in="paw-grain-dark" />
          <feMergeNode in="paw-grain-light" />
        </feMerge>
      </filter>
    </defs>
    <rect className="paw-field__sky" width="1440" height="900" fill="url(#paw-field-sky)" />
    <circle className="paw-field__bloom" cx="985" cy="552" r="560" fill="url(#paw-field-bloom)" />
    <circle className="paw-field__warmth" cx="985" cy="552" r="210" fill="url(#paw-field-warmth)" />
    {/* Light pillar — the cold-climate phenomenon that gives the gap a
        vertical axis: ice crystals in the column of air above and below the
        light bounce it back at the viewer. Both halves reuse the pre-blurred
        mist gradient, so the whole effect costs two gradient fills in the
        picture's single rasterization. */}
    <ellipse className="paw-field__pillar paw-field__pillar--sky" cx="985" cy="438" rx="58" ry="164" fill="url(#paw-field-mist-ball)" opacity=".2" />
    {/* High cirrus haze: a second weather depth resting against the valley
        mist. Faint, tilted and deep rather than thin — over a dark zenith a
        shallow ellipse has nowhere to fall off and draws itself as a ruled
        line across the sky, so each band is given real vertical extent and a
        low density instead. */}
    <g className="paw-field__cirrus">
      <ellipse cx="360" cy="150" rx="500" ry="52" fill="url(#paw-field-mist-ball)" opacity=".12" transform="rotate(-2.2 360 150)" />
      <ellipse cx="900" cy="206" rx="580" ry="58" fill="url(#paw-field-mist-ball)" opacity=".1" transform="rotate(1.6 900 206)" />
      <ellipse cx="1250" cy="104" rx="400" ry="40" fill="url(#paw-field-mist-ball)" opacity=".085" transform="rotate(-1.2 1250 104)" />
    </g>
    <path
      className="paw-field__ridge paw-field__ridge--veil"
      d="M -60 558.4 L -44 558.7 L -28 558.9 L -12 559.1 L 4 559.3 L 20 559.5 L 36 559.7 L 52 559.9 L 68 560.0 L 84 560.1 L 100 560.1 L 116 560.0 L 132 559.9 L 148 559.7 L 164 559.5 L 180 559.3 L 196 559.0 L 212 558.6 L 228 558.2 L 244 557.9 L 260 557.5 L 276 557.3 L 292 557.3 L 308 557.4 L 324 557.4 L 340 557.4 L 356 557.5 L 372 557.8 L 388 558.2 L 404 559.0 L 420 560.1 L 436 561.5 L 452 563.0 L 468 564.4 L 484 565.8 L 500 566.8 L 516 567.4 L 532 567.5 L 548 567.3 L 564 567.0 L 580 566.6 L 596 566.1 L 612 565.4 L 628 564.6 L 644 563.7 L 660 562.4 L 676 560.8 L 692 559.0 L 708 557.2 L 724 555.6 L 740 554.2 L 756 553.2 L 772 552.6 L 788 552.1 L 804 552.0 L 820 552.0 L 836 552.0 L 852 552.0 L 868 552.0 L 884 552.0 L 900 552.0 L 916 552.0 L 932 552.0 L 948 552.0 L 964 552.3 L 980 552.6 L 996 552.9 L 1012 553.0 L 1028 553.1 L 1044 552.9 L 1060 552.8 L 1076 552.6 L 1092 552.5 L 1108 552.5 L 1124 553.0 L 1140 553.7 L 1156 554.6 L 1172 555.6 L 1188 556.6 L 1204 557.4 L 1220 557.9 L 1236 558.2 L 1252 558.3 L 1268 558.3 L 1284 558.3 L 1300 558.4 L 1316 558.8 L 1332 559.5 L 1348 560.5 L 1364 561.6 L 1380 562.8 L 1396 563.9 L 1412 564.8 L 1428 565.3 L 1444 565.5 L 1460 565.2 L 1476 564.5 L 1492 563.6 L 1500 960 L -60 960 Z"
      fill="url(#paw-field-ridge-veil)"
      filter="url(#paw-field-dof-veil)"
    />
    <path
      className="paw-field__ridge paw-field__ridge--far"
      d="M -60 588.5 L -44 580.0 L -28 586.2 L -12 574.7 L 4 570.5 L 20 568.0 L 36 571.2 L 52 560.8 L 68 560.2 L 84 579.1 L 100 595.1 L 116 602.8 L 132 602.1 L 148 601.1 L 164 601.7 L 180 601.6 L 196 598.2 L 212 594.6 L 228 598.3 L 244 595.5 L 260 591.4 L 276 594.6 L 292 574.2 L 308 565.7 L 324 552.6 L 340 539.7 L 356 523.9 L 372 517.9 L 388 511.6 L 404 521.5 L 420 523.0 L 436 517.9 L 452 510.5 L 468 494.8 L 484 506.7 L 500 524.5 L 516 525.7 L 532 536.0 L 548 543.7 L 564 548.5 L 580 540.7 L 596 541.7 L 612 545.9 L 628 552.5 L 644 557.9 L 660 561.6 L 676 570.4 L 692 576.3 L 708 585.7 L 724 596.5 L 740 596.4 L 756 591.6 L 772 588.5 L 788 589.2 L 804 580.1 L 820 576.3 L 836 577.6 L 852 578.3 L 868 582.2 L 884 582.4 L 900 584.5 L 916 588.4 L 932 588.0 L 948 589.4 L 964 590.1 L 980 590.3 L 996 590.6 L 1012 587.8 L 1028 582.3 L 1044 578.2 L 1060 575.9 L 1076 579.6 L 1092 564.2 L 1108 564.9 L 1124 573.1 L 1140 574.2 L 1156 581.9 L 1172 586.2 L 1188 588.5 L 1204 583.7 L 1220 577.9 L 1236 572.8 L 1252 570.2 L 1268 559.7 L 1284 544.3 L 1300 537.4 L 1316 526.0 L 1332 519.1 L 1348 531.1 L 1364 541.1 L 1380 547.9 L 1396 559.2 L 1412 560.3 L 1428 585.1 L 1444 595.2 L 1460 594.6 L 1476 592.8 L 1492 592.8 L 1500 960 L -60 960 Z"
      fill="url(#paw-field-ridge-far)"
      filter="url(#paw-field-dof-far)"
    />
    <circle className="paw-field__airlight paw-field__airlight--far" cx="985" cy="560" r="640" fill="url(#paw-field-airlight)" />
    <ellipse className="paw-field__daylight" cx="985" cy="566" rx="560" ry="132" fill="url(#paw-field-daylight)" />
    <path
      className="paw-field__ridge paw-field__ridge--midfar"
      d="M -60 641.2 L -44 633.0 L -28 639.5 L -12 649.1 L 4 653.7 L 20 651.9 L 36 645.5 L 52 631.8 L 68 621.9 L 84 613.3 L 100 620.8 L 116 622.9 L 132 629.7 L 148 637.0 L 164 635.3 L 180 640.0 L 196 641.0 L 212 641.8 L 228 636.8 L 244 631.4 L 260 627.4 L 276 627.8 L 292 628.4 L 308 629.6 L 324 632.4 L 340 632.6 L 356 627.3 L 372 622.1 L 388 625.3 L 404 615.9 L 420 616.2 L 436 613.4 L 452 613.9 L 468 615.0 L 484 614.3 L 500 619.5 L 516 620.9 L 532 627.7 L 548 624.4 L 564 619.3 L 580 618.6 L 596 625.5 L 612 625.1 L 628 622.5 L 644 624.2 L 660 627.5 L 676 627.1 L 692 626.9 L 708 630.0 L 724 634.0 L 740 638.6 L 756 645.3 L 772 646.4 L 788 647.4 L 804 650.9 L 820 648.7 L 836 648.2 L 852 646.8 L 868 645.0 L 884 644.5 L 900 644.9 L 916 641.9 L 932 642.8 L 948 641.7 L 964 641.0 L 980 645.0 L 996 647.6 L 1012 648.6 L 1028 650.4 L 1044 649.2 L 1060 649.0 L 1076 646.7 L 1092 642.6 L 1108 637.8 L 1124 641.9 L 1140 638.9 L 1156 634.2 L 1172 634.6 L 1188 628.3 L 1204 620.3 L 1220 617.4 L 1236 619.9 L 1252 622.5 L 1268 622.8 L 1284 618.9 L 1300 618.5 L 1316 606.8 L 1332 598.5 L 1348 600.7 L 1364 606.4 L 1380 621.4 L 1396 636.0 L 1412 648.1 L 1428 649.2 L 1444 650.6 L 1460 648.1 L 1476 647.8 L 1492 648.1 L 1500 960 L -60 960 Z"
      fill="url(#paw-field-ridge-midfar)"
      filter="url(#paw-field-dof-midfar)"
    />
    <g className="paw-field__mist paw-field__mist--far">
      <ellipse cx="300" cy="618" rx="360" ry="44" fill="url(#paw-field-mist-ball)" opacity=".5" />
      <ellipse cx="940" cy="604" rx="440" ry="48" fill="url(#paw-field-mist-ball)" opacity=".62" />
      <ellipse cx="1310" cy="612" rx="280" ry="40" fill="url(#paw-field-mist-ball)" opacity=".42" />
    </g>
    <ellipse className="paw-field__pillar paw-field__pillar--valley" cx="985" cy="646" rx="74" ry="126" fill="url(#paw-field-mist-ball)" opacity=".32" />
    <path
      className="paw-field__ridge paw-field__ridge--mid"
      d="M -60 736.8 L -44 737.8 L -28 739.3 L -12 741.2 L 4 743.2 L 20 743.3 L 36 744.1 L 52 741.9 L 68 737.7 L 84 736.0 L 100 733.4 L 116 727.9 L 132 725.2 L 148 727.3 L 164 732.4 L 180 733.9 L 196 731.0 L 212 726.8 L 228 725.1 L 244 721.3 L 260 714.7 L 276 711.6 L 292 715.6 L 308 719.5 L 324 721.2 L 340 722.2 L 356 723.3 L 372 722.5 L 388 720.0 L 404 717.3 L 420 714.4 L 436 708.2 L 452 704.0 L 468 704.7 L 484 708.0 L 500 712.1 L 516 717.5 L 532 723.3 L 548 725.3 L 564 725.5 L 580 726.9 L 596 723.5 L 612 716.8 L 628 716.5 L 644 718.2 L 660 719.5 L 676 725.5 L 692 728.3 L 708 721.0 L 724 712.0 L 740 711.1 L 756 711.7 L 772 711.1 L 788 712.6 L 804 712.2 L 820 708.1 L 836 706.1 L 852 708.4 L 868 708.5 L 884 701.5 L 900 700.0 L 916 700.2 L 932 707.5 L 948 710.1 L 964 710.7 L 980 709.0 L 996 701.3 L 1012 700.5 L 1028 699.6 L 1044 699.5 L 1060 699.0 L 1076 700.8 L 1092 705.4 L 1108 709.2 L 1124 709.8 L 1140 707.5 L 1156 703.4 L 1172 698.1 L 1188 697.3 L 1204 702.0 L 1220 703.6 L 1236 705.1 L 1252 705.7 L 1268 701.8 L 1284 695.6 L 1300 687.3 L 1316 686.8 L 1332 686.6 L 1348 686.6 L 1364 687.0 L 1380 691.1 L 1396 697.6 L 1412 694.1 L 1428 693.6 L 1444 697.6 L 1460 702.7 L 1476 704.1 L 1492 703.3 L 1500 960 L -60 960 Z"
      fill="url(#paw-field-ridge-mid)"
    />
    <circle className="paw-field__airlight paw-field__airlight--near" cx="985" cy="580" r="480" fill="url(#paw-field-airlight)" />
    <g className="paw-field__mist paw-field__mist--mid">
      <ellipse cx="180" cy="706" rx="320" ry="46" fill="url(#paw-field-mist-ball)" opacity=".5" />
      <ellipse cx="760" cy="692" rx="450" ry="50" fill="url(#paw-field-mist-ball)" opacity=".58" />
      <ellipse cx="1240" cy="700" rx="320" ry="44" fill="url(#paw-field-mist-ball)" opacity=".46" />
    </g>
    <path
      className="paw-field__ridge paw-field__ridge--close"
      d="M -60 782.1 L -44 783.2 L -28 785.8 L -12 790.6 L 4 795.8 L 20 801.2 L 36 805.5 L 52 805.3 L 68 801.1 L 84 796.1 L 100 792.8 L 116 789.1 L 132 786.6 L 148 782.4 L 164 781.1 L 180 781.9 L 196 785.9 L 212 789.0 L 228 789.7 L 244 789.8 L 260 789.2 L 276 787.2 L 292 784.4 L 308 782.5 L 324 782.6 L 340 783.0 L 356 782.7 L 372 783.1 L 388 783.6 L 404 782.9 L 420 781.5 L 436 779.9 L 452 780.7 L 468 782.5 L 484 781.2 L 500 779.4 L 516 778.1 L 532 775.8 L 548 773.3 L 564 774.1 L 580 774.8 L 596 775.5 L 612 775.4 L 628 775.7 L 644 776.7 L 660 777.3 L 676 780.2 L 692 782.7 L 708 784.9 L 724 789.5 L 740 792.8 L 756 793.4 L 772 792.5 L 788 791.5 L 804 790.8 L 820 790.5 L 836 789.6 L 852 784.5 L 868 778.7 L 884 777.5 L 900 777.0 L 916 777.5 L 932 778.5 L 948 782.3 L 964 783.6 L 980 780.0 L 996 776.3 L 1012 773.6 L 1028 775.3 L 1044 779.3 L 1060 781.4 L 1076 779.9 L 1092 778.7 L 1108 782.2 L 1124 786.1 L 1140 788.7 L 1156 791.2 L 1172 794.3 L 1188 796.0 L 1204 796.2 L 1220 796.7 L 1236 796.3 L 1252 792.9 L 1268 790.7 L 1284 791.8 L 1300 795.6 L 1316 799.0 L 1332 800.7 L 1348 803.9 L 1364 806.6 L 1380 808.2 L 1396 809.5 L 1412 810.7 L 1428 810.5 L 1444 811.1 L 1460 811.2 L 1476 809.5 L 1492 807.6 L 1500 960 L -60 960 Z"
      fill="url(#paw-field-ridge-close)"
    />
    <g className="paw-field__mist paw-field__mist--near">
      <ellipse cx="480" cy="836" rx="440" ry="54" fill="url(#paw-field-mist-ball)" opacity=".5" />
      <ellipse cx="1120" cy="828" rx="400" ry="50" fill="url(#paw-field-mist-ball)" opacity=".44" />
    </g>
    <path
      className="paw-field__ridge paw-field__ridge--near"
      d="M -60 869.6 L -44 869.3 L -28 869.2 L -12 869.2 L 4 869.4 L 20 869.6 L 36 870.0 L 52 870.4 L 68 870.8 L 84 871.2 L 100 871.4 L 116 871.4 L 132 871.4 L 148 871.4 L 164 871.4 L 180 871.6 L 196 872.0 L 212 872.6 L 228 873.7 L 244 875.2 L 260 877.1 L 276 879.0 L 292 881.0 L 308 882.9 L 324 884.5 L 340 885.7 L 356 886.4 L 372 887.1 L 388 887.7 L 404 888.0 L 420 888.0 L 436 888.0 L 452 888.0 L 468 888.0 L 484 888.0 L 500 888.0 L 516 888.0 L 532 888.0 L 548 888.0 L 564 888.0 L 580 887.6 L 596 886.8 L 612 886.5 L 628 886.5 L 644 886.6 L 660 886.9 L 676 887.3 L 692 887.6 L 708 887.9 L 724 888.0 L 740 887.9 L 756 887.5 L 772 887.3 L 788 887.2 L 804 887.2 L 820 887.1 L 836 887.1 L 852 887.0 L 868 886.8 L 884 886.4 L 900 885.7 L 916 884.6 L 932 883.3 L 948 881.9 L 964 880.4 L 980 879.1 L 996 878.0 L 1012 877.2 L 1028 876.7 L 1044 876.1 L 1060 875.6 L 1076 875.0 L 1092 874.6 L 1108 874.2 L 1124 873.9 L 1140 873.6 L 1156 873.4 L 1172 873.4 L 1188 873.3 L 1204 873.1 L 1220 872.8 L 1236 872.4 L 1252 871.8 L 1268 871.1 L 1284 870.2 L 1300 869.2 L 1316 868.1 L 1332 867.0 L 1348 865.9 L 1364 864.8 L 1380 863.7 L 1396 862.8 L 1412 862.0 L 1428 862.0 L 1444 862.0 L 1460 862.6 L 1476 863.8 L 1492 865.0 L 1500 960 L -60 960 Z"
      fill="url(#paw-field-ridge-near)"
    />
    <rect className="paw-field__grain" width="1440" height="900" filter="url(#paw-field-grain)" />
  </svg>
);

/* The ambient weather plane. Three HTML nodes, each a pre-blurred gradient
 * (soft edges come from the gradient falloff, never from a live filter) and
 * each looping on transform/opacity alone, so the compositor owns them from
 * promotion onward and the painting below is never invalidated. paw-os.css
 * owns their geometry plus the pause and reduced-motion wiring;
 * paw-os-shell-migrated-v1.css owns paint and choreography. A module constant
 * for the same reason as the picture: React reconciles it by reference, so a
 * Wayfinder re-render never walks the weather. */
const pawFieldWeather = (
  <>
    <i className="paw-field-live__rays" />
    <i className="paw-field-live__veil paw-field-live__veil--high" />
    <i className="paw-field-live__veil paw-field-live__veil--low" />
    <i className="paw-field-live__drift" />
    <i className="paw-field-live__sheen" />
  </>
);

export function PawCompositionField({ effects = false }: { effects?: boolean } = {}) {
  const liveRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!effects) return undefined;
    const live = liveRef.current;
    if (!live) return undefined;
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
    // Pulse animations carry this id so a fresh pulse can cancel exactly the
    // previous pulse and nothing else on the overlay.
    const pulseId = 'paw-field-pulse';
    // The overlay never spends frames nobody can see: a hidden document, a
    // desktop whose shell reports the field unwatched (data-ambient-paused —
    // a focused App window, Launchpad or overview covers the scenery), a
    // collaboration-focused desktop and a live window drag/resize all swallow
    // pulses entirely — no energy write, no glow transition, no WAAPI. The
    // same four signals pause the ambient veils through CSS attribute
    // selectors, so the whole overlay goes quiet together.
    const pulsesSuspended = () => {
      if (document.hidden) return true;
      if (live.closest('[data-ambient-paused]')) return true;
      if (live.closest('[data-collaboration-focus]')) return true;
      const root = live.closest<HTMLElement>('.paw-desktop-root');
      return Boolean(root?.dataset.windowInteraction);
    };
    const drive = (source: PawCompositionPulseSource, energyValue: number) => {
      if (pulsesSuspended()) return;
      const energy = Math.max(0, Math.min(1, Number.isFinite(energyValue) ? energyValue : .65));
      live.dataset.drive = source;
      // Residual horizon light: the glow's rest opacity reads this custom
      // property in CSS, so activity leaves the light gap slightly lit. The
      // write invalidates only the two-node overlay, never the picture.
      live.style.setProperty('--paw-composition-energy', energy.toFixed(3));
      const reduceMotionAttr = document.documentElement.getAttribute('data-reduce-motion') === 'true';
      if (reducedMotion.matches || reduceMotionAttr || energy === 0) return;
      const glow = live.querySelector<HTMLElement>('.paw-field-live__glow');
      if (!glow || typeof glow.animate !== 'function') return;
      glow.getAnimations().forEach((animation) => {
        if (animation.id === pulseId) animation.cancel();
      });
      // Compositor-only choreography: opacity plus scale on one HTML element.
      // The static translate lives on the separate `translate` property, so
      // the transform keyframes cannot knock the glow off the light gap.
      glow.animate([
        { transform: 'scale(.62)', opacity: 0 },
        { transform: 'scale(.94)', opacity: .2 + energy * .3, offset: .32 },
        { transform: `scale(${(1.3 + energy * .45).toFixed(2)})`, opacity: 0 },
      ], { id: pulseId, duration: 1240 + energy * 420, easing: 'cubic-bezier(.16, 1, .3, 1)' });
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
    <>
      {pawFieldPicture}
      {effects ? (
        <div aria-hidden="true" className="paw-field-live" ref={liveRef}>
          {pawFieldWeather}
          <i className="paw-field-live__glow" />
        </div>
      ) : null}
    </>
  );
}
