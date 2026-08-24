import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { createRoomProjection, type RoomActivityProjection } from '@/contracts/room-reducer';
import type { RoomSummary } from '@/features/rooms/room-types';
import { PawRoomFlow } from './PawRoomFlow';

describe('PawRoomFlow', () => {
  it('renders the real WorkItem tree and approval FlowPacket from the current Room projection', () => {
    const room = roomSummary();
    const projection = createRoomProjection(room.id);
    projection.activityOrder.push('approval-a');
    projection.activitiesById['approval-a'] = {
      id: 'approval-a', turnId: 'root-a', participantId: 'participant-a', sourceSessionId: 'session-a',
      kind: 'approval_required', status: 'waiting', summary: '批准发布前检查',
      payload: { sourceEventType: 'approval_required', approvalId: 'approval:a', payloadSha256: 'a'.repeat(64) },
      createdAtMs: 120, updatedAtMs: 120,
    };
    projection.messageOrder.push('message-a');
    projection.messagesById['message-a'] = {
      id: 'message-a', roomId: room.id, turnId: 'root-a', participantId: null, sourceSessionId: '',
      role: 'user', status: 'completed', text: '请实现主线迁移', projectionKind: 'post',
      mentionedParticipantIds: ['participant-a'], createdAtMs: 110,
    };

    render(<PawRoomFlow projection={projection} room={room} />);

    expect(screen.getByRole('region', { name: 'Room 工作树' })).toHaveTextContent('完成 Room Focus 生产迁移');
    expect(screen.getByRole('complementary')).toHaveTextContent('审批');
    expect(screen.getByRole('complementary')).toHaveTextContent('实现伙伴 → 主 Room');
    expect(screen.getByRole('complementary')).toHaveTextContent('主 Room → 实现伙伴');
    expect(screen.queryByText(/47\s*\/\s*47/)).not.toBeInTheDocument();
  });

  it.each([
    {
      label: '普通 dispatch（activity.kind）',
      id: 'dispatch-kind',
      kind: 'dispatch',
      payload: { targetParticipantId: 'participant-a' },
      expectedKind: 'dispatch',
      expectedTarget: '实现伙伴',
      project: true,
    },
    {
      label: '普通 route（activity.kind）',
      id: 'route-kind',
      kind: 'route',
      payload: { targetParticipantId: 'participant-a' },
      expectedKind: 'dispatch',
      expectedTarget: '实现伙伴',
      project: true,
    },
    {
      label: '普通 route（payload.sourceEventType）',
      id: 'route-source-event',
      kind: 'participant_activity',
      payload: { sourceEventType: 'route', targetParticipantId: 'participant-a' },
      expectedKind: 'dispatch',
      expectedTarget: '实现伙伴',
      project: true,
    },
    {
      label: 'route_decision（activity.kind）',
      id: 'route-decision-kind',
      kind: 'route_decision',
      payload: { targetParticipantId: 'participant-a' },
      expectedKind: 'dispatch',
      expectedTarget: '实现伙伴',
      project: true,
    },
    {
      label: 'intercom（payload.activityKind）',
      id: 'intercom-activity-kind',
      kind: 'participant_activity',
      payload: { activityKind: 'intercom', targetParticipantId: 'participant-a' },
      expectedKind: 'request',
      expectedTarget: '实现伙伴',
      project: true,
    },
    {
      label: 'intercom（payload.sourceEventType）',
      id: 'intercom-source-event',
      kind: 'participant_activity',
      payload: { sourceEventType: 'intercom', targetParticipantId: 'participant-a' },
      expectedKind: 'request',
      expectedTarget: '实现伙伴',
      project: true,
    },
    {
      label: 'ContextRef',
      id: 'context-ref',
      kind: 'participant_activity',
      payload: { contextRefs: ['context://room-live/brief'], targetParticipantId: 'participant-a' },
      expectedKind: 'context',
      expectedTarget: '实现伙伴',
      project: true,
    },
    {
      label: 'approval（payload.sourceEventType）',
      id: 'approval-source-event',
      kind: 'participant_activity',
      payload: { sourceEventType: 'approval_required', targetParticipantId: 'participant-a' },
      expectedKind: 'approval',
      expectedTarget: '主 Room',
      project: true,
    },
    {
      label: '未知 activity',
      id: 'unknown-activity',
      kind: 'participant_activity',
      payload: { sourceEventType: 'not_a_flow_event', targetParticipantId: 'participant-a' },
      expectedKind: 'dispatch',
      expectedTarget: '实现伙伴',
      project: false,
    },
    {
      label: '无目标 dispatch',
      id: 'dispatch-without-target',
      kind: 'dispatch',
      payload: {},
      participantId: null,
      expectedKind: 'dispatch',
      expectedTarget: '实现伙伴',
      project: false,
    },
  ] as const)('projects $label into the Room Flow ledger only when it is a targeted public event', ({ id, kind, payload, participantId = 'participant-a', expectedKind, expectedTarget, project }) => {
    const room = roomSummary();
    const projection = createRoomProjection(room.id);
    projection.activityOrder.push(id);
    projection.activitiesById[id] = roomActivity({ id, kind, participantId, payload });

    const { container } = render(<PawRoomFlow projection={projection} room={room} />);
    const packets = [...container.querySelectorAll<HTMLButtonElement>('button[data-kind]')].map((button) => ({
      kind: button.dataset.kind,
      summary: button.querySelector('p')?.textContent ?? '',
      text: button.textContent ?? '',
    }));
    const packet = packets.find(({ summary }) => summary === id);

    if (project) {
      expect(packet).toEqual(expect.objectContaining({ kind: expectedKind }));
      expect(packet?.text).toContain(expectedTarget);
    } else {
      expect(packet).toBeUndefined();
    }
  });

  it('keeps nested WorkItems inside the parent reveal, preserves a manual collapse, and exposes the full packet window', () => {
    const room = roomSummary();
    const baseWorkItems = room.workItems!;
    room.workItems = [
      ...baseWorkItems,
      {
        ...baseWorkItems[0], id: 'work-child', parentWorkId: 'work-a', objective: '子任务证据', state: 'active',
      },
    ];
    const projection = createRoomProjection(room.id);
    for (let index = 0; index < 19; index += 1) {
      const id = `route-${index}`;
      projection.activityOrder.push(id);
      projection.activitiesById[id] = roomActivity({ id, kind: 'route', participantId: 'participant-a', payload: { targetParticipantId: 'participant-a' } });
    }
    const { container, rerender } = render(<PawRoomFlow projection={projection} room={room} />);
    const rootTrigger = container.querySelector<HTMLButtonElement>('.paw-room-work-tree__summary');
    expect(rootTrigger).not.toBeNull();
    expect(rootTrigger!).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText('子任务证据').closest('.paw-room-work-tree__reveal')).not.toBeNull();
    expect(screen.getByText('最近 18 / 共 21 条')).toBeInTheDocument();

    fireEvent.click(rootTrigger!);
    expect(rootTrigger!).toHaveAttribute('aria-expanded', 'false');
    const doneRoom = { ...room, workItems: room.workItems.map((item) => ({ ...item, state: 'done' as const })) };
    rerender(<PawRoomFlow projection={projection} room={doneRoom} />);
    expect(rootTrigger!).toHaveAttribute('aria-expanded', 'false');
    expect(container.querySelector('.paw-room-work-tree__children')?.closest('.paw-room-work-tree__reveal')).not.toBeNull();

    fireEvent.click(screen.getByRole('button', { name: '显示全部' }));
    expect(screen.getByText('最近 21 / 共 21 条')).toBeInTheDocument();
  });
});

