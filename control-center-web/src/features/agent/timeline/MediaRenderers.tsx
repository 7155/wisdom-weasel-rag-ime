import {
  ExternalLink,
  FileAudio,
  Image as ImageIcon,
  PackageOpen,
} from 'lucide-react';
import { IconButton } from '@/components/primitives';
import { AgentFileBlock } from '../file-preview/AgentFileBlock';
import { stickerAsset } from './PersonaAvatar';
import { BlockedMedia } from './StructuredRenderers';
import type { AgentBlockRenderProps } from './renderer-contract';
import { finiteNumber, text } from './renderer-values';

export function ArtifactBlockRenderer({ block }: AgentBlockRenderProps) {
  const data = block.data;
  const href = safeArtifactLink(text(data.receiptUrl ?? data.href ?? data.url));
  const name = text(data.title ?? data.name ?? data.fileName) || '任务产物';
  return (
    <section className="agent-rich-artifact" aria-label={name}>
      <PackageOpen size={18} />
      <span>
        <strong>{name}</strong>
        <small>{text(data.summary) || fileMeta(data)}</small>
      </span>
      {href ? (
        <IconButton
          label="打开产物回执"
          icon={<ExternalLink size={16} />}
          onClick={() => window.open(href, '_blank', 'noopener,noreferrer')}
          tooltip
        />
      ) : null}
    </section>
  );
}

export function CitationBlockRenderer({ block }: AgentBlockRenderProps) {
  const data = block.data;
  const href = safeLink(text(data.href ?? data.url));
  const content = (
    <>
      <span className="agent-citation__index">{finiteNumber(data.index) || '•'}</span>
      <span>
        <strong>{text(data.title ?? data.label) || '引用来源'}</strong>
        <small>{text(data.source ?? data.domain)}</small>
        {text(data.excerpt) ? <q>{text(data.excerpt)}</q> : null}
      </span>
      {href ? <ExternalLink size={14} aria-hidden="true" /> : null}
    </>
  );
  return href ? (
    <a
      className="agent-citation"
      href={href}
      rel="noreferrer"
      target={href.startsWith('http') ? '_blank' : undefined}
    >
      {content}
    </a>
  ) : (
    <div className="agent-citation">{content}</div>
  );
}

export function ImageBlockRenderer({ block }: AgentBlockRenderProps) {
  const data = block.data;
  const source = safeManagedImageReceipt(text(data.receiptUrl));
  if (!source) {
    return <BlockedMedia icon={<ImageIcon size={16} />} label="图片回执不可用" />;
  }
  const width = imageDimension(data.width ?? data.pixelWidth);
  const height = imageDimension(data.height ?? data.pixelHeight);
  return (
    <figure className="agent-media-block">
      <img
        src={source}
        alt={text(data.alt) || '对话图片'}
        loading="lazy"
        decoding="async"
        width={width || undefined}
        height={height || undefined}
      />
      {text(data.caption) ? <figcaption>{text(data.caption)}</figcaption> : null}
    </figure>
  );
}

export function AudioBlockRenderer({ block }: AgentBlockRenderProps) {
  const data = block.data;
  const source = safeMediaSource(text(data.receiptUrl ?? data.src ?? data.url), 'audio');
  if (!source) {
    return <BlockedMedia icon={<FileAudio size={16} />} label="音频回执不可用" />;
  }
  return (
    <figure className="agent-audio-block">
      <figcaption><FileAudio size={16} />{text(data.name) || '音频附件'}</figcaption>
      <audio controls preload="metadata" src={source} />
    </figure>
  );
}

export function FileBlockRenderer({ block, sessionId }: AgentBlockRenderProps) {
  return <AgentFileBlock data={block.data} sessionId={sessionId} />;
}

export function StickerBlockRenderer({ block }: AgentBlockRenderProps) {
  const data = block.data;
  const source = stickerAsset(text(data.assetId ?? data.stickerId));
  if (!source) {
    return <BlockedMedia icon={<ImageIcon size={16} />} label="贴纸资产不可用" />;
  }
  return (
    <img
      className="agent-sticker-block"
      src={source}
      alt={text(data.alt) || 'Persona 贴纸'}
      loading="lazy"
    />
  );
}

export function UnknownBlockRenderer({ block }: AgentBlockRenderProps) {
  const label = text(block.rawType) || text(block.presentationKind) || 'unknown';
  const summary = text(block.summary);
  return (
    <details className="agent-unknown-block">
      <summary>暂不支持的内容 · {label}</summary>
      <p>{summary || '内容已安全保留，可以继续对话或在审计区查看原始记录。'}</p>
    </details>
  );
}

function safeManagedImageReceipt(value: string): string | null {
  if (!value.startsWith('/api/agent/media/')) return null;
  try {
    const url = new URL(value, 'http://rag-ime.local');
    if (!/^\/api\/agent\/media\/[^/]+\/content$/u.test(url.pathname) || url.hash) return null;
    const sessionIds = url.searchParams.getAll('sessionId');
    if (sessionIds.length !== 1 || !/^[A-Za-z0-9._:-]{1,240}$/u.test(sessionIds[0] ?? '')) return null;
    if ([...url.searchParams.keys()].some((key) => key !== 'sessionId')) return null;
    return `${url.pathname}?sessionId=${encodeURIComponent(sessionIds[0]!)}`;
  } catch {
    return null;
  }
}

function safeLink(value: string | undefined): string | undefined {
  if (!value) return undefined;
  if (value.includes('\\') || value.startsWith('//')) return undefined;
  if (value.startsWith('#/') || value.startsWith('/')) return value;
  try {
    const url = new URL(value);
    return url.protocol === 'https:' || url.protocol === 'http:' ? url.href : undefined;
  } catch {
    return undefined;
  }
}

function safeMediaSource(value: string, kind: 'image' | 'audio' | 'file'): string | null {
  if (!value) return null;
  if (value.startsWith('/companions/') && kind === 'image') return value;
  if (value.startsWith('/api/agent/') || value.startsWith('/media/') || value.startsWith('blob:')) return value;
  return null;
}

function safeArtifactLink(value: string): string | null {
  const managed = safeMediaSource(value, 'file');
  if (managed) return managed;
  const external = safeLink(value);
  return external?.startsWith('https://') ? external : null;
}

function fileMeta(data: Record<string, unknown>): string {
  const size = finiteNumber(data.byteSize ?? data.size);
  const sizeText = size
    ? size >= 1_048_576
      ? `${(size / 1_048_576).toFixed(1)} MB`
      : `${Math.ceil(size / 1_024)} KB`
    : '';
  return [text(data.mimeType ?? data.type), sizeText].filter(Boolean).join(' · ')
    || '受控文件回执';
}

function imageDimension(value: unknown): number {
  const dimension = finiteNumber(value);
  return dimension >= 1 && dimension <= 8_192 ? Math.round(dimension) : 0;
}
