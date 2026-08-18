import { useEffect, useMemo, useState } from 'react';

import { useControlTransport } from '@/app/control-transport';
import type { WorkDocumentListV1, WorkDocumentV1 } from '@/contracts/work-documents';

import type { RoomSummary } from './room-types';

export interface RoomNavigationDocuments {
  items: WorkDocumentV1[];
  status: 'idle' | 'loading' | 'ready' | 'unavailable';
}

export function useRoomNavigationDocuments(room: RoomSummary): RoomNavigationDocuments {
  const transport = useControlTransport();
  const authorityKey = useMemo(() => [...new Set(
    (room.workItems ?? []).map((item) => item.id.trim()).filter(Boolean),
  )].sort().join('\u001f'), [room.workItems]);
  const [documents, setDocuments] = useState<RoomNavigationDocuments>({
    items: [],
    status: authorityKey ? 'loading' : 'idle',
  });

  useEffect(() => {
    if (!authorityKey) {
      setDocuments({ items: [], status: 'idle' });
      return;
    }
    const controller = new AbortController();
    const allowed = new Set(authorityKey.split('\u001f'));
    setDocuments({ items: [], status: 'loading' });
    void transport.request<WorkDocumentListV1>({
      pathId: 'workDocuments.list',
      query: { limit: 200 },
      signal: controller.signal,
    }).then((response) => {
      if (controller.signal.aborted) return;
      setDocuments({
        items: (response.items ?? []).filter((document) => (
          document.authorityKind === 'room_work_item'
          && allowed.has(document.authorityId)
        )),
        status: 'ready',
      });
    }).catch(() => {
      if (!controller.signal.aborted) {
        setDocuments({ items: [], status: 'unavailable' });
      }
    });
    return () => controller.abort();
  }, [authorityKey, room.id, transport]);

  return documents;
}
