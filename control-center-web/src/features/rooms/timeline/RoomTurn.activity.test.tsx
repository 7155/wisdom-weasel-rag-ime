import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { createRoomProjection } from '@/contracts/room-reducer';
import { RoomTurn } from './RoomTurn';

describe('RoomTurn public activity detail', () => {
  afterEach(() => {
    vi.useRealTimers();
    cleanup();
  });


  it('renders provider work summaries as flat incremental rows in the user language', () => {
    const projection = roomProjection();
    projection.activitiesById['reasoning-a'] = {
      id: 'reasoning-a',
      turnId: 'turn-a',
      participantId: 'participant-a',
      sourceSessionId: 'session-a',
      kind: 'participant_activity',
      status: 'completed',
      summary: 'Identifying room_state tool details',
      payload: {
        rootId: 'root-a',
        dispatchId: 'dispatch-a',
        sourceEventType: 'reasoning_summary',
        source: 'provider_reasoning_summary',
        items: [
          'Identifying room_state tool details',
          'Designing non-overlapping parallel workwaves',
        ],
      },
      createdAtMs: 3_200,
      updatedAtMs: 3_200,
    };
    projection.turnsById['turn-a'] = {
      ...projection.turnsById['turn-a']!,
      activityIds: [...projection.turnsById['turn-a']!.activityIds, 'reasoning-a'],
      updatedAtMs: 3_200,
    };

    const view = render(roomTurn(projection));
    const update = view.container.querySelector('.room-agent-activity--reasoning');

    expect(update).toBeInTheDocument();
    expect(update?.tagName).toBe('DIV');
    expect(update).toHaveTextContent('正在检查相关代码和信息');
    expect(update).toHaveTextContent('正在整理分工和下一步');
    expect(update).not.toHaveTextContent('Identifying');
    expect(update).not.toHaveTextContent('Designing non-overlapping parallel workwaves');
    expect(view.container.querySelector('.room-reasoning-summary')).not.toBeInTheDocument();
  });

  it('pins the latest public thinking summary above the chronological tool feed', () => {
    const projection = roomProjection();
    projection.activitiesById['reasoning-a'] = {
      id: 'reasoning-a',
      turnId: 'turn-a',
      participantId: 'participant-a',
      sourceSessionId: 'session-a',
      kind: 'participant_activity',
      status: 'completed',
      summary: '正在整理持久化边界和下一步',
      payload: {
        rootId: 'root-a',
        dispatchId: 'dispatch-a',
        sourceEventType: 'reasoning_summary',
        source: 'provider_reasoning_summary',
      },
      createdAtMs: 3_200,
      updatedAtMs: 3_200,
    };
    projection.turnsById['turn-a'] = {
      ...projection.turnsById['turn-a']!,
      activityIds: [...projection.turnsById['turn-a']!.activityIds, 'reasoning-a'],
      updatedAtMs: 3_200,
    };

    const view = render(roomTurn(projection));
    const activity = view.container.querySelector('.room-agent-lane__activity')!;
    const thinking = activity.querySelector('.room-agent-activity--reasoning')!;
    const firstTool = activity.querySelector('.room-agent-activity--tool')!;

    expect(thinking).toHaveTextContent('最新思考摘要');
    expect(thinking.compareDocumentPosition(firstTool) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });


  it('shows evidence-backed returned-step progress without claiming task completion', () => {
    const view = render(roomTurn(roomProjection()));
    const progress = view.container.querySelector<HTMLElement>('.room-agent-lane__meter')!;

    expect(progress).toHaveAttribute('role', 'progressbar');
    expect(progress).toHaveAttribute('aria-label', '运行记录已返回 2 / 3');
    expect(progress).toHaveAttribute('aria-valuenow', '2');
    expect(progress).toHaveAttribute('aria-valuemax', '3');
    expect(progress).toHaveTextContent('2 / 3');
  });

  it('keeps a recovered tool miss in the feed without promoting it to the whole task headline', () => {
    const projection = roomProjection();
    projection.activitiesById['read-failed'] = {
      id: 'read-failed',
      turnId: 'turn-a',
      participantId: 'participant-a',
      sourceSessionId: 'session-a',
      kind: 'participant_activity',
      status: 'failed',
      summary: '第一次路径没有找到',
      payload: {
        rootId: 'root-a',
        dispatchId: 'dispatch-a',
        sourceEventType: 'tool_finished',
        toolName: 'read',
        toolCallId: 'call-failed',
        arguments: { path: 'missing.py' },
        error: '文件不存在',
      },
      createdAtMs: 2_900,
      updatedAtMs: 2_900,
    };
    projection.turnsById['turn-a'] = {
      ...projection.turnsById['turn-a']!,
      activityIds: ['route-a', 'wait-a', 'read-failed', 'tool-a'],
    };

    const view = render(roomTurn(projection));
    const lane = view.container.querySelector('.room-agent-lane')!;
    const failed = lane.querySelector('[data-state="failed"]')!;

    expect(lane.querySelector('.room-agent-lane__task')).not.toHaveTextContent('执行失败');
    expect(failed).toHaveTextContent('这次没有完成');
    expect(failed).toHaveTextContent('后续读取已经成功');
  });

  it('drops repeated progress records that contain no new information', () => {
    const projection = roomProjection();
    for (const [index, id] of ['progress-empty-a', 'progress-empty-b'].entries()) {
      projection.activitiesById[id] = {
        id,
        turnId: 'turn-a',
        participantId: 'participant-a',
        sourceSessionId: 'session-a',
        kind: 'participant_activity',
        status: 'completed',
        summary: '协作进度已经同步',
        payload: {
          rootId: 'root-a',
          dispatchId: 'dispatch-a',
          activityKind: 'work',
          phase: 'completed',
        },
        createdAtMs: 3_300 + index,
        updatedAtMs: 3_300 + index,
      };
    }
    projection.turnsById['turn-a'] = {
      ...projection.turnsById['turn-a']!,
      activityIds: [
        ...projection.turnsById['turn-a']!.activityIds,
        'progress-empty-a',
        'progress-empty-b',
      ],
      updatedAtMs: 3_301,
    };

    const view = render(roomTurn(projection));

    expect(view.container).not.toHaveTextContent('完成了一步');
    expect(view.container).not.toHaveTextContent('协作进度已经同步');
    expect(view.container).not.toHaveTextContent('伙伴自述');
  });

  it('keeps distinct authoritative events even when their public text matches', () => {
    const projection = roomProjection();
    for (const [index, id] of ['progress-distinct-a', 'progress-distinct-b'].entries()) {
      projection.activitiesById[id] = {
        id,
        turnId: 'turn-a',
        participantId: 'participant-a',
        sourceSessionId: 'session-a',
        kind: 'participant_activity',
        status: 'completed',
        summary: '已核对用户路径',
        payload: {
          rootId: 'root-a',
          dispatchId: 'dispatch-a',
          sourceEventType: 'current_progress',
        },
        createdAtMs: 3_400 + index,
        updatedAtMs: 3_400 + index,
      };
    }
    projection.turnsById['turn-a'] = {
      ...projection.turnsById['turn-a']!,
      activityIds: [
        ...projection.turnsById['turn-a']!.activityIds,
        'progress-distinct-a',
        'progress-distinct-b',
      ],
      updatedAtMs: 3_401,
    };

    const view = render(roomTurn(projection));

    expect([...view.container.querySelectorAll('.room-agent-activity')].filter((row) => (
      row.textContent?.includes('已核对用户路径')
    ))).toHaveLength(2);
  });

  it('marks a changed public event once and does not replay arrival on a fresh snapshot', () => {
    vi.useFakeTimers();
    vi.setSystemTime(4_200);
    const projection = roomProjection();
    const view = render(roomTurn(projection));
    expect(view.container.querySelector('[data-arriving="true"]')).not.toBeInTheDocument();

    projection.activitiesById['progress-new'] = {
      id: 'progress-new',
      turnId: 'turn-a',
      participantId: 'participant-a',
      sourceSessionId: 'session-a',
      kind: 'participant_activity',
      status: 'running',
      summary: '调用链已经核对完成，正在整理结果',
      payload: {
        rootId: 'root-a',
        dispatchId: 'dispatch-a',
        sourceEventType: 'current_progress',
      },
      createdAtMs: 4_000,
      updatedAtMs: 4_100,
    };
    projection.turnsById['turn-a'] = {
      ...projection.turnsById['turn-a']!,
      activityIds: [...projection.turnsById['turn-a']!.activityIds, 'progress-new'],
      updatedAtMs: 4_100,
    };
    view.rerender(roomTurn(projection));

    const arrived = screen.getAllByText('调用链已经核对完成，正在整理结果')
      .map((element) => element.closest('.room-agent-activity'))
      .find((element): element is HTMLElement => element instanceof HTMLElement)!;
    expect(arrived).toHaveAttribute('data-arriving', 'true');
    act(() => vi.advanceTimersByTime(300));
    expect(arrived).not.toHaveAttribute('data-arriving');
    view.unmount();

    const fresh = render(roomTurn(projection));
    expect(fresh.container.querySelector('[data-arriving="true"]')).not.toBeInTheDocument();
  });


  it('ages fresh activity, stops motion while stale, and resumes only after a fresh synced event', () => {
    vi.useFakeTimers();
    vi.setSystemTime(10_000);
    const projection = roomProjection();
    projection.activitiesById['wait-a'] = {
      ...projection.activitiesById['wait-a']!,
      status: 'completed',
    };
    projection.activitiesById['progress-fresh'] = {
      id: 'progress-fresh',
      turnId: 'turn-a',
      participantId: 'participant-a',
      sourceSessionId: 'session-a',
      kind: 'participant_activity',
      status: 'running',
      summary: '正在核对最新实现',
      payload: {
        rootId: 'root-a',
        dispatchId: 'dispatch-a',
        sourceEventType: 'current_progress',
      },
      createdAtMs: 9_000,
      updatedAtMs: 9_000,
    };
    projection.turnsById['turn-a'] = {
      ...projection.turnsById['turn-a']!,
      activityIds: [...projection.turnsById['turn-a']!.activityIds, 'progress-fresh'],
      updatedAtMs: 9_000,
    };
    const view = render(roomTurn(projection));
    const lane = view.container.querySelector<HTMLElement>('.room-agent-lane')!;

    expect(lane).toHaveAttribute('data-motion', 'fresh');
    expect(lane).toHaveTextContent(/最近更新 .* · 1 秒前/);
    expect(lane.querySelector('.agent-persona-avatar')).toHaveAttribute('data-presence', 'thinking');

    act(() => vi.advanceTimersByTime(2_000));
    expect(lane).toHaveTextContent(/最近更新 .* · 3 秒前/);

    act(() => vi.advanceTimersByTime(14_000));
    expect(lane).toHaveAttribute('data-motion', 'stale');
    expect(lane).toHaveTextContent('正在等待下一条进展');
    expect(lane).not.toHaveTextContent('状态可能过期');
    expect(lane.querySelector('.agent-persona-avatar')).not.toHaveAttribute('data-presence', 'thinking');
    expect(lane.querySelector('.room-agent-lane__activity')).toHaveAttribute('data-state', 'running');
    expect(lane.querySelector('.room-agent-lane__activity')).toHaveAttribute('data-motion', 'paused');

    projection.activitiesById['progress-fresh'] = {
      ...projection.activitiesById['progress-fresh']!,
      summary: '重连后收到新的权威进展',
      updatedAtMs: Date.now(),
    };
    view.rerender(roomTurn(projection));
    expect(lane).toHaveAttribute('data-motion', 'fresh');
    expect(lane).toHaveTextContent(/最近更新 .* · 0 秒前/);
    expect(lane.querySelector('.agent-persona-avatar')).toHaveAttribute('data-presence', 'thinking');
  });

  it('stops motion immediately when only the Room timeline stream disconnects', () => {
    vi.useFakeTimers();
    vi.setSystemTime(10_000);
    const projection = roomProjection();
    projection.activitiesById['progress-fresh'] = {
      id: 'progress-fresh',
      turnId: 'turn-a',
      participantId: 'participant-a',
      sourceSessionId: 'session-a',
      kind: 'participant_activity',
      status: 'running',
      summary: '正在核对最新实现',
      payload: {
        rootId: 'root-a',
        dispatchId: 'dispatch-a',
        sourceEventType: 'current_progress',
      },
      createdAtMs: 9_000,
      updatedAtMs: 9_000,
    };
    projection.turnsById['turn-a'] = {
      ...projection.turnsById['turn-a']!,
      activityIds: [...projection.turnsById['turn-a']!.activityIds, 'progress-fresh'],
      updatedAtMs: 9_000,
    };
    const view = render(roomTurn(projection, 'synced'));
    const lane = view.container.querySelector<HTMLElement>('.room-agent-lane')!;

    expect(lane).toHaveAttribute('data-motion', 'fresh');
    expect(lane.querySelector('.agent-persona-avatar')).toHaveAttribute('data-presence', 'thinking');

    view.rerender(roomTurn(projection, 'failed'));
    expect(lane).toHaveAttribute('data-motion', 'disconnected');
    expect(lane).toHaveTextContent('Room 对话实时更新暂时中断');
    expect(lane.querySelector('.agent-persona-avatar')).not.toHaveAttribute('data-presence', 'thinking');
    expect(lane.querySelector('.room-agent-lane__activity')).toHaveAttribute('data-motion', 'paused');

    projection.activitiesById['progress-fresh'] = {
      ...projection.activitiesById['progress-fresh']!,
      summary: '重连后收到新的权威进展',
      updatedAtMs: Date.now(),
    };
    view.rerender(roomTurn(projection, 'synced'));
    expect(lane).toHaveAttribute('data-motion', 'fresh');
    expect(lane.querySelector('.agent-persona-avatar')).toHaveAttribute('data-presence', 'thinking');
  });


});

function roomTurn(
  projection: ReturnType<typeof roomProjection>,
  roomSyncState?: 'recovering' | 'failed' | 'synced',
) {
  return <RoomTurn
    roomSyncState={roomSyncState}
    personas={[]}
    projection={projection}
    room={{
      participants: [{
        id: 'participant-a',
        sessionId: 'session-a',
        roleId: 'companion-present-v1',
        roleVersion: '1',
        displayName: '澄·今',
      }],
    }}
    turnId="turn-a"
  />;
}

function roomProjection() {
  const projection = createRoomProjection('room-a');
  projection.turnOrder.push('turn-a');
  projection.turnsById['turn-a'] = {
    id: 'turn-a',
    rootId: 'root-a',
    status: 'running',
    messageIds: [],
    activityIds: ['route-a', 'wait-a', 'tool-a'],
    participantIds: ['participant-a'],
    dispatchIds: ['dispatch-a'],
    dispatchParticipantIds: { 'dispatch-a': 'participant-a' },
    createdAtMs: 1_000,
    updatedAtMs: 3_100,
  };
  projection.activitiesById['route-a'] = {
    id: 'route-a',
    turnId: 'turn-a',
    participantId: 'participant-a',
    sourceSessionId: 'session-a',
    kind: 'route_decision',
    status: 'completed',
    summary: '澄·今已接手',
    payload: { rootId: 'root-a', dispatchId: 'dispatch-a' },
    createdAtMs: 1_000,
  };
  projection.activitiesById['wait-a'] = {
    id: 'wait-a',
    turnId: 'turn-a',
    participantId: 'participant-a',
    sourceSessionId: 'session-a',
    kind: 'participant_activity',
    status: 'waiting',
    summary: '等待上游服务恢复',
    payload: {
      rootId: 'root-a',
      dispatchId: 'dispatch-a',
      sourceEventType: 'retry_wait',
      reason: '上游服务正在恢复',
      retryDelayMs: 2_000,
    },
    createdAtMs: 2_000,
    updatedAtMs: 2_100,
  };
  projection.activitiesById['tool-a'] = {
    id: 'tool-a',
    turnId: 'turn-a',
    participantId: 'participant-a',
    sourceSessionId: 'session-a',
    kind: 'participant_activity',
    status: 'completed',
    summary: '核对调用位置',
    payload: {
      rootId: 'root-a',
      dispatchId: 'dispatch-a',
      sourceEventType: 'tool_finished',
      toolName: 'read',
      toolCallId: 'call-a',
      arguments: { path: '…/src/runtime.ts' },
      result: { outputPreview: '已核对三个调用位置', outputTruncated: false },
    },
    createdAtMs: 3_000,
    updatedAtMs: 3_100,
  };
  return projection;
}
