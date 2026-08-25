import type { ReactNode, SVGProps } from 'react';
import type { AgentExecutionMode } from '../composer/agent-preferences-store';
import {
  permissionMarkKind,
  providerMarkInitial,
  providerMarkKind,
  type PermissionMarkKind,
  type ProviderMarkKind,
} from './conversation-mark-model';
import './conversation-marks.css';

/**
 * Conversation chrome marks.
 *
 * Every mark is drawn on the same 24×24 grid inside a 3–21 safe area so the
 * whole family stays legible from 16 px (a collapsed composer picker) up to
 * 32 px (a Session lead-in chip). Permission marks stay monochrome and inherit
 * the control's colour, so a dangerous control keeps signalling through its
 * own red tone and never through the mark alone; provider marks carry their
 * own restrained hue because that is what makes them recognisable once the
 * provider name is gone.
 *
 * The marks are PAW-original geometry. They are semantic cues for a provider
 * family, not reproductions of a vendor logo (PF-CM-019).
 */

type MarkProps = Omit<SVGProps<SVGSVGElement>, 'children' | 'width' | 'height'> & {
  size?: number;
  /** Renders the mark as a labelled image; omit when a parent control already
   *  carries the accessible name. */
  title?: string;
};

function Mark({ kind, size = 16, title, className, children, ...props }: MarkProps & {
  kind: string;
  children: ReactNode;
}) {
  return (
    <svg
      {...props}
      aria-hidden={title ? undefined : 'true'}
      className={['paw-mark', className].filter(Boolean).join(' ')}
      data-mark={kind}
      focusable="false"
      height={size}
      role={title ? 'img' : undefined}
      viewBox="0 0 24 24"
      width={size}
      xmlns="http://www.w3.org/2000/svg"
    >
      {title ? <title>{title}</title> : null}
      {children}
    </svg>
  );
}

const PERMISSION_GLYPHS: Record<PermissionMarkKind, ReactNode> = {
  /* 只读：a lens inside the shield — the Agent may look, never write. */
  'read-only': (
    <>
      <path
        d="M7.9 12.1c1.2-1.9 2.5-2.9 4.1-2.9s2.9 1 4.1 2.9c-1.2 1.9-2.5 2.9-4.1 2.9s-2.9-1-4.1-2.9Z"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.4"
      />
      <circle cx="12" cy="12.1" r="1.15" fill="currentColor" />
    </>
  ),
  /* 按风险确认：one approved action at a time. */
  'per-action': (
    <path
      d="m8.5 12.2 2.4 2.4 4.6-4.9"
      fill="none"
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth="1.9"
    />
  ),
  /* 工作区托管：the approved directory scope is the boundary. */
  workspace: (
    <path
      d="M8 15.7V9.6h2.9l1 1.3H16v4.8Z"
      fill="none"
      stroke="currentColor"
      strokeLinejoin="round"
      strokeWidth="1.5"
    />
  ),
  /* 安全全自动：full automation kept inside a second, arbitrated boundary. */
  'full-trust': (
    <>
      <path
        d="M12 5.6 7.2 7.4v3.9c0 2.8 1.9 5.3 4.8 6.5 2.9-1.2 4.8-3.7 4.8-6.5V7.4Z"
        fill="none"
        stroke="var(--paw-mark-accent)"
        strokeLinejoin="round"
        strokeWidth="1"
      />
      <path d="M13 8.1 9.3 13.4h2.4l-.7 3.3 3.8-5.3h-2.5Z" fill="currentColor" />
    </>
  ),
};

export function PermissionMark({
  mode,
  ...props
}: MarkProps & { mode: AgentExecutionMode | string | undefined | null }) {
  const kind = permissionMarkKind(mode);
  return (
    <Mark {...props} kind={`permission-${kind}`}>
      <path
        d="M12 2.9 4.9 5.6v5.9c0 4.2 2.9 7.9 7.1 9.6 4.2-1.7 7.1-5.4 7.1-9.6V5.6Z"
        fill="none"
        stroke="currentColor"
        strokeLinejoin="round"
        strokeWidth="1.7"
      />
      {PERMISSION_GLYPHS[kind]}
    </Mark>
  );
}

