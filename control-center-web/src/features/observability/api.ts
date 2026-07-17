import { useQuery } from '@tanstack/react-query';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useControlTransport } from '@/app/control-transport';
import type { ObservationEventV1 } from '@/contracts/generated/observation-event.v1';
import type { ObservationSnapshotV1 } from '@/contracts/generated/observation-snapshot.v1';
import type { UiObservationEvent } from '@/contracts/ui-events';
import type { ControlQueryValue } from '@/platform/transport';

export interface ObservationFilters {
  sessionId?: string;
  roomId?: string;
  traceId?: string;
  category?: ObservationEventV1['category'];
  status?: ObservationEventV1['status'];
}

export type ObservationConnectionState =
  | 'connecting'
  | 'live'
  | 'reconnecting'
  | 'offline';

export function useObservationFeed(filters: ObservationFilters) {
  const transport = useControlTransport();
  const [liveItems, setLiveItems] = useState<ObservationEventV1[]>([]);
  const [connection, setConnection] = useState<ObservationConnectionState>('connecting');
  const [streamError, setStreamError] = useState('');
  const filterKey = useMemo(() => JSON.stringify(filters), [filters]);
  const activeSubscription = useRef('');
  const snapshot = useQuery({
    queryKey: ['observability', 'snapshot', filterKey],
    queryFn: ({ signal }) => transport.request<ObservationSnapshotV1>({
      pathId: 'observability.snapshot',
      query: { limit: 300, ...queryFilters(filters) },
      responseContract: 'observation-snapshot.v1',
      signal,
    }),
    retry: false,
    refetchOnWindowFocus: false,
  });

  useEffect(() => {
    setLiveItems([]);
    setConnection('connecting');
    setStreamError('');
  }, [filterKey]);

  useEffect(() => {
    const cursor = snapshot.data?.resumeToken;
    if (!cursor) return;
    const subscriptionKey = `${filterKey}:${cursor}`;
    activeSubscription.current = subscriptionKey;
    const unsubscribe = transport.subscribe<UiObservationEvent>(
      {
        pathId: 'observability.events',
        query: queryFilters(filters),
        lastEventId: cursor,
      },
      {
        open: () => {
          if (activeSubscription.current !== subscriptionKey) return;
          setConnection('live');
          setStreamError('');
        },
        next: (event) => {
          if (
            activeSubscription.current !== subscriptionKey
            || event.eventType === 'snapshot_required'
          ) return;
          setLiveItems((current) => mergeObservationEvents(current, [event], 400));
        },
        reconnect: () => {
          if (activeSubscription.current !== subscriptionKey) return;
          setConnection('reconnecting');
        },
        error: () => {
          if (activeSubscription.current !== subscriptionKey) return;
          setConnection('offline');
          setStreamError('实时事件暂时不可用，正在保留当前快照并尝试重连。');
        },
        snapshotRequired: () => {
          if (activeSubscription.current !== subscriptionKey) return;
          setLiveItems([]);
          void snapshot.refetch();
        },
      },
    );
    return () => {
      if (activeSubscription.current === subscriptionKey) {
        activeSubscription.current = '';
      }
      unsubscribe();
    };
  }, [filterKey, filters, snapshot.data?.resumeToken, transport]);

  const items = useMemo(
    () => mergeObservationEvents(snapshot.data?.items ?? [], liveItems, 500),
    [liveItems, snapshot.data?.items],
  );

  return {
    connection,
    error: snapshot.error as Error | null,
    isFetching: snapshot.isFetching,
    isPending: snapshot.isPending,
    items,
    refresh: snapshot.refetch,
    snapshot: snapshot.data,
    streamError,
  };
}

export function mergeObservationEvents(
  left: readonly ObservationEventV1[],
  right: readonly ObservationEventV1[],
  limit: number,
): ObservationEventV1[] {
  const byId = new Map<string, ObservationEventV1>();
  for (const item of [...left, ...right]) byId.set(item.eventId, item);
  return [...byId.values()]
    .sort((a, b) => b.sequence - a.sequence)
    .slice(0, Math.max(1, limit));
}

function queryFilters(filters: ObservationFilters): Record<string, ControlQueryValue> {
  return Object.fromEntries(
    Object.entries(filters).filter((entry): entry is [string, string] => Boolean(entry[1])),
  );
}
