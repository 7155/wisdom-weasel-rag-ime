import { useQuery } from '@tanstack/react-query';
import { useControlTransport } from '@/app/control-transport';
import type { VoiceProviderId } from '@/platform/transport';

export const voiceQueryKeys = {
  root: ['voice'] as const,
  settings: () => [...voiceQueryKeys.root, 'settings'] as const,
  schema: () => [...voiceQueryKeys.root, 'schema'] as const,
  runtime: () => [...voiceQueryKeys.root, 'runtime'] as const,
  capabilities: () => [...voiceQueryKeys.root, 'capabilities'] as const,
  models: () => [...voiceQueryKeys.root, 'pi-models'] as const,
  credentials: (provider: VoiceProviderId) => [...voiceQueryKeys.root, 'credentials', provider] as const,
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
  const modelCatalogSupported = Boolean(
    capabilities.data?.routeIds?.includes('agent.role.models'),
  );
  const modelCatalog = useQuery({
    queryKey: voiceQueryKeys.models(),
    queryFn: ({ signal }) => transport.request({ pathId: 'agent.role.models', signal }),
    enabled: modelCatalogSupported,
    staleTime: 0,
  });
  return {
    capabilities,
    modelCatalog,
    modelCatalogSupported,
    runtime,
    schema,
    settings,
    transport,
    transportKind: transport.kind,
  };
}

export function useVoiceCredentialStatus(provider: VoiceProviderId) {
  const transport = useControlTransport();
  const capabilities = useQuery({
    queryKey: voiceQueryKeys.capabilities(),
    queryFn: () => transport.capabilities(),
    staleTime: Infinity,
  });
  const supported = capabilities.data?.native.keychain === true
    && typeof transport.voiceCredentialStatus === 'function';
  const status = useQuery({
    queryKey: voiceQueryKeys.credentials(provider),
    queryFn: () => transport.voiceCredentialStatus!(provider),
    enabled: supported,
  });
  return { capabilities, status, supported, transport };
}
