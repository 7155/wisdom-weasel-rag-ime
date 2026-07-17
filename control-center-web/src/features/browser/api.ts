import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useControlTransport } from '@/app/control-transport';

export const browserQueryKeys = {
  root: ['browser'] as const,
  status: () => [...browserQueryKeys.root, 'status'] as const,
  pairing: () => [...browserQueryKeys.root, 'pairing'] as const,
  tabs: () => [...browserQueryKeys.root, 'tabs'] as const,
  snapshot: (deviceId: string, tabId: number) => [...browserQueryKeys.root, 'snapshot', deviceId, tabId] as const,
  permissions: () => [...browserQueryKeys.root, 'permissions'] as const,
  traces: () => [...browserQueryKeys.root, 'traces'] as const,
};

export function useBrowserControl(deviceId: string, tabId: number) {
  const transport = useControlTransport();
  const queryClient = useQueryClient();
  const invalidate = async () => {
    await queryClient.invalidateQueries({ queryKey: browserQueryKeys.root });
  };
  const status = useQuery({
    queryKey: browserQueryKeys.status(),
    queryFn: ({ signal }) => transport.request({ pathId: 'browser.status', signal }),
    refetchInterval: 2_000,
  });
  const pairing = useQuery({
    queryKey: browserQueryKeys.pairing(),
    queryFn: ({ signal }) => transport.request({ pathId: 'browser.pairing', signal }),
    staleTime: 30_000,
  });
  const tabs = useQuery({
    queryKey: browserQueryKeys.tabs(),
    queryFn: ({ signal }) => transport.request({ pathId: 'browser.tabs', signal }),
    refetchInterval: 2_500,
  });
  const snapshot = useQuery({
    enabled: Boolean(deviceId && tabId),
    queryKey: browserQueryKeys.snapshot(deviceId, tabId),
    queryFn: ({ signal }) => transport.request({
      pathId: 'browser.snapshot.latest',
      query: { deviceId, tabId, includeMarkdown: true },
      signal,
    }),
    refetchInterval: 3_000,
  });
  const permissions = useQuery({
    queryKey: browserQueryKeys.permissions(),
    queryFn: ({ signal }) => transport.request({
      pathId: 'browser.permissions',
      query: { limit: 100 },
      signal,
    }),
    refetchInterval: 2_000,
  });
  const traces = useQuery({
    queryKey: browserQueryKeys.traces(),
    queryFn: ({ signal }) => transport.request({
      pathId: 'browser.traces',
      query: { limit: 80 },
      signal,
    }),
    refetchInterval: 3_000,
  });
  const setMode = useMutation({
    mutationFn: (mode: 'observe' | 'codrive' | 'managed') => (
      transport.request({ pathId: 'browser.mode.update', body: { mode } })
    ),
    onSuccess: invalidate,
  });
  const rotatePairing = useMutation({
    mutationFn: () => transport.request({ pathId: 'browser.pairing.rotate', body: {} }),
    onSuccess: invalidate,
  });
  const runCommand = useMutation({
    mutationFn: (body: Record<string, string | number | boolean>) => (
      transport.request({ pathId: 'browser.command', body })
    ),
    onSuccess: invalidate,
  });
  const stop = useMutation({
    mutationFn: () => transport.request({ pathId: 'browser.stop', body: {} }),
    onSuccess: invalidate,
  });
  const startManaged = useMutation({
    mutationFn: () => transport.request({ pathId: 'browser.managed.start', body: {} }),
    onSuccess: invalidate,
  });
  const stopManaged = useMutation({
    mutationFn: () => transport.request({ pathId: 'browser.managed.stop', body: {} }),
    onSuccess: invalidate,
  });
  const decidePermission = useMutation({
    mutationFn: ({ promptId, decision }: { promptId: string; decision: 'allow_once' | 'allow_site' | 'deny' }) => (
      transport.request({
        pathId: 'browser.permission.decide',
        params: { promptId },
        body: { decision },
      })
    ),
    onSuccess: invalidate,
  });
  return {
    status,
    pairing,
    tabs,
    snapshot,
    permissions,
    traces,
    setMode,
    rotatePairing,
    runCommand,
    stop,
    startManaged,
    stopManaged,
    decidePermission,
    snapshotImageUrl: (snapshotId: string) => (
      transport.browserSnapshotImageUrl?.(snapshotId) ?? ''
    ),
  };
}
