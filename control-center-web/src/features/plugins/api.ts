import { useQuery } from '@tanstack/react-query';
import { useControlTransport } from '@/app/control-transport';

export const pluginQueryKeys = {
  root: ['plugins'] as const,
  catalog: () => [...pluginQueryKeys.root, 'catalog'] as const,
};

export function usePluginCatalog() {
  const transport = useControlTransport();
  const catalog = useQuery({
    queryKey: pluginQueryKeys.catalog(),
    queryFn: ({ signal }) => transport.request({ pathId: 'agent.tools.list', signal }),
    staleTime: 30_000,
  });
  return { catalog, transportKind: transport.kind };
}
