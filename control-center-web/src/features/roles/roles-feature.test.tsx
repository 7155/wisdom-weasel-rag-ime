import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { afterEach, describe, expect, it } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import { TooltipProvider } from '@/components/primitives';
import { MockControlTransport } from '@/test/mock-transport';
import { StubControlTransport } from '@/test/stub-control-transport';
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
    expect(await screen.findByText('此刻陪你输入，也陪你把事情想清楚')).toBeInTheDocument();
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
      'agent.sessions.create': { ok: true, session: { id: 'session-past' } },
    } });
    render(
      <MemoryRouter initialEntries={['/roles']}>
        <ControlTransportProvider transport={transport}>
          <TooltipProvider><RolesFeature /><LocationProbe /></TooltipProvider>
        </ControlTransportProvider>
      </MemoryRouter>,
    );

    await user.click(await screen.findByRole('button', { name: /智鼬·初识/ }));
    await user.click(screen.getByRole('button', { name: '开始对话' }));

    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/agent?session=session-past'));
    const create = transport.requests.find((call) => call.request.pathId === 'agent.sessions.create');
    expect(create?.request.body).toEqual({
      title: '智鼬·初识 对话',
      mode: 'assistant',
      roleId: 'hermes-v1',
      roleVersion: '1',
      modelProfile: 'affinity-5.6-luna',
      toolProfileVersion: 'control-center-v1',
      workspaceRoots: [],
    });
  });

  it('does not substitute preview Personas when the native catalog is empty', async () => {
    const transport = new StubControlTransport('native', {
      'agent.roles.list': { ok: true, items: [] },
      'agent.subagents.templates': { ok: true, items: [] },
    });
    render(<MemoryRouter><ControlTransportProvider transport={transport}><TooltipProvider><RolesFeature /></TooltipProvider></ControlTransportProvider></MemoryRouter>);

    expect(await screen.findByText('尚未从本机 Agent Kernel 读取到角色。')).toBeInTheDocument();
    expect(screen.queryByText('此刻陪你输入，也陪你把事情想清楚')).not.toBeInTheDocument();
  });
});

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="location">{location.pathname}{location.search}</output>;
}
