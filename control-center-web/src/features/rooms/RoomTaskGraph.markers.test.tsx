import { cleanup, fireEvent, render } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { ControlTransportProvider } from '@/app/control-transport';
import { createRoomProjection } from '@/contracts/room-reducer';
import { MockControlTransport } from '@/test/mock-transport';
import type { RoomSummary } from './room-types';
import { RoomTaskGraph } from './RoomTaskGraph';
import roomsCss from './rooms.css?raw';

afterEach(cleanup);

describe('RoomTaskGraph SVG marker ownership', () => {
  it('keeps marker ids unique and markerEnd references local to each mounted graph', () => {
    const fixture = markerFixture();
    const { container } = render(
      <ControlTransportProvider transport={new MockControlTransport()}>
        <RoomTaskGraph {...fixture} />
        <RoomTaskGraph {...fixture} />
      </ControlTransportProvider>,
    );

    const taskGraphs = [...container.querySelectorAll<SVGSVGElement>('.room-cockpit__task-dag')];
    const peerGraphs = [...container.querySelectorAll<SVGSVGElement>('.room-cockpit__peer-network')];
    const graphs = [...taskGraphs, ...peerGraphs];
    expect(taskGraphs).toHaveLength(2);
    expect(peerGraphs).toHaveLength(2);

    const markerIds = [...container.querySelectorAll<SVGMarkerElement>('marker')]
      .map((marker) => marker.id);
    expect(new Set(markerIds).size).toBe(markerIds.length);

    for (const graph of graphs) {
      const localMarkerIds = new Set(
        [...graph.querySelectorAll<SVGMarkerElement>('defs marker')].map((marker) => marker.id),
      );
      const markerReferences = [...graph.querySelectorAll<SVGPathElement>('[marker-end]')]
        .map((path) => path.getAttribute('marker-end'))
        .filter((reference): reference is string => Boolean(reference));

      expect(markerReferences.length).toBeGreaterThan(0);
      for (const reference of markerReferences) {
        expect(reference).toMatch(/^url\(#.+\)$/);
        expect(localMarkerIds).toContain(reference.slice(5, -1));
      }
    }
  });

  it('uses a reversible controlled disclosure for peer evidence instead of native details', () => {
    const fixture = markerFixture();
    const { container, rerender } = render(
      <ControlTransportProvider transport={new MockControlTransport()}>
        <RoomTaskGraph {...fixture} />
      </ControlTransportProvider>,
    );
    const trigger = container.querySelector<HTMLButtonElement>('.room-cockpit__peer-evidence > .room-cockpit__disclosure-summary');
    expect(trigger).not.toBeNull();
    expect(trigger).toHaveAttribute('aria-expanded', 'true');
    fireEvent.click(trigger!);
    expect(trigger).toHaveAttribute('aria-expanded', 'false');
    expect(container.querySelector('.room-cockpit__peer-evidence .agent-smooth-reveal')).toHaveAttribute('data-state', 'closing');
    expect(container.querySelector('details.room-cockpit__peer-evidence')).not.toBeInTheDocument();
    rerender(
      <ControlTransportProvider transport={new MockControlTransport()}>
        <RoomTaskGraph {...fixture} />
      </ControlTransportProvider>,
    );
    expect(trigger).toHaveAttribute('aria-expanded', 'false');
  });

  it('keeps disclosure controls reachable at the 375px Room shell breakpoint', () => {
    expect(roomsCss).toContain('@container room-cockpit-shell (max-width: 375px)');
    expect(roomsCss).toContain('.room-cockpit__subagent > .room-cockpit__disclosure-summary { grid-template-columns: auto minmax(0, 1fr); }');
  });

  it('keeps Room lane metadata single-line at narrow window widths', () => {
    expect(roomsCss).toMatch(/\.room-agent-lane__identity strong \{[^}]*min-width: 0;[^}]*flex: 1 1 auto;[^}]*text-overflow: ellipsis;[^}]*white-space: nowrap;/);
    expect(roomsCss).toMatch(/\.room-agent-lane__identity small \{[^}]*min-width: 0;[^}]*max-width: 42%;[^}]*flex: 0 1 auto;[^}]*text-overflow: ellipsis;[^}]*white-space: nowrap;/);
    expect(roomsCss).toMatch(/\.room-agent-activity strong \{[^}]*min-width: 0;[^}]*overflow: hidden;[^}]*text-overflow: ellipsis;[^}]*white-space: nowrap;/);
    expect(roomsCss).toMatch(/\.room-status-activity__heading strong \{[^}]*min-width: 0;[^}]*overflow: hidden;[^}]*text-overflow: ellipsis;[^}]*white-space: nowrap;/);
    expect(roomsCss).toMatch(/\.room-status-activity small \{[^}]*min-width: 0;[^}]*overflow: hidden;[^}]*text-overflow: ellipsis;[^}]*white-space: nowrap;/);
    expect(roomsCss).toMatch(/\.room-status-work__item p > \.room-status-work__value \{[^}]*min-width: 0;[^}]*overflow: hidden;[^}]*text-overflow: ellipsis;[^}]*white-space: nowrap;/);
    expect(roomsCss).toContain('@container paw-window (max-width: 430px)');
    expect(roomsCss).toContain(".paw-window-shell[data-app='agent'] .room-status-work__item > div > header strong");
    expect(roomsCss).not.toContain('.paw-os-app-window');
  });
});

function markerFixture() {
  const room: RoomSummary = {
    id: 'room-marker',
    title: 'Marker 隔离',
    status: 'active',
    routingPolicy: 'moderator',
    moderatorParticipantId: 'participant-a',
    updatedAtMs: 1,
    participants: [
      { id: 'participant-a', sessionId: '', roleId: 'a', roleVersion: '1', displayName: 'A', status: 'active', ordinal: 0 },
      { id: 'participant-b', sessionId: '', roleId: 'b', roleVersion: '1', displayName: 'B', status: 'active', ordinal: 1 },
    ],
  };
  const rootId = 'root-marker';
  const activityId = 'activity-marker';
  const projection = createRoomProjection(room.id);
  projection.turnsById[rootId] = {
    id: rootId,
    rootId,
    status: 'running',
    messageIds: [],
    activityIds: [activityId],
    participantIds: ['participant-a'],
    createdAtMs: 1,
    updatedAtMs: 1,
  };
  projection.turnOrder.push(rootId);
  projection.activitiesById[activityId] = {
    id: activityId,
    turnId: rootId,
    participantId: 'participant-a',
    sourceSessionId: '',
    kind: 'participant_activity',
    status: 'completed',
    summary: '直接通信',
    payload: {
      activityKind: 'intercom',
      rootId,
      dispatchId: 'dispatch-marker',
      targetParticipantId: 'participant-a',
      message: {
        id: 'message-marker',
        kind: 'ask',
        sourceParticipantId: 'participant-a',
        targetParticipantId: 'participant-b',
        status: 'delivered',
        content: '请核对 marker',
      },
    },
    createdAtMs: 1,
  };
  projection.activityOrder.push(activityId);

  return {
    room,
    runtimeWorkItems: [{
      id: rootId,
      objective: '核对图关系',
      status: 'running' as const,
      participantIds: ['participant-a'],
      sessionIds: [],
      laneCount: 1,
      toolCount: 0,
      lastSummary: '',
      updatedAtMs: 1,
    }],
    projection,
  };
}
