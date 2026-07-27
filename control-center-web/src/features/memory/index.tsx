import {
  BookOpen,
  ChevronRight,
  EyeOff,
  Fingerprint,
  GitBranch,
  RefreshCw,
  RotateCcw,
  Search,
} from 'lucide-react';
import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useMemo, useState, type FormEvent } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
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
  Input,
  SegmentedControl,
  Select,
  Switch,
  Tabs as ViewTabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  TextArea,
} from '@/components/primitives';
import { useControlTransport } from '@/app/control-transport';
import { useProductIdentity } from '@/features/identity/product-identity';
import {
  memoryBookArchivePathIds,
  memoryQueryKeys,
  useMemoryBookArchiveBoundary,
  useMemoryQueries,
  type MemoryKind,
} from './api';
import { MemoryRelations } from './MemoryRelations';
import { MemoryCurationWorkbench } from './MemoryCurationWorkbench';
import { ActivityTimeline } from './ActivityTimeline';
import { MemorySystemOverview } from './MemorySystemOverview';
import { RoleBookLayer } from './RoleBookLayer';
import {
  MemoryReferenceDialog,
  type MemoryReferenceSelection,
} from './MemoryReferenceDialog';
import {
  InlineNotice,
  ManagementPage,
  ManagementSection,
  OperationalList,
  PaginationBar,
  QueryState,
  StatusBadge,
  arrayRecords,
  asRecord,
  numberValue,
  stringValue,
} from '@/features/overview/management-ui';
import {
  ManagementMutationWorkflow,
  parseManagementWorkPreview,
  parseManagementWorkReceipt,
} from '@/features/overview/management-mutation';
import type { JsonValue } from '@/platform/transport';
import './memory.css';

type MemoryLayer = 'evidence' | 'atoms' | 'books';
type MemoryRouteLayer = MemoryLayer | 'timelines' | 'role-books';
type MemoryView = 'catalog' | 'roleBooks' | 'timeline' | 'relations' | 'organize';

const layers = [
  { value: 'evidence', label: '记忆来源' },
  { value: 'atoms', label: '关于我的事实' },
  { value: 'books', label: '长期主题' },
] as const;

function defaultMemoryStatus(kind: MemoryKind): string {
  if (kind === 'phrases') return 'approved';
  if (kind === 'evidence') return '';
  return 'active';
}

