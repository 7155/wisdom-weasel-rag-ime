import { useQuery, type UseQueryResult } from '@tanstack/react-query';
import { useEffect } from 'react';
import { useControlTransport } from '@/app/control-transport';
import type {
  WorkDocumentCommandV1,
  WorkDocumentDetailV1,
  WorkDocumentErasePreviewV1,
  WorkDocumentListV1,
} from '@/contracts/work-documents';
import type { ControlTransport, FrontendCapabilities } from '@/platform/transport';

export type WorkDocumentScope = 'active' | 'history';

export const workDocumentQueryKeys = {
  root: ['work-documents'] as const,
  capabilities: () => [...workDocumentQueryKeys.root, 'capabilities'] as const,
  list: () => [...workDocumentQueryKeys.root, 'active'] as const,
  history: (query: string) => [...workDocumentQueryKeys.root, 'history', query] as const,
  detail: (documentId: string) => [...workDocumentQueryKeys.root, 'detail', documentId] as const,
};

const workDocumentReadRouteIds = [
  'workDocuments.list',
  'workDocuments.get',
] as const;

export interface WorkDocumentAccess {
  read: boolean;
  history: boolean;
  register: boolean;
  archive: boolean;
  repair: boolean;
  reopen: boolean;
  erase: boolean;
  missingReadRoutes: string[];
}

export interface WorkDocumentWorkspace {
  active: UseQueryResult<WorkDocumentListV1, Error>;
  capabilities: UseQueryResult<FrontendCapabilities, Error>;
  capabilityKnown: boolean;
  access: WorkDocumentAccess;
  detail: UseQueryResult<WorkDocumentDetailV1, Error>;
  history: UseQueryResult<WorkDocumentListV1, Error>;
  supported: boolean;
  transport: ControlTransport;
}

export function useWorkDocumentWorkspace(
  scope: WorkDocumentScope,
  historyQuery: string,
  documentId: string,
): WorkDocumentWorkspace {
  const transport = useControlTransport();
  const capabilities = useQuery({
    queryKey: workDocumentQueryKeys.capabilities(),
    queryFn: () => transport.capabilities(),
    staleTime: 30_000,
  });
  const routeIds = new Set(capabilities.data?.routeIds ?? []);
  // Route disclosure is the executable contract. A host with the read routes
  // must not lose its whole document library merely because one destructive or
  // repair command was added in a newer release.
  const missingReadRoutes = workDocumentReadRouteIds.filter((pathId) => !routeIds.has(pathId));
  const access: WorkDocumentAccess = {
    read: missingReadRoutes.length === 0,
    history: routeIds.has('workDocuments.history.search'),
    register: routeIds.has('workDocuments.register'),
    archive: routeIds.has('workDocuments.archive'),
    repair: routeIds.has('workDocuments.repair'),
    reopen: routeIds.has('workDocuments.reopen'),
    erase: routeIds.has('workDocuments.erase.preview') && routeIds.has('workDocuments.erase'),
    missingReadRoutes,
  };
  const supported = access.read;
  const capabilityKnown = capabilities.data !== undefined;

  const active = useQuery({
    queryKey: workDocumentQueryKeys.list(),
    queryFn: ({ signal }) => transport.request<WorkDocumentListV1>({
      pathId: 'workDocuments.list',
      query: { limit: 100 },
      signal,
    }),
    enabled: supported && scope === 'active',
  });
  const history = useQuery({
    queryKey: workDocumentQueryKeys.history(historyQuery),
    queryFn: ({ signal }) => transport.request<WorkDocumentListV1>({
      pathId: 'workDocuments.history.search',
      query: { ...(historyQuery ? { query: historyQuery } : {}), limit: 100 },
      signal,
    }),
    enabled: supported && access.history && scope === 'history',
  });
  const detail = useQuery({
    queryKey: workDocumentQueryKeys.detail(documentId),
    queryFn: ({ signal }) => transport.request<WorkDocumentDetailV1>({
      pathId: 'workDocuments.get',
      params: { documentId },
      signal,
    }),
    enabled: supported && Boolean(documentId),
  });

  useEffect(() => {
    const refreshAfterReconnect = () => {
      void capabilities.refetch();
      if (scope === 'active') void active.refetch();
      if (scope === 'history') void history.refetch();
      if (documentId) void detail.refetch();
    };
    window.addEventListener('online', refreshAfterReconnect);
    return () => window.removeEventListener('online', refreshAfterReconnect);
  }, [active.refetch, capabilities.refetch, detail.refetch, documentId, history.refetch, scope]);

  return {
    active,
    access,
    capabilities,
    capabilityKnown,
    detail,
    history,
    supported,
    transport,
  };
}

export type WorkDocumentCommandInput =
  | {
    operation: 'register';
    authorityKind: 'session_todo' | 'session_goal' | 'room_work_item';
    authorityId: string;
    authorityRevision: number;
    workspaceRoot: string;
    sourcePath: string;
    title: string;
  }
  | { operation: 'archive'; documentId: string; terminalReceiptId: string }
  | { operation: 'repair'; documentId: string }
  | { operation: 'reopen'; documentId: string; authorityRevision: number; transitionReceiptId: string }
  | { operation: 'erase'; documentId: string; sessionId: string; approvalId: string; payloadSha256: string };

export function requestWorkDocumentCommand(
  transport: ControlTransport,
  input: WorkDocumentCommandInput,
): Promise<WorkDocumentCommandV1> {
  switch (input.operation) {
    case 'register':
      return transport.request<WorkDocumentCommandV1>({
        pathId: 'workDocuments.register',
        body: {
          authorityKind: input.authorityKind,
          authorityId: input.authorityId,
          authorityRevision: input.authorityRevision,
          workspaceRoot: input.workspaceRoot,
          sourcePath: input.sourcePath,
          title: input.title,
        },
      });
    case 'archive':
      return transport.request<WorkDocumentCommandV1>({
        pathId: 'workDocuments.archive',
        params: { documentId: input.documentId },
        body: { terminalReceiptId: input.terminalReceiptId },
      });
    case 'repair':
      return transport.request<WorkDocumentCommandV1>({
        pathId: 'workDocuments.repair',
        params: { documentId: input.documentId },
        body: {},
      });
    case 'reopen':
      return transport.request<WorkDocumentCommandV1>({
        pathId: 'workDocuments.reopen',
        params: { documentId: input.documentId },
        body: {
          authorityRevision: input.authorityRevision,
          transitionReceiptId: input.transitionReceiptId,
        },
      });
    case 'erase':
      return transport.request<WorkDocumentCommandV1>({
        pathId: 'workDocuments.erase',
        params: { documentId: input.documentId },
        body: {
          sessionId: input.sessionId,
          approvalId: input.approvalId,
          payloadSha256: input.payloadSha256,
        },
      });
  }
}

export function requestWorkDocumentErasePreview(
  transport: ControlTransport,
  documentId: string,
  sessionId: string,
): Promise<WorkDocumentErasePreviewV1> {
  return transport.request<WorkDocumentErasePreviewV1>({
    pathId: 'workDocuments.erase.preview',
    params: { documentId },
    body: { sessionId },
  });
}
