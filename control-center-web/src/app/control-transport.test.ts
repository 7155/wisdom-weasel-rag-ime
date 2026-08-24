import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { createConfiguredControlTransport } from './control-transport';

describe('preview control transport', () => {
  const originalUrl = window.location.href;

  beforeEach(() => {
    window.history.replaceState({}, '', '/?controlTransport=mock#/preview-control-transport-tests');
  });

  afterEach(() => {
    window.history.replaceState({}, '', originalUrl);
  });

  it('keeps Room member Sessions available for direct Agent chat and exposes canonical working tools', async () => {
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

    expect(publicSessions.sessions).toEqual(expect.arrayContaining([
      expect.objectContaining({
        id: 'session-room-present',
        mode: 'coordinator',
        workspaceRoots: ['/Volumes/work/wisdom-weasel-rag-ime'],
      }),
    ]));
    expect(roomSessions.sessions).toEqual(expect.arrayContaining([
      expect.objectContaining({
        id: 'session-room-present',
        mode: 'coordinator',
        workspaceRoots: ['/Volumes/work/wisdom-weasel-rag-ime'],
      }),
    ]));
    expect(tools.items).toEqual(expect.arrayContaining([
      expect.objectContaining({ id: 'overview', enabled: true }),
      expect.objectContaining({ id: 'ask', enabled: true, alwaysAvailable: true }),
      expect.objectContaining({ id: 'todo', enabled: true, alwaysAvailable: true }),
      expect.objectContaining({ id: 'workspace_lsp', enabled: true }),
      expect.objectContaining({ id: 'workspace_job', enabled: true }),
    ]));
    expect(tools.items.some((tool) => [
      'workspace_read',
      'workspace_search',
      'workspace_edit',
      'workspace_shell',
    ].includes(String(tool.id)))).toBe(false);
    expect(tools.items.some((tool) => tool.id === 'control.overview')).toBe(false);
  });

  it('exposes only unified input-method, voice, and Agent-captured memory evidence', async () => {
    const transport = createConfiguredControlTransport();

    const summary = await transport.request<Record<string, unknown>>({
      pathId: 'memory.summary',
    });
    const page = await transport.request<{ items: Record<string, unknown>[] }>({
      pathId: 'memory.pages',
      params: { kind: 'evidence' },
      query: { limit: 50, cursor: '' },
    });

    expect(summary.owners).toEqual(expect.arrayContaining([
      expect.objectContaining({ ownerKind: 'user', ownerId: 'default' }),
      expect.objectContaining({ ownerKind: 'agent', ownerId: 'companion-present-v1' }),
    ]));
    expect(summary.memoryEvidenceCount).toBe(3);
    expect(page.items.map((item) => item.sourceChannel)).toEqual([
      'input_method',
      'voice',
      'agent_capture',
    ]);
    expect(JSON.stringify(page)).not.toContain('reviewed_non_durable_source');
    expect(JSON.stringify(page)).not.toContain('命令执行完成');
  });

  it('keeps preview model and reasoning selections consistent with the next catalog read', async () => {
    const transport = createConfiguredControlTransport();

    await transport.request({
      pathId: 'agent.session.model.select',
      params: { sessionId: 'session-preview' },
      body: { provider: 'openai', modelId: 'gpt-5.4-mini' },
    });
    await transport.request({
      pathId: 'agent.session.thinking.select',
      params: { sessionId: 'session-preview' },
      body: { level: 'high' },
    });
    const catalog = await transport.request<Record<string, unknown>>({
      pathId: 'agent.session.models',
      params: { sessionId: 'session-preview' },
    });

    expect(catalog.selected).toMatchObject({
      provider: 'openai',
      id: 'gpt-5.4-mini',
    });
    expect(catalog.thinkingLevel).toBe('high');
  });
});
