import { Bot, BrainCircuit, Radio, Users } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { publishGlobalNotice } from '@/components/feedback';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/primitives';
import { usePawDesktopApi } from '../runtime/desktop-context';
import { projectRunningWayfinderWork, type WayfinderWorkItem } from './wayfinder-work-projection';
import { usePawWorkDirectory, type PawMemoryMaintenanceActivity } from './PawWorkDirectory';
import './paw-shell-status.css';

export function PawBackgroundActivity() {
  const api = usePawDesktopApi();
  const {
    maintenance,
    maintenanceJob,
    maintenanceStatusFresh,
    roomStatusFresh,
    rooms,
    sessionStatusFresh,
    sessions,
  } = usePawWorkDirectory();
  const [open, setOpen] = useState(false);
  const running = useMemo<BackgroundActivityItem[]>(() => [
    ...projectRunningWayfinderWork({ nowMs: Date.now(), roomStatusFresh, rooms, sessionStatusFresh, sessions }),
    ...(maintenance ? [{ ...maintenance, key: `maintenance:${maintenance.id}`, kind: 'maintenance' as const }] : []),
  ].sort((left, right) => right.updatedAtMs - left.updatedAtMs), [maintenance, roomStatusFresh, rooms, sessionStatusFresh, sessions]);
  useRuntimeCompletionNotices({
    maintenanceStatusFresh,
    maintenanceJob,
    roomStatusFresh,
    rooms,
    running,
    sessionStatusFresh,
    sessions,
  });

  if (!running.length) return null;

  const openWork = (item: BackgroundActivityItem) => {
    if (item.kind === 'maintenance') {
      api.getState().openApp('memory', { initialRoute: '/memory?view=organize', title: 'Memory' });
      setOpen(false);
      return;
    }
    api.getState().openApp('agent', {
      entityId: item.id,
      initialRoute: `/agent?${item.kind === 'room' ? 'room' : 'session'}=${encodeURIComponent(item.id)}`,
      target: { kind: item.kind, id: item.id, title: item.title },
      title: item.title,
    });
    setOpen(false);
  };

  return (
    <Popover onOpenChange={setOpen} open={open}>
      <PopoverTrigger asChild>
        <button
          aria-label={`${running.length} 个后台工作正在运行`}
          className="paw-background-activity__trigger"
          type="button"
        >
          <Radio aria-hidden="true" size={14} />
          <span className="paw-background-activity__trigger-copy">{activityCategory(running[0]!)}</span>
          <b>{running.length}</b>
        </button>
      </PopoverTrigger>
      <PopoverContent align="end" className="paw-background-activity__popover" sideOffset={8}>
        <section aria-label="后台运行" className="paw-background-activity">
          <header>
            <span><Radio aria-hidden="true" size={15} /><strong>后台运行</strong></span>
            <small>{running.length} 项</small>
          </header>
          <div className="paw-background-activity__list">
            {running.map((item) => {
              const CategoryIcon = item.kind === 'room'
                ? Users
                : item.kind === 'maintenance'
                  ? BrainCircuit
                  : Bot;
              return (
                <button key={item.key} onClick={() => openWork(item)} type="button">
                  <span className="paw-background-activity__icon"><CategoryIcon aria-hidden="true" size={15} /></span>
                  <span>
                    <small>{activityCategory(item)}</small>
                    <strong>{item.title}</strong>
                    <span>{item.detail}</span>
                  </span>
                  <i aria-hidden="true" />
                </button>
              );
            })}
          </div>
          <p>点击可回到对应的对话或 Room。</p>
        </section>
      </PopoverContent>
    </Popover>
  );
}

type BackgroundActivityItem = WayfinderWorkItem | (PawMemoryMaintenanceActivity & {
  key: string;
  kind: 'maintenance';
});

function activityCategory(item: BackgroundActivityItem): string {
  if (item.kind === 'room') return 'Room 协作';
  return item.kind === 'maintenance' ? '自动记忆整理' : '对话 Agent';
}

function useRuntimeCompletionNotices({
  maintenanceJob,
  maintenanceStatusFresh,
  roomStatusFresh,
  rooms,
  running,
  sessionStatusFresh,
  sessions,
}: {
  maintenanceJob: ReturnType<typeof usePawWorkDirectory>['maintenanceJob'];
  maintenanceStatusFresh: boolean;
  roomStatusFresh: boolean;
  rooms: ReturnType<typeof usePawWorkDirectory>['rooms'];
  running: readonly BackgroundActivityItem[];
  sessionStatusFresh: boolean;
  sessions: ReturnType<typeof usePawWorkDirectory>['sessions'];
}) {
  const previousRef = useRef<Map<string, BackgroundActivityItem> | null>(null);
  useEffect(() => {
    const current = new Map(running.map((item) => [item.key, item]));
    const previous = previousRef.current;
    if (!previous) {
      previousRef.current = current;
      return;
    }
    const nextPrevious = new Map(current);
    for (const [key, item] of previous) {
      if (current.has(key)) continue;
      const fresh = item.kind === 'maintenance'
        ? maintenanceStatusFresh
        : item.kind === 'room'
          ? roomStatusFresh && sessionStatusFresh
          : sessionStatusFresh;
      if (!fresh) {
        nextPrevious.set(key, item);
        continue;
      }
      const session = item.kind === 'session' ? sessions.find((candidate) => candidate.id === item.id) : undefined;
      const room = item.kind === 'room' ? rooms.find((candidate) => candidate.id === item.id) : undefined;
      /* A missing row can mean pagination or archival rather than completion;
         only a still-present canonical object may close a live notification. */
      if (item.kind === 'maintenance' && maintenanceJob?.id !== item.id) continue;
      if (item.kind !== 'maintenance' && !session && !room) continue;
      const failedPartner = item.kind === 'room' && sessions.some((candidate) => (
        candidate.roomParticipant?.roomId === item.id && candidate.status === 'faulted'
      ));
      const needsAttention = session?.status === 'faulted'
        || failedPartner
        || room?.workItems?.some((workItem) => workItem.state === 'blocked')
        || (item.kind === 'maintenance' && (maintenanceJob?.state === 'failed' || maintenanceJob?.state === 'expired'));
      publishGlobalNotice({
        id: `runtime-transition:${key}:${Date.now()}`,
        title: needsAttention ? `${item.title} 需要处理` : `${item.title} 已结束运行`,
        message: item.kind === 'maintenance'
          ? needsAttention
            ? `自动记忆整理失败，可在 Memory 中检查并重试。${maintenanceJob?.error ? ` ${maintenanceJob.error}` : ''}`
            : '自动记忆整理已完成，可在 Memory 中查看最新状态。'
          : item.kind === 'room'
            ? failedPartner
              ? 'Room 的 Partner 运行失败，可从项目桌面重新打开并检查详情。'
              : 'Room 当前没有正在执行的 Partner，可从项目桌面重新打开。'
            : '对话 Agent 已退出运行态，可从项目桌面重新打开。',
        tone: needsAttention ? 'warning' : 'info',
      });
    }
    previousRef.current = nextPrevious;
  }, [maintenanceJob, maintenanceStatusFresh, roomStatusFresh, rooms, running, sessionStatusFresh, sessions]);
}
