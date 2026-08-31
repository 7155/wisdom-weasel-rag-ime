import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ControlTransportProvider } from '@/app/control-transport';
import { MockControlTransport } from '@/test/mock-transport';
import type { ControlRequest } from '@/platform/transport';
import manifest from './pawos-app.json';
import ZhangguiWenshuApp from './App';

const { sessionWorkspaceProps } = vi.hoisted(() => ({
  sessionWorkspaceProps: vi.fn(),
}));

vi.mock('@/paw-os/apps/PawSessionWorkspace', () => ({
  PawSessionWorkspace: (props: { recordId: string; appearance?: string; composerPlaceholder?: string }) => {
    sessionWorkspaceProps(props);
    return <section data-testid="shared-session">Session {props.recordId}</section>;
  },
}));

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  sessionWorkspaceProps.mockClear();
});

describe('掌柜问数 Extension App', () => {
  it('keeps three conversation modes in one source-isolated App surface', async () => {
    renderApp(new MockControlTransport({ routes: {
      'agent.sessions.list': { ok: true, items: [] },
    } }));

    expect(await screen.findByRole('heading', { name: '掌柜问数' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: '问数' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('tab', { name: '对账' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: '解释' })).toBeInTheDocument();
    expect(await screen.findByRole('textbox', { name: '问数问题' })).toBeInTheDocument();
    expect(screen.getByText(/SGG 仅用于沙盒自测/)).toBeInTheDocument();
  });

  it('creates one ordinary Pi Session, enables the App Skill, and sends the selected mode contract', async () => {
    const user = userEvent.setup();
    const transport = new MockControlTransport({ routes: {
      'agent.sessions.list': { ok: true, items: [] },
      'agent.sessions.create': {
        ok: true,
        session: { id: 'session-zhanggui', title: '掌柜问数 · 对账', mode: 'assistant', status: 'idle', updatedAtMs: 1 },
      },
      'agent.session.mode.update': { ok: true },
      'agent.session.prompt': { ok: true },
    } });
    renderApp(transport);

    await user.click(await screen.findByRole('tab', { name: '对账' }));
    const input = screen.getByRole('textbox', { name: '对账问题' });
    await user.type(input, '核对销售台账与回款表');
    await user.click(screen.getByRole('button', { name: '发送' }));

    expect(await screen.findByTestId('shared-session')).toHaveTextContent('session-zhanggui');
    expect(sessionWorkspaceProps).toHaveBeenLastCalledWith(expect.objectContaining({
      appearance: 'embedded',
      composerPlaceholder: expect.stringContaining('核对'),
    }));
    const calls = transport.requests.map(({ request }) => request.pathId);
    expect(calls).toEqual([
      'agent.sessions.list',
      'agent.sessions.create',
      'agent.session.mode.update',
      'agent.session.prompt',
    ]);
    const mode = requestFor(transport, 'agent.session.mode.update');
    expect(mode.body).toMatchObject({
      mode: 'assistant',
      executionMode: 'per_action',
      piSkillsEnabled: true,
      projectContextEnabled: false,
      codexSkillsEnabled: false,
    });
    const prompt = requestFor(transport, 'agent.session.prompt');
    expect(prompt.params).toEqual({ sessionId: 'session-zhanggui' });
    expect(prompt.body).toMatchObject({ delivery: 'prompt' });
    expect(String((prompt.body as Record<string, unknown>).message)).toContain('`zhanggui-wenshu` Skill');
    expect(String((prompt.body as Record<string, unknown>).message)).toContain('当前掌柜问数模式：对账');
    expect(String((prompt.body as Record<string, unknown>).message)).toContain('核对销售台账与回款表');
  });
});

function renderApp(transport: MockControlTransport) {
  return render(
    <ControlTransportProvider transport={transport}>
      <ZhangguiWenshuApp manifest={manifest as never} />
    </ControlTransportProvider>,
  );
}

function requestFor(transport: MockControlTransport, pathId: ControlRequest['pathId']): ControlRequest {
  const request = transport.requests.find((call) => call.request.pathId === pathId)?.request;
  if (!request) throw new Error(`Missing request ${pathId}`);
  return request;
}
