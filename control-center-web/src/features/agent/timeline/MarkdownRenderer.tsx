import { ChevronDown, ChevronUp, ExternalLink } from 'lucide-react';
import { memo, useMemo, useState, type ReactNode } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { AgentBlockRenderProps } from './renderer-contract';
import { CodeContentBlock, StreamingCursor } from './CodeDiffRenderers';
import { text } from './renderer-values';

const MARKDOWN_FOLD_LINES = 48;
const MARKDOWN_FOLD_CHARACTERS = 7_000;

export function TextBlockRenderer({
  block,
  streamingTail,
}: AgentBlockRenderProps) {
  return (
    <MarkdownBody
      streamingTail={streamingTail}
      text={text(block.data.text ?? block.data.markdown)}
    />
  );
}

export function MarkdownBody({
  streamingTail = false,
  text: source,
}: {
  streamingTail?: boolean;
  text: string;
}) {
  const [expanded, setExpanded] = useState(false);
  const partition = useMemo(
    () => streamingTail
      ? partitionStreamingMarkdownFragments(source)
      : { stableFragments: [source], active: '' },
    [source, streamingTail],
  );
  if (!source) return null;
  const lineCount = source.split('\n').length;
  const foldable = !streamingTail
    && (lineCount > MARKDOWN_FOLD_LINES || source.length > MARKDOWN_FOLD_CHARACTERS);
  const collapsed = foldable && !expanded;
  const body = (
    <div className="agent-markdown" data-collapsed={collapsed || undefined}>
      {partition.stableFragments.map((fragment, index) => (
        <StableMarkdownFragment key={`stable:${index}`} source={fragment} />
      ))}
      {partition.active ? (
        <MarkdownFragment source={partition.active} streamingTail />
      ) : null}
    </div>
  );
  if (!foldable) return body;
  return (
    <div className="agent-markdown-fold">
      <div className="agent-markdown-fold__content">{body}</div>
      <button
        className="agent-markdown-fold__toggle"
        onClick={() => setExpanded((value) => !value)}
        type="button"
      >
        {collapsed ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
        {collapsed ? `展开全文（${lineCount} 行）` : '收起长回复'}
      </button>
    </div>
  );
}

const StableMarkdownFragment = memo(function StableMarkdownFragment({
  source,
}: {
  source: string;
}) {
  return <MarkdownFragment source={source} />;
});

function MarkdownFragment({
  source,
  streamingTail = false,
}: {
  source: string;
  streamingTail?: boolean;
}) {
  return (
    <ReactMarkdown
      skipHtml
      remarkPlugins={streamingTail ? [remarkGfm, remarkStreamingTail] : [remarkGfm]}
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

export function partitionStreamingMarkdown(source: string): {
  stable: string;
  active: string;
} {
  const partition = partitionStreamingMarkdownFragments(source);
  return {
    stable: partition.stableFragments.join(''),
    active: partition.active,
  };
}

export function partitionStreamingMarkdownFragments(source: string): {
  stableFragments: string[];
  active: string;
} {
  let offset = 0;
  const stableBoundaries: number[] = [];
  let previousLineWasBlank = false;
  let fenceCharacter = '';
  let fenceLength = 0;

  while (offset < source.length) {
    const newline = source.indexOf('\n', offset);
    const lineEnd = newline >= 0 ? newline + 1 : source.length;
    const line = source.slice(offset, lineEnd);
    const content = line.replace(/\r?\n$/u, '');
    const fence = /^(`{3,}|~{3,})(?:[^`~].*)?$/u.exec(content);
    if (
      previousLineWasBlank
      && !fenceCharacter
      && isSafeMarkdownFragmentStart(content, Boolean(fence))
    ) {
      stableBoundaries.push(offset);
    }

    if (fence) {
      const marker = fence[1] ?? '';
      if (!fenceCharacter) {
        fenceCharacter = marker[0] ?? '';
        fenceLength = marker.length;
      } else if (marker[0] === fenceCharacter && marker.length >= fenceLength) {
        fenceCharacter = '';
        fenceLength = 0;
      }
    }
    previousLineWasBlank = !fenceCharacter && content.trim() === '';
    offset = lineEnd;
  }

  const stableEnd = stableBoundaries.at(-1) ?? 0;
  if (stableEnd <= 0) return { stableFragments: [], active: source };
  const stableFragments: string[] = [];
  let fragmentStart = 0;
  for (const boundary of stableBoundaries) {
    if (boundary > stableEnd) break;
    if (boundary > fragmentStart) {
      stableFragments.push(source.slice(fragmentStart, boundary));
    }
    fragmentStart = boundary;
  }
  return {
    stableFragments,
    active: source.slice(stableEnd),
  };
}

function isSafeMarkdownFragmentStart(line: string, fenced: boolean): boolean {
  if (!line.trim()) return false;
  if (fenced || /^#{1,6}[ \t]+\S/u.test(line)) return true;
  if (/^[ \t]/u.test(line)) return false;
  return !/^(?:[-+*][ \t]+|\d+[.)][ \t]+|>|:{1,3}[ \t]|\[[^\]]+\]:)/u.test(line);
}

type MarkdownAstNode = {
  type?: string;
  children?: MarkdownAstNode[];
  data?: { hProperties?: Record<string, unknown> };
};

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

export function markdownFoldThresholds() {
  return {
    characters: MARKDOWN_FOLD_CHARACTERS,
    lines: MARKDOWN_FOLD_LINES,
  } as const;
}
