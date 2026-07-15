import { useMutation, useQueryClient } from '@tanstack/react-query';
import {
  BookOpen,
  Database,
  ExternalLink,
  FileSearch,
  FolderPlus,
  RefreshCw,
  Search,
  ServerCog,
  Settings2,
  Trash2,
} from 'lucide-react';
import { useEffect, useMemo, useState, type FormEvent } from 'react';
import { Virtuoso } from 'react-virtuoso';
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  EmptyState,
  Field,
  IconButton,
  Input,
  Switch,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  TextArea,
} from '@/components/primitives';
import {
  InlineNotice,
  ManagementPage,
  QueryState,
  StatusBadge,
  publicErrorText,
} from '@/features/overview/management-ui';
import {
  chooseKnowledgeFiles,
  cancelKnowledgeJob,
  createKnowledgeBase,
  deleteKnowledgeBase,
  deleteKnowledgeDocument,
  importKnowledgeDocuments,
  knowledgeLibraryKeys,
  openKnowledgeHit,
  previewKnowledgeReindex,
  previewKnowledgeChunking,
  rebuildKnowledgeBase,
  retryKnowledgeDocument,
  searchKnowledgeBase,
  updateKnowledgeBase,
  useKnowledgeDocumentDetail,
  useKnowledgeLibraryQueries,
  type KnowledgeChunkingConfig,
  type KnowledgeChunkPreview,
  type DocumentKnowledgeBase,
  type KnowledgeDocument,
  type KnowledgeIndexRuntimeStatus,
  type KnowledgeParserMode,
  type KnowledgeRetrievalConfig,
  type KnowledgeReindexPreview,
  type KnowledgeSearchHit,
  knowledgeIndexRuntimeStatus,
} from './api';
import { KnowledgeDocumentViewer, KnowledgeJobsPanel, KnowledgeMaterialsPanel, type KnowledgeUploadItem } from './document-workspace';
import './knowledge.css';

type DetailTab = 'materials' | 'viewer' | 'search' | 'jobs' | 'settings';

