import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createRoomProjection } from '@/contracts/room-reducer';
import type { RoomSummary } from '@/features/rooms/room-types';
import { PawRoomConversation } from './PawRoomWorkspace';

const originalScrollHeightDescriptor = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'scrollHeight');

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.useRealTimers();
  if (originalScrollHeightDescriptor) {
    Object.defineProperty(HTMLElement.prototype, 'scrollHeight', originalScrollHeightDescriptor);
  } else {
    Reflect.deleteProperty(HTMLElement.prototype, 'scrollHeight');
  }
});

function mockMeasuredDisclosureMotion() {
  vi.useFakeTimers();
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => (
    window.setTimeout(() => callback(performance.now()), 16)
  ));
  vi.stubGlobal('cancelAnimationFrame', (handle: number) => window.clearTimeout(handle));
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function measuredRect(this: HTMLElement) {
    const height = this.classList.contains('agent-smooth-reveal')
      ? Number.parseFloat(this.style.height) || (this.dataset.state === 'open' ? 240 : 0)
      : 240;
    return { bottom: height, height, left: 0, right: 320, top: 0, width: 320, x: 0, y: 0, toJSON: () => ({}) };
  });
  Object.defineProperty(HTMLElement.prototype, 'scrollHeight', { configurable: true, get: () => 240 });
}

