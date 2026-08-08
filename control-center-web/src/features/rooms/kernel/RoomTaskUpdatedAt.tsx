import { useEffect, useState } from 'react';

const roomTaskUpdatedAtFormatter = new Intl.DateTimeFormat('zh-CN', {
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
});

export function useRoomTaskUpdateClock(enabled: boolean): number {
  const [nowMs, setNowMs] = useState(() => Date.now());
  useEffect(() => {
    if (!enabled) return undefined;
    setNowMs(Date.now());
    const timer = window.setInterval(() => setNowMs(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, [enabled]);
  return nowMs;
}

export function RoomTaskUpdatedAt({
  updatedAtMs,
}: {
  updatedAtMs?: number;
}) {
  const nowMs = useRoomTaskUpdateClock(updatedAtMs !== undefined);
  if (updatedAtMs === undefined) {
    return <span className="room-task-updated-at" data-state="missing">更新时间未上报</span>;
  }
  const updatedAt = new Date(updatedAtMs);
  const absolute = roomTaskUpdatedAtFormatter.format(updatedAt);
  const elapsedSeconds = Math.max(0, Math.floor((nowMs - updatedAtMs) / 1_000));
  return <span className="room-task-updated-at" data-state="reported">
    <span>最近更新 <time dateTime={updatedAt.toISOString()}>{absolute}</time></span>
    <span aria-hidden="true"> · {elapsedSeconds} 秒前</span>
  </span>;
}
