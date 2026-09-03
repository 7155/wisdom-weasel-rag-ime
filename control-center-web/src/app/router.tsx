import { AlertTriangle, LoaderCircle, RotateCcw } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { Navigate, createHashRouter, useNavigate } from 'react-router-dom';
import type { RouteId } from '@/app/route-registry';
import { Button } from '@/components/primitives';

const lazyRouteModules = {
  'project-field': async () => ({ Component: (await import('@/features/project-field')).ProjectFieldFeature }),
  overview: async () => ({ Component: (await import('@/features/overview')).OverviewFeature }),
  input: async () => ({ Component: (await import('@/features/input-method')).InputMethodFeature }),
  agent: async () => ({ Component: (await import('@/features/agent')).AgentFeature }),
  rooms: async () => ({ Component: (await import('@/features/rooms')).RoomsFeature }),
  plugins: async () => ({ Component: (await import('@/features/plugins')).PluginsFeature }),
  approvals: async () => ({ Component: (await import('@/features/approvals')).ApprovalsFeature }),
  browser: async () => ({ Component: (await import('@/features/browser')).BrowserFeature }),
  voice: async () => ({ Component: (await import('@/features/voice')).VoiceFeature }),
  planning: async () => ({ Component: (await import('@/features/planning')).PlanningFeature }),
  'work-documents': async () => ({ Component: (await import('@/features/work-documents')).WorkDocumentsFeature }),
  memory: async () => ({ Component: (await import('@/features/memory')).MemoryFeature }),
  knowledge: async () => ({ Component: (await import('@/features/knowledge')).KnowledgeFeature }),
  governance: async () => ({ Component: (await import('@/features/governance')).GovernanceFeature }),
  history: async () => ({ Component: (await import('@/features/history')).HistoryFeature }),
  observability: async () => ({ Component: (await import('@/features/observability')).ObservabilityFeature }),
  'eval-lab': async () => ({ Component: (await import('@/features/eval-lab')).EvalLabFeature }),
  'trace-agent': async () => ({ Component: (await import('@/features/trace-agent')).TraceAgentFeature }),
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
  {
    errorElement: <RouteErrorBoundary />,
    children: [
      { path: '/', element: <Navigate replace to="/agent" /> },
      { path: '/project-field', HydrateFallback: RouteLoading, lazy: lazyRouteModules['project-field'] },
      { path: '/overview', HydrateFallback: RouteLoading, lazy: lazyRouteModules.overview },
      { path: '/input', HydrateFallback: RouteLoading, lazy: lazyRouteModules.input },
      { path: '/agent', HydrateFallback: RouteLoading, lazy: lazyRouteModules.agent },
      { path: '/rooms', HydrateFallback: RouteLoading, lazy: lazyRouteModules.rooms },
      { path: '/plugins', HydrateFallback: RouteLoading, lazy: lazyRouteModules.plugins },
      { path: '/approvals', HydrateFallback: RouteLoading, lazy: lazyRouteModules.approvals },
      { path: '/browser', HydrateFallback: RouteLoading, lazy: lazyRouteModules.browser },
      { path: '/voice', HydrateFallback: RouteLoading, lazy: lazyRouteModules.voice },
      { path: '/planning', HydrateFallback: RouteLoading, lazy: lazyRouteModules.planning },
      { path: '/work-documents', HydrateFallback: RouteLoading, lazy: lazyRouteModules['work-documents'] },
      { path: '/memory', HydrateFallback: RouteLoading, lazy: lazyRouteModules.memory },
      { path: '/knowledge', HydrateFallback: RouteLoading, lazy: lazyRouteModules.knowledge },
      { path: '/governance', HydrateFallback: RouteLoading, lazy: lazyRouteModules.governance },
      { path: '/history', HydrateFallback: RouteLoading, lazy: lazyRouteModules.history },
      { path: '/observability', HydrateFallback: RouteLoading, lazy: lazyRouteModules.observability },
      { path: '/eval-lab', HydrateFallback: RouteLoading, lazy: lazyRouteModules['eval-lab'] },
      { path: '/trace-agent', HydrateFallback: RouteLoading, lazy: lazyRouteModules['trace-agent'] },
      { path: '/context-debug', HydrateFallback: RouteLoading, lazy: lazyRouteModules['context-debug'] },
      { path: '/diagnostics', HydrateFallback: RouteLoading, lazy: lazyRouteModules.diagnostics },
      { path: '/configuration', HydrateFallback: RouteLoading, lazy: lazyRouteModules.configuration },
      { path: '/_primitives', HydrateFallback: RouteLoading, lazy: async () => ({ Component: (await import('@/components/primitives')).PrimitivesShowcase }) },
      { path: '*', element: <Navigate replace to="/agent" /> },
    ],
  },
]);

export function RouteLoading() {
  const slow = useSlowLoadingNotice();

  return (
    <main className="shell-route-loading" aria-live="polite" role="status">
      {slow ? (
        <div className="shell-route-loading__slow">
          <strong>打开得有点久</strong>
          <span>界面仍在载入，连接不稳定时可能需要更久。可以继续等待，或重新载入。</span>
          <Button onClick={() => window.location.reload()} variant="primary">
            重新载入
          </Button>
        </div>
      ) : (
        <>
          <LoaderCircle aria-hidden="true" className="ui-spin" size={20} />
          <span>正在打开</span>
        </>
      )}
    </main>
  );
}

export function RouteErrorBoundary() {
  const navigate = useNavigate();
  const retryRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    retryRef.current?.focus({ preventScroll: true });
  }, []);

  return (
    <main className="shell-route-error">
      <div className="shell-route-error__surface" role="alert">
        <span className="shell-route-error__icon" aria-hidden="true">
          <AlertTriangle size={20} />
        </span>
        <div className="shell-route-error__copy">
          <h1>页面没有打开</h1>
          <p>这次打开没有完成，你的数据未受影响。可以重新打开，或先返回概览。</p>
        </div>
        <div className="shell-route-error__actions">
          <Button
            leadingIcon={<RotateCcw size={16} />}
            onClick={() => navigate(0)}
            ref={retryRef}
            variant="primary"
          >
            重新打开
          </Button>
          <Button onClick={() => navigate('/overview', { replace: true })}>
            返回概览
          </Button>
        </div>
      </div>
    </main>
  );
}

function useSlowLoadingNotice(delayMs = 8_000): boolean {
  const [slow, setSlow] = useState(false);

  useEffect(() => {
    const timeout = window.setTimeout(() => setSlow(true), delayMs);
    return () => window.clearTimeout(timeout);
  }, [delayMs]);

  return slow;
}
