import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  appendOptimisticRoomMessage,
  applyRoomSnapshot,
  createRoomProjection,
  reduceRoomEvent,
  type RoomProjectionState,
} from '@/contracts/room-reducer';
import { parseRoomEvent } from '@/contracts/validators';
import { TooltipProvider } from '@/components/primitives';
import { PawOsDesktopProvider } from '@/features/paw-os/surface-context';
import type { RoomParticipant, RoomSummary, RoomWorkItem } from '@/features/rooms/room-types';
import { PawRoomRoundSheet } from './PawRoomRoundSheet';

afterEach(cleanup);

describe('PawRoomRoundSheet (UR-170/172)', () => {
  it('keeps one unassigned planet out of the task table and preserves its Session actions', () => {
    const projection = projectionWithProgress('尚未分配');
    projection.turnsById['turn-1'] = {
      ...projection.turnsById['turn-1']!,
      activityIds: [],
      participantIds: [],
    };
    projection.activitiesById = {};
    projection.activityOrder = [];

    render(
      <PawRoomRoundSheet
        onOpenParticipant={vi.fn()}
        projection={projection}
        room={roomWith([participant('participant-earth', 'session-earth', 0)])}
      />,
    );

    expect(screen.queryByRole('table')).not.toBeInTheDocument();
    const starter = screen.getByRole('region', { name: 'Earth 未分配' });
    expect(starter).toHaveTextContent('Grill Me');
    expect(within(starter).getByRole('button', { name: '打开 Earth Session' })).toBeInTheDocument();
  });

  it('keeps one row mounted while progress updates and opens the real planet identity explicitly', async () => {
    const user = userEvent.setup();
    const onOpenParticipant = vi.fn();
    const room = roomWith([
      participant('participant-earth', 'session-earth', 0),
      participant('participant-mars', 'session-mars', 1),
    ]);
    const projection = projectionWithProgress('正在核对 dispatch 回执');
    const { container, rerender } = render(
      <PawRoomRoundSheet
        onOpenParticipant={onOpenParticipant}
        projection={projection}
        room={room}
      />,
    );

    const surface = screen.getByRole('region', { name: 'Room 行星任务表' });
    expect(within(surface).getByText('完成 Room 任务表')).toBeInTheDocument();
    expect(within(surface).getByRole('columnheader', { name: '行星' })).toBeInTheDocument();
    expect(within(surface).getAllByRole('row')).toHaveLength(3);
    const earthRow = container.querySelector('[data-row-key="turn-1:participant-earth"]');
    expect(earthRow).not.toBeNull();
    expect(earthRow?.querySelector('[data-planet-row]')).toHaveAttribute('data-flowing-light', 'true');
    expect(earthRow).toHaveTextContent('正在核对 dispatch 回执');

    const detailButton = screen.getByRole('button', { name: '展开 Earth 详情' });
    const detailId = detailButton.getAttribute('aria-controls');
    expect(detailId).toBeTruthy();
    await user.click(detailButton);
    expect(screen.getByRole('region', { name: 'Earth 公开进展与证据' })).toHaveAttribute('id', detailId);
    expect(within(surface).getByText('公开进展')).toBeInTheDocument();
    expect(within(surface).getAllByText('正在核对 dispatch 回执')).toHaveLength(2);

    await user.click(screen.getByRole('button', { name: '打开 Earth Session' }));
    expect(onOpenParticipant).toHaveBeenCalledWith('participant-earth');
    onOpenParticipant.mockClear();
    await user.click(container.querySelector('[data-planet-row="turn-1:participant-earth"] td:nth-child(2)')!);
    expect(onOpenParticipant).toHaveBeenCalledWith('participant-earth');

    const updated: RoomProjectionState = {
      ...projection,
      activitiesById: {
        ...projection.activitiesById,
        'activity-earth': {
          ...projection.activitiesById['activity-earth']!,
          status: 'completed',
          summary: 'dispatch 回执已经核对完成',
          updatedAtMs: 5,
        },
      },
      turnsById: {
        ...projection.turnsById,
        'turn-1': {
          ...projection.turnsById['turn-1']!,
          terminalParticipantIds: ['participant-earth'],
          updatedAtMs: 5,
        },
      },
    };
    rerender(
      <PawRoomRoundSheet
        onOpenParticipant={onOpenParticipant}
        projection={updated}
        room={room}
      />,
    );

    const updatedEarthRow = container.querySelector('[data-row-key="turn-1:participant-earth"]');
    expect(updatedEarthRow).toBe(earthRow);
    expect(updatedEarthRow?.querySelector('[data-planet-row]')).not.toHaveAttribute('data-flowing-light');
    expect(updatedEarthRow).toHaveTextContent('dispatch 回执已经核对完成');
    expect(updatedEarthRow).toHaveTextContent('已完成');
  });

  it('lets the user fold one round without hiding the Room-level list of rounds', async () => {
    const user = userEvent.setup();
    render(
      <PawRoomRoundSheet
        onOpenParticipant={vi.fn()}
        projection={projectionWithProgress('正在工作')}
        room={roomWith([participant('participant-earth', 'session-earth', 0)])}
      />,
    );

    await user.click(screen.getByRole('button', { name: '折叠本轮任务' }));

    expect(screen.getByRole('button', { name: '展开本轮任务' })).toBeInTheDocument();
    expect(screen.queryByRole('table', { name: '完成 Room 任务表 · 行星进展' })).not.toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Room 行星任务表' })).toBeInTheDocument();
  });

  it('keeps multiple user rounds as independent collapsible sheets and updates the same row in place', async () => {
    const user = userEvent.setup();
    const room = roomWith([
      participant('participant-earth', 'session-earth', 0),
      participant('participant-mars', 'session-mars', 1),
    ]);
    const initial = projectionWithTwoRounds();
    const { container, rerender } = render(
      <PawRoomRoundSheet onOpenParticipant={vi.fn()} projection={initial} room={room} />,
    );

    const rounds = () => [...container.querySelectorAll<HTMLElement>('[data-round-id]')];
    const [firstRound, secondRound] = rounds();
    expect(firstRound).toBeTruthy();
    expect(secondRound).toBeTruthy();
    expect(firstRound.querySelector('table')).toBeNull();
    expect(secondRound.querySelector('table')).not.toBeNull();

    // Opening and folding the historical sheet must not change the latest one.
    await user.click(within(firstRound).getByRole('button', { name: '展开本轮任务' }));
    expect(firstRound.querySelector('table')).not.toBeNull();
    expect(secondRound.querySelector('table')).not.toBeNull();
    await user.click(within(firstRound).getByRole('button', { name: '折叠本轮任务' }));
    expect(firstRound.querySelector('table')).toBeNull();
    expect(secondRound.querySelector('table')).not.toBeNull();

    const marsRow = secondRound.querySelector('[data-row-key="turn-2:participant-mars"]');
    expect(marsRow).not.toBeNull();
    expect(marsRow).toHaveTextContent('第二轮正在执行');

    const updated = projectionWithTwoRounds();
    updated.activitiesById['activity-mars'] = {
      ...updated.activitiesById['activity-mars']!,
      status: 'completed',
      summary: '第二轮已经完成并回传证据',
      updatedAtMs: 8,
    };
    updated.turnsById['turn-2'] = {
      ...updated.turnsById['turn-2']!,
      status: 'completed',
      terminalParticipantIds: ['participant-mars'],
      updatedAtMs: 8,
    };
    rerender(<PawRoomRoundSheet onOpenParticipant={vi.fn()} projection={updated} room={room} />);

    const updatedMarsRow = container.querySelector('[data-row-key="turn-2:participant-mars"]');
    expect(updatedMarsRow).toBe(marsRow);
    expect(updatedMarsRow).toHaveTextContent('第二轮已经完成并回传证据');
    expect(updatedMarsRow).toHaveTextContent('已完成');
    expect(secondRound.querySelector('table')).not.toBeNull();
    expect(screen.queryByRole('log')).not.toBeInTheDocument();
  });

  it('moves an accepted result into a standalone result planet instead of a table row', async () => {
    const room = roomWith([participant('participant-earth', 'session-earth', 0)]);
    const running = projectionWithProgress('正在验收功能路径');
    const { rerender } = render(
      <PawRoomRoundSheet onOpenParticipant={vi.fn()} projection={running} room={room} />,
    );

    expect(screen.queryByRole('region', { name: 'Earth 公开进展与证据' })).not.toBeInTheDocument();

    const acceptedRoom = {
      ...room,
      workItems: [workItem(
        'work-accepted',
        'turn-1',
        '验收完成，结果已写入 /work/paw/final-result.md。',
        ['/work/paw/final-result.md'],
        5,
      )],
    };
    const accepted: RoomProjectionState = {
      ...running,
      turnsById: {
        ...running.turnsById,
        'turn-1': {
          ...running.turnsById['turn-1']!,
          status: 'completed',
          terminalParticipantIds: ['participant-earth'],
          updatedAtMs: 5,
        },
      },
    };
    rerender(
      <PawRoomRoundSheet onOpenParticipant={vi.fn()} projection={accepted} room={acceptedRoom} />,
    );

    const result = await screen.findByRole('region', { name: 'Earth 最终结果' });
    expect(result).toHaveAttribute('data-result-ready', 'true');
    expect(result).toHaveTextContent('验收完成');
    expect(within(result).getByRole('link', { name: '打开文件 final-result.md' })).toBeInTheDocument();
    expect(within(result).getByRole('button', { name: '打开文件 final-result.md' })).toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '收起 Earth 详情' })).not.toBeInTheDocument();
  });

  it('keeps unfinished collaborators in the table while presenting a submitted planet result separately', () => {
    const room = roomWith([
      participant('participant-earth', 'session-earth', 0),
      participant('participant-mars', 'session-mars', 1),
    ]);
    room.workItems = [workItem('work-earth-result', 'turn-1', 'Earth 已提交最终结果。', [], 5)];
    const projection = projectionWithProgress('Earth 已完成');
    projection.turnsById['turn-1'] = {
      ...projection.turnsById['turn-1']!,
      status: 'completed',
      terminalParticipantIds: ['participant-earth'],
      updatedAtMs: 5,
    };

    const { container } = render(
      <PawRoomRoundSheet onOpenParticipant={vi.fn()} projection={projection} room={room} />,
    );

    const result = screen.getByRole('region', { name: 'Earth 最终结果' });
    expect(result.closest('table')).toBeNull();
    expect(container.querySelector('[data-row-key="turn-1:participant-earth"]')).toBeNull();
    expect(container.querySelector('[data-row-key="turn-1:participant-mars"]')).not.toBeNull();
    expect(screen.getByRole('table')).toHaveTextContent('Mars');
  });

  it('keeps the round and planet DOM nodes across a retry-only snapshot, without merging a new user round', () => {
    const room = roomWith([
      participant('participant-earth', 'session-earth', 0),
      participant('participant-mars', 'session-mars', 1),
    ]);
    const firstClientMessageId = 'client-dom-lineage';
    const retryClientMessageId = 'client-dom-retry';
    const optimistic = appendOptimisticRoomMessage(createRoomProjection('room-a'), {
      clientMessageId: firstClientMessageId,
      text: '原始 DOM 轮次',
      nowMs: 1,
    });
    const accepted = reduceRoomEvent(optimistic, parseRoomEvent({
      schemaVersion: 'rag-ime.agent-room-event.v1',
      eventId: 'room-a:1',
      roomId: 'room-a',
      sequence: 1,
      turnId: 'room-turn-authoritative',
      eventType: 'user_message',
      participantId: null,
      sourceSessionId: '',
      createdAtMs: 2,
      payload: {
        messageId: 'room-user-authoritative',
        clientMessageId: firstClientMessageId,
        rootId: 'room-turn-authoritative',
        text: '原始 DOM 轮次',
      },
      resumeToken: 'room-a:1',
    })).state;
    const retrying = appendOptimisticRoomMessage(accepted, {
      clientMessageId: retryClientMessageId,
      text: '原始 DOM 轮次（重试）',
      retryOfRootId: 'room-turn-authoritative',
      nowMs: 3,
    });
    const retryDraft = retrying.messagesById[`local-room:${retryClientMessageId}`]!;
    const retryOnly = applyRoomSnapshot(retrying, {
      messages: [{
        ...retryDraft,
        id: 'room-user-retry-authoritative',
        turnId: 'room-turn-retry-authoritative',
        rootId: 'room-turn-retry-authoritative',
        projectionKind: 'post',
        status: 'completed',
        completedAtMs: 4,
      }],
      lastSequence: 2,
      resumeToken: 'room-a:2',
    });

    const { container, rerender } = render(
      <PawRoomRoundSheet onOpenParticipant={vi.fn()} projection={retrying} room={room} />,
    );
    const roundBefore = container.querySelector('[data-round-id="local-room-turn:client-dom-lineage"]');
    const rowBefore = container.querySelector('[data-row-key="local-room-turn:client-dom-lineage:participant-earth"]');
    expect(roundBefore).not.toBeNull();
    expect(rowBefore).not.toBeNull();

    rerender(<PawRoomRoundSheet onOpenParticipant={vi.fn()} projection={retryOnly} room={room} />);
    const roundAfter = container.querySelector('[data-round-id="local-room-turn:client-dom-lineage"]');
    const rowAfter = container.querySelector('[data-row-key="local-room-turn:client-dom-lineage:participant-earth"]');
    expect(roundAfter).toBe(roundBefore);
    expect(rowAfter).toBe(rowBefore);

    const withNewRound = reduceRoomEvent(retryOnly, parseRoomEvent({
      schemaVersion: 'rag-ime.agent-room-event.v1',
      eventId: 'room-a:3',
      roomId: 'room-a',
      sequence: 3,
      turnId: 'room-turn-new',
      eventType: 'user_message',
      participantId: null,
      sourceSessionId: '',
      createdAtMs: 5,
      payload: {
        messageId: 'room-user-new',
        clientMessageId: 'client-dom-new',
        rootId: 'room-turn-new',
        text: '完全新的 DOM 轮次',
      },
      resumeToken: 'room-a:3',
    })).state;
    rerender(<PawRoomRoundSheet onOpenParticipant={vi.fn()} projection={withNewRound} room={room} />);

    expect(container.querySelectorAll('[data-round-id]')).toHaveLength(2);
    expect(container.querySelector('[data-round-id="local-room-turn:client-dom-lineage"]')).toBe(roundBefore);
    expect(container.querySelector('[data-round-id="room-turn-new"]')).not.toBeNull();
    expect(container.querySelector('[data-row-key="room-turn-new:participant-earth"]')).not.toBe(rowBefore);
  });

  it('scrolls only when a new logical user round appears, not for in-place progress updates', async () => {
    const scrollTo = vi.fn();
    const previous = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'scrollTo');
    Object.defineProperty(HTMLElement.prototype, 'scrollTo', {
      configurable: true,
      value: scrollTo,
      writable: true,
    });
    try {
      const room = roomWith([
        participant('participant-earth', 'session-earth', 0),
        participant('participant-mars', 'session-mars', 1),
      ]);
      const first = projectionWithProgress('第一轮正在执行');
      const { rerender } = render(
        <PawRoomRoundSheet onOpenParticipant={vi.fn()} projection={first} room={room} />,
      );
      await waitFor(() => expect(scrollTo).toHaveBeenCalledTimes(1));

      const sameRound = projectionWithProgress('第一轮原地更新');
      rerender(<PawRoomRoundSheet onOpenParticipant={vi.fn()} projection={sameRound} room={room} />);
      await new Promise((resolve) => requestAnimationFrame(resolve));
      expect(scrollTo).toHaveBeenCalledTimes(1);

      rerender(
        <PawRoomRoundSheet
          onOpenParticipant={vi.fn()}
          projection={projectionWithTwoRounds()}
          room={room}
        />,
      );
      await waitFor(() => expect(scrollTo).toHaveBeenCalledTimes(2));
      expect(scrollTo).toHaveBeenLastCalledWith(expect.objectContaining({ behavior: 'smooth' }));
    } finally {
      if (previous) Object.defineProperty(HTMLElement.prototype, 'scrollTo', previous);
      else delete (HTMLElement.prototype as unknown as { scrollTo?: typeof scrollTo }).scrollTo;
    }
  });

  it('shows the authoritative blocker reason and suggested next step in the same row', async () => {
    const user = userEvent.setup();
    const onOpenParticipant = vi.fn();
    const onResumeBlocked = vi.fn();
    const room = roomWith([participant('participant-earth', 'session-earth', 0)]);
    room.workItems = [{
      id: 'work-blocked', roomId: 'room-a', topicId: '', rootTurnId: 'turn-1', rootWorkId: 'work-blocked',
      parentWorkId: '', objective: '检查 Trace API', expectedOutput: '可验证回执', acceptanceCriteria: ['路由可读'],
      accountableParticipantId: 'participant-earth', currentOwnerParticipantId: 'participant-earth',
      offeredToParticipantId: '', createdByParticipantId: 'participant-earth', clientMessageId: 'client-1',
      state: 'blocked', depth: 1, revision: 0, resultSummary: '', artifactRefs: [], evidenceRefs: [],
      blocker: { reason: '缺少 Runtime 路由', nextStep: '恢复 Gateway 后重试' }, acceptedTurnId: '',
      createdAtMs: 2, updatedAtMs: 4, completedAtMs: null,
    }];
    const { rerender } = render(
      <PawRoomRoundSheet
        onOpenParticipant={onOpenParticipant}
        onResumeBlocked={onResumeBlocked}
        projection={projectionWithProgress('等待 Runtime')}
        room={room}
      />,
    );

    expect(screen.getByText('已阻塞')).toBeInTheDocument();
    expect(screen.getByText('缺少 Runtime 路由')).toBeInTheDocument();
    const resumeButton = screen.getByRole('button', { name: '恢复 Earth 并重新分派' });
    await user.click(resumeButton);
    expect(onResumeBlocked).toHaveBeenCalledWith(expect.objectContaining({
      blockedWorkItemId: 'work-blocked',
      state: 'blocked',
    }));
    expect(onOpenParticipant).not.toHaveBeenCalled();
    rerender(
      <PawRoomRoundSheet
        onOpenParticipant={onOpenParticipant}
        onResumeBlocked={onResumeBlocked}
        projection={projectionWithProgress('等待 Runtime')}
        resumeErrorByRow={{ 'turn-1:participant-earth': 'Runtime 拒绝了恢复请求' }}
        room={room}
      />,
    );
    expect(screen.getByRole('button', { name: '重试 Earth 并重新分派' })).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('Runtime 拒绝了恢复请求');
    await user.click(screen.getByRole('button', { name: '展开 Earth 详情' }));
    expect(screen.getByRole('status')).toHaveTextContent('建议下一步：恢复 Gateway 后重试');
  });

  it('opens absolute result paths and registered file artifacts through the Files surface', async () => {
    const user = userEvent.setup();
    const openRoute = vi.fn();
    const room = roomWith([participant('participant-earth', 'session-earth', 0)]);
    room.artifacts = [{
      id: 'artifact:report',
      roomId: 'room-a',
      topicId: '',
      displayName: 'report.md',
      path: '/work/paw/report.md',
      mediaType: 'text/markdown',
      status: 'active',
      createdAtMs: 1,
      updatedAtMs: 4,
    }];
    room.workItems = [workItem('work-report', 'turn-1', '已写入 /work/paw/summary.md。', ['artifact:report'], 4)];
    const projection = projectionWithProgress('已生成 /work/paw/summary.md');
    projection.turnsById['turn-1'] = {
      ...projection.turnsById['turn-1']!,
      messageIds: ['user-1', 'assistant-1'],
    };
    projection.messagesById['assistant-1'] = {
      id: 'assistant-1',
      roomId: 'room-a',
      turnId: 'turn-1',
      participantId: 'participant-earth',
      sourceSessionId: 'session-earth',
      role: 'assistant',
      status: 'completed',
      text: '已写入 /work/paw/summary.md。',
      createdAtMs: 4,
    };
    projection.messageOrder = ['user-1', 'assistant-1'];

    render(
      <TooltipProvider>
        <PawOsDesktopProvider openRoute={openRoute} openWindow={() => undefined}>
          <PawRoomRoundSheet onOpenParticipant={vi.fn()} projection={projection} room={room} />
        </PawOsDesktopProvider>
      </TooltipProvider>,
    );

    await user.click(screen.getByRole('button', { name: '展开 Earth 详情' }));
    await user.click(screen.getByRole('button', { name: '打开文件 report.md' }));
    expect(openRoute).toHaveBeenCalledWith('/files?session=session-earth&path=%2Fwork%2Fpaw%2Freport.md');

    const result = screen.getByRole('region', { name: 'Earth 公开进展与证据' })
      .querySelector<HTMLElement>('.paw-room-round__result')!;
    await user.click(within(result).getByRole('link', { name: '打开文件 summary.md' }));
    expect(openRoute).toHaveBeenCalledWith('/files?session=session-earth&path=%2Fwork%2Fpaw%2Fsummary.md');
  });

  it('opens relative workspace files named by a Room result', async () => {
    const user = userEvent.setup();
    const openRoute = vi.fn();
    const room = roomWith([participant('participant-earth', 'session-earth', 0)]);
    room.artifacts = [{
      id: 'artifact:report',
      roomId: 'room-a',
      topicId: '',
      displayName: 'final-result.md',
      path: 'docs/final-result.md',
      mediaType: 'text/markdown',
      status: 'active',
      createdAtMs: 1,
      updatedAtMs: 4,
    }];
    room.workItems = [workItem(
      'work-report',
      'turn-1',
      '验收通过，详见 docs/final-result.md。',
      ['artifact:report'],
      4,
    )];
    const projection = projectionWithProgress('已生成 docs/final-result.md');
    projection.turnsById['turn-1'] = {
      ...projection.turnsById['turn-1']!,
      status: 'completed',
      terminalParticipantIds: ['participant-earth'],
    };

    render(
      <TooltipProvider>
        <PawOsDesktopProvider openRoute={openRoute} openWindow={() => undefined}>
          <PawRoomRoundSheet onOpenParticipant={vi.fn()} projection={projection} room={room} />
        </PawOsDesktopProvider>
      </TooltipProvider>,
    );

    const result = screen.getByRole('region', { name: 'Earth 最终结果' });
    expect(within(result).getByRole('button', { name: '打开文件 final-result.md' })).toBeInTheDocument();
    const resultLink = within(result).getByRole('link', { name: '打开文件 final-result.md' });
    await user.click(resultLink);
    expect(openRoute).toHaveBeenCalledWith('/files?session=session-earth&path=docs%2Ffinal-result.md');
  });

  it('lets the shared Markdown AST own result file links without rewriting code or punctuation', async () => {
    const user = userEvent.setup();
    const openRoute = vi.fn();
    const room = roomWith([participant('participant-earth', 'session-earth', 0)]);
    room.workItems = [workItem(
      'work-report',
      'turn-1',
      [
        '查看 [报告](docs/report.md)，并保留 `docs/inline.md`。',
        '',
        '```text',
        'docs/fenced.md',
        '```',
        '',
        '补充见 docs/appendix.md。',
      ].join('\n'),
      [],
      4,
    )];
    const projection = projectionWithProgress('报告已完成');
    projection.turnsById['turn-1'] = {
      ...projection.turnsById['turn-1']!,
      status: 'completed',
      terminalParticipantIds: ['participant-earth'],
    };

    render(
      <TooltipProvider>
        <PawOsDesktopProvider openRoute={openRoute} openWindow={() => undefined}>
          <PawRoomRoundSheet onOpenParticipant={vi.fn()} projection={projection} room={room} />
        </PawOsDesktopProvider>
      </TooltipProvider>,
    );

    const detail = screen.getByRole('region', { name: 'Earth 最终结果' });
    expect(within(detail).getByRole('link', { name: '打开文件 report.md' })).toHaveTextContent('报告');
    expect(within(detail).getByText('docs/inline.md').tagName).toBe('CODE');
    expect(within(detail).getByText('docs/fenced.md')).toBeInTheDocument();
    expect(within(detail).queryByRole('link', { name: '打开文件 inline.md' })).not.toBeInTheDocument();
    expect(within(detail).queryByRole('link', { name: '打开文件 fenced.md' })).not.toBeInTheDocument();
    expect(detail).toHaveTextContent('docs/appendix.md。');

    await user.click(within(detail).getByRole('link', { name: '打开文件 report.md' }));
    expect(openRoute).toHaveBeenCalledWith('/files?session=session-earth&path=docs%2Freport.md');
    await user.click(within(detail).getByRole('link', { name: '打开文件 appendix.md' }));
    expect(openRoute).toHaveBeenCalledWith('/files?session=session-earth&path=docs%2Fappendix.md');
  });

  it('renders current task and progress as safe Markdown instead of leaking formatting tokens', () => {
    const projection = projectionWithProgress('**已完成** `Trace`\n\n- 已回执\n- 可复核');
    projection.activitiesById['activity-earth'] = {
      ...projection.activitiesById['activity-earth']!,
      payload: {
        ...projection.activitiesById['activity-earth']!.payload,
        task: '**核对** `Room` 事件',
      },
    };
    const room = roomWith([participant('participant-earth', 'session-earth', 0)]);
    const { container } = render(
      <PawRoomRoundSheet onOpenParticipant={vi.fn()} projection={projection} room={room} />,
    );

    const row = container.querySelector('[data-row-key="turn-1:participant-earth"]')!;
    expect(row.querySelector('td:nth-child(2) .agent-markdown strong')).toHaveTextContent('核对');
    expect(row.querySelector('td:nth-child(2) .agent-markdown code')).toHaveTextContent('Room');
    expect(row.querySelectorAll('li')).toHaveLength(2);
    expect(row).not.toHaveTextContent('**已完成**');
    expect(row).not.toHaveTextContent('`Trace`');
  });

  it('does not turn a completed planet red because its turn history contains a recoverable tool failure', () => {
    const projection = projectionWithProgress('工具失败后已恢复并完成');
    projection.turnsById['turn-1'] = {
      ...projection.turnsById['turn-1']!,
      status: 'completed',
      terminalParticipantIds: [],
    };
    projection.activitiesById['activity-earth'] = {
      ...projection.activitiesById['activity-earth']!,
      status: 'failed',
    };

    render(
      <PawRoomRoundSheet
        onOpenParticipant={vi.fn()}
        projection={projection}
        room={roomWith([participant('participant-earth', 'session-earth', 0)])}
      />,
    );

    const row = screen.getByRole('row', { name: /Earth/ });
    expect(row).toHaveTextContent('已完成');
    expect(row).not.toHaveTextContent('需要关注');
    expect(within(row).getByText('工具失败后已恢复并完成')).toBeInTheDocument();
  });
});