export function KnowledgeFeature() {
  const [selectedBaseId, setSelectedBaseId] = useState('');
  const [tab, setTab] = useState<DetailTab>('materials');
  const [createOpen, setCreateOpen] = useState(false);
  const [deleteBaseOpen, setDeleteBaseOpen] = useState(false);
  const [documentToDelete, setDocumentToDelete] = useState<KnowledgeDocument | null>(null);
  const [selectedDocumentId, setSelectedDocumentId] = useState('');
  const [focusedHit, setFocusedHit] = useState<KnowledgeSearchHit | null>(null);
  const [reparseDocument, setReparseDocument] = useState<KnowledgeDocument | null>(null);
  const [uploadItems, setUploadItems] = useState<KnowledgeUploadItem[]>([]);
  const queries = useKnowledgeLibraryQueries(selectedBaseId);
  const queryClient = useQueryClient();
  const bases = queries.bases.data ?? [];
  const selectedBase = queries.base.data ?? bases.find((item) => item.id === selectedBaseId) ?? null;
  const documents = queries.documents.data ?? [];
  const detailQuery = useKnowledgeDocumentDetail(selectedBaseId, selectedDocumentId);

  useEffect(() => {
    if (!selectedBaseId && bases[0]?.id) setSelectedBaseId(bases[0].id);
    if (selectedBaseId && bases.length && !bases.some((item) => item.id === selectedBaseId)) {
      setSelectedBaseId(bases[0]?.id ?? '');
    }
  }, [bases, selectedBaseId]);

  useEffect(() => {
    if (!documents.length) {
      setSelectedDocumentId('');
      return;
    }
    if (!documents.some((item) => item.id === selectedDocumentId)) setSelectedDocumentId(documents[0]?.id ?? '');
  }, [documents, selectedDocumentId]);

  useEffect(() => {
    setFocusedHit(null);
    setUploadItems([]);
  }, [selectedBaseId]);

  const refresh = () => void Promise.all([
    queries.bases.refetch(),
    queries.worker.refetch(),
    queries.parsers.refetch(),
    ...(selectedBaseId ? [queries.base.refetch(), queries.documents.refetch(), queries.jobs.refetch()] : []),
  ]);

  const invalidateBase = async (baseId = selectedBaseId) => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: knowledgeLibraryKeys.bases() }),
      ...(baseId ? [
        queryClient.invalidateQueries({ queryKey: knowledgeLibraryKeys.base(baseId) }),
        queryClient.invalidateQueries({ queryKey: knowledgeLibraryKeys.documents(baseId) }),
        queryClient.invalidateQueries({ queryKey: knowledgeLibraryKeys.jobs(baseId) }),
        queryClient.invalidateQueries({ queryKey: [...knowledgeLibraryKeys.root, 'document-detail', baseId] }),
        queryClient.invalidateQueries({ queryKey: [...knowledgeLibraryKeys.root, 'document-content', baseId] }),
      ] : []),
    ]);
  };

  const createMutation = useMutation({
    mutationFn: (input: { name: string; description: string }) => createKnowledgeBase(queries.transport, input),
    onSuccess: async (base) => {
      setSelectedBaseId(base.id);
      setCreateOpen(false);
      await invalidateBase(base.id);
    },
  });
  const deleteBaseMutation = useMutation({
    mutationFn: () => selectedBase
      ? deleteKnowledgeBase(queries.transport, selectedBase)
      : Promise.reject(new Error('没有选中的知识库。')),
    onSuccess: async () => {
      setDeleteBaseOpen(false);
      setSelectedBaseId('');
      await invalidateBase('');
    },
  });
  const importMutation = useMutation({
    mutationFn: async ({ retryItem }: { retryItem?: KnowledgeUploadItem }) => {
      if (!selectedBase) return [];
      const parser = retryItem?.parser ?? selectedBase.parser;
      if (queries.transport.kind !== 'http') {
        try {
          const receipts = await importKnowledgeDocuments(queries.transport, {
            kbId: selectedBase.id,
            parserProvider: parser === 'mineru' ? 'mineru_local_http' : parser,
            maxFiles: 20,
          });
          setUploadItems(receipts.map((receipt) => ({ id: receipt.documentId, fileName: receipt.fileName, byteSize: receipt.byteSize, parser, status: 'accepted', documentId: receipt.documentId, error: '' })));
          return receipts;
        } catch (error) {
          setUploadItems([{ id: 'native-import', fileName: '本机文件导入', byteSize: 0, parser, status: 'failed', documentId: '', error: publicErrorText(error, '本机文件导入失败。') }]);
          throw error;
        }
      }
      const files = retryItem?.file ? [retryItem.file] : await chooseKnowledgeFiles(20);
      if (!files.length) return [];
      const queue = retryItem ? [retryItem] : files.map((file, index) => ({
        id: uploadItemId(file, index), fileName: file.name, byteSize: file.size, file, parser, status: 'queued' as const, documentId: '', error: '',
      }));
      if (!retryItem) setUploadItems(queue);
      const receipts = [];
      const errors: string[] = [];
      for (const item of queue) {
        setUploadItems((current) => replaceUploadItem(current, item.id, { status: 'uploading', error: '' }));
        try {
          const [receipt] = await importKnowledgeDocuments(queries.transport, {
            kbId: selectedBase.id,
            files: item.file ? [item.file] : undefined,
            parserProvider: parser === 'mineru' ? 'mineru_local_http' : parser,
            maxFiles: 1,
          });
          if (!receipt) throw new Error('导入服务没有返回文件回执。');
          receipts.push(receipt);
          setUploadItems((current) => replaceUploadItem(current, item.id, { status: 'accepted', documentId: receipt.documentId, error: '' }));
        } catch (error) {
          const message = publicErrorText(error, '上传失败。');
          errors.push(`${item.fileName}: ${message}`);
          setUploadItems((current) => replaceUploadItem(current, item.id, { status: 'failed', error: message }));
        }
      }
      if (errors.length) throw new Error(errors.join('\n'));
      return receipts;
    },
    onSettled: () => invalidateBase(),
  });
  const retryMutation = useMutation({
    mutationFn: ({ document, parser }: { document: KnowledgeDocument; parser: KnowledgeParserMode }) => selectedBase
      ? retryKnowledgeDocument(queries.transport, selectedBase, document, { parser })
      : Promise.reject(new Error('没有选中的知识库。')),
    onSuccess: async () => { setReparseDocument(null); await invalidateBase(); },
  });
  const deleteDocumentMutation = useMutation({
    mutationFn: (documentId: string) => deleteKnowledgeDocument(queries.transport, selectedBaseId, documentId),
    onSuccess: async () => {
      setDocumentToDelete(null);
      await invalidateBase();
    },
  });
  const updateMutation = useMutation({
    mutationFn: (patch: {
      name?: string;
      description?: string;
      agentEnabled?: boolean;
      parser?: KnowledgeParserMode;
      chunkingConfig?: KnowledgeChunkingConfig;
      retrievalConfig?: KnowledgeRetrievalConfig;
    }) => (
      selectedBase
        ? updateKnowledgeBase(queries.transport, selectedBase, patch)
        : Promise.reject(new Error('没有选中的知识库。'))
    ),
    onSuccess: () => invalidateBase(),
  });
  const reindexPreviewMutation = useMutation({
    mutationFn: () => selectedBase
      ? previewKnowledgeReindex(queries.transport, selectedBase)
      : Promise.reject(new Error('没有选中的知识库。')),
  });
  const rebuildMutation = useMutation({
    mutationFn: (preview: KnowledgeReindexPreview) => selectedBase
      ? rebuildKnowledgeBase(queries.transport, selectedBase, preview)
      : Promise.reject(new Error('没有选中的知识库。')),
    onSuccess: async () => {
      reindexPreviewMutation.reset();
      setTab('jobs');
      await invalidateBase();
    },
  });
  const cancelJobMutation = useMutation({
    mutationFn: (jobId: string) => cancelKnowledgeJob(queries.transport, selectedBaseId, jobId),
    onSettled: () => invalidateBase(),
  });
  const chunkPreviewMutation = useMutation({
    mutationFn: ({ documentId, config }: { documentId: string; config: KnowledgeChunkingConfig }) => (
      selectedBase
        ? previewKnowledgeChunking(queries.transport, selectedBase.id, documentId, config)
        : Promise.reject(new Error('没有选中的知识库。'))
    ),
  });

  const pageError = queries.bases.error as Error | null;
  const worker = workerState(queries.worker.data, queries.worker.error);

  return (
    <ManagementPage
      actions={(
        <>
          <Button leadingIcon={<FolderPlus size={15} />} onClick={() => setCreateOpen(true)} size="small" variant="primary">新建知识库</Button>
          <IconButton icon={<RefreshCw size={15} />} label="刷新知识库" onClick={refresh} size="small" tooltip />
        </>
      )}
      description="独立加载大型文档资料，跟踪解析和索引，并控制哪些知识可由 Agent 检索。"
      eyebrow="外部文档"
      routeId="knowledge"
      title="知识库"
    >
      <QueryState error={pageError} isPending={queries.bases.isPending} onRetry={refresh}>
        <div className="knowledge-library" data-empty={!bases.length || undefined}>
          <KnowledgeBaseRail
            bases={bases}
            onCreate={() => setCreateOpen(true)}
            onSelect={(baseId) => { setSelectedBaseId(baseId); setSelectedDocumentId(''); setTab('materials'); }}
            selectedBaseId={selectedBaseId}
            worker={worker}
          />
          <section className="knowledge-library__detail" aria-label="知识库详情">
            {selectedBase ? (
              <>
                <KnowledgeBaseHeader base={selectedBase} onDelete={() => setDeleteBaseOpen(true)} worker={worker} />
                <Tabs className="knowledge-library__tabs" onValueChange={(value) => setTab(asDetailTab(value))} value={tab}>
                  <TabsList aria-label="知识库管理视图">
                    <TabsTrigger value="materials">资料</TabsTrigger>
                    <TabsTrigger value="viewer">材料查看</TabsTrigger>
                    <TabsTrigger value="search">检索测试</TabsTrigger>
                    <TabsTrigger value="jobs">索引任务</TabsTrigger>
                    <TabsTrigger value="settings">设置</TabsTrigger>
                  </TabsList>
                  <TabsContent value="materials">
                    <KnowledgeMaterialsPanel
                      detail={detailQuery.data ?? null}
                      detailError={detailQuery.error as Error | null}
                      detailLoading={detailQuery.isPending && Boolean(selectedDocumentId)}
                      documents={documents}
                      error={queries.documents.error as Error | null}
                      importError={importMutation.error as Error | null}
                      importing={importMutation.isPending}
                      onDelete={setDocumentToDelete}
                      onClearUploads={() => { importMutation.reset(); setUploadItems([]); }}
                      onImport={() => importMutation.mutate({})}
                      onOpen={(documentId) => { setFocusedHit(null); setSelectedDocumentId(documentId); setTab('viewer'); }}
                      onReparse={setReparseDocument}
                      onRetryUpload={(item) => importMutation.mutate({ retryItem: item })}
                      onSelect={(documentId) => { setFocusedHit(null); setSelectedDocumentId(documentId); }}
                      pendingDocumentId={retryMutation.variables?.document.id ?? ''}
                      selectedDocumentId={selectedDocumentId}
                      uploadItems={uploadItems}
                    />
                  </TabsContent>
                  <TabsContent value="viewer">
                    <KnowledgeDocumentViewer
                      detail={detailQuery.data ?? null}
                      documents={documents}
                      error={detailQuery.error as Error | null}
                      loading={detailQuery.isPending && Boolean(selectedDocumentId)}
                      focusHit={focusedHit}
                      hasMoreChunks={Boolean(detailQuery.hasNextPage)}
                      hasMoreContent={Boolean(detailQuery.hasNextContentPage)}
                      loadingMoreChunks={detailQuery.isFetchingNextPage}
                      loadingMoreContent={detailQuery.isFetchingNextContentPage}
                      onLoadMoreChunks={() => void detailQuery.fetchNextPage()}
                      onLoadMoreContent={() => void detailQuery.fetchNextContentPage()}
                      onSelectDocument={(documentId) => { setFocusedHit(null); setSelectedDocumentId(documentId); }}
                      selectedDocumentId={selectedDocumentId}
                      transport={queries.transport}
                    />
                  </TabsContent>
                  <TabsContent value="search">
                    <KnowledgeSearchPanel base={selectedBase} onOpenHit={(hit) => { setSelectedDocumentId(hit.documentId); setFocusedHit(hit); setTab('viewer'); }} transport={queries.transport} />
                  </TabsContent>
                  <TabsContent value="jobs">
                    <KnowledgeJobsPanel
                      cancelError={cancelJobMutation.error}
                      cancellingJobId={cancelJobMutation.isPending ? cancelJobMutation.variables ?? '' : ''}
                      error={queries.jobs.error as Error | null}
                      jobs={queries.jobs.data ?? []}
                      loading={queries.jobs.isFetching}
                      onCancel={(jobId) => cancelJobMutation.mutate(jobId)}
                      onRefresh={() => void queries.jobs.refetch()}
                    />
                  </TabsContent>
                  <TabsContent value="settings">
                    <KnowledgeSettingsPanel
                      base={selectedBase}
                      documents={documents}
                      indexRuntime={knowledgeIndexRuntimeStatus(queries.worker.data)}
                      onAgentEnabled={(agentEnabled) => updateMutation.mutate({ agentEnabled })}
                      onParser={(parser) => updateMutation.mutate({ parser })}
                      onSaveInfo={(name, description) => updateMutation.mutate({ name, description })}
                      onSaveChunking={(chunkingConfig) => updateMutation.mutate({ chunkingConfig })}
                      onSaveRetrieval={(retrievalConfig) => updateMutation.mutate({ retrievalConfig })}
                      onPreviewReindex={() => reindexPreviewMutation.mutate()}
                      onPreviewChunking={(documentId, config) => chunkPreviewMutation.mutate({ documentId, config })}
                      onRebuild={(preview) => rebuildMutation.mutate(preview)}
                      parserData={queries.parsers.data}
                      pending={updateMutation.isPending}
                      updateError={updateMutation.error}
                      rebuildError={rebuildMutation.error ?? reindexPreviewMutation.error}
                      rebuilding={rebuildMutation.isPending}
                      reindexPreview={reindexPreviewMutation.data ?? null}
                      reindexPreviewing={reindexPreviewMutation.isPending}
                      chunkPreview={chunkPreviewMutation.data ?? null}
                      chunkPreviewError={chunkPreviewMutation.error}
                      chunkPreviewing={chunkPreviewMutation.isPending}
                      refreshParser={() => void Promise.all([queries.parsers.refetch(), queries.worker.refetch()])}
                      worker={worker}
                    />
                  </TabsContent>
                </Tabs>
              </>
            ) : (
              <EmptyState
                action={<Button leadingIcon={<FolderPlus size={15} />} onClick={() => setCreateOpen(true)} variant="primary">新建知识库</Button>}
                description="为项目资料、论文或产品文档建立独立知识库。"
                icon={Database}
                title="还没有文档知识库"
              />
            )}
          </section>
        </div>
      </QueryState>
      <CreateKnowledgeBaseDialog
        error={createMutation.error}
        loading={createMutation.isPending}
        onCreate={(input) => createMutation.mutate(input)}
        onOpenChange={(open) => { setCreateOpen(open); if (!open) createMutation.reset(); }}
        open={createOpen}
      />
      <ConfirmDialog
        description={selectedBase ? `将删除“${selectedBase.name}”及其文档索引。个人记忆不会受到影响。` : ''}
        error={deleteBaseMutation.error}
        loading={deleteBaseMutation.isPending}
        onConfirm={() => deleteBaseMutation.mutate()}
        onOpenChange={setDeleteBaseOpen}
        open={deleteBaseOpen}
        title="删除文档知识库"
      />
      <ConfirmDialog
        description={documentToDelete ? `将移除“${documentToDelete.name}”及其索引片段。` : ''}
        error={deleteDocumentMutation.error}
        loading={deleteDocumentMutation.isPending}
        onConfirm={() => { if (documentToDelete) deleteDocumentMutation.mutate(documentToDelete.id); }}
        onOpenChange={(open) => { if (!open) setDocumentToDelete(null); }}
        open={Boolean(documentToDelete)}
        title="删除文档"
      />
      <ReparseDocumentDialog
        document={reparseDocument}
        error={retryMutation.error}
        loading={retryMutation.isPending}
        onConfirm={(parser) => { if (reparseDocument) retryMutation.mutate({ document: reparseDocument, parser }); }}
        onOpenChange={(open) => { if (!open) { setReparseDocument(null); retryMutation.reset(); } }}
      />
    </ManagementPage>
  );
}

