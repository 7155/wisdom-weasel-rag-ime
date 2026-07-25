import { LoaderCircle } from 'lucide-react';
import { Navigate, createHashRouter } from 'react-router-dom';
import { PlanningFeature } from '@/features/planning';

export const router = createHashRouter([
  { path: '/', element: <Navigate replace to="/planning" /> },
  { path: '/overview', HydrateFallback: RouteLoading, lazy: async () => ({ Component: (await import('@/features/overview')).OverviewFeature }) },
  { path: '/input', HydrateFallback: RouteLoading, lazy: async () => ({ Component: (await import('@/features/input-method')).InputMethodFeature }) },
  { path: '/agent', HydrateFallback: RouteLoading, lazy: async () => ({ Component: (await import('@/features/agent')).AgentFeature }) },
  { path: '/rooms', HydrateFallback: RouteLoading, lazy: async () => ({ Component: (await import('@/features/rooms')).RoomsFeature }) },
  { path: '/roles', HydrateFallback: RouteLoading, lazy: async () => ({ Component: (await import('@/features/roles')).RolesFeature }) },
  { path: '/plugins', HydrateFallback: RouteLoading, lazy: async () => ({ Component: (await import('@/features/plugins')).PluginsFeature }) },
  { path: '/browser', HydrateFallback: RouteLoading, lazy: async () => ({ Component: (await import('@/features/browser')).BrowserFeature }) },
  { path: '/voice', HydrateFallback: RouteLoading, lazy: async () => ({ Component: (await import('@/features/voice')).VoiceFeature }) },
  { path: '/planning', element: <PlanningFeature /> },
  { path: '/memory', HydrateFallback: RouteLoading, lazy: async () => ({ Component: (await import('@/features/memory')).MemoryFeature }) },
  { path: '/knowledge', HydrateFallback: RouteLoading, lazy: async () => ({ Component: (await import('@/features/knowledge')).KnowledgeFeature }) },
  { path: '/governance', HydrateFallback: RouteLoading, lazy: async () => ({ Component: (await import('@/features/governance')).GovernanceFeature }) },
  { path: '/history', HydrateFallback: RouteLoading, lazy: async () => ({ Component: (await import('@/features/history')).HistoryFeature }) },
  { path: '/observability', HydrateFallback: RouteLoading, lazy: async () => ({ Component: (await import('@/features/observability')).ObservabilityFeature }) },
  { path: '/context-debug', HydrateFallback: RouteLoading, lazy: async () => ({ Component: (await import('@/features/context-debug')).ContextDebugFeature }) },
  { path: '/diagnostics', HydrateFallback: RouteLoading, lazy: async () => ({ Component: (await import('@/features/diagnostics')).DiagnosticsFeature }) },
  { path: '/configuration', HydrateFallback: RouteLoading, lazy: async () => ({ Component: (await import('@/features/configuration')).ConfigurationFeature }) },
  { path: '/_primitives', HydrateFallback: RouteLoading, lazy: async () => ({ Component: (await import('@/components/primitives')).PrimitivesShowcase }) },
  { path: '*', element: <Navigate replace to="/planning" /> },
]);

export function RouteLoading() {
  return (
    <main className="shell-route-loading" aria-live="polite">
      <LoaderCircle className="ui-spin" size={20} />
      <span>正在打开工作台</span>
    </main>
  );
}
