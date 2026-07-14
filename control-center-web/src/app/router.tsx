import { Navigate, createHashRouter } from 'react-router-dom';
import { AgentFeature } from '@/features/agent';
import { ConfigurationFeature } from '@/features/configuration';
import { DiagnosticsFeature } from '@/features/diagnostics';
import { HistoryFeature } from '@/features/history';
import { InputMethodFeature } from '@/features/input-method';
import { KnowledgeFeature } from '@/features/knowledge';
import { MemoryFeature } from '@/features/memory';
import { OverviewFeature } from '@/features/overview';
import { PlanningFeature } from '@/features/planning';
import { PluginsFeature } from '@/features/plugins';
import { RolesFeature } from '@/features/roles';
import { RoomsFeature } from '@/features/rooms';
import { VoiceFeature } from '@/features/voice';

export const router = createHashRouter([
  { path: '/', element: <Navigate replace to="/overview" /> },
  { path: '/overview', element: <OverviewFeature /> },
  { path: '/input', element: <InputMethodFeature /> },
  { path: '/agent', element: <AgentFeature /> },
  { path: '/rooms', element: <RoomsFeature /> },
  { path: '/roles', element: <RolesFeature /> },
  { path: '/plugins', element: <PluginsFeature /> },
  { path: '/voice', element: <VoiceFeature /> },
  { path: '/planning', element: <PlanningFeature /> },
  { path: '/memory', element: <MemoryFeature /> },
  { path: '/knowledge', element: <KnowledgeFeature /> },
  { path: '/history', element: <HistoryFeature /> },
  { path: '/diagnostics', element: <DiagnosticsFeature /> },
  { path: '/configuration', element: <ConfigurationFeature /> },
  { path: '*', element: <Navigate replace to="/overview" /> },
]);