describe('PawRoomConversation', () => {
  it('owns the public chronology without rendering legacy RoomTurn cards', () => {
    const { projection, room } = roomConversation();

    const { container } = render(<PawRoomConversation
      onApprovalDecision={async () => undefined}
      onRetryTurn={() => undefined}
      projection={projection}
      retryingTurn={false}
      room={room}
    />);

    expect(screen.getByRole('region', { name: 'Room 公开对话' })).toHaveTextContent('请完成主线迁移');
    expect(screen.getByRole('region', { name: 'Room 公开对话' })).toHaveTextContent('实现伙伴');
    expect(container.querySelector('.paw-room-chronology__activity[data-kind="tool_started"]'))
      .toHaveTextContent('read 正在执行');
    expect(container.querySelector('.room-turn, .room-agent-lane')).toBeNull();
    expect(container.querySelectorAll('.paw-room-chronology__message')).toHaveLength(2);
    expect(container.querySelectorAll('.paw-room-chronology__activity')).toHaveLength(2);
  });

  it('keeps raw activity detail collapsed and preserves the real approval action', async () => {
    const user = userEvent.setup();
    const { projection, room } = roomConversation();
    const decide = vi.fn().mockResolvedValue(undefined);

    render(<PawRoomConversation
      onApprovalDecision={decide}
      onRetryTurn={() => undefined}
      projection={projection}
      retryingTurn={false}
      room={room}
    />);

    const disclosure = screen.getByText('详情').closest('details') as HTMLDetailsElement;
    expect(disclosure).not.toHaveAttribute('open');
    expect(screen.queryByText(/Volumes\/private\/workspace/)).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '批准并继续' }));
    await waitFor(() => expect(decide).toHaveBeenCalledWith('approval-a', 'approved', 'a'.repeat(64)));
  });

  it('smoothly closes and reopens a running activity fold without losing its exit content', async () => {
    mockMeasuredDisclosureMotion();
    const { projection, room } = roomConversation();

    render(<PawRoomConversation
      onApprovalDecision={async () => undefined}
      onRetryTurn={() => undefined}
      projection={projection}
      retryingTurn={false}
      room={room}
    />);

    const fold = screen.getByText('过程 1 步').closest('details') as HTMLDetailsElement;
    const summary = fold.querySelector('summary')!;
    expect(fold).toHaveAttribute('open');
    expect(summary).toHaveAttribute('aria-expanded', 'true');

    fireEvent.click(summary);
    await act(async () => { vi.advanceTimersByTime(17); });
    expect(summary).toHaveAttribute('aria-expanded', 'false');
    // The native shell remains open while the measured disclosure plays out.
    expect(fold).toHaveAttribute('open');
    expect(fold).toHaveTextContent('read 正在执行');
    const reveal = fold.querySelector('.paw-room-chronology__reveal')!;
    expect(reveal).toHaveAttribute('data-state', 'closing');
    fireEvent.transitionEnd(reveal, { propertyName: 'height' });
    expect(fold).not.toHaveAttribute('open');

    fireEvent.click(summary);
    await act(async () => { vi.advanceTimersByTime(17); });
    expect(summary).toHaveAttribute('aria-expanded', 'true');
    expect(fold).toHaveAttribute('open');
  });

  it('keeps a manually closed activity fold closed after its running activity completes', async () => {
    const user = userEvent.setup();
    const { projection, room } = roomConversation();
    const view = render(<PawRoomConversation
      onApprovalDecision={async () => undefined}
      onRetryTurn={() => undefined}
      projection={projection}
      retryingTurn={false}
      room={room}
    />);

    const fold = screen.getByText('过程 1 步').closest('details') as HTMLDetailsElement;
    const summary = fold.querySelector('summary')!;
    await user.click(summary);
    await waitFor(() => expect(fold).not.toHaveAttribute('open'));

    const completedProjection = {
      ...projection,
      activitiesById: {
        ...projection.activitiesById,
        'tool-a': { ...projection.activitiesById['tool-a']!, status: 'completed' as const },
      },
    };
    view.rerender(<PawRoomConversation
      onApprovalDecision={async () => undefined}
      onRetryTurn={() => undefined}
      projection={completedProjection}
      retryingTurn={false}
      room={room}
    />);

    expect(fold).not.toHaveAttribute('open');
    expect(summary).toHaveAttribute('aria-expanded', 'false');
  });

  it('uses the same reversible reveal for an activity raw-detail leaf', async () => {
    mockMeasuredDisclosureMotion();
    const { projection, room } = roomConversation();

    render(<PawRoomConversation
      onApprovalDecision={async () => undefined}
      onRetryTurn={() => undefined}
      projection={projection}
      retryingTurn={false}
      room={room}
    />);

    const detail = screen.getByText('详情').closest('details') as HTMLDetailsElement;
    const summary = detail.querySelector('summary')!;
    expect(detail).not.toHaveAttribute('open');
    fireEvent.click(summary);
    await act(async () => { vi.advanceTimersByTime(17); });
    expect(summary).toHaveAttribute('aria-expanded', 'true');
    expect(detail).toHaveAttribute('open');
    const reveal = detail.querySelector('.paw-room-chronology__detail-reveal')!;
    fireEvent.transitionEnd(reveal, { propertyName: 'height' });
    fireEvent.click(summary);
    await act(async () => { vi.advanceTimersByTime(17); });
    expect(summary).toHaveAttribute('aria-expanded', 'false');
    expect(detail).toHaveAttribute('open');
    expect(reveal).toHaveAttribute('data-state', 'closing');
    fireEvent.transitionEnd(reveal, { propertyName: 'height' });
    expect(detail).not.toHaveAttribute('open');
  });

  it('opens a Room background Bash only from an explicit activity action', async () => {
    const user = userEvent.setup();
    const { projection, room } = roomConversation();
    const openProcess = vi.fn();
    projection.activityOrder.push('background-a');
    projection.activitiesById['background-a'] = {
      id: 'background-a', turnId: 'root-a', participantId: 'participant-a', sourceSessionId: 'session-a',
      kind: 'participant_activity', status: 'completed', summary: '后台构建已启动',
      payload: {
        sourceEventType: 'tool_finished',
        toolCallId: 'call-background-a',
        toolName: 'workspace_job',
        arguments: { command: 'pnpm build', cwd: '/workspace' },
        runId: 'bg_0123456789abcdef0123456789abcdef',
      },
      sequence: 5, createdAtMs: 140, updatedAtMs: 140,
    };

    render(<PawRoomConversation
      onApprovalDecision={async () => undefined}
      onOpenProcessActivity={openProcess}
      onRetryTurn={() => undefined}
      projection={projection}
      retryingTurn={false}
      room={room}
    />);

    expect(openProcess).not.toHaveBeenCalled();
    const backgroundFold = screen.getByText('后台构建已启动').closest('details') as HTMLDetailsElement;
    await user.click(backgroundFold.querySelector('summary')!);
    const action = screen.getByRole('button', { name: '查看后台 Bash', hidden: true });
    await user.click(action);
    expect(openProcess).toHaveBeenCalledTimes(1);
    expect(openProcess).toHaveBeenCalledWith(projection.activitiesById['background-a']);
  });

  it('offers retry only for the current failed request', async () => {
    const user = userEvent.setup();
    const { projection, room } = roomConversation();
    const retry = vi.fn();
    projection.turnOrder.push('root-a');
    projection.turnsById['root-a'] = {
      id: 'root-a', rootId: 'root-a', status: 'failed',
      messageIds: ['message-user'], activityIds: [], participantIds: [], createdAtMs: 100, updatedAtMs: 145,
      failure: '503 upstream request failed',
    };

    render(<PawRoomConversation
      onApprovalDecision={async () => undefined}
      onRetryTurn={retry}
      projection={projection}
      retryingTurn={false}
      room={room}
    />);

    await user.click(screen.getByRole('button', { name: '再试一次' }));
    expect(retry).toHaveBeenCalledWith('请完成主线迁移', 'root-a');
  });

  it('keeps an old failure as history without reviving retry after newer user input', () => {
    const { projection, room } = roomConversation();
    projection.turnOrder.push('root-a', 'root-b');
    projection.turnsById['root-a'] = {
      id: 'root-a', rootId: 'root-a', status: 'failed',
      messageIds: ['message-user'], activityIds: [], participantIds: [], createdAtMs: 100, updatedAtMs: 145,
      failure: '503 upstream request failed',
    };
    projection.turnsById['root-b'] = {
      id: 'root-b', rootId: 'root-b', status: 'running',
      messageIds: ['message-user-new'], activityIds: [], participantIds: [], createdAtMs: 160, updatedAtMs: 160,
    };
    projection.messageOrder.push('message-user-new');
    projection.messagesById['message-user-new'] = {
      id: 'message-user-new', roomId: room.id, turnId: 'root-b', participantId: null,
      sourceSessionId: '', role: 'user', status: 'completed', text: '改用新的方案继续',
      projectionKind: 'post', sequence: 5, createdAtMs: 160,
    };

    const { rerender } = render(<PawRoomConversation
      onApprovalDecision={async () => undefined}
      onRetryTurn={() => undefined}
      projection={projection}
      retryingTurn={false}
      room={room}
    />);

    expect(screen.getByText('这轮协作未完成')).toBeVisible();
    expect(screen.queryByRole('button', { name: '再试一次' })).not.toBeInTheDocument();

    projection.turnsById['root-a'] = { ...projection.turnsById['root-a']!, updatedAtMs: 200 };
    rerender(<PawRoomConversation
      onApprovalDecision={async () => undefined}
      onRetryTurn={() => undefined}
      projection={{ ...projection, turnsById: { ...projection.turnsById } }}
      retryingTurn={false}
      room={room}
    />);
    expect(screen.queryByRole('button', { name: '再试一次' })).not.toBeInTheDocument();
  });
});

