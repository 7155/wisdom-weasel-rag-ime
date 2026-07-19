import { createRoot } from 'react-dom/client';
import { createRoomKernelProjection } from '../../src/contracts/room-kernel-reducer';
import { RoomKernelControlPlane } from '../../src/features/rooms/kernel/RoomKernelControlPlane';
import { createFixtureRoomKernelCommandTransport } from '../../src/features/rooms/kernel/room-kernel-command-transport';
import '../../src/design/tokens.css';
import '../../src/design/typography.css';
import '../../src/components/primitives/primitives.css';

const projection = createRoomKernelProjection('room-kernel-qa');
projection.lastSequence = 218;
projection.rootsById['root-research-2026-07-19-with-a-deliberately-long-identifier'] = {
  schemaVersion: 'wisdom-weasel.room-root-execution.v2',
  rootId: 'root-research-2026-07-19-with-a-deliberately-long-identifier',
  roomId: projection.roomId,
  generation: 3,
  state: 'completed',
  owner: '证据审查员与知识治理负责人',
  requirementAnchorRef: 'requirement:research',
  createdByActorRef: 'user:fixture',
  terminalReceiptId: null,
  activeProfileRef: null,
  budgetPolicyRef: 'budget:fixture',
  createdAtMs: 1,
  isFinal: false,
  updatedAtMs: 218,
};
projection.rootsById['root-implementation'] = {
  schemaVersion: 'wisdom-weasel.room-root-execution.v2', rootId: 'root-implementation', roomId: projection.roomId,
  generation: 1, state: 'running', owner: '实现者', requirementAnchorRef: 'requirement:implementation',
  createdByActorRef: 'user:fixture', terminalReceiptId: null, activeProfileRef: null,
  budgetPolicyRef: 'budget:fixture', createdAtMs: 2, isFinal: false, updatedAtMs: 217,
};
projection.postOrder.push('post-finding', 'post-decision');
projection.postsById['post-finding'] = {
  schemaVersion: 'wisdom-weasel.room-post.v2', postId: 'post-finding', roomId: projection.roomId,
  rootId: 'root-research-2026-07-19-with-a-deliberately-long-identifier',
  generation: 3, authorActorRef: '证据审查员', kind: 'finding', visibility: 'room',
  content: '这是经过显式提交才进入 Room 的研究发现。Session 内部的推理、工具日志和自言自语不会混入公开上下文。',
  idempotencyKey: 'post:finding', publicationSource: { kind: 'room_commit', ref: 'commit:finding' }, createdAtMs: 216,
};
projection.postsById['post-decision'] = {
  schemaVersion: 'wisdom-weasel.room-post.v2', postId: 'post-decision', roomId: projection.roomId, rootId: 'root-implementation',
  generation: 1, authorActorRef: '实现者', kind: 'decision', visibility: 'room',
  content: '保持 Root 级停止入口可达，并等待全链静止后的终态回执。', idempotencyKey: 'post:decision',
  publicationSource: { kind: 'room_commit', ref: 'commit:decision' }, createdAtMs: 217,
};
projection.sessionsById['session-private-research-with-long-id'] = {
  sessionId: 'session-private-research-with-long-id',
  rootId: 'root-research-2026-07-19-with-a-deliberately-long-identifier',
  generation: 3, state: 'completed', updatedAtMs: 215,
};
projection.sessionsById['session-private-implementation'] = {
  sessionId: 'session-private-implementation', rootId: 'root-implementation',
  generation: 1, state: 'running', updatedAtMs: 218,
};

createRoot(document.getElementById('root')!).render(<RoomKernelControlPlane
  projection={projection}
  budgetsByRootId={{
    'root-research-2026-07-19-with-a-deliberately-long-identifier': {
      maxDispatches: 12, usedDispatches: 9, maxTokens: 128_000, usedTokens: 82_500,
      maxWallTimeMs: 900_000, elapsedMs: 612_000,
    },
    'root-implementation': {
      maxDispatches: 8, usedDispatches: 3, maxTokens: 64_000, usedTokens: 17_200,
      maxWallTimeMs: 600_000, elapsedMs: 183_000,
    },
  }}
  contextReceiptsByRootId={{
    'root-research-2026-07-19-with-a-deliberately-long-identifier': {
      revision: 'context-revision-17', status: 'sealed', contentHash: `sha256:${'a'.repeat(64)}`,
    },
  }}
  capabilityReceiptsByRootId={{
    'root-research-2026-07-19-with-a-deliberately-long-identifier': {
      revision: 'capability-revision-9', status: 'sealed', contentHash: `sha256:${'b'.repeat(64)}`,
    },
  }}
  commandTransport={createFixtureRoomKernelCommandTransport((command) => {
    document.body.dataset.lastStop = JSON.stringify(command);
    return {
      schemaVersion: 'wisdom-weasel.room-kernel-receipt.v1', receiptId: `fixture:${command.commandId}`,
      rootId: command.rootId, commandId: command.commandId, receiptKind: 'root_cancelled', status: 'applied',
      generation: command.generation + 1, details: {}, createdAtMs: Date.now(),
    };
  })}
/>);
