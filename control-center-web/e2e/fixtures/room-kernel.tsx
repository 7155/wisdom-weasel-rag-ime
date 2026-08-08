import { createRoot } from 'react-dom/client';
import { createRoomKernelProjection } from '../../src/contracts/room-kernel-reducer';
import { RoomKernelControlPlane } from '../../src/features/rooms/kernel/RoomKernelControlPlane';
import { createFixtureRoomKernelCommandTransport } from '../../src/features/rooms/kernel/room-kernel-command-transport';
import { parseRoomRequirementsReadProjection } from '../../src/features/rooms/requirements/room-requirements-read-model';
import '../../src/design/tokens.css';
import '../../src/design/typography.css';
import '../../src/components/primitives/primitives.css';

const projection = createRoomKernelProjection('room-kernel-qa');
projection.lastSequence = 218;
projection.rootsById['root-research-2026-07-19-with-a-deliberately-long-identifier'] = {
  schemaVersion: 'wisdom-weasel.room-root-execution.v3',
  rootId: 'root-research-2026-07-19-with-a-deliberately-long-identifier',
  roomId: projection.roomId,
  generation: 3,
  state: 'completed',
  facilitatorParticipantId: '证据审查员与知识治理负责人',
  reporterParticipantId: null,
  reporterSelectionReceiptId: null,
  requirementAnchorRef: 'requirement:research',
  createdByActorRef: 'user:fixture',
  terminalReceiptId: null,
  activeProfileRef: null,
  budgetPolicyRef: 'budget:fixture',
  independentReviewRequired: false,
  createdAtMs: 1,
  isFinal: false,
  updatedAtMs: 218,
};
projection.rootsById['root-implementation'] = {
  schemaVersion: 'wisdom-weasel.room-root-execution.v3', rootId: 'root-implementation', roomId: projection.roomId,
  generation: 1, state: 'running', facilitatorParticipantId: '实现者',
  reporterParticipantId: null, reporterSelectionReceiptId: null,
  requirementAnchorRef: 'requirement:implementation',
  createdByActorRef: 'user:fixture', terminalReceiptId: null, activeProfileRef: null,
  budgetPolicyRef: 'budget:fixture', independentReviewRequired: false,
  createdAtMs: 2, isFinal: false, updatedAtMs: 217,
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
  taskId: null, taskKind: null, workItemId: null, dispatchId: null,
  generation: 3, state: 'completed', updatedAtMs: 215,
};
projection.sessionsById['session-private-implementation'] = {
  sessionId: 'session-private-implementation', rootId: 'root-implementation',
  taskId: null, taskKind: null, workItemId: null, dispatchId: null,
  generation: 1, state: 'running', updatedAtMs: 218,
};

const requirementRootId = 'root-research-2026-07-19-with-a-deliberately-long-identifier';
const requirementProjection = parseRoomRequirementsReadProjection({
  projectionSource: 'canonical_fixture', rootId: requirementRootId,
  anchors: [{
    anchor: {
      schemaVersion: 'wisdom-weasel.requirement-anchor.v1', anchorId: 'anchor-research', rootId: requirementRootId,
      rootSequence: 1, originalContentSha256: 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad',
      originalByteLength: 3, createdBy: 'user:fixture', authenticity: 'original_user_bytes',
      provenance: { requestId: 'fixture-request' }, createdAtMs: 1,
    },
    originalText: 'abc', integrityStatus: 'verified',
  }],
  catalog: {
    schemaVersion: 'wisdom-weasel.requirement-catalog-revision.v1', catalogRevisionId: 'catalog-research-r2',
    rootId: requirementRootId, revision: 2, supersedesRevisionId: 'catalog-research-r1', anchorRefs: ['anchor-research'],
    items: [{ itemId: 'requirement-original', statement: '原始需求永久保留', kind: 'explicit_user_requirement', state: 'active' }],
    acceptanceCriteria: [{ criterionId: 'criterion-original', itemId: 'requirement-original', acceptanceCriterionFullNameZh: '原始需求永久保留验收标准', criterionKind: 'user_journey', expectedReceiptTypes: ['test'], statement: '原始字节哈希一致且界面只读' }],
    changeReason: '补充用户旅程验收', provenance: { source: 'canonical-fixture' }, payloadHash: 'c'.repeat(64),
    createdBy: 'requirements-governor', createdAtMs: 2,
  },
  receiptAssessments: [{ receipt: {
    schemaVersion: 'wisdom-weasel.typed-verification-receipt.v1', receiptId: 'receipt-research-test', rootId: requirementRootId,
    catalogRevisionId: 'catalog-research-r2', receiptType: 'test', sourceCommit: 'commit-current', environment: 'managed-ci',
    commandOrAction: 'pnpm test', exitStatus: 0, outputHash: 'd'.repeat(64), artifactHash: 'e'.repeat(64),
    verifier: 'managed-test-runner', createdAtMs: 3,
  }, status: 'observed_pass', reasons: [] }],
  deliveryGate: {
    schemaVersion: 'wisdom-weasel.delivery-gate-observation.v1', gateReceiptId: 'gate-research', rootId: requirementRootId,
    catalogRevisionId: 'catalog-research-r2', targetCommit: 'commit-current', mode: 'observe_warn', gateStatus: 'warn_blocked',
    enforcementApplied: false, blindReviewStatus: 'pending', reasons: ['unresolved_unknown', 'blind_review_not_passed'],
    proofMatrix: [{ criterionId: 'criterion-original', criterionKind: 'user_journey', passed: true, receiptIds: ['receipt-research-test'] }], createdAtMs: 4,
  },
  conflicts: [{ conflictId: 'conflict-research', leftItemId: 'requirement-original', rightItemId: 'requirement-derived', conflictKind: 'unknown', status: 'open', resolution: '' }],
  peerReviewRounds: [{ roundId: 'peer-round-research', reviewerActorRefs: ['peer-reviewer'], verdicts: [], status: 'pending', receiptRef: null, conflictMatrixRevisionId: null }],
});

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
  requirementsByRootId={{ [requirementRootId]: requirementProjection }}
  commandTransport={createFixtureRoomKernelCommandTransport((command) => {
    document.body.dataset.lastStop = JSON.stringify(command);
    return {
      schemaVersion: 'wisdom-weasel.room-kernel-receipt.v1', receiptId: `fixture:${command.commandId}`,
      rootId: command.rootId, commandId: command.commandId, receiptKind: 'root_cancelled', status: 'applied',
      generation: command.generation + 1, details: {}, createdAtMs: Date.now(),
    };
  })}
/>);
