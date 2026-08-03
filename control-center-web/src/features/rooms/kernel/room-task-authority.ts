import type { Todo } from '@/contracts/generated/agent-workflow-state.v1';
import type { RoomDispatchEnvelopeV2 } from '@/contracts/generated/room-dispatch-envelope.v2';
import type { RoomTaskV3 } from '@/contracts/generated/room-task.v3';
import type { PrivateSessionProjection } from '@/contracts/room-kernel-reducer';
import type { RoomWorkItem } from '../room-types';
import type {
  RoomPublicVerification,
  RoomTaskRoleResultProjection,
  RoomWorkspaceDeliveryProjection,
} from './RoomTaskAuthorityDetails';

type RoomTaskAuthoritySource = RoomTaskV3 & {
  workItemId?: string;
  workspaceDelivery?: RoomWorkspaceDeliveryProjection;
  resultSummary?: string;
  resultKind?: RoomTaskRoleResultProjection['resultKind'];
  resultAtMs?: number;
  verificationCount?: number;
  verifications?: RoomPublicVerification[];
  artifactRefs?: string[];
  residualRisks?: string[];
};

type RoomSessionAuthoritySource = PrivateSessionProjection & {
  participantId?: string;
  todo?: Todo;
};

export type RoomTaskAuthorityProjection = {
  canonicalDispatch?: RoomDispatchEnvelopeV2;
  delivery?: RoomWorkspaceDeliveryProjection;
  roleResult?: RoomTaskRoleResultProjection;
  todo?: Todo;
  workItem?: RoomWorkItem;
};

/**
 * Join one task to its exact Session, Todo, WorkItem, and delivery owners.
 * Missing or conflicting identities fail closed; presentation must not guess.
 */
export function projectRoomTaskAuthority({
  dispatches,
  generation,
  sessionsById,
  task,
  workItems,
}: {
  dispatches: RoomDispatchEnvelopeV2[];
  generation: number;
  sessionsById: Record<string, PrivateSessionProjection>;
  task: RoomTaskV3;
  workItems: RoomWorkItem[];
}): RoomTaskAuthorityProjection {
  if (String(task.taskKind) === 'report') return {};
  const source = task as RoomTaskAuthoritySource;
  const canonicalDispatch = canonicalTaskDispatch(
    source,
    dispatches,
    generation,
    sessionsById,
  );
  const session = canonicalDispatch
    ? sessionsById[canonicalDispatch.targetSessionId] as RoomSessionAuthoritySource | undefined
    : undefined;
  const workItemId = source.workItemId?.trim() ?? '';
  const workItem = workItemId
    ? workItems.find((item) => (
        item.id === workItemId
        && item.currentOwnerParticipantId === task.currentOwnerParticipantId
      ))
    : undefined;
  const sessionOwnerMatches = Boolean(
    canonicalDispatch
    && session
    && session.sessionId === canonicalDispatch.targetSessionId
    && session.participantId === task.currentOwnerParticipantId
    && session.rootId === task.rootId
    && session.taskId === task.taskId
    && session.taskKind === task.taskKind
    && session.workItemId === workItemId
    && session.dispatchId === canonicalDispatch.dispatchId
    && session.generation === generation
  );
  const lineage = session?.todo?.roomLineage;
  const todo = sessionOwnerMatches
    && session
    && session.todo?.sessionId === session.sessionId
    && workItem
    && lineage?.schemaVersion === 'wisdom-weasel.room-todo-lineage.v1'
    && lineage.roomId === workItem.roomId
    && lineage.rootId === task.rootId
    && lineage.taskId === task.taskId
    && lineage.workItemId === workItem.id
    && lineage.dispatchId === canonicalDispatch?.dispatchId
    && lineage.sessionId === session.sessionId
    && lineage.participantId === task.currentOwnerParticipantId
    && lineage.generation === generation
    && lineage.taskRevision === task.revision
    && lineage.ownershipRevision === task.ownershipRevision
    && lineage.workItemRevision === workItem.revision
    ? session.todo
    : undefined;
  const rawDelivery = source.workspaceDelivery;
  const delivery = rawDelivery
    && canonicalDispatch
    && sessionOwnerMatches
    && rawDelivery.taskId === task.taskId
    && rawDelivery.workItemId === workItemId
    && rawDelivery.ownerParticipantId === task.currentOwnerParticipantId
    && rawDelivery.ownerSessionId === canonicalDispatch.targetSessionId
      ? rawDelivery
      : undefined;
  const roleResult = taskRoleResult(source);
  return {
    ...(canonicalDispatch ? { canonicalDispatch } : {}),
    ...(delivery ? { delivery } : {}),
    ...(roleResult ? { roleResult } : {}),
    ...(todo ? { todo } : {}),
    ...(workItem ? { workItem } : {}),
  };
}

function taskRoleResult(
  task: RoomTaskAuthoritySource,
): RoomTaskRoleResultProjection | undefined {
  const hasResult = task.resultSummary !== undefined
    || task.resultKind !== undefined
    || task.resultAtMs !== undefined
    || task.verificationCount !== undefined
    || task.verifications !== undefined
    || task.artifactRefs !== undefined
    || task.residualRisks !== undefined;
  if (!hasResult) return undefined;
  return {
    resultSummary: task.resultSummary ?? '',
    ...(task.resultKind ? { resultKind: task.resultKind } : {}),
    ...(task.resultAtMs !== undefined ? { resultAtMs: task.resultAtMs } : {}),
    verificationCount: task.verificationCount ?? 0,
    verifications: task.verifications ?? [],
    artifactRefs: task.artifactRefs ?? [],
    residualRisks: task.residualRisks ?? [],
  };
}

function canonicalTaskDispatch(
  task: RoomTaskAuthoritySource,
  dispatches: RoomDispatchEnvelopeV2[],
  generation: number,
  sessionsById: Record<string, PrivateSessionProjection>,
): RoomDispatchEnvelopeV2 | undefined {
  const candidates = dispatches.filter((dispatch) => (
    dispatch.taskId === task.taskId
    && dispatch.rootId === task.rootId
    && dispatch.generation === generation
    && dispatch.targetParticipantId === task.currentOwnerParticipantId
  ));
  const activelyBound = candidates.filter((dispatch) => {
    const session = sessionsById[dispatch.targetSessionId];
    const manifest = session?.capabilityManifest;
    return manifest?.status === 'active'
      && manifest.rootId === task.rootId
      && manifest.taskId === task.taskId
      && manifest.dispatchId === dispatch.dispatchId
      && manifest.generation === generation;
  });
  return [...(activelyBound.length ? activelyBound : candidates)].sort((left, right) => (
    right.attempt - left.attempt
    || right.capabilityEpoch - left.capabilityEpoch
    || right.dispatchId.localeCompare(left.dispatchId)
  ))[0];
}
