import {
  Check,
  Clipboard,
  Code2,
  Download,
  ExternalLink,
  File,
  FileAudio,
  Image as ImageIcon,
  ShieldAlert,
  TriangleAlert,
} from 'lucide-react';
import { useState, type ReactNode } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Button, IconButton } from '@/components/primitives';
import type { UiAgentBlock } from '@/contracts/ui-events';
import { writeClipboardText } from '@/platform/clipboard';
import { stickerAsset } from './PersonaAvatar';
import { publicAgentErrorText } from '../public-error';

export function AgentBlocks({
  blocks,
  onApprovalDecision,
  streaming = false,
}: {
  blocks: UiAgentBlock[];
  onApprovalDecision?: (approvalId: string, decision: 'approved' | 'rejected', hash: string) => void;
  streaming?: boolean;
}) {
  const tailIndex = streaming ? findLastTextBlock(blocks) : -1;
  return (
    <div className="agent-blocks" data-has-stream-tail={tailIndex >= 0 || undefined}>
      {blocks.map((block, index) => (
        <AgentBlock
          key={block.id}
          block={block}
          onApprovalDecision={onApprovalDecision}
          streamingTail={index === tailIndex}
        />
      ))}
    </div>
  );
}

export function AgentBlock({
  block,
  onApprovalDecision,
  streamingTail = false,
}: {
  block: UiAgentBlock;
  onApprovalDecision?: (approvalId: string, decision: 'approved' | 'rejected', hash: string) => void;
  streamingTail?: boolean;
}) {
  const data = block.data;
  switch (block.type) {
    case 'text':
      return <MarkdownBody streamingTail={streamingTail} text={text(data.text ?? data.markdown)} />;
    case 'code':
      return (
        <CodeBlock
          code={text(data.code ?? data.text)}
          language={text(data.language) || 'text'}
          fileName={text(data.fileName ?? data.title)}
        />
      );
    case 'citation':
      return <CitationBlock data={data} />;
    case 'image':
      return <ImageBlock data={data} />;
    case 'audio':
      return <AudioBlock data={data} />;
    case 'file':
      return <FileBlock data={data} />;
    case 'sticker':
      return <StickerBlock data={data} />;
    case 'task_plan':
      return <TaskPlanBlock data={data} />;
    case 'diff':
      return (
        <CodeBlock
          code={text(data.diff ?? data.text)}
          language="diff"
          fileName={text(data.fileName ?? data.title) || '变更预览'}
        />
      );
    case 'approval':
      return (
        <ApprovalBlock data={data} onDecision={onApprovalDecision} />
      );
    case 'error':
      return (
        <div className="agent-inline-notice" data-tone="danger" role="alert">
          <TriangleAlert size={16} />
          <span>{publicAgentErrorText(data.message ?? data.summary)}</span>
        </div>
      );
    case 'reasoning_summary':
      return (
        <details className="agent-structured-block">
          <summary>处理进度</summary>
          <p>智鼬正在整理信息与下一步。</p>
        </details>
      );
    case 'progress':
    case 'tool_call':
    case 'tool_result':
      return <StructuredSummaryBlock type={block.type} data={data} />;
    case 'unknown':
      return (
        <details className="agent-unknown-block">
          <summary>暂时无法展示这项内容</summary>
          <p>可以继续对话，或稍后刷新后重试。</p>
        </details>
      );
  }
}

