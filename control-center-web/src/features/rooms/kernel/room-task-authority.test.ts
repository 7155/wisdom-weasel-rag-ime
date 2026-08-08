import { describe, expect, it } from 'vitest';

import type { Todo } from '@/contracts/generated/agent-workflow-state.v1';
import type { RoomDispatchEnvelopeV2 } from '@/contracts/generated/room-dispatch-envelope.v2';
import type { RoomTaskV3 } from '@/contracts/generated/room-task.v3';
import type { PrivateSessionProjection } from '@/contracts/room-kernel-reducer';
import type { RoomWorkItem } from '../room-types';
import type { RoomWorkspaceDeliveryProjection } from './RoomTaskAuthorityDetails';
import { projectRoomTaskAuthority } from './room-task-authority';

describe('projectRoomTaskAuthority', () => {
  it('joins Todo and delivery only through the canonical participant-owned Session', () => {
    const todo = todoProjection('session:owner');
    const delivery = deliveryProjection();
    const task = taskProjection({
      workItemId: 'work:owner',
      workspaceDelivery: delivery,
    });
    const stale = dispatchProjection({
      attempt: 1,
      dispatchId: 'dispatch:stale',
      targetSessionId: 'session:stale',
    });
    const current = dispatchProjection({ attempt: 2 });
    const sessionsById = {
      'session:owner': sessionProjection({
        capabilityManifest: capabilityManifest(),
        participantId: 'participant:owner',
        todo,
      }),
      'session:stale': sessionProjection({
        participantId: 'participant:owner',
        sessionId: 'session:stale',
        todo: todoProjection('session:stale'),
      }),
    };
    const workItem = workItemProjection();

    const projection = projectRoomTaskAuthority({
      dispatches: [stale, current],
      generation: 3,
      sessionsById,
      task,
      workItems: [workItem],
    });

    expect(projection.canonicalDispatch?.dispatchId).toBe('dispatch:owner');
    expect(projection.todo).toBe(todo);
    expect(projection.delivery).toBe(delivery);
    expect(projection.workItem).toBe(workItem);
  });

  it('fails closed for mismatched Session, Todo, delivery, and WorkItem owners', () => {
    const task = taskProjection({
      workItemId: 'work:owner',
      workspaceDelivery: deliveryProjection({ ownerSessionId: 'session:other' }),
    });
    const projection = projectRoomTaskAuthority({
      dispatches: [dispatchProjection()],
      generation: 3,
      sessionsById: {
        'session:owner': sessionProjection({
          participantId: 'participant:other',
          todo: todoProjection('session:other'),
        }),
      },
      task,
      workItems: [workItemProjection({ currentOwnerParticipantId: 'participant:other' })],
    });

    expect(projection.canonicalDispatch?.dispatchId).toBe('dispatch:owner');
    expect(projection.todo).toBeUndefined();
    expect(projection.delivery).toBeUndefined();
    expect(projection.workItem).toBeUndefined();
  });

  it('keeps an exact WorkItem role result even when no workspace delivery exists', () => {
    const workItem = workItemProjection();
    const projection = projectRoomTaskAuthority({
      dispatches: [dispatchProjection()],
      generation: 3,
      sessionsById: {
        'session:owner': sessionProjection({
          participantId: 'participant:owner',
          todo: todoProjection('session:owner'),
        }),
      },
      task: taskProjection({
        workItemId: workItem.id,
        resultSummary: '复核完成',
        resultKind: 'complete',
        resultAtMs: 11,
        verificationCount: 1,
        verifications: [{ label: '独立复核', result: 'pass', source: 'quality_gate' }],
        artifactRefs: [],
        residualRisks: [],
      }),
      workItems: [workItem],
    });

    expect(projection.todo?.sessionId).toBe('session:owner');
    expect(projection.delivery).toBeUndefined();
    expect(projection.workItem).toBe(workItem);
    expect(projection.roleResult).toMatchObject({
      resultSummary: '复核完成',
      verificationCount: 1,
    });
  });

  it('never attaches a Session Todo or WorkItem contribution to the internal report task', () => {
    const projection = projectRoomTaskAuthority({
      dispatches: [dispatchProjection()],
      generation: 3,
      sessionsById: {
        'session:owner': sessionProjection({
          participantId: 'participant:owner',
          todo: todoProjection('session:owner'),
        }),
      },
      task: taskProjection({ taskKind: 'report', workItemId: 'work:owner' }),
      workItems: [workItemProjection()],
    });

    expect(projection).toEqual({});
  });

  it('does not reuse the current Todo when one Session has moved to another WorkItem', () => {
    const workItemA = workItemProjection({ id: 'work:a', revision: 2 });
    const workItemB = workItemProjection({ id: 'work:b', revision: 4 });
    const projection = projectRoomTaskAuthority({
      dispatches: [dispatchProjection()],
      generation: 3,
      sessionsById: {
        'session:owner': sessionProjection({
          participantId: 'participant:owner',
          taskId: 'task:b',
          taskKind: 'work',
          workItemId: 'work:b',
          dispatchId: 'dispatch:b',
          todo: todoProjection('session:owner', {
            taskId: 'task:b',
            workItemId: 'work:b',
            dispatchId: 'dispatch:b',
            taskRevision: 5,
            ownershipRevision: 3,
            workItemRevision: 4,
          }),
        }),
      },
      task: taskProjection({ workItemId: 'work:a', revision: 2 }),
      workItems: [workItemA, workItemB],
    });

    expect(projection.todo).toBeUndefined();
    expect(projection.workItem).toBe(workItemA);
  });
});

