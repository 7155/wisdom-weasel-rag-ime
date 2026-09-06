import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import { StubControlTransport } from '@/test/stub-control-transport';
import { PawWindowChromeProvider } from '@/paw-os/shell/PawWindowChrome';
import { SatelliteModelBadge } from './SatelliteModelBadge';

afterEach(() => { cleanup(); document.querySelectorAll('[data-test-model-chrome]').forEach((node) => node.remove()); });
const catalog = (sessionId: string, name = 'GPT-5.6 Sol') => ({ schemaVersion: 'rag-ime.agent-model-catalog.v1', ok: true, sessionId, selected: { id: 'gpt-5.6-sol', provider: 'openai-codex', name }, thinkingLevel: 'high', providers: [] });
function harness(sessionId?: string, response = catalog(sessionId ?? ''), inline = false) {
  const transport = new StubControlTransport('mock', { 'agent.session.models': response });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const chrome = document.createElement('header'); chrome.dataset.testModelChrome = 'true'; document.body.append(chrome);
  const rendered = render(<QueryClientProvider client={client}><ControlTransportProvider transport={transport}>
    <PawWindowChromeProvider trailing={chrome}><SatelliteModelBadge sessionId={sessionId} inline={inline} /></PawWindowChromeProvider>
  </ControlTransportProvider></QueryClientProvider>);
  return { transport, client, chrome, ...rendered };
}
describe('satellite model identity', () => {
  it('keeps a selected star model inside its inspector, without writing into another window chrome', async () => {
    const { chrome, container, transport } = harness('selected-star', catalog('selected-star'), true);
    expect(await screen.findByText('GPT-5.6 Sol')).toBeVisible();
    expect(container).toHaveTextContent('GPT-5.6 Sol');
    expect(chrome).toBeEmptyDOMElement();
    expect(transport.requests[0]?.params).toEqual({ sessionId: 'selected-star' });
  });
  it('shows the bound child Session model in its window chrome', async () => {
    const { transport, chrome } = harness('session-child');
    expect(await screen.findByText('GPT-5.6 Sol')).toBeVisible();
    expect(chrome).toHaveTextContent('GPT-5.6 Sol');
    expect(transport.requests).toEqual([expect.objectContaining({ pathId: 'agent.session.models', params: { sessionId: 'session-child' } })]);
  });
  it('does not show a model returned for another Session', async () => {
    const { transport } = harness('session-child', catalog('session-parent', 'Wrong Parent Model'));
    await waitFor(() => expect(transport.requests).toHaveLength(1));
    expect(await screen.findByText('模型未提供')).toBeVisible();
    expect(screen.queryByText('Wrong Parent Model')).not.toBeInTheDocument();
  });
  it('does not ask for the parent or global model when the child binding is absent', () => {
    const { transport } = harness();
    expect(screen.getByText('模型未提供')).toBeVisible();
    expect(transport.requests).toHaveLength(0);
  });
});
