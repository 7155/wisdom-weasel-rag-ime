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

/** Eight rounded gear teeth as one path; the base circle unions them visually. */
const GEAR_TEETH =
  'M23.1 2.4L24.9 2.4A3.4 3.4 0 0 1 28.3 5.8L28.3 7.6A3.4 3.4 0 0 1 24.9 11L23.1 11A3.4 3.4 0 0 1 19.7 7.6L19.7 5.8A3.4 3.4 0 0 1 23.1 2.4Z'
  + 'M38.64 8.09L39.91 9.36A3.4 3.4 0 0 1 39.91 14.17L38.64 15.44A3.4 3.4 0 0 1 33.83 15.44L32.56 14.17A3.4 3.4 0 0 1 32.56 9.36L33.83 8.09A3.4 3.4 0 0 1 38.64 8.09Z'
  + 'M45.6 23.1L45.6 24.9A3.4 3.4 0 0 1 42.2 28.3L40.4 28.3A3.4 3.4 0 0 1 37 24.9L37 23.1A3.4 3.4 0 0 1 40.4 19.7L42.2 19.7A3.4 3.4 0 0 1 45.6 23.1Z'
  + 'M39.91 38.64L38.64 39.91A3.4 3.4 0 0 1 33.83 39.91L32.56 38.64A3.4 3.4 0 0 1 32.56 33.83L33.83 32.56A3.4 3.4 0 0 1 38.64 32.56L39.91 33.83A3.4 3.4 0 0 1 39.91 38.64Z'
  + 'M24.9 45.6L23.1 45.6A3.4 3.4 0 0 1 19.7 42.2L19.7 40.4A3.4 3.4 0 0 1 23.1 37L24.9 37A3.4 3.4 0 0 1 28.3 40.4L28.3 42.2A3.4 3.4 0 0 1 24.9 45.6Z'
  + 'M9.36 39.91L8.09 38.64A3.4 3.4 0 0 1 8.09 33.83L9.36 32.56A3.4 3.4 0 0 1 14.17 32.56L15.44 33.83A3.4 3.4 0 0 1 15.44 38.64L14.17 39.91A3.4 3.4 0 0 1 9.36 39.91Z'
  + 'M2.4 24.9L2.4 23.1A3.4 3.4 0 0 1 5.8 19.7L7.6 19.7A3.4 3.4 0 0 1 11 23.1L11 24.9A3.4 3.4 0 0 1 7.6 28.3L5.8 28.3A3.4 3.4 0 0 1 2.4 24.9Z'
  + 'M8.09 9.36L9.36 8.09A3.4 3.4 0 0 1 14.17 8.09L15.44 9.36A3.4 3.4 0 0 1 15.44 14.17L14.17 15.44A3.4 3.4 0 0 1 9.36 15.44L8.09 14.17A3.4 3.4 0 0 1 8.09 9.36Z';

/** The two blades of the plug an App Center package is installed with. */
const PLUG_PRONGS =
  'M18.5 4h1a3 3 0 0 1 3 3V16.5h-7V7a3 3 0 0 1 3-3Z'
  + 'M28.5 4h1a3 3 0 0 1 3 3V16.5h-7V7a3 3 0 0 1 3-3Z';

/** Three keycaps cut out of the Input Studio keyboard as one path. */
const KEY_ROW =
  'M13.2 19h2a1.8 1.8 0 0 1 1.8 1.8v2a1.8 1.8 0 0 1-1.8 1.8h-2a1.8 1.8 0 0 1-1.8-1.8v-2A1.8 1.8 0 0 1 13.2 19Z'
  + 'M23 19h2a1.8 1.8 0 0 1 1.8 1.8v2a1.8 1.8 0 0 1-1.8 1.8h-2a1.8 1.8 0 0 1-1.8-1.8v-2A1.8 1.8 0 0 1 23 19Z'
  + 'M32.8 19h2a1.8 1.8 0 0 1 1.8 1.8v2a1.8 1.8 0 0 1-1.8 1.8h-2a1.8 1.8 0 0 1-1.8-1.8v-2A1.8 1.8 0 0 1 32.8 19Z';

