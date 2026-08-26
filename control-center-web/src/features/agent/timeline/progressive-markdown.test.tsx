import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { TooltipProvider } from '@/components/primitives';
import { MarkdownBody } from './MarkdownRenderer';
import {
  INITIAL_SCAN_STATE,
  scanIncrementalMarkdown,
  settleScannedMarkdown,
  splitSettledMarkdown,
} from './progressive-markdown';
import {
  advanceToSafeBoundary,
  findSafeInlineBoundary,
  remapVisibleOffsetAfterEdit,
} from './progressive-markdown/safeInlineBoundary';

afterEach(() => {
  cleanup();
  document.documentElement.removeAttribute('data-reduce-motion');
});

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

  it('settles by carrying committed chunks over by identity instead of re-scanning from zero', () => {
    const midStream = scanIncrementalMarkdown(
      INITIAL_SCAN_STATE,
      '第一段。\n\n第二段。\n\n第三段还在生成',
    );
    const finalText = '第一段。\n\n第二段。\n\n第三段完成了。\n\n第四段收尾。';
    const streamed = scanIncrementalMarkdown(midStream, finalText);

    const settled = settleScannedMarkdown(streamed, finalText);

    // The committed prefix keeps the exact objects React.memo froze on; only
    // the unscanned suffix is walked once more at settle.
    expect(settled[0]).toBe(streamed.chunks[0]);
    expect(settled[1]).toBe(streamed.chunks[1]);
    // The settled partition is byte-for-byte what a from-zero scan would say.
    expect(settled.map((chunk) => ({ ...chunk }))).toEqual(
      splitSettledMarkdown(finalText).map((chunk) => ({ ...chunk })),
    );
  });

  it('rebuilds the settled partition from zero when the final text is not an append', () => {
    const streamed = scanIncrementalMarkdown(
      INITIAL_SCAN_STATE,
      '旧的第一段。\n\n旧的第二段还在生成',
    );
    const rewritten = '全新的第一段。\n\n全新的第二段。';

    const settled = settleScannedMarkdown(streamed, rewritten);

    expect(settled.map((chunk) => ({ ...chunk }))).toEqual(
      splitSettledMarkdown(rewritten).map((chunk) => ({ ...chunk })),
    );
    expect(settled.some((chunk) => chunk.text.includes('旧的'))).toBe(false);
  });

  it('does not treat headings inside a fenced block as commit boundaries', () => {
    const scanned = scanIncrementalMarkdown(
      INITIAL_SCAN_STATE,
      '稳定说明。\n\n```md\n\n# 这是代码，不是新章节\n```\n\n后续段落还在生成',
    );

    // One committed chunk for the intro, one for the whole closed fence; the
    // heading line inside the fence never splits the code block apart.
    expect(scanned.chunks.map((chunk) => chunk.text)).toEqual([
      '稳定说明。',
      '```md\n\n# 这是代码，不是新章节\n```',
    ]);
  });

  it('never pulls a CJK tail back to a distant space the way it holds back Latin words', () => {
    // Latin: an incomplete trailing word is held back to the last space.
    expect(findSafeInlineBoundary('progress on wor')).toBe('progress on '.length);
    // CJK after a space: ideographs are complete display units — releasing
    // them immediately is correct, pinning to the ASCII space is not.
    const mixed = 'PAWOS 渲染优化已经生效';
    expect(findSafeInlineBoundary(mixed)).toBe(mixed.length);
  });

  it('catches up on a burst instead of stepping a fixed distance per frame', () => {
    const text = `${'delivered text that already arrived. '.repeat(40)}tail`;
    const ceiling = findSafeInlineBoundary(text);

    // A 1400-character backlog cleared 40 characters at a time would trail the
    // delivered answer by dozens of frames.
    const catchUp = advanceToSafeBoundary(text, 0, ceiling);
    expect(catchUp).toBeGreaterThan(ceiling / 5);

    // Near the end the step falls back to the base, so the last few words
    // still read as typing rather than snapping into place.
    const nearEnd = advanceToSafeBoundary(text, ceiling - 30, ceiling);
    expect(nearEnd).toBe(ceiling);
    expect(advanceToSafeBoundary(text, ceiling, ceiling)).toBe(ceiling);
  });

  it('keeps the reveal position when a retry rewrites only the opening', () => {
    const previous = '旧的开头。\n\n共同的主体内容，很长的一段。\n\n结尾。';
    const next = '全新的开头，更长一些。\n\n共同的主体内容，很长的一段。\n\n结尾。';
    // The reader had everything through the shared body visible.
    const visible = previous.length - '结尾。'.length;

    const mapped = remapVisibleOffsetAfterEdit(previous, next, visible);

    // Measured from the end, so the same shared text stays visible instead of
    // collapsing to the common prefix and replaying the whole reveal.
    expect(next.slice(0, mapped)).toContain('共同的主体内容，很长的一段。');
    expect(mapped).toBe(next.length - '结尾。'.length);
  });

  it('falls back to the common prefix when a rewrite genuinely diverges', () => {
    const previous = '共享前缀。原来的后半段完全不同。';
    const next = '共享前缀。换成了另一套完全不相干的说法。';

    expect(remapVisibleOffsetAfterEdit(previous, next, previous.length))
      .toBeLessThanOrEqual(next.length);
    // An append is not an edit: the offset survives untouched.
    expect(remapVisibleOffsetAfterEdit('前半段', '前半段加上新内容', 3)).toBe(3);
  });

  it('freezes completed chunk DOM identity while only the streaming tail updates', async () => {
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
    // Appended text flows through the rAF release scheduler, so it lands a
    // few frames after the commit rather than in the same synchronous render.
    expect(await screen.findByText('第二段正在生成，补充细节')).toBeInTheDocument();
    expect(screen.getByText('第一段结论已经写完。')).toBe(frozenParagraph);

    view.rerender(
      <MarkdownBody
        documentKey="msg-freeze"
        streamingTail
        text={'第一段结论已经写完。\n\n第二段正在生成，补充细节。\n\n第三段开始'}
      />,
    );
    const promotedParagraph = await screen.findByText('第二段正在生成，补充细节。');
    expect(screen.getByText('第一段结论已经写完。')).toBe(frozenParagraph);

    view.rerender(
      <MarkdownBody
        documentKey="msg-freeze"
        streamingTail
        text={'第一段结论已经写完。\n\n第二段正在生成，补充细节。\n\n第三段开始，仍在续写'}
      />,
    );
    // A chunk committed once may never remount on later tail growth.
    expect(await screen.findByText('第三段开始，仍在续写')).toBeInTheDocument();
    expect(screen.getByText('第一段结论已经写完。')).toBe(frozenParagraph);
    expect(screen.getByText('第二段正在生成，补充细节。')).toBe(promotedParagraph);
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

  it('streams an open fence into the code island without re-parsing per token', async () => {
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
    // The streaming figure carries the CSS hook for the caption sweep.
    expect(island).toHaveAttribute('data-streaming', 'true');

    view.rerender(
      <TooltipProvider>
        <MarkdownBody
          documentKey="msg-fence"
          streamingTail
          text={'说明如下。\n\n```ts\nconst a = 1;\nconst b = 2;\nconst c'}
        />
      </TooltipProvider>,
    );
    // The island is a live DOM node that grows in place as the release
    // scheduler paces the appended tokens in.
    await waitFor(() =>
      expect(island!.querySelector('code')?.textContent).toContain('const b = 2;'));
    expect(document.querySelector('figure.agent-code-block')).toBe(island);
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
    await waitFor(() => {
      const settledFence = document.querySelector('figure.agent-code-block pre');
      expect(settledFence).toHaveAttribute('data-language', 'ts');
      expect(settledFence?.textContent).toContain('const c = 3;');
    });
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

  it('shows already-delivered text synchronously on mount and paces only appended text', async () => {
    const view = render(
      <MarkdownBody
        documentKey="msg-holdback"
        streamingTail
        text={'第一段落已经送达。\n\n第二段也已经送达。'}
      />,
    );

    // Mount starts fully flushed: a Virtuoso remount or a restored mid-stream
    // snapshot must never replay the reveal from zero.
    expect(screen.getByText('第一段落已经送达。')).toBeInTheDocument();
    expect(screen.getByText('第二段也已经送达。')).toBeInTheDocument();

    view.rerender(
      <MarkdownBody
        documentKey="msg-holdback"
        streamingTail
        text={'第一段落已经送达。\n\n第二段也已经送达。\n\n新追加的第三段'}
      />,
    );
    // Text appended after mount goes through the release scheduler: withheld
    // in the commit itself, revealed a few frames later.
    expect(screen.queryByText('新追加的第三段')).not.toBeInTheDocument();
    expect(await screen.findByText('新追加的第三段')).toBeInTheDocument();
  });

  it('flushes appended text instantly when the user disabled motion', () => {
    document.documentElement.setAttribute('data-reduce-motion', 'true');
    const view = render(
      <MarkdownBody
        documentKey="msg-reduced-motion"
        streamingTail
        text={'第一段落已经送达。'}
      />,
    );

    view.rerender(
      <MarkdownBody
        documentKey="msg-reduced-motion"
        streamingTail
        text={'第一段落已经送达。\n\n新追加的第二段'}
      />,
    );
    // Reduced motion means the reveal is skipped, not the text: delivery is
    // synchronous with the commit.
    expect(screen.getByText('新追加的第二段')).toBeInTheDocument();
  });

  it('settles from the progressive renderer to the whole-document parse after the stream ends', async () => {
    const view = render(
      <MarkdownBody
        documentKey="msg-settle"
        streamingTail
        text={'第一段结论。\n\n第二段收尾。'}
      />,
    );
    expect(document.querySelector('[data-progressive-markdown]')).not.toBeNull();

    view.rerender(
      <MarkdownBody
        documentKey="msg-settle"
        text={'第一段结论。\n\n第二段收尾。'}
      />,
    );
    // The deferred latch keeps the progressive renderer mounted through the
    // settle commit, then hands off to the plain settled document.
    await waitFor(() =>
      expect(document.querySelector('[data-progressive-markdown]')).toBeNull());
    expect(screen.getByText('第一段结论。')).toBeInTheDocument();
    expect(screen.getByText('第二段收尾。')).toBeInTheDocument();
  });
});
