import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { MarkdownBody } from './MarkdownRenderer';

afterEach(cleanup);

describe('model-authored HTML inside assistant replies', () => {
  it('renders a standalone HTML document in place and keeps a source toggle', () => {
    const source = '<!doctype html><html><body><h1>项目报告</h1><script>document.body.dataset.ready="yes"</script></body></html>';
    render(<MarkdownBody text={source} />);

    const frame = screen.getByTitle('HTML 输出预览');
    expect(frame.getAttribute('sandbox')).toContain('allow-scripts');
    expect(frame.getAttribute('src')).toMatch(/^blob:/u);
    expect(frame).not.toHaveAttribute('srcdoc');

    fireEvent.click(screen.getByRole('button', { name: '查看 HTML 源码' }));
    expect(screen.getByText(source)).toBeInTheDocument();
  });

  it('replaces a completed fenced HTML block at its Markdown position', () => {
    render(
      <MarkdownBody text={'上方说明。\n\n```html\n<section><strong>富文本卡片</strong></section>\n```\n\n下方说明。'} />,
    );

    expect(screen.getByText('上方说明。')).toBeInTheDocument();
    expect(screen.getByText('下方说明。')).toBeInTheDocument();
    const frame = screen.getByTitle('HTML 输出预览');
    expect(frame.getAttribute('src')).toMatch(/^blob:/u);
    expect(screen.queryByText(/<section>/u)).not.toBeInTheDocument();
  });

  it('renders multiple fenced HTML blocks independently', () => {
    render(
      <MarkdownBody text={'```html\n<div>第一块</div>\n```\n\n中间文字\n\n```html\n<div>第二块</div>\n```'} />,
    );

    const frames = screen.getAllByTitle('HTML 输出预览');
    expect(frames).toHaveLength(2);
    expect(frames[0]?.getAttribute('src')).toMatch(/^blob:/u);
    expect(frames[1]?.getAttribute('src')).toMatch(/^blob:/u);
    expect(frames[0]?.getAttribute('src')).not.toBe(frames[1]?.getAttribute('src'));
  });

  it('shows a stable placeholder instead of rebuilding an incomplete streaming document', () => {
    render(<MarkdownBody streamingTail text={'<!doctype html><html><body><h1>仍在生成'} />);
    expect(screen.getByRole('status')).toHaveTextContent('正在生成 HTML 预览');
    expect(screen.queryByTitle('HTML 输出预览')).not.toBeInTheDocument();
  });

  it('renders a fenced HTML block as soon as its closing fence streams in', () => {
    render(
      <MarkdownBody
        streamingTail
        text={'正在生成卡片。\n\n```html\n<section><strong>流式富文本已就绪</strong></section>\n```'}
      />,
    );

    const frame = screen.getByTitle('HTML 输出预览');
    expect(frame.getAttribute('src')).toMatch(/^blob:/u);
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('keeps ordinary Markdown and quoted inline tags readable', () => {
    const { container } = render(<MarkdownBody text={'**粗体** 与 `代码`，还有 <b>标签</b>。'} />);
    expect(container.querySelector('strong')?.textContent).toBe('粗体');
    expect(container.querySelector('code')?.textContent).toBe('代码');
    expect(container.querySelector('b')).toBeNull();
    expect(container.textContent).toContain('<b>标签</b>');
  });
});
