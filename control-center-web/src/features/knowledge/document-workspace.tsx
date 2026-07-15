import {
  ChevronDown,
  CircleStop,
  Download,
  Eye,
  FileImage,
  FileSearch,
  FileText,
  GalleryHorizontalEnd,
  Grid3X3,
  PanelRightOpen,
  RotateCcw,
  Rows3,
  Table2,
  Trash2,
  Upload,
} from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import { Virtuoso } from 'react-virtuoso';
import remarkGfm from 'remark-gfm';
import { Button, EmptyState, IconButton, Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/primitives';
import { InlineNotice, StatusBadge, publicErrorText } from '@/features/overview/management-ui';
import type { ControlTransport } from '@/platform/transport';
import type {
  KnowledgeAsset,
  KnowledgeDocument,
  KnowledgeDocumentDetail,
  KnowledgeIndexJob,
  KnowledgeParserMode,
  KnowledgeSearchHit,
  KnowledgeTableArtifact,
} from './api';

export interface KnowledgeUploadItem {
  id: string;
  fileName: string;
  byteSize: number;
  parser: KnowledgeParserMode;
  status: 'queued' | 'uploading' | 'accepted' | 'failed';
  documentId: string;
  error: string;
  file?: File;
}

export function KnowledgeMaterialsPanel({
  detail,
  detailError,
  detailLoading,
  documents,
  error,
  importError,
  importing,
  onDelete,
  onImport,
  onOpen,
  onReparse,
  onRetryUpload,
  onClearUploads,
  onSelect,
  pendingDocumentId,
  selectedDocumentId,
  uploadItems,
}: {
  detail: KnowledgeDocumentDetail | null;
  detailError: Error | null;
  detailLoading: boolean;
  documents: readonly KnowledgeDocument[];
  error: Error | null;
  importError: Error | null;
  importing: boolean;
  onDelete: (document: KnowledgeDocument) => void;
  onImport: () => void;
  onOpen: (documentId: string) => void;
  onReparse: (document: KnowledgeDocument) => void;
  onRetryUpload: (item: KnowledgeUploadItem) => void;
  onClearUploads: () => void;
  onSelect: (documentId: string) => void;
  pendingDocumentId: string;
  selectedDocumentId: string;
  uploadItems: readonly KnowledgeUploadItem[];
}) {
  const summary = useMemo(() => summarizeDocuments(documents), [documents]);
  const selected = documents.find((item) => item.id === selectedDocumentId) ?? documents[0] ?? null;
  return (
    <div className="knowledge-panel knowledge-materials">
      <div className="knowledge-panel__toolbar">
        <div><strong>资料</strong><span>{documents.length} 个文件 · {formatBytes(summary.bytes)} · {summary.ready} 个可检索</span></div>
        <Button leadingIcon={<Upload size={15} />} loading={importing} onClick={onImport} size="small" variant="primary">导入文件</Button>
      </div>
      <dl className="knowledge-material-stats">
        <div><dt>可检索</dt><dd>{summary.ready}</dd></div>
        <div><dt>处理中</dt><dd>{summary.processing}</dd></div>
        <div><dt>需处理</dt><dd>{summary.attention}</dd></div>
        <div><dt>当前产物</dt><dd>{detail ? detail.assets.length + detail.tables.length : 0}</dd></div>
      </dl>
      <UploadQueue items={uploadItems} onClear={onClearUploads} onRetry={onRetryUpload} />
      {error ? <InlineNotice title="文件列表暂不可用" tone="warning">{publicErrorText(error, '刷新后重试。')}</InlineNotice> : null}
      {importError ? <InlineNotice title="导入未完成" tone="warning">{publicErrorText(importError, '请查看上传队列后重试。')}</InlineNotice> : null}
      {documents.length ? (
        <div className="knowledge-material-workspace">
          <div className="knowledge-material-list" aria-label="知识库文件">
            <div className="knowledge-material-list__head"><span>文件</span><span>状态</span><span>片段</span><span>操作</span></div>
            <Virtuoso
              className="knowledge-material-list__body"
              data={documents}
              itemContent={(_index, document) => (
                <div className="knowledge-material-row" data-selected={selected?.id === document.id || undefined}>
                  <button className="knowledge-material-row__select" onClick={() => onSelect(document.id)} type="button">
                    <FileText aria-hidden="true" size={15} />
                    <span><strong>{document.name}</strong><small>{document.parser || '等待解析器'} · {formatBytes(document.byteSize)}</small></span>
                  </button>
                  <StatusBadge label={documentStatusLabel(document.status)} tone={documentTone(document.status)} />
                  <span className="knowledge-material-row__chunks">{document.chunkCount || '—'}</span>
                  <span className="knowledge-material-row__actions">
                    <IconButton disabled={pendingDocumentId === document.id || ['queued', 'parsing', 'indexing'].includes(document.status)} icon={<RotateCcw size={13} />} label={`重新解析 ${document.name}`} onClick={() => onReparse(document)} size="small" tooltip />
                    <IconButton icon={<PanelRightOpen size={13} />} label={`查看 ${document.name}`} onClick={() => onOpen(document.id)} size="small" tooltip />
                    <IconButton icon={<Trash2 size={13} />} label={`删除 ${document.name}`} onClick={() => onDelete(document)} size="small" tooltip />
                  </span>
                  {['queued', 'parsing', 'indexing'].includes(document.status) ? <i className="knowledge-material-row__progress" style={{ '--document-progress': document.progress } as React.CSSProperties} /> : null}
                </div>
              )}
            />
          </div>
          <DocumentSummary detail={detail} document={selected} error={detailError} loading={detailLoading} />
        </div>
      ) : (
        <EmptyState action={<Button leadingIcon={<Upload size={15} />} loading={importing} onClick={onImport}>导入文件</Button>} description="" icon={FileText} title="还没有资料" />
      )}
    </div>
  );
}

function UploadQueue({ items, onClear, onRetry }: { items: readonly KnowledgeUploadItem[]; onClear: () => void; onRetry: (item: KnowledgeUploadItem) => void }) {
  if (!items.length) return null;
  const active = items.filter((item) => item.status === 'queued' || item.status === 'uploading').length;
  const failed = items.filter((item) => item.status === 'failed').length;
  return (
    <section className="knowledge-upload-queue" aria-label="上传队列">
      <header><div><strong>上传队列</strong><span>{active} 个处理中 · {failed} 个失败 · {items.length} 个文件</span></div><Button disabled={active > 0} onClick={onClear} size="small" variant="quiet">清空记录</Button></header>
      <div>
        {items.map((item) => (
          <article key={item.id}>
            <Upload size={14} />
            <span><strong>{item.fileName}</strong><small>{formatBytes(item.byteSize)} · {parserLabel(item.parser)}</small>{item.error ? <em>{item.error}</em> : null}</span>
            <StatusBadge label={uploadStatusLabel(item.status)} tone={uploadTone(item.status)} />
            {item.status === 'failed' ? <IconButton icon={<RotateCcw size={13} />} label={`重试上传 ${item.fileName}`} onClick={() => onRetry(item)} size="small" tooltip /> : null}
          </article>
        ))}
      </div>
    </section>
  );
}

function DocumentSummary({ detail, document, error, loading }: { detail: KnowledgeDocumentDetail | null; document: KnowledgeDocument | null; error: Error | null; loading: boolean }) {
  if (!document) return null;
  return (
    <aside className="knowledge-document-summary" aria-label={`${document.name} 元数据`}>
      <header><FileText size={17} /><div><strong>{document.name}</strong><span>{document.mimeType || '未知格式'}</span></div></header>
      {loading ? <p className="knowledge-detail-loading">正在读取材料详情…</p> : null}
      {error ? <InlineNotice title="详情暂不可用" tone="warning">{publicErrorText(error, '稍后重试。')}</InlineNotice> : null}
      <dl>
        <div><dt>解析状态</dt><dd>{documentStatusLabel(document.status)}</dd></div>
        <div><dt>解析器</dt><dd>{document.parser || '未记录'}{document.parserVersion ? ` · ${document.parserVersion}` : ''}</dd></div>
        <div><dt>页数</dt><dd>{document.pageCount || detail?.pages.length || '未提供'}</dd></div>
        <div><dt>片段</dt><dd>{detail?.chunkTotal || document.chunkCount || 0}</dd></div>
        <div><dt>Token</dt><dd>{document.tokenCount || '未提供'}</dd></div>
        <div><dt>文件大小</dt><dd>{formatBytes(document.byteSize)}</dd></div>
        <div><dt>更新时间</dt><dd>{formatTime(document.updatedAtMs)}</dd></div>
        <div><dt>内容指纹</dt><dd>{shortHash(document.sha256)}</dd></div>
      </dl>
      {document.error ? <p className="knowledge-document-summary__error">{document.error}</p> : null}
      <div className="knowledge-document-summary__counts">
        <span><FileImage size={13} />{detail?.assets.length ?? 0} 个图片/附件</span>
        <span><Table2 size={13} />{detail?.tables.length ?? 0} 个表格</span>
      </div>
    </aside>
  );
}

export function KnowledgeDocumentViewer({
  detail,
  error,
  loading,
  onSelectDocument,
  selectedDocumentId,
  documents,
  transport,
  focusHit,
  hasMoreChunks,
  hasMoreContent,
  loadingMoreChunks,
  loadingMoreContent,
  onLoadMoreChunks,
  onLoadMoreContent,
}: {
  detail: KnowledgeDocumentDetail | null;
  error: Error | null;
  loading: boolean;
  onSelectDocument: (documentId: string) => void;
  selectedDocumentId: string;
  documents: readonly KnowledgeDocument[];
  transport: ControlTransport;
  focusHit: KnowledgeSearchHit | null;
  hasMoreChunks: boolean;
  hasMoreContent: boolean;
  loadingMoreChunks: boolean;
  loadingMoreContent: boolean;
  onLoadMoreChunks: () => void;
  onLoadMoreContent: () => void;
}) {
  const [view, setView] = useState<'source' | 'markdown' | 'chunks' | 'artifacts'>('markdown');
  const pageCount = detail ? detail.pages.length || detail.document.pageCount : 0;
  useEffect(() => setView('markdown'), [selectedDocumentId]);
  useEffect(() => { if (focusHit?.documentId === selectedDocumentId) setView('chunks'); }, [focusHit, selectedDocumentId]);
  if (!documents.length) return <EmptyState description="" icon={FileText} title="先导入资料" />;
  return (
    <div className="knowledge-panel knowledge-viewer">
      <div className="knowledge-viewer__bar">
        <label><span>材料</span><select className="ui-input" onChange={(event) => onSelectDocument(event.target.value)} value={selectedDocumentId || documents[0]?.id}>{documents.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        {detail ? <span>{detail.chunkTotal} 个片段 · {pageCount ? `${pageCount} 页` : '页码未提供'} · {detail.assets.length} 个产物</span> : null}
      </div>
      {loading ? <p className="knowledge-detail-loading">正在读取解析结果…</p> : null}
      {error ? <InlineNotice title="材料查看不可用" tone="warning">{publicErrorText(error, '稍后重试。')}</InlineNotice> : null}
      {detail ? (
        <Tabs className="knowledge-document-tabs" onValueChange={(value) => setView(value === 'source' || value === 'chunks' || value === 'artifacts' ? value : 'markdown')} value={view}>
          <TabsList aria-label="材料查看方式">
            <TabsTrigger value="source"><FileText size={13} />源文件</TabsTrigger>
            <TabsTrigger value="markdown"><Rows3 size={13} />Markdown</TabsTrigger>
            <TabsTrigger value="chunks"><Grid3X3 size={13} />Chunks</TabsTrigger>
            <TabsTrigger value="artifacts"><GalleryHorizontalEnd size={13} />解析产物</TabsTrigger>
          </TabsList>
          <TabsContent value="source"><DocumentSource detail={detail} transport={transport} /></TabsContent>
          <TabsContent value="markdown"><DocumentContent detail={detail} hasMore={hasMoreContent} loadingMore={loadingMoreContent} onLoadMore={onLoadMoreContent} /></TabsContent>
          <TabsContent value="chunks"><ChunkGallery detail={detail} focusHit={focusHit?.documentId === selectedDocumentId ? focusHit : null} hasMore={hasMoreChunks} loadingMore={loadingMoreChunks} onLoadMore={onLoadMoreChunks} /></TabsContent>
          <TabsContent value="artifacts"><ArtifactGallery assets={detail.assets} document={detail.document} tables={detail.tables} transport={transport} /></TabsContent>
        </Tabs>
      ) : null}
    </div>
  );
}

function DocumentContent({ detail, hasMore, loadingMore, onLoadMore }: { detail: KnowledgeDocumentDetail; hasMore: boolean; loadingMore: boolean; onLoadMore: () => void }) {
  if (detail.contentWindow.length) {
    const markdown = detail.contentWindow.map((line) => line.content).join('\n');
    return (
      <div className="knowledge-markdown-preview">
        <header><span>Markdown</span><b>{detail.contentWindow.length} / {detail.contentLineTotal || detail.contentWindow.length} 行 · {formatBytes(detail.artifact.byteSize)}</b></header>
        <div className="knowledge-markdown-body">
          <ReactMarkdown
            components={{
              img: ({ alt }) => <span className="knowledge-markdown-blocked-image">图片引用已隔离：{alt || '未命名图片'}</span>,
              a: ({ children, href }) => { const safe = safeMarkdownLink(href); return safe ? <a href={safe} rel="noreferrer" target="_blank">{children}</a> : <span>{children}</span>; },
            }}
            remarkPlugins={[remarkGfm]}
          >{markdown}</ReactMarkdown>
        </div>
        {hasMore ? <footer><span>已加载 {detail.contentWindow.length} / {detail.contentLineTotal} 行</span><Button loading={loadingMore} onClick={onLoadMore} size="small">继续加载 Markdown</Button></footer> : null}
      </div>
    );
  }
  const pages = groupChunksByPage(detail);
  return pages.length ? (
    <div className="knowledge-page-preview">
      {pages.map((page) => (
        <section key={page.key}>
          <header><span>{page.page ? `第 ${page.page} 页` : '无页码内容'}</span><b>{page.chunks.length} 个片段</b></header>
          {page.chunks.map((chunk) => <article key={chunk.id}>{chunk.heading ? <h4>{chunk.heading}</h4> : null}<p>{chunk.content}</p></article>)}
        </section>
      ))}
    </div>
  ) : <EmptyState description="" icon={FileText} title="暂无解析正文" />;
}

function DocumentSource({ detail, transport }: { detail: KnowledgeDocumentDetail; transport: ControlTransport }) {
  const source = useKnowledgeDocumentSource(detail, transport);
  if (!detail.document.sourceReadPath || !transport.readKnowledgeDocumentSource) {
    return <EmptyState description="" icon={FileText} title="源文件预览不可用" />;
  }
  if (source.loading) return <p className="knowledge-detail-loading">正在安全读取源文件…</p>;
  if (source.error || !source.url) {
    return <InlineNotice title="源文件暂不可用" tone="warning">{source.error ? publicErrorText(source.error, '稍后重试。') : '稍后重试。'}</InlineNotice>;
  }
  if (source.mimeType === 'application/pdf') {
    return <iframe className="knowledge-source-frame" src={source.url} title={`${detail.document.name} 源文件`} />;
  }
  if (source.mimeType.startsWith('image/')) {
    return <div className="knowledge-source-image"><img alt={detail.document.name} src={source.url} /></div>;
  }
  return <div className="knowledge-source-fallback"><FileText size={24} /><strong>{detail.document.name}</strong><a href={source.url} rel="noreferrer" target="_blank">打开源文件</a></div>;
}

function ChunkGallery({ detail, focusHit, hasMore, loadingMore, onLoadMore }: { detail: KnowledgeDocumentDetail; focusHit: KnowledgeSearchHit | null; hasMore: boolean; loadingMore: boolean; onLoadMore: () => void }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const focusedLoaded = Boolean(focusHit && detail.chunks.some((chunk) => chunk.id === focusHit.id));
  useEffect(() => {
    if (focusHit && !focusedLoaded && hasMore && !loadingMore) onLoadMore();
  }, [focusHit, focusedLoaded, hasMore, loadingMore, onLoadMore]);
  useEffect(() => {
    if (!focusHit || !focusedLoaded) return;
    const node = containerRef.current?.querySelector<HTMLElement>('[data-focused="true"]');
    if (node && typeof node.scrollIntoView === 'function') node.scrollIntoView({ block: 'center' });
  }, [focusHit, focusedLoaded, detail.chunks.length]);
  return detail.chunks.length ? (
    <div className="knowledge-chunk-grid" ref={containerRef}>
      {focusHit ? <div className="knowledge-focus-banner"><FileSearch size={14} /><span>{focusedLoaded ? `已定位检索命中：${focusHit.title}` : hasMore ? `正在加载命中片段：${focusHit.title}` : `命中来自较早的索引 revision：${focusHit.title}`}</span></div> : null}
      {detail.chunks.map((chunk) => (
        <article data-focused={focusHit?.id === chunk.id || undefined} key={chunk.id}>
          <header><b>#{chunk.ordinal + 1}{focusHit?.id === chunk.id ? ' · 检索命中' : ''}</b><span>{chunk.page ? `第 ${chunk.page} 页` : chunk.lineStart ? `第 ${chunk.lineStart} 行` : '无页码'}</span></header>
          {chunk.heading ? <h4>{chunk.heading}</h4> : null}
          <p>{focusHit?.id === chunk.id ? <HighlightedChunkText content={chunk.content} excerpt={focusHit.excerpt} /> : chunk.content}</p>
          <footer><span>{chunk.tokenCount ? `${chunk.tokenCount} tokens` : 'Token 未统计'}</span><span>{chunk.id}</span></footer>
        </article>
      ))}
      {hasMore ? <div className="knowledge-more-note"><span>已显示 {detail.chunks.length} / {detail.chunkTotal} 个片段</span><Button loading={loadingMore} onClick={onLoadMore} size="small">加载更多</Button></div> : <p className="knowledge-more-note">已加载全部 {detail.chunkTotal} 个片段。</p>}
    </div>
  ) : <EmptyState description="" icon={Grid3X3} title="暂无 Chunk" />;
}

function HighlightedChunkText({ content, excerpt }: { content: string; excerpt: string }) {
  const needle = excerpt.trim();
  const index = needle ? content.indexOf(needle) : -1;
  return index >= 0 ? <>{content.slice(0, index)}<mark>{needle}</mark>{content.slice(index + needle.length)}</> : <mark>{content}</mark>;
}

function ArtifactGallery({ assets, document, tables, transport }: { assets: readonly KnowledgeAsset[]; document: KnowledgeDocument; tables: readonly KnowledgeTableArtifact[]; transport: ControlTransport }) {
  const images = assets.filter((item) => item.mimeType.startsWith('image/') && item.readPath);
  const attachments = assets.filter((item) => !images.includes(item));
  if (!assets.length && !tables.length) return <EmptyState description="" icon={GalleryHorizontalEnd} title="暂无解析产物" />;
  return (
    <div className="knowledge-artifacts">
      {images.length ? <section><header><FileImage size={14} /><strong>图片</strong><span>{images.length}</span></header><div className="knowledge-image-grid">{images.map((asset) => <KnowledgeAssetImage asset={asset} document={document} key={asset.id} transport={transport} />)}</div></section> : null}
      {tables.length ? <section><header><Table2 size={14} /><strong>表格</strong><span>{tables.length}</span></header><div className="knowledge-table-gallery">{tables.map((table) => <ParsedTable key={table.id} table={table} />)}</div></section> : null}
      {attachments.length ? <section><header><FileText size={14} /><strong>附件产物</strong><span>{attachments.length}</span></header><div className="knowledge-asset-list">{attachments.map((asset) => <KnowledgeAssetAttachment asset={asset} document={document} key={asset.id} transport={transport} />)}</div></section> : null}
    </div>
  );
}

function KnowledgeAssetImage({ asset, document, transport }: { asset: KnowledgeAsset; document: KnowledgeDocument; transport: ControlTransport }) {
  const binary = useKnowledgeAsset(document, asset, transport);
  return (
    <figure>
      {binary.loading ? <div className="knowledge-image-placeholder">正在读取…</div> : null}
      {binary.url ? <img alt={asset.caption || asset.name} loading="lazy" src={binary.url} /> : null}
      {binary.error ? <div className="knowledge-image-placeholder">读取失败</div> : null}
      <figcaption><span><strong>{asset.name}</strong><small>{asset.page ? `第 ${asset.page} 页 · ` : ''}{formatBytes(asset.byteSize)}</small></span>{binary.url ? <span className="knowledge-asset-actions"><a aria-label={`查看 ${asset.name}`} href={binary.url} rel="noreferrer" target="_blank" title={`查看 ${asset.name}`}><Eye size={13} /></a><a aria-label={`下载 ${asset.name}`} download={asset.name} href={binary.url} title={`下载 ${asset.name}`}><Download size={13} /></a></span> : null}</figcaption>
    </figure>
  );
}

function KnowledgeAssetAttachment({ asset, document, transport }: { asset: KnowledgeAsset; document: KnowledgeDocument; transport: ControlTransport }) {
  const binary = useKnowledgeAsset(document, asset, transport);
  return <div><FileText size={14} /><span><strong>{asset.name}</strong><small>{asset.mimeType || '未知格式'} · {formatBytes(asset.byteSize)}{binary.error ? ' · 读取受限' : ''}</small></span>{binary.url ? <span className="knowledge-asset-actions"><a aria-label={`查看 ${asset.name}`} href={binary.url} rel="noreferrer" target="_blank"><Eye size={13} /></a><a aria-label={`下载 ${asset.name}`} download={asset.name} href={binary.url}><Download size={13} /></a></span> : null}</div>;
}

interface BinaryViewState {
  error: Error | null;
  loading: boolean;
  mimeType: string;
  url: string;
}

function useKnowledgeDocumentSource(detail: KnowledgeDocumentDetail, transport: ControlTransport): BinaryViewState {
  const [state, setState] = useState<BinaryViewState>({ error: null, loading: false, mimeType: '', url: '' });
  useEffect(() => {
    if (!detail.document.sourceReadPath || !transport.readKnowledgeDocumentSource) {
      setState({ error: null, loading: false, mimeType: '', url: '' });
      return;
    }
    const controller = new AbortController();
    let objectUrl = '';
    let active = true;
    setState({ error: null, loading: true, mimeType: '', url: '' });
    void transport.readKnowledgeDocumentSource({
      kbId: detail.document.baseId,
      fileId: detail.document.id,
      signal: controller.signal,
    }).then((payload) => {
      if (!active) return;
      objectUrl = URL.createObjectURL(payload.blob);
      setState({ error: null, loading: false, mimeType: payload.mimeType, url: objectUrl });
    }).catch((error: unknown) => {
      if (!active || controller.signal.aborted) return;
      setState({ error: asError(error), loading: false, mimeType: '', url: '' });
    });
    return () => {
      active = false;
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [detail.document.baseId, detail.document.id, detail.document.sourceReadPath, transport]);
  return state;
}

function useKnowledgeAsset(document: KnowledgeDocument, asset: KnowledgeAsset, transport: ControlTransport): BinaryViewState {
  const [state, setState] = useState<BinaryViewState>({ error: null, loading: false, mimeType: '', url: '' });
  useEffect(() => {
    if (!asset.readPath || !transport.readKnowledgeAsset) {
      setState({ error: null, loading: false, mimeType: '', url: '' });
      return;
    }
    const controller = new AbortController();
    let objectUrl = '';
    let active = true;
    setState({ error: null, loading: true, mimeType: '', url: '' });
    void transport.readKnowledgeAsset({
      kbId: document.baseId,
      fileId: document.id,
      assetId: asset.id,
      signal: controller.signal,
    }).then((payload) => {
      if (!active) return;
      objectUrl = URL.createObjectURL(payload.blob);
      setState({ error: null, loading: false, mimeType: payload.mimeType, url: objectUrl });
    }).catch((error: unknown) => {
      if (!active || controller.signal.aborted) return;
      setState({ error: asError(error), loading: false, mimeType: '', url: '' });
    });
    return () => {
      active = false;
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [asset.id, asset.readPath, document.baseId, document.id, transport]);
  return state;
}

function ParsedTable({ table }: { table: KnowledgeTableArtifact }) {
  const [visibleRows, setVisibleRows] = useState(20);
  useEffect(() => setVisibleRows(20), [table.id]);
  return (
    <article>
      <header><strong>{table.title}</strong><span>{table.page ? `第 ${table.page} 页` : ''}</span></header>
      {table.columns.length && table.rows.length ? <><div className="knowledge-table-scroll"><table><thead><tr>{table.columns.map((column, index) => <th key={`${index}:${column}`}>{column}</th>)}</tr></thead><tbody>{table.rows.slice(0, visibleRows).map((row, rowIndex) => <tr key={rowIndex}>{row.map((cell, cellIndex) => <td key={cellIndex}>{cell}</td>)}</tr>)}</tbody></table></div>{visibleRows < table.rows.length ? <div className="knowledge-table-more"><span>{visibleRows} / {table.rows.length} 行</span><Button onClick={() => setVisibleRows((value) => Math.min(table.rows.length, value + 20))} size="small">加载更多</Button></div> : null}</> : <pre>{table.markdown || '表格内容未结构化'}</pre>}
    </article>
  );
}

export function KnowledgeJobsPanel({ cancellingJobId, cancelError, error, jobs, loading, onCancel, onRefresh }: { cancellingJobId: string; cancelError: unknown; error: Error | null; jobs: readonly KnowledgeIndexJob[]; loading: boolean; onCancel: (jobId: string) => void; onRefresh: () => void }) {
  const [expandedId, setExpandedId] = useState('');
  const active = jobs.filter((job) => ['queued', 'running', 'parsing', 'embedding', 'indexing'].includes(job.status.toLowerCase()));
  return (
    <div className="knowledge-panel knowledge-jobs">
      <div className="knowledge-panel__toolbar"><div><strong>索引任务</strong><span>{active.length} 个进行中 · {jobs.length} 条记录</span></div><IconButton disabled={loading} icon={<RotateCcw className={loading ? 'ui-spin' : undefined} size={14} />} label="刷新索引任务" onClick={onRefresh} size="small" tooltip /></div>
      {error ? <InlineNotice title="任务记录暂不可用" tone="warning">{publicErrorText(error, '刷新后重试。')}</InlineNotice> : null}
      {cancelError ? <InlineNotice title="任务未取消" tone="warning">{publicErrorText(cancelError, '请刷新任务状态后重试。')}</InlineNotice> : null}
      {jobs.length ? <div className="knowledge-job-list">{jobs.map((job) => {
        const expanded = expandedId === job.id;
        return <article data-expanded={expanded || undefined} key={job.id}><span className="knowledge-job-list__icon"><RotateCcw size={14} /></span><button aria-expanded={expanded} className="knowledge-job-list__summary" onClick={() => setExpandedId(expanded ? '' : job.id)} type="button"><span><strong>{job.documentName || job.kind}</strong><small>{jobStageLabel(job.stage)} · {formatTime(job.updatedAtMs || job.createdAtMs)}</small>{job.error ? <em>{job.error}</em> : null}<i style={{ '--job-progress': terminalJobStatus(job.status) ? 1 : job.progress } as React.CSSProperties} /></span><ChevronDown aria-hidden="true" size={14} /></button><StatusBadge label={jobStatusLabel(job.status)} tone={jobTone(job.status)} />{job.cancellable ? <IconButton disabled={cancellingJobId === job.id} icon={<CircleStop size={14} />} label="取消任务" onClick={() => onCancel(job.id)} size="small" tooltip /> : null}{expanded ? <JobDetails job={job} /> : null}</article>;
      })}</div> : loading ? <p className="knowledge-detail-loading">正在读取索引任务…</p> : <EmptyState description="" icon={RotateCcw} title="暂无索引任务" />}
    </div>
  );
}

function JobDetails({ job }: { job: KnowledgeIndexJob }) {
  const finished = job.finishedAtMs || (terminalJobStatus(job.status) ? job.updatedAtMs : 0);
  const started = job.startedAtMs || job.createdAtMs;
  return <div className="knowledge-job-detail"><dl><div><dt>任务 ID</dt><dd>{job.id}</dd></div><div><dt>类型</dt><dd>{job.kind}</dd></div><div><dt>解析器</dt><dd>{parserLabel(job.parserMode)}</dd></div><div><dt>文档 ID</dt><dd>{job.documentId || '整库任务'}</dd></div><div><dt>索引 revision</dt><dd>{job.revision || '未提供'}</dd></div><div><dt>耗时</dt><dd>{finished && started ? formatDuration(finished - started) : '进行中'}</dd></div><div><dt>错误代码</dt><dd>{job.errorCode || '无'}</dd></div></dl><ol aria-label="任务阶段记录"><li><span>创建</span><time>{formatTime(job.createdAtMs)}</time></li>{job.startedAtMs ? <li><span>开始 · {jobStageLabel(job.stage)}</span><time>{formatTime(job.startedAtMs)}</time></li> : null}{finished ? <li><span>{jobStatusLabel(job.status)}</span><time>{formatTime(finished)}</time></li> : null}</ol>{job.error ? <p>{job.error}</p> : null}</div>;
}

function summarizeDocuments(documents: readonly KnowledgeDocument[]) {
  return documents.reduce((summary, item) => ({
    bytes: summary.bytes + item.byteSize,
    ready: summary.ready + (item.status === 'ready' ? 1 : 0),
    processing: summary.processing + (['queued', 'parsing', 'indexing'].includes(item.status) ? 1 : 0),
    attention: summary.attention + (['failed', 'stale'].includes(item.status) ? 1 : 0),
  }), { bytes: 0, ready: 0, processing: 0, attention: 0 });
}

function groupChunksByPage(detail: KnowledgeDocumentDetail) {
  const groups = new Map<string, { key: string; page: number | null; chunks: KnowledgeDocumentDetail['chunks'] }>();
  for (const chunk of detail.chunks) {
    const key = chunk.page === null ? 'none' : String(chunk.page);
    const group = groups.get(key) ?? { key, page: chunk.page, chunks: [] };
    group.chunks.push(chunk);
    groups.set(key, group);
  }
  return [...groups.values()].sort((left, right) => (left.page ?? Number.MAX_SAFE_INTEGER) - (right.page ?? Number.MAX_SAFE_INTEGER));
}

function asError(value: unknown): Error { return value instanceof Error ? value : new Error('读取文件失败。'); }

function documentStatusLabel(value: KnowledgeDocument['status']): string { return ({ queued: '等待处理', parsing: '解析中', indexing: '索引中', ready: '可检索', failed: '处理失败', stale: '需要重建' } as const)[value]; }
function documentTone(value: KnowledgeDocument['status']): 'success' | 'warning' | 'danger' | 'info' { return value === 'ready' ? 'success' : value === 'failed' ? 'danger' : value === 'stale' ? 'warning' : 'info'; }
function formatBytes(value: number): string { if (!value) return '0 B'; if (value < 1_024) return `${value} B`; if (value < 1_048_576) return `${(value / 1_024).toFixed(1)} KB`; return `${(value / 1_048_576).toFixed(1)} MB`; }
function formatTime(value: number): string { return value ? new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(value) : '暂无'; }
function shortHash(value: string): string { return value ? `${value.slice(0, 8)}…${value.slice(-6)}` : '未记录'; }
function jobStageLabel(value: string): string { return (({ queued: '等待开始', parsing: '解析材料', embedding: '生成向量', indexing: '写入索引', ready: '完成' } as Record<string, string>)[value] ?? value) || '处理中'; }
function jobStatusLabel(value: string): string { return ({ queued: '等待中', running: '进行中', parsing: '进行中', embedding: '进行中', indexing: '进行中', ready: '已完成', succeeded: '已完成', success: '已完成', completed: '已完成', failed: '失败', cancelled: '已取消', canceled: '已取消' } as Record<string, string>)[value.toLowerCase()] ?? value; }
function jobTone(value: string): 'success' | 'warning' | 'danger' | 'info' { const status = value.toLowerCase(); return ['ready', 'succeeded', 'success', 'completed'].includes(status) ? 'success' : status === 'failed' ? 'danger' : ['cancelled', 'canceled'].includes(status) ? 'warning' : 'info'; }
function terminalJobStatus(value: string): boolean { return ['ready', 'succeeded', 'success', 'completed', 'failed', 'cancelled', 'canceled'].includes(value.toLowerCase()); }
function formatDuration(value: number): string { if (value < 1_000) return `${Math.max(0, value)} ms`; const seconds = Math.round(value / 1_000); return seconds < 60 ? `${seconds} 秒` : `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒`; }
function parserLabel(value: KnowledgeParserMode): string { return value === 'mineru' ? 'MinerU OCR' : value === 'builtin' ? '内置解析' : '自动选择'; }
function uploadStatusLabel(value: KnowledgeUploadItem['status']): string { return ({ queued: '等待上传', uploading: '上传中', accepted: '已进入解析', failed: '上传失败' } as const)[value]; }
function uploadTone(value: KnowledgeUploadItem['status']): 'success' | 'danger' | 'info' { return value === 'accepted' ? 'success' : value === 'failed' ? 'danger' : 'info'; }
function safeMarkdownLink(value: string | undefined): string | null { return value && /^(?:https?:|#)/iu.test(value) ? value : null; }
