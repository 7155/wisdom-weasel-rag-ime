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

/** Head and cord of the plug an App Center package is installed with. */
const PLUG_BODY =
  'M9.5 13h28a3.5 3.5 0 0 1 3.5 3.5V23c0 8.3-6.7 15-15 15h-4c-8.3 0-15-6.7-15-15v-6.5A3.5 3.5 0 0 1 9.5 13Z'
  + 'M21 37h6v4a3 3 0 0 1-6 0z';

/** The two blades above that head. */
const PLUG_PRONGS =
  'M18 4a3 3 0 0 1 3 3v9h-6V7a3 3 0 0 1 3-3Z'
  + 'M30 4a3 3 0 0 1 3 3v9h-6V7a3 3 0 0 1 3-3Z';

/** Four keycaps cut out of the Input Studio keyboard as one path. */
const KEY_ROW =
  'M11.8 21.5h3.4a1.8 1.8 0 0 1 1.8 1.8v2.4a1.8 1.8 0 0 1-1.8 1.8h-3.4a1.8 1.8 0 0 1-1.8-1.8v-2.4a1.8 1.8 0 0 1 1.8-1.8Z'
  + 'M19.3 21.5h3.4a1.8 1.8 0 0 1 1.8 1.8v2.4a1.8 1.8 0 0 1-1.8 1.8h-3.4a1.8 1.8 0 0 1-1.8-1.8v-2.4a1.8 1.8 0 0 1 1.8-1.8Z'
  + 'M26.8 21.5h3.4a1.8 1.8 0 0 1 1.8 1.8v2.4a1.8 1.8 0 0 1-1.8 1.8h-3.4a1.8 1.8 0 0 1-1.8-1.8v-2.4a1.8 1.8 0 0 1 1.8-1.8Z'
  + 'M34.3 21.5h3.4a1.8 1.8 0 0 1 1.8 1.8v2.4a1.8 1.8 0 0 1-1.8 1.8h-3.4a1.8 1.8 0 0 1-1.8-1.8v-2.4a1.8 1.8 0 0 1 1.8-1.8Z';

