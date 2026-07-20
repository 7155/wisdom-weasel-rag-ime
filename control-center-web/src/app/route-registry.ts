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
  group: 'work' | 'knowledge' | 'system';
};

export const routeRegistry: readonly RouteDefinition[] = [
  { id: 'planning', path: '/planning', label: '规划', shortLabel: '规划', group: 'work' },
  { id: 'overview', path: '/overview', label: '总览', shortLabel: '总览', group: 'work' },
  { id: 'input', path: '/input', label: '输入法', shortLabel: '输入', group: 'work' },
  { id: 'agent', path: '/agent', label: 'Agent', shortLabel: 'Agent', group: 'work' },
  { id: 'rooms', path: '/rooms', label: 'Rooms', shortLabel: 'Room', group: 'work' },
  { id: 'roles', path: '/roles', label: '角色', shortLabel: '角色', group: 'work' },
  { id: 'plugins', path: '/plugins', label: '插件', shortLabel: '插件', group: 'work' },
  { id: 'browser', path: '/browser', label: '浏览器', shortLabel: '浏览器', group: 'work' },
  { id: 'voice', path: '/voice', label: '语音', shortLabel: '语音', group: 'work' },
  { id: 'memory', path: '/memory', label: '记忆', shortLabel: '记忆', group: 'knowledge' },
  { id: 'knowledge', path: '/knowledge', label: '知识库', shortLabel: '知识', group: 'knowledge' },
  { id: 'governance', path: '/governance', label: '治理中心', shortLabel: '治理', group: 'knowledge' },
  { id: 'history', path: '/history', label: '历史', shortLabel: '历史', group: 'knowledge' },
  { id: 'observability', path: '/observability', label: '运行观察', shortLabel: '观察', group: 'system' },
  { id: 'context-debug', path: '/context-debug', label: '上下文 Debug', shortLabel: 'Debug', group: 'system' },
  { id: 'diagnostics', path: '/diagnostics', label: '诊断', shortLabel: '诊断', group: 'system' },
  { id: 'configuration', path: '/configuration', label: '配置', shortLabel: '配置', group: 'system' },
] as const;