export function MemoryFeature() {
  const queryClient = useQueryClient();
  const identity = useProductIdentity();
  const location = useLocation();
  const navigate = useNavigate();
  const routeSelection = useMemo(() => memoryRouteSelection(location.search), [location.search]);
  const [view, setView] = useState<MemoryView>(
    routeSelection.view,
  );
  const [layer, setLayer] = useState<MemoryLayer>(routeSelection.layer);
  const kind: MemoryKind = layer;
  const [draftQuery, setDraftQuery] = useState('');
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState(defaultMemoryStatus(kind));
  const [ownerKey, setOwnerKey] = useState('');
  const [selectedId, setSelectedId] = useState(routeSelection.id);
  const [editOpen, setEditOpen] = useState(false);
  const [reference, setReference] = useState<MemoryReferenceSelection | null>(
    routeSelection.reference,
  );
  const selectedOwner = parseOwnerKey(ownerKey);
  const { pages, summary } = useMemoryQueries(
    kind,
    query,
    status,
    selectedOwner.ownerKind,
    selectedOwner.ownerId,
    view === 'catalog',
  );
  const archiveBoundary = useMemoryBookArchiveBoundary();
  const summaryPayload = asRecord(summary.data);
  const ownerOptions = useMemo(() => [
    { value: '', label: '全部归属' },
    ...arrayRecords(summaryPayload.owners).map((owner) => {
      const ownerKind = stringValue(owner.ownerKind);
      const ownerId = stringValue(owner.ownerId);
      return {
        value: encodeOwnerKey(ownerKind, ownerId),
        label: `${ownerLabel(ownerKind, ownerId)} · ${numberValue(owner.itemCount)} 项`,
      };
    }),
  ], [summaryPayload.owners]);
  const rows = useMemo(() =>
    (pages.data?.pages ?? []).flatMap((page) => arrayRecords(asRecord(page).items)).map(normalizeMemoryRow),
  [pages.data]);
  const selected = rows.find((row) => stringValue(row.id) === selectedId);
  const selectedStatus = stringValue(selected?.status);
  const selectedType = stringValue(selected?.type);
  const archiveDraft = {
    bookId: selectedId,
    archived: selectedStatus !== 'archived',
    reason: selectedStatus === 'archived' ? 'control_center_restore' : 'control_center_archive',
  };
  const archiveAvailability = archiveBoundary.availability(archiveBlockedReason());
  const runtimeRevision = numberValue(summaryPayload.runtimeRevision);
  const error = ((view === 'catalog' ? pages.error : null) ?? summary.error) as Error | null;
  const pending = summary.isPending || (view === 'catalog' && pages.isPending);
  const refresh = () => queryClient.refetchQueries({
    queryKey: memoryQueryKeys.root,
    type: 'active',
  });

  useEffect(() => {
    const next = memoryRouteSelection(location.search);
    setView(next.view);
    if (next.view === 'catalog') {
      setLayer(next.layer);
      setStatus(defaultMemoryStatus(next.layer));
      setSelectedId(next.id);
      setEditOpen(false);
    }
    setReference(next.reference);
  }, [location.search]);

  return (
    <ManagementPage
      actions={<Button leadingIcon={<RefreshCw size={15} />} loading={summary.isRefetching || pages.isRefetching} onClick={refresh} size="small">刷新</Button>}
      description={`看看${identity.assistantName}记住了什么、为什么这样记，以及哪些内容需要你确认。`}
      eyebrow="关于我"
      routeId="memory"
      title="我的记忆"
    >
      <QueryState error={error} isPending={pending} onRetry={refresh}>
        <MemorySystemOverview
          onOpenLayer={(next) => {
            if (next === 'roleBooks') openView('roleBooks');
            else openCatalogLayer(next);
          }}
          onOpenOrganize={() => setView('organize')}
          onOpenRelations={() => openView('relations')}
          onOpenTimeline={() => openView('timeline')}
          summary={summaryPayload}
        />

        <ViewTabs
          className="memory-view-tabs"
          onValueChange={(next) => openView(normalizeMemoryView(next))}
          value={view}
        >
          <TabsList aria-label="记忆视图">
            <TabsTrigger value="catalog">记忆</TabsTrigger>
            <TabsTrigger value="roleBooks">伙伴记忆</TabsTrigger>
            <TabsTrigger value="timeline">时间线</TabsTrigger>
            <TabsTrigger value="relations">关系图</TabsTrigger>
            <TabsTrigger value="organize">让{identity.assistantName}整理</TabsTrigger>
          </TabsList>
          <TabsContent value="catalog">
            <ManagementSection
              title="记忆如何形成"
              description="先保留来源，再整理成当前有效的事实，最后归入长期主题。应用、标签和分组只帮助查找，不会被当成记忆本身。"
            >
              <div className="mgmt-stack">
                <SegmentedControl
                  aria-label="事实链层级"
                  items={layers}
                  onValueChange={(next) => openCatalogLayer(next as MemoryLayer)}
                  value={layer}
                />
                <div className="mgmt-filter-row memory-catalog-filters">
                  <Field className="memory-catalog-filters__query" htmlFor="memory-search" label="搜索">
                    <Input id="memory-search" onChange={(event) => setDraftQuery(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') runSearch(); }} placeholder="标题、正文或标签" value={draftQuery} />
                  </Field>
                  <Button className="memory-catalog-filters__submit" leadingIcon={<Search size={14} />} onClick={runSearch} size="small">搜索</Button>
                  <Field className="memory-catalog-filters__status" htmlFor="memory-status-filter" label="状态">
                    <Select
                      id="memory-status-filter"
                      onValueChange={(value) => {
                        setStatus(value);
                        setSelectedId('');
                        setEditOpen(false);
                      }}
                      options={memoryStatusOptions(kind)}
                      value={status}
                    />
                  </Field>
                  {ownerAwareKind(kind) ? (
                    <Field className="memory-catalog-filters__owner" htmlFor="memory-owner-filter" label="归属">
                      <Select
                        id="memory-owner-filter"
                        onValueChange={(value) => {
                          setOwnerKey(value);
                          setSelectedId('');
                          setEditOpen(false);
                        }}
                        options={ownerOptions}
                        value={ownerKey}
                      />
                    </Field>
                  ) : null}
                </div>
              </div>
              <div className="memory-layer-workspace">
                <aside className="memory-layer-list" aria-label={`${kindLabel(kind)}目录`}>
                  {rows.length ? (
                    <>
                      <OperationalList items={rows.map((row) => {
                        const id = stringValue(row.id);
                        const rowStatus = stringValue(row.status, 'unknown');
                        return {
                          id,
                          title: stringValue(row.title, '未命名记忆'),
                          detail: stringValue(row.detail, '暂无摘要'),
                          meta: [
                            catalogSourceLabel(kind, row, identity.assistantName),
                            ownerLabel(stringValue(row.ownerKind), stringValue(row.ownerId)),
                          ].filter(Boolean).join(' · '),
                          status: <StatusBadge label={catalogStatusLabel(kind, rowStatus)} tone={catalogStatusTone(kind, rowStatus)} />,
                          onClick: () => {
                            setSelectedId(id);
                            setEditOpen(false);
                          },
                          selected: id === selectedId,
                        };
                      })} />
                      <PaginationBar count={rows.length} hasMore={pages.hasNextPage} isFetching={pages.isFetchingNextPage} onLoadMore={() => void pages.fetchNextPage()} />
                    </>
                  ) : (
                    <EmptyState description="当前筛选没有这一层的记录。" icon={Search} title="没有匹配结果" />
                  )}
                </aside>
                <div className="memory-layer-detail">
                  {selected ? (
                    <>
                      <MemoryCatalogDetail
                        assistantName={identity.assistantName}
                        kind={kind}
                        onOpenReference={(next) => setReference(next)}
                        row={selected}
                      />
                      <div className="memory-layer-actions">
                        {kind === 'evidence' ? (
                          <MemoryEvidenceDispositionAction
                            disabledReason={sourceDispositionBlockedReason()}
                            onChanged={refresh}
                            row={selected}
                          />
                        ) : (
                          <DirectMemoryEditAction
                            disabledReason={memoryEditBlockedReason()}
                            onClick={() => setEditOpen(true)}
                          />
                        )}
                        {kind === 'books' ? (
                          archiveAvailability.state === 'unsupported' ? (
                            <UnavailableMemoryAction
                              description="归档或恢复长期主题，并保留事实与来源关系。"
                              reason={archiveAvailability.reason || '安全归档暂未开放。'}
                              risk="R2"
                              title="管理长期主题"
                            />
                          ) : (
                            <ManagementMutationWorkflow
                              availability={archiveAvailability}
                              description={archiveDraft.archived
                                ? '归档长期主题，退出日常自动召回；事实和来源关系仍会保留。'
                                : '恢复长期主题，重新参与日常记忆召回。'}
                              draftKey={JSON.stringify(archiveDraft)}
                              mutationKey={['memory', 'mutation', 'archive']}
                              onApply={async (preview) => parseManagementWorkReceipt(
                                await archiveBoundary.request({
                                  pathId: memoryBookArchivePathIds.apply,
                                  body: {
                                    ...preview.context,
                                    expectedRuntimeRevision: preview.expectedRuntimeRevision,
                                    previewToken: preview.previewToken,
                                    payloadSha256: preview.payloadSha256,
                                    confirmText: preview.requiredConfirm,
                                  },
                                }),
                                memoryBookArchivePathIds.apply,
                                preview.payloadSha256,
                              )}
                              onApplied={() => refresh()}
                              onPreview={async () => parseManagementWorkPreview(
                                await archiveBoundary.request({
                                  pathId: memoryBookArchivePathIds.preview,
                                  body: { ...archiveDraft, expectedRuntimeRevision: runtimeRevision },
                                }),
                                memoryBookArchivePathIds.apply,
                                archiveDraft,
                              )}
                              onRollback={async (receipt, preview) => parseManagementWorkReceipt(
                                await archiveBoundary.request({
                                  pathId: memoryBookArchivePathIds.rollback,
                                  body: {
                                    receiptId: receipt.receiptId,
                                    rollbackToken: receipt.rollbackToken,
                                    payloadSha256: receipt.payloadSha256,
                                    confirmText: 'rollback',
                                  },
                                }),
                                memoryBookArchivePathIds.rollback,
                                preview.payloadSha256,
                              )}
                              onRolledBack={() => refresh()}
                              risk="R2"
                              title={archiveDraft.archived ? '归档长期主题' : '恢复长期主题'}
                            />
                          )
                        ) : null}
                      </div>
                    </>
                  ) : (
                    <EmptyState description="从左侧选择一项，查看正文、状态和证据来源。" icon={BookOpen} title="选择一条记录" />
                  )}
                </div>
              </div>
            </ManagementSection>
          </TabsContent>
          <TabsContent value="roleBooks">
            <RoleBookLayer
              enabled={view === 'roleBooks'}
              initialReferenceId={routeSelection.routeLayer === 'role-books' ? routeSelection.id : ''}
              onOpenGovernance={() => setView('organize')}
            />
          </TabsContent>
          <TabsContent value="relations">
            <MemoryRelations enabled={view === 'relations'} />
          </TabsContent>
          <TabsContent value="timeline">
            {view === 'timeline' ? <ActivityTimeline /> : null}
          </TabsContent>
          <TabsContent value="organize">
            <MemoryCurationWorkbench enabled={view === 'organize'} />
          </TabsContent>
        </ViewTabs>
        <MemoryEditDialog
          kind={kind}
          onOpenChange={setEditOpen}
          onSaved={refresh}
          open={editOpen && Boolean(selected)}
          row={selected}
        />
        {reference ? (
          <MemoryReferenceDialog
            {...reference}
            onOpenChange={(open) => {
              if (open) return;
              setReference(null);
              if (routeSelection.id) {
                navigate({ pathname: location.pathname, search: `?layer=${routeSelection.routeLayer}` }, { replace: true });
              }
            }}
          />
        ) : null}
      </QueryState>
    </ManagementPage>
  );

  function runSearch() {
    setSelectedId('');
    setEditOpen(false);
    setQuery(draftQuery.trim());
  }

  function openCatalogLayer(next: MemoryLayer) {
    setView('catalog');
    setLayer(next);
    setStatus(defaultMemoryStatus(next));
    setOwnerKey('');
    setSelectedId('');
    setEditOpen(false);
    setReference(null);
    navigate({ pathname: location.pathname, search: `?layer=${next}` }, { replace: true });
  }

  function openView(next: MemoryView) {
    setView(next);
    setEditOpen(false);
    setReference(null);
    if (next === 'catalog') {
      navigate({ pathname: location.pathname, search: `?layer=${layer}` }, { replace: true });
    } else if (next === 'timeline') {
      navigate({ pathname: location.pathname, search: '?layer=timelines' }, { replace: true });
    } else if (next === 'roleBooks') {
      navigate({ pathname: location.pathname, search: '?layer=role-books' }, { replace: true });
    }
  }

  function archiveBlockedReason(): string {
    if (!selected) return '先从上方目录中选择一项。';
    if (kind !== 'books') return '当前只有长期主题支持可回滚归档。';
    if (selectedType !== 'topic') return '只有长期主题可以手动归档。';
    if (!['active', 'approved', 'archived'].includes(selectedStatus)) {
      return '当前记忆状态不支持归档或恢复。';
    }
    return '';
  }

  function memoryEditBlockedReason(): string {
    if (!selected) return '先从上方目录中选择一项。';
    if (archiveBoundary.capabilities.isPending) return '正在确认本机记忆编辑能力。';
    if (archiveBoundary.capabilities.error) return '无法确认本机记忆编辑能力，请刷新后重试。';
    if (!archiveBoundary.capabilities.data?.routeIds.includes('memory.edit')) {
      return '当前服务尚未开放本机记忆编辑。';
    }
    return '';
  }

  function sourceDispositionBlockedReason(): string {
    if (!selected) return '先从上方目录中选择一条证据。';
    if (archiveBoundary.capabilities.isPending) return '正在确认本机记忆管理能力。';
    if (archiveBoundary.capabilities.error) return '无法确认本机记忆管理能力，请刷新后重试。';
    if (!archiveBoundary.capabilities.data?.routeIds.includes('memory.source.disposition')) {
      return '当前服务尚未开放证据遗忘与恢复。';
    }
    if (
      selectedStatus === 'not_for_memory'
      && selected.sensitive === true
    ) {
      return '敏感输入不能直接恢复；请改为创建一条不含凭据的明确记忆。';
    }
    if (selectedStatus === 'consolidated') {
      return '这条来源已经写入长期记忆，请改为编辑或归档对应的长期主题。';
    }
    if (!['pending', 'remember', 'needs_review', 'not_for_memory', 'expired'].includes(selectedStatus)) {
      return '当前证据状态不支持遗忘或恢复。';
    }
    return '';
  }
}

interface MemoryRouteSelection {
  id: string;
  layer: MemoryLayer;
  reference: MemoryReferenceSelection | null;
  routeLayer: MemoryRouteLayer;
  view: MemoryView;
}

function memoryRouteSelection(search: string): MemoryRouteSelection {
  const params = new URLSearchParams(search);
  const rawLayer = params.get('layer') ?? 'atoms';
  const routeLayer: MemoryRouteLayer = isMemoryRouteLayer(rawLayer) ? rawLayer : 'atoms';
  const id = (params.get('id') ?? '').trim().slice(0, 500);
  const view: MemoryView = routeLayer === 'timelines'
    ? 'timeline'
    : routeLayer === 'role-books'
      ? 'roleBooks'
      : 'catalog';
  const layer: MemoryLayer = routeLayer === 'evidence' || routeLayer === 'books'
    ? routeLayer
    : 'atoms';
  return {
    id,
    layer,
    reference: id ? {
      kind: referenceKindForRoute(routeLayer, id),
      referenceId: id,
    } : null,
    routeLayer,
    view,
  };
}

function isMemoryRouteLayer(value: string): value is MemoryRouteLayer {
  return ['evidence', 'atoms', 'books', 'timelines', 'role-books'].includes(value);
}

function referenceKindForRoute(layer: MemoryRouteLayer, id: string): MemoryReferenceSelection['kind'] {
  if (layer === 'atoms') return 'atom';
  if (layer === 'books') return 'book';
  if (layer === 'timelines') return 'timeline';
  if (layer === 'role-books') return 'role_book_revision';
  return /^\d+$/u.test(id) || id.startsWith('event:') || id.startsWith('input-memory:')
    ? 'event'
    : 'evidence';
}

function normalizeMemoryView(value: string): MemoryView {
  return value === 'roleBooks' || value === 'timeline' || value === 'relations' || value === 'organize'
    ? value
    : 'catalog';
}

function normalizeMemoryRow(item: Record<string, unknown>): Record<string, unknown> {
  const source = asRecord(item.source);
  return {
    id: item.id ?? item.bookId ?? item.atomId ?? item.tagId ?? item.groupId ?? item.phraseId,
    title: item.title ?? item.name ?? item.label ?? item.tag ?? item.text ?? item.phrase ?? item.reason ?? item.value,
    detail: item.detail ?? item.summary ?? item.note ?? item.description ?? item.text ?? item.reason ?? item.value ?? item.aliases,
    source: typeof item.source === 'string'
      ? item.source
      : source.type ?? source.kind ?? source.sourceType ?? item.sourceType ?? item.project ?? item.kind,
    sourceRecord: item.source,
    ref: item.ref,
    status: item.status ?? (item.active === false ? 'inactive' : 'active'),
    type: item.type ?? item.bookType ?? item.kind,
    text: item.text ?? item.textPreview ?? item.phrase,
    summary: item.summary,
    note: item.note,
    description: item.description,
    reason: item.reason,
    active: item.active,
    color: item.color ?? item.color_token,
    tags: safeCatalogStringList(item.tags),
    aliases: safeCatalogStringList(item.aliases),
    ownerKind: item.ownerKind ?? item.owner_kind,
    ownerId: item.ownerId ?? item.owner_id,
    disposition: item.disposition,
    dispositionReason: item.dispositionReason,
    trustClass: item.trustClass,
    sensitive: item.sensitive,
    canForget: item.canForget,
    canRestore: item.canRestore,
    bundleId: item.bundleId ?? item.app,
    eventCount: item.eventCount,
    finalizedSegmentCount: item.finalizedSegmentCount,
    contextGroupCount: item.contextGroupCount,
    atomCount: item.atomCount,
    bookCount: item.bookCount,
    confidence: item.confidence,
    qualityScore: item.qualityScore,
    createdAtMs: item.createdAtMs ?? item.created_at_ms,
    latestAtMs: item.latestAtMs,
    updatedAtMs: item.updatedAtMs ?? item.updated_at_ms,
    evidenceRefs: item.evidenceRefs ?? item.sourceRefs ?? item.references ?? item.sourceEventIds,
    memories: item.memories,
  };
}

function safeCatalogStringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    if (typeof item !== 'string') return [];
    const text = item.trim().slice(0, 64);
    return text ? [text] : [];
  }).slice(0, 64);
}

