import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import agentCss from '../agent.css?raw';
import {
  DISCLOSURE_MOTION,
  SmoothDisclosureReveal,
} from './SmoothDisclosureReveal';

describe('SmoothDisclosureReveal', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => (
      window.setTimeout(() => callback(performance.now()), 16)
    ));
    vi.stubGlobal('cancelAnimationFrame', (handle: number) => window.clearTimeout(handle));
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function measuredRect(this: HTMLElement) {
      const height = this.classList.contains('agent-smooth-reveal')
        ? Number.parseFloat(this.style.height) || (this.dataset.state === 'open' ? 240 : 0)
        : 240;
      return {
        bottom: height,
        height,
        left: 0,
        right: 320,
        top: 0,
        width: 320,
        x: 0,
        y: 0,
        toJSON: () => ({}),
      };
    });
    Object.defineProperty(HTMLElement.prototype, 'scrollHeight', {
      configurable: true,
      get: () => 240,
    });
  });

  afterEach(() => {
    document.documentElement.removeAttribute('data-reduce-motion');
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it('uses the one calm ease-out disclosure voice that the conversation CSS actually ships', () => {
    // 全对话统一披露动效（agent-deep 定稿）：180ms 平静 ease-out。
    expect(DISCLOSURE_MOTION).toEqual({
      durationMs: 180,
      easing: 'cubic-bezier(0.23, 1, 0.32, 1)',
    });
    // 常量与真实 CSS 不允许悄悄分叉：agent.css 的 reveal 过渡必须使用同一对值。
    expect(agentCss).toContain(
      `height ${DISCLOSURE_MOTION.durationMs}ms ${DISCLOSURE_MOTION.easing}`,
    );
  });

  it('keeps closing content mounted, supports reversal, and removes it only after exit', async () => {
    const view = render(
      <SmoothDisclosureReveal id="evidence" open={false}>
        <p>真实工具证据</p>
      </SmoothDisclosureReveal>,
    );
    const region = document.getElementById('evidence')!;
    expect(region).toHaveAttribute('aria-hidden', 'true');
    expect(region).toHaveAttribute('data-state', 'closed');
    expect(screen.queryByText('真实工具证据')).not.toBeInTheDocument();

    view.rerender(
      <SmoothDisclosureReveal id="evidence" open>
        <p>真实工具证据</p>
      </SmoothDisclosureReveal>,
    );
    await act(async () => { vi.advanceTimersByTime(17); });
    expect(region).toHaveAttribute('aria-hidden', 'false');
    expect(region).toHaveAttribute('data-state', 'opening');
    expect(screen.getByText('真实工具证据')).toBeInTheDocument();
    fireEvent.transitionEnd(region, { propertyName: 'height' });
    expect(region).toHaveAttribute('data-state', 'open');

    view.rerender(
      <SmoothDisclosureReveal id="evidence" open={false}>
        <p>真实工具证据</p>
      </SmoothDisclosureReveal>,
    );
    await act(async () => { vi.advanceTimersByTime(17); });
    expect(region).toHaveAttribute('aria-hidden', 'true');
    expect(region).toHaveAttribute('data-state', 'closing');
    expect(screen.getByText('真实工具证据')).toBeInTheDocument();

    view.rerender(
      <SmoothDisclosureReveal id="evidence" open>
        <p>真实工具证据</p>
      </SmoothDisclosureReveal>,
    );
    await act(async () => { vi.advanceTimersByTime(17); });
    expect(region).toHaveAttribute('aria-hidden', 'false');
    expect(region).toHaveAttribute('data-state', 'opening');
    expect(screen.getByText('真实工具证据')).toBeInTheDocument();

    view.rerender(
      <SmoothDisclosureReveal id="evidence" open={false}>
        <p>真实工具证据</p>
      </SmoothDisclosureReveal>,
    );
    await act(async () => { vi.advanceTimersByTime(17); });
    fireEvent.transitionEnd(region, { propertyName: 'height' });
    expect(region).toHaveAttribute('data-state', 'closed');
    expect(screen.queryByText('真实工具证据')).not.toBeInTheDocument();
  });

  it('uses an immediate height path when motion is reduced', () => {
    document.documentElement.dataset.reduceMotion = 'true';
    const view = render(
      <SmoothDisclosureReveal id="reduced" open>
        <p>简化动画内容</p>
      </SmoothDisclosureReveal>,
    );
    const region = document.getElementById('reduced')!;
    expect(region).toHaveAttribute('data-state', 'open');
    expect(region).toHaveStyle({ height: 'auto' });

    view.rerender(
      <SmoothDisclosureReveal id="reduced" open={false}>
        <p>简化动画内容</p>
      </SmoothDisclosureReveal>,
    );
    expect(region).toHaveAttribute('data-state', 'closed');
    expect(screen.queryByText('简化动画内容')).not.toBeInTheDocument();
  });
});
