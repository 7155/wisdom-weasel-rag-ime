import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import { MockControlTransport, type MockControlTransportOptions } from '@/test/mock-transport';
import { PawDesktopProvider } from '../runtime/desktop-context';
import { PawWayfinderWork } from './PawWayfinderWork';

/* The desktop panel is a projection, not a manager: it must fold the raw
 * directory to desktop density, keep its own scroll, and hand every click to
 * the Agent window. These tests drive it through the same transport seam the
 * desktop uses, with the exact clone/repeat shapes that once flooded the
 * screen. */

const NOW = Date.now();

beforeEach(() => window.localStorage.clear());
afterEach(() => cleanup());

describe('PawWayfinderWork', () => {
  it('shows one folded Room row instead of a page of Agent 1/2/3 clones', async () => {
    renderPanel({
      routes: {
        'agent.sessions.list': { ok: true, items: [
          sessionRecord('s-1', '迁移作战室 · Agent 1', { roomParticipant: { roomId: 'room-9', participantId: 'p1', status: 'active' } }),
          sessionRecord('s-2', '迁移作战室 · Agent 2', { roomParticipant: { roomId: 'room-9', participantId: 'p2', status: 'active' } }),
          sessionRecord('s-3', '迁移作战室 · Agent 3', { roomParticipant: { roomId: 'room-9', participantId: 'p3', status: 'active' } }),
        ] },
        'agent.rooms.list': { ok: true, items: [] },
      },
    });

    const panel = await screen.findByRole('region', { name: '最近工作' });
    const rows = within(panel).getAllByRole('button', { name: /迁移作战室/ });
    expect(rows).toHaveLength(1);
    expect(within(rows[0]!).getByLabelText('3 位伙伴')).toHaveTextContent('Agent 1Agent 2Agent 3');
    expect(within(panel).queryByText('迁移作战室 · Agent 1')).not.toBeInTheDocument();
  });

  it('collapses repeated goal copy and reveals older runs only on demand', async () => {
    renderPanel({
      routes: {
        'agent.sessions.list': { ok: true, items: [
          sessionRecord('s-new', '重构 Wayfinder 列表', { updatedAtMs: NOW - 60_000 }),
          sessionRecord('s-old', '重构 Wayfinder 列表', { updatedAtMs: NOW - 3_600_000 }),
        ] },
        'agent.rooms.list': { ok: true, items: [] },
      },
    });

    expect(await screen.findAllByRole('button', { name: /重构 Wayfinder 列表/ })).toHaveLength(1);
    expect(screen.queryByRole('button', { name: /较早一段/ })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '同名工作还有 1 段' }));
    expect(screen.getByRole('button', { name: /较早一段/ })).toBeInTheDocument();
  });

  it('filters rows through the panel search without leaving the desktop', async () => {
    renderPanel({
      routes: {
        'agent.sessions.list': { ok: true, items: [
          sessionRecord('s-1', '重构列表'),
          sessionRecord('s-2', '整理知识库'),
        ] },
        'agent.rooms.list': { ok: true, items: [] },
      },
    });

    await screen.findByRole('button', { name: /整理知识库/ });
    fireEvent.change(screen.getByRole('searchbox', { name: '搜索最近工作' }), { target: { value: '重构' } });

    expect(screen.getByRole('button', { name: /重构列表/ })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /整理知识库/ })).not.toBeInTheDocument();
  });

  it('rests the 更早 bucket collapsed so stale history never fills the first screen', async () => {
    renderPanel({
      routes: {
        'agent.sessions.list': { ok: true, items: [
          sessionRecord('s-now', '今天的工作'),
          sessionRecord('s-old-1', '上个月的工作 A', { updatedAtMs: NOW - 30 * 86_400_000 }),
          sessionRecord('s-old-2', '上个月的工作 B', { updatedAtMs: NOW - 31 * 86_400_000 }),
        ] },
        'agent.rooms.list': { ok: true, items: [] },
      },
    });

    await screen.findByRole('button', { name: /今天的工作/ });
    expect(screen.queryByRole('button', { name: /上个月的工作/ })).not.toBeInTheDocument();

    const stale = screen.getByRole('button', { name: /更早/ });
    expect(stale).toHaveAttribute('aria-expanded', 'false');
    fireEvent.click(stale);
    expect(screen.getAllByRole('button', { name: /上个月的工作/ })).toHaveLength(2);
  });

  it('opens a row straight into the Agent window projection', async () => {
    renderPanel({
      routes: {
        'agent.sessions.list': { ok: true, items: [sessionRecord('s-42', '继续修复投影')] },
        'agent.rooms.list': { ok: true, items: [] },
      },
    });

    fireEvent.click(await screen.findByRole('button', { name: /继续修复投影/ }));

    // Desktop persistence is a trailing debounce, so the snapshot lands one
    // beat after the interaction instead of inside it.
    await waitFor(() => {
      const snapshot = JSON.parse(window.localStorage.getItem('pawos.desktop.v1') ?? '{}') as {
        windows?: Record<string, { appId?: string; initialRoute?: string; target?: { kind?: string; id?: string } }>;
      };
      expect(snapshot.windows?.['agent:s-42']).toMatchObject({
        appId: 'agent',
        initialRoute: '/agent?session=s-42',
        target: { kind: 'session', id: 's-42' },
      });
    });
  });

  it('reports an unreadable directory with a retry instead of an empty desktop', async () => {
    renderPanel({ routes: {} });

    expect(await screen.findByRole('alert')).toHaveTextContent('工作记录暂时无法读取');
    expect(screen.getByRole('button', { name: '重试' })).toBeInTheDocument();
  });
});

function renderPanel(options: MockControlTransportOptions) {
  return render(
    <ControlTransportProvider transport={new MockControlTransport(options)}>
      <PawDesktopProvider>
        <PawWayfinderWork />
      </PawDesktopProvider>
    </ControlTransportProvider>,
  );
}

function sessionRecord(id: string, title: string, overrides: Record<string, unknown> = {}) {
  return {
    id,
    title,
    mode: 'assistant',
    status: 'idle',
    roleId: 'default',
    roleVersion: '1',
    roleBookRevisionId: 'r1',
    updatedAtMs: NOW - 60_000,
    workspaceRoots: [],
    ...overrides,
  };
}
