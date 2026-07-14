import { useQuery } from '@tanstack/react-query';
import { useControlTransport } from '@/app/control-transport';

export const configurationQueryKeys = {
  root: ['configuration'] as const,
  settings: () => [...configurationQueryKeys.root, 'settings'] as const,
  schema: () => [...configurationQueryKeys.root, 'schema'] as const,
  capabilities: () => [...configurationQueryKeys.root, 'capabilities'] as const,
};

export function useConfigurationQueries() {
  const transport = useControlTransport();
  const settings = useQuery({
    queryKey: configurationQueryKeys.settings(),
    queryFn: ({ signal }) => transport.request({ pathId: 'configuration.settings', signal }),
  });
  const schema = useQuery({
    queryKey: configurationQueryKeys.schema(),
    queryFn: ({ signal }) => transport.request({ pathId: 'configuration.schema', signal }),
    staleTime: 60_000,
  });
  const capabilities = useQuery({
    queryKey: configurationQueryKeys.capabilities(),
    queryFn: () => transport.capabilities(),
    staleTime: Infinity,
  });
  return { capabilities, schema, settings, transport, transportKind: transport.kind };
}
