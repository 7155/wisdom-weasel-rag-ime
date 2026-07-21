import { ExternalLink } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

export function MarkdownPreview({ content }: { content: string }) {
  return (
    <article className="agent-file-markdown">
      <ReactMarkdown
        skipHtml
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ href, children }) => {
            const safe = safeMarkdownLink(href);
            return safe ? <a href={safe} rel="noreferrer" target={safe.startsWith('http') ? '_blank' : undefined}>{children}{safe.startsWith('http') ? <ExternalLink aria-hidden="true" size={12} /> : null}</a> : <span>{children}</span>;
          },
          img: ({ alt }) => <span className="agent-file-markdown__blocked-media">{alt || '图片引用'}</span>,
          code: ({ className, children }) => {
            const fenced = Boolean(/language-[\w-]+/u.exec(className ?? '')) || String(children).endsWith('\n');
            return fenced ? <pre><code>{String(children).replace(/\n$/u, '')}</code></pre> : <code>{children}</code>;
          },
          pre: ({ children }) => <>{children}</>,
        }}
      >
        {content}
      </ReactMarkdown>
    </article>
  );
}

function safeMarkdownLink(value: string | undefined): string | null {
  if (!value || value.includes('\\') || value.startsWith('//')) return null;
  if (value.startsWith('#')) return value;
  try {
    const url = new URL(value);
    return url.protocol === 'https:' || url.protocol === 'http:' ? url.href : null;
  } catch {
    return null;
  }
}