export function MarkdownBody({ streamingTail = false, text: source }: { streamingTail?: boolean; text: string }) {
  if (!source) return null;
  return (
    <div className="agent-markdown">
      <ReactMarkdown
        remarkPlugins={streamingTail ? [remarkGfm, remarkStreamingTail] : [remarkGfm]}
        components={{
          a: ({ href, children }) => {
            const safe = safeLink(href);
            return safe ? (
              <a href={safe} target={safe.startsWith('http') ? '_blank' : undefined} rel="noreferrer">
                {children}
                {safe.startsWith('http') ? <ExternalLink size={12} aria-hidden="true" /> : null}
              </a>
            ) : (
              <span>{children}</span>
            );
          },
          p: ({ children, node: _node, ...props }) => <p {...props}>{children}<StreamingCursor active={hasStreamingTail(props)} /></p>,
          li: ({ children, node: _node, ...props }) => <li {...props}>{children}<StreamingCursor active={hasStreamingTail(props)} /></li>,
          td: ({ children, node: _node, ...props }) => <td {...props}>{children}<StreamingCursor active={hasStreamingTail(props)} /></td>,
          h1: ({ children, node: _node, ...props }) => <h1 {...props}>{children}<StreamingCursor active={hasStreamingTail(props)} /></h1>,
          h2: ({ children, node: _node, ...props }) => <h2 {...props}>{children}<StreamingCursor active={hasStreamingTail(props)} /></h2>,
          h3: ({ children, node: _node, ...props }) => <h3 {...props}>{children}<StreamingCursor active={hasStreamingTail(props)} /></h3>,
          code: ({ className, children, node: _node, ...props }) => {
            const match = /language-([\w-]+)/u.exec(className ?? '');
            const raw = String(children);
            const code = raw.replace(/\n$/u, '');
            const fenced = Boolean(match) || raw.endsWith('\n');
            const tail = hasStreamingTail(props);
            return fenced ? <CodeBlock code={code} language={match?.[1] ?? 'text'} streamingTail={tail} /> : <code {...props}>{children}<StreamingCursor active={tail} /></code>;
          },
          pre: ({ children }) => <>{children}</>,
          img: ({ alt }) => <span className="agent-markdown__blocked-media">{alt || '图片'}</span>,
        }}
      >
        {source}
      </ReactMarkdown>
    </div>
  );
}

function CodeBlock({
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
  async function copy(): Promise<void> {
    await writeClipboardText(code);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1_500);
  }
  return (
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
      <pre data-language={language}>
        <code data-stream-tail={streamingTail || undefined}>{code}<StreamingCursor active={streamingTail} /></code>
      </pre>
    </figure>
  );
}

function StreamingCursor({ active }: { active: boolean }) {
  return active ? <span aria-hidden="true" className="agent-streaming-cursor agent-streaming-cursor--inline" /> : null;
}

type MarkdownAstNode = {
  type?: string;
  children?: MarkdownAstNode[];
  data?: { hProperties?: Record<string, unknown> };
};

function remarkStreamingTail() {
  return (tree: MarkdownAstNode) => {
    let terminalPath: MarkdownAstNode[] = [];
    const visit = (node: MarkdownAstNode, parents: MarkdownAstNode[]) => {
      const path = [...parents, node];
      if (node.children?.length) {
        node.children.forEach((child) => visit(child, path));
      } else if (['text', 'inlineCode', 'code', 'image', 'break'].includes(node.type ?? '')) {
        terminalPath = path;
      }
    };
    visit(tree, []);
    const target = tailContainer(terminalPath);
    if (!target) return;
    target.data = target.data ?? {};
    target.data.hProperties = { ...target.data.hProperties, 'data-stream-tail': 'true' };
  };
}

function tailContainer(path: MarkdownAstNode[]) {
  for (const type of ['code', 'tableCell', 'listItem', 'paragraph', 'heading']) {
    for (let index = path.length - 1; index >= 0; index -= 1) {
      if (path[index]?.type === type) return path[index];
    }
  }
  return undefined;
}

function hasStreamingTail(props: Record<string, unknown>) {
  return props['data-stream-tail'] === true || props['data-stream-tail'] === 'true';
}

function findLastTextBlock(blocks: readonly UiAgentBlock[]) {
  for (let index = blocks.length - 1; index >= 0; index -= 1) {
    const block = blocks[index];
    if (block?.type === 'text' && block.status === 'running' && text(block.data.text ?? block.data.markdown)) return index;
  }
  return -1;
}