const PROVIDER_GEOMETRY: Record<Exclude<ProviderMarkKind, 'generic'>, ReactNode> = {
  /* Hexagonal cell with a solid core. */
  openai: (
    <>
      <path
        d="M12 3.2 19.2 7.3v8.2L12 19.6 4.8 15.5V7.3Z"
        fill="none"
        stroke="currentColor"
        strokeLinejoin="round"
        strokeWidth="1.7"
      />
      <circle cx="12" cy="11.4" r="2.7" fill="currentColor" />
    </>
  ),
  /* Converging apex over a tie bar. */
  anthropic: (
    <>
      <path d="M12 4.2 19.2 19.6h-3.6L12 10.9l-3.6 8.7H4.8Z" fill="currentColor" />
      <rect x="9" y="14.1" width="6" height="2" rx="1" fill="var(--paw-mark-accent)" />
    </>
  ),
  /* Four quadrant petals around a hollow centre. */
  google: (
    <>
      <path d="M12 4.2a7.8 7.8 0 0 1 7.8 7.8h-4.2A3.6 3.6 0 0 0 12 8.4Z" fill="currentColor" />
      <path d="M19.8 12A7.8 7.8 0 0 1 12 19.8v-4.2A3.6 3.6 0 0 0 15.6 12Z" fill="var(--paw-mark-accent)" />
      <path d="M12 19.8A7.8 7.8 0 0 1 4.2 12h4.2A3.6 3.6 0 0 0 12 15.6Z" fill="currentColor" />
      <path d="M4.2 12A7.8 7.8 0 0 1 12 4.2v4.2A3.6 3.6 0 0 0 8.4 12Z" fill="var(--paw-mark-accent)" />
    </>
  ),
  /* Probe descending inside a ring. */
  deepseek: (
    <>
      <circle cx="12" cy="12" r="7.8" fill="none" stroke="currentColor" strokeWidth="1.7" />
      <circle cx="12" cy="8.2" r="1.1" fill="var(--paw-mark-accent)" />
      <path
        d="m8.7 11.2 3.3 3.6 3.3-3.6"
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.8"
      />
    </>
  ),
  /* Two interlocking diamonds. */
  qwen: (
    <>
      <path d="m12 3.4 5.4 5.4L12 14.2 6.6 8.8Z" fill="currentColor" />
      <path d="m12 9.8 5.4 5.4L12 20.6l-5.4-5.4Z" fill="var(--paw-mark-accent)" />
    </>
  ),
  /* Crescent with a companion light. */
  moonshot: (
    <>
      <path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z" fill="currentColor" />
      <circle cx="18.4" cy="5.2" r="1.5" fill="var(--paw-mark-accent)" />
    </>
  ),
  /* Prism with a refracted core. */
  zhipu: (
    <>
      <path
        d="M12 3.9 20.5 19.2H3.5Z"
        fill="none"
        stroke="currentColor"
        strokeLinejoin="round"
        strokeWidth="1.8"
      />
      <circle cx="12" cy="14.6" r="2.2" fill="var(--paw-mark-accent)" />
    </>
  ),
  /* Crossed axes. */
  xai: (
    <>
      <path
        d="m5.8 5.2 12.4 13.6"
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeWidth="2.6"
      />
      <path
        d="M18.2 5.2 5.8 18.8"
        fill="none"
        stroke="var(--paw-mark-accent)"
        strokeLinecap="round"
        strokeWidth="2.6"
      />
    </>
  ),
  /* Offset bands. */
  mistral: (
    <>
      <rect x="4.2" y="5.9" width="15.6" height="3.2" rx="1.6" fill="currentColor" />
      <rect x="6.8" y="10.4" width="13" height="3.2" rx="1.6" fill="var(--paw-mark-accent)" />
      <rect x="4.2" y="14.9" width="10.8" height="3.2" rx="1.6" fill="currentColor" />
    </>
  ),
  /* On-device silicon. */
  local: (
    <>
      <path
        d="M9.4 3.4v2.8M14.6 3.4v2.8M9.4 17.8v2.8M14.6 17.8v2.8M3.4 9.4h2.8M3.4 14.6h2.8M17.8 9.4h2.8M17.8 14.6h2.8"
        fill="none"
        stroke="var(--paw-mark-accent)"
        strokeLinecap="round"
        strokeWidth="1.5"
      />
      <rect
        x="6.2"
        y="6.2"
        width="11.6"
        height="11.6"
        rx="2.6"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.7"
      />
      <rect x="9.6" y="9.6" width="4.8" height="4.8" rx="1.2" fill="currentColor" />
    </>
  ),
  /* One hub fanning out to several upstreams. */
  router: (
    <>
      <path
        d="M3.6 12h3M10.8 12h3.4M14.2 12l3.2-4.6M14.2 12l3.2 4.6"
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeWidth="1.6"
      />
      <circle cx="8.7" cy="12" r="2.4" fill="currentColor" />
      <circle cx="18.4" cy="6.6" r="1.6" fill="var(--paw-mark-accent)" />
      <circle cx="18.4" cy="17.4" r="1.6" fill="var(--paw-mark-accent)" />
    </>
  ),
};

