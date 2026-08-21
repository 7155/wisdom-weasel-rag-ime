import { cleanup, render, screen } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/components/layout', () => ({
  AppShell: ({ children }: { children: ReactNode }) => (
    <section data-testid="legacy-shell">{children}</section>
  ),
}));

vi.mock('@/components/paw-os', () => ({
  PawOsShell: ({ children }: { children: ReactNode }) => (
    <section data-testid="paw-os-shell">{children}</section>
  ),
}));

import { FrontendShell } from './FrontendShell';

afterEach(cleanup);

describe('FrontendShell', () => {
  it('keeps the existing Control Center shell available as the legacy product', () => {
    render(<FrontendShell product="legacy"><p>shared route</p></FrontendShell>);

    expect(screen.getByTestId('legacy-shell')).toHaveTextContent('shared route');
    expect(screen.queryByTestId('paw-os-shell')).not.toBeInTheDocument();
  });

  it('projects the same routed content through the PAWOS shell', () => {
    render(<FrontendShell product="paw-os"><p>shared route</p></FrontendShell>);

    expect(screen.getByTestId('paw-os-shell')).toHaveTextContent('shared route');
    expect(screen.queryByTestId('legacy-shell')).not.toBeInTheDocument();
  });
});
