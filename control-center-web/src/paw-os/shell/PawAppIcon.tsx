import { type ReactNode, type SVGProps, useId } from 'react';
import type { PawAppId } from '../runtime/app-registry';
import './paw-app-icon.css';

/** Room is a visible collaboration identity inside Agent, not a top-level App. */
export type PawIdentityIconId = PawAppId | 'room';

export type PawAppIconProps = Omit<SVGProps<SVGSVGElement>, 'children'> & {
  appId: PawIdentityIconId;
  size?: number | string;
  title?: string;
};

/**
 * Approved identity wall source:
 * /Volumes/undo 4t/MyGlobalDownloads/pawos-brand-icons-v1/icon-wall.html
 *
 * Keep this mapping explicit. The production App ids stay canonical while the
 * data attribute preserves the exact approved source symbol for regression
 * checks and future asset handoffs.
 */
const APPROVED_SYMBOL_IDS: Record<PawIdentityIconId, string> = {
  agent: 'app-agent',
  room: 'app-room',
  browser: 'app-browser',
  terminal: 'app-terminal',
  files: 'app-files',
  'project-workbench': 'app-workbench',
  memory: 'app-memory',
  knowledge: 'app-knowledge',
  'input-studio': 'app-input',
  'app-center': 'app-appcenter',
  'system-monitor': 'app-monitor',
  'system-settings': 'app-settings',
};

const APP_COLORS: Record<PawIdentityIconId, string> = {
  agent: '#0A84FF',
  room: '#7A5AF8',
  browser: '#14B8C8',
  terminal: '#1D1D1F',
  files: '#F5A623',
  'project-workbench': '#FF6B4A',
  memory: '#E85D9E',
  knowledge: '#1FA54A',
  'input-studio': '#5E5CE6',
  'app-center': '#0E9F8A',
  'system-monitor': '#3E4C59',
  'system-settings': '#8E8E93',
};

const PAW_ICON_PAPER = 'var(--paw-icon-paper)';