function CitationBlock({ data }: { data: Record<string, unknown> }) {
  const href = safeLink(text(data.href ?? data.url));
  const content = (
    <>
      <span className="agent-citation__index">{number(data.index) || '•'}</span>
      <span>
        <strong>{text(data.title ?? data.label) || '引用来源'}</strong>
        <small>{text(data.source ?? data.domain)}</small>
        {text(data.excerpt) ? <q>{text(data.excerpt)}</q> : null}
      </span>
      {href ? <ExternalLink size={14} aria-hidden="true" /> : null}
    </>
  );
  return href ? (
    <a className="agent-citation" href={href} rel="noreferrer" target={href.startsWith('http') ? '_blank' : undefined}>
      {content}
    </a>
  ) : (
    <div className="agent-citation">{content}</div>
  );
}

function ImageBlock({ data }: { data: Record<string, unknown> }) {
  const source = safeManagedImageReceipt(text(data.receiptUrl));
  if (!source) return <BlockedMedia icon={<ImageIcon size={16} />} label="图片回执不可用" />;
  return (
    <figure className="agent-media-block">
      <img src={source} alt={text(data.alt) || '对话图片'} loading="lazy" />
      {text(data.caption) ? <figcaption>{text(data.caption)}</figcaption> : null}
    </figure>
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

function AudioBlock({ data }: { data: Record<string, unknown> }) {
  const source = safeMediaSource(text(data.receiptUrl ?? data.src ?? data.url), 'audio');
  if (!source) return <BlockedMedia icon={<FileAudio size={16} />} label="音频回执不可用" />;
  return (
    <figure className="agent-audio-block">
      <figcaption><FileAudio size={16} />{text(data.name) || '音频附件'}</figcaption>
      <audio controls preload="metadata" src={source} />
    </figure>
  );
}

function FileBlock({ data }: { data: Record<string, unknown> }) {
  const href = safeMediaSource(text(data.receiptUrl ?? data.href), 'file');
  return (
    <div className="agent-file-block">
      <span className="agent-file-block__icon"><File size={18} /></span>
      <span>
        <strong>{text(data.name ?? data.fileName) || '文件产物'}</strong>
        <small>{fileMeta(data)}</small>
      </span>
      {href ? (
        <IconButton
          label="打开文件回执"
          icon={<Download size={16} />}
          onClick={() => window.open(href, '_blank', 'noopener,noreferrer')}
          tooltip
        />
      ) : null}
    </div>
  );
}

function StickerBlock({ data }: { data: Record<string, unknown> }) {
  const source = stickerAsset(text(data.assetId ?? data.stickerId));
  if (!source) return <BlockedMedia icon={<ImageIcon size={16} />} label="贴纸资产不可用" />;
  return (
    <img
      className="agent-sticker-block"
      src={source}
      alt={text(data.alt) || 'Persona 贴纸'}
      loading="lazy"
    />
  );
}

function TaskPlanBlock({ data }: { data: Record<string, unknown> }) {
  const items = Array.isArray(data.items) ? data.items : Array.isArray(data.tasks) ? data.tasks : [];
  return (
    <section className="agent-task-plan">
      <strong>{text(data.title) || '任务计划'}</strong>
      <ol>
        {items.map((item, index) => {
          const value = record(item);
          const label = text(value.title ?? value.label ?? item);
          return <li key={`${label}-${index}`} data-status={text(value.status)}>{label || `步骤 ${index + 1}`}</li>;
        })}
      </ol>
    </section>
  );
}

function ApprovalBlock({
  data,
  onDecision,
}: {
  data: Record<string, unknown>;
  onDecision?: (approvalId: string, decision: 'approved' | 'rejected', hash: string) => void;
}) {
  const approvalId = text(data.approvalId ?? data.id);
  const hash = text(data.payloadSha256);
  const pending = !['approved', 'rejected', 'applied'].includes(text(data.state));
  return (
    <section className="agent-approval-block">
      <ShieldAlert size={18} />
      <span>
        <strong>{text(data.title ?? data.summary) || '需要批准'}</strong>
        <small>{text(data.detail ?? data.action)}</small>
      </span>
      {pending && onDecision && approvalId && hash ? (
        <span className="agent-approval-block__actions">
          <Button size="small" variant="quiet" onClick={() => onDecision(approvalId, 'rejected', hash)}>拒绝</Button>
          <Button size="small" variant="primary" onClick={() => onDecision(approvalId, 'approved', hash)}>批准</Button>
        </span>
      ) : null}
    </section>
  );
}

function StructuredSummaryBlock({
  type,
  data,
}: {
  type: UiAgentBlock['type'];
  data: Record<string, unknown>;
}) {
  return (
    <details className="agent-structured-block">
      <summary>{text(data.summary ?? data.title ?? data.label) || structuredLabel(type)}</summary>
      <SafeFieldList data={data} />
    </details>
  );
}

export function SafeFieldList({ data }: { data: Record<string, unknown> }) {
  const allowed = [
    'query',
    'status',
    'resultCount',
    'books',
    'recentItems',
    'completed',
    'artifacts',
    'risk',
  ];
  const entries = allowed
    .filter((key) => Object.hasOwn(data, key))
    .map((key) => [key, safeFieldValue(data[key])] as const)
    .filter((entry) => entry[1]);
  if (entries.length === 0) return <p>暂无可展示的结构化明细。</p>;
  return (
    <dl className="agent-safe-fields">
      {entries.map(([key, value]) => (
        <div key={key}><dt>{fieldLabel(key)}</dt><dd>{value}</dd></div>
      ))}
    </dl>
  );
}

function BlockedMedia({ icon, label }: { icon: ReactNode; label: string }) {
  return <div className="agent-inline-notice" data-tone="neutral">{icon}<span>{label}</span></div>;
}

function structuredLabel(type: UiAgentBlock['type']): string {
  switch (type) {
    case 'reasoning_summary': return '处理说明';
    case 'progress': return '进度';
    case 'tool_call': return '正在使用工具';
    case 'tool_result': return '工具处理结果';
    default: return '结构化明细';
  }
}

function fieldLabel(key: string): string {
  return ({
    query: '查询', status: '状态', resultCount: '结果数', books: '工具书',
    recentItems: '近期记录', completed: '已完成', artifacts: '产物', risk: '确认级别',
  } as Record<string, string>)[key] ?? key;
}

function safeFieldValue(value: unknown): string {
  if (typeof value === 'string') return publicStructuredValue(value);
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  if (Array.isArray(value)) return value
    .filter((item) => ['string', 'number', 'boolean'].includes(typeof item))
    .map((item) => typeof item === 'string' ? publicStructuredValue(item) : String(item))
    .join('、');
  return '';
}

function publicStructuredValue(value: string): string {
  const normalized = value.trim();
  const known = ({
    ready: '可用', running: '进行中', waiting: '等待确认', completed: '已完成',
    failed: '失败', approved: '已批准', rejected: '已拒绝', R0: '只读',
    R1: '需要确认', R2: '谨慎确认', R3: '高风险',
  } as Record<string, string>)[normalized];
  if (known) return known;
  return /^[a-z][a-z0-9_.:/-]*$/i.test(normalized) ? '已记录' : normalized;
}

function safeLink(value: string | undefined): string | undefined {
  if (!value) return undefined;
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

function fileMeta(data: Record<string, unknown>): string {
  const size = number(data.byteSize ?? data.size);
  const sizeText = size ? (size >= 1_048_576 ? `${(size / 1_048_576).toFixed(1)} MB` : `${Math.ceil(size / 1_024)} KB`) : '';
  return [text(data.mimeType ?? data.type), sizeText].filter(Boolean).join(' · ') || '受控文件回执';
}

function record(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function text(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

function number(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}
