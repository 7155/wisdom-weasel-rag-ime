import { describe, expect, it } from 'vitest';
import {
  projectWayfinderWork,
  wayfinderWorkTime,
  type WayfinderWorkRoomSource,
  type WayfinderWorkSessionSource,
} from './wayfinder-work-projection';

/* The projection is the desktop-density contract: whatever web-length noise
 * the directory returns (partner clones, repeated goal prompts, months of
 * history), the desktop receives a short, folded, bucketed view. These tests
 * pin the folding rules with the exact shapes the user's screenshot showed —
 * "迁移作战室 · Agent 1/2/3" clones and many identical goal rows. */

// Local-time anchors: bucketFor compares calendar days in the runner's zone.
const NOW = new Date(2026, 7, 25, 12, 0, 0).getTime();
const TODAY_9AM = new Date(2026, 7, 25, 9, 0, 0).getTime();
const TWO_DAYS_AGO = NOW - 2 * 86_400_000;
const NINE_DAYS_AGO = NOW - 9 * 86_400_000;

function session(overrides: Partial<WayfinderWorkSessionSource> & { id: string }): WayfinderWorkSessionSource {
  return {
    title: '未命名工作',
    status: 'idle',
    updatedAtMs: TODAY_9AM,
    ...overrides,
  };
}

function room(overrides: Partial<WayfinderWorkRoomSource> & { id: string }): WayfinderWorkRoomSource {
  return {
    title: '未命名工作',
    status: 'idle',
    updatedAtMs: TODAY_9AM,
    ...overrides,
  };
}

