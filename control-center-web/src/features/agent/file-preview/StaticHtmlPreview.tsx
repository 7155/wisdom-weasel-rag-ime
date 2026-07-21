import { useMemo } from 'react';
import { staticHtmlDocument } from './static-html';

export function StaticHtmlPreview({ content, title }: { content: string; title: string }) {
  const document = useMemo(() => staticHtmlDocument(content), [content]);
  return (
    <iframe
      className="agent-static-html-preview"
      referrerPolicy="no-referrer"
      sandbox=""
      srcDoc={document}
      title={`${title} 静态预览`}
    />
  );
}