function roomActivity({
  id,
  kind,
  participantId,
  payload,
}: {
  id: string;
  kind: string;
  participantId: string | null;
  payload: Record<string, unknown>;
}): RoomActivityProjection {
  return {
    id,
    turnId: 'root-a',
    participantId,
    sourceSessionId: 'session-a',
    kind,
    status: 'completed',
    summary: id,
    payload,
    createdAtMs: 200,
    updatedAtMs: 200,
  };
}

function roomSummary(): RoomSummary {
  return {
    id: 'room-live', title: 'PAWOS 完整迁移', status: 'active',
    description: '将网页模型结构接入真实 Room reducer。', routingPolicy: 'natural',
    moderatorParticipantId: 'participant-root', updatedAtMs: 130,
    participants: [{
      id: 'participant-a', sessionId: 'session-a', roleId: 'implementer', roleVersion: '1',
      displayName: '实现伙伴', collaborationRole: 'implementer', status: 'active', ordinal: 1,
    }],
    workItems: [{
      id: 'work-a', roomId: 'room-live', topicId: '', rootTurnId: 'root-a', rootWorkId: 'work-a', parentWorkId: '',
      objective: '完成 Room Focus 生产迁移', expectedOutput: '真实 WorkItem 与审批流', acceptanceCriteria: ['不使用静态候选数据'],
      accountableParticipantId: 'participant-a', currentOwnerParticipantId: 'participant-a', offeredToParticipantId: '',
      createdByParticipantId: 'participant-root', clientMessageId: 'client-a', state: 'active', depth: 0, revision: 1,
      resultSummary: '', artifactRefs: [], evidenceRefs: [], blocker: {}, acceptedTurnId: 'turn-a',
      createdAtMs: 100, updatedAtMs: 110, completedAtMs: null,
    }],
  };
}
