import { type CSSProperties, type ReactNode, type SVGProps } from 'react';
import type { PawAppId } from '../runtime/app-registry';
import './paw-app-icon.css';

/** Room is a visible identity inside Agent, but it is not a top-level App. */
export type PawIdentityIconId = PawAppId | 'room';

export type PawAppIconProps = Omit<SVGProps<SVGSVGElement>, 'children'> & {
  appId: PawIdentityIconId;
  size?: number | string;
  title?: string;
};

/**
 * One colour band for all twelve identities: saturated mid-tones that stay
 * legible on the light chrome veil, on white App surfaces and over a rich
 * wallpaper. No identity may be near-black or near-white, so no placement
 * ever needs a per-surface recolour of an icon.
 */
const APP_COLORS: Record<PawIdentityIconId, string> = {
  agent: '#0a84ff',
  room: '#7a5af8',
  browser: '#14b8c8',
  terminal: '#454f5e',
  files: '#f7a91f',
  'project-workbench': '#ff6b4a',
  memory: '#e85d9e',
  knowledge: '#1fa54a',
  'input-studio': '#5e5ce6',
  'app-center': '#0e9f8a',
  'system-monitor': '#52708c',
  'system-settings': '#8e8e93',
};

/** Each identity owns exactly one companion accent for its supporting element. */
const APP_ACCENTS: Record<PawIdentityIconId, string> = {
  agent: '#7bc8ff',
  room: '#b7a3ff',
  browser: '#7fdce4',
  terminal: '#30d158',
  files: '#d9820c',
  'project-workbench': '#ff9a83',
  memory: '#efa0c4',
  knowledge: '#45c06b',
  'input-studio': '#8f8df2',
  'app-center': '#4fc9b6',
  'system-monitor': '#30d158',
  'system-settings': '#d1d1d6',
};

/**
 * PAWOS identity silhouettes — one flat grammar shared by every placement.
 *
 * The grammar: a 48×48 grid with content inside the 4–44 safe area; flat,
 * front-facing forms only (no isometric faces, no rotated stacks — the single
 * permitted rotation is Room's orbit line); each mark is one primary mass in
 * the identity colour, exactly one supporting element in the identity accent,
 * plus at most fine white detail cuts from the shared paper token. Every App
 * still owns a distinct outer contour — there is deliberately no shared
 * square, plate, rail, or sheen, and no white-tile-versus-transparent split.
 * Line icons elsewhere remain actions, so a close/search/tool command can
 * never be mistaken for an App. Room keeps its purple collaboration identity
 * and speaks the Sol/orbit metaphor without becoming a top-level App.
 *
 * Small-size contract: every silhouette must still resolve at 14 / 34 / 48 px
 * on the glacial Wayfinder veil. That means thick masses, deliberate air gaps,
 * and no hairline teeth or paper cuts that vanish when the Dock / menu bar
 * scale them down.
 */
export function PawAppIcon({ appId, className = '', size = 24, style, title, ...props }: PawAppIconProps) {
  const compact = typeof size === 'number' && size <= 18;
  const iconStyle = {
    '--paw-app-icon-color': APP_COLORS[appId],
    '--paw-app-icon-accent': APP_ACCENTS[appId],
    ...style,
  } as CSSProperties;

  return (
    <svg
      {...props}
      aria-hidden={title ? undefined : 'true'}
      aria-label={title}
      className={`paw-app-icon ${className}`.trim()}
      data-paw-app-icon={appId}
      data-paw-icon-color={APP_COLORS[appId]}
      data-paw-icon-scale={compact ? 'small' : undefined}
      focusable="false"
      height={size}
      preserveAspectRatio="xMidYMid meet"
      role={title ? 'img' : undefined}
      style={iconStyle}
      viewBox="0 0 48 48"
      width={size}
    >
      {title ? <title>{title}</title> : null}
      <g
        className="paw-app-icon__silhouette"
        data-paw-icon-silhouette={appId}
        data-paw-icon-variant={compact ? 'compact' : 'full'}
      >
        {silhouettes[appId]}
      </g>
    </svg>
  );
}

