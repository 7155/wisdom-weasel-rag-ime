import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import type { ControlRequest } from '@/platform/transport';
import { MockControlTransport } from '@/test/mock-transport';
import { MemorySteward } from './MemorySteward';

const { sessionWorkspaceProps } = vi.hoisted(() => ({ sessionWorkspaceProps: vi.fn() }));

vi.mock('@/paw-os/apps/PawSessionWorkspace', () => ({
  PawSessionWorkspace: (props: { appearance?: string; recordId: string }) => {
    sessionWorkspaceProps(props);
    return <section data-testid="memory-steward-session">Session {props.recordId}</section>;
  },
}));

afterEach(() => {
  cleanup();
  sessionWorkspaceProps.mockClear();
  window.localStorage.clear();
});

describe('MemorySteward', () => {
  it('starts a date-owned Pi Session in place and sends the real timeline boundary', async () => {
    const user = userEvent.setup();
    const transport = new MockControlTransport({ routes: {
      'agent.sessions.list': { ok: true, items: [] },
      'agent.sessions.surface.ensure': {
        ok: true,
        created: true,
        session: {
          id: 'session-memory-20260831',
          title: 'Memory 管家 · 2026-08-31',
          mode: 'assistant',
          status: 'idle',
          updatedAtMs: 1,
          surfaceKind: 'builtin_app',
          ownerAppId: 'memory',
          surfaceKey: 'journal-2026-08-31',
        },
      },
      'agent.session.mode.update': { ok: true },
      'agent.session.prompt': { ok: true },
    } });
    renderSteward(transport);

    await user.click(await screen.findByRole('button', { name: '最近有哪些 idea 还没完成？' }));
    await user.click(screen.getByRole('button', { name: '发送给记忆管家' }));

    expect(await screen.findByTestId('memory-steward-session')).toHaveTextContent('session-memory-20260831');
    expect(sessionWorkspaceProps).toHaveBeenLastCalledWith(expect.objectContaining({
      appearance: 'embedded',
      recordId: 'session-memory-20260831',
    }));
    expect(requestFor(transport, 'agent.sessions.surface.ensure').body).toMatchObject({
      surfaceKind: 'builtin_app',
      ownerAppId: 'memory',
      surfaceKey: 'journal-2026-08-31',
      executionMode: 'read_only',
    });
    expect(requestFor(transport, 'agent.session.mode.update').body).toMatchObject({
      executionMode: 'read_only',
      projectContextEnabled: false,
      piSkillsEnabled: true,
    });
    const prompt = String((requestFor(transport, 'agent.session.prompt').body as Record<string, unknown>).message);
    expect(prompt).toContain('2026-08-31');
    expect(prompt).toContain('timeline-20260831');
    expect(prompt).toContain('最近有哪些 idea 还没完成？');
    expect(window.localStorage.length).toBe(0);
  });

  it('restores only the Memory journal Session for the selected date', async () => {
    const transport = new MockControlTransport({ routes: {
      'agent.sessions.list': {
        ok: true,
        items: [{
          id: 'session-memory-existing',
          title: 'Memory 管家 · 2026-08-31',
          mode: 'assistant',
          status: 'idle',
          updatedAtMs: 8,
          surfaceKind: 'builtin_app',
          ownerAppId: 'memory',
          surfaceKey: 'journal-2026-08-31',
        }],
      },
    } });
    renderSteward(transport);

    expect(await screen.findByTestId('memory-steward-session')).toHaveTextContent('session-memory-existing');
    expect(requestFor(transport, 'agent.sessions.list').query).toMatchObject({
      surfaceKind: 'builtin_app',
      ownerAppId: 'memory',
      surfaceKey: 'journal-2026-08-31',
    });
  });

  it('keeps transport wording out of the personal Memory surface', async () => {
    const transport = new MockControlTransport({ routes: {
      'agent.sessions.list': () => { throw new Error('Failed to fetch'); },
    } });
    renderSteward(transport);

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('暂时没有读到这一天的管家对话，仍可重新开始。');
    expect(alert).not.toHaveTextContent('Failed to fetch');
  });
});

function renderSteward(transport: MockControlTransport) {
  return render(
    <ControlTransportProvider transport={transport}>
      <MemorySteward date="2026-08-31" timelineId="timeline-20260831" />
    </ControlTransportProvider>,
  );
}

function requestFor(transport: MockControlTransport, pathId: ControlRequest['pathId']): ControlRequest {
  const request = transport.requests.find((call) => call.request.pathId === pathId)?.request;
  if (!request) throw new Error(`Missing request ${pathId}`);
  return request;
}
