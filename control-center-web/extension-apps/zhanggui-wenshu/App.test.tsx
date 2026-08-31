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
    expect(screen.getByRole('checkbox', { name: '启动前运行受管沙箱自测' })).not.toBeChecked();
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
      'extension.sandbox.experiment.run': {
        schemaVersion: 'rag-ime.extension-sandbox-experiment-receipt.v1',
        ok: true,
        sessionId: 'session-zhanggui',
        ownerAppId: manifest.id,
        candidateBindingSha256: manifest.bindingSha256,
        requestedDecision: 'skip',
        executed: false,
        executionStatus: 'skipped',
      },
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
      'extension.sandbox.experiment.run',
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
    const list = requestFor(transport, 'agent.sessions.list');
    expect(list.query).toMatchObject({
      surfaceKind: 'extension_app',
      ownerAppId: manifest.id,
    });
    const create = requestFor(transport, 'agent.sessions.create');
    expect(create.body).toMatchObject({
      surfaceKind: 'extension_app',
      ownerAppId: manifest.id,
      surfaceKey: 'reconcile',
    });
    expect(requestFor(transport, 'extension.sandbox.experiment.run').body).toMatchObject({
      sessionId: 'session-zhanggui',
      ownerAppId: manifest.id,
      candidateBindingSha256: manifest.bindingSha256,
      requestedDecision: 'skip',
    });
    expect(prompt.params).toEqual({ sessionId: 'session-zhanggui' });
    expect(prompt.body).toMatchObject({ delivery: 'prompt' });
    expect(String((prompt.body as Record<string, unknown>).message)).toContain('`zhanggui-wenshu` Skill');
    expect(String((prompt.body as Record<string, unknown>).message)).toContain('当前掌柜问数模式：对账');
    expect(String((prompt.body as Record<string, unknown>).message)).toContain('核对销售台账与回款表');
    expect(window.localStorage.length).toBe(0);
    expect(screen.queryByRole('button', { name: '打开运行详情' })).not.toBeInTheDocument();
  });

  it('runs the selected managed sandbox before handing the first prompt to Pi', async () => {
    const user = userEvent.setup();
    const transport = new MockControlTransport({ routes: {
      'agent.sessions.list': { ok: true, items: [] },
      'agent.sessions.create': {
        ok: true,
        session: { id: 'session-sandbox', title: '掌柜问数 · 问数', mode: 'assistant', status: 'idle', updatedAtMs: 1 },
      },
      'agent.session.mode.update': { ok: true },
      'extension.sandbox.experiment.run': {
        schemaVersion: 'rag-ime.extension-sandbox-experiment-receipt.v1',
        ok: true,
        sessionId: 'session-sandbox',
        ownerAppId: manifest.id,
        candidateBindingSha256: manifest.bindingSha256,
        requestedDecision: 'run',
        executed: true,
        executionStatus: 'completed',
        sandboxRunId: 'sandbox:sgg:test',
        traceId: 'trace:sgg:test',
        evalRunId: 'eval:sgg:test',
      },
      'agent.session.prompt': { ok: true },
    } });
    renderApp(transport);

    await user.click(await screen.findByRole('checkbox', { name: '启动前运行受管沙箱自测' }));
    await user.type(screen.getByRole('textbox', { name: '问数问题' }), '本月销售额是多少？');
    await user.click(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => expect(requestFor(transport, 'extension.sandbox.experiment.run').body).toMatchObject({
      sessionId: 'session-sandbox',
      ownerAppId: manifest.id,
      candidateBindingSha256: manifest.bindingSha256,
      requestedDecision: 'run',
    }));
    const calls = transport.requests.map(({ request }) => request.pathId);
    expect(calls.indexOf('extension.sandbox.experiment.run')).toBeLessThan(calls.indexOf('agent.session.prompt'));
    expect(await screen.findByRole('status')).toHaveTextContent('sandbox:sgg:test');
    await user.click(screen.getByRole('tab', { name: '对账' }));
    expect(screen.queryByText(/sandbox:sgg:test/)).not.toBeInTheDocument();
  });

  it('refuses a mismatched sandbox receipt and never sends the Pi prompt', async () => {
    const user = userEvent.setup();
    const transport = new MockControlTransport({ routes: {
      'agent.sessions.list': { ok: true, items: [] },
      'agent.sessions.create': {
        ok: true,
        session: { id: 'session-invalid-receipt', title: '掌柜问数 · 问数', mode: 'assistant', status: 'idle', updatedAtMs: 1 },
      },
      'agent.session.mode.update': { ok: true },
      'extension.sandbox.experiment.run': {
        schemaVersion: 'rag-ime.extension-sandbox-experiment-receipt.v1',
        ok: true,
        sessionId: 'session-invalid-receipt',
        ownerAppId: manifest.id,
        candidateBindingSha256: manifest.bindingSha256,
        requestedDecision: 'run',
        executed: false,
        executionStatus: 'skipped',
      },
      'agent.session.prompt': { ok: true },
    } });
    renderApp(transport);

    await user.click(await screen.findByRole('checkbox', { name: '启动前运行受管沙箱自测' }));
    await user.type(screen.getByRole('textbox', { name: '问数问题' }), '本月销售额是多少？');
    await user.click(screen.getByRole('button', { name: '发送' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('沙箱');
    expect(transport.requests.some(({ request }) => request.pathId === 'agent.session.prompt')).toBe(false);
  });

  it('restores only App-owned conversations from the durable Session owner query', async () => {
    const transport = new MockControlTransport({ routes: {
      'agent.sessions.list': {
        ok: true,
        items: [
          {
            id: 'session-app-ask',
            title: '掌柜问数 · 问数',
            mode: 'assistant',
            status: 'idle',
            updatedAtMs: 12,
            surfaceKind: 'extension_app',
            ownerAppId: manifest.id,
            surfaceKey: 'ask',
          },
          {
            id: 'session-agent',
            title: '普通 Agent 对话',
            mode: 'assistant',
            status: 'idle',
            updatedAtMs: 11,
            surfaceKind: 'agent',
            ownerAppId: '',
            surfaceKey: '',
          },
        ],
      },
    } });

    renderApp(transport);

    expect(await screen.findByTestId('shared-session')).toHaveTextContent('session-app-ask');
    expect(screen.queryByText('session-agent')).not.toBeInTheDocument();
    expect(requestFor(transport, 'agent.sessions.list').query).toMatchObject({
      surfaceKind: 'extension_app',
      ownerAppId: manifest.id,
    });
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
