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
import { useSearchParams } from 'react-router-dom';
import { Virtuoso } from 'react-virtuoso';
import { useControlTransport } from '@/app/control-transport';
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
  Select,
  Switch,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  TextArea,
} from '@/components/primitives';
import {
  InlineNotice,
  QueryState,
  StatusBadge,
  asRecord,
  numberValue,
  publicErrorText,
} from '@/features/overview/management-ui';
import {
  ManagementMutationWorkflow,
  parseManagementWorkPreview,
  parseManagementWorkReceipt,
} from '@/features/overview/management-mutation';
import {
  configurationMutationPathIds,
  useConfigurationMutationBoundary,
} from '@/features/configuration/api';
import {
  chooseKnowledgeFiles,
  cancelKnowledgeJob,
  createKnowledgeBase,
  deleteKnowledgeBase,
  deleteKnowledgeDocument,
  importKnowledgeDocuments,
  knowledgeLibraryKeys,
  openKnowledgeHit,
  previewKnowledgeEmbeddingImpact,
  previewKnowledgeReindex,
  previewKnowledgeChunking,
  probeKnowledgeEmbedding,
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
  type KnowledgeEmbeddingCandidate,
  type KnowledgeEmbeddingImpact,
  type KnowledgeEmbeddingProfileState,
  type KnowledgeEmbeddingProvider,
  type KnowledgeParserMode,
  type KnowledgeRetrievalConfig,
  type KnowledgeReindexPreview,
  type KnowledgeSearchHit,
  knowledgeIndexRuntimeStatus,
} from './api';
import { KnowledgeDocumentViewer, KnowledgeJobsPanel, KnowledgeMaterialsPanel, type KnowledgeUploadItem } from './document-workspace';
import { KnowledgeGraphPanel } from './knowledge-graph';
import './knowledge.css';

type DetailTab = 'materials' | 'viewer' | 'search' | 'graph' | 'jobs' | 'settings';

