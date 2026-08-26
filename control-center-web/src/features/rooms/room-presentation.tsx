import { BriefcaseBusiness, MessagesSquare, Sparkles, UsersRound } from 'lucide-react';
import { roomCollaborationRoleLabel, roomPlanetName } from './room-copy';
import type {
  RoomCollaborationRole,
  RoomExecutionMode,
  RoomKind,
  RoomSummary,
  RoomWorkState,
} from './room-types';

export function pathName(path: string): string {
  return path.split('/').filter(Boolean).at(-1) ?? path;
}

export function roomPathName(room: RoomSummary): string {
  return room.workspaceRoots?.[0] ? pathName(room.workspaceRoots[0]) : '未选择工作目录';
}

export function roomExecutionModeOptions(roomKind: RoomKind): Array<{
  value: RoomExecutionMode;
  label: string;
  description: string;
}> {
  const base = [
    { value: 'read_only' as const, label: '只读', description: '可以查看文件；写入和命令都不执行' },
    { value: 'per_action' as const, label: '每次确认', description: '每次写文件或运行命令前都先问你' },
  ];
  if (roomKind === 'roleplay') return base;
  return [
    ...base,
    { value: 'workspace_managed' as const, label: '工作区托管', description: '在选定目录内自主工作，越界时再问你' },
    { value: 'full_trust' as const, label: '全自动', description: '所有待审批操作由独立审批助手（Luna Max）依据整个协作空间的审批记录自动判定' },
  ];
}

export function roomWorkspaceViewOptions(roomKind: RoomKind | undefined) {
  if (roomKind === 'roleplay') {
    return [
      { value: 'posts' as const, label: '对话' },
      { value: 'sessions' as const, label: '伙伴' },
    ];
  }
  return [
    { value: 'posts' as const, label: '对话' },
    { value: 'execution' as const, label: '任务' },
    { value: 'sessions' as const, label: '伙伴' },
  ];
}

export function roomExecutionModeLabel(value: RoomExecutionMode | undefined): string {
  return {
    read_only: '只读',
    per_action: '每次确认',
    workspace_managed: '工作区托管',
    full_trust: '全自动',
  }[value ?? 'per_action'];
}

export function recommendedCreateRole(
  roleId: string,
  _selectedRoleIds: string[],
  coordinatorRoleId: string,
): RoomCollaborationRole {
  if (roleId === coordinatorRoleId) return 'coordinator';
  return 'implementer';
}

export function roomCreateParticipantLabel(
  roomKind: RoomKind,
  selected: boolean,
  roleId: string,
  selectedRoleIds: string[],
  coordinatorRoleId: string,
): string {
  if (!selected) return '可邀请';
  if (roomKind === 'roleplay') return '一起聊天';
  return roomCollaborationRoleLabel(
    recommendedCreateRole(roleId, selectedRoleIds, coordinatorRoleId),
  );
}

export function participantName(room: RoomSummary, participantId: string): string {
  const participant = room.participants.find((item) => item.id === participantId);
  return participant ? roomPlanetName(participant.ordinal) : '待接收';
}

export function roomWorkStateLabel(state: RoomWorkState): string {
  return {
    queued: '待接收',
    active: '执行中',
    review: '等待汇合',
    blocked: '已阻塞',
    done: '已完成',
    failed: '未完成',
    cancelled: '已取消',
  }[state];
}

export function roomAvatarOptions(): { value: string; label: string }[] {
  return [
    { value: 'briefcase', label: '任务' },
    { value: 'members', label: '伙伴' },
    { value: 'sparkles', label: '灵感' },
    { value: 'messages', label: '对话' },
  ];
}

export function roomCollaborationRoleOptions(
  currentRole?: RoomCollaborationRole,
): { value: RoomCollaborationRole; label: string; disabled?: boolean }[] {
  const options: { value: RoomCollaborationRole; label: string; disabled?: boolean }[] = [
    { value: 'coordinator', label: roomCollaborationRoleLabel('coordinator') },
    { value: 'implementer', label: roomCollaborationRoleLabel('implementer') },
    { value: 'researcher', label: roomCollaborationRoleLabel('researcher') },
    { value: 'reviewer', label: roomCollaborationRoleLabel('reviewer') },
  ];
  if (currentRole === 'specialist') {
    options.push({
      value: 'specialist',
      label: roomCollaborationRoleLabel('specialist'),
      disabled: true,
    });
  }
  return options;
}

export function roomAvatarIcon(room: RoomSummary) {
  if (room.avatar === 'sparkles' || room.roomKind === 'roleplay') return <Sparkles size={16} />;
  if (room.avatar === 'briefcase') return <BriefcaseBusiness size={16} />;
  if (room.avatar === 'messages') return <MessagesSquare size={16} />;
  return <UsersRound size={16} />;
}
