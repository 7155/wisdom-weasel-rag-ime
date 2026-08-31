import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import { PawOsDesktopProvider } from '@/features/paw-os/surface-context';
import type { ControlRequest } from '@/platform/transport';
import { MockControlTransport, type MockControlTransportOptions } from '@/test/mock-transport';
import {
  collectEvidenceEchoUsage,
  evidenceEchoFocusFromRoute,
  evidenceEchoNodeEntities,
  evidenceEchoRoute,
  evidenceEchoSessionRoute,
  openEvidenceEchoEntity,
} from './evidence-echo';
import { EvidenceEchoUsage } from './EvidenceEchoUsage';
import evidenceEchoCss from './evidence-echo.css?raw';

afterEach(cleanup);

describe('evidenceEchoNodeEntities', () => {
  it('keeps the shared refresh control large enough to target reliably', () => {
    expect(evidenceEchoCss).toMatch(/\.evidence-echo-usage__refresh\s*\{[^}]*width:\s*32px;[^}]*height:\s*32px;/s);
  });

  it('resolves only the flat reference keys a trace node can actually carry', () => {
    expect(evidenceEchoNodeEntities(traceNode({
      memoryBookId: 'book-provider-context',
      memoryAtomIds: 'atom-context-order, atom-foreground',
      knowledgeDocumentId: 'doc-9',
      knowledgeBaseId: 'kb-1',
      workspaceFile: '/work/paw/README.md',
      browserUrl: 'https://example.test/spec',
    }), { sessionId: 'session-a' })).toEqual([
      { appId: 'memory', entityId: 'atom-context-order', label: 'atom-context-order', layer: 'atoms' },
      { appId: 'memory', entityId: 'atom-foreground', label: 'atom-foreground', layer: 'atoms' },
      { appId: 'memory', entityId: 'book-provider-context', label: 'book-provider-context', layer: 'books' },
      { appId: 'knowledge', entityId: 'doc-9', label: 'doc-9', baseId: 'kb-1' },
      { appId: 'files', entityId: '/work/paw/README.md', label: 'README.md', sessionId: 'session-a' },
      { appId: 'browser', entityId: 'https://example.test/spec', label: 'example.test' },
    ]);
  });

  it('resolves nothing for a node that records no concrete entity', () => {
    expect(evidenceEchoNodeEntities(traceNode({ itemCount: 3, priority: 'developer' }))).toEqual([]);
    expect(evidenceEchoNodeEntities(undefined)).toEqual([]);
  });

  it('refuses values the Runtime sanitizer already destroyed', () => {
    // `_public_text` rewrites /Users, /Volumes, /private and /tmp paths, so
    // what arrives is prose, not something Files or Browser could open.
    expect(evidenceEchoNodeEntities(traceNode({
      workspaceFile: '本地资源',
      browserUrl: '本地资源',
    }))).toEqual([]);
  });
});

describe('evidence echo routes', () => {
  it('routes each entity to the App surface that owns it', () => {
    expect(evidenceEchoRoute({ appId: 'memory', entityId: 'atom 1', label: '', layer: 'atoms' }))
      .toBe('/memory?layer=atoms&id=atom%201');
    expect(evidenceEchoRoute({ appId: 'knowledge', entityId: 'doc-9', label: '', baseId: 'kb-1' }))
      .toBe('/knowledge?base=kb-1&document=doc-9&tab=viewer');
    expect(evidenceEchoRoute({ appId: 'files', entityId: '/work/paw/README.md', label: '', sessionId: 'session-a' }))
      .toBe('/files?session=session-a&path=%2Fwork%2Fpaw%2FREADME.md');
    expect(evidenceEchoRoute({ appId: 'browser', entityId: 'https://example.test/', label: '' })).toBe('');
  });

  it('carries the trace node identity into and out of the Agent App route', () => {
    const route = evidenceEchoSessionRoute({ sessionId: 'session-a', traceId: 'trace-a', nodeId: 'node:4' });
    expect(route).toBe('/agent?session=session-a&trace=trace-a&node=node%3A4');
    expect(evidenceEchoFocusFromRoute(route)).toEqual({ traceId: 'trace-a', nodeId: 'node:4' });
    expect(evidenceEchoFocusFromRoute('/agent?session=session-a')).toBeUndefined();
  });

  it('opens a memory entity through the desktop route and a page through its own window', () => {
    const openRoute = vi.fn();
    const openWindow = vi.fn();
    const desktop = { openRoute, openWindow };

    openEvidenceEchoEntity(desktop, { appId: 'memory', entityId: 'atom-1', label: 'atom-1', layer: 'atoms' });
    expect(openRoute).toHaveBeenCalledWith('/memory?layer=atoms&id=atom-1');

    openEvidenceEchoEntity(desktop, { appId: 'browser', entityId: 'https://example.test/spec', label: 'example.test' });
    expect(openWindow).toHaveBeenCalledWith(expect.objectContaining({
      appId: 'browser',
      target: expect.objectContaining({ kind: 'browser-target', id: 'https://example.test/spec', url: 'https://example.test/spec' }),
    }));
  });
});

