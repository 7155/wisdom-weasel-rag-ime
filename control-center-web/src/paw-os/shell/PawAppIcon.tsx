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

const APP_COLORS: Record<PawIdentityIconId, string> = {
  agent: '#0a84ff',
  room: '#7a5af8',
  browser: '#14b8c8',
  terminal: '#1d1d1f',
  files: '#f7a91f',
  'project-workbench': '#ff6b4a',
  memory: '#e85d9e',
  knowledge: '#1fa54a',
  'input-studio': '#5e5ce6',
  'app-center': '#0e9f8a',
  'system-monitor': '#3e4c59',
  'system-settings': '#8e8e93',
};

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
 * PAWOS identity silhouettes, shared by every visible identity placement.
 *
 * Every App owns a distinct outer contour; there is deliberately no shared
 * square, plate, rail, or sheen. Line icons elsewhere remain actions, so a
 * close/search/tool command can never be mistaken for an App. Room keeps its
 * purple collaboration identity and speaks the Sol/orbit metaphor without
 * becoming a top-level App.
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

const silhouettes: Record<PawIdentityIconId, ReactNode> = {
  /* Session bubble with a linked satellite node: system connection, not a face. */
  agent: <>
    <path className="paw-app-icon__primary" d="M4 16C4 9.9 8.9 5 15 5h18c6.1 0 11 4.9 11 11v7c0 6.1-4.9 11-11 11H19.5L9.8 42.6v-9.4C6.3 31.1 4 27.7 4 23.5z" />
    <circle className="paw-app-icon__secondary" cx="41" cy="7.5" r="6" stroke="#fff" strokeWidth="3" />
    <rect className="paw-app-icon__paper" height="5.6" rx="2.8" width="18" x="13" y="13.5" />
    <rect className="paw-app-icon__paper" height="5.6" rx="2.8" width="11" x="13" y="22.5" />
  </>,
  /* Sol with one orbit and one planet: the Room solar collaboration metaphor. */
  room: <>
    <circle className="paw-app-icon__primary" cx="23.5" cy="25.5" r="12.5" />
    <ellipse className="paw-app-icon__ring" cx="23.5" cy="25.5" rx="20.5" ry="7.5" strokeWidth="3.6" transform="rotate(-24 23.5 25.5)" />
    <circle className="paw-app-icon__secondary" cx="42.5" cy="18.5" r="4.6" />
  </>,
  /* Globe with a two-tone compass needle. */
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
  /* Folder: deep back panel with tab, cool paper, lighter front pocket. */
  files: <>
    <path className="paw-app-icon__secondary" d="M4 34V12.5C4 9.5 6.5 7 9.5 7h9.6c1.6 0 3.2.7 4.2 2l3.5 4.4h11.7c3 0 5.5 2.5 5.5 5.5V34z" />
    <rect className="paw-app-icon__paper" height="14" rx="2.5" width="31" x="8.5" y="15.5" />
    <path className="paw-app-icon__primary" d="M4 23h40v10.5c0 3.6-2.9 6.5-6.5 6.5h-27C6.9 40 4 37.1 4 33.5z" />
  </>,
  /* Staggered plan bars with the next milestone. */
  'project-workbench': <>
    <rect className="paw-app-icon__primary" height="8.6" rx="4.3" width="23" x="4" y="6.5" />
    <rect className="paw-app-icon__primary" height="8.6" opacity=".84" rx="4.3" width="26" x="13" y="19.7" />
    <rect className="paw-app-icon__primary" height="8.6" opacity=".68" rx="4.3" width="17" x="8" y="32.9" />
    <circle className="paw-app-icon__secondary" cx="33.5" cy="37.2" r="6" />
  </>,
  /* A loose stack of memory cards; the front card keeps one traceable entry. */
  memory: <>
    <rect className="paw-app-icon__secondary" height="19" rx="5" transform="rotate(-9 22.5 16)" width="27" x="9" y="6.5" />
    <rect className="paw-app-icon__primary" height="23" rx="6" width="34" x="7" y="17" />
    <circle className="paw-app-icon__paper" cx="15.5" cy="28.5" r="3.6" />
    <rect className="paw-app-icon__paper" height="5" rx="2.5" width="13" x="22" y="26" />
  </>,
  /* Open book: two leaves and a light spine. */
  knowledge: <>
    <path className="paw-app-icon__primary" d="M4.5 9.2c7.4-2.3 13.6-1 19.5 3.5v30.5c-5.9-4.4-12.1-5.6-19.5-3.6z" />
    <path className="paw-app-icon__secondary" d="M43.5 9.2c-7.4-2.3-13.6-1-19.5 3.5v30.5c5.9-4.4 12.1-5.6 19.5-3.6z" />
    <rect className="paw-app-icon__paper" height="30.7" rx="1.6" width="3.2" x="22.4" y="12.6" />
  </>,
  /* Voice waveform bars. */
  'input-studio': <>
    <rect className="paw-app-icon__secondary" height="17" rx="4" width="8" x="2" y="15.5" />
    <rect className="paw-app-icon__primary" height="34" rx="4" width="8" x="14" y="7" />
    <rect className="paw-app-icon__primary" height="44" rx="4" width="8" x="26" y="2" />
    <rect className="paw-app-icon__secondary" height="22" rx="4" width="8" x="38" y="13" />
  </>,
  /* Isometric package. */
  'app-center': <>
    <path className="paw-app-icon__primary" d="M24 2.5 43.5 13.7v20.6L24 45.5 4.5 34.3V13.7z" />
    <path className="paw-app-icon__paper" d="M24 8.9 37.2 16.5 24 24.1 10.8 16.5z" />
    <path className="paw-app-icon__secondary" d="M9.3 21.2 20.8 27.8v12.4L9.3 33.6z" />
  </>,
  /* Live gauge: dome, signal needle, hub. */
  'system-monitor': <>
    <path className="paw-app-icon__primary" d="M24 7C13.2 7 4.5 15.7 4.5 26.5v6C4.5 35 6.5 37 9 37h30c2.5 0 4.5-2 4.5-4.5v-6C43.5 15.7 34.8 7 24 7z" />
    <path className="paw-app-icon__stroke-accent" d="M24 30.5 13.5 16.5" strokeLinecap="round" strokeWidth="5" />
    <circle className="paw-app-icon__paper" cx="24" cy="30.5" r="4.2" />
  </>,
  /* Rounded-tooth gear. */
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
      <ellipse cx="10.5" cy="17.5" rx="5.6" ry="7" transform="rotate(-14 10.5 17.5)" />
      <ellipse cx="24" cy="13" rx="5.9" ry="7.3" />
      <ellipse cx="37.5" cy="17.5" rx="5.6" ry="7" transform="rotate(14 37.5 17.5)" />
      <path d="M24 24.8c4.1 0 7.8 1.7 10.3 4.4 2 2.2 3.2 5 3.2 7.7 0 5.7-6 9.3-13.5 9.3s-13.5-3.6-13.5-9.3c0-2.7 1.2-5.5 3.2-7.7 2.5-2.7 6.2-4.4 10.3-4.4z" />
    </svg>
  );
}
