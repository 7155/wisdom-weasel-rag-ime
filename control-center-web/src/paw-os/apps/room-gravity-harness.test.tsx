/// <reference types="node" />

import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { cleanup, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createRoomProjection, reduceRoomEvents, type RoomProjectionState } from '@/contracts/room-reducer';
import { parseRoomEvent } from '@/contracts/validators';
import type { RoomSummary } from '@/features/rooms/room-types';
import { PawRoomFocusOverview } from './PawRoomFocusOverview';
import { PawRoomConversation } from './PawRoomWorkspace';
import { buildRoomFocusProjection, type RoomFocusProjection } from './room-focus-projection';
import { roomDispatchPlans, roomDispatchWaves } from './room-gravity-projection';

/**
 * Sol gravity against the real minecraft-harness fixture: 3261 authoritative
 * Room events, one coordinator, one reviewer and two parallel partners. The
 * projection and both surfaces must answer goal, owners, parallel lanes,
 * blockers and the verification planet from this data alone.
 */

const root = resolve(process.cwd(), 'e2e/fixtures/minecraft-harness-20260825');

const harness = (() => {
  const events = readFileSync(resolve(root, 'room/history.jsonl'), 'utf8')
    .trim().split('\n').map((line) => parseRoomEvent(JSON.parse(line)));
  const snapshot = JSON.parse(readFileSync(resolve(root, 'room/snapshot.json'), 'utf8')) as { room: RoomSummary };
  const projection = reduceRoomEvents(createRoomProjection(snapshot.room.id), events);
  const focus = buildRoomFocusProjection(snapshot.room, projection);
  return { events, room: snapshot.room, projection, focus };
})() satisfies { events: unknown[]; room: RoomSummary; projection: RoomProjectionState; focus: RoomFocusProjection };

afterEach(cleanup);

