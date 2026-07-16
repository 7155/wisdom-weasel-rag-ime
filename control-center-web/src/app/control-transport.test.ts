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
        sourceId: 'input-memory:preview-noise',
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
    expect(before.items[0]).toMatchObject({
      id: 'input-memory:preview-noise',
      disposition: 'not_for_memory',
    });
    expect(after.items[0]).toMatchObject({
      id: 'input-memory:preview-noise',
      disposition: 'pending',
    });
  });
});