/** The twelve deterministic SVG drawings from the approved wall. */
const APPROVED_ART: Record<PawIdentityIconId, ReactNode> = {
  agent: <>
    <path d="M10 15 a10 10 0 0 1 10-10 h8 a10 10 0 0 1 10 10 v7 a10 10 0 0 1-10 10 h-9 l-6.5 6 v-6.2 A10 10 0 0 1 10 25 z" fill={PAW_ICON_PAPER} transform="translate(0,4)" />
    <circle cx="24" cy="22" fill="#0A84FF" r="5.2" />
  </>,
  room: <>
    <circle cx="19" cy="19" fill={PAW_ICON_PAPER} opacity=".96" r="8.5" />
    <circle cx="29" cy="19" fill={PAW_ICON_PAPER} opacity=".78" r="8.5" />
    <circle cx="24" cy="28.5" fill={PAW_ICON_PAPER} opacity=".62" r="8.5" />
  </>,
  browser: <>
    <circle cx="24" cy="24" fill="none" r="13.5" stroke={PAW_ICON_PAPER} strokeWidth="4" />
    <path d="M30.5 14.5 L27 27 17.5 33.5 21 21 z" fill={PAW_ICON_PAPER} />
  </>,
  terminal: <>
    <path d="M13 15.5 l9 8.5 -9 8.5" fill="none" stroke="#30D158" strokeLinecap="round" strokeLinejoin="round" strokeWidth="4.2" />
    <rect fill="#E9F7EE" height="3.8" rx="1.9" width="10.5" x="26" y="31" />
  </>,
  files: <>
    <path d="M9 16.5 a2.5 2.5 0 0 1 2.5-2.5 h8.6 l3.6 4.5 h13.8 a2.5 2.5 0 0 1 2.5 2.5 V33 a4 4 0 0 1-4 4 H13 a4 4 0 0 1-4-4 z" fill={PAW_ICON_PAPER} />
    <rect fill="#F5A623" height="3" opacity=".35" width="31" x="9" y="23.5" />
  </>,
  'project-workbench': <>
    <rect fill={PAW_ICON_PAPER} height="4.6" opacity=".96" rx="2.3" width="14" x="11" y="12.5" />
    <rect fill={PAW_ICON_PAPER} height="4.6" opacity=".8" rx="2.3" width="20" x="11" y="21.7" />
    <rect fill={PAW_ICON_PAPER} height="4.6" opacity=".64" rx="2.3" width="24" x="11" y="30.9" />
    <circle cx="38.5" cy="33.2" fill="#FFD9CF" r="3" />
  </>,
  memory: <>
    <circle cx="24" cy="24" fill="none" r="13.5" stroke={PAW_ICON_PAPER} strokeWidth="3.6" />
    <circle cx="24" cy="24" fill="none" opacity=".75" r="7.5" stroke={PAW_ICON_PAPER} strokeWidth="3.6" />
    <circle cx="24" cy="24" fill={PAW_ICON_PAPER} r="2.8" />
  </>,
  knowledge: <>
    <path d="M24 13.5 C21.5 11.2 17 10.6 12 11.2 a2 2 0 0 0-2 2 V32.6 a2 2 0 0 0 2 2.2 c5-.6 9.5-.1 12 1.9 2.5-2 7-2.5 12-1.9 a2 2 0 0 0 2-2.2 V13.2 a2 2 0 0 0-2-2 c-5-.6-9.5 0-12 2.3 z" fill={PAW_ICON_PAPER} />
    <path d="M24 13.5 V36" stroke="#1FA54A" strokeWidth="2.2" />
  </>,
  'input-studio': <>
    <rect fill={PAW_ICON_PAPER} height="12" opacity=".7" rx="1.9" width="3.8" x="10" y="18" />
    <rect fill={PAW_ICON_PAPER} height="26" rx="1.9" width="3.8" x="16.4" y="11" />
    <rect fill={PAW_ICON_PAPER} height="18" opacity=".85" rx="1.9" width="3.8" x="22.8" y="15" />
    <rect fill={PAW_ICON_PAPER} height="32" rx="1.9" width="3.8" x="29.2" y="8" />
    <rect fill={PAW_ICON_PAPER} height="8" opacity=".7" rx="1.9" width="3.8" x="35.6" y="20" />
  </>,
  'app-center': <>
    <path d="M24 9 37.5 16.8 v14.4 L24 39 10.5 31.2 V16.8 z" fill="none" stroke={PAW_ICON_PAPER} strokeLinejoin="round" strokeWidth="3.4" />
    <path d="M24 24.5 V39 M24 24.5 11.2 17.2 M24 24.5 36.8 17.2" fill="none" stroke={PAW_ICON_PAPER} strokeLinejoin="round" strokeWidth="3.4" />
  </>,
  'system-monitor': <path d="M9 27.5 h7.5 l3-9.5 5 16.5 3.6-11 H39" fill="none" stroke="#30D158" strokeLinecap="round" strokeLinejoin="round" strokeWidth="3.6" />,
  'system-settings': <>
    <circle cx="24" cy="24" fill="none" r="6.6" stroke={PAW_ICON_PAPER} strokeWidth="3.6" />
    <path d="M24 8.5 v5.4 M24 34.1 v5.4 M8.5 24 h5.4 M34.1 24 h5.4 M13.2 13.2 l3.8 3.8 M31 31 l3.8 3.8 M34.8 13.2 31 17 M17 31 l-3.8 3.8" stroke={PAW_ICON_PAPER} strokeLinecap="round" strokeWidth="3.6" />
  </>,
};

export function PawAppIcon({ appId, className = '', size = 24, title, ...props }: PawAppIconProps) {
  const compact = typeof size === 'number' && size <= 18;
  const localId = useId().replaceAll(':', '');
  const sheenId = `paw-icon-sheen-${APPROVED_SYMBOL_IDS[appId]}-${localId}`;

  return (
    <svg
      {...props}
      aria-hidden={title ? undefined : 'true'}
      aria-label={title}
      className={`paw-app-icon ${className}`.trim()}
      data-paw-app-icon={appId}
      data-paw-approved-symbol={APPROVED_SYMBOL_IDS[appId]}
      data-paw-icon-color={APP_COLORS[appId]}
      data-paw-icon-scale={compact ? 'small' : undefined}
      focusable="false"
      height={size}
      preserveAspectRatio="xMidYMid meet"
      role={title ? 'img' : undefined}
      viewBox="0 0 48 48"
      width={size}
    >
      {title ? <title>{title}</title> : null}
      <defs>
        <linearGradient id={sheenId} x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stopColor={PAW_ICON_PAPER} stopOpacity=".24" />
          <stop offset=".55" stopColor={PAW_ICON_PAPER} stopOpacity="0" />
        </linearGradient>
      </defs>
      <rect data-paw-icon-tile fill={APP_COLORS[appId]} height="45" rx="11.5" width="45" x="1.5" y="1.5" />
      <rect className="paw-app-icon__sheen" data-paw-icon-sheen fill={`url(#${sheenId})`} height="45" rx="11.5" width="45" x="1.5" y="1.5" />
      <g data-paw-icon-art>{APPROVED_ART[appId]}</g>
    </svg>
  );
}

export type PawBrandMarkProps = Omit<SVGProps<SVGSVGElement>, 'children'> & {
  size?: number | string;
  title?: string;
};

/** The PAW system mark stays monochrome and outside the App identity system. */
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
