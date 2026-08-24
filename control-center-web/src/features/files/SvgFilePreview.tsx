import { Code2, Image, TriangleAlert } from 'lucide-react';
import { useMemo, useState } from 'react';
import { CodePreview } from '@/features/agent/file-preview/CodePreview';

/**
 * SVG is the one media type the bounded UTF-8 read route can deliver whole.
 * The image view renders through a data URL inside an <img>, which never
 * executes embedded scripts or loads external references; the source view
 * reuses the shared code reader and its owned colour pair.
 */
export function SvgFilePreview({ content, fileName }: { content: string; fileName: string }) {
  const [view, setView] = useState<'image' | 'source'>('image');
  const [renderFailed, setRenderFailed] = useState(false);
  const url = useMemo(
    () => `data:image/svg+xml;charset=utf-8,${encodeURIComponent(content)}`,
    [content],
  );

  return (
    <div className="paw-files-svg" data-view={view}>
      <div aria-label="SVG 预览方式" className="paw-files-svg__bar" role="group">
        <button aria-pressed={view === 'image'} onClick={() => setView('image')} type="button"><Image size={13} /><span>图像</span></button>
        <button aria-pressed={view === 'source'} onClick={() => setView('source')} type="button"><Code2 size={13} /><span>源码</span></button>
      </div>
      {view === 'image' ? (
        renderFailed ? (
          <div className="paw-files-preview__state" role="status">
            <TriangleAlert size={18} />
            <span>这个 SVG 无法作为图像渲染，可切换到源码视图。</span>
          </div>
        ) : (
          <div className="paw-files-svg__stage">
            <img alt={`${fileName} 矢量图预览`} onError={() => setRenderFailed(true)} src={url} />
          </div>
        )
      ) : (
        <CodePreview content={content} fileName={fileName} language="xml" />
      )}
    </div>
  );
}
