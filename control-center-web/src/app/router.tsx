import { Navigate, createHashRouter } from 'react-router-dom';
import { PlanningFeature } from '@/features/planning';

export const router = createHashRouter([
  { path: '/', element: <Navigate replace to="/planning" /> },
  { path: '/overview', lazy: async () => ({ Component: (await import('@/features/overview')).OverviewFeature }) },
  { path: '/input', lazy: async () => ({ Component: (await import('@/features/input-method')).InputMethodFeature }) },
  { path: '/agent', lazy: async () => ({ Component: (await import('@/features/agent')).AgentFeature }) },
  { path: '/rooms', lazy: async () => ({ Component: (await import('@/features/rooms')).RoomsFeature }) },
  { path: '/roles', lazy: async () => ({ Component: (await import('@/features/roles')).RolesFeature }) },
  { path: '/plugins', lazy: async () => ({ Component: (await import('@/features/plugins')).PluginsFeature }) },
  { path: '/browser', lazy: async () => ({ Component: (await import('@/features/browser')).BrowserFeature }) },
  { path: '/voice', lazy: async () => ({ Component: (await import('@/features/voice')).VoiceFeature }) },
  { path: '/planning', element: <PlanningFeature /> },
  { path: '/memory', lazy: async () => ({ Component: (await import('@/features/memory')).MemoryFeature }) },
  { path: '/knowledge', lazy: async () => ({ Component: (await import('@/features/knowledge')).KnowledgeFeature }) },
  { path: '/governance', lazy: async () => ({ Component: (await import('@/features/governance')).GovernanceFeature }) },
  { path: '/history', lazy: async () => ({ Component: (await import('@/features/history')).HistoryFeature }) },
  { path: '/observability', lazy: async () => ({ Component: (await import('@/features/observability')).ObservabilityFeature }) },
  { path: '/context-debug', lazy: async () => ({ Component: (await import('@/features/context-debug')).ContextDebugFeature }) },
  { path: '/diagnostics', lazy: async () => ({ Component: (await import('@/features/diagnostics')).DiagnosticsFeature }) },
  { path: '/configuration', lazy: async () => ({ Component: (await import('@/features/configuration')).ConfigurationFeature }) },
  { path: '/_primitives', lazy: async () => ({ Component: (await import('@/components/primitives')).PrimitivesShowcase }) },
  { path: '*', element: <Navigate replace to="/planning" /> },
]);
