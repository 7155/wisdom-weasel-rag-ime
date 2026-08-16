import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useControlTransport } from '@/app/control-transport';
import {
  parseCapabilityDefaults,
  requireCapabilityCatalog,
  requireSessionCapabilityCatalog,
  type CapabilityPreference,
} from './capability-policy';

export const pluginQueryKeys = {
  root: ['plugins'] as const,
  catalog: (sessionId = '') => [...pluginQueryKeys.root, 'catalog', sessionId] as const,
  defaults: () => [...pluginQueryKeys.root, 'defaults'] as const,
  installed: () => [...pluginQueryKeys.root, 'installed'] as const,
  versions: () => [...pluginQueryKeys.root, 'versions'] as const,
  proposals: () => [...pluginQueryKeys.root, 'proposals'] as const,
  lifecycle: () => [...pluginQueryKeys.root, 'lifecycle'] as const,
};

export function usePluginCatalog(sessionId = '') {
  const transport = useControlTransport();
  const catalog = useQuery({
    queryKey: pluginQueryKeys.catalog(sessionId),
    queryFn: async ({ signal }) => {
      const response = await transport.request({
        pathId: 'agent.tools.list',
        ...(sessionId ? { query: { sessionId } } : {}),
        signal,
      });
      return sessionId
        ? requireSessionCapabilityCatalog(response, sessionId)
        : requireCapabilityCatalog(response);
    },
    staleTime: 30_000,
    refetchOnReconnect: 'always',
  });
  const defaults = useQuery({
    queryKey: pluginQueryKeys.defaults(),
    queryFn: async ({ signal }) => {
      const response = await transport.request({ pathId: 'agent.configuration.get', signal });
      const parsed = parseCapabilityDefaults(response);
      if (!parsed) throw new Error('默认能力设置版本未知，当前设置不会被猜测或修改。');
      return parsed;
    },
    staleTime: 30_000,
    refetchOnReconnect: 'always',
  });
  const installed = useQuery({
    queryKey: pluginQueryKeys.installed(),
    queryFn: ({ signal }) => transport.request({ pathId: 'agent.extensions.list', signal }),
    staleTime: 5_000,
  });
  const versions = useQuery({
    queryKey: pluginQueryKeys.versions(),
    queryFn: ({ signal }) => transport.request({ pathId: 'agent.extensions.catalog', signal }),
    staleTime: 30_000,
  });
  const proposals = useQuery({
    queryKey: pluginQueryKeys.proposals(),
    queryFn: ({ signal }) => transport.request({ pathId: 'agent.extensions.proposals', signal }),
    refetchInterval: 5_000,
  });
  const queryClient = useQueryClient();
  const validate = useMutation({
    mutationFn: (body: { sourcePath?: string; packageSource?: string; catalogId?: string; catalogVersion?: string }) => transport.request({ pathId: 'agent.extensions.validate', body }),
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
        queryClient.invalidateQueries({ queryKey: pluginQueryKeys.catalog(sessionId) }),
      ]);
    },
  });
  const updateDefaults = useMutation({
    mutationFn: (input: {
      expectedRevision: number;
      preferences: Record<string, CapabilityPreference>;
    }) => transport.request({
      pathId: 'agent.configuration.update',
      body: {
        expectedRevision: input.expectedRevision,
        changes: {
          'sessionDefaults.capabilityDisclosurePreferences': input.preferences,
        },
        updatedBy: 'capability-settings-ui',
      },
    }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: pluginQueryKeys.catalog(sessionId) }),
        queryClient.invalidateQueries({ queryKey: pluginQueryKeys.defaults() }),
      ]);
    },
  });
  const updateProjectDefaults = useMutation({
    mutationFn: (input: {
      expectedRevision: number;
      projectPreferences: Record<string, Record<string, CapabilityPreference>>;
    }) => transport.request({
      pathId: 'agent.configuration.update',
      body: {
        expectedRevision: input.expectedRevision,
        changes: {
          'capabilityDisclosure.projectPreferences': input.projectPreferences,
        },
        updatedBy: 'capability-settings-ui',
      },
    }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: pluginQueryKeys.catalog(sessionId) }),
        queryClient.invalidateQueries({ queryKey: pluginQueryKeys.defaults() }),
      ]);
    },
  });
  const lifecycle = useQuery({
    queryKey: pluginQueryKeys.lifecycle(),
    queryFn: ({ signal }) => transport.request({ pathId: 'agent.lifecycleHooks.get', query: { limit: 20 }, signal }),
    staleTime: 5_000,
  });
  const updateLifecycle = useMutation({
    mutationFn: (body: { eventType: string; enabled?: boolean; tokenLimit?: number; cooldownSeconds?: number }) => (
      transport.request({ pathId: 'agent.lifecycleHooks.update', body })
    ),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: pluginQueryKeys.lifecycle() });
    },
  });
  const refreshAll = async () => {
    await Promise.all([
      catalog.refetch(),
      defaults.refetch(),
      installed.refetch(),
      versions.refetch(),
      proposals.refetch(),
      lifecycle.refetch(),
    ]);
  };
  return {
    catalog,
    defaults,
    installed,
    versions,
    proposals,
    lifecycle,
    validate,
    preview,
    apply,
    updateDefaults,
    updateProjectDefaults,
    updateLifecycle,
    refreshAll,
    transport,
  };
}
