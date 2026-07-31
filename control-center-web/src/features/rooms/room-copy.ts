import type { RoomParticipantPublicProgressProjection } from '@/contracts/room-reducer';
import { publicToolName } from '../agent/tool-presentation';

export const ROOM_PUBLIC_PROGRESS_KIND_LABELS: Record<
  RoomParticipantPublicProgressProjection['kind'],
  string
> = {
  reasoning: '公开思路',
  progress: '工作进度',
  tool: '工具进度',
  dispatch: '协作安排',
  status: '状态更新',
  post: '公开回复',
  activity: '协作动态',
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
    return `${toolName}${update.status === 'completed' ? '已返回' : update.status === 'failed' ? '未能完成' : '正在处理'}`;
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
  if (role === 'coordinator') return '帮大家对齐进度';
  if (role === 'researcher') return '查清资料';
  if (role === 'reviewer') return '一起检查结果';
  if (role === 'specialist') return '专项伙伴（尚未设置）';
  if (role === 'implementer') return '完成自己的部分';
  return '协作伙伴';
}

export function roomCollaborationRoleDescription(role: RoomCollaborationRoleValue): string {
  if (role === 'coordinator') return '完成自己的部分，同时帮大家对齐目标和进度';
  if (role === 'researcher') return '查清事实和来源，把不确定之处说清楚';
  if (role === 'reviewer') return '从另一角度检查结果是否满足要求';
  if (role === 'specialist') return '尚未设置具体领域，不会冒充专家';
  if (role === 'implementer') return '完成修改、验证结果，并交付可复核内容';
  return '根据当前任务完成自己这一轮的部分';
}
