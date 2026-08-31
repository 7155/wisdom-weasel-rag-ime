import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import { createPreviewTransport } from '@/app/preview-control-transport';
import { previewRoomSnapshot } from '@/app/preview-room-data';
import type { RoomSummary } from '@/features/rooms/room-types';
import { PawGalaxyStarfield, PawRoomStarfield, PawSessionStarfield } from './PawStarfield';
import { LazyPawRoomStarfield } from './PawStarfieldLazy';
import { buildRoomFocusProjection } from './room-focus-projection';
import roomWorkspaceSource from './PawRoomWorkspace.tsx?raw';
import sessionWorkspaceSource from './PawSessionWorkspace.tsx?raw';
import starfieldLazySource from './PawStarfieldLazy.tsx?raw';

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

describe('星空 lazy bundle boundary', () => {
  it('keeps PawStarfield out of the default Agent home / Room bundle path', () => {
    // A static value import would pull the whole sky (scene model, feed,
    // texture factory) back into the conversation chunk. Only the erased
    // `import type` and the boundary's dynamic import may name the module.
    const staticValueImport = /import\s+(?!type\b)[^;]*?from\s+'\.\/PawStarfield'/u;
    expect(roomWorkspaceSource).not.toMatch(staticValueImport);
    expect(sessionWorkspaceSource).not.toMatch(staticValueImport);
    expect(roomWorkspaceSource).toContain("from './PawStarfieldLazy'");
    expect(sessionWorkspaceSource).toContain("from './PawStarfieldLazy'");
    expect(starfieldLazySource).not.toMatch(staticValueImport);
    expect(starfieldLazySource).toMatch(/lazy\(/u);
    expect(starfieldLazySource).toMatch(/await import\('\.\/PawStarfield'\)/u);
  });

  it('mounts the Room sky through the lazy boundary once the chunk resolves', async () => {
    const room = previewRoomSnapshot('room-preview').room as unknown as RoomSummary;
    const focus = buildRoomFocusProjection(room);
    render(<LazyPawRoomStarfield focus={focus} roomId={room.id} />);

    const sky = await screen.findByRole('region', { name: 'Room 星空' });
    expect(sky).toHaveAttribute('data-immersive');
    expect(within(sky).getByText('Sol')).toBeInTheDocument();
  });
});

describe('PAWOS 星空 v2 immersive visualization', () => {
  it('unmounts the immersive Room portal while its owning window is inactive', () => {
    const room = previewRoomSnapshot('room-inactive').room as unknown as RoomSummary;
    const focus = buildRoomFocusProjection(room);
    const setInterval = vi.spyOn(window, 'setInterval');

    try {
      render(<PawRoomStarfield active={false} focus={focus} roomId={room.id} />);

      expect(screen.queryByRole('region', { name: 'Room 星空' })).not.toBeInTheDocument();
      expect(setInterval).not.toHaveBeenCalledWith(expect.any(Function), 30_000);
    } finally {
      setInterval.mockRestore();
    }
  });

  it('renders the Session as an immersive fullscreen sky with honest per-run motion', async () => {
    renderSessionSky();

    // Immersive by default; jsdom has no WebGL so the sky reports the
    // graceful fullscreen 2D fallback while keeping every identity.
    const sky = await screen.findByRole('region', { name: 'Session 星空' });
    expect(sky).toHaveAttribute('data-immersive');
    expect(sky).toHaveAttribute('data-render', '2d');
    expect(within(sky).getByText('预览 Session')).toBeInTheDocument();
    // Without WebGL the 3D/2D toggle is not offered — the fallback is honest.
    expect(within(sky).queryByRole('button', { name: /切换为/ })).not.toBeInTheDocument();

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

    // Presence layer: seeded shooting-star streaks exist as decoration only
    // (aria-hidden), and CSS stills them under reduced motion.
    expect(sky.querySelectorAll('.paw-sf2__meteor')).toHaveLength(3);
    expect(sky.querySelector('.paw-sf2__meteors')).toHaveAttribute('aria-hidden', 'true');
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

  it('paints a cooler deterministic backdrop — tinted stars, meteors and an aurora', () => {
    const room = previewRoomSnapshot('room-preview').room as unknown as RoomSummary;
    const focus = buildRoomFocusProjection(room);
    const first = render(<PawRoomStarfield focus={focus} roomId={room.id} />);
    const sky = screen.getByRole('region', { name: 'Room 星空' });

    // Shooting stars and the aurora veil are aria-hidden decoration only.
    const meteors = [...sky.querySelectorAll<HTMLElement>('.paw-sf2__meteor')];
    expect(meteors).toHaveLength(3);
    for (const meteor of meteors) {
      expect(meteor.closest('[aria-hidden="true"]')).not.toBeNull();
    }
    expect(sky.querySelector('.paw-sf2__aurora')).not.toBeNull();
    expect(sky.querySelector('.paw-sf2__aurora')?.getAttribute('aria-hidden')).toBe('true');

    // The star scatter is no longer monochrome: seeded tints vary per star.
    const fills = new Set(
      [...sky.querySelectorAll<SVGCircleElement>('.paw-sf2__star-layer circle')]
        .map((circle) => circle.style.fill),
    );
    expect(fills.size).toBeGreaterThan(1);

    // Determinism: the same seed always deals the same meteor schedule.
    const schedule = meteors.map((meteor) => [
      meteor.style.getPropertyValue('--sf-meteor-x'),
      meteor.style.getPropertyValue('--sf-meteor-y'),
      meteor.style.getPropertyValue('--sf-meteor-delay'),
      meteor.style.getPropertyValue('--sf-meteor-duration'),
    ].join('@'));
    first.unmount();
    render(<PawRoomStarfield focus={focus} roomId={room.id} />);
    const replay = [
      ...screen.getByRole('region', { name: 'Room 星空' }).querySelectorAll<HTMLElement>('.paw-sf2__meteor'),
    ].map((meteor) => [
      meteor.style.getPropertyValue('--sf-meteor-x'),
      meteor.style.getPropertyValue('--sf-meteor-y'),
      meteor.style.getPropertyValue('--sf-meteor-delay'),
      meteor.style.getPropertyValue('--sf-meteor-duration'),
    ].join('@'));
    expect(replay).toEqual(schedule);
  });

  it('releases only the system fullscreen it owns when the sky exits', async () => {
    const requestFullscreen = vi.fn().mockResolvedValue(undefined);
    const exitFullscreen = vi.fn().mockResolvedValue(undefined);
    let fullscreenElement: Element | null = null;
    Object.defineProperty(HTMLElement.prototype, 'requestFullscreen', {
      configurable: true,
      value: requestFullscreen,
    });
    Object.defineProperty(document, 'exitFullscreen', { configurable: true, value: exitFullscreen });
    Object.defineProperty(document, 'fullscreenElement', {
      configurable: true,
      get: () => fullscreenElement,
    });
    try {
      const room = previewRoomSnapshot('room-preview').room as unknown as RoomSummary;
      const focus = buildRoomFocusProjection(room);
      const view = render(<PawRoomStarfield focus={focus} roomId={room.id} />);
      const sky = screen.getByRole('region', { name: 'Room 星空' });

      // The shell acquires system fullscreen on its own root element.
      await userEvent.setup().click(screen.getByRole('button', { name: '进入系统全屏' }));
      expect(requestFullscreen).toHaveBeenCalledTimes(1);
      fullscreenElement = sky;
      fireEvent(document, new Event('fullscreenchange'));

      // Dispose on exit: unmounting releases the fullscreen the sky took.
      view.unmount();
      expect(exitFullscreen).toHaveBeenCalledTimes(1);

      // A sky that never owned fullscreen leaves a foreign fullscreen alone.
      fullscreenElement = document.createElement('div');
      const second = render(<PawRoomStarfield focus={focus} roomId={room.id} />);
      fireEvent(document, new Event('fullscreenchange'));
      second.unmount();
      expect(exitFullscreen).toHaveBeenCalledTimes(1);
    } finally {
      delete (HTMLElement.prototype as { requestFullscreen?: unknown }).requestFullscreen;
      delete (document as { exitFullscreen?: unknown }).exitFullscreen;
      delete (document as { fullscreenElement?: unknown }).fullscreenElement;
    }
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

  it('foregrounds the real work: task lines on working planets, quiet idle ones', async () => {
    const room = previewRoomSnapshot('room-preview').room as unknown as RoomSummary;
    const focus = buildRoomFocusProjection(room);
    render(<PawRoomStarfield focus={focus} roomId={room.id} />);
    const sky = screen.getByRole('region', { name: 'Room 星空' });

    // Every partner planet says what it is working on, from the real
    // projection — the task is part of the accessible name, not decoration.
    const owner = focus.partners.find((partner) => partner.state !== 'idle')!;
    expect(within(sky).getByRole('button', {
      name: new RegExp(`^${owner.celestialName}，.*，${owner.currentAction}$`),
    })).toBeInTheDocument();
    expect(within(sky).getAllByText(owner.currentAction).length).toBeGreaterThan(0);

    // Partners with nothing live keep their identity but stop competing:
    // the preview Room's third partner owns no WorkItem at all.
    const idle = focus.partners.find((partner) => partner.state === 'idle')!;
    const quiet = within(sky).getByRole('button', { name: new RegExp(`^${idle.celestialName}，`) });
    expect(quiet).toHaveAttribute('data-idle');
    expect(within(quiet).queryByText(idle.currentAction)).toBeNull();

    // The feed leads with the shared objective before any partner row.
    const feed = within(sky).getByRole('complementary', { name: '星空信息流' });
    const rows = within(feed).getAllByRole('listitem');
    expect(rows[0]).toHaveTextContent(`Sol · ${focus.goal.title}`);

    // Picking a planet names the WorkItems it actually owns.
    const withWork = focus.partners.find((partner) => partner.ownedWorkItemIds.length)!;
    await userEvent.setup().click(
      within(sky).getByRole('button', { name: new RegExp(`^${withWork.celestialName}，`) }),
    );
    const work = within(sky).getByRole('list', { name: '负责的工作项' });
    const objective = focus.workItems.find((item) => item.id === withWork.ownedWorkItemIds[0])!;
    expect(work).toHaveTextContent(objective.objective);
  });

  it('keeps Sol dark when no facilitator hosts the Room', () => {
    const snapshot = previewRoomSnapshot('room-unhosted');
    const room = snapshot.room as unknown as RoomSummary;
    // Same real Room, only the hosting role removed: nobody coordinates.
    const unhosted: RoomSummary = {
      ...room,
      participants: room.participants.map((participant) => ({
        ...participant,
        collaborationRole: 'implementer' as const,
      })),
    };
    const focus = buildRoomFocusProjection(unhosted);
    render(<PawRoomStarfield focus={focus} roomId={unhosted.id} />);
    const sky = screen.getByRole('region', { name: 'Room 星空' });

    // No Sol body, and the sky says why instead of faking a center.
    expect(within(sky).queryByText('Sol')).toBeNull();
    expect(sky.querySelector('.paw-sf2__center')).toBeNull();
    expect(sky).toHaveTextContent('这间 Room 没有主持人');

    // Partner-only constellation: every real planet and orbit still stands.
    for (const partner of focus.partners) {
      expect(within(sky).getByRole('button', { name: new RegExp(`^${partner.celestialName}，`) })).toBeInTheDocument();
    }
    expect(sky.querySelectorAll('.paw-sf2__ring').length).toBe(focus.partners.length);

    // The feed keeps the objective but stops pointing at a star that is gone.
    const feed = within(sky).getByRole('complementary', { name: '星空信息流' });
    expect(feed).toHaveTextContent(focus.goal.title);
    expect(feed).not.toHaveTextContent('Sol ·');
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