describe('room gravity projection over the minecraft harness', () => {
  it('recovers the real task counters and tree from 3261 events', () => {
    expect(harness.events).toHaveLength(3261);
    // Real snapshot state: one blocked core WorkItem, everything else landed.
    // Every child dispatch is bound to an explicit WorkItem, so the tree shows
    // each task exactly once — no runtime duplicate rows.
    expect(harness.focus.counts).toEqual({ active: 0, review: 0, blocked: 1, completed: 4 });
    expect(harness.focus.workItems).toHaveLength(5);
    expect(harness.focus.workItems.every((item) => item.source === 'work-item')).toBe(true);

    const blocked = harness.focus.workItems.find((item) => item.state === 'blocked');
    expect(blocked?.id).toBe('room-work:10000000-0000-4000-8000-000000000001');
    expect(blocked?.blocker?.reason).toContain('WorkDocument');
  });

  it('reconstructs the parallel wave with both partner planets on their own tracks', () => {
    const activities = harness.projection.activityOrder
      .map((id) => harness.projection.activitiesById[id])
      .filter((activity): activity is NonNullable<typeof activity> => Boolean(activity));
    const waves = roomDispatchWaves(roomDispatchPlans(activities));

    expect(waves).toHaveLength(1);
    expect(waves[0]?.phaseName).toBe('并行实现纯逻辑与界面轨道');
    expect(waves[0]?.parallelSize).toBe(2);
    expect(waves[0]?.dispatches.map((dispatch) => dispatch.targetDisplayName)).toEqual(['Agent 2', 'Agent 4']);

    // The wave lands on the explicit WorkItems, so the tree can draw lanes.
    const core = harness.focus.workItems.find((item) => item.id.endsWith('000000000001') && item.source === 'work-item');
    const ui = harness.focus.workItems.find((item) => item.id.endsWith('000000000005') && item.source === 'work-item');
    expect(core?.wave?.parallelIndex).toBe(0);
    expect(ui?.wave?.parallelIndex).toBe(1);
    expect(core?.wave?.waveId).toBe(ui?.wave?.waveId);
  });

  it('keeps the dual-axis review verdicts and the verifying planet on completed work', () => {
    const reviewed = harness.focus.workItems.filter((item) => item.review);
    expect(reviewed.length).toBeGreaterThanOrEqual(4);
    for (const item of reviewed) {
      expect(item.review?.operability).toBe('passed');
      expect(item.review?.requirement).toBe('satisfied');
      expect(item.review?.reviewerParticipantId).toBeTruthy();
      expect(item.verifierParticipantId).toBe(item.review?.reviewerParticipantId);
    }
  });

  it('turns every route decision into a readable dispatch packet with a resolved source planet', () => {
    const dispatches = harness.focus.flow.filter((packet) => packet.kind === 'dispatch');
    expect(dispatches.length).toBeGreaterThanOrEqual(10);
    expect(dispatches.every((packet) => packet.dispatchPlan)).toBe(true);

    // The delegate_batch wave: the coordinator planet pulls both partners.
    const waveDispatches = dispatches.filter((packet) => packet.dispatchPlan?.waveId);
    expect(waveDispatches.map((packet) => packet.summary)).toEqual([
      '伙伴委派 · 交给 Venus · 并行轨道 1/2 · 并行实现纯逻辑与界面轨道',
      '伙伴委派 · 交给 Jupiter · 并行轨道 2/2 · 并行实现纯逻辑与界面轨道',
    ]);
    for (const packet of waveDispatches) {
      expect(packet.sourceParticipantId).toBe('participant:10000000-0000-4000-8000-000000000001');
    }
    // Root routing is Sol's own gravity, never a fabricated planet.
    const opening = dispatches.find((packet) => packet.dispatchPlan?.reason === 'facilitator');
    expect(opening?.sourceParticipantId).toBe('root');
  });

  it('renders the collaboration console with lanes, owners, blockers and verifiers', () => {
    render(<PawRoomFocusOverview focus={harness.focus} onOpenParticipant={vi.fn()} />);

    // Pulse counters mirror the real numbers.
    const pulse = screen.getByLabelText('协作摘要');
    expect(pulse).toHaveTextContent('受阻');
    expect(pulse.querySelectorAll('.paw-room-focus-overview__pulse-bar > i').length).toBeGreaterThanOrEqual(2);

    const tree = screen.getByRole('tree', { name: '任务树' });
    expect(within(tree).getByText('并行波次 · 并行实现纯逻辑与界面轨道')).toBeInTheDocument();
    expect(within(tree).getAllByText('∥ 轨道 1/2').length).toBeGreaterThanOrEqual(1);
    expect(within(tree).getAllByText('∥ 轨道 2/2').length).toBeGreaterThanOrEqual(1);
    expect(within(tree).getAllByText('负责 Venus').length).toBeGreaterThanOrEqual(1);
    expect(within(tree).getAllByText('负责 Jupiter').length).toBeGreaterThanOrEqual(1);
    expect(within(tree).getAllByText(/^复核/).length).toBeGreaterThanOrEqual(4);
    // The blocked lane names its real blocker inline.
    expect(within(tree).getByText(/WorkDocument 尚未完成开工与交付同步/)).toBeInTheDocument();

    // The machine enum never leaks into the reader-facing console.
    expect(screen.getByLabelText('Sol 协作态势').textContent).not.toContain('route_decision');
  });

  it('renders the fixture route decisions as dispatch cards in the public chronology', () => {
    // The opening scene up to the parallel delegate_batch wave (seq 68-73).
    const slice = readFileSync(resolve(root, 'room/history.jsonl'), 'utf8')
      .trim().split('\n').map((line) => parseRoomEvent(JSON.parse(line)))
      .filter((event) => event.sequence <= 120);
    const projection = reduceRoomEvents(createRoomProjection(harness.room.id), slice);

    const { container } = render(<PawRoomConversation
      onApprovalDecision={async () => undefined}
      onRetryTurn={() => undefined}
      projection={projection}
      retryingTurn={false}
      room={harness.room}
    />);

    const cards = container.querySelectorAll('.paw-room-chronology__activity--dispatch');
    expect(cards.length).toBeGreaterThanOrEqual(2);
    const texts = [...cards].map((card) => card.textContent ?? '');
    expect(texts.some((text) => text.includes('Earth → Venus · 任务分派'))).toBe(true);
    expect(texts.some((text) => text.includes('Earth → Jupiter · 任务分派'))).toBe(true);
    const waveCard = [...cards].find((card) => card.textContent?.includes('Earth → Venus'));
    expect(waveCard).toHaveTextContent('伙伴委派');
    expect(waveCard).toHaveTextContent('∥ 轨道 1/2');
    expect(waveCard).toHaveTextContent('并行实现纯逻辑与界面轨道');
    // The real core objective rides with the dispatch, not just an id.
    expect(waveCard).toHaveTextContent('实现原创 3D 方块生存游戏的纯逻辑核心');
    // The dead label pattern (planet · 分派 with no plan) is gone.
    expect(container.textContent).not.toContain('route_decision');
  });
});
