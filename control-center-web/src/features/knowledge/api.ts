import { useQuery } from '@tanstack/react-query';
import { useControlTransport } from '@/app/control-transport';

export const knowledgeQueryKeys = {
  root: ['knowledge'] as const,
  route: () => [...knowledgeQueryKeys.root, 'route-status'] as const,
  session: (sessionId: string) => [...knowledgeQueryKeys.root, 'session', sessionId] as const,
};

export function useKnowledgeQueries(sessionId: string) {
  const transport = useControlTransport();
  const route = useQuery({
    queryKey: knowledgeQueryKeys.route(),
    queryFn: ({ signal }) => transport.request({ pathId: 'knowledge.routeStatus', signal }),
    staleTime: 20_000,
  });
  const session = useQuery({
    queryKey: knowledgeQueryKeys.session(sessionId),
    queryFn: ({ signal }) => transport.request({
      pathId: 'knowledge.status',
      query: sessionId ? { sessionId } : {},
      signal,
    }),
    refetchInterval: (query) => {
      const status = (query.state.data as { status?: unknown } | undefined)?.status;
      return ['queued', 'retrieving', 'generating', 'organizing'].includes(String(status)) ? 500 : false;
    },
  });
  return { route, session, transportKind: transport.kind };
}
