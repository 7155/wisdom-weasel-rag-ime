import { describe, expect, it } from 'vitest';

import type { RoomDispatchEnvelopeV2 } from '@/contracts/generated/room-dispatch-envelope.v2';
import type { RoomPostV2 } from '@/contracts/generated/room-post.v2';
import type { RoomScreenStateV1 } from '@/contracts/generated/room-screen-state.v1';
import type { RoomTaskV3 } from '@/contracts/generated/room-task.v3';
import {
  createRoomKernelProjection,
  type RootProjection,
} from '@/contracts/room-kernel-reducer';
import { buildRoomScreenModel } from './room-screen-model';

describe('buildRoomScreenModel', () => {
  it('uses the backend active Root instead of locally choosing the most recent Root', () => {
    const projection = createRoomKernelProjection('room-a');
    projection.rootsById['root-authoritative'] = root({
      rootId: 'root-authoritative',
      updatedAtMs: 5,
    });
    projection.rootsById['root-newer'] = root({
      rootId: 'root-newer',
      updatedAtMs: 50,
    });

    projection.screenState = screenState({
      activeRootId: 'root-authoritative',
      phase: 'execution',
    });
    const model = buildRoomScreenModel(projection);

    expect(model.activeRoot?.rootId).toBe('root-authoritative');
    expect(model.phase).toBe('execution');
  });

  it('keeps a managed wait busy without presenting it as a blocker', () => {
    const projection = createRoomKernelProjection('room-a');
    projection.rootsById['root-a'] = root({ state: 'waiting' });

    projection.screenState = screenState({
      activeRootId: 'root-a',
      phase: 'waiting',
      waitReason: {
        kind: 'participant',
        reason: '等待上一波任务完成',
        requiresUserAction: false,
      },
    });
    const model = buildRoomScreenModel(projection);

    expect(model.wait).toEqual({
      kind: 'participant',
      reason: '等待上一波任务完成',
      requiresUserAction: false,
    });
    expect(model.header.busyState).toBe('running');
    expect(model.header.needsAttention).toBe(false);
    expect(model.composer.taskBusyState).toBe('running');
  });

  it('preserves backend workflow authority without re-deriving review from failed Tasks', () => {
    const projection = createRoomKernelProjection('room-a');
    projection.rootsById['root-a'] = root({ state: 'blocked' });
    projection.tasksById['task-failed'] = task({ state: 'failed' });
    projection.screenState = screenState({
      phase: 'blocked',
      runnableFrontier: { taskIds: ['task-recover'], dispatchIds: [] },
      integrationReadiness: {
        ready: false,
        reason: '当前交付尚未成功整合',
        pendingTaskIds: ['task-failed'],
      },
      reviewReadiness: {
        ready: false,
        reason: '未完成的功能不能进入独立复核',
        pendingTaskIds: ['task-failed'],
      },
      recommendedNextAction: 'resolve_blocker',
    });

    const model = buildRoomScreenModel(projection);

    expect(model.phase).toBe('blocked');
    expect(model.recommendedNextAction).toBe('resolve_blocker');
    expect(model.runnableFrontier).toEqual({ taskIds: ['task-recover'], dispatchIds: [] });
    expect(model.integrationReadiness.ready).toBe(false);
    expect(model.reviewReadiness.reason).toBe('未完成的功能不能进入独立复核');
    expect(model.collaborationStage).toBe('parallel_work');
  });

  it('shows independent review only from a canonical review action or a live review Task', () => {
    const projection = createRoomKernelProjection('room-a');
    projection.rootsById['root-a'] = root({ state: 'waiting' });
    projection.screenState = screenState({
      phase: 'waiting',
      recommendedNextAction: 'complete_independent_review',
    });

    expect(buildRoomScreenModel(projection).collaborationStage).toBe('independent_review');
  });

  it.each(['failed', 'cancelled', 'cancelled_with_unknowns'] as const)(
    'does not expose a final delivery for a %s Root',
    (state) => {
      const projection = createRoomKernelProjection('room-a');
      projection.rootsById['root-a'] = root({
        reporterParticipantId: 'participant:reporter',
        state,
      });
      projection.postOrder.push('post-final');
      projection.postsById['post-final'] = finalPost();

      const model = buildRoomScreenModel(projection);

      expect(model.finalDelivery).toBeUndefined();
    },
  );

  it('requires a completed Root, the selected reporter, result kind, and room_commit source', () => {
    const projection = createRoomKernelProjection('room-a');
    projection.rootsById['root-a'] = root({
      reporterParticipantId: 'participant:reporter',
      state: 'completed',
    });
    projection.postOrder.push('wrong-author', 'wrong-kind', 'wrong-source', 'post-final');
    projection.postsById['wrong-author'] = finalPost({
      authorActorRef: 'participant:other',
      postId: 'wrong-author',
    });
    projection.postsById['wrong-kind'] = finalPost({ kind: 'progress', postId: 'wrong-kind' });
    projection.postsById['wrong-source'] = finalPost({
      postId: 'wrong-source',
      publicationSource: { kind: 'room_post', ref: 'post:wrong-source' },
    });
    projection.postsById['post-final'] = finalPost();

    projection.screenState = screenState({
      finalDeliveryPostId: 'post-final',
    });
    const model = buildRoomScreenModel(projection);

    expect(model.finalDelivery?.postId).toBe('post-final');
  });

  it('keeps dispatch attempts from the active Root generation only', () => {
    const projection = createRoomKernelProjection('room-a');
    projection.rootsById['root-a'] = root({ generation: 4 });
    projection.tasksById['task-a'] = task();
    projection.dispatchesById['dispatch-stale'] = dispatch({
      dispatchId: 'dispatch-stale',
      generation: 3,
    });
    projection.dispatchesById['dispatch-current'] = dispatch({
      dispatchId: 'dispatch-current',
      generation: 4,
    });

    const model = buildRoomScreenModel(projection);

    expect(model.tasks.map((item) => item.taskId)).toEqual(['task-a']);
    expect(model.dispatchAttempts.map((item) => item.dispatchId)).toEqual(['dispatch-current']);
  });

  it('fails closed when screen state and its active Root generation disagree', () => {
    const projection = createRoomKernelProjection('room-a');
    projection.rootsById['root-a'] = root({ generation: 4 });
    projection.tasksById['task-a'] = task();
    projection.screenState = screenState({
      activeRootId: 'root-a',
      activeRootGeneration: 3,
      phase: 'completed',
      finalDeliveryPostId: 'post-final',
    });
    projection.postsById['post-final'] = finalPost();

    const model = buildRoomScreenModel(projection);

    expect(model.activeRoot).toBeUndefined();
    expect(model.phase).toBe('waiting');
    expect(model.tasks).toEqual([]);
    expect(model.finalDelivery).toBeUndefined();
    expect(model.header.label).toBe('正在同步最新进度');
    expect(model.composer.acceptsIntervention).toBe(false);
  });
});

