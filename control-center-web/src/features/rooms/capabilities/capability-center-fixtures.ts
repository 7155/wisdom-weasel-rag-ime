import type {
  CapabilityCenterProjection,
  CapabilityProjection,
  ParticipantBindingProjection,
  RuntimeRevisionReferenceProjection,
} from '@/contracts/capability-center-reducer';
import { createCapabilityCenterProjection } from '@/contracts/capability-center-reducer';

export type RoomTaskProjectionFixture = {
  taskId: string;
  rootId: string;
  generation: number;
  title: string;
  state: 'queued' | 'running' | 'waiting' | 'completed' | 'failed' | 'cancelled';
  ownerParticipantId: string | null;
  receiptId: string;
};

export type RoomDispatchProjectionFixture = {
  dispatchId: string;
  rootId: string;
  taskId: string;
  generation: number;
  attempt: number;
  targetSessionId: string;
  state: 'queued' | 'running' | 'settled' | 'failed' | 'cancelled';
  receiptId: string;
};

export function capabilityCenterFixture(): {
  projection: CapabilityCenterProjection;
  tasksByRootId: Record<string, RoomTaskProjectionFixture[]>;
  dispatchesByRootId: Record<string, RoomDispatchProjectionFixture[]>;
} {
  const projection = createCapabilityCenterProjection('room-kernel-qa');
  projection.lastSequence = 218;
  projection.snapshotHash = `sha256:${'f'.repeat(64)}`;
  const roomBinding = participantBinding('session-room-research', 3, {
    schemaVersion: 'wisdom-weasel.room-binding.v2', bindingId: 'room-binding-a',
  });
  const ordinaryBinding = participantBinding('session-ordinary', 1, null);
  projection.bindingsBySessionId[roomBinding.sessionId] = roomBinding;
  projection.bindingsBySessionId[ordinaryBinding.sessionId] = ordinaryBinding;
  projection.capabilitiesBySessionId[roomBinding.sessionId] = {
    'rag.read': capability({
      capabilityId: 'rag.read', displayName: '知识检索', generation: 3, sessionId: roomBinding.sessionId,
      summary: '读取经过授权的知识资料。很长的资料名称、工具标识和回执必须在窄屏完整换行，不能挤压状态列。',
      states: { available: true, authorized: true, disclosed: true, loaded: true, invoked: true, revoked: false },
      narrowedBy: [
        { layer: 'authorization', decision: 'allowed', reason: '用户授权只读知识检索', receiptId: 'authorization-receipt-17' },
        { layer: 'collaboration-profile', decision: 'removed', reason: '角色书移除 control，只保留研究所需的 read', receiptId: 'compile-receipt-4' },
      ],
    }),
    'memory.write': capability({
      capabilityId: 'memory.write', displayName: '长期记忆写入', generation: 3, sessionId: roomBinding.sessionId,
      summary: '该能力存在于 manifest，但未被当前授权和角色书保留。',
      states: { available: true, authorized: false, disclosed: false, loaded: false, invoked: false, revoked: true },
      narrowedBy: [
        { layer: 'authorization', decision: 'removed', reason: '当前任务没有长期写入授权', receiptId: 'authorization-receipt-18' },
        { layer: 'revocation', decision: 'removed', reason: 'capability epoch 4 已撤销旧写入票据', receiptId: 'revocation-receipt-9' },
      ],
    }),
  };
  projection.capabilitiesBySessionId[ordinaryBinding.sessionId] = {
    'rag.read': capability({
      capabilityId: 'rag.read', displayName: '知识检索', generation: 1, sessionId: ordinaryBinding.sessionId,
      summary: '普通 Agent 的独立检索能力。',
      states: { available: true, authorized: true, disclosed: true, loaded: false, invoked: false, revoked: false },
      narrowedBy: [{ layer: 'agent-template', decision: 'allowed', reason: '普通助手模板保留只读检索', receiptId: 'template-receipt-2' }],
    }),
  };
  return {
    projection,
    tasksByRootId: {
      'root-research': [{
        taskId: 'task-verify-room-routing-and-capability-receipts', rootId: 'root-research', generation: 3,
        title: '核对 Room 路由和能力回执，保持原始需求与验证证据可追溯', state: 'running',
        ownerParticipantId: 'participant-session-room-research', receiptId: 'task-receipt-31',
      }],
      'root-review': [{
        taskId: 'task-independent-review', rootId: 'root-review', generation: 1,
        title: '独立审查交付物', state: 'waiting', ownerParticipantId: 'participant-reviewer', receiptId: 'task-receipt-32',
      }],
    },
    dispatchesByRootId: {
      'root-research': [{
        dispatchId: 'dispatch-research-attempt-2', rootId: 'root-research',
        taskId: 'task-verify-room-routing-and-capability-receipts', generation: 3, attempt: 2,
        targetSessionId: roomBinding.sessionId, state: 'running', receiptId: 'dispatch-receipt-71',
      }],
      'root-review': [{
        dispatchId: 'dispatch-review-attempt-1', rootId: 'root-review', taskId: 'task-independent-review',
        generation: 1, attempt: 1, targetSessionId: 'session-reviewer', state: 'queued', receiptId: 'dispatch-receipt-72',
      }],
    },
  };
}

function participantBinding(
  sessionId: string,
  generation: number,
  roomBindingRef: ParticipantBindingProjection['roomBindingRef'],
): ParticipantBindingProjection {
  return {
    bindingId: `binding-${sessionId}`, sessionId, participantId: `participant-${sessionId}`, generation,
    roomBindingRef,
    personaRef: definitionRef('persona', 'zhiyou-v1'),
    collaborationRoleRef: definitionRef('collaboration-role', roomBindingRef ? 'researcher' : 'specialist'),
    agentTemplateRef: definitionRef('agent-template', roomBindingRef ? 'researcher' : 'assistant'),
    collaborationProfileRef: roomBindingRef ? definitionRef('collaboration-profile', 'evidence-review') : null,
    compiledRuntimeProfileRef: {
      profileId: `compiled:binding-${sessionId}`, revision: 'agent-definition-compiler-v1', contentHash: `sha256:${'1'.repeat(64)}`,
    },
    capabilityRevision: `capability-revision-${generation}`, capabilityEpoch: generation + 1,
  };
}

function capability(value: Pick<CapabilityProjection, 'capabilityId' | 'displayName' | 'generation' | 'sessionId' | 'summary' | 'states' | 'narrowedBy'>): CapabilityProjection {
  return {
    ...value,
    manifestRef: revisionRef('manifest', 'manifest-r8', '8'),
    profileRef: revisionRef('profile', 'profile-r4', '4'),
    skillRefs: [revisionRef('skill', 'knowledge-research', '3')],
    toolRefs: [revisionRef('tool', 'knowledge.search', '5')],
    contextRef: revisionRef('context', 'context-r12', '12'),
    receipts: [
      { receiptId: `${value.capabilityId}-available-r8`, kind: 'available', revision: '8', contentHash: `sha256:${'8'.repeat(64)}` },
      { receiptId: `${value.capabilityId}-authorized-r4`, kind: 'authorized', revision: '4', contentHash: `sha256:${'9'.repeat(64)}` },
    ],
  };
}

function definitionRef(kind: string, id: string) {
  return { kind, id, version: '1', contentHash: `sha256:${'2'.repeat(64)}` };
}

function revisionRef(kind: string, id: string, revision: string): RuntimeRevisionReferenceProjection {
  return { kind, id, revision, contentHash: `sha256:${'3'.repeat(64)}`, receiptId: `${id}-receipt` };
}
