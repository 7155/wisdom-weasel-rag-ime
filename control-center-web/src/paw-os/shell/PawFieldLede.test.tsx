import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { PawFieldLede } from './PawFieldLede';
import ledeSource from './PawFieldLede.tsx?raw';

afterEach(cleanup);

describe('Project Field lede', () => {
  it('states what the machine is for in real product nouns and offers one way in', () => {
    const onOpen = vi.fn();
    render(<PawFieldLede onOpen={onOpen} />);

    // The first viewport's subject names the things the product actually has
    // — a Session, its receipts, the two governed stores — instead of generic
    // workspace copy.
    const heading = screen.getByRole('heading', { level: 2 });
    expect(heading).toHaveTextContent('交给 Session 一件事。');
    expect(screen.getByText(/回执/)).toHaveTextContent('记忆与知识');
    expect(screen.getByText(/回执/)).toHaveTextContent('上下文');

    // Exactly one action: the desktop is a way into work, never a second
    // place to configure or start it.
    const actions = screen.getAllByRole('button');
    expect(actions).toHaveLength(1);
    fireEvent.click(actions[0]!);
    expect(onOpen).toHaveBeenCalledWith('agent');
  });

  it('claims no runtime state, reads no directory and caches no progress', () => {
    // The lede is a navigation projection. A fetch, a store subscription or a
    // count rendered here would turn the desktop into a second place that
    // believes something about the Runtime.
    expect(ledeSource).not.toMatch(/useControlTransport|usePawDesktopStore|useState|useEffect/);
    expect(ledeSource).not.toMatch(/已连接|运行中|\d+\s*(个|条|段)/);
  });

  it('leaves the bidirectional evidence seam addressable without owning it', () => {
    const { container } = render(<PawFieldLede onOpen={vi.fn()} />);
    expect(container.querySelector('[data-paw-evidence-echo="field-lede"]')).toBeInTheDocument();
  });
});
