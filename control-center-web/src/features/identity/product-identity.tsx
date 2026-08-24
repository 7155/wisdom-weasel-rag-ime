import { useQuery } from '@tanstack/react-query';
import {
  createContext,
  useContext,
  useMemo,
  type ReactNode,
} from 'react';
import { useControlTransport } from '@/app/control-transport';
import { configurationQueryKeys } from '@/features/configuration/api';

export type ProductIdentity = {
  productName: string;
  assistantName: string;
  tagline: string;
};

export const defaultProductIdentity: ProductIdentity = {
  productName: 'PAW',
  assistantName: 'Agent',
  tagline: '记得你，也陪你做事',
};

const ProductIdentityContext = createContext<ProductIdentity>(defaultProductIdentity);

export function ProductIdentityProvider({ children }: { children: ReactNode }) {
  const transport = useControlTransport();
  const settings = useQuery({
    queryKey: configurationQueryKeys.settings(),
    queryFn: ({ signal }) => transport.request({ pathId: 'configuration.settings', signal }),
    retry: false,
    staleTime: 30_000,
  });
  const identity = useMemo(
    () => productIdentityFromSettings(settings.data),
    [settings.data],
  );

  return (
    <ProductIdentityContext.Provider value={identity}>
      {children}
    </ProductIdentityContext.Provider>
  );
}

export function useProductIdentity(): ProductIdentity {
  return useContext(ProductIdentityContext);
}

export function productIdentityFromSettings(value: unknown): ProductIdentity {
  const envelope = recordValue(value);
  const settings = recordValue(envelope.settings);
  const identity = recordValue(settings.identity);
  return {
    productName: boundedName(identity.productName, defaultProductIdentity.productName, 24),
    assistantName: boundedName(identity.assistantName, defaultProductIdentity.assistantName, 24),
    tagline: boundedName(identity.tagline, defaultProductIdentity.tagline, 48),
  };
}

function boundedName(value: unknown, fallback: string, maximumLength: number): string {
  if (typeof value !== 'string') return fallback;
  const normalized = value.trim();
  return normalized && normalized.length <= maximumLength ? normalized : fallback;
}

function recordValue(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}
