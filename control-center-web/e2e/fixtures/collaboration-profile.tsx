import { createRoot } from 'react-dom/client';
import { ControlTransportProvider } from '../../src/app/control-transport';
import { CollaborationProfileGovernancePanel } from '../../src/features/roles/CollaborationProfileGovernancePanel';
import { MockControlTransport } from '../../src/test/mock-transport';
import '../../src/design/tokens.css';
import '../../src/design/typography.css';
import '../../src/components/primitives/primitives.css';
import '../../src/features/roles/roles.css';

const profileId = 'evidence-review';
const routeHash = 'sha256:53186f4ad0acfd089d4215b79ff3ffa535f12be751f42fd95b9a388059907e13';
const transport = new MockControlTransport({
  capabilities: {
    routeIds: ['agent.collaborationProfile.get', 'agent.collaborationProfile.command'],
    raw: {
      client: { remote: true, deviceAuthenticated: true, grantedScopes: ['agent.read', 'agent.write', 'agent.approve'] },
      routes: [
        { pathId: 'agent.collaborationProfile.get', method: 'GET', remoteSafe: true, subscription: false, params: ['profileId'], query: [], remoteScopes: ['agent.read'] },
        { pathId: 'agent.collaborationProfile.command', method: 'POST', remoteSafe: true, subscription: false, params: [], query: [], remoteScopes: ['agent.write', 'agent.approve'] },
      ],
    },
  },
  routes: {
    'agent.collaborationProfile.get': {
      schemaVersion: 'rag-ime.collaboration-profile-projection.v1', profileId, routeHash,
      requiredReadScopes: ['agent.read'], requiredWriteScopes: ['agent.write', 'agent.approve'], guardEpoch: 7, normalAgentFallback: true,
      inspection: {
        schemaVersion: 'rag-ime.collaboration-profile-inspection.v1', profileId, pointerRevision: 12,
        active: { profileId, version: '9', contentHash: `sha256:${'a'.repeat(64)}`, pointerRevision: 12, compileReceiptId: 'profile-compile:aaaaaaaaaaaaaaaaaaaaaaaa', bindingRevision: 'binding-long-revision-2026-07-20' },
        versions: [{
          contentHash: `sha256:${'a'.repeat(64)}`, version: '9', compileReceiptId: 'profile-compile:aaaaaaaaaaaaaaaaaaaaaaaa',
          revoked: false, revokeReason: '', stagedAtMs: 1,
          manifest: {
            schemaVersion: 'rag-ime.collaboration-profile.v1', profileId, version: '9', displayName: '证据研究与独立复核',
            summary: '这是一个用于移动端长文本验证的正式 CollaborationProfile 投影。', collaborationRoleRefs: ['researcher@1', 'reviewer@1'],
            capabilityRequests: ['rag', 'review', 'control'], requiredGateIds: ['evidence-required'],
            promptGuidance: ['先核对原始需求、证据来源和验收标准，再独立复核。'.repeat(8), '不能用 Agent 自述代替类型化回执。'], trustTier: 'signed',
          },
        }],
      },
      recentReceipts: [],
    },
  },
});

createRoot(document.getElementById('root')!).render(
  <ControlTransportProvider transport={transport}>
    <div className="profile-fixture role-inspector"><CollaborationProfileGovernancePanel profileId={profileId} /></div>
  </ControlTransportProvider>,
);