function screenState(
  overrides: Partial<RoomScreenStateV1> = {},
): RoomScreenStateV1 {
  return {
    schemaVersion: 'wisdom-weasel.room-screen-state.v1',
    roomId: 'room-a',
    activeRootId: 'root-a',
    activeRootGeneration: 4,
    phase: 'execution',
    waitReason: null,
    runnableFrontier: { taskIds: [], dispatchIds: [] },
    integrationReadiness: { ready: true, reason: null, pendingTaskIds: [] },
    reviewReadiness: { ready: true, reason: null, pendingTaskIds: [] },
    finalDeliveryPostId: null,
    recommendedNextAction: 'continue_execution',
    ...overrides,
  };
}

function root(overrides: Partial<RootProjection> = {}): RootProjection {
  return {
    schemaVersion: 'wisdom-weasel.room-root-execution.v3',
    rootId: 'root-a',
    roomId: 'room-a',
    generation: 4,
    state: 'running',
    facilitatorParticipantId: 'participant:facilitator',
    reporterParticipantId: null,
    reporterSelectionReceiptId: null,
    requirementAnchorRef: 'requirement:1',
    createdByActorRef: 'user:local',
    terminalReceiptId: null,
    activeProfileRef: null,
    budgetPolicyRef: 'budget:default',
    independentReviewRequired: false,
    createdAtMs: 1,
    isFinal: false,
    updatedAtMs: 10,
    ...overrides,
  };
}

function task(overrides: Partial<RoomTaskV3> = {}): RoomTaskV3 {
  return {
    schemaVersion: 'wisdom-weasel.room-task.v3',
    taskId: 'task-a',
    rootId: 'root-a',
    parentTaskId: null,
    taskKind: 'work',
    currentOwnerParticipantId: 'participant:worker',
    ownershipRevision: 0,
    ownershipReceiptId: null,
    objective: '完成用户功能',
    expectedOutput: '可复核成果',
    requirementItemIds: ['requirement:1'],
    acceptanceCriterionIds: ['criterion:1'],
    contextEvidenceRefs: [],
    invitationId: null,
    reviewOfTaskIds: [],
    reviewAuthorParticipantIds: [],
    reviewState: 'not_required',
    revision: 1,
    state: 'active',
    ...overrides,
  };
}

function dispatch(overrides: Partial<RoomDispatchEnvelopeV2> = {}): RoomDispatchEnvelopeV2 {
  return {
    schemaVersion: 'wisdom-weasel.room-dispatch-envelope.v2',
    dispatchId: 'dispatch-current',
    rootId: 'root-a',
    taskId: 'task-a',
    parentDispatchId: null,
    generation: 4,
    hopCount: 1,
    depth: 1,
    budgetCost: 1,
    targetSessionId: 'session:worker',
    targetParticipantId: 'participant:worker',
    triggerId: 'trigger:1',
    intentKind: 'execute',
    idempotencyKey: 'dispatch:1',
    attempt: 1,
    capabilityEpoch: 1,
    runtimeProfileRevision: 'profile:1',
    state: 'running',
    ...overrides,
  };
}

function finalPost(overrides: Partial<RoomPostV2> = {}): RoomPostV2 {
  return {
    schemaVersion: 'wisdom-weasel.room-post.v2',
    postId: 'post-final',
    roomId: 'room-a',
    rootId: 'root-a',
    generation: 4,
    authorActorRef: 'participant:reporter',
    kind: 'result',
    visibility: 'room',
    content: '最终交付',
    idempotencyKey: 'post:final',
    publicationSource: { kind: 'room_commit', ref: 'commit:final' },
    createdAtMs: 20,
    ...overrides,
  };
}
