import type { ReactNode } from 'react';
import { AppShell } from '@/components/layout';

export function FrontendShell({
  children,
}: {
  children: ReactNode;
}) {
  return <AppShell>{children}</AppShell>;
}
