import { describe, expect, it } from 'vitest';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { createElement } from 'react';
import { createRoomProjection, type RoomActivityProjection } from '@/contracts/room-reducer';
import {
  createPawDesktopStore,
  PAW_WINDOW_MIN_HEIGHT,
  PAW_WINDOW_MIN_WIDTH,
  type PawWindowNode,
} from '../runtime/desktop-store';
import {
  isCollaborationSatellite,
  layoutCollaborationFocus,
  normalizeCollaborationFocusFrames,
  PawRoomWindowFlowLayer,
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

  it('projects only the current Room into non-overlapping focus regions', () => {
    const main = windowNode('main', { kind: 'room', id: 'room-a', title: 'Room A' });
    const left = windowNode('participant-a', {
      kind: 'participant', id: 'participant-a', roomId: 'room-a', title: '伙伴 A',
    });
    const right = windowNode('participant-b', {
      kind: 'participant', id: 'participant-b', roomId: 'room-a', title: '伙伴 B',
    });
    const otherRoom = windowNode('other-room', { kind: 'room', id: 'room-b', title: 'Room B' });
    const current = [main, left, right, otherRoom].filter((node) => windowBelongsToFocus(node, 'room:room-a'));
    const frames = layoutCollaborationFocus(current, { width: 1280, height: 720 });

    expect(current.map((node) => node.id)).toEqual(['main', 'participant-a', 'participant-b']);
    expect(frames.size).toBe(3);
    const regions = [...frames.values()];
    for (let index = 0; index < regions.length; index += 1) {
      for (let otherIndex = index + 1; otherIndex < regions.length; otherIndex += 1) {
        expect(overlaps(regions[index]!, regions[otherIndex]!)).toBe(false);
      }
    }
    expect(frames.get('main')!.width).toBeGreaterThan(frames.get('participant-a')!.width);
  });

  it.each([
    { width: 1280, height: 720, planetCount: 2 },
    { width: 1440, height: 900, planetCount: 8 },
  ])('keeps the reduced Room central and places $planetCount complete participant Sessions around it at $width×$height', ({ width, height, planetCount }) => {
    const nodes = [
      windowNode('main', { kind: 'room', id: 'room-a', title: 'Room A' }),
      ...Array.from({ length: planetCount }, (_, index) => windowNode(`participant-${index}`, {
        kind: 'participant', id: `participant-${index}`, roomId: 'room-a', title: `伙伴 ${index + 1}`,
      })),
    ];
    const frames = layoutCollaborationFocus(nodes, { width, height }, { modeBarHeight: 46, ledgerHeight: 198 });
    const main = frames.get('main')!;

    expect(frames.size).toBe(nodes.length);
    expect(main.width).toBeLessThan(width * .8);
    expect(main.height).toBeGreaterThanOrEqual(PAW_WINDOW_MIN_HEIGHT);
    expect(Math.max(...[...frames.values()].map((frame) => frame.y + frame.height))).toBe(height - 10);
    expect(Math.min(...[...frames.values()].map((frame) => frame.width))).toBeGreaterThanOrEqual(PAW_WINDOW_MIN_WIDTH);
    expect(Math.min(...[...frames.values()].map((frame) => frame.height))).toBeGreaterThanOrEqual(PAW_WINDOW_MIN_HEIGHT);
    for (const frame of frames.values()) {
      expect(frame.x).toBeGreaterThanOrEqual(0);
      expect(frame.y).toBeGreaterThanOrEqual(46);
      expect(frame.x + frame.width).toBeLessThanOrEqual(width);
      expect(frame.y + frame.height).toBeLessThanOrEqual(height);
    }
    const regions = [...frames.values()];
    for (let index = 0; index < regions.length; index += 1) {
      for (let otherIndex = index + 1; otherIndex < regions.length; otherIndex += 1) {
        expect(overlaps(regions[index]!, regions[otherIndex]!)).toBe(false);
      }
    }
  });

  it('contains five Room planet windows when a stale focus override is outside the desktop', () => {
    const viewport = { width: 1440, height: 940 };
    const nodes = [
      windowNode('main', { kind: 'room', id: 'room-a', title: 'Room A' }),
      ...Array.from({ length: 5 }, (_, index) => windowNode(`participant-${index}`, {
        kind: 'participant', id: `participant-${index}`, roomId: 'room-a', title: `伙伴 ${index + 1}`,
      })),
    ];
    const computed = layoutCollaborationFocus(nodes, viewport, { modeBarHeight: 46 });
    const overrides = {
      'participant-0': { ...computed.get('participant-0')!, x: -117.5 },
    };

    const frames = normalizeCollaborationFocusFrames(computed, overrides, viewport, { modeBarHeight: 46 }, true);

    expect(frames.size).toBe(6);
    for (const frame of frames.values()) {
      expect(frame.x).toBeGreaterThanOrEqual(0);
      expect(frame.y).toBeGreaterThanOrEqual(46);
      expect(frame.x + frame.width).toBeLessThanOrEqual(viewport.width);
      expect(frame.y + frame.height).toBeLessThanOrEqual(viewport.height);
    }
    expect(frames.get('participant-0')!.x).toBe(0);
  });

  it('lets wide focus canvases grow the perimeter slots instead of leaving thumbnail-sized planets', () => {
    const width = 1920;
    const height = 1080;
    const nodes = [
      windowNode('main', { kind: 'room', id: 'room-a', title: 'Room A' }),
      ...Array.from({ length: 4 }, (_, index) => windowNode(`participant-${index}`, {
        kind: 'participant', id: `participant-${index}`, roomId: 'room-a', title: `伙伴 ${index + 1}`,
      })),
    ];
    const frames = layoutCollaborationFocus(nodes, { width, height }, { modeBarHeight: 46 });
    const main = frames.get('main')!;
    const planets = nodes.slice(1).map((node) => frames.get(node.id)!);

    expect(Math.min(...planets.map((frame) => frame.width))).toBeGreaterThan(300);
    expect(Math.min(...planets.map((frame) => frame.height))).toBeGreaterThan(400);
    expect(main.x).toBeGreaterThan(300);
    expect(main.x + main.width).toBeLessThan(width - 300);
    expect(Math.max(...[...frames.values()].map((frame) => frame.y + frame.height))).toBe(height - 10);
    for (let index = 0; index < planets.length; index += 1) {
      for (let otherIndex = index + 1; otherIndex < planets.length; otherIndex += 1) {
        expect(overlaps(planets[index]!, planets[otherIndex]!)).toBe(false);
      }
    }
  });

  it('uses an ordered horizontal rail when a narrow Room cannot surround its planets', () => {
    const nodes = [
      windowNode('main', { kind: 'room', id: 'room-a', title: 'Room A' }),
      ...Array.from({ length: 8 }, (_, index) => windowNode(`participant-${index}`, {
        kind: 'participant', id: `participant-${index}`, roomId: 'room-a', title: `伙伴 ${index + 1}`,
      })),
    ];
    const frames = layoutCollaborationFocus(nodes, { width: 390, height: 720 }, { modeBarHeight: 46 });
    const main = frames.get('main')!;
    const planets = nodes.slice(1).map((node) => frames.get(node.id)!);

    expect(main.x).toBe(10);
    expect(main.width).toBe(370);
    expect(planets.every((frame) => frame.y === planets[0]!.y)).toBe(true);
    expect(planets.every((frame, index) => index === 0 || frame.x > planets[index - 1]!.x)).toBe(true);
    expect(planets.at(-1)!.x + planets.at(-1)!.width).toBeGreaterThan(390);
  });

  it('preserves intentional narrow Room rail overflow during focus-frame normalization', () => {
    const viewport = { width: 390, height: 720 };
    const nodes = [
      windowNode('main', { kind: 'room', id: 'room-a', title: 'Room A' }),
      ...Array.from({ length: 8 }, (_, index) => windowNode(`participant-${index}`, {
        kind: 'participant', id: `participant-${index}`, roomId: 'room-a', title: `伙伴 ${index + 1}`,
      })),
    ];
    const computed = layoutCollaborationFocus(nodes, viewport, { modeBarHeight: 46 });
    const frames = normalizeCollaborationFocusFrames(computed, {}, viewport, { modeBarHeight: 46 }, true);
    const planets = nodes.slice(1).map((node) => frames.get(node.id)!);

    expect(planets.every((frame) => frame.y === planets[0]!.y)).toBe(true);
    expect(planets.every((frame, index) => index === 0 || frame.x > planets[index - 1]!.x)).toBe(true);
    expect(planets.at(-1)!.x + planets.at(-1)!.width).toBeGreaterThan(viewport.width);
  });

  it('contains a stale Room rail override without collapsing the remaining rail', () => {
    const viewport = { width: 390, height: 720 };
    const nodes = [
      windowNode('main', { kind: 'room', id: 'room-a', title: 'Room A' }),
      ...Array.from({ length: 8 }, (_, index) => windowNode(`participant-${index}`, {
        kind: 'participant', id: `participant-${index}`, roomId: 'room-a', title: `伙伴 ${index + 1}`,
      })),
    ];
    const computed = layoutCollaborationFocus(nodes, viewport, { modeBarHeight: 46 });
    const frames = normalizeCollaborationFocusFrames(computed, {
      'participant-0': { ...computed.get('participant-0')!, x: -500 },
    }, viewport, { modeBarHeight: 46 }, true);
    const planets = nodes.slice(1).map((node) => frames.get(node.id)!);

    expect(frames.get('participant-0')!.x).toBe(0);
    expect(planets.at(-1)!.x + planets.at(-1)!.width).toBeGreaterThan(viewport.width);
    expect(planets.slice(1).every((frame, index) => frame.x > planets[index]!.x)).toBe(true);
  });

  it('keeps the Room reduced and centered when collaboration has no running participant Sessions', () => {
    const width = 1400;
    const height = 900;
    const frames = layoutCollaborationFocus([
      windowNode('main', { kind: 'room', id: 'room-a', title: 'Room A' }),
    ], { width, height }, { modeBarHeight: 46 });
    const main = frames.get('main')!;

    expect(frames.size).toBe(1);
    expect(main.width).toBeLessThan(width * .8);
    expect(main.height).toBeLessThan(height - 46 - 20);
    expect(main.x).toBeGreaterThan(10);
    expect(main.x + main.width).toBeLessThan(width - 10);
    expect(main.y).toBeGreaterThan(46);
    expect(main.y + main.height).toBeLessThan(height - 10);
    expect(main.x + main.width / 2).toBeCloseTo(width / 2, 1);
    expect(main.y + main.height / 2).toBeCloseTo((46 + height) / 2, 1);
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

  it('keeps Room flow in the compact ledger without drawing a cross-window overlay', () => {
    const pulseKey = 'message:answer-a:completed:12';
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
        id: 'message:answer-a', pulseKey,
        sourceId: 'participant-a', targetIds: ['root'], kind: 'answer' as const,
        summary: '迁移完成', status: 'completed', createdAtMs: 12,
      }],
    };

    const { container, unmount } = render(createElement(PawRoomWindowFlowLayer, {
      focusGroup: 'room:room-a',
      groups: [group],
    }));

    expect(container.querySelector('.paw-room-window-flow')).toBeNull();
    expect(container.querySelector('.paw-room-window-flow__label')).toBeNull();
    expect(screen.getByLabelText('Room 流转记录')).toBeInTheDocument();
    unmount();
  });

  it('keeps the bottom Room flow ledger collapsed until the user asks for it', () => {
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
      actorNames: new Map([
        ['root', '主 Room'],
        ['participant-a', '实现伙伴'],
      ]),
      packets: [{
        id: 'message:answer-a', pulseKey: 'message:answer-a:completed:12',
        sourceId: 'participant-a', targetIds: ['root'], kind: 'answer' as const,
        summary: '迁移完成', status: 'completed', createdAtMs: 12,
      }],
    };
    render(createElement(PawRoomWindowFlowLayer, { focusGroup: 'room:room-a', groups: [group] }));

    const ledger = screen.getByLabelText('Room 流转记录');
    const summary = within(ledger).getByText('流转记录').closest('summary')!;
    const reveal = ledger.querySelector('.ui-disclosure__reveal')!;
    expect(ledger).toHaveClass('ui-disclosure');
    expect(ledger).not.toHaveAttribute('open');
    expect(summary).toHaveAttribute('aria-expanded', 'false');
    expect(reveal).toHaveAttribute('inert');
    fireEvent.click(summary);
    expect(ledger).toHaveAttribute('open');
    expect(summary).toHaveAttribute('aria-expanded', 'true');
    fireEvent.click(summary);
    expect(summary).toHaveAttribute('aria-expanded', 'false');
    expect(reveal).toHaveAttribute('inert');
  });

  it('uses a collapsed flow ledger as an overlay instead of reserving an empty bottom band', () => {
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
