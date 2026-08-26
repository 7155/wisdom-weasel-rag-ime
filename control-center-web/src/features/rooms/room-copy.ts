import type { RoomParticipantPublicProgressProjection } from '@/contracts/room-reducer';
import { publicToolName } from '../agent/tool-presentation';

/**
 * Stable public identity for Room participants. Runtime keeps participant and
 * Session ids plus the original persona display name; every collaboration
 * surface derives the one user-facing name from the persisted ordinal.
 */
export const ROOM_PLANET_NAMES = [
  'Earth',
  'Mars',
  'Venus',
  'Jupiter',
  'Saturn',
  'Mercury',
  'Neptune',
  'Uranus',
] as const;

export function roomPlanetName(ordinal: number): string {
  const normalized = Number.isInteger(ordinal) && ordinal >= 0 ? ordinal : 0;
  return ROOM_PLANET_NAMES[normalized] ?? `Planet ${normalized + 1}`;
}

export const ROOM_PUBLIC_PROGRESS_KIND_LABELS: Record<
  RoomParticipantPublicProgressProjection['kind'],
  string
> = {
  reasoning: '工作摘要',
  progress: '进度更新',
  tool: '运行记录 · 工具进度',
  dispatch: '运行记录 · 协作安排',
  status: '运行记录 · 伙伴状态',
  post: '公开回复',
  activity: '运行记录 · 协作动态',
};

export function roomParticipantPublicProgressSummary(
  update: RoomParticipantPublicProgressProjection,
): string {
  const summary = update.summary.trim();
  if (update.kind !== 'tool') return summary || '公开进度已经更新';
  const rawToolName = text(update.data?.toolName);
  const toolName = publicToolName(rawToolName, text(update.data?.displayName));
  if (
    !summary
    || summary === rawToolName
    || summary === text(update.data?.displayName)
    || /^[a-z][a-z0-9_.:/-]*$/iu.test(summary)
    || summary === '工具进度已更新'
  ) {
    return `${toolName}${update.status === 'completed' ? '已返回' : update.status === 'failed' ? '未能完成' : update.status === 'aborted' ? '已停止' : '正在处理'}`;
  }
  return summary;
}

function text(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

export type RoomCollaborationRoleValue =
  | 'coordinator'
  | 'implementer'
  | 'researcher'
  | 'reviewer'
  | 'specialist'
  | undefined;

export function roomCollaborationRoleLabel(role: RoomCollaborationRoleValue): string {
  if (role === 'coordinator') return '最终汇合与回复';
  if (role === 'researcher') return '调研与证据';
  if (role === 'reviewer') return '最终独立复核';
  if (role === 'specialist') return '专项伙伴（尚未设置）';
  if (role === 'implementer') return '实现与验证';
  return '协作伙伴';
}

export function roomCollaborationRoleDescription(role: RoomCollaborationRoleValue): string {
  if (role === 'coordinator') return '只负责最终 Root 汇合与回复，不是伙伴之间的消息中继';
  if (role === 'researcher') return '查清事实和来源，提交证据与不确定性，不替代实现';
  if (role === 'reviewer') return '只在整合完成后独立检查完整结果，不参与原实现';
  if (role === 'specialist') return '尚未设置具体领域，不会冒充专家';
  if (role === 'implementer') return '完成分配的改动与验证，提交可直接整合的结果';
  return '根据当前任务完成自己这一轮的部分';
}
