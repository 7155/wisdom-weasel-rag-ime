import type { ReactNode } from 'react';
import { AppShell } from '@/components/layout';
import { PawOsShell } from '@/components/paw-os';
import type { FrontendProduct } from './frontend-product';

export function FrontendShell({
  children,
  product,
}: {
  children: ReactNode;
  product: FrontendProduct;
}) {
  return product === 'paw-os'
    ? <PawOsShell>{children}</PawOsShell>
    : <AppShell>{children}</AppShell>;
}
