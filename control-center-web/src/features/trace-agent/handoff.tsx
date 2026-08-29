import { Sparkles } from 'lucide-react';
import { Button, type ButtonProps } from '@/components/primitives';
import { openPawOsRoute, usePawOsDesktop } from '@/features/paw-os/surface-context';

export const TRACE_AGENT_HANDOFF_SCHEMA_VERSION = 'paw.trace-agent-handoff.v1' as const;

export type TraceAgentHandoffKind =
  | 'session'
  | 'room'
  | 'planet'
  | 'satellite'
  | 'tool'
  | 'runtime'
  | 'review'
  | 'memory'
  | 'knowledge'
  | 'sandbox'
  | 'context'
  | 'task'
  | 'file'
  | 'generic';

export type TraceAgentHandoff = {
  schemaVersion: typeof TRACE_AGENT_HANDOFF_SCHEMA_VERSION;
  kind: TraceAgentHandoffKind;
  entityId: string;
  title: string;
  summary: string;
  error?: string;
  sessionId?: string;
  roomId?: string;
  traceId?: string;
  runId?: string;
  failureRef?: string;
  sourceRoute: string;
  workspaceRoots: string[];
  refs: Record<string, string>;
  occurredAtMs: number;
};

export type TraceAgentHandoffInput = Omit<
  TraceAgentHandoff,
  'schemaVersion' | 'entityId' | 'sourceRoute' | 'workspaceRoots' | 'refs' | 'occurredAtMs'
> & {
  entityId?: string;
  sourceRoute?: string;
  workspaceRoots?: string[];
  refs?: Record<string, string | number | boolean | null | undefined>;
  occurredAtMs?: number;
};

const handoffKinds = new Set<TraceAgentHandoffKind>([
  'session',
  'room',
  'planet',
  'satellite',
  'tool',
  'runtime',
  'review',
  'memory',
  'knowledge',
  'sandbox',
  'context',
  'task',
  'file',
  'generic',
]);

const maxTextLength = 4_000;
const maxHandoffIdLength = 180;
const maxHandoffTitleLength = 180;
const maxHandoffSummaryLength = 640;
const maxHandoffErrorLength = 640;
const maxHandoffRefLength = 220;
const maxSourceRouteLength = 480;
const maxHandoffJsonLength = 5_000;

const sensitiveFieldNames = new Set([
  'authorization',
  'auth',
  'token',
  'accesstoken',
  'refreshtoken',
  'secret',
  'password',
  'credential',
  'cookie',
  'apikey',
  'accesskey',
  'privatekey',
  'secretkey',
  'key',
]);

const pathFieldNames = new Set([
  'path',
  'filepath',
  'filename',
  'directory',
  'directorypath',
  'dir',
  'root',
  'workspaceroot',
  'workspaceroots',
]);

const urlFieldNames = new Set(['url', 'sourceurl', 'targeturl', 'href', 'link']);

