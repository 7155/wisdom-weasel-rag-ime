import { Check, ChevronRight, Clipboard, Code2, FileDiff } from 'lucide-react';
import { useState } from 'react';
import { IconButton } from '@/components/primitives';
import { writeClipboardText } from '@/platform/clipboard';
import { DiffPreview } from '../file-preview/DiffPreview';
import type { AgentBlockRenderProps } from './renderer-contract';
import { text } from './renderer-values';

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
    <details
      className="agent-inline-diff agent-rich-collapsible"
      data-tone="project"
      open={lineCount <= 80}
    >
      <summary>
        <span className="agent-insert-icon"><FileDiff size={15} /></span>
        <span>{title}</span>
        <small>{lineCount} 行</small>
        <ChevronRight className="agent-rich-collapsible__chevron" size={14} />
      </summary>
      <DiffPreview content={content} fileName={title} />
    </details>
  );
}

export function CodeContentBlock({
  code,
  language,
  fileName,
  streamingTail = false,
  lineNumbers = false,
  startLine = 1,
}: {
  code: string;
  language: string;
  fileName?: string;
  streamingTail?: boolean;
  lineNumbers?: boolean;
  startLine?: number;
}) {
  const [copied, setCopied] = useState(false);

  async function copy(): Promise<void> {
    await writeClipboardText(code);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1_500);
  }

  const figure = (
    <figure className="agent-code-block">
      <figcaption>
        <span>
          <Code2 size={14} />
          {fileName || language}
        </span>
        <IconButton
          size="small"
          label={copied ? '已复制' : '复制代码'}
          icon={copied ? <Check size={14} /> : <Clipboard size={14} />}
          onClick={() => void copy()}
          tooltip
        />
      </figcaption>
      <pre
        aria-label={fileName ? `${fileName} 代码内容` : `${language} 代码内容`}
        data-language={language}
        tabIndex={0}
      >
        <code
          className="agent-code-block__content"
          data-line-numbers={lineNumbers || undefined}
          data-stream-tail={streamingTail || undefined}
        >
          {lineNumbers
            ? code.split('\n').map((line, index, lines) => (
                <span
                  className="agent-code-block__line"
                  data-line-number={Math.max(1, startLine) + index}
                  key={`${Math.max(1, startLine) + index}:${line}`}
                >
                  <span>{line || '\u00a0'}</span>
                  <StreamingCursor active={streamingTail && index === lines.length - 1} />
                </span>
              ))
            : <>{code}<StreamingCursor active={streamingTail} /></>}
        </code>
      </pre>
    </figure>
  );
  const lineCount = code ? code.split('\n').length : 0;
  if (!streamingTail && (lineCount > 32 || code.length > 4_000)) {
    return (
      <details className="agent-code-collapse agent-rich-collapsible" data-tone="project">
        <summary>
          <span className="agent-insert-icon"><Code2 size={15} /></span>
          <span>{fileName || language}</span>
          <small>{lineCount} 行</small>
          <ChevronRight className="agent-rich-collapsible__chevron" size={14} />
        </summary>
        {figure}
      </details>
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
