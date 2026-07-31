import type { FrontendCapabilities } from '@/platform/transport';

type RouteManifest = {
  pathId: string;
  method: string;
  remoteSafe: boolean;
  subscription: boolean;
  params: string[];
  query: string[];
  remoteScopes: string[];
};

export type RoomKernelControlGate = {
  readEnabled: boolean;
  commandEnabled: boolean;
  panicEnabled: boolean;
  reason: string;
  expectedCommandRouteHash: string;
  commandRouteHash: string;
};

const EXPECTED_COMMAND_ROUTE: RouteManifest = {
  pathId: 'agent.room.kernel.command',
  method: 'POST',
  remoteSafe: true,
  subscription: false,
  params: ['roomId'],
  query: [],
  remoteScopes: ['agent.write'],
};

const EXPECTED_SNAPSHOT_ROUTE: RouteManifest = {
  pathId: 'agent.room.kernel.snapshot',
  method: 'GET',
  remoteSafe: true,
  subscription: false,
  params: ['roomId'],
  query: [],
  remoteScopes: ['agent.read'],
};

const EXPECTED_EVENTS_ROUTE: RouteManifest = {
  pathId: 'agent.room.kernel.events',
  method: 'GET',
  remoteSafe: true,
  subscription: true,
  params: ['roomId'],
  query: ['lastEventId'],
  remoteScopes: ['agent.read'],
};

export async function evaluateRoomKernelControlGate(
  capabilities: FrontendCapabilities,
): Promise<RoomKernelControlGate> {
  const raw = record(capabilities.raw);
  const routes = array(raw.routes).map(normalizeRoute).filter((item): item is RouteManifest => Boolean(item));
  const command = routes.find((route) => route.pathId === EXPECTED_COMMAND_ROUTE.pathId);
  const snapshot = routes.find((route) => route.pathId === EXPECTED_SNAPSHOT_ROUTE.pathId);
  const events = routes.find((route) => route.pathId === EXPECTED_EVENTS_ROUTE.pathId);
  const expectedCommandRouteHash = await routeHash(EXPECTED_COMMAND_ROUTE);
  const commandRouteHash = command ? await routeHash(command) : '';
  const routeIds = new Set<string>(capabilities.routeIds);
  const nativePolicy = capabilities.transport === 'native';
  const readEnabled = nativePolicy
    ? routeIds.has(EXPECTED_SNAPSHOT_ROUTE.pathId)
      && routeIds.has(EXPECTED_EVENTS_ROUTE.pathId)
    : routeMatches(snapshot, EXPECTED_SNAPSHOT_ROUTE)
      && routeMatches(events, EXPECTED_EVENTS_ROUTE);
  const commandRouteVerified = nativePolicy
    ? routeIds.has(EXPECTED_COMMAND_ROUTE.pathId)
    : routeMatches(command, EXPECTED_COMMAND_ROUTE);
  const client = record(raw.client);
  const remote = client.remote === true;
  const scopes = new Set(array(client.grantedScopes).filter((item): item is string => typeof item === 'string'));
  const authorized = !remote || (client.deviceAuthenticated === true && scopes.has('agent.write'));
  const commandEnabled = readEnabled
    && commandRouteVerified
    && authorized
    && routeIds.has(EXPECTED_COMMAND_ROUTE.pathId);
  const features = record(raw.features);
  const panicEnabled = commandEnabled
    && features.roomKernelPanic === true
    && scopes.has('agent.admin');
  return {
    readEnabled,
    commandEnabled,
    panicEnabled,
    expectedCommandRouteHash,
    commandRouteHash,
    reason: commandEnabled
      ? '任务控制已连接'
      : !readEnabled
        ? '任务进度暂时不可用，请刷新后重试。已有对话和工作文件不会受影响。'
        : !authorized
          ? '当前连接可以查看任务，但没有停止任务的权限'
          : !commandRouteVerified && !nativePolicy
            ? '停止任务的控制通道已发生变化，请刷新或更新应用'
            : '当前连接暂不支持停止任务',
  };
}

function routeMatches(
  actual: RouteManifest | undefined,
  expected: RouteManifest,
): boolean {
  return actual !== undefined
    && JSON.stringify(canonicalRoute(actual)) === JSON.stringify(canonicalRoute(expected));
}

function canonicalRoute(route: RouteManifest): RouteManifest {
  return {
    pathId: route.pathId,
    method: route.method,
    remoteSafe: route.remoteSafe,
    subscription: route.subscription,
    params: [...route.params].sort(),
    query: [...route.query].sort(),
    remoteScopes: [...route.remoteScopes].sort(),
  };
}

async function routeHash(route: RouteManifest): Promise<string> {
  const bytes = new TextEncoder().encode(JSON.stringify(route));
  if (!globalThis.crypto?.subtle) return '';
  const digest = await globalThis.crypto.subtle.digest('SHA-256', bytes);
  return `sha256:${Array.from(new Uint8Array(digest), (value) => value.toString(16).padStart(2, '0')).join('')}`;
}

function normalizeRoute(value: unknown): RouteManifest | null {
  const item = record(value);
  if (typeof item.pathId !== 'string' || typeof item.method !== 'string') return null;
  return {
    pathId: item.pathId,
    method: item.method,
    remoteSafe: item.remoteSafe === true,
    subscription: item.subscription === true,
    params: strings(item.params),
    query: strings(item.query),
    remoteScopes: strings(item.remoteScopes),
  };
}

function strings(value: unknown): string[] {
  return array(value).filter((item): item is string => typeof item === 'string').sort();
}

function array(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function record(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : {};
}
