import type { PawOsWindowRequest } from '@/features/paw-os/surface-context';
import type { RoomSummary } from '@/features/rooms/room-types';
import { roomCollaborationRoleLabel } from '@/features/rooms/room-copy';

/** UR-054：进入 Room 后最多自动展开四到五个活跃伙伴卫星窗。 */
export const ROOM_AUTO_SATELLITE_LIMIT = 5;

/**
 * UR-054 焦点合同：进入 Room 时活跃伙伴以卫星窗围绕主窗自动展开；
 * 全部后台打开，主 Room 保持焦点，用户点击伙伴才把对应卫星窗前置。
 * 每位伙伴只自动展开一次（由调用方用 alreadyExpandedIds 记账），
 * 用户关闭卫星窗后不会被同一事实循环重开。
 */
export function roomAutoSatelliteRequests(
  room: RoomSummary,
  participantAliases: Record<string, string>,
  alreadyExpandedIds: ReadonlySet<string>,
): PawOsWindowRequest[] {
  if (room.status !== 'active') return [];
  return room.participants
    .filter((participant) => participant.status === 'active')
    .sort((left, right) => left.ordinal - right.ordinal || left.id.localeCompare(right.id))
    .slice(0, ROOM_AUTO_SATELLITE_LIMIT)
    .filter((participant) => !alreadyExpandedIds.has(participant.id))
    .map((participant) => ({
      appId: 'agent',
      background: true,
      target: {
        kind: 'participant',
        id: participant.id,
        roomId: room.id,
        title: participantAliases[participant.id] || participant.displayName,
        subtitle: `${participant.displayName} · ${roomCollaborationRoleLabel(participant.collaborationRole)} · ${participant.sessionId}`,
      },
    }));
}