function roomConversation() {
  const room: RoomSummary = {
    id: 'room-live', title: 'PAWOS 完整迁移', status: 'active',
    description: '将候选结构接到真实 Room reducer。', routingPolicy: 'natural',
    moderatorParticipantId: 'participant-root', updatedAtMs: 140,
    participants: [{
      id: 'participant-a', sessionId: 'session-a', roleId: 'implementer', roleVersion: '1',
      displayName: '实现伙伴', collaborationRole: 'implementer', status: 'active', ordinal: 1,
    }],
    workItems: [],
  };
  const projection = createRoomProjection(room.id);
  projection.messageOrder.push('message-user', 'message-agent');
  projection.messagesById['message-user'] = {
    id: 'message-user', roomId: room.id, turnId: 'root-a', participantId: null,
    sourceSessionId: '', role: 'user', status: 'completed', text: '请完成主线迁移',
    projectionKind: 'post', sequence: 1, createdAtMs: 100,
  };
  projection.messagesById['message-agent'] = {
    id: 'message-agent', roomId: room.id, turnId: 'root-a', participantId: 'participant-a',
    sourceSessionId: 'session-a', role: 'assistant', status: 'completed', text: '已接入生产 reducer。',
    projectionKind: 'post', sequence: 4, createdAtMs: 130,
  };
  projection.activityOrder.push('tool-a', 'approval-a');
  projection.activitiesById['tool-a'] = {
    id: 'tool-a', turnId: 'root-a', participantId: 'participant-a', sourceSessionId: 'session-a',
    kind: 'tool', status: 'running',
    summary: '```json\n{"path":"/Volumes/private/workspace/PawWindowLayer.tsx"}\n```',
    payload: { sourceEventType: 'tool_started', toolName: 'read' },
    sequence: 2, createdAtMs: 110, updatedAtMs: 110,
  };
  projection.activitiesById['approval-a'] = {
    id: 'approval-a', turnId: 'root-a', participantId: 'participant-a', sourceSessionId: 'session-a',
    kind: 'approval_required', status: 'waiting', summary: '批准受控迁移操作',
    payload: { sourceEventType: 'approval_required', approvalId: 'approval-a', payloadSha256: 'a'.repeat(64) },
    sequence: 3, createdAtMs: 120, updatedAtMs: 120,
  };
  return { projection, room };
}