function taskProjection(overrides: Record<string, unknown> = {}): RoomTaskV3 {
  return {
    schemaVersion: 'wisdom-weasel.room-task.v3',
    taskId: 'task:owner',
    rootId: 'root:1',
    parentTaskId: 'task:root',
    taskKind: 'work',
    currentOwnerParticipantId: 'participant:owner',
    ownershipRevision: 1,
    ownershipReceiptId: null,
    objective: '实现任务页',
    expectedOutput: '权威任务详情',
    requirementItemIds: [],
    acceptanceCriterionIds: [],
    contextEvidenceRefs: [],
    invitationId: null,
    reviewOfTaskIds: [],
    reviewAuthorParticipantIds: [],
    reviewState: 'not_required',
    revision: 1,
    state: 'active',
    ...overrides,
  } as RoomTaskV3;
}

function dispatchProjection(
  overrides: Partial<RoomDispatchEnvelopeV2> = {},
): RoomDispatchEnvelopeV2 {
  return {
    schemaVersion: 'wisdom-weasel.room-dispatch-envelope.v2',
    dispatchId: 'dispatch:owner',
    rootId: 'root:1',
    taskId: 'task:owner',
    parentDispatchId: null,
    generation: 3,
    hopCount: 0,
    depth: 1,
    budgetCost: 1,
    targetSessionId: 'session:owner',
    targetParticipantId: 'participant:owner',
    triggerId: 'trigger:1',
    intentKind: 'execute',
    idempotencyKey: 'dispatch:owner',
    attempt: 1,
    capabilityEpoch: 2,
    runtimeProfileRevision: 'profile:1',
    state: 'running',
    ...overrides,
  };
}

function sessionProjection(overrides: Record<string, unknown> = {}): PrivateSessionProjection {
  return {
    sessionId: 'session:owner',
    rootId: 'root:1',
    taskId: 'task:owner',
    taskKind: 'work',
    workItemId: 'work:owner',
    dispatchId: 'dispatch:owner',
    generation: 3,
    state: 'running',
    updatedAtMs: 10,
    ...overrides,
  } as PrivateSessionProjection;
}

function capabilityManifest(): NonNullable<PrivateSessionProjection['capabilityManifest']> {
  return {
    manifestId: 'manifest:1',
    manifestHash: 'a'.repeat(64),
    status: 'active',
    rootId: 'root:1',
    taskId: 'task:owner',
    dispatchId: 'dispatch:owner',
    generation: 3,
    capabilityEpoch: 2,
    promptCompileReceiptId: 'compile:1',
    promptPlanHash: 'b'.repeat(64),
    compiledRuntimeProfileRef: {
      profileId: 'profile:1',
      revision: '1',
      contentHash: 'c'.repeat(64),
    },
  };
}

function todoProjection(
  sessionId: string,
  lineageOverrides: Partial<NonNullable<Todo['roomLineage']>> = {},
): Todo {
  return {
    schemaVersion: 'rag-ime.agent-todo.v1',
    id: `todo:${sessionId}`,
    sessionId,
    revision: 1,
    actor: 'agent-runtime',
    updatedAtMs: 10,
    roomLineage: {
      schemaVersion: 'wisdom-weasel.room-todo-lineage.v1',
      roomId: 'room:1',
      rootId: 'root:1',
      taskId: 'task:owner',
      workItemId: 'work:owner',
      dispatchId: 'dispatch:owner',
      sessionId,
      participantId: 'participant:owner',
      generation: 3,
      taskRevision: 1,
      ownershipRevision: 1,
      workItemRevision: 1,
      ...lineageOverrides,
    },
    phases: [],
    counts: {
      total: 0,
      pending: 0,
      inProgress: 0,
      blocked: 0,
      completed: 0,
      abandoned: 0,
    },
  };
}

function deliveryProjection(
  overrides: Partial<RoomWorkspaceDeliveryProjection> = {},
): RoomWorkspaceDeliveryProjection {
  return {
    schemaVersion: 'wisdom-weasel.room-workspace-delivery.v1',
    ownerParticipantId: 'participant:owner',
    ownerSessionId: 'session:owner',
    workItemId: 'work:owner',
    taskId: 'task:owner',
    deliveryRevision: `sha256:${'d'.repeat(64)}`,
    baseCommit: 'git:base',
    workspaceSnapshotSha256: 'f'.repeat(64),
    patchSha256: '0'.repeat(64),
    deliveredAtMs: 10,
    resultSummary: '完成',
    manifestSha256: 'e'.repeat(64),
    files: [],
    totals: {
      fileCount: 0,
      additions: 0,
      deletions: 0,
      binaryFiles: 0,
      generatedFiles: 0,
      redactedFiles: 0,
    },
    artifactRefs: [],
    verificationCount: 0,
    verifications: [],
    verificationRefs: [],
    residualRisks: [],
    ...overrides,
  };
}

function workItemProjection(overrides: Partial<RoomWorkItem> = {}): RoomWorkItem {
  return {
    id: 'work:owner',
    roomId: 'room:1',
    topicId: '',
    rootTurnId: 'root:1',
    rootWorkId: 'work:owner',
    parentWorkId: '',
    objective: '实现任务页',
    expectedOutput: '权威任务详情',
    acceptanceCriteria: ['只读展示'],
    accountableParticipantId: 'participant:owner',
    currentOwnerParticipantId: 'participant:owner',
    offeredToParticipantId: '',
    createdByParticipantId: 'participant:owner',
    clientMessageId: 'message:1',
    state: 'done',
    depth: 1,
    revision: 1,
    resultSummary: '已完成',
    artifactRefs: [],
    evidenceRefs: [],
    blocker: {},
    acceptedTurnId: 'turn:1',
    createdAtMs: 1,
    updatedAtMs: 10,
    completedAtMs: 10,
    ...overrides,
  };
}
