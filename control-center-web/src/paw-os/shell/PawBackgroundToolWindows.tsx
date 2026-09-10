import { useEffect } from 'react';
import { useControlTransport } from '@/app/control-transport';
import { validateContract } from '@/contracts/validators';
import { usePageVisibility } from '@/platform/use-page-visibility';
import { usePawDesktopApi, usePawDesktopStore } from '../runtime/desktop-context';
import { backgroundToolRequest, reconcileBackgroundToolWindow } from '../runtime/background-tool-windows';

const record = (value: unknown): Record<string, unknown> => value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
const rows = (value: unknown): Record<string, unknown>[] => Array.isArray(value) ? value.map(record) : [];
const text = (value: unknown): string => typeof value === 'string' ? value : '';

/** Observe durable resources independently of frequent tool calls and the Room's turn lifetime. */
export function PawBackgroundToolWindows() {
  const transport = useControlTransport();
  const api = usePawDesktopApi();
  const visible = usePageVisibility();
  const focus = usePawDesktopStore((state) => state.collaborationFocusGroup);
  const observers = usePawDesktopStore((state) => Object.values(state.windows)
    .filter((node) => (node.target?.kind === 'browser-target' || node.target?.kind === 'process-terminal') && node.target.backgroundObserver)
    .map((node) => node.id).sort().join('\0'));
  useEffect(() => {
    if (!visible || (!focus?.startsWith('room:') && !observers)) return;
    const controller = new AbortController();
    const signal = controller.signal;
    let timer: ReturnType<typeof setTimeout>;
    const roomId = focus?.startsWith('room:') ? focus.slice(5) : '';
    const request = async (input: Parameters<typeof transport.request>[0]) => record(await transport.request({ ...input, signal }));
    async function poll() {
      try {
        const room = roomId ? record((await request({ pathId: 'agent.room.get', params: { roomId } })).room) : {};
        if (signal.aborted) return;
        const participants = room.id === roomId ? rows(room.participants).filter((item) => item.status === 'active' && text(item.sessionId)) : [];
        const current = Object.values(api.getState().windows).filter((node) => (
          (node.target?.kind === 'browser-target' || node.target?.kind === 'process-terminal') && node.target.backgroundObserver
        ));
        const work = participants.map(async (participant) => {
          const sessionId = text(participant.sessionId);
          const value = await request({ pathId: 'agent.session.backgroundJobs.list', params: { sessionId }, query: { limit: 100 } });
          if (signal.aborted || value.ok !== true || value.sessionId !== sessionId || value.schemaVersion !== 'rag-ime.agent-background-job-list.v1') return;
          for (const candidate of rows(value.items)) {
            if (candidate.sessionId !== sessionId || candidate.schemaVersion !== 'rag-ime.agent-background-job.v1' || !text(candidate.jobId).startsWith('bg_')) continue;
            const parsed = validateContract('agent-background-job.v1', candidate);
            if (!parsed.ok) continue;
            const job = parsed.value;
            reconcileBackgroundToolWindow(api, backgroundToolRequest(job, roomId, text(participant.id)), job.status);
          }
        });
        // A completed resource may drop out of a bounded list. Its own get receipt
        // remains authoritative, also after the user leaves collaboration mode.
        for (const node of current) {
          const target = node.target;
          if (target?.kind !== 'process-terminal' || !target.runId) continue;
          work.push((async () => {
            const value = await request({ pathId: 'agent.session.backgroundJob.get', params: { sessionId: target.sessionId, jobId: target.runId! } });
            const job = record(value.job);
            const parsed = validateContract('agent-background-job.v1', job);
            if (!signal.aborted && value.ok === true && parsed.ok && job.jobId === target.runId && job.sessionId === target.sessionId) {
              reconcileBackgroundToolWindow(api, backgroundToolRequest(parsed.value, target.roomId!, target.participantId ?? ''), text(job.status));
            }
          })());
        }
        work.push((async () => {
          const [tabsValue, tracesValue] = await Promise.all([
            request({ pathId: 'browser.tabs' }),
            roomId ? request({ pathId: 'browser.traces', query: { limit: 200 } }) : Promise.resolve({}),
          ]);
          if (signal.aborted || tabsValue.ok !== true || tabsValue.liveSnapshot !== true) return;
          const tabs = rows(tabsValue.items);
          for (const node of current) {
            const target = node.target;
            if (target?.kind === 'browser-target' && !tabs.some((tab) => tab.targetId === target.targetId)) {
              reconcileBackgroundToolWindow(api, { appId: 'browser', target, background: true }, 'closed');
            }
          }
          for (const tab of tabs) {
            const targetId = text(tab.targetId);
            if (!targetId || typeof tab.tabId !== 'number') continue;
            const trace = rows(record(tracesValue).items).find((item) => (
              (item.tabId === tab.tabId || record(item.result).tabId === tab.tabId || record(item.result).targetId === targetId)
              && item.status !== 'failed' && participants.some((participant) => participant.sessionId === item.sessionId)
            ));
            const owner = trace && participants.find((participant) => participant.sessionId === trace.sessionId);
            if (!owner) continue;
            reconcileBackgroundToolWindow(api, { appId: 'browser', background: true, target: {
              kind: 'browser-target', backgroundObserver: true,
              id: `${roomId}:background:browser:${targetId}`,
              title: text(tab.title) || '后台浏览器', targetId, tabId: tab.tabId,
              url: text(tab.url), sessionId: text(owner.sessionId), roomId, participantId: text(owner.id), toolCallId: '',
            } }, 'running');
          }
        })());
        // Failed reads retain the last known window state; they never mean a tool ended.
        await Promise.allSettled(work);
      } catch { /* Recovery uses the next read; never restart or cancel a resource. */ }
      if (!signal.aborted) timer = setTimeout(() => { void poll(); }, 2_000);
    }
    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [api, focus, observers, transport, visible]);
  return null;
}
