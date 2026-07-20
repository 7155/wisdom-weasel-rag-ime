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

export type CollaborationProfileControlGate = {
  readEnabled: boolean;
  commandEnabled: boolean;
  reason: string;
  expectedProfileRouteHash: string;
  profileRouteHash: string;
};

const EXPECTED_GET: RouteManifest = {
  pathId: 'agent.collaborationProfile.get', method: 'GET', remoteSafe: true,
  subscription: false, params: ['profileId'], query: [], remoteScopes: ['agent.read'],
};

const EXPECTED_COMMAND: RouteManifest = {
  pathId: 'agent.collaborationProfile.command', method: 'POST', remoteSafe: true,
  subscription: false, params: [], query: [], remoteScopes: ['agent.approve', 'agent.write'],
};

const PROFILE_ROUTE_DESCRIPTOR = '{"command":{"method":"POST","path":"/api/agent/collaboration-profiles/commands","scopes":["agent.write","agent.approve"]},"projection":{"method":"GET","path":"/api/agent/collaboration-profiles/{profileId}","scopes":["agent.read"]}}';

export async function evaluateCollaborationProfileControlGate(
  capabilities: FrontendCapabilities,
  projectionRouteHash = '',
): Promise<CollaborationProfileControlGate> {
  const raw = record(capabilities.raw);
  const routes = array(raw.routes).map(normalizeRoute).filter((route): route is RouteManifest => Boolean(route));
  const get = routes.find((route) => route.pathId === EXPECTED_GET.pathId);
  const command = routes.find((route) => route.pathId === EXPECTED_COMMAND.pathId);
  const getMatches = get ? await routeHash(get) === await routeHash(EXPECTED_GET) : false;
  const commandMatches = command ? await routeHash(command) === await routeHash(EXPECTED_COMMAND) : false;
  const expectedProfileRouteHash = await sha256(PROFILE_ROUTE_DESCRIPTOR);
  const profileHashMatches = projectionRouteHash === '' || projectionRouteHash === expectedProfileRouteHash;
  const client = record(raw.client);
  const remote = client.remote === true;
  const scopes = new Set(strings(client.grantedScopes));
  const remoteAuthorized = !remote || (
    client.deviceAuthenticated === true
    && scopes.has('agent.write')
    && scopes.has('agent.approve')
  );
  const readEnabled = getMatches && capabilities.routeIds.includes('agent.collaborationProfile.get');
  const commandEnabled = readEnabled
    && commandMatches
    && profileHashMatches
    && remoteAuthorized
    && capabilities.routeIds.includes('agent.collaborationProfile.command');
  return {
    readEnabled,
    commandEnabled,
    expectedProfileRouteHash,
    profileRouteHash: projectionRouteHash,
    reason: commandEnabled
      ? 'canonical routes, Profile route hash and authorization verified'
      : !readEnabled
        ? 'CollaborationProfile read route is unavailable or changed'
        : !commandMatches
          ? 'CollaborationProfile command route hash mismatch'
          : !profileHashMatches
            ? 'CollaborationProfile projection route hash mismatch'
            : !remoteAuthorized
              ? 'remote caller requires authentication plus agent.write and agent.approve'
              : 'CollaborationProfile command capability is not advertised',
  };
}

async function routeHash(value: RouteManifest): Promise<string> {
  return sha256(JSON.stringify({
    pathId: value.pathId,
    method: value.method,
    remoteSafe: value.remoteSafe,
    subscription: value.subscription,
    params: [...value.params].sort(),
    query: [...value.query].sort(),
    remoteScopes: [...value.remoteScopes].sort(),
  }));
}

async function sha256(value: string): Promise<string> {
  if (!globalThis.crypto?.subtle) return '';
  const digest = await globalThis.crypto.subtle.digest('SHA-256', new TextEncoder().encode(value));
  return `sha256:${Array.from(new Uint8Array(digest), (item) => item.toString(16).padStart(2, '0')).join('')}`;
}

function normalizeRoute(value: unknown): RouteManifest | null {
  const item = record(value);
  if (typeof item.pathId !== 'string' || typeof item.method !== 'string') return null;
  return {
    pathId: item.pathId, method: item.method, remoteSafe: item.remoteSafe === true,
    subscription: item.subscription === true, params: strings(item.params), query: strings(item.query),
    remoteScopes: strings(item.remoteScopes),
  };
}

function strings(value: unknown): string[] { return array(value).filter((item): item is string => typeof item === 'string').sort(); }
function array(value: unknown): unknown[] { return Array.isArray(value) ? value : []; }
function record(value: unknown): Record<string, unknown> { return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : {}; }
