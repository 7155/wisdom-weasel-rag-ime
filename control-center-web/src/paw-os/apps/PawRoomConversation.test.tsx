import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { appendOptimisticRoomMessage, createRoomProjection } from '@/contracts/room-reducer';
import { clearConversationScrollMemory } from '@/features/conversation-ui';
import type { RoomSummary } from '@/features/rooms/room-types';
import { PawRoomConversation } from './PawRoomWorkspace';

afterEach(() => {
  cleanup();
  clearConversationScrollMemory();
  vi.restoreAllMocks();
});

describe('PawRoomConversation', () => {
  it('reads the public chronology on the shared conversation surface', () => {
    const { container } = renderRoom();

    const surface = screen.getByRole('region', { name: 'Room 公开对话' });
    expect(surface).toHaveTextContent('请完成主线迁移');
    expect(surface).toHaveTextContent('已接入生产 reducer。');
    // Messages and activities share one planet identity; the real display
    // name stays reachable as the collaboration role beside it.
    expect(surface).toHaveTextContent('Mars');
    expect(surface).not.toHaveTextContent('Root');
    // One real Runtime loop is one card, and the legacy per-event DOM is gone.
    expect(container.querySelectorAll('.ccui-assistant-turn')).toHaveLength(1);
    expect(container.querySelectorAll('.ccui-user-turn')).toHaveLength(1);
    expect(container.querySelector('.room-turn, .room-agent-lane, .paw-room-chronology')).toBeNull();
  });

  it('names a tool by its reader label and keeps the raw call one click away', async () => {
    const user = userEvent.setup();
    const { container } = renderRoom();

    const tool = container.querySelector<HTMLElement>('[data-tool-block="tool:tool-a"]')!;
    // Raw Runtime tool ids map to reader-facing labels (`read` → 读取文件).
    expect(tool).toHaveTextContent('读取文件');
    expect(tool).toHaveTextContent('正在执行');
    // The raw argument blob never leaks into the collapsed reading line.
    expect(screen.queryByText(/Volumes\/private\/workspace/)).not.toBeInTheDocument();

    await user.click(within(tool).getByRole('button', { expanded: false }));
    expect(tool).toHaveTextContent('/Volumes/private/workspace/PawWindowLayer.tsx');
  });

  it('keeps a pending approval decidable without expanding anything', async () => {
    const user = userEvent.setup();
    const decide = vi.fn().mockResolvedValue(undefined);
    renderRoom({ onApprovalDecision: decide });

    await user.click(screen.getByRole('button', { name: '批准并继续' }));
    await waitFor(() => expect(decide).toHaveBeenCalledWith('approval-a', 'approved', 'a'.repeat(64)));
  });

  it('surfaces an approval failure next to the decision it belongs to', async () => {
    const user = userEvent.setup();
    const decide = vi.fn().mockRejectedValue(new Error('approval store unreachable'));
    renderRoom({ onApprovalDecision: decide });

    await user.click(screen.getByRole('button', { name: '拒绝' }));
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
    expect(screen.getByRole('button', { name: '拒绝' })).toBeEnabled();
  });

  it('expands an edit receipt into the shared structured diff reader, not a flat text wall', async () => {
    const user = userEvent.setup();
    const { projection, room } = roomConversation();
    const diff = [
      '--- a/src/example.ts',
      '+++ b/src/example.ts',
      '@@ -1,3 +1,4 @@',
      ' export function greet() {',
      "-  return 'hi';",
      "+  const name = 'PAW';",
      '+  return `hi ${name}`;',
      ' }',
    ].join('\n');
    projection.activityOrder.push('edit-a');
    projection.activitiesById['edit-a'] = {
      id: 'edit-a', turnId: 'root-a', participantId: 'participant-a', sourceSessionId: 'session-a',
      kind: 'tool', status: 'completed', summary: 'edit',
      payload: {
        sourceEventType: 'tool_finished',
        toolCallId: 'call-edit-a',
        toolName: 'edit',
        arguments: { path: 'src/example.ts' },
        result: { details: { ok: true, diff } },
      },
      sequence: 6, createdAtMs: 150, updatedAtMs: 150,
    };

    const { container } = renderRoom({ projection, room });

    // The reader line derives from real evidence, never the machine tool id.
    const card = container.querySelector<HTMLElement>('[data-tool-block="tool:edit-a"]')!;
    expect(card).toHaveTextContent('编辑文件');
    await user.click(within(card).getByRole('button', { expanded: false }));

    const output = within(card).getByLabelText('工具变更差异');
    expect(output.querySelector(':scope > pre')).toBeNull();
    const preview = output.querySelector<HTMLElement>('.agent-diff-preview')!;
    expect(preview).toHaveTextContent('src/example.ts');
    expect(preview.querySelector('tr[data-kind="add"]')).toHaveTextContent("const name = 'PAW';");
    expect(preview.querySelector('tr[data-kind="remove"]')).toHaveTextContent("return 'hi';");
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

    renderRoom({ onOpenProcessActivity: openProcess, projection, room });

    expect(openProcess).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: '查看后台 Bash' }));
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

    renderRoom({ onRetryTurn: retry, projection, room });

    expect(screen.getByText('503 upstream request failed')).toBeVisible();
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

    renderRoom({ projection, room });

    expect(screen.getByText('503 upstream request failed')).toBeVisible();
    expect(screen.queryByRole('button', { name: '再试一次' })).not.toBeInTheDocument();
  });

  it('tells the writer a steer is not delivered yet, then clears the receipt', () => {
    const { projection, room } = roomConversation();
    projection.turnOrder.push('root-a');
    projection.turnsById['root-a'] = {
      id: 'root-a', rootId: 'root-a', status: 'running',
      messageIds: ['message-user', 'message-agent'], activityIds: ['tool-a', 'approval-a'],
      participantIds: ['participant-a'], createdAtMs: 100, updatedAtMs: 130,
    };

    const pending = renderRoom({
      projection: appendOptimisticRoomMessage(projection, {
        clientMessageId: 'client-steer', text: '改成先做迁移脚本', nowMs: 200,
      }),
      room,
    });
    expect(screen.getByText('尚未送达伙伴')).toBeVisible();
    // Nothing is offered that the Room cannot honour: no Runtime contract can
    // recall a published Room post, so the receipt stays read-only.
    expect(pending.container.querySelector('.ccui-steer-receipt button')).toBeNull();

    cleanup();
    clearConversationScrollMemory();
    projection.messageOrder.push('message-steer');
    projection.turnsById['root-a']!.messageIds.push('message-steer');
    projection.messagesById['message-steer'] = {
      id: 'message-steer', roomId: room.id, turnId: 'root-a', participantId: null,
      sourceSessionId: '', role: 'user', status: 'completed', text: '改成先做迁移脚本',
      projectionKind: 'post', sequence: 5, createdAtMs: 200,
    };

    renderRoom({ projection, room });
    expect(screen.getByText('已送达伙伴')).toBeVisible();
    expect(screen.queryByText('尚未送达伙伴')).not.toBeInTheDocument();
  });

  it('scopes a partner satellite to that partner and drops the Room-wide chrome', () => {
    const { projection, room } = roomConversation();
    projection.activityOrder.push('tool-b');
    projection.activitiesById['tool-b'] = {
      id: 'tool-b', turnId: 'root-a', participantId: 'participant-b', sourceSessionId: 'session-b',
      kind: 'tool', status: 'completed', summary: '写入完成',
      payload: { sourceEventType: 'tool_finished', toolName: 'write' },
      sequence: 6, createdAtMs: 150, updatedAtMs: 150,
    };

    const { container } = renderRoom({ participantId: 'participant-a', projection, room });

    expect(screen.getByRole('region', { name: '行星公开对话' })).toBeInTheDocument();
    expect(container.querySelector('[data-tool-block="tool:tool-a"]')).not.toBeNull();
    expect(container.querySelector('[data-tool-block="tool:tool-b"]')).toBeNull();
    expect(container.querySelector('.ccui-conversation-surface')).toHaveAttribute('data-density', 'compact');
  });

  it('keeps a planet observation surface read-only while retaining its public timeline', () => {
    const { projection, room } = roomConversation();

    renderRoom({ participantId: 'participant-a', projection, readOnly: true, room });

    const surface = screen.getByRole('region', { name: '行星公开对话' });
    expect(surface).toHaveTextContent('已接入生产 reducer。');
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '批准并继续' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '拒绝' })).not.toBeInTheDocument();
  });
});

function renderRoom(overrides: Partial<Parameters<typeof PawRoomConversation>[0]> = {}) {
  const fixture = roomConversation();
  return render(<PawRoomConversation
    onApprovalDecision={async () => undefined}
    onRetryTurn={() => undefined}
    projection={fixture.projection}
    retryingTurn={false}
    room={fixture.room}
    {...overrides}
  />);
}

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
