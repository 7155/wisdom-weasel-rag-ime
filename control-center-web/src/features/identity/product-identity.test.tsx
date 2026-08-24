import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import { MockControlTransport } from '@/test/mock-transport';
import {
  ProductIdentityProvider,
  defaultProductIdentity,
  productIdentityFromSettings,
  useProductIdentity,
} from './product-identity';

describe('product identity', () => {
  afterEach(cleanup);

  it('reads editable product copy from the shared settings envelope', async () => {
    const transport = new MockControlTransport({
      routes: {
        'configuration.settings': {
          ok: true,
          settings: {
            identity: {
              productName: '记川',
              assistantName: '阿川',
              tagline: '陪你记住，也陪你完成',
            },
          },
        },
      },
    });
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    render(
      <ControlTransportProvider transport={transport}>
        <QueryClientProvider client={client}>
          <ProductIdentityProvider>
            <IdentityProbe />
          </ProductIdentityProvider>
        </QueryClientProvider>
      </ControlTransportProvider>,
    );

    await waitFor(() => expect(screen.getByTestId('product-name')).toHaveTextContent('记川'));
    expect(screen.getByTestId('assistant-name')).toHaveTextContent('阿川');
    expect(screen.getByTestId('tagline')).toHaveTextContent('陪你记住，也陪你完成');
    expect(transport.requests.filter(({ request }) => request.pathId === 'configuration.settings')).toHaveLength(1);
  });

  it('falls back safely for missing, blank, or oversized values', () => {
    expect(productIdentityFromSettings({})).toEqual(defaultProductIdentity);
    expect(productIdentityFromSettings({
      settings: {
        identity: {
          productName: '   ',
          assistantName: '长'.repeat(25),
          tagline: '  仍然在这里  ',
        },
      },
    })).toEqual({
      productName: 'PAW',
      assistantName: 'Agent',
      tagline: '仍然在这里',
    });
  });
});

function IdentityProbe() {
  const identity = useProductIdentity();
  return (
    <>
      <span data-testid="product-name">{identity.productName}</span>
      <span data-testid="assistant-name">{identity.assistantName}</span>
      <span data-testid="tagline">{identity.tagline}</span>
    </>
  );
}
