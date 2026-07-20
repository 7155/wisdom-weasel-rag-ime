export type ProjectSceneId = 'memory-evidence-timeline' | 'room-duoagent-handoff';

export type ProjectSceneAsset = Readonly<{
  id: ProjectSceneId;
  source: string;
  width: number;
  height: number;
  alt: string;
  intendedSlots: readonly string[];
}>;

export const projectSceneAssets = {
  'memory-evidence-timeline': {
    id: 'memory-evidence-timeline',
    source: '/companions/scenes/memory-evidence-timeline-v1.webp',
    width: 960,
    height: 640,
    alt: '从封存的历史证据中选出当前任务所需内容，形成小型上下文并回到光标',
    intendedSlots: ['memory-overview', 'memory-empty-state'],
  },
  'room-duoagent-handoff': {
    id: 'room-duoagent-handoff',
    source: '/companions/scenes/room-duoagent-handoff-v1.webp',
    width: 960,
    height: 720,
    alt: '两位智鼬在私有工作区之间显式交接，并将公开交付送回光标',
    intendedSlots: ['room-empty-state', 'room-onboarding'],
  },
} as const satisfies Record<ProjectSceneId, ProjectSceneAsset>;

export function resolveProjectScene(id: ProjectSceneId): ProjectSceneAsset {
  return projectSceneAssets[id];
}
