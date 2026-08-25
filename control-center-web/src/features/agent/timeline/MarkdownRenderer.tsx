import { ExternalLink } from 'lucide-react';
import { memo, useMemo, type ReactNode } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { AgentBlockRenderProps } from './renderer-contract';
import { CodeContentBlock, StreamingCursor } from './CodeDiffRenderers';
import {
  ProgressiveMarkdown,
  useDeferredStreaming,
  type ProgressiveChunkRenderContext,
} from './progressive-markdown';
import { text } from './renderer-values';
import {
  HtmlOutputPlaceholder,
  InlineHtmlOutput,
  standaloneHtmlSource,
} from './InlineHtmlOutput';

export function TextBlockRenderer({
  block,
  streamingTail,
}: AgentBlockRenderProps) {
  return (
    <MarkdownBody
      documentKey={block.id}
      streamingTail={streamingTail}
      text={text(block.data.text ?? block.data.markdown)}
    />
  );
}

export function MarkdownBody({
  documentKey = '',
  streamingTail = false,
  text: source,
}: {
  documentKey?: string;
  streamingTail?: boolean;
  text: string;
}) {
  /* Deferred settle latch: the progressive renderer stays mounted for one
     transition render after the stream ends, so the final whole-document
     parse never swaps render modes inside the urgent settle commit. */
  const progressiveMode = useDeferredStreaming(streamingTail);
  const standaloneHtml = useMemo(() => standaloneHtmlSource(source), [source]);
  if (!source) return null;
  if (standaloneHtml) {
    return streamingTail
      ? <HtmlOutputPlaceholder />
      : <InlineHtmlOutput content={standaloneHtml} />;
  }
  if (!progressiveMode) {
    return (
      <div className="agent-markdown">
        <StableMarkdownFragment source={source} />
      </div>
    );
  }
  // Live path: the cleanroom scanner freezes the stable prefix chunk-by-chunk
  // (React.memo keeps frozen DOM identical per token batch) while only the
  // active tail re-parses. holdBack is on: the safe-text release scheduler
  // turns batched live-store commits into a paced Markdown-safe reveal — the
  // visible typing motion. It starts fully flushed on mount (restores and
  // Virtuoso remounts never replay) and flushes instantly under reduced
  // motion or a hidden document, so the transcript stays truthful.
  return (
    <ProgressiveMarkdown
      className="agent-markdown"
      documentKey={documentKey}
      isStreaming={streamingTail}
      renderChunk={renderProgressiveChunk}
      text={source}
    />
  );
}

function renderProgressiveChunk(context: ProgressiveChunkRenderContext) {
  if (!context.active || context.settled) {
    return (
      <StableMarkdownFragment
        deferRichHtml={!context.settled}
        source={context.text}
      />
    );
  }
  return (
    <div className="agent-markdown__active-tail" data-active-tail="">
      {context.openFence ? (
        <>
          {context.openFence.prefix.trim() ? (
            <StableMarkdownFragment
              deferRichHtml
              source={context.openFence.prefix}
            />
          ) : null}
          <StreamingFenceIsland
            language={context.openFence.language}
            value={context.openFence.value}
          />
        </>
      ) : (
        <MarkdownFragment source={context.text} streamingTail />
      )}
    </div>
  );
}

/**
 * Open-fence fast path: while a fenced block is still unclosed at the
 * streaming tail, its growing body bypasses the Markdown parser entirely and
 * streams into the same code island the parsed path would produce. HTML
 * fences keep the inert placeholder policy they already have while streaming.
 */
function StreamingFenceIsland({
  language,
  value,
}: {
  language: string;
  value: string;
}) {
  const kind = language.toLowerCase();
  if (kind === 'html' || kind === 'htm') return <HtmlOutputPlaceholder />;
  return (
    <CodeContentBlock
      code={value}
      language={language || 'text'}
      streamingTail
    />
  );
}

const StableMarkdownFragment = memo(function StableMarkdownFragment({
  deferRichHtml = false,
  source,
}: {
  deferRichHtml?: boolean;
  source: string;
}) {
  return <MarkdownFragment deferRichHtml={deferRichHtml} source={source} />;
});

