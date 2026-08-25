import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { RoomFocusProjection } from './room-focus-projection';
import { PawRoomFocusOverview } from './PawRoomFocusOverview';

afterEach(cleanup);

const focus: RoomFocusProjection = {
  goal: {
    title: '任务图依赖验证',
    description: '两个实现分支汇合后复核。',
    rootId: 'turn-root',
    state: 'review',
  },
  workItems: [
    {
      id: 'work-root',
      source: 'work-item',
      objective: '整合 Room 任务图',
      expectedOutput: '可复查的整合版本',
      acceptanceCriteria: [],
      ownerParticipantId: 'p-venus',
      accountableParticipantId: 'p-venus',
      state: 'review',
      reviewRequired: true,
      latestResult: '两个实现分支已汇合。',
      evidence: [{ ref: 'test:room-focus', kind: 'evidence' }],
      updatedAtMs: 30,
    },
    {
      id: 'runtime:earth',
      parentId: 'work-root',
      source: 'runtime',
      objective: '实现任务图交互',
      acceptanceCriteria: [],
      ownerParticipantId: 'p-earth',
      state: 'completed',
      currentAction: '任务图交互已通过测试',
      reviewRequired: false,
      evidence: [],
      dispatchId: 'earth',
      updatedAtMs: 20,
    },
    {
      id: 'runtime:mars',
      parentId: 'work-root',
      source: 'runtime',
      objective: '实现依赖数据投影',
      acceptanceCriteria: [],
      ownerParticipantId: 'p-mars',
      state: 'running',
      currentAction: '正在核对依赖投影',
      reviewRequired: false,
      evidence: [],
      dispatchId: 'mars',
      updatedAtMs: 21,
    },
  ],
  partners: [
    {
      participantId: 'p-earth',
      sessionId: 'session-earth',
      displayName: 'Agent 1',
      celestialName: 'Earth',
      state: 'completed',
      ownedWorkItemIds: ['runtime:earth'],
      currentAction: '任务图交互已通过测试',
      latestReceipt: '交互实现完成',
      unread: false,
    },
    {
      participantId: 'p-mars',
      sessionId: 'session-mars',
      displayName: 'Agent 2',
      celestialName: 'Mars',
      state: 'running',
      ownedWorkItemIds: ['runtime:mars'],
      currentAction: '正在核对依赖投影',
      unread: false,
    },
    {
      participantId: 'p-venus',
      sessionId: 'session-venus',
      displayName: 'Agent 3',
      celestialName: 'Venus',
      state: 'review',
      ownedWorkItemIds: ['work-root'],
      currentAction: '等待独立复核',
      unread: false,
    },
  ],
  handoffs: [{
    id: 'handoff-earth-mars',
    sourceParticipantId: 'p-earth',
    targetParticipantId: 'p-mars',
    dispatchId: 'mars',
    task: '交付依赖投影',
    state: 'dispatched',
    createdAtMs: 22,
  }],
  flow: [
    {
      id: 'message:request',
      sourceParticipantId: 'root',
      targetParticipantIds: ['p-earth'],
      kind: 'request',
      summary: '请并行实现任务图交互与依赖投影',
      status: 'completed',
      createdAtMs: 10,
      sequence: 1,
      refs: [],
    },
    {
      id: 'activity:dispatch-mars',
      sourceParticipantId: 'p-earth',
      targetParticipantIds: ['p-mars'],
      kind: 'dispatch',
      summary: '分派依赖投影支线',
      status: 'completed',
      createdAtMs: 22,
      sequence: 2,
      dispatchId: 'mars',
      refs: ['context://room/brief'],
    },
    {
      id: 'message:result-earth',
      sourceParticipantId: 'p-earth',
      targetParticipantIds: ['root'],
      kind: 'result',
      summary: '任务图交互已通过测试',
      status: 'completed',
      createdAtMs: 30,
      sequence: 3,
      refs: [],
    },
  ],
  rootEvidence: [{ ref: 'test:room-focus', kind: 'evidence' }],
  counts: { active: 1, review: 1, blocked: 0, completed: 1 },
};