describe('projectWayfinderWork', () => {
  it('folds orphan Room partner clones into one synthesized Room row', () => {
    const view = projectWayfinderWork({
      nowMs: NOW,
      rooms: [],
      sessions: [
        session({ id: 's-1', title: '迁移作战室 · Agent 1', roomParticipant: { roomId: 'room-9' } }),
        session({ id: 's-2', title: '迁移作战室 · Agent 2', status: 'busy', roomParticipant: { roomId: 'room-9' }, updatedAtMs: TODAY_9AM + 60_000 }),
        session({ id: 's-3', title: '迁移作战室 · Agent 3', roomParticipant: { roomId: 'room-9' } }),
      ],
    });

    expect(view.rowCount).toBe(1);
    expect(view.foldedCount).toBe(3);
    const [row] = view.buckets[0]!.items;
    expect(row).toMatchObject({
      kind: 'room',
      id: 'room-9',
      title: '迁移作战室',
      activity: 'running',
    });
    expect(row!.agents).toEqual(['Earth', 'Mars', 'Venus']);
  });

  it('keeps partner Sessions off the list entirely when their Room record exists', () => {
    const view = projectWayfinderWork({
      nowMs: NOW,
      rooms: [room({
        id: 'room-1',
        title: '迁移作战室',
        status: 'active',
        participants: [
          { displayName: 'Agent 2', ordinal: 2 },
          { displayName: 'Agent 1', ordinal: 1 },
          { displayName: '已移除', ordinal: 3, status: 'removed' },
        ],
      })],
      sessions: [
        session({ id: 's-1', title: '迁移作战室 · Agent 1', roomParticipant: { roomId: 'room-1' } }),
        session({ id: 's-2', title: '迁移作战室 · Agent 2', roomParticipant: { roomId: 'room-1' } }),
        session({ id: 's-3', title: '独立调查', updatedAtMs: TODAY_9AM + 1 }),
      ],
    });

    expect(view.rowCount).toBe(2);
    expect(view.foldedCount).toBe(2);
    const titles = view.buckets[0]!.items.map((item) => item.title);
    expect(titles).toEqual(['独立调查', '迁移作战室']);
    const roomItem = view.buckets[0]!.items.find((item) => item.kind === 'room');
    expect(roomItem?.agents).toEqual(['Mars', 'Venus']);
    expect(roomItem?.activity).toBe('running');
  });

  it('collapses records repeating the same goal copy into the newest with reachable repeats', () => {
    const view = projectWayfinderWork({
      nowMs: NOW,
      rooms: [],
      sessions: [
        session({ id: 's-old', title: '重构 Wayfinder 列表', status: 'faulted', updatedAtMs: TODAY_9AM }),
        session({ id: 's-new', title: '重构  Wayfinder 列表…', updatedAtMs: TODAY_9AM + 120_000 }),
        session({ id: 's-mid', title: '重构 Wayfinder 列表', updatedAtMs: TODAY_9AM + 60_000 }),
      ],
    });

    expect(view.rowCount).toBe(1);
    expect(view.foldedCount).toBe(2);
    const [row] = view.buckets[0]!.items;
    expect(row!.id).toBe('s-new');
    // The lead row inherits the loudest state so a faulted older run is not lost.
    expect(row!.activity).toBe('attention');
    expect(row!.repeats.map((repeat) => repeat.id)).toEqual(['s-mid', 's-old']);
  });

  it('groups rows into 今天 / 本周 / 更早 with a bounded preview per bucket', () => {
    const view = projectWayfinderWork({
      nowMs: NOW,
      rooms: [],
      sessions: [
        ...Array.from({ length: 7 }, (_, index) => session({
          id: `today-${index}`,
          title: `今日目标 ${index}`,
          updatedAtMs: TODAY_9AM + index,
        })),
        session({ id: 'week-1', title: '周中目标', updatedAtMs: TWO_DAYS_AGO }),
        session({ id: 'old-1', title: '陈旧目标 A', updatedAtMs: NINE_DAYS_AGO }),
        session({ id: 'old-2', title: '陈旧目标 B', updatedAtMs: NINE_DAYS_AGO }),
      ],
    });

    expect(view.buckets.map((bucket) => bucket.id)).toEqual(['today', 'week', 'earlier']);
    const [today, week, earlier] = view.buckets;
    expect(today!.items).toHaveLength(7);
    expect(today!.previewCount).toBe(5);
    expect(week!.items).toHaveLength(1);
    // The stale bucket rests fully collapsed: zero rows on the first screen.
    expect(earlier!.previewCount).toBe(0);
    expect(earlier!.items).toHaveLength(2);
  });

  it('drops archived records and empty buckets', () => {
    const view = projectWayfinderWork({
      nowMs: NOW,
      rooms: [room({ id: 'room-a', title: '已归档房间', status: 'archived' })],
      sessions: [
        session({ id: 's-1', title: '仍在进行' }),
        session({ id: 's-2', title: '已归档工作', status: 'archived' }),
      ],
    });

    expect(view.rowCount).toBe(1);
    expect(view.buckets.map((bucket) => bucket.id)).toEqual(['today']);
    expect(view.buckets[0]!.items[0]!.title).toBe('仍在进行');
  });

  it('searches title, project leaf and partner names without touching the caps', () => {
    const sources = {
      nowMs: NOW,
      rooms: [room({
        id: 'room-1',
        title: '迁移作战室',
        participants: [{ displayName: 'Kimi', ordinal: 1 }],
      })],
      sessions: [
        session({ id: 's-1', title: '重构列表', workspaceRoots: ['/Users/me/paw/control-center-web'] }),
        session({ id: 's-2', title: '其他工作' }),
      ],
    };

    expect(projectWayfinderWork({ ...sources, query: 'control-center' }).rowCount).toBe(1);
    expect(projectWayfinderWork({ ...sources, query: 'mars' }).rowCount).toBe(1);
    expect(projectWayfinderWork({ ...sources, query: 'kimi' }).rowCount).toBe(0);
    expect(projectWayfinderWork({ ...sources, query: '重构' }).rowCount).toBe(1);
    expect(projectWayfinderWork({ ...sources, query: '不存在' }).rowCount).toBe(0);
  });
});

describe('wayfinderWorkTime', () => {
  it('speaks desktop recency instead of raw timestamps', () => {
    expect(wayfinderWorkTime(NOW - 20_000, NOW)).toBe('刚刚');
    expect(wayfinderWorkTime(NOW - 5 * 60_000, NOW)).toBe('5 分钟前');
    expect(wayfinderWorkTime(NOW - 3 * 3_600_000, NOW)).toBe('3 小时前');
    expect(wayfinderWorkTime(NINE_DAYS_AGO, NOW)).toMatch(/8\/16|8月16日/);
  });
});
