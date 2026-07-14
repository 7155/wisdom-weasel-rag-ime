import { useInfiniteQuery } from '@tanstack/react-query';
import { useControlTransport } from '@/app/control-transport';
import { asRecord, stringValue } from '@/features/overview/management-ui';

export const historyQueryKeys = {
  root: ['history'] as const,
  page: (query: string, filter: string) => [...historyQueryKeys.root, 'page', query, filter] as const,
};

export function useHistoryPages(query: string, filter: string) {
  const transport = useControlTransport();
  const pages = useInfiniteQuery({
    queryKey: historyQueryKeys.page(query, filter),
    queryFn: ({ pageParam, signal }) => transport.request({
      pathId: 'history.page',
      query: { limit: 50, cursor: String(pageParam), ...(query ? { query } : {}), ...(filter ? { filter } : {}) },
      signal,
    }),
    initialPageParam: '',
    getNextPageParam: (lastPage) => stringValue(asRecord(lastPage).nextCursor) || undefined,
  });
  return { pages, transportKind: transport.kind };
}