export function KnowledgeFeature() {
  const [selectedBaseId, setSelectedBaseId] = useState('');
  const [searchParams, setSearchParams] = useSearchParams();
  const tab = asDetailTab(searchParams.get('tab') ?? 'materials');
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
  const selectTab = (nextTab: DetailTab, replace = true) => {
    const next = new URLSearchParams(searchParams);
    if (nextTab === 'materials') next.delete('tab');
    else next.set('tab', nextTab);
    setSearchParams(next, { replace });
  };

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
    mutationFn: async (input: { name: string; description: string }) => {
      const created = await createKnowledgeBase(queries.transport, input);
      if (!created.id || created.name !== input.name) {
        throw new Error('知识服务没有确认新知识库，未关闭创建窗口。');
      }
      return created;
    },
    onSuccess: async (base) => {
      queryClient.setQueryData<DocumentKnowledgeBase[]>(knowledgeLibraryKeys.bases(), (current = []) => (
        current.some((item) => item.id === base.id)
          ? current.map((item) => item.id === base.id ? base : item)
          : [...current, base]
      ));
      queryClient.setQueryData(knowledgeLibraryKeys.base(base.id), base);
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
    onSuccess: async () => {
      setReparseDocument(null);
      selectTab('jobs');
      await invalidateBase();
    },
  });
  const deleteDocumentMutation = useMutation({
    mutationFn: (documentId: string) => deleteKnowledgeDocument(queries.transport, selectedBaseId, documentId),
    onSuccess: async () => {
      setDocumentToDelete(null);
      await invalidateBase();
    },
  });
  const updateMutation = useMutation({
    mutationFn: async (patch: {
      name?: string;
      description?: string;
      agentEnabled?: boolean;
      parser?: KnowledgeParserMode;
      chunkingConfig?: KnowledgeChunkingConfig;
      retrievalConfig?: KnowledgeRetrievalConfig;
    }) => {
      if (!selectedBase) throw new Error('没有选中的知识库。');
      const updated = await updateKnowledgeBase(queries.transport, selectedBase, patch);
      if (
        (patch.name !== undefined && updated.name !== patch.name)
        || (patch.description !== undefined && updated.description !== patch.description)
      ) {
        throw new Error('知识服务没有确认基本信息更新，页面仍保留你的输入。');
      }
      return updated;
    },
    onSuccess: async (base) => {
      queryClient.setQueryData(knowledgeLibraryKeys.base(base.id), base);
      queryClient.setQueryData<DocumentKnowledgeBase[]>(knowledgeLibraryKeys.bases(), (current = []) => (
        current.map((item) => item.id === base.id ? base : item)
      ));
      await invalidateBase(base.id);
    },
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
      selectTab('jobs');
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
    <main className="knowledge-feature" data-route-id="knowledge">
      <h1 className="knowledge-feature__title">知识库</h1>
      <QueryState error={pageError} isPending={queries.bases.isPending} onRetry={refresh}>
        <div className="knowledge-library" data-empty={!bases.length || undefined}>
          <KnowledgeBaseRail
            bases={bases}
            onCreate={() => setCreateOpen(true)}
            onRefresh={refresh}
            onSelect={(baseId) => { setSelectedBaseId(baseId); setSelectedDocumentId(''); selectTab('materials'); }}
            refreshing={queries.bases.isFetching || queries.worker.isFetching}
            selectedBaseId={selectedBaseId}
            worker={worker}
          />
          <section className="knowledge-library__detail" aria-label="知识库详情">
            {selectedBase ? (
              <>
                <KnowledgeBaseHeader base={selectedBase} onDelete={() => setDeleteBaseOpen(true)} worker={worker} />
                <Tabs className="knowledge-library__tabs" onValueChange={(value) => selectTab(asDetailTab(value))} value={tab}>
                  <TabsList aria-label="知识库管理视图">
                    <TabsTrigger value="materials">资料</TabsTrigger>
                    <TabsTrigger value="viewer">查看材料</TabsTrigger>
                    <TabsTrigger value="search">检索测试</TabsTrigger>
                    <TabsTrigger value="graph">知识图谱</TabsTrigger>
                    <TabsTrigger value="jobs">处理记录</TabsTrigger>
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
                      onOpen={(documentId) => { setFocusedHit(null); setSelectedDocumentId(documentId); selectTab('viewer'); }}
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
                    <KnowledgeSearchPanel base={selectedBase} onOpenHit={(hit) => { setSelectedDocumentId(hit.documentId); setFocusedHit(hit); selectTab('viewer'); }} transport={queries.transport} />
                  </TabsContent>
                  <TabsContent value="graph">
                    <KnowledgeGraphPanel
                      base={selectedBase}
                      documents={documents}
                      onOpenSource={(node) => {
                        if (!node.documentId) return;
                        const document = documents.find((item) => item.id === node.documentId);
                        setSelectedDocumentId(node.documentId);
                        setFocusedHit(node.chunkId ? {
                          id: node.chunkId,
                          documentId: node.documentId,
                          documentName: node.documentName || document?.name || '',
                          title: node.heading || node.label,
                          excerpt: node.excerpt,
                          score: node.weight,
                          page: node.page,
                          heading: node.heading,
                          lineStart: null,
                          lineEnd: null,
                          diagnostics: { effectiveMode: 'unknown', lexicalRank: null, denseRank: null, graphRank: null, lexicalScore: null, denseScore: null, graphScore: null, graphMatches: [], graphPaths: [] },
                        } : null);
                        selectTab('viewer');
                      }}
                      transport={queries.transport}
                    />
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
                      key={selectedBase.id}
                      base={selectedBase}
                      documents={documents}
                      embeddingState={queries.embeddingProfile.data}
                      embeddingStateError={queries.embeddingProfile.error}
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
                      settingsEnvelope={queries.settings.data}
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
    </main>
  );
}

function KnowledgeBaseRail({
  bases,
  onCreate,
  onRefresh,
  onSelect,
  refreshing,
  selectedBaseId,
  worker,
}: {
  bases: readonly DocumentKnowledgeBase[];
  onCreate: () => void;
  onRefresh: () => void;
  onSelect: (baseId: string) => void;
  refreshing: boolean;
  selectedBaseId: string;
  worker: WorkerState;
}) {
  return (
    <aside className="knowledge-base-rail" aria-label="文档知识库">
      <header>
        <div><strong>知识库</strong><span>{bases.length} 个独立库</span></div>
        <div className="knowledge-base-rail__actions">
          <IconButton disabled={refreshing} icon={<RefreshCw size={14} />} label="刷新知识库" onClick={onRefresh} size="small" tooltip />
          <IconButton icon={<FolderPlus size={15} />} label="新建知识库" onClick={onCreate} size="small" tooltip />
        </div>
      </header>
      <div className="knowledge-base-rail__mobile">
        <Field htmlFor="knowledge-mobile-base" label="当前知识库">
          <Select
            disabled={!bases.length}
            id="knowledge-mobile-base"
            onValueChange={onSelect}
            options={bases.map((base) => ({
              value: base.id,
              label: `${base.name} · ${base.documentCount} 个文件`,
            }))}
            value={selectedBaseId || bases[0]?.id || ''}
          />
        </Field>
        <span className="knowledge-base-rail__mobile-worker" data-state={worker.tone}>
          <i aria-hidden="true" />
          {worker.label}
        </span>
        <div className="knowledge-base-rail__actions">
          <IconButton disabled={refreshing} icon={<RefreshCw size={15} />} label="刷新知识库" onClick={onRefresh} size="large" tooltip />
          <IconButton icon={<FolderPlus size={16} />} label="新建知识库" onClick={onCreate} size="large" tooltip />
        </div>
      </div>
      <div className="knowledge-base-rail__worker" data-state={worker.tone}>
        <i aria-hidden="true" />
        <span>知识服务</span>
        <b>{worker.label}</b>
      </div>
      {bases.length ? (
        <Virtuoso
          className="knowledge-base-rail__list"
          data={bases}
          itemContent={(_index, base) => (
            <button
              aria-label={`${base.name}，${base.documentCount} 个文件，${base.chunkCount} 个片段`}
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
        {base.retrievalConfig.mode === 'hybrid' ? (
          <span>{base.retrievalConfig.graphEnabled ? `图谱 ×${base.retrievalConfig.graphWeight.toFixed(1)}` : '图谱关闭'}</span>
        ) : null}
      </div>
      <p className="knowledge-search__score-note">排名分融合关键词、向量与已就绪图谱的候选名次，只用于排列召回片段，不代表答案正确率。</p>
      {searchMutation.error ? <InlineNotice title="检索失败" tone="warning">{publicErrorText(searchMutation.error, '知识服务暂时无法完成检索。')}</InlineNotice> : null}
      {hits.length ? (
        <div className="knowledge-search__results">
          <div className="knowledge-search__list" role="listbox" aria-label="检索结果">
            {hits.map((hit) => (
              <button aria-selected={selected?.id === hit.id} data-selected={selected?.id === hit.id || undefined} key={hit.id} onClick={() => setSelectedId(hit.id)} role="option" type="button">
                <span><strong>{hit.documentName}</strong><small>{hit.title} · {citationLabel(hit)}{hit.diagnostics.graphRank === null ? '' : ' · 图谱关联'}</small><small>{hit.excerpt || '没有可显示的摘录'}</small></span>
                <b>{scorePoints(hit.score)}</b>
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
        <div><dt>综合排名分</dt><dd>{scorePoints(hit.score)} / 100（非正确率）</dd></div>
        <div><dt>命中依据</dt><dd>{retrievalEvidenceLabel(hit)}</dd></div>
        {hit.diagnostics.graphPaths.length ? <div><dt>图谱路径</dt><dd>{hit.diagnostics.graphPaths.slice(0, 2).join('；')}</dd></div> : null}
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
  embeddingState,
  embeddingStateError,
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
  settingsEnvelope,
  updateError,
  worker,
}: {
  base: DocumentKnowledgeBase;
  chunkPreview: KnowledgeChunkPreview | null;
  chunkPreviewError: unknown;
  chunkPreviewing: boolean;
  documents: readonly KnowledgeDocument[];
  embeddingState: KnowledgeEmbeddingProfileState | undefined;
  embeddingStateError: unknown;
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
  settingsEnvelope: unknown;
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
        : retrieval.graphWeight < 0 || retrieval.graphWeight > 10
          ? '图谱权重必须在 0–10 之间。'
        : retrieval.lexicalWeight + retrieval.denseWeight <= 0
          ? 'Lexical 和 Dense 权重不能同时为 0。'
          : retrieval.rrfK < 1 || retrieval.rrfK > 1_000 || retrieval.candidateMultiplier < 1 || retrieval.candidateMultiplier > 20
            ? 'RRF K 或候选倍数超出允许范围。'
            : '';
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
          <div className="knowledge-settings__heading"><ServerCog size={16} /><div><strong>Agent</strong><span>knowledge</span></div></div>
          <Switch checked={base.agentEnabled} disabled={pending} label="允许 Agent 使用" onCheckedChange={onAgentEnabled} />
        </section>
        <section>
          <div className="knowledge-settings__heading"><Settings2 size={16} /><div><strong>解析器</strong><span>新导入与重试</span></div></div>
          <Field htmlFor="knowledge-parser" label="Provider">
            <Select disabled={pending} id="knowledge-parser" onValueChange={(value) => onParser(asParserMode(value))} options={[{ value: 'auto', label: '自动选择' }, { value: 'builtin', label: '内置解析' }, { value: 'mineru', label: 'MinerU' }]} value={base.parser} />
          </Field>
          <div className="knowledge-parser-health"><div><span>Worker</span><StatusBadge label={worker.label} tone={worker.tone} /></div><div><span>MinerU</span><StatusBadge label={mineru.label} tone={mineru.tone} /></div><IconButton icon={<RefreshCw size={14} />} label="检查解析服务" onClick={refreshParser} size="small" tooltip /></div>
          {base.parser === 'mineru' && !mineru.ready ? <InlineNotice title="MinerU 未连接" tone="warning">本机服务不可用。</InlineNotice> : null}
        </section>
      </div>
      <section>
        <div className="knowledge-settings__heading"><Settings2 size={16} /><div><strong>切分</strong><span>修改后材料进入待重建状态</span></div></div>
        <div className="knowledge-settings-fields knowledge-settings-fields--chunking">
          <Field htmlFor="knowledge-chunk-strategy" label="策略"><Select id="knowledge-chunk-strategy" onValueChange={(value) => setChunking({ ...chunking, strategy: asChunkingStrategy(value) })} options={[{ value: 'general', label: '通用段落' }, { value: 'markdown', label: 'Markdown 标题' }, { value: 'book', label: '书籍章节' }, { value: 'qa', label: '问答' }, { value: 'laws', label: '法律条款' }, { value: 'separator', label: '自定义分隔符' }, { value: 'fixed', label: '固定长度' }]} value={chunking.strategy} /></Field>
          <Field htmlFor="knowledge-chunk-size" label="大小"><Input id="knowledge-chunk-size" max={8_000} min={200} onChange={(event) => setChunking({ ...chunking, size: Number(event.target.value) })} step={100} type="number" value={chunking.size} /></Field>
          <Field htmlFor="knowledge-chunk-overlap" label="重叠"><Input id="knowledge-chunk-overlap" max={2_000} min={0} onChange={(event) => setChunking({ ...chunking, overlap: Number(event.target.value) })} step={20} type="number" value={chunking.overlap} /></Field>
          {chunking.strategy === 'separator' ? <Field htmlFor="knowledge-chunk-separator" label="分隔符"><Input id="knowledge-chunk-separator" maxLength={100} onChange={(event) => setChunking({ ...chunking, separator: event.target.value })} value={chunking.separator} /></Field> : null}
          <Switch checked={chunking.respectHeadings} label="保留标题边界" onCheckedChange={(respectHeadings) => setChunking({ ...chunking, respectHeadings })} />
          <Switch checked={chunking.respectPageBoundaries} label="保留页面边界" onCheckedChange={(respectPageBoundaries) => setChunking({ ...chunking, respectPageBoundaries })} />
        </div>
        {chunkingError ? <p className="knowledge-inline-error" role="alert">{chunkingError}</p> : null}
        <div className="knowledge-chunk-preview-controls">
          <Field htmlFor="knowledge-preview-document" label="预览材料"><Select id="knowledge-preview-document" onValueChange={setPreviewDocumentId} options={documents.map((document) => ({ value: document.id, label: document.name }))} value={previewDocumentId} /></Field>
          <Button disabled={!previewDocumentId || Boolean(chunkingError)} loading={chunkPreviewing} onClick={() => onPreviewChunking(previewDocumentId, chunking)} size="small">预览切分</Button>
        </div>
        {chunkPreviewError ? <InlineNotice title="切分预览失败" tone="warning">{publicErrorText(chunkPreviewError, '请确认材料已经完成解析。')}</InlineNotice> : null}
        {visibleChunkPreview ? <div className="knowledge-chunk-preview"><header><strong>{visibleChunkPreview.total} 个片段</strong><span>显示前 {visibleChunkPreview.chunks.length} 个</span></header><div>{visibleChunkPreview.chunks.map((chunk) => <article key={chunk.id}><b>#{chunk.ordinal + 1}{chunk.page ? ` · 第 ${chunk.page} 页` : ''}</b><p>{chunk.content}</p></article>)}</div></div> : null}
        <div className="knowledge-settings__actions"><Button disabled={pending || Boolean(chunkingError) || equalConfig(chunking, base.chunkingConfig)} loading={pending} onClick={() => onSaveChunking(chunking)} size="small" variant="primary">保存切分设置</Button></div>
      </section>
      <section>
        <div className="knowledge-settings__heading"><Search size={16} /><div><strong>检索</strong><span>页面测试与 Agent Tool</span></div></div>
        <div className="knowledge-settings-fields">
          <Field htmlFor="knowledge-retrieval-mode" label="模式"><Select id="knowledge-retrieval-mode" onValueChange={(value) => setRetrieval({ ...retrieval, mode: asRetrievalMode(value) })} options={[{ value: 'hybrid', label: '混合' }, { value: 'dense', label: '向量' }, { value: 'lexical', label: '关键词' }]} value={retrieval.mode} /></Field>
          <Field htmlFor="knowledge-retrieval-topk" label="Top K"><Input id="knowledge-retrieval-topk" max={100} min={1} onChange={(event) => setRetrieval({ ...retrieval, topK: Number(event.target.value) })} type="number" value={retrieval.topK} /></Field>
          <Field htmlFor="knowledge-retrieval-threshold" label="阈值"><Input id="knowledge-retrieval-threshold" max={1} min={0} onChange={(event) => setRetrieval({ ...retrieval, threshold: Number(event.target.value) })} step={0.05} type="number" value={retrieval.threshold} /></Field>
        </div>
        <div className="knowledge-settings-fields knowledge-settings-fields--advanced">
          <Field htmlFor="knowledge-lexical-weight" label="Lexical 权重"><Input id="knowledge-lexical-weight" max={10} min={0} onChange={(event) => setRetrieval({ ...retrieval, lexicalWeight: Number(event.target.value) })} step={0.1} type="number" value={retrieval.lexicalWeight} /></Field>
          <Field htmlFor="knowledge-dense-weight" label="Dense 权重"><Input id="knowledge-dense-weight" max={10} min={0} onChange={(event) => setRetrieval({ ...retrieval, denseWeight: Number(event.target.value) })} step={0.1} type="number" value={retrieval.denseWeight} /></Field>
          <Switch checked={retrieval.graphEnabled} disabled={retrieval.mode !== 'hybrid'} label="启用图谱增强" onCheckedChange={(graphEnabled) => setRetrieval({ ...retrieval, graphEnabled })} />
          <Field htmlFor="knowledge-graph-weight" label="Graph 权重"><Input disabled={retrieval.mode !== 'hybrid' || !retrieval.graphEnabled} id="knowledge-graph-weight" max={10} min={0} onChange={(event) => setRetrieval({ ...retrieval, graphWeight: Number(event.target.value) })} step={0.05} type="number" value={retrieval.graphWeight} /></Field>
          <Field htmlFor="knowledge-rrf-k" label="RRF K"><Input id="knowledge-rrf-k" max={1_000} min={1} onChange={(event) => setRetrieval({ ...retrieval, rrfK: Number(event.target.value) })} type="number" value={retrieval.rrfK} /></Field>
          <Field htmlFor="knowledge-candidate-multiplier" label="候选倍数"><Input id="knowledge-candidate-multiplier" max={20} min={1} onChange={(event) => setRetrieval({ ...retrieval, candidateMultiplier: Number(event.target.value) })} type="number" value={retrieval.candidateMultiplier} /></Field>
        </div>
        {retrievalError ? <p className="knowledge-inline-error" role="alert">{retrievalError}</p> : null}
        <div className="knowledge-settings__actions"><Button disabled={pending || Boolean(retrievalError) || equalConfig(retrieval, base.retrievalConfig)} loading={pending} onClick={() => onSaveRetrieval(retrieval)} size="small" variant="primary">保存检索设置</Button></div>
      </section>
      <KnowledgeEmbeddingSettings
        baseRevision={String(base.revision)}
        documents={documents}
        error={embeddingStateError}
        fallbackRuntime={indexRuntime}
        settingsEnvelope={settingsEnvelope}
        state={embeddingState}
      />
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

type EmbeddingMutationContext = {
  candidate: KnowledgeEmbeddingCandidate;
  changes: KnowledgeEmbeddingImpact['configurationChanges'];
  impact: KnowledgeEmbeddingImpact;
};

function KnowledgeEmbeddingSettings({
  baseRevision,
  documents,
  error,
  fallbackRuntime,
  settingsEnvelope,
  state,
}: {
  baseRevision: string;
  documents: readonly KnowledgeDocument[];
  error: unknown;
  fallbackRuntime: KnowledgeIndexRuntimeStatus;
  settingsEnvelope: unknown;
  state: KnowledgeEmbeddingProfileState | undefined;
}) {
  const transport = useControlTransport();
  const queryClient = useQueryClient();
  const mutationBoundary = useConfigurationMutationBoundary();
  const [candidate, setCandidate] = useState<KnowledgeEmbeddingCandidate>(emptyEmbeddingCandidate());
  const [draftDirty, setDraftDirty] = useState(false);
  const [verifiedDraftKey, setVerifiedDraftKey] = useState('');
  const profileRevision = state?.profile.profileSha256 ?? '';
  const draftKey = JSON.stringify(candidate);
  const settingsRoot = asRecord(settingsEnvelope);
  const runtimeConfig = asRecord(settingsRoot.runtimeConfig);
  const rawRuntimeRevision = settingsRoot.runtimeRevision ?? runtimeConfig.runtimeRevision;
  const runtimeRevision = Number.isInteger(rawRuntimeRevision) && numberValue(rawRuntimeRevision) >= 0
    ? numberValue(rawRuntimeRevision)
    : null;
  const validationError = embeddingCandidateError(candidate);

  useEffect(() => {
    if (!state || draftDirty) return;
    setCandidate(candidateFromEmbeddingState(state));
  }, [draftDirty, profileRevision, state]);

  const probeMutation = useMutation({
    mutationKey: ['knowledge-library', 'embedding', 'probe'],
    mutationFn: (profile: KnowledgeEmbeddingCandidate) => probeKnowledgeEmbedding(transport, profile),
    onSuccess: (_receipt, profile) => setVerifiedDraftKey(JSON.stringify(profile)),
  });
  const verified = Boolean(probeMutation.data && verifiedDraftKey === draftKey);
  const updateCandidate = (patch: Partial<KnowledgeEmbeddingCandidate>) => {
    setCandidate((current) => ({ ...current, ...patch }));
    setDraftDirty(true);
    setVerifiedDraftKey('');
    probeMutation.reset();
  };
  const selectProvider = (provider: KnowledgeEmbeddingProvider) => {
    if (provider === 'environment' || provider === 'none') {
      updateCandidate({ provider, model: '', baseUrl: '', dimensions: 0, secretReference: '', queryPrefix: '', documentPrefix: '', denseBackend: 'sqlite-exact' });
      return;
    }
    if (provider === 'local-hash') {
      updateCandidate({ provider, model: 'deterministic-term-vector-v1', baseUrl: '', dimensions: candidate.dimensions >= 8 ? candidate.dimensions : 96, secretReference: '', queryPrefix: '', documentPrefix: '' });
      return;
    }
    updateCandidate({ provider, model: candidate.model === 'deterministic-term-vector-v1' ? '' : candidate.model, baseUrl: provider === 'openai-compatible' ? candidate.baseUrl : '', secretReference: provider === 'openai-compatible' ? candidate.secretReference : '' });
  };
  const refreshAuthoritativeState = async () => {
    await queryClient.invalidateQueries({ queryKey: knowledgeLibraryKeys.root });
    setDraftDirty(false);
    setVerifiedDraftKey('');
  };
  const blockedReason = runtimeRevision === null
    ? '当前设置 revision 尚未就绪，请刷新后重试。'
    : validationError
      ? validationError
      : !verified
        ? '请先测试候选模型；只有 Probe 成功的同一份配置才能进入影响预览。'
        : '';
  const phase = state?.phase ?? 'applied_pending_restart';
  const runtime = state?.runtime;
  const runtimeProvider = String(runtime?.provider.provider ?? fallbackRuntime.provider);
  const runtimeModel = String(runtime?.provider.model ?? fallbackRuntime.model);
  const fingerprint = runtime?.fingerprint || fallbackRuntime.fingerprint;
  const dimensions = runtime?.dimensions ?? fallbackRuntime.dimensions;
  const vectorCount = runtime?.vectorCount ?? fallbackRuntime.vectorCount;
  const phaseLabel = phase === 'active' ? '已生效' : phase === 'applied_pending_rebuild' ? '待重建' : '待 Worker 重启';
  const phaseTone = phase === 'active' ? 'success' : 'warning';

  return (
    <section aria-label="Embedding 与索引">
      <div className="knowledge-settings__heading"><Database size={16} /><div><strong>Embedding 与索引</strong><span>全局 Profile · Probe · 批准 · 重建</span></div></div>
      {error ? <InlineNotice title="无法读取活动 Embedding Profile" tone="warning">{publicErrorText(error, '当前草稿不会自动应用。')}</InlineNotice> : null}
      <div className="knowledge-index-status">
        <StatusBadge label={phaseLabel} tone={phaseTone} />
        <span>{runtime?.reason || fallbackRuntime.reason || '配置状态与实际向量覆盖率分别核对。'}</span>
      </div>
      <div className="knowledge-settings-fields knowledge-settings-fields--index">
        <Field htmlFor="knowledge-embedding-provider" label="Embedding Provider">
          <Select
            id="knowledge-embedding-provider"
            onValueChange={(value) => selectProvider(value as KnowledgeEmbeddingProvider)}
            options={embeddingProviderOptions}
            value={candidate.provider}
          />
        </Field>
        <Field htmlFor="knowledge-embedding-model" label="Embedding 模型">
          <Input disabled={['environment', 'none', 'local-hash'].includes(candidate.provider)} id="knowledge-embedding-model" maxLength={1_000} onChange={(event) => updateCandidate({ model: event.target.value })} value={candidate.model} />
        </Field>
        <Field htmlFor="knowledge-embedding-base-url" label="兼容 API 地址">
          <Input disabled={candidate.provider !== 'openai-compatible'} id="knowledge-embedding-base-url" maxLength={2_000} onChange={(event) => updateCandidate({ baseUrl: event.target.value })} placeholder="https://host.example/v1" value={candidate.baseUrl} />
        </Field>
        <Field htmlFor="knowledge-embedding-dimensions" label="向量维度">
          <Input disabled={['environment', 'none'].includes(candidate.provider)} id="knowledge-embedding-dimensions" max={65_536} min={0} onChange={(event) => updateCandidate({ dimensions: Number(event.target.value) })} type="number" value={candidate.dimensions} />
        </Field>
        <Field htmlFor="knowledge-embedding-secret-reference" label="密钥环境变量名">
          <Input disabled={candidate.provider !== 'openai-compatible'} id="knowledge-embedding-secret-reference" maxLength={128} onChange={(event) => updateCandidate({ secretReference: event.target.value })} placeholder="PAW_EMBEDDING_API_KEY" value={candidate.secretReference} />
        </Field>
      </div>
      <details className="knowledge-embedding-advanced">
        <summary>高级参数</summary>
        <div className="knowledge-settings-fields knowledge-settings-fields--advanced">
          <Field htmlFor="knowledge-embedding-backend" label="Dense 索引后端">
            <Select disabled={['environment', 'none'].includes(candidate.provider)} id="knowledge-embedding-backend" onValueChange={(value) => updateCandidate({ denseBackend: value === 'usearch' ? 'usearch' : 'sqlite-exact' })} options={[{ value: 'sqlite-exact', label: 'SQLite exact' }, { value: 'usearch', label: 'USearch ANN' }]} value={candidate.denseBackend} />
          </Field>
          <Field htmlFor="knowledge-embedding-query-prefix" label="Query Prefix">
            <Input disabled={['environment', 'none', 'local-hash'].includes(candidate.provider)} id="knowledge-embedding-query-prefix" maxLength={500} onChange={(event) => updateCandidate({ queryPrefix: event.target.value })} value={candidate.queryPrefix} />
          </Field>
          <Field htmlFor="knowledge-embedding-document-prefix" label="Document Prefix">
            <Input disabled={['environment', 'none', 'local-hash'].includes(candidate.provider)} id="knowledge-embedding-document-prefix" maxLength={500} onChange={(event) => updateCandidate({ documentPrefix: event.target.value })} value={candidate.documentPrefix} />
          </Field>
        </div>
      </details>
      {validationError ? <p className="knowledge-inline-error" role="alert">{validationError}</p> : null}
      <div className="knowledge-settings__actions">
        <Button disabled={Boolean(validationError) || !state} loading={probeMutation.isPending} onClick={() => probeMutation.mutate(candidate)} size="small">测试候选模型</Button>
      </div>
      {probeMutation.error ? <InlineNotice title="候选模型测试失败" tone="warning">{publicErrorText(probeMutation.error, '不会保存或重启当前 Worker。')}</InlineNotice> : null}
      {verified && probeMutation.data ? (
        <InlineNotice title="Probe 已通过" tone="success">
          {probeMutation.data.provider} · {probeMutation.data.model || '无向量模型'} · {probeMutation.data.dimensions} 维 · {probeMutation.data.latencyMs.toFixed(1)} ms；收据不包含密钥。
        </InlineNotice>
      ) : null}
      <ManagementMutationWorkflow<EmbeddingMutationContext>
        availability={mutationBoundary.availability(blockedReason)}
        description="先再次 Probe 并列出所有受影响知识库；批准后保存 Profile、重启隔离 Worker，再逐库重建。旧 fingerprint 向量保留用于配置回滚。"
        draftKey={JSON.stringify({ draftKey, profileRevision, runtimeRevision })}
        mutationKey={['knowledge-library', 'embedding', 'apply']}
        onApply={async (preview) => parseManagementWorkReceipt(
          await mutationBoundary.request({
            pathId: configurationMutationPathIds.apply,
            body: {
              changes: preview.context.changes,
              expectedRuntimeRevision: preview.expectedRuntimeRevision,
              previewToken: preview.previewToken,
              payloadSha256: preview.payloadSha256,
              confirmText: preview.requiredConfirm,
            },
          }),
          configurationMutationPathIds.apply,
          preview.payloadSha256,
        )}
        onApplied={() => void refreshAuthoritativeState()}
        onPreview={async () => {
          if (!verified || runtimeRevision === null || !state) throw new Error('候选 Profile 已变化，请重新 Probe。');
          const impact = await previewKnowledgeEmbeddingImpact(transport, candidate);
          if (impact.currentProfileSha256 !== state.profile.profileSha256 || impact.probe.profileSha256 !== probeMutation.data?.profileSha256) {
            throw new Error('活动 Profile 或 Probe 收据已经变化，请刷新后重试。');
          }
          const context: EmbeddingMutationContext = { candidate: { ...candidate }, changes: impact.configurationChanges, impact };
          const preview = parseManagementWorkPreview(
            await mutationBoundary.request({
              pathId: configurationMutationPathIds.preview,
              body: { changes: impact.configurationChanges, expectedRuntimeRevision: runtimeRevision },
            }),
            configurationMutationPathIds.apply,
            context,
          );
          return {
            ...preview,
            summary: {
              ...preview.summary,
              title: '切换 Knowledge Embedding Profile？',
              items: [
                `候选：${impact.probe.provider} / ${impact.probe.model || '无向量模型'} / ${impact.probe.dimensions} 维`,
                `影响 ${impact.affectedBaseCount} 个知识库、${impact.affectedDocumentCount} 个文档、${impact.affectedChunkCount} 个片段`,
                impact.requiresWorkerRestart ? '保存后需要重启 Knowledge Worker' : 'Worker 配置 fingerprint 不变',
                impact.requiresRebuild ? '新 Profile 生效前必须逐库重建向量索引' : '当前没有需要重建的文档',
              ],
              risk: 'R2',
            },
          };
        }}
        onRollback={async (receipt, preview) => parseManagementWorkReceipt(
          await mutationBoundary.request({
            pathId: configurationMutationPathIds.rollback,
            body: { receiptId: receipt.receiptId, rollbackToken: receipt.rollbackToken, payloadSha256: receipt.payloadSha256, confirmText: 'rollback' },
          }),
          configurationMutationPathIds.rollback,
          preview.payloadSha256,
        )}
        onRolledBack={() => void refreshAuthoritativeState()}
        risk="R2"
        title="切换 Embedding Profile"
      />
      <div className="knowledge-settings-fields knowledge-settings-fields--index">
        <Field htmlFor="knowledge-dense-provider" label="实际 Provider"><Input disabled id="knowledge-dense-provider" readOnly value={runtimeProvider || '未报告'} /></Field>
        <Field htmlFor="knowledge-dense-model" label="实际 Model / Fingerprint"><Input disabled id="knowledge-dense-model" readOnly value={fingerprint || runtimeModel || '未报告'} /></Field>
        <Field htmlFor="knowledge-dense-dimension" label="实际维度"><Input disabled id="knowledge-dense-dimension" readOnly value={dimensions ?? '未报告'} /></Field>
        <Field htmlFor="knowledge-vector-count" label="当前 fingerprint 向量"><Input disabled id="knowledge-vector-count" readOnly value={vectorCount ?? '未报告'} /></Field>
        <Field htmlFor="knowledge-index-revision" label="索引 revision"><Input disabled id="knowledge-index-revision" readOnly value={indexRevisionLabel(documents)} /></Field>
        <Field htmlFor="knowledge-config-revision" label="配置 revision"><Input disabled id="knowledge-config-revision" readOnly value={baseRevision} /></Field>
      </div>
      <InlineNotice title="生效判定" tone="info">只有 Worker fingerprint 与活动 Profile 一致，且当前 fingerprint 的向量覆盖全部片段，才显示“已生效”；配置保存成功不等于索引重建完成。</InlineNotice>
    </section>
  );
}

const embeddingProviderOptions = [
  { value: 'environment', label: '沿用环境配置' },
  { value: 'none', label: '关闭 Dense（仅关键词）' },
  { value: 'local-hash', label: 'Local Hash（基线）' },
  { value: 'sentence-transformers', label: 'Sentence Transformers' },
  { value: 'mlx-bert', label: 'MLX BERT' },
  { value: 'openai-compatible', label: 'OpenAI-compatible Embedding' },
];

function emptyEmbeddingCandidate(): KnowledgeEmbeddingCandidate {
  return { provider: 'environment', model: '', baseUrl: '', dimensions: 0, secretReference: '', queryPrefix: '', documentPrefix: '', denseBackend: 'sqlite-exact' };
}

function candidateFromEmbeddingState(state: KnowledgeEmbeddingProfileState): KnowledgeEmbeddingCandidate {
  if (state.profile.source === 'environment') return emptyEmbeddingCandidate();
  return {
    provider: state.profile.provider,
    model: state.profile.model,
    baseUrl: state.profile.baseUrl,
    dimensions: state.profile.dimensions,
    secretReference: state.profile.secretReference,
    queryPrefix: state.profile.queryPrefix,
    documentPrefix: state.profile.documentPrefix,
    denseBackend: state.profile.denseBackend,
  };
}

function embeddingCandidateError(candidate: KnowledgeEmbeddingCandidate): string {
  if (!Number.isInteger(candidate.dimensions) || candidate.dimensions < 0 || candidate.dimensions > 65_536) return '向量维度必须是 0–65536 的整数。';
  if (candidate.provider === 'local-hash' && candidate.dimensions < 8) return 'Local Hash 至少需要 8 维。';
  if (['sentence-transformers', 'mlx-bert', 'openai-compatible'].includes(candidate.provider) && !candidate.model.trim()) return '当前 Provider 必须填写模型 ID 或本机模型目录。';
  if (candidate.provider === 'openai-compatible') {
    try {
      const parsed = new URL(candidate.baseUrl);
      if (!['http:', 'https:'].includes(parsed.protocol)) return '兼容 API 地址必须使用 HTTP(S)。';
    } catch {
      return 'OpenAI-compatible Provider 必须填写有效的 HTTP(S) API 地址。';
    }
    if (candidate.secretReference && !/^[A-Z][A-Z0-9_]{2,127}$/u.test(candidate.secretReference)) return '密钥引用必须是大写环境变量名，页面不会保存明文密钥。';
  }
  return '';
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
            <Select id="knowledge-document-parser" onValueChange={(value) => setParser(asParserMode(value))} options={[{ value: 'auto', label: '自动选择' }, { value: 'builtin', label: '内置文本解析' }, { value: 'mineru', label: 'MinerU OCR / 版面解析' }]} value={parser} />
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

function asDetailTab(value: string): DetailTab { return ['viewer', 'search', 'graph', 'jobs', 'settings'].includes(value) ? value as DetailTab : 'materials'; }
function asParserMode(value: string): KnowledgeParserMode { return value === 'builtin' ? value : value === 'mineru' || value === 'mineru_local_http' ? 'mineru' : 'auto'; }
function asChunkingStrategy(value: string): KnowledgeChunkingConfig['strategy'] { return ['general', 'markdown', 'book', 'qa', 'laws', 'separator', 'fixed'].includes(value) ? value as KnowledgeChunkingConfig['strategy'] : 'markdown'; }
function asRetrievalMode(value: string): KnowledgeRetrievalConfig['mode'] { return value === 'dense' || value === 'lexical' ? value : 'hybrid'; }
function retrievalModeLabel(value: KnowledgeRetrievalConfig['mode']): string { return value === 'dense' ? '向量检索' : value === 'lexical' ? '关键词检索' : '混合检索'; }
function equalConfig(left: object, right: object): boolean { return JSON.stringify(left) === JSON.stringify(right); }
function parserLabel(value: KnowledgeParserMode): string { return value === 'builtin' ? '内置' : value === 'mineru' ? 'MinerU' : '自动'; }
function scorePoints(value: number | null): string { return value === null ? '未提供' : String(Math.round(value <= 1 ? value * 100 : value)); }
function retrievalEvidenceLabel(hit: KnowledgeSearchHit): string {
  const mode = hit.diagnostics.effectiveMode === 'hybrid' ? '混合检索' : hit.diagnostics.effectiveMode === 'lexical' ? '关键词检索' : hit.diagnostics.effectiveMode === 'dense' ? '向量检索' : '检索服务未报告';
  const ranks = [
    hit.diagnostics.lexicalRank === null ? '' : `关键词候选第 ${hit.diagnostics.lexicalRank}`,
    hit.diagnostics.denseRank === null ? '' : `向量候选第 ${hit.diagnostics.denseRank}`,
    hit.diagnostics.graphRank === null ? '' : `图谱候选第 ${hit.diagnostics.graphRank}`,
  ].filter(Boolean);
  const matches = hit.diagnostics.graphMatches.length ? ` · 关联 ${hit.diagnostics.graphMatches.slice(0, 3).join('、')}` : '';
  return ranks.length ? `${mode} · ${ranks.join(' · ')}${matches}` : mode;
}
function citationLabel(hit: KnowledgeSearchHit): string { if (hit.page !== null) return `第 ${hit.page} 页`; if (hit.lineStart !== null) return hit.lineEnd && hit.lineEnd !== hit.lineStart ? `第 ${hit.lineStart}-${hit.lineEnd} 行` : `第 ${hit.lineStart} 行`; return '文档片段'; }
function uploadItemId(file: File, index: number): string { return `upload-${Date.now()}-${index}-${file.name}-${file.size}`; }
function replaceUploadItem(items: KnowledgeUploadItem[], id: string, patch: Partial<KnowledgeUploadItem>): KnowledgeUploadItem[] { return items.map((item) => item.id === id ? { ...item, ...patch } : item); }
function indexRevisionLabel(documents: readonly KnowledgeDocument[]): string {
  const revisions = [...new Set(documents.map((document) => document.indexedConfigRevision).filter((value) => value > 0))].sort((left, right) => left - right);
  if (!revisions.length) return '未建立';
  return revisions.length === 1 ? String(revisions[0]) : `${revisions[0]}–${revisions.at(-1)}`;
}
