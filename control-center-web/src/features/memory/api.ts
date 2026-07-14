import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import { useControlTransport } from '@/app/control-transport';
import { asRecord, stringValue } from '@/features/overview/management-ui';

export type MemoryKind = 'books' | 'atoms' | 'tags' | 'phrases' | 'groups' | 'negative';

export const memoryQueryKeys = {
  root: ['memory'] as const,
  summary: () => [...memoryQueryKeys.root, 'summary'] as const,
  page: (kind: MemoryKind, query: string, status: string) => [...memoryQueryKeys.root, 'page', kind, query, status] as const,
  graphPage: (kind: 'groups' | 'tags') => [...memoryQueryKeys.root, 'graph', kind] as const,
};

export function useMemoryQueries(kind: MemoryKind, query: string, status: string) {
  const transport = useControlTransport();
  const summary = useQuery({
    queryKey: memoryQueryKeys.summary(),
    queryFn: ({ signal }) => transport.request({ pathId: 'memory.summary', signal }),
  });
  const pages = useInfiniteQuery({
    queryKey: memoryQueryKeys.page(kind, query, status),
    queryFn: ({ pageParam, signal }) => transport.request({
      pathId: 'memory.pages',
      params: { kind },
      query: { limit: 50, cursor: String(pageParam), ...(query ? { query } : {}), ...(status ? { status } : {}) },
      signal,
    }),
    initialPageParam: '',
    getNextPageParam: (lastPage) => stringValue(asRecord(lastPage).nextCursor) || undefined,
  });
  return { pages, summary, transportKind: transport.kind };
}

export function useMemoryGraphQueries(enabled: boolean) {
  const transport = useControlTransport();
  const tags = useQuery({
    enabled,
    queryKey: memoryQueryKeys.graphPage('tags'),
    queryFn: ({ signal }) => transport.request({
      pathId: 'memory.pages',
      params: { kind: 'tags' },
      query: { limit: 50, cursor: '' },
      signal,
    }),
  });
  const groups = useQuery({
    enabled,
    queryKey: memoryQueryKeys.graphPage('groups'),
    queryFn: ({ signal }) => transport.request({
      pathId: 'memory.pages',
      params: { kind: 'groups' },
      query: { limit: 50, cursor: '' },
      signal,
    }),
  });
  return { groups, tags };
}
