import {
  FileImage,
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
import { useEffect, useMemo, useState } from 'react';
import { Virtuoso } from 'react-virtuoso';
import { Button, EmptyState, IconButton, Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/primitives';
import { InlineNotice, StatusBadge, publicErrorText } from '@/features/overview/management-ui';
import type { ControlTransport } from '@/platform/transport';
import type {
  KnowledgeAsset,
  KnowledgeDocument,
  KnowledgeDocumentDetail,
  KnowledgeIndexJob,
  KnowledgeTableArtifact,
} from './api';

export function KnowledgeMaterialsPanel({
  detail,
  detailError,
  detailLoading,
  documents,
  error,
  importing,
  onDelete,
  onImport,
  onOpen,
  onRetry,
  onSelect,
  pendingDocumentId,
  selectedDocumentId,
}: {
  detail: KnowledgeDocumentDetail | null;
  detailError: Error | null;
  detailLoading: boolean;
  documents: readonly KnowledgeDocument[];
  error: Error | null;
  importing: boolean;
  onDelete: (document: KnowledgeDocument) => void;
  onImport: () => void;
  onOpen: (documentId: string) => void;
  onRetry: (document: KnowledgeDocument) => void;
  onSelect: (documentId: string) => void;
  pendingDocumentId: string;
  selectedDocumentId: string;
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
        <div><dt>解析产物</dt><dd>{detail ? detail.assets.length + detail.tables.length : 0}</dd></div>
      </dl>
      {error ? <InlineNotice title="文件列表暂不可用" tone="warning">{publicErrorText(error, '刷新后重试。')}</InlineNotice> : null}
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
                    {document.status === 'failed' || document.status === 'stale' ? (
                      <IconButton disabled={pendingDocumentId === document.id} icon={<RotateCcw size={13} />} label={`重试 ${document.name}`} onClick={() => onRetry(document)} size="small" tooltip />
                    ) : null}
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
}: {
  detail: KnowledgeDocumentDetail | null;
  error: Error | null;
  loading: boolean;
  onSelectDocument: (documentId: string) => void;
  selectedDocumentId: string;
  documents: readonly KnowledgeDocument[];
  transport: ControlTransport;
}) {
  const [view, setView] = useState<'source' | 'markdown' | 'chunks' | 'artifacts'>('markdown');
  useEffect(() => setView('markdown'), [selectedDocumentId]);
  if (!documents.length) return <EmptyState description="" icon={FileText} title="先导入资料" />;
  return (
    <div className="knowledge-panel knowledge-viewer">
      <div className="knowledge-viewer__bar">
        <label><span>材料</span><select className="ui-input" onChange={(event) => onSelectDocument(event.target.value)} value={selectedDocumentId || documents[0]?.id}>{documents.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        {detail ? <span>{detail.chunkTotal} 个片段 · {detail.pages.length || detail.document.pageCount || 0} 页 · {detail.assets.length} 个产物</span> : null}
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
          <TabsContent value="markdown"><DocumentContent detail={detail} /></TabsContent>
          <TabsContent value="chunks"><ChunkGallery detail={detail} /></TabsContent>
          <TabsContent value="artifacts"><ArtifactGallery assets={detail.assets} document={detail.document} tables={detail.tables} transport={transport} /></TabsContent>
        </Tabs>
      ) : null}
    </div>
  );
}

function DocumentContent({ detail }: { detail: KnowledgeDocumentDetail }) {
  if (detail.contentWindow.length) {
    return (
      <div className="knowledge-markdown-preview">
        <header><span>Markdown</span><b>{detail.artifact.lineCount || detail.contentWindow.length} 行 · {formatBytes(detail.artifact.byteSize)}</b></header>
        <pre>{detail.contentWindow.map((line) => line.content).join('\n')}</pre>
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

function ChunkGallery({ detail }: { detail: KnowledgeDocumentDetail }) {
  return detail.chunks.length ? (
    <div className="knowledge-chunk-grid">
      {detail.chunks.map((chunk) => (
        <article key={chunk.id}>
          <header><b>#{chunk.ordinal + 1}</b><span>{chunk.page ? `第 ${chunk.page} 页` : chunk.lineStart ? `第 ${chunk.lineStart} 行` : '无页码'}</span></header>
          {chunk.heading ? <h4>{chunk.heading}</h4> : null}
          <p>{chunk.content}</p>
          <footer><span>{chunk.tokenCount ? `${chunk.tokenCount} tokens` : 'Token 未统计'}</span><span>{chunk.id}</span></footer>
        </article>
      ))}
      {detail.chunkHasMore ? <p className="knowledge-more-note">当前显示前 {detail.chunks.length} / {detail.chunkTotal} 个片段。</p> : null}
    </div>
  ) : <EmptyState description="" icon={Grid3X3} title="暂无 Chunk" />;
}

function ArtifactGallery({ assets, document, tables, transport }: { assets: readonly KnowledgeAsset[]; document: KnowledgeDocument; tables: readonly KnowledgeTableArtifact[]; transport: ControlTransport }) {
  const images = assets.filter((item) => item.mimeType.startsWith('image/') && item.readPath);
  const attachments = assets.filter((item) => !images.includes(item));
  if (!assets.length && !tables.length) return <EmptyState description="" icon={GalleryHorizontalEnd} title="暂无解析产物" />;
  return (
    <div className="knowledge-artifacts">
      {images.length ? <section><header><FileImage size={14} /><strong>图片</strong><span>{images.length}</span></header><div className="knowledge-image-grid">{images.map((asset) => <KnowledgeAssetImage asset={asset} document={document} key={asset.id} transport={transport} />)}</div></section> : null}
      {tables.length ? <section><header><Table2 size={14} /><strong>表格</strong><span>{tables.length}</span></header><div className="knowledge-table-gallery">{tables.map((table) => <ParsedTable key={table.id} table={table} />)}</div></section> : null}
      {attachments.length ? <section><header><FileText size={14} /><strong>附件产物</strong><span>{attachments.length}</span></header><div className="knowledge-asset-list">{attachments.map((asset) => <div key={asset.id}><FileText size={14} /><span><strong>{asset.name}</strong><small>{asset.mimeType || '未知格式'} · {formatBytes(asset.byteSize)}</small></span></div>)}</div></section> : null}
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
      <figcaption><strong>{asset.name}</strong><span>{asset.page ? `第 ${asset.page} 页 · ` : ''}{formatBytes(asset.byteSize)}</span></figcaption>
    </figure>
  );
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
  return (
    <article>
      <header><strong>{table.title}</strong><span>{table.page ? `第 ${table.page} 页` : ''}</span></header>
      {table.columns.length && table.rows.length ? <div className="knowledge-table-scroll"><table><thead><tr>{table.columns.map((column, index) => <th key={`${index}:${column}`}>{column}</th>)}</tr></thead><tbody>{table.rows.slice(0, 20).map((row, rowIndex) => <tr key={rowIndex}>{row.map((cell, cellIndex) => <td key={cellIndex}>{cell}</td>)}</tr>)}</tbody></table></div> : <pre>{table.markdown || '表格内容未结构化'}</pre>}
    </article>
  );
}

export function KnowledgeJobsPanel({ jobs }: { jobs: readonly KnowledgeIndexJob[] }) {
  const active = jobs.filter((job) => ['queued', 'running', 'parsing', 'indexing'].includes(job.status));
  return (
    <div className="knowledge-panel knowledge-jobs">
      <div className="knowledge-panel__toolbar"><div><strong>索引任务</strong><span>{active.length} 个进行中 · {jobs.length} 条记录</span></div></div>
      {jobs.length ? <div className="knowledge-job-list">{jobs.map((job) => <article key={job.id}><span className="knowledge-job-list__icon"><RotateCcw size={14} /></span><div><strong>{job.documentName || job.kind}</strong><small>{jobStageLabel(job.stage)} · {formatTime(job.updatedAtMs || job.createdAtMs)}</small>{job.error ? <em>{job.error}</em> : null}<i style={{ '--job-progress': job.progress } as React.CSSProperties} /></div><StatusBadge label={jobStatusLabel(job.status)} tone={jobTone(job.status)} /></article>)}</div> : <EmptyState description="" icon={RotateCcw} title="暂无索引任务" />}
    </div>
  );
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
function jobStatusLabel(value: string): string { return ({ queued: '等待中', running: '进行中', parsing: '进行中', indexing: '进行中', ready: '已完成', completed: '已完成', failed: '失败', cancelled: '已取消' } as Record<string, string>)[value] ?? '处理中'; }
function jobTone(value: string): 'success' | 'warning' | 'danger' | 'info' { return value === 'ready' || value === 'completed' ? 'success' : value === 'failed' ? 'danger' : value === 'cancelled' ? 'warning' : 'info'; }
