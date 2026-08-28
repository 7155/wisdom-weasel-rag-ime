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
 * planet 窗口统一铭牌：无论从主 Room、协同模式还是星空进来，
 * 同一位伙伴永远得到同一扇窗——标题是行星名，副标题只留人读得懂的
 * 分工。真实姓名和 Session id 都是内部身份，去完整 Session 的入口在
 * 窗内状态行，不占窗口铭牌。
 */
export function roomPlanetWindowRequest(
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
 * UR-177 协同模式合同：只有用户显式进入协同模式时，Runtime 当前仍在
 * 执行的 Partner 才以行星 Session 窗展开。Room 名册是身份目录，不是执行
 * 状态；因此 idle、已结束或仅存在于历史名册的成员不能被自动打开。请求
 * 保持后台，主 Room 仍是返回面；稳定 participant target 让 WindowLayer
 * 唤起现有窗口而非复制。
 */
export function roomCollaborationSatelliteRequests(
  room: RoomSummary,
  runtimeActiveParticipantIds: ReadonlySet<string>,
): PawOsWindowRequest[] {
  if (room.status !== 'active') return [];
  return room.participants
    .filter((participant) => (
      participant.status === 'active'
      && runtimeActiveParticipantIds.has(participant.id)
    ))
    .sort((left, right) => left.ordinal - right.ordinal || left.id.localeCompare(right.id))
    .map((participant) => roomPlanetWindowRequest(participant, room.id, true));
}
