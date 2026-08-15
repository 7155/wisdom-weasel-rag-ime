import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { AppErrorBoundary } from './AppErrorBoundary';

function BrokenSurface(): never {
  throw new Error('private render detail');
}

describe('AppErrorBoundary', () => {
  afterEach(() => vi.restoreAllMocks());

  it('keeps provider and shell render failures inside a reload surface', () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined);

    render(
      <AppErrorBoundary>
        <BrokenSurface />
      </AppErrorBoundary>,
    );

    expect(screen.getByRole('heading', { name: '工作台需要重新载入' })).toBeInTheDocument();
    expect(screen.queryByText('private render detail')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '重新载入' })).toHaveFocus();
  });
});
