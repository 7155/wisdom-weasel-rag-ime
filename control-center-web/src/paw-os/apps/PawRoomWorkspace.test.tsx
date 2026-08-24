import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ControlTransportProvider } from '@/app/control-transport';
import { createPreviewTransport } from '@/app/preview-control-transport';
import { previewRoomSnapshot } from '@/app/preview-room-data';
import { TooltipProvider } from '@/components/primitives';
import { PawOsDesktopProvider } from '@/features/paw-os/surface-context';
import type { RoomSummary } from '@/features/rooms/room-types';
import { PawWindowFrame } from '../shell/PawWindowLayer';
import { PawRoomWorkspace } from './PawRoomWorkspace';

afterEach(cleanup);

describe('PAWOS Room collaboration tools', () => {
  it('opens one purpose-built Sol collaboration view instead of four duplicate summaries', async () => {
    const user = userEvent.setup();
    const openWindow = vi.fn();
    const { container } = renderRoom(900, openWindow);
    await screen.findByRole('textbox', { name: '协作消息' });

    const primaryNavigation = screen.getByRole('navigation', { name: 'Room 工作台视图' });
    expect(within(primaryNavigation).getAllByRole('button')).toHaveLength(2);
    expect(within(primaryNavigation).getByRole('button', { name: '公开对话' })).toHaveAttribute('aria-pressed', 'false');
    expect(within(primaryNavigation).getByRole('button', { name: '协作态势' })).toHaveAttribute('aria-pressed', 'true');
    expect(container.querySelector('.paw-room-workspace')).toHaveAttribute('data-panel', 'focus');

    const tools = screen.getByRole('complementary', { name: 'Room 协作态势' });
    expect(within(tools).getAllByRole('tab')).toHaveLength(2);
    expect(within(tools).getByRole('tab', { name: '态势' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('region', { name: 'Room 当前协作' })).toHaveTextContent('任务图依赖验证');
    expect(within(tools).getByRole('tree', { name: 'WorkItem 任务流' })).toHaveTextContent('实现 Room 依赖数据投影');
    const userMessage = screen.getByText('并行实现 Room 任务图与依赖数据，整合后交给独立伙伴复核。').closest('article');
    expect(userMessage).not.toBeNull();
    expect(within(userMessage!).queryByText('你')).not.toBeInTheDocument();
    const earthMessage = screen.getByText('我已把实时进展收拢在同一条消息里；完成后会在原处留下清晰结果。').closest('article');
    expect(within(earthMessage!).getByText('Earth')).toBeInTheDocument();
    expect(openWindow).not.toHaveBeenCalled();

    await user.click(within(tools).getByRole('button', { name: '关闭协作态势' }));

    expect(screen.getByRole('main', { name: /主 Room/ })).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: '协作消息' })).toBeInTheDocument();
    expect(screen.queryByRole('complementary', { name: 'Room 协作态势' })).not.toBeInTheDocument();
    expect(container.querySelector('.paw-room-workspace')).toHaveAttribute('data-panel', 'none');
  });

  it('opens only the selected real planet participant and never铺开 every partner', async () => {
    const user = userEvent.setup();
    const openWindow = vi.fn();
    renderRoom(900, openWindow);
    await screen.findByRole('textbox', { name: '协作消息' });

    const tools = screen.getByRole('complementary', { name: 'Room 协作态势' });
    const partners = within(tools).getByRole('list', { name: '行星伙伴' });
    await user.click(within(partners).getByRole('button', { name: /Mars/ }));
    await user.click(within(tools).getByRole('button', { name: '打开 Mars 伙伴窗口' }));

    expect(screen.queryByRole('button', { name: /铺开 .* 位/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('complementary', { name: 'Room 协作态势' })).not.toBeInTheDocument();
    expect(openWindow).toHaveBeenCalledTimes(1);
    expect(openWindow).toHaveBeenCalledWith(expect.objectContaining({
      target: expect.objectContaining({
        id: 'participant-firstlight',
        title: 'Mars',
        subtitle: expect.stringContaining('Agent 2'),
      }),
    }));
  });
});

function renderRoom(width: number, openWindow = vi.fn()) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const room = previewRoomSnapshot('room-preview').room as unknown as RoomSummary;
  return {
    ...render(
      <QueryClientProvider client={queryClient}>
        <ControlTransportProvider transport={createPreviewTransport()}>
          <PawOsDesktopProvider openWindow={openWindow}>
            <TooltipProvider>
              <PawWindowFrame
                active
                appId="agent"
                bounds={{ x: 0, y: 0, width, height: 720 }}
                onBoundsCommit={() => undefined}
                onClose={() => undefined}
                onFocus={() => undefined}
                onMinimize={() => undefined}
                onToggleMaximize={() => undefined}
                title={`Room ${width}`}
                windowChrome="agent-room"
                windowId={`room-${width}`}
                zIndex={10}
              >
                <PawRoomWorkspace
                  personas={[]}
                  record={room}
                  recordId={room.id}
                  onRoomUpdated={vi.fn()}
                />
              </PawWindowFrame>
            </TooltipProvider>
          </PawOsDesktopProvider>
        </ControlTransportProvider>
      </QueryClientProvider>,
    ),
    room,
  };
}