function MemoryCatalogDetail({
  assistantName,
  kind,
  onOpenReference,
  row,
}: {
  assistantName: string;
  kind: MemoryKind;
  onOpenReference: (reference: MemoryReferenceSelection) => void;
  row: Record<string, unknown>;
}) {
  const values = Array.isArray(row.tags)
    ? safeCatalogStringList(row.tags)
    : Array.isArray(row.aliases)
      ? safeCatalogStringList(row.aliases)
      : [];
  const references = catalogReferences(row, kind);
  const rootReference = catalogRootReference(row, kind);
  const status = stringValue(row.status);
  const forgotten = status === 'not_for_memory' || status === 'expired';
  const redacted = row.sensitive === true;
  const auditOnly = kind === 'evidence' && isRawConversationEvidence(
    stringValue(row.type, stringValue(row.detail)),
  );
  return (
    <section className="memory-catalog-detail" aria-label={`${stringValue(row.title, '记忆')} 详情`}>
      <div className="memory-catalog-detail__identity">
        <span><Fingerprint aria-hidden="true" size={16} />{kindLabel(kind)}</span>
        <h3>{stringValue(row.title, '未命名记忆')}</h3>
        <p>{redacted ? '正文因为隐私策略已隐藏，只保留可审计的来源和状态。' : stringValue(row.detail, '暂无摘要')}</p>
      </div>
      <dl>
        <div><dt>状态</dt><dd>{catalogStatusLabel(kind, status)}</dd></div>
        <div><dt>来源</dt><dd>{catalogSourceLabel(kind, row, assistantName)}</dd></div>
        {stringValue(row.ownerKind) ? (
          <div><dt>归属</dt><dd>{ownerLabel(stringValue(row.ownerKind), stringValue(row.ownerId))}</dd></div>
        ) : null}
        <div><dt>更新</dt><dd>{formatUpdatedAt(numberValue(row.updatedAtMs))}</dd></div>
        <div><dt>索引关系</dt><dd>{values.length ? `${values.length} 项` : '暂无'}</dd></div>
        <div><dt>来源引用</dt><dd>{references.length ? `${references.length} 条` : '查看完整链路'}</dd></div>
      </dl>
      {values.length ? <div className="memory-catalog-detail__tags">{values.slice(0, 8).map((value) => <span key={value}>{value}</span>)}</div> : null}
      {redacted ? (
        <InlineNotice title="敏感内容已脱敏" tone="warning">
          此处不会显示原文。来源标识、处理时间和治理状态仍可用于审计。
        </InlineNotice>
      ) : auditOnly ? (
        <InlineNotice title="原始对话仅用于审计" tone="info">
          这条记录不会直接成为伙伴记忆或关于你的长期事实；只有明确提出的记忆草案，或空闲时生成的有界摘要，才会进入后续整理。
        </InlineNotice>
      ) : forgotten ? (
        <InlineNotice title="这条证据已退出记忆召回" tone="info">
          遗忘不会伪造删除历史：正文不再参与整理和召回，审计引用仍然保留，并可在允许时恢复。
        </InlineNotice>
      ) : null}
      <div className="memory-lineage-panel">
        <div>
          <span><GitBranch aria-hidden="true" size={15} />证据链</span>
          <strong>{references.length ? `${references.length} 条直接引用` : '从稳定引用读取完整来源'}</strong>
          <p>点击引用会进入统一查看器；查看器支持继续向下展开，并阻止循环或异常深链。</p>
        </div>
        {references.length ? (
          <div className="memory-reference-list" aria-label="直接来源引用">
            {references.map((reference) => (
              <button key={`${reference.kind}:${reference.referenceId}`} onClick={() => onOpenReference(reference)} type="button">
                <Fingerprint aria-hidden="true" size={14} />
                <span>{reference.label || referenceKindLabel(reference.kind)}</span>
                <ChevronRight aria-hidden="true" size={14} />
              </button>
            ))}
          </div>
        ) : null}
        {rootReference ? (
          <Button
            leadingIcon={<GitBranch size={14} />}
            onClick={() => onOpenReference(rootReference)}
            size="small"
            variant="quiet"
          >
            查看完整来源
          </Button>
        ) : null}
      </div>
    </section>
  );
}

