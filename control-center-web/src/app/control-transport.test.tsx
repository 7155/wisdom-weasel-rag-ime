import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import {
  ControlTransportProvider,
  createConfiguredControlTransport,
  useControlTransport,
} from '@/app/control-transport';

function Probe() {
  const transport = useControlTransport();
  return <output>{transport.kind}</output>;
}

describe('ControlTransportProvider', () => {
  it('provides the preview transport when no native bridge is present', () => {
    render(
      <ControlTransportProvider>
        <Probe />
      </ControlTransportProvider>,
    );
    expect(screen.getByText('mock')).toBeInTheDocument();
  });

  it('keeps the preview memory surface representative and contract-valid', async () => {
    const transport = createConfiguredControlTransport();
    const summary = await transport.request<Record<string, unknown>>({ pathId: 'memory.summary' });
    const apps = await transport.request<Record<string, unknown>>({
      pathId: 'memory.pages',
      params: { kind: 'apps' },
      query: { limit: 50, cursor: '' },
    });
    const graph = await transport.request<Record<string, unknown>>({
      pathId: 'memory.graph.get',
      query: { plane: 'tags' },
    });
    const entity = await transport.request<Record<string, unknown>>({
      pathId: 'memory.entity.get',
      params: { kind: 'tag', entityId: 'agent-runtime' },
      query: { connectionsLimit: 40, membersLimit: 40 },
    });
    const status = await transport.request<Record<string, unknown>>({
      pathId: 'agent.memoryMaintenance.run',
      query: { limit: 12 },
    });

    expect(summary).toMatchObject({ appCount: 4, blockedFragmentCount: 4_887 });
    expect(apps.items).toEqual(expect.arrayContaining([
      expect.objectContaining({ id: 'com.openai.codex' }),
    ]));
    expect(JSON.stringify(apps.items)).not.toContain('rawText');
    expect(graph).toMatchObject({ schemaVersion: 'rag-ime.memory-graph.v1', plane: 'tags' });
    expect(entity).toMatchObject({ schemaVersion: 'rag-ime.memory-entity.v1', entityId: 'agent-runtime' });
    expect(status).toMatchObject({ pendingDraftCount: 1 });
  });
});
