import { QueryClient } from '@tanstack/react-query';

type QueryStatusProjection = { state: { status: string } };

export function transientControlErrorRefetchInterval(active: boolean) {
  return (query: QueryStatusProjection): number | false => (
    active && query.state.status === 'error' ? 4_000 : false
  );
}

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
      staleTime: 15_000,
    },
    mutations: {
      retry: false,
    },
  },
});
