import { useQuery } from '@tanstack/react-query';
import { useControlTransport } from '@/app/control-transport';

export const diagnosticsQueryKeys = {
  root: ['diagnostics'] as const,
  runtime: () => [...diagnosticsQueryKeys.root, 'runtime'] as const,
  predictor: () => [...diagnosticsQueryKeys.root, 'predictor'] as const,
  models: () => [...diagnosticsQueryKeys.root, 'models'] as const,
  source: () => [...diagnosticsQueryKeys.root, 'input-source'] as const,
  capabilities: () => [...diagnosticsQueryKeys.root, 'capabilities'] as const,
};

export function useDiagnosticsQueries() {
  const transport = useControlTransport();
  const runtime = useQuery({
    queryKey: diagnosticsQueryKeys.runtime(),
    queryFn: ({ signal }) => transport.request({ pathId: 'diagnostics.runtime', signal }),
    refetchInterval: 10_000,
  });
  const predictor = useQuery({
    queryKey: diagnosticsQueryKeys.predictor(),
    queryFn: ({ signal }) => transport.request({ pathId: 'diagnostics.predictor', signal }),
    staleTime: 10_000,
  });
  const models = useQuery({
    queryKey: diagnosticsQueryKeys.models(),
    queryFn: ({ signal }) => transport.request({ pathId: 'diagnostics.models', signal }),
    staleTime: 10_000,
  });
  const source = useQuery({
    queryKey: diagnosticsQueryKeys.source(),
    queryFn: ({ signal }) => transport.request({ pathId: 'input.source.get', signal }),
    refetchInterval: 10_000,
  });
  const capabilities = useQuery({
    queryKey: diagnosticsQueryKeys.capabilities(),
    queryFn: () => transport.capabilities(),
    staleTime: Infinity,
  });
  return { capabilities, models, predictor, runtime, source, transport, transportKind: transport.kind };
}
