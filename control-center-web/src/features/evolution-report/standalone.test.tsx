import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { StandaloneEvolutionReportPage } from './standalone';

afterEach(cleanup);

describe('StandaloneEvolutionReportPage', () => {
  it('renders the report as a web document without PAWOS desktop or window chrome', () => {
    render(<StandaloneEvolutionReportPage />);

    expect(screen.getByTestId('standalone-evolution-report')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '返回 PAW' })).toHaveAttribute(
      'href',
      '/?frontend=paw-os#/project-field',
    );
    expect(document.querySelector('.paw-desktop-root')).toBeNull();
    expect(document.querySelector('.paw-system-app')).toBeNull();
    expect(document.querySelector('[data-paw-os-app]')).toBeNull();
  });

  it('uses document scrolling for chapter navigation', async () => {
    const user = userEvent.setup();
    render(<StandaloneEvolutionReportPage />);
    const target = document.getElementById('cloudops')!;
    const scrollIntoView = vi.fn();
    Object.defineProperty(target, 'scrollIntoView', {
      configurable: true,
      value: scrollIntoView,
    });

    await user.click(screen.getByRole('button', { name: 'CloudOps' }));

    expect(scrollIntoView).toHaveBeenCalledWith({ behavior: 'auto', block: 'start' });
  });
});
