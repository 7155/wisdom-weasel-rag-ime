import { useInfiniteQuery, useMutation, useQuery } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import { useControlTransport } from '@/app/control-transport';
import type { MutationAvailability } from '@/features/overview/management-mutation';
import { asRecord, stringValue } from '@/features/overview/management-ui';
import type { ControlTransport, JsonValue } from '@/platform/transport';

export type MemoryKind =
  | 'apps'
  | 'books'
  | 'atoms'
  | 'tags'
  | 'phrases'
  | 'evidence'
  | 'groups'
  | 'negative';
export type MemoryEntityKind = 'tag' | 'group' | 'book';

export const memoryQueryKeys = {
  root: ['memory'] as const,
  summary: () => [...memoryQueryKeys.root, 'summary'] as const,
  page: (
    kind: MemoryKind,
    query: string,
    status: string,
    ownerKind: string,
    ownerId: string,
  ) => [...memoryQueryKeys.root, 'page', kind, query, status, ownerKind, ownerId] as const,
  graph: (plane: 'groups' | 'tags', query: string, focusId: string) => [
    ...memoryQueryKeys.root,
    'graph',
    plane,
    query,
    focusId,
  ] as const,
  entity: (kind: MemoryEntityKind, entityId: string) => [...memoryQueryKeys.root, 'entity', kind, entityId] as const,
  curationStatus: () => [...memoryQueryKeys.root, 'curation-status'] as const,
  curationRun: (runId: string) => [...memoryQueryKeys.root, 'curation-run', runId] as const,
  capabilities: () => [...memoryQueryKeys.root, 'capabilities'] as const,
};

export const memoryBookArchivePathIds = {
  preview: 'memory.book.archive.preview',
  apply: 'memory.book.archive.apply',
  rollback: 'memory.book.archive.rollback',
} as const;

export type MemoryBookArchivePathId = (typeof memoryBookArchivePathIds)[keyof typeof memoryBookArchivePathIds];

export type MemoryBookArchiveRequest = {
  pathId: MemoryBookArchivePathId;
  body: Record<string, JsonValue>;
};

export function useMemoryQueries(
  kind: MemoryKind,
  query: string,
  status: string,
  ownerKind = '',
  ownerId = '',
) {
  const transport = useControlTransport();
  const summary = useQuery({
    queryKey: memoryQueryKeys.summary(),
    queryFn: ({ signal }) => transport.request({ pathId: 'memory.summary', signal }),
  });
  const pages = useInfiniteQuery({
    queryKey: memoryQueryKeys.page(kind, query, status, ownerKind, ownerId),
    queryFn: ({ pageParam, signal }) => transport.request({
      pathId: 'memory.pages',
      params: { kind },
      query: {
        limit: 50,
        cursor: String(pageParam),
        ...(query ? { query } : {}),
        ...(status ? { status } : {}),
        ...(ownerKind && ownerId ? { ownerKind, ownerId } : {}),
      },
      signal,
    }),
    initialPageParam: '',
    getNextPageParam: (lastPage) => stringValue(asRecord(lastPage).nextCursor) || undefined,
  });
  return { pages, summary, transportKind: transport.kind };
}

export function useMemoryGraphQueries(
  enabled: boolean,
  options: {
    query?: string;
    tagFocusId?: string;
    groupFocusId?: string;
  } = {},
) {
  const transport = useControlTransport();
  const query = boundedQuery(options.query, 200);
  // A text search and a focused-neighborhood lookup are distinct backend
  // operations. Search wins so a previously selected node cannot turn a new
  // query into a misleading "not found" response.
  const tagFocusId = query ? '' : boundedQuery(options.tagFocusId, 128);
  const groupFocusId = query ? '' : boundedQuery(options.groupFocusId, 128);
  const tags = useQuery({
    enabled,
    placeholderData: (previousData) => previousData,
    queryKey: memoryQueryKeys.graph('tags', query, tagFocusId),
    queryFn: ({ signal }) => transport.request({
      pathId: 'memory.graph.get',
      query: {
        plane: 'tags',
        status: 'active',
        ...(query ? { query } : {}),
        ...(tagFocusId ? { focusId: tagFocusId } : {}),
        depth: 1,
        nodeLimit: query ? 120 : 32,
        edgeLimit: query ? 500 : 150,
        minWeight: 0,
      },
      signal,
    }),
  });
  const groups = useQuery({
    enabled,
    placeholderData: (previousData) => previousData,
    queryKey: memoryQueryKeys.graph('groups', query, groupFocusId),
    queryFn: ({ signal }) => transport.request({
      pathId: 'memory.graph.get',
      query: {
        plane: 'groups',
        status: 'active',
        ...(query ? { query } : {}),
        ...(groupFocusId ? { focusId: groupFocusId } : {}),
        depth: 1,
        nodeLimit: query ? 120 : 48,
        edgeLimit: query ? 500 : 160,
        minWeight: 0,
      },
      signal,
    }),
  });
  return { groups, tags };
}

