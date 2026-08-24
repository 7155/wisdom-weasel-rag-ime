import { routeRegistry, type RouteId } from '@/app/route-registry';

export type PawOsAppId =
  | 'project-workbench'
  | 'agent'
  | 'memory'
  | 'knowledge'
  | 'input-studio'
  | 'app-center'
  | 'system-monitor'
  | 'system-settings'
  | 'files'
  | 'browser'
  | 'terminal';

export type PawOsAppPresentation =
  | 'workspace'
  | 'conversation'
  | 'collaboration'
  | 'library'
  | 'studio'
  | 'utility'
  | 'system';

export type PawOsAppDefinition = {
  id: PawOsAppId;
  label: string;
  shortLabel: string;
  routeIds: readonly RouteId[];
  defaultRouteId: RouteId | null;
  presentation: PawOsAppPresentation;
  accent: 'cyan' | 'blue' | 'violet' | 'amber' | 'green' | 'rose' | 'slate';
  tagline: string;
};

export const wayfinderRouteId: RouteId = 'project-field';

export const pawOsAppRegistry: readonly PawOsAppDefinition[] = [
  {
    id: 'project-workbench',
    label: '项目工作台',
    shortLabel: '项目',
    routeIds: ['overview', 'planning', 'work-documents'],
    defaultRouteId: 'overview',
    presentation: 'workspace',
    accent: 'green',
    tagline: '概览、任务与工作文档',
  },
  {
    id: 'agent',
    label: 'Agent',
    shortLabel: 'Agent',
    routeIds: ['agent', 'rooms'],
    defaultRouteId: 'agent',
    presentation: 'conversation',
    accent: 'violet',
    tagline: 'Session 与 Room',
  },
  {
    id: 'memory',
    label: 'Memory',
    shortLabel: '记忆',
    routeIds: ['memory'],
    defaultRouteId: 'memory',
    presentation: 'library',
    accent: 'rose',
    tagline: '可追溯的个人记忆',
  },
  {
    id: 'knowledge',
    label: 'Knowledge',
    shortLabel: '知识',
    routeIds: ['knowledge'],
    defaultRouteId: 'knowledge',
    presentation: 'library',
    accent: 'blue',
    tagline: '资料、索引与检索空间',
  },
  {
    id: 'input-studio',
    label: 'Input Studio',
    shortLabel: '输入',
    routeIds: ['input', 'voice', 'history'],
    defaultRouteId: 'input',
    presentation: 'studio',
    accent: 'green',
    tagline: '语音、输入法、词库与输入记录',
  },
  {
    id: 'app-center',
    label: 'App Center',
    shortLabel: '应用',
    routeIds: ['plugins'],
    defaultRouteId: 'plugins',
    presentation: 'utility',
    accent: 'violet',
    tagline: '插件、Pi Package 与 App Surface',
  },
  {
    id: 'system-monitor',
    label: 'System Monitor',
    shortLabel: '监控',
    routeIds: ['context-debug', 'observability', 'diagnostics'],
    defaultRouteId: 'observability',
    presentation: 'system',
    accent: 'cyan',
    tagline: '上下文、运行记录与问题排查',
  },
  {
    id: 'system-settings',
    label: 'System Settings',
    shortLabel: '设置',
    routeIds: ['configuration', 'governance', 'approvals'],
    defaultRouteId: 'configuration',
    presentation: 'system',
    accent: 'slate',
    tagline: '通用配置、外观与安全审批',
  },
  {
    id: 'files',
    label: 'Files',
    shortLabel: '文件',
    routeIds: [],
    defaultRouteId: null,
    presentation: 'utility',
    accent: 'blue',
    tagline: '项目文件与工作区浏览',
  },
  {
    id: 'browser',
    label: 'Browser',
    shortLabel: '浏览器',
    routeIds: ['browser'],
    defaultRouteId: 'browser',
    presentation: 'utility',
    accent: 'cyan',
    tagline: '受控浏览与网页工作台',
  },
  {
    id: 'terminal',
    label: 'Terminal',
    shortLabel: '终端',
    routeIds: [],
    defaultRouteId: null,
    presentation: 'utility',
    accent: 'slate',
    tagline: '项目命令与本地任务',
  },
] as const;

export const primaryDockAppIds: readonly PawOsAppId[] = [
  'project-workbench',
  'agent',
  'memory',
  'knowledge',
  'input-studio',
  'files',
  'browser',
  'terminal',
];

const appById = new Map(pawOsAppRegistry.map((app) => [app.id, app]));
const appByRoute = new Map<RouteId, PawOsAppDefinition>();

for (const app of pawOsAppRegistry) {
  for (const routeId of app.routeIds) appByRoute.set(routeId, app);
}

export function pawOsApp(appId: PawOsAppId): PawOsAppDefinition {
  const app = appById.get(appId);
  if (!app) throw new Error(`Unknown PAWOS App: ${appId}`);
  return app;
}

export function pawOsAppForRoute(routeId: RouteId): PawOsAppDefinition | null {
  if (routeId === wayfinderRouteId) return null;
  return appByRoute.get(routeId) ?? null;
}

export function routePath(routeId: RouteId): string {
  return routeRegistry.find((route) => route.id === routeId)?.path ?? '/project-field';
}
