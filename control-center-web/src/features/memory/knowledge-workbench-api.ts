import { useQuery } from '@tanstack/react-query';
import { useControlTransport } from '@/app/control-transport';
import type { MutationAvailability } from '@/features/overview/management-mutation';
import type { ControlTransport, JsonValue } from '@/platform/transport';

export const knowledgeQueryKeys = {
  root: ['knowledge'] as const,
  route: () => [...knowledgeQueryKeys.root, 'route-status'] as const,
  session: (sessionId: string) => [...knowledgeQueryKeys.root, 'session', sessionId] as const,
  capabilities: () => [...knowledgeQueryKeys.root, 'capabilities'] as const,
};

export const knowledgeMutationPathIds = {
  start: 'knowledge.start',
  cancel: 'knowledge.cancel',
  databaseDraftEdit: 'knowledge.database.draft.edit',
  databaseApplyPreview: 'knowledge.database.apply.preview',
  databaseApply: 'knowledge.database.apply',
  databaseRollback: 'knowledge.database.rollback',
} as const;

export type KnowledgeMutationPathId = (typeof knowledgeMutationPathIds)[keyof typeof knowledgeMutationPathIds];

export type KnowledgeMutationRequest = {
  pathId: KnowledgeMutationPathId;
  body: Record<string, JsonValue>;
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
    enabled: Boolean(sessionId),
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

export function useKnowledgeMutationBoundary() {
  const transport = useControlTransport();
  const capabilities = useQuery({
    queryKey: knowledgeQueryKeys.capabilities(),
    queryFn: () => transport.capabilities(),
    staleTime: 30_000,
  });

  const routeAvailability = (
    pathIds: readonly KnowledgeMutationPathId[],
    blockedReason = '',
  ): MutationAvailability => {
    if (capabilities.isPending) return { state: 'checking' };
    if (capabilities.error) return { state: 'unsupported', reason: '无法确认当前操作是否可用，请刷新后重试。' };
    const routeIds = new Set((capabilities.data?.routeIds ?? []) as readonly string[]);
    if (pathIds.some((pathId) => !routeIds.has(pathId))) {
      return { state: 'unsupported', reason: '当前版本还不能启动或取消知识任务；没有请求被发送。' };
    }
    if (blockedReason) return { state: 'blocked', reason: blockedReason };
    return { state: 'available' };
  };

  const databaseAvailability = (blockedReason = ''): MutationAvailability => {
    const routeState = routeAvailability([
      knowledgeMutationPathIds.databaseDraftEdit,
      knowledgeMutationPathIds.databaseApplyPreview,
      knowledgeMutationPathIds.databaseApply,
      knowledgeMutationPathIds.databaseRollback,
    ]);
    if (routeState.state !== 'available') return routeState;
    const flags = capabilities.data?.features ?? {};
    if (!flags.managementWorkContract || !flags.knowledgeDatabaseWorkContract) {
      return { state: 'unsupported', reason: '当前版本还不能安全应用知识库整理草案；没有请求被发送。' };
    }
    return blockedReason ? { state: 'blocked', reason: blockedReason } : routeState;
  };

  return {
    capabilities,
    databaseAvailability,
    routeAvailability,
    request: <Response,>(request: KnowledgeMutationRequest) => requestKnowledgeMutation<Response>(transport, request),
  };
}

export function requestKnowledgeMutation<Response>(
  transport: ControlTransport,
  request: KnowledgeMutationRequest,
): Promise<Response> {
  return transport.request<Response>({
    pathId: request.pathId,
    body: request.body,
  });
}
