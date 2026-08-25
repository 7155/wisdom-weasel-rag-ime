import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { PawFieldLede } from './PawFieldLede';
import ledeSource from './PawFieldLede.tsx?raw';

afterEach(cleanup);

describe('Project Field lede', () => {
  it('states what the machine is for in real product nouns and offers one way in', () => {
    const onOpen = vi.fn();
    const { container } = render(<PawFieldLede onOpen={onOpen} />);

    // The heading claims the outcome; the sentence under it names the things
    // the product actually has — a Session, its receipts, the two governed
    // stores — instead of generic workspace copy.
    const heading = screen.getByRole('heading', { level: 2 });
    expect(heading).toHaveTextContent('做过的事，下次不用重讲。');
    // The heading must not repeat the Agent home title the button leads to;
    // the two lines are one path, not an echo.
    expect(heading.textContent).not.toContain('交给 Agent');
    const copy = container.querySelector('.paw-field-lede__copy');
    for (const noun of ['Session', '回执', '记忆与知识', '上下文']) {
      expect(copy).toHaveTextContent(noun);
    }
    // Emphasis is spent on the three real things on that path, nothing else.
    expect([...container.querySelectorAll('.paw-field-lede__copy b')].map((node) => node.textContent))
      .toEqual(['回执', '记忆与知识', '上下文']);

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
