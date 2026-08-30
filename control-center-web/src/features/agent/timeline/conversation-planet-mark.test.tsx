import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import agentCss from '../agent.css?raw';
import { ConversationPlanetMark, type ConversationPlanetState } from './ConversationPlanetMark';

describe('ConversationPlanetMark', () => {
  it('keeps one stable mark tree across live and settled state changes', () => {
    const { container, rerender } = render(<ConversationPlanetMark state="thinking" />);
    const mark = container.querySelector('.paw-conv-planet')!;
    const body = mark.querySelector('.paw-conv-planet__body');
    const orbit = mark.querySelector('.paw-conv-planet__orbit');

    expect(mark).toHaveAttribute('data-live', 'true');
    expect(body).toBeTruthy();
    expect(orbit).toBeTruthy();

    for (const state of ['running', 'waiting', 'done', 'failed', 'idle'] as const) {
      rerender(<ConversationPlanetMark state={state} />);
      expect(container.querySelector('.paw-conv-planet')).toBe(mark);
      expect(mark.querySelector('.paw-conv-planet__body'), state).toBe(body);
      expect(mark.querySelector('.paw-conv-planet__orbit'), state).toBe(orbit);
      expect(mark).toHaveAttribute('data-state', state);
    }
    expect(mark).not.toHaveAttribute('data-live');
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

  it('moves only the live status ring and makes reduced motion completely static', () => {
    expect(agentCss).toMatch(/\.paw-conv-planet__body\s*\{[^}]*radial-gradient/s);
    expect(agentCss).toMatch(/\.paw-conv-planet__orbit\s*\{[^}]*conic-gradient[^}]*mask-composite:\s*exclude;/s);
    expect(agentCss).toMatch(
      /\.paw-conv-planet\[data-live='true'\] \.paw-conv-planet__orbit \{[^}]*animation: paw-conv-planet-orbit/,
    );
    expect(agentCss).toContain('@keyframes paw-conv-planet-orbit');
    expect(agentCss).toMatch(
      /@media \(prefers-reduced-motion: reduce\) \{\s*\.paw-conv-planet__orbit \{\s*animation: none;\s*transition: none;/,
    );
    expect(agentCss).toMatch(
      /:root\[data-reduce-motion='true'\] \.paw-conv-planet__orbit \{\s*animation: none;\s*transition: none;/,
    );
  });
});
