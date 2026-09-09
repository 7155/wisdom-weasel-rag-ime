import { describe, expect, it } from 'vitest';
import { createRoomProjection, type RoomActivityProjection } from '@/contracts/room-reducer';
import {
  createPawDesktopStore,
  type PawWindowNode,
} from '../runtime/desktop-store';
import {
  isCollaborationSatellite,
  layoutCollaborationFocus,
  normalizeCollaborationFocusFrames,
  roomFocusPartnerRegions,
  roomWindowFlowGroups,
  windowBelongsToFocus,
  windowFlowArrivalPulse,
} from './PawWindowLayer';

describe('PAWOS collaboration focus', () => {
  it('keeps Room focus ownership separate from satellite classification', () => {
    const participant = windowNode('participant-window', {
      kind: 'participant',
      id: 'participant-a',
      roomId: 'room-a',
      title: '伙伴 A',
    });
    const subagent = windowNode('subagent-window', {
      kind: 'subagent',
      id: 'run-a',
      sessionId: 'session-a',
      title: '子 Agent A',
    });

    expect(isCollaborationSatellite(participant)).toBe(false);
    expect(isCollaborationSatellite(subagent)).toBe(true);
    expect(isCollaborationSatellite({ ...participant, minimized: true })).toBe(false);
    expect(isCollaborationSatellite(windowNode('room-main', {
      kind: 'room', id: 'room-a', title: 'Room A',
    }))).toBe(false);
  });

  it('keeps focus while closing or minimizing satellites when the Room main survives', () => {
    const store = createPawDesktopStore();
    const mainId = store.getState().openApp('agent', {
      entityId: 'room-a',
      target: { kind: 'room', id: 'room-a', title: 'Room A' },
    });
    const participantId = store.getState().openApp('agent', {
      entityId: 'participant-a',
      target: { kind: 'participant', id: 'participant-a', roomId: 'room-a', title: '伙伴 A' },
    });
    store.getState().setCollaborationFocusGroup('room:room-a');

    store.getState().closeWindow(participantId);
    expect(store.getState().collaborationFocusGroup).toBe('room:room-a');

    const secondParticipantId = store.getState().openApp('agent', {
      entityId: 'participant-b',
      target: { kind: 'participant', id: 'participant-b', roomId: 'room-a', title: '伙伴 B' },
    });
    store.getState().minimizeWindow(secondParticipantId);
    expect(store.getState().collaborationFocusGroup).toBe('room:room-a');

    store.getState().closeWindow(mainId);
    expect(store.getState().collaborationFocusGroup).toBeNull();
  });

  it('enters and exits an explicit Room focus mode without mutating ordinary window bounds', () => {
    const store = createPawDesktopStore();
    const mainId = store.getState().openApp('agent', {
      entityId: 'room-a',
      target: { kind: 'room', id: 'room-a', title: 'Room A' },
    });
    const ordinaryBounds = store.getState().windows[mainId]!.bounds;
    store.getState().openApp('agent', {
      entityId: 'participant-a',
      target: { kind: 'participant', id: 'participant-a', roomId: 'room-a', title: '伙伴 A' },
    });

    expect(store.getState().collaborationFocusGroup).toBeNull();
    expect(store.getState().windows[mainId]!.bounds).toEqual(ordinaryBounds);

    store.getState().setCollaborationFocusGroup(null);
    expect(store.getState().collaborationFocusGroup).toBeNull();
    expect(store.getState().windows[mainId]!.bounds).toEqual(ordinaryBounds);
    expect(store.getState().windows['agent:participant-a']).toBeDefined();

    store.getState().focusWindow('agent:participant-a');
    expect(store.getState().collaborationFocusGroup).toBeNull();

    store.getState().setCollaborationFocusGroup('room:room-a');
    expect(store.getState().collaborationFocusGroup).toBe('room:room-a');
  });

  it('restores the valid pre-focus active window and keeps it across repeated focus updates', () => {
    const store = createPawDesktopStore();
    const returnId = store.getState().openApp('project-workbench');
    const roomId = store.getState().openApp('agent', {
      entityId: 'room-a',
      target: { kind: 'room', id: 'room-a', title: 'Room A' },
    });
    store.getState().focusWindow(returnId);
    store.getState().openApp('agent', {
      background: true,
      target: { kind: 'participant', id: 'participant-a', roomId: 'room-a', title: '伙伴 A' },
    });
    store.getState().setCollaborationFocusGroup('room:room-a');
    store.getState().setCollaborationFocusGroup('room:room-b');
    store.getState().setCollaborationFocusGroup('room:room-b');

    expect(store.getState().collaborationFocusReturnWindowId).toBe(returnId);
    store.getState().setCollaborationFocusGroup(null);
    expect(store.getState().activeWindowId).toBe(returnId);
    expect(store.getState().stack.at(-1)).toBe(returnId);
    expect(store.getState().windows[roomId]).toBeDefined();
  });

  it('falls back to the Room primary when the pre-focus window was closed', () => {
    const store = createPawDesktopStore();
    const returnId = store.getState().openApp('project-workbench');
    const roomId = store.getState().openApp('agent', {
      entityId: 'room-a',
      target: { kind: 'room', id: 'room-a', title: 'Room A' },
    });
    store.getState().focusWindow(returnId);
    store.getState().setCollaborationFocusGroup('room:room-a');
    store.getState().closeWindow(returnId);

    store.getState().setCollaborationFocusGroup(null);
    expect(store.getState().activeWindowId).toBe(roomId);
    expect(store.getState().collaborationFocusReturnWindowId).toBeNull();
  });

  it.each([
    { width: 1280, height: 720 },
    { width: 934, height: 867 },
    { width: 390, height: 720 },
  ])('gives the main Room the full canvas at $width×$height when no partner window is open', ({ width, height }) => {
    const frames = layoutCollaborationFocus(roomFocusNodes(0), { width, height }, { modeBarHeight: 46 });
    expect([...frames.keys()]).toEqual(['main']);
    expect(frames.get('main')).toEqual({ x: 10, y: 104, width: width - 20, height: height - 114 });
  });

  it.each([{ width: 1280, height: 720 }, { width: 1440, height: 900 }, { width: 1900, height: 1300 }])('surrounds the centered Room with four retained partner windows at $width×$height', (viewport) => {
    const nodes = roomFocusNodes(4);
    const first = layoutCollaborationFocus(nodes, viewport, { modeBarHeight: 46, selectedParticipantId: 'participant-2' });
    const second = layoutCollaborationFocus(nodes, viewport, { modeBarHeight: 46, selectedParticipantId: 'participant-3' });
    expect([...first.keys()]).toEqual(nodes.map((node) => node.id));
    expect(second).toEqual(first);
    expect(first.get('main')!.width).toBeGreaterThanOrEqual(640);
    const main = first.get('main')!;
    expect(main.x + main.width / 2).toBeCloseTo(viewport.width / 2);
    expect(nodes.slice(1).filter((node) => first.get(node.id)!.x < main.x)).toHaveLength(2);
    expect(nodes.slice(1).filter((node) => first.get(node.id)!.x > main.x + main.width)).toHaveLength(2);
    const frames = [...first.values()];
    for (let index = 0; index < frames.length; index += 1) {
      for (const other of frames.slice(index + 1)) expect(overlaps(frames[index]!, other)).toBe(false);
    }
    for (const frame of first.values()) {
      expect(frame.x + frame.width).toBeLessThanOrEqual(viewport.width - 10);
      expect(frame.y + frame.height).toBeLessThanOrEqual(viewport.height - 10);
    }
  });

  it.each([{ width: 934, height: 867 }, { width: 390, height: 720 }])(
    'stacks retained partners below the main composer without horizontal overflow at $width×$height',
    (viewport) => {
      const nodes = roomFocusNodes(4);
      const frames = layoutCollaborationFocus(nodes, viewport, { modeBarHeight: 46 });
      expect([...frames.keys()]).toEqual(nodes.map((node) => node.id));
      const main = frames.get('main')!;
      for (const node of nodes.slice(1)) {
        const detail = frames.get(node.id)!;
        expect(detail.y).toBeGreaterThan(main.y + main.height);
        expect(detail.x).toBeGreaterThanOrEqual(10);
        expect(detail.x + detail.width).toBeLessThanOrEqual(viewport.width - 10);
        expect(detail.width).toBeGreaterThanOrEqual(280);
      }
      expect(frames.get('participant-3')!.y).toBeGreaterThan(frames.get('participant-0')!.y);
      const regions = roomFocusPartnerRegions(frames, viewport);
      expect(regions).toHaveLength(1);
      expect(regions[0]!.key).toBe('bottom');
      expect(regions[0]!.contentHeight).toBeGreaterThan(regions[0]!.bounds.height);
    },
  );

  it.each([
    { width: 1920, height: 1080 }, { width: 1440, height: 900 },
    { width: 1365, height: 768 }, { width: 1280, height: 720 },
    { width: 934, height: 867 }, { width: 390, height: 720 },
  ])('keeps 1, 3, 4 and 8 partners reachable in bounded scrolling regions at $width×$height', (viewport) => {
    for (const count of [1, 3, 4, 8]) {
      const nodes = roomFocusNodes(count);
      const frames = layoutCollaborationFocus(nodes, viewport, { modeBarHeight: 46 });
      const regions = roomFocusPartnerRegions(frames, viewport);
      expect([...frames.keys()]).toEqual(nodes.map((node) => node.id));
      expect(regions.flatMap((region) => region.windowIds).sort()).toEqual(nodes.slice(1).map((node) => node.id).sort());
      expect(frames.get('main')!.width).toBeGreaterThanOrEqual(Math.min(640, viewport.width - 20));
      for (const region of regions) {
        expect(region.bounds.x).toBeGreaterThanOrEqual(10);
        expect(region.bounds.x + region.bounds.width).toBeLessThanOrEqual(viewport.width - 10);
        expect(region.bounds.y + region.bounds.height).toBeLessThanOrEqual(viewport.height - 10);
        for (const id of region.windowIds) {
          const frame = frames.get(id)!;
          expect(frame.width).toBeGreaterThanOrEqual(280);
          expect(frame.height).toBeGreaterThanOrEqual(280);
          expect(frame.x).toBeGreaterThanOrEqual(region.bounds.x);
          // The native host's visible vertical scrollbar consumes 11px.
          expect(frame.x + frame.width).toBeLessThanOrEqual(region.bounds.x + region.bounds.width - 11);
          expect(frame.y + frame.height).toBeLessThanOrEqual(region.bounds.y + region.contentHeight);
        }
      }
      const values = [...frames.values()];
      for (let index = 0; index < values.length; index += 1) {
        for (const other of values.slice(index + 1)) expect(overlaps(values[index]!, other)).toBe(false);
      }
    }
  });

  it.each([{ width: 1440, height: 900 }, { width: 934, height: 867 }, { width: 390, height: 720 }])('constrains user adjustments to the partner area at $width×$height without moving the main or persisted windows', (viewport) => {
    const nodes = roomFocusNodes(4);
    const before = nodes.map((node) => ({ ...node.bounds }));
    const computed = layoutCollaborationFocus(nodes, viewport, { modeBarHeight: 46, selectedParticipantId: 'removed' });
    const normalized = normalizeCollaborationFocusFrames(computed, {
      main: { x: -117, y: 400, width: 300, height: 250 },
      'participant-0': { x: 700, y: 20, width: 280, height: 500 },
    }, viewport, { modeBarHeight: 46 }, true);
    expect(normalized.get('main')).toEqual(computed.get('main'));
    for (const node of nodes.slice(1)) {
      const frame = normalized.get(node.id)!;
      expect(overlaps(normalized.get('main')!, frame)).toBe(false);
      expect(frame.x).toBeGreaterThanOrEqual(10);
      expect(frame.x + frame.width).toBeLessThanOrEqual(viewport.width - 10);
    }
    expect(nodes.map((node) => node.bounds)).toEqual(before);
  });

  it('does not leak unowned documents or results into the current Room', () => {
    expect(windowBelongsToFocus(windowNode('document', {
      kind: 'work-document', id: 'doc-a', title: '无归属文档',
    }), 'room:room-a')).toBe(false);
    expect(windowBelongsToFocus(windowNode('result', {
      kind: 'result', id: 'result-a', title: '无归属结果', resultKind: 'artifact',
    }), 'room:room-a')).toBe(false);
  });

  it('keeps Runtime projections, Room panels and Session subagents out of the Room planet layout', () => {
    const targets = [
      { kind: 'room', id: 'room-a', title: '态势', panel: 'focus' as const },
      { kind: 'process-terminal', id: 'run-a', title: 'pnpm test', roomId: 'room-a', sessionId: 'session-a', toolCallId: 'call-a', command: 'pnpm test' },
      { kind: 'browser-target', id: 'browser-a', title: 'Browser', roomId: 'room-a', sessionId: 'session-a', toolCallId: 'call-a', targetId: 'target-a', url: 'http://localhost' },
      { kind: 'subagent', id: 'subagent-a', title: '子 Agent', sessionId: 'session-a' },
    ] as const;
    for (const [index, target] of targets.entries()) {
      const node = windowNode(`auxiliary-${index}`, target);
      expect(windowBelongsToFocus(node, 'room:room-a')).toBe(false);
      if (target.kind === 'subagent') expect(isCollaborationSatellite(node)).toBe(true);
      else expect(isCollaborationSatellite(node)).toBe(false);
    }
  });

  it('projects a real ContextRef receipt from the Room main window to its participant satellite', () => {
    const projection = createRoomProjection('room-a');
    projection.activityOrder.push('context-a');
    projection.activitiesById['context-a'] = {
      id: 'context-a',
      turnId: 'turn-a',
      participantId: 'participant-a',
      sourceSessionId: 'session-a',
      kind: 'participant_activity',
      status: 'completed',
      summary: '已送达上下文',
      payload: {
        targetParticipantId: 'participant-a',
        contextRefs: ['context://room-a/brief'],
      },
      createdAtMs: 10,
      updatedAtMs: 12,
    };
    const windows = {
      main: windowNode('main', { kind: 'room', id: 'room-a', title: 'Room A' }),
      participant: windowNode('participant', {
        kind: 'participant', id: 'participant-a', roomId: 'room-a', title: '伙伴 A',
      }),
    };

    const groups = roomWindowFlowGroups(windows, { 'room-a': projection });
    expect(groups).toHaveLength(1);
    expect(groups[0]?.packets).toEqual([
      expect.objectContaining({
        id: 'activity:context-a',
        kind: 'context',
        sourceId: 'root',
        targetIds: ['participant-a'],
      }),
    ]);
    const arrival = windowFlowArrivalPulse(groups, new Set());
    expect(arrival.sourceWindowIds).toEqual(new Set(['main']));
    expect(arrival.targetWindowIds).toEqual(new Set(['participant']));
  });

  it('reuses the WorkItem producer review mapping for cross-window packets', () => {
    const work = {
      id: 'work-child',
      parentWorkId: 'work-root',
      createdByParticipantId: 'participant-a',
      accountableParticipantId: 'participant-a',
      currentOwnerParticipantId: 'participant-a',
      artifactRefs: ['artifact:child'],
      evidenceRefs: ['trace:child'],
    };
    const projection = createRoomProjection('room-a');
    projection.activityOrder.push('work-submitted', 'work-completed');
    projection.activitiesById['work-submitted'] = activity({
      id: 'work-submitted',
      kind: 'participant_activity',
      participantId: 'participant-b',
      payload: { activityKind: 'work', phase: 'submitted', workItemId: 'work-child', work },
    });
    projection.activitiesById['work-completed'] = activity({
      id: 'work-completed',
      kind: 'participant_activity',
      participantId: 'participant-b',
      payload: { activityKind: 'work', phase: 'completed', workItemId: 'work-child', work },
    });
    const windows = {
      main: windowNode('main', { kind: 'room', id: 'room-a', title: 'Room A' }),
      owner: windowNode('owner', { kind: 'participant', id: 'participant-a', roomId: 'room-a', title: '伙伴 A' }),
      reviewer: windowNode('reviewer', { kind: 'participant', id: 'participant-b', roomId: 'room-a', title: '伙伴 B' }),
    };

    expect(roomWindowFlowGroups(windows, { 'room-a': projection })[0]?.packets).toEqual([
      expect.objectContaining({
        id: 'activity:work-submitted', kind: 'review', sourceId: 'participant-b', targetIds: ['participant-a'],
        status: 'waiting', workItemId: 'work-child', refs: ['artifact:child', 'trace:child'],
      }),
      expect.objectContaining({
        id: 'activity:work-completed', kind: 'review', sourceId: 'participant-b', targetIds: ['participant-a'],
        status: 'completed', workItemId: 'work-child', refs: ['artifact:child', 'trace:child'],
      }),
    ]);
  });

  it.each([
    {
      id: 'intercom-a',
      participantId: null,
      payload: { sourceEventType: 'intercom', targetParticipantId: 'participant-a' },
      expectedKind: 'intercom',
      expectedSource: 'root',
      expectedTarget: 'participant-a',
    },
    {
      id: 'approval-signal-a',
      participantId: 'participant-a',
      payload: { sourceEventType: 'approval_required' },
      expectedKind: 'approval',
      expectedSource: 'participant-a',
      expectedTarget: 'root',
    },
  ] as const)('classifies $id the same way in the panel and cross-window flow', ({ id, participantId, payload, expectedKind, expectedSource, expectedTarget }) => {
    const projection = createRoomProjection('room-a');
    projection.activityOrder.push(id);
    projection.activitiesById[id] = {
      id,
      turnId: 'turn-a',
      participantId,
      sourceSessionId: participantId ? 'session-a' : '',
      kind: 'participant_activity',
      status: 'completed',
      summary: id,
      payload,
      createdAtMs: 14,
      updatedAtMs: 14,
    };
    const windows = {
      main: windowNode('main', { kind: 'room', id: 'room-a', title: 'Room A' }),
      participant: windowNode('participant', {
        kind: 'participant', id: 'participant-a', roomId: 'room-a', title: '伙伴 A',
      }),
    };

    expect(roomWindowFlowGroups(windows, { 'room-a': projection })[0]?.packets).toEqual([
      expect.objectContaining({
        id: `activity:${id}`,
        kind: expectedKind,
        sourceId: expectedSource,
        targetIds: [expectedTarget],
      }),
    ]);
  });

  it('projects a real participant approval request back to the Room main window', () => {
    const projection = createRoomProjection('room-a');
    projection.activityOrder.push('approval-a');
    projection.activitiesById['approval-a'] = {
      id: 'approval-a',
      turnId: 'turn-a',
      participantId: 'participant-a',
      sourceSessionId: 'session-a',
      kind: 'approval_required',
      status: 'waiting',
      summary: '等待批准发布检查',
      payload: {
        sourceEventType: 'approval_required',
        approvalId: 'approval:a',
        payloadSha256: 'a'.repeat(64),
      },
      createdAtMs: 20,
      updatedAtMs: 20,
    };
    const windows = {
      main: windowNode('main', { kind: 'room', id: 'room-a', title: 'Room A' }),
      participant: windowNode('participant', {
        kind: 'participant', id: 'participant-a', roomId: 'room-a', title: '伙伴 A',
      }),
    };

    const groups = roomWindowFlowGroups(windows, { 'room-a': projection });

    expect(groups[0]?.packets).toEqual([
      expect.objectContaining({
        id: 'activity:approval-a',
        kind: 'approval',
        sourceId: 'participant-a',
        targetIds: ['root'],
      }),
    ]);
  });

  it('emits one arrival for a new event revision and does not replay a seen receipt', () => {
    const group = {
      roomId: 'room-a',
      points: new Map([
        ['root', { x: 10, y: 10 }],
        ['participant-a', { x: 100, y: 100 }],
      ]),
      windowIds: new Map([
        ['root', 'main'],
        ['participant-a', 'participant'],
      ]),
      packets: [{
        id: 'message:answer-a',
        pulseKey: 'message:answer-a:completed:12',
        sourceId: 'participant-a',
        targetIds: ['root'],
        kind: 'answer' as const,
      }],
    };

    expect(windowFlowArrivalPulse([group], new Set()).packetPulseKeys.size).toBe(1);
    expect(windowFlowArrivalPulse([group], new Set(['message:answer-a:completed:12'])).packetPulseKeys.size).toBe(0);
  });

  it('keeps the composer above the lower edge without an old flow ledger overlay', () => {
    const frames = layoutCollaborationFocus([
      windowNode('main', { kind: 'room', id: 'room-a', title: 'Room A' }),
      windowNode('participant-a', {
        kind: 'participant', id: 'participant-a', roomId: 'room-a', title: 'Earth',
      }),
    ], { width: 1280, height: 720 }, { modeBarHeight: 46, ledgerHeight: 0 });

    expect(Math.max(...[...frames.values()].map((frame) => frame.y + frame.height))).toBe(710);
  });
});

