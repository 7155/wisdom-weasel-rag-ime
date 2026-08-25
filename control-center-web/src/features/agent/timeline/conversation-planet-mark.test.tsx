import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import agentCss from '../agent.css?raw';
import { ConversationPlanetMark, type ConversationPlanetState } from './ConversationPlanetMark';

describe('ConversationPlanetMark', () => {
  it('gives every live state an orbit and keeps settled states still', () => {
    const orbitFor = (state: ConversationPlanetState) => {
      const { container } = render(<ConversationPlanetMark state={state} />);
      const mark = container.querySelector(`.paw-conv-planet[data-state="${state}"]`);
      expect(mark, state).toBeTruthy();
      expect(mark!.querySelector('.paw-conv-planet__body'), state).toBeTruthy();
      return mark!.querySelector('.paw-conv-planet__orbit');
    };

    for (const state of ['thinking', 'running', 'waiting'] as const) {
      expect(orbitFor(state), state).toBeTruthy();
    }
    for (const state of ['idle', 'done', 'failed'] as const) {
      expect(orbitFor(state), state).toBeNull();
    }
  });

  it('marks a live state for assistive technology only when it carries its own label', () => {
    const { container, rerender } = render(<ConversationPlanetMark state="running" />);
    const decorative = container.querySelector('.paw-conv-planet')!;
    expect(decorative).toHaveAttribute('aria-hidden', 'true');
    expect(decorative).not.toHaveAttribute('role');
    expect(decorative).toHaveAttribute('data-live', 'true');

    rerender(<ConversationPlanetMark label="正在执行工具" size="sm" state="running" />);
    const labelled = container.querySelector('.paw-conv-planet[data-size="sm"]')!;
    expect(labelled).toHaveAttribute('role', 'img');
    expect(labelled).toHaveAttribute('aria-label', '正在执行工具');
    expect(labelled).not.toHaveAttribute('aria-hidden');
  });

  it('carries its own size scale so a pill dot and a thinking bar share one body', () => {
    const sizeOf = (props: Partial<{ size: 'sm' | 'md' | 'lg' }>) => {
      const { container } = render(<ConversationPlanetMark state="thinking" {...props} />);
      return container.querySelector('.paw-conv-planet')!.getAttribute('data-size');
    };
    expect(sizeOf({})).toBe('md');
    expect(sizeOf({ size: 'sm' })).toBe('sm');
    expect(sizeOf({ size: 'lg' })).toBe('lg');
  });

  it('keeps the shared planet pulse in the Agent owner and stops it under reduced motion', () => {
    // The vendored conversation surface pulses its thinking dot at 1.2s; the
    // running planet holds that rhythm so both surfaces read as one product.
    expect(agentCss).toMatch(
      /\.paw-conv-planet\[data-state='running'\] \.paw-conv-planet__body \{ animation: paw-conv-planet-breathe 1\.2s/,
    );
    expect(agentCss).toContain('@keyframes paw-conv-planet-orbit');
    expect(agentCss).toMatch(
      /@media \(prefers-reduced-motion: reduce\) \{\s*\.paw-conv-planet__body,\s*\.paw-conv-planet__orbit \{ animation: none; \}/,
    );
    expect(agentCss).toContain(":root[data-reduce-motion='true'] .paw-conv-planet__orbit { animation: none; }");
  });
});
