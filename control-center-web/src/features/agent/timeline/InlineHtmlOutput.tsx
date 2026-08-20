import { Code2, Globe2, Maximize2, Minimize2, X } from 'lucide-react';
import { memo, useMemo, useState } from 'react';
import { RICH_HTML_SANDBOX, richHtmlDocument } from '../file-preview/rich-html';
import { useRichHtmlUrl } from '../file-preview/use-rich-html-url';

const INLINE_HEIGHT = 420;
const EXPANDED_HEIGHT = 720;

/**
 * Render complete model-authored HTML in the message that produced it.
 *
 * HTML remains presentation of the saved assistant reply, not a second Tool
 * or backend action. Refreshing history can therefore restore it directly.
 */
export const InlineHtmlOutput = memo(function InlineHtmlOutput({
  content,
}: {
  content: string;
}) {
  const [expanded, setExpanded] = useState(false);
  const [showSource, setShowSource] = useState(false);
  const document = useMemo(() => richHtmlDocument(content), [content]);
  const url = useRichHtmlUrl(document);
  const frameHeight = expanded ? EXPANDED_HEIGHT : INLINE_HEIGHT;

  return (
    <section className="agent-html-output" data-expanded={expanded || undefined}>
      <header className="agent-html-output__header">
        <span className="agent-html-output__label">
          <Globe2 aria-hidden="true" size={15} />
          HTML 输出
        </span>
        <span className="agent-html-output__actions">
          <button
            aria-label={expanded ? '收起 HTML 预览' : '展开 HTML 预览'}
            className="agent-html-output__action"
            onClick={() => setExpanded((value) => !value)}
            type="button"
          >
            {expanded ? <Minimize2 aria-hidden="true" size={14} /> : <Maximize2 aria-hidden="true" size={14} />}
            {expanded ? '收起' : '展开'}
          </button>
          <button
            aria-expanded={showSource}
            aria-label={showSource ? '关闭 HTML 源码' : '查看 HTML 源码'}
            className="agent-html-output__action"
            onClick={() => setShowSource((value) => !value)}
            type="button"
          >
            {showSource ? <X aria-hidden="true" size={14} /> : <Code2 aria-hidden="true" size={14} />}
            {showSource ? '关闭源码' : '源码'}
          </button>
        </span>
      </header>
      <iframe
        className="agent-html-output__frame"
        referrerPolicy="no-referrer"
        sandbox={RICH_HTML_SANDBOX}
        src={url}
        style={{ height: `${frameHeight}px` }}
        title="HTML 输出预览"
      />
      {showSource ? (
        <pre className="agent-html-output__source"><code>{content}</code></pre>
      ) : null}
    </section>
  );
});

export function HtmlOutputPlaceholder() {
  return (
    <div className="agent-html-output-placeholder" role="status">
      <span aria-hidden="true" className="agent-html-output-placeholder__dot" />
      正在生成 HTML 预览…
    </div>
  );
}

export function standaloneHtmlSource(source: string): string | undefined {
  const trimmed = source.trim();
  if (!trimmed || /^```/u.test(trimmed)) return undefined;
  if (/^(?:<!doctype\s+html\b|<html\b|<head\b|<body\b)/iu.test(trimmed)) return trimmed;
  if (/^<(?:article|aside|canvas|div|footer|header|main|nav|section|style|svg|table)\b/iu.test(trimmed)) {
    return trimmed;
  }
  return undefined;
}