function windowNode(
  id: string,
  target: NonNullable<PawWindowNode['target']>,
): PawWindowNode {
  return {
    id,
    appId: 'agent',
    title: target.title,
    target,
    bounds: { x: id === 'main' ? 100 : 800, y: 80, width: 360, height: 280 },
    minimized: false,
  };
}

function activity({ id, kind, payload, participantId = 'participant-a' }: {
  id: string;
  kind: string;
  payload: Record<string, unknown>;
  participantId?: string | null;
}): RoomActivityProjection {
  return {
    id,
    turnId: 'turn-a',
    participantId,
    sourceSessionId: participantId ? `session-${participantId}` : '',
    kind,
    status: 'completed',
    summary: id,
    payload,
    createdAtMs: 10,
    updatedAtMs: 10,
  };
}

function overlaps(left: PawWindowNode['bounds'], right: PawWindowNode['bounds']): boolean {
  return left.x < right.x + right.width
    && left.x + left.width > right.x
    && left.y < right.y + right.height
    && left.y + left.height > right.y;
}

function roomFocusNodes(count: number): PawWindowNode[] {
  return [
    windowNode('main', { kind: 'room', id: 'room-a', title: 'Room A' }),
    ...Array.from({ length: count }, (_, index) => windowNode(`participant-${index}`, {
      kind: 'participant', id: `participant-${index}`, roomId: 'room-a', title: `伙伴 ${index + 1}`,
    })),
  ];
}