export function useMemoryCurationQueries(enabled: boolean) {
  const transport = useControlTransport();
  const status = useQuery({
    enabled,
    queryKey: memoryQueryKeys.curationStatus(),
    queryFn: ({ signal }) => transport.request({
      pathId: 'agent.memoryMaintenance.run',
      query: { limit: 12 },
      signal,
    }),
  });
  const statusPayload = asRecord(status.data);
  const runs = Array.isArray(statusPayload.runs)
    ? statusPayload.runs.map(asRecord)
    : [];
  const latest = runs.find((item) => stringValue(item.status) === 'draft') ?? runs[0];
  const runId = stringValue(latest?.runId);
  const run = useQuery({
    enabled: enabled && Boolean(runId),
    queryKey: memoryQueryKeys.curationRun(runId),
    queryFn: ({ signal }) => transport.request({
      pathId: 'agent.memoryMaintenance.run',
      query: { runId },
      signal,
    }),
  });
  return { run, runId, status };
}

export function useMemoryEntityQuery(
  kind: MemoryEntityKind,
  entityId: string,
  enabled: boolean,
) {
  const transport = useControlTransport();
  const identity = `${kind}:${entityId}`;
  const [pagination, setPagination] = useState<EntityPaginationState>({ identity });
  const query = useQuery({
    enabled: enabled && Boolean(entityId),
    queryKey: memoryQueryKeys.entity(kind, entityId),
    queryFn: ({ signal }) => transport.request({
      pathId: 'memory.entity.get',
      params: { kind, entityId },
      query: { connectionsLimit: 40, membersLimit: 40 },
      signal,
    }),
  });
  const activePagination = pagination.identity === identity
    ? pagination
    : { identity };
  const baseConnections = entityPage(query.data, 'connections');
  const baseMembers = entityPage(query.data, 'members');
  const connectionCursor = activePagination.connections?.nextCursor ?? baseConnections.nextCursor;
  const memberCursor = activePagination.members?.nextCursor ?? baseMembers.nextCursor;

  const connectionPagination = useMutation({
    mutationKey: [...memoryQueryKeys.entity(kind, entityId), 'connections'],
    mutationFn: () => requestMemoryEntityPage(
      transport,
      kind,
      entityId,
      'connections',
      connectionCursor,
    ),
    onSuccess: (payload) => {
      const page = entityPage(payload, 'connections');
      setPagination((current) => {
        const previous = current.identity === identity ? current.connections : undefined;
        return {
          ...(current.identity === identity ? current : { identity }),
          connections: {
            items: [...(previous?.items ?? []), ...page.items],
            nextCursor: page.nextCursor,
            hasMore: page.hasMore,
          },
        };
      });
    },
  });
  const memberPagination = useMutation({
    mutationKey: [...memoryQueryKeys.entity(kind, entityId), 'members'],
    mutationFn: () => requestMemoryEntityPage(
      transport,
      kind,
      entityId,
      'members',
      memberCursor,
    ),
    onSuccess: (payload) => {
      const page = entityPage(payload, 'members');
      setPagination((current) => {
        const previous = current.identity === identity ? current.members : undefined;
        return {
          ...(current.identity === identity ? current : { identity }),
          members: {
            items: [...(previous?.items ?? []), ...page.items],
            nextCursor: page.nextCursor,
            hasMore: page.hasMore,
          },
        };
      });
    },
  });
  const data = useMemo(
    () => mergeEntityPages(query.data, activePagination),
    [activePagination, query.data],
  );

  return {
    ...query,
    data,
    connectionLoadError: connectionPagination.error,
    fetchNextConnections: () => connectionPagination.mutateAsync(),
    fetchNextMembers: () => memberPagination.mutateAsync(),
    isFetchingNextConnections: connectionPagination.isPending,
    isFetchingNextMembers: memberPagination.isPending,
    memberLoadError: memberPagination.error,
  };
}

