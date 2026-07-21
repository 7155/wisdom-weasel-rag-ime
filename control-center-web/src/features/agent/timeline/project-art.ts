export type ProjectSceneId =
  | 'knowledge-authorized-retrieval'
  | 'memory-evidence-timeline'
  | 'recovery-safe-resume'
  | 'room-agent-handoff'
  | 'room-onboarding'
  | 'task-evidence-acceptance';

export type ProjectSceneAsset = Readonly<{
  id: ProjectSceneId;
  source: string;
  width: number;
  height: number;
  alt: string;
  intendedSlots: readonly string[];
}>;

export const projectSceneAssets = {
  'knowledge-authorized-retrieval': {
    id: 'knowledge-authorized-retrieval',
    source: '/companions/scenes/knowledge-authorized-retrieval-v2.webp',
    width: 960,
    height: 640,
    alt: '初识与闪念在明亮资料库中挑选经过授权、能回答当前问题的可靠材料',
    intendedSlots: ['knowledge-library-empty-state', 'knowledge-retrieval-empty-state'],
  },
  'memory-evidence-timeline': {
    id: 'memory-evidence-timeline',
    source: '/companions/scenes/memory-evidence-timeline-v2.webp',
    width: 960,
    height: 640,
    alt: '初识从长期输入形成的时间线中选出当前任务真正需要的原文、偏好和证据',
    intendedSlots: ['memory-overview', 'memory-empty-state'],
  },
  'recovery-safe-resume': {
    id: 'recovery-safe-resume',
    source: '/companions/scenes/recovery-safe-resume-v2.webp',
    width: 960,
    height: 640,
    alt: '此刻与闪念把失败限制在安全边界内，保留检查点并准备从可验证状态继续',
    intendedSlots: ['room-runtime-error', 'agent-recovery'],
  },
  'room-agent-handoff': {
    id: 'room-agent-handoff',
    source: '/companions/scenes/room-structured-handoff-v2.webp',
    width: 960,
    height: 640,
    alt: '此刻把带有任务、证据和验收条件的交接单递给未来，责任路径清楚可追踪',
    intendedSlots: ['room-execution-empty-state', 'room-handoff'],
  },
  'room-onboarding': {
    id: 'room-onboarding',
    source: '/companions/scenes/room-ensemble-onboarding-v2.webp',
    width: 960,
    height: 640,
    alt: '四位长期智能伙伴围绕同一项真实任务交流、分工并共同核对证据',
    intendedSlots: ['room-empty-state', 'room-onboarding'],
  },
  'task-evidence-acceptance': {
    id: 'task-evidence-acceptance',
    source: '/companions/scenes/task-evidence-acceptance-v2.webp',
    width: 960,
    height: 640,
    alt: '此刻完成任务实现，未来依据原始需求、验收条件和证据独立复核交付',
    intendedSlots: ['planning-task-empty-state', 'task-acceptance'],
  },
} as const satisfies Record<ProjectSceneId, ProjectSceneAsset>;

export function resolveProjectScene(id: ProjectSceneId): ProjectSceneAsset {
  return projectSceneAssets[id];
}
