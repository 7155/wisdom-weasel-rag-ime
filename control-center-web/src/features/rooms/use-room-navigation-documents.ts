import { useEffect, useMemo, useState } from 'react';

import { useControlTransport } from '@/app/control-transport';
import type {
  WorkDocumentDetailV1,
  WorkDocumentListV1,
  WorkDocumentV1,
} from '@/contracts/work-documents';

import type { RoomSummary } from './room-types';

export interface RoomNavigationDocuments {
  items: WorkDocumentV1[];
  status: 'idle' | 'loading' | 'ready' | 'unavailable';
}

export function useRoomNavigationDocuments(room: RoomSummary): RoomNavigationDocuments {
  const transport = useControlTransport();
  const bindingKey = useMemo(() => (room.workItems ?? []).map((item) => [
    item.id.trim(),
    ...item.evidenceRefs.filter((reference) => reference.startsWith('workdoc:')),
  ].join('\u001e')).filter(Boolean).sort().join('\u001f'), [room.workItems]);
  const [documents, setDocuments] = useState<RoomNavigationDocuments>({
    items: [],
    status: bindingKey ? 'loading' : 'idle',
  });

  useEffect(() => {
    if (!bindingKey) {
      setDocuments({ items: [], status: 'idle' });
      return;
    }
    const controller = new AbortController();
    const bindings = bindingKey.split('\u001f').map((binding) => binding.split('\u001e'));
    const allowed = new Set(bindings.map(([authorityId]) => authorityId).filter(Boolean));
    const referencedDocumentIds = [...new Set(bindings.flatMap(([, ...references]) => (
      references.flatMap((reference) => {
        const match = /^workdoc:(workdoc_[a-f0-9]{32})@\d+$/.exec(reference);
        return match ? [match[1]] : [];
      })
    )))];
    setDocuments({ items: [], status: 'loading' });
    const listRequests = [
      transport.request<WorkDocumentListV1>({
        pathId: 'workDocuments.list',
        query: { limit: 200 },
        signal: controller.signal,
      }),
      transport.request<WorkDocumentListV1>({
        pathId: 'workDocuments.history.search',
        query: { query: '', limit: 200 },
        signal: controller.signal,
      }),
    ];
    const detailRequests = referencedDocumentIds.map((documentId) => (
      transport.request<WorkDocumentDetailV1>({
        pathId: 'workDocuments.get',
        params: { documentId },
        signal: controller.signal,
      })
    ));
    void Promise.allSettled([...listRequests, ...detailRequests]).then((results) => {
      if (controller.signal.aborted) return;
      const fulfilled = results.flatMap((result) => (
        result.status === 'fulfilled' ? [result.value] : []
      ));
      if (!fulfilled.length) {
        setDocuments({ items: [], status: 'unavailable' });
        return;
      }
      const byDocumentId = new Map<string, WorkDocumentV1>();
      for (const response of fulfilled) {
        const responseDocuments = 'document' in response
          ? [response.document]
          : response.items ?? [];
        for (const document of responseDocuments) {
          if (
            document.authorityKind === 'room_work_item'
            && allowed.has(document.authorityId)
          ) {
            byDocumentId.set(document.documentId, document);
          }
        }
      }
      setDocuments({
        items: [...byDocumentId.values()],
        status: 'ready',
      });
    });
    return () => controller.abort();
  }, [bindingKey, room.id, transport]);

  return documents;
}
