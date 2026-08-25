import React, { Fragment, memo, useCallback, useMemo, type ReactNode } from "react";
import { detectOpenFenceTail } from "../core/openFence";
import { normalizeStreamingMarkdown } from "../core/normalizeStreamingMarkdown";
import { useDeferredStreaming } from "./useDeferredStreaming";
import { useProgressiveChunks } from "./useProgressiveChunks";
import { useSafeTextRelease } from "./useSafeTextRelease";

function inlineMarkdown(text: string): ReactNode[] {
  const tokens: ReactNode[] = [];
  const regex = /(`[^`]+`|\*\*[^*]+\*\*|\[[^\]]+\]\(https?:\/\/[^)]+\))/g;
  let last = 0;
  let match: RegExpExecArray | null;
  while ((match = regex.exec(text))) {
    if (match.index > last) tokens.push(text.slice(last, match.index));
    const token = match[0];
    if (token.startsWith("`")) {
      tokens.push(<code key={`${match.index}:code`}>{token.slice(1, -1)}</code>);
    } else if (token.startsWith("**")) {
      tokens.push(<strong key={`${match.index}:strong`}>{token.slice(2, -2)}</strong>);
    } else {
      const link = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(token);
      tokens.push(link ? <a key={`${match.index}:a`} href={link[2]} target="_blank" rel="noreferrer">{link[1]}</a> : token);
    }
    last = regex.lastIndex;
  }
  if (last < text.length) tokens.push(text.slice(last));
  return tokens;
}

function BasicMarkdownChunk({ text }: { text: string }) {
  const lines = text.split("\n");
  const nodes: ReactNode[] = [];
  let paragraph: string[] = [];
  let list: string[] = [];

  const flushParagraph = () => {
    if (!paragraph.length) return;
    const value = paragraph.join("\n");
    nodes.push(<p key={`p-${nodes.length}`}>{inlineMarkdown(value)}</p>);
    paragraph = [];
  };
  const flushList = () => {
    if (!list.length) return;
    nodes.push(<ul key={`ul-${nodes.length}`}>{list.map((item, index) => <li key={index}>{inlineMarkdown(item)}</li>)}</ul>);
    list = [];
  };

  let inFence = false;
  let fenceLang = "";
  let fence: string[] = [];
  for (const line of lines) {
    const fenceMatch = /^```\s*([\w+-]*)/.exec(line);
    if (fenceMatch) {
      if (!inFence) {
        flushParagraph();
        flushList();
        inFence = true;
        fenceLang = fenceMatch[1] ?? "";
        fence = [];
      } else {
        nodes.push(
          <pre key={`pre-${nodes.length}`} data-language={fenceLang || undefined}>
            <code>{fence.join("\n")}</code>
          </pre>,
        );
        inFence = false;
        fenceLang = "";
        fence = [];
      }
      continue;
    }
    if (inFence) {
      fence.push(line);
      continue;
    }
    if (/^#{1,4}\s/.test(line)) {
      flushParagraph();
      flushList();
      const level = line.match(/^#+/)?.[0].length ?? 1;
      const value = line.replace(/^#{1,4}\s+/, "");
      const Tag: any = `h${Math.min(level, 4)}`;
      nodes.push(<Tag key={`h-${nodes.length}`}>{inlineMarkdown(value)}</Tag>);
      continue;
    }
    const li = /^[-*+]\s+(.*)$/.exec(line);
    if (li) {
      flushParagraph();
      list.push(li[1] ?? "");
      continue;
    }
    if (line.trim() === "") {
      flushParagraph();
      flushList();
      continue;
    }
    paragraph.push(line);
  }
  flushParagraph();
  flushList();
  if (inFence) {
    nodes.push(<pre key={`pre-open-${nodes.length}`} data-language={fenceLang || undefined}><code>{fence.join("\n")}</code></pre>);
  }
  return <>{nodes}</>;
}

interface ChunkProps {
  documentKey: string;
  text: string;
  offset: number;
  active: boolean;
  settled: boolean;
}

const Chunk = memo(function Chunk({ text, active, settled }: ChunkProps) {
  const openFence = active && !settled ? detectOpenFenceTail(text) : null;
  if (openFence) {
    return (
      <>
        {openFence.prefix ? <BasicMarkdownChunk text={openFence.prefix} /> : null}
        <pre className="ccui-streaming-code" data-language={openFence.language || undefined}>
          <code>{openFence.value}</code>
        </pre>
      </>
    );
  }
  return <BasicMarkdownChunk text={text} />;
}, (a, b) => a.text === b.text && a.offset === b.offset && a.active === b.active && a.settled === b.settled && a.documentKey === b.documentKey);

export function ProgressiveMarkdown({
  text,
  isStreaming,
  documentKey,
  className,
}: {
  text: string;
  isStreaming: boolean;
  documentKey: string;
  className?: string;
}) {
  const effectiveStreaming = useDeferredStreaming(isStreaming);
  const normalized = useMemo(
    () => normalizeStreamingMarkdown(text, { isStreaming }),
    [text, isStreaming],
  );
  const visibleText = useSafeTextRelease(normalized, {
    enabled: isStreaming,
  });
  const progressive = useProgressiveChunks({
    text: visibleText,
    isStreaming: effectiveStreaming,
    documentKey,
  });

  const chunks = useMemo(() => progressive.streamingChunk
    ? [...progressive.completedChunks, { text: progressive.streamingChunk, offset: progressive.streamingChunkOffset }]
    : [...progressive.completedChunks], [progressive.completedChunks, progressive.streamingChunk, progressive.streamingChunkOffset]);
  const activeIndex = effectiveStreaming && progressive.streamingChunk ? chunks.length - 1 : -1;

  return (
    <div className={className ?? "ccui-markdown"} data-progressive-markdown="">
      {chunks.map((chunk, index) => (
        <Fragment key={`${documentKey}:${chunk.offset}`}>
          <Chunk
            documentKey={documentKey}
            text={chunk.text}
            offset={chunk.offset}
            active={index === activeIndex}
            settled={!effectiveStreaming}
          />
        </Fragment>
      ))}
    </div>
  );
}
