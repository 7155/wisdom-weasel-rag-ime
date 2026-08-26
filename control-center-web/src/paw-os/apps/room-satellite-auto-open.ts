import type { PawOsWindowRequest } from '@/features/paw-os/surface-context';
import type { RoomParticipant, RoomSummary } from '@/features/rooms/room-types';
import { roomCollaborationRoleLabel } from '@/features/rooms/room-copy';
import { roomFocusCelestialName } from './room-focus-projection';

/** UR-054：进入 Room 后最多自动展开四到五个活跃伙伴卫星窗。 */
export const ROOM_AUTO_SATELLITE_LIMIT = 5;

/**
 * planet 窗口统一铭牌：无论从主 Room、协作态势、星空还是自动展开进来，
 * 同一位伙伴永远得到同一扇窗——标题是行星名，副标题只留当前分工。
 * Session id 与旧 persona 名都是内部事实，去完整 Session 的入口在窗内
 * 状态行，不占窗口铭牌。
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
      title: roomFocusCelestialName(participant.ordinal),
      subtitle: roomCollaborationRoleLabel(participant.collaborationRole),
    },
  };
}

/**
 * UR-054 焦点合同：进入 Room 时活跃伙伴以卫星窗围绕主窗自动展开；
 * 全部后台打开，主 Room 保持焦点，用户点击伙伴才把对应卫星窗前置。
 * 每位伙伴只自动展开一次（由调用方用 alreadyExpandedIds 记账），
 * 用户关闭卫星窗后不会被同一事实循环重开。
 */
export function roomAutoSatelliteRequests(
  room: RoomSummary,
  alreadyExpandedIds: ReadonlySet<string>,
): PawOsWindowRequest[] {
  if (room.status !== 'active') return [];
  return room.participants
    .filter((participant) => participant.status === 'active')
    .sort((left, right) => left.ordinal - right.ordinal || left.id.localeCompare(right.id))
    .slice(0, ROOM_AUTO_SATELLITE_LIMIT)
    .filter((participant) => !alreadyExpandedIds.has(participant.id))
    .map((participant) => roomPlanetWindowRequest(participant, room.id, true));
}
