import { Eye, File, FileCode2, FileDiff, FileImage, FileText, Globe2 } from 'lucide-react';
import type { ReactNode } from 'react';
import { useOptionalControlTransport } from '@/app/control-transport';
import { filePreviewRequestFromBlock, fileSizeLabel } from './file-descriptor';
import { useFilePreviewStore } from './file-preview-store';
import './file-preview.css';

export function AgentFileBlock({ data, sessionId = '' }: { data: Record<string, unknown>; sessionId?: string }) {
  const transport = useOptionalControlTransport();
  const openPreview = useFilePreviewStore((state) => state.openPreview);
  const request = filePreviewRequestFromBlock(data, sessionId);
  const fileName = request?.fileNameHint || string(data.fileName ?? data.name ?? data.title) || '文件产物';
  const meta = [request?.mimeTypeHint || string(data.mimeType), fileSizeLabel(request?.byteSizeHint ?? 0)].filter(Boolean).join(' · ');
  const available = Boolean(request && transport);

  return (
    <button
      aria-label={available ? `预览 ${fileName}` : `${fileName} 的预览回执不可用`}
      className="agent-file-block"
      data-disabled={!available || undefined}
      disabled={!available}
      onClick={() => request && transport && openPreview(request, transport)}
      type="button"
    >
      <span className="agent-file-block__icon">{fileIcon(fileName, request?.mimeTypeHint ?? '')}</span>
      <span><strong>{fileName}</strong><small>{meta || '受控文件'}</small></span>
      <Eye aria-hidden="true" size={16} />
    </button>
  );
}

function fileIcon(fileName: string, mimeType: string): ReactNode {
  const lower = fileName.toLowerCase();
  if (mimeType.startsWith('image/')) return <FileImage size={18} />;
  if (/\.(?:md|markdown|mdx)$/u.test(lower)) return <FileText size={18} />;
  if (/\.(?:diff|patch)$/u.test(lower)) return <FileDiff size={18} />;
  if (/\.(?:html|htm)$/u.test(lower)) return <Globe2 size={18} />;
  if (mimeType.startsWith('text/') || /\.[a-z0-9]{1,8}$/u.test(lower)) return <FileCode2 size={18} />;
  return <File size={18} />;
}

function string(value: unknown): string {
  return typeof value === 'string' ? value : '';
}