function catalogRootReference(
  row: Record<string, unknown>,
  kind: MemoryKind,
): MemoryReferenceSelection | null {
  const canonicalRef = asRecord(row.ref);
  const referenceId = stringValue(
    canonicalRef.referenceId,
    stringValue(canonicalRef.refId, stringValue(canonicalRef.id, stringValue(row.id))),
  );
  if (!referenceId) return null;
  const explicitKind = stringValue(
    canonicalRef.kind,
    stringValue(canonicalRef.referenceKind, stringValue(canonicalRef.type)),
  );
  if (kind === 'atoms') return {
    kind: normalizeCatalogReferenceKind(explicitKind, referenceId, 'atom'),
    referenceId,
    label: stringValue(row.title),
  };
  if (kind === 'books') return {
    kind: normalizeCatalogReferenceKind(explicitKind, referenceId, 'book'),
    referenceId,
    label: stringValue(row.title),
  };
  if (kind === 'evidence') {
    return {
      kind: normalizeCatalogReferenceKind(
        explicitKind,
        referenceId,
        /^\d+$/u.test(referenceId) || referenceId.startsWith('input-memory:') ? 'event' : 'evidence',
      ),
      referenceId,
      label: stringValue(row.title),
    };
  }
  return null;
}

function catalogReferences(
  row: Record<string, unknown>,
  kind: MemoryKind,
): MemoryReferenceSelection[] {
  const candidates = [
    ...(Array.isArray(row.evidenceRefs) ? row.evidenceRefs : []),
    ...(Array.isArray(row.memories) ? row.memories : []),
  ];
  const fallback: MemoryReferenceSelection['kind'] = kind === 'books' ? 'atom' : 'event';
  const seen = new Set<string>();
  return candidates.flatMap((value): MemoryReferenceSelection[] => {
    const item = asRecord(value);
    const referenceId = typeof value === 'string' || typeof value === 'number'
      ? String(value)
      : stringValue(
        item.referenceId,
        stringValue(item.refId, stringValue(item.id, stringValue(item.sourceId))),
      );
    if (!referenceId) return [];
    const referenceKind = normalizeCatalogReferenceKind(
      stringValue(
        item.kind,
        stringValue(item.referenceKind, stringValue(item.type, stringValue(item.sourceType))),
      ),
      referenceId,
      fallback,
    );
    const key = `${referenceKind}:${referenceId}`;
    if (seen.has(key)) return [];
    seen.add(key);
    return [{
      kind: referenceKind,
      referenceId,
      label: stringValue(item.label, stringValue(item.title, stringValue(item.textPreview, stringValue(item.text)))),
    }];
  }).slice(0, 40);
}

