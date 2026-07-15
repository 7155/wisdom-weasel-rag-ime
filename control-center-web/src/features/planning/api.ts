import { useQuery } from '@tanstack/react-query';
import { useControlTransport } from '@/app/control-transport';
import type { MutationAvailability } from '@/features/overview/management-mutation';
import type { ControlTransport, JsonValue } from '@/platform/transport';

export const planningQueryKeys = {
  root: ['planning'] as const,
  dashboard: (date: string, project: string) => [...planningQueryKeys.root, 'dashboard', date, project] as const,
  capabilities: () => [...planningQueryKeys.root, 'capabilities'] as const,
};

export const planningMutationPathIds = {
  preview: 'planning.mutation.preview',
  taskSave: 'planning.task.save',
  goalSave: 'planning.goal.save',
  taskAction: 'planning.task.action',
  taskEventUndo: 'planning.taskEvent.undo',
  rollback: 'planning.mutation.rollback',
} as const;

export type PlanningMutationPathId = (typeof planningMutationPathIds)[keyof typeof planningMutationPathIds];

export type PlanningMutationRequest = {
  pathId: PlanningMutationPathId;
  body: Record<string, JsonValue>;
};

export function usePlanningDashboard(date: string, project = '') {
  const transport = useControlTransport();
  const dashboard = useQuery({
    queryKey: planningQueryKeys.dashboard(date, project),
    queryFn: ({ signal }) => transport.request({
      pathId: 'planning.dashboard',
      query: { ...(date ? { date } : {}), ...(project ? { project } : {}) },
      signal,
    }),
  });
  return { dashboard, transportKind: transport.kind };
}

export function usePlanningMutationBoundary() {
  const transport = useControlTransport();
  const capabilities = useQuery({
    queryKey: planningQueryKeys.capabilities(),
    queryFn: () => transport.capabilities(),
    staleTime: 30_000,
  });

  const availability = (
    pathIds: readonly PlanningMutationPathId[],
    blockedReason = '',
  ): MutationAvailability => {
    if (capabilities.isPending) return { state: 'checking' };
    if (capabilities.error) return { state: 'unsupported', reason: '无法确认当前操作是否可用，请刷新后重试。' };
    const flags = capabilities.data?.features ?? {};
    const routeIds = new Set((capabilities.data?.routeIds ?? []) as readonly string[]);
    if (!flags.managementWorkContract || !flags.planningWorkContract || pathIds.some((pathId) => !routeIds.has(pathId))) {
      return { state: 'unsupported', reason: '当前版本还不能安全保存规划内容；没有请求被发送。' };
    }
    if (blockedReason) return { state: 'blocked', reason: blockedReason };
    return { state: 'available' };
  };

  return {
    availability,
    capabilities,
    request: <Response,>(request: PlanningMutationRequest) => requestPlanningMutation<Response>(transport, request),
  };
}

export function requestPlanningMutation<Response>(
  transport: ControlTransport,
  request: PlanningMutationRequest,
): Promise<Response> {
  return transport.request<Response>({
    pathId: request.pathId,
    body: request.body,
  });
}
