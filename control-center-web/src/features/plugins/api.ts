import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useControlTransport } from '@/app/control-transport';

export const pluginQueryKeys = {
  root: ['plugins'] as const,
  catalog: () => [...pluginQueryKeys.root, 'catalog'] as const,
  installed: () => [...pluginQueryKeys.root, 'installed'] as const,
  proposals: () => [...pluginQueryKeys.root, 'proposals'] as const,
};

export function usePluginCatalog() {
  const transport = useControlTransport();
  const catalog = useQuery({
    queryKey: pluginQueryKeys.catalog(),
    queryFn: ({ signal }) => transport.request({ pathId: 'agent.tools.list', signal }),
    staleTime: 30_000,
  });
  const installed = useQuery({
    queryKey: pluginQueryKeys.installed(),
    queryFn: ({ signal }) => transport.request({ pathId: 'agent.extensions.list', signal }),
    staleTime: 5_000,
  });
  const proposals = useQuery({
    queryKey: pluginQueryKeys.proposals(),
    queryFn: ({ signal }) => transport.request({ pathId: 'agent.extensions.proposals', signal }),
    refetchInterval: 5_000,
  });
  const queryClient = useQueryClient();
  const validate = useMutation({
    mutationFn: (body: { sourcePath: string }) => transport.request({ pathId: 'agent.extensions.validate', body }),
  });
  const preview = useMutation({
    mutationFn: (body: { action: string; validationToken?: string; pluginId?: string; enable?: boolean }) => (
      transport.request({ pathId: 'agent.extensions.preview', body })
    ),
  });
  const apply = useMutation({
    mutationFn: (body: { previewToken: string; payloadSha256: string; confirmText: string }) => (
      transport.request({ pathId: 'agent.extensions.apply', body })
    ),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: pluginQueryKeys.installed() }),
        queryClient.invalidateQueries({ queryKey: pluginQueryKeys.proposals() }),
        queryClient.invalidateQueries({ queryKey: pluginQueryKeys.catalog() }),
      ]);
    },
  });
  return { catalog, installed, proposals, validate, preview, apply, transport };
}