function normalizeCatalogReferenceKind(
  value: string,
  referenceId: string,
  fallback: MemoryReferenceSelection['kind'],
): MemoryReferenceSelection['kind'] {
  const normalized = value.toLocaleLowerCase('en-US').replaceAll('-', '_');
  if (normalized.includes('role_book')) return 'role_book_revision';
  if (normalized.includes('timeline')) return 'timeline';
  if (normalized.includes('book')) return 'book';
  if (normalized.includes('atom') || normalized === 'fact') return 'atom';
  if (normalized.includes('evidence')) return 'evidence';
  if (normalized.includes('event')) return 'event';
  if (referenceId.startsWith('atom:')) return 'atom';
  if (referenceId.startsWith('book:')) return 'book';
  if (referenceId.startsWith('timeline:')) return 'timeline';
  if (referenceId.startsWith('evidence:')) return 'evidence';
  return fallback;
}

function referenceKindLabel(kind: MemoryReferenceSelection['kind']): string {
  return ({
    event: '原始事件',
    evidence: '对话证据与审计',
    atom: '关于我的事实',
    book: '长期主题',
    timeline: '活动时间线',
    role_book_revision: '伙伴记忆版本',
  } as const)[kind];
}

interface MemoryEditDraft {
  title: string;
  text: string;
  summary: string;
  note: string;
  description: string;
  tags: string;
  aliases: string;
  type: string;
  color: string;
  reason: string;
  active: boolean;
}