function KnowledgeBaseRail({
  bases,
  onCreate,
  onSelect,
  selectedBaseId,
  worker,
}: {
  bases: readonly DocumentKnowledgeBase[];
  onCreate: () => void;
  onSelect: (baseId: string) => void;
  selectedBaseId: string;
  worker: WorkerState;
}) {
  return (
    <aside className="knowledge-base-rail" aria-label="文档知识库">
      <header>
        <div><strong>知识库</strong><span>{bases.length} 个独立库</span></div>
        <IconButton icon={<FolderPlus size={15} />} label="新建知识库" onClick={onCreate} size="small" tooltip />
      </header>
      <div className="knowledge-base-rail__worker" data-state={worker.tone}>
        <i aria-hidden="true" />
        <span>Knowledge Worker</span>
        <b>{worker.label}</b>
      </div>
      {bases.length ? (
        <Virtuoso
          className="knowledge-base-rail__list"
          data={bases}
          itemContent={(_index, base) => (
            <button
              aria-current={base.id === selectedBaseId ? 'page' : undefined}
              className="knowledge-base-row"
              data-selected={base.id === selectedBaseId || undefined}
              onClick={() => onSelect(base.id)}
              type="button"
            >
              <span className="knowledge-base-row__icon"><BookOpen size={15} /></span>
              <span><strong>{base.name}</strong><small>{base.documentCount} 个文件 · {base.chunkCount} 个片段</small></span>
              {base.agentEnabled ? <span className="knowledge-base-row__agent">Agent</span> : null}
            </button>
          )}
        />
      ) : <p className="knowledge-base-rail__empty">新建一个库后再导入资料。</p>}
    </aside>
  );
}