function projectionWithProgress(summary: string): RoomProjectionState {
  return {
    ...createRoomProjection('room-a'),
    turnOrder: ['turn-1'],
    turnsById: {
      'turn-1': {
        id: 'turn-1',
        rootId: 'turn-1',
        status: 'running',
        messageIds: ['user-1'],
        activityIds: ['activity-earth'],
        participantIds: ['participant-earth'],
        createdAtMs: 1,
        updatedAtMs: 3,
      },
    },
    messagesById: {
      'user-1': {
        id: 'user-1',
        roomId: 'room-a',
        turnId: 'turn-1',
        participantId: null,
        sourceSessionId: '',
        role: 'user',
        status: 'completed',
        text: '完成 Room 任务表',
        createdAtMs: 1,
      },
    },
    messageOrder: ['user-1'],
    activitiesById: {
      'activity-earth': {
        id: 'activity-earth',
        turnId: 'turn-1',
        participantId: 'participant-earth',
        sourceSessionId: 'session-earth',
        kind: 'participant_activity',
        status: 'running',
        summary,
        payload: {
          rootId: 'turn-1',
          dispatchId: 'dispatch-earth',
          sourceEventType: 'current_progress',
          task: '检查 Room 事件投影',
        },
        createdAtMs: 2,
        updatedAtMs: 3,
      },
    },
    activityOrder: ['activity-earth'],
  };
}

