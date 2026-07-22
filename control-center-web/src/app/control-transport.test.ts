import { describe, expect, it } from 'vitest';
import { createConfiguredControlTransport } from './control-transport';

describe('preview control transport', () => {
  it('keeps Room member Sessions internal and exposes canonical working tools', async () => {
    const transport = createConfiguredControlTransport();

    const publicSessions = await transport.request<{ sessions: Record<string, unknown>[] }>({
      pathId: 'agent.sessions.list',
      query: { includeInternal: false },
    });
    const roomSessions = await transport.request<{ sessions: Record<string, unknown>[] }>({
      pathId: 'agent.sessions.list',
      query: { includeInternal: true },
    });
    const tools = await transport.request<{ items: Record<string, unknown>[] }>({
      pathId: 'agent.tools.list',
      query: { sessionId: 'session-room-present' },
    });

    expect(publicSessions.sessions.some((session) => session.id === 'session-room-present')).toBe(false);
    expect(roomSessions.sessions).toEqual(expect.arrayContaining([
      expect.objectContaining({
        id: 'session-room-present',
        mode: 'coordinator',
        workspaceRoots: ['/Volumes/work/wisdom-weasel-rag-ime'],
      }),
    ]));
    expect(tools.items).toEqual(expect.arrayContaining([
      expect.objectContaining({ id: 'ime_overview', enabled: true }),
      expect.objectContaining({ id: 'workspace_read', enabled: true }),
      expect.objectContaining({ id: 'workspace_shell', enabled: true }),
    ]));
    expect(tools.items.some((tool) => tool.id === 'control.overview')).toBe(false);
  });

  it('demonstrates owner-scoped evidence and reversible forgetting', async () => {
    const transport = createConfiguredControlTransport();

    const summary = await transport.request<Record<string, unknown>>({
      pathId: 'memory.summary',
    });
    const before = await transport.request<{ items: Record<string, unknown>[] }>({
      pathId: 'memory.pages',
      params: { kind: 'evidence' },
      query: { limit: 50, cursor: '' },
    });
    await transport.request({
      pathId: 'memory.source.disposition',
      body: {
        sourceId: 'event:10001',
        disposition: 'pending',
      },
    });
    const after = await transport.request<{ items: Record<string, unknown>[] }>({
      pathId: 'memory.pages',
      params: { kind: 'evidence' },
      query: { limit: 50, cursor: '' },
    });

    expect(summary.owners).toEqual(expect.arrayContaining([
      expect.objectContaining({ ownerKind: 'user', ownerId: 'default' }),
      expect.objectContaining({ ownerKind: 'agent', ownerId: 'companion-present-v1' }),
    ]));
    expect(before.items.find((item) => item.id === 'event:10001')).toMatchObject({
      id: 'event:10001',
      disposition: 'not_for_memory',
    });
    expect(after.items.find((item) => item.id === 'event:10001')).toMatchObject({
      id: 'event:10001',
      disposition: 'pending',
    });
  });
});