const silhouettes: Record<PawIdentityIconId, ReactNode> = {
  /* Session bubble with a linked satellite node: system connection, not a face.
     The node rides the bubble's own corner, so the mark reads as one Session
     with one companion instead of a bubble wearing a notification badge. */
  agent: <>
    <path className="paw-app-icon__primary" d="M14 8h14c5.5 0 10 4.5 10 10v8c0 5.5-4.5 10-10 10H18.6L10 44v-8.7C6.3 33.5 4 30 4 26v-8C4 12.5 8.5 8 14 8Z" />
    <circle className="paw-app-icon__secondary paw-app-icon__outlined" cx="37.4" cy="11" r="5" strokeWidth="2.8" />
    <rect className="paw-app-icon__paper" height="5.4" rx="2.7" width="16.5" x="11.5" y="15.4" />
    <rect className="paw-app-icon__paper" height="5.4" rx="2.7" width="10" x="11.5" y="24" />
  </>,
  /* Sol with one orbit and one planet: the Room solar collaboration metaphor. */
  room: <>
    <circle className="paw-app-icon__primary" cx="21.5" cy="26" r="10.5" />
    <ellipse className="paw-app-icon__ring" cx="21.5" cy="26" rx="17" ry="6.5" strokeWidth="3.2" transform="rotate(-24 21.5 26)" />
    <circle className="paw-app-icon__secondary" cx="38.5" cy="11.5" r="4.6" />
  </>,
  /* Globe with a two-tone compass needle. A window with an address bar was the
     fourth rounded rectangle in the set and read as an appliance at 16px. */
  browser: <>
    <circle className="paw-app-icon__primary" cx="24" cy="24" r="20" />
    <path className="paw-app-icon__paper" d="M34.9 13.1 27.4 27.4l-6.8-6.8z" />
    <path className="paw-app-icon__secondary" d="M13.1 34.9l7.5-14.3 6.8 6.8z" />
  </>,
  /* A naked prompt: rounded chevron plus the live cursor. */
  terminal: <>
    <path className="paw-app-icon__stroke" d="M9.5 9.5 25.5 24 9.5 38.5" strokeLinecap="round" strokeLinejoin="round" strokeWidth="8.4" />
    <rect className="paw-app-icon__secondary" height="8.4" rx="4.2" width="17.5" x="25.5" y="34.5" />
  </>,
  /* Flat folder: deep back tab, amber front body, one label line. */
  files: <>
    <path className="paw-app-icon__secondary" d="M4 30V12.5C4 9.5 6.5 7 9.5 7h9.6c1.6 0 3.2.7 4.2 2l3.5 4.4h11.7c3 0 5.5 2.5 5.5 5.5V30z" />
    <path className="paw-app-icon__primary" d="M4 17.5h40V34c0 3.6-2.9 6.5-6.5 6.5h-27C6.9 40.5 4 37.6 4 34z" />
    <rect className="paw-app-icon__paper" height="4.6" rx="2.3" width="17" x="10.5" y="24" />
  </>,
  /* The plan board itself: a clipped work sheet carrying two task lines. */
  'project-workbench': <>
    <rect className="paw-app-icon__secondary" height="8" rx="4" width="16" x="16" y="5" />
    <path className="paw-app-icon__primary" d="M11.5 10h25c3 0 5.5 2.5 5.5 5.5v23c0 3-2.5 5.5-5.5 5.5h-25C8.5 44 6 41.5 6 38.5v-23C6 12.5 8.5 10 11.5 10Z" />
    <rect className="paw-app-icon__paper" height="5.2" rx="2.6" width="21" x="13.5" y="21" />
    <rect className="paw-app-icon__paper" height="5.2" rx="2.6" width="13" x="13.5" y="30.5" />
  </>,
  /* An offset stack of memory cards; the front card keeps one traceable entry. */
  memory: <>
    <rect className="paw-app-icon__secondary" height="24" rx="5" width="30" x="11" y="7" />
    <rect className="paw-app-icon__primary" height="25" rx="6" width="34" x="7" y="15" />
    <circle className="paw-app-icon__paper" cx="15.5" cy="27.5" r="3.6" />
    <rect className="paw-app-icon__paper" height="5" rx="2.5" width="13" x="22" y="25" />
  </>,
  /* Open book: two leaves and a light spine. */
  knowledge: <>
    <path className="paw-app-icon__primary" d="M4.5 9.2c7.4-2.3 13.6-1 19.5 3.5v30.5c-5.9-4.4-12.1-5.6-19.5-3.6z" />
    <path className="paw-app-icon__secondary" d="M43.5 9.2c-7.4-2.3-13.6-1-19.5 3.5v30.5c5.9-4.4 12.1-5.6 19.5-3.6z" />
    <rect className="paw-app-icon__paper" height="30.7" rx="1.6" width="3.2" x="22.4" y="12.6" />
  </>,
  /* The keyboard Input Studio actually owns, under its candidate bar. Voice is
     one input source here, so an equaliser cannot stand for the whole App. */
  'input-studio': <>
    <path className="paw-app-icon__primary" d="M9.5 13h29c3 0 5.5 2.5 5.5 5.5v11c0 3-2.5 5.5-5.5 5.5h-29C6.5 35 4 32.5 4 29.5v-11C4 15.5 6.5 13 9.5 13Z" />
    <path className="paw-app-icon__paper" d={KEY_ROW} />
    <rect className="paw-app-icon__secondary" height="5" rx="2.5" width="21" x="13.5" y="26.5" />
  </>,
  /* The plug a package is installed with; the grid it replaced was the one
     interchangeable mark in the set and doubled the conversation tool mark. */
  'app-center': <>
    <path className="paw-app-icon__secondary" d={PLUG_PRONGS} />
    <path className="paw-app-icon__primary" d="M11 13h26a4 4 0 0 1 4 4v5c0 9.4-7.6 17-17 17S7 31.4 7 22v-5a4 4 0 0 1 4-4ZM20 34h8v6a4 4 0 0 1-8 0z" />
  </>,
  /* Live gauge: dial, signal needle, hub. */
  'system-monitor': <>
    <path className="paw-app-icon__primary" d="M24 7C13.2 7 4.5 15.7 4.5 26.5v6C4.5 35 6.5 37 9 37h30c2.5 0 4.5-2 4.5-4.5v-6C43.5 15.7 34.8 7 24 7z" />
    <path className="paw-app-icon__stroke-accent" d="M24 30.5 13.5 16.5" strokeLinecap="round" strokeWidth="5" />
    <circle className="paw-app-icon__paper" cx="24" cy="30.5" r="4.2" />
  </>,
  /* Rounded-tooth gear. Slider rails carry no mass at 16px, where a settings
     mark has to survive the menu bar. */
  'system-settings': <>
    <path className="paw-app-icon__primary" d={GEAR_TEETH} />
    <circle className="paw-app-icon__primary" cx="24" cy="24" r="16.6" />
    <circle className="paw-app-icon__paper" cx="24" cy="24" r="7.2" />
  </>,
};

export type PawBrandMarkProps = Omit<SVGProps<SVGSVGElement>, 'children'> & {
  size?: number | string;
  title?: string;
};

/**
 * The PAW system mark: a paw print in the current text colour. It identifies
 * the system itself (menu bar, launcher, boot), never an App, so it stays
 * monochrome and outside the App identity colour system.
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
      {/* Flared toe pads so the system paw reads as a mark, not three identical dots. */}
      <ellipse cx="9.8" cy="18.2" rx="5.4" ry="7.4" transform="rotate(-18 9.8 18.2)" />
      <ellipse cx="24" cy="12.2" rx="6.2" ry="7.8" />
      <ellipse cx="38.2" cy="18.2" rx="5.4" ry="7.4" transform="rotate(18 38.2 18.2)" />
      <path d="M24 23.6c4.4 0 8.4 1.9 11 4.8 2.2 2.4 3.5 5.4 3.5 8.2 0 6.2-6.5 10-14.5 10S9.5 42.8 9.5 36.6c0-2.8 1.3-5.8 3.5-8.2 2.6-2.9 6.6-4.8 11-4.8z" />
    </svg>
  );
}
