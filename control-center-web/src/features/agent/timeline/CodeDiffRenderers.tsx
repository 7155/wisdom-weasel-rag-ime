import { Check, ChevronRight, Clipboard, Code2, FileDiff } from 'lucide-react';
import { useEffect, useState } from 'react';
import { Disclosure, IconButton } from '@/components/primitives';
import { writeClipboardText } from '@/platform/clipboard';
import { DiffPreview } from '../file-preview/DiffPreview';
import { highlightCode } from '../file-preview/syntax-highlighter';
import type { AgentBlockRenderProps } from './renderer-contract';
import { text } from './renderer-values';

/** Highlighting is a settled-read affordance: it never runs on the streaming
 * tail (which re-renders per token) and never on pathological payloads whose
 * grammar pass would cost more than the tokens communicate. */
const HIGHLIGHT_CHAR_LIMIT = 60_000;

export function CodeBlockRenderer({ block }: AgentBlockRenderProps) {
  const data = block.data;
  return (
    <CodeContentBlock
      code={text(data.code ?? data.text)}
      language={text(data.language) || 'text'}
      fileName={text(data.fileName ?? data.title)}
    />
  );
}

export function DiffBlockRenderer({ block }: AgentBlockRenderProps) {
  const data = block.data;
  const content = text(data.diff ?? data.text);
  const title = text(data.fileName ?? data.title) || '代码变更';
  const lineCount = content ? content.split('\n').length : 0;
  return (
    <Disclosure
      className="agent-inline-diff agent-rich-collapsible"
      data-tone="project"
      defaultOpen={lineCount <= 80}
      summary={<>
        <span className="agent-insert-icon"><FileDiff size={15} /></span>
        <span>{title}</span>
        <small>{lineCount} 行</small>
        <ChevronRight className="agent-rich-collapsible__chevron" size={14} />
      </>}
    >
      <DiffPreview
        content={content}
        disclosureRegionLabel={`${title}完整变更`}
        fileName={title}
      />
    </Disclosure>
  );
}

export function CodeContentBlock({
  code,
  language,
  fileName,
  streamingTail = false,
}: {
  code: string;
  language: string;
  fileName?: string;
  streamingTail?: boolean;
}) {
  const [copied, setCopied] = useState(false);
  const [highlighted, setHighlighted] = useState('');
  const lineCount = code ? code.split('\n').length : 0;
  const collapsed = !streamingTail && (lineCount > 32 || code.length > 4_000);
  const highlightable = !streamingTail && Boolean(code) && code.length <= HIGHLIGHT_CHAR_LIMIT;

  useEffect(() => {
    if (!highlightable) {
      setHighlighted('');
      return undefined;
    }
    let current = true;
    void highlightCode(code, language, { inheritSurface: true })
      .then((html) => { if (current) setHighlighted(html); })
      .catch(() => { if (current) setHighlighted(''); });
    return () => { current = false; };
  }, [code, highlightable, language]);

  async function copy(): Promise<void> {
    await writeClipboardText(code);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1_500);
  }

  const figure = (
    <figure
      aria-label={collapsed ? `${fileName || language}完整内容` : undefined}
      className="agent-code-block"
      data-streaming={streamingTail || undefined}
      role={collapsed ? 'region' : undefined}
    >
      <figcaption>
        <span>
          <Code2 size={14} />
          {fileName || language}
          {!streamingTail && lineCount > 1 ? <small>{lineCount} 行</small> : null}
        </span>
        <IconButton
          size="small"
          label={copied ? '已复制' : '复制代码'}
          icon={copied ? <Check size={14} /> : <Clipboard size={14} />}
          onClick={() => void copy()}
          tooltip
        />
      </figcaption>
      {highlightable && highlighted ? (
        // Shiki emits escaped token spans from the settled text receipt; the
        // original code never reaches this path as executable HTML. The copy
        // action above keeps operating on the exact text value.
        <div
          aria-label={fileName ? `${fileName} 代码内容` : `${language} 代码内容`}
          className="agent-code-block__highlight"
          dangerouslySetInnerHTML={{ __html: highlighted }}
          data-language={language}
          role="region"
          tabIndex={0}
        />
      ) : (
        <pre
          aria-label={fileName ? `${fileName} 代码内容` : `${language} 代码内容`}
          data-language={language}
          role="region"
          tabIndex={0}
        >
          <code
            className="agent-code-block__content"
            data-stream-tail={streamingTail || undefined}
          >
            {code}
            <StreamingCursor active={streamingTail} />
          </code>
        </pre>
      )}
    </figure>
  );
  if (collapsed) {
    return (
      <Disclosure className="agent-code-collapse agent-rich-collapsible" data-tone="project" summary={<>
          <span className="agent-insert-icon"><Code2 size={15} /></span>
          <span>{fileName || language}</span>
          <small>{lineCount} 行</small>
          <ChevronRight className="agent-rich-collapsible__chevron" size={14} />
        </>}>
        {figure}
      </Disclosure>
    );
  }
  return figure;
}

export function StreamingCursor({ active }: { active: boolean }) {
  return active ? (
    <span
      aria-hidden="true"
      className="agent-streaming-cursor agent-streaming-cursor--inline"
    />
  ) : null;
}
