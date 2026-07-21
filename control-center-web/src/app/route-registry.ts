export type RouteId =
  | 'overview'
  | 'input'
  | 'agent'
  | 'rooms'
  | 'roles'
  | 'plugins'
  | 'browser'
  | 'voice'
  | 'planning'
  | 'memory'
  | 'knowledge'
  | 'governance'
  | 'history'
  | 'observability'
  | 'context-debug'
  | 'diagnostics'
  | 'configuration';

export type RouteDefinition = {
  id: RouteId;
  path: `/${string}`;
  label: string;
  shortLabel: string;
  group: 'work' | 'capability' | 'operations';
};

export const routeRegistry: readonly RouteDefinition[] = [
  { id: 'planning', path: '/planning', label: '任务与验收', shortLabel: '任务', group: 'work' },
  { id: 'overview', path: '/overview', label: '运行总览', shortLabel: '总览', group: 'work' },
  { id: 'input', path: '/input', label: '输入法', shortLabel: '输入', group: 'work' },
  { id: 'agent', path: '/agent', label: 'Session 工作台', shortLabel: 'Session', group: 'work' },
  { id: 'rooms', path: '/rooms', label: 'Room 工作台', shortLabel: 'Room', group: 'work' },
  { id: 'roles', path: '/roles', label: 'Agent 伙伴', shortLabel: '伙伴', group: 'work' },
  { id: 'plugins', path: '/plugins', label: '能力中心', shortLabel: '能力', group: 'capability' },
  { id: 'knowledge', path: '/knowledge', label: '知识库', shortLabel: '知识', group: 'capability' },
  { id: 'memory', path: '/memory', label: '记忆', shortLabel: '记忆', group: 'capability' },
  { id: 'browser', path: '/browser', label: '浏览器', shortLabel: '浏览器', group: 'capability' },
  { id: 'voice', path: '/voice', label: '语音输入', shortLabel: '语音', group: 'capability' },
  { id: 'governance', path: '/governance', label: '交付与治理', shortLabel: '治理', group: 'operations' },
  { id: 'context-debug', path: '/context-debug', label: '上下文透视', shortLabel: '上下文', group: 'operations' },
  { id: 'observability', path: '/observability', label: '运行观察', shortLabel: '观察', group: 'operations' },
  { id: 'history', path: '/history', label: '历史', shortLabel: '历史', group: 'operations' },
  { id: 'diagnostics', path: '/diagnostics', label: '诊断', shortLabel: '诊断', group: 'operations' },
  { id: 'configuration', path: '/configuration', label: '配置', shortLabel: '配置', group: 'operations' },
] as const;
