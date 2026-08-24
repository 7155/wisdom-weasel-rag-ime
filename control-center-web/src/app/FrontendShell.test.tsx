import { cleanup, render, screen } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/components/layout', () => ({
  AppShell: ({ children }: { children: ReactNode }) => (
    <section data-testid="legacy-shell">{children}</section>
  ),
}));

import { FrontendShell } from './FrontendShell';

afterEach(cleanup);

describe('FrontendShell', () => {
  it('keeps the existing Control Center shell available as the legacy product', () => {
    render(<FrontendShell><p>shared route</p></FrontendShell>);

    expect(screen.getByTestId('legacy-shell')).toHaveTextContent('shared route');
  });
});