function DirectMemoryEditAction({
  disabledReason,
  onClick,
}: {
  disabledReason: string;
  onClick: () => void;
}) {
  return (
    <div className="mgmt-workflow" data-availability={disabledReason ? 'blocked' : 'available'} data-stage="idle">
      <div className="mgmt-workflow__heading">
        <div>
          <span className="mgmt-workflow__risk">本机写入</span>
          <strong>编辑内容</strong>
          <p>直接编辑当前选中的记忆，不经过 Agent 转述。</p>
        </div>
        <Button disabled={Boolean(disabledReason)} onClick={onClick} size="small">编辑</Button>
      </div>
      <p className="memory-action-unavailable">{disabledReason || '保存只会作用于当前选择的这项记忆。'}</p>
    </div>
  );
}

function MemoryEvidenceDispositionAction({
  disabledReason,
  onChanged,
  row,
}: {
  disabledReason: string;
  onChanged: () => Promise<unknown> | void;
  row: Record<string, unknown> | undefined;
}) {
  const transport = useControlTransport();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const sourceId = stringValue(row?.id);
  const status = stringValue(row?.status);
  const restoring = status === 'not_for_memory' || status === 'expired';
  const action = restoring ? '恢复证据' : '遗忘证据';
  const disposition = restoring ? 'pending' : 'not_for_memory';

  async function submit() {
    if (!sourceId || disabledReason) return;
    setSaving(true);
    setError('');
    try {
      const result = asRecord(await transport.request({
        pathId: 'memory.source.disposition',
        body: { sourceId, disposition },
      }));
      if (result.ok !== true) throw new Error('memory source disposition rejected');
      await onChanged();
    } catch {
      setError('操作失败，证据状态没有改变。');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="mgmt-workflow" data-availability={disabledReason ? 'blocked' : 'available'} data-stage="idle">
      <div className="mgmt-workflow__heading">
        <div>
          <span className="mgmt-workflow__risk">可回滚</span>
          <strong>{action}</strong>
          <p>
            {restoring
              ? '重新放回每日整理队列；原始证据仍不会直接进入检索。'
              : '从长期记忆整理中排除这条噪声，原始输入和审计记录仍保留。'}
          </p>
        </div>
        <Button
          disabled={Boolean(disabledReason)}
          leadingIcon={restoring ? <RotateCcw size={14} /> : <EyeOff size={14} />}
          loading={saving}
          onClick={() => void submit()}
          size="small"
        >
          {restoring ? '恢复' : '遗忘'}
        </Button>
      </div>
      <p className="memory-action-unavailable">
        {error || disabledReason || (restoring ? '恢复后会在下一次整理时重新判断。' : '之后可以从证据目录中恢复。')}
      </p>
    </div>
  );
}

function MemoryEditDialog({
  kind,
  onOpenChange,
  onSaved,
  open,
  row,
}: {
  kind: MemoryKind;
  onOpenChange: (open: boolean) => void;
  onSaved: () => Promise<unknown> | void;
  open: boolean;
  row: Record<string, unknown> | undefined;
}) {
  const transport = useControlTransport();
  const identity = stringValue(row?.id);
  const [draft, setDraft] = useState<MemoryEditDraft>(() => memoryEditDraft(kind, row));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!open) return;
    setDraft(memoryEditDraft(kind, row));
    setError('');
  }, [identity, kind, open, row]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const validation = memoryEditValidation(kind, draft);
    if (validation) {
      setError(validation);
      return;
    }
    if (!identity) {
      setError('这项记忆已经不可用，请关闭窗口后重新选择。');
      return;
    }
    setSaving(true);
    setError('');
    try {
      const result = asRecord(await transport.request({
        pathId: 'memory.edit',
        body: memoryEditBody(kind, identity, draft),
      }));
      if (result.ok !== true) throw new Error('memory edit rejected');
      try {
        await onSaved();
      } catch {
        // The write succeeded; a later manual refresh can recover a failed read.
      }
      onOpenChange(false);
    } catch {
      setError('保存失败。草稿已保留，请确认这项记忆仍然存在后重试。');
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(next) => { if (!saving) onOpenChange(next); }}>
      <DialogContent className="memory-edit-dialog">
        <DialogHeader>
          <DialogTitle>编辑{kindLabel(kind)}</DialogTitle>
          <DialogDescription>修改只会写入当前选中的本机记忆。</DialogDescription>
        </DialogHeader>
        <form className="memory-edit-form" id="memory-edit-form" onSubmit={(event) => void submit(event)}>
          <MemoryEditFields draft={draft} kind={kind} setDraft={setDraft} />
          {error ? <p className="memory-edit-error" role="alert">{error}</p> : null}
        </form>
        <DialogFooter>
          <Button disabled={saving} onClick={() => onOpenChange(false)} variant="quiet">取消</Button>
          <Button form="memory-edit-form" loading={saving} type="submit" variant="primary">保存</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function MemoryEditFields({
  draft,
  kind,
  setDraft,
}: {
  draft: MemoryEditDraft;
  kind: MemoryKind;
  setDraft: (draft: MemoryEditDraft) => void;
}) {
  const update = <Key extends keyof MemoryEditDraft>(key: Key, value: MemoryEditDraft[Key]) => {
    setDraft({ ...draft, [key]: value });
  };
  const colorField = (
    <Field htmlFor="memory-edit-color" label="颜色">
      <Select id="memory-edit-color" onValueChange={(value) => update('color', value)} options={[
        { value: 'blue', label: '蓝色' },
        { value: 'teal', label: '青色' },
        { value: 'green', label: '绿色' },
        { value: 'orange', label: '橙色' },
        { value: 'pink', label: '粉色' },
        { value: 'purple', label: '紫色' },
        { value: 'gray', label: '灰色' },
      ]} value={draft.color} />
    </Field>
  );

  if (kind === 'apps') return null;

  if (kind === 'books') {
    return <>
      <Field htmlFor="memory-edit-title" label="标题" required><Input id="memory-edit-title" maxLength={240} onChange={(event) => update('title', event.target.value)} value={draft.title} /></Field>
      <Field htmlFor="memory-edit-summary" label="摘要"><TextArea id="memory-edit-summary" maxLength={4_000} onChange={(event) => update('summary', event.target.value)} rows={4} value={draft.summary} /></Field>
      <ListField id="memory-edit-tags" label="标签" onChange={(value) => update('tags', value)} value={draft.tags} />
    </>;
  }
  if (kind === 'atoms') {
    return <>
      <Field htmlFor="memory-edit-text" label="正文" required><TextArea id="memory-edit-text" maxLength={8_000} onChange={(event) => update('text', event.target.value)} rows={5} value={draft.text} /></Field>
      <ListField id="memory-edit-tags" label="标签" onChange={(value) => update('tags', value)} value={draft.tags} />
    </>;
  }
  if (kind === 'tags') {
    return <>
      <Field htmlFor="memory-edit-title" label="标签名" required><Input id="memory-edit-title" maxLength={120} onChange={(event) => update('title', event.target.value)} value={draft.title} /></Field>
      <Field htmlFor="memory-edit-description" label="说明"><TextArea id="memory-edit-description" maxLength={2_000} onChange={(event) => update('description', event.target.value)} rows={3} value={draft.description} /></Field>
      <div className="memory-edit-form__split">
        <Field htmlFor="memory-edit-type" label="类型"><Input id="memory-edit-type" maxLength={64} onChange={(event) => update('type', event.target.value)} value={draft.type} /></Field>
        {colorField}
      </div>
      <ListField id="memory-edit-aliases" label="别名" onChange={(value) => update('aliases', value)} value={draft.aliases} />
    </>;
  }
  if (kind === 'phrases') {
    return <Field htmlFor="memory-edit-text" label="短语" required><TextArea id="memory-edit-text" maxLength={2_000} onChange={(event) => update('text', event.target.value)} rows={4} value={draft.text} /></Field>;
  }
  if (kind === 'groups') {
    return <>
      <Field htmlFor="memory-edit-title" label="名称"><Input id="memory-edit-title" maxLength={240} onChange={(event) => update('title', event.target.value)} value={draft.title} /></Field>
      <Field htmlFor="memory-edit-note" label="说明"><TextArea id="memory-edit-note" maxLength={4_000} onChange={(event) => update('note', event.target.value)} rows={4} value={draft.note} /></Field>
      {colorField}
    </>;
  }
  return <>
    <Field htmlFor="memory-edit-reason" label="原因" required><TextArea id="memory-edit-reason" maxLength={2_000} onChange={(event) => update('reason', event.target.value)} rows={4} value={draft.reason} /></Field>
    <Switch checked={draft.active} description="关闭后，这条负反馈将不再参与过滤。" label="启用这条负反馈" onCheckedChange={(checked) => update('active', checked)} />
  </>;
}

