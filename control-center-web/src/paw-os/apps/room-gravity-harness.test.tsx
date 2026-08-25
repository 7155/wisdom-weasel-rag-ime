/// <reference types="node" />

import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import { createRoomProjection, parseRoomEventSnapshot, reduceRoomEvents, type RoomProjectionState } from '@/contracts/room-reducer';
import { parseRoomEvent } from '@/contracts/validators';
import { PawOsSatelliteHost } from '@/features/paw-os/PawOsSatelliteHost';
import type { RoomSummary } from '@/features/rooms/room-types';
import { useRoomLiveStore } from '@/features/rooms/state/live-store';
import { MockControlTransport } from '@/test/mock-transport';
import { PawRoomFocusOverview } from './PawRoomFocusOverview';
import { PawRoomConversation } from './PawRoomWorkspace';
import { buildRoomFocusProjection, type RoomFocusProjection } from './room-focus-projection';
import {
  roomDispatchPlans,
  roomDispatchWaves,
  roomToolActivityLine,
  roomToolEvidence,
  roomToolSummaryIsMachine,
} from './room-gravity-projection';

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

afterEach(() => {
  cleanup();
  useRoomLiveStore.setState({ projections: {} });
});

const machineTokenPattern = /^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$/u;

function harnessToolActivities() {
  return harness.projection.activityOrder
    .map((id) => harness.projection.activitiesById[id])
    .filter((activity): activity is NonNullable<typeof activity> => Boolean(activity))
    .filter((activity) => String(activity.payload.sourceEventType ?? '').startsWith('tool'));
}

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

  it('renders the collaboration console as one mesh with owners, blockers and verifiers', () => {
    const { container } = render(<PawRoomFocusOverview focus={harness.focus} onOpenParticipant={vi.fn()} />);

    // Pulse counters mirror the real numbers.
    const pulse = screen.getByLabelText('协作摘要');
    expect(pulse).toHaveTextContent('受阻');
    expect(pulse.querySelectorAll('.paw-room-focus-overview__pulse-bar > i').length).toBeGreaterThanOrEqual(2);

    // Every real partner and WorkItem is exactly one clickable mesh node.
    const mesh = screen.getByRole('group', { name: '协作网状图' });
    expect(within(mesh).getAllByRole('button')).toHaveLength(
      harness.focus.partners.length + harness.focus.workItems.length,
    );
    // The real parallel wave keeps its two lanes readable on the work nodes.
    expect(within(mesh).getAllByText('∥ 轨道 1/2').length).toBeGreaterThanOrEqual(1);
    expect(within(mesh).getAllByText('∥ 轨道 2/2').length).toBeGreaterThanOrEqual(1);
    // The two wave planets stay clickable owners with their live states.
    expect(within(mesh).getByRole('button', { name: /^Venus，/ })).toBeInTheDocument();
    expect(within(mesh).getByRole('button', { name: /^Jupiter，/ })).toBeInTheDocument();

    // Edges exist only for recorded relations: one ownership edge per owned
    // task and one review edge per recorded verdict (>= 4 in this fixture).
    const owned = new Set(harness.focus.workItems
      .filter((item) => item.ownerParticipantId)
      .map((item) => item.id));
    expect(container.querySelectorAll('.paw-room-focus-overview__mesh-edge[data-kind="ownership"]')).toHaveLength(owned.size);
    expect(container.querySelectorAll('.paw-room-focus-overview__mesh-edge[data-kind="review"]').length).toBeGreaterThanOrEqual(4);

    // The blocked task is the red node, and — as the strongest state — the
    // default selection, so its real blocker reads in the inspector.
    expect(container.querySelector('.paw-room-focus-overview__mesh-node--work[data-state="blocked"]')).not.toBeNull();
    expect(screen.getByRole('region', { name: '焦点详情' })).toHaveTextContent('WorkDocument 尚未完成开工与交付同步');

    // The machine enum never leaks into the reader-facing console.
    expect(screen.getByLabelText('Sol 协作态势').textContent).not.toContain('route_decision');
  });

  it('keeps one row per task in the production snapshot window — the paper UI double-count is gone', () => {
    // Production reduces the snapshot's recent event page (373 events), not the
    // full history. In that window the paper UI showed 任务树 6 项 / 完成 5,
    // because the Core acceptance migration task was counted twice: once as
    // WorkItem …0002 and again as its own bare dispatch row. One task, one row.
    const page = parseRoomEventSnapshot(JSON.parse(readFileSync(resolve(root, 'room/snapshot.json'), 'utf8')));
    const projection = reduceRoomEvents(createRoomProjection(harness.room.id), page.events);
    const focus = buildRoomFocusProjection(harness.room, projection);

    expect(focus.counts).toEqual({ active: 0, review: 0, blocked: 1, completed: 4 });
    expect(focus.workItems).toHaveLength(5);
    const objectives = focus.workItems.map((item) => item.objective);
    expect(new Set(objectives).size).toBe(objectives.length);
    // Every task the designer named stays visible with its real long text.
    expect(objectives.some((objective) => objective.includes('Core acceptance migration'))).toBe(true);
    expect(objectives.some((objective) => objective.includes('smoke test'))).toBe(true);
    // The dispatch itself is flow, not a duplicate task row.
    expect(focus.flow.some((packet) => packet.kind === 'dispatch')).toBe(true);
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

    const cards = [...container.querySelectorAll('.ccui-tool-card')]
      .filter((card) => card.textContent?.includes('任务分派'));
    expect(cards.length).toBeGreaterThanOrEqual(2);
    const texts = cards.map((card) => card.textContent ?? '');
    expect(texts.some((text) => text.includes('Earth → Venus · 任务分派'))).toBe(true);
    expect(texts.some((text) => text.includes('Earth → Jupiter · 任务分派'))).toBe(true);
    const waveCard = cards.find((card) => card.textContent?.includes('Earth → Venus'));
    expect(waveCard).toHaveTextContent('伙伴委派');
    expect(waveCard).toHaveTextContent('并行轨道 1/2');
    expect(waveCard).toHaveTextContent('并行实现纯逻辑与界面轨道');
    // The real core objective rides with the dispatch, not just an id — a
    // WorkItem paragraph belongs in the receipt body, not in its head line.
    expect(waveCard).not.toHaveTextContent('实现原创 3D 方块生存游戏的纯逻辑核心');
    fireEvent.click(within(waveCard!).getByRole('button'));
    expect(waveCard).toHaveTextContent('实现原创 3D 方块生存游戏的纯逻辑核心');
    // The dead label pattern (planet · 分派 with no plan) is gone.
    expect(container.textContent).not.toContain('route_decision');

    // Every tool receipt names the concrete tool, never the bare category.
    const toolNames = [...container.querySelectorAll('.ccui-tool-main strong')]
      .map((element) => element.textContent?.trim() ?? '');
    expect(toolNames.length).toBeGreaterThanOrEqual(1);
    expect(toolNames).not.toContain('工具');
  });

  it('resolves all 112 machine-id tool summaries in the 3261-event history into evidence lines', () => {
    // The Runtime echoes only the tool id as the summary for 112 of the 290
    // real tool activities (`room_partner`, `agents`, `tool_search`…). Every
    // reader row must resolve to the evidence headline with the honest state.
    const toolActivities = harnessToolActivities();
    expect(toolActivities).toHaveLength(290);
    const machine = toolActivities.filter((activity) => roomToolSummaryIsMachine(activity.summary, activity.payload));
    expect(machine).toHaveLength(112);
    for (const activity of toolActivities) {
      const line = roomToolActivityLine(activity.summary, activity.payload, activity.status);
      expect(line).not.toBe('');
      expect(machineTokenPattern.test(line)).toBe(false);
      expect(line).not.toBe(String(activity.payload.toolName ?? ''));
    }

    // The real parallel wave keeps its true op through the fallback.
    const batch = toolActivities.find((activity) => (
      (activity.payload.arguments as Record<string, unknown> | undefined)?.op === 'delegate_batch'
    ));
    expect(batch && roomToolActivityLine(batch.summary, batch.payload, batch.status))
      .toBe('行星协调 · 批量并行委派 已完成');

    // Op labels stay scoped to their owning tool: the workspace_job/browser
    // status polls in this run are never presented as partner checks.
    const jobStatus = toolActivities.find((activity) => (
      activity.payload.toolName === 'workspace_job'
      && (activity.payload.arguments as Record<string, unknown> | undefined)?.op === 'status'
    ));
    expect(jobStatus).toBeDefined();
    expect(roomToolEvidence(jobStatus!.payload)?.facts.find((fact) => fact.label === '操作')?.value).toBe('status');
  });

  it('keeps every chronology tool row a readable evidence line in the opening scene', () => {
    const slice = harness.events.filter((event) => event.sequence <= 120);
    const projection = reduceRoomEvents(createRoomProjection(harness.room.id), slice);

    const { container } = render(<PawRoomConversation
      onApprovalDecision={async () => undefined}
      onRetryTurn={() => undefined}
      projection={projection}
      retryingTurn={false}
      room={harness.room}
    />);

    const summaries = [...container.querySelectorAll('.ccui-tool-main')]
      .map((main) => main.textContent?.trim() ?? '');
    expect(summaries.length).toBeGreaterThanOrEqual(5);
    // No row text is ever the bare Runtime id (`room_partner`, `tool_search`…).
    expect(summaries.filter((summary) => machineTokenPattern.test(summary))).toEqual([]);
    // The delegate_batch tool call reads as the real gravity it exerted.
    expect(summaries.some((summary) => summary.includes('行星协调 · 批量并行委派 已完成'))).toBe(true);
  });

  it('expands the coordinator satellite to the real sent and modified evidence — no empty tool rows', async () => {
    // The opening scene: the coordinator writes ROOT.md/AGENTS.md and pulls
    // both partners with one delegate_batch (seq 30-110 of the real run).
    const slice = harness.events.filter((event) => event.sequence >= 30 && event.sequence <= 110);
    const projection = reduceRoomEvents(createRoomProjection(harness.room.id), slice);
    useRoomLiveStore.setState({ projections: { [harness.room.id]: projection } });
    const roomGet = JSON.parse(readFileSync(resolve(root, 'room/get.json'), 'utf8')) as Record<string, unknown>;
    const transport = new MockControlTransport({ routes: { 'agent.room.get': roomGet } });
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    render(
      <ControlTransportProvider transport={transport}>
        <QueryClientProvider client={queryClient}>
          <PawOsSatelliteHost target={{
            kind: 'participant', id: 'participant:10000000-0000-4000-8000-000000000001',
            roomId: harness.room.id, title: 'Agent 3', subtitle: 'coordinator',
          }} />
        </QueryClientProvider>
      </ControlTransportProvider>,
    );

    const timeline = await screen.findByRole('log', { name: '伙伴公开对话时间线' });
    const receipts = [...timeline.querySelectorAll('.ccui-tool-card')];
    const messages = receipts.map((card) => card.querySelector('.ccui-tool-main')?.textContent?.trim() ?? '');
    expect(messages.length).toBeGreaterThanOrEqual(5);
    // Real prose summaries survive; machine ids never surface as row text.
    expect(messages.some((message) => message.includes('已创建 ROOT.md'))).toBe(true);
    expect(messages.some((message) => message.includes('行星协调 · 批量并行委派 已完成'))).toBe(true);
    expect(messages.filter((message) => machineTokenPattern.test(message))).toEqual([]);

    // The write receipt expands to the file it really modified.
    const writeRow = receipts.find((card) => card.textContent?.includes('已创建 ROOT.md')) as HTMLElement;
    expect(writeRow).toBeDefined();
    fireEvent.click(within(writeRow).getByRole('button'));
    expect(writeRow).toHaveTextContent('docs/agent/ROOT.md');
  });
});
