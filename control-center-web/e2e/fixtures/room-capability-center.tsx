import { createRoot } from 'react-dom/client';
import { createRoomKernelProjection } from '../../src/contracts/room-kernel-reducer';
import { CapabilityCenter } from '../../src/features/rooms/capabilities/CapabilityCenter';
import { capabilityCenterFixture } from '../../src/features/rooms/capabilities/capability-center-fixtures';
import { ParticipantBindingInspector } from '../../src/features/rooms/capabilities/ParticipantBindingInspector';
import { RoomExecutionTopology } from '../../src/features/rooms/capabilities/RoomExecutionTopology';
import { RoomKernelControlPlane } from '../../src/features/rooms/kernel/RoomKernelControlPlane';
import '../../src/design/tokens.css';
import '../../src/design/typography.css';
import '../../src/components/primitives/primitives.css';

const fixture = capabilityCenterFixture();
const kernel = createRoomKernelProjection('room-kernel-qa');
kernel.lastSequence = 218;
kernel.rootsById['root-research'] = { rootId: 'root-research', generation: 3, state: 'running', ownerParticipantId: 'researcher', isFinal: false, updatedAtMs: 218 };
kernel.rootsById['root-review'] = { rootId: 'root-review', generation: 1, state: 'waiting', ownerParticipantId: 'reviewer', isFinal: false, updatedAtMs: 217 };
kernel.runtimeByRootId['root-research'] = { generation: 3, stopRequest: null };
kernel.runtimeByRootId['root-review'] = { generation: 1, stopRequest: null };
kernel.postOrder.push('post-research', 'post-review');
kernel.postsById['post-research'] = {
  postId: 'post-research', roomId: kernel.roomId, rootId: 'root-research', sequence: 215,
  authorParticipantId: 'researcher', kind: 'finding', visibility: 'room',
  content: '这是一条经过显式提交的公开 Post。私有 Session 的推理、工具调用细节和中间草稿不会自动进入 Room。', createdAtMs: 215,
};
kernel.postsById['post-review'] = {
  postId: 'post-review', roomId: kernel.roomId, rootId: 'root-review', sequence: 216,
  authorParticipantId: 'reviewer', kind: 'question', visibility: 'room',
  content: '等待独立复核，不把另一个 Root 的完成状态当作自己的终态。', createdAtMs: 216,
};
kernel.sessionsById['session-room-research'] = { sessionId: 'session-room-research', rootId: 'root-research', generation: 3, state: 'running', updatedAtMs: 218 };
kernel.sessionsById['session-reviewer'] = { sessionId: 'session-reviewer', rootId: 'root-review', generation: 1, state: 'queued', updatedAtMs: 217 };

createRoot(document.getElementById('root')!).render(<>
  <div className="qa-band"><RoomExecutionTopology
    roots={Object.values(kernel.rootsById)}
    tasksByRootId={fixture.tasksByRootId}
    dispatchesByRootId={fixture.dispatchesByRootId}
  /></div>
  <div className="qa-band"><RoomKernelControlPlane
    projection={kernel}
    budgetsByRootId={{
      'root-research': { maxDispatches: 8, usedDispatches: 3, maxTokens: 64_000, usedTokens: 28_000, maxWallTimeMs: 600_000, elapsedMs: 190_000 },
      'root-review': { maxDispatches: 4, usedDispatches: 1, maxTokens: 32_000, usedTokens: 8_000, maxWallTimeMs: 300_000, elapsedMs: 70_000 },
    }}
    contextReceiptsByRootId={{ 'root-research': { revision: 'context-r12', status: 'sealed', contentHash: `sha256:${'3'.repeat(64)}` } }}
    capabilityReceiptsByRootId={{ 'root-research': { revision: 'capability-r4', status: 'sealed', contentHash: `sha256:${'4'.repeat(64)}` } }}
  /></div>
  <div className="qa-inspectors">
    <CapabilityCenter projection={fixture.projection} sessionId="session-room-research" />
    <ParticipantBindingInspector binding={fixture.projection.bindingsBySessionId['session-room-research']!} />
  </div>
</>);
