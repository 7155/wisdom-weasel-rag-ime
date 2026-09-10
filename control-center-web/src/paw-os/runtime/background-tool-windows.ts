import type { AgentBackgroundJobV1 } from '@/contracts/generated/agent-background-job.v1';
import type { PawOsWindowRequest } from '@/features/paw-os/surface-context';
import type { PawDesktopStore } from './desktop-store';
import { backgroundJobWindowRequest } from './runtime-tool-window';

export function backgroundToolRequest(job: AgentBackgroundJobV1, roomId: string, participantId: string): PawOsWindowRequest {
  const request = backgroundJobWindowRequest(job, { roomId, participantId });
  return { ...request, background: true, target: {
    ...request.target, id: `${roomId}:background:${job.sessionId}:${job.jobId}`, backgroundObserver: true,
  } as PawOsWindowRequest['target'] };
}

export function reconcileBackgroundToolWindow(store: PawDesktopStore, request: PawOsWindowRequest, status: string): void {
  const target = request.target;
  if (target.kind !== 'process-terminal' && target.kind !== 'browser-target') return;
  if (!target.backgroundObserver || !target.roomId) return;
  const windowId = `${request.appId}:${target.id}`;
  const current = store.getState().windows[windowId];
  if (['completed', 'failed', 'cancelled', 'orphaned', 'closed'].includes(status)) {
    // Closing a projection never invokes a tool cancellation/Browser command.
    if (current?.target?.kind === target.kind && current.target.backgroundObserver) store.getState().closeWindow(windowId);
    else if (!store.getState().dismissedBackgroundToolIds.includes(target.id)) store.setState((state) => ({
      dismissedBackgroundToolIds: [...state.dismissedBackgroundToolIds, target.id].slice(-512),
    }));
    return;
  }
  if (!['queued', 'running', 'cancelling'].includes(status)) return;
  if (!current && (store.getState().collaborationFocusGroup !== `room:${target.roomId}`
    || store.getState().dismissedBackgroundToolIds.includes(target.id))) return;
  if (current) {
    // Enrich a resident view without changing focus, stack, minimized state or geometry.
    if (JSON.stringify(current.target) !== JSON.stringify(target)) store.setState((state) => ({
      windows: { ...state.windows, [windowId]: { ...current, target } },
    }));
  } else store.getState().openApp(request.appId, { entityId: target.id, target, title: target.title, background: true });
}