export function ProviderMark({
  providerId,
  displayName,
  ...props
}: MarkProps & { providerId?: string | null; displayName?: string | null }) {
  const kind = providerMarkKind(providerId, displayName);
  if (kind === 'generic') {
    const initial = providerMarkInitial(providerId, displayName);
    return (
      <Mark {...props} kind="provider-generic">
        <rect
          x="3.4"
          y="3.4"
          width="17.2"
          height="17.2"
          rx="5"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.7"
        />
        <text
          x="12"
          y="12.6"
          fill="currentColor"
          fontSize={initial.length > 1 ? 8.6 : 11}
          fontWeight="700"
          textAnchor="middle"
          dominantBaseline="middle"
        >
          {initial}
        </text>
      </Mark>
    );
  }
  return <Mark {...props} kind={`provider-${kind}`}>{PROVIDER_GEOMETRY[kind]}</Mark>;
}

/** The capability set this conversation can reach — a tool inventory, not the
 *  wrench action icon that opens an unrelated menu elsewhere. */
export function CapabilityMark(props: MarkProps) {
  return (
    <Mark {...props} kind="capability">
      <rect x="3.8" y="3.8" width="7.4" height="7.4" rx="2.2" fill="currentColor" />
      <rect x="12.8" y="3.8" width="7.4" height="7.4" rx="2.2" fill="var(--paw-mark-accent)" />
      <rect x="3.8" y="12.8" width="7.4" height="7.4" rx="2.2" fill="var(--paw-mark-accent)" />
      <rect x="12.8" y="12.8" width="7.4" height="7.4" rx="3.7" fill="currentColor" />
    </Mark>
  );
}

/** The workspace this Session is bound to; `bound=false` states the absence
 *  rather than hiding the chip. */
export function WorkspaceMark({ bound = true, ...props }: MarkProps & { bound?: boolean }) {
  return (
    <Mark {...props} kind={bound ? 'workspace-bound' : 'workspace-unbound'}>
      <path
        d="M3.9 7.2a1.9 1.9 0 0 1 1.9-1.9h3.5l2 2.4h6.8a1.9 1.9 0 0 1 1.9 1.9v8.9a1.9 1.9 0 0 1-1.9 1.9H5.8a1.9 1.9 0 0 1-1.9-1.9Z"
        fill="none"
        stroke="currentColor"
        strokeLinejoin="round"
        strokeWidth="1.7"
      />
      {bound
        ? <circle cx="12" cy="13.6" r="2.3" fill="currentColor" />
        : <path d="M9.7 13.6h4.6" fill="none" stroke="currentColor" strokeLinecap="round" strokeWidth="1.7" />}
    </Mark>
  );
}
