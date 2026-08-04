import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { RoomDispatchEnvelopeV2 } from '@/contracts/generated/room-dispatch-envelope.v2';
import type { RoomTaskV3 } from '@/contracts/generated/room-task.v3';
import { createRoomProjection } from '@/contracts/room-reducer';
import type { RoomTaskSubagentRun } from '../kernel/RoomTaskFlowGraph';
import type { RoomKernelSyncProjection } from '../state/live-store';
import { RoomTurn } from './RoomTurn';

describe('RoomTurn public activity detail', () => {
  afterEach(() => {
    vi.useRealTimers();
    cleanup();
  });

  it('shows one continuous activity stream with expandable tool output and nested helpers', () => {
    const projection = roomProjection();
    const view = render(roomTurn(projection));
    const activityFeed = view.container.querySelector('.room-agent-lane__activity-feed');
    const activityRows = view.container.querySelectorAll(
      '.room-agent-activity, .room-reasoning-summary',
    );

    expect(activityFeed).toHaveAttribute('data-layout', 'continuous');
    expect([...activityRows].every((row) => row.parentElement === activityFeed)).toBe(true);
    expect(activityRows).toHaveLength(3);
    expect([...activityRows].every((row) => row.querySelector('time[datetime]'))).toBe(true);
    expect(view.container).toHaveTextContent('等待原因：上游服务正在恢复');
    expect(view.container).toHaveTextContent('恢复条件：2s 后自动重试');
    const tool = view.container.querySelector<HTMLDetailsElement>('.room-agent-activity--tool')!;
    fireEvent.click(tool.querySelector('summary')!);
    expect(tool).toHaveAttribute('open');
    expect(tool).toHaveTextContent('已核对三个调用位置');

    const helper = screen.getByRole('region', { name: '负责人调用了 1 个临时协作者' });
    expect(helper).toHaveTextContent('研究助手 1');
    expect(helper).toHaveTextContent('核对边界与失败恢复');
    expect(helper.querySelector('time')).toHaveAttribute(
      'datetime',
      new Date(2_500).toISOString(),
    );
    expect(view.container.textContent).not.toMatch(
      /Kernel|Root|Dispatch|Receipt|schemaVersion|root-a|dispatch-a|task-a/,
    );
    expect(activityFeed).not.toHaveAttribute('role', 'log');
    expect(activityFeed).not.toHaveAttribute('aria-live');
    expect(activityFeed).not.toHaveAttribute('tabindex');
    expect(screen.queryByRole('button', { name: '回到最新' })).not.toBeInTheDocument();
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

  it('summarizes each role file changes without merging same-basename paths', () => {
    const projection = roomProjection();
    projection.activitiesById['edit-a'] = {
      id: 'edit-a',
      turnId: 'turn-a',
      participantId: 'participant-a',
      sourceSessionId: 'session-a',
      kind: 'participant_activity',
      status: 'completed',
      summary: '更新 RoomTurn.tsx',
      payload: {
        rootId: 'root-a',
        dispatchId: 'dispatch-a',
        sourceEventType: 'tool_finished',
        toolName: 'apply_patch',
        toolCallId: 'edit-a',
        arguments: { path: '/private/worktree/src/RoomTurn.tsx' },
        result: { additions: 18, deletions: 7 },
      },
      createdAtMs: 3_200,
      updatedAtMs: 3_300,
    };
    projection.activitiesById['edit-b'] = {
      ...projection.activitiesById['edit-a']!,
      id: 'edit-b',
      summary: '更新 RoomTurn 测试',
      payload: {
        ...projection.activitiesById['edit-a']!.payload,
        toolCallId: 'edit-b',
        arguments: { path: '/private/worktree/tests/RoomTurn.tsx' },
        result: { additions: 4, deletions: 2 },
      },
      createdAtMs: 3_250,
      updatedAtMs: 3_350,
    };
    projection.activitiesById['edit-c'] = {
      ...projection.activitiesById['edit-a']!,
      id: 'edit-c',
      summary: '更新应用入口',
      payload: {
        ...projection.activitiesById['edit-a']!.payload,
        toolCallId: 'edit-c',
        arguments: { path: '/Users/alice/project/src/index.ts' },
        result: { additions: 3, deletions: 1 },
      },
      createdAtMs: 3_275,
      updatedAtMs: 3_375,
    };
    projection.activitiesById['edit-d'] = {
      ...projection.activitiesById['edit-a']!,
      id: 'edit-d',
      summary: '更新另一个工作区入口',
      payload: {
        ...projection.activitiesById['edit-a']!.payload,
        toolCallId: 'edit-d',
        arguments: { path: '/Volumes/secret/project/src/index.ts' },
        result: { additions: 6, deletions: 2 },
      },
      createdAtMs: 3_300,
      updatedAtMs: 3_400,
    };
    projection.turnsById['turn-a'] = {
      ...projection.turnsById['turn-a']!,
      activityIds: [
        ...projection.turnsById['turn-a']!.activityIds,
        'edit-a',
        'edit-b',
        'edit-c',
        'edit-d',
      ],
      updatedAtMs: 3_400,
    };

    render(roomTurn(projection));

    const files = screen.getByRole('list', { name: '澄·今改动的文件' });
    expect(files).toHaveTextContent('src/RoomTurn.tsx');
    expect(files).toHaveTextContent('tests/RoomTurn.tsx');
    expect(files).toHaveTextContent('+18');
    expect(files).toHaveTextContent('−7');
    expect(files).toHaveTextContent('+4');
    expect(files).toHaveTextContent('−2');
    const fileLabels = [...files.querySelectorAll('code')].map((item) => item.textContent ?? '');
    expect(fileLabels.filter((label) => label.startsWith('src/index.ts · '))).toHaveLength(2);
    expect(new Set(fileLabels).size).toBe(4);
    expect(files.querySelectorAll('li')).toHaveLength(4);
    expect(files).not.toHaveTextContent('/private/worktree');
    expect(files).not.toHaveTextContent('alice');
    expect(files).not.toHaveTextContent('secret');
    expect(files).not.toHaveTextContent('Users');
    expect(files).not.toHaveTextContent('Volumes');
  });

  it('keeps the final activity in the shared outer stream when the same snapshot settles the lane', () => {
    vi.useFakeTimers();
    vi.setSystemTime(5_000);
    const projection = roomProjection();
    const view = render(roomTurn(projection, {}, undefined, kernelSync('synced', 4_500)));
    const activityFeed = view.container.querySelector<HTMLElement>(
      '.room-agent-lane__activity-feed',
    )!;
    projection.activitiesById['final-result'] = {
      id: 'final-result',
      turnId: 'turn-a',
      participantId: 'participant-a',
      sourceSessionId: 'session-a',
      kind: 'participant_activity',
      status: 'completed',
      summary: '最终验证已经完成',
      payload: {
        rootId: 'root-a',
        dispatchId: 'dispatch-a',
        sourceEventType: 'current_progress',
      },
      createdAtMs: 4_000,
      updatedAtMs: 4_000,
    };
    projection.turnsById['turn-a'] = {
      ...projection.turnsById['turn-a']!,
      status: 'completed',
      activityIds: [...projection.turnsById['turn-a']!.activityIds, 'final-result'],
      terminalDispatchIds: ['dispatch-a'],
      terminalParticipantIds: ['participant-a'],
      updatedAtMs: 4_000,
    };
    view.rerender(roomTurn(projection, {}, undefined, kernelSync('synced', 4_500)));

    expect(activityFeed.closest('details')).toBeNull();
    expect(activityFeed).toHaveTextContent('最终验证已经完成');
    expect(activityFeed).not.toHaveAttribute('aria-live');
    expect(
      screen.getByText('最终验证已经完成').closest('.room-agent-activity'),
    ).toHaveAttribute('data-arriving', 'true');
  });

  it.each([
    ['materialized', '工作区已准备', 'running', false],
    ['work_started', '负责人正在独立工作', 'running', false],
    ['delivered', '结果已经交回', 'completed', false],
    ['integration_started', '正在纳入共同工作', 'running', false],
    ['integrated', '结果已纳入共同工作', 'completed', false],
    ['conflict', '整合发生冲突，需要处理', 'failed', true],
    ['retained', '工作区已保留', 'waiting', false],
    ['retry_bound', '工作区已留给下一次尝试', 'waiting', false],
    ['abandoned', '工作区已确认放弃', 'completed', false],
    ['cleaned', '工作区已安全清理', 'completed', false],
    ['cancelled', '工作区任务已停止', 'failed', true],
    ['cleanup_failed', '工作区清理失败', 'failed', true],
  ] as const)(
    'shows canonical workspace lifecycle %s in the corresponding role activity',
    (workspaceLifecycleState, title, displayState, attention) => {
      const projection = roomProjection();
      const view = render(roomTurn(projection, {
        revision: 8,
        workspacePolicy: 'isolated_writable',
        workspaceRoot: '/private/worker-path',
        workspaceLifecycleState,
        workspaceCleanupState: workspaceLifecycleState === 'cleaned'
          || workspaceLifecycleState === 'abandoned'
          ? 'cleaned'
          : workspaceLifecycleState === 'retained'
            || workspaceLifecycleState === 'conflict'
            || workspaceLifecycleState === 'cancelled'
            ? 'retained'
            : workspaceLifecycleState === 'cleanup_failed'
              ? 'failed'
              : 'not_authorized',
        workspaceAttentionRequired: false,
      }));

      const lane = view.container.querySelector('.room-agent-lane')!;
      const activityDisclosure = lane.querySelector<HTMLElement>(
        '.room-agent-lane__activity',
      )!;
      const workspaceActivity = activityDisclosure.querySelector(
        '.room-agent-activity--workspace',
      )!;
      expect(workspaceActivity).toHaveAttribute(
        'data-workspace-lifecycle',
        workspaceLifecycleState,
      );
      expect(workspaceActivity).toHaveAttribute('data-state', displayState);
      expect(workspaceActivity).toHaveTextContent(title);
      expect(workspaceActivity).toHaveTextContent('任务记录');
      expect(workspaceActivity).toHaveTextContent('更新时间未上报');
      expect(workspaceActivity).not.toHaveTextContent('/private/worker-path');
      expect(activityDisclosure).toHaveAttribute(
        'data-state',
        attention ? 'attention' : 'running',
      );
      expect(workspaceActivity).toHaveTextContent(attention ? '需要处理' : title);
    },
  );

  it('honors explicit canonical attention even when the lifecycle is normally active', () => {
    const projection = roomProjection();
    const view = render(roomTurn(projection, {
      revision: 9,
      workspacePolicy: 'isolated_writable',
      workspaceLifecycleState: 'materialized',
      workspaceCleanupState: 'not_authorized',
      workspaceAttentionRequired: true,
    }));
    const workspaceActivity = view.container.querySelector(
      '.room-agent-activity--workspace',
    )!;
    expect(workspaceActivity).toHaveAttribute('data-state', 'failed');
    expect(workspaceActivity).toHaveTextContent('工作区已准备');
    expect(workspaceActivity).toHaveTextContent('当前记录要求负责人处理');
    expect(workspaceActivity).toHaveTextContent('需要处理');
  });

  it('keeps the authoritative update time fixed while the client elapsed seconds advance', () => {
    vi.useFakeTimers();
    vi.setSystemTime(10_000);
    const projection = roomProjection();
    const view = render(roomTurn(projection, {
      revision: 10,
      workspacePolicy: 'isolated_writable',
      workspaceLifecycleState: 'work_started',
      workspaceCleanupState: 'not_authorized',
      workspaceAttentionRequired: false,
    }, 7_000));
    const workspaceActivity = view.container.querySelector(
      '.room-agent-activity--workspace',
    )!;
    const timestamp = workspaceActivity.querySelector('time')!;
    const absolute = timestamp.textContent;
    expect(timestamp).toHaveAttribute('datetime', new Date(7_000).toISOString());
    expect(workspaceActivity).toHaveTextContent(/最近更新 .* · 3 秒前/);

    act(() => vi.advanceTimersByTime(2_000));

    expect(timestamp).toHaveTextContent(absolute ?? '');
    expect(workspaceActivity).toHaveTextContent(/最近更新 .* · 5 秒前/);
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
    const synced = kernelSync('synced', 9_500);
    const view = render(roomTurn(projection, {}, undefined, synced));
    const lane = view.container.querySelector<HTMLElement>('.room-agent-lane')!;

    expect(lane).toHaveAttribute('data-motion', 'fresh');
    expect(lane).toHaveTextContent(/最近更新 .* · 1 秒前/);
    expect(lane.querySelector('.agent-persona-avatar')).toHaveAttribute('data-presence', 'thinking');

    act(() => vi.advanceTimersByTime(2_000));
    expect(lane).toHaveTextContent(/最近更新 .* · 3 秒前/);

    act(() => vi.advanceTimersByTime(58_000));
    expect(lane).toHaveAttribute('data-motion', 'stale');
    expect(lane).toHaveTextContent('最近一分钟没有新的公开进展，实时连接仍正常');
    expect(lane.querySelector('.agent-persona-avatar')).not.toHaveAttribute('data-presence', 'thinking');
    expect(lane.querySelector('.room-agent-lane__activity')).toHaveAttribute('data-state', 'running');
    expect(lane.querySelector('.room-agent-lane__activity')).toHaveAttribute('data-motion', 'paused');

    view.rerender(roomTurn(projection, {}, undefined, kernelSync('stale', 9_500)));
    expect(lane).toHaveAttribute('data-motion', 'disconnected');
    expect(lane).toHaveTextContent('实时更新暂时中断');
    expect(lane.querySelector('.agent-persona-avatar')).not.toHaveAttribute('data-presence', 'thinking');

    projection.activitiesById['progress-fresh'] = {
      ...projection.activitiesById['progress-fresh']!,
      summary: '重连后收到新的权威进展',
      updatedAtMs: Date.now(),
    };
    view.rerender(roomTurn(
      projection,
      {},
      undefined,
      kernelSync('synced', Date.now()),
    ));
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
    const syncedKernel = kernelSync('synced', 9_500);
    const view = render(roomTurn(projection, {}, undefined, syncedKernel, 'synced'));
    const lane = view.container.querySelector<HTMLElement>('.room-agent-lane')!;

    expect(lane).toHaveAttribute('data-motion', 'fresh');
    expect(lane.querySelector('.agent-persona-avatar')).toHaveAttribute('data-presence', 'thinking');

    view.rerender(roomTurn(projection, {}, undefined, syncedKernel, 'failed'));
    expect(lane).toHaveAttribute('data-motion', 'disconnected');
    expect(lane).toHaveTextContent('Room 对话实时更新暂时中断');
    expect(lane.querySelector('.agent-persona-avatar')).not.toHaveAttribute('data-presence', 'thinking');
    expect(lane.querySelector('.room-agent-lane__activity')).toHaveAttribute('data-motion', 'paused');

    projection.activitiesById['progress-fresh'] = {
      ...projection.activitiesById['progress-fresh']!,
      summary: '重连后收到新的权威进展',
      updatedAtMs: Date.now(),
    };
    view.rerender(roomTurn(projection, {}, undefined, syncedKernel, 'synced'));
    expect(lane).toHaveAttribute('data-motion', 'fresh');
    expect(lane.querySelector('.agent-persona-avatar')).toHaveAttribute('data-presence', 'thinking');
  });
});

function roomTurn(
  projection: ReturnType<typeof roomProjection>,
  taskOverrides: Partial<RoomTaskV3> = {},
  taskUpdatedAtMs?: number,
  kernelSync?: RoomKernelSyncProjection,
  roomSyncState?: 'recovering' | 'failed' | 'synced',
) {
  return <RoomTurn
    kernelDispatchesById={{
      'dispatch-a': { taskId: 'task-a' } as RoomDispatchEnvelopeV2,
    }}
    kernelTasksById={{
      'task-a': {
        taskId: 'task-a',
        objective: '核对公开活动边界',
        revision: 1,
        ...taskOverrides,
      } as RoomTaskV3,
    }}
    kernelTaskUpdatedAtMsById={taskUpdatedAtMs === undefined
      ? {}
      : { 'task-a': taskUpdatedAtMs }}
    kernelSync={kernelSync}
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
    subagentsByTaskId={{ 'task-a': [subagent()] }}
    turnId="turn-a"
  />;
}

function kernelSync(
  state: RoomKernelSyncProjection['state'],
  updatedAtMs: number,
): RoomKernelSyncProjection {
  return {
    state,
    detail: state === 'synced' ? '实时更新已连接' : '实时更新暂时中断',
    updatedAtMs,
    ...(state === 'synced' ? {} : { failureAtMs: updatedAtMs }),
  };
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

function subagent(): RoomTaskSubagentRun {
  return {
    templateId: 'researcher',
    ordinal: 0,
    task: '核对边界与失败恢复',
    state: 'completed',
    budget: {
      maxTurns: 4,
      maxToolCalls: 6,
      maxTotalTokens: 8_000,
      maxDurationMs: 120_000,
      maxOutputChars: 6_000,
    },
    usage: { turnCount: 2, toolCount: 2, totalTokens: 1_200 },
    resultSummary: '边界与恢复条件均已核对',
    error: '',
    createdAtMs: 1_200,
    startedAtMs: 1_300,
    updatedAtMs: 2_500,
    completedAtMs: 2_500,
  };
}
