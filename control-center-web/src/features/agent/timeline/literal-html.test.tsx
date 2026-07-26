import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { MarkdownBody } from './MarkdownRenderer';

afterEach(cleanup);

/**
 * The transcript renders assistant prose; it is never an HTML renderer. Raw
 * markup has to survive as readable text — dropping it loses what the agent
 * was quoting — while never becoming live nodes.
 */
describe('raw HTML inside assistant prose', () => {
  it('shows the markup as literal text instead of dropping it', () => {
    const { container } = render(<MarkdownBody text={'看这段：\n\n<script>alert(1)</script>\n\n结束'} />);
    expect(container.textContent).toContain('<script>alert(1)</script>');
    expect(screen.getByText(/结束/u)).toBeInTheDocument();
  });

  it('never turns the markup into live elements', () => {
    const { container } = render(
      <MarkdownBody text={'<script>window.__leak = true;</script><img src="x" onerror="window.__leak = true">'} />,
    );
    expect(container.querySelector('script')).toBeNull();
    expect(container.querySelector('img')).toBeNull();
    expect((window as unknown as { __leak?: boolean }).__leak).toBeUndefined();
  });

  it('keeps ordinary markdown working alongside it', () => {
    const { container } = render(<MarkdownBody text={'**粗体** 与 `代码`，还有 <b>标签</b>。'} />);
    expect(container.querySelector('strong')?.textContent).toBe('粗体');
    expect(container.querySelector('code')?.textContent).toBe('代码');
    // The <b> is shown, not applied.
    expect(container.querySelector('b')).toBeNull();
    expect(container.textContent).toContain('<b>标签</b>');
  });
});
