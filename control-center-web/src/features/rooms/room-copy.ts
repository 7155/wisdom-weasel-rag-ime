export type RoomCollaborationRoleValue =
  | 'coordinator'
  | 'implementer'
  | 'researcher'
  | 'reviewer'
  | 'specialist'
  | undefined;

export function roomCollaborationRoleLabel(role: RoomCollaborationRoleValue): string {
  if (role === 'coordinator') return '组织协作';
  if (role === 'researcher') return '查资料与核对';
  if (role === 'reviewer') return '独立验收';
  if (role === 'specialist') return '专项职责（尚未设置）';
  if (role === 'implementer') return '动手实现';
  return '协作分工';
}

export function roomCollaborationRoleDescription(role: RoomCollaborationRoleValue): string {
  if (role === 'coordinator') return '对齐目标、安排分工，并推动交接和收口';
  if (role === 'researcher') return '查清事实和来源，把不确定之处说清楚';
  if (role === 'reviewer') return '不参与原实现，按验收条件独立检查结果';
  if (role === 'specialist') return '尚未设置具体领域，不会冒充专家';
  if (role === 'implementer') return '修改文件、运行验证，并交付可复核结果';
  return '根据当前任务明确这一轮要负责什么';
}
