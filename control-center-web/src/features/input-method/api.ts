import { useQuery } from '@tanstack/react-query';
import { useControlTransport } from '@/app/control-transport';

export const inputMethodQueryKeys = {
  root: ['input-method'] as const,
  source: () => [...inputMethodQueryKeys.root, 'source'] as const,
  overview: () => [...inputMethodQueryKeys.root, 'overview'] as const,
  settings: () => [...inputMethodQueryKeys.root, 'settings'] as const,
  schema: () => [...inputMethodQueryKeys.root, 'schema'] as const,
};

export function useInputMethodQueries() {
  const transport = useControlTransport();
  const source = useQuery({
    queryKey: inputMethodQueryKeys.source(),
    queryFn: ({ signal }) => transport.request({ pathId: 'input.source.get', signal }),
    refetchInterval: 10_000,
  });
  const overview = useQuery({
    queryKey: inputMethodQueryKeys.overview(),
    queryFn: ({ signal }) => transport.request({ pathId: 'overview.get', signal }),
  });
  const settings = useQuery({
    queryKey: inputMethodQueryKeys.settings(),
    queryFn: ({ signal }) => transport.request({ pathId: 'configuration.settings', signal }),
  });
  const schema = useQuery({
    queryKey: inputMethodQueryKeys.schema(),
    queryFn: ({ signal }) => transport.request({ pathId: 'configuration.schema', signal }),
  });
  return { overview, schema, settings, source, transportKind: transport.kind };
}