function KnowledgeBaseHeader({ base, onDelete, worker }: { base: DocumentKnowledgeBase; onDelete: () => void; worker: WorkerState }) {
  return (
    <header className="knowledge-base-header">
      <div>
        <span>文档知识库</span>
        <h2>{base.name}</h2>
        <p>{base.description || '这个库还没有说明。'}</p>
      </div>
      <dl>
        <div><dt>文件</dt><dd>{base.documentCount}</dd></div>
        <div><dt>片段</dt><dd>{base.chunkCount}</dd></div>
        <div><dt>解析</dt><dd>{parserLabel(base.parser)}</dd></div>
        <div><dt>服务</dt><dd><StatusBadge label={worker.label} tone={worker.tone} /></dd></div>
      </dl>
      <IconButton className="knowledge-base-header__delete" icon={<Trash2 size={15} />} label="删除知识库" onClick={onDelete} size="small" tooltip />
    </header>
  );
}

function KnowledgeSearchPanel({ base, onOpenHit, transport }: { base: DocumentKnowledgeBase; onOpenHit: (hit: KnowledgeSearchHit) => void; transport: ReturnType<typeof useKnowledgeLibraryQueries>['transport'] }) {
  const [draft, setDraft] = useState('');
  const [selectedId, setSelectedId] = useState('');
  const searchMutation = useMutation({
    mutationFn: (query: string) => searchKnowledgeBase(transport, base.id, query, base.retrievalConfig),
    onSuccess: (hits) => setSelectedId(hits[0]?.id ?? ''),
  });
  const hits = searchMutation.data ?? [];
  const selected = hits.find((item) => item.id === selectedId) ?? hits[0] ?? null;

  useEffect(() => {
    setDraft('');
    setSelectedId('');
    searchMutation.reset();
  // A different base must not retain results or citations from the previous base.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [base.id]);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (draft.trim()) searchMutation.mutate(draft.trim());
  };
  return (
    <div className="knowledge-panel knowledge-search">
      <form className="knowledge-search__form" onSubmit={submit}>
        <Field htmlFor="knowledge-library-search" label="检索测试" description="只查询当前知识库，不读取个人记忆。">
          <Input id="knowledge-library-search" onChange={(event) => setDraft(event.target.value)} placeholder="输入一个问题或关键词" value={draft} />
        </Field>
        <Button disabled={!draft.trim()} leadingIcon={<Search size={15} />} loading={searchMutation.isPending} type="submit" variant="primary">检索</Button>
      </form>
      <div className="knowledge-search__config" aria-label="当前检索配置">
        <span>{retrievalModeLabel(base.retrievalConfig.mode)}</span>
        <span>Top K {base.retrievalConfig.topK}</span>
        <span>阈值 {base.retrievalConfig.threshold.toFixed(2)}</span>
        {base.retrievalConfig.mode === 'hybrid' ? <span>L {base.retrievalConfig.lexicalWeight.toFixed(1)} / D {base.retrievalConfig.denseWeight.toFixed(1)}</span> : null}
        {base.retrievalConfig.mode === 'hybrid' ? <span>RRF K {base.retrievalConfig.rrfK} · 候选 ×{base.retrievalConfig.candidateMultiplier}</span> : null}
      </div>
      {searchMutation.error ? <InlineNotice title="检索失败" tone="warning">{publicErrorText(searchMutation.error, 'Knowledge Worker 暂时无法完成检索。')}</InlineNotice> : null}
      {hits.length ? (
        <div className="knowledge-search__results">
          <div className="knowledge-search__list" role="listbox" aria-label="检索结果">
            {hits.map((hit) => (
              <button aria-selected={selected?.id === hit.id} data-selected={selected?.id === hit.id || undefined} key={hit.id} onClick={() => setSelectedId(hit.id)} role="option" type="button">
                <span><strong>{hit.title}</strong><small>{hit.excerpt || '没有可显示的摘录'}</small></span>
                <b>{scoreLabel(hit.score)}</b>
              </button>
            ))}
          </div>
          {selected ? <KnowledgeHitDetail baseId={base.id} hit={selected} onOpen={onOpenHit} transport={transport} /> : null}
        </div>
      ) : searchMutation.isSuccess ? (
        <EmptyState description="换一个关键词，或检查文件是否已经完成索引。" icon={FileSearch} title="没有匹配片段" />
      ) : (
        <EmptyState description="结果会显示文档、页码或行号，并可回到原始来源。" icon={Search} title="验证这套知识是否可用" />
      )}
    </div>
  );
}

function KnowledgeHitDetail({ baseId, hit, onOpen, transport }: { baseId: string; hit: KnowledgeSearchHit; onOpen: (hit: KnowledgeSearchHit) => void; transport: ReturnType<typeof useKnowledgeLibraryQueries>['transport'] }) {
  const openMutation = useMutation({ mutationFn: () => openKnowledgeHit(transport, baseId, hit), onSuccess: () => onOpen(hit) });
  return (
    <article className="knowledge-search__detail">
      <span>{hit.documentName}</span>
      <h3>{hit.title}</h3>
      <p>{hit.excerpt || '这个片段没有可显示的摘录。'}</p>
      <dl>
        <div><dt>位置</dt><dd>{citationLabel(hit)}</dd></div>
        <div><dt>相关度</dt><dd>{scoreLabel(hit.score)}</dd></div>
        <div><dt>标题路径</dt><dd>{hit.heading || '未提供'}</dd></div>
      </dl>
      <Button leadingIcon={<ExternalLink size={14} />} loading={openMutation.isPending} onClick={() => openMutation.mutate()} size="small">打开来源</Button>
      {openMutation.error ? <p className="knowledge-inline-error">当前无法打开来源。</p> : null}
    </article>
  );
}

function KnowledgeSettingsPanel({
  base,
  chunkPreview,
  chunkPreviewError,
  chunkPreviewing,
  documents,
  indexRuntime,
  onAgentEnabled,
  onParser,
  onSaveInfo,
  onSaveChunking,
  onSaveRetrieval,
  onPreviewReindex,
  onPreviewChunking,
  onRebuild,
  parserData,
  pending,
  rebuildError,
  rebuilding,
  reindexPreview,
  reindexPreviewing,
  refreshParser,
  updateError,
  worker,
}: {
  base: DocumentKnowledgeBase;
  chunkPreview: KnowledgeChunkPreview | null;
  chunkPreviewError: unknown;
  chunkPreviewing: boolean;
  documents: readonly KnowledgeDocument[];
  indexRuntime: KnowledgeIndexRuntimeStatus;
  onAgentEnabled: (enabled: boolean) => void;
  onParser: (parser: KnowledgeParserMode) => void;
  onSaveInfo: (name: string, description: string) => void;
  onSaveChunking: (config: KnowledgeChunkingConfig) => void;
  onSaveRetrieval: (config: KnowledgeRetrievalConfig) => void;
  onPreviewReindex: () => void;
  onPreviewChunking: (documentId: string, config: KnowledgeChunkingConfig) => void;
  onRebuild: (preview: KnowledgeReindexPreview) => void;
  parserData: unknown;
  pending: boolean;
  rebuildError: unknown;
  rebuilding: boolean;
  reindexPreview: KnowledgeReindexPreview | null;
  reindexPreviewing: boolean;
  refreshParser: () => void;
  updateError: unknown;
  worker: WorkerState;
}) {
  const mineru = mineruState(parserData);
  const [chunking, setChunking] = useState(base.chunkingConfig);
  const [retrieval, setRetrieval] = useState(base.retrievalConfig);
  const [name, setName] = useState(base.name);
  const [description, setDescription] = useState(base.description);
  const [previewDocumentId, setPreviewDocumentId] = useState(documents[0]?.id ?? '');
  const chunkingError = chunking.size < 200 || chunking.size > 8_000
    ? '切分大小必须在 200–8000 之间。'
    : chunking.overlap < 0 || chunking.overlap > 2_000 || chunking.overlap >= chunking.size
      ? '重叠必须大于等于 0，且小于切分大小。'
      : chunking.strategy === 'separator' && !chunking.separator
        ? '自定义分隔符不能为空。'
      : '';
  const retrievalError = retrieval.topK < 1 || retrieval.topK > 100
    ? 'Top K 必须在 1–100 之间。'
    : retrieval.threshold < 0 || retrieval.threshold > 1
      ? '阈值必须在 0–1 之间。'
      : retrieval.lexicalWeight < 0 || retrieval.lexicalWeight > 10 || retrieval.denseWeight < 0 || retrieval.denseWeight > 10
        ? '检索权重必须在 0–10 之间。'
        : retrieval.lexicalWeight + retrieval.denseWeight <= 0
          ? 'Lexical 和 Dense 权重不能同时为 0。'
          : retrieval.rrfK < 1 || retrieval.rrfK > 1_000 || retrieval.candidateMultiplier < 1 || retrieval.candidateMultiplier > 20
            ? 'RRF K 或候选倍数超出允许范围。'
            : '';
  useEffect(() => {
    setChunking(base.chunkingConfig);
    setRetrieval(base.retrievalConfig);
    setName(base.name);
    setDescription(base.description);
  }, [base.id, base.name, base.description, base.chunkingConfig, base.retrievalConfig]);
  useEffect(() => {
    if (!documents.some((document) => document.id === previewDocumentId)) {
      setPreviewDocumentId(documents[0]?.id ?? '');
    }
  }, [documents, previewDocumentId]);
  const visibleChunkPreview = chunkPreview?.documentId === previewDocumentId ? chunkPreview : null;
  return (
    <div className="knowledge-panel knowledge-settings">
      {updateError ? <InlineNotice title="设置没有保存" tone="warning">{publicErrorText(updateError, '知识库仍使用保存前的配置。')}</InlineNotice> : null}
      <section>
        <div className="knowledge-settings__heading"><BookOpen size={16} /><div><strong>基本信息</strong><span>知识库识别信息</span></div></div>
        <div className="knowledge-settings-fields knowledge-settings-fields--info">
          <Field htmlFor="knowledge-base-settings-name" label="名称"><Input id="knowledge-base-settings-name" maxLength={120} onChange={(event) => setName(event.target.value)} value={name} /></Field>
          <Field htmlFor="knowledge-base-settings-description" label="说明"><Input id="knowledge-base-settings-description" maxLength={1_000} onChange={(event) => setDescription(event.target.value)} value={description} /></Field>
        </div>
        <div className="knowledge-settings__actions"><Button disabled={pending || !name.trim() || (name.trim() === base.name && description.trim() === base.description)} loading={pending} onClick={() => onSaveInfo(name.trim(), description.trim())} size="small" variant="primary">保存基本信息</Button></div>
      </section>
      <div className="knowledge-settings-grid">
        <section>
          <div className="knowledge-settings__heading"><ServerCog size={16} /><div><strong>Agent</strong><span>ime_knowledge</span></div></div>
          <Switch checked={base.agentEnabled} disabled={pending} label="允许 Agent 使用" onCheckedChange={onAgentEnabled} />
        </section>
        <section>
          <div className="knowledge-settings__heading"><Settings2 size={16} /><div><strong>解析器</strong><span>新导入与重试</span></div></div>
          <Field htmlFor="knowledge-parser" label="Provider">
            <select className="ui-input" disabled={pending} id="knowledge-parser" onChange={(event) => onParser(asParserMode(event.target.value))} value={base.parser}>
              <option value="auto">自动选择</option><option value="builtin">内置解析</option><option value="mineru">MinerU</option>
            </select>
          </Field>
          <div className="knowledge-parser-health"><div><span>Worker</span><StatusBadge label={worker.label} tone={worker.tone} /></div><div><span>MinerU</span><StatusBadge label={mineru.label} tone={mineru.tone} /></div><IconButton icon={<RefreshCw size={14} />} label="检查解析服务" onClick={refreshParser} size="small" tooltip /></div>
          {base.parser === 'mineru' && !mineru.ready ? <InlineNotice title="MinerU 未连接" tone="warning">本机服务不可用。</InlineNotice> : null}
        </section>
      </div>
      <section>
        <div className="knowledge-settings__heading"><Settings2 size={16} /><div><strong>切分</strong><span>修改后材料进入待重建状态</span></div></div>
        <div className="knowledge-settings-fields knowledge-settings-fields--chunking">
          <Field htmlFor="knowledge-chunk-strategy" label="策略"><select className="ui-input" id="knowledge-chunk-strategy" onChange={(event) => setChunking({ ...chunking, strategy: asChunkingStrategy(event.target.value) })} value={chunking.strategy}><option value="general">通用段落</option><option value="markdown">Markdown 标题</option><option value="book">书籍章节</option><option value="qa">问答</option><option value="laws">法律条款</option><option value="separator">自定义分隔符</option><option value="fixed">固定长度</option></select></Field>
          <Field htmlFor="knowledge-chunk-size" label="大小"><Input id="knowledge-chunk-size" max={8_000} min={200} onChange={(event) => setChunking({ ...chunking, size: Number(event.target.value) })} step={100} type="number" value={chunking.size} /></Field>
          <Field htmlFor="knowledge-chunk-overlap" label="重叠"><Input id="knowledge-chunk-overlap" max={2_000} min={0} onChange={(event) => setChunking({ ...chunking, overlap: Number(event.target.value) })} step={20} type="number" value={chunking.overlap} /></Field>
          {chunking.strategy === 'separator' ? <Field htmlFor="knowledge-chunk-separator" label="分隔符"><Input id="knowledge-chunk-separator" maxLength={100} onChange={(event) => setChunking({ ...chunking, separator: event.target.value })} value={chunking.separator} /></Field> : null}
          <Switch checked={chunking.respectHeadings} label="保留标题边界" onCheckedChange={(respectHeadings) => setChunking({ ...chunking, respectHeadings })} />
          <Switch checked={chunking.respectPageBoundaries} label="保留页面边界" onCheckedChange={(respectPageBoundaries) => setChunking({ ...chunking, respectPageBoundaries })} />
        </div>
        {chunkingError ? <p className="knowledge-inline-error" role="alert">{chunkingError}</p> : null}
        <div className="knowledge-chunk-preview-controls">
          <Field htmlFor="knowledge-preview-document" label="预览材料"><select className="ui-input" id="knowledge-preview-document" onChange={(event) => setPreviewDocumentId(event.target.value)} value={previewDocumentId}>{documents.map((document) => <option key={document.id} value={document.id}>{document.name}</option>)}</select></Field>
          <Button disabled={!previewDocumentId || Boolean(chunkingError)} loading={chunkPreviewing} onClick={() => onPreviewChunking(previewDocumentId, chunking)} size="small">预览切分</Button>
        </div>
        {chunkPreviewError ? <InlineNotice title="切分预览失败" tone="warning">{publicErrorText(chunkPreviewError, '请确认材料已经完成解析。')}</InlineNotice> : null}
        {visibleChunkPreview ? <div className="knowledge-chunk-preview"><header><strong>{visibleChunkPreview.total} 个片段</strong><span>显示前 {visibleChunkPreview.chunks.length} 个</span></header><div>{visibleChunkPreview.chunks.map((chunk) => <article key={chunk.id}><b>#{chunk.ordinal + 1}{chunk.page ? ` · 第 ${chunk.page} 页` : ''}</b><p>{chunk.content}</p></article>)}</div></div> : null}
        <div className="knowledge-settings__actions"><Button disabled={pending || Boolean(chunkingError) || equalConfig(chunking, base.chunkingConfig)} loading={pending} onClick={() => onSaveChunking(chunking)} size="small" variant="primary">保存切分设置</Button></div>
      </section>
      <section>
        <div className="knowledge-settings__heading"><Search size={16} /><div><strong>检索</strong><span>页面测试与 Agent Tool</span></div></div>
        <div className="knowledge-settings-fields">
          <Field htmlFor="knowledge-retrieval-mode" label="模式"><select className="ui-input" id="knowledge-retrieval-mode" onChange={(event) => setRetrieval({ ...retrieval, mode: asRetrievalMode(event.target.value) })} value={retrieval.mode}><option value="hybrid">混合</option><option value="dense">向量</option><option value="lexical">关键词</option></select></Field>
          <Field htmlFor="knowledge-retrieval-topk" label="Top K"><Input id="knowledge-retrieval-topk" max={100} min={1} onChange={(event) => setRetrieval({ ...retrieval, topK: Number(event.target.value) })} type="number" value={retrieval.topK} /></Field>
          <Field htmlFor="knowledge-retrieval-threshold" label="阈值"><Input id="knowledge-retrieval-threshold" max={1} min={0} onChange={(event) => setRetrieval({ ...retrieval, threshold: Number(event.target.value) })} step={0.05} type="number" value={retrieval.threshold} /></Field>
        </div>
        <div className="knowledge-settings-fields knowledge-settings-fields--advanced">
          <Field htmlFor="knowledge-lexical-weight" label="Lexical 权重"><Input id="knowledge-lexical-weight" max={10} min={0} onChange={(event) => setRetrieval({ ...retrieval, lexicalWeight: Number(event.target.value) })} step={0.1} type="number" value={retrieval.lexicalWeight} /></Field>
          <Field htmlFor="knowledge-dense-weight" label="Dense 权重"><Input id="knowledge-dense-weight" max={10} min={0} onChange={(event) => setRetrieval({ ...retrieval, denseWeight: Number(event.target.value) })} step={0.1} type="number" value={retrieval.denseWeight} /></Field>
          <Field htmlFor="knowledge-rrf-k" label="RRF K"><Input id="knowledge-rrf-k" max={1_000} min={1} onChange={(event) => setRetrieval({ ...retrieval, rrfK: Number(event.target.value) })} type="number" value={retrieval.rrfK} /></Field>
          <Field htmlFor="knowledge-candidate-multiplier" label="候选倍数"><Input id="knowledge-candidate-multiplier" max={20} min={1} onChange={(event) => setRetrieval({ ...retrieval, candidateMultiplier: Number(event.target.value) })} type="number" value={retrieval.candidateMultiplier} /></Field>
        </div>
        {retrievalError ? <p className="knowledge-inline-error" role="alert">{retrievalError}</p> : null}
        <div className="knowledge-settings__actions"><Button disabled={pending || Boolean(retrievalError) || equalConfig(retrieval, base.retrievalConfig)} loading={pending} onClick={() => onSaveRetrieval(retrieval)} size="small" variant="primary">保存检索设置</Button></div>
      </section>
      <section>
        <div className="knowledge-settings__heading"><Database size={16} /><div><strong>Embedding 与索引</strong><span>运行时只读状态</span></div></div>
        <div className="knowledge-index-status">
          <StatusBadge label={indexRuntime.available ? indexRuntime.degraded ? '降级' : '可用' : '未就绪'} tone={indexRuntime.available ? indexRuntime.degraded ? 'warning' : 'success' : 'neutral'} />
          <span>{indexRuntime.reason || '配置由 Knowledge Worker 启动环境管理。'}</span>
        </div>
        <div className="knowledge-settings-fields knowledge-settings-fields--index">
          <Field htmlFor="knowledge-dense-provider" label="Dense Provider"><Input disabled id="knowledge-dense-provider" readOnly value={indexRuntime.provider} /></Field>
          <Field htmlFor="knowledge-dense-model" label="Model / Fingerprint"><Input disabled id="knowledge-dense-model" readOnly value={indexRuntime.fingerprint || indexRuntime.model} /></Field>
          <Field htmlFor="knowledge-dense-dimension" label="维度"><Input disabled id="knowledge-dense-dimension" readOnly value={indexRuntime.dimensions ?? '未报告'} /></Field>
          <Field htmlFor="knowledge-vector-count" label="向量数量"><Input disabled id="knowledge-vector-count" readOnly value={indexRuntime.vectorCount ?? '未报告'} /></Field>
          <Field htmlFor="knowledge-index-revision" label="索引 revision"><Input disabled id="knowledge-index-revision" readOnly value={indexRevisionLabel(documents)} /></Field>
          <Field htmlFor="knowledge-config-revision" label="配置 revision"><Input disabled id="knowledge-config-revision" readOnly value={String(base.revision)} /></Field>
        </div>
        <InlineNotice title="运行时索引身份" tone="info">Provider、模型和维度由 Knowledge Worker 启动环境管理；页面只展示服务真实报告，不会伪保存。</InlineNotice>
      </section>
      <section>
        <div className="knowledge-settings__heading"><RefreshCw size={16} /><div><strong>索引重建</strong><span>{base.documentCount} 个材料 · {base.chunkCount} 个现有片段</span></div></div>
        {reindexPreview ? (
          <div className="knowledge-reindex-preview">
            <dl><div><dt>材料</dt><dd>{reindexPreview.documentCount}</dd></div><div><dt>待重建</dt><dd>{reindexPreview.staleDocumentCount}</dd></div><div><dt>预计片段</dt><dd>{reindexPreview.estimatedChunkCount || '重新计算'}</dd></div></dl>
            <div><Button disabled={rebuilding} onClick={onPreviewReindex} size="small" variant="quiet">重新预览</Button><Button loading={rebuilding} onClick={() => onRebuild(reindexPreview)} size="small" variant="primary">确认重建</Button></div>
          </div>
        ) : <div className="knowledge-settings__actions"><Button loading={reindexPreviewing} onClick={onPreviewReindex} size="small">预览重建</Button></div>}
        {rebuildError ? <InlineNotice title="索引操作失败" tone="warning">{publicErrorText(rebuildError, '当前索引保持不变。')}</InlineNotice> : null}
      </section>
    </div>
  );
}

function CreateKnowledgeBaseDialog({
  error,
  loading,
  onCreate,
  onOpenChange,
  open,
}: {
  error: unknown;
  loading: boolean;
  onCreate: (input: { name: string; description: string }) => void;
  onOpenChange: (open: boolean) => void;
  open: boolean;
}) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  useEffect(() => {
    if (!open) { setName(''); setDescription(''); }
  }, [open]);
  return (
    <Dialog open={open} onOpenChange={(next) => { if (!loading) onOpenChange(next); }}>
      <DialogContent>
        <DialogHeader><DialogTitle>新建文档知识库</DialogTitle><DialogDescription>资料和个人记忆会使用不同存储，不会混在一起。</DialogDescription></DialogHeader>
        <form className="knowledge-create-form" id="knowledge-create-form" onSubmit={(event) => { event.preventDefault(); if (name.trim()) onCreate({ name: name.trim(), description: description.trim() }); }}>
          <Field htmlFor="knowledge-base-name" label="名称" required><Input autoFocus id="knowledge-base-name" maxLength={120} onChange={(event) => setName(event.target.value)} placeholder="例如：Agent Runtime 源码" value={name} /></Field>
          <Field htmlFor="knowledge-base-description" label="说明"><TextArea id="knowledge-base-description" maxLength={1_000} onChange={(event) => setDescription(event.target.value)} placeholder="这个库包含什么、给谁使用" rows={4} value={description} /></Field>
          {error ? <p className="knowledge-inline-error" role="alert">{publicErrorText(error, '暂时无法新建知识库。')}</p> : null}
        </form>
        <DialogFooter><Button disabled={loading} onClick={() => onOpenChange(false)} variant="quiet">取消</Button><Button disabled={!name.trim()} form="knowledge-create-form" loading={loading} type="submit" variant="primary">创建</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ReparseDocumentDialog({ document, error, loading, onConfirm, onOpenChange }: { document: KnowledgeDocument | null; error: unknown; loading: boolean; onConfirm: (parser: KnowledgeParserMode) => void; onOpenChange: (open: boolean) => void }) {
  const [parser, setParser] = useState<KnowledgeParserMode>('auto');
  useEffect(() => { if (document) setParser(asParserMode(document.parser)); }, [document]);
  return (
    <Dialog open={Boolean(document)} onOpenChange={(next) => { if (!loading) onOpenChange(next); }}>
      <DialogContent>
        <DialogHeader><DialogTitle>重新解析文档</DialogTitle><DialogDescription>{document ? `“${document.name}”将重新生成 Markdown、Chunks 和索引。` : ''}</DialogDescription></DialogHeader>
        <div className="knowledge-create-form">
          <Field htmlFor="knowledge-document-parser" label="解析方式">
            <select className="ui-input" id="knowledge-document-parser" onChange={(event) => setParser(asParserMode(event.target.value))} value={parser}>
              <option value="auto">自动选择</option>
              <option value="builtin">内置文本解析</option>
              <option value="mineru">MinerU OCR / 版面解析</option>
            </select>
          </Field>
          {parser === 'mineru' ? <InlineNotice title="MinerU OCR" tone="info">适用于扫描 PDF、图片和需要保留版面的文档；任务会走本机 MinerU 服务。</InlineNotice> : null}
          {error ? <p className="knowledge-inline-error" role="alert">{publicErrorText(error, '重新解析失败，现有索引仍然保留。')}</p> : null}
        </div>
        <DialogFooter><Button disabled={loading} onClick={() => onOpenChange(false)} variant="quiet">取消</Button><Button leadingIcon={<RefreshCw size={14} />} loading={loading} onClick={() => onConfirm(parser)} variant="primary">开始重新解析</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ConfirmDialog({ description, error, loading, onConfirm, onOpenChange, open, title }: { description: string; error: unknown; loading: boolean; onConfirm: () => void; onOpenChange: (open: boolean) => void; open: boolean; title: string }) {
  return (
    <Dialog open={open} onOpenChange={(next) => { if (!loading) onOpenChange(next); }}>
      <DialogContent>
        <DialogHeader><DialogTitle>{title}</DialogTitle><DialogDescription>{description}</DialogDescription></DialogHeader>
        {error ? <p className="knowledge-inline-error" role="alert">{publicErrorText(error, '删除失败，原内容仍然保留。')}</p> : null}
        <DialogFooter><Button disabled={loading} onClick={() => onOpenChange(false)} variant="quiet">取消</Button><Button leadingIcon={<Trash2 size={14} />} loading={loading} onClick={onConfirm}>确认删除</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

interface WorkerState { label: string; tone: 'success' | 'warning' | 'danger' | 'info' | 'neutral' }

function workerState(value: unknown, error: unknown): WorkerState {
  if (error) return { label: '不可用', tone: 'danger' };
  const payload = object(value);
  const status = String(payload.status ?? payload.state ?? '').toLowerCase();
  if (payload.ok === true || ['ready', 'healthy', 'idle', 'running'].includes(status)) return { label: status === 'idle' ? '待命' : '可用', tone: 'success' };
  if (!value) return { label: '检查中', tone: 'info' };
  return { label: '未就绪', tone: 'warning' };
}

function mineruState(value: unknown): WorkerState & { ready: boolean } {
  const payload = object(value);
  const list = Array.isArray(payload.items) ? payload.items : Array.isArray(payload.parsers) ? payload.parsers : [];
  const mineru = list.map(object).find((item) => String(item.id ?? item.name ?? item.provider).toLowerCase().includes('mineru')) ?? object(payload.mineru);
  const status = String(mineru.status ?? mineru.state ?? '').toLowerCase();
  const ready = mineru.ready === true || mineru.available === true || ['ready', 'healthy', 'running'].includes(status);
  const enabled = mineru.enabled === true;
  if (ready) return { ready, label: '已连接', tone: 'success' };
  if (enabled) return { ready, label: '连接失败', tone: 'danger' };
  return { ready, label: '未启用', tone: 'neutral' };
}

function object(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function asDetailTab(value: string): DetailTab { return ['viewer', 'search', 'jobs', 'settings'].includes(value) ? value as DetailTab : 'materials'; }
function asParserMode(value: string): KnowledgeParserMode { return value === 'builtin' ? value : value === 'mineru' || value === 'mineru_local_http' ? 'mineru' : 'auto'; }
function asChunkingStrategy(value: string): KnowledgeChunkingConfig['strategy'] { return ['general', 'markdown', 'book', 'qa', 'laws', 'separator', 'fixed'].includes(value) ? value as KnowledgeChunkingConfig['strategy'] : 'markdown'; }
function asRetrievalMode(value: string): KnowledgeRetrievalConfig['mode'] { return value === 'dense' || value === 'lexical' ? value : 'hybrid'; }
function retrievalModeLabel(value: KnowledgeRetrievalConfig['mode']): string { return value === 'dense' ? '向量检索' : value === 'lexical' ? '关键词检索' : '混合检索'; }
function equalConfig(left: object, right: object): boolean { return JSON.stringify(left) === JSON.stringify(right); }
function parserLabel(value: KnowledgeParserMode): string { return value === 'builtin' ? '内置' : value === 'mineru' ? 'MinerU' : '自动'; }
function scoreLabel(value: number | null): string { return value === null ? '未提供评分' : `${Math.round(value <= 1 ? value * 100 : value)}%`; }
function citationLabel(hit: KnowledgeSearchHit): string { if (hit.page !== null) return `第 ${hit.page} 页`; if (hit.lineStart !== null) return hit.lineEnd && hit.lineEnd !== hit.lineStart ? `第 ${hit.lineStart}-${hit.lineEnd} 行` : `第 ${hit.lineStart} 行`; return '文档片段'; }
function uploadItemId(file: File, index: number): string { return `upload-${Date.now()}-${index}-${file.name}-${file.size}`; }
function replaceUploadItem(items: KnowledgeUploadItem[], id: string, patch: Partial<KnowledgeUploadItem>): KnowledgeUploadItem[] { return items.map((item) => item.id === id ? { ...item, ...patch } : item); }
function indexRevisionLabel(documents: readonly KnowledgeDocument[]): string {
  const revisions = [...new Set(documents.map((document) => document.indexedConfigRevision).filter((value) => value > 0))].sort((left, right) => left - right);
  if (!revisions.length) return '未建立';
  return revisions.length === 1 ? String(revisions[0]) : `${revisions[0]}–${revisions.at(-1)}`;
}
