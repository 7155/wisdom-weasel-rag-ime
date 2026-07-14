import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import { TooltipProvider } from '@/components/primitives';
import { MockControlTransport } from '@/test/mock-transport';
import { StubControlTransport } from '@/test/stub-control-transport';
import { AgentFeature } from './index';
import { previewAgentEvents, previewAgentSnapshot, previewModelCatalog, previewPersonas, previewSessions } from './preview-data';
import { SessionRail } from './sessions/SessionRail';
import { useAgentLiveStore } from './state/live-store';
import { AgentTurn } from './timeline/AgentTimeline';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  for (const session of previewSessions) useAgentLiveStore.getState().clear(session.id);
});

describe('Agent experience', () => {
  it('makes the full session row clickable', async () => {
    const onSelect = vi.fn();
    const user = userEvent.setup();
    render(<TooltipProvider><SessionRail sessions={previewSessions} selectedId="session-preview" loading={false} onSelect={onSelect} onCreate={() => {}} /></TooltipProvider>);
    await user.click(screen.getByRole('button', { name: /记忆整理/ }));
    expect(onSelect).toHaveBeenCalledWith('session-memory');
  });

  it('renders one persona avatar and one activity container per assistant turn without raw payloads', async () => {
    const sessionId = 'session-preview';
    const snapshot = previewAgentSnapshot(sessionId);
    useAgentLiveStore.getState().hydrateSnapshot(sessionId, snapshot);
    const events = previewAgentEvents(sessionId);
    events[1] = { ...events[1]!, payload: { ...events[1]!.payload, rawSecret: '{"token":"do-not-render"}' } };
    useAgentLiveStore.getState().applyEvents(sessionId, events);
    const turnId = `${sessionId}:turn-architecture`;
    render(<TooltipProvider><AgentTurn sessionId={sessionId} turnId={turnId} persona={previewPersonas[0]} onApprovalDecision={() => {}} /></TooltipProvider>);
    expect(screen.getAllByAltText('智鼬·此刻头像')).toHaveLength(1);
    expect(document.querySelectorAll('.agent-activity')).toHaveLength(1);
    expect(document.querySelector('.agent-user-message')).toBeInTheDocument();
    expect(screen.queryByText(/do-not-render/)).not.toBeInTheDocument();
    expect(document.querySelector('.agent-assistant-message')).toHaveTextContent('三条 Lane 已经收束到同一个');
  });

  it('sends through the allowlisted prompt path', async () => {
    const transport = featureTransport();
    const user = userEvent.setup();
    renderAgent(transport);
    const composer = await screen.findByRole('textbox', { name: '消息' });
    await user.type(composer, '检查 reducer 边界');
    await user.click(screen.getByRole('button', { name: '发送' }));
    await waitFor(() => expect(transport.requests.some((call) => call.request.pathId === 'agent.session.prompt')).toBe(true));
    const prompt = transport.requests.find((call) => call.request.pathId === 'agent.session.prompt');
    expect(prompt?.request.params).toEqual({ sessionId: 'session-preview' });
    expect(prompt?.request.body).toMatchObject({ message: '检查 reducer 边界' });
  });

  it('imports managed images for the current session before sending mediaIds', async () => {
    const transport = featureTransport();
    const user = userEvent.setup();
    renderAgent(transport);
    await screen.findByRole('textbox', { name: '消息' });
    await user.click(screen.getByRole('button', { name: '添加附件' }));
    expect(transport.filePickCalls).toEqual([{
      accepts: ['image/png', 'image/jpeg', 'image/gif', 'image/webp'],
      multiple: true,
      purpose: 'attachment',
      sessionId: 'session-preview',
      maxFiles: 8,
    }]);
    await user.click(screen.getByRole('button', { name: '发送' }));
    await waitFor(() => expect(transport.requests.some((call) => call.request.pathId === 'agent.session.prompt')).toBe(true));
    const prompt = transport.requests.find((call) => call.request.pathId === 'agent.session.prompt');
    expect(prompt?.request.body).toMatchObject({ attachments: ['media_fixture_attachment_01'] });
  });

  it('starts with the session rail closed on mobile and closes it after selection', async () => {
    vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: true })));
    const user = userEvent.setup();
    renderAgent(featureTransport());
    const feature = document.querySelector('.agent-feature');
    expect(feature).toHaveAttribute('data-rail-open', 'false');

    await user.click(screen.getByRole('button', { name: '展开 Sessions' }));
    expect(feature).toHaveAttribute('data-rail-open', 'true');
    await user.click(await screen.findByRole('button', { name: /记忆整理/ }));
    expect(feature).toHaveAttribute('data-rail-open', 'false');
  });

  it('selects the Session requested by the roles route handoff', async () => {
    const transport = featureTransport();
    renderAgent(transport, '/agent?session=session-memory');

    expect(await screen.findByRole('button', { name: /记忆整理/ })).toHaveAttribute('aria-current', 'true');
    await waitFor(() => expect(transport.requests).toContainEqual(expect.objectContaining({
      request: expect.objectContaining({
        pathId: 'agent.session.snapshot',
        params: { sessionId: 'session-memory' },
      }),
    })));
  });

  it('does not substitute preview Sessions or Personas in the native host', async () => {
    const transport = new StubControlTransport('native', {
      'agent.sessions.list': { ok: true, items: [] },
      'agent.roles.list': { ok: true, items: [] },
    });
    render(
      <MemoryRouter initialEntries={['/agent']}>
        <ControlTransportProvider transport={transport}>
          <TooltipProvider><AgentFeature /></TooltipProvider>
        </ControlTransportProvider>
      </MemoryRouter>,
    );

    await waitFor(() => expect(transport.requests.map((request) => request.pathId)).toEqual(
      expect.arrayContaining(['agent.sessions.list', 'agent.roles.list']),
    ));
    expect(screen.getByText('0 个连续对话')).toBeInTheDocument();
    expect(screen.queryByText('控制中心迁移')).not.toBeInTheDocument();
    expect(screen.queryByText('记忆整理')).not.toBeInTheDocument();
  });
});

function renderAgent(transport: MockControlTransport, initialEntry = '/agent') {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <ControlTransportProvider transport={transport}>
        <TooltipProvider><AgentFeature /></TooltipProvider>
      </ControlTransportProvider>
    </MemoryRouter>,
  );
}

function featureTransport(): MockControlTransport {
  return new MockControlTransport({
    pickedFiles: [{
      id: 'media_fixture_attachment_01',
      name: 'screen.png',
      mimeType: 'image/png',
      byteSize: 68,
      sessionId: 'session-preview',
      sha256: '0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef',
    }],
    routes: {
      'agent.sessions.list': { ok: true, items: previewSessions },
      'agent.roles.list': { ok: true, items: previewPersonas },
      'agent.session.snapshot': previewAgentSnapshot('session-preview'),
      'agent.session.models': previewModelCatalog('session-preview'),
      'agent.session.prompt': { ok: true },
      'agent.sessions.create': { ok: true },
      'agent.session.compact': { ok: true },
      'agent.session.abort': { ok: true },
      'agent.session.mode.update': { ok: true },
      'agent.session.model.select': { ok: true },
      'agent.session.thinking.select': { ok: true },
      'agent.approval.decide': { ok: true },
    },
  });
}