describe('collectEvidenceEchoUsage', () => {
  it('projects the Sessions that assembled an entity out of existing trace reads', async () => {
    const usage = await collectEvidenceEchoUsage(usageTransport(), { appId: 'memory', entityId: 'atom-context-order' });

    expect(usage.partial).toBe(false);
    expect(usage.scannedSessionCount).toBe(2);
    expect(usage.scannedTraceCount).toBe(2);
    expect(usage.rows).toEqual([{
      sessionId: 'session-a',
      sessionTitle: '核对 Provider 上下文顺序',
      traceId: 'trace-a',
      turnId: 'turn-a',
      nodeId: 'node:memory',
      nodeLabel: '个人记忆召回',
      disposition: 'included',
      atMs: 1_200,
    }]);
  });

  it('reports a trace it could not read as partial instead of dropping the block', async () => {
    const transport = usageTransport({
      'agent.session.contextTrace.get': () => {
        throw new Error('trace unavailable');
      },
    });

    const usage = await collectEvidenceEchoUsage(transport, { appId: 'memory', entityId: 'atom-context-order' });
    expect(usage.rows).toEqual([]);
    expect(usage.partial).toBe(true);
  });
});

describe('EvidenceEchoUsage', () => {
  it('lists the assembling Sessions and lands a click on the matching trace node', async () => {
    const openRoute = vi.fn();
    const user = userEvent.setup();

    render(
      <ControlTransportProvider transport={usageTransport()}>
        <PawOsDesktopProvider openRoute={openRoute} openWindow={() => {}}>
          <EvidenceEchoUsage appId="memory" entityId="atom-context-order" entityLabel="上下文顺序" />
        </PawOsDesktopProvider>
      </ControlTransportProvider>,
    );

    const row = await screen.findByRole('button', { name: '打开 核对 Provider 上下文顺序，定位到装配节点 个人记忆召回' });
    await user.click(row);
    expect(openRoute).toHaveBeenCalledWith('/agent?session=session-a&trace=trace-a&node=node%3Amemory');
  });

  it('says plainly that nothing assembled this entity rather than showing an empty list', async () => {
    render(
      <ControlTransportProvider transport={usageTransport()}>
        <PawOsDesktopProvider openWindow={() => {}}>
          <EvidenceEchoUsage appId="memory" entityId="atom-never-used" />
        </PawOsDesktopProvider>
      </ControlTransportProvider>,
    );

    expect(await screen.findByText('最近 2 段 Session 的 2 次上下文装配里没有用到这一条。')).toBeInTheDocument();
    expect(screen.queryByRole('list')).not.toBeInTheDocument();
  });
});

function traceNode(metadata: Record<string, unknown>) {
  return {
    nodeId: 'node:test',
    ordinal: 1,
    stage: 'memory_recall',
    label: '个人记忆召回',
    sourceKind: 'memory_bootstrap',
    disposition: 'included' as const,
    summary: '',
    charCount: 0,
    tokenEstimate: 0,
    durationMs: 0,
    fingerprint: '',
    reason: '',
    metadata,
    createdAtMs: 1_000,
  };
}

function usageTransport(overrides: MockControlTransportOptions['routes'] = {}) {
  return new MockControlTransport({
    routes: {
      'agent.sessions.list': {
        ok: true,
        sessions: [
          { id: 'session-a', title: '核对 Provider 上下文顺序', roleId: 'engineer', updatedAtMs: 2_000 },
          { id: 'session-b', title: '检查发布门禁', roleId: 'engineer', updatedAtMs: 1_000 },
        ],
      },
      'agent.session.contextTraces.list': (request: ControlRequest) => ({
        ok: true,
        items: request.params?.sessionId === 'session-a'
          ? [{ traceId: 'trace-a', sessionId: 'session-a', turnId: 'turn-a', createdAtMs: 1_100 }]
          : [{ traceId: 'trace-b', sessionId: 'session-b', turnId: 'turn-b', createdAtMs: 900 }],
      }),
      'agent.session.contextTrace.get': (request: ControlRequest) => (
        String(request.params?.traceId) === 'trace-a'
          ? contextTrace('session-a', 'trace-a', 'turn-a', { memoryAtomIds: 'atom-context-order' }, 1_200)
          : contextTrace('session-b', 'trace-b', 'turn-b', { itemCount: 0 }, 950)
      ),
      ...overrides,
    },
  });
}

function contextTrace(
  sessionId: string,
  traceId: string,
  turnId: string,
  metadata: Record<string, unknown>,
  createdAtMs: number,
) {
  return {
    schemaVersion: 'rag-ime.agent-context-trace.v1',
    traceId,
    sessionId,
    turnId,
    sourceKind: 'user',
    status: 'accepted',
    finalFingerprint: 'sha256:0123456789abcdef',
    nodes: [{ ...traceNode(metadata), nodeId: 'node:memory', createdAtMs }],
    edges: [],
    createdAtMs,
    updatedAtMs: createdAtMs,
  };
}
