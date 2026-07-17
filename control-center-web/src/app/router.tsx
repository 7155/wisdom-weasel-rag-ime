import { Navigate, createHashRouter } from 'react-router-dom';
import { PrimitivesShowcase } from '@/components/primitives';
import { AgentFeature } from '@/features/agent';
import { BrowserFeature } from '@/features/browser';
import { ConfigurationFeature } from '@/features/configuration';
import { ContextDebugFeature } from '@/features/context-debug';
import { DiagnosticsFeature } from '@/features/diagnostics';
import { HistoryFeature } from '@/features/history';
import { InputMethodFeature } from '@/features/input-method';
import { KnowledgeFeature } from '@/features/knowledge';
import { MemoryFeature } from '@/features/memory';
import { ObservabilityFeature } from '@/features/observability';
import { OverviewFeature } from '@/features/overview';
import { PlanningFeature } from '@/features/planning';
import { PluginsFeature } from '@/features/plugins';
import { RolesFeature } from '@/features/roles';
import { RoomsFeature } from '@/features/rooms';
import { VoiceFeature } from '@/features/voice';

export const router = createHashRouter([
  { path: '/', element: <Navigate replace to="/planning" /> },
  { path: '/overview', element: <OverviewFeature /> },
  { path: '/input', element: <InputMethodFeature /> },
  { path: '/agent', element: <AgentFeature /> },
  { path: '/rooms', element: <RoomsFeature /> },
  { path: '/roles', element: <RolesFeature /> },
  { path: '/plugins', element: <PluginsFeature /> },
  { path: '/browser', element: <BrowserFeature /> },
  { path: '/voice', element: <VoiceFeature /> },
  { path: '/planning', element: <PlanningFeature /> },
  { path: '/memory', element: <MemoryFeature /> },
  { path: '/knowledge', element: <KnowledgeFeature /> },
  { path: '/history', element: <HistoryFeature /> },
  { path: '/observability', element: <ObservabilityFeature /> },
  { path: '/context-debug', element: <ContextDebugFeature /> },
  { path: '/diagnostics', element: <DiagnosticsFeature /> },
  { path: '/configuration', element: <ConfigurationFeature /> },
  { path: '/_primitives', element: <PrimitivesShowcase /> },
  { path: '*', element: <Navigate replace to="/planning" /> },
]);
