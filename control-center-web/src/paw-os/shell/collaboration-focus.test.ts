import { describe, expect, it } from 'vitest';
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { createElement } from 'react';
import { createRoomProjection } from '@/contracts/room-reducer';
import { createPawDesktopStore, type PawWindowNode } from '../runtime/desktop-store';
import {
  isCollaborationSatellite,
  layoutCollaborationFocus,
  PAW_WINDOW_FLOW_GEOMETRY_EVENT,
  PawRoomWindowFlowLayer,
  roomWindowFlowGroups,
  windowBelongsToFocus,
  windowFlowArrivalPulse,
  windowFlowGroupsWithLivePoints,
} from './PawWindowLayer';

describe('PAWOS collaboration focus', () => {
  it('follows the real visible satellite lifecycle and clears when the satellite is minimized', () => {
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

    expect(isCollaborationSatellite(participant)).toBe(true);
    expect(isCollaborationSatellite(subagent)).toBe(true);
    expect(isCollaborationSatellite({ ...participant, minimized: true })).toBe(false);
    expect(isCollaborationSatellite(windowNode('room-main', {
      kind: 'room', id: 'room-a', title: 'Room A',
    }))).toBe(false);
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

    expect(store.getState().collaborationFocusGroup).toBe('room:room-a');
    expect(store.getState().windows[mainId]!.bounds).toEqual(ordinaryBounds);

    store.getState().setCollaborationFocusGroup(null);
    expect(store.getState().collaborationFocusGroup).toBeNull();
    expect(store.getState().windows[mainId]!.bounds).toEqual(ordinaryBounds);
    expect(store.getState().windows['agent:participant-a']).toBeDefined();

    store.getState().focusWindow('agent:participant-a');
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
    { width: 800, height: 620 },
    { width: 560, height: 720 },
  ])('keeps the focus projection inside a $width px viewport without overlap', (viewport) => {
    const nodes = [
      windowNode('main', { kind: 'room', id: 'room-a', title: 'Room A' }),
      windowNode('participant-a', { kind: 'participant', id: 'participant-a', roomId: 'room-a', title: '伙伴 A' }),
      windowNode('participant-b', { kind: 'participant', id: 'participant-b', roomId: 'room-a', title: '伙伴 B' }),
      windowNode('participant-c', { kind: 'participant', id: 'participant-c', roomId: 'room-a', title: '伙伴 C' }),
    ];
    const frames = layoutCollaborationFocus(nodes, viewport);
    for (const frame of frames.values()) {
      expect(frame.x).toBeGreaterThanOrEqual(0);
      expect(frame.y).toBeGreaterThanOrEqual(0);
      expect(frame.x + frame.width).toBeLessThanOrEqual(viewport.width);
      expect(frame.y + frame.height).toBeLessThanOrEqual(viewport.height);
    }
    const regions = [...frames.values()];
    for (let index = 0; index < regions.length; index += 1) {
      for (let otherIndex = index + 1; otherIndex < regions.length; otherIndex += 1) {
        expect(overlaps(regions[index]!, regions[otherIndex]!)).toBe(false);
      }
    }
  });

  it.each([
    { satelliteCount: 0, width: 1280, height: 720 },
    { satelliteCount: 1, width: 1280, height: 720 },
    { satelliteCount: 5, width: 1280, height: 720 },
    { satelliteCount: 7, width: 1280, height: 720 },
    { satelliteCount: 0, width: 560, height: 720 },
    { satelliteCount: 1, width: 560, height: 720 },
    { satelliteCount: 5, width: 560, height: 720 },
    { satelliteCount: 7, width: 560, height: 720 },
  ])('reserves the Room Focus mode bar and intentionally places $satelliteCount satellites at $width px', ({ satelliteCount, width, height }) => {
    const nodes = [
      windowNode('main', { kind: 'room', id: 'room-a', title: 'Room A' }),
      ...Array.from({ length: satelliteCount }, (_, index) => windowNode(`participant-${index}`, {
        kind: 'participant', id: `participant-${index}`, roomId: 'room-a', title: `伙伴 ${index + 1}`,
      })),
    ];
    const ledgerHeight = width < 720 ? 0 : 48;
    const frames = layoutCollaborationFocus(nodes, { width, height }, { modeBarHeight: 46, ledgerHeight });

    expect(frames.size).toBe(nodes.length);
    const satelliteFrames = [...frames.entries()]
      .filter(([id]) => id !== 'main')
      .map(([, frame]) => frame);
    const horizontalRail = satelliteFrames.length >= 5
      && new Set(satelliteFrames.map((frame) => frame.y)).size === 1
      && Math.max(...satelliteFrames.map((frame) => frame.x + frame.width)) > width;
    for (const [id, frame] of frames) {
      expect(frame.y).toBeGreaterThanOrEqual(46);
      expect(frame.x).toBeGreaterThanOrEqual(0);
      if (!horizontalRail || id === 'main') expect(frame.x + frame.width).toBeLessThanOrEqual(width);
      expect(frame.y + frame.height).toBeLessThanOrEqual(height - (satelliteCount ? ledgerHeight : 0));
    }
    const regions = [...frames.values()];
    for (let index = 0; index < regions.length; index += 1) {
      for (let otherIndex = index + 1; otherIndex < regions.length; otherIndex += 1) {
        expect(overlaps(regions[index]!, regions[otherIndex]!)).toBe(false);
      }
    }
    if (satelliteCount && width >= 720) expect(frames.get('main')!.width).toBeGreaterThan(frames.get('participant-0')!.width);
    if (satelliteCount === 5 && width < 720) {
      expect(frames.get('main')!.height).toBeGreaterThanOrEqual(320);
      expect(Math.min(...[...frames.entries()].filter(([id]) => id !== 'main').map(([, frame]) => frame.height))).toBeGreaterThanOrEqual(96);
    }
  });

  it.each([5, 7])('keeps all $satelliteCount satellites readable in one horizontal rail at 560×720', (satelliteCount) => {
    const nodes = [
      windowNode('main', { kind: 'room', id: 'room-a', title: 'Room A' }),
      ...Array.from({ length: satelliteCount }, (_, index) => windowNode(`participant-${index}`, {
        kind: 'participant', id: `participant-${index}`, roomId: 'room-a', title: `伙伴 ${index + 1}`,
      })),
    ];
    const frames = layoutCollaborationFocus(nodes, { width: 560, height: 720 }, { modeBarHeight: 46, ledgerHeight: 0 });
    const main = frames.get('main')!;
    const satellites = nodes.slice(1).map((node) => frames.get(node.id)!);

    expect(frames.size).toBe(satelliteCount + 1);
    expect(main.width).toBeGreaterThanOrEqual(320);
    expect(main.height).toBeGreaterThanOrEqual(320);
    expect(new Set(satellites.map((frame) => frame.y)).size).toBe(1);
    expect(Math.min(...satellites.map((frame) => frame.width))).toBeGreaterThanOrEqual(260);
    expect(Math.min(...satellites.map((frame) => frame.height))).toBeGreaterThanOrEqual(220);
    expect(Math.max(...satellites.map((frame) => frame.x + frame.width))).toBeGreaterThan(560);
    for (let index = 1; index < satellites.length; index += 1) {
      expect(satellites[index]!.x).toBeGreaterThanOrEqual(satellites[index - 1]!.x + satellites[index - 1]!.width);
    }
    for (const satellite of satellites) expect(overlaps(main, satellite)).toBe(false);
  });

  it.each([5, 8])('keeps all $satelliteCount satellites above the window height floor in one rail at 800×720', (satelliteCount) => {
    const nodes = [
      windowNode('main', { kind: 'room', id: 'room-a', title: 'Room A' }),
      ...Array.from({ length: satelliteCount }, (_, index) => windowNode(`participant-${index}`, {
        kind: 'participant', id: `participant-${index}`, roomId: 'room-a', title: `伙伴 ${index + 1}`,
      })),
    ];
    const frames = layoutCollaborationFocus(nodes, { width: 800, height: 720 }, { modeBarHeight: 46, ledgerHeight: 0 });
    const main = frames.get('main')!;
    const satellites = nodes.slice(1).map((node) => frames.get(node.id)!);

    expect(main.height).toBeGreaterThanOrEqual(320);
    expect(new Set(satellites.map((frame) => frame.y)).size).toBe(1);
    expect(Math.min(...satellites.map((frame) => frame.height))).toBeGreaterThanOrEqual(210);
    expect(Math.max(...satellites.map((frame) => frame.x + frame.width))).toBeGreaterThan(800);
    for (const satellite of satellites) expect(overlaps(main, satellite)).toBe(false);
  });

  it('does not leak unowned documents or results into the current Room', () => {
    expect(windowBelongsToFocus(windowNode('document', {
      kind: 'work-document', id: 'doc-a', title: '无归属文档',
    }), 'room:room-a')).toBe(false);
    expect(windowBelongsToFocus(windowNode('result', {
      kind: 'result', id: 'result-a', title: '无归属结果', resultKind: 'artifact',
    }), 'room:room-a')).toBe(false);
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

  it.each([
    {
      id: 'intercom-a',
      participantId: null,
      payload: { sourceEventType: 'intercom', targetParticipantId: 'participant-a' },
      expectedKind: 'request',
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

  it('renders one transient flow label for each arriving packet target', () => {
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
      activePulseKeys: new Set([pulseKey]),
      focusGroup: 'room:room-a',
      groups: [group],
    }));

    expect(container.querySelectorAll('.paw-room-window-flow__label')).toHaveLength(1);
    unmount();
  });

  it('overrides only the dragged window point and keeps committed groups untouched otherwise', () => {
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
      packets: [],
    };

    expect(windowFlowGroupsWithLivePoints([group], {})[0]).toBe(group);
    const adjusted = windowFlowGroupsWithLivePoints([group], { participant: { x: 300, y: 200 } });
    expect(adjusted[0]?.points.get('participant-a')).toEqual({ x: 300, y: 200 });
    expect(adjusted[0]?.points.get('root')).toEqual({ x: 10, y: 10 });
    expect(group.points.get('participant-a')).toEqual({ x: 100, y: 100 });
    expect(windowFlowGroupsWithLivePoints([group], { unrelated: { x: 1, y: 1 } })[0]).toBe(group);
  });

  it('moves the flow path with the live window transform during drag and settles after release', () => {
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
      activePulseKeys: new Set<string>(),
      focusGroup: 'room:room-a',
      groups: [group],
    }));
    const initialPath = container.querySelector('.paw-room-window-flow__base')?.getAttribute('d');
    expect(initialPath).toContain('M 100 100');

    act(() => {
      window.dispatchEvent(new CustomEvent(PAW_WINDOW_FLOW_GEOMETRY_EVENT, {
        detail: { windowId: 'participant', point: { x: 320, y: 240 } },
      }));
    });
    expect(container.querySelector('.paw-room-window-flow__base')?.getAttribute('d')).toContain('M 320 240');

    act(() => {
      window.dispatchEvent(new CustomEvent(PAW_WINDOW_FLOW_GEOMETRY_EVENT, {
        detail: { windowId: 'participant', point: null },
      }));
    });
    expect(container.querySelector('.paw-room-window-flow__base')?.getAttribute('d')).toBe(initialPath);
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
    render(createElement(PawRoomWindowFlowLayer, { activePulseKeys: new Set<string>(), focusGroup: 'room:room-a', groups: [group] }));

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

function overlaps(left: PawWindowNode['bounds'], right: PawWindowNode['bounds']): boolean {
  return left.x < right.x + right.width
    && left.x + left.width > right.x
    && left.y < right.y + right.height
    && left.y + left.height > right.y;
}
