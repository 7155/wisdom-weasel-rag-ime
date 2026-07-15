import { useQuery } from '@tanstack/react-query';
import { useControlTransport } from '@/app/control-transport';

export const voiceQueryKeys = {
  root: ['voice'] as const,
  settings: () => [...voiceQueryKeys.root, 'settings'] as const,
  schema: () => [...voiceQueryKeys.root, 'schema'] as const,
  runtime: () => [...voiceQueryKeys.root, 'runtime'] as const,
  tools: () => [...voiceQueryKeys.root, 'tools'] as const,
  capabilities: () => [...voiceQueryKeys.root, 'capabilities'] as const,
};

export function useVoiceQueries() {
  const transport = useControlTransport();
  const settings = useQuery({
    queryKey: voiceQueryKeys.settings(),
    queryFn: ({ signal }) => transport.request({ pathId: 'configuration.settings', signal }),
  });
  const schema = useQuery({
    queryKey: voiceQueryKeys.schema(),
    queryFn: ({ signal }) => transport.request({ pathId: 'configuration.schema', signal }),
  });
  const runtime = useQuery({
    queryKey: voiceQueryKeys.runtime(),
    queryFn: ({ signal }) => transport.request({ pathId: 'diagnostics.runtime', signal }),
    refetchInterval: 10_000,
  });
  const capabilities = useQuery({
    queryKey: voiceQueryKeys.capabilities(),
    queryFn: () => transport.capabilities(),
    staleTime: Infinity,
  });
  const tools = useQuery({
    queryKey: voiceQueryKeys.tools(),
    queryFn: ({ signal }) => transport.request({ pathId: 'agent.tools.list', signal }),
    enabled: capabilities.data?.routeIds.includes('agent.tools.list') === true,
    staleTime: 30_000,
  });
  return { capabilities, runtime, schema, settings, tools, transportKind: transport.kind };
}
