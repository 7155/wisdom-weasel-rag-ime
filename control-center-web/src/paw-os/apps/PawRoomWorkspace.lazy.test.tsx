/**
 * Lazy-mount proof for the Room 星空.
 *
 * The starfield module must never be evaluated on the Room's default
 * conversation view (or any non-星空 panel): it loads only after the user
 * explicitly clicks 星空, and exiting the sky unmounts it again — which is
 * what lets the 3D stage dispose its WebGL resources.
 *
 * The probe below piggybacks on module evaluation order: the vi.mock factory
 * for './PawStarfield' only runs when something actually imports the module,
 * so `evaluated` flips exactly when the lazy chunk would load in production.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import { createPreviewTransport } from '@/app/preview-control-transport';
import { previewRoomSnapshot } from '@/app/preview-room-data';
import { TooltipProvider } from '@/components/primitives';
import type { RoomSummary } from '@/features/rooms/room-types';
import { PawRoomWorkspace } from './PawRoomWorkspace';

const starfieldModule = vi.hoisted(() => ({ evaluated: false }));

vi.mock('./PawStarfield', async (importOriginal) => {
  starfieldModule.evaluated = true;
  return importOriginal();
});

afterEach(cleanup);

function renderRoom() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const room = previewRoomSnapshot('room-preview').room as unknown as RoomSummary;
  render(
    <QueryClientProvider client={queryClient}>
      <ControlTransportProvider transport={createPreviewTransport()}>
        <TooltipProvider>
          <PawRoomWorkspace personas={[]} record={room} recordId={room.id} onRoomUpdated={vi.fn()} />
        </TooltipProvider>
      </ControlTransportProvider>
    </QueryClientProvider>,
  );
}

describe('PAWOS Room 星空 lazy mount', () => {
  it('never evaluates the starfield module on the default conversation view', async () => {
    renderRoom();
    await screen.findByRole('textbox', { name: '协作消息' });

    // The Room opens on the conversation; the sky module stays unloaded.
    expect(starfieldModule.evaluated).toBe(false);
    expect(screen.queryByRole('region', { name: 'Room 星空' })).not.toBeInTheDocument();

    // Switching between the non-sky views still never touches the module.
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: '协作态势' }));
    await user.click(screen.getByRole('button', { name: '公开对话' }));
    expect(starfieldModule.evaluated).toBe(false);
  });

  it('loads the starfield only after the 星空 click and unmounts it on exit', async () => {
    renderRoom();
    await screen.findByRole('textbox', { name: '协作消息' });
    const user = userEvent.setup();
    expect(starfieldModule.evaluated).toBe(false);

    await user.click(screen.getByRole('button', { name: '星空' }));
    const sky = await screen.findByRole('region', { name: 'Room 星空' });
    expect(starfieldModule.evaluated).toBe(true);
    expect(sky).toHaveAttribute('data-immersive');

    // Exit unmounts the sky entirely, so the 3D stage disposes with it.
    await user.click(within(sky).getByRole('button', { name: /返回 Room/ }));
    expect(screen.queryByRole('region', { name: 'Room 星空' })).not.toBeInTheDocument();
  });
});
