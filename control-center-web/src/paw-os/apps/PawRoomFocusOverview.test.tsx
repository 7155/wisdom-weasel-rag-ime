import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
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
      collaborationRole: 'coordinator',
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
  it('answers partner responsibility, state and handoff without drawing Sol or tasks as partners', () => {
    const { container } = render(<PawRoomFocusOverview focus={focus} onOpenParticipant={vi.fn()} />);

    expect(screen.getByRole('region', { name: 'Sol 协作态势' })).toHaveTextContent('任务图依赖验证');
    const mesh = screen.getByRole('group', { name: '协作网状图' });
    expect(within(mesh).getByRole('button', { name: 'Earth，职责：实现任务图交互，已完成' })).toBeInTheDocument();
    expect(within(mesh).getByRole('button', { name: 'Mars，职责：实现依赖数据投影，进行中' })).toBeInTheDocument();
    expect(within(mesh).queryByRole('img', { name: /^Sol，/ })).not.toBeInTheDocument();
    expect(mesh.querySelector('.paw-room-focus-overview__mesh-node--work')).toBeNull();
    const relations = within(mesh).getByRole('list', { name: '协作关系' });
    expect(relations.querySelector('li[data-kind="handoff"][data-state="dispatched"]')).not.toBeNull();
    expect(relations).toHaveTextContent('Earth');
    expect(relations).toHaveTextContent('Mars');
    expect(mesh.querySelector(':scope > svg, .paw-room-focus-overview__mesh-edge-label')).toBeNull();
    expect(screen.getByRole('region', { name: '焦点详情' })).toHaveTextContent('等待独立复核');
    expect(screen.queryByText(/Agent [123]/)).not.toBeInTheDocument();
  });

  it('keeps planet responsibility labels aligned on the stable partner grid', () => {
    render(<PawRoomFocusOverview focus={focus} onOpenParticipant={vi.fn()} />);
    const mesh = screen.getByRole('group', { name: '协作网状图' });
    const partners = within(mesh).getByRole('list', { name: '行星伙伴' });
    const planets = within(partners).getAllByRole('button');
    expect(planets).toHaveLength(3);
    expect(within(partners).getAllByRole('listitem')).toHaveLength(3);
    for (const planet of planets) expect(planet).not.toHaveAttribute('style');
    expect(within(mesh).getByText('实现任务图交互')).toBeInTheDocument();
    expect(within(mesh).getByText('实现依赖数据投影')).toBeInTheDocument();
    expect(within(mesh).getByText('整合 Room 任务图')).toBeInTheDocument();
    expect(document.querySelector('.paw-room-focus-overview__mesh-timespan')).toBeNull();
  });

  it('selects a planet with pointer or keyboard and opens only its real participant target', async () => {
    const user = userEvent.setup();
    const onOpenParticipant = vi.fn();
    render(<PawRoomFocusOverview focus={focus} onOpenParticipant={onOpenParticipant} />);
    const mesh = screen.getByRole('group', { name: '协作网状图' });

    await user.click(within(mesh).getByRole('button', { name: /^Mars，/ }));
    expect(screen.getByRole('region', { name: '焦点详情' })).toHaveTextContent('正在核对依赖投影');
    within(mesh).getByRole('button', { name: /^Earth，/ }).focus();
    await user.keyboard('{Enter}');
    await user.click(screen.getByRole('button', { name: '打开 Earth 伙伴窗口' }));

    expect(onOpenParticipant).toHaveBeenCalledWith('p-earth');
  });

  it('keeps WorkItem detail in the inspector without drawing a WorkItem node', () => {
    render(<PawRoomFocusOverview focus={focus} onOpenParticipant={vi.fn()} />);
    const mesh = screen.getByRole('group', { name: '协作网状图' });
    expect(within(mesh).queryByRole('button', { name: '实现任务图交互，已完成' })).not.toBeInTheDocument();
    expect(screen.getByRole('region', { name: '焦点详情' })).toHaveTextContent('两个实现分支已汇合');
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

  it('projects the pulse meter and partner-only dependency and handoff relations', () => {
    const { container } = render(<PawRoomFocusOverview focus={focus} onOpenParticipant={vi.fn()} />);

    // Pulse: proportional segments plus the exact numbers (进行1 复核1 完成1).
    const pulse = screen.getByLabelText('协作摘要');
    expect(pulse.querySelectorAll('.paw-room-focus-overview__pulse-bar > i')).toHaveLength(3);
    expect(pulse).toHaveTextContent('进行');
    expect(pulse).toHaveTextContent('复核');

    const mesh = screen.getByRole('group', { name: '协作网状图' });
    expect(within(mesh).getByText('实现任务图交互')).toBeInTheDocument();
    expect(within(mesh).getByText('实现依赖数据投影')).toBeInTheDocument();
    const relations = within(mesh).getByRole('list', { name: '协作关系' });
    expect(relations.querySelectorAll('li[data-kind="dependency"]')).toHaveLength(2);
    expect(relations.querySelectorAll('li[data-kind="handoff"]')).toHaveLength(1);
    expect(relations.querySelectorAll('li[data-kind="review"]')).toHaveLength(0);
    expect(container.querySelector('.paw-room-focus-overview__mesh-node--work')).toBeNull();
    expect(relations).toHaveTextContent('任务依赖');
    expect(relations).toHaveTextContent('交接');
    expect(screen.queryByRole('list', { name: '关系图例' })).not.toBeInTheDocument();
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

  it('draws no Sol anywhere until a partner really hosts the Room', () => {
    /* Venus is the only coordinator in the fixture; demote her and the whole
       console has to stop naming an origin nobody sits at. */
    const unhosted = {
      ...focus,
      partners: focus.partners.map((partner) => partner.collaborationRole === 'coordinator'
        ? { ...partner, collaborationRole: 'reviewer' as const }
        : partner),
    };
    const { container } = render(<PawRoomFocusOverview focus={unhosted} onOpenParticipant={vi.fn()} />);

    // No mission header, no Sol centre body, no origin lifeline.
    expect(container.querySelector('.paw-room-focus-overview__mission--dormant')).not.toBeNull();
    expect(container.querySelector('.paw-room-focus-overview__sol')).toBeNull();
    expect(screen.queryByRole('img', { name: /^Sol，/ })).not.toBeInTheDocument();
    expect(container.querySelector('.paw-room-focus-overview')).not.toHaveAttribute('data-coordinator');
    // The ledger still has to name where a root packet came from — as the
    // shared main Room, not as a star that has not risen.
    const packets = within(screen.getByRole('region', { name: '往来记录' })).getByRole('list', { name: '往来事件' });
    expect(packets).toHaveTextContent('主 Room → Earth');
    expect(packets).not.toHaveTextContent('Sol → Earth');
  });

  it('lights the Sol mission the moment a connected coordinator takes the chair', () => {
    const { container } = render(<PawRoomFocusOverview focus={focus} onOpenParticipant={vi.fn()} />);

    expect(container.querySelector('.paw-room-focus-overview')).toHaveAttribute('data-coordinator', 'true');
    expect(container.querySelector('.paw-room-focus-overview__mission--dormant')).toBeNull();
    expect(container.querySelector('.paw-room-focus-overview__sol')).not.toBeNull();
    expect(within(screen.getByRole('group', { name: '协作网状图' })).queryByRole('img', { name: /^Sol，/ })).not.toBeInTheDocument();
  });

  it('drops Sol again when the only coordinator disconnects', () => {
    const dropped = {
      ...focus,
      partners: focus.partners.map((partner) => partner.collaborationRole === 'coordinator'
        ? { ...partner, state: 'disconnected' as const }
        : partner),
    };
    render(<PawRoomFocusOverview focus={dropped} onOpenParticipant={vi.fn()} />);

    expect(screen.queryByRole('img', { name: /^Sol，/ })).not.toBeInTheDocument();
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