function ListField({ id, label, onChange, value }: { id: string; label: string; onChange: (value: string) => void; value: string }) {
  return <Field description="用逗号或换行分隔" htmlFor={id} label={label}><TextArea id={id} maxLength={4_000} onChange={(event) => onChange(event.target.value)} rows={3} value={value} /></Field>;
}

function memoryEditDraft(kind: MemoryKind, row: Record<string, unknown> | undefined): MemoryEditDraft {
  const item = row ?? {};
  return {
    title: stringValue(item.title),
    text: stringValue(item.text),
    summary: stringValue(item.summary),
    note: stringValue(item.note),
    description: stringValue(item.description),
    tags: safeCatalogStringList(item.tags).join('，'),
    aliases: safeCatalogStringList(item.aliases).join('，'),
    type: stringValue(item.type, kind === 'tags' ? 'concept' : ''),
    color: stringValue(item.color, 'blue'),
    reason: stringValue(item.reason),
    active: item.active !== false && numberValue(item.active, 1) !== 0,
  };
}

function memoryEditBody(kind: MemoryKind, id: string, draft: MemoryEditDraft): Record<string, JsonValue> {
  if (kind === 'apps') return { kind, id };
  if (kind === 'books') return { kind, id, title: draft.title.trim(), summary: draft.summary.trim(), tags: splitList(draft.tags) };
  if (kind === 'atoms') return { kind, id, text: draft.text.trim(), tags: splitList(draft.tags) };
  if (kind === 'tags') return { kind, id, title: draft.title.trim(), description: draft.description.trim(), type: draft.type.trim() || 'concept', aliases: splitList(draft.aliases), color: draft.color };
  if (kind === 'phrases') return { kind, id, text: draft.text.trim() };
  if (kind === 'groups') return { kind, id, title: draft.title.trim(), note: draft.note.trim(), color: draft.color };
  return { kind, id, reason: draft.reason.trim(), active: draft.active };
}

function memoryEditValidation(kind: MemoryKind, draft: MemoryEditDraft): string {
  if (kind === 'apps') return '应用上下文由输入来源自动维护，不能手动编辑。';
  if ((kind === 'books' || kind === 'tags') && !draft.title.trim()) return '请填写标题。';
  if ((kind === 'atoms' || kind === 'phrases') && !draft.text.trim()) return '请填写内容。';
  if (kind === 'negative' && !draft.reason.trim()) return '请填写原因。';
  return '';
}

function splitList(value: string): string[] {
  return [...new Set(value.split(/[，,\n]/u).map((item) => item.trim()).filter(Boolean))].slice(0, 64);
}

function UnavailableMemoryAction({
  description,
  reason,
  risk,
  title,
}: {
  description: string;
  reason: string;
  risk: 'R1' | 'R2';
  title: string;
}) {
  return (
    <div className="mgmt-workflow" data-availability="unsupported" data-stage="idle">
      <div className="mgmt-workflow__heading">
        <div>
          <span className="mgmt-workflow__risk">{risk === 'R2' ? '谨慎确认' : '需要确认'}</span>
          <strong>{title}</strong>
          <p>{description}</p>
        </div>
        <Button disabled size="small">暂未开放</Button>
      </div>
      <p className="memory-action-unavailable">{reason}</p>
    </div>
  );
}

