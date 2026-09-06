import type { PawOsWindowRequest } from '@/features/paw-os/surface-context';
import type { RoomProjectionState } from '@/contracts/room-reducer';
import type { RoomParticipant, RoomSummary } from '@/features/rooms/room-types';
import { roomCollaborationRoleLabel } from '@/features/rooms/room-copy';
import {
  selectPublicRoomTurnOrder,
  selectRoomTurnExecution,
} from '@/features/rooms/runtime/room-execution-lanes';
import { roomFocusCelestialName } from './room-focus-projection';

interface RoomRuntimeTurnFacts {
  status: string;
  participantIds: readonly string[];
  terminalParticipantIds?: readonly string[];
  failedParticipantIds?: readonly string[];
  abortedParticipantIds?: readonly string[];
}

/**
 * Runtime participant ids can briefly lag behind already projected execution
 * lanes during snapshot recovery. Reconcile both mechanical sources, then
 * remove every terminal lane; Room membership alone is intentionally absent.
 */
export function roomRuntimeActiveParticipantIds(
  turn: RoomRuntimeTurnFacts | undefined,
  lanes: readonly { participantId: string | null }[],
): Set<string> {
  if (turn?.status !== 'running') return new Set();
  const terminal = new Set([
    ...(turn.terminalParticipantIds ?? []),
    ...(turn.failedParticipantIds ?? []),
    ...(turn.abortedParticipantIds ?? []),
  ]);
  return new Set([
    ...turn.participantIds,
    ...lanes.flatMap((lane) => lane.participantId ? [lane.participantId] : []),
  ].filter((participantId) => !terminal.has(participantId)));
}

/**
 * The composer steers only the newest public root, but Runtime can execute two
 * disjoint Partner Sessions for different public roots at the same time.
 * Collaboration mode therefore unions every still-running logical public
 * root. `selectPublicRoomTurnOrder` already removes retry ancestors and
 * detached intercom delivery turns; each turn then contributes only its
 * non-terminal Runtime participants.
 */
export function roomProjectionRuntimeActiveParticipantIds(
  projection: RoomProjectionState | undefined,
): Set<string> {
  if (!projection) return new Set();
  const active = new Set<string>();
  for (const turnId of selectPublicRoomTurnOrder(projection)) {
    const turn = projection.turnsById[turnId];
    if (turn?.status !== 'running') continue;
    const lanes = selectRoomTurnExecution(projection, turnId).lanes;
    for (const participantId of roomRuntimeActiveParticipantIds(turn, lanes)) {
      active.add(participantId);
    }
  }
  return active;
}

/**
 * Compact read-only planet observer used by collaboration mode. The target
 * keeps participant identity because WindowLayer lays these observers around
 * the Room without turning them into a second writable Session surface.
 */
export function roomPlanetObserverWindowRequest(
  participant: RoomParticipant,
  roomId: string,
  background = false,
): PawOsWindowRequest {
  return {
    appId: 'agent',
    background,
    target: {
      kind: 'participant',
      id: participant.id,
      roomId,
      sessionId: participant.sessionId,
      title: roomFocusCelestialName(participant.ordinal),
      subtitle: roomCollaborationRoleLabel(participant.collaborationRole),
    },
  };
}

/**
 * UR-170/172: a deliberate click in the ordinary Room task table opens the
 * participant's canonical Session, not the compact collaboration observer.
 * Session identity is the window key, so repeated clicks raise the same real
 * Session instead of creating observer/session duplicates.
 */
export function roomPartnerSessionWindowRequest(
  participant: RoomParticipant,
  background = false,
): PawOsWindowRequest {
  return {
    appId: 'agent',
    background,
    target: {
      kind: 'session',
      id: participant.sessionId,
      title: roomFocusCelestialName(participant.ordinal),
      subtitle: roomCollaborationRoleLabel(participant.collaborationRole),
    },
  };
}

/**
 * An explicit collaboration view opens partners admitted to a running public
 * turn. Membership alone cannot invent activity or an empty observer. These
 * background requests preserve the main composer and stable participant keys.
 */
export function roomCollaborationPlanetRequests(
  room: RoomSummary,
  projection?: RoomProjectionState,
): PawOsWindowRequest[] {
  if (room.status !== 'active') return [];
  const activeIds = roomProjectionRuntimeActiveParticipantIds(projection);
  return room.participants
    .filter((participant) => participant.status === 'active' && activeIds.has(participant.id))
    .sort((left, right) => left.ordinal - right.ordinal || left.id.localeCompare(right.id))
    .map((participant) => roomPlanetObserverWindowRequest(participant, room.id, true));
}
