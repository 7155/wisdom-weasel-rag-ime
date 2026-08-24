import { ExternalLink, FileText, Globe2, LoaderCircle, RefreshCw, TriangleAlert } from 'lucide-react';
import { useOptionalControlTransport } from '@/app/control-transport';
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  IconButton,
} from '@/components/primitives';
import { CopyTextButton } from './CopyTextButton';
import { fileSizeLabel } from './file-descriptor';
import { useFilePreviewStore } from './file-preview-store';
import { FilePreviewRenderer } from './renderer-registry';
import './file-preview.css';

export function FilePreviewHost() {
  const transport = useOptionalControlTransport();
  const open = useFilePreviewStore((state) => state.open);
  const presentation = useFilePreviewStore((state) => state.presentation);
  const request = useFilePreviewStore((state) => state.request);
  const status = useFilePreviewStore((state) => state.status);
  const preview = useFilePreviewStore((state) => state.preview);
  const error = useFilePreviewStore((state) => state.error);
  const close = useFilePreviewStore((state) => state.close);
  const retry = useFilePreviewStore((state) => state.retry);
  const descriptor = preview?.descriptor;
  const fileName = descriptor?.fileName || request?.fileNameHint || '文件预览';
  const meta = descriptor
    ? [descriptor.mimeType, fileSizeLabel(descriptor.byteSize)].filter(Boolean).join(' · ')
    : [request?.mimeTypeHint, fileSizeLabel(request?.byteSizeHint ?? 0)].filter(Boolean).join(' · ');

  return (
    <Dialog open={open && presentation === 'dialog'} onOpenChange={(next) => { if (!next) close(); }}>
      <DialogContent className="agent-file-preview-dialog">
        <DialogHeader>
          {/* The icon names what is being previewed rather than defaulting to a
              generic page: an HTML report and a markdown handoff are not the
              same kind of thing to open. */}
          <span className="agent-file-preview-dialog__icon">
            {descriptor?.previewKind === 'html' ? <Globe2 size={20} /> : <FileText size={20} />}
          </span>
          <DialogTitle>{fileName}</DialogTitle>
          <DialogDescription>{meta || '正在读取受控文件回执'}</DialogDescription>
          {descriptor ? (
            <span className="agent-file-preview-dialog__actions">
              {typeof preview?.content === 'string' && preview.content ? (
                <CopyTextButton label={`${fileName} 内容`} value={preview.content} />
              ) : null}
              <IconButton
                className="agent-file-preview-dialog__download"
                icon={<ExternalLink size={16} />}
                label="打开原文件"
                onClick={() => window.open(descriptor.contentUrl, '_blank', 'noopener,noreferrer')}
                tooltip
              />
            </span>
          ) : null}
        </DialogHeader>
        {preview?.truncated ? <div className="agent-file-preview-dialog__notice">文件较大，当前显示前 512 KB。</div> : null}
        <div className="agent-file-preview-dialog__body" data-preview-kind={status === 'ready' ? descriptor?.previewKind : undefined} data-status={status}>
          {status === 'loading' ? <div className="agent-file-preview-dialog__state"><LoaderCircle size={20} /><span>正在读取文件</span></div> : null}
          {status === 'error' ? (
            <div className="agent-file-preview-dialog__state" role="alert">
              <TriangleAlert size={20} />
              <span>{error}</span>
              <Button disabled={!transport} leadingIcon={<RefreshCw size={15} />} onClick={() => transport && retry(transport)} size="small" variant="quiet">重试</Button>
            </div>
          ) : null}
          {status === 'ready' && preview ? <FilePreviewRenderer preview={preview} /> : null}
        </div>
      </DialogContent>
    </Dialog>
  );
}