function kindLabel(kind: MemoryKind): string {
  return {
    apps: '应用',
    books: '长期主题',
    atoms: '关于我的事实',
    tags: '标签',
    phrases: '短语',
    evidence: '记忆来源与审计',
    groups: '分组',
    negative: '负反馈',
  }[kind];
}

function memoryStatusOptions(kind: MemoryKind) {
  if (kind === 'evidence') {
    return [
      { value: '', label: '全部' },
      { value: 'pending', label: '待整理' },
      { value: 'remember', label: '值得保留' },
      { value: 'needs_review', label: '待判断' },
      { value: 'not_for_memory', label: '已遗忘' },
      { value: 'consolidated', label: '已整理为记忆' },
      { value: 'expired', label: '已过期' },
    ];
  }
  return [
    { value: '', label: '全部' },
    { value: 'active', label: '使用中' },
    { value: 'approved', label: '已确认' },
    { value: 'archived', label: '已归档' },
    { value: 'hidden', label: '历史保留' },
    { value: 'superseded', label: '已合并' },
    { value: 'source_archive', label: '碎片证据' },
    { value: 'disabled', label: '已暂停' },
    { value: 'suppressed', label: '已抑制' },
  ];
}

function statusLabel(status: string): string {
  return {
    active: '使用中',
    approved: '已确认',
    archived: '已归档',
    hidden: '历史保留',
    superseded: '已合并',
    source_archive: '碎片证据',
    disabled: '已暂停',
    suppressed: '已抑制',
    inactive: '未启用',
    tombstoned: '已移除',
    pending: '待整理',
    remember: '值得保留',
    not_for_memory: '已遗忘',
    needs_review: '待判断',
    consolidated: '已整理为记忆',
    expired: '已过期',
  }[status] ?? '状态未知';
}

function catalogStatusLabel(kind: MemoryKind, status: string): string {
  if (kind === 'evidence' && status === 'active') return '审计保留';
  return statusLabel(status);
}

function catalogStatusTone(kind: MemoryKind, status: string): 'success' | 'warning' | 'danger' | 'info' | 'neutral' {
  if (kind === 'evidence' && status === 'active') return 'info';
  return statusTone(status);
}

function statusTone(status: string): 'success' | 'warning' | 'danger' | 'info' | 'neutral' {
  if (status === 'active' || status === 'approved' || status === 'consolidated') return 'success';
  if (status === 'archived' || status === 'hidden' || status === 'source_archive' || status === 'inactive' || status === 'not_for_memory' || status === 'expired') return 'info';
  if (status === 'disabled' || status === 'suppressed' || status === 'pending' || status === 'needs_review' || status === 'remember') return 'warning';
  if (status === 'tombstoned') return 'danger';
  return 'neutral';
}

function sourceLabel(source: string, assistantName: string): string {
  const normalized = source.toLocaleLowerCase('en-US');
  if (!normalized) return '本地记忆';
  if (normalized.includes('input_app')) return '应用上下文';
  if (normalized.includes('dsv4') || normalized.includes('deepseek')) return '智能整理';
  if (normalized.includes('user')) return '用户编辑';
  if (normalized.includes('import')) return '导入';
  if (normalized.includes('notion')) return 'Notion';
  if (normalized.includes('rime') || normalized.includes('input')) return '输入记录';
  if (normalized.includes('agent') || normalized.includes('pi')) return `${assistantName}整理`;
  if (normalized.includes('manual')) return '手动整理';
  if (normalized.includes('sqlite') || normalized.includes('memory_')) return '本地记忆';
  return '其他来源';
}

function catalogSourceLabel(kind: MemoryKind, row: Record<string, unknown>, assistantName: string): string {
  if (kind !== 'evidence') return sourceLabel(stringValue(row.source), assistantName);
  // Older/local page payloads sometimes expose source_kind as the detail
  // field. Keep the UI honest even while those rows are being migrated.
  const type = stringValue(row.type, stringValue(row.detail));
  if (isRawConversationEvidence(type)) return '对话审计';
  if (type === 'session_digest') return '空闲摘要';
  if (type === 'tool_receipt') return '已应用工具回执';
  if (type === 'work_receipt') return '已验收工作回执';
  return sourceLabel(stringValue(row.source), assistantName);
}

function isRawConversationEvidence(type: string): boolean {
  return type === 'user_message' || type === 'assistant_message' || type === 'room_event';
}

function ownerAwareKind(kind: MemoryKind): boolean {
  return kind === 'books' || kind === 'atoms' || kind === 'phrases' || kind === 'evidence';
}

function encodeOwnerKey(ownerKind: string, ownerId: string): string {
  return ownerKind && ownerId ? JSON.stringify([ownerKind, ownerId]) : '';
}

function parseOwnerKey(value: string): { ownerKind: string; ownerId: string } {
  try {
    const parsed: unknown = JSON.parse(value);
    if (
      Array.isArray(parsed)
      && parsed.length === 2
      && typeof parsed[0] === 'string'
      && typeof parsed[1] === 'string'
    ) {
      return { ownerKind: parsed[0], ownerId: parsed[1] };
    }
  } catch {
    // An empty or stale filter means "all owners".
  }
  return { ownerKind: '', ownerId: '' };
}

function ownerLabel(ownerKind: string, ownerId: string): string {
  if (!ownerKind || !ownerId) return '';
  if (ownerKind === 'user' && ownerId === 'default') return '个人记忆';
  if (ownerKind === 'shared' && ownerId === 'default') return '全局共享';
  if (ownerKind === 'shared') return `项目共享 · ${ownerId}`;
  if (ownerKind === 'agent') return `角色 · ${ownerId}`;
  if (ownerKind === 'session') return `会话 · ${ownerId}`;
  if (ownerKind === 'room') return `协作空间 · ${ownerId}`;
  return `${ownerKind} · ${ownerId}`;
}

function formatUpdatedAt(value: number): string {
  if (!value) return '暂无';
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(value);
}
