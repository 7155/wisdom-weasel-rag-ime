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

describe('PAWOS 星空 visualization', () => {
  it('shows the Session as one planet with its real subagent runs as clickable moons', async () => {
    const onOpenRun = vi.fn();
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <ControlTransportProvider transport={createPreviewTransport()}>
          <PawSessionStarfield
            active
            busy={false}
            sessionId="session-preview"
            sessionTitle="预览 Session"
            onOpenRun={onOpenRun}
          />
        </ControlTransportProvider>
      </QueryClientProvider>,
    );

    const sky = screen.getByRole('region', { name: 'Session 星空' });
    expect(within(sky).getByText('预览 Session')).toBeInTheDocument();

    // Real preview run graph: one running researcher, one completed reviewer.
    const runningMoon = await within(sky).findByRole('button', { name: /研究员 卫星 .*进行中/ });
    expect(within(sky).getByRole('button', { name: /审阅者 卫星 .*已完成/ })).toBeInTheDocument();

    await userEvent.setup().click(runningMoon);
    expect(onOpenRun).toHaveBeenCalledTimes(1);
    expect(onOpenRun.mock.calls[0]?.[0]).toMatchObject({
      id: 'subagent-run:research',
      state: 'running',
    });

    // Legend counts stay projections of the same real runs.
    const legend = within(sky).getByLabelText('星空图例');
    expect(legend).toHaveTextContent('运行 1');
    expect(legend).toHaveTextContent('返回 1');
  });

  it('turns the Room focus projection into a solar system whose planets keep real identities', async () => {
    const onOpenParticipant = vi.fn();
    const room = previewRoomSnapshot('room-preview').room as unknown as RoomSummary;
    const focus = buildRoomFocusProjection(room);
    render(
      <PawRoomStarfield focus={focus} roomId={room.id} onOpenParticipant={onOpenParticipant} />,
    );

    const sky = screen.getByRole('region', { name: 'Room 星空' });
    expect(within(sky).getByText('Sol')).toBeInTheDocument();
    for (const partner of focus.partners) {
      expect(within(sky).getByRole('button', { name: new RegExp(`^${partner.celestialName}，`) })).toBeInTheDocument();
    }

    const mars = focus.partners[1]!;
    await userEvent.setup().click(within(sky).getByRole('button', { name: new RegExp(`^${mars.celestialName}，`) }));
    expect(onOpenParticipant).toHaveBeenCalledWith(mars.participantId);
  });

  it('renders every Room as a star system and opens the clicked Room', async () => {
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

    const galaxy = screen.getByRole('region', { name: 'Room 星系' });
    expect(within(galaxy).getByRole('button', { name: /Room alpha .*活跃/ })).toBeInTheDocument();
    expect(within(galaxy).getByRole('button', { name: /Room beta .*已归档/ })).toBeInTheDocument();
    expect(within(galaxy).getByLabelText('星系图例')).toHaveTextContent('共 2 个 Room');

    await userEvent.setup().click(within(galaxy).getByRole('button', { name: /Room beta/ }));
    expect(onOpenRoom).toHaveBeenCalledWith('beta');
  });
});
