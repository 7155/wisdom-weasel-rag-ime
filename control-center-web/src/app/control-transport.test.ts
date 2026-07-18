import { describe, expect, it } from 'vitest';
import { createConfiguredControlTransport } from './control-transport';

describe('preview control transport', () => {
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
      expect.objectContaining({ ownerKind: 'agent', ownerId: 'zhiyou-v1' }),
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
