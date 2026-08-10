import { LoaderCircle } from 'lucide-react';
import { Navigate, createHashRouter } from 'react-router-dom';
import type { RouteId } from '@/app/route-registry';
import { PlanningFeature } from '@/features/planning';

const lazyRouteModules = {
  'project-field': async () => ({ Component: (await import('@/features/project-field')).ProjectFieldFeature }),
  overview: async () => ({ Component: (await import('@/features/overview')).OverviewFeature }),
  input: async () => ({ Component: (await import('@/features/input-method')).InputMethodFeature }),
  agent: async () => ({ Component: (await import('@/features/agent')).AgentFeature }),
  rooms: async () => ({ Component: (await import('@/features/rooms')).RoomsFeature }),
  roles: async () => ({ Component: (await import('@/features/roles')).RolesFeature }),
  plugins: async () => ({ Component: (await import('@/features/plugins')).PluginsFeature }),
  browser: async () => ({ Component: (await import('@/features/browser')).BrowserFeature }),
  voice: async () => ({ Component: (await import('@/features/voice')).VoiceFeature }),
  'work-documents': async () => ({ Component: (await import('@/features/work-documents')).WorkDocumentsFeature }),
  memory: async () => ({ Component: (await import('@/features/memory')).MemoryFeature }),
  knowledge: async () => ({ Component: (await import('@/features/knowledge')).KnowledgeFeature }),
  governance: async () => ({ Component: (await import('@/features/governance')).GovernanceFeature }),
  history: async () => ({ Component: (await import('@/features/history')).HistoryFeature }),
  observability: async () => ({ Component: (await import('@/features/observability')).ObservabilityFeature }),
  'context-debug': async () => ({ Component: (await import('@/features/context-debug')).ContextDebugFeature }),
  diagnostics: async () => ({ Component: (await import('@/features/diagnostics')).DiagnosticsFeature }),
  configuration: async () => ({ Component: (await import('@/features/configuration')).ConfigurationFeature }),
} as const;

type LazyRouteId = keyof typeof lazyRouteModules;

export function prefetchRoute(routeId: RouteId): void {
  if (!isLazyRouteId(routeId)) return;
  void lazyRouteModules[routeId]().catch(() => undefined);
}

function isLazyRouteId(routeId: RouteId): routeId is LazyRouteId {
  return routeId in lazyRouteModules;
}

export const router = createHashRouter([
  { path: '/', element: <Navigate replace to="/agent" /> },
  { path: '/project-field', HydrateFallback: RouteLoading, lazy: lazyRouteModules['project-field'] },
  { path: '/overview', HydrateFallback: RouteLoading, lazy: lazyRouteModules.overview },
  { path: '/input', HydrateFallback: RouteLoading, lazy: lazyRouteModules.input },
  { path: '/agent', HydrateFallback: RouteLoading, lazy: lazyRouteModules.agent },
  { path: '/rooms', HydrateFallback: RouteLoading, lazy: lazyRouteModules.rooms },
  { path: '/roles', HydrateFallback: RouteLoading, lazy: lazyRouteModules.roles },
  { path: '/plugins', HydrateFallback: RouteLoading, lazy: lazyRouteModules.plugins },
  { path: '/browser', HydrateFallback: RouteLoading, lazy: lazyRouteModules.browser },
  { path: '/voice', HydrateFallback: RouteLoading, lazy: lazyRouteModules.voice },
  { path: '/planning', element: <PlanningFeature /> },
  { path: '/work-documents', HydrateFallback: RouteLoading, lazy: lazyRouteModules['work-documents'] },
  { path: '/memory', HydrateFallback: RouteLoading, lazy: lazyRouteModules.memory },
  { path: '/knowledge', HydrateFallback: RouteLoading, lazy: lazyRouteModules.knowledge },
  { path: '/governance', HydrateFallback: RouteLoading, lazy: lazyRouteModules.governance },
  { path: '/history', HydrateFallback: RouteLoading, lazy: lazyRouteModules.history },
  { path: '/observability', HydrateFallback: RouteLoading, lazy: lazyRouteModules.observability },
  { path: '/context-debug', HydrateFallback: RouteLoading, lazy: lazyRouteModules['context-debug'] },
  { path: '/diagnostics', HydrateFallback: RouteLoading, lazy: lazyRouteModules.diagnostics },
  { path: '/configuration', HydrateFallback: RouteLoading, lazy: lazyRouteModules.configuration },
  { path: '/_primitives', HydrateFallback: RouteLoading, lazy: async () => ({ Component: (await import('@/components/primitives')).PrimitivesShowcase }) },
  { path: '*', element: <Navigate replace to="/agent" /> },
]);

export function RouteLoading() {
  return (
    <main className="shell-route-loading" aria-live="polite">
      <LoaderCircle className="ui-spin" size={20} />
      <span>正在打开</span>
    </main>
  );
}
