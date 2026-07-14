import { useQuery } from '@tanstack/react-query';
import { useControlTransport } from '@/app/control-transport';

export const planningQueryKeys = {
  root: ['planning'] as const,
  dashboard: (date: string, project: string) => [...planningQueryKeys.root, 'dashboard', date, project] as const,
};

export function usePlanningDashboard(date: string, project = '') {
  const transport = useControlTransport();
  const dashboard = useQuery({
    queryKey: planningQueryKeys.dashboard(date, project),
    queryFn: ({ signal }) => transport.request({
      pathId: 'planning.dashboard',
      query: { ...(date ? { date } : {}), ...(project ? { project } : {}) },
      signal,
    }),
  });
  return { dashboard, transportKind: transport.kind };
}