/**
 * Six rounded gear teeth as one path. Eight thin teeth muddied at 14 px; six
 * thicker lobes keep the Settings outer contour crisp on the Dock and menu bar.
 */
const GEAR_TEETH =
  'M24.10 1.40L23.90 1.40A3.1 3.1 0 0 1 20.80 4.50L20.80 5.50A3.1 3.1 0 0 1 23.90 8.60L24.10 8.60A3.1 3.1 0 0 1 27.20 5.50L27.20 4.50A3.1 3.1 0 0 1 24.10 1.40Z'
  + 'M43.62 12.79L43.52 12.61A3.1 3.1 0 0 1 39.29 11.48L38.42 11.98A3.1 3.1 0 0 1 37.29 16.21L37.39 16.39A3.1 3.1 0 0 1 41.62 17.52L42.49 17.02A3.1 3.1 0 0 1 43.62 12.79Z'
  + 'M43.52 35.39L43.62 35.21A3.1 3.1 0 0 1 42.49 30.98L41.62 30.48A3.1 3.1 0 0 1 37.39 31.61L37.29 31.79A3.1 3.1 0 0 1 38.42 36.02L39.29 36.52A3.1 3.1 0 0 1 43.52 35.39Z'
  + 'M23.90 46.60L24.10 46.60A3.1 3.1 0 0 1 27.20 43.50L27.20 42.50A3.1 3.1 0 0 1 24.10 39.40L23.90 39.40A3.1 3.1 0 0 1 20.80 42.50L20.80 43.50A3.1 3.1 0 0 1 23.90 46.60Z'
  + 'M4.38 35.21L4.48 35.39A3.1 3.1 0 0 1 8.71 36.52L9.58 36.02A3.1 3.1 0 0 1 10.71 31.79L10.61 31.61A3.1 3.1 0 0 1 6.38 30.48L5.51 30.98A3.1 3.1 0 0 1 4.38 35.21Z'
  + 'M4.48 12.61L4.38 12.79A3.1 3.1 0 0 1 5.51 17.02L6.38 17.52A3.1 3.1 0 0 1 10.61 16.39L10.71 16.21A3.1 3.1 0 0 1 9.58 11.98L8.71 11.48A3.1 3.1 0 0 1 4.48 12.61Z';

/** Three rounded 18×18 squares; the accent square completes the 2×2 grid. */
const APP_GRID =
  'M9.5 4h7C19.5 4 22 6.5 22 9.5v7c0 3-2.5 5.5-5.5 5.5h-7C6.5 22 4 19.5 4 16.5v-7C4 6.5 6.5 4 9.5 4Z'
  + 'M31.5 4h7C41.5 4 44 6.5 44 9.5v7c0 3-2.5 5.5-5.5 5.5h-7c-3 0-5.5-2.5-5.5-5.5v-7C26 6.5 28.5 4 31.5 4Z'
  + 'M9.5 26h7c3 0 5.5 2.5 5.5 5.5v7c0 3-2.5 5.5-5.5 5.5h-7C6.5 44 4 41.5 4 38.5v-7C4 28.5 6.5 26 9.5 26Z';