const silhouettes: Record<PawIdentityIconId, ReactNode> = {
  /* Session bubble with a linked satellite node: system connection, not a face.
     The node rides the bubble's own corner, so the mark reads as one Session
     with one companion instead of a bubble wearing a notification badge. */
  agent: <>
    <path className="paw-app-icon__primary" d="M11 14h14a7 7 0 0 1 7 7v12a7 7 0 0 1-7 7H11a7 7 0 0 1-7-7V21a7 7 0 0 1 7-7ZM22 16.5 34 6.5l-4.5 12z" />
    <circle className="paw-app-icon__secondary" cx="39" cy="10.5" r="4.6" />
    <rect className="paw-app-icon__paper" height="5" rx="2.5" width="16" x="10" y="21" />
    <rect className="paw-app-icon__paper" height="5" rx="2.5" width="10" x="10" y="29" />
  </>,
  /* Sol with one orbit and one planet riding that orbit's own line: the Room
     solar collaboration metaphor. */
  room: <>
    <circle className="paw-app-icon__primary" cx="23" cy="27" r="11" />
    <ellipse className="paw-app-icon__ring" cx="23" cy="27" rx="17.5" ry="6.8" strokeWidth="3.2" transform="rotate(-24 23 27)" />
    <circle className="paw-app-icon__secondary" cx="39" cy="19.9" r="4.7" />
  </>,
  /* A browser window: tab, chrome, address field. A globe belongs to every
     network product and a compass needle is another vendor's browser. */
  browser: <>
    <path className="paw-app-icon__primary" d="M8.5 8h31a4.5 4.5 0 0 1 4.5 4.5v23a4.5 4.5 0 0 1-4.5 4.5h-31A4.5 4.5 0 0 1 4 35.5v-23A4.5 4.5 0 0 1 8.5 8Z" />
    <rect className="paw-app-icon__secondary" height="4.6" rx="2.3" width="21" x="9" y="11.5" />
    <circle className="paw-app-icon__paper" cx="24" cy="28.5" r="8.6" />
    <path className="paw-app-icon__stroke" d="M24 19.9a3.7 8.6 0 0 1 0 17.2 3.7 8.6 0 0 1 0-17.2M15.4 28.5h17.2" strokeWidth="1.8" />
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
  /* The plan board itself: a clipped work sheet carrying one settled step.
     Two stacked bars on a sheet were a progress meter, not a plan. */
  'project-workbench': <>
    <rect className="paw-app-icon__secondary" height="8" rx="4" width="14" x="17" y="5" />
    <path className="paw-app-icon__primary" d="M11.5 9h25a5.5 5.5 0 0 1 5.5 5.5v24a5.5 5.5 0 0 1-5.5 5.5h-25A5.5 5.5 0 0 1 6 38.5v-24A5.5 5.5 0 0 1 11.5 9Z" />
    <path className="paw-app-icon__paper" d="m32.4 19.6 3.1 3.1L21.2 37l-8.7-8.7 3.1-3.1 5.6 5.6z" />
  </>,
  /* An offset stack of memory cards; the front card keeps one traceable entry.
     The offset is wide enough to survive the menu bar as a stack. */
  memory: <>
    <rect className="paw-app-icon__secondary" height="21" rx="5" width="29" x="13" y="6" />
    <rect className="paw-app-icon__primary" height="24" rx="6" width="32" x="6" y="16" />
    <circle className="paw-app-icon__paper" cx="14.2" cy="28" r="3.6" />
    <rect className="paw-app-icon__paper" height="4.8" rx="2.4" width="12" x="21" y="25.6" />
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
    <rect className="paw-app-icon__secondary" height="8.5" rx="4.25" width="32" x="8" y="5" />
    <path className="paw-app-icon__primary" d="M8.5 17h31a4.5 4.5 0 0 1 4.5 4.5v17a4.5 4.5 0 0 1-4.5 4.5h-31A4.5 4.5 0 0 1 4 38.5v-17A4.5 4.5 0 0 1 8.5 17Z" />
    <path className="paw-app-icon__paper" d={KEY_ROW} />
    <rect className="paw-app-icon__paper" height="5.5" rx="2.75" width="20" x="14" y="31.5" />
  </>,
  /* The plug a package is installed with; the grid it replaced was the one
     interchangeable mark in the set and doubled the conversation tool mark. */
  'app-center': <>
    <path className="paw-app-icon__secondary" d={PLUG_PRONGS} />
    <path className="paw-app-icon__primary" d={PLUG_BODY} />
  </>,
  /* Live gauge: dial, signal needle, hub. */
  'system-monitor': <>
    <path className="paw-app-icon__primary" d="M24 7C13.2 7 4.5 15.7 4.5 26.5v6C4.5 35 6.5 37 9 37h30c2.5 0 4.5-2 4.5-4.5v-6C43.5 15.7 34.8 7 24 7z" />
    <path className="paw-app-icon__stroke-accent" d="M24 30.5 13.5 16.5" strokeLinecap="round" strokeWidth="5" />
    <circle className="paw-app-icon__paper" cx="24" cy="30.5" r="4.2" />
  </>,
  /* Two tuned controls: full-width rails with knobs set to different values.
     A gear is the one icon every OS already owns and says nothing about what
     this App actually does. */
  'system-settings': <>
    <rect className="paw-app-icon__primary" height="10" rx="5" width="38" x="5" y="10.5" />
    <circle className="paw-app-icon__secondary" cx="33" cy="15.5" r="7.5" />
    <rect className="paw-app-icon__primary" height="10" rx="5" width="38" x="5" y="27.5" />
    <circle className="paw-app-icon__paper" cx="17" cy="32.5" r="7.5" />
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
      {/* A real paw print: four toes on a spread arc, the outer pair smaller and
          splayed, over one shouldered pad. Three even dots over a circle was a
          generic animal glyph. */}
      <ellipse cx="8.9" cy="23.4" rx="4.5" ry="6.1" transform="rotate(-34 8.9 23.4)" />
      <ellipse cx="18.4" cy="13.6" rx="5.1" ry="6.9" transform="rotate(-13 18.4 13.6)" />
      <ellipse cx="30.4" cy="13.1" rx="5.1" ry="6.9" transform="rotate(13 30.4 13.1)" />
      <ellipse cx="39.6" cy="23.4" rx="4.5" ry="6.1" transform="rotate(34 39.6 23.4)" />
      <path d="M24 25.6c4.9 0 9.4 2.1 12.2 5.4 2.4 2.8 3.8 6 3.8 8.8 0 4-3.4 6.4-8.2 6.4H16.2C11.4 46.2 8 43.8 8 39.8c0-2.8 1.4-6 3.8-8.8 2.8-3.3 7.3-5.4 12.2-5.4Z" />
    </svg>
  );
}