function MarkdownFragment({
  deferRichHtml = false,
  source,
  streamingTail = false,
}: {
  deferRichHtml?: boolean;
  source: string;
  streamingTail?: boolean;
}) {
  return (
    <ReactMarkdown
      skipHtml
      remarkPlugins={streamingTail ? [remarkGfm, remarkLiteralHtml, remarkStreamingTail] : [remarkGfm, remarkLiteralHtml]}
      components={{
        a: ({ href, children }) => {
          const safe = safeLink(href);
          return safe ? (
            <a
              href={safe}
              target={safe.startsWith('http') ? '_blank' : undefined}
              rel="noreferrer"
            >
              {children}
              {safe.startsWith('http') ? <ExternalLink size={12} aria-hidden="true" /> : null}
            </a>
          ) : (
            <span>{children}</span>
          );
        },
        p: ({ children, node: _node, ...props }) => (
          <p {...props}>
            {children}
            <StreamingCursor active={hasStreamingTail(props)} />
          </p>
        ),
        li: ({ children, node: _node, ...props }) => (
          <li {...props}>
            {children}
            <StreamingCursor active={hasStreamingTail(props)} />
          </li>
        ),
        td: ({ children, node: _node, ...props }) => (
          <td {...props}>
            {children}
            <StreamingCursor active={hasStreamingTail(props)} />
          </td>
        ),
        h1: ({ children, node: _node, ...props }) => (
          <h1 {...props}>
            {children}
            <StreamingCursor active={hasStreamingTail(props)} />
          </h1>
        ),
        h2: ({ children, node: _node, ...props }) => (
          <h2 {...props}>
            {children}
            <StreamingCursor active={hasStreamingTail(props)} />
          </h2>
        ),
        h3: ({ children, node: _node, ...props }) => (
          <h3 {...props}>
            {children}
            <StreamingCursor active={hasStreamingTail(props)} />
          </h3>
        ),
        code: ({ className, children, node: _node, ...props }) => {
          const match = /language-([\w-]+)/u.exec(className ?? '');
          const raw = String(children);
          const code = raw.replace(/\n$/u, '');
          const fenced = Boolean(match) || raw.endsWith('\n');
          const tail = hasStreamingTail(props);
          const html = match?.[1]?.toLowerCase() === 'html';
          if (fenced && html) {
            return deferRichHtml || streamingTail || tail
              ? <HtmlOutputPlaceholder />
              : <InlineHtmlOutput content={code} />;
          }
          return fenced ? (
            <CodeContentBlock
              code={code}
              language={match?.[1] ?? 'text'}
              streamingTail={tail}
            />
          ) : (
            <code {...props}>
              {children}
              <StreamingCursor active={tail} />
            </code>
          );
        },
        pre: ({ children }) => <>{children}</>,
        img: ({ alt }) => (
          <span className="agent-markdown__blocked-media">{alt || '图片'}</span>
        ),
      }}
    >
      {source}
    </ReactMarkdown>
  );
}

type MarkdownAstNode = {
  type?: string;
  value?: string;
  children?: MarkdownAstNode[];
  data?: { hProperties?: Record<string, unknown> };
};

/**
 * Raw HTML in assistant prose is turned into literal text.
 *
 * react-markdown does not render HTML without rehype-raw, so these nodes were
 * being dropped outright — an agent quoting `<script>alert(1)</script>` in its
 * explanation produced a blank line, and the reader never learned what was
 * quoted. Rewriting the node to text keeps the content visible while React's
 * own escaping keeps it inert; the alternative, rehype-raw, would make the
 * transcript a live HTML renderer, which is exactly what it must never be.
 */
function remarkLiteralHtml() {
  return (tree: MarkdownAstNode) => {
    const visit = (node: MarkdownAstNode) => {
      if (!node.children?.length) return;
      node.children = node.children.map((child) => {
        visit(child);
        return child.type === 'html' ? { type: 'text', value: child.value ?? '' } : child;
      });
    };
    visit(tree);
  };
}

function remarkStreamingTail() {
  return (tree: MarkdownAstNode) => {
    let terminalPath: MarkdownAstNode[] = [];
    const visit = (node: MarkdownAstNode, parents: MarkdownAstNode[]) => {
      const path = [...parents, node];
      if (node.children?.length) {
        node.children.forEach((child) => visit(child, path));
      } else if (['text', 'inlineCode', 'code', 'image', 'break'].includes(node.type ?? '')) {
        terminalPath = path;
      }
    };
    visit(tree, []);
    const target = tailContainer(terminalPath);
    if (!target) return;
    target.data = target.data ?? {};
    target.data.hProperties = {
      ...target.data.hProperties,
      'data-stream-tail': 'true',
    };
  };
}

function tailContainer(path: MarkdownAstNode[]) {
  for (const type of ['code', 'tableCell', 'listItem', 'paragraph', 'heading']) {
    for (let index = path.length - 1; index >= 0; index -= 1) {
      if (path[index]?.type === type) return path[index];
    }
  }
  return undefined;
}

function hasStreamingTail(props: Record<string, unknown>) {
  return props['data-stream-tail'] === true || props['data-stream-tail'] === 'true';
}

function safeLink(value: string | undefined): string | undefined {
  if (!value) return undefined;
  if (value.includes('\\') || value.startsWith('//')) return undefined;
  if (value.startsWith('#/') || value.startsWith('/')) return value;
  try {
    const url = new URL(value);
    return url.protocol === 'https:' || url.protocol === 'http:' ? url.href : undefined;
  } catch {
    return undefined;
  }
}
