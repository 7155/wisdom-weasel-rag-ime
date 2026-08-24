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
  files: '#f5a623',
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
  room: '#c4b8ff',
  browser: '#83e7e1',
  terminal: '#30d158',
  files: '#ffd47c',
  'project-workbench': '#ffb3a2',
  memory: '#ffacd1',
  knowledge: '#8ce1a4',
  'input-studio': '#b8b7ff',
  'app-center': '#79ded1',
  'system-monitor': '#30d158',
  'system-settings': '#d1d1d6',
};

/**
 * PAWOS identity silhouettes, shared by every visible identity placement.
 *
 * Every App owns a distinct outer contour; there is deliberately no shared
 * square, plate, rail, or sheen. Line icons elsewhere remain actions, so a
 * close/search/tool command can never be mistaken for an App. Room receives
 * its own purple collaboration identity without becoming a top-level App.
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

const silhouettes: Record<PawIdentityIconId, ReactNode> = {
  agent: <>
    <path className="paw-app-icon__primary" d="M5 13C5 7.5 9.5 4 15 4h15c5.5 0 10 3.5 10 9v10c0 5.5-4.5 9-10 9H19L9 41v-9.2C6.5 30 5 27 5 23z" />
    <circle className="paw-app-icon__secondary" cx="38" cy="16" r="7" />
    <rect className="paw-app-icon__paper" height="5" rx="2.5" width="15" x="23" y="13.5" />
  </>,
  room: <>
    <circle className="paw-app-icon__primary" cx="18" cy="19" r="13" />
    <circle className="paw-app-icon__secondary" cx="30" cy="19" r="13" />
    <circle className="paw-app-icon__tertiary" cx="24" cy="31" r="13" />
  </>,
  browser: <>
    <circle className="paw-app-icon__primary" cx="24" cy="24" r="20" />
    <path className="paw-app-icon__paper" d="m33.5 10.5-5.2 17.8-13.8 9.2 5.2-17.8z" />
  </>,
  terminal: <>
    <path className="paw-app-icon__primary" d="M8 5 28 24 8 43l-5-6 14-13L3 11z" />
    <rect className="paw-app-icon__secondary" height="7" rx="3.5" width="17" x="27" y="34" />
  </>,
  files: <>
    <path className="paw-app-icon__primary" d="M4 13a5 5 0 0 1 5-5h11l5 6h14a5 5 0 0 1 5 5v18a6 6 0 0 1-6 6H10a6 6 0 0 1-6-6z" />
    <path className="paw-app-icon__paper" d="M8 20h32l-3 17H11z" />
  </>,
  'project-workbench': <>
    <rect className="paw-app-icon__primary" height="8" rx="4" width="22" x="4" y="6" />
    <rect className="paw-app-icon__primary" height="8" opacity=".86" rx="4" width="29" x="4" y="17" />
    <rect className="paw-app-icon__primary" height="8" opacity=".72" rx="4" width="36" x="4" y="28" />
    <circle className="paw-app-icon__secondary" cx="40" cy="37" r="7" />
  </>,
  memory: <>
    <circle className="paw-app-icon__primary" cx="24" cy="24" r="21" />
    <circle className="paw-app-icon__paper" cx="24" cy="24" r="12.5" />
    <circle className="paw-app-icon__primary" cx="24" cy="24" r="5" />
  </>,
  knowledge: <>
    <path className="paw-app-icon__primary" d="M4 8c8-2 14-.2 19 4v31c-5-4.2-11-5.3-19-3z" />
    <path className="paw-app-icon__secondary" d="M44 8c-8-2-14-.2-19 4v31c5-4.2 11-5.3 19-3z" />
    <rect className="paw-app-icon__paper" height="28" rx="1.5" width="3" x="22.5" y="12" />
  </>,
  'input-studio': <>
    <rect className="paw-app-icon__secondary" height="22" rx="5" width="9" x="3" y="13" />
    <rect className="paw-app-icon__primary" height="38" rx="5" width="9" x="14" y="5" />
    <rect className="paw-app-icon__secondary" height="28" rx="5" width="9" x="25" y="10" />
    <rect className="paw-app-icon__primary" height="42" rx="5" width="9" x="36" y="3" />
  </>,
  'app-center': <>
    <path className="paw-app-icon__primary" d="M24 2 44 13.5v21L24 46 4 34.5v-21z" />
    <path className="paw-app-icon__paper" d="m24 9 13.5 7.8L24 24.5l-13.5-7.7z" />
    <path className="paw-app-icon__secondary" d="M9.5 21.5 21 28v11.5L9.5 33z" />
  </>,
  'system-monitor': <>
    <path className="paw-app-icon__primary" d="M6 10h36l4 8-4 20H6L2 30z" />
    <path className="paw-app-icon__secondary" d="M5 27h10l4-11 6 20 5-14 3 5h10v5H30l-3.5-5.5L24 36l-5-12-2.5 8H5z" />
  </>,
  'system-settings': <>
    <path className="paw-app-icon__primary" d="m24 3 5 4 6-1 3 6 6 3-1 6 3 5-4 5 1 6-6 3-3 6-6-1-5 3-5-4-6 1-3-6-6-3 1-6-3-5 4-5-1-6 6-3 3-6 6 1z" />
    <circle className="paw-app-icon__paper" cx="24" cy="24" r="8" />
  </>,
};
