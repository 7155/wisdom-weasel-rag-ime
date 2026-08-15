import { Code2, Globe2, Maximize2, Minimize2, X } from 'lucide-react';
import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';

const INLINE_MIN_HEIGHT = 180;
const INLINE_MAX_HEIGHT = 720;
const EXPANDED_MAX_HEIGHT = 1_800;

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
  const frameRef = useRef<HTMLIFrameElement>(null);
  const observerRef = useRef<ResizeObserver | null>(null);
  const animationFrameRef = useRef(0);
  const [contentHeight, setContentHeight] = useState(320);
  const [expanded, setExpanded] = useState(false);
  const [showSource, setShowSource] = useState(false);
  const document = useMemo(() => modelHtmlDocument(content), [content]);

  const measure = useCallback(() => {
    const frame = frameRef.current;
    const frameDocument = frame?.contentDocument;
    if (!frame || !frameDocument?.body) return;
    const height = measureDocumentHeight(frameDocument);
    if (height > 0) setContentHeight(clampHeight(height, INLINE_MIN_HEIGHT, 12_000));
  }, []);

  const scheduleMeasure = useCallback(() => {
    if (animationFrameRef.current) return;
    animationFrameRef.current = window.requestAnimationFrame(() => {
      animationFrameRef.current = 0;
      measure();
    });
  }, [measure]);

  const bindMeasurement = useCallback(() => {
    observerRef.current?.disconnect();
    const frameDocument = frameRef.current?.contentDocument;
    if (!frameDocument?.documentElement || !frameDocument.body) return;
    observerRef.current = new ResizeObserver(scheduleMeasure);
    observerRef.current.observe(frameDocument.documentElement);
    observerRef.current.observe(frameDocument.body);
    scheduleMeasure();
    window.setTimeout(scheduleMeasure, 50);
    window.setTimeout(scheduleMeasure, 200);
  }, [scheduleMeasure]);

  useEffect(() => () => {
    observerRef.current?.disconnect();
    if (animationFrameRef.current) window.cancelAnimationFrame(animationFrameRef.current);
  }, []);

  const maximum = expanded ? EXPANDED_MAX_HEIGHT : INLINE_MAX_HEIGHT;
  const frameHeight = clampHeight(contentHeight, INLINE_MIN_HEIGHT, maximum);
  const canExpand = contentHeight > INLINE_MAX_HEIGHT;

  return (
    <section className="agent-html-output" data-expanded={expanded || undefined}>
      <header className="agent-html-output__header">
        <span className="agent-html-output__label">
          <Globe2 aria-hidden="true" size={15} />
          HTML 输出
        </span>
        <span className="agent-html-output__actions">
          {canExpand ? (
            <button
              aria-label={expanded ? '收起 HTML 预览' : '展开 HTML 预览'}
              className="agent-html-output__action"
              onClick={() => setExpanded((value) => !value)}
              type="button"
            >
              {expanded ? <Minimize2 aria-hidden="true" size={14} /> : <Maximize2 aria-hidden="true" size={14} />}
              {expanded ? '收起' : '展开'}
            </button>
          ) : null}
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
        loading="lazy"
        onLoad={bindMeasurement}
        ref={frameRef}
        referrerPolicy="no-referrer"
        sandbox="allow-downloads allow-forms allow-modals allow-popups allow-same-origin allow-scripts"
        srcDoc={document}
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

export function modelHtmlDocument(source: string): string {
  const completeDocument = /(?:<!doctype\s+html\b|<html\b|<head\b|<body\b)/iu.test(source);
  const document = new DOMParser().parseFromString(
    completeDocument ? source : `<main class="paw-html-fragment">${source}</main>`,
    'text/html',
  );

  const viewport = document.createElement('meta');
  viewport.name = 'viewport';
  viewport.content = 'width=device-width, initial-scale=1';
  document.head.prepend(viewport);

  const guardrails = document.createElement('style');
  guardrails.dataset.pawHtmlHost = 'true';
  guardrails.textContent = [
    'html{box-sizing:border-box;min-width:0;background:transparent}',
    '*,*::before,*::after{box-sizing:inherit}',
    'body{min-width:0;margin:0;overflow-wrap:anywhere}',
    '.paw-html-fragment{padding:18px;font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#17231d;background:#fff}',
    'img,video,svg,canvas{max-width:100%}',
    'pre,table{max-width:100%;overflow:auto}',
  ].join('');
  document.head.append(guardrails);
  return `<!doctype html>${document.documentElement.outerHTML}`;
}

function measureDocumentHeight(document: Document): number {
  let anchor = document.getElementById('paw-html-height-anchor');
  if (!anchor) {
    anchor = document.createElement('div');
    anchor.id = 'paw-html-height-anchor';
    anchor.style.cssText = 'clear:both;height:1px;margin-top:-1px;visibility:hidden;pointer-events:none';
    document.body.append(anchor);
  }
  const bodyTop = document.body.getBoundingClientRect().top;
  let height = anchor.offsetTop + anchor.offsetHeight;
  for (const node of document.querySelectorAll<HTMLElement>('body > *:not(#paw-html-height-anchor)')) {
    const rect = node.getBoundingClientRect();
    height = Math.max(height, rect.bottom - bodyTop, node.scrollHeight || 0);
  }
  return Math.ceil(height);
}

function clampHeight(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, Math.round(value)));
}