const silhouettes: Record<PawIdentityIconId, ReactNode> = {
  /* Session bubble with a linked satellite node: system connection, not a face.
     One thick message cut keeps the interior readable at 14 px. */
  agent: <>
    <path className="paw-app-icon__primary" d="M4 15.5C4 9.6 8.9 4.8 14.8 4.8h18.4c5.9 0 10.8 4.8 10.8 10.7v7.4c0 5.9-4.9 10.7-10.8 10.7H19.2L9.2 42.4v-9.2C6 31.2 4 27.6 4 23.4z" />
    <circle className="paw-app-icon__secondary paw-app-icon__outlined" cx="41.2" cy="7.2" r="6.2" strokeWidth="3.2" />
    <rect className="paw-app-icon__paper" height="6.4" rx="3.2" width="20" x="12.5" y="14.8" />
    <rect className="paw-app-icon__paper" height="6.4" rx="3.2" width="12" x="12.5" y="24.2" />
  </>,
  /* Sol with one orbit and one planet: the Room solar collaboration metaphor. */
  room: <>
    <circle className="paw-app-icon__primary" cx="23.5" cy="25.5" r="12.8" />
    <ellipse className="paw-app-icon__ring" cx="23.5" cy="25.5" rx="20.8" ry="7.8" strokeWidth="3.8" transform="rotate(-24 23.5 25.5)" />
    <circle className="paw-app-icon__secondary" cx="42.6" cy="18.2" r="4.8" />
  </>,
  /* Globe with a two-tone compass needle — Browser as Wayfinder guest. */
  browser: <>
    <circle className="paw-app-icon__primary" cx="24" cy="24" r="20" />
    <path className="paw-app-icon__paper" d="M35.2 12.8 27.2 27.2l-7-7z" />
    <path className="paw-app-icon__secondary" d="M12.8 35.2l7.8-14.6 7 7z" />
  </>,
  /* Filled prompt chevron plus live cursor — mass holds at Dock size. */
  terminal: <>
    <path className="paw-app-icon__primary" d="M7 8.5 24 24 7 39.5h6.8L30.8 24 13.8 8.5z" />
    <rect className="paw-app-icon__secondary" height="8.6" rx="4.3" width="18" x="25.2" y="34.2" />
  </>,
  /* Flat folder: deep back tab, amber front body, one label line. */
  files: <>
    <path className="paw-app-icon__secondary" d="M4 30V12.2C4 9.2 6.5 6.8 9.5 6.8h9.8c1.6 0 3.2.7 4.2 2l3.4 4.2h11.6c3 0 5.5 2.5 5.5 5.5V30z" />
    <path className="paw-app-icon__primary" d="M4 17.2h40V34c0 3.6-2.9 6.5-6.5 6.5h-27C6.9 40.5 4 37.6 4 34z" />
    <rect className="paw-app-icon__paper" height="5" rx="2.5" width="18" x="10.5" y="23.5" />
  </>,
  /* Plan ledger: rounded page with a folded corner and one rule — not bars. */
  'project-workbench': <>
    <path className="paw-app-icon__primary" d="M10 5.5h20.5L38 13v24.5c0 3.3-2.7 6-6 6H10c-3.3 0-6-2.7-6-6v-26c0-3.3 2.7-6 6-6z" />
    <path className="paw-app-icon__secondary" d="M30.5 5.5 38 13h-4.5c-1.7 0-3-1.3-3-3z" />
    <rect className="paw-app-icon__paper" height="4.8" rx="2.4" width="18" x="11" y="22" />
    <rect className="paw-app-icon__paper" height="4.8" rx="2.4" width="13" x="11" y="30" />
  </>,
  /* An offset stack of memory cards; the front card keeps one traceable entry. */
  memory: <>
    <rect className="paw-app-icon__secondary" height="24" rx="5.2" width="30" x="11" y="6.5" />
    <rect className="paw-app-icon__primary" height="25.5" rx="6" width="34.5" x="6.5" y="14.5" />
    <circle className="paw-app-icon__paper" cx="15.2" cy="27.2" r="3.8" />
    <rect className="paw-app-icon__paper" height="5.2" rx="2.6" width="14" x="21.5" y="24.6" />
  </>,
  /* Open book: two leaves and a light spine. */
  knowledge: <>
    <path className="paw-app-icon__primary" d="M4.5 9c7.4-2.3 13.6-1 19.5 3.5v30.8c-5.9-4.4-12.1-5.6-19.5-3.6z" />
    <path className="paw-app-icon__secondary" d="M43.5 9c-7.4-2.3-13.6-1-19.5 3.5v30.8c5.9-4.4 12.1-5.6 19.5-3.6z" />
    <rect className="paw-app-icon__paper" height="31" rx="1.6" width="3.4" x="22.3" y="12.2" />
  </>,
  /* Voice waveform bars with clear gaps for small-size reading. */
  'input-studio': <>
    <rect className="paw-app-icon__secondary" height="18" rx="4.2" width="8.2" x="2" y="15" />
    <rect className="paw-app-icon__primary" height="34" rx="4.2" width="8.2" x="14" y="7" />
    <rect className="paw-app-icon__primary" height="44" rx="4.2" width="8.2" x="26" y="2" />
    <rect className="paw-app-icon__secondary" height="22" rx="4.2" width="8.2" x="38" y="13" />
  </>,
  /* Flat 2×2 App grid; the accent square is the one being added. */
  'app-center': <>
    <path className="paw-app-icon__primary" d={APP_GRID} />
    <rect className="paw-app-icon__secondary" height="18" rx="5.5" width="18" x="26" y="26" />
  </>,
  /* Live gauge: dial, signal needle, hub. */
  'system-monitor': <>
    <path className="paw-app-icon__primary" d="M24 6.5C13 6.5 4.2 15.3 4.2 26.3v6.2C4.2 35.2 6.3 37.2 9 37.2h30c2.7 0 4.8-2 4.8-4.7v-6.2C43.8 15.3 35 6.5 24 6.5z" />
    <path className="paw-app-icon__stroke-accent" d="M24 30.2 13.2 16" strokeLinecap="round" strokeWidth="5.4" />
    <circle className="paw-app-icon__paper" cx="24" cy="30.2" r="4.4" />
  </>,
  /* Six-lobe rounded gear — thicker teeth survive 14 px. */
  'system-settings': <>
    <path className="paw-app-icon__primary" d={GEAR_TEETH} />
    <circle className="paw-app-icon__primary" cx="24" cy="24" r="16.2" />
    <circle className="paw-app-icon__paper" cx="24" cy="24" r="7.4" />
  </>,
};

