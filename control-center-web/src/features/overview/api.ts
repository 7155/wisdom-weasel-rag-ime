import { useQuery } from '@tanstack/react-query';
import { useControlTransport } from '@/app/control-transport';

export const overviewQueryKeys = {
  root: ['overview'] as const,
  snapshot: () => [...overviewQueryKeys.root, 'snapshot'] as const,
  health: () => [...overviewQueryKeys.root, 'health'] as const,
  agentRuntime: () => [...overviewQueryKeys.root, 'agent-runtime'] as const,
  models: () => [...overviewQueryKeys.root, 'models'] as const,
  knowledgeRoute: () => [...overviewQueryKeys.root, 'knowledge-route'] as const,
};

export function useOverviewQueries() {
  const transport = useControlTransport();
  const snapshot = useQuery({
    queryKey: overviewQueryKeys.snapshot(),
    queryFn: ({ signal }) => transport.request({ pathId: 'overview.get', signal }),
    refetchInterval: 15_000,
  });
  const health = useQuery({
    queryKey: overviewQueryKeys.health(),
    queryFn: ({ signal }) => transport.request({ pathId: 'system.health', signal }),
    refetchInterval: 15_000,
  });
  const agentRuntime = useQuery({
    queryKey: overviewQueryKeys.agentRuntime(),
    queryFn: ({ signal }) => transport.request({ pathId: 'agent.runtime.get', signal }),
    refetchInterval: 15_000,
  });
  const models = useQuery({
    queryKey: overviewQueryKeys.models(),
    queryFn: ({ signal }) => transport.request({ pathId: 'diagnostics.models', signal }),
    staleTime: 30_000,
  });
  const knowledgeRoute = useQuery({
    queryKey: overviewQueryKeys.knowledgeRoute(),
    queryFn: ({ signal }) => transport.request({ pathId: 'knowledge.routeStatus', signal }),
    staleTime: 30_000,
  });
  return { agentRuntime, health, knowledgeRoute, models, snapshot, transportKind: transport.kind };
}
