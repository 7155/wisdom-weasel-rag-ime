import { useState } from 'react';
import { SegmentedControl } from '@/components/primitives';
import type { AgentFilePreviewV1 } from '@/contracts/generated/agent-file-preview.v1';
import { CodePreview } from './CodePreview';
import { RichHtmlPreview } from './RichHtmlPreview';

type HtmlArtifactView = 'preview' | 'source';

/**
 * A rendered HTML report must stay verifiable: the same managed receipt can be
 * read as raw source without leaving the dialog, so a reader never has to
 * trust the sandboxed rendering alone (PF-CM-008).
 */
export function HtmlArtifactPreview({ preview }: { preview: AgentFilePreviewV1 }) {
  const [view, setView] = useState<HtmlArtifactView>('preview');
  const fileName = preview.descriptor.fileName;
  const content = preview.content ?? '';
  return (
    <div className="agent-html-artifact" data-view={view}>
      <header className="agent-html-artifact__bar">
        <small>
          {view === 'preview'
            ? '沙箱渲染 · 脚本无法访问会话数据'
            : '原始 HTML · 与渲染页面来自同一份受控回执'}
        </small>
        <SegmentedControl
          aria-label={`${fileName} 展示形式`}
          items={[
            { value: 'preview', label: '渲染预览' },
            { value: 'source', label: 'HTML 源码' },
          ]}
          onValueChange={setView}
          value={view}
        />
      </header>
      {view === 'preview'
        ? <RichHtmlPreview content={content} title={fileName} />
        : <CodePreview content={content} fileName={fileName} language="html" />}
    </div>
  );
}
