import { act, cleanup, render } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import agentCss from '../agent.css?raw';
import { ConversationPlanetMark } from './ConversationPlanetMark';

describe('ConversationPlanetMark', () => {
  afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
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

  it('pauses hidden and offscreen activity without changing authoritative state', () => {
    let intersection: IntersectionObserverCallback | undefined;
    const disconnect = vi.fn();
    vi.stubGlobal('IntersectionObserver', class {
      constructor(callback: IntersectionObserverCallback) { intersection = callback; }
      observe() {}
      disconnect = disconnect;
    });
    const hidden = vi.spyOn(document, 'hidden', 'get').mockReturnValue(false);
    const { container, rerender } = render(<ConversationPlanetMark state="thinking" />);
    const mark = container.querySelector('.paw-conv-planet')!;
    expect(mark).toHaveAttribute('data-motion', 'active');
    act(() => {
      hidden.mockReturnValue(true);
      document.dispatchEvent(new Event('visibilitychange'));
    });
    expect(mark).toHaveAttribute('data-state', 'thinking');
    expect(mark).toHaveAttribute('data-motion', 'paused');
    act(() => {
      hidden.mockReturnValue(false);
      document.dispatchEvent(new Event('visibilitychange'));
    });
    expect(mark).toHaveAttribute('data-motion', 'active');
    act(() => intersection?.([{ isIntersecting: false } as IntersectionObserverEntry], {} as IntersectionObserver));
    expect(mark).toHaveAttribute('data-motion', 'paused');
    act(() => intersection?.([{ isIntersecting: true } as IntersectionObserverEntry], {} as IntersectionObserver));
    expect(mark).toHaveAttribute('data-motion', 'active');
    rerender(<ConversationPlanetMark state="done" />);
    expect(mark).toHaveAttribute('data-motion', 'paused');
    expect(mark).not.toHaveAttribute('data-live');
    expect(disconnect).toHaveBeenCalledTimes(1);
  });

  it('keeps waiting static and lets a collapsed parent pause live work', () => {
    const { container, rerender } = render(<ConversationPlanetMark state="waiting" />);
    const mark = container.querySelector('.paw-conv-planet')!;
    expect(mark).not.toHaveAttribute('data-live');
    rerender(<ConversationPlanetMark state="running" motionActive={false} />);
    expect(mark).toHaveAttribute('data-live', 'true');
    expect(mark).toHaveAttribute('data-motion', 'paused');
  });

  it('shares a still nucleus with distinct spiral and satellite paths and reduced motion', () => {
    const { container } = render(<ConversationPlanetMark state="thinking" />);
    expect(container.querySelector('svg .paw-conv-planet__spiral path')).toBeTruthy();
    expect(container.querySelector('svg .paw-conv-planet__satellites circle')).toBeTruthy();
    expect(agentCss).toContain("[data-state='thinking'] .paw-conv-planet__spiral { display: block; }");
    expect(agentCss).toContain("[data-state='thinking'] .paw-conv-planet__satellites { display: none; }");
    expect(agentCss).toContain("[data-motion='paused'] .paw-conv-planet__orbit { animation-play-state: paused; }");
    expect(agentCss).toContain('@media (prefers-reduced-motion: reduce)');
    expect(agentCss).toContain(".paw-conv-planet[data-live] .paw-conv-planet__orbit { animation: none; }");
    expect(agentCss).toContain(":root[data-reduce-motion='true']");
  });
});
