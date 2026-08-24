import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import { createPreviewTransport } from '@/app/preview-control-transport';
import { previewRoomSnapshot } from '@/app/preview-room-data';
import type { RoomSummary } from '@/features/rooms/room-types';
import { PawGalaxyStarfield, PawRoomStarfield, PawSessionStarfield } from './PawStarfield';
import { buildRoomFocusProjection } from './room-focus-projection';

afterEach(cleanup);

function renderSessionSky(overrides: {
  onExit?: () => void;
  onOpenRun?: (run: { id: string; state: string }) => void;
} = {}) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <ControlTransportProvider transport={createPreviewTransport()}>
        <PawSessionStarfield
          active
          busy={false}
          sessionId="session-preview"
          sessionTitle="预览 Session"
          {...overrides}
        />
      </ControlTransportProvider>
    </QueryClientProvider>,
  );
}

describe('PAWOS 星空 v2 immersive visualization', () => {
  it('renders the Session as an immersive fullscreen sky with honest per-run motion', async () => {
    renderSessionSky();

    // Immersive by default; jsdom has no WebGL so the sky reports the
    // graceful fullscreen 2D fallback while keeping every identity.
    const sky = await screen.findByRole('region', { name: 'Session 星空' });
    expect(sky).toHaveAttribute('data-immersive');
    expect(sky).toHaveAttribute('data-render', '2d');
    expect(within(sky).getByText('预览 Session')).toBeInTheDocument();

    // Real preview run graph: one running researcher, one completed reviewer.
    const runningMoon = await within(sky).findByRole('button', { name: /研究员 卫星 .*进行中/ });
    const doneMoon = within(sky).getByRole('button', { name: /审阅者 卫星 .*已完成/ });

    // Motion is evidence: only the genuinely running moon's orbiter revolves.
    expect(runningMoon.closest('.paw-sf2__orbiter')).toHaveAttribute('data-working');
    expect(doneMoon.closest('.paw-sf2__orbiter')).not.toHaveAttribute('data-working');

    // Legend counts stay projections of the same real runs.
    const legend = within(sky).getByRole('contentinfo', { name: '星空图例' });
    expect(legend).toHaveTextContent('运行 1');
    expect(legend).toHaveTextContent('返回 1');
    expect(legend).toHaveTextContent('转动 = 正在工作');

    // The information feed lists who is doing what from the same records.
    const feed = within(sky).getByRole('complementary', { name: '星空信息流' });
    expect(feed).toHaveTextContent('检索 Agent 状态投影和知识来源证据');
    expect(feed).toHaveTextContent('审阅前端交互与工具生命周期边界');
  });

  it('opens a detail card on pick and only then jumps into the run', async () => {
    const onOpenRun = vi.fn();
    renderSessionSky({ onOpenRun });

    const sky = await screen.findByRole('region', { name: 'Session 星空' });
    const runningMoon = await within(sky).findByRole('button', { name: /研究员 卫星 .*进行中/ });
    await userEvent.setup().click(runningMoon);

    const card = within(sky).getByRole('complementary', { name: '天体详情' });
    expect(card).toHaveTextContent('研究员');
    expect(card).toHaveTextContent('检索 Agent 状态投影和知识来源证据');
    expect(card).toHaveTextContent('独立上下文');
    expect(onOpenRun).not.toHaveBeenCalled();

    await userEvent.setup().click(within(card).getByRole('button', { name: '打开运行详情' }));
    expect(onOpenRun).toHaveBeenCalledTimes(1);
    expect(onOpenRun.mock.calls[0]?.[0]).toMatchObject({
      id: 'subagent-run:research',
      state: 'running',
    });
  });

  it('leaves the immersive sky through the exit control and Esc — card first, sky second', async () => {
    const onExit = vi.fn();
    renderSessionSky({ onExit });
    const user = userEvent.setup();

    const sky = await screen.findByRole('region', { name: 'Session 星空' });
    const exit = within(sky).getByRole('button', { name: /返回对话/ });

    // Esc with an open detail card closes the card, not the sky.
    await user.click(await within(sky).findByRole('button', { name: /研究员 卫星/ }));
    expect(within(sky).getByRole('complementary', { name: '天体详情' })).toBeInTheDocument();
    await user.keyboard('{Escape}');
    expect(within(sky).queryByRole('complementary', { name: '天体详情' })).not.toBeInTheDocument();
    expect(onExit).not.toHaveBeenCalled();

    await user.keyboard('{Escape}');
    expect(onExit).toHaveBeenCalledTimes(1);

    await user.click(exit);
    expect(onExit).toHaveBeenCalledTimes(2);
  });

  it('turns the Room focus projection into a solar system with a partner detail flow', async () => {
    const onOpenParticipant = vi.fn();
    const room = previewRoomSnapshot('room-preview').room as unknown as RoomSummary;
    const focus = buildRoomFocusProjection(room);
    render(
      <PawRoomStarfield focus={focus} roomId={room.id} onOpenParticipant={onOpenParticipant} />,
    );

    const sky = screen.getByRole('region', { name: 'Room 星空' });
    expect(sky).toHaveAttribute('data-immersive');
    expect(within(sky).getByText('Sol')).toBeInTheDocument();
    for (const partner of focus.partners) {
      expect(within(sky).getByRole('button', { name: new RegExp(`^${partner.celestialName}，`) })).toBeInTheDocument();
    }

    const mars = focus.partners[1]!;
    await userEvent.setup().click(within(sky).getByRole('button', { name: new RegExp(`^${mars.celestialName}，`) }));
    const card = within(sky).getByRole('complementary', { name: '天体详情' });
    expect(card).toHaveTextContent(mars.celestialName);
    expect(onOpenParticipant).not.toHaveBeenCalled();

    await userEvent.setup().click(within(card).getByRole('button', { name: '打开伙伴窗口' }));
    expect(onOpenParticipant).toHaveBeenCalledWith(mars.participantId);
  });

  it('renders every Room as a star system inline and expands to a fullscreen galaxy', async () => {
    const onOpenRoom = vi.fn();
    const room = (id: string, status: string, updatedAtMs: number): RoomSummary => ({
      id,
      title: `Room ${id}`,
      status,
      routingPolicy: 'parallel',
      moderatorParticipantId: '',
      updatedAtMs,
      participants: [
        { id: `${id}-p0`, sessionId: `${id}-s0`, roleId: 'role', roleVersion: '1', displayName: '伙伴 0', status: 'active', ordinal: 0 },
        { id: `${id}-p1`, sessionId: `${id}-s1`, roleId: 'role', roleVersion: '1', displayName: '伙伴 1', status: 'active', ordinal: 1 },
      ],
    });
    render(
      <PawGalaxyStarfield
        rooms={[room('alpha', 'active', 2_000), room('beta', 'archived', 1_000)]}
        onOpenRoom={onOpenRoom}
      />,
    );
    const user = userEvent.setup();

    // Inline on the home surface, with an explicit way into full immersion.
    const galaxy = screen.getByRole('region', { name: 'Room 星系' });
    expect(galaxy).not.toHaveAttribute('data-immersive');
    expect(within(galaxy).getByRole('button', { name: /Room alpha .*活跃/ })).toBeInTheDocument();
    expect(within(galaxy).getByRole('button', { name: /Room beta .*已归档/ })).toBeInTheDocument();
    expect(within(galaxy).getByRole('contentinfo', { name: '星系图例' })).toHaveTextContent('共 2 个 Room');

    // Pick a star → detail card → enter the real Room.
    await user.click(within(galaxy).getByRole('button', { name: /Room beta/ }));
    const card = within(galaxy).getByRole('complementary', { name: '天体详情' });
    expect(card).toHaveTextContent('已归档');
    await user.click(within(card).getByRole('button', { name: '进入 Room' }));
    expect(onOpenRoom).toHaveBeenCalledWith('beta');

    // Fullscreen expansion and the way back.
    await user.click(within(galaxy).getByRole('button', { name: '全屏星空' }));
    expect(screen.getByRole('region', { name: 'Room 星系' })).toHaveAttribute('data-immersive');
    await user.click(screen.getByRole('button', { name: /返回工作台/ }));
    expect(screen.getByRole('region', { name: 'Room 星系' })).not.toHaveAttribute('data-immersive');
  });
});