function projectionWithTwoRounds(): RoomProjectionState {
  const first = projectionWithProgress('第一轮已经完成');
  return {
    ...first,
    turnOrder: ['turn-1', 'turn-2'],
    turnsById: {
      ...first.turnsById,
      'turn-1': {
        ...first.turnsById['turn-1']!,
        status: 'completed',
        terminalParticipantIds: ['participant-earth'],
      },
      'turn-2': {
        id: 'turn-2',
        rootId: 'turn-2',
        status: 'running',
        messageIds: ['user-2'],
        activityIds: ['activity-mars'],
        participantIds: ['participant-mars'],
        createdAtMs: 4,
        updatedAtMs: 6,
      },
    },
    messagesById: {
      ...first.messagesById,
      'user-2': {
        id: 'user-2',
        roomId: 'room-a',
        turnId: 'turn-2',
        participantId: null,
        sourceSessionId: '',
        role: 'user',
        status: 'completed',
        text: '第二轮任务',
        createdAtMs: 4,
      },
    },
    messageOrder: ['user-1', 'user-2'],
    activitiesById: {
      ...first.activitiesById,
      'activity-mars': {
        id: 'activity-mars',
        turnId: 'turn-2',
        participantId: 'participant-mars',
        sourceSessionId: 'session-mars',
        kind: 'participant_activity',
        status: 'running',
        summary: '第二轮正在执行',
        payload: {
          rootId: 'turn-2',
          dispatchId: 'dispatch-mars',
          sourceEventType: 'current_progress',
          task: '核对第二轮证据',
        },
        createdAtMs: 5,
        updatedAtMs: 6,
      },
    },
    activityOrder: ['activity-earth', 'activity-mars'],
  };
}