const sensitiveAssignmentPattern = /\b([A-Za-z][A-Za-z0-9_.-]*(?:authorization(?:header)?|auth(?:token|header)?|token|secret|password|credential|cookie|api[_-]?key|access[_-]?key|private[_-]?key|secret[_-]?key)|key)\s*[:=]\s*(?:"[^"]*"|'[^']*'|(?:(?:Bearer|Basic)\s+)?[^\s,;]+)/giu;
const bearerPattern = /\b(?:Bearer|Basic)\s+[^\s,;]+/giu;
const urlPattern = /\b(?:https?|wss?):\/\/[^\s<>"'`]+/giu;
const windowsPathPattern = /\b[A-Z]:\\[^\s<>"'`]+/giu;
const posixPathPattern = /(?:^|[^A-Za-z0-9])\/(?:[A-Za-z0-9._~-]+\/)+[A-Za-z0-9._~:-]+/gu;
const explicitSchemePattern = /^[A-Za-z][A-Za-z0-9+.-]*:/u;
const machinePathRoutePattern = /^\/(?:users|volumes|private|tmp|var|home|workspace|opt|etc|usr|system|applications)(?:\/|$)/iu;

export function buildTraceAgentHandoffRoute(input: TraceAgentHandoffInput): string {
  const handoff = compactTraceAgentHandoff(normalizeTraceAgentHandoff(input));
  return `/trace-agent?${new URLSearchParams({ handoff: JSON.stringify(handoff) }).toString()}`;
}

export function parseTraceAgentHandoff(search: string | URLSearchParams): TraceAgentHandoff | null {
  try {
    const params = typeof search === 'string'
      ? new URLSearchParams(search.startsWith('?') ? search.slice(1) : search)
      : search;
    const raw = params.get('handoff');
    if (!raw) return null;
    const value = JSON.parse(raw) as unknown;
    if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
    const record = value as Record<string, unknown>;
    if (record.schemaVersion !== TRACE_AGENT_HANDOFF_SCHEMA_VERSION) return null;
    if (!handoffKinds.has(record.kind as TraceAgentHandoffKind)) return null;
    if (!text(record.entityId) || !text(record.title) || !text(record.summary)) return null;
    return normalizeTraceAgentHandoff({
      kind: record.kind as TraceAgentHandoffKind,
      entityId: text(record.entityId),
      title: text(record.title),
      summary: text(record.summary),
      error: text(record.error) || undefined,
      sessionId: text(record.sessionId) || undefined,
      roomId: text(record.roomId) || undefined,
      traceId: text(record.traceId) || undefined,
      runId: text(record.runId) || undefined,
      failureRef: text(record.failureRef) || undefined,
      sourceRoute: text(record.sourceRoute),
      workspaceRoots: stringArray(record.workspaceRoots),
      refs: stringRecord(record.refs),
      occurredAtMs: finiteNumber(record.occurredAtMs),
    });
  } catch {
    return null;
  }
}

export function TraceAgentHandoffButton({
  handoff,
  label = '交给 Trace Agent',
  size = 'small',
  variant = 'quiet',
  ...buttonProps
}: {
  handoff: TraceAgentHandoffInput;
  label?: string;
} & Omit<ButtonProps, 'children' | 'leadingIcon' | 'onClick'>) {
  const desktop = usePawOsDesktop();
  return (
    <Button
      {...buttonProps}
      leadingIcon={<Sparkles aria-hidden="true" size={14} />}
      onClick={() => openPawOsRoute(desktop, buildTraceAgentHandoffRoute({
        ...handoff,
        sourceRoute: handoff.sourceRoute || currentPawRoute(),
      }))}
      size={size}
      variant={variant}
    >
      {label}
    </Button>
  );
}

export function traceHandoffContextFromRoute(route: string): Pick<
  TraceAgentHandoffInput,
  'sessionId' | 'roomId' | 'traceId' | 'runId'
> {
  const [pathname, query = ''] = route.replace(/^#/u, '').split('?', 2);
  const params = new URLSearchParams(query);
  return {
    sessionId: pathname === '/agent' ? params.get('session') || undefined : undefined,
    roomId: pathname === '/rooms' ? params.get('room') || undefined : undefined,
    traceId: pathname === '/observability' ? params.get('traceId') || undefined : undefined,
    runId: pathname === '/observability' ? params.get('runId') || undefined : undefined,
  };
}

/**
 * Redact untrusted handoff text before it is rendered, put in a URL, or sent
 * to a diagnostic Agent.  Handoffs are navigation metadata, not a secure
 * transport for raw tool failures or credentials.
 */
export function redactTraceAgentText(value: unknown, limit = maxHandoffSummaryLength): string {
  let result = bounded(value, limit);
  if (!result) return '';
  result = result.replace(urlPattern, '[url redacted]');
  result = result.replace(sensitiveAssignmentPattern, '$1: [redacted]');
  result = result.replace(bearerPattern, '[redacted]');
  result = result.replace(windowsPathPattern, '[path redacted]');
  result = result.replace(posixPathPattern, '[path redacted]');
  return bounded(result, limit);
}

/** Keep only a short, safe first-line failure summary for URL/prompt handoffs. */
export function redactTraceAgentError(value: unknown): string {
  const raw = text(value);
  if (!raw) return '';
  const firstLine = raw.split(/\r?\n/u).map((line) => line.trim()).find(Boolean) ?? '';
  const safe = redactTraceAgentText(firstLine, maxHandoffErrorLength);
  if (!safe) return '';
  const hadOmittedDetails = raw !== firstLine || /(?:authorization|token|secret|password|credential|cookie|api[_-]?key|https?:\/\/|wss?:\/\/|[A-Z]:\\|\/(?:Users|Volumes|private|tmp|var|home|workspace)\/)/iu.test(raw);
  return bounded(
    hadOmittedDetails && !safe.includes('[redacted]') ? `${safe} [redacted]` : safe,
    maxHandoffErrorLength,
  );
}

/** Redact a typed reference while retaining a useful safe marker. */
export function redactTraceAgentRef(key: unknown, value: unknown): string {
  const field = normalizedFieldName(key);
  if (isSensitiveFieldName(field)) return '[redacted]';
  if (pathFieldNames.has(field) || field.endsWith('path') || field.endsWith('root')) return '[path redacted]';
  if (urlFieldNames.has(field) || field.endsWith('url')) return '[url redacted]';
  return redactTraceAgentText(value, maxHandoffRefLength);
}

/**
 * Keep only an internal PAW route and non-sensitive identity query params.
 * This preserves the back link without allowing a nested handoff, path, URL,
 * or credential to become a query-string leak.
 */
export function sanitizeTraceAgentSourceRoute(value: unknown): string {
  const raw = text(value);
  if (!raw) return '/';
  if (explicitSchemePattern.test(raw) || raw.startsWith('//')) return '/';
  try {
    const parsed = new URL(raw, 'http://paw.local');
    if (parsed.origin !== 'http://paw.local' && /^https?:/iu.test(raw)) return '/';
    const pathname = parsed.pathname.startsWith('/') ? bounded(parsed.pathname, 240) : '/';
    if (machinePathRoutePattern.test(pathname)) return '/';
    const params = new URLSearchParams();
    for (const [key, rawValue] of parsed.searchParams.entries()) {
      const field = normalizedFieldName(key);
      if (field === 'handoff' || isSensitiveFieldName(field) || pathFieldNames.has(field) || urlFieldNames.has(field)) continue;
      const safeValue = redactTraceAgentText(rawValue, 160);
      if (!safeValue || /\[(?:url|path|redacted)/u.test(safeValue)) continue;
      params.set(bounded(key, 64), safeValue);
    }
    const query = params.toString();
    return bounded(`${pathname}${query ? `?${query}` : ''}`, maxSourceRouteLength);
  } catch {
    return '/';
  }
}

function normalizeTraceAgentHandoff(input: TraceAgentHandoffInput): TraceAgentHandoff {
  const occurredAtMs = input.occurredAtMs && Number.isFinite(input.occurredAtMs)
    ? Math.max(0, Math.trunc(input.occurredAtMs))
    : Date.now();
  const sourceRoute = sanitizeTraceAgentSourceRoute(input.sourceRoute || currentPawRoute() || '/');
  const inferred = traceHandoffContextFromRoute(sourceRoute);
  const entityId = bounded(
    input.entityId
      || input.failureRef
      || input.traceId
      || input.runId
      || input.sessionId
      || input.roomId
      || sourceRoute
      || `${input.kind}:${occurredAtMs}`,
  );
  return {
    schemaVersion: TRACE_AGENT_HANDOFF_SCHEMA_VERSION,
    kind: input.kind,
    entityId: redactTraceAgentText(entityId, maxHandoffIdLength),
    title: redactTraceAgentText(input.title, maxHandoffTitleLength) || '待诊断问题',
    summary: redactTraceAgentText(input.summary, maxHandoffSummaryLength) || '原位置请求 Trace Agent 检查这条记录。',
    ...(input.error ? { error: redactTraceAgentError(input.error) } : {}),
    ...(input.sessionId || inferred.sessionId ? { sessionId: redactTraceAgentText(input.sessionId || inferred.sessionId, maxHandoffIdLength) } : {}),
    ...(input.roomId || inferred.roomId ? { roomId: redactTraceAgentText(input.roomId || inferred.roomId, maxHandoffIdLength) } : {}),
    ...(input.traceId || inferred.traceId ? { traceId: redactTraceAgentText(input.traceId || inferred.traceId, maxHandoffIdLength) } : {}),
    ...(input.runId || inferred.runId ? { runId: redactTraceAgentText(input.runId || inferred.runId, maxHandoffIdLength) } : {}),
    ...(input.failureRef ? { failureRef: redactTraceAgentText(input.failureRef, maxHandoffIdLength) } : {}),
    sourceRoute: sanitizeTraceAgentSourceRoute(sourceRoute),
    // A handoff can be copied into a URL and a diagnostic prompt.  Never put
    // machine-specific absolute roots in either channel.  A real writable
    // Session gets its roots from the canonical Session/Room record instead.
    workspaceRoots: [],
    refs: Object.fromEntries(
      Object.entries(input.refs ?? {})
        .filter(([, value]) => value !== null && value !== undefined)
        .slice(0, 12)
        .map(([key, value]) => [bounded(key, 120), redactTraceAgentRef(key, value)]),
    ),
    occurredAtMs,
  };
}

function compactTraceAgentHandoff(handoff: TraceAgentHandoff): TraceAgentHandoff {
  if (JSON.stringify(handoff).length <= maxHandoffJsonLength) return handoff;
  const refs = Object.fromEntries(Object.entries(handoff.refs).slice(0, 6));
  return {
    ...handoff,
    error: handoff.error ? redactTraceAgentError(handoff.error).slice(0, 240) : undefined,
    refs,
  };
}

function currentPawRoute(): string {
  if (typeof window === 'undefined') return '/';
  const hash = window.location.hash.replace(/^#/u, '');
  if (hash) return hash;
  return `${window.location.pathname}${window.location.search}` || '/';
}

function bounded(value: unknown, limit = maxTextLength): string {
  return text(value).slice(0, limit);
}

function normalizedFieldName(value: unknown): string {
  return text(value).toLowerCase().replace(/[^a-z0-9]/gu, '');
}

function isSensitiveFieldName(field: string): boolean {
  return sensitiveFieldNames.has(field)
    || field.includes('authorization')
    || field.includes('password')
    || field.includes('credential')
    || field.includes('cookie')
    || field.endsWith('token')
    || field.endsWith('secret')
    || field.endsWith('apikey')
    || field.endsWith('accesskey')
    || field.endsWith('privatekey')
    || field.endsWith('secretkey')
    || field.endsWith('auth');
}

function text(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

function finiteNumber(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : [];
}

function stringRecord(value: unknown): Record<string, string> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {};
  return Object.fromEntries(Object.entries(value).filter((entry): entry is [string, string] => (
    typeof entry[1] === 'string'
  )));
}