interface EntityPageSlice {
  items: unknown[];
  nextCursor: string;
  hasMore: boolean;
}

interface EntityPaginationState {
  identity: string;
  connections?: EntityPageSlice;
  members?: EntityPageSlice;
}

function boundedQuery(value: unknown, maximum: number): string {
  return typeof value === 'string' ? value.trim().slice(0, maximum) : '';
}

function entityPage(payload: unknown, key: 'connections' | 'members'): EntityPageSlice {
  const page = asRecord(asRecord(payload)[key]);
  const nextCursor = stringValue(page.nextCursor);
  return {
    items: Array.isArray(page.items) ? page.items : [],
    nextCursor,
    hasMore: page.hasMore === true && Boolean(nextCursor),
  };
}

function mergeEntityPages(payload: unknown, pagination: EntityPaginationState): unknown {
  if (!payload || (!pagination.connections && !pagination.members)) return payload;
  const root = asRecord(payload);
  const merged: Record<string, unknown> = { ...root };
  for (const key of ['connections', 'members'] as const) {
    const extra = pagination[key];
    if (!extra) continue;
    const initial = asRecord(root[key]);
    merged[key] = {
      ...initial,
      items: [
        ...(Array.isArray(initial.items) ? initial.items : []),
        ...extra.items,
      ],
      nextCursor: extra.nextCursor,
      hasMore: extra.hasMore,
    };
  }
  return merged;
}

function requestMemoryEntityPage(
  transport: ControlTransport,
  kind: MemoryEntityKind,
  entityId: string,
  page: 'connections' | 'members',
  cursor: string,
): Promise<unknown> {
  if (!cursor) return Promise.reject(new Error('No additional entity page is available'));
  return transport.request({
    pathId: 'memory.entity.get',
    params: { kind, entityId },
    query: page === 'connections'
      ? { connectionsLimit: 40, connectionsCursor: cursor, membersLimit: 1 }
      : { connectionsLimit: 1, membersLimit: 40, membersCursor: cursor },
  });
}

export function useMemoryBookArchiveBoundary() {
  const transport = useControlTransport();
  const capabilities = useQuery({
    queryKey: memoryQueryKeys.capabilities(),
    queryFn: () => transport.capabilities(),
    staleTime: 30_000,
  });

  const availability = (blockedReason = ''): MutationAvailability => {
    if (capabilities.isPending) return { state: 'checking' };
    if (capabilities.error) {
      return { state: 'unsupported', reason: '无法确认记忆管理能力，请刷新后重试。' };
    }
    const routeIds = new Set((capabilities.data?.routeIds ?? []) as readonly string[]);
    const required = Object.values(memoryBookArchivePathIds);
    if (required.some((pathId) => !routeIds.has(pathId))) {
      return {
        state: 'unsupported',
        reason: '当前服务尚未开放主题记忆的可回滚归档；不会发送写入请求。',
      };
    }
    if (blockedReason) return { state: 'blocked', reason: blockedReason };
    return { state: 'available' };
  };

  return {
    availability,
    capabilities,
    request: <Response,>(request: MemoryBookArchiveRequest) => requestMemoryBookArchive<Response>(transport, request),
  };
}

export function requestMemoryBookArchive<Response>(
  transport: ControlTransport,
  request: MemoryBookArchiveRequest,
): Promise<Response> {
  return transport.request<Response>({ pathId: request.pathId, body: request.body });
}
