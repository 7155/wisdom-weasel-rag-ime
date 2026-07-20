import { describe, expect, it } from 'vitest';
import type { FrontendCapabilities } from '@/platform/transport';
import { evaluateCollaborationProfileControlGate } from './collaboration-profile-control-gate';

const PROFILE_ROUTE_HASH = 'sha256:53186f4ad0acfd089d4215b79ff3ffa535f12be751f42fd95b9a388059907e13';

describe('CollaborationProfile production control gate', () => {
  it('requires exact routes, the backend descriptor hash and both write scopes', async () => {
    const gate = await evaluateCollaborationProfileControlGate(capabilities(), PROFILE_ROUTE_HASH);
    expect(gate).toMatchObject({ readEnabled: true, commandEnabled: true, expectedProfileRouteHash: PROFILE_ROUTE_HASH });
  });

  it('fails closed for a changed route, stale projection hash or missing remote approval', async () => {
    const changed = capabilities();
    (changed.raw as { routes: Array<Record<string, unknown>> }).routes[1]!.method = 'PATCH';
    expect((await evaluateCollaborationProfileControlGate(changed, PROFILE_ROUTE_HASH)).reason).toMatch(/command route hash mismatch/);
    expect((await evaluateCollaborationProfileControlGate(capabilities(), `sha256:${'0'.repeat(64)}`)).reason).toMatch(/projection route hash mismatch/);
    const remote = capabilities();
    (remote.raw as { client: Record<string, unknown> }).client = { remote: true, deviceAuthenticated: true, grantedScopes: ['agent.write'] };
    expect((await evaluateCollaborationProfileControlGate(remote, PROFILE_ROUTE_HASH)).reason).toMatch(/agent.write and agent.approve/);
  });
});

function capabilities(): FrontendCapabilities {
  return {
    schemaVersion: 'rag-ime.control-capabilities.v1', transport: 'http',
    routeIds: ['agent.collaborationProfile.get', 'agent.collaborationProfile.command'], features: {},
    native: { pickFiles: false, managedAgentImageImport: false, revealPath: false, approvedExternalActions: false, keychain: false, tcc: false },
    raw: {
      client: { remote: false, deviceAuthenticated: false, grantedScopes: [] },
      routes: [
        { pathId: 'agent.collaborationProfile.get', method: 'GET', remoteSafe: true, subscription: false, params: ['profileId'], query: [], remoteScopes: ['agent.read'] },
        { pathId: 'agent.collaborationProfile.command', method: 'POST', remoteSafe: true, subscription: false, params: [], query: [], remoteScopes: ['agent.write', 'agent.approve'] },
      ],
    },
  };
}
