import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import type { RoomSummary } from '@/features/rooms/room-types';
import { PawRoomExecution } from './PawRoomExecution';

describe('PawRoomExecution', () => {
  it('keeps the full acceptance checklist reachable through a reversible disclosure', async () => {
    const room: RoomSummary = {
      id: 'room-a',
      title: '验收 Room',
      status: 'active',
      routingPolicy: 'parallel',
      moderatorParticipantId: '',
      updatedAtMs: 2,
      participants: [],
      workItems: [{
        id: 'work-a',
        roomId: 'room-a',
        topicId: '',
        rootTurnId: 'turn-a',
        rootWorkId: 'work-a',
        parentWorkId: '',
        objective: '核对完整验收清单',
        expectedOutput: '回归报告',
        acceptanceCriteria: Array.from({ length: 18 }, (_, index) => `验收项 ${index + 1}`),
        accountableParticipantId: '',
        currentOwnerParticipantId: '',
        offeredToParticipantId: '',
        createdByParticipantId: '',
        clientMessageId: '',
        state: 'review',
        depth: 0,
        revision: 2,
        resultSummary: '',
        artifactRefs: [],
        evidenceRefs: [],
        blocker: {},
        acceptedTurnId: '',
        createdAtMs: 1,
        updatedAtMs: 2,
        completedAtMs: null,
      }],
    };
    const user = userEvent.setup();
    render(<PawRoomExecution room={room} />);

    const summary = screen.getByText('验收条件 · 18').closest('summary')!;
    const disclosure = summary.closest('details')!;
    const reveal = disclosure.querySelector('.ui-disclosure__reveal')!;
    expect(disclosure).toHaveClass('ui-disclosure');
    expect(summary).toHaveAttribute('aria-expanded', 'false');
    expect(reveal).toHaveAttribute('inert');
    await user.click(summary);
    expect(summary).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText('验收项 18')).toBeInTheDocument();
    await user.click(summary);
    expect(summary).toHaveAttribute('aria-expanded', 'false');
    expect(reveal).toHaveAttribute('inert');
    await user.click(summary);
    expect(screen.getByText('验收项 1')).toBeInTheDocument();
  });
});
