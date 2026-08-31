import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ControlTransportProvider } from '@/app/control-transport';
import { ControlTransportHttpError } from '@/platform/http-transport';
import type { ControlRequest } from '@/platform/transport';
import { MockControlTransport } from '@/test/mock-transport';
import type { PawExtensionAppManifest } from '@/paw-os/extensions/types';
import ExtensionAppFrontend from './App';

vi.mock('@/paw-os/apps/PawSessionWorkspace', () => ({
  PawSessionWorkspace: ({ recordId }: { recordId: string }) => (
    <section data-testid="shared-session">Shared Session {recordId}</section>
  ),
}));

const manifest: PawExtensionAppManifest = {
  schemaVersion: 'pawos.extension-app.v1',
  id: 'extension:sample-insights',
  version: '0.1.0',
  bindingSha256: 'a'.repeat(64),
  packageId: '@paw/sample-insights',
  label: 'Sample Insights',
  shortLabel: 'Insights',
  tagline: 'Inspect current evidence',
  route: '/extensions/sample-insights',
  presentation: 'workspace',
  accent: 'green',
  icon: { symbol: 'analytics', background: '#087F68' },
  skillRef: 'sample-insights',
  skillSha256: 'b'.repeat(64),
  verticalSuiteId: 'sample',
  verticalSuiteRevision: 'fixture-v1',
};

afterEach(cleanup);

describe('Extension App frontend starter', () => {
  it('binds each mode to an App-owned ordinary Pi Session', async () => {
    const transport = transportWithPrompt(() => ({ ok: true, accepted: true }));
    const user = userEvent.setup();
    renderApp(transport);

    await user.click(await screen.findByRole('tab', { name: 'Review' }));
    await user.type(screen.getByLabelText('Start this App conversation'), 'Compare these claims.');
    await user.click(screen.getByRole('button', { name: 'Start' }));

    await waitFor(() => expect(requestsFor(transport, 'agent.session.prompt')).toHaveLength(1));
    expect(requestFor(transport, 'agent.sessions.create').body).toMatchObject({
      surfaceKind: 'extension_app',
      ownerAppId: manifest.id,
      surfaceKey: 'review',
    });
    expect(requestFor(transport, 'agent.session.mode.update').body).toMatchObject({
      piSkillsEnabled: true,
      codexSkillsEnabled: false,
    });
    expect(requestFor(transport, 'agent.session.prompt').body).toMatchObject({
      delivery: 'prompt',
      message: expect.stringContaining('App mode: Review'),
    });
  });

  it('replays an unknown admission with the same id and semantic payload', async () => {
    let attempt = 0;
    const transport = transportWithPrompt(() => {
      attempt += 1;
      if (attempt === 1) throw new TypeError('connection closed before receipt');
      return { ok: true, accepted: true };
    });
    const user = userEvent.setup();
    renderApp(transport);

    await user.type(await screen.findByLabelText('Start this App conversation'), 'Summarize the evidence.');
    await user.click(screen.getByRole('button', { name: 'Start' }));
    await user.click(await screen.findByRole('button', { name: 'Retry' }));

    await waitFor(() => expect(requestsFor(transport, 'agent.session.prompt')).toHaveLength(2));
    const [first, second] = requestsFor(transport, 'agent.session.prompt').map((request) => request.body);
    expect(second).toEqual(first);
    expect(second).not.toHaveProperty('retryOfClientMessageId');
  });

  it('creates one failed-command successor with a new id and explicit lineage', async () => {
    let attempt = 0;
    const transport = transportWithPrompt((request) => {
      attempt += 1;
      if (attempt === 1) {
        const body = request.body as Record<string, unknown>;
        throw new ControlTransportHttpError(
          'agent.session.prompt',
          409,
          'command failed before acceptance',
          {
            ok: false,
            code: 'AGENT_COMMAND_FAILED',
            commandReceipt: {
              state: 'failed',
              clientMessageId: body.clientMessageId,
              causeCode: 'SESSION_IDLE',
            },
          },
        );
      }
      return { ok: true, accepted: true };
    });
    const user = userEvent.setup();
    renderApp(transport);

    await user.type(await screen.findByLabelText('Start this App conversation'), 'Review the evidence.');
    await user.click(screen.getByRole('button', { name: 'Start' }));
    await user.click(await screen.findByRole('button', { name: 'Retry' }));

    await waitFor(() => expect(requestsFor(transport, 'agent.session.prompt')).toHaveLength(2));
    const [first, second] = requestsFor(transport, 'agent.session.prompt').map((request) => request.body as Record<string, unknown>);
    expect(second.clientMessageId).not.toBe(first.clientMessageId);
    expect(second.retryOfClientMessageId).toBe(first.clientMessageId);
    expect(second.message).toBe(first.message);
  });
});

function transportWithPrompt(handler: (request: ControlRequest) => unknown): MockControlTransport {
  return new MockControlTransport({ routes: {
    'agent.sessions.list': { ok: true, items: [] },
    'agent.sessions.create': {
      ok: true,
      session: { id: 'session-sample', title: 'Sample Insights', mode: 'assistant', status: 'idle', updatedAtMs: 1 },
    },
    'agent.session.mode.update': { ok: true },
    'agent.session.prompt': handler,
  } });
}

function renderApp(transport: MockControlTransport) {
  return render(
    <ControlTransportProvider transport={transport}>
      <ExtensionAppFrontend manifest={manifest} />
    </ControlTransportProvider>,
  );
}

function requestsFor(transport: MockControlTransport, pathId: ControlRequest['pathId']): ControlRequest[] {
  return transport.requests
    .map(({ request }) => request)
    .filter((request) => request.pathId === pathId);
}

function requestFor(transport: MockControlTransport, pathId: ControlRequest['pathId']): ControlRequest {
  const request = requestsFor(transport, pathId)[0];
  if (!request) throw new Error(`Missing request ${pathId}`);
  return request;
}