export type PawBrandMarkProps = Omit<SVGProps<SVGSVGElement>, 'children'> & {
  size?: number | string;
  title?: string;
};

/**
 * The PAW system mark: a glacial paw print in the current text colour. Three
 * crisply gapped toe pads and a stamp-like main pad identify the system itself
 * (menu bar, launcher, boot, favicon), never an App, so it stays monochrome and
 * outside the App identity colour system. Geometry is tuned for 13–16 px on the
 * Wayfinder chrome veil — soft animal paws were redesigned because they muddied
 * into one blob at menu-bar size.
 */
export function PawBrandMark({ className = '', size = 16, title, ...props }: PawBrandMarkProps) {
  return (
    <svg
      {...props}
      aria-hidden={title ? undefined : 'true'}
      aria-label={title}
      className={`paw-brand-mark ${className}`.trim()}
      fill="currentColor"
      focusable="false"
      height={size}
      role={title ? 'img' : undefined}
      viewBox="0 0 48 48"
      width={size}
    >
      {title ? <title>{title}</title> : null}
      {/* Deliberate air gaps between toes (~3–4 units) so the mark stays three
          pads + one heel at 14 px instead of dissolving into a soft animal blob. */}
      <ellipse cx="8.8" cy="16.2" rx="6" ry="7.4" transform="rotate(-22 8.8 16.2)" />
      <ellipse cx="24" cy="10.8" rx="6.2" ry="7.6" />
      <ellipse cx="39.2" cy="16.2" rx="6" ry="7.4" transform="rotate(22 39.2 16.2)" />
      <path d="M24 22.6c5 0 9.4 2.2 12.2 5.6 2.4 2.9 3.6 6.4 3.6 9.4 0 6.4-6.6 10.2-15.8 10.2S8.2 44 8.2 37.6c0-3 1.2-6.5 3.6-9.4 2.8-3.4 7.2-5.6 12.2-5.6z" />
    </svg>
  );
}
