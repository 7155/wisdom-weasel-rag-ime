import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { afterEach, describe, expect, it } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import { TooltipProvider } from '@/components/primitives';
import { MockControlTransport } from '@/test/mock-transport';
import { previewPersonas, previewTemplates } from '@/features/agent/preview-data';
import { RolesFeature } from './index';

describe('Roles experience', () => {
  afterEach(cleanup);
  it('keeps Persona visuals separate from Agent Template runtime limits', async () => {
    const user = userEvent.setup();
    const transport = new MockControlTransport({ routes: {
      'agent.roles.list': { ok: true, items: previewPersonas },
      'agent.subagents.templates': { ok: true, items: previewTemplates },
    } });
    render(<MemoryRouter><ControlTransportProvider transport={transport}><TooltipProvider><RolesFeature /></TooltipProvider></ControlTransportProvider></MemoryRouter>);
    expect(await screen.findByText('热心、灵动，关键时刻可靠')).toBeInTheDocument();
    await user.click(screen.getByRole('radio', { name: 'Agent Template' }));
    expect(screen.getAllByText('研究员')).toHaveLength(2);
    expect(screen.getByText(/10 turns/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '开始对话' })).not.toBeInTheDocument();
    await waitFor(() => expect(transport.requests.map((call) => call.request.pathId)).toEqual(expect.arrayContaining(['agent.roles.list', 'agent.subagents.templates'])));
  });

  it('creates a Session with the selected Persona and navigates to it', async () => {
    const user = userEvent.setup();
    const transport = new MockControlTransport({ routes: {
      'agent.roles.list': { ok: true, items: previewPersonas },
      'agent.subagents.templates': { ok: true, items: previewTemplates },
      'agent.sessions.create': { ok: true, session: { id: 'session-hermes' } },
    } });
    render(
      <MemoryRouter initialEntries={['/roles']}>
        <ControlTransportProvider transport={transport}>
          <TooltipProvider><RolesFeature /><LocationProbe /></TooltipProvider>
        </ControlTransportProvider>
      </MemoryRouter>,
    );

    await user.click(await screen.findByRole('button', { name: /Hermes/ }));
    await user.click(screen.getByRole('button', { name: '开始对话' }));

    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/agent?session=session-hermes'));
    const create = transport.requests.find((call) => call.request.pathId === 'agent.sessions.create');
    expect(create?.request.body).toEqual({
      title: 'Hermes 对话',
      mode: 'assistant',
      roleId: 'hermes-v1',
      roleVersion: '1',
      modelProfile: 'session-selected',
      toolProfileVersion: 'control-center-v1',
      workspaceRoots: [],
    });
  });
});

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="location">{location.pathname}{location.search}</output>;
}