describe('PawRoomFocusOverview', () => {
  it('answers goal, owner, state and handoff without opening every partner', () => {
    render(<PawRoomFocusOverview focus={focus} onOpenParticipant={vi.fn()} />);

    expect(screen.getByRole('region', { name: 'Sol 协作态势' })).toHaveTextContent('任务图依赖验证');
    expect(screen.getByRole('list', { name: '并行轨道' })).toHaveTextContent('实现依赖数据投影');
    expect(screen.getByRole('list', { name: '行星伙伴' })).toHaveTextContent('Earth');
    expect(screen.getByLabelText('任务交接')).toHaveTextContent('Earth → Mars');
    expect(screen.getByRole('region', { name: '焦点详情' })).toHaveTextContent('等待独立复核');
  });

  it('lays the task flow out as parallel owner lanes with verifier planets and a state pulse', () => {
    const withVerifier = {
      ...focus,
      workItems: focus.workItems.map((item) => item.id === 'runtime:mars'
        ? { ...item, accountableParticipantId: 'p-venus' }
        : item),
    };
    render(<PawRoomFocusOverview focus={withVerifier} onOpenParticipant={vi.fn()} />);

    // Dead counters are gone; the same real counts live on one pulse strip.
    expect(screen.queryByLabelText('协作摘要')).not.toBeInTheDocument();
    expect(screen.getByRole('img', { name: '任务状态：进行 1，复核 1，完成 1' })).toBeInTheDocument();

    const laneList = screen.getByRole('list', { name: '并行轨道' });
    expect(within(laneList).getByRole('list', { name: 'Earth 的任务' })).toHaveTextContent('实现任务图交互');
    expect(within(laneList).getByRole('list', { name: 'Venus 的任务' })).toHaveTextContent('整合 Room 任务图');
    const marsTrack = within(laneList).getByRole('list', { name: 'Mars 的任务' });
    expect(marsTrack).toHaveTextContent('实现依赖数据投影');
    expect(marsTrack).toHaveTextContent('复核 Venus');

    // Selecting a lane node fills the inspector with owner and verifier.
    fireEvent.click(within(marsTrack).getByRole('button', { name: /实现依赖数据投影/ }));
    const inspector = screen.getByRole('region', { name: '焦点详情' });
    expect(inspector).toHaveTextContent('负责人');
    expect(inspector).toHaveTextContent('Mars · Agent 2');
    expect(inspector).toHaveTextContent('复核人');
    expect(inspector).toHaveTextContent('Venus · Agent 3');
  });

  it('keeps unowned work visible in one trailing 待认领 lane instead of dropping it', () => {
    const withUnclaimed = {
      ...focus,
      workItems: [...focus.workItems, {
        id: 'work-orphan',
        source: 'work-item' as const,
        objective: '补齐验收记录',
        acceptanceCriteria: [],
        state: 'waiting' as const,
        reviewRequired: false,
        evidence: [],
        updatedAtMs: 40,
      }],
    };
    render(<PawRoomFocusOverview focus={withUnclaimed} onOpenParticipant={vi.fn()} />);

    expect(within(screen.getByRole('list', { name: '并行轨道' }))
      .getByRole('list', { name: '待认领 的任务' })).toHaveTextContent('补齐验收记录');
  });

  it('reveals the dispatch verdict — every candidate and the selection — behind a dispatch packet', () => {
    const withPlan = {
      ...focus,
      flow: focus.flow.map((packet) => packet.id === 'activity:dispatch-mars'
        ? {
            ...packet,
            plan: {
              policy: 'parallel',
              reason: 'partner_delegate',
              targetParticipantIds: ['p-mars'],
              child: true,
              parallelIndex: 0,
              parallelSize: 2,
              candidates: [
                { participantId: 'p-earth', displayName: 'Agent 1', score: 0, signals: [], selected: false },
                { participantId: 'p-mars', displayName: 'Agent 2', score: 1, signals: ['explicit_invite'], selected: true },
              ],
            },
          }
        : packet),
    };
    render(<PawRoomFocusOverview focus={withPlan} onOpenParticipant={vi.fn()} />);

    const ledger = screen.getByRole('region', { name: '往来记录' });
    fireEvent.click(within(ledger).getByRole('button', { name: /分派依赖投影支线/ }));
    const candidates = within(ledger).getByRole('list', { name: '候选伙伴' });
    const mars = within(candidates).getByText('Mars').closest('li')!;
    expect(mars).toHaveAttribute('data-selected');
    expect(mars).toHaveTextContent('点名邀请');
    const earth = within(candidates).getByText('Earth').closest('li')!;
    expect(earth).not.toHaveAttribute('data-selected');
    expect(earth).toHaveTextContent('未选');
  });

  it('selects a planet with pointer or keyboard and opens only its real participant target', () => {
    const onOpenParticipant = vi.fn();
    render(<PawRoomFocusOverview focus={focus} onOpenParticipant={onOpenParticipant} />);
    const planets = screen.getByRole('list', { name: '行星伙伴' });
    const mars = within(planets).getByRole('button', { name: /Mars/ });

    fireEvent.click(mars);
    expect(screen.getByRole('region', { name: '焦点详情' })).toHaveTextContent('正在核对依赖投影');
    fireEvent.keyDown(within(planets).getByRole('button', { name: /Earth/ }), { key: 'Enter' });
    fireEvent.click(screen.getByRole('button', { name: '打开 Earth 伙伴窗口' }));

    expect(onOpenParticipant).toHaveBeenCalledWith('p-earth');
  });

  it('keeps the chronological flow ledger inside the console with celestial actor names and packet detail', () => {
    render(<PawRoomFocusOverview focus={focus} onOpenParticipant={vi.fn()} />);

    const ledger = screen.getByRole('region', { name: '往来记录' });
    expect(within(ledger).getByText('最近 3 / 共 3 条')).toBeInTheDocument();
    const packets = within(ledger).getByRole('list', { name: '往来事件' });
    expect(packets).toHaveTextContent('Sol → Earth');
    expect(packets).toHaveTextContent('Earth → Mars');

    // The latest packet is pre-selected; picking the dispatch reveals its refs.
    expect(within(ledger).getByRole('button', { name: /任务图交互已通过测试/ })).toHaveAttribute('aria-current', 'true');
    fireEvent.click(within(ledger).getByRole('button', { name: /分派依赖投影支线/ }));
    const detail = ledger.querySelector('.paw-room-focus-overview__packet-detail')!;
    expect(detail).toHaveTextContent('任务分派');
    expect(detail).toHaveTextContent('context://room/brief');
    expect(detail).toHaveTextContent('mars');
  });

  it('windows a long ledger to the recent slice until the reader asks for everything', () => {
    const longFlow = Array.from({ length: 21 }, (_, index) => ({
      id: `packet-${index}`,
      sourceParticipantId: 'root',
      targetParticipantIds: ['p-earth'],
      kind: 'dispatch' as const,
      summary: `分派 ${index}`,
      status: 'completed',
      createdAtMs: index,
      sequence: index,
      refs: [],
    }));
    render(<PawRoomFocusOverview focus={{ ...focus, flow: longFlow }} onOpenParticipant={vi.fn()} />);

    expect(screen.getByText('最近 18 / 共 21 条')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '显示全部' }));
    expect(screen.getByText('最近 21 / 共 21 条')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '显示全部' })).not.toBeInTheDocument();
  });

  it('keeps the full acceptance checklist reachable through the inspector disclosure', () => {
    const acceptance = Array.from({ length: 18 }, (_, index) => `验收项 ${index + 1}`);
    const withAcceptance = {
      ...focus,
      workItems: focus.workItems.map((item) => item.id === 'work-root'
        ? { ...item, acceptanceCriteria: acceptance }
        : item),
    };
    render(<PawRoomFocusOverview focus={withAcceptance} onOpenParticipant={vi.fn()} />);

    const summary = screen.getByText('验收条件 · 18').closest('summary')!;
    expect(summary).toHaveAttribute('aria-expanded', 'false');
    fireEvent.click(summary);
    expect(summary).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText('验收项 18')).toBeInTheDocument();
    expect(screen.getByRole('region', { name: '焦点详情' })).toHaveTextContent('可复查的整合版本');
  });
});
