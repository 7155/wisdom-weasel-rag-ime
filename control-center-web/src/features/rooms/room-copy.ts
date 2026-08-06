import type { RoomParticipantPublicProgressProjection } from '@/contracts/room-reducer';
import { publicToolName } from '../agent/tool-presentation';

export const ROOM_PUBLIC_PROGRESS_KIND_LABELS: Record<
  RoomParticipantPublicProgressProjection['kind'],
  string
> = {
  reasoning: '实时进展 · 工作摘要',
  progress: '实时进展 · 工作进度',
  tool: '运行记录 · 工具进度',
  dispatch: '运行记录 · 协作安排',
  status: '运行记录 · 伙伴状态',
  post: '伙伴回复 · 公开消息',
  activity: '运行记录 · 协作动态',
};

export function roomParticipantPublicProgressSummary(
  update: RoomParticipantPublicProgressProjection,
): string {
  const summary = update.summary.trim();
  if (update.kind !== 'tool') {
    const updateCount = Number(update.data?.updateCount);
    const suffix = update.kind === 'reasoning'
      && Number.isInteger(updateCount)
      && updateCount > 1
      ? ` · 已更新 ${updateCount} 次`
      : '';
    return `${summary || '公开进度已经更新'}${suffix}`;
  }
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
  if (role === 'coordinator') return '本轮主持与集成';
  if (role === 'researcher') return '本轮查证';
  if (role === 'reviewer') return '本轮复核';
  if (role === 'specialist') return '专项伙伴（尚未设置）';
  if (role === 'implementer') return '本轮功能负责人';
  return '协作伙伴';
}

export function roomCollaborationRoleDescription(role: RoomCollaborationRoleValue): string {
  if (role === 'coordinator') return '这是当前一轮的协调责任，不代表能力或层级更高';
  if (role === 'researcher') return '这是当前一轮的查证责任，同样可以在其他任务负责完整功能';
  if (role === 'reviewer') return '只复核自己未参与实现或集成的范围，不是固定岗位';
  if (role === 'specialist') return '尚未设置具体领域，不会冒充专家';
  if (role === 'implementer') return '端到端完成当前分配的用户功能、验证和交接';
  return '所有伙伴能力相同，具体责任按每轮任务动态分配';
}
