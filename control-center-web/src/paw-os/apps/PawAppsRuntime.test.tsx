import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import { PawOsAppearanceProvider } from '@/design/paw-os-themes';
import { MockControlTransport } from '@/test/mock-transport';
import { PawAppBody } from './PawAppsRuntime';

vi.mock('./PawBrowserApp', () => ({
  PawBrowserApp: () => <main>PAW 直连 Browser</main>,
}));

vi.mock('./PawAgentApp', () => ({
  PawAgentApp: ({ target }: { target?: { kind?: string; id?: string } }) => (
    <main data-testid="agent-app">{target ? `${target.kind}:${target.id}` : 'agent-home'}</main>
  ),
}));

vi.mock('@/features/paw-os/PawOsSatelliteHost', () => ({
  PawOsSatelliteHost: ({ target }: { target: { kind: string; panel?: string } }) => (
    <aside data-testid="satellite-host">{`${target.kind}:${target.panel ?? 'none'}`}</aside>
  ),
}));

describe('PAWOS App runtime', () => {
  it('mounts the direct PAW Browser surface', async () => {
    render(<PawAppBody appId="browser" />);

    expect(await screen.findByText('PAW 直连 Browser')).toBeInTheDocument();
  });

  it('mounts an isolated Agent result window for authored HTML', async () => {
    render(
      <PawAppBody
        appId="agent"
        target={{
          kind: 'result',
          id: 'result-42',
          title: '音乐律动预览',
          resultKind: 'html',
          content: '<main><h2>Composition 8</h2></main>',
        }}
      />,
    );

    expect(await screen.findByRole('heading', { name: '音乐律动预览' })).toBeInTheDocument();
    expect(screen.getByTitle('音乐律动预览')).toHaveAttribute('sandbox', expect.stringContaining('allow-scripts'));
  });

  it('keeps the Room conversation in Agent while routing only named Room panels to satellites', async () => {
    const { rerender } = render(
      <PawAppBody
        appId="agent"
        target={{ kind: 'room', id: 'room-42', title: '产品协作室' }}
      />,
    );

    expect(await screen.findByTestId('agent-app')).toHaveTextContent('room:room-42');
    expect(screen.queryByTestId('satellite-host')).not.toBeInTheDocument();

    rerender(
      <PawAppBody
        appId="agent"
        target={{ kind: 'room', id: 'room-42', title: '产品协作室', panel: 'flow' }}
      />,
    );

    expect(await screen.findByTestId('satellite-host')).toHaveTextContent('room:flow');
    expect(screen.queryByTestId('agent-app')).not.toBeInTheDocument();
  });

  it('routes non-conversation Apps through the PAWOS-native, data-backed surface', async () => {
    const transport = new MockControlTransport({ routes: {
      'overview.get': { ok: true, project: { name: 'PAWOS' } },
      'planning.dashboard': { ok: true, tasks: [] },
      'workDocuments.list': { ok: true, items: [] },
    } });
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    render(
      <ControlTransportProvider transport={transport}>
        <PawOsAppearanceProvider>
          <QueryClientProvider client={queryClient}>
            <PawAppBody appId="project-workbench" />
          </QueryClientProvider>
        </PawOsAppearanceProvider>
      </ControlTransportProvider>,
    );

    expect(await screen.findByRole('heading', { name: '项目概览' })).toBeInTheDocument();
    await waitFor(() => expect(transport.requests.map(({ request }) => request.pathId)).toEqual(
      expect.arrayContaining(['overview.get', 'planning.dashboard', 'workDocuments.list']),
    ));
  });
});
