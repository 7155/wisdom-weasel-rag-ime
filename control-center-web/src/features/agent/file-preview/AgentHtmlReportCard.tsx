import { ExternalLink, Eye, Sparkles } from 'lucide-react';
import { Button } from '@/components/primitives';
import type { ControlTransport } from '@/platform/transport';
import { fileSizeLabel, managedContentUrl, type FilePreviewRequest } from './file-descriptor';
import { useFilePreviewStore } from './file-preview-store';

/**
 * A generated report is the thing the user actually asked for, so it does not
 * get the same one-line chip as a raw CSV sitting beside it. Measured on the
 * delivery scenario: report, source markdown and raw export rendered as three
 * identical grey slabs whose only affordance was a 16px eye icon ~700px from
 * the file name — nothing said which one was the deliverable, and nothing said
 * the preview was safe to open.
 *
 * The card stays inside the insert family (same 620px measure, same hanging
 * edge) rather than becoming a card-shaped exception; it is the emphatic member
 * of that family, not a different species.
 */
export function AgentHtmlReportCard({
  request,
  fileName,
  transport,
}: {
  request: FilePreviewRequest;
  fileName: string;
  transport: ControlTransport | null;
}) {
  const openPreview = useFilePreviewStore((state) => state.openPreview);
  const originalUrl = managedContentUrl(request);
  const size = fileSizeLabel(request.byteSizeHint);

  return (
    <section aria-labelledby={`${request.mediaId}-title`} className="agent-report-card">
      <header>
        <span className="agent-report-card__kind">HTML 报告</span>
        <strong id={`${request.mediaId}-title`}>{fileName}</strong>
      </header>
      {/* Size and the safety statement share one line: split across two rows
          the size orphaned itself under the file name for no benefit. */}
      <p className="agent-report-card__assurance">
        <Sparkles aria-hidden="true" size={14} />
        <span>{size ? `${size} · ` : ''}交互预览：保留页面样式、脚本、图表与表单</span>
      </p>
      <div className="agent-report-card__actions">
        <Button
          disabled={!transport}
          leadingIcon={<Eye size={15} />}
          onClick={() => transport && openPreview(request, transport)}
          size="small"
          variant="primary"
        >
          预览报告
        </Button>
        {originalUrl ? (
          <Button
            leadingIcon={<ExternalLink size={15} />}
            onClick={() => window.open(originalUrl, '_blank', 'noopener,noreferrer')}
            size="small"
            variant="quiet"
          >
            打开原文件
          </Button>
        ) : null}
      </div>
    </section>
  );
}
