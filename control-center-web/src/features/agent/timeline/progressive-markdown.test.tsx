import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { TooltipProvider } from '@/components/primitives';
import { MarkdownBody } from './MarkdownRenderer';
import {
  INITIAL_SCAN_STATE,
  scanIncrementalMarkdown,
} from './progressive-markdown';

afterEach(cleanup);

describe('progressive markdown streaming path', () => {
  it('reuses committed chunk objects across append-only scans', () => {
    const first = scanIncrementalMarkdown(
      INITIAL_SCAN_STATE,
      '第一段。\n\n第二段还在生成',
    );
    const second = scanIncrementalMarkdown(
      first,
      '第一段。\n\n第二段还在生成，现在完成。\n\n第三段还在生成',
    );

    expect(first.chunks).toHaveLength(1);
    expect(second.chunks).toHaveLength(2);
    // Chunk object identity is the contract React.memo freezes on.
    expect(second.chunks[0]).toBe(first.chunks[0]);
    expect(second.chunks[1]?.text).toBe('第二段还在生成，现在完成。');
  });

  it('freezes completed chunk DOM identity while only the streaming tail updates', () => {
    const view = render(
      <MarkdownBody
        documentKey="msg-freeze"
        streamingTail
        text={'第一段结论已经写完。\n\n第二段正在生成'}
      />,
    );

    // The live body must actually run through the cleanroom renderer.
    expect(document.querySelector('[data-progressive-markdown]')).toHaveClass(
      'agent-markdown',
    );
    const frozenParagraph = screen.getByText('第一段结论已经写完。');

    view.rerender(
      <MarkdownBody
        documentKey="msg-freeze"
        streamingTail
        text={'第一段结论已经写完。\n\n第二段正在生成，补充细节'}
      />,
    );
    expect(screen.getByText('第一段结论已经写完。')).toBe(frozenParagraph);
    expect(screen.getByText('第二段正在生成，补充细节')).toBeInTheDocument();

    view.rerender(
      <MarkdownBody
        documentKey="msg-freeze"
        streamingTail
        text={'第一段结论已经写完。\n\n第二段正在生成，补充细节。\n\n第三段开始'}
      />,
    );
    expect(screen.getByText('第一段结论已经写完。')).toBe(frozenParagraph);
    const promotedParagraph = screen.getByText('第二段正在生成，补充细节。');

    view.rerender(
      <MarkdownBody
        documentKey="msg-freeze"
        streamingTail
        text={'第一段结论已经写完。\n\n第二段正在生成，补充细节。\n\n第三段开始，仍在续写'}
      />,
    );
    // A chunk committed once may never remount on later tail growth.
    expect(screen.getByText('第一段结论已经写完。')).toBe(frozenParagraph);
    expect(screen.getByText('第二段正在生成，补充细节。')).toBe(promotedParagraph);
    expect(screen.getByText('第三段开始，仍在续写')).toBeInTheDocument();
  });

  it('keeps streaming motion on the active tail only', () => {
    const { container } = render(
      <MarkdownBody
        documentKey="msg-motion"
        streamingTail
        text={'冻结的段落。\n\n活动尾部还在生成'}
      />,
    );

    const tails = container.querySelectorAll('.agent-markdown__active-tail');
    expect(tails).toHaveLength(1);
    const tail = tails[0]!;
    expect(tail).toHaveTextContent('活动尾部还在生成');
    expect(tail.querySelector('[data-stream-tail]')).not.toBeNull();
    expect(tail.querySelector('.agent-streaming-cursor--inline')).not.toBeNull();

    const frozenParagraph = screen.getByText('冻结的段落。');
    expect(tail.contains(frozenParagraph)).toBe(false);
    expect(frozenParagraph).not.toHaveAttribute('data-stream-tail');
  });

  it('streams an open fence into the code island without re-parsing per token', () => {
    const view = render(
      <TooltipProvider>
        <MarkdownBody
          documentKey="msg-fence"
          streamingTail
          text={'说明如下。\n\n```ts\nconst a = 1;\nconst b'}
        />
      </TooltipProvider>,
    );

    const frozenIntro = screen.getByText('说明如下。');
    const island = document.querySelector<HTMLElement>('figure.agent-code-block');
    expect(island).not.toBeNull();
    const code = island!.querySelector('code.agent-code-block__content');
    expect(code).toHaveAttribute('data-stream-tail', 'true');
    expect(code?.textContent).toContain('const a = 1;');
    expect(island!.querySelector('pre')).toHaveAttribute('data-language', 'ts');
    // The open fence body reaches the island verbatim, not through ReactMarkdown.
    expect(island!.closest('.agent-markdown__active-tail')).not.toBeNull();

    view.rerender(
      <TooltipProvider>
        <MarkdownBody
          documentKey="msg-fence"
          streamingTail
          text={'说明如下。\n\n```ts\nconst a = 1;\nconst b = 2;\nconst c'}
        />
      </TooltipProvider>,
    );
    // The island is a live DOM node that grows in place per token batch.
    expect(document.querySelector('figure.agent-code-block')).toBe(island);
    expect(island!.querySelector('code')?.textContent).toContain('const b = 2;');
    expect(screen.getByText('说明如下。')).toBe(frozenIntro);

    view.rerender(
      <TooltipProvider>
        <MarkdownBody
          documentKey="msg-fence"
          streamingTail
          text={'说明如下。\n\n```ts\nconst a = 1;\nconst b = 2;\nconst c = 3;\n```'}
        />
      </TooltipProvider>,
    );
    // Once the fence closes, the tail falls back to the parsed Markdown path
    // and still renders the same kind of code block.
    const settledFence = document.querySelector('figure.agent-code-block pre');
    expect(settledFence).toHaveAttribute('data-language', 'ts');
    expect(settledFence?.textContent).toContain('const c = 3;');
  });

  it('keeps a streaming open HTML fence on the inert placeholder', () => {
    render(
      <MarkdownBody
        documentKey="msg-html-fence"
        streamingTail
        text={'```html\n<section><strong>还在生成'}
      />,
    );

    expect(screen.getByRole('status')).toHaveTextContent('正在生成 HTML 预览');
    expect(screen.queryByTitle('HTML 输出预览')).not.toBeInTheDocument();
    expect(document.querySelector('figure.agent-code-block')).toBeNull();
  });
});