function participant(id: string, sessionId: string, ordinal: number): RoomParticipant {
  return {
    id,
    sessionId,
    roleId: 'implementer',
    roleVersion: '1',
    displayName: `伙伴 ${id}`,
    collaborationRole: ordinal === 0 ? 'coordinator' : 'implementer',
    status: 'active',
    ordinal,
  };
}

function workItem(
  id: string,
  rootTurnId: string,
  resultSummary: string,
  evidenceRefs: string[],
  updatedAtMs: number,
): RoomWorkItem {
  return {
    id,
    roomId: 'room-a',
    topicId: '',
    rootTurnId,
    rootWorkId: id,
    parentWorkId: '',
    objective: `${id} task`,
    expectedOutput: '',
    acceptanceCriteria: [],
    accountableParticipantId: 'participant-earth',
    currentOwnerParticipantId: 'participant-earth',
    offeredToParticipantId: '',
    createdByParticipantId: 'participant-earth',
    clientMessageId: id,
    state: 'done',
    depth: 1,
    revision: 0,
    resultSummary,
    artifactRefs: [],
    evidenceRefs,
    blocker: {},
    acceptedTurnId: rootTurnId,
    createdAtMs: updatedAtMs - 1,
    updatedAtMs,
    completedAtMs: updatedAtMs,
  };
}

function roomWith(participants: RoomParticipant[]): RoomSummary {
  return {
    id: 'room-a',
    title: 'Room A',
    status: 'active',
    routingPolicy: 'natural',
    moderatorParticipantId: participants[0]?.id ?? '',
    updatedAtMs: 1,
    participants,
  };
}
