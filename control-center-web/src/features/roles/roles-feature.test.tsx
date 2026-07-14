import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
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
    render(<ControlTransportProvider transport={transport}><TooltipProvider><RolesFeature /></TooltipProvider></ControlTransportProvider>);
    expect(await screen.findByText('热心、灵动，关键时刻可靠')).toBeInTheDocument();
    await user.click(screen.getByRole('radio', { name: 'Agent Template' }));
    expect(screen.getAllByText('研究员')).toHaveLength(2);
    expect(screen.getByText(/10 turns/)).toBeInTheDocument();
    await waitFor(() => expect(transport.requests.map((call) => call.request.pathId)).toEqual(expect.arrayContaining(['agent.roles.list', 'agent.subagents.templates'])));
  });
});
