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
      verifierParticipantId: 'p-venus',
      state: 'review',
      reviewRequired: true,
      review: { operability: 'passed', requirement: 'satisfied', reviewerParticipantId: 'p-venus' },
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
      wave: { waveId: 'wave-a', phaseName: '并行实现两条支线', parallelIndex: 0, parallelSize: 2 },
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
      wave: { waveId: 'wave-a', phaseName: '并行实现两条支线', parallelIndex: 1, parallelSize: 2 },
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
      dispatchPlan: {
        dispatchId: 'mars',
        parentDispatchId: 'earth-root',
        child: true,
        reason: 'partner_delegate',
        reasonLabel: '伙伴委派',
        routingPolicy: 'parallel',
        routingPolicyLabel: '并行协作',
        targetParticipantId: 'p-mars',
        targetDisplayName: 'Agent 2',
        waveId: 'wave-a',
        phaseName: '并行实现两条支线',
        parallelIndex: 1,
        parallelSize: 2,
        workItemId: 'runtime:mars',
        workItemState: 'active',
        candidates: [
          { participantId: 'p-earth', displayName: 'Agent 1', score: 0, signals: [], selected: false },
          { participantId: 'p-mars', displayName: 'Agent 2', score: 1, signals: ['explicit_invite'], selected: true },
        ],
      },
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
    expect(screen.getByRole('tree', { name: '任务树' })).toHaveTextContent('实现依赖数据投影');
    expect(screen.getByRole('list', { name: '行星伙伴' })).toHaveTextContent('Earth');
    expect(screen.getByLabelText('任务交接')).toHaveTextContent('Earth → Mars');
    expect(screen.getByRole('region', { name: '焦点详情' })).toHaveTextContent('等待独立复核');
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

  it('renders a selected route decision as a readable dispatch plan, not a dead label', () => {
    render(<PawRoomFocusOverview focus={focus} onOpenParticipant={vi.fn()} />);

    const ledger = screen.getByRole('region', { name: '往来记录' });
    fireEvent.click(within(ledger).getByRole('button', { name: /分派依赖投影支线/ }));
    const plan = within(ledger).getByRole('group', { name: '分派方案' });

    // Route, reason, policy and the parallel track all read as prose.
    expect(plan).toHaveTextContent('Earth');
    expect(plan).toHaveTextContent('Mars');
    expect(plan).toHaveTextContent('伙伴委派 · 并行协作');
    expect(plan).toHaveTextContent('轨道 2/2 · 并行实现两条支线');
    expect(plan).toHaveTextContent('实现依赖数据投影');

    // Candidate scoring stays reachable behind a disclosure.
    fireEvent.click(within(plan).getByText('候选 2 位 · 选中 1 位'));
    expect(plan).toHaveTextContent('explicit_invite · 1.0');
  });

  it('projects the pulse bar and the parallel wave lanes with owner and verifier planets', () => {
    const { container } = render(<PawRoomFocusOverview focus={focus} onOpenParticipant={vi.fn()} />);

    // Pulse: proportional segments plus the exact numbers (进行1 复核1 完成1).
    const pulse = screen.getByLabelText('协作摘要');
    expect(pulse.querySelectorAll('.paw-room-focus-overview__pulse-bar > i')).toHaveLength(3);
    expect(pulse).toHaveTextContent('进行');
    expect(pulse).toHaveTextContent('复核');

    const tree = screen.getByRole('tree', { name: '任务树' });
    // The real wave groups both branches under one parallel header with tracks.
    expect(within(tree).getByText('并行波次 · 并行实现两条支线')).toBeInTheDocument();
    expect(within(tree).getByText('2 道轨道同时推进')).toBeInTheDocument();
    expect(within(tree).getByText('∥ 轨道 1/2')).toBeInTheDocument();
    expect(within(tree).getByText('∥ 轨道 2/2')).toBeInTheDocument();
    // Owner planets and the dual-axis verifier chip stay text, not just color.
    expect(within(tree).getByText('负责 Earth')).toBeInTheDocument();
    expect(within(tree).getByText('负责 Mars')).toBeInTheDocument();
    expect(within(tree).getByText(/复核 Venus ✓✓/)).toBeInTheDocument();
    expect(container.querySelectorAll('[data-in-wave]')).toHaveLength(2);
  });

  it('answers the dual-axis review verdict inside the inspector', () => {
    render(<PawRoomFocusOverview focus={focus} onOpenParticipant={vi.fn()} />);

    // work-root (review state) is the default selection.
    const inspector = screen.getByRole('region', { name: '焦点详情' });
    expect(inspector).toHaveTextContent('独立复核 · Venus');
    expect(inspector).toHaveTextContent('可运行');
    expect(inspector).toHaveTextContent('通过');
    expect(inspector).toHaveTextContent('符合需求');
    expect(inspector).toHaveTextContent('满足');
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
